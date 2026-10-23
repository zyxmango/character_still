# -*- coding: utf-8 -*-
"""自定义风格管理：用户描述 -> LLM 生成 StyleConfig -> 持久化 -> 注入 engine.style_presets"""
import json
from pathlib import Path

import requests

import config
from logger import get_logger
from main_end import StyleConfig

logger = get_logger(__name__)

# 风格 key 前缀，避免与内置 "1"/"2" 冲突
CUSTOM_PREFIX = "c"


def _load_custom_styles() -> list:
    """读取自定义风格列表"""
    if not config.CUSTOM_STYLES_FILE.exists():
        return []
    try:
        with open(config.CUSTOM_STYLES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_custom_styles(items: list):
    """保存自定义风格列表"""
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.CUSTOM_STYLES_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def list_styles() -> list:
    """列出所有自定义风格（含 id/name/description，供前端展示）"""
    return _load_custom_styles()


def get_style_by_id(style_id: str) -> dict | None:
    for s in _load_custom_styles():
        if s.get("id") == style_id:
            return s
    return None


def delete_style(style_id: str) -> bool:
    items = _load_custom_styles()
    new_items = [s for s in items if s.get("id") != style_id]
    if len(new_items) == len(items):
        return False
    _save_custom_styles(new_items)
    return True


def generate_style_from_description(description: str, name: str = None,
                                    ollama_url: str = None, model: str = None) -> dict:
    """调用 LLM 根据用户描述生成 StyleConfig 字段。
    返回 dict（含 id/style_name/description/temperament_keywords/color_preference/...）。
    """
    ollama_url = ollama_url or config.OLLAMA_URL
    model = model or config.OLLAMA_MODEL

    system_prompt = """你是古装人物剧照风格设计专家。根据用户描述，生成一套完整的风格配置。
必须严格输出纯 JSON（不要 markdown 代码块、不要解释文字），格式如下：
{
  "style_name": "风格名称（4-8字，简洁有力）",
  "description": "风格详细描述（20-50字，说明视觉特征）",
  "temperament_keywords": ["关键词1", "关键词2", ...],
  "color_preference": ["颜色1", "颜色2", ...],
  "pose_style": "姿势风格描述（10-30字）",
  "lighting_mood": "光影氛围描述（10-30字）",
  "detail_level": "细节程度描述（10-30字）"
}

约束：
- temperament_keywords: 8-16 个气质关键词
- color_preference: 3-5 个偏好颜色，必须从这 8 种中选：白色、粉色、黑色、紫色、藏青色、绿色、红色、蓝色
- 所有字段必须为中文
- 输出必须是合法 JSON"""

    user_prompt = f"用户描述：{description}\n\n请生成对应的风格配置 JSON。"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.7, "top_p": 0.9},
    }
    logger.info(f"调用 LLM 生成自定义风格: model={model}, description={description[:50]}")
    resp = requests.post(f"{ollama_url}/api/chat", json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    content = (data.get("message", {}) or {}).get("content", "") or ""

    # 清理可能的 markdown 代码块
    content = content.strip()
    if content.startswith("```"):
        # 去掉首行 ``` 和末尾 ```
        lines = content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        cfg = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"LLM 返回的 JSON 解析失败: {e}\n原始内容: {content[:200]}")
        raise ValueError(f"LLM 返回格式错误：{e}")

    # 校验并兜底
    valid_colors = {"白色", "粉色", "黑色", "紫色", "藏青色", "绿色", "红色", "蓝色"}
    cfg["color_preference"] = [c for c in cfg.get("color_preference", []) if c in valid_colors]
    if not cfg["color_preference"]:
        cfg["color_preference"] = ["红色", "黑色"]  # 兜底

    if not cfg.get("temperament_keywords"):
        cfg["temperament_keywords"] = ["端庄", "大气"]
    if not cfg.get("style_name"):
        cfg["style_name"] = name or "自定义风格"
    if not cfg.get("pose_style"):
        cfg["pose_style"] = "正面站立，身姿挺拔"
    if not cfg.get("lighting_mood"):
        cfg["lighting_mood"] = "明亮柔和的自然光"
    if not cfg.get("detail_level"):
        cfg["detail_level"] = "高细节，服饰纹理清晰"

    # 记录用户原始描述
    cfg["user_description"] = description
    if name:
        cfg["style_name"] = name

    return cfg


def save_style(cfg: dict) -> dict:
    """保存自定义风格（自动分配 id）"""
    import uuid as _uuid
    items = _load_custom_styles()
    # 同名更新
    name = cfg.get("style_name", "")
    existing = next((s for s in items if s.get("style_name") == name), None)
    if existing:
        existing.update(cfg)
        existing["id"] = existing.get("id") or _uuid.uuid4().hex[:8]
        cfg = existing
    else:
        cfg["id"] = _uuid.uuid4().hex[:8]
        items.append(cfg)
    _save_custom_styles(items)
    return cfg


def to_style_config(cfg: dict) -> StyleConfig:
    """dict -> StyleConfig 对象，供 OllamaQwenEngine 使用"""
    return StyleConfig(
        style_name=cfg.get("style_name", "自定义风格"),
        description=cfg.get("description", ""),
        temperament_keywords=cfg.get("temperament_keywords", []),
        color_preference=cfg.get("color_preference", []),
        pose_style=cfg.get("pose_style", ""),
        lighting_mood=cfg.get("lighting_mood", ""),
        detail_level=cfg.get("detail_level", ""),
    )


def inject_custom_styles(engine):
    """把自定义风格注入 engine.style_presets（key 为 c1, c2, ...）"""
    items = _load_custom_styles()
    for i, cfg in enumerate(items, 1):
        key = f"{CUSTOM_PREFIX}{i}"
        try:
            engine.style_presets[key] = to_style_config(cfg)
        except Exception as e:
            logger.warning(f"注入自定义风格 {cfg.get('style_name')} 失败: {e}")


def get_style_key_by_name(name: str) -> str | None:
    """根据风格名查找 key（提示词工程配置中的风格，或自定义风格）"""
    style_map = config.style_map()
    if name in style_map:
        return style_map[name]
    # 自定义风格
    for i, s in enumerate(_load_custom_styles(), 1):
        if s.get("style_name") == name:
            return f"{CUSTOM_PREFIX}{i}"
    return None
