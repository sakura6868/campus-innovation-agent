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
    锁定赛事；答案默认用确定性模板生成（LLM 未启用时的回退）。若配置了 LLM
    （设 AGENT_LLM_API_KEY，可选 AGENT_LLM_BASE_URL 指向任意 OpenAI 兼容端点）：
      * qa / detail（指向具体赛事的事实查询）：由 LLM 基于检索证据**自由撰写**
        答案（可解释、对比、给建议），但所有赛事事实必须带 [n] 引用、且不得
        超出证据范围（见 src/agent/skills/evidence_speaking.md 铁律 + 引用校验）。
      * chat（开放/建议/通用问题）：走自由对话，LLM 当参谋，同样受证据铁律约束。
      * recommend / team：保持确定性逻辑（列表/文案），team 文案做轻量润色。
    门控结论与引用编号始终来自本地可信数据，模型无法改写；生成失败自动回退模板。

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
    recommend_teammates,
    soft_match_score,
)
from schemas import Citation, Competition, UserProfile
from trust import assess_source_readiness
from agent.llm import generate_answer as _llm_generate
from agent.web_search import web_search as _web_search, is_web_search_enabled as _web_enabled


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    # 输入
    question: str
    user_id: Optional[str]
    competition_id: Optional[str]     # 可由前端直接指定，否则路由自动锁定
    top_k: int
    model: Optional[str]               # 可选：请求级覆盖默认 LLM 模型

    # 路由结果
    intent: str                       # qa | detail | recommend | team | teammate | chat | unknown
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
    teammate_matches: list[dict]      # 基于画像的互补队友推荐

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


def _strip_year(s: str) -> str:
    """去掉年份（如「2026年」），避免赛事名里的年份前缀与问题里的年份形成
    虚假公共子串，导致「2026年蓝桥杯」被错配到「2026年XX大赛」。年份消歧
    交给 ``_resolve_competition_versioned`` 的 ``mentioned_years`` 处理。"""
    return re.sub(r"20\d{2}", "", s).replace("年", "")


def _competition_match_score(question: str, competition: Competition) -> float:
    q = _norm(question)
    c = competition
    name = c.competition_name or ""
    core = name
    for token in _GENERIC_TOKENS:
        core = core.replace(token, "")
    core = "".join(ch for ch in core if not ch.isdigit()).strip()
    # 完整名 / 核心名 / ID 直接命中仍保留（强信号）
    if name and name in q:
        return 10 + len(name)
    if core and core in q:
        return 8 + len(core)
    if c.competition_id and c.competition_id in q:
        return 6
    # 模糊匹配时对「完整名」剥离年份再比 LCS，既保留「蓝桥杯」等品牌字，
    # 又避免赛事名里的「2026年」前缀与问题里的年份形成虚假公共子串。
    lcs = _lcs_len(_strip_year(q), _strip_year(name)) if name else 0
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

    verified = [c for c in same_name if assess_source_readiness(c).ready]
    if not verified:
        # 兜底：即便评估未达「ready」（如 evidence 字段待补），只要已锚定官方来源
        # （found），就默认按最新届作答，避免常见赛事因多版本直接掉进「请明确年份」
        # 的澄清分支、从而完全不触发润色与引用。
        verified = [c for c in same_name if c.official_source_status == "found"]
    years = "、".join(str(c.document_year) for c in sorted(same_name, key=lambda item: item.document_year, reverse=True))
    if verified:
        selected = max(verified, key=lambda item: item.document_year)
        note = f"你没有指定年份，以下使用最新官网来源已确认版本：{selected.document_year}年（{selected.doc_version}）。"
        return selected, note, None
    clarification = f"“{best.competition_name}”存在多个年份版本（{years}），且暂无官网来源与关键证据完整的版本。请明确年份后再查询。"
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
_KW_TEAMMATE = [
    "推荐队友", "匹配队友", "找队友", "找搭档", "组队搭档", "互补队友",
    "队友推荐", "组队成员", "想找队友", "帮我找队友", "缺队友", "需要队友", "组队缺",
]
_KW_TEAM = ["组队招募", "招募", "招新", "招人", "招队友", "文案", "写一份", "招队员", "找人组队"]
_KW_DETAIL = ["介绍", "详情", "是什么", "概况", "简介", "了解一下"]
# 联网补充触发词：用户明显想要「最新 / 官方之外」的动态时，主动补联网检索
_WEB_TRIGGER = [
    "最新", "2026", "2025", "2024", "新闻", "官网", "今年", "最近", "动态",
    "报名开始", "通知", "公告", "刚出", "新增", "更新", "实时", "网上", "查一下",
    # 开放/建议类问题也主动联网，补充真实「备赛攻略 / 经验 / 含金量评价」
    "备赛", "备考", "备战", "攻略", "经验", "怎么准备", "如何准备", "怎么学",
    "含金量", "值得参加", "难不难", "前景", "评价", "靠谱吗", "避坑", "注意什么",
    "复习", "冲刺", "怎么规划", "如何规划", "经验分享",
]
_KW_CHAT = [
    "规划", "计划", "建议", "怎么准备", "如何准备", "怎么选", "如何选",
    "策略", "路线", "方向", "经验", "分享", "攻略", "提升", "怎么学",
    "如何学", "怎么备", "如何备", "我该怎么", "该不该", "值不值", "怎么样",
    "含金量", "值得参加", "值得报", "难不难", "难吗", "有没有用", "有用吗",
    "前景", "优势", "评价", "靠谱吗", "好不好", "如何准备", "怎么冲刺",
    "帮我", "如何冲", "怎么冲", "怎么安排", "如何安排", "注意什么", "避坑",
    # —— 以下扩充：覆盖「备赛 / 备考 / 备战」整类问法，避免被误判为规则问答 ——
    "备赛", "备考", "备战", "怎么备考", "如何备考", "怎么打", "如何打",
    "复习", "冲刺", "学习路线", "时间规划", "怎么规划", "如何规划",
    "备考攻略", "经验分享", "备赛经验", "经验贴", "怎么提升", "如何提升",
    "提升路径", "能力提升", "怎么练", "如何练", "该如何准备", "从零开始",
    # 指定了具体赛事时的「选赛项 / 是否适合我」也走 chat 给针对性建议，而非全局推荐
    "选哪个", "选什么", "报哪个", "报什么", "适合我", "适合吗", "适合打", "适合报",
]


def _classify_intent(question: str, has_comp: bool) -> str:
    q = question
    if any(k in q for k in _KW_TEAMMATE):
        return "teammate"
    if any(k in q for k in _KW_TEAM):
        return "team"
    if has_comp and any(k in q for k in _KW_DETAIL):
        return "detail"
    # 开放/建议/评价/选型类问题（怎么准备、值不值得、含金量、选赛项、是否适合我…）
    # 优先走 chat：由 LLM 或确定性生成器基于赛事证据+通用方法论作答。即便 LLM 未启用，
    # chat 也有基于证据的兜底回答（备赛路线/价值研判/选型建议），不再被当成 qa 拒答、
    # 也不会因「未通过推荐门控」而答非所问。
    if has_comp and any(k in q for k in _KW_CHAT):
        return "chat"
    if any(k in q for k in _KW_RECOMMEND):
        return "recommend"
    if has_comp:
        return "qa"          # 指向具体赛事的事实查询，走规则问答（检索带引用）
    # 无明确赛事：开放/建议/通用类问题走自由对话（chat），由 LLM 当参谋
    return "chat"


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


def _llm_polish(draft: str, context: str, model: Optional[str] = None) -> str:
    """若启用 LLM，则对确定性草稿做自然语言润色；否则原样返回。

    仅润色措辞，绝不改写引用编号、门控结论与数值——这些来自本地可信数据。
    实现见 src/agent/llm.py（OpenAI 兼容，含引用安全校验与优雅回退）。
    ``model`` 可选，请求级覆盖默认模型（前端模型选择器透传）。
    """
    from agent.llm import polish as _polish

    out = _polish(draft, context, model=model)
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


def _broad_retrieve(question: str, top_k: int = 5) -> tuple[list, list]:
    """开放对话（chat）用：跨全部赛事做轻量召回，作为 LLM 自由作答的接地证据。

    不依赖 RAG 语义检索（本环境 RAG 为本地隔离实现），改用「赛事名模糊匹配 +
    关键字段（技能/对象/类别）关键词重叠」打分，取 top-k 赛事，再把每个赛事的
    关键结构化字段转成 Citation 作为证据。返回 (相关赛事列表, 证据列表)。
    """
    comps = db.get_all_competitions()
    scored = []
    for c in comps:
        score = _competition_match_score(question, c)
        hay_parts = [c.competition_name or ""]
        hay_parts += list(getattr(c, "required_skills", []) or [])
        hay_parts += [getattr(s, "value", str(s)) for s in (getattr(c, "eligible_students", []) or [])]
        cat = getattr(c, "category", None)
        if cat:
            hay_parts.append(str(cat))
        hay = " ".join(hay_parts)
        if any(tok in _norm(question) for tok in hay.split() if len(tok) >= 2):
            score += 2
        if score >= 4:
            scored.append((c, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    top = [c for c, _ in scored[:top_k]]
    cites: list = []
    for c in top:
        for cit in _detail_fallback_citations(c)[:3]:
            cites.append(cit)
    return top, cites


def node_retrieve(state: AgentState) -> AgentState:
    trace = list(state.get("trace") or [])
    cid = state.get("resolved_competition")
    if not cid:
        if (state.get("intent") or "") == "chat":
            top, cites = _broad_retrieve(state.get("question") or "", top_k=int(state.get("top_k") or 5))
            trace.append(f"开放检索：跨赛事召回 {len(top)} 个相关赛事、{len(cites)} 条证据")
            return {**state, "citations": [_cite_dict(h) for h in cites], "trace": trace}
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
    # qa 事实查询：语义检索为空时用赛事结构化关键字段兜底，避免「未检索到相关
    # 条款」式拒答——评价/开放类问题（已走 chat）更应如此；即便纯事实问法检索
    # 落空，也至少能基于团队/对象/截止/材料/技能给出可溯源答复。
    if state.get("intent") == "qa" and not hits and comp is not None:
        hits = _detail_fallback_citations(comp)
        if hits:
            trace.append("隔离检索：qa 兜底返回关键字段证据")
    trace.append(f"隔离检索：collection=rag_{cid}，命中 {len(hits)} 条证据")
    return {
        **state,
        "citations": [_cite_dict(h) for h in hits],
        "trace": trace,
    }


# ---------------------------------------------------------------------------
# 节点 2.5：联网补充（可选，仅作本地官方证据的补充，不混入 [n] 引用）
# ---------------------------------------------------------------------------


def node_web_augment(state: AgentState) -> AgentState:
    """对 qa/detail/chat 意图，在本地证据偏薄或用户明显要「最新动态」时，
    调用可选联网搜索作为补充。结果存于 ``web_results``，由 compose 明确标注，
    绝不与已核验的官方 [n] 引用混在一起。未启用 / 失败均返回空，不影响主链路。
    """
    trace = list(state.get("trace") or [])
    if not _web_enabled():
        return {**state, "web_results": []}
    intent = state.get("intent") or ""
    if intent not in ("qa", "detail", "chat"):
        return {**state, "web_results": []}
    q = state.get("question") or ""
    cites = state.get("citations") or []
    wants_web = any(k in q for k in _WEB_TRIGGER)
    # 仅当「显式要联网」或「本地证据偏薄（<3 条）」时才补充，避免每次都打外部 API
    if not wants_web and len(cites) >= 3:
        return {**state, "web_results": []}
    results = _web_search(q) or []
    if results:
        trace.append(f"联网补充：检索到 {len(results)} 条网络结果（标注为参考，不混入官方引用）")
    else:
        trace.append("联网补充：未启用或检索无结果，保持纯本地作答")
    return {**state, "web_results": results, "trace": trace}


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
    pending_review = bool(comp and not assess_source_readiness(comp).ready)
    if comp is None or profile is None:
        trace.append("硬性门控：跳过（缺用户画像或赛事）")
        return {**state, "gate": {"skipped": True}, "pending_review": pending_review, "trace": trace}

    today = date.today()
    problems = data_validity_check(comp, today)
    if problems:
        # 来源尚未完全核验 ≠ 「数据不可用」：事实仍会照常展示，仅提示以官网为准。
        gate = {
            "eligible": False,
            "source_issues": [f"来源待核实：{p}" for p in problems],
            "reasons": [],
            "actions": [],
        }
        trace.append("硬性门控：官方来源尚待核验（不阻断信息查阅）")
        return {**state, "gate": gate, "pending_review": not assess_source_readiness(comp).ready, "trace": trace}

    eligible, reasons = eligibility_gate(profile, comp, today)
    gate = {
        "eligible": eligible,
        "source_issues": [],
        "reasons": [r.reason for r in reasons],
        "actions": [r.possible_action for r in reasons if r.possible_action],
    }
    trace.append(f"硬性门控：{'通过' if eligible else '一票否决'}（{len(reasons)} 条原因）")
    return {
        **state,
        "gate": gate,
        "pending_review": not assess_source_readiness(comp).ready,
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
    source_ready = assess_source_readiness(comp).ready
    if not source_ready:
        trace.append("组队文案：跳过（关键证据待补充）")
        copy = "该赛事目前仅作为候选信息展示，关键字段证据尚不完整，暂不生成组队招募结论。请先查看赛事官网最新通知。"
        return {**state, "team_copy": copy, "pending_review": True, "trace": trace}

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
    copy = _llm_polish(copy, f"赛事={comp.competition_name}，队伍={team_txt}，技能={skills}，截止={deadline}", model=state.get("model"))
    trace.append("组队文案：已生成（含引用编号）")
    return {**state, "team_copy": copy, "pending_review": False, "trace": trace}


# ---------------------------------------------------------------------------
# 节点 5.5：基于画像的互补队友推荐（teammate intent 专用）
# ---------------------------------------------------------------------------
def node_teammate_match(state: AgentState) -> AgentState:
    trace = list(state.get("trace") or [])
    seeker = _load_profile(state)
    if seeker is None:
        trace.append("队友推荐：跳过（无可用画像）")
        return {**state, "teammate_matches": [], "trace": trace}

    candidates = db.list_user_profiles(exclude_user_id=seeker.user_id)
    matches = recommend_teammates(seeker, candidates, top_k=state.get("top_k") or 5)
    matches_dict = [m.model_dump(mode="json") for m in matches]
    trace.append(f"队友推荐：从 {len(candidates)} 名候选中匹配出 {len(matches)} 名互补队友")
    return {**state, "teammate_matches": matches_dict, "trace": trace}


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
    selected = formal

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
        f"全库推荐：共检查 {len(results)} 条，正式推荐 {len(formal)} 条；候选信息仅在赛事目录展示"
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


# ---------------------------------------------------------------------------
# 工具：混合模式 —— LLM 基于证据自由撰写（仍强约束 [n] 引用）
# ---------------------------------------------------------------------------

_CIT_RE = re.compile(r"\[(\d+)\]")


def _build_evidence_brief(citations: list[dict], web_results: Optional[list] = None) -> str:
    """把 citations 序列化成 LLM 能读懂的「编号证据清单」。

    每条形如：[n] （文档名｜字段｜可信等级）原文片段 官方链接
    LLM 撰写时须用 [n] 回指，从而保证所有事实可溯源。
    ``web_results`` 作为单独「🌐 联网参考」块附在末尾，明确标注仅供参考、
    不计入 [n] 官方引用，避免与已核验来源混淆。
    """
    if not citations and not web_results:
        return "（无具体赛事证据，请基于通用方法论回答，不要编造任何具体赛事的事实、日期或数字）"
    lines = []
    for i, c in enumerate(citations):
        doc = c.get("document_name") or "官方通知"
        url = c.get("source_url") or ""
        field = c.get("field") or ""
        txt = (c.get("source_text") or "").strip().replace("\n", " ")
        lvl = c.get("trusted_level") or "C"
        line = f"[{i + 1}] （{doc}｜字段:{field}｜可信等级:{lvl}）{txt}"
        if url:
            line += f" 官方链接:{url}"
        lines.append(line)
    if web_results:
        lines.append("\n🌐 联网参考（仅供参考，不得用于 [n] 引用，也不计入官方证据）：")
        for i, w in enumerate(web_results[:4]):
            title = " ".join((w.get("title") or "").split())
            url = w.get("url") or ""
            snippet = " ".join((w.get("snippet") or "").split())
            if len(snippet) > 80:
                snippet = snippet[:80] + "…"
            lines.append(f"  - {title}：{snippet} {url}")
    return "\n".join(lines)


def _profile_summary(profile) -> str:
    if not profile:
        return ""
    parts = []
    edu = getattr(profile, "education_level", None)
    if edu:
        parts.append(f"学历：{edu}")
    if getattr(profile, "major", None):
        parts.append(f"专业：{profile.major}")
    if getattr(profile, "skills", None):
        parts.append("技能：" + "、".join(profile.skills))
    if getattr(profile, "interests", None):
        parts.append("兴趣：" + "、".join(profile.interests))
    return "；".join(parts)


def _sanitize_citations(answer: str, n_citations: int) -> str:
    """去掉超出证据范围的 [n] 引用，防止模型编造不存在的编号。

    若模型写了 [7] 但只有 3 条证据，则该标记被剥离，避免前端渲染幽灵引用。
    """
    def _repl(m: "re.Match") -> str:
        idx = int(m.group(1))
        return "" if idx < 1 or idx > n_citations else m.group(0)
    return _CIT_RE.sub(_repl, answer)


# ---------------------------------------------------------------------------
# 工具：开放/建议类问题的「确定性作答」（LLM 未启用时也能真正回答问题）
# ---------------------------------------------------------------------------

# 编程 / 算法类赛事识别（用于给出针对性的备赛路线）
_PROG_KW = (
    "算法", "程序设计", "编程", "C/C++", "C++", "Java", "Python", "软件开发",
    "Web应用", "网络安全", "软件赛", "计算机", "数据结构",
)


def _is_programming_comp(comp) -> bool:
    if comp is None:
        return False
    blob = " ".join(
        [str(getattr(comp, "category", ""))]
        + list(getattr(comp, "required_skills", []) or [])
        + list(getattr(comp, "evaluation_dimensions", []) or [])
    )
    return any(k in blob for k in _PROG_KW)


def _is_prep_question(q: str) -> bool:
    return any(k in q for k in (
        "备赛", "备考", "备战", "怎么准备", "如何准备", "怎么备", "如何备",
        "怎么备考", "如何备考", "怎么打", "如何打", "复习", "冲刺", "攻略",
        "学习路线", "时间规划", "怎么规划", "如何规划", "备考攻略", "备赛经验",
        "经验贴", "怎么提升", "如何提升", "提升路径", "能力提升", "怎么练",
        "如何练", "该如何准备", "从零开始", "怎么学", "如何学",
    ))


def _is_eval_question(q: str) -> bool:
    return any(k in q for k in (
        "含金量", "值得参加", "值得报", "难不难", "难吗", "有没有用", "有用吗",
        "前景", "优势", "评价", "靠谱吗", "好不好", "该不该", "值不值", "怎么样",
        "适合我", "适合吗", "适合打", "适合报",
    ))


def _is_selection_question(q: str) -> bool:
    return any(k in q for k in ("怎么选", "如何选", "选哪个", "选什么", "报哪个", "报什么"))


def _web_block(web_results, limit: int = 4) -> str:
    """把联网结果序列化为「🌐 参考」块（明确标注仅供参考、不混入官方引用）。"""
    if not web_results:
        return ""
    lines = ["\n🌐 联网补充参考（网友/媒体经验，仅供参考，请以官网为准）："]
    for w in web_results[:limit]:
        title = " ".join((w.get("title") or "").split())
        url = w.get("url") or ""
        snippet = " ".join((w.get("snippet") or "").split())
        if len(snippet) > 70:
            snippet = snippet[:70] + "…"
        lines.append(f"  · {title}：{snippet} {url}")
    return "\n".join(lines)


def _build_prep_guide(comp, web_results, profile) -> str:
    """生成可执行的备赛路线图（按赛事类别 + 用户画像定制）。"""
    name = comp.competition_name
    year = comp.document_year
    lines = [f"关于「{name}（{year}）」怎么备赛，我给你一份可直接落地的路线图（结合赛事结构 + 通用方法论）：\n"]

    facts = []
    if comp.registration_deadline:
        facts.append(f"报名/缴费截止约 {comp.registration_deadline.isoformat()}")
    if comp.competition_start_date:
        facts.append(f"省赛/初赛时间约 {comp.competition_start_date.isoformat()}")
    if comp.eligible_students:
        facts.append("参赛对象：" + "、".join(comp.eligible_students))
    if comp.required_skills:
        facts.append("主要赛项/方向：" + "、".join(comp.required_skills))
    if facts:
        lines.append("📌 先锁定几个关键事实（来自官方通知）：")
        for f in facts:
            lines.append(f"  · {f}")
        lines.append("")

    if _is_programming_comp(comp):
        lines.append("🗺️ 软件/算法类备赛四阶段（建议提前 3–6 个月启动）：")
        lines.append("  1) 打基础（第1–6周）：吃透一门主力语言（C/C++ / Java / Python），"
                     "熟练掌握数据结构与基础算法——枚举、模拟、排序、贪心、递推递归、基础 DP、简单图论、哈希、字符串。")
        lines.append("  2) 专项突破（第7–12周）：按高频专题刷——数组/字符串、DFS/BFS、"
                     "动态规划、最短路、并查集、数论/组合数学、二分、前缀和/差分、单调栈/队列。")
        lines.append("  3) 真题实战（第13–18周）：限时刷近 5 年省赛真题，先稳拿填空/简单编程题，"
                     "再攻大题；每题复盘时间复杂度与更优解。")
        lines.append("  4) 冲刺模考（赛前2–4周）：全真 4 小时模拟，整理易错模板"
                     "（快读、二分、前缀和、并查集等），查漏补缺。")
        lines.append("")
        lines.append("📚 资料与平台：官网章程/样题/历年真题；洛谷、AcWing、蓝桥杯官方练习系统、"
                     "LeetCode 对应语言热题。")
        lines.append("💡 提分点：填空题重速度与准确性，编程大题重正确率与边界处理；"
                     "把标准库/STL 用熟能省大量赛场时间。")
    else:
        lines.append("🗺️ 通用备赛四阶段（按赛制调整）：")
        lines.append("  1) 读懂赛制：研读竞赛章程、评分标准与往年获奖作品，明确「评什么、怎么评」。")
        lines.append("  2) 积累素材：按赛项补齐知识/技能短板；组队类尽早找互补队友、定选题方向。")
        lines.append("  3) 打磨作品/演练：做 1–2 轮完整模拟（含答辩/文档），按评分标准逐项自检。")
        lines.append("  4) 冲刺提交：预留时间做格式校对、查重/合规检查与最终提交，避免技术性失误。")
        lines.append("")
        lines.append("📚 资料与平台：竞赛官网与主办方通知、往年优秀作品集、指导老师与同好社群、相关公开课/教材。")

    if profile:
        major = getattr(profile, "major", None)
        skills = getattr(profile, "skills", None) or []
        if major or skills:
            lines.append(
                f"\n💡 结合你的画像（{major or '专业未填'} / 技能：{', '.join(skills) or '待补充'}）："
                f"优先用你最熟的语言或方向做主力，把短板专题（如算法/文档/答辩）排进前 6 周重点突破。"
            )

    web = _web_block(web_results)
    if web:
        lines.append(web)
    if comp.official_source_url:
        lines.append(f"\n🔗 官方入口：{comp.official_source_url}")
    return "\n".join(lines)


def _build_eval_answer(comp, web_results, profile) -> str:
    """对「含金量 / 难不难 / 值不值得」给出平衡研判。"""
    name = comp.competition_name
    year = comp.document_year
    lines = [f"关于「{name}（{year}）」值不值得参加、难度如何，我给你一个平衡的判断框架：\n"]
    lines.append("✅ 它的价值通常在这些方面：")
    lines.append("  · 简历/综测：作为受认可的学科竞赛，获奖在保研、综测、就业简历上有实质加分；")
    lines.append("  · 能力成长：逼着自己系统补短板（算法/工程/文档/答辩），比零散自学更成体系；")
    lines.append("  · 圈层资源：通过校赛/省赛认识同好与指导老师，打开后续项目与实习机会。")
    lines.append("")
    lines.append("⚠️ 也要客观看难度与成本：")
    lines.append("  · 越是「认可度高」的赛事，省赛以上竞争越激烈，需要持续投入（通常 3–6 个月）而非临时突击；")
    if _is_programming_comp(comp):
        lines.append("  · 软件/算法类对算法功底要求高，零基础直接冲国奖不现实，建议从省赛获奖率较高的赛项切入；")
    lines.append("  · 投入产出比取决于你的目标：若只为综测凑数，优先选与本专业/技能最贴合的赛项，性价比最高。")
    lines.append("")
    lines.append("🎯 适合谁：")
    lines.append("  · 想保研/刷简历、且愿意花时间系统训练的同学；")
    if comp.eligible_students:
        lines.append(f"  · 参赛对象覆盖：{ '、'.join(comp.eligible_students) }，先确认你在本科学段内；")
    lines.append("  · 时间紧的同学，建议「保一门主力赛项 + 顺带了解其他」，别贪多。")
    web = _web_block(web_results, limit=3)
    if web:
        lines.append(web)
    lines.append("\nℹ️ 以上为通用研判，具体获奖比例/含金量以当年官方章程与你所在院校认定为准。")
    return "\n".join(lines)


def _build_selection_answer(comp, profile) -> str:
    """对「怎么选赛项 / 报哪个」给出决策思路。"""
    name = comp.competition_name
    lines = [f"「{name}」怎么选赛项/方向，给你一个决策思路：\n"]
    if comp.required_skills:
        lines.append("· 先看赛项清单：" + "、".join(comp.required_skills)
                     + "。挑与你当前最强技能重合度最高的，起步最快、性价比最高。")
    if profile and getattr(profile, "skills", None):
        lines.append(f"· 结合你的技能（{', '.join(profile.skills)}）：优先用熟的语言/方向做主力，"
                     "把陌生但高分的专题列为「下一步突破」。")
    lines.append("· 时间与目标：保研/简历导向 → 选认可度高、与你专业贴合的赛项；纯练手 → 选最感兴趣、能坚持下来的。")
    lines.append("· 实在拿不准，可以说「推荐适合我的比赛」，我按你的画像帮你匹配；"
                 "或对比多场时说「A 和 B 怎么选」让我帮你拆解。")
    return "\n".join(lines)


def _compose_chat_deterministic(state, comp, citations, web_results) -> Optional[str]:
    """LLM 未启用或生成失败时的确定性兜底；按问题类型产出真正有用的回答。

    返回 None 表示「无确定模板可套」（交由 compose 的通用兜底处理）。
    """
    if comp is None:
        return None
    q = state.get("question") or ""
    profile = _load_profile(state)
    if _is_prep_question(q):
        body = _build_prep_guide(comp, web_results, profile)
    elif _is_eval_question(q):
        body = _build_eval_answer(comp, web_results, profile)
    elif _is_selection_question(q):
        body = _build_selection_answer(comp, profile)
    else:
        return None
    answer = body + _citations_appendix(citations)
    if state.get("version_resolution_note"):
        answer = state["version_resolution_note"] + "\n\n" + answer
    return answer


def _generate_grounded(state: AgentState, intent: str, citations: list, name: str,
                       allow_empty_evidence: bool = False) -> Optional[str]:
    """调用 LLM 基于证据自由撰写；LLM 未启用/生成失败返回 None（回退确定性）。"""
    if not citations and not allow_empty_evidence:
        return None
    brief = _build_evidence_brief(citations, state.get("web_results"))
    profile = _load_profile(state)
    profile_summary = _profile_summary(profile) if profile else ""
    question = state.get("question") or ""
    out = _llm_generate(
        question, brief,
        intent=intent,
        profile_summary=profile_summary,
        model=state.get("model"),
    )
    if not out:
        return None
    return _sanitize_citations(out, len(citations))


def _finalize_grounded(generated: str, state: AgentState, citations: list,
                       intent: str, trace: list) -> str:
    """把 LLM 生成结果 + 确定性门控/评分结论 + 引用附录拼成最终答案。"""
    answer = generated
    # chat 为开放/建议类，不追加任何「门控」结论（与备赛/研判建议无关）
    if intent != "chat":
        gate = state.get("gate") or {}
        if gate.get("source_issues"):
            # 来源待核验 ≠ 数据不可用：事实已展示，仅作软提示
            answer += "\n\nℹ️ 说明：该赛事官方来源尚待核验（不影响以上信息查阅），报名与赛程请以官网最新通知为准。"
        elif gate.get("eligible") is False:
            reasons = gate.get("reasons") or []
            if reasons:
                answer += f"\n\n⚠️ 结合你的画像，你暂不符合该赛事硬性条件：{'；'.join(reasons)}"
            else:
                answer += "\n\nℹ️ 说明：该赛事官方来源尚待核验，报名与赛程请以官网最新通知为准。"
        elif gate.get("eligible") is True and not (state.get("score") or {}).get("skipped"):
            answer += f"\n\n✅ 你符合报名硬性条件，综合匹配度约 {(state.get('score') or {}).get('total')} 分。"
    answer += _citations_appendix(citations)
    if state.get("version_resolution_note"):
        answer = state["version_resolution_note"] + "\n\n" + answer
    if state.get("pending_review") and intent in ("qa", "detail"):
        comp = db.get_competition(state.get("resolved_competition")) if state.get("resolved_competition") else None
        if comp is None or comp.official_source_status != "found":
            answer += "\n\n该赛事目前仅作为候选信息展示，关键字段证据尚不完整；以上内容不构成资格判断或匹配评分，请以官网最新通知为准。"
    trace.append("组装答案：LLM 基于证据自由撰写（带 [n] 引用）")
    return answer


# ---------------------------------------------------------------------------
# 节点 7：组装答案（自动带引用）
# ---------------------------------------------------------------------------
def node_compose(state: AgentState) -> AgentState:
    trace = list(state.get("trace") or [])
    intent = state.get("intent") or "unknown"
    citations = state.get("citations") or []
    name = state.get("resolved_name")

    # 歧义澄清优先：多版本未定 / 需明确年份时，直接给出澄清，不进入自由生成，
    # 避免 LLM 在信息不足时自行猜测赛事版本。
    if state.get("clarification"):
        answer = state["clarification"]
        answer += _citations_appendix(citations)
        trace.append("组装答案：歧义澄清（需用户明确年份/版本）")
        return {**state, "answer": answer, "trace": trace}

    # ---- 混合模式核心：qa/detail 事实查询、chat 开放对话，均由 LLM 基于证据自由撰写 ----
    if intent in ("qa", "detail") and citations:
        generated = _generate_grounded(state, intent, citations, name)
        if generated:
            answer = _finalize_grounded(generated, state, citations, intent, trace)
            return {**state, "answer": answer, "trace": trace}
    if intent == "chat":
        # 优先用 LLM 当参谋；未启用/失败时回退到确定性生成器（备赛/研判/选型也能真正回答）。
        generated = _generate_grounded(state, "chat", citations, name, allow_empty_evidence=True)
        if generated:
            answer = _finalize_grounded(generated, state, citations, "chat", trace)
            return {**state, "answer": answer, "trace": trace}
        # —— LLM 未启用或生成失败：走确定性生成，确保开放/建议类问题有实质回答 ——
        det = _compose_chat_deterministic(
            state,
            db.get_competition(state.get("resolved_competition")),
            citations,
            state.get("web_results") or [],
        )
        if det:
            trace.append("组装答案：chat 确定性生成（备赛/研判/选型）")
            return {**state, "answer": det, "trace": trace}
        # 完全兜底：仅当无可套用模板时，列出已知赛事事实并引导启用模型。
        if citations:
            lines = ["我先基于已知赛事信息给你方向性参考：\n"]
            for i, c in enumerate(citations[:5]):
                txt = (c.get("source_text") or "").strip().replace("\n", " ")
                if len(txt) > 80:
                    txt = txt[:80] + "…"
                lines.append(f"· {txt}{_cite_marker(i)}")
            lines.append("\n如需就备赛规划、能力提升等开放问题获得更自然的对话式建议，可在设置中启用智能模型。")
            answer = "\n".join(lines)
        else:
            answer = (
                "我可以帮你查询具体赛事的规则、给出个性化推荐或生成组队文案。"
                "请告诉我具体赛事名称（例如「蓝桥杯报名截止日期」），或直接说「推荐适合我的比赛」。"
                "启用智能模型后，这里还能就备赛规划、能力提升等开放问题给出建议。"
            )
        answer += _citations_appendix(citations)
        if state.get("version_resolution_note"):
            answer = state["version_resolution_note"] + "\n\n" + answer
        trace.append("组装答案：chat 回退提示（基于证据引导）")
        return {**state, "answer": answer, "trace": trace}

    if intent == "teammate":
        matches = state.get("teammate_matches") or []
        if not matches:
            answer = (
                "暂时没有可供匹配的队友候选。你可以先完善个人画像（专业、技能、年级），"
                "系统会从队友库中为你推荐互补搭档。"
            )
        else:
            lines = ["根据你的画像，我为你匹配了以下互补队友（按互补度排序）：\n"]
            for i, m in enumerate(matches, 1):
                name = m.get("display_name") or m.get("user_id")
                lines.append(
                    f"{i}. {name}（{m.get('major')} · {m.get('grade')}）— 互补度 {m.get('match_score'):.0f} 分"
                )
                for r in (m.get("reasons") or [])[:3]:
                    lines.append(f"   · {r}")
            lines.append("\n可在「我的队友」中查看完整画像与联系方式（演示环境为虚拟候选）。")
            answer = "\n".join(lines)
        trace.append("组装答案：teammate 互补队友推荐")
        return {**state, "answer": answer, "trace": trace}

    if intent == "team":
        body = state.get("team_copy") or "未能生成组队文案。"
        answer = body + _citations_appendix(citations)

    elif intent == "recommend":
        recos = state.get("recommendations") or []
        if not recos:
            answer = "暂时没有通过官网来源、关键证据和报名时间门控的正式推荐。请检查个人画像，或前往「赛事大厅」查看待核验候选并自行核对官网。"
        else:
            status_map = {
                "highly_suitable": "高度适合", "suitable": "比较适合",
                "marginal": "可参加需补充", "not_prioritized": "暂不优先",
            }
            lines = ["根据你的画像，门控+评分后为你推荐以下赛事（已过滤关键证据不完整、不符合硬性资格以及不可报名的赛事）：\n"]
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
            lines.append("\n以上结论基于已锚定的官方来源，报名前仍请查看赛事官网最新通知。")
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
        if gate.get("source_issues"):
            answer += "\n\nℹ️ 说明：该赛事官方来源尚待核验（不影响以上信息查阅），报名与赛程请以官网最新通知为准。"
        elif gate.get("eligible") is False:
            reasons = gate.get("reasons") or []
            if reasons:
                answer += f"\n\n⚠️ 结合你的画像，你暂不符合该赛事硬性条件：{'；'.join(reasons)}"
            else:
                answer += "\n\nℹ️ 说明：该赛事官方来源尚待核验，报名与赛程请以官网最新通知为准。"
        elif gate.get("eligible") is True and not (state.get("score") or {}).get("skipped"):
            answer += f"\n\n✅ 你符合报名硬性条件，综合匹配度约 {(state.get('score') or {}).get('total')} 分。"

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
            if gate.get("source_issues"):
                lines.append("\nℹ️ 说明：该赛事官方来源尚待核验（不影响以上信息查阅），报名与赛程请以官网最新通知为准。")
            elif gate.get("eligible") is False:
                reasons = gate.get("reasons") or []
                if reasons:
                    lines.append(f"\n⚠️ 结合你的画像，你暂不符合该赛事硬性条件：{'；'.join(reasons)}")
                else:
                    lines.append("\nℹ️ 说明：该赛事官方来源尚待核验，报名与赛程请以官网最新通知为准。")
            elif gate.get("eligible") is True and not (state.get("score") or {}).get("skipped"):
                sc = state.get("score") or {}
                lines.append(f"\n✅ 你符合报名硬性条件，综合匹配度约 {sc.get('total')} 分。")
            answer = "\n".join(lines) + _citations_appendix(citations)
        answer = _llm_polish(answer, f"赛事={name}；证据条数={len(citations)}", model=state.get("model"))

    else:
        answer = state.get("clarification") or (
            "我可以帮你查询赛事规则、给出个性化推荐或生成组队文案。请补充具体赛事名称。"
        )

    if state.get("version_resolution_note"):
        answer = state["version_resolution_note"] + "\n\n" + answer
    if state.get("pending_review") and intent in ("qa", "detail"):
        comp = db.get_competition(state.get("resolved_competition")) if state.get("resolved_competition") else None
        # 仅对「无官方来源 / 待核验」赛事显示候选免责；已锚定官方来源（found）的
        # A/B 级赛事不再套用，避免对已核验信息给出误导性的「候选」措辞。
        if comp is None or comp.official_source_status != "found":
            answer += "\n\n该赛事目前仅作为候选信息展示，关键字段证据尚不完整；以上内容不构成资格判断或匹配评分，请以官网最新通知为准。"

    # 联网补充：结果存于 state["web_results"]，由前端明确标注为「🌐 联网信息（仅供参考）」
    # 并附可点击来源链接；不混入答案正文的官方 [n] 引用，保持证据一致性。

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
    g.add_node("teammate_match", node_teammate_match)
    g.add_node("recommend_all", node_recommend_all)
    g.add_node("web_augment", node_web_augment)
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
            "chat": "retrieve",
            "teammate": "teammate_match",
            "recommend": "recommend_all",
            "unknown": "compose",
        },
    )

    # qa/detail：检索 → 联网补充 → 门控 → 评分 → 组装
    # team：      检索 → 联网补充 → 门控 → 评分 → 组队文案 → 组装
    g.add_edge("retrieve", "web_augment")
    g.add_edge("web_augment", "gate")
    g.add_edge("gate", "score")

    # score 之后根据意图决定是否生成组队文案
    def _after_score(state: AgentState) -> str:
        return "team_copy" if state.get("intent") == "team" else "compose"

    g.add_conditional_edges("score", _after_score, {"team_copy": "team_copy", "compose": "compose"})
    g.add_edge("team_copy", "compose")
    g.add_edge("teammate_match", "compose")
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
    model: Optional[str] = None,
) -> dict:
    """一次问答，走完整闭环，返回可直接序列化的结果字典。

    ``model`` 可选：请求级覆盖默认 LLM 模型（前端模型选择器透传），
    仅在已配置 LLM key 时生效；未配置或调用失败自动回退确定性模板。
    """
    init: AgentState = {
        "question": question,
        "user_id": user_id,
        "competition_id": competition_id,
        "top_k": top_k,
        "model": model,
        "trace": [],
        "citations": [],
        "web_results": [],
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
        "teammate_matches": final.get("teammate_matches") or [],
        "pending_review": bool(final.get("pending_review")),
        "trace": final.get("trace") or [],
        "web_results": final.get("web_results") or [],
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
