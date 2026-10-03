"""Opt-in local HTTP smoke check; sends only public evidence, no student profiles."""

import argparse
import json
from datetime import datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse

import requests


ROOT = Path(__file__).resolve().parents[1]
TARGET = "mathorcup_data_2026"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8014")
    parser.add_argument("--live", action="store_true", help="Permit a small paid online-model smoke check")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required to opt in to model usage")
    if urlparse(args.url).hostname not in ("127.0.0.1", "localhost"):
        parser.error("This smoke check is restricted to the local preview")
    base = args.url.rstrip("/")
    status = requests.get(base + "/api/agent/llm-status", timeout=10).json()
    if not status.get("enabled"):
        raise SystemExit("Local model is not enabled")
    cases = []

    def ask(case_id, question, checks, **params):
        started = perf_counter()
        response = requests.get(base + "/api/agent/ask", params={"question": question, **params}, timeout=60)
        response.raise_for_status()
        data = response.json()
        assertions = [{"expectation": name, "passed": bool(check(data))} for name, check in checks]
        cases.append({"id": case_id, "question": question, "response": data,
                      "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                      "assertions": assertions, "passed": all(check["passed"] for check in assertions)})
        print(case_id, "PASS" if cases[-1]["passed"] else "FAIL", flush=True)

    ask("LIVE-01", "报名截止和比赛结束分别是什么时候？", [
        ("two distinct official times", lambda d: "2026-10-23 12:00" in d["answer"] and "20:00" in d["answer"]),
        ("no other-field citations", lambda d: {c["field"] for c in d["citations"]} == {"registration_deadline", "competition_end_date"}),
    ], competition_id=TARGET)
    ask("LIVE-02", "这个比赛几个人一队？", [
        ("followup context retained", lambda d: d["resolved_competition"] == TARGET),
        ("official team quote", lambda d: "1" in d["answer"] and "3" in d["answer"]),
    ], context_competition_id=TARGET)
    ask("LIVE-03", "MathorCup大数据今年怎么报名？", [
        ("independent track correctly resolved", lambda d: d["resolved_competition"] == TARGET),
    ])
    ask("LIVE-04", "帮我为这个比赛制定一周备赛计划", [
        ("candidate notice and no score", lambda d: d["pending_review"] and "候选" in d["answer"] and not d["score"].get("total")),
        ("one week rather than months", lambda d: "第7天" in d["answer"]),
    ], competition_id="cocr_2026")
    ask("LIVE-05", "明年宇宙高校创新杯报名要多少钱？", [
        ("unknown event cannot inherit context", lambda d: not d["resolved_competition"] and not d["citations"]),
    ], context_competition_id=TARGET)
    model_used = lambda d: any("LLM 基于证据自由撰写" in step.get("detail", "") for step in d["trace"])
    ask("LIVE-06", "请用三句话建议我如何准备这个比赛，不要重复官方截止日期。", [
        ("real model was used, not just configured", model_used),
        ("answer and official evidence returned", lambda d: bool(d["answer"] and d["citations"])),
    ], competition_id=TARGET)
    ask("LIVE-07", "请用三句话说明这个比赛怎么准备，不要给资格结论。", [
        ("real model was used", model_used),
        ("candidate boundary retained", lambda d: d["pending_review"] and "候选" in d["answer"] and not d["score"].get("total")),
    ], competition_id="cocr_2026")
    result = {"executed_at": datetime.now().astimezone().isoformat(), "mode": "local_http_live_model",
              "provider": status.get("provider"), "model": status.get("model"),
              "limitations": ["Automated smoke check, not human feedback or online deployment verification",
                              "Only public contest evidence; no personal student profile sent",
                              "Advice and registration-method queries may use paid model calls; critical facts use deterministic rules"],
              "summary": {"passed": sum(case["passed"] for case in cases), "total": len(cases)}, "cases": cases}
    destination = ROOT / "evals/live_agent_results.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result["summary"], flush=True)
    if not all(case["passed"] for case in cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
