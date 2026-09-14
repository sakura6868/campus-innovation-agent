# -*- coding: utf-8 -*-
"""轻量并发压测：给出可读的性能与稳定性数据，供评审复现。

用法（项目根目录，服务已启动）：
    venv\\Scripts\\python.exe scripts\\benchmark_smoke.py

设计说明：
- 只压测**确定性本地链路**（检索 / 列表 / 雷达 / 质量 / 项目），这些是本系统的核心闭环；
- LLM 问答单独以低并发采样，因为其延迟主要取决于外部模型服务，不代表本系统性能；
- 全程只读，不写入业务数据。
"""

from __future__ import annotations

import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE = "http://127.0.0.1:8011"
USERNAME = "test"
PASSWORD = "test123"

READ_ENDPOINTS = [
    ("健康检查", "GET", "/health", False),
    ("赛事列表", "GET", "/api/competitions", False),
    ("学生画像类型", "GET", "/api/student-types", False),
    ("来源雷达状态", "GET", "/api/radar/status", False),
    ("系统质量驾驶舱", "GET", "/api/system/quality", False),
    ("我的项目", "GET", "/api/users/test/projects", True),
    ("情报收件箱", "GET", "/api/users/test/alerts", True),
]

CONCURRENCY = 10
REQUESTS_PER_ENDPOINT = 30


def login() -> str:
    resp = requests.post(
        BASE + "/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def once(method: str, path: str, headers: dict | None) -> tuple[bool, float]:
    start = time.perf_counter()
    try:
        r = requests.request(method, BASE + path, headers=headers, timeout=30)
        ok = 200 <= r.status_code < 400
    except Exception:  # noqa: BLE001
        ok = False
    return ok, (time.perf_counter() - start) * 1000


def run_case(name, method, path, need_auth, headers):
    h = headers if need_auth else None
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = [pool.submit(once, method, path, h) for _ in range(REQUESTS_PER_ENDPOINT)]
        results = [f.result() for f in as_completed(futures)]

    ok_flags = [r[0] for r in results]
    latencies = sorted(r[1] for r in results)
    success = sum(1 for x in ok_flags if x)
    total = len(ok_flags)

    def pct(p: float) -> float:
        if not latencies:
            return 0.0
        idx = min(int(round(p / 100 * (len(latencies) - 1))), len(latencies) - 1)
        return latencies[idx]

    elapsed = sum(latencies) / CONCURRENCY / 1000 if latencies else 0
    return {
        "name": name,
        "path": path,
        "total": total,
        "success": success,
        "rate": 100.0 * success / total if total else 0.0,
        "avg": statistics.mean(latencies) if latencies else 0.0,
        "p50": pct(50),
        "p95": pct(95),
        "max": latencies[-1] if latencies else 0.0,
        "qps": success / elapsed if elapsed > 0 else 0.0,
    }


def sample_ask(headers, times: int = 3):
    """LLM 问答采样：延迟主要来自外部模型，仅作参考。"""
    latencies = []
    ok_count = 0
    for _ in range(times):
        start = time.perf_counter()
        try:
            r = requests.get(
                BASE + "/api/agent/ask",
                params={"question": "智能车怎么备赛", "user_id": USERNAME},
                headers=headers,
                timeout=120,
            )
            if r.status_code == 200:
                ok_count += 1
        except Exception:  # noqa: BLE001
            pass
        latencies.append((time.perf_counter() - start) * 1000)
    return ok_count, times, statistics.mean(latencies), max(latencies)


def main() -> int:
    print("=" * 78)
    print("校园科创导航智能体 · 并发压测（并发=%d，每接口 %d 次）" % (CONCURRENCY, REQUESTS_PER_ENDPOINT))
    print("=" * 78)
    try:
        token = login()
    except Exception as exc:  # noqa: BLE001
        print("登录失败：", exc)
        return 1
    headers = {"Authorization": "Bearer %s" % token}

    print()
    print("%-16s %-28s %6s %8s %9s %9s %9s %8s" % ("接口", "路径", "成功", "成功率", "均值ms", "P50ms", "P95ms", "QPS"))
    print("-" * 78)
    rows = []
    for name, method, path, need_auth in READ_ENDPOINTS:
        r = run_case(name, method, path, need_auth, headers)
        rows.append(r)
        print(
            "%-16s %-28s %3d/%-3d %7.1f%% %9.1f %9.1f %9.1f %8.1f"
            % (r["name"], r["path"], r["success"], r["total"], r["rate"], r["avg"], r["p50"], r["p95"], r["qps"])
        )
    print("-" * 78)

    all_ok = sum(r["success"] for r in rows)
    all_total = sum(r["total"] for r in rows)
    print("合计：%d/%d 成功，成功率 %.2f%%" % (all_ok, all_total, 100.0 * all_ok / all_total))
    worst = max(rows, key=lambda r: r["p95"])
    print("最慢接口（P95）：%s %.1f ms" % (worst["name"], worst["p95"]))

    print()
    print("--- LLM 问答采样（含外部模型调用，仅供参考）---")
    ok, total, avg, mx = sample_ask(headers)
    print("成功 %d/%d，平均 %.0f ms，最大 %.0f ms" % (ok, total, avg, mx))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
