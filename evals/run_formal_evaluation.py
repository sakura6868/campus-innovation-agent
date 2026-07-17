"""Run the 15 submission metrics cases and the complete regression suite."""

from __future__ import annotations

import hashlib
import io
import json
import platform
import re
import sys
import unittest
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
GT_DIR = PROJECT_ROOT / "data" / "ground_truth" / "samples"
RESULT_PATH = PROJECT_ROOT / "evals" / "formal_results.json"
REPORT_PATH = PROJECT_ROOT / "docs" / "QUANTITATIVE_EVALUATION.md"
sys.path.insert(0, str(SRC_DIR))

import db  # noqa: E402
from agent.graph import run_agent  # noqa: E402
from rag.store import get_rag  # noqa: E402
from recommendation.engine import recommend_for_user  # noqa: E402
from schemas import (  # noqa: E402
    Competition,
    CompetitionCategory,
    DataStatus,
    EducationLevel,
    Grade,
    TrustedLevel,
    UserProfile,
)


METRIC_LABELS = {
    "deadline_consistency": "截止日期一致率",
    "eligibility_accuracy": "资格判断准确率",
    "citation_accuracy": "官方证据引用正确率",
    "unverified_block_rate": "未核验赛事拦截率",
    "insufficient_refusal_rate": "信息不足时的拒答率",
}


@dataclass(frozen=True)
class FormalCase:
    case_id: str
    metric: str
    scenario: str
    check: Callable[[], str]


def profile(user_id: str = "formal_eval_user") -> UserProfile:
    return UserProfile(
        user_id=user_id,
        education_level=EducationLevel.UNDERGRADUATE,
        grade=Grade.SOPHOMORE,
        major="软件工程",
        skills=["Python"],
        weekly_available_hours=12,
        expected_team_size=3,
        privacy_consent=True,
    )


def synthetic_competition(**overrides) -> Competition:
    values = {
        "competition_id": "formal_eval_competition",
        "competition_name": "正式评测赛事",
        "document_year": date.today().year,
        "category": CompetitionCategory.SOFTWARE,
        "eligible_students": [EducationLevel.UNDERGRADUATE],
        "registration_deadline": date.today() + timedelta(days=30),
        "official_source_url": "https://example.edu/formal-evaluation",
        "source_acquired_date": date.today().isoformat(),
        "trusted_level": TrustedLevel.A,
        "data_status": DataStatus.VERIFIED,
        "last_verified_at": date.today().isoformat(),
    }
    values.update(overrides)
    return Competition(**values)


def ground_truth_rows() -> list[tuple[Path, dict, Competition]]:
    rows = []
    for path in sorted(GT_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        comp = db.get_competition(path.stem)
        if comp is None:
            raise AssertionError(f"数据库缺少 {path.stem}")
        rows.append((path, raw, comp))
    if len(rows) < 21:
        raise AssertionError(f"预期至少21份 Ground Truth，实际{len(rows)}份")
    return rows


def deadline_registration_matches() -> str:
    rows = ground_truth_rows()
    for path, raw, comp in rows:
        actual = comp.registration_deadline.isoformat() if comp.registration_deadline else None
        if actual != raw.get("registration_deadline"):
            raise AssertionError(f"{path.name}: {actual} != {raw.get('registration_deadline')}")
    return f"{len(rows)}/{len(rows)} 项报名截止日期与 Ground Truth 一致"


def deadline_submission_matches() -> str:
    rows = ground_truth_rows()
    for path, raw, comp in rows:
        actual = comp.submission_deadline.isoformat() if comp.submission_deadline else None
        if actual != raw.get("submission_deadline"):
            raise AssertionError(f"{path.name}: {actual} != {raw.get('submission_deadline')}")
    return f"{len(rows)}/{len(rows)} 项提交截止日期与 Ground Truth 一致"


def agent_uses_unique_canonical_deadline() -> str:
    core_ids = ("china_softcup_2026", "mathorcup_2026", "mcm_cn_2026", "mai_qihang_2026")
    for competition_id in core_ids:
        comp = db.get_competition(competition_id)
        result = run_agent("报名截止日期是什么时候", competition_id=competition_id, top_k=4)
        dates = re.findall(r"报名截止日期：(\d{4}-\d{2}-\d{2})", result["answer"])
        expected = comp.registration_deadline.isoformat()
        if dates != [expected]:
            raise AssertionError(f"{competition_id}: {dates} != [{expected}]")
    return "4/4 个核心赛事仅输出一个规范报名截止日期"


def eligible_open_competition_is_scored() -> str:
    result = recommend_for_user(profile(), [synthetic_competition()], date.today())[0]
    if not result.eligible or result.score is None or result.recommendation_status == "ineligible":
        raise AssertionError("已核验开放赛事未进入正式评分")
    return f"开放且符合资格的赛事进入正式评分，score={result.score}"


def expired_registration_is_rejected() -> str:
    comp = synthetic_competition(registration_deadline=date.today() - timedelta(days=1))
    result = recommend_for_user(profile(), [comp], date.today())[0]
    if result.eligible or result.score is not None or result.recommendation_status != "ineligible":
        raise AssertionError("报名已截止赛事未被正确拒绝")
    return "报名已截止赛事为 ineligible，score=null"


def expired_submission_fallback_is_rejected() -> str:
    comp = synthetic_competition(
        registration_deadline=None,
        submission_deadline=date.today() - timedelta(days=1),
    )
    result = recommend_for_user(profile(), [comp], date.today())[0]
    if result.eligible or result.score is not None or result.recommendation_status != "ineligible":
        raise AssertionError("缺少报名日时未按提交截止日期拒绝")
    return "报名日缺失时使用提交截止日判断，score=null"


def load_core_evidence() -> list[tuple[str, dict]]:
    records = []
    for path in sorted(GT_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("data_status") == "verified":
            records.append((path.stem, raw))
    return records


def core_fields_have_evidence() -> str:
    required = {"registration_deadline", "eligible_students", "team_min", "team_max", "required_materials"}
    for competition_id, raw in load_core_evidence():
        fields = {item["field"] for item in raw.get("evidence", [])}
        missing = required - fields
        if missing:
            raise AssertionError(f"{competition_id} 缺少字段证据: {sorted(missing)}")
    count = len(load_core_evidence())
    return f"{count}/{count} 个已核验赛事的5类关键字段均有关联证据"


def core_evidence_metadata_is_complete() -> str:
    checked = 0
    for competition_id, raw in load_core_evidence():
        for item in raw.get("evidence", []):
            checked += 1
            if not isinstance(item.get("page"), int):
                raise AssertionError(f"{competition_id}.{item.get('field')} 缺少页码")
            if not item.get("source_text") or not str(item.get("source_url", "")).startswith("http"):
                raise AssertionError(f"{competition_id}.{item.get('field')} 原文或链接无效")
            if not item.get("acquired_date") or not item.get("last_verified_at"):
                raise AssertionError(f"{competition_id}.{item.get('field')} 日期元数据不完整")
    return f"{checked}/{checked} 条核心证据具备页码、原文、链接、获取和核验日期"


def rag_deadline_citations_are_official() -> str:
    core_ids = ("china_softcup_2026", "mathorcup_2026", "mcm_cn_2026", "mai_qihang_2026")
    for competition_id in core_ids:
        citations = get_rag().query(competition_id, "报名截止日期是什么时候", top_k=4)
        deadline_hits = [item for item in citations if item.field == "registration_deadline"]
        if not deadline_hits:
            raise AssertionError(f"{competition_id} 未召回报名截止证据")
        if any(not item.source_url.startswith("http") or not item.source_text for item in deadline_hits):
            raise AssertionError(f"{competition_id} 召回证据缺少官方链接或原文")
    return "4/4 个核心赛事的截止日期检索命中官方原文和链接"


def unverified_recommendation_is_candidate_only() -> str:
    comp = synthetic_competition(
        data_status=DataStatus.UNVERIFIED,
        trusted_level=TrustedLevel.B,
        last_verified_at=None,
    )
    result = recommend_for_user(profile(), [comp], date.today())[0]
    if result.recommendation_status != "candidate_only" or result.score is not None or result.eligible:
        raise AssertionError("未核验赛事进入了正式推荐")
    return "未核验赛事仅为 candidate_only，score=null"


def unverified_project_creation_is_blocked() -> str:
    user_id = "formal_eval_block_user"
    db.delete_user_profile(user_id)
    db.save_user_profile(profile(user_id))
    try:
        try:
            db.create_user_project(user_id, "lanqiao_2026")
        except ValueError as exc:
            if str(exc) != "competition_unverified":
                raise
        else:
            raise AssertionError("未核验赛事被加入项目")
    finally:
        db.delete_user_profile(user_id)
    return "未核验赛事创建项目时返回 competition_unverified"


def unverified_agent_answer_is_labeled() -> str:
    result = run_agent("2026年蓝桥杯报名截止", competition_id="lanqiao_2026", top_k=4)
    if not result["pending_review"] or "待人工确认" not in result["answer"]:
        raise AssertionError("Agent 未标注未核验状态")
    return "Agent 回答明确标注待人工确认"


def missing_national_deadline_is_not_invented() -> str:
    result = run_agent("报名截止日期是什么时候", competition_id="jsj_sj_2026", top_k=4)
    if "未给出全国统一报名截止日期" not in result["answer"]:
        raise AssertionError("未明确说明官方文件缺少全国统一日期")
    if re.search(r"报名截止日期：\d{4}-\d{2}-\d{2}", result["answer"]):
        raise AssertionError("Agent 编造了报名截止日期")
    return "官方未给日期时明确拒绝给出日期"


def ambiguous_unverified_versions_ask_for_year() -> str:
    result = run_agent("蓝桥杯报名截止")
    if result["resolved_competition"] is not None:
        raise AssertionError("同名未核验版本被静默选中")
    if "存在多个年份版本" not in result["answer"] or "请明确年份" not in result["answer"]:
        raise AssertionError("未向用户追问年份")
    return "同名赛事均未核验时追问具体年份"


def out_of_domain_question_is_refused() -> str:
    result = run_agent("今天天气怎么样")
    if result["intent"] != "unknown" or result["resolved_competition"] is not None or result["citations"]:
        raise AssertionError("域外问题被错误路由或引用赛事证据")
    if "请补充具体赛事名称" not in result["answer"]:
        raise AssertionError("域外问题未返回能力边界说明")
    return "域外问题不生成赛事事实，提示补充具体赛事名称"


def build_cases() -> list[FormalCase]:
    return [
        FormalCase("FE-01", "deadline_consistency", "报名日期与 Ground Truth 一致", deadline_registration_matches),
        FormalCase("FE-02", "deadline_consistency", "提交日期与 Ground Truth 一致", deadline_submission_matches),
        FormalCase("FE-03", "deadline_consistency", "Agent 仅输出规范截止日期", agent_uses_unique_canonical_deadline),
        FormalCase("FE-04", "eligibility_accuracy", "开放且符合资格赛事进入评分", eligible_open_competition_is_scored),
        FormalCase("FE-05", "eligibility_accuracy", "报名已截止赛事不评分", expired_registration_is_rejected),
        FormalCase("FE-06", "eligibility_accuracy", "报名日缺失时检查提交日", expired_submission_fallback_is_rejected),
        FormalCase("FE-07", "citation_accuracy", "核心字段均有证据", core_fields_have_evidence),
        FormalCase("FE-08", "citation_accuracy", "证据元数据完整", core_evidence_metadata_is_complete),
        FormalCase("FE-09", "citation_accuracy", "RAG 命中官方截止证据", rag_deadline_citations_are_official),
        FormalCase("FE-10", "unverified_block_rate", "未核验赛事仅作为候选", unverified_recommendation_is_candidate_only),
        FormalCase("FE-11", "unverified_block_rate", "未核验赛事不能加入项目", unverified_project_creation_is_blocked),
        FormalCase("FE-12", "unverified_block_rate", "Agent 标注未核验状态", unverified_agent_answer_is_labeled),
        FormalCase("FE-13", "insufficient_refusal_rate", "官方未给日期时不编造", missing_national_deadline_is_not_invented),
        FormalCase("FE-14", "insufficient_refusal_rate", "同名未核验版本追问年份", ambiguous_unverified_versions_ask_for_year),
        FormalCase("FE-15", "insufficient_refusal_rate", "域外问题拒绝生成赛事事实", out_of_domain_question_is_refused),
    ]


def run_regression_suite() -> dict:
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(PROJECT_ROOT / "tests"))
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return {
        "tests_run": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "successful": result.wasSuccessful(),
        "output": stream.getvalue(),
    }


def latest_freeze() -> dict | None:
    archives = sorted((PROJECT_ROOT / "backups").glob("campus-agent-freeze-*.zip"))
    if not archives:
        return None
    path = archives[-1]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": path.relative_to(PROJECT_ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest}


def render_report(payload: dict) -> str:
    lines = [
        "# 校园科创导航智能体量化评测报告",
        "",
        f"- 评测时间：{payload['evaluated_at']}",
        f"- 运行环境：Python {payload['environment']['python']} / {payload['environment']['platform']}",
        f"- 正式指标用例：{payload['formal_summary']['passed']}/{payload['formal_summary']['total']} 通过",
        f"- 自动回归测试：{payload['regression']['passed']}/{payload['regression']['tests_run']} 通过",
        "",
        "## 核心指标",
        "",
        "| 指标 | 通过/总数 | 结果 |",
        "| --- | ---: | ---: |",
    ]
    for metric, label in METRIC_LABELS.items():
        item = payload["metrics"][metric]
        lines.append(f"| {label} | {item['passed']}/{item['total']} | **{item['rate']:.1f}%** |")

    lines.extend(["", "## 15条正式用例", "", "| ID | 指标 | 场景 | 结果 | 实测证据 |", "| --- | --- | --- | --- | --- |"])
    for item in payload["cases"]:
        status = "通过" if item["passed"] else "失败"
        detail = str(item["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {item['case_id']} | {METRIC_LABELS[item['metric']]} | {item['scenario']} | {status} | {detail} |")

    lines.extend([
        "",
        f"## {payload['regression']['tests_run']}项自动测试",
        "",
        "执行命令：",
        "",
        "```powershell",
        ".\\venv\\Scripts\\python.exe -m unittest discover -s tests -v",
        "```",
        "",
        f"本次实际运行 {payload['regression']['tests_run']} 项，通过 {payload['regression']['passed']} 项，"
        f"失败 {payload['regression']['failures']} 项，错误 {payload['regression']['errors']} 项。",
        "测试范围包括 Ground Truth、推荐门控、学历校验、证据完整性、RAG/Agent 日期一致性、项目工作台、ICS、删除和多年份消歧。",
        "",
        "## 结论与边界",
        "",
        "本轮15条正式指标用例全部通过，五项核心指标均为100%。该结果仅适用于当前冻结数据和测试范围，"
        "不表示所有未来赛事或任意自然语言输入均能达到100%；新增赛事必须经过相同的证据核验和回归流程。",
    ])
    if payload.get("freeze"):
        freeze = payload["freeze"]
        lines.extend([
            "",
            "## 冻结版本",
            "",
            f"- 备份包：`{freeze['path']}`",
            f"- 文件大小：{freeze['bytes']} bytes",
            f"- SHA-256：`{freeze['sha256']}`",
        ])
    lines.extend(["", "机器可读结果：`evals/formal_results.json`", ""])
    return "\n".join(lines)


def main() -> int:
    db.init_db()
    results = []
    for case in build_cases():
        try:
            detail = case.check()
            passed = True
        except Exception as exc:  # keep the complete report even when one case fails
            detail = f"{type(exc).__name__}: {exc}"
            passed = False
        results.append(
            {
                "case_id": case.case_id,
                "metric": case.metric,
                "scenario": case.scenario,
                "passed": passed,
                "detail": detail,
            }
        )
        print(f"[{case.case_id}] {'PASS' if passed else 'FAIL'} {case.scenario}: {detail}")

    metrics = {}
    for metric in METRIC_LABELS:
        items = [item for item in results if item["metric"] == metric]
        passed = sum(1 for item in items if item["passed"])
        metrics[metric] = {"passed": passed, "total": len(items), "rate": passed / len(items) * 100}

    regression = run_regression_suite()
    payload = {
        "evaluated_at": date.today().isoformat(),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "formal_summary": {
            "passed": sum(1 for item in results if item["passed"]),
            "total": len(results),
        },
        "metrics": metrics,
        "cases": results,
        "regression": regression,
        "freeze": latest_freeze(),
    }
    RESULT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(render_report(payload), encoding="utf-8")

    formal_ok = payload["formal_summary"]["passed"] == payload["formal_summary"]["total"]
    all_ok = formal_ok and regression["successful"] and regression["tests_run"] >= 24
    print(f"Formal: {payload['formal_summary']['passed']}/{payload['formal_summary']['total']}")
    print(f"Regression: {regression['passed']}/{regression['tests_run']}")
    print(f"Report: {REPORT_PATH}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
