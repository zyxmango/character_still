# -*- coding: utf-8 -*-
"""
工具函数库：从原 agent.py 抽出 8 个工具实现，砍掉 LLM 调用循环 + 上下文压缩 + 流式分发。

每个工具都是普通函数 / 生成器：
- CPU 工具（export_selected / list_resources / evaluate_image）立即返回结果
- GPU 工具（generate_prompt / generate_stills / edit_image / full_pipeline / regenerate_image）
  通过 task_queue 异步执行，进度走 /ws/tasks 推送

Yields 事件字典供上层（如工具执行分发器）使用：
  {"type": "progress", "message": "..."}
  {"type": "_result", "result": {...}}    # 末端，附结果

跨工具的轻量 state（最近 prompts 文件 / 最近剧照列表）通过 state 参数显式传入，
不再依赖 Agent 实例。
"""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import requests

import config
from comfyui_client import ComfyUIClient, ComfyUIError
from logger import get_logger
from main_end import OllamaQwenEngine
from style_manager import inject_custom_styles, get_style_key_by_name

logger = get_logger(__name__)

# ==================== 模块级单例（跨调用复用）====================
_engine: OllamaQwenEngine | None = None
_comfy: ComfyUIClient | None = None


def get_engine() -> OllamaQwenEngine:
    """获取（或初始化）Ollama 提示词生成引擎单例"""
    global _engine
    if _engine is None:
        _engine = OllamaQwenEngine(
            base_url=config.OLLAMA_URL,
            model=config.OLLAMA_MODEL,
            output_dir=str(config.PROMPTS_DIR),
        )
        try:
            inject_custom_styles(_engine)
        except Exception as e:
            logger.warning(f"注入自定义风格失败（不影响内置风格）: {e}")
    return _engine


def get_comfy() -> ComfyUIClient:
    """获取 ComfyUI 客户端单例"""
    global _comfy
    if _comfy is None:
        _comfy = ComfyUIClient()
    return _comfy


# ==================== 工具注册表 ====================
# key：工具名（与原 Agent 8 工具保持一致，便于上层路由）
# value：(function, kind)  kind="cpu"|"gpu"
TOOL_REGISTRY: dict[str, tuple] = {}


def register_tool(name: str, kind: str):
    """工具注册装饰器：kind="cpu" 表示同步返回，"gpu" 表示异步排队"""
    def deco(fn):
        TOOL_REGISTRY[name] = (fn, kind)
        return fn
    return deco


def run_tool(name: str, args: dict, state: dict | None = None, user_id: str = "default"):
    """统一入口：CPU 工具直接返回结果 dict；GPU 工具走任务队列，返回 {"task_id", "queued": True}

    - state: 跨工具共享的轻量状态（最近 prompts / 最近剧照），由调用方持有
    """
    if name not in TOOL_REGISTRY:
        return {"error": f"未知工具：{name}"}
    fn, kind = TOOL_REGISTRY[name]
    if kind == "cpu":
        # CPU 工具：生成器实现，立即消费完，返回结果
        # 约定：工具 yield {"type": "_result", "result": {...}} 作为终止信号
        result = None
        for ev in fn(args, state=state, user_id=user_id):
            if ev.get("type") == "_result":
                result = ev.get("result", {})
                break
        return result or {"error": "工具未返回结果"}
    # GPU 工具：提交到任务队列异步执行
    from task_queue import task_queue
    task_id = task_queue.submit(name, args or {}, user_id=user_id, func=fn)
    logger.info(f"提交任务: task_id={task_id} tool={name} user={user_id}")
    return {"task_id": task_id, "queued": True}


def run_tool_blocking(name: str, args: dict, state: dict | None = None, user_id: str = "default",
                      timeout: float = 60 * 60 * 6):
    """同步等待：仅 CPU 工具可用；GPU 工具会快速返回（先 queue 后改用 task_queue 的 watch）。"""
    if name not in TOOL_REGISTRY:
        return {"error": f"未知工具：{name}"}, []
    fn, kind = TOOL_REGISTRY[name]
    if kind == "cpu":
        progress = []
        for ev in fn(args, state=state, user_id=user_id):
            if ev.get("type") == "_result":
                return ev.get("result", {}), progress
            progress.append(ev)
        return {"error": "工具未返回结果"}, progress
    # GPU 工具：提交并阻塞订阅事件直至完成
    from task_queue import task_queue, event_broker
    task_id = task_queue.submit(name, args or {}, user_id=user_id, func=fn)
    progress = [{"type": "progress", "message": f"📋 任务已提交（{name}），排队执行中..."}]
    sync_q = event_broker.subscribe_sync()
    try:
        import time as _time
        import threading
        # 用一个总超时兜底，避免永久阻塞
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            try:
                event = sync_q.get(timeout=1.0)
            except Exception:
                # 超时：检查任务是否已结束（兜底，防止漏事件）
                task = task_queue.get(task_id)
                if task and task["status"] in ("success", "failed", "cancelled"):
                    if task["status"] == "success":
                        return task.get("result") or {}, progress
                    return {"error": task.get("error", "任务异常结束")}, progress
                continue
            if event.get("task_id") != task_id:
                continue
            etype = event.get("type")
            if etype == "task_progress":
                pi = event.get("progress_item") or {}
                msg = pi.get("message", "")
                if msg:
                    progress.append({"type": "progress", "message": msg})
            elif etype == "task_success":
                return event.get("result") or {}, progress
            elif etype == "task_failed":
                return {"error": event.get("error", "任务执行失败")}, progress
            elif etype == "task_cancelled":
                return {"error": "任务已取消"}, progress
        return {"error": "任务执行超时"}, progress
    finally:
        event_broker.unsubscribe_sync(sync_q)


# ==================== 路径规范化 ====================
def _normalize_image_path(p: str) -> str:
    """路径规范化：支持 web 路径(/files/stills/xx.png) 或文件系统路径，统一转为绝对路径。"""
    if not p:
        return p
    if "?" in p:
        p = p.split("?", 1)[0]
    if p.startswith("/files/"):
        rel = p[len("/files/"):]
        return str(config.OUTPUT_DIR / rel.replace("/", os.sep))
    return p


# ====================================================================
# 工具 1：生成提示词
# ====================================================================
@register_tool("generate_prompt", "gpu")
def tool_generate_prompt(args: dict, state: dict | None = None, user_id: str = "default"):
    style = args.get("style", "端庄大气传统型")
    counts = args.get("counts", {}) or {}
    specials = args.get("specials", {}) or {}
    gender = args.get("gender")
    age = args.get("age")
    color = args.get("color")
    body_type = args.get("body_type")
    counts = {k: max(1, int(v)) for k, v in counts.items()
              if k in config.all_statuses() and int(v) > 0}
    specials = {k: max(1, int(v)) for k, v in specials.items()
                if k in config.all_specials() and int(v) > 0}
    if not counts and not specials:
        yield {"type": "_result", "result": {"error": "未指定有效的身份数量或特殊特征数量"}}
        return

    style_key = get_style_key_by_name(style) or "1"
    total_count = sum(counts.values()) + sum(specials.values())
    attrs = []
    if gender: attrs.append(f"性别={gender}")
    if age: attrs.append(f"年龄={age}")
    if color: attrs.append(f"主色={color}")
    if body_type: attrs.append(f"体型={body_type}")
    attrs_str = f"，属性：{', '.join(attrs)}" if attrs else "（属性随机）"
    yield {"type": "progress", "message": f"开始生成提示词【{style}】，共 {total_count} 个角色{attrs_str}..."}

    engine = get_engine()
    results = engine.quick_generate(
        style_key, counts, specials,
        gender=gender, age=age, color=color, body_type=body_type)
    prompts_file = engine.last_save_path
    if state is not None:
        state["last_prompts_file"] = prompts_file

    # 面向用户的结果：每条给中文描述，路径只作内部字段（前端不展示）
    items = [{
        "name": r.get("名字", ""),
        "gender": r.get("性别", ""),
        "age": r.get("年龄", ""),
        "rank": r.get("地位", r.get("角色类型", "")),
        "special": r.get("特殊", ""),
        "color": r.get("服装颜色", ""),
        "body_type": r.get("体型", ""),
        "zh": r.get("完整中文描述词", "") or "",
        "en": r.get("完整英文描述词", "") or "",
    } for r in results]

    yield {"type": "_result", "result": {
        "prompts_file": prompts_file,   # 内部用：后续出图任务需要它
        "count": len(results),
        "style": style,
        "items": items,
    }}


# ====================================================================
# 工具 2：生成剧照
# ====================================================================
@register_tool("generate_stills", "gpu")
def tool_generate_stills(args: dict, state: dict | None = None, user_id: str = "default"):
    prompts_file = args.get("prompts_file") or (state or {}).get("last_prompts_file")
    if not prompts_file:
        d = config.PROMPTS_DIR
        if d.exists():
            files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if files:
                prompts_file = str(files[0])
    if not prompts_file:
        yield {"type": "_result", "result": {"error": "没有可用的提示词文件，请先生成提示词"}}
        return
    if not Path(prompts_file).exists():
        yield {"type": "_result", "result": {"error": f"提示词文件不存在：{prompts_file}"}}
        return

    with open(prompts_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    sheet = data.get("Sheet1", [])

    id_to_prompt = {}
    id_to_name = {}
    for item in sheet:
        seq = str(item.get("名字", item.get("序号", ""))).strip()
        p = (item.get("完整英文描述词", "") or "").strip()
        if seq and p:
            id_to_prompt[seq] = p
            id_to_name[seq] = item.get("名字", seq)

    ids = args.get("ids")
    if ids:
        ids = [str(i).strip() for i in ids]
        id_to_prompt = {k: v for k, v in id_to_prompt.items() if k in ids}

    if not id_to_prompt:
        yield {"type": "_result", "result": {"error": "未找到匹配的序号"}}
        return

    total = len(id_to_prompt)
    force = bool(args.get("force", False))

    # 任务 ID 归档；启用断点续传时自动复用已有目录
    task_id = args.get("task_id")
    if not task_id and not force:
        first_uuid = id_to_name.get(next(iter(id_to_prompt.keys())), "")
        if first_uuid and config.STILLS_DIR.exists():
            for d in config.STILLS_DIR.iterdir():
                if d.is_dir() and (d / f"{first_uuid}.png").exists():
                    task_id = d.name
                    yield {"type": "progress", "message": f"📌 检测到已有任务目录 {task_id}，启用断点续传..."}
                    break
    if not task_id:
        task_id = uuid.uuid4().hex[:8]

    yield {"type": "progress", "message": f"准备生成 {total} 张剧照{'（强制重出）' if force else '（断点续传：跳过已存在）'}..."}

    task_dir = config.STILLS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    comfy = get_comfy()
    images = []
    skipped = 0
    failed = []
    for i, (seq, prompt) in enumerate(id_to_prompt.items(), 1):
        file_uuid = id_to_name.get(seq, seq)
        out = task_dir / f"{file_uuid}.png"
        if not force and out.exists() and out.stat().st_size > 0:
            skipped += 1
            images.append(str(out))
            yield {"type": "progress", "message": f"[{i}/{total}] 角色 {seq[:16]}... 已存在，跳过（{skipped} 张续传）"}
            continue
        yield {"type": "progress", "message": f"[{i}/{total}] 角色 {seq[:16]}... 生成中..."}
        try:
            path = comfy.text_to_image(
                prompt, str(out),
                width=config.T2I_WIDTH, height=config.T2I_HEIGHT,
                on_log=lambda m: None)
            images.append(path)
        except ComfyUIError as e:
            yield {"type": "progress", "message": f"角色 {seq[:16]}... 失败：{e}"}
            failed.append({"seq": seq, "error": str(e)})

    if state is not None:
        state["last_images"] = images
    # 面向用户的结果：给文件名 + 可访问 URL，前端可直接渲染缩略图
    items = []
    for p in images:
        try:
            rel = Path(p).resolve().relative_to(config.OUTPUT_DIR.resolve())
            url = "/files/" + str(rel).replace("\\", "/")
        except (ValueError, TypeError):
            url = ""
        items.append({"name": Path(p).stem, "url": url})
    yield {"type": "_result", "result": {
        "images": images,          # 内部用（绝对路径），前端不展示
        "items": items,            # 界面用：{name, url}
        "count": len(images),
        "total": total,
        "task_id": task_id,
        "skipped": skipped,
        "failed": failed,
        "failed_count": len(failed),
    }}


# ====================================================================
# 工具 3：修图
# ====================================================================
@register_tool("edit_image", "gpu")
def tool_edit_image(args: dict, state: dict | None = None, user_id: str = "default"):
    image_paths = args.get("image_paths")
    if not image_paths:
        single = args.get("image_path")
        if single:
            image_paths = [single]
        else:
            imgs = (state or {}).get("last_images") or []
            if imgs:
                image_paths = [imgs[-1]]
            else:
                d = config.STILLS_DIR
                if d.exists():
                    files = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
                    if files:
                        image_paths = [str(files[0])]
    if not image_paths:
        yield {"type": "_result", "result": {"error": "没有可修的图片，请先生成剧照或提供图片路径"}}
        return

    instructions_map = args.get("instructions") or {}
    normalized_paths = []
    normalized_instructions = {}
    for p in image_paths:
        np = _normalize_image_path(p)
        normalized_paths.append(np)
        if p in instructions_map:
            normalized_instructions[np] = instructions_map[p]
    image_paths = normalized_paths
    instructions_map = normalized_instructions

    unified_instruction = args.get("instruction", "")
    if not instructions_map and not unified_instruction:
        yield {"type": "_result", "result": {"error": "请提供修图指令"}}
        return

    overwrite = bool(args.get("overwrite", False))
    task_id = args.get("task_id") or uuid.uuid4().hex[:12]
    task_dir = config.EDITED_DIR / task_id
    if not overwrite:
        task_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"修图任务开始: task_id={task_id} overwrite={overwrite} "
                f"total={len(image_paths)} task_dir={task_dir if not overwrite else '(覆盖模式,不创建)'}")

    comfy = get_comfy()
    results = []
    total = len(image_paths)
    success_count = 0
    for idx, img_path in enumerate(image_paths, 1):
        instr = instructions_map.get(img_path) or unified_instruction
        if not instr:
            yield {"type": "progress", "message": f"({idx}/{total}) 跳过（无指令）：{Path(img_path).name}"}
            continue
        if overwrite:
            out_path = img_path
            yield {"type": "progress", "message": f"({idx}/{total}) 修图中（覆盖原图）：{Path(img_path).name} - {instr}"}
        else:
            out_path = str(task_dir / Path(img_path).name)
            yield {"type": "progress", "message": f"({idx}/{total}) 修图中：{Path(img_path).name} - {instr}"}
        logger.info(f"修图({idx}/{total}): 源={img_path} -> 目标={out_path} overwrite={overwrite}")
        try:
            def _on_log(m, _idx=idx, _total=total):
                logger.info(f"修图({_idx}/{_total}) ComfyUI: {m}")
            path = comfy.edit_image(img_path, instr, out_path, on_log=_on_log)
            if Path(path).exists():
                size_kb = Path(path).stat().st_size / 1024
                logger.info(f"修图成功: {path} ({size_kb:.1f} KB) overwrite={overwrite}")
                yield {"type": "progress", "message": f"({idx}/{total}) 完成：{Path(img_path).name} -> {Path(path).name} ({size_kb:.0f} KB)"}
            else:
                logger.warning(f"修图返回但文件不存在: {path}")
                yield {"type": "progress", "message": f"({idx}/{total}) 警告：返回路径但文件不存在 {path}"}
            results.append({
                "source": img_path,
                "edited_image": path,
                "instruction": instr,
                "overwrite": overwrite,
            })
            success_count += 1
        except Exception as e:
            logger.exception(f"修图失败: {img_path} -> {e}")
            yield {"type": "progress", "message": f"({idx}/{total}) 失败：{Path(img_path).name} - {e}"}
            results.append({"source": img_path, "error": str(e), "instruction": instr})

    if state is not None:
        state["last_edited"] = results[-1]["edited_image"] if results and "edited_image" in results[-1] else None

    # 面向用户的结果：{name, url} 列表
    items = []
    for r in results:
        p = r.get("edited_image") or r.get("source")
        try:
            rel = Path(p).resolve().relative_to(config.OUTPUT_DIR.resolve())
            url = "/files/" + str(rel).replace("\\", "/")
        except (ValueError, TypeError):
            url = ""
        items.append({"name": Path(p).stem, "url": url, "error": r.get("error")})

    yield {"type": "_result", "result": {
        "task_id": task_id,
        "task_dir": str(task_dir),
        "total": total,
        "success": success_count,
        "failed": total - success_count,
        "overwrite": overwrite,
        "items": items,      # 界面用
        "results": results,  # 内部用（含绝对路径）
    }}


# ====================================================================
# 工具 4：全流程
# ====================================================================
@register_tool("full_pipeline", "gpu")
def tool_full_pipeline(args: dict, state: dict | None = None, user_id: str = "default"):
    style = args.get("style", "端庄大气传统型")
    counts = args.get("counts", {}) or {}
    specials = args.get("specials", {}) or {}
    edit_instruction = args.get("edit_instruction", "")
    gender = args.get("gender")
    age = args.get("age")
    color = args.get("color")
    body_type = args.get("body_type")
    counts = {k: max(1, int(v)) for k, v in counts.items()
              if k in config.all_statuses() and int(v) > 0}
    specials = {k: max(1, int(v)) for k, v in specials.items()
                if k in config.all_specials() and int(v) > 0}
    if not counts and not specials:
        yield {"type": "_result", "result": {"error": "未指定有效的身份数量或特殊特征数量"}}
        return

    # 1. 生成提示词
    attrs = []
    if gender: attrs.append(f"性别={gender}")
    if age: attrs.append(f"年龄={age}")
    if color: attrs.append(f"主色={color}")
    if body_type: attrs.append(f"体型={body_type}")
    attrs_str = f"，属性：{', '.join(attrs)}" if attrs else "（属性随机）"
    yield {"type": "progress", "message": f"【1/3】生成提示词{attrs_str}..."}
    style_key = get_style_key_by_name(style) or "1"
    engine = get_engine()
    results = engine.quick_generate(
        style_key, counts, specials,
        gender=gender, age=age, color=color, body_type=body_type)
    prompts_file = engine.last_save_path
    if state is not None:
        state["last_prompts_file"] = prompts_file

    # 2. 生成剧照
    yield {"type": "progress", "message": "【2/3】生成剧照..."}
    sheet = []
    with open(prompts_file, "r", encoding="utf-8") as f:
        sheet = json.load(f).get("Sheet1", [])
    id_to_prompt = {}
    id_to_name = {}
    for it in sheet:
        seq = str(it.get("名字", it.get("序号", ""))).strip()
        p = (it.get("完整英文描述词", "") or "")
        if seq and p:
            id_to_prompt[seq] = p
            id_to_name[seq] = it.get("名字", seq)

    images = []
    task_id = args.get("task_id") or uuid.uuid4().hex[:8]
    stills_task_dir = config.STILLS_DIR / task_id
    stills_task_dir.mkdir(parents=True, exist_ok=True)
    comfy = get_comfy()
    for i, (seq, prompt) in enumerate(id_to_prompt.items(), 1):
        yield {"type": "progress", "message": f"  [{i}/{len(id_to_prompt)}] 角色 {seq[:16]}... 出图中..."}
        file_uuid = id_to_name.get(seq, seq)
        out = stills_task_dir / f"{file_uuid}.png"
        try:
            images.append(comfy.text_to_image(
                prompt, str(out), width=config.T2I_WIDTH, height=config.T2I_HEIGHT))
        except ComfyUIError as e:
            yield {"type": "progress", "message": f"  角色 {seq[:16]}... 失败：{e}"}
    if state is not None:
        state["last_images"] = images

    # 3. 修图（可选）
    edited = []
    if edit_instruction and images:
        yield {"type": "progress", "message": "【3/3】修图..."}
        edited_task_dir = config.EDITED_DIR / task_id
        edited_task_dir.mkdir(parents=True, exist_ok=True)
        for i, img in enumerate(images, 1):
            stem = Path(img).stem
            out = edited_task_dir / f"{stem}_edited.png"
            yield {"type": "progress", "message": f"  [{i}/{len(images)}] 修图：{img}"}
            try:
                edited.append(comfy.edit_image(img, edit_instruction, str(out)))
            except ComfyUIError as e:
                yield {"type": "progress", "message": f"  修图失败：{e}"}
        if edited and state is not None:
            state["last_edited"] = edited[-1]

    # 面向用户的结果：中文角色列表 + 图片 URL，避免前端展示原始路径 JSON
    def _to_items(paths):
        out = []
        for p in paths:
            try:
                rel = Path(p).resolve().relative_to(config.OUTPUT_DIR.resolve())
                url = "/files/" + str(rel).replace("\\", "/")
            except (ValueError, TypeError):
                url = ""
            out.append({"name": Path(p).stem, "url": url})
        return out

    char_items = [{
        "name": r.get("名字", ""),
        "rank": r.get("地位", r.get("角色类型", "")),
        "special": r.get("特殊", ""),
        "color": r.get("服装颜色", ""),
        "zh": r.get("完整中文描述词", "") or "",
    } for r in results]

    yield {"type": "_result", "result": {
        "prompts_file": prompts_file,        # 内部用
        "style": style,
        "characters": char_items,            # 界面用：角色中文列表
        "characters_count": len(char_items),
        "stills": images,                    # 内部用（绝对路径）
        "stills_items": _to_items(images),   # 界面用：{name, url}
        "stills_count": len(images),
        "edited": edited,                    # 内部用
        "edited_items": _to_items(edited),   # 界面用
        "edited_count": len(edited),
        "edit_instruction": edit_instruction or None,
    }}


# ====================================================================
# 工具 5：导出打标 Excel + 入库 SQL
# ====================================================================
@register_tool("export_selected", "cpu")
def tool_export_selected(args: dict, state: dict | None = None, user_id: str = "default"):
    image_filenames = args.get("image_filenames") or []
    if not image_filenames:
        last_images = (state or {}).get("last_images", []) or []
        image_filenames = [Path(p).name for p in last_images]
    if not image_filenames:
        yield {"type": "_result", "result": {"error": "没有可导出的图片，请先生成剧照或指定图片文件名列表"}}
        return

    yield {"type": "progress", "message": f"📦 准备导出 {len(image_filenames)} 张图片对应的角色信息..."}

    def _normalize_name(fn):
        stem = Path(fn).stem
        if stem.endswith("_edited"):
            stem = stem[:-len("_edited")]
        return stem

    target_names = {_normalize_name(fn) for fn in image_filenames}
    yield {"type": "progress", "message": f"  匹配角色名：{', '.join(list(target_names)[:5])}{'...' if len(target_names) > 5 else ''}"}

    prompts_dir = config.PROMPTS_DIR
    matched_chars = []
    matched_file = None
    not_found = set(target_names)
    for json_path in sorted(prompts_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            sheet = data.get("Sheet1", [])
            style_name = data.get("style_name", "默认风格")
        except Exception:
            continue
        for ch in sheet:
            name = str(ch.get("名字", "")).strip()
            if name in target_names:
                matched_chars.append(ch)
                not_found.discard(name)
                if matched_file is None:
                    matched_file = json_path
        if not not_found:
            break

    if not matched_chars:
        yield {"type": "_result", "result": {
            "error": f"未在任何 prompts 文件中找到匹配的角色。目标名字：{list(target_names)[:10]}"
        }}
        return

    yield {"type": "progress", "message": f"  匹配到 {len(matched_chars)} 个角色（来源：{Path(matched_file).name}）"}

    try:
        from export_to_db import export_excel, export_sql
    except ImportError:
        yield {"type": "_result", "result": {"error": "导出模块 export_to_db.py 未安装（缺 pandas/openpyxl）"}}
        return

    outdir = config.OUTPUT_DIR / "export"
    outdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        with open(matched_file, "r", encoding="utf-8") as f:
            style_name = json.load(f).get("style_name", "默认风格")
    except Exception:
        style_name = "默认风格"
    safe_style = str(style_name).replace(" ", "_").replace("/", "_")

    try:
        excel_path = export_excel(matched_chars, outdir, f"{safe_style}_selected_{ts}")
        yield {"type": "progress", "message": f"  ✅ Excel 已生成：{Path(excel_path).name}"}
        sql_path = export_sql(matched_chars, outdir, f"{safe_style}_selected_{ts}")
        yield {"type": "progress", "message": f"  ✅ SQL 已生成：{Path(sql_path).name}"}
    except Exception as e:
        yield {"type": "_result", "result": {"error": f"导出失败：{e}"}}
        return

    def _to_web(p):
        try:
            return "/files/" + str(Path(p).resolve().relative_to(config.OUTPUT_DIR.resolve())).replace("\\", "/")
        except Exception:
            return str(p)

    yield {"type": "_result", "result": {
        "count": len(matched_chars),
        "excel_path": _to_web(excel_path),
        "sql_path": _to_web(sql_path),
        "excel_filename": Path(excel_path).name,
        "sql_filename": Path(sql_path).name,
        "source_prompts_file": Path(matched_file).name,
        "not_found": list(not_found),
    }}


# ====================================================================
# 工具 6：列出资源
# ====================================================================
@register_tool("list_resources", "cpu")
def tool_list_resources(args: dict, state: dict | None = None, user_id: str = "default"):
    resource_type = args.get("resource_type", "all")
    limit = min(int(args.get("limit", 10)), 50)

    def _to_web(p):
        try:
            return "/files/" + str(Path(p).resolve().relative_to(config.OUTPUT_DIR.resolve())).replace("\\", "/")
        except Exception:
            return str(p)

    def _list_prompts():
        files = sorted(config.PROMPTS_DIR.glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        items = []
        for f in files:
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                count = len(data.get("Sheet1", []))
                style = data.get("style_name", "未知")
            except Exception:
                count, style = 0, "未知"
            items.append({
                "filename": f.name,
                "style": style,
                "character_count": count,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
        return items

    def _list_stills():
        if not config.STILLS_DIR.exists():
            return [], 0
        dirs = sorted([d for d in config.STILLS_DIR.iterdir() if d.is_dir()],
                      key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        items = []
        total_images = 0
        for d in dirs:
            pngs = list(d.glob("*.png"))
            total_images += len(pngs)
            items.append({
                "task_id": d.name,
                "image_count": len(pngs),
                "image_filenames": [p.name for p in pngs[:5]],
                "mtime": datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "preview_top5": [_to_web(p) for p in pngs[:5]],
            })
        return items, total_images

    def _list_edited():
        if not config.EDITED_DIR.exists():
            return [], 0
        dirs = sorted([d for d in config.EDITED_DIR.iterdir() if d.is_dir()],
                      key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        items = []
        total_images = 0
        for d in dirs:
            pngs = list(d.glob("*.png"))
            total_images += len(pngs)
            items.append({
                "task_id": d.name,
                "image_count": len(pngs),
                "image_filenames": [p.name for p in pngs[:5]],
                "mtime": datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "preview_top5": [_to_web(p) for p in pngs[:5]],
            })
        return items, total_images

    if resource_type == "prompts":
        items = _list_prompts()
        yield {"type": "_result", "result": {"resource_type": "prompts", "count": len(items), "items": items}}
    elif resource_type == "stills":
        items, total = _list_stills()
        yield {"type": "_result", "result": {
            "resource_type": "stills", "count": len(items), "total_images": total, "items": items
        }}
    elif resource_type == "edited":
        items, total = _list_edited()
        yield {"type": "_result", "result": {
            "resource_type": "edited", "count": len(items), "total_images": total, "items": items
        }}
    else:
        prompts = _list_prompts()
        stills, stills_total = _list_stills()
        edited, edited_total = _list_edited()
        yield {"type": "_result", "result": {
            "prompts_count": len(prompts),
            "stills_folders": len(stills),
            "stills_images_total": stills_total,
            "edited_folders": len(edited),
            "edited_images_total": edited_total,
            "prompts_recent": prompts[:5],
            "stills_recent": stills[:5],
            "edited_recent": edited[:5],
        }}


# ====================================================================
# 工具 7：单图重出
# ====================================================================
@register_tool("regenerate_image", "gpu")
def tool_regenerate_image(args: dict, state: dict | None = None, user_id: str = "default"):
    image_filename = args.get("image_filename", "").strip()
    if not image_filename:
        yield {"type": "_result", "result": {"error": "缺少 image_filename 参数"}}
        return

    if "?" in image_filename:
        image_filename = image_filename.split("?", 1)[0]
    image_filename = Path(image_filename).name

    stem = Path(image_filename).stem
    if stem.endswith("_edited"):
        stem = stem[:-len("_edited")]

    yield {"type": "progress", "message": f"🔍 查找角色 {stem} 的提示词..."}

    matched_prompt = None
    matched_file = None
    for json_path in sorted(config.PROMPTS_DIR.glob("*.json"),
                            key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            sheet = data.get("Sheet1", [])
        except Exception:
            continue
        for ch in sheet:
            name = str(ch.get("名字", "")).strip()
            if name == stem:
                matched_prompt = ch.get("完整英文描述词", "") or ""
                matched_file = json_path
                break
        if matched_prompt:
            break

    if not matched_prompt:
        yield {"type": "_result", "result": {
            "error": f"未找到角色 {stem} 的提示词。请确认文件名是否正确。"
        }}
        return

    yield {"type": "progress", "message": f"  找到提示词（来源：{Path(matched_file).name}），开始重新出图..."}

    original_path = None
    if config.STILLS_DIR.exists():
        for d in config.STILLS_DIR.iterdir():
            if d.is_dir():
                candidate = d / image_filename
                if candidate.exists():
                    original_path = candidate
                    break

    if not original_path:
        task_id = uuid.uuid4().hex[:8]
        stills_dir = config.STILLS_DIR / task_id
        stills_dir.mkdir(parents=True, exist_ok=True)
        original_path = stills_dir / image_filename

    yield {"type": "progress", "message": f"  🎨 正在重新生成 {stem}..."}

    comfy = get_comfy()
    try:
        new_image = comfy.text_to_image(
            matched_prompt, str(original_path),
            width=config.T2I_WIDTH, height=config.T2I_HEIGHT)
        yield {"type": "progress", "message": f"  ✅ 重新生成成功：{Path(new_image).name}"}
        try:
            web_path = "/files/" + str(Path(new_image).resolve().relative_to(config.OUTPUT_DIR.resolve())).replace("\\", "/")
        except Exception:
            web_path = str(new_image)
        yield {"type": "_result", "result": {
            "image_path": web_path,
            "image_filename": Path(new_image).name,
            "character_name": stem,
            "overwritten": True,
        }}
    except Exception as e:
        yield {"type": "_result", "result": {"error": f"重新生成失败：{e}"}}


# ====================================================================
# 工具 8：出图质量自评
# ====================================================================
@register_tool("evaluate_image", "cpu")
def tool_evaluate_image(args: dict, state: dict | None = None, user_id: str = "default"):
    import base64

    image_filenames = args.get("image_filenames") or []
    threshold = int(args.get("threshold", config.EVALUATE_THRESHOLD))

    normalized = []
    for fn in image_filenames:
        if "?" in fn:
            fn = fn.split("?", 1)[0]
        normalized.append(Path(fn).name)
    image_filenames = normalized

    if not image_filenames:
        last_images = (state or {}).get("last_images") or []
        if not last_images:
            if config.STILLS_DIR.exists():
                dirs = sorted([d for d in config.STILLS_DIR.iterdir() if d.is_dir()],
                              key=lambda p: p.stat().st_mtime, reverse=True)
                if dirs:
                    last_images = [str(p) for p in dirs[0].glob("*.png")]
        image_filenames = [Path(p).name for p in last_images]

    if not image_filenames:
        yield {"type": "_result", "result": {"error": "没有可评估的图片，请先生成剧照或指定 image_filenames"}}
        return

    image_filenames = image_filenames[:config.EVALUATE_BATCH_LIMIT]

    def _resolve_image(filename):
        if config.STILLS_DIR.exists():
            for d in config.STILLS_DIR.iterdir():
                if d.is_dir():
                    candidate = d / filename
                    if candidate.exists():
                        return candidate
            top = config.STILLS_DIR / filename
            if top.exists():
                return top
        if config.EDITED_DIR.exists():
            for d in config.EDITED_DIR.iterdir():
                if d.is_dir():
                    candidate = d / filename
                    if candidate.exists():
                        return candidate
        return None

    if not config.DASHSCOPE_API_KEY:
        yield {"type": "_result", "result": {"error": "未配置 DASHSCOPE_API_KEY，无法调用视觉模型"}}
        return

    yield {"type": "progress", "message": f"🔍 开始评估 {len(image_filenames)} 张图片（视觉模型 {config.DASHSCOPE_VL_MODEL}）..."}

    evaluations = []
    for idx, fn in enumerate(image_filenames, 1):
        img_path = _resolve_image(fn)
        if not img_path:
            evaluations.append({
                "filename": fn, "score": 0, "needs_regen": True,
                "suggestion": "图片文件未找到", "dimensions": {},
            })
            yield {"type": "progress", "message": f"  [{idx}/{len(image_filenames)}] {fn} ❌ 文件未找到"}
            continue

        yield {"type": "progress", "message": f"  [{idx}/{len(image_filenames)}] 评估 {fn}..."}

        try:
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            ext = img_path.suffix.lstrip(".").lower()
            mime = "image/png" if ext == "png" else f"image/{ext}"
            data_url = f"data:{mime};base64,{b64}"

            vl_payload = {
                "model": config.DASHSCOPE_VL_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_url}},
                            {
                                "type": "text",
                                "text": (
                                    "你是古装人物剧照质量评审专家。请对这张古装人物剧照进行严格质量评分。"
                                    "从以下5个维度打分（每项0-20分，总分100）：\n"
                                    "1. 人物完整性：是否全身、比例是否协调、是否有残缺\n"
                                    "2. 服饰准确性：是否符合古代服饰特征、是否有现代元素（运动鞋/高跟鞋等）\n"
                                    "3. 颜色匹配度：服装主色是否清晰、是否有杂色干扰\n"
                                    "4. 画面构图：是否正面全身、背景是否纯净、光影是否合理\n"
                                    "5. 风格一致性：是否符合古装剧照整体审美\n\n"
                                    "严格输出纯 JSON（不要 markdown 代码块），格式：\n"
                                    '{"score": 总分, "dimensions": {"人物完整性": 分, "服饰准确性": 分, '
                                    '"颜色匹配度": 分, "画面构图": 分, "风格一致性": 分}, '
                                    '"issues": ["问题1", "问题2"], "suggestion": "改进建议（一句话）"}'
                                ),
                            },
                        ],
                    }
                ],
            }
            resp = requests.post(
                config.DASHSCOPE_API_URL,
                json=vl_payload,
                headers={
                    "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=60,
            )
            resp.raise_for_status()
            resp_json = resp.json()
            content = resp_json.get("choices", [{}])[0].get("message", {}).get("content", "")

            content_stripped = content.strip()
            if content_stripped.startswith("```"):
                parts = content_stripped.split("```", 2)
                content = parts[1] if len(parts) > 1 else content
                if content.startswith("json\n"):
                    content = content[5:]
            eval_data = json.loads(content)

            score = int(eval_data.get("score", 0))
            needs_regen = score < threshold
            evaluations.append({
                "filename": fn,
                "score": score,
                "dimensions": eval_data.get("dimensions", {}),
                "issues": eval_data.get("issues", []),
                "suggestion": eval_data.get("suggestion", ""),
                "needs_regen": needs_regen,
            })
            tag = "⚠️ 需重出" if needs_regen else "✅ 合格"
            yield {"type": "progress", "message": f"    → {score} 分 {tag}"}

        except Exception as e:
            evaluations.append({
                "filename": fn, "score": 0, "needs_regen": True,
                "suggestion": f"评估失败：{e}", "dimensions": {},
            })
            yield {"type": "progress", "message": f"    → 评估失败：{e}"}

    valid_scores = [e["score"] for e in evaluations if e["score"] > 0]
    avg = round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else 0
    needs_regen_count = sum(1 for e in evaluations if e.get("needs_regen"))

    yield {"type": "progress", "message": f"📊 评估完成：共 {len(evaluations)} 张，平均 {avg} 分，{needs_regen_count} 张需重出"}

    yield {"type": "_result", "result": {
        "total": len(evaluations),
        "average_score": avg,
        "threshold": threshold,
        "needs_regen_count": needs_regen_count,
        "evaluations": evaluations,
    }}
