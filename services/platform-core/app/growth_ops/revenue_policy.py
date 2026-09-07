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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

REVENUE_POLICY_VERSION = "content-intent-revenue-v1"
POLICY = "content-intent-revenue/2026-09-06.v1"
CONTENT_TYPES = {"demand_capture", "sales_objection", "proof", "opportunity", "partner_enablement"}
_FRESHNESS_DECISIONS = {"preferred_0_30_days", "accepted_31_90_days"}
_PURCHASE_MARKERS = (
    "keresek",
    "keresünk",
    "keresunk",
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
    plain = _buyer_authored_text(text)
    if re.search(_CLOSED_PATTERN, plain) or re.search(_PROVIDER_PATTERN, plain):
        return False
    return (
        score_intent(text)[0] >= 45
        or any(_plain(marker) in plain for marker in _PURCHASE_MARKERS)
        or bool(
            re.search(
                r"(?:kivitelező|kivitelezo|generálkivitelező|generalkivitelezo)\w*\s+"
                r"(?:keres(?:ek|ünk|unk)|visszamondta|eltűnt|eltunt|nem vállalja|nem vallalja)"
                r"|ajánlatkérés|ajanlatkeres|rendelési? szándék|rendelesi? szandek"
                r"|ajanlatot\s+kerek|kerek\s+arajanlatot|arajanlatot\s+kerek",
                plain,
            )
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


def _buyer_authored_text(text: str) -> str:
    """Keep explicit first-person requests separate from quoted/reported demand.

    This is a conservative textual safeguard, not proof of the author's identity.
    Adapters must still bind the body to its original post.
    """
    raw = re.sub(r"(?im)^[ \t]*>[^\n]*", " . ", str(text or ""))
    raw = re.sub(r"<blockquote\b[^>]*>.*?</blockquote>", " . ", raw, flags=re.I | re.S)
    for pattern in (r'"[^"\n]*"', r"[„“][^”\n]*”", r"«[^»\n]*»"):
        # Keep a sentence boundary so a preceding attribution cannot swallow
        # the author's independent request immediately after the quote.
        raw = re.sub(pattern, " . ", raw)
    clean = _plain(raw)
    # Flattened source text may retain attribution even when the HTML quote
    # container is gone. Do not attribute that reported first-person request
    # to the writer; a following independent sentence remains available.
    return re.sub(
        r"\b(?:idezet|idezem|peldamondat|mintaszoveg|olvastam|"
        r"(?:ismerosom|szomszedom|baratom|valaki|szerzo)[^.!?]{0,45}(?:irta|irja|mondta|kerdezte)|"
        r"(?:ezt|azt)\s+(?:irta|irja|mondta)[^.!?]{0,45})"
        r"\s*(?::|,?\s+hogy)\s*[^.!?]*(?:[.!?]|$)",
        " ", clean,
    )


_SPECIALIST_PATTERN = (
    r"(?:kivitelezo|generalkivitelezo|epitoceg|szakember|statikus|epitesz|"
    r"tervezo|tetofedo|badogos|villanyszerelo|vizszerelo|futesszerelo|"
    r"gazszerelo|burkolo|komuves|festo|acs|asztalos|szigetelo)\w*"
)
_FEATURES = {
    "explicit_request": (
        45,
        rf"\b{_SPECIALIST_PATTERN}\s+keres(?:ek|unk)\b|"
        rf"\bkeres(?:ek|unk)\b[^.!?;]{{0,90}}\b{_SPECIALIST_PATTERN}\b|"
        r"ajanlatot\s+ker(?:ek|unk)|ajanlatkeres|"
        rf"\b(?:tudtok|ajanlanatok|ajanljatok)\b[^.!?]{{0,90}}\b{_SPECIALIST_PATTERN}\b",
    ),
    "contractor_cancelled": (
        45,
        r"kivitelezo\w*\s+(?:visszamondta|eltunt|nem vallalja)|(?:befejezo|masik)\s+kivitelezo|"
        r"felbemaradt\s+(?:az?\s+)?(?:epitkezesem|epitkezesunk|hazunk\s+epitese)",
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
    r"(?:kivitelezest|hazepitest|epitest)\s+vallalunk|keressen\s+(?:minket|bizalommal)|"
    r"megrendeleseket\s+varunk|"
    rf"\b{_SPECIALIST_PATTERN}\b[^.!?]{{0,70}}\bvallal(?:ok|unk)\b|"
    r"\b(?:vallalok|vallalunk)\b[^.!?]{0,70}"
    r"(?:statikai|tervezes|tetofedes|villanyszereles|vizszereles|burkolas|festes|felmeres)|"
    r"\b(?:munkatars\w*|alkalmazott\w*)\s+keres(?:ek|unk)|"
    r"\b(?:ugyfel\w*|megrendelo\w*|megbizas\w*|munkat)\s+keres(?:ek|unk)|"
    r"\bkeres(?:ek|unk)\b[^.!?]{0,90}\bcsapatunkba\b"
)


def score_intent(text: str) -> tuple[int, dict[str, str]]:
    clean = _buyer_authored_text(text)
    if re.search(_CLOSED_PATTERN, clean) or re.search(_PROVIDER_PATTERN, clean):
        return 0, {}
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
    buyer_text = _buyer_authored_text(text)
    if evidence.get("closed") is True or re.search(_CLOSED_PATTERN, buyer_text):
        result.update(queue="CLOSED", reasons=["project_closed_or_no_longer_seeking"])
    elif re.search(_PROVIDER_PATTERN, buyer_text):
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
    try:
        return canonical_url(str(value or "").strip())
    except ValueError:
        return ""


def _topic_value(topic: object, key: str, default: object = None) -> object:
    if isinstance(topic, Mapping):
        return topic.get(key, default)
    return getattr(topic, key, default)


def revalidate_topic_for_use(
    topic: object,
    *,
    source_snapshot: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_age_days: int = 30,
    purpose: str = "content",
) -> dict[str, Any]:
    """Re-read the stored identity and freshness fields immediately before use.

    A caller that fetched the source again supplies ``source_snapshot``.  Without
    it, the function still performs a database-backed snapshot check; it never
    upgrades an unknown or legacy record to eligible.
    """

    current = _utc(now or datetime.now(UTC))
    source = source_snapshot or {}
    url = _clean_url(source.get("source_url", _topic_value(topic, "source_url")))
    reasons: list[str] = []
    if not url:
        reasons.append("source_url_missing")
    if source.get("error"):
        reasons.append("source_refresh_unavailable")
    if source_snapshot is None and _topic_value(topic, "eligibility_status") != "eligible":
        reasons.append("freshness_not_eligible")
    if source_snapshot is None and _topic_value(topic, "freshness_decision") not in (
        _FRESHNESS_DECISIONS | {"HOT", "WARM", "QUALIFIED_7D", "CONTENT_SIGNAL"}
    ):
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
            if "published_at" in source:
                reasons.append("published_date_timezone_missing")
            published_at = published_at.replace(tzinfo=UTC)
        age_days = (current - published_at.astimezone(UTC)).total_seconds() / 86400
        if age_days < 0 or age_days > max_age_days:
            reasons.append("published_date_out_of_range")
    else:
        age_days = _topic_value(topic, "age_days")
        if not isinstance(age_days, int) or age_days < 0 or age_days > max_age_days:
            reasons.append("age_unverified")
    active = str(source.get("active_status", _topic_value(topic, "active_status")) or "").casefold()
    if purpose == "reply" and active != "active":
        reasons.append("source_not_proven_active")
    elif active in {"closed", "deleted", "resolved", "expired", "inactive"}:
        reasons.append("source_closed_or_unavailable")
    # Replies on a thread do not prove the buyer's need was fulfilled.
    # Recompute demand age/intent instead of treating any reply as a closed sale.
    decision = None
    if isinstance(published_at, datetime):
        decision = assess_signal(
            {
                "text": source.get("source_text") or _topic_value(topic, "question", ""),
                "source_url": url,
                "observed_at": current,
                "source_scoped": True,
                "permalink_verified": True,
                "timestamp_proof": "post_published",
                "published_at_raw": published_at.isoformat(),
                "closed": active in {"closed", "deleted", "resolved", "expired", "inactive"},
            },
            now=current,
        )
        allowed_queues = {"HOT", "WARM", "QUALIFIED_7D", "CONTENT_SIGNAL"}
        if purpose == "reply":
            allowed_queues.discard("CONTENT_SIGNAL")
        if decision["queue"] not in allowed_queues:
            reasons.extend(decision["reasons"] or ["not_current_buyer_demand"])
    if source.get("source_url") and _clean_url(source.get("source_url")) != _clean_url(
        _topic_value(topic, "source_url")
    ):
        reasons.append("source_identity_changed")
    return {
        "eligible": not reasons,
        "reasons": sorted(set(reasons)),
        "source_url": url,
        "policy": REVENUE_POLICY_VERSION,
        "purpose": purpose,
        "demand_decision": decision,
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


_PROBLEM_NUMBER = (
    r"(?:\d+(?:[ .]\d{3})*(?:[.,]\d+)?|egy|két|kettő|három|négy|öt|hat|hét|nyolc|kilenc|tíz)"
    r"(?:\s*(?:[-–—]|és|vagy)\s*\d+(?:[.,]\d+)?)?"
)
_PROBLEM_SUFFIX = r"(?:-?(?P<suffix>es|os|as|ös|és|ot|et|at|ból|ből|ban|ben|ra|re|on|en|ig|ért))?"


def _editorial_buyer_problem(original: str) -> tuple[str, str]:
    """Generalize customer quantities without authorizing any numeric claim.

    Exact quantities stay in the private source evidence. The public problem
    describes the same work; it is not a price, performance or timing promise.
    Unsupported numeric syntax produces a concrete topic brief, never a retry
    requirement or an exception to the publication claim checks.
    """
    value = str(original or "").strip()
    value = re.sub(r"https?://\S+", "a megadott forrás", value)
    value = re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+", "a megadott elérhetőség", value)
    value = re.sub(r"(?<!\w)(?:\+36|06)[ -]?(?:\d[ -]?){8,9}\b", "a megadott elérhetőség", value)
    value = re.sub(r"(?<!\w)(?:/?u/|@)[\w.-]+", "az érintett fórumozó", value)
    # Dates are context, not a new publication/freshness timestamp.
    value = re.sub(r"\b\d{4}[-.]\s*\d{1,2}[-.]\s*\d{1,2}[.]?", "a megadott időpont", value)

    def quantity(pattern: str, forms: Mapping[str, str], default: str) -> None:
        nonlocal value
        value = re.sub(
            rf"\b{_PROBLEM_NUMBER}\s*(?:{pattern}){_PROBLEM_SUFFIX}\b(?!-\w)",
            lambda match: forms.get((match.group("suffix") or "").casefold(), default),
            value, flags=re.IGNORECASE,
        )

    quantity(r"m2|m²|nm|négyzetméter", {
        "ra": "megadott alapterületre", "re": "megadott alapterületre",
        "en": "megadott alapterületen", "on": "megadott alapterületen",
        "ot": "megadott alapterületet", "et": "megadott alapterületet",
    }, "megadott méretű")
    thickness = any(word in _plain(original) for word in ("szigetel", "vastag", "homlokzat"))
    quantity(r"mm|cm|méter|meter|m", {
        "ra": "megadott méretre", "re": "megadott méretre",
        "en": "megadott méreten", "on": "megadott méreten",
    }, "eltérő vastagságú" if thickness and re.search(r"\d\s*(?:[-–—]|és|vagy)\s*\d", original)
        else "megadott vastagságú" if thickness else "megadott méretű")
    value = re.sub(r"(eltérő vastagságú[^.!?]{0,60}szigetelés)\s+között", r"\1ek között", value)
    # Keep inflection where it carries the question's meaning (budget/price).
    quantity(r"(?:ezer|millió|millio|milliárd|milliard)?\s*(?:Ft|forint|euró|euro)(?:\s*/\s*(?:m2|m²|nm|óra|nap))?", {
        "es": "megadott összegű", "os": "megadott összegű", "as": "megadott összegű",
        "ot": "megadott összeget", "et": "megadott összeget", "at": "megadott összeget",
        "ból": "megadott keretből", "ből": "megadott keretből",
        "ért": "megadott összegért", "ra": "megadott összegre", "re": "megadott összegre",
        "ig": "megadott keretig", "ban": "megadott összegben", "ben": "megadott összegben",
    }, "megadott összeg")
    quantity(r"ezer|millió|millio|milliárd|milliard", {
        "ból": "megadott keretből", "ből": "megadott keretből",
        "ot": "megadott összeget", "et": "megadott összeget",
    }, "megadott összeg")
    value = re.sub(rf"\b{_PROBLEM_NUMBER}\s*(?:napja|hete|hónapja|honapja|éve|órája|oraja)\b", "egy ideje", value, flags=re.I)
    quantity(r"nap|hét|het|hónap|honap|év|óra|ora", {
        "es": "megadott időtartamú", "os": "megadott időtartamú",
        "ig": "megadott ideig", "on": "megadott időn", "en": "megadott időn",
        "ra": "megadott időre", "re": "megadott időre",
        "ban": "megadott időszakban", "ben": "megadott időszakban",
    }, "megadott idő")
    value = re.sub(
        rf"\b{_PROBLEM_NUMBER}\s*(?:%|százalék)(?:-?(?P<percent_suffix>os|kal|ot|ra))?(?![-\w])",
        lambda match: {"kal": "megadott aránnyal", "ot": "megadott arányt", "ra": "megadott arányra"}.get(
            match.group("percent_suffix"), "megadott arányú"
        ), value, flags=re.I,
    )
    if re.search(r"\d", value):
        # Model/type codes, complex dimensions and uncommon number morphology
        # remain verbatim in original_problem; do not publish mangled fragments.
        plain = _plain(original)
        subjects = [description for markers, description in (
            (("laminalt", "padlo", "burkol"), "padlóburkolás"),
            (("fest", "glett"), "festés és falelőkészítés"),
            (("hoszigetel", "szigetel", "parazar"), "hőszigetelés"),
            (("tetoter",), "tetőtér-beépítés"),
            (("teto",), "tető felújítása"),
            (("garazs",), "garázs építése"),
            (("falaz", "tegla", "ytong"), "falazat megválasztása"),
            (("konyha",), "konyha felújítása"),
            (("kivitelezo", "epitkezes", "hazepit"), "kivitelezés megtervezése"),
            (("villany", "konnektor"), "villamos hálózat kialakítása"),
            (("futes", "kazan"), "fűtés kialakítása"),
            (("lakasa", "lakas", "ingatlan"), "ingatlanhoz kapcsolódó döntés"),
        ) if any(marker in plain for marker in markers)]
        subject = " és ".join(subjects[:2]) or "a forrásban leírt konkrét munka megtervezése"
        goal = "a költséget és az ajánlatok tartalmát" if any(
            marker in plain for marker in ("ar", "koltseg", "munkadij", "ajanlat", "keret", "ft")
        ) else "a műszaki feltételeket és a következő lépést"
        return (
            f"A vevő a megadott projektadatok mellett a következő feladatról szeretne dönteni: {subject}. "
            f"Ehhez {goal} kell tisztáznia."
        ), "topic_brief_with_original_evidence"
    return value, "quantity_and_contact_generalization" if value != original else "original_wording"


def _problem_source_identity(source_url: str) -> tuple[str, str | None]:
    parsed = urlsplit(source_url)
    host = (parsed.hostname or "").removeprefix("www.")
    native = None
    if host == "reddit.com":
        match = re.search(r"/comments/([a-z0-9]+)(?:/[^/]+/([a-z0-9]+))?", parsed.path, flags=re.I)
        if match:
            native = "post:" + match[1].lower() + (":comment:" + match[2].lower() if match[2] else "")
    elif host == "forum.index.hu":
        native = dict(parse_qsl(parsed.query)).get("a")
    elif host == "prohardver.hu":
        match = re.search(r"(.+)/hsz_(\d+)-\2[.]html$", parsed.path)
        if match:
            native = match[1] + ":post:" + match[2]
    identity_url = urlunsplit(("https", host, parsed.path, parsed.query, parsed.fragment))
    return identity(identity_url, native or ""), native


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
    source = source_snapshot or {}
    original_problem = str(source.get("source_text") or _topic_value(topic, "question") or "").strip()
    buyer_problem, derivation = _editorial_buyer_problem(original_problem)
    source_url = revalidation["source_url"]
    source_identity, native_id = _problem_source_identity(source_url)
    published_at = source.get("published_at", _topic_value(topic, "published_at"))
    if isinstance(published_at, datetime):
        published_at = published_at.replace(tzinfo=UTC) if published_at.tzinfo is None else published_at
        published_at = published_at.astimezone(UTC).isoformat()
    intent = {
        "policy": REVENUE_POLICY_VERSION,
        "brand_id": str(_topic_value(topic, "brand_id") or ""),
        "radar_topic_id": str(_topic_value(topic, "topic_id") or ""),
        "buyer_problem": buyer_problem,
        "source_problem_evidence": {
            "original_problem": original_problem,
            "source_url": source_url,
            "source_identity": source_identity,
            "native_id": native_id,
            "radar_identity_hash": _topic_value(topic, "identity_hash"),
            "published_at": published_at,
            "published_at_raw": source.get("published_at_raw", _topic_value(topic, "published_at_raw")),
            "observed_at": source.get("observed_at", revalidation["revalidated_at"]),
            "revalidated_at": revalidation["revalidated_at"],
            "verification_mode": "source_refresh" if source_snapshot is not None else "stored_topic_revalidation",
            "original_text_sha256": hashlib.sha256(original_problem.encode("utf-8")).hexdigest(),
            "public_problem_derivation": derivation,
            "editorial_instruction": (
                "A pontos méretek, összegek és időadatok a vevő saját helyzetének adatai. "
                "A nyilvános szövegben a buyer_problem számadatok nélkül megfogalmazott "
                "változatát használd; az eredeti számadatokat ne másold át. "
                "A cikk a munka tartalmáról és a döntési szempontokról szóljon; ezekből "
                "ne képezzen márkaárat, vállalási határidőt vagy teljesítményígéretet."
            ),
        },
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


def build_brand_source_intent(
    brand_id: str, approved_brand_facts: list[Mapping[str, Any]]
) -> dict[str, Any]:
    """Use an approved, documented buyer problem when no current radar input exists.

    This is an editorial input, never a fabricated forum question or sales lead.
    Both the problem and the offered next step must exist in the same brand's
    approved source payload; a source URL alone is not enough.
    """
    for fact in approved_brand_facts:
        payload = fact.get("payload")
        if not isinstance(payload, Mapping):
            continue
        problems = payload.get("buyer_problems") or [payload.get("buyer_problem")]
        steps = payload.get("next_steps") or [payload.get("next_step")]
        if not isinstance(problems, list) or not isinstance(steps, list):
            continue
        problem = next(
            (x.strip() for x in problems if isinstance(x, str) and len(x.strip()) >= 12), ""
        )
        step = next((x.strip() for x in steps if isinstance(x, str) and len(x.strip()) >= 8), "")
        source_url = _clean_url(fact.get("source_url"))
        if not problem or not step or not source_url or not payload.get("statement"):
            continue
        intent = {
            "policy": REVENUE_POLICY_VERSION,
            "brand_id": brand_id,
            "input_type": "approved_brand_customer_problem",
            "radar_topic_id": None,
            "buyer_problem": problem,
            "sales_goal": str(
                payload.get("sales_goal") or f"{brand_id}: minősített kapcsolatfelvétel"
            ),
            "approved_brand_facts": [dict(item) for item in approved_brand_facts],
            "next_step": step,
            "source_refs": [source_url],
            "publication_allowed": False,
            "send_allowed": False,
        }
        if evaluate_revenue_intent(intent, brand_id=brand_id)["eligible"]:
            return intent
    raise SourceReplenishmentRequired(["buyer_problem_source_missing"])


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
