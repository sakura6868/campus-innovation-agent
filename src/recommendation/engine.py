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
    UserProfile,
)
from fact_formatting import format_team_size


# ---------------------------------------------------------------------------
# 第一层：数据有效性检查
# ---------------------------------------------------------------------------


def data_validity_check(comp: Competition, current: date) -> list[str]:
    """返回阻止赛事进入正式推荐的原因；空列表表示数据可用。"""
    problems: list[str] = []
    if not comp.official_source_url:
        problems.append("缺少官方来源")
    if comp.document_year is None:
        problems.append("缺少明确年份")
    if comp.registration_deadline is None and comp.submission_deadline is None:
        problems.append("缺少有效报名时间")
    if comp.data_status == DataStatus.UNVERIFIED:
        problems.append("尚未完成人工核验")
    if comp.data_status == DataStatus.STALE:
        problems.append("长期未核验（超过90天）")
    return problems


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
        pending = comp.data_status == DataStatus.UNVERIFIED
        # 第一层：数据有效性
        problems = data_validity_check(comp, current)
        if pending:
            results.append(
                RecommendationResult(
                    competition_id=comp.competition_id,
                    competition_name=comp.competition_name,
                    recommendation_status="candidate_only",
                    eligible=False,
                    gate_reasons=[GateReason(reason=f"候选信息：{p}") for p in problems],
                    explanation={
                        "数据状态": "待人工核验，仅作为候选信息展示",
                        "评分状态": "未进入资格门控和软性评分",
                    },
                    pending_review=True,
                )
            )
            continue
        if problems:
            # 数据不可靠：不进入正式推荐列表，仅记录
            results.append(
                RecommendationResult(
                    competition_id=comp.competition_id,
                    competition_name=comp.competition_name,
                    recommendation_status="ineligible",
                    eligible=False,
                    gate_reasons=[GateReason(reason=f"数据不可用：{p}") for p in problems],
                    explanation={"数据状态": "来源不可靠，未进入正式推荐"},
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
