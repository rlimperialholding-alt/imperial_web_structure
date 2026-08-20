from __future__ import annotations

import hashlib
from dataclasses import dataclass

SPEC_VERSION = "2026-08-20-canonical-wide-v1"
SOURCE_LEDGER_SPREADSHEET_ID = "1ddn6e2EbuafPc_S9_eb6oetBQsp4iOO9cFuMD6sQ4H4"
SOURCE_LEDGER_SHEET_ID = 959591161
SOURCE_LEDGER_SHEET_NAME = "Útvonal-nyilvántartás"
SOURCE_LEDGER_ROUTE_COUNT = 25_494

DAILY_UNIQUE_LEAD_MINIMUM = 100
DAILY_QUESTION_TOPIC_MINIMUM = 80
DAILY_ROUTE_ATTEMPT_MINIMUM = 800
DAILY_CONTENT_BRAND_MINIMUM = 19

IORA_EXECUTIVE_NAME = "Právicz Anna"
IORA_EXECUTIVE_EMAIL = "ugyvezeto@imperialholding.hu"
IORA_INTERNAL_SENDER = "info@imperialholding.hu"

# Owner-provided, customer-facing anchor. It is deliberately not an LLM prompt.
PARTNER_OUTREACH_ANCHOR = (
    "Szeretnénk felajánlani szakmai segítségünket és kapacitásunkat a projekthez, "
    "ha szükség van ránk."
)
PARTNER_OUTREACH_ANCHOR_SHA256 = "7004cccbda5c2e45109edf92474791a4b2fd268d8ffe2de08d093c32f1b1e24f"

ACTIVE_CONTENT_BRANDS = (
    "Imperial",
    "Bautica",
    "Prefab",
    "Casa Moderna",
    "BauFreund",
    "Danish Fabrik",
    "TimberHaus",
    "RED Property",
    "Property360",
    "Everyday Homes",
    "Venture Studio",
    "Family Homes",
    "Imperial Construction",
    "Imperial Intelligence",
    "Imperial Technologies",
    "Imperial Knowledge",
    "ExitFlow",
    "Veritas Construct",
    "BauShield",
)

# The canonical hard gate remains ACTIVE / FAIL_CLOSED. Matching content must not be
# queried, fetched, stored, enriched, prompted, handed off, published, or contacted.
NO_MONITORING_HARD_GATE = (
    "Homes4you",
    "HWS Home",
    "Horizont Global",
)

ETDR_BRANCHES = (
    "NEW_OR_CHANGED_RECORD_DELTA",
    "ETDR_START_NOT_VERIFIED",
    "ETDR_COMPLETION_NOT_VERIFIED",
)


@dataclass(frozen=True)
class DailyGateResult:
    route_attempts: int
    unique_leads: int
    question_topics: int
    content_brands: int

    @property
    def errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.route_attempts < DAILY_ROUTE_ATTEMPT_MINIMUM:
            errors.append("route_attempt_minimum_not_met")
        if self.unique_leads < DAILY_UNIQUE_LEAD_MINIMUM:
            errors.append("unique_lead_minimum_not_met")
        if self.question_topics < DAILY_QUESTION_TOPIC_MINIMUM:
            errors.append("question_topic_minimum_not_met")
        if self.content_brands < DAILY_CONTENT_BRAND_MINIMUM:
            errors.append("all_brand_content_minimum_not_met")
        return tuple(errors)

    @property
    def passed(self) -> bool:
        return not self.errors


def assert_policy_integrity() -> None:
    actual = hashlib.sha256(PARTNER_OUTREACH_ANCHOR.encode("utf-8")).hexdigest()
    if actual != PARTNER_OUTREACH_ANCHOR_SHA256:
        raise RuntimeError("Partner outreach anchor integrity check failed")
    if len(ACTIVE_CONTENT_BRANDS) != DAILY_CONTENT_BRAND_MINIMUM:
        raise RuntimeError("Canonical active-brand count is inconsistent")
    if len(set(ACTIVE_CONTENT_BRANDS)) != len(ACTIVE_CONTENT_BRANDS):
        raise RuntimeError("Canonical active-brand list contains duplicates")


def assert_outreach_copy(body: str) -> None:
    assert_policy_integrity()
    if PARTNER_OUTREACH_ANCHOR not in body:
        raise ValueError("owner_locked_partner_outreach_anchor_missing")


def contains_no_monitoring_entity(value: str) -> bool:
    normalized = " ".join(value.casefold().split())
    return any(name.casefold() in normalized for name in NO_MONITORING_HARD_GATE)


assert_policy_integrity()
