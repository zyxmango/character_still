# -*- coding: utf-8 -*-
"""
FastAPI 后端服务（生产级）：
- 异步任务队列（出图/修图不再阻塞）
- 无登录态：v2.2 起移除登录/注册/JWT，匿名访问全部 API；保留 IP 级速率限制
- 结构化日志 + 全局异常
- 健康检查 + 配置环境变量化
- 前端静态文件服务

启动： python server.py
"""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from auth import (rate_limit, rate_limit_require_login, get_current_user)
from session_store import session_store  # 仍在 metrics 中读取 user 统计
from logger import setup_logging, get_logger, get_trace_id, TraceLogger
from task_queue import task_queue, TaskStatus, event_broker
from tools import run_tool_blocking

# 初始化日志（必须最先）
setup_logging()
logger = get_logger(__name__)


# ==================== 生命周期 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("应用启动")
    yield
    logger.info("应用关闭")


# ==================== 工具函数 ====================
def _find_latest_image() -> Optional[str]:
    d = config.STILLS_DIR
    if not d.exists():
        return None
    files = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(files[0]) if files else None


def _find_latest_prompts() -> Optional[str]:
    d = config.PROMPTS_DIR
    if not d.exists():
        return None
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(files[0]) if files else None


def _to_web_path(p: str) -> str:
    try:
        rel = Path(p).resolve().relative_to(config.OUTPUT_DIR.resolve())
        return "/files/" + str(rel).replace("\\", "/")
    except (ValueError, TypeError):
        return p


def _convert_paths(obj: Any) -> Any:
    if isinstance(obj, str):
        return _to_web_path(obj)
    if isinstance(obj, list):
        return [_convert_paths(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _convert_paths(v) for k, v in obj.items()}
    return obj


def _run_tool_direct(tool_name: str, args: dict):
    """同步调用工具（兼容旧 API 行为：阻塞至任务完成）。
    新代码请优先使用 POST /api/tasks + WS /ws/tasks 获取实时进度。
    """
    result, progress = run_tool_blocking(tool_name, args or {}, user_id="default")
    return result, progress


# ==================== 请求模型 ====================
class GeneratePromptReq(BaseModel):
    style: str = "端庄大气传统型"
    counts: Dict[str, int] = {}
    specials: Optional[Dict[str, int]] = None


class GenerateStillsReq(BaseModel):
    prompts_file: Optional[str] = None
    ids: Optional[List[str]] = None


class EditImageReq(BaseModel):
    image_path: Optional[str] = None
    instruction: str


class PipelineReq(BaseModel):
    style: str = "端庄大气传统型"
    counts: Dict[str, int] = {}
    specials: Optional[Dict[str, int]] = None
    edit_instruction: Optional[str] = None


class TaskReq(BaseModel):
    task_type: str  # generate_prompt / generate_stills / edit_image / full_pipeline
    args: dict = {}


# ==================== App ====================
app = FastAPI(title="古装人物剧照批量生成平台", version="2.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

config.ensure_dirs()

# API 静态文件服务（图片等）
app.mount("/files", StaticFiles(directory=str(config.OUTPUT_DIR)), name="files")

# 前端 SPA 挂载到根路径（放在路由定义之后，确保 API 路由优先匹配）
STATIC_DIR = Path(__file__).parent / "static"
if (STATIC_DIR / "assets").exists():
    # 只把 static/assets 目录挂载到 /assets 路径
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")


# ==================== 全局异常处理 ====================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"未捕获异常: {exc}", extra={
        "path": request.url.path, "method": request.method})
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# ==================== 基础路由 ====================
@app.get("/")
async def root():
    """根路径直接返回前端页面（不缓存，保证能拿到最新 hash 引用）"""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        from fastapi.responses import FileResponse
        return FileResponse(
            str(index_file),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return JSONResponse(status_code=200, content={"status": "ok", "service": "character_agent"})


@app.get("/health")
async def health():
    """健康检查（K8s 探针用）"""
    import requests
    checks = {"server": "ok"}
    # 检查 Ollama
    try:
        r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        checks["ollama"] = "ok" if r.status_code == 200 else f"error:{r.status_code}"
    except Exception as e:
        checks["ollama"] = f"down:{e}"
    # 检查 ComfyUI
    try:
        r = requests.get(f"{config.COMFYUI_URL}/system_stats", timeout=3)
        checks["comfyui"] = "ok" if r.status_code == 200 else f"error:{r.status_code}"
    except Exception as e:
        checks["comfyui"] = f"down:{e}"

    status_code = 200 if all(v == "ok" for v in checks.values()) else 503
    return JSONResponse(status_code=status_code, content=checks)


@app.get("/api/options")
async def options():
    # 每次拉取都刷新一次，保证 md 配置改动即时可见
    config.refresh_dynamic()
    # 合并配置中的风格 + 自定义风格
    styles = list(config.STYLE_MAP.keys())
    custom_styles_list = []
    try:
        from style_manager import list_styles
        custom_styles_list = list_styles()
        for s in custom_styles_list:
            name = s.get("style_name")
            if name and name not in styles:
                styles.append(name)
    except Exception:
        pass
    return {
        "styles": styles,
        "custom_styles": custom_styles_list,
        "statuses": config.ALL_STATUSES,
        "specials": config.ALL_SPECIALS,
        "comfyui_url": config.COMFYUI_URL,
        "ollama_url": config.OLLAMA_URL,
        "model": config.OLLAMA_MODEL,
        "max_concurrent_tasks": config.MAX_CONCURRENT_TASKS,
    }


@app.get("/api/list_images")
async def list_images():
    def scan(folder: str):
        d = config.OUTPUT_DIR / folder
        if not d.exists():
            return {"images": [], "folders": []}
        # 顶层散图（旧结构兼容）
        top_images = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        # 子文件夹（按任务ID归档的新结构）
        folders = []
        for sub in sorted(d.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if sub.is_dir():
                files = sorted(sub.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
                if files:
                    folders.append({
                        "folder": sub.name,
                        "count": len(files),
                        "mtime": sub.stat().st_mtime,
                        "images": [
                            {"filename": f.name,
                             "url": f"/files/{folder}/{sub.name}/{f.name}",
                             "size": f.stat().st_size, "mtime": f.stat().st_mtime}
                            for f in files
                        ]
                    })
        return {
            "images": [
                {"filename": f.name, "url": f"/files/{folder}/{f.name}",
                 "size": f.stat().st_size, "mtime": f.stat().st_mtime}
                for f in top_images
            ],
            "folders": folders
        }
    return {"stills": scan("stills"), "edited": scan("edited")}


# ==================== 删除图片 ====================
class DeleteImageReq(BaseModel):
    section: str  # "stills" / "edited"
    folder: Optional[str] = None  # 指定文件夹名（删整个任务文件夹）；留空=删单张
    filename: Optional[str] = None  # 单张图片文件名（folder 留空时必填）


@app.delete("/api/images")
async def delete_image(req: DeleteImageReq, user: dict = Depends(rate_limit_require_login())):
    """删除图片：支持删整文件夹或删单张图片
    - section: "stills" / "edited"
    - folder: 指定时删除整个任务文件夹
    - filename: folder 留空时必填，删除顶层散图中的单张
    - folder + filename 同时指定时，删除该文件夹下的单张图片
    """
    if req.section not in ("stills", "edited"):
        raise HTTPException(status_code=400, detail="section 必须是 stills 或 edited")

    base_dir = config.OUTPUT_DIR / req.section
    if not base_dir.exists():
        raise HTTPException(status_code=404, detail="目录不存在")

    deleted_paths = []

    if req.folder:
        # 删文件夹（整个任务）或文件夹内单张
        folder_path = base_dir / req.folder
        # 防路径穿越
        if not folder_path.resolve().is_relative_to(base_dir.resolve()):
            raise HTTPException(status_code=400, detail="非法路径")
        if not folder_path.exists():
            raise HTTPException(status_code=404, detail="文件夹不存在")

        if req.filename:
            # 删文件夹内单张
            target = folder_path / req.filename
            if not target.resolve().is_relative_to(folder_path.resolve()):
                raise HTTPException(status_code=400, detail="非法路径")
            if not target.exists() or not target.is_file():
                raise HTTPException(status_code=404, detail="文件不存在")
            target.unlink()
            deleted_paths.append(str(target))
            # 若文件夹已空，一并删除
            remaining = list(folder_path.glob("*"))
            if not remaining:
                folder_path.rmdir()
        else:
            # 删整个文件夹
            import shutil
            shutil.rmtree(folder_path)
            deleted_paths.append(str(folder_path))
    else:
        # 删顶层散图单张
        if not req.filename:
            raise HTTPException(status_code=400, detail="必须指定 folder 或 filename")
        target = base_dir / req.filename
        if not target.resolve().is_relative_to(base_dir.resolve()):
            raise HTTPException(status_code=400, detail="非法路径")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        target.unlink()
        deleted_paths.append(str(target))

    logger.info(f"用户 {user.get('user_id')} 删除图片: {deleted_paths}")
    return {"detail": "已删除", "deleted": deleted_paths}


# ==================== 认证路由 ====================
# v2.2：登录/注册/JWT 已移除。所有 API 匿名可访问（关键操作仍走 IP 级速率限制）。
# 保留以下端点仅为向后兼容（旧前端缓存的调用不会 hard error）：
#   POST /api/register  -> 200 {"deprecated": true, "message": "登录注册已下线，v2.2 起免登录使用"}
#   POST /api/login     -> 200 同上
#   GET  /api/me        -> 200 {"user_id": "anonymous", "username": "匿名用户", "role": "admin"}
@app.post("/api/register", deprecated=True)
async def register_deprecated():
    return {"deprecated": True, "message": "登录注册已下线，v2.2 起免登录使用"}

@app.post("/api/login", deprecated=True)
async def login_deprecated():
    return {"deprecated": True, "message": "登录注册已下线，v2.2 起免登录使用"}

@app.get("/api/me")
async def me(user: dict = Depends(get_current_user)):
    return user


# ==================== 异步任务路由 ====================
@app.post("/api/tasks")
async def submit_task(req: TaskReq, user: dict = Depends(rate_limit_require_login())):
    """提交异步任务，立即返回 task_id"""
    valid_types = {"generate_prompt", "generate_stills", "edit_image", "full_pipeline"}
    if req.task_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"无效任务类型: {req.task_type}")
    # 出图类任务使用更严格的限流
    if req.task_type in ("generate_stills", "edit_image", "full_pipeline"):
        if not rate_limiter_check_generate(user["user_id"]):
            raise HTTPException(status_code=429,
                                detail=f"出图任务每小时限 {config.RATE_LIMIT_GENERATE_PER_HOUR} 次")
    task_id = task_queue.submit(req.task_type, req.args, user["user_id"])
    logger.info(f"提交任务: {task_id} type={req.task_type} user={user['user_id']}")
    return {"task_id": task_id, "status": "pending"}


def rate_limiter_check_generate(user_id: str) -> bool:
    """出图任务每小时限流"""
    from auth import rate_limiter
    return rate_limiter.check(f"generate:{user_id}",
                              config.RATE_LIMIT_GENERATE_PER_HOUR, 3600)


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str, user: dict = Depends(get_current_user)):
    task = task_queue.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 权限检查（同用户或管理员）
    if task.get("user_id") != user["user_id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权访问")
    # 转换路径
    if task.get("result"):
        task["result"] = _convert_paths(task["result"])
    if task.get("progress"):
        task["progress"] = _convert_paths(task["progress"])
    return task


@app.get("/api/tasks")
async def list_tasks(user: dict = Depends(get_current_user), limit: int = 50):
    return task_queue.list_tasks(user["user_id"], limit)


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, user: dict = Depends(get_current_user)):
    task = task_queue.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.get("user_id") != user["user_id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权操作")
    ok = task_queue.cancel(task_id)
    return {"cancelled": ok, "status": task_queue.get(task_id)["status"]}


# ==================== 任务进度 WebSocket 推送 ====================
@app.websocket("/ws/tasks")
async def ws_tasks(ws: WebSocket):
    """任务进度实时推送：连接后立即下发当前任务列表快照，之后推送增量事件。
    事件类型：task_submitted / task_running / task_progress / task_success / task_failed / task_cancelled
    v2.2：免登录，无需鉴权。
    """
    user_id = "anonymous"
    await ws.accept()
    tlog = TraceLogger("ws.tasks", get_trace_id())
    tlog.info(f"任务 WS 连接建立: user={user_id}")

    # 订阅事件代理
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    event_broker.subscribe(queue, loop)

    # 下发当前任务列表快照（仅本用户的）
    try:
        snapshot = task_queue.list_tasks(user_id, limit=30)
        await ws.send_json({
            "type": "snapshot",
            "tasks": [_convert_paths(t) for t in snapshot],
        })
    except Exception as e:
        tlog.error(f"下发任务快照失败: {e}")

    try:
        while True:
            # 1) 优先消费事件队列（带超时，避免永久阻塞）
            try:
                event = await asyncio.wait_for(queue.get(), timeout=25.0)
            except asyncio.TimeoutError:
                # 发心跳保活
                await ws.send_json({"type": "ping", "ts": datetime.now().isoformat()})
                continue

            # 仅推送属于当前用户的事件（按 task_id 查 user_id）
            tid = event.get("task_id")
            if tid:
                task = task_queue.get(tid)
                if task and task.get("user_id") != user_id and user.get("role") != "admin":
                    continue  # 跳过他人任务
            # 转换 result/progress_item 中的本地路径为 web 路径
            if "result" in event and event["result"]:
                event["result"] = _convert_paths(event["result"])
            if "progress_item" in event and event["progress_item"]:
                event["progress_item"] = _convert_paths(event["progress_item"])
            await ws.send_json(event)

    except WebSocketDisconnect:
        tlog.info("任务 WS 断开")
    except Exception as e:
        tlog.exception(f"任务 WS 异常: {e}")
    finally:
        event_broker.unsubscribe(queue)
        tlog.info("任务 WS 订阅已注销")


# ==================== Prompts 文件管理（供前端筛选后导出） ====================
def _parse_prompts_json(json_path: Path) -> tuple:
    """解析 prompts JSON，返回 (characters, style_name)"""
    import json as _json
    with open(json_path, "r", encoding="utf-8") as f:
        data = _json.load(f)
    characters = None
    if isinstance(data, list):
        characters = data
    else:
        for key in ("Sheet1", "characters", "data"):
            if isinstance(data, dict) and key in data and isinstance(data[key], list):
                characters = data[key]
                break
    if not characters:
        raise ValueError("无法解析 JSON，没有找到角色数据")

    style_name = "未命名"
    m = json_path.name
    if "generated_prompts_" in m:
        tail = m.replace("generated_prompts_", "")
        parts = tail.rsplit("_", 2)  # 去掉日期_时间
        style_name = parts[0] if len(parts) == 3 else tail.replace(".json", "")
    return characters, style_name


@app.get("/api/prompts/list")
async def list_prompts(user: dict = Depends(get_current_user)):
    """列出所有已生成的 prompts JSON 文件，供前端选择后筛选导出"""
    d = config.PROMPTS_DIR
    result = []
    if d.exists():
        for f in sorted(d.glob("generated_prompts_*.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True):
            count = 0
            style_name = "未命名"
            try:
                chars, style_name = _parse_prompts_json(f)
                count = len(chars)
            except Exception:
                pass
            result.append({
                "filename": f.name,
                "path": str(f),
                "style": style_name,
                "count": count,
                "mtime": f.stat().st_mtime,
            })
    return {"items": result}


@app.get("/api/prompts/characters")
async def get_prompts_characters(file: str, user: dict = Depends(get_current_user)):
    """读取指定 prompts JSON 的角色列表，供前端勾选后导出"""
    json_path = Path(file)
    if not json_path.exists():
        raise HTTPException(status_code=400, detail=f"找不到文件: {file}")
    try:
        characters, style_name = _parse_prompts_json(json_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {e}")

    # 返回精简字段供前端展示与勾选（prompt_cn/prompt_en 为完整提示词，供界面直接展示）
    items = []
    for idx, ch in enumerate(characters):
        prompt_cn = str(ch.get("完整中文描述词", "") or "").strip()
        items.append({
            "idx": idx,
            "名字": str(ch.get("名字", "")).strip(),
            "性别": str(ch.get("性别", "")).strip(),
            "年龄": str(ch.get("年龄", "")).strip(),
            "体型": str(ch.get("体型", "")).strip(),
            "地位": str(ch.get("地位", "")).strip(),
            "服装颜色": str(ch.get("服装颜色", "")).strip(),
            "特殊": str(ch.get("特殊", "")).strip(),
            "朝代": str(ch.get("朝代", "")).strip(),
            "prompt_cn": prompt_cn,
            "prompt_en": str(ch.get("完整英文描述词", "") or "").strip(),
            "中文摘要": prompt_cn[:60],
        })
    return {"file": str(json_path), "style": style_name, "count": len(items), "items": items}


# ==================== 提示词工程配置（md 文档，可在线编辑） ====================
class PromptGuideReq(BaseModel):
    content: str


def _guide_payload():
    """组装提示词工程配置的返回体"""
    import prompt_loader
    data, info = prompt_loader.load_guide()
    info = dict(info)
    info["path"] = str(prompt_loader.GUIDE_PATH)
    return {
        "content": prompt_loader.read_text(),
        "path": str(prompt_loader.GUIDE_PATH),
        "info": info,
        "statuses": prompt_loader.statuses(),
        "specials": prompt_loader.specials(),
        "colors": prompt_loader.colors(),
        "styles": prompt_loader.style_names(),
    }


@app.get("/api/prompt-guide")
async def get_prompt_guide(user: dict = Depends(get_current_user)):
    """读取提示词工程配置文档（md）原文与解析状态"""
    return _guide_payload()


@app.post("/api/prompt-guide/validate")
async def validate_prompt_guide(req: PromptGuideReq, user: dict = Depends(get_current_user)):
    """只校验不落盘：返回 yaml 块数、错误、结构性问题、解析出的身份与风格"""
    import prompt_loader
    return prompt_loader.validate_text(req.content)


@app.put("/api/prompt-guide")
async def save_prompt_guide(req: PromptGuideReq, user: dict = Depends(rate_limit_require_login())):
    """保存提示词工程配置文档。先校验，通过才落盘（旧文件自动备份）"""
    import prompt_loader
    result = prompt_loader.validate_text(req.content)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail={
            "message": "配置校验未通过，未保存",
            "errors": result["errors"],
            "problems": result["problems"],
        })
    backup = prompt_loader.write_text(req.content)
    config.refresh_dynamic()
    payload = _guide_payload()
    payload["backup"] = backup
    return payload


@app.post("/api/prompt-guide/reload")
async def reload_prompt_guide(user: dict = Depends(get_current_user)):
    """强制重新加载配置（手动修改 md 后调用）"""
    import prompt_loader
    prompt_loader.reload_guide()
    config.refresh_dynamic()
    return _guide_payload()


@app.post("/api/prompt-guide/restore")
async def restore_prompt_guide(user: dict = Depends(rate_limit_require_login())):
    """恢复为内置默认配置（当前文件会先备份）"""
    import prompt_loader
    backup = prompt_loader.restore_default()
    config.refresh_dynamic()
    payload = _guide_payload()
    payload["backup"] = backup
    return payload


# ==================== 导出：打标 Excel + 入库 SQL（支持按选中项导出） ====================
class ExportReq(BaseModel):
    file: Optional[str] = None  # 指定 prompts JSON，留空=最新生成的
    selected_names: Optional[List[str]] = None  # 选中的角色名字列表，留空=导出全部


@app.post("/api/export")
async def api_export(req: ExportReq, user: dict = Depends(rate_limit_require_login())):
    """导出打标 Excel + 入库 SQL。
    - file 留空自动取最新 generated_prompts JSON
    - selected_names 传入时仅导出选中的角色；留空则导出全部
    """
    # 1. 找到 JSON 文件
    if req.file:
        json_path = Path(req.file)
        if not json_path.exists():
            raise HTTPException(status_code=400, detail=f"找不到文件: {req.file}")
    else:
        d = config.PROMPTS_DIR
        if not d.exists():
            raise HTTPException(status_code=400, detail="还没有生成过 prompts 文件")
        files = sorted(d.glob("generated_prompts_*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            raise HTTPException(status_code=400, detail=f"目录 {d} 下没有 prompts JSON")
        json_path = files[0]

    # 2. 解析角色列表
    try:
        characters, style_name = _parse_prompts_json(json_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {e}")

    # 3. 按选中名字过滤
    selected_set = None
    if req.selected_names:
        selected_set = {str(n).strip() for n in req.selected_names if str(n).strip()}
    if selected_set is not None:
        characters = [ch for ch in characters
                      if str(ch.get("名字", "")).strip() in selected_set]
        if not characters:
            raise HTTPException(status_code=400, detail="选中的角色在文件中均未匹配到")

    # 4. 导出（复用 export_to_db.py）
    try:
        from export_to_db import export_excel, export_sql
    except ImportError:
        raise HTTPException(status_code=500, detail="缺少 export_to_db 模块或 pandas/openpyxl 依赖")

    outdir = config.OUTPUT_DIR / "export"
    outdir.mkdir(parents=True, exist_ok=True)

    # 选中部分导出时在风格名后追加标记，避免覆盖全量导出文件
    export_style = style_name if selected_set is None else f"{style_name}_selected"

    excel_path = export_excel(characters, outdir, export_style)
    sql_path = export_sql(characters, outdir, export_style)

    return {
        "source_json": str(json_path),
        "count": len(characters),
        "total": len(selected_set) if selected_set is not None else len(characters),
        "style": style_name,
        "excel": str(excel_path),
        "excel_web": _to_web_path(str(excel_path)),
        "sql": str(sql_path),
        "sql_web": _to_web_path(str(sql_path)),
    }


class ExportByImagesReq(BaseModel):
    image_filenames: List[str]  # 图片文件名列表，如 ["abc.png", "def_edited.png"]


@app.post("/api/export/by_images")
async def api_export_by_images(req: ExportByImagesReq, user: dict = Depends(rate_limit_require_login())):
    """根据画廊中选中的图片文件名，在所有 prompts JSON 中匹配角色并导出 Excel + SQL。
    图片文件名去掉扩展名和 _edited 后缀后，与 prompts JSON 中"名字"字段匹配。
    """
    if not req.image_filenames:
        raise HTTPException(status_code=400, detail="请至少选择一张图片")

    # 从文件名提取角色名：去掉扩展名 + 去掉 _edited 后缀
    def _extract_name(filename: str) -> str:
        import os as _os
        base = _os.path.splitext(_os.path.basename(filename))[0]
        if base.endswith("_edited"):
            base = base[:-len("_edited")]
        return base.strip()

    target_names = {_extract_name(f) for f in req.image_filenames if f}
    if not target_names:
        raise HTTPException(status_code=400, detail="无法从文件名中提取角色名")

    # 遍历所有 prompts JSON，收集匹配的角色
    d = config.PROMPTS_DIR
    if not d.exists():
        raise HTTPException(status_code=400, detail="没有 prompts 目录")
    files = sorted(d.glob("generated_prompts_*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise HTTPException(status_code=400, detail="没有 prompts JSON 文件")

    matched_chars = []
    matched_files = []
    found_names = set()
    for f in files:
        try:
            characters, style_name = _parse_prompts_json(f)
        except Exception:
            continue
        for ch in characters:
            name = str(ch.get("名字", "")).strip()
            if name in target_names and name not in found_names:
                matched_chars.append(ch)
                found_names.add(name)
                if f.name not in matched_files:
                    matched_files.append(f.name)
        if found_names == target_names:
            break  # 全部找到，提前结束

    if not matched_chars:
        raise HTTPException(
            status_code=400,
            detail=f"在所有 prompts 文件中均未匹配到选中的图片（{len(target_names)} 个）")

    # 导出
    try:
        from export_to_db import export_excel, export_sql
    except ImportError:
        raise HTTPException(status_code=500, detail="缺少 export_to_db 模块或 pandas/openpyxl 依赖")

    outdir = config.OUTPUT_DIR / "export"
    outdir.mkdir(parents=True, exist_ok=True)
    export_style = "画廊筛选"

    excel_path = export_excel(matched_chars, outdir, export_style)
    sql_path = export_sql(matched_chars, outdir, export_style)

    not_found = target_names - found_names
    return {
        "count": len(matched_chars),
        "total_selected": len(target_names),
        "matched_files": matched_files,
        "not_found": list(not_found),
        "style": export_style,
        "excel": str(excel_path),
        "excel_web": _to_web_path(str(excel_path)),
        "sql": str(sql_path),
        "sql_web": _to_web_path(str(sql_path)),
    }


@app.get("/api/export/list")
async def list_exports(user: dict = Depends(get_current_user)):
    """列出所有已导出的 Excel 和 SQL 文件"""
    d = config.OUTPUT_DIR / "export"
    result = {"excel": [], "sql": []}
    if d.exists():
        for f in sorted(d.glob("*_AI打标_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True):
            result["excel"].append({
                "filename": f.name,
                "path": str(f),
                "url": _to_web_path(str(f)),
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
            })
        for f in sorted(d.glob("insert_*.sql"), key=lambda p: p.stat().st_mtime, reverse=True):
            result["sql"].append({
                "filename": f.name,
                "path": str(f),
                "url": _to_web_path(str(f)),
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
            })
    return result


# ==================== 任务模板（保存常用配置一键复用）====================
class TemplateReq(BaseModel):
    name: str
    task_type: str = "full_pipeline"  # generate_prompt / generate_stills / full_pipeline
    config: dict = {}  # {style, counts, specials, edit_instruction, ...}


def _load_templates() -> list:
    """读取模板列表"""
    if not config.TEMPLATES_FILE.exists():
        return []
    try:
        with open(config.TEMPLATES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_templates(items: list):
    """保存模板列表"""
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.TEMPLATES_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


@app.get("/api/templates")
async def list_templates(user: dict = Depends(get_current_user)):
    """列出所有任务模板"""
    return {"items": _load_templates()}


@app.post("/api/templates")
async def create_template(req: TemplateReq, user: dict = Depends(rate_limit_require_login())):
    """新建任务模板"""
    import uuid as _uuid
    items = _load_templates()
    # 同名模板更新，否则新增
    existing = next((t for t in items if t["name"] == req.name), None)
    if existing:
        existing["task_type"] = req.task_type
        existing["config"] = req.config
        existing["updated_at"] = datetime.now().isoformat()
        msg = f"模板「{req.name}」已更新"
    else:
        items.append({
            "id": _uuid.uuid4().hex[:8],
            "name": req.name,
            "task_type": req.task_type,
            "config": req.config,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        })
        msg = f"模板「{req.name}」已保存"
    _save_templates(items)
    return {"ok": True, "message": msg, "items": items}


@app.delete("/api/templates/{template_id}")
async def delete_template(template_id: str, user: dict = Depends(rate_limit_require_login())):
    """删除任务模板"""
    items = _load_templates()
    before = len(items)
    items = [t for t in items if t.get("id") != template_id]
    if len(items) == before:
        raise HTTPException(status_code=404, detail="模板不存在")
    _save_templates(items)
    return {"ok": True, "message": "模板已删除", "items": items}


# ==================== 自定义风格（用户描述 -> LLM 生成 StyleConfig）====================
class CreateStyleReq(BaseModel):
    description: str  # 用户的自然语言风格描述
    name: Optional[str] = None  # 可选风格名（不填则由 LLM 生成）


@app.get("/api/styles")
async def list_custom_styles(user: dict = Depends(get_current_user)):
    """列出所有自定义风格"""
    from style_manager import list_styles
    return {"items": list_styles()}


@app.post("/api/styles")
async def create_custom_style(req: CreateStyleReq, user: dict = Depends(rate_limit_require_login())):
    """根据用户描述调用 LLM 生成自定义风格配置并保存"""
    from style_manager import generate_style_from_description, save_style, list_styles
    if not req.description.strip():
        raise HTTPException(status_code=400, detail="风格描述不能为空")
    try:
        cfg = generate_style_from_description(req.description.strip(), name=req.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成风格失败：{e}")
    saved = save_style(cfg)
    return {
        "ok": True,
        "message": f"自定义风格「{saved.get('style_name')}」已保存",
        "style": saved,
        "items": list_styles(),
    }


@app.delete("/api/styles/{style_id}")
async def delete_custom_style(style_id: str, user: dict = Depends(rate_limit_require_login())):
    """删除自定义风格"""
    from style_manager import delete_style, list_styles
    ok = delete_style(style_id)
    if not ok:
        raise HTTPException(status_code=404, detail="风格不存在")
    return {"ok": True, "message": "风格已删除", "items": list_styles()}


# ==================== 出图质量评估 ====================
class EvaluateReq(BaseModel):
    image_filenames: Optional[List[str]] = None  # 留空=评估最近一批剧照
    threshold: int = 70


@app.post("/api/evaluate")
async def api_evaluate(req: EvaluateReq, user: dict = Depends(rate_limit_require_login())):
    """调用视觉模型对剧照质量评分。走云端API，不占本地GPU。"""
    args = {"image_filenames": req.image_filenames or [], "threshold": req.threshold}
    result, progress = await asyncio.to_thread(_run_tool_direct, "evaluate_image", args)
    return {"result": result, "progress": progress}


# ==================== 系统监控 ====================
# 简易 API 调用计数器（进程内）
_api_call_stats = {"chat": 0, "generate_prompt": 0, "generate_stills": 0,
                   "edit_image": 0, "full_pipeline": 0, "evaluate": 0,
                   "export": 0, "other": 0}


def _bump_api_stat(name: str):
    key = name if name in _api_call_stats else "other"
    _api_call_stats[key] = _api_call_stats.get(key, 0) + 1


@app.get("/api/metrics")
async def api_metrics(user: dict = Depends(rate_limit_require_login())):
    """系统监控：GPU 状态、任务队列、API 调用量、服务健康。
    仅 admin 可访问；普通用户仅能看队列摘要。
    """
    is_admin = user.get("role") == "admin"
    # ---- 任务队列 ----
    import requests as _requests
    tasks_all = task_queue.list_tasks(limit=200)
    stats = {"queued": 0, "running": 0, "success": 0, "failed": 0, "cancelled": 0}
    for t in tasks_all:
        s = t.get("status")
        if s in stats:
            stats[s] += 1
    task_summary = {"total": len(tasks_all), **stats}

    # ---- GPU 状态（仅 admin）----
    gpu_info = None
    if is_admin:
        gpu_info = _probe_gpu()

    # ---- 服务健康 ----
    services = {}
    try:
        r = _requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=2)
        services["ollama"] = {"status": "ok" if r.status_code == 200 else f"error:{r.status_code}"}
        if r.status_code == 200:
            models = [m.get("name", "") for m in r.json().get("models", [])]
            services["ollama"]["models"] = models
    except Exception as e:
        services["ollama"] = {"status": f"down:{e}"}
    try:
        r = _requests.get(f"{config.COMFYUI_URL}/system_stats", timeout=2)
        services["comfyui"] = {"status": "ok" if r.status_code == 200 else f"error:{r.status_code}"}
        if r.status_code == 200:
            data = r.json()
            services["comfyui"]["device"] = data.get("devices", [{}])[0].get("name", "")
    except Exception as e:
        services["comfyui"] = {"status": f"down:{e}"}
    services["dashscope"] = {"configured": bool(config.DASHSCOPE_API_KEY),
                             "vl_model": config.DASHSCOPE_VL_MODEL}

    # ---- 磁盘输出统计 ----
    def _count_images(folder):
        d = config.OUTPUT_DIR / folder
        if not d.exists():
            return 0
        n = 0
        for p in d.rglob("*.png"):
            n += 1
        return n

    disk = {
        "prompts_files": len(list(config.PROMPTS_DIR.glob("*.json"))) if config.PROMPTS_DIR.exists() else 0,
        "stills_images": _count_images("stills"),
        "edited_images": _count_images("edited"),
    }

    result = {
        "task_summary": task_summary,
        "services": services,
        "disk": disk,
        "api_calls": _api_call_stats if is_admin else None,
        "config": {
            "max_concurrent_tasks": config.MAX_CONCURRENT_TASKS,
            "ollama_model": config.OLLAMA_MODEL,
            "evaluate_threshold": config.EVALUATE_THRESHOLD,
        },
    }
    if is_admin and gpu_info is not None:
        result["gpu"] = gpu_info
    return result


def _probe_gpu():
    """通过 nvidia-smi 探测 GPU 状态（仅 Windows/Linux）。失败返回 None。"""
    import subprocess
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3)
        if out.returncode != 0:
            return None
        rows = []
        for line in out.stdout.strip().splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 6:
                rows.append({
                    "name": parts[0],
                    "memory_total_mb": int(parts[1]),
                    "memory_used_mb": int(parts[2]),
                    "memory_free_mb": int(parts[3]),
                    "utilization_pct": int(parts[4]),
                    "temperature_c": int(parts[5]),
                })
        return rows
    except Exception:
        return None


# ==================== 同步工具调用（兼容旧接口）====================
@app.post("/api/generate_prompt")
async def api_generate_prompt(req: GeneratePromptReq, user: dict = Depends(rate_limit_require_login())):
    args = {"style": req.style, "counts": req.counts}
    if req.specials:
        args["specials"] = req.specials
    result, progress = await asyncio.to_thread(
        _run_tool_direct, "generate_prompt", args)
    return {"result": _convert_paths(result), "progress": progress}


@app.post("/api/generate_stills")
async def api_generate_stills(req: GenerateStillsReq, user: dict = Depends(rate_limit_require_login())):
    prompts_file = req.prompts_file or _find_latest_prompts()
    if not prompts_file:
        return {"result": {"error": "没有可用的提示词文件"}, "progress": []}
    args = {"prompts_file": prompts_file, "ids": req.ids}
    result, progress = await asyncio.to_thread(_run_tool_direct, "generate_stills", args)
    return {"result": _convert_paths(result), "progress": progress}


@app.post("/api/edit_image")
async def api_edit_image(req: EditImageReq, user: dict = Depends(rate_limit_require_login())):
    image_path = req.image_path or _find_latest_image()
    if not image_path:
        return {"result": {"error": "没有可修的图片"}, "progress": []}
    args = {"image_path": image_path, "instruction": req.instruction}
    result, progress = await asyncio.to_thread(_run_tool_direct, "edit_image", args)
    return {"result": _convert_paths(result), "progress": progress}


@app.post("/api/pipeline")
async def api_pipeline(req: PipelineReq, user: dict = Depends(rate_limit_require_login())):
    args = {"style": req.style, "counts": req.counts,
            "edit_instruction": req.edit_instruction or ""}
    if req.specials:
        args["specials"] = req.specials
    result, progress = await asyncio.to_thread(_run_tool_direct, "full_pipeline", args)
    return {"result": _convert_paths(result), "progress": progress}


# 注：/ws/chat 与 /api/chat 已随 Agent 对话框模块整体移除（v2.1）。
#     用户主交互路径为「Pipeline / Stills / Edit / Gallery」+ 任务队列 WS（/ws/tasks）。
if __name__ == "__main__":
    import uvicorn
    import logging
    # 关闭 access log，只保留 error 和启动信息
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    uvicorn.run("server:app", host=config.SERVER_HOST,
                port=config.SERVER_PORT, reload=False,
                access_log=False, log_level="info")


# ==================== /app/ 重定向到根路径 ====================
@app.get("/app")
async def redirect_app():
    """将 /app 重定向到 /（前端现在挂载在根路径）"""
    return RedirectResponse(url="/")


# ==================== SPA 回退（必须放在所有路由之后）====================
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str, request: Request):
    """任何非 API / 非文件 / 非 WS 的 GET 请求，都返回前端 index.html"""
    path = request.url.path
    # API 和特殊路径不回退
    if path.startswith("/api/") or path.startswith("/files/") or path.startswith("/ws"):
        raise HTTPException(status_code=404, detail="Not Found")
    # 静态资源直接返回（文件名带 content hash，可长期缓存）
    if path.startswith("/assets/"):
        file_path = STATIC_DIR / path.lstrip("/")
        if file_path.is_file():
            from fastapi.responses import FileResponse
            return FileResponse(
                str(file_path),
                headers={"Cache-Control": "public, max-age=31536000, immutable"})
    # 默认返回 index.html（SPA）—— 绝不能缓存，否则会一直引用旧 hash
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        from fastapi.responses import FileResponse
        return FileResponse(
            str(index_file),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    raise HTTPException(status_code=404, detail="前端文件不存在")
