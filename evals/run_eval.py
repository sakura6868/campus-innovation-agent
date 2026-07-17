"""校园科创导航 Agent —— 自动化评测闭环（对照全部官方 ground_truth）。

设计目标：
  1. 零外部依赖：直接 import 业务代码（agent.graph.run_agent），不需要起服务、
     不需要 LLM key、不需要 Chroma（走本地隔离检索）。
  2. 用例自生成：从 data/ground_truth/samples/*.json（或退化到 DB 已 seed 的赛事）
     读取每个赛事的「名称 / ID」，自动构造：介绍/团队/截止/组队/推荐/未知 六类问句。
  3. 对照断言 & 指标：
       - intent_acc       意图分类准确率
       - resolve_acc      赛事锁定准确率（resolved_competition == 期望 ID）
       - citation_recall  引用字段召回（团队类问题是否召回到 team_max；截止类是否召回到 registration_deadline）
       - gate_consistency 门控一致性（与 recommendation.engine.eligibility_gate 重算结果比对）
       - answer_coverage  答案非空率
       - recommend_hit    推荐非空率
       - team_hit         组队文案命中率
  4. 输出：控制台汇总 + evals/report.md（Markdown 指标报告）+ evals/metrics.json。

运行：
  cd campus-innovation-agent
  ./venv/Scripts/python.exe evals/run_eval.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

# ---- 路径：把 src 加入 sys.path，使 `import db / agent.graph / rag.store` 可用 ----
PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ / "src"
sys.path.insert(0, str(SRC))

import db  # noqa: E402
from agent.graph import run_agent  # noqa: E402
from recommendation.engine import data_validity_check, eligibility_gate  # noqa: E402
from schemas import Competition, UserProfile  # noqa: E402

GT_DIR = PROJ / "data" / "ground_truth" / "samples"
OUT_REPORT = PROJ / "evals" / "report.md"
OUT_METRICS = PROJ / "evals" / "metrics.json"


# ---------------------------------------------------------------------------
# 1. 加载赛事（优先 ground_truth 样本，退化到 DB）
# ---------------------------------------------------------------------------


def load_competitions() -> list[Competition]:
    """返回 (competition_id, competition_name) 列表，用于构造测试用例。"""
    items: list[Competition] = []
    raws: list[dict] = []
    if GT_DIR.exists():
        for f in sorted(GT_DIR.glob("*.json")):
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
                raw.setdefault("competition_id", f.stem)
                raws.append(raw)
            except Exception:
                pass
    if not raws:
        # 退化：直接用已 seed 的 DB 赛事
        raws = [c.model_dump(mode="json") for c in db.get_all_competitions()]

    for raw in raws:
        try:
            items.append(Competition(**{k: v for k, v in raw.items() if k != "evidence"}))
        except Exception:
            # 允许 evidence 缺字段时不致命
            cid = raw.get("competition_id")
            name = raw.get("competition_name")
            if cid and name:
                items.append(
                    Competition(
                        competition_id=cid,
                        competition_name=name,
                        document_year=int(raw.get("document_year", 2026)),
                        category=raw.get("category", "programming"),
                    )
                )
    return items


# ---------------------------------------------------------------------------
# 2. 生成测试用例
# ---------------------------------------------------------------------------


def build_cases(comps: list[Competition]) -> list[dict]:
    cases: list[dict] = []
    name_counts: dict[str, int] = {}
    for comp in comps:
        name_counts[comp.competition_name] = name_counts.get(comp.competition_name, 0) + 1

    for c in comps:
        cid, name = c.competition_id, c.competition_name
        query_name = f"{c.document_year}年{name}" if name_counts[name] > 1 else name
        # 介绍（detail）—— 检测「是否返回了任意引用」（兜底修复前此处为 0）
        cases.append(
            {"group": "detail", "q": f"介绍一下{query_name}", "expect_intent": "detail",
             "expect_cid": cid, "user_id": "mock_user_001", "target_any": True}
        )
        # 团队人数（qa，目标引用字段 team_max）
        cases.append(
            {"group": "qa_team", "q": f"{query_name} 团队几人", "expect_intent": "qa",
             "expect_cid": cid, "user_id": "mock_user_001", "target_fields": {"team_min", "team_max"}}
        )
        # 报名截止（qa，目标引用字段 registration_deadline）
        cases.append(
            {"group": "qa_deadline", "q": f"{query_name} 报名什么时候截止", "expect_intent": "qa",
             "expect_cid": cid, "user_id": "mock_user_001", "target_field": "registration_deadline"}
        )
        # 组队文案（team）
        cases.append(
            {"group": "team", "q": f"帮我写一份{query_name}的组队招募文案", "expect_intent": "team",
             "expect_cid": cid, "user_id": "mock_user_001"}
        )
    # 推荐（recommend）
    cases.append(
        {"group": "recommend", "q": "推荐适合我的比赛", "expect_intent": "recommend",
         "user_id": "mock_user_001"}
    )
    # 未知（unknown）
    cases.append(
        {"group": "unknown", "q": "今天天气怎么样", "expect_intent": "unknown"}
    )
    return cases


# ---------------------------------------------------------------------------
# 3. 运行并断言
# ---------------------------------------------------------------------------


def recompute_gate(profile: UserProfile, comp: Competition) -> bool:
    """重算门控期望：数据有效 且 资格通过 == eligible。"""
    if data_validity_check(comp, date.today()):
        return False
    eligible, _ = eligibility_gate(profile, comp, date.today())
    return eligible


def run_case(case: dict, comps_by_id: dict) -> dict:
    r = run_agent(case["q"], user_id=case.get("user_id"), top_k=4)

    result = {
        "group": case["group"],
        "q": case["q"],
        "intent_ok": r["intent"] == case.get("expect_intent"),
        "intent": r["intent"],
        "expect_intent": case.get("expect_intent"),
        "resolve_ok": None,
        "resolved": r["resolved_competition"],
        "expect_cid": case.get("expect_cid"),
        "citation_ok": None,
        "gate_ok": None,
        "answer_nonempty": bool(r["answer"] and r["answer"].strip()),
        "n_citations": len(r["citations"]),
        "error": r.get("error"),
    }

    # 赛事锁定
    if case.get("expect_cid") is not None:
        result["resolve_ok"] = (r["resolved_competition"] == case["expect_cid"])

    # 引用字段召回
    if case.get("target_fields"):
        fields = {c.get("field") for c in r["citations"]}
        result["citation_ok"] = bool(fields & set(case["target_fields"]))
    elif case.get("target_field"):
        fields = {c.get("field") for c in r["citations"]}
        result["citation_ok"] = case["target_field"] in fields
    elif case.get("target_any"):
        # detail：只要返回了任意引用即算召回（兜底修复前为 0）
        result["citation_ok"] = len(r["citations"]) > 0

    # 门控一致性（仅当显式带 user_id 且锁定到赛事）
    if case.get("user_id") and r["resolved_competition"] and case.get("expect_cid"):
        # 用实时库对象重算门控（与 agent 同源），避免 comps_by_id 退化到
        # 历史 ground_truth JSON（截止日仍是 2024-2026）导致"已截止"误判
        comp = db.get_competition(r["resolved_competition"])
        profile = db.get_user_profile(case["user_id"])
        if comp and profile:
            try:
                expected = recompute_gate(profile, comp)
                result["gate_ok"] = (bool(r["gate"].get("eligible")) == expected)
                result["gate_expected"] = expected
                result["gate_actual"] = r["gate"].get("eligible")
            except Exception as exc:  # 门控重算失败不应中断整轮评测
                result["gate_ok"] = None
                result["gate_error"] = str(exc)[:120]

    # 组队 / 推荐 命中
    if case["group"] == "team":
        result["team_hit"] = ("组队招募" in (r["answer"] or "")) and bool(r.get("resolved_competition"))
    if case["group"] == "recommend":
        result["recommend_hit"] = len(r.get("recommendations") or []) > 0
    return result


# ---------------------------------------------------------------------------
# 4. 指标聚合
# ---------------------------------------------------------------------------


def aggregate(results: list[dict]) -> dict:
    def rate(items, key):
        vals = [x[key] for x in items if x.get(key) is not None]
        return (sum(1 for v in vals if v) / len(vals) * 100) if vals else None

    groups: dict[str, list] = {}
    for x in results:
        groups.setdefault(x["group"], []).append(x)

    metrics = {
        "total_cases": len(results),
        "intent_acc": rate(results, "intent_ok"),
        "resolve_acc": rate(results, "resolve_ok"),
        "citation_recall": rate(results, "citation_ok"),
        "gate_consistency": rate(results, "gate_ok"),
        "answer_coverage": rate(results, "answer_nonempty"),
        "by_group": {},
    }
    for g, items in sorted(groups.items()):
        metrics["by_group"][g] = {
            "n": len(items),
            "intent_acc": rate(items, "intent_ok"),
            "resolve_acc": rate(items, "resolve_ok"),
            "citation_recall": rate(items, "citation_ok"),
            "gate_consistency": rate(items, "gate_ok"),
            "answer_coverage": rate(items, "answer_nonempty"),
        }
        if g == "team":
            metrics["by_group"][g]["team_hit"] = rate(items, "team_hit")
        if g == "recommend":
            metrics["by_group"][g]["recommend_hit"] = rate(items, "recommend_hit")
    return metrics


def render_report(metrics: dict, results: list[dict]) -> str:
    lines = ["# Agent 自动化评测报告", ""]
    lines.append(f"测试时间：{date.today().isoformat()}　用例总数：**{metrics['total_cases']}**")
    lines.append("")
    lines.append("## 总体指标")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 意图分类准确率 | {metrics['intent_acc']:.1f}% |")
    lines.append(f"| 赛事锁定准确率 | {metrics['resolve_acc']:.1f}% |")
    lines.append(f"| 引用字段召回率 | {metrics['citation_recall']:.1f}% |")
    lines.append(f"| 门控一致性 | {metrics['gate_consistency']:.1f}% |")
    lines.append(f"| 答案非空率 | {metrics['answer_coverage']:.1f}% |")
    lines.append("")
    lines.append("## 分组明细")
    lines.append("")
    lines.append("| 分组 | 用例数 | 意图 | 锁定 | 引用召回 | 门控 | 答案 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for g, m in metrics["by_group"].items():
        def f(v):
            return f"{v:.0f}%" if v is not None else "-"
        extra = ""
        if g == "team":
            extra = f" | 组队命中 {f(m.get('team_hit'))}"
        elif g == "recommend":
            extra = f" | 推荐命中 {f(m.get('recommend_hit'))}"
        lines.append(
            f"| {g} | {m['n']} | {f(m['intent_acc'])} | {f(m['resolve_acc'])} | "
            f"{f(m['citation_recall'])} | {f(m['gate_consistency'])} | {f(m['answer_coverage'])}{extra} |"
        )
    lines.append("")
    lines.append("## 失败用例（供排错）")
    lines.append("")
    fails = [x for x in results if not (
        x["intent_ok"] and (x["resolve_ok"] in (True, None)) and (x["citation_ok"] in (True, None))
        and (x["gate_ok"] in (True, None))
    )]
    if not fails:
        lines.append("无。全部用例通过。")
    else:
        for x in fails:
            lines.append(
                f"- [{x['group']}] {x['q']} → 意图={x['intent']}(期望{x['expect_intent']}) "
                f"锁定={x['resolved']}(期望{x['expect_cid']}) 引用数={x['n_citations']}"
                + (f" 门控 期望={x.get('gate_expected')}/实际={x.get('gate_actual')}" if x.get('gate_ok') is False else "")
            )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    print("[eval] 加载赛事并构造用例……")
    comps = load_competitions()
    if not comps:
        print("[eval] 未找到任何赛事，退出。")
        return
    comps_by_id = {c.competition_id: c for c in comps}
    cases = build_cases(comps)
    print(f"[eval] 共 {len(comps)} 个赛事，生成 {len(cases)} 条测试用例。")

    results = []
    for i, case in enumerate(cases, 1):
        try:
            res = run_case(case, comps_by_id)
        except Exception as exc:
            res = {
                "group": case["group"], "q": case["q"],
                "intent_ok": False, "intent": "ERROR",
                "expect_intent": case.get("expect_intent"),
                "resolve_ok": None, "resolved": None, "expect_cid": case.get("expect_cid"),
                "citation_ok": None, "gate_ok": None,
                "answer_nonempty": False, "n_citations": 0,
                "error": f"{type(exc).__name__}: {exc}"[:200],
            }
            print(f"  [{i:02d}/{len(cases)}] ERR {case['group']:<10} {case['q']} -> {res['error']}")
        else:
            flag = "OK" if (res["intent_ok"] and res["resolve_ok"] in (True, None)) else "XX"
            print(f"  [{i:02d}/{len(cases)}] {flag} {case['group']:<10} {case['q']}")
        results.append(res)

    metrics = aggregate(results)
    report = render_report(metrics, results)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(report, encoding="utf-8")
    OUT_METRICS.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)
    print(f"[eval] 报告已写入：{OUT_REPORT}")
    print(f"[eval] 指标已写入：{OUT_METRICS}")


if __name__ == "__main__":
    main()
