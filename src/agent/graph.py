"""LangGraph Agent 闭环 —— 意图路由 → 隔离检索 → 门控 → 评分 → 组队文案。

设计目标（对应修订方案「亮点：Agent 编排」）：
  - 用 LangGraph StateGraph 把已有的四个能力模块串成一个可解释的闭环：
        route_intent   意图路由（判断用户想干什么、锁定目标赛事）
        retrieve       赛事隔离检索（rag.store，强制 competition_id 隔离）
        gate           硬性门控（recommendation.engine.eligibility_gate）
        score          软性评分（recommendation.engine.soft_match_score）
        team_copy      组队招募文案生成（基于赛事字段 + 检索证据）
        recommend_all  全库门控+评分推荐（recommend intent 专用）
        compose        组装最终答案，**自动附带引用证据**
  - 「让问答自动带引用」：任何回答都在 state["citations"] 中携带来源，
    compose 节点把引用编号嵌入答案文本（[1][2]…），前端可渲染角标。
  - 离线可运行：不依赖任何外部 LLM Key。意图路由用规则 + 最长公共子串
    锁定赛事；答案用确定性模板生成。若配置了 LLM（设 AGENT_LLM_API_KEY，
    可选 AGENT_LLM_BASE_URL 指向任意 OpenAI 兼容端点），compose / team_copy
    会调用 LLM 对模板润色，但引用与门控结论始终来自本地可信数据，不被模型改写
    （润色后做引用标记校验，破坏 [n] 编号则自动回退原稿）。详见 src/agent/llm.py。

执行轨迹：state["trace"] 记录每个节点，前端可展示「意图→检索→门控→评分→文案」。
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional, TypedDict

# 允许脚本直接运行（python agent/graph.py）或模块运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 优先使用真实 langgraph；无法安装（如受限环境内存不足）时降级到内置等价引擎，
# 保证离线可运行、对外 API 与行为不变。
try:  # pragma: no cover - 依赖可选
    from langgraph.graph import END, START, StateGraph  # type: ignore
    _USING_LANGGRAPH = True
except Exception:  # noqa: BLE001
    from agent._graph_shim import END, START, StateGraph  # type: ignore
    _USING_LANGGRAPH = False

import db
from fact_formatting import format_team_size
from rag.store import get_rag
from recommendation.engine import (
    data_validity_check,
    eligibility_gate,
    recommend_for_user,
    soft_match_score,
)
from schemas import Citation, Competition, UserProfile


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    # 输入
    question: str
    user_id: Optional[str]
    competition_id: Optional[str]     # 可由前端直接指定，否则路由自动锁定
    top_k: int

    # 路由结果
    intent: str                       # qa | detail | recommend | team | unknown
    resolved_competition: Optional[str]
    resolved_name: Optional[str]
    version_resolution_note: Optional[str]
    clarification: Optional[str]

    # 中间产物
    profile: Optional[dict]
    citations: list[dict]             # 序列化后的 Citation（供 API/前端）
    gate: dict
    score: dict
    recommendations: list[dict]
    team_copy: str

    # 输出
    answer: str
    pending_review: bool
    trace: list[str]


# ---------------------------------------------------------------------------
# 工具：赛事锁定（最长公共子串 + 别名）
# ---------------------------------------------------------------------------

_GENERIC_TOKENS = ["大赛", "竞赛", "大学生", "全国", "中国", "比赛", "杯", "赛"]


def _norm(s: str) -> str:
    """归一化：全角→半角、空白压缩，让「互联网＋」与「互联网+」可匹配。"""
    if not s:
        return ""
    s = s.replace("＋", "+").replace("—", "-").replace("，", ",").replace("。", ".")
    return " ".join(s.split())


def _lcs_len(a: str, b: str) -> int:
    """最长公共子串长度（用于赛事名模糊匹配）。"""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0
    m, n = len(a), len(b)
    prev = [0] * (n + 1)
    best = 0
    for i in range(1, m + 1):
        cur = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def _competition_match_score(question: str, competition: Competition) -> float:
    q = _norm(question)
    c = competition
    name = c.competition_name or ""
    core = name
    for token in _GENERIC_TOKENS:
        core = core.replace(token, "")
    core = "".join(ch for ch in core if not ch.isdigit()).strip()
    if name and name in q:
        return 10 + len(name)
    if core and core in q:
        return 8 + len(core)
    if c.competition_id and c.competition_id in q:
        return 6
    lcs = _lcs_len(q, name)
    return 3 + lcs if lcs >= 3 else 0


def _resolve_competition_versioned(
    question: str, comps: list[Competition]
) -> tuple[Optional[Competition], Optional[str], Optional[str]]:
    """锁定赛事并显式处理同名多年份版本。"""
    q = _norm(question)
    mentioned_years = {int(y) for y in re.findall(r"20\d{2}", q)}
    scored = [(c, _competition_match_score(q, c)) for c in comps]
    scored = [(c, score) for c, score in scored if score >= 4]
    if not scored:
        return None, None, None

    if mentioned_years:
        year_matches = [(c, score) for c, score in scored if c.document_year in mentioned_years]
        if year_matches:
            selected = max(year_matches, key=lambda item: item[1])[0]
            return selected, None, None

    best = max(scored, key=lambda item: item[1])[0]
    same_name = [c for c, _ in scored if _norm(c.competition_name) == _norm(best.competition_name)]
    if len(same_name) == 1:
        return best, None, None

    verified = [c for c in same_name if c.data_status.value == "verified"]
    years = "、".join(str(c.document_year) for c in sorted(same_name, key=lambda item: item.document_year, reverse=True))
    if verified:
        selected = max(verified, key=lambda item: item.document_year)
        note = f"你没有指定年份，以下使用最新已核验版本：{selected.document_year}年（{selected.doc_version}）。"
        return selected, note, None
    clarification = f"“{best.competition_name}”存在多个年份版本（{years}），且暂无已核验版本。请明确年份后再查询。"
    return None, None, clarification


def _resolve_competition(question: str, comps: list[Competition]) -> Optional[Competition]:
    """从问题里锁定最匹配的赛事；无明显匹配返回 None。

    打分优先级：完整名子串命中 > 核心名子串命中 > 赛事ID子串命中，
    再叠加年份加权，避免「互联网+」被「蓝桥杯」的 LCS 噪声抢走。
    """
    return _resolve_competition_versioned(question, comps)[0]


# ---------------------------------------------------------------------------
# 工具：意图判定（规则）
# ---------------------------------------------------------------------------

_KW_RECOMMEND = ["推荐", "适合我", "适合参加", "该参加", "选哪个", "报哪个", "有什么比赛", "参加什么"]
_KW_TEAM = ["组队", "招募", "招新", "招人", "队友", "文案", "招队友", "找队友", "队员"]
_KW_DETAIL = ["介绍", "详情", "是什么", "概况", "简介", "了解一下"]


def _classify_intent(question: str, has_comp: bool) -> str:
    q = question
    if any(k in q for k in _KW_TEAM):
        return "team"
    if any(k in q for k in _KW_RECOMMEND):
        return "recommend"
    if has_comp and any(k in q for k in _KW_DETAIL):
        return "detail"
    if has_comp:
        return "qa"          # 指向具体赛事的问题，默认走规则问答（检索带引用）
    return "unknown"


# ---------------------------------------------------------------------------
# 工具：Citation 序列化 / 引用编号
# ---------------------------------------------------------------------------


def _cite_dict(c: Citation) -> dict:
    return c.model_dump(mode="json")


def _cite_marker(idx: int) -> str:
    return f"[{idx + 1}]"


def _asks_registration_deadline(question: str) -> bool:
    """识别报名截止问法，交给结构化日期做唯一事实源。"""
    text = (question or "").strip().lower()
    asks_registration = "报名" in text
    asks_time = any(word in text for word in ("截止", "日期", "时间", "什么时候", "哪天"))
    return asks_registration and asks_time


def _asks_team_size(question: str) -> bool:
    """识别团队人数问法，优先返回对应结构化字段及页级证据。"""
    text = (question or "").strip().lower()
    asks_team = any(word in text for word in ("团队", "队伍", "组队", "队员"))
    asks_size = any(word in text for word in ("几人", "人数", "多少人", "规模"))
    return asks_team and asks_size


# ---------------------------------------------------------------------------
# 工具：可选 LLM 润色（默认关闭，不影响引用与门控结论）
# ---------------------------------------------------------------------------


def _llm_polish(draft: str, context: str) -> str:
    """若启用 LLM，则对确定性草稿做自然语言润色；否则原样返回。

    仅润色措辞，绝不改写引用编号、门控结论与数值——这些来自本地可信数据。
    实现见 src/agent/llm.py（OpenAI 兼容，含引用安全校验与优雅回退）。
    """
    from agent.llm import polish as _polish

    out = _polish(draft, context)
    return out if out else draft


# ---------------------------------------------------------------------------
# 节点 1：意图路由
# ---------------------------------------------------------------------------


def node_route_intent(state: AgentState) -> AgentState:
    question = (state.get("question") or "").strip()
    trace = list(state.get("trace") or [])

    comps = db.get_all_competitions()

    # 优先使用前端显式指定的赛事
    resolved: Optional[Competition] = None
    version_note: Optional[str] = None
    clarification: Optional[str] = None
    if state.get("competition_id"):
        resolved = db.get_competition(state["competition_id"])
    if resolved is None:
        resolved, version_note, clarification = _resolve_competition_versioned(question, comps)

    intent = _classify_intent(question, has_comp=resolved is not None)
    trace.append(
        f"意图路由：intent={intent}"
        + (f"，锁定赛事={resolved.competition_name}" if resolved else "，未锁定具体赛事")
    )

    return {
        **state,
        "intent": intent,
        "resolved_competition": resolved.competition_id if resolved else None,
        "resolved_name": resolved.competition_name if resolved else None,
        "version_resolution_note": version_note,
        "clarification": clarification,
        "trace": trace,
    }


# ---------------------------------------------------------------------------
# 节点 2：赛事隔离检索
# ---------------------------------------------------------------------------


def _detail_fallback_citations(comp: Optional[Competition]) -> list[Citation]:
    """detail 意图兜底：介绍/详情类问句的关键词不在赛事数据中，关键词重叠检索
    易召回为空。此时用赛事「结构化关键字段」兜底，保证「介绍一下X」也带官方
    引用（团队/参赛对象/截止/材料/技能），避免答案回退成"未检索到相关条款"。"""
    if comp is None:
        return []
    out: list[Citation] = []
    doc = f"{comp.competition_name}_{comp.document_year}_官方通知"

    def _add(field: str, text: str) -> None:
        out.append(
            Citation(
                field=field,
                page=None,
                source_text=text,
                document_name=doc,
                source_url=comp.official_source_url,
                acquired_date=comp.source_acquired_date,
                last_verified_at=comp.last_verified_at,
                trusted_level=comp.trusted_level,
            )
        )

    if comp.team_min is not None or comp.team_max is not None:
        _add("team_max", f"团队人数要求：{format_team_size(comp.team_min, comp.team_max)}。")
    if comp.eligible_students:
        _add("eligible_students", f"参赛对象：{'、'.join(getattr(s, 'value', str(s)) for s in comp.eligible_students)}。")
    if comp.registration_deadline:
        _add("registration_deadline", f"报名截止时间：{comp.registration_deadline}。")
    if comp.submission_deadline:
        _add("submission_deadline", f"提交截止时间：{comp.submission_deadline}。")
    if comp.required_materials:
        _add("required_materials", f"所需材料：{'、'.join(comp.required_materials)}。")
    if comp.required_skills:
        _add("required_skills", f"所需技能：{'、'.join(comp.required_skills)}。")
    return out


def node_retrieve(state: AgentState) -> AgentState:
    trace = list(state.get("trace") or [])
    cid = state.get("resolved_competition")
    if not cid:
        trace.append("隔离检索：跳过（无目标赛事）")
        return {**state, "citations": [], "trace": trace}

    comp = db.get_competition(cid)
    top_k = int(state.get("top_k") or 4)
    hits = get_rag().query(
        cid,
        state.get("question") or "",
        document_year=comp.document_year if comp else None,
        top_k=top_k,
    )
    # 截止日期只能由结构化 Ground Truth 给出；RAG 仅返回同字段的一条页级证据。
    # 这样既保留可追溯原文，又不会把报名开始日、校赛日或提交日误写成第二个截止日。
    if comp is not None and _asks_registration_deadline(state.get("question") or ""):
        deadline_evidence = [e for e in comp.evidence if e.field == "registration_deadline"]
        if deadline_evidence:
            hits = deadline_evidence[:1]
        else:
            deadline_text = comp.registration_deadline.isoformat() if comp.registration_deadline else "未明确"
            hits = [
                Citation(
                    field="registration_deadline",
                    page=None,
                    source_text=f"报名截止日期：{deadline_text}。",
                    document_name=f"{comp.competition_name}_{comp.document_year}_官方通知",
                    source_url=comp.official_source_url,
                    acquired_date=comp.source_acquired_date,
                    last_verified_at=comp.last_verified_at,
                    trusted_level=comp.trusted_level,
                )
            ]
        trace.append("隔离检索：报名截止问题仅保留 registration_deadline 单一证据")
    if (
        comp is not None
        and state.get("intent") == "qa"
        and _asks_team_size(state.get("question") or "")
    ):
        team_evidence = [e for e in comp.evidence if e.field in {"team_min", "team_max"}]
        if team_evidence:
            hits = team_evidence[:top_k]
        else:
            hits = [
                Citation(
                    field="team_max" if comp.team_max is not None else "team_min",
                    page=None,
                    source_text=f"团队人数要求：{format_team_size(comp.team_min, comp.team_max)}。",
                    document_name=f"{comp.competition_name}_{comp.document_year}_官方通知",
                    source_url=comp.official_source_url,
                    acquired_date=comp.source_acquired_date,
                    last_verified_at=comp.last_verified_at,
                    trusted_level=comp.trusted_level,
                )
            ]
        trace.append("隔离检索：团队人数问题仅保留 team_min/team_max 对应证据")
    # detail 介绍类：保证「介绍一下X」始终带完整官方结构化引用。
    # 语义/关键词检索为空 → 整段兜底；检索有结果 → 在其基础上补全缺失关键字段。
    if state.get("intent") == "detail" and not _asks_registration_deadline(state.get("question") or ""):
        if not hits:
            hits = _detail_fallback_citations(comp)
            trace.append("隔离检索：detail 兜底返回关键字段证据")
        else:
            existing = {getattr(h, "field", None) for h in hits}
            extra = [c for c in _detail_fallback_citations(comp) if c.field not in existing]
            if extra:
                hits = list(hits) + extra
                trace.append(f"隔离检索：detail 补全 {len(extra)} 条关键字段证据")
    trace.append(f"隔离检索：collection=rag_{cid}，命中 {len(hits)} 条证据")
    return {
        **state,
        "citations": [_cite_dict(h) for h in hits],
        "trace": trace,
    }


# ---------------------------------------------------------------------------
# 节点 3：硬性门控
# ---------------------------------------------------------------------------


def _load_profile(state: AgentState) -> Optional[UserProfile]:
    uid = state.get("user_id")
    if not uid:
        return None
    return db.get_user_profile(uid)


def node_gate(state: AgentState) -> AgentState:
    trace = list(state.get("trace") or [])
    cid = state.get("resolved_competition")
    profile = _load_profile(state)
    comp = db.get_competition(cid) if cid else None
    pending_review = bool(comp and comp.data_status.value == "unverified")
    if comp is None or profile is None:
        trace.append("硬性门控：跳过（缺用户画像或赛事）")
        return {**state, "gate": {"skipped": True}, "pending_review": pending_review, "trace": trace}

    today = date.today()
    problems = data_validity_check(comp, today)
    if problems:
        gate = {"eligible": False, "reasons": [f"数据不可用：{p}" for p in problems]}
        trace.append("硬性门控：数据有效性未通过")
        return {**state, "gate": gate, "pending_review": comp.data_status.value == "unverified", "trace": trace}

    eligible, reasons = eligibility_gate(profile, comp, today)
    gate = {
        "eligible": eligible,
        "reasons": [r.reason for r in reasons],
        "actions": [r.possible_action for r in reasons if r.possible_action],
    }
    trace.append(f"硬性门控：{'通过' if eligible else '一票否决'}（{len(reasons)} 条原因）")
    return {
        **state,
        "gate": gate,
        "pending_review": comp.data_status.value == "unverified",
        "trace": trace,
    }


# ---------------------------------------------------------------------------
# 节点 4：软性评分
# ---------------------------------------------------------------------------


def node_score(state: AgentState) -> AgentState:
    trace = list(state.get("trace") or [])
    cid = state.get("resolved_competition")
    profile = _load_profile(state)
    gate = state.get("gate") or {}

    if not cid or profile is None:
        trace.append("软性评分：跳过（缺用户画像或赛事）")
        return {**state, "score": {"skipped": True}, "trace": trace}
    if gate.get("eligible") is False:
        trace.append("软性评分：跳过（门控未通过，不进入评分）")
        return {**state, "score": {"skipped": True, "reason": "门控未通过"}, "trace": trace}

    comp = db.get_competition(cid)
    bd = soft_match_score(profile, comp, date.today())
    trace.append(f"软性评分：总分 {bd.total}（S{bd.skill_score}/E{bd.experience_score}/R{bd.resource_score}/W{bd.workload_score}）")
    return {**state, "score": bd.model_dump(mode="json"), "trace": trace}


# ---------------------------------------------------------------------------
# 节点 5：组队招募文案
# ---------------------------------------------------------------------------


def node_team_copy(state: AgentState) -> AgentState:
    trace = list(state.get("trace") or [])
    cid = state.get("resolved_competition")
    if not cid:
        trace.append("组队文案：跳过（无目标赛事）")
        return {**state, "team_copy": "", "trace": trace}

    comp = db.get_competition(cid)
    profile = _load_profile(state)
    citations = state.get("citations") or []

    team_txt = format_team_size(comp.team_min, comp.team_max)
    skills = "、".join(comp.required_skills) if comp.required_skills else "相关技能不限"
    deadline = comp.registration_deadline.isoformat() if comp.registration_deadline else "以官方通知为准"
    my_skills = "、".join(profile.skills) if profile and profile.skills else "（可在个人画像补充）"

    # 引用编号：把 team/skill 相关证据映射到 [n]
    def _mark_for(field_key: str) -> str:
        for i, c in enumerate(citations):
            if c.get("field") in field_key:
                return _cite_marker(i)
        return ""

    team_mark = _mark_for(("team_max", "team_min"))
    skill_mark = _mark_for(("required_skills",))
    reg_mark = _mark_for(("registration_deadline",))

    copy = (
        f"【{comp.competition_name}（{comp.document_year}）· 组队招募】\n\n"
        f"🚀 我们正在为「{comp.competition_name}」组队，诚招志同道合的队友！\n\n"
        f"· 队伍规模：{team_txt}{team_mark}\n"
        f"· 需要能力：{skills}{skill_mark}\n"
        f"· 报名截止：{deadline}{reg_mark}\n"
        f"· 我能带来：{my_skills}\n\n"
        f"如果你对{('、'.join(comp.evaluation_dimensions) if comp.evaluation_dimensions else '这项赛事')}感兴趣，"
        f"欢迎私信我一起冲！报名信息以官方通知为准。"
    )
    if comp.data_status.value == "unverified":
        copy += "\n\n⚠️ 以上赛事信息由 AI 整理，报名前请以官网最新通知为准。"

    copy = _llm_polish(copy, f"赛事={comp.competition_name}，队伍={team_txt}，技能={skills}，截止={deadline}")
    trace.append("组队文案：已生成（含引用编号）")
    return {**state, "team_copy": copy, "pending_review": comp.data_status.value == "unverified", "trace": trace}


# ---------------------------------------------------------------------------
# 节点 6：全库推荐（recommend intent 专用）
# ---------------------------------------------------------------------------


def node_recommend_all(state: AgentState) -> AgentState:
    trace = list(state.get("trace") or [])
    profile = _load_profile(state)
    if profile is None:
        trace.append("全库推荐：跳过（无用户画像）")
        return {**state, "recommendations": [], "trace": trace}

    comps = db.get_all_competitions()
    results = recommend_for_user(profile, comps, date.today())
    formal = [r for r in results if r.eligible][:5]
    candidates = [r for r in results if r.recommendation_status == "candidate_only"][:5]
    selected = formal if formal else candidates

    # 为每条可推荐赛事附 1 条最有代表性的引用（团队/技能）
    rag = get_rag()
    recos: list[dict] = []
    all_citations: list[dict] = list(state.get("citations") or [])
    for r in selected:
        comp = db.get_competition(r.competition_id)
        cite_idx = None
        try:
            hits = rag.query(r.competition_id, "参赛对象与团队人数要求",
                             document_year=comp.document_year if comp else None, top_k=1)
            if hits:
                all_citations.append(_cite_dict(hits[0]))
                cite_idx = len(all_citations) - 1
        except Exception:
            pass
        recos.append({
            "competition_id": r.competition_id,
            "competition_name": r.competition_name,
            "recommendation_status": r.recommendation_status,
            "score": r.score,
            "urgent": r.urgent,
            "pending_review": r.pending_review,
            "cite_index": cite_idx,
        })

    trace.append(
        f"全库推荐：共 {len(results)} 条，正式推荐 {len(formal)} 条，候选信息 {len(candidates)} 条"
    )
    return {**state, "recommendations": recos, "citations": all_citations, "trace": trace}


# ---------------------------------------------------------------------------
# 节点 7：组装答案（自动带引用）
# ---------------------------------------------------------------------------


def _citations_appendix(citations: list[dict]) -> str:
    if not citations:
        return ""
    lines = ["\n\n——— 引用来源 ———"]
    for i, c in enumerate(citations):
        page = c.get("page")
        loc = f"第{page}页" if page not in (None, -1) else "未定位页码"
        doc = c.get("document_name") or "官方通知"
        lvl = c.get("trusted_level") or "C"
        txt = (c.get("source_text") or "").strip().replace("\n", " ")
        if len(txt) > 60:
            txt = txt[:60] + "…"
        lines.append(f"{_cite_marker(i)} {doc}·{loc}·{lvl}级：{txt}")
    return "\n".join(lines)


def node_compose(state: AgentState) -> AgentState:
    trace = list(state.get("trace") or [])
    intent = state.get("intent") or "unknown"
    citations = state.get("citations") or []
    name = state.get("resolved_name")

    if intent == "team":
        body = state.get("team_copy") or "未能生成组队文案。"
        answer = body + _citations_appendix(citations)

    elif intent == "recommend":
        recos = state.get("recommendations") or []
        if not recos:
            answer = "暂时无法给出推荐：请先在「个人画像」中填写并授权保存资料（学历/年级/专业/技能等）。"
        else:
            status_map = {
                "highly_suitable": "高度适合", "suitable": "比较适合",
                "marginal": "可参加需补充", "not_prioritized": "暂不优先",
                "candidate_only": "候选信息（未评分）",
            }
            candidate_only = all(r.get("recommendation_status") == "candidate_only" for r in recos)
            if candidate_only:
                lines = ["当前没有已完成人工核验的赛事可进入正式推荐。以下仅为候选信息，不进行资格判断或匹配评分：\n"]
            else:
                lines = ["根据你的画像，门控+评分后为你推荐以下赛事（已过滤不符合硬性资格的项）：\n"]
            for i, r in enumerate(recos, 1):
                mark = _cite_marker(r["cite_index"]) if r.get("cite_index") is not None else ""
                tags = []
                if r.get("urgent"):
                    tags.append("⏰临近截止")
                tag_s = ("（" + "，".join(tags) + "）") if tags else ""
                sc = f"{r['score']}分" if r.get("score") is not None else "—"
                lines.append(
                    f"{i}. {r['competition_name']} · {status_map.get(r['recommendation_status'], r['recommendation_status'])} · {sc}{mark}{tag_s}"
                )
            lines.append("\n请以官方通知为准。候选信息须经人工核验后才会进入正式推荐。")
            answer = "\n".join(lines)
        answer += _citations_appendix(citations)

    elif intent in ("qa", "detail") and _asks_registration_deadline(state.get("question") or ""):
        comp = db.get_competition(state.get("resolved_competition")) if state.get("resolved_competition") else None
        mark = _cite_marker(0) if citations else ""
        if comp is None:
            answer = "没能定位到具体赛事，请补充赛事名称。"
        elif comp.registration_deadline is None:
            answer = f"「{comp.competition_name}」的官方文件未给出全国统一报名截止日期{mark}。"
        else:
            answer = f"「{comp.competition_name}」的报名截止日期：{comp.registration_deadline.isoformat()}{mark}。"
        answer += _citations_appendix(citations)

        gate = state.get("gate") or {}
        if gate.get("eligible") is False:
            answer += f"\n\n结合你的画像，该赛事门控未通过：{'；'.join(gate.get('reasons') or [])}"
        elif gate.get("eligible") is True and not (state.get("score") or {}).get("skipped"):
            answer += f"\n\n你符合报名硬性条件，综合匹配度约 {(state.get('score') or {}).get('total')} 分。"

    elif intent in ("qa", "detail"):
        if not citations:
            answer = (
                (f"未在「{name}」的资料中检索到与你问题相关的条款。" if name
                 else "没能定位到你想了解的具体赛事，请补充赛事名称，例如「蓝桥杯 团队几人」。")
            )
        else:
            head = f"关于「{name}」，依据官方通知检索到：\n" if name else "依据官方通知检索到：\n"
            lines = [head]
            for i, c in enumerate(citations):
                txt = (c.get("source_text") or "").strip().replace("\n", " ")
                lines.append(f"· {txt}{_cite_marker(i)}")
            gate = state.get("gate") or {}
            if gate.get("eligible") is False:
                lines.append(f"\n⚠️ 结合你的画像，该赛事门控未通过：{'；'.join(gate.get('reasons') or [])}")
            elif gate.get("eligible") is True and not (state.get("score") or {}).get("skipped"):
                sc = state.get("score") or {}
                lines.append(f"\n✅ 你符合报名硬性条件，综合匹配度约 {sc.get('total')} 分。")
            answer = "\n".join(lines) + _citations_appendix(citations)
        answer = _llm_polish(answer, f"赛事={name}；证据条数={len(citations)}")

    else:
        answer = state.get("clarification") or (
            "我可以帮你查询赛事规则、给出个性化推荐或生成组队文案。请补充具体赛事名称。"
        )

    if state.get("version_resolution_note"):
        answer = state["version_resolution_note"] + "\n\n" + answer

    trace.append("组装答案：完成")
    return {**state, "answer": answer, "trace": trace}


# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------


def _branch(state: AgentState) -> str:
    return state.get("intent") or "unknown"


def build_graph():
    """构建并编译 LangGraph 闭环（真实 langgraph 或内置等价引擎）。"""
    global _USING_LANGGRAPH
    g = StateGraph(AgentState)

    g.add_node("route_intent", node_route_intent)
    g.add_node("retrieve", node_retrieve)
    g.add_node("gate", node_gate)
    g.add_node("score", node_score)
    g.add_node("team_copy", node_team_copy)
    g.add_node("recommend_all", node_recommend_all)
    g.add_node("compose", node_compose)

    g.add_edge(START, "route_intent")

    # 意图分流
    g.add_conditional_edges(
        "route_intent",
        _branch,
        {
            "qa": "retrieve",
            "detail": "retrieve",
            "team": "retrieve",
            "recommend": "recommend_all",
            "unknown": "compose",
        },
    )

    # qa/detail：检索 → 门控 → 评分 → 组装
    # team：      检索 → 门控 → 评分 → 组队文案 → 组装
    g.add_edge("retrieve", "gate")
    g.add_edge("gate", "score")

    # score 之后根据意图决定是否生成组队文案
    def _after_score(state: AgentState) -> str:
        return "team_copy" if state.get("intent") == "team" else "compose"

    g.add_conditional_edges("score", _after_score, {"team_copy": "team_copy", "compose": "compose"})
    g.add_edge("team_copy", "compose")
    g.add_edge("recommend_all", "compose")
    g.add_edge("compose", END)

    compiled = g.compile()
    print(f"[agent] 闭环图已编译，引擎={'langgraph' if _USING_LANGGRAPH else '内置等价引擎(shim)'}")
    return compiled


# 编译后的单例（供 API 复用）
_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def run_agent(
    question: str,
    user_id: Optional[str] = None,
    competition_id: Optional[str] = None,
    top_k: int = 4,
) -> dict:
    """一次问答，走完整闭环，返回可直接序列化的结果字典。"""
    init: AgentState = {
        "question": question,
        "user_id": user_id,
        "competition_id": competition_id,
        "top_k": top_k,
        "trace": [],
        "citations": [],
        "pending_review": False,
    }
    final = get_graph().invoke(init)
    return {
        "question": question,
        "intent": final.get("intent"),
        "resolved_competition": final.get("resolved_competition"),
        "resolved_name": final.get("resolved_name"),
        "answer": final.get("answer"),
        "citations": final.get("citations") or [],
        "gate": final.get("gate") or {},
        "score": final.get("score") or {},
        "recommendations": final.get("recommendations") or [],
        "pending_review": bool(final.get("pending_review")),
        "trace": final.get("trace") or [],
        "error": final.get("error"),
    }


if __name__ == "__main__":
    # 自测：四类意图闭环
    print("=" * 70)
    samples = [
        ("蓝桥杯团队几人？报名什么时候截止", None, None),
        ("介绍一下数学建模竞赛", None, None),
        ("推荐适合我的比赛", "mock_user_001", None),
        ("帮我写一份蓝桥杯的组队招募文案", "mock_user_001", None),
        ("今天天气怎么样", None, None),
    ]
    for q, uid, cid in samples:
        r = run_agent(q, user_id=uid, competition_id=cid)
        print(f"\n【问】{q}  (user={uid})")
        print(f"意图={r['intent']}  赛事={r['resolved_name']}  引用={len(r['citations'])} 条  待确认={r['pending_review']}")
        print("轨迹：" + " → ".join(r["trace"]))
        print("答：\n" + (r["answer"] or ""))
        print("-" * 70)
