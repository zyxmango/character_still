import json
import random
import re
import requests
import os
import time
import uuid
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
from collections import Counter

import prompt_loader as pl

@dataclass
class CharacterConfig:
    """人物配置"""
    gender: str           # 男/女
    age_group: str        # 青年/老年/少年
    status: str           # 贵族/富豪/仙人/侠客/魔族/平民/特殊
    body_type: str        # 矮胖/普通/瘦小
    color_theme: str      # 主色调+辅色调
    special_feature: Optional[str] = None  # 轮椅/独眼/孕妇/光头/侏儒/巨人


@dataclass
class StyleConfig:
    """风格配置"""
    style_name: str       # 风格名称
    description: str      # 风格描述
    temperament_keywords: List[str]  # 气质关键词库
    color_preference: List[str]      # 偏好的色调
    pose_style: str       # 姿势风格
    lighting_mood: str    # 光影氛围
    detail_level: str      # 细节程度

class OllamaQwenEngine:
    """基于本地Ollama Qwen模型的纯AI驱动提示词引擎 - 交互式版本"""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5:14b",
                 output_dir: str = None):
        self.base_url = base_url
        self.model = model
        self.api_url = f"{base_url}/api/generate"
        self.chat_url = f"{base_url}/api/chat"
        self.current_id = 0
        self.current_style: Optional[StyleConfig] = None
        # 输出目录可配置，默认为本机项目下的 output/prompts
        self.output_dir = output_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "output", "prompts")
        self.last_save_path = None  # 最近一次保存的提示词文件路径

        # 属性映射表
        self.gender_map = {"1": "女", "2": "男"}
        self.age_map = {"1": "老年", "2": "青年", "3": "少年"}
        self.body_map = {"1": "矮胖", "2": "普通", "3": "瘦小"}

        # ⬇️ 以下全部来自「提示词工程配置」md（backend/prompts/prompt_engineering.md）
        # 改 md 即可扩展身份/风格/颜色/时代，无需改代码
        self._load_prompt_guide()

    def _load_prompt_guide(self):
        """从提示词工程配置加载所有约束与素材库（单例引擎每次生成前调用以实现热更新）"""
        # 颜色（数据库打标校验 + 交互式编号）
        self.db_colors = pl.colors()
        self.color_map = {str(i + 1): c for i, c in enumerate(self.db_colors)}
        self.accent_colors = pl.accent_colors()

        # 身份 / 特殊特征（编号按配置顺序生成）
        self.status_map = {str(i + 1): s for i, s in enumerate(pl.statuses())}
        self.special_map = {str(i + 1): s for i, s in enumerate(pl.specials())}

        # 身份约束：气质词池 / 禁令 / 允许元素 / 核心特征 / 可用时代
        self.status_temperament = pl.status_temperament()
        self.status_forbidden = pl.status_forbidden()
        self.status_allowed = pl.status_allowed()
        self.status_features = pl.status_features()
        self.dynasties = pl.status_dynasties()

        # 风格预设
        self.style_presets = {}
        for i, (name, s) in enumerate((pl.styles() or {}).items(), 1):
            self.style_presets[str(i)] = StyleConfig(
                style_name=name,
                description=s.get("描述", ""),
                temperament_keywords=list(s.get("气质关键词") or []),
                color_preference=list(s.get("偏好颜色") or []),
                pose_style=s.get("姿势", ""),
                lighting_mood=s.get("光影", ""),
                detail_level=s.get("细节", ""),
            )
        # 风格名 → 编号（供 quick_generate 反查）
        self.style_name_to_key = {s.style_name: k for k, s in self.style_presets.items()}

        # 面部特征词池：配置键形如 "老年-男"
        self.face_features = {}
        for k, v in (pl.face_features() or {}).items():
            parts = str(k).replace("－", "-").replace("—", "-").split("-")
            if len(parts) == 2 and isinstance(v, list):
                self.face_features[(parts[0].strip(), parts[1].strip())] = v

        # 体型 → 英文（翻译阶段兜底注入用）
        self.body_en_map = pl.body_map() or {
            "矮胖": "chubby and short figure",
            "普通": "average figure",
            "瘦小": "slim and petite figure",
        }

    def select_style(self) -> StyleConfig:
        """交互式选择风格（仅1、2）"""
        print("\n" + "=" * 80)
        print("🎨 请选择生成风格:")
        print("=" * 80)

        for key, style in self.style_presets.items():
            print(f"\n【{key}】{style.style_name}")
            print(f"    {style.description}")
            print(f"    关键词示例: {', '.join(style.temperament_keywords[:5])}")

        while True:
            choice = input("\n请输入风格编号 (1-2): ").strip()

            if choice in self.style_presets:
                selected = self.style_presets[choice]
                print(f"\n✅ 已选择: {selected.style_name}")
                print(f"   {selected.description}")
                return selected
            else:
                print("❌ 无效选择，请重新输入")

    def configure_generation(self) -> Dict[str, int]:
        """配置生成数量 - 已删除皇族"""
        print("\n" + "=" * 80)
        print("📊 配置各身份类型生成数量")
        print("=" * 80)
        print("请输入每种类型的生成数量 (直接回车表示0):")
        print("-" * 80)

        all_statuses = ["贵族", "富豪", "仙人", "侠客", "魔族", "平民", "特殊"]
        counts = {}
        total = 0

        for status in all_statuses:
            while True:
                try:
                    num = input(f"  {status}: ").strip()
                    if num == "":
                        count = 0
                    else:
                        count = int(num)
                        if count < 0:
                            print("    ❌ 数量不能为负数")
                            continue
                    counts[status] = count
                    total += count
                    break
                except ValueError:
                    print("    ❌ 请输入有效数字")

        if total == 0:
            print("\n⚠️ 未指定任何类型，使用默认配置生成10个随机角色")
            return {s: 1 for s in random.sample(all_statuses, 5)}

        print(f"\n📋 生成计划:")
        for status, count in counts.items():
            if count > 0:
                print(f"   {status}: {count}个")
        print(f"   总计: {total}个角色")

        return {k: v for k, v in counts.items() if v > 0}

    def _call_ollama(self, system_prompt: str, user_prompt: str, 
                     temperature: float = 0.9, num_predict: int = 1000) -> Optional[str]:
        """调用本地Ollama API"""
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "think": False,  # 关闭 qwen3 思考模式，保证 JSON 输出干净
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                    "top_p": 0.95,
                    "top_k": 60,
                    "repeat_penalty": 1.2
                }
            }

            response = requests.post(self.chat_url, json=payload, timeout=120)

            if response.status_code == 200:
                return response.json()["message"]["content"]
            else:
                print(f"❌ API调用失败: {response.status_code}")
                return None

        except Exception as e:
            print(f"❌ API调用异常: {e}")
            return None

    def _generate_costume_with_ollama(self, config: CharacterConfig, dynasty: str) -> Dict[str, str]:
        """使用本地Qwen生成详细的服饰描述 - 融入风格要求 + 身份强差异化 + 平底无后跟鞋"""

        style = self.current_style
        if not style:
            style = self.style_presets["1"]

        main_color = random.choice(style.color_preference) if style.color_preference else (
            self.db_colors[0] if self.db_colors else "红色")
        accent_color = random.choice(self.accent_colors) if self.accent_colors else "金色"

        # 提示词工程配置（改 md 即可生效）
        g = pl.global_settings()
        expert = g.get("服饰专家人设") or "角色造型设计师"
        costume_word = g.get("服饰种类词") or "造型"
        shoe_rule = g.get("鞋履规则") or ""
        era_word = pl.epoch_word()
        hard_rules = [r for r in (g.get("硬性要求") or []) if isinstance(r, str)]

        # 核心要求：配置硬性要求 + 动态规则，统一编号
        rules = [
            f"**{era_word}多样性**：可以在{self.dynasties.get(config.status, ['通用'])}中选择",
            f"**鞋履规则（违反即废稿）**：{shoe_rule}",
        ]
        rules.extend(hard_rules)
        rules.append(f"**身份特征鲜明**：{config.status}必须有独特的视觉符号，但要符合{style.style_name}的审美")
        rules.append(
            f"**配色严格使用指定颜色（最高优先级，违反即废稿）**："
            f"主色调必须使用「{main_color}」，配色仅可使用「{accent_color}」；"
            f"严禁在服装描述中出现其他颜色词；鞋子、配饰、绣线颜色也必须使用主色或配色，"
            f"严禁出现第三种颜色；材质词不得隐含其他颜色（如\"黑麻\"\"红绸\"必须改为\"主色面料\"）；"
            f"仅金色/银色作为绣线配饰点缀允许")
        rules.append(
            f"**体型适配（必须在服饰描述中显式体现）**：角色体型为「{config.body_type}」，"
            f"必须在「服装描述」字段中明确写出体现该体型的剪裁关键词"
            f"（如瘦小→修身/紧贴/纤细轮廓；矮胖→宽松/圆润剪裁；普通→合体剪裁），不能只字不提")
        rules.append(f"**风格一致性**：所有设计元素必须符合{style.style_name}的整体审美，不能偏离")
        rules.append(f"**性别严格匹配**：{config.gender}性角色绝对不能出现异性特征（女性不能有胡须/喉结，男性不能有女性化妆容）")
        rules_text = "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1))

        # 输出字段模板：由配置的「输出字段」动态生成
        fields = pl.output_fields()
        def _fmt(desc):
            return str(desc).replace("{style}", style.style_name)
        json_tpl = "{{\n" + ",\n".join(f'    "{k}": "{_fmt(v)}"' for k, v in fields.items()) + "\n}}"

        system_prompt = f"""你是{expert}。请为角色设计符合特定风格的{costume_word}造型。

【当前风格要求】
风格名称: {style.style_name}
风格描述: {style.description}
必须体现的气质: {random.choice(self.status_temperament.get(config.status, style.temperament_keywords) or ['端庄'])}
姿势风格: {style.pose_style}
光影氛围: {style.lighting_mood}
细节要求: {style.detail_level}

【🔥 身份强差异化要求（必须严格遵守，违反即废稿）】
{config.status} 核心特征：{self.status_features.get(config.status, '无')}
{config.status} 禁令（绝对禁止）：{self.status_forbidden.get(config.status, '无')}
{config.status} 允许元素（推荐使用）：{self.status_allowed.get(config.status, '无')}

⚠️ 身份约束 > 风格约束：当风格要求与身份特征冲突时，必须以身份特征为准。
   例如：低阶身份即使采用华丽风格，也必须保持朴素面料、严禁神兽纹样和重工刺绣；
   行动型身份即使采用唯美风格，也必须保持利落剪裁、严禁宽袍大袖。

核心要求：
{rules_text}

输出格式（严格JSON）：
{json_tpl}"""

        user_prompt = f"""请为以下角色设计{style.style_name}风格的{costume_word}造型：

角色档案：
- 性别：{config.gender}
- 年龄：{config.age_group}
- 社会地位：{config.status}（核心特征，优先级高于风格）
- 推荐{era_word}：{dynasty}
- 配色方案：主色「{main_color}」+ 配色「{accent_color}」（⚠️严禁使用其他颜色，包括鞋子/配饰/绣线，违反即废稿）
- 体型特征：{config.body_type}（必须在服饰描述中体现）
- 特殊特征：{config.special_feature if config.special_feature else '无'}

身份约束（最高优先级，违反即废稿）：
- 身份禁令：{self.status_forbidden.get(config.status, '无')}
- 允许元素：{self.status_allowed.get(config.status, '无')}
- 气质必须符合身份：{config.status}应体现「{', '.join(self.status_temperament.get(config.status, []))}」，严禁出现与该身份不符的气质词
- 服饰华丽度必须匹配身份：{self.status_features.get(config.status, '符合该身份的社会定位')}

风格约束（必须严格遵守）：
- 整体气质必须: {random.choice(self.status_temperament.get(config.status, style.temperament_keywords) or ['端庄'])}
- 面部特征必须匹配性别（{config.gender}）和年龄（{config.age_group}）：老年必须体现皱纹、皮肤松弛等苍老感；少年必须体现稚气、婴儿肥等稚嫩感；男性阳刚英气，女性柔美精致。必须写明具体脸型、眼型、眉形、鼻型、唇形，每个角色五官组合必须不同
- 发型必须写明结构（位置、形状、是否有垂发、是否分编）、具体发饰名称及颜色材质，每个角色发型结构要不同
- 女性角色绝对不能出现胡须、喉结等男性特征；男性角色绝对不能出现女性化妆容
- 光影氛围要符合{style.style_name}风格但要有创意变化，不要照搬固定套路
- 细节程度: {style.detail_level}
- 鞋履要求：{shoe_rule}

请发挥创造力，但必须严格遵循身份约束 > {style.style_name}的整体审美！输出严格JSON格式。"""

        print(f"  🤖 正在生成符合【{style.style_name}】的服饰设计...")
        result = self._call_ollama(system_prompt, user_prompt, temperature=0.9, num_predict=1200)

        if result:
            try:
                cleaned = self._clean_json_response(result)
                parsed = json.loads(cleaned)
                return {
                    "朝代": parsed.get("朝代", dynasty),
                    "服装描述": parsed.get("服装描述", ""),
                    "鞋子描述": parsed.get("鞋子描述", ""),
                    "发型描述": parsed.get("发型描述", ""),
                    "面部特征": parsed.get("面部特征", ""),
                    "光影氛围": parsed.get("光影氛围", ""),
                    "特殊细节": parsed.get("特殊细节", ""),
                    "气质关键词": parsed.get("气质关键词", ",".join(self.status_temperament.get(config.status, style.temperament_keywords)[:3]))
                }
            except json.JSONDecodeError as e:
                print(f"  ⚠️ JSON解析失败，尝试文本提取: {e}")
                return self._parse_text_to_parts(result, dynasty, config)

        return self._minimal_random_costume(config, dynasty, style)

    def _clean_json_response(self, text: str) -> str:
        """清理AI返回的JSON格式"""
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return cleaned.strip()

    def _parse_text_to_parts(self, text: str, dynasty: str, config: CharacterConfig = None) -> Dict[str, str]:
        """从非JSON文本中提取信息"""
        lines = [l.strip() for l in text.split('\n') if l.strip() and not l.startswith('#')]

        style = self.current_style
        # 优先用身份专属气质词池，避免风格气质池污染身份
        if config and config.status in self.status_temperament:
            default_temperament = ",".join(self.status_temperament[config.status][:3])
        else:
            default_temperament = ",".join(style.temperament_keywords[:3]) if style else "端庄,大气"

        parts = {
            "朝代": dynasty,
            "服装描述": "",
            "鞋子描述": "",
            "发型描述": "",
            "面部特征": "",
            "光影氛围": "",
            "特殊细节": "",
            "气质关键词": default_temperament
        }

        for line in lines:
            if any(k in line for k in ["面部", "五官", "容貌", "脸"]):
                parts["面部特征"] = line.split("：", 1)[-1].strip() if "：" in line else line
            elif any(k in line for k in ["光影", "光线", "光照", "氛围"]):
                parts["光影氛围"] = line.split("：", 1)[-1].strip() if "：" in line else line
            elif any(k in line for k in ["服装", "衣服", "袍", "裙", "衫", "衣"]):
                parts["服装描述"] = line.split("：", 1)[-1].strip() if "：" in line else line
            elif any(k in line for k in ["鞋", "靴", "履"]):
                parts["鞋子描述"] = line.split("：", 1)[-1].strip() if "：" in line else line
            elif any(k in line for k in ["发", "髻", "簪", "冠", "头"]):
                parts["发型描述"] = line.split("：", 1)[-1].strip() if "：" in line else line
            elif any(k in line for k in ["细节", "特殊", "配饰", "武器"]):
                parts["特殊细节"] = line.split("：", 1)[-1].strip() if "：" in line else line
            elif any(k in line for k in ["气质", "关键词", "风格"]):
                parts["气质关键词"] = line.split("：", 1)[-1].strip() if "：" in line else line

        if not parts["服装描述"] and text:
            parts["服装描述"] = text[:150]

        return parts

    def _minimal_random_costume(self, config: CharacterConfig, dynasty: str, style: StyleConfig) -> Dict[str, str]:
        """极简随机描述 - 保留旧版华丽唯美风格"""

        if "唯美" in style.style_name:
            fabrics = ["轻纱", "雪纺", "丝绸", "薄绡", "云雾绡"]
            upper_styles = ["广袖襦裙", "对襟衫裙", "齐胸襦裙", "大袖衫", "披帛襦裙"]
        else:  # 端庄大气
            fabrics = ["云锦", "缂丝", "织金锦", "妆花缎", "提花纱"]
            upper_styles = ["交领右衽袍", "圆领袍", "对襟袄", "立领长衫", "大袖衫"]
        # 气质词优先用身份专属词池，避免风格污染身份
        temperament = random.choice(self.status_temperament.get(config.status, ["端庄", "大气"]))

        lower_styles = ["马面裙", "百褶裙", "襦裙", "裤装", "裳"]
        
        # 🔥 全部改为 平底无后跟 + 全包脚、绝对不露趾
        shoe_styles = [
            "平底云头履", "平底绣花鞋", "平底软底鞋", "平底翘头履", 
            "平底布履", "平底锦鞋", "平底僧鞋", "平底麻鞋"
        ]
        
        hair_styles = ["堕马髻", "灵蛇髻", "双丫髻", "飞天髻", "凌云髻", "高髻"]

        main_color = random.choice(style.color_preference) if style.color_preference else "红色"
        accent_color = random.choice(["金色", "银色", "白色"])

        fabric = random.choice(fabrics)
        upper = random.choice(upper_styles)
        lower = random.choice(lower_styles)
        shoe = random.choice(shoe_styles)
        hair = random.choice(hair_styles)

        costume_desc = f"{dynasty} {main_color}{fabric}{upper}，下着{lower}，{accent_color}镶边，"
        costume_desc += f"体现{config.status}身份的精致纹样"

        # 面部特征 fallback（按性别区分）
        if config.gender == "男":
            face_desc = random.choice([
                "面容俊朗，剑眉星目，鼻梁高挺，神采飞扬",
                "五官立体分明，眼神锐利有神，轮廓硬朗",
                "眉眼深邃，下颌线清晰，目光坚定明亮"
            ])
        else:
            face_desc = random.choice([
                "明眸皓齿，肌肤细腻如玉，五官精致柔和",
                "面容清丽，眼波流转，气质温婉灵动",
                "肌肤白皙透亮，眉眼精致，眼神清澈温柔"
            ])

        # 光影 fallback
        lighting_desc = random.choice([
            "明亮柔和的自然光，突出人物立体感",
            "侧光勾勒轮廓，柔和阴影增强质感",
            "均匀漫射光，细节清晰，色彩还原准确"
        ])

        return {
            "朝代": dynasty,
            "服装描述": costume_desc,
            "鞋子描述": f"{main_color}{shoe}，{accent_color}点缀，全包脚不露趾，平底无后跟",
            "发型描述": f"梳{hair}，插{accent_color}簪钗",
            "面部特征": face_desc,
            "光影氛围": lighting_desc,
            "特殊细节": f"符合{style.style_name}的{config.status}设计",
            "气质关键词": f"{temperament},{random.choice(self.status_temperament.get(config.status, ['端庄', '大气']))}"
        }

    def _generate_action(self, config: CharacterConfig) -> str:
        """生成动作描述 - 3维度随机组合（站姿×手部×神态），全部站立正面"""
        # 身份差异化的3维度选项池，4×4×4=64种组合
        action_pools = {
            "贵族": {
                "站姿": ["挺身直立", "端正伫立", "稳重大方", "挺胸直立"],
                "手部": ["双手自然垂放", "拱手而立", "执卷于胸", "双手交握身前"],
                "神态": ["仪态端庄威严", "气度高雅从容", "不苟言笑", "雍容华贵"]
            },
            "富豪": {
                "站姿": ["挺肚而立", "稳稳伫立", "挺胸直立", "端正站立"],
                "手部": ["执扇而立", "持珠而站", "双手垂放", "一手抚肚"],
                "神态": ["神态从容富贵", "满脸富态", "气定神闲", "志得意满"]
            },
            "仙人": {
                "站姿": ["轻盈伫立", "衣袂飘飘而立", "稳稳伫立", "挺身而立"],
                "手部": ["拂袖而立", "垂手伫立", "持尘而立", "双手合十"],
                "神态": ["仙气出尘", "神态超然", "空灵淡漠", "飘逸出尘"]
            },
            "侠客": {
                "站姿": ["挺身而立", "稳稳伫立", "双脚开立", "端正站立"],
                "手部": ["抱拳行礼", "一手握拳", "持剑拄地", "双手下垂"],
                "神态": ["英气逼人", "目光锐利", "沉稳内敛", "不怒自威"]
            },
            "魔族": {
                "站姿": ["挺身而立", "稳稳伫立", "双脚开立", "端正站立"],
                "手部": ["抱臂而立", "叉腰睥睨", "垂手而站", "持杖而立"],
                "神态": ["眼神冷冽", "气场压迫", "邪魅冷笑", "神秘诡谲"]
            },
            "平民": {
                "站姿": ["朴实站立", "自然伫立", "端正站立", "稳稳伫立"],
                "手部": ["垂手而立", "双手交握", "挑担直立", "持物而立"],
                "神态": ["神态平和", "朴实憨厚", "安分守己", "质朴自然"]
            }
        }

        pool = action_pools.get(config.status, action_pools["平民"])

        pose = random.choice(pool["站姿"])
        hands = random.choice(pool["手部"])
        expression = random.choice(pool["神态"])

        # 特殊特征修正（轮椅坐姿，其余站立）
        if config.special_feature == "轮椅":
            wheelchair_poses = ["端坐轮椅之上", "倚坐轮椅之中"]
            wheelchair_hands = ["双手扶轮椅扶手", "一手轻抚扶手", "双手安放膝上"]
            return f"{random.choice(wheelchair_poses)}，{random.choice(wheelchair_hands)}，{expression}"

        if config.special_feature:
            special_modifiers = {
                "独眼": "独眼目光如炬，",
                "孕妇": "一手轻抚隆起腹部，",
                "光头": "光头光洁，",
                "侏儒": "身材矮小但比例匀称，",
                "巨人": "身材高大魁梧，",
            }
            modifier = special_modifiers.get(config.special_feature, "")
            return f"{modifier}{pose}，{hands}，{expression}"

        return f"{pose}，{hands}，{expression}"

    def _build_color_theme(self, main_color: str) -> str:
        """构建配色方案 - 严格使用数据库8种颜色"""
        partner = random.choice(self.db_colors)
        # 确保主色和配色不同
        if partner == main_color:
            remaining = [c for c in self.db_colors if c != main_color]
            partner = random.choice(remaining)
        return f"{main_color} + {partner}"

    def generate_single(self, config: CharacterConfig) -> Dict:
        """生成单个角色的完整提示词"""
        self.current_id += 1

        # 生成全局唯一UUID作为名字
        char_uuid = str(uuid.uuid4()).replace('-', '')

        style_name = self.current_style.style_name if self.current_style else "默认风格"
        print(f"\n🎭 生成角色 {self.current_id}: {config.status} | {config.gender} | {config.age_group} | UUID: {char_uuid[:16]}... | 【{style_name}】")

        dynasty = random.choice(self.dynasties.get(config.status, ["明代"]))

        costume_parts = self._generate_costume_with_ollama(config, dynasty)
        actual_dynasty = costume_parts.get("朝代", dynasty)

        action = self._generate_action(config)

        style = self.current_style
        temperament = costume_parts.get("气质关键词",
                                       ",".join(self.status_temperament.get(config.status, style.temperament_keywords if style else ["端庄", "大气"])[:3]))

        # 面部特征和光影由 LLM 自由生成，fallback 按 (年龄, 性别) 双维度
        face_feature = costume_parts.get("面部特征", "")
        if not face_feature:
            face_feature = random.choice(self.face_features.get(
                (config.age_group, config.gender), ["面容端庄"]))

        lighting = costume_parts.get("光影氛围", "")
        if not lighting:
            lighting = style.lighting_mood if style else "明亮自然光"

        detail = style.detail_level if style else "8k超高清，服饰纹理清晰可见"

        # 提取服装主颜色（从配色方案中）
        color_str = config.color_theme or "白色"
        main_clothing_color = color_str.split(" + ")[0] if " + " in color_str else color_str

        # 体型关键词映射：显式注入到人物描述开头，确保 LLM 即使不写也能体现
        body_type_map = {
            "矮胖": ("身材矮胖圆润", "chubby and short figure"),
            "普通": ("身材匀称", "average figure"),
            "瘦小": ("身材瘦小纤细", "slim and petite figure"),
        }
        body_cn, body_en = body_type_map.get(config.body_type, ("身材匀称", "average figure"))

        # 体型兜底校验：检测服饰描述里是否有体现体型的关键词，没有则强制追加
        costume_desc_for_check = costume_parts.get('服装描述', '')
        body_keywords_in_costume = ['瘦小', '纤细', '修长', '矮胖', '圆润', '匀称', '修身', '紧贴', '宽松']
        has_body_desc = any(kw in costume_desc_for_check for kw in body_keywords_in_costume)
        if not has_body_desc:
            # 没有体型词，强制在服饰描述末尾追加体型剪裁描述
            body_tail_map = {
                "矮胖": "剪裁宽松以遮盖矮胖体型",
                "普通": "剪裁合体体现匀称身材",
                "瘦小": "剪裁修身凸显纤细瘦小体型",
            }
            body_tail = body_tail_map.get(config.body_type, "")
            if body_tail:
                costume_parts['服装描述'] = f"{costume_desc_for_check.rstrip('，。')}，{body_tail}"

        # 🔥 优化：纯白背景、全身图前置，放在提示词最开头；体型关键词显式注入到人物描述
        chinese_prompt = (
            f"纯白色背景，全身图，{body_cn}，{temperament}的{config.age_group}{config.gender}{config.status}"
            f"{'（' + config.special_feature + '）' if config.special_feature else ''}，"
            f"{face_feature}，"
            f"身着{actual_dynasty}服饰：{costume_parts['服装描述']}，"
            f"{costume_parts['发型描述']}，"
            f"{costume_parts['鞋子描述']}，"
            f"{costume_parts.get('特殊细节', '')}，"
            f"{action}，"
            f"{lighting}，{detail}，8k超高清，服饰纹理清晰可见， masterpiece, best quality"
        )

        # 颜色严格校验：①清洗 LLM 自加的"主色调为XX" ②剔除所有非主色非配色的颜色词 ③确保主色存在
        # 数据库 8 种颜色 + 常见材质隐含色（需一并清洗，如"黑麻"含"黑"）
        costume_desc_raw = costume_parts.get('服装描述', '')
        special_detail_raw = costume_parts.get('特殊细节', '')
        shoe_desc_raw = costume_parts.get('鞋子描述', '')

        # 从 color_theme 提取允许的颜色集合（主色 + 配色）
        allowed_colors = set()
        if config.color_theme:
            for part in config.color_theme.split("+"):
                part = part.strip()
                if part:
                    allowed_colors.add(part)
        if main_clothing_color:
            allowed_colors.add(main_clothing_color)
        # 金色/银色作为绣线/配饰配色允许保留（不算服装主色冲突）
        allowed_colors.update(["金色", "银色"])
        # 白色背景允许
        allowed_colors.add("白色")

        # 所有需要检测的"颜色词"（含材质隐含色，如"黑麻"→"黑"）
        all_color_words = ["白色", "粉色", "黑色", "紫色", "藏青色", "绿色", "红色", "蓝色",
                           "红", "蓝", "绿", "黄", "紫", "黑", "白", "粉"]

        def _clean_conflicting_colors(text: str) -> str:
            """剔除 text 中所有非 allowed 的颜色词（含材质隐含色）"""
            if not text:
                return text
            cleaned = text
            # 先清理"主色调为XX"字样（不管颜色对不对，统一由后续逻辑追加）
            cleaned = re.sub(r'主色调为[^，。；,;]+，?', '', cleaned).strip()
            # 剔除冲突颜色词：长词先剔（避免"藏青色"被"青"误伤，"白色"被"白"误伤后只剩"色"）
            # 按长度降序处理
            sorted_colors = sorted(all_color_words, key=len, reverse=True)
            for cw in sorted_colors:
                if cw in cleaned and cw not in allowed_colors:
                    # 直接替换为空（保留前后文连贯）
                    cleaned = cleaned.replace(cw, "")
            # 清理可能产生的多余标点和空格
            cleaned = re.sub(r'[，。；,;]\s*[，。；,;]+', '，', cleaned)
            cleaned = re.sub(r'^[，。；,;]\s*', '', cleaned)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            cleaned = cleaned.rstrip('，。；,;')
            return cleaned

        if main_clothing_color:
            # 清洗三个字段
            cleaned_desc = _clean_conflicting_colors(costume_desc_raw)
            cleaned_special = _clean_conflicting_colors(special_detail_raw)
            cleaned_shoe = _clean_conflicting_colors(shoe_desc_raw)

            # 确保主色存在（若清洗后主色没了，强制追加）
            if main_clothing_color not in cleaned_desc:
                cleaned_desc = f"主色调为{main_clothing_color}，{cleaned_desc}"

            # 同步更新 costume_parts
            costume_parts['服装描述'] = cleaned_desc
            if cleaned_special:
                costume_parts['特殊细节'] = cleaned_special
            if cleaned_shoe:
                costume_parts['鞋子描述'] = cleaned_shoe

            # 重建中文提示词中的服装部分（保留体型关键词）
            chinese_prompt = (
                f"纯白色背景，全身图，{body_cn}，{temperament}的{config.age_group}{config.gender}{config.status}"
                f"{'（' + config.special_feature + '）' if config.special_feature else ''}，"
                f"{face_feature}，"
                f"身着{actual_dynasty}服饰：{cleaned_desc}，"
                f"{costume_parts['发型描述']}，"
                f"{costume_parts['鞋子描述']}，"
                f"{costume_parts.get('特殊细节', '')}，"
                f"{action}，"
                f"{lighting}，{detail}，8k超高清，服饰纹理清晰可见， masterpiece, best quality"
            )

        # 英文提示词也前置纯白背景和全身图
        english_prompt = self._generate_english_with_ollama(
            config, actual_dynasty, costume_parts, action, temperament, face_feature, char_uuid
        )

        return {
            "序号": self.current_id,
            "名字": char_uuid,
            "性别": config.gender,
            "年龄": config.age_group,
            "体型": config.body_type,
            "地位": config.status,
            "服装颜色": main_clothing_color,
            "特殊": config.special_feature or "",
            "朝代风格": actual_dynasty,
            "整体风格": style_name,
            "完整中文描述词": chinese_prompt,
            "完整英文描述词": english_prompt
        }

    def _generate_english_with_ollama(self, config: CharacterConfig, dynasty: str, 
                                     costume_parts: Dict, action: str, temperament: str, face_feature: str = "", char_uuid: str = "") -> str:
        """翻译为英文提示词 - 纯白背景、全身图前置"""
        style = self.current_style
        g = pl.global_settings()
        costume_word = g.get("服饰种类词") or "造型"
        bg_prefix = (g.get("背景与构图") or "pure white background, full body shot, front view, standing pose").strip()
        quality_suffix = (g.get("质量词") or "masterpiece, best quality, 8k ultra detailed").strip()
        shoe_rule = g.get("鞋履规则") or ""
        style_desc = style.description if style else (g.get("世界观") or "")
        body_en_hint = "；".join(f"{k}→{v}" for k, v in self.body_en_map.items())

        system_prompt = f"""你是一位专业的AI绘画提示词翻译专家。

当前风格: {style.style_name if style else '默认风格'}
风格要求: {style_desc}

请将中文{costume_word}描述翻译成高质量的英文Stable Diffusion/Midjourney提示词。
必须保留身份气质特征：{self.status_temperament.get(config.status, ['dignified', 'elegant'])}。
身份禁令：{self.status_forbidden.get(config.status, '无')}（英文翻译中也要严格规避这些元素）。

强制要求：
1. 开头必须包含 "{bg_prefix}"
2. 使用准确的英文{costume_word}术语
3. 鞋履要求：{shoe_rule}
4. 性别严格匹配：{config.gender}性角色不能出现异性特征（女性不能有beard/facial hair，男性不能有女性化妆容）
5. 颜色严格匹配中文原文中的颜色，不要自行更改
6. 结尾加上：{quality_suffix}
7. 只输出英文tags，用逗号分隔
8. 【发型绝对禁止拼音】中文专有名称必须翻译成描述性英文结构，绝不能直接写拼音。必须说明发型位置(top/sides/back of head/low bun)、形状(round/looped/spiral/flat/tall)、是否有垂发(loose strands at temples/shoulders)、具体发饰(hairpins with gemstones/gold filigree/pearl tassels/white jade pins)
9. 【面部必须加具体五官英文术语】除翻译原文形容词外，必须显式写出具体的面部特征英文术语：脸型(oval face/round face/square face/heart-shaped face/long face/goose-egg face)、眼型(phoenix eyes/almond eyes/peach blossom eyes/round eyes/slender willow-leaf eyes)、眉形(willow-leaf eyebrows/sword eyebrows/straight eyebrows/arched eyebrows/distant-mountain eyebrows)、鼻型(straight delicate nose/small upturned nose/high-bridged nose)、唇型(thin lips/full lips/cherry-like small lips)。每个角色的这些组合要不同，避免所有角色都是同样的handsome/beautiful模糊词"""

        lighting = costume_parts.get("光影氛围", "")

        chinese_text = (
            f"{temperament}的{config.age_group}{config.gender}{config.status}，"
            f"{face_feature}，"
            f"身着{dynasty}{costume_word}：{costume_parts['服装描述']}，"
            f"{costume_parts['发型描述']}，"
            f"{costume_parts['鞋子描述']}，"
            f"{costume_parts.get('特殊细节', '')}，"
            f"{action}，"
            f"{lighting}"
        )

        user_prompt = f"""将以下中文提示词翻译成英文（保留{style.style_name if style else '传统'}风格）：

{chinese_text}

要求：
1. 开头必须是：{bg_prefix},
2. 使用准确的英文{costume_word}术语
3. 保留所有细节和风格特征
4. 鞋履要求：{shoe_rule}
5. 结尾加上：{quality_suffix}
6. 只输出英文tags，用逗号分隔
7. ⚠️发型严禁写拼音！必须译成位置+形状+结构的英文描述（如 two looped buns on both sides / tall bun at crown / low slanted bun with loose strands），并说明具体发饰材质颜色（gold filigree hairpins / pearl tassels / white jade pins）
8. ⚠️面部必须显式写出具体英文五官术语：脸型(oval/round/square/heart-shaped/long)、眼型(phoenix eyes/almond eyes/peach blossom eyes/round eyes/slender eyes)、眉形(willow-leaf/sword/straight/arched/distant-mountain eyebrows)、鼻型(straight delicate/small/high-bridged nose)、唇型(thin/full/cherry-like lips)。不要只写 vague 的 handsome/beautiful
9. ⚠️体型必须显式翻译：{body_en_hint}。体型词必须紧跟在角色描述开头，不能省略"""

        print(f"  🌐 翻译为英文...")
        result = self._call_ollama(system_prompt, user_prompt, temperature=0.4, num_predict=800)

        if result:
            cleaned = result.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json") or cleaned.startswith("plaintext"):
                    cleaned = cleaned[4:].strip()
            # 体型兜底校验：检测英文结果是否包含体型关键词，没有则强制注入
            body_en_target = self.body_en_map.get(config.body_type, "")
            if body_en_target:
                body_en_keywords = ["chubby", "short figure", "average figure",
                                    "slim", "petite", "slender"]
                if not any(kw in cleaned.lower() for kw in body_en_keywords):
                    # 在配置的「背景与构图」之后注入体型词
                    prefix = bg_prefix + ","
                    if prefix in cleaned:
                        cleaned = cleaned.replace(
                            prefix, f"{prefix} {body_en_target},", 1)
                    else:
                        cleaned = f"{prefix} {body_en_target}, {cleaned}"
            return cleaned

        # Fallback: 确保背景与构图前置 + 体型词
        body_en_fallback = self.body_en_map.get(config.body_type, "average figure")
        world = pl.global_settings().get("世界观") or ""
        return (
            f"{bg_prefix}, "
            f"{body_en_fallback}, "
            f"{world} {config.status}, {config.gender}, {config.age_group}, "
            f"{style.style_name if style else 'default'} style, "
            f"{quality_suffix}"
        )

    def generate_batch_interactive(self):
        """交互式批量生成主流程"""
        self.current_style = self.select_style()
        status_counts = self.configure_generation()

        print("\n" + "=" * 80)
        print(f"🚀 开始生成角色 - 风格: {self.current_style.style_name}")
        print("=" * 80)

        results = []
        total = sum(status_counts.values())
        current = 0

        for status, count in status_counts.items():
            for _ in range(count):
                current += 1

                gender = random.choice(["男", "女"])
                age = random.choice(["青年", "老年", "少年"])
                body = random.choice(["普通", "瘦小", "矮胖"])

                if self.current_style and self.current_style.color_preference:
                    main_color = random.choice(self.current_style.color_preference)
                else:
                    main_color = random.choice(list(self.color_map.values()))
                color_theme = self._build_color_theme(main_color)

                special = None
                if random.random() < 0.2:
                    special = random.choice(list(self.special_map.values()))

                config = CharacterConfig(
                    gender=gender,
                    age_group=age,
                    status=status,
                    body_type=body,
                    color_theme=color_theme,
                    special_feature=special
                )

                result = self.generate_single(config)
                results.append(result)

                if current % 3 == 0 and current < total:
                    print(f"\n⏳ 进度 {current}/{total}，暂停2秒...")
                    time.sleep(2)

        self._save_and_summary(results)
        return results

    def _save_and_summary(self, results: List[Dict]):
        """输出打标格式JSON：名字(UUID), 性别, 年龄, 体型, 地位, 服装颜色, 特殊, 朝代, 提示词"""
        output_dir = self.output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        filename = f"generated_prompts_{self.current_style.style_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        full_path = os.path.join(output_dir, filename)

        # 严格打标标准输出 - 包含所有数据库字段
        sheet1_list = []
        for item in results:
            sheet1_item = {
                "名字": item["名字"],
                "性别": item["性别"],
                "年龄": item["年龄"],
                "体型": item["体型"],
                "地位": item["地位"],
                "服装颜色": item["服装颜色"],
                "特殊": item["特殊"],
                "朝代": item["朝代风格"],
                "完整中文描述词": item["完整中文描述词"],
                "完整英文描述词": item["完整英文描述词"]
            }
            sheet1_list.append(sheet1_item)

        output_data = {
            "Sheet1": sheet1_list
        }

        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        self.last_save_path = full_path  # 供 agent 读取

        print("\n" + "=" * 80)
        print("✅ 生成完成！【数据库打标格式 + 纯白背景前置】")
        print("=" * 80)
        print(f"📁 已保存到: {full_path}")
        print(f"📊 总计生成: {len(results)}个角色")
        print(f"🎨 风格: {self.current_style.style_name if self.current_style else '默认'}")
        print("💡 提示：打标 Excel 与入库 SQL 改为在前端「画廊」页筛选所需角色后按需导出")

        status_count = Counter([r['地位'] for r in results])
        print("\n📋 各类型统计:")
        for status, count in status_count.items():
            print(f"   {status}: {count}个")

        # 统计颜色使用情况
        color_count = Counter([r['服装颜色'] for r in results])
        print("\n🎨 服装颜色统计:")
        for color, count in color_count.items():
            print(f"   {color}: {count}个")

        print("\n📝 生成示例预览:")
        for i, r in enumerate(results[:3], 1):
            print(f"\n【角色{i}】{r['名字'][:16]}... | {r['地位']} | {r['性别']} | {r['年龄']} | {r['服装颜色']}")
            print(f"   中文: {r['完整中文描述词'][:100]}...")

    def quick_generate(self, style_key: str, status_counts: Dict[str, int],
                       specials: Dict[str, int] = None,
                       gender: str = None, age: str = None,
                       color: str = None, body_type: str = None):
        """快速生成模式
        Args:
            style_key: 风格编号 "1" 或 "2"
            status_counts: 各地位生成数量，如 {"贵族": 2, "平民": 1}
            specials: 特殊特征生成数量，如 {"轮椅": 1}，生成的角色会随机搭配一个合法地位
            gender: 指定性别 "男"/"女"（可选，不指定则随机）
            age: 指定年龄组 "青年"/"老年"/"少年"（可选，不指定则随机）
            color: 指定服装主色（可选，不指定则随机）
            body_type: 指定体型 "普通"/"瘦小"/"矮胖"（可选，不指定则随机）
        """
        specials = specials or {}
        # 每次生成前重新加载：改完 md 无需重启服务
        self._load_prompt_guide()
        if not self.style_presets:
            self.style_presets["1"] = StyleConfig(
                style_name="默认风格",
                description="未在提示词工程配置中定义风格",
                temperament_keywords=["端庄"],
                color_preference=self.db_colors or ["红色"],
                pose_style="正面站立",
                lighting_mood="自然光",
                detail_level="高",
            )
            self.style_name_to_key["默认风格"] = "1"
        if style_key in self.style_presets:
            self.current_style = self.style_presets[style_key]
        elif style_key in self.style_name_to_key:
            self.current_style = self.style_presets[self.style_name_to_key[style_key]]
        else:
            self.current_style = self.style_presets[sorted(self.style_presets.keys())[0]]

        # 属性选择器：指定则用指定值，不指定则随机
        def _pick_gender():
            return gender if gender in ("男", "女") else random.choice(["男", "女"])
        def _pick_age():
            return age if age in ("青年", "老年", "少年") else random.choice(["青年", "老年", "少年"])
        def _pick_body():
            return body_type if body_type in ("普通", "瘦小", "矮胖") else random.choice(["普通", "瘦小", "矮胖"])
        def _pick_color():
            if color and color in self.db_colors:
                return color
            if self.current_style.color_preference:
                return random.choice(self.current_style.color_preference)
            return random.choice(list(self.color_map.values()))

        results = []

        # 1. 生成普通角色
        for status, count in status_counts.items():
            for _ in range(count):
                g = _pick_gender()
                a = _pick_age()
                b = _pick_body()
                main_color = _pick_color()
                color_theme = self._build_color_theme(main_color)

                config_obj = CharacterConfig(
                    gender=g,
                    age_group=a,
                    status=status,
                    body_type=b,
                    color_theme=color_theme,
                    special_feature=None
                )

                result = self.generate_single(config_obj)
                results.append(result)

        # 2. 生成特殊角色（随机搭配一个合法地位）
        valid_statuses = list(self.status_map.values())
        for special_feature, count in specials.items():
            for _ in range(count):
                g = _pick_gender()
                a = _pick_age()
                b = _pick_body()
                status = random.choice(valid_statuses)
                main_color = _pick_color()
                color_theme = self._build_color_theme(main_color)

                config_obj = CharacterConfig(
                    gender=g,
                    age_group=a,
                    status=status,
                    body_type=b,
                    color_theme=color_theme,
                    special_feature=special_feature
                )

                result = self.generate_single(config_obj)
                results.append(result)

        self._save_and_summary(results)
        return results


def main():
    print("=" * 80)
    print("🎨  Ollama Qwen 古装提示词生成器【华丽唯美版+规范格式】")
    print("=" * 80)
    engine = OllamaQwenEngine(
        base_url="http://localhost:11434",
        model="qwen2.5:7b"
    )
    engine.generate_batch_interactive()


if __name__ == "__main__":
    main()