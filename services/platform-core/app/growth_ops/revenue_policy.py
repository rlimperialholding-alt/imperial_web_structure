"""Fail-closed revenue intent policy shared by Question Radar and Content Factory.

This module is deliberately side-effect free.  It decides whether a radar signal
contains enough evidence for a content brief; it never authorises publication,
distribution, or email delivery.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

REVENUE_POLICY_VERSION = "content-intent-revenue-v1"
POLICY = "content-intent-revenue/2026-09-06.v1"
CONTENT_TYPES = {"demand_capture", "sales_objection", "proof", "opportunity", "partner_enablement"}
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
    plain = _plain(text)
    return any(marker in normalized for marker in _PURCHASE_MARKERS) or bool(
        re.search(
            r"(?:kivitelező|kivitelezo|generálkivitelező|generalkivitelezo)\w*\s+"
            r"(?:keres(?:ek|ünk|unk)|visszamondta|eltűnt|eltunt|nem vállalja|nem vallalja)"
            r"|ajánlatkérés|ajanlatkeres|rendelési? szándék|rendelesi? szandek"
            r"|ajanlatot\s+kerek|kerek\s+arajanlatot|arajanlatot\s+kerek",
            plain,
        )
    )


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone_required")
    return value.astimezone(UTC)


def _norm(text: Any) -> str:
    return " ".join(str(text or "").casefold().split())


def _plain(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", _norm(text)) if not unicodedata.combining(c)
    )


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def canonical_url(raw: str) -> str:
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("public_https_permalink_required")
    tracking = {"fbclid", "gclid", "msclkid"}
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in tracking
    ]
    return urlunsplit(
        (
            "https",
            parsed.netloc.lower(),
            parsed.path or "/",
            urlencode(sorted(query)),
            parsed.fragment,
        )
    )


def identity(source_url: str, native_id: str = "") -> str:
    url = canonical_url(source_url)
    material = [urlsplit(url).hostname, native_id] if native_id else [url]
    return hashlib.sha256(_json(material)).hexdigest()


def observed_window(
    raw: str, observed_at: datetime, source_timezone: str = "Europe/Budapest"
) -> tuple[datetime, datetime]:
    """Return a conservative publication interval bound to the observed post.

    Search-snippet dates, page-modified dates, and naive timestamps are rejected.
    Date-only and relative labels remain intervals; discovery time never becomes
    the publication time.
    """
    observed = _utc(observed_at)
    zone = ZoneInfo(source_timezone)
    text = _norm(raw).strip(" .,")
    day: date | None = None
    if text in {"ma", "today"}:
        day = observed.astimezone(zone).date()
    elif text in {"tegnap", "yesterday"}:
        day = observed.astimezone(zone).date() - timedelta(days=1)
    else:
        relative = re.fullmatch(
            r"(\d+)\s*(perce|órája|oraja|napja|hete|minutes? ago|hours? ago|days? ago|weeks? ago)",
            text,
        )
        if relative:
            amount, unit = int(relative[1]), relative[2]
            seconds = (
                60
                if unit.startswith(("perc", "minute"))
                else 3600
                if unit.startswith(("ór", "or", "hour"))
                else 86400
                if unit.startswith(("nap", "day"))
                else 604800
            )
            return (
                observed - timedelta(seconds=(amount + 1) * seconds),
                observed - timedelta(seconds=amount * seconds),
            )
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            day = date.fromisoformat(text)
        else:
            stamp = datetime.fromisoformat(text.replace("z", "+00:00"))
            stamp = _utc(stamp)
            return stamp, stamp
    start = datetime.combine(day, time.min, zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)
    return start, min(end, observed) if start <= observed else end


_FEATURES = {
    "explicit_request": (
        45,
        r"(?:kivitelezo\w*|generalkivitelezo\w*|epitoceg\w*)\s+keres(?:ek|unk)|ajanlatot\s+ker(?:ek|unk)|ajanlatkeres",
    ),
    "contractor_cancelled": (
        45,
        r"kivitelezo\w*\s+(?:visszamondta|eltunt|nem vallalja)|(?:befejezo|masik)\s+kivitelezo",
    ),
    "land_owned": (20, r"(?:megvan|megvettem|megvettuk)\s+(?:a\s+)?telk\w*|van\s+telk(?:em|unk)"),
    "plans_ready": (
        20,
        r"(?:keszen|megvannak)\s+(?:vannak\s+)?(?:a\s+)?tervek|megvan\s+(?:az\s+)?(?:epitesi\s+)?engedely",
    ),
    "size_defined": (10, r"\b\d{2,4}\s*(?:m²|m2|nm|negyzetmeter)\b"),
    "budget_declared": (
        10,
        r"\b(?:keret|koltsegkeret|rendelkezesre all)\w*[^.!?]{0,35}"
        r"\d+[^.!?]{0,15}(?:millio|forint|ft)",
    ),
    "start_defined": (
        10,
        r"(?:szeptember|oktober|november|december|januar|februar|marcius|aprilis|majus|junius|julius|augusztus|azonnal|jovo\s+honap)[^.!?]{0,35}(?:kezden|indul)|(?:kezden|indul)[^.!?]{0,35}(?:honap|heten|azonnal)",
    ),
}
_CLOSED_PATTERN = (
    r"mar\s+(?:talaltam|talaltunk|megoldodott)|nem\s+keres(?:ek|unk)|"
    r"targytalan|lezart\s+(?:kerdes|projekt)|megoldva"
)
_PROVIDER_PATTERN = (
    r"(?:kivitelezest|hazepitest|epitest)\s+vallalunk|keressen\s+minket|megrendeleseket\s+varunk"
)


def score_intent(text: str) -> tuple[int, dict[str, str]]:
    clean = _plain(text)
    matched = {
        name: match.group(0)
        for name, (_, pattern) in _FEATURES.items()
        if (match := re.search(pattern, clean))
    }
    return min(100, sum(_FEATURES[name][0] for name in matched)), matched


def assess_signal(evidence: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """Classify adapter-proven evidence without granting contact permission."""
    current = _utc(now)
    text = str(evidence.get("text") or "")
    score, features = score_intent(text)
    result: dict[str, Any] = {
        "policy": POLICY,
        "queue": "UNVERIFIED",
        "lead_eligible": False,
        "contact_allowed": False,
        "intent_score": score,
        "features": features,
        "funding_status": "declared_unverified" if "budget_declared" in features else "unknown",
        "reasons": [],
        "identity": None,
        "age_hours_max": None,
    }
    try:
        result["identity"] = identity(
            str(evidence.get("source_url") or ""), str(evidence.get("native_id") or "")
        )
        observed = _utc(evidence["observed_at"])
        if observed > current:
            raise ValueError("observation_in_future")
        if (
            evidence.get("source_scoped") is not True
            or evidence.get("permalink_verified") is not True
        ):
            raise ValueError("post_scoped_evidence_required")
        proof = evidence.get("timestamp_proof")
        if proof not in {"post_published", "author_renewal"}:
            raise ValueError("post_publication_proof_required")
        if proof == "author_renewal" and evidence.get("renewal_by_original_author") is not True:
            raise ValueError("third_party_bump_is_not_new_demand")
        earliest, latest = observed_window(
            str(evidence.get("published_at_raw") or ""),
            observed,
            str(evidence.get("source_timezone") or "Europe/Budapest"),
        )
        if earliest > observed or latest > observed:
            raise ValueError("publication_in_future")
        age = (current - earliest).total_seconds() / 3600
        result.update(
            age_hours_max=age,
            published_at_earliest=earliest.isoformat(),
            published_at_latest=latest.isoformat(),
        )
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        result["reasons"] = [str(exc) if isinstance(exc, ValueError) else "invalid_source_evidence"]
        return result
    if evidence.get("closed") is True or re.search(_CLOSED_PATTERN, _plain(text)):
        result.update(queue="CLOSED", reasons=["project_closed_or_no_longer_seeking"])
    elif re.search(_PROVIDER_PATTERN, _plain(text)):
        result.update(queue="RESEARCH_ONLY", reasons=["provider_advert_not_buyer"])
    elif age > 720:
        result.update(queue="RESEARCH_ONLY", reasons=["older_than_30_days"])
    elif age > 168:
        result.update(queue="CONTENT_SIGNAL", reasons=["older_than_7_days"])
    elif not ({"explicit_request", "contractor_cancelled"} & features.keys()):
        result.update(queue="CONTENT_SIGNAL", reasons=["no_explicit_buying_trigger"])
    elif score < 45 or (age > 72 and score < 80):
        result.update(queue="CONTENT_SIGNAL", reasons=["insufficient_intent_for_age"])
    elif age <= 24 and score >= 65:
        result.update(queue="HOT", lead_eligible=True)
    else:
        result.update(queue="WARM" if age <= 72 else "QUALIFIED_7D", lead_eligible=True)
    return result


def unique_signals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.get("identity")
        if not key:
            continue
        old = selected.get(key)
        age = row.get("age_hours_max")
        old_age = old.get("age_hours_max") if old else None
        if old is None or (age is not None and (old_age is None or age < old_age)):
            selected[key] = row
    return list(selected.values())


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


def verify_fact_registry(
    document: Mapping[str, Any], *, key: bytes, now: datetime
) -> dict[str, dict[str, Any]]:
    """Authenticate operator-approved public facts and filter expired/private rows."""
    if len(key) < 32:
        raise ValueError("approval_key_too_short")
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    expected = hmac.new(key, _json(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(document.get("signature", "")), expected):
        raise ValueError("fact_registry_signature_invalid")
    if document.get("policy") != POLICY:
        raise ValueError("fact_registry_policy_mismatch")
    current = _utc(now)
    facts: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    if not isinstance(document.get("facts"), list):
        raise ValueError("fact_list_required")
    for row in document["facts"]:
        if not isinstance(row, dict):
            raise ValueError("fact_object_required")
        identifier = str(row.get("id") or "")
        if not identifier or identifier in seen_ids:
            raise ValueError("fact_id_missing_or_duplicate")
        seen_ids.add(identifier)
        if not row.get("brand_id") or not row.get("statement") or row.get("public") is not True:
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("source_sha256") or "")):
            continue
        try:
            canonical_url(str(row["source_url"]))
            verified = _utc(datetime.fromisoformat(str(row["verified_at"])))
            expires = _utc(datetime.fromisoformat(str(row["expires_at"])))
        except (ValueError, KeyError, TypeError):
            continue
        if not verified <= current < expires:
            continue
        if row.get("kind") == "price" and not all(
            row.get(k) for k in ("vat_basis", "unit", "scope")
        ):
            continue
        facts[identifier] = dict(row)
    return facts


def assess_content(
    package: Mapping[str, Any],
    *,
    brand_id: str,
    facts: Mapping[str, Mapping[str, Any]],
    now: datetime,
    demand_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply deterministic commercial and evidence gates in addition to editorial gates."""
    current = _utc(now)
    reasons: list[str] = []
    if package.get("brand_id") != brand_id:
        reasons.append("brand_mismatch")
    if package.get("content_type") not in CONTENT_TYPES:
        reasons.append("commercial_content_type_missing")
    for field in ("customer_problem", "buyer_stage", "business_goal"):
        if len(str(package.get(field) or "").strip()) < 8:
            reasons.append(field + "_missing")
    steps = package.get("practical_steps")
    if (
        not isinstance(steps, list)
        or len(steps) < 2
        or any(len(str(step).strip()) < 15 for step in steps)
    ):
        reasons.append("practical_decision_help_missing")
    demand_ids = package.get("demand_evidence_ids")
    if (not isinstance(demand_ids, list) or not demand_ids) and package.get(
        "content_type"
    ) != "proof":
        reasons.append("observed_customer_problem_required")
    for demand_id in demand_ids if isinstance(demand_ids, list) else []:
        record = (demand_evidence or {}).get(str(demand_id))
        if (
            not record
            or record.get("brand_id") != brand_id
            or record.get("privacy_reviewed") is not True
        ):
            reasons.append("demand_evidence_not_verified_for_brand")
            continue
        try:
            if _utc(datetime.fromisoformat(str(record["verified_at"]))) > current:
                raise ValueError("future")
            if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("excerpt_sha256") or "")):
                raise ValueError("missing_hash")
        except (ValueError, KeyError, TypeError):
            reasons.append("demand_evidence_proof_invalid")
    cta = package.get("cta")
    if not isinstance(cta, dict) or not cta.get("label") or not cta.get("action"):
        reasons.append("specific_next_step_required")
        cta = {}
    claims = package.get("claims")
    if not isinstance(claims, list) or not claims:
        reasons.append("needs_evidence")
        claims = []
    texts = {key: str(package.get(key) or "") for key in ("title", "body", "facebook_post")}
    texts["cta"] = str(cta.get("label") or "")
    public_copy = _norm(" ".join(texts.values()))
    if _norm(package.get("customer_problem")) not in public_copy:
        reasons.append("customer_problem_not_in_public_copy")
    if isinstance(steps, list) and any(_norm(step) not in public_copy for step in steps):
        reasons.append("practical_steps_not_in_public_copy")
    coverage: dict[str, list[tuple[int, int]]] = {key: [] for key in texts}
    used: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            reasons.append("claim_object_required")
            continue
        fact_id = str(claim.get("fact_id") or "")
        fact = facts.get(fact_id)
        field, span = str(claim.get("field") or ""), str(claim.get("text") or "")
        if not fact or fact.get("brand_id") != brand_id or fact.get("public") is not True:
            reasons.append("claim_has_no_approved_brand_fact")
            continue
        try:
            if (
                not _utc(datetime.fromisoformat(str(fact["verified_at"])))
                <= current
                < _utc(datetime.fromisoformat(str(fact["expires_at"])))
            ):
                raise ValueError("expired")
        except (KeyError, TypeError, ValueError):
            reasons.append("claim_expired_or_unverified")
            continue
        if (
            field not in texts
            or not span
            or span != fact.get("statement")
            or span not in texts[field]
        ):
            reasons.append("claim_text_not_bound_to_approved_statement")
            continue
        coverage[field].extend(
            (match.start(), match.end()) for match in re.finditer(re.escape(span), texts[field])
        )
        used.add(fact_id)
    for field, value in texts.items():
        for match in re.finditer(r"\d+(?:[.,]\d+)?", value):
            if not any(
                start <= match.start() and match.end() <= end for start, end in coverage[field]
            ):
                reasons.append("unbound_numeric_claim:" + field)
    capability = facts.get(str(cta.get("capability_fact_id") or ""))
    if (
        not capability
        or capability.get("brand_id") != brand_id
        or capability.get("kind") != "capability"
    ):
        reasons.append("cta_capability_not_approved")
    else:
        try:
            if capability.get("public") is not True or not _utc(
                datetime.fromisoformat(str(capability["verified_at"]))
            ) <= current < _utc(datetime.fromisoformat(str(capability["expires_at"]))):
                raise ValueError("expired")
        except (ValueError, KeyError, TypeError):
            reasons.append("cta_capability_expired_or_private")
        if str(cta.get("action")) not in (capability.get("allowed_actions") or []):
            reasons.append("cta_action_outside_approved_scope")
    if package.get("content_type") == "proof" and not any(
        facts[fact_id].get("kind") == "case_study" for fact_id in used
    ):
        reasons.append("real_case_study_evidence_required")
    if not used:
        reasons.append("needs_evidence")
    return {
        "policy": POLICY,
        "status": "BLOCKED" if reasons else "PASS",
        "publish_allowed": False,
        "reasons": sorted(set(reasons)),
        "approved_fact_ids": sorted(used),
    }
