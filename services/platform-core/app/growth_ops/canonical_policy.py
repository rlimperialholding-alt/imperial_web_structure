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

# Owner-approved land-listing copy, 2026-08-25. The three anchors prevent a
# runtime template or later refactor from changing the product, commission, or
# property-owner offer without an explicit policy update.
LAND_OUTREACH_SERVICE_ANCHOR = (
    "Az Imperial Holding típustervek kulcsrakész építésével foglalkozik."
)
LAND_OUTREACH_SERVICE_ANCHOR_SHA256 = (
    "0220cfa5398c899f068acdf1530b7002ca00fcc422a2f6895c52883bbe02ee26"
)
LAND_AGENT_COMMISSION_ANCHOR = (
    "Ha az Ön által közvetített érdeklődő megvásárolja valamelyik típustervünket, "
    "az értékesített típusterv nettó árából 2,5%-ot fizetünk Önnek."
)
LAND_AGENT_COMMISSION_ANCHOR_SHA256 = (
    "487fa86e9ac27c22da12807ae314854bf5cdb0b0fc5519c80cd4dbaa5d105181"
)
LAND_OWNER_FREE_AD_ANCHOR = (
    "Ingyen, jutalék nélkül meghirdetjük az ingatlanát a telekhez illő típusházunkkal."
)
LAND_OWNER_FREE_AD_ANCHOR_SHA256 = (
    "09bff47f226817749a551e2cb8d7d44a9481e02d57829a6e47f09b191b1f380c"
)

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
    anchors = (
        (PARTNER_OUTREACH_ANCHOR, PARTNER_OUTREACH_ANCHOR_SHA256),
        (LAND_OUTREACH_SERVICE_ANCHOR, LAND_OUTREACH_SERVICE_ANCHOR_SHA256),
        (LAND_AGENT_COMMISSION_ANCHOR, LAND_AGENT_COMMISSION_ANCHOR_SHA256),
        (LAND_OWNER_FREE_AD_ANCHOR, LAND_OWNER_FREE_AD_ANCHOR_SHA256),
    )
    if any(
        hashlib.sha256(value.encode("utf-8")).hexdigest() != expected
        for value, expected in anchors
    ):
        raise RuntimeError("Owner-approved outreach anchor integrity check failed")
    if len(ACTIVE_CONTENT_BRANDS) != DAILY_CONTENT_BRAND_MINIMUM:
        raise RuntimeError("Canonical active-brand count is inconsistent")
    if len(set(ACTIVE_CONTENT_BRANDS)) != len(ACTIVE_CONTENT_BRANDS):
        raise RuntimeError("Canonical active-brand list contains duplicates")


def assert_outreach_copy(body: str) -> None:
    assert_policy_integrity()
    if LAND_OUTREACH_SERVICE_ANCHOR in body:
        has_agent_offer = LAND_AGENT_COMMISSION_ANCHOR in body
        has_owner_offer = LAND_OWNER_FREE_AD_ANCHOR in body
        if has_agent_offer == has_owner_offer:
            raise ValueError("owner_locked_land_outreach_offer_missing_or_mixed")
        return
    if PARTNER_OUTREACH_ANCHOR not in body:
        raise ValueError("owner_locked_partner_outreach_anchor_missing")


def contains_no_monitoring_entity(value: str) -> bool:
    normalized = " ".join(value.casefold().split())
    return any(name.casefold() in normalized for name in NO_MONITORING_HARD_GATE)


assert_policy_integrity()
