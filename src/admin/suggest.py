"""基于解析文本块的字段自动抽取建议（人工确认辅助）。

设计原则：不替代人工核对。所有抽取结果都回带「命中原文块 index」，
前端可一键采纳并把该原文块作为 evidence 提交；错误抽取由人工手动覆盖。
"""
from __future__ import annotations

import re
from typing import Optional

_DATE_CN = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_DATE_NUM = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")

# (kind, 正则)：range=区间, max=上限, min=下限/以上, exact=固定人数
_TEAM_PATTERNS = [
    ("range", re.compile(r"(\d{1,2})\s*[-~到至]\s*(\d{1,2})\s*人")),
    ("max", re.compile(r"不超过\s*(\d{1,2})\s*人")),
    ("min", re.compile(r"(\d{1,2})\s*人(?:以上|及以上)")),
    ("exact", re.compile(r"每队[约合]?\s*(\d{1,2})\s*人")),
]

_ELIGIBLE = [
    ("本科", "本科生"),
    ("在校大学生", "本科生"),
    ("研究生", "研究生"),
    ("硕士", "研究生"),
]


def extract_date(text: str) -> Optional[str]:
    """从文本抽取日期，返回 YYYY-MM-DD 或 None。"""
    m = _DATE_CN.search(text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = _DATE_NUM.search(text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def suggest_fields(blocks: list[dict]) -> dict:
    """输入 [{page, paragraph_index, text}]，返回字段抽取建议。

    每个字段建议含 value 与 evidence_index（命中原文块的序号），
    便于前端预关联引用。
    """
    suggestions: dict = {
        "team": {"required": False, "min": None, "max": None, "evidence_index": None},
        "registration_deadline": {"value": None, "evidence_index": None},
        "submission_deadline": {"value": None, "evidence_index": None},
        "eligible": {"value": None, "evidence_index": None},
    }

    for i, b in enumerate(blocks):
        text = b.get("text", "")

        # —— 团队人数 ——
        if not suggestions["team"]["required"]:
            for kind, pat in _TEAM_PATTERNS:
                m = pat.search(text)
                if m:
                    if kind == "range":
                        suggestions["team"]["min"] = int(m.group(1))
                        suggestions["team"]["max"] = int(m.group(2))
                    elif kind == "max":
                        suggestions["team"]["max"] = int(m.group(1))
                    else:  # min / exact
                        suggestions["team"]["min"] = int(m.group(1))
                        suggestions["team"]["max"] = suggestions["team"]["max"] or int(m.group(1))
                    suggestions["team"]["required"] = True
                    suggestions["team"]["evidence_index"] = i
                    break

        # —— 报名截止 ——
        if suggestions["registration_deadline"]["value"] is None and ("报名" in text or "注册" in text):
            d = extract_date(text)
            if d:
                suggestions["registration_deadline"]["value"] = d
                suggestions["registration_deadline"]["evidence_index"] = i

        # —— 提交/作品截止 ——
        if suggestions["submission_deadline"]["value"] is None and (
            "提交" in text or "作品" in text or "终评" in text or "决赛" in text
        ):
            d = extract_date(text)
            if d:
                suggestions["submission_deadline"]["value"] = d
                suggestions["submission_deadline"]["evidence_index"] = i

        # —— 参赛对象 ——
        if suggestions["eligible"]["value"] is None:
            for kw, val in _ELIGIBLE:
                if kw in text:
                    suggestions["eligible"]["value"] = val
                    suggestions["eligible"]["evidence_index"] = i
                    break

    return suggestions
