from __future__ import annotations

import hashlib
import re
import unicodedata
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

# Owner-approved land-listing copy, revised 2026-08-25. These subjects and
# anchors prevent a runtime template or later refactor from changing the
# product, commission, or property-owner offer without an explicit policy
# update.
LAND_OWNER_SUBJECT = "szeretnék érdeklődni a telek iránt"
LAND_OWNER_SUBJECT_SHA256 = (
    "792451ca4fd342fdf19cf530caa910030e8a5e06f96eec39f3b02700ea4159e5"
)
LAND_AGENT_SUBJECT = "ház eladásában kérnék segítséget"
LAND_AGENT_SUBJECT_SHA256 = (
    "4f5460a60567e226c1fb4c4e4a28b59315738a2eda21ce37eebdbf6d28b43334"
)
LAND_CATALOG_URL = "https://imperialholding.hu/termek/telek-kereso"
LAND_OUTREACH_SERVICE_ANCHOR = (
    "előregyártott készházak és típusházak építésével foglalkozik"
)
LAND_OUTREACH_SERVICE_ANCHOR_SHA256 = (
    "49b13d78545af86f7cce867c44567cf7575085228b7cc81415e16208683d39f3"
)
LAND_AGENT_COMMISSION_ANCHOR = (
    "2,5% jutalékot fizetünk azoknak az ingatlanos partnereinknek, akik a hirdetett "
    "telkeik mellé valamelyik típusházunkat is eladják."
)
LAND_AGENT_COMMISSION_ANCHOR_SHA256 = (
    "ae48724a42c7de14cb30a6715ce488f314320c12b566ac4255ba8bf6ac1bb393"
)
LAND_OWNER_FREE_AD_ANCHOR = (
    "Szívesen felvennénk a kínálatunkba DÍJMENTESEN, mert sokan keresnek nálunk a "
    "típusházakhoz eladó telkeket."
)
LAND_OWNER_FREE_AD_ANCHOR_SHA256 = (
    "d232996df9487fa74c70c2d517939cd209e8b8422d880a36f953c7ea5f25ac60"
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

# Owner-mandated land-agent exclusions, approved 2026-08-25. These are evaluated
# independently from scoring and global email suppression. An Otthon Centrum agent
# must carry verified office affiliation so the II./II/A. and XII. district office
# exclusions cannot be bypassed by an incomplete source record.
LAND_AGENT_BLOCKED_OC_OFFICE_ALIASES = (
    "bem rakpart",
    "tdg",
    "hidegkuti ut",
    "lajos utca",
    "uromi utca",
    "mom park",
    "varosmajor utca",
)

LAND_AGENT_HARD_GATE_TURCZER = "land_agent_turczer_jozsef_hard_gate"
LAND_AGENT_HARD_GATE_GDN = "land_agent_gdn_network_hard_gate"
LAND_AGENT_HARD_GATE_OC_II_XII = "land_agent_otthon_centrum_ii_xii_office_hard_gate"
LAND_AGENT_HARD_GATE_OC_UNVERIFIED = "land_agent_otthon_centrum_office_unverified_hard_gate"
LAND_AGENT_HARD_GATE_AFFILIATION_UNVERIFIED = "land_agent_affiliation_unverified_hard_gate"
LAND_AGENT_HARD_GATE_REASONS = frozenset(
    {
        LAND_AGENT_HARD_GATE_TURCZER,
        LAND_AGENT_HARD_GATE_GDN,
        LAND_AGENT_HARD_GATE_OC_II_XII,
        LAND_AGENT_HARD_GATE_OC_UNVERIFIED,
        LAND_AGENT_HARD_GATE_AFFILIATION_UNVERIFIED,
    }
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
        (LAND_OWNER_SUBJECT, LAND_OWNER_SUBJECT_SHA256),
        (LAND_AGENT_SUBJECT, LAND_AGENT_SUBJECT_SHA256),
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


def _identity_fold(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_like = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_like.casefold()).split())


def _blocked_oc_office(office_name: str) -> bool:
    normalized = _identity_fold(office_name)
    district_pattern = re.compile(
        r"\b(?:ii(?:\s+a)?|2(?:\s+a)?|xii|12)\s+kerulet\b|\b(?:2|12)ker\b"
    )
    if district_pattern.search(normalized):
        return True
    if re.search(r"\b(?:102\d|112\d)\b", normalized):
        return True
    return any(alias in normalized for alias in LAND_AGENT_BLOCKED_OC_OFFICE_ALIASES)


def land_agent_hard_gate_reason(
    *,
    recipient_role: str,
    contact_name: str | None,
    organization_name: str | None,
    office_name: str | None,
    recipient_email: str | None,
    public_contact_url: str | None,
    evidence_url: str | None,
) -> str | None:
    """Return a non-overridable exclusion reason for a land-listing agent."""

    if recipient_role != "listing_agent":
        return None
    identity = _identity_fold(
        " ".join(
            value
            for value in (
                contact_name,
                organization_name,
                office_name,
                recipient_email,
                public_contact_url,
                evidence_url,
            )
            if value
        )
    )
    if re.search(r"\b(?:turczer\s+jozsef|jozsef\s+turczer)\b", identity):
        return LAND_AGENT_HARD_GATE_TURCZER
    if re.search(r"\bgdn\b", identity):
        return LAND_AGENT_HARD_GATE_GDN
    if not organization_name or not organization_name.strip():
        return LAND_AGENT_HARD_GATE_AFFILIATION_UNVERIFIED
    is_otthon_centrum = bool(
        re.search(r"\botthon\s+centrum\b|\boc\s+hu\b", identity)
    )
    if not is_otthon_centrum:
        return None
    if not office_name or not office_name.strip():
        return LAND_AGENT_HARD_GATE_OC_UNVERIFIED
    if _blocked_oc_office(office_name):
        return LAND_AGENT_HARD_GATE_OC_II_XII
    return None


assert_policy_integrity()
