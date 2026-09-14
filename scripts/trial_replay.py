#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真人试用 · 系统侧证据复跑（trial_replay）

读取 scripts/trial_inputs.json（真人填写的提问），
以 test 演示账号登录后逐一调用 /api/agent/ask，
只记录系统真实返回（意图 / 引用数 / 是否带 [n] / 延迟），
作为 TRIAL_FORM「④ 系统侧证据」的客观佐证。

注意：本脚本只产生系统行为证据，不产生用户主观评价。
用户评价必须由真人填写（见 docs/TRIAL_FORM.md ③）。

可复现：venv/Scripts/python.exe scripts/trial_replay.py
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "http://127.0.0.1:8011"
USER = "test"
PASS = "test123"
TIMEOUT = 30
INPUT_FILE = "scripts/trial_inputs.json"
OUTPUT_FILE = "scripts/trial_replay_result.json"

_TOKEN = {"value": None}


def login() -> str:
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
            data = json.loads(resp.read().decode("utf-8", "replace"))
        elapsed = (time.perf_counter() - t0) * 1000
        answer = (data.get("answer") or "")
        return {
            "ok": True, "status": status, "elapsed_ms": round(elapsed, 1),
            "intent": data.get("intent"),
            "citations": len(data.get("citations") or []),
            "has_marker": ("[1]" in answer or "[2]" in answer),
            "answer_len": len(answer),
            "answer_snippet": answer[:120],
        }
    except urllib.error.HTTPError as e:
        if e.code == 401 and _TOKEN["value"] is not None:
            try:
                login()
                req = urllib.request.Request(url, headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {_TOKEN['value']}",
                })
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace"))
                elapsed = (time.perf_counter() - t0) * 1000
                answer = (data.get("answer") or "")
                return {
                    "ok": True, "status": resp.status, "elapsed_ms": round(elapsed, 1),
                    "intent": data.get("intent"),
                    "citations": len(data.get("citations") or []),
                    "has_marker": ("[1]" in answer or "[2]" in answer),
                    "answer_len": len(answer),
                    "answer_snippet": answer[:120],
                }
            except Exception as e2:
                return {"ok": False, "status": 401, "elapsed_ms": 0,
                        "error": f"RETRY_FAIL:{type(e2).__name__}"}
        return {"ok": False, "status": e.code, "elapsed_ms": 0,
                "error": e.read().decode("utf-8", "replace")[:200]}
    except Exception as e:
        return {"ok": False, "status": 0, "elapsed_ms": 0,
                "error": f"CLIENT_ERROR:{type(e).__name__}:{e}"}


def main():
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            trials = json.load(f)
    except FileNotFoundError:
        print(f"缺少 {INPUT_FILE}，请先按 docs/TRIAL_FORM.md 第四节整理提问列表")
        return

    results = []
    for t in trials:
        tid = t.get("trial_id", "?")
        q = t.get("question", "")
        res = ask(q)
        rec = {"trial_id": tid, "question": q, **res}
        results.append(rec)
        print(f"[{tid}] intent={res.get('intent')} cites={res.get('citations')} "
              f"marker={res.get('has_marker')} {res.get('elapsed_ms')}ms "
              f"| {res.get('status')}")

    summary = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base": BASE, "user": USER, "count": len(results),
        "results": results,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n→ {OUTPUT_FILE}（系统侧证据，非用户主观评价）")


if __name__ == "__main__":
    main()
