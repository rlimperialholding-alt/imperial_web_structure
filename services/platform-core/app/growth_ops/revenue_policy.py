"""Fail-closed revenue intent policy shared by Question Radar and Content Factory.

This module is deliberately side-effect free.  It decides whether a radar signal
contains enough evidence for a content brief; it never authorises publication,
distribution, or email delivery.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

REVENUE_POLICY_VERSION = "content-intent-revenue-v1"
_FRESHNESS_DECISIONS = {"preferred_0_30_days", "accepted_31_90_days"}
_PURCHASE_MARKERS = (
    "keresek",
    "vennék",
    "vennek",
    "vásárolnék",
    "vasarolnek",
    "rendelnék",
    "rendelnek",
    "ajánlatot kérek",
    "ajanlatot kérek",
    "ára érdekel",
    "ara erdekel",
    "mennyiért vállal",
    "mennyiert vallal",
    "megrendelné",
    "megrendelne",
)


class SourceReplenishmentRequired(ValueError):
    """Raised when content lacks a usable approved fact source."""

    def __init__(self, reasons: list[str]):
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(", ".join(self.reasons) or "approved_source_missing")


def is_purchase_signal(text: str) -> bool:
    normalized = " ".join(str(text or "").casefold().split())
    return any(marker in normalized for marker in _PURCHASE_MARKERS)


def _clean_url(value: object) -> str:
    value = str(value or "").strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.fragment:
        return ""
    return value.rstrip("/")


def _topic_value(topic: object, key: str, default: object = None) -> object:
    if isinstance(topic, Mapping):
        return topic.get(key, default)
    return getattr(topic, key, default)


def revalidate_topic_for_use(
    topic: object,
    *,
    source_snapshot: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_age_days: int = 90,
) -> dict[str, Any]:
    """Re-read the stored identity and freshness fields immediately before use.

    A caller that fetched the source again supplies ``source_snapshot``.  Without
    it, the function still performs a database-backed snapshot check; it never
    upgrades an unknown or legacy record to eligible.
    """

    current = now or datetime.now(UTC)
    source = source_snapshot or {}
    url = _clean_url(source.get("source_url", _topic_value(topic, "source_url")))
    reasons: list[str] = []
    if not url:
        reasons.append("source_url_missing")
    if _topic_value(topic, "eligibility_status") != "eligible":
        reasons.append("freshness_not_eligible")
    if _topic_value(topic, "freshness_decision") not in _FRESHNESS_DECISIONS:
        reasons.append("freshness_unverified_or_expired")
    published_at = source.get("published_at", _topic_value(topic, "published_at"))
    if not published_at:
        reasons.append("published_date_unverified")
    elif isinstance(published_at, str):
        try:
            published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            reasons.append("published_date_unparseable")
    if isinstance(published_at, datetime):
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
        age_days = (current.astimezone(UTC).date() - published_at.astimezone(UTC).date()).days
        if age_days < 0 or age_days > max_age_days:
            reasons.append("published_date_out_of_range")
    else:
        age_days = _topic_value(topic, "age_days")
        if not isinstance(age_days, int) or age_days < 0 or age_days > max_age_days:
            reasons.append("age_unverified")
    active = str(source.get("active_status", _topic_value(topic, "active_status")) or "").casefold()
    if active != "active":
        reasons.append("source_not_proven_active")
    answers = source.get("existing_answer_count", _topic_value(topic, "existing_answer_count"))
    if not isinstance(answers, int):
        reasons.append("answer_count_unverified")
    elif answers != 0:
        reasons.append("already_answered")
    if source.get("source_url") and _clean_url(source.get("source_url")) != _clean_url(
        _topic_value(topic, "source_url")
    ):
        reasons.append("source_identity_changed")
    return {
        "eligible": not reasons,
        "reasons": sorted(set(reasons)),
        "source_url": url,
        "policy": REVENUE_POLICY_VERSION,
        "revalidated_at": current.isoformat(),
    }


def evaluate_revenue_intent(
    intent: Mapping[str, Any],
    *,
    brand_id: str | None = None,
    approved_brand_facts: list[Mapping[str, Any]] | None = None,
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if brand_id and str(intent.get("brand_id")) != brand_id:
        reasons.append("brand_mismatch")
    for field, minimum in (("buyer_problem", 12), ("sales_goal", 3), ("next_step", 8)):
        if len(str(intent.get(field) or "").strip()) < minimum:
            reasons.append(f"{field}_missing")
    facts = (
        approved_brand_facts
        if approved_brand_facts is not None
        else intent.get("approved_brand_facts")
    )
    if not isinstance(facts, list) or not facts:
        reasons.append("approved_brand_fact_missing")
    elif any(
        not isinstance(item, Mapping)
        or not str(item.get("source_key") or item.get("id") or "").strip()
        for item in facts
    ):
        reasons.append("approved_brand_fact_invalid")
    refs = source_refs if source_refs is not None else intent.get("source_refs")
    if not isinstance(refs, list) or not refs or any(not _clean_url(item) for item in refs):
        reasons.append("usable_source_missing")
    return {
        "eligible": not reasons,
        "reasons": sorted(set(reasons)),
        "policy": REVENUE_POLICY_VERSION,
        "publication_allowed": False,
        "send_allowed": False,
    }


def build_revenue_intent(
    topic: object,
    *,
    approved_brand_facts: list[Mapping[str, Any]],
    sales_goal: str,
    next_step: str,
    now: datetime | None = None,
    source_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    revalidation = revalidate_topic_for_use(topic, source_snapshot=source_snapshot, now=now)
    if not revalidation["eligible"]:
        raise SourceReplenishmentRequired(list(revalidation["reasons"]))
    intent = {
        "policy": REVENUE_POLICY_VERSION,
        "brand_id": str(_topic_value(topic, "brand_id") or ""),
        "radar_topic_id": str(_topic_value(topic, "topic_id") or ""),
        "buyer_problem": str(_topic_value(topic, "question") or "").strip(),
        "sales_goal": sales_goal.strip(),
        "approved_brand_facts": [dict(item) for item in approved_brand_facts],
        "next_step": next_step.strip(),
        "source_refs": [revalidation["source_url"]],
        "revalidation": revalidation,
        "publication_allowed": False,
        "send_allowed": False,
    }
    decision = evaluate_revenue_intent(intent, brand_id=intent["brand_id"])
    if not decision["eligible"]:
        raise SourceReplenishmentRequired(list(decision["reasons"]))
    return intent


def is_replenishment_needed(topic: object, approved_brand_facts: list[Mapping[str, Any]]) -> bool:
    """Small helper used by workers and tests to keep missing-source behaviour explicit."""
    try:
        build_revenue_intent(
            topic,
            approved_brand_facts=approved_brand_facts,
            sales_goal="minősített érdeklődőből ajánlatkérés",
            next_step="Kérjünk be rövid helyzetleírást.",
        )
    except SourceReplenishmentRequired:
        return True
    return False
