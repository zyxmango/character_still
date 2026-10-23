# -*- coding: utf-8 -*-
"""
打标导出工具：从生成的 prompts JSON 文件一键导出
1. Excel 打标文件（可直接喂给 sqlGen.py）
2. SQL INSERT 文件（直接入库，无需 sqlGen.py 中转）

用法：
    # 导出最新生成的提示词文件
    python export_to_db.py

    # 导出指定 JSON 文件
    python export_to_db.py --file d:/character_agent/output/prompts/generated_prompts_xxx.json

    # 导出到指定输出目录
    python export_to_db.py --outdir C:/Users/admin/Downloads
"""
import json
import argparse
import os
from pathlib import Path
from datetime import datetime

import pandas as pd

import config

# ===== 查找最新 prompts JSON =====
def find_latest_prompts_json() -> Path:
    d = config.PROMPTS_DIR
    if not d.exists():
        raise FileNotFoundError(f"找不到 prompts 目录: {d}")
    files = sorted(d.glob("generated_prompts_*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"目录 {d} 下没有 generated_prompts_*.json 文件")
    return files[0]


# ===== 读取角色列表 =====
def load_characters(json_path: Path) -> list:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # JSON 格式是 {"Sheet1": [...]} 或直接列表
    if isinstance(data, list):
        return data
    for key in ("Sheet1", "characters", "data"):
        if isinstance(data, dict) and key in data and isinstance(data[key], list):
            return data[key]
    raise ValueError(f"无法解析 JSON，预期 Sheet1/characters/data 键或直接数组: {json_path}")


# ===== 打标 Excel 列（严格匹配 sqlGen.py 期望的列名）=====
LABEL_COLUMNS = [
    "名字",
    "性别",
    "年龄",
    "体型",
    "地位",
    "服装颜色",
    "特殊",
]

# 数据库字典表允许值集合（用于校验）
# 固定维度直接写死；身份/颜色/特殊特征改为从「提示词工程配置」md 读取，
# 这样新增的身份与颜色也能通过校验。
_FIXED_VALID_VALUES = {
    "性别": {"男", "女"},
    "年龄": {"老年", "青年", "少年"},
    "体型": {"矮胖", "普通", "瘦小"},
}

# 内置回退值（md 缺失时使用）
_DEFAULT_DYNAMIC_VALUES = {
    "地位": {"贵族", "富豪", "仙人", "侠客", "魔族", "平民", "特殊"},
    "服装颜色": {"白色", "粉色", "黑色", "紫色", "藏青色", "绿色", "红色", "蓝色"},
    "特殊": {"", "轮椅", "独眼", "孕妇", "光头", "侏儒", "巨人"},
}


def valid_values() -> dict:
    """合并固定维度与配置维度，每次调用都取最新配置"""
    merged = {k: set(v) for k, v in _FIXED_VALID_VALUES.items()}
    dynamic = {k: set(v) for k, v in _DEFAULT_DYNAMIC_VALUES.items()}
    try:
        import prompt_loader
        statuses = prompt_loader.statuses()
        colors = prompt_loader.colors()
        specials = prompt_loader.specials()
        if statuses:
            dynamic["地位"] = set(statuses) | {"特殊"}
        if colors:
            dynamic["服装颜色"] = set(colors)
        if specials:
            dynamic["特殊"] = set(specials) | {""}
    except Exception:
        pass
    merged.update(dynamic)
    return merged


def validate_character(ch: dict) -> list:
    """校验字段合法性，返回错误列表"""
    errors = []
    for col, valid_set in valid_values().items():
        val = str(ch.get(col, "")).strip()
        # 特殊：空字符串合法
        if col == "特殊" and val == "":
            continue
        if val not in valid_set:
            errors.append(f"[{ch.get('名字', '?')}] {col}='{val}' 不在允许集合 {valid_set} 中")
    return errors


def export_excel(characters: list, outdir: Path, style_name: str) -> Path:
    """导出打标 Excel，返回输出文件路径"""
    rows = []
    all_errors = []
    for ch in characters:
        row = {col: str(ch.get(col, "")).strip() for col in LABEL_COLUMNS}
        rows.append(row)
        all_errors.extend(validate_character(ch))

    df = pd.DataFrame(rows, columns=LABEL_COLUMNS)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_style = style_name.replace(" ", "_")
    out_path = outdir / f"{safe_style}_角色信息表_名字列_AI打标_{ts}.xlsx"
    df.to_excel(out_path, index=False, sheet_name="Sheet1")

    if all_errors:
        print(f"⚠️  字段校验警告（共 {len(all_errors)} 条）：")
        for err in all_errors[:10]:
            print(f"   - {err}")
        if len(all_errors) > 10:
            print(f"   ... 省略 {len(all_errors) - 10} 条")

    print(f"✅ Excel 打标文件已保存: {out_path}（{len(rows)} 行）")
    return out_path


# ===== 直接生成 SQL（替代 sqlGen.py 中转）=====
LOOKUP_TABLES = {
    "性别": "gender",
    "年龄": "age",
    "体型": "body_type",
    "地位": "status",
    "服装颜色": "clothing_color",
    "特殊": "special",
}

# Excel 列名 -> person 表外键字段
PERSON_FK_COLUMNS = {
    "性别": "gender_id",
    "年龄": "age_id",
    "体型": "body_type_id",
    "地位": "status_id",
    "服装颜色": "clothing_color_id",
    "特殊": "special_id",
}


def _escape_sql(s: str) -> str:
    return str(s).replace("'", "''").replace("\\", "\\\\")


def gen_person_insert(row: dict) -> str:
    """生成单条 person 表 INSERT，使用子查询关联字典表"""
    name = _escape_sql(row["名字"])
    image_path = f"character/{name}.png"

    # 构造字段值：字典表走子查询
    values = [f"'{image_path}'"]
    for col in ["性别", "年龄", "体型", "地位", "服装颜色", "特殊"]:
        val = row[col]
        if val == "" or val is None:
            values.append("NULL")
        else:
            tbl = LOOKUP_TABLES[col]
            values.append(f"(SELECT id FROM {tbl} WHERE name='{_escape_sql(val)}')")

    fk_cols = ["image_path"] + [PERSON_FK_COLUMNS[c] for c in ["性别", "年龄", "体型", "地位", "服装颜色", "特殊"]]
    return (
        "INSERT INTO person (" + ", ".join(fk_cols) + ")\n"
        "SELECT " + ", ".join(values) + ";"
    )


def gen_lookup_upserts() -> str:
    """生成字典表（gender/age/body_type/status/clothing_color/special）的 UPSERT 语句。
    确保字典表中有所有可能值，即使之前不存在也能插入占位。
    """
    lookup_values = {
        "gender": ["男", "女"],
        "age": ["老年", "青年", "少年"],
        "body_type": ["矮胖", "普通", "瘦小"],
        "status": ["贵族", "富豪", "仙人", "侠客", "魔族", "平民"],
        "clothing_color": ["白色", "粉色", "黑色", "紫色", "藏青色", "绿色", "红色", "蓝色"],
        "special": ["轮椅", "独眼", "孕妇", "光头", "侏儒", "巨人"],
    }

    lines = [
        "-- ===========================================",
        "-- 字典表占位 UPSERT（如不存在则插入，方便后续使用）",
        "-- MySQL 语法：INSERT ... ON DUPLICATE KEY UPDATE",
        "-- ===========================================",
        "",
    ]
    for tbl, names in lookup_values.items():
        lines.append(f"-- 表 {tbl}")
        for n in names:
            escaped = n.replace("'", "''")
            lines.append(
                f"INSERT INTO {tbl} (name) VALUES ('{escaped}') "
                f"ON DUPLICATE KEY UPDATE name=name;"
            )
        lines.append("")
    return "\n".join(lines)


def export_sql(characters: list, outdir: Path, style_name: str) -> Path:
    """导出 SQL INSERT 文件，返回输出文件路径"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_style = style_name.replace(" ", "_")
    out_path = outdir / f"insert_{safe_style}_{ts}.sql"

    header = [
        "-- ===========================================",
        f"-- 古装人物剧照批量入库 SQL",
        f"-- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"-- 角色数量：{len(characters)}",
        f"-- 风格：{style_name}",
        "-- 数据库：MySQL（兼容大部分关系型数据库，语法微调即可）",
        "-- 说明：",
        "--   1. 先执行字典表 UPSERT（确保字典值存在）",
        "--   2. 再执行 person 表 INSERT（子查询关联字典表 id）",
        "--   3. 若字典表表名不同，请修改 LOOKUP_TABLES 映射",
        "-- ===========================================",
        "",
    ]

    lookup_sql = gen_lookup_upserts()

    person_section = [
        "",
        "-- ===========================================",
        "-- person 表 INSERT",
        "-- ===========================================",
        "",
    ]
    for ch in characters:
        row = {col: str(ch.get(col, "")).strip() for col in LABEL_COLUMNS}
        person_section.append(gen_person_insert(row))
        person_section.append("")

    content = "\n".join(header) + lookup_sql + "\n".join(person_section)
    out_path.write_text(content, encoding="utf-8")
    print(f"✅ SQL 入库文件已保存: {out_path}（{len(characters)} 条 INSERT）")
    return out_path


# ===== 主流程 =====
def main():
    parser = argparse.ArgumentParser(description="导出 prompts JSON -> 打标 Excel + SQL")
    parser.add_argument("--file", type=str, default=None, help="prompts JSON 文件路径（留空=最新生成的）")
    parser.add_argument("--outdir", type=str, default=None,
                        help=f"输出目录（留空={config.OUTPUT_DIR / 'export'}）")
    args = parser.parse_args()

    # 1. 找到 JSON 文件
    if args.file:
        json_path = Path(args.file)
        if not json_path.exists():
            raise FileNotFoundError(f"找不到文件: {json_path}")
    else:
        json_path = find_latest_prompts_json()
    print(f"📄 数据源：{json_path}")

    # 2. 解析角色
    characters = load_characters(json_path)
    if not characters:
        print("⚠️  JSON 中没有角色数据，结束")
        return
    print(f"🎭 加载角色：{len(characters)} 个")

    # 3. 从 JSON 文件名中提取风格名
    style_name = "未命名"
    m = json_path.name
    if "generated_prompts_" in m:
        tail = m.replace("generated_prompts_", "")
        # tail 格式可能是：端庄大气传统型_20260803_091432.json
        parts = tail.split("_")
        if parts:
            # 去掉最后两段（日期+时间），剩下的拼回风格名
            style_name = "_".join(parts[:-2]) if len(parts) >= 3 else parts[0]
    print(f"🎨 风格：{style_name}")

    # 4. 输出目录
    outdir = Path(args.outdir) if args.outdir else (config.OUTPUT_DIR / "export")
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"📁 输出目录：{outdir}")
    print()

    # 5. 导出
    excel_path = export_excel(characters, outdir, style_name)
    sql_path = export_sql(characters, outdir, style_name)
    print()
    print("=" * 60)
    print("📦 导出完成！")
    print(f"   Excel：{excel_path} → 可用现有 sqlGen.py 生成入库 SQL")
    print(f"   SQL  ：{sql_path}   → 直接在数据库执行即可入库")
    print("=" * 60)


if __name__ == "__main__":
    main()
