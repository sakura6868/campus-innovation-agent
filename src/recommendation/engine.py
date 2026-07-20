"""推荐引擎：数据有效性检查 -> 硬性门控（一票否决）-> 软性匹配评分。

严格遵循修订方案「三、推荐算法改为门控加评分」：
  - 第一层：数据本身是否可用（无可靠来源不进入正式推荐）
  - 第二层：资格与时间硬性门控，任一不满足则一票否决，score=null
  - 第三层：仅对通过门控的赛事计算 MatchScore = 0.40S + 0.25E + 0.20R + 0.15W
  - 推荐结果必须解释：资格/匹配/缺口/队友/时间/下一步
"""

from __future__ import annotations

from datetime import date, timedelta

from schemas import (
    Competition,
    DataStatus,
    GateReason,
    MatchBreakdown,
    RecommendationResult,
    TeammateMatch,
    UserProfile,
)
from fact_formatting import format_team_size
from trust import assess_source_readiness, is_registerable_now


# ---------------------------------------------------------------------------
# 第一层：数据有效性检查
# ---------------------------------------------------------------------------


def data_validity_check(comp: Competition, current: date) -> list[str]:
    """返回阻止赛事进入正式推荐的原因；空列表表示数据可用。"""
    return list(assess_source_readiness(comp).reasons)


# ---------------------------------------------------------------------------
# 第二层：硬性门控（一票否决）
# ---------------------------------------------------------------------------


def eligibility_gate(
    user: UserProfile, comp: Competition, current: date
) -> tuple[bool, list[GateReason]]:
    """资格与时间硬条件。任一不满足即一票否决。"""
    reasons: list[GateReason] = []

    effective_deadline = comp.registration_deadline or comp.submission_deadline
    if effective_deadline is not None and effective_deadline < current:
        reason = "报名已经截止" if comp.registration_deadline else "作品提交已经截止"
        reasons.append(GateReason(reason=reason))

    if user.education_level not in comp.eligible_students:
        reasons.append(GateReason(reason="学历层次不符合要求"))

    if comp.allowed_grades and user.grade not in comp.allowed_grades:
        reasons.append(
            GateReason(
                reason=f"年级不符合要求（仅允许 {', '.join(g.value for g in comp.allowed_grades)}）",
                possible_action="寻找允许该年级参加的同类赛事",
            )
        )

    if comp.allowed_majors:
        # 专业匹配放宽到「包含关系」，避免「计算机科学与技术」无法命中「计算机类」
        major_ok = any(user.major in m or m in user.major for m in comp.allowed_majors)
        if not major_ok:
            reasons.append(
                GateReason(
                    reason=f"专业不符合要求（仅允许 {', '.join(comp.allowed_majors)}）",
                    possible_action="寻找允许该专业参加的同类赛事",
                )
            )

    if comp.team_required and user.expected_team_size > (comp.team_max or 999):
        reasons.append(GateReason(reason="预计团队人数超过上限"))

    return len(reasons) == 0, reasons


# ---------------------------------------------------------------------------
# 时间门控（用户规则）：仅推送当前仍可报名的赛事
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 第三层：软性匹配评分
# ---------------------------------------------------------------------------


def _skill_score(user: UserProfile, comp: Competition) -> float:
    if not comp.required_skills:
        return 80.0
    matched = sum(1 for s in comp.required_skills if s in user.skills)
    return round(min(100.0, matched / len(comp.required_skills) * 100), 1)


def _experience_score(user: UserProfile, comp: Competition) -> float:
    if not user.experiences:
        return 40.0
    # 同类别或含关键词的经历视为有效
    kw = comp.category.value
    hit = sum(1 for e in user.experiences if kw in e or comp.competition_name[:2] in e)
    return round(min(100.0, 40.0 + hit * 30.0), 1)


def _resource_score(user: UserProfile, comp: Competition) -> float:
    # 组队赛：现有期望人数越接近上限，资源越充足
    if not comp.team_required:
        return 90.0
    if user.expected_team_size >= (comp.team_min or 1):
        return 80.0
    return 50.0


def _workload_score(user: UserProfile, comp: Competition, current: date) -> float:
    effective_deadline = comp.registration_deadline or comp.submission_deadline
    if effective_deadline is None:
        return 70.0
    remaining_weeks = max(0, (effective_deadline - current).days / 7.0)
    available_hours = remaining_weeks * user.weekly_available_hours
    required_hours = estimate_competition_workload(comp)
    return round(min(100.0, available_hours / required_hours * 100), 1)


def estimate_competition_workload(comp: Competition) -> float:
    """估算赛事所需投入小时（启发式）。"""
    base = 40.0
    if comp.team_required:
        base += 60.0
    base += 10.0 * max(0, len(comp.required_materials) - 1)
    return base


def soft_match_score(
    user: UserProfile, comp: Competition, current: date
) -> MatchBreakdown:
    s = _skill_score(user, comp)
    e = _experience_score(user, comp)
    r = _resource_score(user, comp)
    w = _workload_score(user, comp, current)
    total = round(0.40 * s + 0.25 * e + 0.20 * r + 0.15 * w, 1)
    return MatchBreakdown(
        skill_score=s, experience_score=e, resource_score=r,
        workload_score=w, total=total,
    )


# ---------------------------------------------------------------------------
# 分层与解释
# ---------------------------------------------------------------------------


def _status_from_score(score: float) -> RecommendationResult.recommendation_status:  # type: ignore[valid-type]
    if score >= 85:
        return "highly_suitable"
    if score >= 70:
        return "suitable"
    if score >= 55:
        return "marginal"
    return "not_prioritized"


def _build_explanation(
    user: UserProfile, comp: Competition, breakdown: MatchBreakdown, current: date
) -> dict:
    skill_gap = [s for s in comp.required_skills if s not in user.skills]
    effective_deadline = comp.registration_deadline or comp.submission_deadline
    remaining_weeks = ((effective_deadline - current).days / 7.0 if effective_deadline else None)
    return {
        "资格": "符合硬性资格与时间要求",
        "能力匹配": f"技能匹配度 {breakdown.skill_score}，经历匹配度 {breakdown.experience_score}",
        "能力缺口": f"缺少技能：{', '.join(skill_gap) if skill_gap else '无'}",
        "需要队友": (
            f"该赛事团队要求：{format_team_size(comp.team_min, comp.team_max)}"
            if comp.team_required else "个人赛，无需组队"
        ),
        "时间是否充足": (
            f"剩余约 {remaining_weeks:.1f} 周，工作量可承受度 {breakdown.workload_score}"
            if remaining_weeks is not None else "关键截止时间未知"
        ),
        "下一步": "补充缺失技能 / 组建团队 / 在截止前提交报名" if skill_gap or comp.team_required else "可直接报名",
    }


# ---------------------------------------------------------------------------
# 对外主入口
# ---------------------------------------------------------------------------


def recommend_for_user(
    user: UserProfile, competitions: list[Competition], current: date
) -> list[RecommendationResult]:
    """对全部赛事执行三层推荐，返回排序后的结果列表。"""
    results: list[RecommendationResult] = []

    for comp in competitions:
        # 时间问题属于明确的一票否决，保留结果以便 API / 评测解释 score=null。
        if not is_registerable_now(comp, current):
            results.append(
                RecommendationResult(
                    competition_id=comp.competition_id,
                    competition_name=comp.competition_name,
                    recommendation_status="ineligible",
                    eligible=False,
                    gate_reasons=[GateReason(reason="赛事当前已不可报名")],
                    explanation={"时间": "赛事已截止、已开赛或已结束，不进入评分"},
                )
            )
            continue
        source_readiness = assess_source_readiness(comp)
        pending = not source_readiness.ready
        # 第一层：数据有效性
        problems = data_validity_check(comp, current)
        if problems:
            # 来源或关键字段证据不完整：仅作为目录候选，不进行资格判断或评分。
            results.append(
                RecommendationResult(
                    competition_id=comp.competition_id,
                    competition_name=comp.competition_name,
                    recommendation_status="candidate_only",
                    eligible=False,
                    gate_reasons=[GateReason(reason=f"候选信息：{p}") for p in problems],
                    explanation={"数据状态": "关键证据待补充，仅在赛事目录展示"},
                    pending_review=pending,
                )
            )
            continue

        # 第二层：硬性门控
        eligible, reasons = eligibility_gate(user, comp, current)
        if not eligible:
            results.append(
                RecommendationResult(
                    competition_id=comp.competition_id,
                    competition_name=comp.competition_name,
                    recommendation_status="ineligible",
                    eligible=False,
                    gate_reasons=reasons,
                    explanation={
                        "资格": "不满足硬性资格或时间要求，一票否决",
                        "原因": [r.reason for r in reasons],
                    },
                    pending_review=pending,
                )
            )
            continue

        # 第三层：软性评分
        breakdown = soft_match_score(user, comp, current)
        status = _status_from_score(breakdown.total)
        effective_deadline = comp.registration_deadline or comp.submission_deadline
        urgent = effective_deadline is not None and 0 <= (effective_deadline - current).days <= 14
        results.append(
            RecommendationResult(
                competition_id=comp.competition_id,
                competition_name=comp.competition_name,
                recommendation_status=status,
                score=breakdown.total,
                eligible=True,
                match_breakdown=breakdown,
                explanation=_build_explanation(user, comp, breakdown, current),
                urgent=urgent,
                pending_review=pending,
            )
        )

    # 排序原则：正式推荐 -> 候选信息 -> 不符合项；正式推荐内部按适配度排序。
    results.sort(
        key=lambda r: (
            0 if r.eligible else 1,
            0 if r.recommendation_status == "candidate_only" else 1,
            -(r.score or 0),
            not r.urgent,
        )
    )
    return results


# ---------------------------------------------------------------------------
# 队友推荐：基于画像的互补匹配
# ---------------------------------------------------------------------------


def _grade_level(grade: str) -> int:
    return {"大一": 1, "大二": 2, "大三": 3, "大四": 4, "研究生": 5}.get(grade, 2)


def _teammate_score(seeker: UserProfile, c: UserProfile) -> tuple[float, list[str]]:
    """互补度评分（0-100）与中文理由。五个维度加权：技能互补40/专业互补25/年级搭配15/时间互补10/经验匹配10。"""
    reasons: list[str] = []
    seeker_skills = {s.lower() for s in seeker.skills}
    cand_skills = {s.lower() for s in c.skills}

    # 技能互补（40%）：候选具备而 seeker 缺失的技能越多，互补度越高
    missing = cand_skills - seeker_skills
    skill_comp = 100.0 * len(missing) / len(cand_skills) if cand_skills else 0.0
    if missing:
        shown = "、".join(list({s for s in c.skills if s.lower() in missing})[:3])
        reasons.append(f"技能互补：你尚未掌握的 {shown} 正是 TA 的强项")

    # 专业互补（25%）：跨学科组队视角更全
    if seeker.major != c.major:
        major_comp = 100.0
        reasons.append(f"专业互补：你是{seeker.major}，TA 是{c.major}，跨学科组合")
    else:
        major_comp = 45.0

    # 年级搭配（15%）：经验梯度合理
    diff = abs(_grade_level(seeker.grade) - _grade_level(c.grade))
    grade_comp = 100.0 if diff >= 2 else (80.0 if diff == 1 else 60.0)
    if diff >= 1:
        reasons.append(f"年级搭配：{seeker.grade} + {c.grade}，经验梯度合理")

    # 时间互补（10%）：每周可投入工时差异越大，节奏搭配越灵活
    maxh = max(seeker.weekly_available_hours, c.weekly_available_hours, 1)
    time_comp = 100.0 * (1 - abs(seeker.weekly_available_hours - c.weekly_available_hours) / maxh)
    if abs(seeker.weekly_available_hours - c.weekly_available_hours) >= 6:
        reasons.append(f"时间互补：TA 每周可投入 {c.weekly_available_hours}h，与你形成节奏搭配")

    # 经验匹配（10%）：候选有参赛经历即加分
    if c.experiences:
        exp_comp = 75.0
        reasons.append(f"经验加持：TA 有{'、'.join(c.experiences[:2])}等经历")
    else:
        exp_comp = 45.0

    total = (
        0.40 * skill_comp
        + 0.25 * major_comp
        + 0.15 * grade_comp
        + 0.10 * time_comp
        + 0.10 * exp_comp
    )
    return round(total, 1), reasons


def recommend_teammates(
    seeker: UserProfile, candidates: list[UserProfile], top_k: int = 5
) -> list[TeammateMatch]:
    """从候选池中为 seeker 推荐互补队友，按互补度降序返回前 top_k 名。"""
    matches: list[TeammateMatch] = []
    for c in candidates:
        if c.user_id == seeker.user_id:
            continue
        score, reasons = _teammate_score(seeker, c)
        edu = c.education_level.value if hasattr(c.education_level, "value") else str(c.education_level)
        matches.append(
            TeammateMatch(
                user_id=c.user_id,
                display_name=c.display_name,
                persona=c.persona,
                avatar=c.avatar,
                major=c.major,
                grade=c.grade,
                education_level=edu,
                skills=c.skills,
                experiences=c.experiences,
                weekly_available_hours=c.weekly_available_hours,
                match_score=score,
                reasons=reasons[:4],
            )
        )
    matches.sort(key=lambda m: m.match_score, reverse=True)
    return matches[:top_k]
