from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .models import GrowthControlState, GrowthSignal, OutreachMessage
from .official_source import (
    OFFICIAL_SOURCE_MAX_REDIRECTS,
    OFFICIAL_SOURCE_MAX_RESPONSE_BYTES,
    OFFICIAL_SOURCE_TIMEOUT_SECONDS,
    _fetch_html,
    _normalized_marker,
    _visible_email_addresses,
    _visible_text,
)
from .registry import (
    GrowthRegistry,
    GrowthRegistryError,
    _official_source_binding_sha256,
    _registrable_domain,
    settings,
)
from .schemas import GrowthSignalIn

PARTNERPOINT_SYNC_STATE_KEY = "partnerpoint:control-sheet-sync"
PARTNERPOINT_REPLY_SYNC_STATE_KEY = "partnerpoint:reply-stop-sync"
PARTNERPOINT_WRITEBACK_PREFIX = "partnerpoint:writeback:"
PARTNERPOINT_CHECKPOINT_PREFIX = "partnerpoint:daily-checkpoint:"
PARTNERPOINT_READY_STATUS = "MINŐSÍTVE – KÖZPONTI ÁTADÁSRA KÉSZ"
PARTNERPOINT_ALLOWED_TEMPLATES = {
    "ARCHITECT_OFFICE_FIRST_CONTACT_HU": "architect_office",
    "REFERRAL_PARTNER_FIRST_CONTACT_HU": "referral_partner",
}
PARTNERPOINT_RANGES = (
    "Partner_Universe!A1:W2000",
    "Priority_Targets!A1:W2000",
    "Outreach_Pipeline!A1:O3000",
    "Existing_Verified!A1:W2000",
    "Outreach_Suppression!A1:P2000",
    "Run_Checkpoints!A1:V2000",
)
_LEGAL_ENTITY_RE = re.compile(r"(?:\bKft\.?\b|\bZrt\.?\b|\bNyrt\.?\b|\bBt\.?\b)", re.IGNORECASE)
_EMAIL_RE = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_FREE_MAIL_DOMAINS = {
    "gmail.com",
    "icloud.com",
    "freemail.hu",
    "citromail.hu",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
    "t-online.hu",
    "chello.hu",
    "datanet.hu",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _google_json(
    request: urllib.request.Request,
    *,
    timeout: float = 45.0,
) -> dict[str, Any]:
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read(2000).decode("utf-8", "replace")
            try:
                reasons = {
                    str(item.get("reason") or "")
                    for item in json.loads(detail).get("error", {}).get("errors", [])
                }
            except (ValueError, json.JSONDecodeError, AttributeError):
                reasons = set()
            retryable = exc.code == 429 or bool(
                reasons.intersection({"rateLimitExceeded", "userRateLimitExceeded"})
            )
            if retryable and attempt < 4:
                time.sleep(2**attempt)
                continue
            raise GrowthRegistryError(
                f"partnerpoint_google_http_{exc.code}:{detail[:300]}"
            ) from exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise GrowthRegistryError("partnerpoint_google_request_failed") from exc
    if not isinstance(payload, dict):
        raise GrowthRegistryError("partnerpoint_google_response_invalid")
    return payload


def _access_token(secret: dict[str, Any]) -> str:
    fields = ("client_id", "client_secret", "refresh_token")
    if any(not str(secret.get(field) or "").strip() for field in fields):
        raise GrowthRegistryError("partnerpoint_google_oauth_incomplete")
    body = urllib.parse.urlencode(
        {
            "client_id": secret["client_id"],
            "client_secret": secret["client_secret"],
            "refresh_token": secret["refresh_token"],
            "grant_type": "refresh_token",
        }
    ).encode()
    payload = _google_json(
        urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    )
    token = str(payload.get("access_token") or "")
    if not token:
        raise GrowthRegistryError("partnerpoint_google_oauth_refresh_failed")
    return token


def _sheet_token() -> str:
    registry = GrowthRegistry.load(include_runtime_sources=False)
    return _access_token(registry.brand_binding("imperial").secret)


def fetch_snapshot() -> dict[str, list[list[str]]]:
    config = settings()
    if not config.partnerpoint_enabled:
        return {}
    if (
        config.partnerpoint_sheet_id != GrowthRegistry.PARTNERPOINT_SHEET_ID
        or config.partnerpoint_spec_file_id != GrowthRegistry.PARTNERPOINT_SPEC_FILE_ID
        or config.partnerpoint_spec_version != GrowthRegistry.PARTNERPOINT_SPEC_VERSION
    ):
        raise GrowthRegistryError("partnerpoint_canonical_reference_mismatch")
    query = urllib.parse.urlencode([("ranges", value) for value in PARTNERPOINT_RANGES])
    payload = _google_json(
        urllib.request.Request(
            "https://sheets.googleapis.com/v4/spreadsheets/"
            f"{config.partnerpoint_sheet_id}/values:batchGet?{query}",
            headers={"Authorization": f"Bearer {_sheet_token()}"},
        )
    )
    result: dict[str, list[list[str]]] = {}
    for item in payload.get("valueRanges") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("range") or "").split("!", 1)[0].strip("'")
        values = item.get("values") or []
        if name and isinstance(values, list):
            result[name] = [list(map(str, row)) for row in values if isinstance(row, list)]
    missing = {value.split("!", 1)[0] for value in PARTNERPOINT_RANGES} - set(result)
    if missing:
        raise GrowthRegistryError("partnerpoint_required_tabs_missing:" + ",".join(sorted(missing)))
    return result


def _padded(row: list[str], size: int) -> list[str]:
    return row[:size] + [""] * max(0, size - len(row))


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.port not in {None, 443}
    ):
        raise GrowthRegistryError("partnerpoint_official_url_invalid")
    return urlunsplit(("https", parsed.netloc.casefold(), parsed.path or "/", parsed.query, ""))


def _brand_marker(company: str) -> str:
    first = company.split("/", 1)[0].strip(' „”"')
    first = re.sub(r"\s+(?:Kft\.?|Zrt\.?|Nyrt\.?|Bt\.?)$", "", first, flags=re.I)
    first = re.sub(
        r"\s+(?:Építész(?:eti)?(?:\s+Stúdió|\s+Iroda|műterem)?|Tervező.*)$",
        "",
        first,
        flags=re.I,
    )
    return " ".join(first.split())


def _business_context(category: str) -> str:
    folded = category.casefold()
    if "tüzép" in folded or "építőanyag" in folded:
        return "építőanyag-kereskedésük"
    if "földmér" in folded or "geod" in folded:
        return "földmérési és geodéziai szolgáltatásainak"
    if "műszaki ellenőr" in folded:
        return "műszaki ellenőrzési szolgáltatásainak"
    if "geotechn" in folded or "geológ" in folded:
        return "geotechnikai és geológiai szolgáltatásainak"
    if "villamos" in folded:
        return "villamos tervezési szolgáltatásainak"
    if "mérnök" in folded:
        return "mérnöki szolgáltatásainak"
    return "szakmai szolgáltatásainak"


def _candidate_rows(snapshot: dict[str, list[list[str]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    values = snapshot["Partner_Universe"]
    for row_number, raw in enumerate(values[1:], start=2):
        row = _padded(raw, 23)
        template_id = row[18].strip()
        lane = PARTNERPOINT_ALLOWED_TEMPLATES.get(template_id)
        if not lane:
            continue
        company, category, status = row[1].strip(), row[2].strip(), row[3].strip()
        email = row[10].strip().casefold()
        hard_gate = row[21].strip()
        if (
            status != PARTNERPOINT_READY_STATUS
            or not hard_gate.startswith("PASS")
            or "Primary=Imperial Holding" not in row[15]
            or not _LEGAL_ENTITY_RE.search(company)
            or not _EMAIL_RE.fullmatch(email)
            or ";" in email
        ):
            continue
        email_domain = email.rsplit("@", 1)[1]
        if email_domain in _FREE_MAIL_DOMAINS:
            continue
        source_url = _canonical_url(row[14] or row[7])
        if _registrable_domain(urlsplit(source_url).hostname or "") != _registrable_domain(
            email_domain
        ):
            continue
        marker = _brand_marker(company)
        if not marker:
            continue
        candidate = {
            "row_number": row_number,
            "candidate_id": row[0].strip(),
            "company": company,
            "organization_marker": marker,
            "recipient_name": marker,
            "category": category,
            "recipient_type": lane,
            "email": email,
            "location": row[5].strip() or row[4].strip() or "Magyarország",
            "source_url": source_url,
            "template_id": template_id,
            "control_row_sha256": _sha(row),
        }
        if lane == "referral_partner":
            candidate["business_context"] = _business_context(category)
        rows.append(candidate)
    return rows


def _gmail_message_ids(token: str, query: str, *, maximum: int = 5) -> list[str]:
    params = urllib.parse.urlencode({"q": query, "maxResults": maximum})
    payload = _google_json(
        urllib.request.Request(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?" + params,
            headers={"Authorization": f"Bearer {token}"},
        )
    )
    return [str(item["id"]) for item in payload.get("messages") or [] if item.get("id")]


def _existing_relationship_gate(
    db: Session,
    candidate: dict[str, Any],
    *,
    gmail_token: str,
) -> str | None:
    """Fail closed on CRM history, previous mail, or actual two-way correspondence."""
    from .service import upsert_account_stop

    email = candidate["email"]
    domain = email.rsplit("@", 1)[1]
    crm = (
        db.execute(
            text(
                "SELECT id, created_at FROM sales_agent_leads "
                "WHERE lower(email) = :email OR lower(email) LIKE :domain "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"email": email, "domain": f"%@{domain}"},
        )
        .mappings()
        .first()
    )
    if crm:
        upsert_account_stop(
            db,
            recipient_email=email,
            stop_kind="existing_relationship",
            source="sales_agent_crm",
            source_event_id=str(crm["id"]),
            reason="Existing corporate account is present in the production CRM",
            occurred_at=crm["created_at"] or _utcnow(),
            organization_key=candidate["company"],
            details={"candidate_id": candidate["candidate_id"]},
        )
        db.commit()
        return "partnerpoint_existing_relationship_crm"
    sent = _gmail_message_ids(gmail_token, f"in:sent newer_than:365d to:({domain})")
    inbound = _gmail_message_ids(gmail_token, f"newer_than:365d from:({domain})")
    if not sent:
        return None
    stop_kind = "existing_relationship" if inbound else "other_brand_active"
    upsert_account_stop(
        db,
        recipient_email=email,
        stop_kind=stop_kind,
        source="gmail_candidate_screening",
        source_event_id=sent[0],
        reason=(
            "Two-way corporate Gmail correspondence already exists"
            if inbound
            else "A previous Imperial-group Gmail send already exists"
        ),
        occurred_at=_utcnow(),
        organization_key=candidate["company"],
        details={
            "candidate_id": candidate["candidate_id"],
            "sent_message_ids": sent,
            "inbound_message_ids": inbound,
        },
    )
    db.commit()
    return (
        "partnerpoint_existing_relationship_two_way"
        if inbound
        else "partnerpoint_previous_or_other_brand_send"
    )


def sync_control_stops(db: Session, snapshot: dict[str, list[list[str]]]) -> dict[str, Any]:
    from .service import upsert_account_stop

    stops: list[dict[str, Any]] = []
    for raw in snapshot["Existing_Verified"][1:]:
        row = _padded(raw, 23)
        for email in re.findall(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+", row[10].casefold()):
            stops.append(
                {
                    "email": email,
                    "kind": "existing_relationship",
                    "event_id": row[0],
                    "reason": row[15] or row[3] or "PartnerPont Existing_Verified",
                    "organization": row[1],
                    "force_email": False,
                }
            )
    for raw in snapshot["Partner_Universe"][1:]:
        row = _padded(raw, 23)
        status = row[3].casefold()
        hard_gate = row[21].casefold()
        kind = None
        if "pozitív válasz" in status or "replied" in status:
            kind = "response"
        elif "hard bounce" in status or "bounce" in hard_gate:
            kind = "bounce"
        elif "owner_manual_only" in hard_gate or "meglévő aktív üzleti kapcsolat" in status:
            kind = "existing_relationship"
        elif "dnc" in status or "do_not_contact" in hard_gate:
            kind = "dnc"
        if kind:
            for email in re.findall(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+", row[10].casefold()):
                stops.append(
                    {
                        "email": email,
                        "kind": kind,
                        "event_id": row[0],
                        "reason": row[15] or row[3] or hard_gate,
                        "organization": row[1],
                        "force_email": kind == "bounce",
                    }
                )
    for raw in snapshot["Outreach_Suppression"][1:]:
        row = _padded(raw, 16)
        if "aktív" not in row[14].casefold():
            continue
        event = row[5].casefold()
        kind = (
            "bounce"
            if "bounce" in event
            else "complaint"
            if "complaint" in event or "spam" in event
            else "rejection"
            if "no_interest" in event or "sequence_stop" in event
            else "dnc"
            if "opt_out" in event or "do_not_contact" in event
            else "hard_suppression"
        )
        emails = re.findall(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+", row[3].casefold())
        if not emails and row[2].strip():
            emails = [f"suppression@{row[2].strip().casefold()}"]
        for email in emails:
            stops.append(
                {
                    "email": email,
                    "kind": kind,
                    "event_id": row[0],
                    "reason": row[11] or row[5],
                    "organization": row[1],
                    "force_email": kind == "bounce" and "e-mail" in row[4].casefold(),
                }
            )
    created = 0
    blocked = 0
    for item in stops:
        match_key = item["email"].rsplit("@", 1)[-1]
        matched = db.scalar(
            select(OutreachMessage)
            .where(
                OutreachMessage.status.in_(("sent", "delivered", "responded")),
                OutreachMessage.sent_at.is_not(None),
                (
                    func.lower(OutreachMessage.recipient_email) == item["email"]
                    if item["force_email"]
                    else func.lower(OutreachMessage.recipient_email).like(f"%@{match_key}")
                ),
            )
            .order_by(OutreachMessage.sent_at.desc())
            .limit(1)
        )
        _row, was_created, blocked_now = upsert_account_stop(
            db,
            recipient_email=item["email"],
            stop_kind=item["kind"],
            source="partnerpoint_control",
            source_event_id=item["event_id"],
            reason=item["reason"],
            occurred_at=_utcnow(),
            organization_key=item["organization"],
            force_email_scope=item["force_email"],
            matched_outreach_id=(
                matched.outreach_id
                if matched and item["kind"] in {"response", "rejection"}
                else None
            ),
            details={"sheet_id": GrowthRegistry.PARTNERPOINT_SHEET_ID},
        )
        created += was_created
        blocked += blocked_now
    db.commit()
    return {"status": "healthy", "observed": len(stops), "created": created, "blocked": blocked}


def _source_entry(
    candidate: dict[str, Any], architect_authority: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    source_url = candidate["source_url"]
    root_domain = _registrable_domain(urlsplit(source_url).hostname or "")
    source_id = "DYNAMIC_HU_" + re.sub(r"[^A-Z0-9]+", "_", root_domain.upper()).strip("_")
    page, body = _fetch_html(
        source_url,
        allowed_urls={source_url},
        root_domain=root_domain,
        max_bytes=OFFICIAL_SOURCE_MAX_RESPONSE_BYTES,
        max_redirects=OFFICIAL_SOURCE_MAX_REDIRECTS,
        expected_final_url=source_url,
        deadline_monotonic=(__import__("time").monotonic() + OFFICIAL_SOURCE_TIMEOUT_SECONDS),
    )
    visible = _visible_text(body)
    visible_emails = _visible_email_addresses(body)
    marker = _normalized_marker(candidate["organization_marker"])
    if candidate["email"] not in visible_emails:
        raise GrowthRegistryError("partnerpoint_official_email_not_visible")
    if not marker or marker not in visible:
        raise GrowthRegistryError("partnerpoint_official_organization_not_visible")
    checked_at = _utcnow()
    binding: dict[str, Any] = {
        "recipient_type": candidate["recipient_type"],
        "recipient_email": candidate["email"],
        "recipient_email_type": "role",
        "contact_basis": "public_business_contact",
        "primary_language": "hu",
        "organization_names": [
            candidate["company"],
            candidate["organization_marker"],
        ],
        "recipient_names": [candidate["recipient_name"]],
    }
    if candidate["recipient_type"] == "referral_partner":
        binding.update(
            {
                "business_context": candidate["business_context"],
                "business_context_verified": True,
                "business_context_evidence_url": source_url,
            }
        )
        authority = {
            "registry_id": "PARTNERPOINT_CONTROL_V1",
            "sheet_id": GrowthRegistry.PARTNERPOINT_SHEET_ID,
            "spec_file_id": GrowthRegistry.PARTNERPOINT_SPEC_FILE_ID,
            "spec_version": GrowthRegistry.PARTNERPOINT_SPEC_VERSION,
            "candidate_id": candidate["candidate_id"],
            "control_row_sha256": candidate["control_row_sha256"],
            "owner_instruction_ref": "production-recovery-2026-09-08",
        }
        bucket = "referral_partner"
    else:
        authority = architect_authority
        bucket = "architect_office"
    source: dict[str, Any] = {
        "enabled": True,
        "motor": "construction",
        "bucket": bucket,
        "kind": GrowthRegistry.OFFICIAL_COMPANY_SOURCE_KIND,
        "fetch_mode": GrowthRegistry.OFFICIAL_COMPANY_FETCH_MODE,
        "url": source_url,
        "allowed_evidence_urls": [source_url],
        "context_evidence_url": source_url,
        "public_contact_url": source_url,
        "recipient_binding": binding,
        "policy_evidence": {
            "evidence_url": source_url,
            "final_url": source_url,
            "http_status": page.http_status,
            "content_type": page.content_type,
            "content_sha256": page.content_sha256,
            "checked_at": checked_at.isoformat(),
            "valid_until": (checked_at + timedelta(days=1)).isoformat(),
        },
        "max_evidence_age_seconds": 86_400,
        "authority": authority,
    }
    source["binding_sha256"] = _official_source_binding_sha256(source_id, source)
    return source_id, source


def _write_runtime_sources(sources: dict[str, dict[str, Any]]) -> None:
    config = settings()
    registry_path = Path(config.registry_file)
    target = Path(config.partnerpoint_runtime_sources_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": GrowthRegistry.PARTNERPOINT_RUNTIME_SCHEMA,
        "generated_at": _utcnow().isoformat(),
        "base_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        "sheet_id": GrowthRegistry.PARTNERPOINT_SHEET_ID,
        "spec_file_id": GrowthRegistry.PARTNERPOINT_SPEC_FILE_ID,
        "spec_version": GrowthRegistry.PARTNERPOINT_SPEC_VERSION,
        "sources": sources,
    }
    descriptor, temporary = tempfile.mkstemp(
        prefix="partnerpoint-", suffix=".json", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _state(db: Session, key: str, *, enabled: bool, reason: str) -> None:
    row = db.get(GrowthControlState, key)
    if row is None:
        row = GrowthControlState(key=key)
        db.add(row)
    row.enabled = enabled
    row.reason = reason[:4000]
    row.changed_by = "growth-partnerpoint"
    row.changed_at = _utcnow()
    db.commit()


def sync_candidates(db: Session) -> dict[str, Any]:
    if not settings().partnerpoint_enabled:
        return {"status": "disabled", "discovered": 0, "qualified": 0, "queued": 0}
    previous = db.get(GrowthControlState, PARTNERPOINT_SYNC_STATE_KEY)
    if (
        previous
        and previous.enabled
        and previous.changed_at
        and _utcnow() - previous.changed_at.astimezone(UTC) < timedelta(minutes=15)
        and Path(settings().partnerpoint_runtime_sources_file).is_file()
    ):
        try:
            cached = json.loads(previous.reason or "{}")
        except json.JSONDecodeError:
            cached = {}
        return {"status": "cached", **cached}
    try:
        snapshot = fetch_snapshot()
        stop_sync = sync_control_stops(db, snapshot)
        candidates = _candidate_rows(snapshot)
        base = GrowthRegistry.load(include_runtime_sources=False)
        architect_source = next(
            (
                source
                for source in base.sources.values()
                if source.get("enabled")
                and source.get("kind") == GrowthRegistry.OFFICIAL_COMPANY_SOURCE_KIND
                and source.get("recipient_binding", {}).get("recipient_type") == "architect_office"
            ),
            None,
        )
        if not isinstance(architect_source, dict):
            raise GrowthRegistryError("partnerpoint_architect_authority_missing")
        architect_authority = dict(architect_source["authority"])
        gmail_token = _sheet_token()
        sources: dict[str, dict[str, Any]] = {}
        qualified: list[dict[str, Any]] = []
        blocked: list[dict[str, str]] = []
        lane_discovered = {
            lane: sum(candidate["recipient_type"] == lane for candidate in candidates)
            for lane in ("architect_office", "referral_partner")
        }
        lane_counts = {"architect_office": 0, "referral_partner": 0}
        limits = {
            "architect_office": settings().partnerpoint_architect_daily_max,
            "referral_partner": settings().partnerpoint_referral_daily_max,
        }
        for candidate in candidates:
            lane = candidate["recipient_type"]
            if lane_counts[lane] >= limits[lane]:
                continue
            try:
                relationship_reason = _existing_relationship_gate(
                    db,
                    candidate,
                    gmail_token=gmail_token,
                )
                if relationship_reason:
                    raise GrowthRegistryError(relationship_reason)
                source_id, source = _source_entry(candidate, architect_authority)
                if source_id in sources:
                    raise GrowthRegistryError("partnerpoint_duplicate_root_domain")
                sources[source_id] = source
                qualified.append({**candidate, "source_id": source_id, "source": source})
                lane_counts[lane] += 1
            except GrowthRegistryError as exc:
                blocked.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "recipient_type": lane,
                        "reason": str(exc),
                    }
                )
        _write_runtime_sources(sources)
        # Validate the complete merged artifact before any database state is created.
        GrowthRegistry.load()
        from .service import ingest_signal

        # During a recovery run, put one independently-qualified candidate from
        # each partner lane at the front. The remaining daily architect volume
        # stays queued behind them and all normal pacing remains intact.
        architects = [
            candidate
            for candidate in qualified
            if candidate["recipient_type"] == "architect_office"
        ]
        referrals = [
            candidate
            for candidate in qualified
            if candidate["recipient_type"] == "referral_partner"
        ]
        dispatch_order = [*architects[:1], *referrals[:1], *architects[1:], *referrals[1:]]

        queued = 0
        receipts: list[dict[str, Any]] = []
        for candidate in dispatch_order:
            source = candidate["source"]
            binding = source["recipient_binding"]
            data = GrowthSignalIn(
                source_id=candidate["source_id"],
                external_key=candidate["candidate_id"],
                motor_key="construction",
                source_bucket=source["bucket"],
                signal_type=candidate["recipient_type"],
                detected_at=_utcnow(),
                company_name=candidate["company"],
                recipient_organization_name=candidate["organization_marker"],
                subject_type="organization",
                recipient_role="unknown",
                recipient_type=candidate["recipient_type"],
                recipient_name=candidate["recipient_name"],
                sender_company_name="Imperial Holding",
                business_context=binding.get("business_context"),
                business_context_verified=bool(binding.get("business_context_verified")),
                business_context_evidence_url=binding.get("business_context_evidence_url"),
                recipient_classification_verified=True,
                exclusion_screening_verified=True,
                recipient_email=candidate["email"],
                recipient_email_type="role",
                contact_basis="public_business_contact",
                public_contact_url=candidate["source_url"],
                location=candidate["location"],
                summary=(
                    f"PartnerPont {GrowthRegistry.PARTNERPOINT_SPEC_VERSION} exact control row; "
                    f"template={candidate['template_id']}; category={candidate['category']}"
                ),
                evidence_url=candidate["source_url"],
                brand_id="imperial",
                confidence=90,
                urgency=70,
                source_payload_hash=source["binding_sha256"],
            )
            receipt = ingest_signal(db, data)
            queued += bool(receipt.outreach_id and receipt.status == "queued")
            receipts.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "signal_id": receipt.signal_id,
                    "outreach_id": receipt.outreach_id,
                    "status": receipt.status,
                    "idempotent": receipt.idempotent,
                    "reasons": receipt.reasons,
                }
            )
        architect_shortfall = max(0, 5 - lane_counts["architect_office"])
        detail = {
            "status": "healthy" if not blocked and not architect_shortfall else "degraded",
            "discovered": len(candidates),
            "qualified": len(qualified),
            "queued": queued,
            "lane_discovered": lane_discovered,
            "lane_qualified": lane_counts,
            "architect_daily_minimum": 5,
            "architect_shortfall": architect_shortfall,
            "blocked": blocked,
            "receipts": receipts,
            "stop_sync": stop_sync,
        }
        _state(db, PARTNERPOINT_SYNC_STATE_KEY, enabled=True, reason=_canonical_json(detail))
        return detail
    except Exception as exc:
        db.rollback()
        detail = {
            "status": "failed",
            "discovered": 0,
            "qualified": 0,
            "queued": 0,
            "reason": f"{type(exc).__name__}:{str(exc)[:300]}",
        }
        _state(db, PARTNERPOINT_SYNC_STATE_KEY, enabled=False, reason=_canonical_json(detail))
        return detail


def _values_batch_update(token: str, data: list[dict[str, Any]]) -> None:
    config = settings()
    body = json.dumps({"valueInputOption": "RAW", "data": data}, ensure_ascii=False).encode("utf-8")
    _google_json(
        urllib.request.Request(
            "https://sheets.googleapis.com/v4/spreadsheets/"
            f"{config.partnerpoint_sheet_id}/values:batchUpdate",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
    )


def _copy_checkpoint_row_format(token: str, *, source_row: int, target_row: int) -> None:
    config = settings()
    metadata = _google_json(
        urllib.request.Request(
            "https://sheets.googleapis.com/v4/spreadsheets/"
            f"{config.partnerpoint_sheet_id}?fields=sheets.properties",
            headers={"Authorization": f"Bearer {token}"},
        )
    )
    sheet_id = next(
        (
            sheet.get("properties", {}).get("sheetId")
            for sheet in metadata.get("sheets", [])
            if sheet.get("properties", {}).get("title") == "Run_Checkpoints"
        ),
        None,
    )
    if sheet_id is None:
        raise GrowthRegistryError("partnerpoint_checkpoint_sheet_missing")
    body = json.dumps(
        {
            "requests": [
                {
                    "copyPaste": {
                        "source": {
                            "sheetId": sheet_id,
                            "startRowIndex": source_row - 1,
                            "endRowIndex": source_row,
                            "startColumnIndex": 0,
                            "endColumnIndex": 21,
                        },
                        "destination": {
                            "sheetId": sheet_id,
                            "startRowIndex": target_row - 1,
                            "endRowIndex": target_row,
                            "startColumnIndex": 0,
                            "endColumnIndex": 21,
                        },
                        "pasteType": "PASTE_FORMAT",
                        "pasteOrientation": "NORMAL",
                    }
                }
            ]
        }
    ).encode("utf-8")
    _google_json(
        urllib.request.Request(
            "https://sheets.googleapis.com/v4/spreadsheets/"
            f"{config.partnerpoint_sheet_id}:batchUpdate",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
    )


def write_daily_checkpoint(
    db: Session,
    *,
    outbound: dict[str, Any],
    writeback: dict[str, Any],
) -> dict[str, Any]:
    """Write one read-back-verified daily row without conflating prepared and sent."""
    if not settings().partnerpoint_enabled:
        return {"status": "disabled", "updated": 0}
    local_day = _utcnow().astimezone(ZoneInfo(settings().timezone)).date().strftime("%Y%m%d")
    run_id = f"PN-SERVER-{local_day}"
    lanes = outbound.get("lanes") or {}
    totals = {
        key: sum(int(values.get(key) or 0) for values in lanes.values())
        for key in (
            "discovered",
            "qualified",
            "ready",
            "queued",
            "sent",
            "readback_verified",
            "replies",
            "followups",
            "blocked",
        )
    }
    semantic = {
        "outbound_status": outbound.get("status"),
        "fatal": outbound.get("fatal") or [],
        "degraded": outbound.get("degraded") or [],
        "queue_backlog": int(outbound.get("queue_backlog") or 0),
        "lanes": lanes,
        "writeback": writeback,
    }
    digest = _sha(semantic)
    state_key = PARTNERPOINT_CHECKPOINT_PREFIX + local_day
    previous = db.get(GrowthControlState, state_key)
    if previous and previous.enabled:
        try:
            previous_detail = json.loads(previous.reason or "{}")
        except json.JSONDecodeError:
            previous_detail = {}
        if previous_detail.get("sha256") == digest:
            return {"status": "cached", "updated": 0, "run_id": run_id, "sha256": digest}
    try:
        snapshot = fetch_snapshot()
        rows = snapshot["Run_Checkpoints"]
        existing_row = next(
            (index for index, row in enumerate(rows[1:], start=2) if row and row[0] == run_id),
            None,
        )
        target_row = existing_row or len(rows) + 1
        token = _sheet_token()
        if existing_row is None and len(rows) >= 2:
            _copy_checkpoint_row_format(token, source_row=len(rows), target_row=target_row)
        status = str(outbound.get("status") or "failed_outbound").upper()
        reason = _canonical_json(
            {
                "architect": lanes.get("architect", {}),
                "referral": lanes.get("referral", {}),
                "real_estate": lanes.get("real_estate", {}),
                "fatal": outbound.get("fatal") or [],
                "degraded": outbound.get("degraded") or [],
            }
        )
        now = _utcnow().isoformat()
        values = [
            run_id,
            now,
            f"PartnerPont {GrowthRegistry.PARTNERPOINT_SPEC_VERSION}",
            "PRODUCTION_OUTBOUND",
            "ARCHITECT/REFERRAL/REAL_ESTATE",
            "server-canonical-worker",
            totals["discovered"],
            totals["qualified"],
            int(writeback.get("updated") or 0),
            totals["replies"],
            totals["blocked"],
            0,
            totals["sent"],
            totals["readback_verified"],
            status,
            semantic["queue_backlog"],
            reason,
            "NINCS" if status == "HEALTHY" else "SZÜKSÉGES",
            f"SPEC:{GrowthRegistry.PARTNERPOINT_SPEC_FILE_ID}",
            "POSTGRES+PARTNERPONT",
            "NEM",
        ]
        _values_batch_update(
            token,
            [{"range": f"Run_Checkpoints!A{target_row}:U{target_row}", "values": [values]}],
        )
        check = fetch_snapshot()["Run_Checkpoints"]
        saved = _padded(check[target_row - 1], 21)
        if saved[0] != run_id or saved[14] != status or str(saved[12]) != str(totals["sent"]):
            raise GrowthRegistryError("partnerpoint_checkpoint_readback_mismatch")
        _state(
            db,
            state_key,
            enabled=True,
            reason=_canonical_json({"sha256": digest, "row": target_row, "status": status}),
        )
        return {
            "status": "healthy",
            "updated": 1,
            "run_id": run_id,
            "row": target_row,
            "sha256": digest,
        }
    except Exception as exc:
        db.rollback()
        detail = {
            "status": "failed",
            "updated": 0,
            "run_id": run_id,
            "reason": f"{type(exc).__name__}:{str(exc)[:300]}",
        }
        _state(db, state_key, enabled=False, reason=_canonical_json(detail))
        return detail


def writeback_sent(db: Session) -> dict[str, Any]:
    if not settings().partnerpoint_enabled:
        return {"status": "disabled", "updated": 0, "failed": 0}
    rows = db.scalars(
        select(OutreachMessage)
        .where(
            OutreachMessage.status.in_(("sent", "delivered", "responded")),
            OutreachMessage.provider_message_id.is_not(None),
        )
        .order_by(OutreachMessage.sent_at.desc())
        .limit(50)
    ).all()
    pending: list[tuple[OutreachMessage, GrowthSignal]] = []
    for row in rows:
        state = db.get(GrowthControlState, PARTNERPOINT_WRITEBACK_PREFIX + row.outreach_id)
        if state is not None and state.enabled:
            continue
        signal = db.scalar(select(GrowthSignal).where(GrowthSignal.signal_id == row.signal_id))
        if signal is None:
            continue
        try:
            source = GrowthRegistry.load().sources.get(signal.source_id)
        except GrowthRegistryError:
            source = None
        authority = source.get("authority") if isinstance(source, dict) else None
        if (
            isinstance(authority, dict)
            and authority.get("candidate_id") == signal.external_key
            and authority.get("sheet_id") == GrowthRegistry.PARTNERPOINT_SHEET_ID
        ) or (
            isinstance(source, dict)
            and source.get("recipient_binding", {}).get("recipient_type") == "architect_office"
            and signal.external_key.startswith("PC-")
        ):
            pending.append((row, signal))
    if not pending:
        return {"status": "healthy", "updated": 0, "failed": 0}
    try:
        snapshot = fetch_snapshot()
        universe_rows = snapshot["Partner_Universe"]
        pipeline_rows = snapshot["Outreach_Pipeline"]
        universe_by_candidate = {
            row[0]: number for number, row in enumerate(universe_rows[1:], start=2) if row
        }
        pipeline_by_candidate = {
            row[1]: number for number, row in enumerate(pipeline_rows[1:], start=2) if len(row) > 1
        }
        token = _sheet_token()
        updated = 0
        failed = 0
        for outreach, signal in pending:
            try:
                candidate_id = signal.external_key
                urow = universe_by_candidate[candidate_id]
                prow = pipeline_by_candidate[candidate_id]
                receipt = json.loads(outreach.receipt_json or "{}")
                delivery = receipt.get("delivery_detail") or {}
                template = receipt.get("canonical_template") or {}
                when = outreach.sent_at or _utcnow()
                note = (
                    f"SENT_READBACK_VERIFIED; server_outreach_id={outreach.outreach_id}; "
                    f"gmail_id={outreach.provider_message_id}; "
                    f"rfc_message_id={delivery.get('rfc_message_id')}; "
                    f"mime_sha256={delivery.get('readback_mime_sha256')}; "
                    f"template={template.get('template_id')}; "
                    f"template_registry={template.get('registry_sha256')}"
                )
                _values_batch_update(
                    token,
                    [
                        {
                            "range": f"Outreach_Pipeline!F{prow}:H{prow}",
                            "values": [
                                [
                                    "SENT_READBACK_VERIFIED",
                                    when.astimezone(UTC).isoformat(),
                                    "Válasz figyelése; automatikus follow-up nincs "
                                    "jóváhagyott sablon nélkül",
                                ]
                            ],
                        },
                        {"range": f"Outreach_Pipeline!N{prow}", "values": [[note]]},
                        {
                            "range": f"Partner_Universe!D{urow}",
                            "values": [["MEGKERESVE – SENT READBACK IGAZOLT"]],
                        },
                    ],
                )
                check = fetch_snapshot()
                prow_values = _padded(check["Outreach_Pipeline"][prow - 1], 15)
                universe_values = _padded(check["Partner_Universe"][urow - 1], 23)
                if (
                    prow_values[5] != "SENT_READBACK_VERIFIED"
                    or outreach.outreach_id not in prow_values[13]
                    or universe_values[3] != "MEGKERESVE – SENT READBACK IGAZOLT"
                ):
                    raise GrowthRegistryError("partnerpoint_writeback_readback_mismatch")
                _state(
                    db,
                    PARTNERPOINT_WRITEBACK_PREFIX + outreach.outreach_id,
                    enabled=True,
                    reason=note,
                )
                updated += 1
            except Exception as exc:
                _state(
                    db,
                    PARTNERPOINT_WRITEBACK_PREFIX + outreach.outreach_id,
                    enabled=False,
                    reason=f"{type(exc).__name__}:{str(exc)[:300]}",
                )
                failed += 1
        return {
            "status": "healthy" if failed == 0 else "failed",
            "updated": updated,
            "failed": failed,
        }
    except Exception as exc:
        db.rollback()
        return {
            "status": "failed",
            "updated": 0,
            "failed": len(pending),
            "reason": f"{type(exc).__name__}:{str(exc)[:300]}",
        }
