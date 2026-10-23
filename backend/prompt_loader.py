# -*- coding: utf-8 -*-
"""
提示词工程配置加载器。

职责：
- 读取 backend/prompts/prompt_engineering.md 中的 yaml 配置块
- 按文件修改时间热加载，改完 md 无需重启服务
- 文件缺失或解析失败时，回退到内置默认配置（DEFAULTS），保证服务可用

md 中的 yaml 块会以「后面的覆盖前面的」方式合并成一个 dict。
"""

import os
import re
import shutil
import datetime
from pathlib import Path

import yaml

GUIDE_PATH = Path(os.environ.get(
    "PROMPT_GUIDE_FILE",
    str(Path(__file__).resolve().parent / "prompts" / "prompt_engineering.md"),
))

# ==================== 内置默认配置（回退用） ====================
# 与代码原硬编码值保持一致；md 存在且可解析时以 md 为准
DEFAULTS = {
    "世界观": "中国古代",
    "服饰专家人设": "精通中国古代服饰史的顶级设计师",
    "服饰种类词": "古装",
    "背景与构图": "pure white background, full body shot, front view, standing pose",
    "质量词": "masterpiece, best quality, 8k ultra detailed",
    "鞋履规则": "必须全包脚、不露脚趾、平底无后跟；严禁运动鞋、高跟鞋、皮鞋、凉鞋、木屐",
    "时代名词": "朝代",
    "硬性要求": [
        "绝对禁止与现代世界观冲突的元素",
        "配色严格使用指定主色与配色，严禁出现第三种服装主色",
        "体型必须在服饰描述中显式体现剪裁关键词",
        "所有元素必须符合所选风格的整体审美",
        "性别严格匹配，严禁出现异性特征",
    ],
    "输出字段": {
        "朝代": "具体时代或地域，如 唐代",
        "服装描述": "详细描述，包含上衣款式、下装、外罩、面料质感、纹样刺绣、配饰细节，必须符合所选风格，80-120字",
        "鞋子描述": "鞋履详细描述，包含款式名称、颜色、材质、装饰纹样，30-40字，必须全包脚不露趾+平底无后跟",
        "发型描述": "发型详细描述，必须包含①具体髻式名称+位置/结构描述 ②簪钗步摇等配饰及材质颜色 ③发色发质描述，40-50字",
        "面部特征": "根据性别和年龄生成，必须包含①脸型②眼型③眉形④鼻型⑤唇形⑥肤质年龄特征，40-50字",
        "光影氛围": "符合所选风格的光影描述，要有创意变化，20-30字",
        "特殊细节": "针对该身份与风格的独特设计元素，30-50字",
        "气质关键词": "3-5个形容角色气质的词汇，必须符合身份气质",
    },
    "颜色": ["白色", "粉色", "黑色", "紫色", "藏青色", "绿色", "红色", "蓝色"],
    "配色伙伴色": ["金色", "银色", "白色", "黑色", "月白", "玄色"],
    "身份": {
        "贵族": {
            "气质词池": ["端庄", "威严", "高贵", "雍容", "肃穆", "典雅"],
            "核心特征": "权力象征、礼制严谨、纹样尊贵、版型正统、配饰华丽但克制",
            "禁令": "无特殊禁令",
            "允许元素": "云锦、缂丝、织金锦；龙纹四章、仙鹤补子；玉带、金冠",
            "时代": ["唐代", "宋代", "明代", "清代"],
        },
        "富豪": {
            "气质词池": ["富态", "从容", "气定神闲", "志得意满", "富贵"],
            "核心特征": "富贵逼人、面料奢华、金玉点缀、纹样繁复、尽显财力",
            "禁令": "严禁出现象征权力的龙纹/凤纹/十二章纹",
            "允许元素": "绸缎、织锦；缠枝纹、宝相花；金镯、玉佩、宝石帽正",
            "时代": ["明代", "清代", "宋代"],
        },
        "仙人": {
            "气质词池": ["出尘", "飘逸", "空灵", "超然", "仙气"],
            "核心特征": "仙气出尘、飘逸空灵、素净淡雅、云纹水袖、不食人间烟火",
            "禁令": "严禁金玉堆砌的富贵感、严禁繁琐宫廷礼制元素",
            "允许元素": "轻纱、雪纺、素绢；云纹、水波纹；拂尘、玉簪、丝带",
            "时代": ["唐代", "宋代", "魏晋"],
        },
        "侠客": {
            "气质词池": ["英气", "锐利", "沉稳", "凛然", "干练"],
            "核心特征": "英气干练、劲装利落、便于行动、侠气凛然、简约实用",
            "禁令": "严禁宽袍大袖、严禁长裙曳地、严禁繁复刺绣、严禁金玉珠宝",
            "允许元素": "劲布、皮革、麻布；暗纹、素纹；剑、斗笠、束带",
            "时代": ["明代", "宋代", "唐代"],
        },
        "魔族": {
            "气质词池": ["冷峻", "诡谲", "邪魅", "压迫", "神秘"],
            "核心特征": "邪魅冷峻、暗纹诡谲、色调暗沉、气场压迫、神秘妖异",
            "禁令": "严禁明亮喜庆色调、严禁端庄正统礼制服饰",
            "允许元素": "暗纹绸、玄色面料；鬼纹、火焰纹；骨饰、黑玉、暗银",
            "时代": ["元代", "唐代"],
        },
        "平民": {
            "气质词池": ["质朴", "朴实", "平和", "憨厚", "安分"],
            "核心特征": "朴素简约、粗布麻衣、实用耐穿、无过多装饰、贴近生活",
            "禁令": ("严禁凤凰/龙纹/麒麟等神兽纹样、严禁金线/银线重工刺绣、严禁锦缎/云锦/缂丝等奢华面料、"
                     "严禁步摇/凤冠/珠翠等华贵头饰、严禁披风/大氅、严禁红玉/翡翠等宝石配饰、面料必须为棉麻粗布"),
            "允许元素": "棉布、麻布、粗布；素面或简单几何纹；木簪、布巾、绳结",
            "时代": ["宋代", "明代", "唐代"],
        },
        "特殊": {
            "气质词池": ["怪异", "独特", "诡奇", "异于常人"],
            "核心特征": "独特怪异、与众不同、自带辨识度、视觉冲击力强",
            "禁令": "严禁过于正常的平民元素，需突出怪异感",
            "允许元素": "异材质、怪异纹样；奇特配饰",
            "时代": ["宋代", "明代", "唐代"],
        },
    },
    "特殊特征": ["轮椅", "独眼", "孕妇", "光头", "侏儒", "巨人"],
    "面部特征": {
        "老年-男": [
            "面容沧桑，皱纹纵横交错，额头深纹，眼角鱼尾纹明显，肤色偏深粗糙，银发稀疏，神态硬朗，充满阅历感",
            "面容硬朗，皱纹深刻有型，眉骨突出，目光炯炯有神但眼袋明显，银发整齐，气质威严沉稳，不怒自威",
        ],
        "老年-女": [
            "面容慈祥，眼角皱纹细密，法令纹明显，眼神温润睿智，银发疏朗，皮肤松弛但有光泽，神态安详从容",
            "面容优雅，皱纹柔和但清晰可见，眼角细纹与额头纹路诉说岁月，眼神沉静知性，银发梳理整齐，气质温婉大气",
        ],
        "青年-男": [
            "面容俊朗，剑眉星目，鼻梁高挺，下颌线锋利，神采飞扬，朝气蓬勃，英气十足",
            "五官立体分明，眉骨突出，眼神锐利有神，轮廓硬朗，气质清爽干练，风华正茂",
        ],
        "青年-女": [
            "明眸皓齿，肌肤细腻如玉，眉眼弯弯，五官精致柔和，气质温婉灵动，青春靓丽",
            "肌肤白皙透亮，眉眼精致，眼神清澈温柔，气质温婉娴静，自带少女感",
        ],
        "少年-男": [
            "眉目清秀带英气，眼神明亮坚定，面庞稚嫩但轮廓初显，神态挺拔，少年英姿初显",
            "面容俊气稚嫩，鼻梁挺翘，目光清澈有神，脸颊尚带婴儿肥，自带少年英气与朝气",
        ],
        "少年-女": [
            "面容稚嫩可爱，脸颊圆润带婴儿肥，眼神清澈明亮，天真烂漫，稚气未脱，神态软萌乖巧",
            "五官小巧精致，眉眼灵动，笑容灿烂，眼神明亮有光，天真无邪，活力满满",
        ],
    },
    "体型": {
        "矮胖": "chubby and short figure",
        "普通": "average figure",
        "瘦小": "slim and petite figure",
    },
    "风格": {
        "端庄大气传统型": {
            "描述": "整体气势端庄大气，符合传统古代人设，威严正统",
            "气质关键词": ["端庄", "大气", "威严", "正统", "肃穆", "稳重", "高贵", "典雅"],
            "偏好颜色": ["红色", "黑色", "紫色", "藏青色", "蓝色"],
            "姿势": "正面站立，身姿挺拔，气宇轩昂",
            "光影": "明亮但柔和的自然光，突出人物立体感，背景纯净",
            "细节": "极高，服饰纹理清晰可见，刺绣细节精致，配饰考究",
        },
        "唯美艺术型": {
            "描述": "极致精致华丽，仙气飘逸，五官绝美，服饰重工华丽，光影梦幻，整体高级美感拉满，艺术感极强",
            "气质关键词": ["绝美", "精致", "华丽", "仙气", "灵动", "倾城", "绝色", "璀璨"],
            "偏好颜色": ["白色", "粉色", "紫色", "绿色", "蓝色"],
            "姿势": "身姿曼妙，衣袂翩飞，动态优雅，回眸浅笑，姿态柔美灵动",
            "光影": "柔光璀璨，发丝光晕，丁达尔光效，梦幻光影，高光点缀，通透质感",
            "细节": "极致精致，重工刺绣，珠翠环绕，面料流光溢彩，发丝根根分明",
        },
    },
}

# ==================== 缓存 ====================
_cache = {"mtime": None, "data": None, "source": None}


def _parse_yaml_blocks(text: str):
    """提取 md 中所有 ```yaml 块并合并。返回 (dict, errors, block_count)"""
    blocks = re.findall(r"```[ \t]*ya?ml[ \t]*\r?\n(.*?)```", text, flags=re.S | re.I)
    merged = {}
    errors = []
    for i, block in enumerate(blocks, 1):
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError as e:
            errors.append(f"第 {i} 个 yaml 块解析失败：{_brief(e)}")
            continue
        if isinstance(data, dict):
            merged.update(data)
    return merged, errors, len(blocks)


def _brief(e) -> str:
    msg = str(e).replace("\n", " ")
    return msg[:200]


def _validate_sections(data: dict):
    """校验必需字段是否齐全、类型是否正确。返回问题列表"""
    problems = []

    if not isinstance(data.get("身份"), dict) or not data["身份"]:
        problems.append("缺少「身份」配置（三、身份设定）")
    else:
        for name, info in data["身份"].items():
            if not isinstance(info, dict):
                problems.append(f"身份「{name}」格式错误，应为包含 气质词池/核心特征/禁令/允许元素/时代 的对象")
                continue
            for key in ("气质词池", "核心特征", "禁令", "允许元素", "时代"):
                if key not in info:
                    problems.append(f"身份「{name}」缺少字段：{key}")
            if not isinstance(info.get("气质词池"), list):
                problems.append(f"身份「{name}」的气质词池必须是列表")

    if not isinstance(data.get("风格"), dict) or not data["风格"]:
        problems.append("缺少「风格」配置（五、风格预设）")
    else:
        for name, s in data["风格"].items():
            if not isinstance(s, dict):
                problems.append(f"风格「{name}」格式错误")
                continue
            for key in ("描述", "气质关键词", "偏好颜色", "姿势", "光影", "细节"):
                if key not in s:
                    problems.append(f"风格「{name}」缺少字段：{key}")

    if not isinstance(data.get("颜色"), list) or not data["颜色"]:
        problems.append("缺少「颜色」配置（二、数据库颜色）")

    if not isinstance(data.get("输出字段"), dict) or not data["输出字段"]:
        problems.append("缺少「输出字段」配置（一、全局设定）")

    return problems


def load_guide(force: bool = False):
    """加载配置。md 存在且可解析则返回 md 内容，否则返回内置默认值。

    返回 (data: dict, info: dict)
    info 含 source('file'|'default'|'fallback')、errors、problems、mtime
    """
    if not force and _cache["data"] is not None:
        if GUIDE_PATH.exists():
            mtime = GUIDE_PATH.stat().st_mtime
            if mtime == _cache["mtime"]:
                return _cache["data"], {"source": _cache["source"], "errors": [], "problems": [],
                                        "mtime": mtime, "path": str(GUIDE_PATH)}

    info = {"source": "default", "errors": [], "problems": [], "mtime": None, "path": str(GUIDE_PATH)}

    if not GUIDE_PATH.exists():
        _cache.update({"mtime": None, "data": DEFAULTS, "source": "default"})
        return DEFAULTS, info

    mtime = GUIDE_PATH.stat().st_mtime
    info["mtime"] = mtime
    try:
        text = GUIDE_PATH.read_text(encoding="utf-8")
    except Exception as e:
        info["errors"].append(f"读取文件失败：{e}")
        _cache.update({"mtime": mtime, "data": DEFAULTS, "source": "fallback"})
        return DEFAULTS, info

    data, errors, block_count = _parse_yaml_blocks(text)
    info["errors"] = errors
    info["blocks"] = block_count

    if block_count == 0:
        info["errors"].append("没有找到任何 yaml 配置块，请检查 ```yaml 代码块是否完整")
    if errors or not data:
        _cache.update({"mtime": mtime, "data": DEFAULTS, "source": "fallback"})
        return DEFAULTS, info

    problems = _validate_sections(data)
    info["problems"] = problems
    if problems:
        # 结构性问题：仍然回退，避免生成出残缺提示词
        _cache.update({"mtime": mtime, "data": DEFAULTS, "source": "fallback"})
        return DEFAULTS, info

    _cache.update({"mtime": mtime, "data": data, "source": "file"})
    info["source"] = "file"
    return data, info


def reload_guide():
    """强制重新加载（保存 md 后调用）"""
    return load_guide(force=True)


# ==================== 结构化取值 ====================
def _get(key, default=None):
    data, _ = load_guide()
    return data.get(key, default)


def statuses() -> list:
    """身份列表（不含 '特殊'，特殊是独立维度）"""
    identity, _ = load_guide()
    return [k for k in (identity.get("身份") or {}).keys() if k != "特殊"]


def status_info(name: str) -> dict:
    identity, _ = load_guide()
    return (identity.get("身份") or {}).get(name, {}) or {}


def status_temperament() -> dict:
    identity, _ = load_guide()
    return {k: (v or {}).get("气质词池", []) for k, v in (identity.get("身份") or {}).items()}


def status_forbidden() -> dict:
    identity, _ = load_guide()
    return {k: (v or {}).get("禁令", "无") for k, v in (identity.get("身份") or {}).items()}


def status_allowed() -> dict:
    identity, _ = load_guide()
    return {k: (v or {}).get("允许元素", "") for k, v in (identity.get("身份") or {}).items()}


def status_features() -> dict:
    identity, _ = load_guide()
    return {k: (v or {}).get("核心特征", "") for k, v in (identity.get("身份") or {}).items()}


def status_dynasties() -> dict:
    identity, _ = load_guide()
    return {k: (v or {}).get("时代", []) for k, v in (identity.get("身份") or {}).items()}


def styles() -> dict:
    return _get("风格", {}) or {}


def style_names() -> list:
    return list((_get("风格", {}) or {}).keys())


def colors() -> list:
    return _get("颜色", []) or []


def accent_colors() -> list:
    return _get("配色伙伴色", []) or ["金色", "银色", "白色", "黑色"]


def specials() -> list:
    return _get("特殊特征", []) or []


def face_features() -> dict:
    return _get("面部特征", {}) or {}


def body_map() -> dict:
    return _get("体型", {}) or {}


def global_settings() -> dict:
    """全局设定相关字段"""
    data, _ = load_guide()
    keys = ["世界观", "服饰专家人设", "服饰种类词", "背景与构图", "质量词",
            "鞋履规则", "时代名词", "硬性要求", "输出字段"]
    return {k: data.get(k) for k in keys}


def output_fields() -> dict:
    return _get("输出字段", {}) or {}


def epoch_word() -> str:
    return _get("时代名词", "朝代") or "朝代"


# ==================== 读写 md ====================
def read_text() -> str:
    if not GUIDE_PATH.exists():
        return ""
    return GUIDE_PATH.read_text(encoding="utf-8")


def write_text(text: str, backup: bool = True) -> str:
    """保存 md，返回备份路径（无备份则返回空串）"""
    backup_path = ""
    if backup and GUIDE_PATH.exists():
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = str(GUIDE_PATH.with_suffix(f".bak_{ts}.md"))
        shutil.copy2(GUIDE_PATH, backup_path)
    GUIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GUIDE_PATH.write_text(text, encoding="utf-8")
    reload_guide()
    return backup_path


def validate_text(text: str) -> dict:
    """校验一段 md 文本，返回 {ok, errors, problems, blocks, sections}"""
    data, errors, block_count = _parse_yaml_blocks(text)
    problems = _validate_sections(data) if not errors else []
    sections = sorted(data.keys())
    return {
        "ok": not errors and not problems and bool(data),
        "errors": errors,
        "problems": problems,
        "blocks": block_count,
        "sections": sections,
        "statuses": [k for k in (data.get("身份") or {}).keys()] if isinstance(data.get("身份"), dict) else [],
        "styles": list((data.get("风格") or {}).keys()) if isinstance(data.get("风格"), dict) else [],
    }


def restore_default(backup: bool = True) -> str:
    """恢复为内置默认配置的 md 内容（会先备份当前文件）"""
    backup_path = ""
    if backup and GUIDE_PATH.exists():
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = str(GUIDE_PATH.with_suffix(f".bak_{ts}.md"))
        shutil.copy2(GUIDE_PATH, backup_path)

    # 用当前文件保留说明性文字，只替换 yaml 数据块是不现实的，
    # 因此这里直接写回一份由 DEFAULTS 生成的最小可用文档
    lines = [
        "# 提示词工程配置手册（已恢复为默认配置）",
        "",
        "> 本文件由「恢复默认」自动生成。原文件已备份为同目录下 .bak_*.md。",
        "> 修改下方 yaml 块即可扩展角色类型与风格，保存后下次生成自动生效。",
        "",
        "```yaml",
        yaml.safe_dump(DEFAULTS, allow_unicode=True, sort_keys=False, default_flow_style=False),
        "```",
        "",
    ]
    GUIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GUIDE_PATH.write_text("\n".join(lines), encoding="utf-8")
    reload_guide()
    return backup_path
