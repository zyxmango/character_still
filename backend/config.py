# -*- coding: utf-8 -*-
"""
全局配置：路径、服务地址、工作流节点ID、模型参数。
所有可变配置支持环境变量覆盖，方便容器化部署。
"""
import os
from pathlib import Path

# ==================== 基础路径 ====================
# 后端代码移至 backend/ 子目录，BASE_DIR 指向项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# ==================== 服务地址（环境变量化）====================
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
# 提示词生成模型（高质量中文写作，需要大模型）
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_FALLBACK_MODELS = os.environ.get(
    "OLLAMA_FALLBACK_MODELS", "qwen2.5:14b,qwen2.5:7b,qwen3:32b").split(",")
COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
# ==================== 云端 API 配置（视觉评估用，阿里云百炼 DashScope）====================
# API Key：在阿里云百炼控制台获取 https://bailian.console.aliyun.com/
# Dashboard -> 模型广场 -> API-KEY 管理 -> 创建
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
# 百炼 OpenAI 兼容模式 endpoint
DASHSCOPE_API_URL = os.environ.get(
    "DASHSCOPE_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")

# ==================== 视觉模型配置（出图质量自评用）====================
# 使用百炼 qwen-vl-plus 视觉理解模型对生成的剧照打分
DASHSCOPE_VL_MODEL = os.environ.get("DASHSCOPE_VL_MODEL", "qwen-vl-plus")
# 质量评估及格分数线（低于此分数标记 needs_regen）
EVALUATE_THRESHOLD = int(os.environ.get("EVALUATE_THRESHOLD", "70"))
# 单次批量评估上限（避免 token 超限）
EVALUATE_BATCH_LIMIT = int(os.environ.get("EVALUATE_BATCH_LIMIT", "20"))

# ==================== 服务器配置 ====================
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8000"))

# ==================== 并发与限流 ====================
MAX_CONCURRENT_TASKS = int(os.environ.get("MAX_CONCURRENT_TASKS", "1"))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))
RATE_LIMIT_GENERATE_PER_HOUR = int(os.environ.get("RATE_LIMIT_GENERATE_PER_HOUR", "20"))

# ==================== 重试配置 ====================
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))
COMFYUI_MAX_RETRIES = int(os.environ.get("COMFYUI_MAX_RETRIES", "2"))

# ==================== 工作流文件（ComfyUI API 格式）====================
T2I_WORKFLOW = BASE_DIR / os.environ.get(
    "T2I_WORKFLOW", "FLUX(文生图）-短剧项目-API-agent(test).json")
EDIT_WORKFLOW = BASE_DIR / os.environ.get(
    "EDIT_WORKFLOW", "服装迁移-千问Edit2509图像编辑 (2)-API-agent-test.json")

# ==================== 输出目录 ====================
OUTPUT_DIR = BASE_DIR / os.environ.get("OUTPUT_DIR", "output")
PROMPTS_DIR = OUTPUT_DIR / "prompts"
STILLS_DIR = OUTPUT_DIR / "stills"
EDITED_DIR = OUTPUT_DIR / "edited"
# 任务模板和自定义风格配置目录（用户级配置数据）
CONFIG_DIR = OUTPUT_DIR / "config"
TEMPLATES_FILE = CONFIG_DIR / "templates.json"
CUSTOM_STYLES_FILE = CONFIG_DIR / "custom_styles.json"

# ==================== 文生图工作流节点ID（已核对修正）====================
T2I_NODES = {
    "text": "17",            # Text Multiline —— 正向提示词
    "flux_guidance": "3",    # FluxGuidance
    "clip_encode": "8",      # CLIPTextEncodeFlux
    "negative": "7",         # CLIPTextEncode —— 负向提示词
    "empty_latent": "12",    # EmptyLatentImage（宽高）
    "save_image": "11",      # SaveImage
    "ksampler": "6",         # KSampler —— 随机种子(seed)
}
T2I_GUIDANCE = 8.0
T2I_CLIP_GUIDANCE = 3.5
T2I_WIDTH = 720
T2I_HEIGHT = 1280

# ==================== 修图工作流节点ID（已核对修正）====================
EDIT_NODES = {
    "load_image": "57",      # LoadImage
    "instruction": "56",     # Text Multiline —— 修图指令
    "save_image": "22",      # SaveImage
}

# ==================== 轮询参数 ====================
POLL_INTERVAL = 3
POLL_MAX_RETRY = 400       # 约20分钟

# ==================== 风格映射 ====================
# 以下为内置回退值；若存在「提示词工程配置」md（backend/prompts/prompt_engineering.md），
# 则以该文件的配置为准。改 md 即可新增风格/身份/特征，无需改代码。
STYLE_MAP = {
    "端庄大气传统型": "1",
    "唯美艺术型": "2",
}
ALL_STATUSES = ["贵族", "富豪", "仙人", "侠客", "魔族", "平民"]
# 特殊特征（独立维度，可叠加在任意地位上）
ALL_SPECIALS = ["轮椅", "独眼", "孕妇", "光头", "侏儒", "巨人"]


def _from_loader(fn, fallback):
    """优先取提示词工程配置，失败则回退内置值"""
    try:
        import prompt_loader
        value = fn(prompt_loader)
        if value:
            return value
    except Exception:
        pass
    return fallback


def all_statuses() -> list:
    """身份列表（来自提示词工程配置）"""
    return _from_loader(lambda pl: pl.statuses(), ALL_STATUSES)


def all_specials() -> list:
    """特殊特征列表（来自提示词工程配置）"""
    return _from_loader(lambda pl: pl.specials(), ALL_SPECIALS)


def style_map() -> dict:
    """风格名 → 编号（来自提示词工程配置）"""
    return _from_loader(
        lambda pl: {name: str(i + 1) for i, name in enumerate(pl.style_names())},
        STYLE_MAP,
    )


def refresh_dynamic():
    """用最新配置刷新模块级常量。改完 md 或保存配置后调用。"""
    global STYLE_MAP, ALL_STATUSES, ALL_SPECIALS
    ALL_STATUSES = all_statuses()
    ALL_SPECIALS = all_specials()
    STYLE_MAP = style_map()


def ensure_dirs():
    """确保所有输出目录存在"""
    for d in (OUTPUT_DIR, PROMPTS_DIR, STILLS_DIR, EDITED_DIR, CONFIG_DIR):
        d.mkdir(parents=True, exist_ok=True)
