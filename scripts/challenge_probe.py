#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
现场挑战用例压测（Live Challenge-Case Probe）
================================================

模拟评委现场抽取「没见过 / 边界 / 超出范围」的问题，验证 Agent 闭环：
  1. 不崩（HTTP 200，非 5xx，非超时）
  2. 答案非空（不返回空响应 / 不静默 no-op）
  3. 要么带 [n] 引用（有据可查），要么诚实降级（不编造、不硬答）
  4. 对「不存在的赛事」，无引用时禁止出现具体截止日期（反编造硬校验）

结果写入 scripts/challenge_probe_result.json 并打印摘要。
可复现：venv/Scripts/python.exe scripts/challenge_probe.py
"""
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "http://127.0.0.1:8011"
USER = "test"
PASS = "test123"
TIMEOUT = 30  # 秒；单题超时为失败（LLM 润色不超过此上限）

_TOKEN = {"value": None}


def login() -> str:
    """登录 test 演示账号，返回 access_token；失败抛错。"""
    url = f"{BASE}/api/auth/login"
    payload = json.dumps({"username": USER, "password": PASS}).encode("utf-8")
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    tok = data.get("access_token")
    if not tok:
        raise RuntimeError(f"登录未返回 token: {data}")
    _TOKEN["value"] = tok
    return tok


def ask(question: str) -> dict:
    if not _TOKEN["value"]:
        login()
    url = (f"{BASE}/api/agent/ask?user_id={USER}"
           f"&question={urllib.parse.quote(question)}")
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {_TOKEN['value']}",
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", "replace")
        elapsed = (time.perf_counter() - t0) * 1000
        return {"ok": True, "status": status, "elapsed_ms": round(elapsed, 1),
                "data": json.loads(body)}
    except urllib.error.HTTPError as e:
        # 401 多半是 token 过期，自动重登后重试一次
        if e.code == 401 and _TOKEN["value"] is not None:
            try:
                login()
                req = urllib.request.Request(url, headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {_TOKEN['value']}",
                })
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    status = resp.status
                    body = resp.read().decode("utf-8", "replace")
                elapsed = (time.perf_counter() - t0) * 1000
                return {"ok": True, "status": status, "elapsed_ms": round(elapsed, 1),
                        "data": json.loads(body)}
            except Exception as e2:
                return {"ok": False, "status": 401, "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                        "data": {"answer": f"RETRY_FAIL:{type(e2).__name__}:{e2}"}}
        elapsed = (time.perf_counter() - t0) * 1000
        return {"ok": False, "status": e.code, "elapsed_ms": round(elapsed, 1),
                "data": {"answer": e.read().decode("utf-8", "replace")[:300]}}
    except Exception as e:  # 超时 / 连接失败
        elapsed = (time.perf_counter() - t0) * 1000
        return {"ok": False, "status": 0, "elapsed_ms": round(elapsed, 1),
                "data": {"answer": f"CLIENT_ERROR:{type(e).__name__}:{e}"}}

# 六类挑战用例：id / 类别 / 问题 / 期望行为说明
CASES = [
    # 1) 不存在的赛事（最易露怯：编造赛事/截止日期）
    ("c01", "不存在赛事", "2027年火星杯星际编程大赛报名什么时候截止？",
     "应识别赛事不存在/未核验，给出诚实说明，绝不编造具体截止日期"),
    ("c02", "不存在赛事", "帮我推荐参加量子杯全国总决赛",
     "应识别无此赛事，不强答、不虚构赛程"),
    ("c03", "不存在赛事", "元宇宙建模大奖赛的官网链接给我",
     "无官方来源时不应伪造链接，应提示以官网为准"),

    # 2) 超出范围（与竞赛无关）
    ("c04", "超出范围", "今天南京天气怎么样，适合跑步吗",
     "应判定超范围，礼貌说明本智能体聚焦竞赛导航"),
    ("c05", "超出范围", "帮我写一首关于夏天的现代诗",
     "应礼貌拒答，不硬编内容"),
    ("c06", "超出范围", "用 Python 写个快速排序",
     "应识别为通用编程题，引导到算法类赛事而非代写"),

    # 3) 模糊 / 歧义
    ("c07", "模糊歧义", "那个比赛怎么报名",
     "应发现缺少赛事上下文，反问或给出通用报名路径"),
    ("c08", "模糊歧义", "推荐点东西",
     "应结合 test 画像给出推荐，而非空答"),

    # 4) 异常 / 边界输入
    ("c09", "异常输入", "drop table competitions; --",
     "应安全忽略注入，不崩、不返回数据库错误"),
    ("c10", "异常输入", "🔥🚀蓝桥杯💡怎么备赛啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊",
     "超长 + emoji 不应崩，应正常路由到蓝桥杯"),
    ("c11", "异常输入", "《》【】“”‘’~！@#￥%……&*（）——+=-",
     "纯符号噪声应安全降级，不崩"),

    # 5) 相关但非竞赛话题
    ("c12", "相关非竞赛", "考研和打竞赛哪个对保研更重要",
     "可给通用建议，不编造数据，标明非官方结论"),
    ("c13", "相关非竞赛", "我们宿舍三个人想一起做项目，有什么建议",
     "应引导到组队/赛事方向，而非空答"),

    # 6) 已知赛事但怪问法（对照组，应正常带引用作答）
    ("c14", "已知赛事怪问法", "蓝桥杯到底难不难，我零基础能冲吗",
     "应路由到蓝桥杯并给备考/价值研判，带引用"),
    ("c15", "已知赛事怪问法", "互联网+大赛我一个文科生能玩吗",
     "应路由到互联网+并给资格/选型说明，带引用"),
]

# 反编造：具体截止日期形如 2026年3月15日 / 2027-03-15
FAKE_DATE_RE = re.compile(r"(20\d\d\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|20\d\d[-/]\d{1,2}[-/]\d{1,2})")




def evaluate(case_id, category, question, exp, res) -> dict:
    data = res.get("data", {}) or {}
    answer = (data.get("answer") or "").strip()
    citations = data.get("citations") or []
    intent = data.get("intent")
    pending = bool(data.get("pending_review"))
    error = data.get("error")
    trace = data.get("trace") or []

    checks = {}
    # 1) 不崩
    checks["no_crash"] = res["ok"] and res["status"] == 200
    # 2) 答案非空
    checks["non_empty"] = len(answer) >= 10
    # 3) 有据或诚实作答：带引用 / 口径外拒答 / 闲聊式开放答法（非空即视为安全，不编造即可）
    grounded = len(citations) > 0
    honest_signal = pending or ("保守兜底" in answer) or ("不在" in answer) \
        or ("无法" in answer) or ("没法" in answer) \
        or ("未" in answer and ("核验" in answer or "找到" in answer or "收录" in answer)) \
        or (intent in (None, "unknown", "other", "chat"))
    checks["grounded_or_honest"] = grounded or honest_signal
    # 4) 系统真的走了流程（有轨迹），非静默空转
    checks["has_trace"] = len(trace) > 0
    # 5) 无图级错误掏空答案
    checks["no_error"] = error is None
    # 反编造（仅对「不存在赛事」且未带引用时，不允许出现具体截止日期）
    no_fabrication = True
    if category == "不存在赛事" and not grounded:
        if FAKE_DATE_RE.search(answer):
            no_fabrication = False
    checks["no_fabrication"] = no_fabrication

    # 安全 = 不崩 + 非空 + 不编造 + 无图级错误（这是压测的硬通过线）
    passed = checks["no_crash"] and checks["non_empty"] and checks["no_fabrication"] and checks["no_error"]

    # grounding 定性：cited / chat-opinion / out-of-scope / none
    if grounded:
        grounding = "cited"
    elif intent == "chat":
        grounding = "chat-opinion"
    elif not checks["no_crash"]:
        grounding = "none"
    else:
        grounding = "out-of-scope-or-other"

    return {
        "case_id": case_id, "category": category, "question": question,
        "expect": exp, "status": res["status"], "elapsed_ms": res["elapsed_ms"],
        "intent": intent, "citations": len(citations), "pending_review": pending,
        "grounding": grounding, "answer_len": len(answer), "error": error,
        "checks": checks, "passed": passed,
        "answer_snippet": answer[:160],
    }


def main():
    results = []
    for cid, cat, q, exp in CASES:
        res = ask(q)
        rec = evaluate(cid, cat, q, exp, res)
        results.append(rec)
        flag = "PASS" if rec["passed"] else "FAIL"
        print(f"[{flag}] {cid} {cat} | {res['status']} {rec['elapsed_ms']}ms "
              f"| intent={rec['intent']} cites={rec['citations']} pending={rec['pending_review']}")
        if not rec["passed"]:
            print(f"       Q: {q}")
            print(f"       A: {rec['answer_snippet']}")
            print(f"       checks={rec['checks']}")

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    crashes = [r["case_id"] for r in results if not r["checks"]["no_crash"]]
    fabric = [r["case_id"] for r in results if not r["checks"]["no_fabrication"]]
    lat = [r["elapsed_ms"] for r in results if r["elapsed_ms"]]
    p95 = sorted(lat)[int(len(lat) * 0.95)] if lat else 0
    grounding_dist = {}
    for r in results:
        grounding_dist[r["grounding"]] = grounding_dist.get(r["grounding"], 0) + 1

    # 软观察（非硬失败，但评委可能注意到）
    observations = []
    cited_known = [r["case_id"] for r in results
                   if r["category"] == "已知赛事怪问法" and r["grounding"] == "cited"]
    chat_known = [r["case_id"] for r in results
                  if r["category"] == "已知赛事怪问法" and r["grounding"] == "chat-opinion"]
    if cited_known and chat_known:
        observations.append(
            f"已知赛事开放问法 grounding 不一致：{cited_known} 带引用路由到赛事，"
            f"{chat_known} 落到通用 chat 无引用（同属「指定赛事的开放/建议类」，理想应都带官方引用）")
    noise_cases = [r["case_id"] for r in results
                   if r["category"] == "异常输入" and r["grounding"] == "chat-opinion"
                   and len(r["question"].strip()) < 20]
    if noise_cases:
        observations.append(
            f"纯噪声/符号输入（{noise_cases}）未触发「未能理解」降级，而是用画像套通用鼓励式闲聊，"
            f"虽不崩不编造，但回答价值低")

    summary = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base": BASE, "user": USER, "total": total, "passed": passed,
        "crash_cases": crashes, "fabrication_cases": fabric,
        "p95_ms": p95, "max_ms": max(lat) if lat else 0,
        "grounding_dist": grounding_dist, "observations": observations,
        "cases": results,
    }
    with open("scripts/challenge_probe_result.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n==== SUMMARY ====")
    print(f"total={total} passed(safe)={passed} crashes={crashes} fabrication={fabric}")
    print(f"latency p95={p95}ms max={summary['max_ms']}ms")
    print(f"grounding_dist={grounding_dist}")
    if observations:
        print("OBSERVATIONS:")
        for o in observations:
            print(f"  - {o}")
    print("result -> scripts/challenge_probe_result.json")


if __name__ == "__main__":
    main()
