#!/usr/bin/env python3
"""定时发现的新赛事：去重 + 入库本地 + 生成周报。

工作流（由 WorkBuddy 自动化任务驱动）：
  1. 自动化任务用 WebSearch 发现新比赛，写入 data/ground_truth/incoming/*.json
     （字段同 samples，trusted_level=C, data_status=unverified，禁止编造日期/链接）。
  2. 本脚本：去重 -> 移入 samples/ -> 重灌本地库 -> 生成周报。

"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import db  # noqa: E402
import schemas  # noqa: E402

INCOMING_DIR = ROOT / "data" / "ground_truth" / "incoming"
SAMPLES_DIR = ROOT / "data" / "ground_truth" / "samples"
DIGEST_DIR = ROOT / "data"


def slugify(text: str) -> str:
    text = re.sub(r"[\s\u3000]+", "_", text.strip())
    text = re.sub(r"[^\w一-鿿-]", "", text)  # 保留字母/数字/下划线/中日韩
    return text or "comp"


def norm_key(name: str, year: int) -> str:
    return (re.sub(r"[\s\u3000]+", "", name) + str(year)).lower()


def coerce_category(value) -> str:
    allowed = {c.value for c in schemas.CompetitionCategory}
    if value in allowed:
        return value
    v = str(value or "").lower()
    mapping = {
        "计算机": "programming", "程序": "programming", "软件": "software",
        "数学建模": "modeling", "建模": "modeling", "数学": "math",
        "创业": "innovation", "创新": "innovation", "商业": "business",
        "英语": "english", "外语": "english", "电子": "electronics",
        "机器人": "robotics_ai", "人工智能": "robotics_ai", "ai": "robotics_ai",
        "数据": "data", "大数据": "data", "设计": "design",
        "机械": "engineering", "工程": "engineering", "生命": "life_science",
        "医学": "life_science", "医药": "life_science", "物理": "physics",
        "化学": "chem_env", "环境": "chem_env", "能源": "chem_env",
    }
    for k, val in mapping.items():
        if k in v:
            return val
    return "innovation"  # 兜底类别


def coerce_edu(values) -> list[str]:
    allowed = {e.value for e in schemas.EducationLevel}
    out: list[str] = []
    for v in (values or []):
        if v in allowed:
            out.append(v)
            continue
        s = str(v)
        if "研究" in s:
            out.append("研究生")
        elif "本科" in s:
            out.append("本科生")
        elif "专科" in s:
            out.append("专科生")
        elif "高职" in s:
            out.append("高职高专生")
        elif "职业本科" in s:
            out.append("职业本科生")
        elif "毕业" in s:
            out.append("毕业生（毕业5年内）")
        elif "中职" in s:
            out.append("中职生")
    seen, res = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            res.append(v)
    # 未识别的学历保持未知；空列表会让记录停留在候选区，禁止静默按本科生处理。
    return res


def build_competition(raw: dict, existing_ids: set) -> tuple[dict, str]:
    """把 incoming 的原始记录规整为可入库结构，返回 (record, competition_id)。"""
    year = int(raw.get("document_year") or date.today().year)
    name = raw.get("competition_name") or "未命名赛事"
    cid = raw.get("competition_id") or f"{slugify(name)}_{year}"
    base, i = cid, 1
    while cid in existing_ids:
        cid = f"{base}_{i}"
        i += 1
    url = raw.get("official_source_url") or None
    rec = {
        "competition_id": cid,
        "competition_name": name,
        "document_year": year,
        "category": coerce_category(raw.get("category")),
        "organizer": raw.get("organizer"),
        "eligible_students": coerce_edu(raw.get("eligible_students")),
        "allowed_grades": raw.get("allowed_grades"),
        "allowed_majors": raw.get("allowed_majors"),
        "team_required": bool(raw.get("team_required", False)),
        "team_min": raw.get("team_min"),
        "team_max": raw.get("team_max"),
        "registration_deadline": raw.get("registration_deadline"),
        "submission_deadline": raw.get("submission_deadline"),
        "result_announcement_date": raw.get("result_announcement_date"),
        "competition_start_date": raw.get("competition_start_date"),
        "competition_end_date": raw.get("competition_end_date"),
        "award_settings": raw.get("award_settings"),
        "award_distribution": raw.get("award_distribution") or [],
        "brief_description": raw.get("brief_description"),
        "required_materials": raw.get("required_materials") or [],
        "evaluation_dimensions": raw.get("evaluation_dimensions") or [],
        "required_skills": raw.get("required_skills") or [],
        "official_source_url": url,
        "source_acquired_date": raw.get("source_acquired_date") or date.today().isoformat(),
        "trusted_level": "C",
        "data_status": "unverified",
        "last_verified_at": None,
        "official_source_status": "found" if url else None,
        "notes": raw.get("notes") or f"自动发现于 {date.today().isoformat()}，关键证据待补充。",
        "evidence": [],
        "doc_version": raw.get("doc_version") or f"{year}_v1",
    }
    return rec, cid


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只报告将要做的操作，不写库/不推送")
    args = ap.parse_args()

    if not INCOMING_DIR.exists():
        print(f"[ingest] 无 incoming 目录：{INCOMING_DIR}")
        return
    incoming_files = sorted(INCOMING_DIR.glob("*.json"))
    if not incoming_files:
        print("[ingest] incoming 为空，无需处理。")
        return

    # 现有「名称+年份」键集合（用于去重），以及已占用 id
    existing_keys: set[str] = set()
    for f in SAMPLES_DIR.glob("*.json"):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if raw.get("competition_name") and raw.get("document_year"):
            existing_keys.add(norm_key(raw["competition_name"], int(raw["document_year"])))
    existing_ids = {c.competition_id for c in db.get_all_competitions()}

    added: list[tuple[str, dict, Path]] = []
    skipped_dup: list[str] = []
    for f in incoming_files:
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[ingest] 跳过无法解析的文件 {f.name}: {e}")
            continue
        rec, cid = build_competition(raw, existing_ids)
        key = norm_key(rec["competition_name"], rec["document_year"])
        if key in existing_keys:
            skipped_dup.append(rec["competition_name"])
            continue  # 不移动文件，便于后续人工处理
        added.append((cid, rec, f))
        existing_keys.add(key)
        existing_ids.add(cid)

    # 本地入库：移入 samples + 重灌
    for cid, rec, f in added:
        if not args.dry_run:
            out = SAMPLES_DIR / f"{cid}.json"
            out.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            f.unlink()  # 移走 incoming 原文件，避免重复处理
    if added and not args.dry_run:
        n = db.seed_all()
        print(f"[ingest] 本地重灌完成，当前赛事总数：{n}")

    # 周报
    lines = [
        f"# 赛事自动发现周报 {date.today().isoformat()}",
        "",
        f"- 扫描 incoming 文件：{len(incoming_files)}",
        f"- 新增入库：{len(added)}",
        f"- 因重复跳过：{len(skipped_dup)}",
        "",
    ]
    if added:
        lines.append("## 新增赛事")
        for cid, rec, _ in added:
            src = "有官方链接" if rec["official_source_url"] else "无官方链接"
            lines.append(f"- **{rec['competition_name']}** (`{cid}`) 类别={rec['category']} {src}")
    if skipped_dup:
        lines.append("")
        lines.append("## 重复跳过（已存在同名同年份）")
        for n in skipped_dup:
            lines.append(f"- {n}")
    digest = "\n".join(lines) + "\n"
    if not args.dry_run:
        (DIGEST_DIR / f"INGEST_DIGEST_{date.today().isoformat()}.md").write_text(digest, encoding="utf-8")

    print(digest)
    print(f"[ingest] dry_run={args.dry_run} 完成。")


if __name__ == "__main__":
    main()
