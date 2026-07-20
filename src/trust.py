"""Central recommendation-readiness rules for competition source data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath
from urllib.parse import urlparse

from schemas import Competition, DataStatus, TrustedLevel


REQUIRED_EVIDENCE_FIELDS = frozenset(
    {
        "registration_deadline",
        "eligible_students",
        "team_min",
        "team_max",
        "required_materials",
    }
)

_SEARCH_OR_AGGREGATOR_DOMAINS = (
    "baidu.com",
    "bing.com",
    "google.com",
    "sogou.com",
    "so.com",
    "toutiao.com",
    "weixin.qq.com",
    "zhihu.com",
)


@dataclass(frozen=True)
class ReadinessAssessment:
    ready: bool
    reasons: tuple[str, ...]


def _is_direct_source_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    return not any(host == domain or host.endswith(f".{domain}") for domain in _SEARCH_OR_AGGREGATOR_DOMAINS)


def _is_pdf_evidence(document_name: str | None, source_url: str | None) -> bool:
    candidates = (document_name or "", urlparse(source_url or "").path)
    return any(PurePosixPath(value.lower()).suffix == ".pdf" for value in candidates if value)


def _evidence_is_complete(item) -> bool:
    if not item.source_text.strip() or not _is_direct_source_url(item.source_url):
        return False
    if not item.acquired_date or not item.last_verified_at:
        return False
    if _is_pdf_evidence(item.document_name, item.source_url) and not isinstance(item.page, int):
        return False
    return True


def is_registerable_now(comp: Competition, current: date) -> bool:
    """Return whether registration is still plausibly open on ``current``."""
    if comp.competition_start_date is not None and comp.competition_start_date <= current:
        return False
    if comp.competition_end_date is not None and comp.competition_end_date < current:
        return False
    if comp.registration_deadline is not None and comp.registration_deadline < current:
        return False
    if (
        comp.registration_deadline is None
        and comp.submission_deadline is not None
        and comp.submission_deadline < current
    ):
        return False
    return True


def assess_source_readiness(comp: Competition) -> ReadinessAssessment:
    """Assess whether official-source data is complete enough for scoring."""
    reasons: list[str] = []
    if comp.data_status != DataStatus.VERIFIED:
        reasons.append("官网来源尚未确认")
    if comp.trusted_level != TrustedLevel.A:
        reasons.append("可信等级未达到 A")
    if comp.official_source_status != "found":
        reasons.append("未找到官方来源")
    if not _is_direct_source_url(comp.official_source_url):
        reasons.append("官方链接缺失或不是直接来源")
    if not comp.eligible_students:
        reasons.append("缺少明确参赛对象")
    if comp.registration_deadline is None and comp.submission_deadline is None:
        reasons.append("缺少有效报名时间")

    complete_fields = {
        item.field for item in comp.evidence if item.field in REQUIRED_EVIDENCE_FIELDS and _evidence_is_complete(item)
    }
    missing = REQUIRED_EVIDENCE_FIELDS - complete_fields
    if missing:
        reasons.append(f"关键字段证据不完整：{', '.join(sorted(missing))}")
    return ReadinessAssessment(ready=not reasons, reasons=tuple(reasons))


def assess_recommendation_readiness(
    comp: Competition, current: date | None = None
) -> ReadinessAssessment:
    """Assess source trust and, when supplied, whether the event is still open."""
    source = assess_source_readiness(comp)
    reasons = list(source.reasons)
    if current is not None and not is_registerable_now(comp, current):
        reasons.append("当前已不可报名")
    return ReadinessAssessment(ready=not reasons, reasons=tuple(reasons))
