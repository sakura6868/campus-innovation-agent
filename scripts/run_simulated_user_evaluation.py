"""Automated journeys using owner-confirmed real profiles, not human feedback."""

from __future__ import annotations

import json
import argparse
import hashlib
import os
import sys
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-10-03T11:00:00+08:00")
TARGET = "mathorcup_data_2026"
NAME = "2026年第七届MathorCup数学应用挑战赛（大数据竞赛）"
PERSONAS = [
    ("p01", "计算机大二，3人团队", "本科生", "大二", "计算机科学与技术", 3, 12, ["Python", "数据分析"]),
    ("p02", "英语大一，独自参赛", "本科生", "大一", "英语", 1, 6, ["英语", "报告写作"]),
    ("p03", "数学大三，4人团队", "本科生", "大三", "数学", 4, 15, ["MATLAB", "数学建模"]),
    ("p04", "研究生一年级", "研究生", "研一", "统计学", 3, 15, ["Python", "统计分析"]),
    ("p05", "高职大二，3人团队", "高职高专生", "大二", "大数据技术", 3, 10, ["Python"]),
    ("p06", "毕业两年，希望继续参赛", "毕业生（毕业5年内）", "大四", "软件工程", 2, 8, ["Python"]),
]


def no_score(payload):
    score = payload.get("score") or {}
    return score.get("total") is None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("all", "non-qa"), default="all")
    parser.add_argument("--output", type=Path, help="Save a new run without replacing historical results")
    args = parser.parse_args()
    non_qa = args.scope == "non-qa"
    cases = []
    accounts = {}
    recommendation_counts = {}
    with TemporaryDirectory(prefix="campus-simulated-users-", ignore_cleanup_errors=True) as workspace:
        os.environ.update({
            "DATABASE_URL": "sqlite:///" + workspace.replace("\\", "/") + "/simulation.db",
            "RAG_USE_ST": "0", "AGENT_LLM": "0", "AGENT_LLM_API_KEY": "",
            "WEB_SEARCH_PROVIDER": "none", "WEB_SEARCH_API_KEY": "",
            "ADMIN_API_TOKEN": "simulation-isolated-admin",
            "AUTH_TOKEN_SECRET": "simulation-isolated-session",
        })
        sys.path.insert(0, str(ROOT / "src"))
        from fastapi.testclient import TestClient
        import api
        import db
        import agent.graph as graph
        from evaluation_provenance import code_sha256, dataset_sha256, competition_snapshot_sha256
        from trust import assess_source_readiness, assess_recommendation_readiness

        def record(case_id, persona, group, scenario, response, checks, elapsed=0):
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            assertions = [{"expectation": text, "passed": bool(value)} for text, value in checks]
            entry = {
                "id": case_id, "persona": persona, "group": group,
                "scenario": scenario, "status_code": response.status_code,
                "elapsed_ms": round(elapsed * 1000, 2),
                "passed": all(item["passed"] for item in assertions),
                "assertions": assertions, "response": payload,
            }
            cases.append(entry)
            print(f"{case_id}: {'PASS' if entry['passed'] else 'FAIL'} {scenario}", flush=True)
            return payload

        with ExitStack() as stack:
            for module in (api, db, graph):
                stack.enter_context(patch.object(module, "contest_now", return_value=NOW))
            client = stack.enter_context(TestClient(api.app))
            competitions = db.get_all_competitions()
            comp_map = {c.competition_id: c for c in competitions}
            candidate = next(c for c in competitions if not assess_source_readiness(c).ready
                             and c.registration_deadline and c.registration_deadline > NOW.date()
                             and c.official_source_status == "found")
            expired = next(c for c in competitions if assess_source_readiness(c).ready
                           and c.registration_deadline and c.registration_deadline < NOW.date())
            data_summary = {
                "total": len(competitions),
                "source_complete": sum(assess_source_readiness(c).ready for c in competitions),
                "registerable_complete": sum(assess_recommendation_readiness(c, NOW).ready for c in competitions),
                "candidate_test_id": candidate.competition_id,
                "expired_test_id": expired.competition_id,
            }
            fingerprints = {
                "dataset_sha256": dataset_sha256(ROOT), "code_sha256": code_sha256(ROOT),
                "competition_snapshot_sha256": competition_snapshot_sha256(competitions),
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            }

            for pid, label, education, grade, major, size, hours, skills in PERSONAS:
                if education == "毕业生（毕业5年内）":
                    grade = "已毕业"
                uid = "sim_" + pid
                password = "isolated-simulation-password"
                registered = client.post("/api/auth/register", json={
                    "username": uid, "password": password, "display_name": label,
                })
                if registered.status_code != 200:
                    raise RuntimeError(f"Registration failed for {uid}")
                login = client.post("/api/auth/login", json={"username": uid, "password": password})
                login.raise_for_status()
                headers = {"Authorization": "Bearer " + login.json()["access_token"]}
                profile = {
                    "user_id": uid, "education_level": education, "grade": grade,
                    "major": major, "skills": skills, "experiences": [],
                    "weekly_available_hours": hours, "expected_team_size": size,
                    "privacy_consent": True,
                }
                response = client.post(f"/api/users/{uid}/profile", json=profile, headers=headers)
                record(f"ON-{pid}", pid, "onboarding", label + "保存真实学籍画像", response,
                       [("画像保存成功且没有把学历/年级转换成别的值", response.status_code == 200
                         and response.json().get("grade") == grade
                         and response.json().get("education_level") == education)])
                accounts[pid] = (uid, headers, profile)
                if response.status_code == 200:
                    reco = client.get(f"/api/users/{uid}/recommendations", headers=headers)
                    recommendation_counts[pid] = len(reco.json())
                    record(f"RE-{pid}", pid, "safety", label + "查看个性化推荐", reco, [
                        ("推荐接口正常返回", reco.status_code == 200),
                        ("所有推荐均证据完整、可报名且有分数", all(
                            assess_recommendation_readiness(comp_map[r["competition_id"]], NOW).ready
                            and r.get("eligible") and r.get("score") is not None for r in reco.json())),
                    ])

            def ask(cid, pid, question, expectation, condition, competition_id=None, group="conversation"):
                if non_qa:
                    return None
                uid, headers, _ = accounts[pid]
                params = {"question": question, "user_id": uid, "top_k": 4}
                if competition_id:
                    params["competition_id"] = competition_id
                elif conversation_context.get(pid):
                    params["context_competition_id"] = conversation_context[pid]
                started = perf_counter()
                response = client.get("/api/agent/ask", params=params, headers=headers)
                payload = response.json()
                conversation_context[pid] = payload.get("resolved_competition")
                identity = lambda c: (c.get("field"), c.get("page"), c.get("source_text"), c.get("source_url"))
                target = comp_map.get(payload.get("resolved_competition"))
                source_comps = [target] if target else [comp_map[r["competition_id"]]
                    for r in payload.get("recommendations", [])]
                known = {identity(e.model_dump(mode="json")) for c in source_comps for e in c.evidence}
                checks = [("问答接口正常返回", response.status_code == 200),
                          (expectation, condition(payload)),
                          ("引用原文与锁定赛事已有证据一致，不串赛", all(
                              identity(c) in known for c in payload.get("citations", [])))]
                return record(cid, pid, group, question, response, checks, perf_counter() - started)

            conversation_context = {}
            ask("QA-01", "p01", NAME + "报名最晚是哪天几点？",
                "回答10月23日12:00而非春季赛日期", lambda p: p.get("resolved_competition") == TARGET
                and "12:00" in p.get("answer", "") and "2026" in p.get("answer", ""))
            ask("QA-02", "p01", "这个比赛几个人一队？",
                "自然追问沿用上一问大数据赛，回答1至3人", lambda p: p.get("resolved_competition") == TARGET
                and "3" in p.get("answer", ""))
            ask("QA-03", "p01", "报名还来得及吗？",
                "自然追问沿用上文赛事，明确当前仍可报名", lambda p: p.get("resolved_competition") == TARGET
                and p.get("gate", {}).get("eligible") is True)
            ask("QA-04", "p01", "这个比赛要交哪些东西？",
                "显式选定赛事后能回答论文、数据集和源码", lambda p: all(
                    word in p.get("answer", "") for word in ("论文", "数据集", "代码")), TARGET)
            ask("QA-05", "p01", "MathorCup大数据今年怎么报名？",
                "自然简称不会错锁春季赛，并标明版本", lambda p: p.get("resolved_competition") == TARGET
                and "2026" in p.get("answer", ""))
            ask("QA-06", "p01", "蓝桥杯什么时候报名？",
                "多年份查询澄清或明确标明年份/版本", lambda p: any(
                    word in p.get("answer", "") for word in ("年份", "版本", "2026", "2027")))
            ask("QA-07", "p02", NAME + "英语专业也可以参加吗？",
                "明确不限专业或允许英语专业，附官方依据", lambda p: any(
                    word in p.get("answer", "") for word in ("不限专业", "跨专业", "专业不限制")))
            ask("QA-08", "p02", NAME + "我一个人能报吗？",
                "单人参赛回答与1至3人的官方范围一致", lambda p: p.get("gate", {}).get("eligible") is True
                and "1" in p.get("answer", "") and "3" in p.get("answer", ""))
            ask("QA-09", "p02", "我英语专业不会编程，每周只能花六小时，你推荐什么？",
                "推荐或空结果解释不会把候选赛当正式结果", lambda p: all(
                    r.get("score") is not None and assess_recommendation_readiness(
                        comp_map[r["competition_id"]], NOW).ready for r in p.get("recommendations", [])), group="safety")
            ask("QA-10", "p03", NAME + "我们四个人，可以一起参赛吗？",
                "超过3人被明确门控，不评分", lambda p: p.get("gate", {}).get("eligible") is False
                and no_score(p) and any(w in p.get("answer", "") for w in ("超过", "上限", "不符合")), group="safety")
            ask("QA-11", "p01", NAME + "现在我们改成四个人了，还能报名吗？",
                "当前发言与旧画像冲突时不能仍肯定有资格", lambda p: p.get("gate", {}).get("eligible") is not True
                or any(w in p.get("answer", "") for w in ("修改画像", "更新画像", "超过上限")))
            ask("QA-12", "p05", NAME + "我在高职读大二，属于大专在读，能报吗？",
                "不因高职/专科标签差异直接错误拒绝，至少解释待确认", lambda p: not any(
                    "学历层次不符合" in str(r) for r in p.get("gate", {}).get("reasons", []))
                or any(w in p.get("answer", "") for w in ("专科身份", "学历对应", "学历映射")))
            ask("QA-13", "p06", NAME + "毕业两年了还可以参加吗？",
                "非在读学生被拒绝且不评分", lambda p: p.get("gate", {}).get("eligible") is False
                and no_score(p), group="safety")
            ask("QA-14", "p01", candidate.competition_name + "我符合报名条件吗？",
                "候选赛事不输出确定资格和分数", lambda p: p.get("gate", {}).get("eligible") is not True
                and no_score(p) and any(w in p.get("answer", "") for w in ("候选", "证据待", "不足")),
                candidate.competition_id, "safety")
            ask("QA-15", "p01", expired.competition_name + "还能报名吗？",
                "已截止赛事明确拒绝推荐、无分数", lambda p: p.get("gate", {}).get("eligible") is False
                and no_score(p) and "截止" in p.get("answer", ""), expired.competition_id, "safety")
            ask("QA-16", "p01", "推荐三个现在能报名的编程或设计比赛给我",
                "数据不足也不凑数、不混入候选赛", lambda p: all(
                    r.get("score") is not None and assess_recommendation_readiness(
                        comp_map[r["competition_id"]], NOW).ready for r in p.get("recommendations", [])), group="safety")
            ask("QA-17", "p01", "明年宇宙高校创新杯报名要多少钱？",
                "不存在的赛事应拒答或确认，不能擅自锁定另一赛事", lambda p: not p.get("resolved_competition")
                and not p.get("citations") and no_score(p), group="safety")
            ask("QA-18", "p01", NAME + "需要交多少钱？",
                "有费用原文则准确回答200元，无字段证据则说明不能确认", lambda p: "200" in p.get("answer", "")
                or any(w in p.get("answer", "") for w in ("无法确认", "没有", "不足", "未提取", "待确认")))
            ask("QA-19", "p01", NAME + "的报名截止和比赛结束分别是什么时候？",
                "复合问题同时回答报名截止及初赛结束，不混淆", lambda p: "12:00" in p.get("answer", "")
                and "20:00" in p.get("answer", ""))
            ask("QA-20", "p01", "可以跨校和跨专业组队吗？",
                "选定大数据赛后回答跨校/跨专业并附依据", lambda p: "跨校" in p.get("answer", "")
                and "跨专业" in p.get("answer", ""), TARGET)
            ask("QA-21", "p01", "MathorCup春季赛和大数据竞赛的截止日期一样吗？",
                "明确独立赛项或追问两个版本，不能给单赛日期冒充比较", lambda p: any(
                    w in p.get("answer", "") for w in ("独立", "分别", "两项", "请选择", "请明确", "赛项", "多个赛事")))
            ask("QA-22", "p06", "帮我为这个比赛写个组队招募，我已经毕业两年了",
                "资格不符时不直接生成可参赛招募", lambda p: "我们正在为" not in p.get("answer", "")
                or any(w in p.get("answer", "") for w in ("暂不符合", "不满足参赛", "无法参赛")), TARGET)
            ask("QA-23", "p01", "帮我为这个比赛制定一周备赛计划",
                "计算机候选赛不套机械长周期模板，且保留候选风险提示", lambda p: not any(
                    w in p.get("answer", "") for w in ("机械/工程备赛", "机械/结构方向"))
                and any(w in p.get("answer", "") for w in ("候选", "关键证据", "不构成资格")),
                candidate.competition_id)

            for pid in ("p03", "p05", "p06"):
                uid, headers, _ = accounts[pid]
                response = client.post(f"/api/users/{uid}/projects", headers=headers,
                                       json={"competition_id": TARGET})
                expected = 200 if pid == "p05" else 409
                scenario = "专科同义学历可创建项目，超人数及毕业生被拦截"
                record("JOIN-" + pid, pid, "workflow", scenario, response,
                       [("按真实学历和团队条件校验项目创建", response.status_code == expected)])

            uid, headers, original = accounts["p01"]
            response = client.post(f"/api/users/{uid}/tasks/from-agent", headers=headers,
                json={"competition_id": candidate.competition_id, "title": "候选赛计划转任务"})
            record("TASK-CAND", "p01", "safety", "候选赛事问答不能创建正式执行任务", response,
                   [("后端拒绝创建候选赛任务", response.status_code == 409)])
            for case_id, comp in (("JOIN-CAND", candidate), ("JOIN-EXPIRED", expired)):
                response = client.post(f"/api/users/{uid}/projects", headers=headers,
                                       json={"competition_id": comp.competition_id})
                record(case_id, "p01", "safety", "阻止创建候选/已截止赛事项目", response,
                       [("拒绝创建项目", response.status_code == 409)])
            response = client.post(f"/api/users/{uid}/projects", headers=headers, json={"competition_id": TARGET})
            created = record("FLOW-01", "p01", "workflow", "正式推荐赛事加入我的项目", response,
                             [("成功创建项目", response.status_code == 200)])
            record("FLOW-PLAN", "p01", "workflow", "新项目自动计划不应一创建就逾期", response,
                   [("未完成的新任务日期不得早于创建日，或应注明历史节点", all(
                       not item.get("due_date") or item["due_date"] >= NOW.date().isoformat()
                       for item in created.get("items", [])))])
            project_path = f"/api/users/{uid}/projects/{created['project_id']}"
            task = client.post(project_path + "/items", headers=headers, json={
                "item_type": "task", "title": "确认队员并完成报名", "due_date": "2026-10-20"})
            task_data = record("FLOW-02", "p01", "workflow", "添加报名准备任务", task,
                               [("任务持久化成功", task.status_code == 200)])
            dependent = client.post(project_path + "/items", headers=headers, json={
                "item_type": "material", "title": "报名提交记录", "depends_on_item_id": task_data["item_id"]})
            dependent_data = record("FLOW-03", "p01", "workflow", "添加带前置任务的材料", dependent,
                                    [("材料保存成功", dependent.status_code == 200)])
            blocked = client.patch(project_path + f"/items/{dependent_data['item_id']}", headers=headers,
                                   json={"status": "done"})
            record("FLOW-04", "p01", "workflow", "前置未完成不能直接完成依赖材料", blocked,
                   [("依赖检查拦截", blocked.status_code == 409)])
            done = client.patch(project_path + f"/items/{task_data['item_id']}", headers=headers, json={"status": "done"})
            record("FLOW-05", "p01", "workflow", "完成任务", done, [("任务变为已完成", done.status_code == 200
                   and done.json().get("status") == "done")])
            done = client.patch(project_path + f"/items/{dependent_data['item_id']}", headers=headers, json={"status": "done"})
            record("FLOW-06", "p01", "workflow", "前置完成后完成材料", done,
                   [("材料完成成功", done.status_code == 200)])
            calendar = client.get(project_path + "/calendar.ics", headers=headers)
            record("FLOW-07", "p01", "workflow", "导出ICS且准确保留报名截止时刻", calendar,
                   [("导出正常且10月23日12:00+08转换为04:00Z", calendar.status_code == 200
                     and "DTSTART:20261023T040000Z" in calendar.text and "BEGIN:VCALENDAR" in calendar.text)])
            changed = dict(original, expected_team_size=4)
            response = client.post(f"/api/users/{uid}/profile", headers=headers, json=changed)
            reco = client.get(f"/api/users/{uid}/recommendations", headers=headers)
            record("FLOW-08", "p01", "workflow", "画像改为4人后正式推荐立即消失", reco,
                   [("保存更新成功且不再推荐大数据赛", response.status_code == 200
                     and all(r["competition_id"] != TARGET for r in reco.json()))])
            if non_qa:
                projects = client.get(f"/api/users/{uid}/projects", headers=headers)
                record("FLOW-WARNING", "p01", "workflow", "画像变化保留已有项目并提示资格风险", projects,
                       [("原项目被保留且失去正式资格", any(p["project_id"] == created["project_id"]
                         and not p["recommendation_ready"] and p["readiness_reasons"] for p in projects.json()))])
                eligibility = client.get(f"/api/users/{uid}/competitions/{TARGET}/eligibility", headers=headers)
                record("JOIN-READINESS", "p01", "safety", "详情加入按钮使用当前个人资格", eligibility,
                       [("四人画像不允许加入", eligibility.status_code == 200 and not eligibility.json()["can_create_project"])])
            deleted = client.delete(project_path, headers=headers)
            record("FLOW-09", "p01", "workflow", "删除项目", deleted,
                   [("项目被删除且不可再读取", deleted.status_code == 200
                     and all(p["project_id"] != created["project_id"] for p in
                             client.get(f"/api/users/{uid}/projects", headers=headers).json()))])
            deleted = client.delete(f"/api/users/{uid}/profile", headers=headers)
            record("FLOW-10", "p01", "privacy", "删除画像并拒绝后续个性化访问", deleted,
                   [("画像已删除", deleted.status_code == 200
                     and client.get(f"/api/users/{uid}/profile", headers=headers).status_code == 404)])
            uid, headers, profile = accounts["p02"]
            response = client.post(f"/api/users/{uid}/profile", headers=headers, json=dict(profile, privacy_consent=False))
            record("PRIV-01", "p02", "privacy", "未授权不能保存画像", response,
                   [("隐私授权缺失被拒绝", response.status_code == 403)])
            other = accounts["p06"][0]
            response = client.get(f"/api/users/{other}/profile", headers=headers)
            record("PRIV-02", "p02", "privacy", "尝试访问另一个学生的画像", response,
                   [("不能越权读取他人画像", response.status_code == 403)])
            for readiness in ("all", "ready", "candidate"):
                response = client.get("/api/competitions", params={"readiness": readiness})
                payload = response.json()
                record("CAT-" + readiness, "anonymous", "catalog", "赛事目录筛选" + readiness, response,
                       [("目录返回正常且标签与筛选一致", response.status_code == 200 and all(
                           readiness == "all" or bool(c["recommendation_ready"]) == (readiness == "ready")
                           for c in payload))])
        db.get_engine().dispose()

    groups = {}
    for case in cases:
        totals = groups.setdefault(case["group"], {"passed": 0, "total": 0})
        totals["total"] += 1
        totals["passed"] += int(case["passed"])
    result = {
        "evaluation_type": "automated_journeys_owner_confirmed_real_profiles",
        "profile_provenance": json.loads((ROOT / "evals/user_profile_provenance.json").read_text(encoding="utf-8")),
        "executed_at": datetime.now().astimezone().isoformat(),
        "fixed_business_time": NOW.isoformat(),
        "mode": "offline_rules_testclient_temporary_sqlite",
        "scope": args.scope,
        "limitations": ["画像来自真人数据（负责人确认），执行为自动复测，不包含亲自操作记录、满意度或推广调查", "未使用在线大模型或联网搜索",
                        "耗时为本机进程内API调用，非线上网络体验", "未验证每个官方链接当前可访问性",
                        "自然语言预期由本轮评测者预先定义，不是独立标注集"],
        "data": data_summary,
        "fingerprints": fingerprints,
        "personas": [{"id": p[0], "description": p[1], "education_level": p[2], "grade": "已毕业" if p[0] == "p06" else p[3],
                     "team_size": p[5]} for p in PERSONAS],
        "recommendation_counts": recommendation_counts,
        "summary": {"passed": sum(c["passed"] for c in cases), "total": len(cases), "groups": groups},
        "cases": cases,
    }
    destination = args.output or ROOT / "evals" / ("nonqa_user_results.json" if non_qa else "simulated_user_results.json")
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False), flush=True)
    print(str(destination), flush=True)
    if result["summary"]["passed"] != result["summary"]["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
