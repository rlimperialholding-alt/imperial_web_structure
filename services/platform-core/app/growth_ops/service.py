from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from secrets import token_urlsafe
from threading import Event
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings as platform_settings
from ..global_email_guard import (
    claim_global_recipient_delivery,
    fail_global_recipient_delivery,
    finalize_global_recipient_delivery,
)
from ..land_acquisition.registry import LandRegistryError
from ..models import AuditLog, MailSendingDomain, MailSuppression
from .canonical_policy import (
    LAND_AGENT_HARD_GATE_REASONS,
    assert_outreach_copy,
    contains_no_monitoring_entity,
    land_agent_hard_gate_reason,
)
from .canonical_templates import CanonicalFirstContactRegistry
from .connectors import SourceError, fetch_source
from .email import (
    GMAIL_OAUTH_FIELDS,
    EmailDeliveryError,
    SMTPEmailAdapter,
)
from .models import (
    GrowthControlState,
    GrowthLandCanarySlot,
    GrowthLandCanaryState,
    GrowthPublicLandListingCursor,
    GrowthRun,
    GrowthSignal,
    GrowthSignalSourceEvidence,
    GrowthWorkerHeartbeat,
    OutreachMessage,
)
from .official_source import (
    OFFICIAL_SOURCE_MAX_RESPONSE_BYTES,
    OfficialSourceEvidenceError,
    fetch_official_source_evidence,
    is_public_unicast_address,
    normalize_official_source_marker,
)
from .registry import BrandBinding, GrowthRegistry, GrowthRegistryError, settings, writes_unlocked
from .schemas import GrowthSignalIn, GrowthSignalReceipt, OutreachEventIn, OutreachReleaseIn

LAND_RECIPIENT_TYPES_BY_ROLE = {
    "listing_agent": "real_estate_agent",
    "property_owner": "land_owner",
}
LAND_RENDER_RECIPIENT_NAME_BY_ROLE = {
    "listing_agent": "Ingatlanközvetítő",
    "property_owner": "Hirdető",
}
LAND_RENDER_RECIPIENT_NAME_POLICY_VERSION = "LAND-PUBLIC-ROLE-NAME-FALLBACK-V2"
PUBLIC_LAND_TRANSIENT_QUEUE_REASONS = frozenset(
    {"brand_daily_rate_limit", "growth_writes_locked"}
)

OUTREACH_CAPACITY_ADVISORY_LOCK_KEY = 3_292_944_878_079_892_252
OUTREACH_TRANSPORT_ADVISORY_LOCK_KEY = 3_292_944_878_079_892_253
OUTREACH_PACING_STATE_KEY = "transport:gmail:info@imperialholding.hu"
OUTREACH_COMPLAINT_STOP_RATE = 0.003
OUTREACH_BOUNCE_STOP_RATE = 0.05
OUTREACH_BOUNCE_STOP_MINIMUM = 3
_PROCESS_EMERGENCY_SEND_STOP = Event()


@dataclass(frozen=True)
class OfficialSourceBindingProofTarget:
    signal_id: str
    outreach_id: str
    source_id: str
    binding_sha256: str


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _official_source_receipt_hmac(payload: dict[str, Any]) -> str:
    key = platform_settings.imperial_release_hmac_key
    if len(key) < 32:
        raise OfficialSourceEvidenceError("official_source_receipt_hmac_key_missing")
    return hmac.new(
        key.encode(),
        canonical_json(payload).encode(),
        hashlib.sha256,
    ).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _control_enabled(db: Session, motor_key: str) -> bool:
    row = db.get(GrowthControlState, f"motor:{motor_key}")
    return True if row is None else bool(row.enabled)


def set_control_state(
    db: Session, motor_key: str, *, enabled: bool, reason: str, actor: str
) -> GrowthControlState:
    if motor_key not in GrowthRegistry.REQUIRED_MOTORS:
        raise ValueError("Unknown growth motor")
    if len(reason.strip()) < 10:
        raise ValueError("A detailed control-state reason is required")
    key = f"motor:{motor_key}"
    row = db.get(GrowthControlState, key)
    if not row:
        row = GrowthControlState(key=key)
        db.add(row)
    before = {"enabled": row.enabled, "reason": row.reason}
    row.enabled = enabled
    row.reason = reason.strip()
    row.changed_by = actor
    row.changed_at = utcnow()
    audit(
        db,
        actor=actor,
        action="growth_motor_enabled" if enabled else "growth_motor_paused",
        entity_type="growth_motor",
        entity_id=motor_key,
        before=before,
        after={"enabled": enabled, "reason": row.reason},
    )
    db.commit()
    return row


def _signal_dedupe(data: GrowthSignalIn, brand_id: str) -> str:
    identity = data.company_registration_id or (data.company_name or "").strip().lower()
    return sha(
        {
            "identity": identity,
            "signal_type": data.signal_type,
            "brand_id": brand_id,
            "detected_date": _aware(data.detected_at).date().isoformat(),
            "evidence_url": data.evidence_url,
        }
    )


def _validated_source_evidence(
    data: GrowthSignalIn, source_evidence: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    public_land_listing = _is_public_land_listing_contact(data)
    if source_evidence is None:
        if public_land_listing:
            raise GrowthRegistryError("public_land_source_evidence_required")
        return []
    if not public_land_listing:
        raise GrowthRegistryError("source_evidence_only_allowed_for_public_land_listing")
    if (
        not data.public_contact_url
        or data.public_contact_url != data.evidence_url
        or urlsplit(data.public_contact_url).scheme != "https"
    ):
        raise GrowthRegistryError("public_land_listing_url_binding_mismatch")
    expected_required: dict[str, str] = {
        "listing_permalink": str(data.public_contact_url or ""),
        "recipient_email": str(data.recipient_email or ""),
        "recipient_role": data.recipient_role,
    }
    expected_known = {
        **expected_required,
        **(
            {"recipient_name": data.recipient_name}
            if data.recipient_name is not None
            else {}
        ),
        **({"location": data.location} if data.location is not None else {}),
        **(
            {"plot_size_sqm": str(data.plot_size_sqm)}
            if data.plot_size_sqm is not None
            else {}
        ),
        **(
            {"recipient_organization_name": data.recipient_organization_name}
            if data.recipient_organization_name is not None
            else {}
        ),
        **(
            {"recipient_office_name": data.recipient_office_name}
            if data.recipient_office_name is not None
            else {}
        ),
    }
    allowed_fields = set(expected_required) | {
        "recipient_name",
        "property_type",
        "location",
        "plot_size_sqm",
        "recipient_organization_name",
        "recipient_office_name",
    }
    supplied: dict[str, dict[str, Any]] = {}
    for item in source_evidence:
        if not isinstance(item, dict):
            raise GrowthRegistryError("public_land_source_evidence_invalid")
        field_name = str(item.get("field_name") or "")
        if field_name in supplied or field_name not in allowed_fields:
            raise GrowthRegistryError("public_land_source_evidence_field_invalid")
        observed_value = str(item.get("observed_value") or "")
        snippet = str(item.get("source_snippet") or "")
        source_url = str(item.get("source_url") or "")
        snapshot_sha256 = str(item.get("snapshot_sha256") or "")
        fetched_at = item.get("fetched_at")
        if (
            (field_name in expected_known and observed_value != expected_known[field_name])
            or not observed_value.strip()
            or not snippet.strip()
            or len(snippet) > 2_000
            or source_url != data.evidence_url
            or snapshot_sha256 != data.source_payload_hash
            or not isinstance(fetched_at, datetime)
            or _aware(fetched_at) > utcnow()
        ):
            raise GrowthRegistryError("public_land_source_evidence_binding_mismatch")
        supplied[field_name] = {
            "field_name": field_name,
            "observed_value": observed_value,
            "source_snippet": snippet,
            "source_url": source_url,
            "snapshot_sha256": snapshot_sha256,
            "fetched_at": _aware(fetched_at),
        }
    if not set(expected_required).issubset(supplied):
        raise GrowthRegistryError("public_land_source_evidence_incomplete")
    return [supplied[field_name] for field_name in sorted(supplied)]


def _source_evidence_manifest_sha256(evidence: list[dict[str, Any]]) -> str:
    manifest = [
        {
            "field_name": str(item["field_name"]),
            "observed_value": str(item["observed_value"]),
            "source_snippet": str(item["source_snippet"]),
            "snippet_sha256": hashlib.sha256(
                str(item["source_snippet"]).encode("utf-8")
            ).hexdigest(),
            "source_url": str(item["source_url"]),
            "snapshot_sha256": str(item["snapshot_sha256"]),
            "fetched_at": _aware(item["fetched_at"]).isoformat(),
        }
        for item in sorted(evidence, key=lambda value: str(value["field_name"]))
    ]
    return sha(manifest)


def _persisted_source_evidence_manifest_sha256(db: Session, signal_id: str) -> str:
    rows = list(
        db.scalars(
            select(GrowthSignalSourceEvidence).where(
                GrowthSignalSourceEvidence.signal_id == signal_id
            )
        )
    )
    return _source_evidence_manifest_sha256(
        [
            {
                "field_name": row.field_name,
                "observed_value": row.observed_value,
                "source_snippet": row.source_snippet,
                "source_url": row.source_url,
                "snapshot_sha256": row.snapshot_sha256,
                "fetched_at": row.fetched_at,
            }
            for row in rows
        ]
    )


def _score(data: GrowthSignalIn) -> int:
    score = round(data.confidence * 0.45 + data.urgency * 0.35)
    if data.company_registration_id:
        score += 8
    if data.recipient_email:
        score += 7
    if data.contact_basis in {"explicit_request", "documented_consent"}:
        score += 5
    return min(100, max(0, score))


def _is_public_land_listing_contact(data: GrowthSignalIn) -> bool:
    return (
        data.signal_type == "residential_building_plot"
        and data.contact_basis == "public_property_listing"
        and data.recipient_role in LAND_RECIPIENT_TYPES_BY_ROLE
        and data.recipient_email_type in {"role", "named", "unknown"}
        and bool(data.public_contact_url)
    )


def _canonical_screening_values(
    data: GrowthSignalIn,
    *,
    render_recipient_name: str | None = None,
) -> list[object]:
    return [
        render_recipient_name if render_recipient_name is not None else data.recipient_name,
        data.company_name,
        data.recipient_organization_name,
        data.recipient_office_name,
        data.recipient_email,
        data.recipient_role,
        data.sender_company_name,
        *data.reference_names,
        data.business_context,
        data.business_context_evidence_url,
        data.summary,
        data.evidence_url,
        data.public_contact_url,
    ]


def _is_recipient_hard_gate_error(exc: Exception) -> bool:
    reason = str(exc)
    return (
        reason in LAND_AGENT_HARD_GATE_REASONS
        or reason == "no_monitoring_hard_gate_blocked"
        or reason.startswith("canonical_hard_gate_blocked:")
        or reason.startswith("outbound_recipient_hard_gate_no_send:")
        or reason.startswith("cross_brand_customer_facing_content_no_send:")
        or reason.startswith("public_land_live_")
        or reason.startswith("public_land_source_evidence_")
    )


def _land_canary_limit() -> int:
    value = getattr(settings(), "land_outreach_production_canary_max_total", 3)
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise GrowthRegistryError("land_outreach_production_canary_cap_invalid") from exc
    if not 0 <= limit <= 3:
        raise GrowthRegistryError("land_outreach_production_canary_cap_invalid")
    return limit


def _land_canary_scope(db: Session, now: datetime | None = None) -> tuple[int, date, bool]:
    limit = _land_canary_limit()
    raw_date = str(
        getattr(settings(), "land_outreach_production_canary_local_date", "") or ""
    ).strip()
    try:
        scope_date = date.fromisoformat(raw_date)
        zone = ZoneInfo(settings().timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise GrowthRegistryError("land_outreach_production_canary_date_invalid") from exc
    state = db.get(GrowthLandCanaryState, 1)
    if (
        state is None
        or state.scope_local_date != scope_date
        or state.max_total != limit
        or state.status not in {"pending", "completed", "released"}
    ):
        raise GrowthRegistryError("land_outreach_production_canary_state_invalid")
    if state.status == "released":
        return limit, scope_date, False
    current_date = (now or utcnow()).astimezone(zone).date()
    if current_date != scope_date:
        raise GrowthRegistryError("land_outreach_production_canary_release_required")
    if limit <= 0:
        raise GrowthRegistryError("land_outreach_production_canary_cap_reached")
    return limit, scope_date, True


def _valid_land_canary_slot(row: GrowthLandCanarySlot) -> bool:
    if row.status == "available":
        return not any((row.outreach_id, row.claimed_at, row.sent_at))
    if row.status == "claimed":
        return bool(row.outreach_id and row.claimed_at and row.sent_at is None)
    if row.status in {"sent", "consumed"}:
        return bool(row.outreach_id and row.claimed_at and row.sent_at)
    return False


def _claim_land_canary_slot(db: Session, outreach_id: str, *, now: datetime | None = None) -> bool:
    if not str(
        getattr(settings(), "land_outreach_production_canary_local_date", "") or ""
    ).strip():
        return False
    limit, scope_date, active = _land_canary_scope(db, now)
    if not active:
        return False
    rows = list(
        db.scalars(
            select(GrowthLandCanarySlot)
            .where(GrowthLandCanarySlot.scope_local_date == scope_date)
            .order_by(GrowthLandCanarySlot.slot_number)
            .with_for_update()
        )
    )
    if (
        len(rows) != 3
        or [row.slot_number for row in rows] != [1, 2, 3]
        or any(not _valid_land_canary_slot(row) for row in rows)
    ):
        raise GrowthRegistryError("land_outreach_production_canary_slots_invalid")
    zone = ZoneInfo(settings().timezone)
    day_start = datetime.combine(scope_date, time.min, tzinfo=zone).astimezone(UTC)
    day_end = (datetime.combine(scope_date, time.min, tzinfo=zone) + timedelta(days=1)).astimezone(
        UTC
    )
    # Backfill provider-accepted messages from the scoped day before any claim.
    historical = list(
        db.scalars(
            select(OutreachMessage)
            .join(
                GrowthSignal,
                GrowthSignal.signal_id == OutreachMessage.signal_id,
            )
            .where(
                OutreachMessage.sent_at >= day_start,
                OutreachMessage.sent_at < day_end,
                OutreachMessage.status.in_(("sent", "delivered", "responded")),
                GrowthSignal.signal_type == "residential_building_plot",
                GrowthSignal.contact_basis == "public_property_listing",
                GrowthSignal.public_contact_url.is_not(None),
                GrowthSignal.public_contact_url == GrowthSignal.evidence_url,
            )
            .order_by(OutreachMessage.sent_at.asc(), OutreachMessage.id.asc())
        )
    )
    represented = {
        value
        for value in db.scalars(
            select(GrowthLandCanarySlot.outreach_id).where(
                GrowthLandCanarySlot.scope_local_date == scope_date,
                GrowthLandCanarySlot.outreach_id.is_not(None),
            )
        )
        if value
    }
    for historical_row in historical:
        if historical_row.outreach_id in represented:
            continue
        available = db.scalar(
            select(GrowthLandCanarySlot)
            .where(
                GrowthLandCanarySlot.scope_local_date == scope_date,
                GrowthLandCanarySlot.status == "available",
            )
            .order_by(GrowthLandCanarySlot.slot_number)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not available:
            break
        available.status = "sent"
        available.outreach_id = historical_row.outreach_id
        available.claimed_at = historical_row.sent_at or historical_row.updated_at
        available.sent_at = historical_row.sent_at or historical_row.updated_at
        available.provider_message_id = historical_row.provider_message_id
        available.updated_at = utcnow()
        represented.add(historical_row.outreach_id)
        db.flush()
    existing = db.scalar(
        select(GrowthLandCanarySlot)
        .where(GrowthLandCanarySlot.outreach_id == outreach_id)
        .with_for_update()
    )
    if existing:
        if existing.scope_local_date == scope_date and existing.status in {
            "claimed",
            "sent",
            "consumed",
        }:
            return True
        raise GrowthRegistryError("land_outreach_production_canary_state_invalid")
    slot = db.scalar(
        select(GrowthLandCanarySlot)
        .where(
            GrowthLandCanarySlot.slot_number <= limit,
            GrowthLandCanarySlot.scope_local_date == scope_date,
            GrowthLandCanarySlot.status == "available",
        )
        .order_by(GrowthLandCanarySlot.slot_number)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not slot:
        raise GrowthRegistryError("land_outreach_production_canary_cap_reached")
    slot.status = "claimed"
    slot.outreach_id = outreach_id
    slot.claimed_at = utcnow()
    slot.sent_at = None
    slot.provider_message_id = None
    slot.updated_at = utcnow()
    db.flush()
    return True


def _finish_land_canary_slot(
    db: Session,
    outreach_id: str,
    *,
    outcome: str,
    provider_message_id: str | None = None,
) -> None:
    slot = db.scalar(
        select(GrowthLandCanarySlot)
        .where(GrowthLandCanarySlot.outreach_id == outreach_id)
        .with_for_update()
    )
    if not slot:
        return
    if outcome in {"sent", "consumed"}:
        slot.status = outcome
        slot.sent_at = utcnow()
        slot.provider_message_id = provider_message_id
    elif outcome == "release":
        slot.status = "available"
        slot.outreach_id = None
        slot.claimed_at = None
        slot.sent_at = None
        slot.provider_message_id = None
    else:
        raise GrowthRegistryError("land_outreach_production_canary_outcome_invalid")
    slot.updated_at = utcnow()
    if outcome in {"sent", "consumed"}:
        # SessionLocal intentionally disables autoflush. Persist the current
        # slot transition before counting the completed canary deliveries, or
        # the final slot remains invisible and the singleton stays pending.
        db.flush()
        state = db.get(GrowthLandCanaryState, 1)
        if state is None:
            raise GrowthRegistryError("land_outreach_production_canary_state_invalid")
        consumed = int(
            db.scalar(
                select(func.count())
                .select_from(GrowthLandCanarySlot)
                .where(
                    GrowthLandCanarySlot.scope_local_date == state.scope_local_date,
                    GrowthLandCanarySlot.status.in_(("sent", "consumed")),
                    GrowthLandCanarySlot.slot_number <= state.max_total,
                )
            )
            or 0
        )
        if consumed >= state.max_total:
            state.status = "completed"
            state.updated_at = utcnow()


def _gmail_sent_mime_verified(row: OutreachMessage) -> bool:
    if not row.sent_at or not row.provider_message_id or not row.receipt_json:
        return False
    try:
        receipt = json.loads(row.receipt_json)
    except (TypeError, json.JSONDecodeError):
        return False
    detail = receipt.get("delivery_detail")
    if not isinstance(detail, dict):
        return False
    mime_sha256 = detail.get("readback_mime_sha256")
    response_sha256 = receipt.get("response_sha256")
    rfc_message_id = detail.get("rfc_message_id")
    label_ids = detail.get("label_ids")
    return bool(
        receipt.get("provider") == "gmail_api"
        and receipt.get("accepted") is True
        and detail.get("readback_verified") is True
        and detail.get("provider_message_id") == row.provider_message_id
        and isinstance(label_ids, list)
        and "SENT" in label_ids
        and isinstance(mime_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", mime_sha256)
        and isinstance(response_sha256, str)
        and hmac.compare_digest(response_sha256, mime_sha256)
        and isinstance(rfc_message_id, str)
        and rfc_message_id.startswith("<")
        and rfc_message_id.endswith(">")
    )


def release_land_canary(
    db: Session,
    *,
    approved_by: str,
    now: datetime | None = None,
) -> GrowthLandCanaryState:
    actor = approved_by.strip()
    if not actor:
        raise GrowthRegistryError("land_outreach_production_canary_releaser_missing")
    state = db.scalar(
        select(GrowthLandCanaryState).where(GrowthLandCanaryState.id == 1).with_for_update()
    )
    if state is None or state.status != "completed":
        raise GrowthRegistryError("land_outreach_production_canary_not_completed")
    limit = _land_canary_limit()
    raw_date = str(
        getattr(settings(), "land_outreach_production_canary_local_date", "") or ""
    ).strip()
    try:
        configured_date = date.fromisoformat(raw_date)
        zone = ZoneInfo(settings().timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise GrowthRegistryError("land_outreach_production_canary_date_invalid") from exc
    if limit <= 0 or state.scope_local_date != configured_date or state.max_total != limit:
        raise GrowthRegistryError("land_outreach_production_canary_state_invalid")
    slots = list(
        db.scalars(
            select(GrowthLandCanarySlot)
            .where(
                GrowthLandCanarySlot.scope_local_date == state.scope_local_date,
                GrowthLandCanarySlot.slot_number <= state.max_total,
            )
            .order_by(GrowthLandCanarySlot.slot_number)
            .with_for_update()
        )
    )
    if (
        len(slots) != state.max_total
        or [slot.slot_number for slot in slots] != list(range(1, state.max_total + 1))
        or any(
            slot.status != "sent" or not slot.outreach_id or not slot.provider_message_id
            for slot in slots
        )
    ):
        raise GrowthRegistryError("land_outreach_production_canary_verified_delivery_required")
    verified_outreach_ids: list[str] = []
    verified_delivery_evidence: list[dict[str, Any]] = []
    for slot in slots:
        row = db.scalar(
            select(OutreachMessage)
            .where(OutreachMessage.outreach_id == slot.outreach_id)
            .with_for_update()
        )
        if (
            row is None
            or row.provider_message_id != slot.provider_message_id
            or not _gmail_sent_mime_verified(row)
        ):
            raise GrowthRegistryError("land_outreach_production_canary_verified_delivery_required")
        receipt = json.loads(row.receipt_json)
        delivery_detail = receipt["delivery_detail"]
        verified_outreach_ids.append(row.outreach_id)
        verified_delivery_evidence.append(
            {
                "slot_number": slot.slot_number,
                "outreach_id": row.outreach_id,
                "provider_message_id": row.provider_message_id,
                "rfc_message_id": delivery_detail["rfc_message_id"],
                "label_ids": delivery_detail["label_ids"],
                "readback_verified": delivery_detail["readback_verified"],
                "readback_mime_sha256": delivery_detail["readback_mime_sha256"],
                "response_sha256": receipt["response_sha256"],
            }
        )
    release_at = now or utcnow()
    local_date = release_at.astimezone(zone).date()
    if local_date < state.scope_local_date:
        raise GrowthRegistryError("land_outreach_production_canary_release_too_early")
    state.status = "released"
    state.released_by = actor
    state.released_at = release_at
    state.updated_at = release_at
    audit(
        db,
        actor=actor,
        action="growth_land_production_canary_released",
        entity_type="growth_land_canary",
        entity_id=str(state.scope_local_date),
        after={
            "max_total": state.max_total,
            "status": state.status,
            "verified_sent": len(verified_outreach_ids),
            "verified_outreach_ids": verified_outreach_ids,
            "verified_delivery_evidence": verified_delivery_evidence,
            "scope_local_date": state.scope_local_date.isoformat(),
            "release_local_date": local_date.isoformat(),
            "same_day_release_allowed_after_exact_verification": True,
            "release_not_before_scope_local_date": True,
            "approved_by_present": True,
        },
    )
    db.commit()
    return state


def _public_land_signal(signal: GrowthSignal) -> bool:
    return bool(
        signal.signal_type == "residential_building_plot"
        and signal.contact_basis == "public_property_listing"
        and signal.recipient_role in LAND_RECIPIENT_TYPES_BY_ROLE
        and signal.public_contact_url
        and signal.public_contact_url == signal.evidence_url
    )


def _authoritative_send_readiness_reason(
    db: Session,
    registry: GrowthRegistry,
    signal: GrowthSignal,
) -> str | None:
    state = _outbound_send_readiness_state(db, registry)
    if not state["ready"]:
        return str(state["reason"])
    if not _public_land_signal(signal) and int(state.get("scheduled_enabled_sources") or 0) <= 0:
        return "growth_scheduled_source_missing"
    if state.get("canary_active") and not _public_land_signal(signal):
        return "land_outreach_production_canary_public_land_only"
    return None


def _outbound_send_readiness_state(
    db: Session,
    registry: GrowthRegistry,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "ready": False,
        "reason": None,
        "scheduled_enabled_sources": 0,
        "managed_land_source": {"ready": False},
        "managed_land_routes": {"ready": False},
        "land_canary": {"ready": False},
    }
    if _PROCESS_EMERGENCY_SEND_STOP.is_set():
        detail["reason"] = "growth_process_emergency_stop_no_send"
        return detail
    if not writes_unlocked():
        detail["reason"] = "growth_writes_locked"
        return detail
    try:
        paused_motors = [
            motor_key
            for motor_key in sorted(GrowthRegistry.REQUIRED_MOTORS)
            if not _control_enabled(db, motor_key)
        ]
        if paused_motors:
            detail["reason"] = "growth_controls_paused_no_send"
            detail["paused_motors"] = paused_motors
            return detail
        db.execute(select(func.count()).select_from(GrowthSignalSourceEvidence))
        db.execute(select(func.count()).select_from(GrowthPublicLandListingCursor))
        db.execute(select(func.count()).select_from(GrowthLandCanaryState))
        db.execute(select(func.count()).select_from(GrowthLandCanarySlot))
        sources = registry.sources
        if not isinstance(sources, dict):
            detail["reason"] = "growth_source_registry_missing"
            return detail
        scheduled = [
            (source_id, source)
            for source_id, source in sources.items()
            if isinstance(source, dict)
            and source.get("enabled") is True
            and source.get("fetch_mode", "scheduled") != "ingest_only"
        ]
        detail["scheduled_enabled_sources"] = len(scheduled)
        detail["scheduled_source_lane"] = {
            "ready": bool(scheduled),
            "informational_for_public_land": True,
        }
        from ..land_acquisition.service import (
            managed_public_land_route_set_sha256,
            public_land_route_readiness,
        )

        expected_route_sha = managed_public_land_route_set_sha256()
        land_source = sources.get("construction_public_land_html")
        if not isinstance(land_source, dict) or land_source.get("enabled") is not True:
            detail["reason"] = "managed_land_source_binding_missing"
            return detail
        if (
            land_source.get("kind") != "public_land_listing_html"
            or land_source.get("fetch_mode") != "ingest_only"
            or land_source.get("motor") != "construction"
            or land_source.get("bucket") != "property_development"
            or land_source.get("route_set_sha256") != expected_route_sha
        ):
            detail["reason"] = "managed_land_source_binding_invalid"
            return detail
        duplicate_bindings = [
            source_id
            for source_id, source in sources.items()
            if source_id != "construction_public_land_html"
            and isinstance(source, dict)
            and source.get("enabled") is True
            and source.get("fetch_mode") == "ingest_only"
            and source.get("motor") == "construction"
            and source.get("bucket") == "property_development"
        ]
        if duplicate_bindings:
            detail["reason"] = "managed_land_source_binding_not_unique"
            return detail
        detail["managed_land_source"] = {
            "ready": True,
            "source_id": "construction_public_land_html",
            "route_set_sha256": expected_route_sha,
        }
        route_state = public_land_route_readiness(db)
        detail["managed_land_routes"] = route_state
        if not route_state.get("ready"):
            detail["reason"] = "public_land_route_readiness_no_send"
            return detail
        canary_date = str(
            getattr(settings(), "land_outreach_production_canary_local_date", "") or ""
        ).strip()
        if not canary_date:
            detail["land_canary"] = {
                "ready": True,
                "configured": False,
                "active": False,
            }
            detail["canary_active"] = False
        else:
            limit, scope_date, canary_active = _land_canary_scope(db)
            slots = list(
                db.scalars(
                    select(GrowthLandCanarySlot).where(
                        GrowthLandCanarySlot.scope_local_date == scope_date
                    )
                )
            )
            if (
                len(slots) != 3
                or sorted(row.slot_number for row in slots) != [1, 2, 3]
                or any(not _valid_land_canary_slot(row) for row in slots)
            ):
                detail["reason"] = "land_outreach_production_canary_slots_invalid"
                return detail
            if limit < 0:
                detail["reason"] = "land_outreach_production_canary_cap_invalid"
                return detail
            state = db.get(GrowthLandCanaryState, 1)
            detail["land_canary"] = {
                "ready": True,
                "configured": True,
                "scope_local_date": scope_date.isoformat(),
                "max_total": limit,
                "status": state.status if state else None,
                "active": canary_active,
                "valid_slots": len(slots),
            }
            detail["canary_active"] = canary_active
    except (GrowthRegistryError, LandRegistryError) as exc:
        detail["reason"] = str(exc)
        return detail
    except Exception:
        db.rollback()
        detail["reason"] = "growth_send_readiness_schema_invalid"
        return detail
    detail["ready"] = True
    return detail


def _assert_public_land_evidence_manifest(
    db: Session,
    signal: GrowthSignal,
    canonical_metadata: dict[str, Any],
) -> None:
    if not _public_land_signal(signal):
        return
    expected = str(canonical_metadata.get("source_evidence_manifest_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise GrowthRegistryError("public_land_source_evidence_manifest_missing")
    actual = _persisted_source_evidence_manifest_sha256(db, signal.signal_id)
    if not hmac.compare_digest(expected, actual):
        raise GrowthRegistryError("public_land_source_evidence_manifest_mismatch")


def _attest_live_listing_evidence(row: OutreachMessage, evidence: dict[str, Any]) -> dict[str, Any]:
    key = platform_settings.imperial_release_hmac_key
    if len(key) < 32:
        raise GrowthRegistryError("IMPERIAL_RELEASE_HMAC_KEY is not configured")
    payload = dict(evidence)
    value = canonical_json(
        {
            "outreach_id": row.outreach_id,
            "idempotency_key": row.idempotency_key,
            "live_listing_evidence": payload,
        }
    )
    payload["attestation_hmac_sha256"] = hmac.new(
        key.encode(), value.encode(), hashlib.sha256
    ).hexdigest()
    return payload


def _assert_live_listing_evidence_attestation(
    row: OutreachMessage, evidence: dict[str, Any]
) -> None:
    supplied = str(evidence.get("attestation_hmac_sha256") or "")
    unsigned = {key: value for key, value in evidence.items() if key != "attestation_hmac_sha256"}
    expected = _attest_live_listing_evidence(row, unsigned)["attestation_hmac_sha256"]
    try:
        fetched_at = datetime.fromisoformat(str(unsigned.get("fetched_at") or ""))
    except ValueError as exc:
        raise GrowthRegistryError("public_land_live_attestation_invalid") from exc
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    if (
        unsigned.get("status") != "passed"
        or utcnow() - fetched_at.astimezone(UTC) > timedelta(minutes=5)
        or not hmac.compare_digest(supplied, expected)
    ):
        raise GrowthRegistryError("public_land_live_attestation_invalid")


def _incoming_hard_gate_reason(
    data: GrowthSignalIn, canonical_registry: CanonicalFirstContactRegistry
) -> str | None:
    land_agent_gate = _land_agent_gate_reason(data)
    if land_agent_gate:
        return land_agent_gate
    if contains_no_monitoring_entity(
        "\n".join(str(value or "") for value in _canonical_screening_values(data))
    ):
        return "no_monitoring_hard_gate_blocked"
    canonical_gate = canonical_registry.hard_gate_match(_canonical_screening_values(data))
    return f"canonical_hard_gate_blocked:{canonical_gate}" if canonical_gate else None


def _block_existing_signal_for_new_hard_gate(
    db: Session,
    existing: GrowthSignal,
    data: GrowthSignalIn,
    reason: str,
) -> None:
    before = {
        "status": existing.status,
        "recipient_email": existing.recipient_email,
        "recipient_organization_name": existing.recipient_organization_name,
        "recipient_office_name": existing.recipient_office_name,
    }
    for field in (
        "company_name",
        "recipient_organization_name",
        "recipient_office_name",
        "recipient_email",
        "recipient_role",
        "summary",
        "evidence_url",
        "public_contact_url",
        "plot_size_sqm",
        "source_payload_hash",
    ):
        incoming = getattr(data, field)
        if incoming is not None:
            setattr(existing, field, incoming)
    existing.last_seen_at = utcnow()
    existing.status = "blocked"
    existing.rejection_reasons_json = canonical_json([reason])
    unsent_rows = list(
        db.scalars(
            select(OutreachMessage)
            .where(
                OutreachMessage.signal_id == existing.signal_id,
                OutreachMessage.status.in_(("queued", "claimed")),
            )
            .with_for_update()
        )
    )
    for row in unsent_rows:
        row.status = "blocked"
        row.last_error = reason
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None
    audit(
        db,
        actor="growth-ops",
        action="growth_existing_outreach_new_hard_gate_blocked",
        entity_type="growth_signal",
        entity_id=existing.signal_id,
        before=before,
        after={
            "status": existing.status,
            "reason": reason,
            "source_payload_hash": data.source_payload_hash,
            "blocked_outreach_ids": [row.outreach_id for row in unsent_rows],
        },
    )
    db.commit()


def _land_agent_gate_reason(signal: GrowthSignalIn | GrowthSignal) -> str | None:
    if signal.signal_type != "residential_building_plot":
        return None
    exclusion_reason = land_agent_hard_gate_reason(
        recipient_role=signal.recipient_role,
        contact_name=signal.company_name,
        organization_name=signal.recipient_organization_name,
        office_name=signal.recipient_office_name,
        recipient_email=signal.recipient_email,
        public_contact_url=signal.public_contact_url,
        evidence_url=signal.evidence_url,
    )
    if exclusion_reason:
        return exclusion_reason
    return None


def _eligibility(data: GrowthSignalIn, score: int) -> list[str]:
    reasons: list[str] = []
    public_land_contact = _is_public_land_listing_contact(data)
    if data.motor_key == "ivs":
        reasons.append("iora_internal_executive_review_only")
    if not public_land_contact and score < 55:
        reasons.append("score_below_55")
    if (
        not public_land_contact
        and utcnow() - _aware(data.detected_at) > timedelta(days=30)
    ):
        reasons.append("signal_older_than_30_days")
    if not data.recipient_email:
        reasons.append("recipient_email_missing")
    if data.contact_basis == "unknown":
        reasons.append("contact_basis_unknown")
    if (
        data.subject_type == "natural_person"
        and data.contact_basis not in {"explicit_request", "documented_consent"}
        and not public_land_contact
    ):
        reasons.append("natural_person_without_prior_consent_or_request")
    if data.contact_basis == "public_business_contact" and (
        data.subject_type != "organization" or data.recipient_email_type != "role"
    ):
        reasons.append("public_business_basis_requires_organization_role_inbox")
    if (
        data.recipient_email_type in {"named", "unknown"}
        and data.contact_basis not in {"explicit_request", "documented_consent"}
        and not public_land_contact
    ):
        reasons.append("named_or_unknown_mailbox_requires_consent_or_request")
    if data.contact_basis == "public_property_listing" and not public_land_contact:
        reasons.append("invalid_public_property_listing_contact")
    if data.recipient_type == "unknown":
        reasons.append("recipient_type_unclassified_no_send")
    if not data.recipient_classification_verified:
        reasons.append("recipient_classification_not_verified_no_send")
    if not data.exclusion_screening_verified:
        reasons.append("exclusion_screening_not_verified_no_send")
    if (
        not public_land_contact
        and data.recipient_type != "unknown"
        and not data.recipient_name
    ):
        reasons.append("recipient_name_missing")
    if data.recipient_type == "architect_office" and not data.sender_company_name:
        reasons.append("sender_company_name_missing")
    if data.recipient_type == "referral_partner" and not (
        data.business_context
        and data.business_context_verified
        and data.business_context_evidence_url
    ):
        reasons.append("template-variable-missing")
    if public_land_contact:
        required_recipient_type = LAND_RECIPIENT_TYPES_BY_ROLE[data.recipient_role]
        if data.recipient_type != required_recipient_type:
            reasons.append("land_recipient_role_type_mismatch_no_send")
    return sorted(set(reasons))


def _verified_sender(db: Session, binding: BrandBinding) -> MailSendingDomain:
    row = db.scalar(
        select(MailSendingDomain).where(
            MailSendingDomain.domain_key == binding.domain_key,
            MailSendingDomain.active.is_(True),
        )
    )
    if not row:
        raise GrowthRegistryError("Verified sending domain binding is missing")
    if row.from_email.strip().lower() != binding.sender_email:
        raise GrowthRegistryError("Sending-domain From address conflicts with the brand registry")
    sender_domain = binding.sender_email.rsplit("@", 1)[-1]
    if row.domain_name.strip().lower() != sender_domain:
        raise GrowthRegistryError("Sending-domain name conflicts with the brand registry")
    if row.provider == "gmail_api":
        if not GMAIL_OAUTH_FIELDS.issubset(binding.secret):
            raise GrowthRegistryError("Gmail OAuth sender binding is incomplete")
        scopes = str(binding.secret.get("scope") or "").split()
        if not any(
            scope.endswith("/gmail.compose") or scope.endswith("/gmail.send") for scope in scopes
        ) or not any(
            scope.endswith(("/gmail.readonly", "/gmail.modify", "/mail.google.com"))
            for scope in scopes
        ):
            raise GrowthRegistryError("Gmail OAuth sender scopes are incomplete")
        try:
            evidence = json.loads(row.verification_evidence_json or "{}")
        except json.JSONDecodeError as exc:
            raise GrowthRegistryError("Gmail OAuth sender evidence is unreadable") from exc
        if (
            not isinstance(evidence, dict)
            or evidence.get("verification_method") != "gmail_oauth_profile"
            or str(evidence.get("profile_email") or "").strip().lower() != binding.sender_email
            or row.verified_at is None
        ):
            raise GrowthRegistryError("Gmail OAuth sender profile is not verified")
        return row
    if any(getattr(row, name) != "pass" for name in ("spf_status", "dkim_status", "dmarc_status")):
        raise GrowthRegistryError("SPF, DKIM and DMARC must all pass")
    if row.provider == "provider_not_configured":
        raise GrowthRegistryError("Live mail provider is not configured")
    return row


def _render_message(
    signal: GrowthSignal,
    binding: BrandBinding,
    *,
    step: int,
    unsubscribe_token: str,
    data: GrowthSignalIn | None = None,
) -> tuple[str, str, dict[str, Any]]:
    if step != 0:
        raise GrowthRegistryError("owner_approved_followup_template_missing_no_send")
    if not settings().base_url.startswith("https://"):
        raise GrowthRegistryError("HTTPS GROWTH_OPS_BASE_URL is required")
    unsubscribe_url = f"{settings().base_url}/growth/unsubscribe/{unsubscribe_token}"
    if data is None:
        raise GrowthRegistryError("canonical_first_contact_input_missing")
    if signal.signal_type == "residential_building_plot":
        required_recipient_type = LAND_RECIPIENT_TYPES_BY_ROLE.get(signal.recipient_role)
        if not required_recipient_type or data.recipient_type != required_recipient_type:
            raise GrowthRegistryError("land_recipient_role_type_mismatch_no_send")
    public_land_contact = _is_public_land_listing_contact(data)
    render_recipient_name = data.recipient_name
    recipient_name_origin = "VERIFIED_LISTING_EVIDENCE"
    if public_land_contact and not render_recipient_name:
        render_recipient_name = LAND_RENDER_RECIPIENT_NAME_BY_ROLE.get(signal.recipient_role)
        recipient_name_origin = "ROLE_FALLBACK"
    if not render_recipient_name:
        raise GrowthRegistryError("template-variable-missing:recipient_name")
    rendered = CanonicalFirstContactRegistry.load().render(
        recipient_type=data.recipient_type,
        recipient_name=render_recipient_name,
        sender_company_name=data.sender_company_name,
        reference_names=data.reference_names,
        reference_names_verified=data.reference_names_verified,
        business_context=data.business_context,
        business_context_verified=data.business_context_verified,
        business_context_evidence_url=data.business_context_evidence_url,
        listing_location=data.location,
        listing_size=(f"{data.plot_size_sqm} m²" if data.plot_size_sqm else None),
        listing_url=data.public_contact_url or data.evidence_url,
        unsubscribe_url=unsubscribe_url,
        recipient_classification_verified=data.recipient_classification_verified,
        exclusion_screening_verified=data.exclusion_screening_verified,
        screening_values=_canonical_screening_values(
            data,
            render_recipient_name=render_recipient_name,
        ),
    )
    if rendered.sender_brand_id != binding.brand_id:
        raise GrowthRegistryError("canonical_template_sender_brand_conflicts_with_routing")
    if not rendered.sendable or not rendered.subject:
        raise GrowthRegistryError(";".join(rendered.blocked_reasons))
    metadata = rendered.metadata()
    if public_land_contact:
        metadata["recipient_name_render_policy"] = {
            "policy_version": LAND_RENDER_RECIPIENT_NAME_POLICY_VERSION,
            "origin": recipient_name_origin,
            "recipient_role": signal.recipient_role,
            "evidence_recipient_name_present": bool(data.recipient_name),
        }
        render_input = metadata.get("render_input")
        if (
            not isinstance(render_input, dict)
            or render_input.get("listing_url") != data.public_contact_url
            or data.public_contact_url != data.evidence_url
        ):
            raise GrowthRegistryError("public_land_render_listing_url_binding_mismatch")
    return rendered.subject, rendered.body_text, metadata


def _recipient_suppressed(db: Session, email: str) -> bool:
    return bool(
        db.scalar(
            select(MailSuppression.id).where(
                MailSuppression.email == email.lower(),
                MailSuppression.active.is_(True),
            )
        )
    )


def _rate_errors(db: Session, binding: BrandBinding, recipient: str) -> list[str]:
    now = utcnow()
    recent_recipient = db.scalar(
        select(OutreachMessage.id)
        .where(
            OutreachMessage.brand_id == binding.brand_id,
            OutreachMessage.recipient_email == recipient,
            OutreachMessage.created_at
            >= now - timedelta(days=int(binding.config.get("recipient_cooldown_days", 30))),
            OutreachMessage.status.in_(("queued", "claimed", "sent", "delivered", "responded")),
        )
        .limit(1)
    )
    errors: list[str] = []
    if recent_recipient:
        errors.append("recipient_brand_cooldown")
    return errors


def _queue_message(
    db: Session,
    signal: GrowthSignal,
    binding: BrandBinding,
    *,
    step: int,
    available_at: datetime,
    enforce_recipient_cooldown: bool,
    data: GrowthSignalIn | None = None,
    source_evidence_manifest_sha256: str | None = None,
) -> OutreachMessage:
    hard_gate_reason = _land_agent_gate_reason(signal)
    if hard_gate_reason:
        raise GrowthRegistryError(hard_gate_reason)
    if _recipient_suppressed(db, signal.recipient_email or ""):
        raise GrowthRegistryError("Recipient is suppressed")
    if enforce_recipient_cooldown:
        # A queued candidate is not a Gmail transport reservation. The rolling
        # 24-hour account quota, single concurrency and persisted pacing gates
        # remain authoritative at claim and immediately before transport;
        # recipient cooldown is still enforced while the queue is built.
        errors = _rate_errors(db, binding, signal.recipient_email or "")
        if errors:
            raise GrowthRegistryError(";".join(errors))
    token = token_urlsafe(32)
    subject, body, canonical_metadata = _render_message(
        signal,
        binding,
        step=step,
        unsubscribe_token=token,
        data=data,
    )
    if data is not None and _is_public_land_listing_contact(data):
        if not source_evidence_manifest_sha256:
            raise GrowthRegistryError("public_land_source_evidence_manifest_missing")
        canonical_metadata["source_evidence_manifest_sha256"] = source_evidence_manifest_sha256
    body_html = str(canonical_metadata["body_html"])
    key = sha({"signal_id": signal.signal_id, "brand_id": binding.brand_id, "step": step})
    payload_hash = _outreach_payload_sha256(
        sender_email=binding.sender_email,
        recipient_email=signal.recipient_email or "",
        subject=subject,
        body_text=body,
        body_html=body_html,
        idempotency_key=key,
        unsubscribe_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        canonical_metadata=canonical_metadata,
    )
    row = OutreachMessage(
        outreach_id=f"OUT-{uuid4().hex[:20].upper()}",
        signal_id=signal.signal_id,
        motor_key=signal.motor_key,
        brand_id=binding.brand_id,
        sender_email=binding.sender_email,
        recipient_email=signal.recipient_email or "",
        sequence_step=step,
        subject=subject,
        body_text=body,
        body_html=body_html,
        unsubscribe_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        idempotency_key=key,
        payload_sha256=payload_hash,
        receipt_json=canonical_json({"canonical_template": canonical_metadata}),
        status="queued",
        available_at=available_at,
    )
    policy_release_audit: dict[str, Any] | None = None
    if (
        step == 0
        and signal.signal_type == "residential_building_plot"
        and signal.recipient_role in LAND_RECIPIENT_TYPES_BY_ROLE
        and (
            signal.contact_basis in {"explicit_request", "documented_consent"}
            or (data is not None and _is_public_land_listing_contact(data))
        )
    ):
        assert_outreach_copy(row.body_text)
        row.release_approved_by = "owner-policy:land-public-listing-v3:2026-08-28"
        row.release_approved_at = utcnow()
        row.release_token_hash = _release_digest(row, row.release_approved_by)
        policy_release_audit = {
            "payload_sha256": row.payload_sha256,
            "signal_id": signal.signal_id,
            "recipient_role": signal.recipient_role,
            "policy_scope": "single_initial_public_building_plot_outreach",
        }
    db.add(row)
    if policy_release_audit is not None:
        audit(
            db,
            actor=row.release_approved_by,
            action="growth_outreach_policy_released",
            entity_type="growth_outreach",
            entity_id=row.outreach_id,
            after=policy_release_audit,
        )
    return row


def ingest_signal(
    db: Session,
    data: GrowthSignalIn,
    *,
    run_id: str | None = None,
    source_evidence: list[dict[str, Any]] | None = None,
) -> GrowthSignalReceipt:
    pre_registry_hard_gate = _land_agent_gate_reason(data)
    if not pre_registry_hard_gate and contains_no_monitoring_entity(
        "\n".join(str(value or "") for value in _canonical_screening_values(data))
    ):
        pre_registry_hard_gate = "no_monitoring_hard_gate_blocked"
    if pre_registry_hard_gate:
        existing = db.scalar(
            select(GrowthSignal)
            .where(
                GrowthSignal.source_id == data.source_id,
                GrowthSignal.external_key == data.external_key,
            )
            .with_for_update()
        )
        if existing:
            _block_existing_signal_for_new_hard_gate(db, existing, data, pre_registry_hard_gate)
        raise GrowthRegistryError(pre_registry_hard_gate)
    canonical_registry = CanonicalFirstContactRegistry.load()
    hard_gate_reason = _incoming_hard_gate_reason(data, canonical_registry)
    if hard_gate_reason:
        existing = db.scalar(
            select(GrowthSignal)
            .where(
                GrowthSignal.source_id == data.source_id,
                GrowthSignal.external_key == data.external_key,
            )
            .with_for_update()
        )
        if existing:
            _block_existing_signal_for_new_hard_gate(db, existing, data, hard_gate_reason)
        raise GrowthRegistryError(hard_gate_reason)
    validated_source_evidence = _validated_source_evidence(data, source_evidence)
    source_evidence_manifest = (
        _source_evidence_manifest_sha256(validated_source_evidence)
        if validated_source_evidence
        else None
    )
    public_land_template_fields: set[str] = set()
    if _is_public_land_listing_contact(data):
        # A verified name remains evidence-bound when one is present. When the
        # listing exposes only an unambiguous email+role binding, the immutable
        # template receives a role-derived salutation at render time instead;
        # no synthetic recipient_name is persisted as source evidence.
        if data.recipient_name:
            public_land_template_fields.add("recipient_name")
        if data.recipient_role == "property_owner":
            public_land_template_fields.update({"location", "plot_size_sqm"})
    registry = GrowthRegistry.load()
    registry.validate_signal_source(
        source_id=data.source_id,
        motor_key=data.motor_key,
        source_bucket=data.source_bucket,
        recipient_type=data.recipient_type,
        recipient_email=data.recipient_email,
        recipient_email_type=data.recipient_email_type,
        contact_basis=data.contact_basis,
        recipient_name=data.recipient_name,
        company_name=data.company_name,
        recipient_organization_name=data.recipient_organization_name,
        evidence_url=data.evidence_url,
        public_contact_url=data.public_contact_url,
        source_payload_hash=data.source_payload_hash,
        detected_at=data.detected_at,
    )
    brand_id = registry.brand_for(data.signal_type, data.brand_id)
    dedupe_hash = _signal_dedupe(data, brand_id)
    existing = db.scalar(
        select(GrowthSignal)
        .where(
            or_(
                and_(
                    GrowthSignal.source_id == data.source_id,
                    GrowthSignal.external_key == data.external_key,
                ),
                GrowthSignal.dedupe_hash == dedupe_hash,
            )
        )
        .with_for_update()
    )
    if existing:
        existing.last_seen_at = utcnow()
        db.commit()
        outreach = db.scalar(
            select(OutreachMessage).where(
                OutreachMessage.signal_id == existing.signal_id,
                OutreachMessage.sequence_step == 0,
            )
        )
        return GrowthSignalReceipt(
            signal_id=existing.signal_id,
            status=existing.status,
            brand_id=existing.brand_id,
            score=existing.score,
            idempotent=True,
            outreach_id=outreach.outreach_id if outreach else None,
            reasons=json.loads(existing.rejection_reasons_json or "[]"),
        )
    score = _score(data)
    reasons = _eligibility(data, score)
    row = GrowthSignal(
        signal_id=f"SIG-{uuid4().hex[:20].upper()}",
        run_id=run_id,
        motor_key=data.motor_key,
        source_id=data.source_id,
        source_bucket=data.source_bucket,
        external_key=data.external_key,
        signal_type=data.signal_type,
        detected_at=_aware(data.detected_at),
        company_name=data.company_name,
        company_registration_id=data.company_registration_id,
        recipient_organization_name=data.recipient_organization_name,
        recipient_office_name=data.recipient_office_name,
        subject_type=data.subject_type,
        recipient_role=data.recipient_role,
        recipient_email=data.recipient_email,
        recipient_email_type=data.recipient_email_type,
        contact_basis=data.contact_basis,
        consent_evidence_id=data.consent_evidence_id,
        public_contact_url=data.public_contact_url,
        location=data.location,
        plot_size_sqm=data.plot_size_sqm,
        summary=data.summary,
        evidence_url=data.evidence_url,
        brand_id=brand_id,
        score=score,
        urgency=data.urgency,
        confidence=data.confidence,
        dedupe_hash=dedupe_hash,
        source_payload_hash=data.source_payload_hash,
        status=(
            "template-variable-missing"
            if "template-variable-missing" in reasons
            else "rejected"
            if reasons
            else "accepted"
        ),
        rejection_reasons_json=canonical_json(reasons),
    )
    db.add(row)
    db.flush()
    for evidence in validated_source_evidence:
        snippet = str(evidence["source_snippet"])
        db.add(
            GrowthSignalSourceEvidence(
                evidence_id=f"GSE-{uuid4().hex[:20].upper()}",
                signal_id=row.signal_id,
                field_name=str(evidence["field_name"]),
                observed_value=str(evidence["observed_value"]),
                source_snippet=snippet,
                snippet_sha256=hashlib.sha256(snippet.encode("utf-8")).hexdigest(),
                source_url=str(evidence["source_url"]),
                snapshot_sha256=str(evidence["snapshot_sha256"]),
                fetched_at=evidence["fetched_at"],
            )
        )
    outreach: OutreachMessage | None = None
    if not reasons:
        try:
            if public_land_template_fields:
                evidenced_fields = {
                    str(item["field_name"]) for item in validated_source_evidence
                }
                missing_template_fields = sorted(
                    field_name
                    for field_name in public_land_template_fields
                    if field_name not in evidenced_fields
                    or not str(getattr(data, field_name, None) or "").strip()
                )
                if missing_template_fields:
                    raise GrowthRegistryError(
                        "template-variable-missing:"
                        + ",".join(missing_template_fields)
                    )
            binding = registry.brand_binding(brand_id)
            _verified_sender(db, binding)
            if not writes_unlocked() or not _control_enabled(db, data.motor_key):
                raise GrowthRegistryError("growth_writes_locked")
            outreach = _queue_message(
                db,
                row,
                binding,
                step=0,
                available_at=utcnow(),
                enforce_recipient_cooldown=True,
                data=data,
                source_evidence_manifest_sha256=source_evidence_manifest,
            )
            row.status = "queued"
        except (GrowthRegistryError, ValueError) as exc:
            error = str(exc)
            render_missing_prefix = "Canonical render field is missing: "
            if error.startswith(render_missing_prefix):
                error = "template-variable-missing:" + error.removeprefix(
                    render_missing_prefix
                )
            reasons.append(error)
            if "template-variable-missing" in error:
                row.status = "template-variable-missing"
            else:
                row.status = "suppressed" if "suppressed" in error else "blocked"
            row.rejection_reasons_json = canonical_json(sorted(set(reasons)))
    registry_sources = getattr(registry, "sources", {})
    source = registry_sources.get(row.source_id) if isinstance(registry_sources, dict) else None
    if (
        outreach is not None
        and row.status == "queued"
        and isinstance(source, dict)
        and source.get("kind") == GrowthRegistry.OFFICIAL_COMPANY_SOURCE_KIND
    ):
        _record_official_source_binding_proof(
            db,
            outreach,
            row,
            source,
            actor="growth-ops",
            proof_origin="signal_ingest",
        )
    audit(
        db,
        actor="growth-ops",
        action="growth_signal_ingested",
        entity_type="growth_signal",
        entity_id=row.signal_id,
        after={
            "motor_key": row.motor_key,
            "source_id": row.source_id,
            "source_bucket": row.source_bucket,
            "signal_type": row.signal_type,
            "recipient_role": row.recipient_role,
            "brand_id": row.brand_id,
            "score": row.score,
            "status": row.status,
            "reasons": reasons,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Concurrent growth-signal idempotency conflict") from exc
    return GrowthSignalReceipt(
        signal_id=row.signal_id,
        status=row.status,
        brand_id=row.brand_id,
        score=row.score,
        idempotent=False,
        outreach_id=outreach.outreach_id if outreach else None,
        reasons=sorted(set(reasons)),
    )


def _public_land_name_fallback_signal_input(signal: GrowthSignal) -> GrowthSignalIn:
    recipient_type = LAND_RECIPIENT_TYPES_BY_ROLE.get(signal.recipient_role)
    if not recipient_type:
        raise GrowthRegistryError("land_recipient_role_type_mismatch_no_send")
    return GrowthSignalIn.model_validate(
        {
            "source_id": signal.source_id,
            "external_key": signal.external_key,
            "motor_key": signal.motor_key,
            "source_bucket": signal.source_bucket,
            "signal_type": signal.signal_type,
            "detected_at": signal.detected_at,
            "company_name": signal.company_name,
            "company_registration_id": signal.company_registration_id,
            "recipient_organization_name": signal.recipient_organization_name,
            "recipient_office_name": signal.recipient_office_name,
            "subject_type": signal.subject_type,
            "recipient_role": signal.recipient_role,
            "recipient_type": recipient_type,
            # The fallback is render-only. Persisted source identity remains null.
            "recipient_name": None,
            "recipient_classification_verified": True,
            "exclusion_screening_verified": True,
            "recipient_email": signal.recipient_email,
            "recipient_email_type": signal.recipient_email_type,
            "contact_basis": signal.contact_basis,
            "consent_evidence_id": signal.consent_evidence_id,
            "public_contact_url": signal.public_contact_url,
            "location": signal.location,
            "plot_size_sqm": signal.plot_size_sqm,
            "summary": signal.summary,
            "evidence_url": signal.evidence_url,
            "brand_id": signal.brand_id,
            "confidence": signal.confidence,
            "urgency": signal.urgency,
            "source_payload_hash": signal.source_payload_hash,
        }
    )


def _persisted_source_evidence(db: Session, signal_id: str) -> list[dict[str, Any]]:
    return [
        {
            "field_name": row.field_name,
            "observed_value": row.observed_value,
            "source_snippet": row.source_snippet,
            "source_url": row.source_url,
            "snapshot_sha256": row.snapshot_sha256,
            "fetched_at": row.fetched_at,
        }
        for row in db.scalars(
            select(GrowthSignalSourceEvidence)
            .where(GrowthSignalSourceEvidence.signal_id == signal_id)
            .order_by(GrowthSignalSourceEvidence.field_name)
        )
    ]


def _persisted_public_land_signal_input(
    signal: GrowthSignal,
    source_evidence: list[dict[str, Any]],
) -> GrowthSignalIn:
    payload = _public_land_name_fallback_signal_input(signal).model_dump()
    payload["recipient_name"] = next(
        (
            str(item["observed_value"])
            for item in source_evidence
            if item["field_name"] == "recipient_name"
        ),
        None,
    )
    return GrowthSignalIn.model_validate(payload)


def automatic_public_land_transient_block_promotion(
    db: Session,
    *,
    max_rows: int = 500,
) -> dict[str, Any]:
    """Re-queue only old public listings blocked by a transient queue condition."""

    if not settings().enabled:
        return {"status": "disabled", "selected_count": 0, "queued": 0}
    if not writes_unlocked():
        return {"status": "writes_locked", "selected_count": 0, "queued": 0}
    if max_rows < 1 or max_rows > 500:
        raise GrowthRegistryError("public_land_transient_promotion_limit_invalid")

    transient_reason_json = tuple(
        canonical_json([reason]) for reason in sorted(PUBLIC_LAND_TRANSIENT_QUEUE_REASONS)
    )
    filters = (
        GrowthSignal.status == "blocked",
        GrowthSignal.rejection_reasons_json.in_(transient_reason_json),
        GrowthSignal.signal_type == "residential_building_plot",
        GrowthSignal.contact_basis == "public_property_listing",
        GrowthSignal.recipient_role.in_(tuple(LAND_RECIPIENT_TYPES_BY_ROLE)),
        GrowthSignal.recipient_email.is_not(None),
        GrowthSignal.recipient_email_type.in_(("role", "named", "unknown")),
        GrowthSignal.public_contact_url.is_not(None),
        GrowthSignal.public_contact_url == GrowthSignal.evidence_url,
        GrowthSignal.signal_id.not_in(
            select(OutreachMessage.signal_id).where(OutreachMessage.sequence_step == 0)
        ),
    )
    rows = [
        row
        for row in db.scalars(
            select(GrowthSignal)
            .where(*filters)
            .order_by(GrowthSignal.id)
            .limit(max_rows)
            .with_for_update()
        )
        if _control_enabled(db, row.motor_key)
    ]
    if not rows:
        return {
            "status": "applied",
            "selected_count": 0,
            "queued": 0,
            "blocked": 0,
            "suppressed": 0,
            "idempotent": True,
        }

    registry = GrowthRegistry.load()
    canonical_registry = CanonicalFirstContactRegistry.load()
    outcomes: list[dict[str, Any]] = []
    for row in rows:
        before = {
            "status": row.status,
            "reasons": json.loads(row.rejection_reasons_json or "[]"),
        }
        outreach: OutreachMessage | None = None
        evidence_manifest_sha256: str | None = None
        try:
            source_evidence = _persisted_source_evidence(db, row.signal_id)
            data = _persisted_public_land_signal_input(row, source_evidence)
            hard_gate_reason = _incoming_hard_gate_reason(data, canonical_registry)
            if hard_gate_reason:
                raise GrowthRegistryError(hard_gate_reason)
            validated_evidence = _validated_source_evidence(data, source_evidence)
            required_template_evidence = (
                {"location", "plot_size_sqm"}
                if row.recipient_role == "property_owner"
                else set()
            )
            if data.recipient_name:
                required_template_evidence.add("recipient_name")
            evidenced_fields = {str(item["field_name"]) for item in validated_evidence}
            missing_template_fields = sorted(
                field_name
                for field_name in required_template_evidence
                if field_name not in evidenced_fields
                or not str(getattr(data, field_name, None) or "").strip()
            )
            if missing_template_fields:
                raise GrowthRegistryError(
                    "template-variable-missing:" + ",".join(missing_template_fields)
                )
            registry.validate_signal_source(
                source_id=data.source_id,
                motor_key=data.motor_key,
                source_bucket=data.source_bucket,
                recipient_type=data.recipient_type,
                recipient_email=data.recipient_email,
                recipient_email_type=data.recipient_email_type,
                contact_basis=data.contact_basis,
                recipient_name=data.recipient_name,
                company_name=data.company_name,
                recipient_organization_name=data.recipient_organization_name,
                evidence_url=data.evidence_url,
                public_contact_url=data.public_contact_url,
                source_payload_hash=data.source_payload_hash,
                detected_at=data.detected_at,
            )
            if registry.brand_for(data.signal_type, data.brand_id) != row.brand_id:
                raise GrowthRegistryError("public_land_transient_promotion_brand_mismatch")
            binding = registry.brand_binding(row.brand_id)
            _verified_sender(db, binding)
            evidence_manifest_sha256 = _source_evidence_manifest_sha256(validated_evidence)
            outreach = _queue_message(
                db,
                row,
                binding,
                step=0,
                available_at=utcnow(),
                enforce_recipient_cooldown=True,
                data=data,
                source_evidence_manifest_sha256=evidence_manifest_sha256,
            )
            # SessionLocal disables autoflush. Make this row visible to the
            # next recipient-cooldown query in the same promotion batch.
            db.flush()
            row.status = "queued"
            row.rejection_reasons_json = "[]"
            outcome = "queued"
            error = None
        except (GrowthRegistryError, ValueError) as exc:
            error = str(exc)
            render_missing_prefix = "Canonical render field is missing: "
            if error.startswith(render_missing_prefix):
                error = "template-variable-missing:" + error.removeprefix(
                    render_missing_prefix
                )
            row.status = "suppressed" if "suppressed" in error else "blocked"
            row.rejection_reasons_json = canonical_json([error])
            outcome = row.status
        outcome_item = {
            "signal_id": row.signal_id,
            "outreach_id": outreach.outreach_id if outreach else None,
            "status": outcome,
            "error": error,
        }
        outcomes.append(outcome_item)
        audit(
            db,
            actor="growth-worker",
            action="growth_public_land_transient_block_signal_promoted",
            entity_type="growth_signal",
            entity_id=row.signal_id,
            before=before,
            after={
                **outcome_item,
                "eligible_transient_reasons": sorted(PUBLIC_LAND_TRANSIENT_QUEUE_REASONS),
                "persisted_source_evidence_manifest_sha256": evidence_manifest_sha256,
                "suppression_rechecked": True,
                "recipient_cooldown_rechecked": True,
                "hard_gates_rechecked": True,
                "canonical_template_and_release_recreated": outreach is not None,
            },
        )
    summary = {
        "status": "applied",
        "selected_count": len(rows),
        "queued": sum(item["status"] == "queued" for item in outcomes),
        "blocked": sum(item["status"] == "blocked" for item in outcomes),
        "suppressed": sum(item["status"] == "suppressed" for item in outcomes),
        "idempotent": False,
        "outcomes": outcomes,
    }
    audit(
        db,
        actor="growth-worker",
        action="growth_public_land_transient_block_promotion_applied",
        entity_type="growth_public_land_transient_block_promotion",
        entity_id=f"{utcnow().date().isoformat()}:{sha(summary)[:32]}",
        before={"selected_count": len(rows), "queued": 0},
        after=summary,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise GrowthRegistryError("public_land_transient_promotion_concurrent_conflict") from exc
    return summary


def promote_public_land_name_fallback_signals(
    db: Session,
    *,
    policy_version: str,
    max_rows: int,
    apply: bool,
    expected_plan_sha256: str | None,
    reason: str,
    actor: str,
    automatic: bool = False,
) -> dict[str, Any]:
    """Queue old name-only blocked listings through the unchanged guarded path.

    The plan contains hashes and database identifiers only. Applying it never
    dispatches mail; it re-runs sender, suppression, cooldown, hard-exclusion,
    evidence-manifest and immutable-template gates before creating step zero.
    """

    if policy_version != LAND_RENDER_RECIPIENT_NAME_POLICY_VERSION:
        raise GrowthRegistryError("public_land_name_fallback_policy_version_invalid")
    if max_rows < 1 or max_rows > 100:
        raise GrowthRegistryError("public_land_name_fallback_limit_invalid")
    if len(reason.strip()) < 10:
        raise GrowthRegistryError("public_land_name_fallback_reason_required")
    if apply and not automatic and not expected_plan_sha256:
        raise GrowthRegistryError("public_land_name_fallback_preview_hash_required")
    if not apply and expected_plan_sha256:
        raise GrowthRegistryError("public_land_name_fallback_dry_run_hash_forbidden")
    if apply and not writes_unlocked():
        raise GrowthRegistryError("growth_writes_locked")

    name_only_reason = canonical_json(["template-variable-missing:recipient_name"])
    filters = (
        GrowthSignal.status == "template-variable-missing",
        GrowthSignal.rejection_reasons_json == name_only_reason,
        GrowthSignal.signal_type == "residential_building_plot",
        GrowthSignal.contact_basis == "public_property_listing",
        GrowthSignal.recipient_role.in_(tuple(LAND_RECIPIENT_TYPES_BY_ROLE)),
        GrowthSignal.recipient_email.is_not(None),
        GrowthSignal.recipient_email_type.in_(("role", "named", "unknown")),
        GrowthSignal.company_name.is_(None),
        GrowthSignal.public_contact_url.is_not(None),
        GrowthSignal.public_contact_url == GrowthSignal.evidence_url,
        or_(
            GrowthSignal.recipient_role == "listing_agent",
            and_(
                GrowthSignal.recipient_role == "property_owner",
                GrowthSignal.location.is_not(None),
                GrowthSignal.plot_size_sqm.is_not(None),
            ),
        ),
        GrowthSignal.signal_id.not_in(
            select(OutreachMessage.signal_id).where(OutreachMessage.sequence_step == 0)
        ),
    )
    total_matching = int(
        db.scalar(select(func.count()).select_from(GrowthSignal).where(*filters)) or 0
    )
    row_query = select(GrowthSignal).where(*filters).order_by(GrowthSignal.id).limit(max_rows)
    if apply:
        row_query = row_query.with_for_update()
    rows = [row for row in db.scalars(row_query) if _control_enabled(db, row.motor_key)]
    plan_items = [
        {
            "signal_id": row.signal_id,
            "source_id": row.source_id,
            "source_payload_hash": row.source_payload_hash,
            "recipient_role": row.recipient_role,
            "recipient_email_sha256": hashlib.sha256(
                str(row.recipient_email or "").strip().casefold().encode("utf-8")
            ).hexdigest(),
            "source_evidence_manifest_sha256": _persisted_source_evidence_manifest_sha256(
                db, row.signal_id
            ),
        }
        for row in rows
    ]
    plan = {
        "policy_version": policy_version,
        "selected_count": len(plan_items),
        "total_matching": total_matching,
        "truncated": total_matching > len(rows),
        "items": plan_items,
    }
    plan_sha256 = sha(plan)
    result = {
        "status": "preview" if not apply else "applied",
        "apply": apply,
        "automatic": automatic,
        "idempotent": not rows,
        "plan_sha256": plan_sha256,
        **plan,
    }
    if not apply or not rows:
        return result
    if not automatic and expected_plan_sha256 != plan_sha256:
        raise GrowthRegistryError("public_land_name_fallback_plan_changed")

    audit_entity_id = f"{policy_version}:{plan_sha256[:32]}"
    existing_audit = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "growth_public_land_name_fallback_promotion_applied",
            AuditLog.entity_type == "growth_public_land_name_fallback_policy",
            AuditLog.entity_id == audit_entity_id,
        )
        .order_by(AuditLog.id.desc())
    )
    if existing_audit is not None:
        return {
            **result,
            "status": "already_applied",
            "idempotent": True,
            "audit_log_id": existing_audit.id,
        }

    registry = GrowthRegistry.load()
    outcomes: list[dict[str, Any]] = []
    for row, plan_item in zip(rows, plan_items, strict=True):
        before = {
            "status": row.status,
            "reasons": json.loads(row.rejection_reasons_json or "[]"),
        }
        outreach: OutreachMessage | None = None
        try:
            data = _public_land_name_fallback_signal_input(row)
            source_evidence = _persisted_source_evidence(db, row.signal_id)
            if any(item["field_name"] == "recipient_name" for item in source_evidence):
                raise GrowthRegistryError("public_land_name_fallback_evidence_conflict")
            validated_evidence = _validated_source_evidence(data, source_evidence)
            template_evidence_fields = {
                "location",
                "plot_size_sqm",
            } if row.recipient_role == "property_owner" else set()
            evidenced_fields = {str(item["field_name"]) for item in validated_evidence}
            missing_template_fields = sorted(template_evidence_fields - evidenced_fields)
            if missing_template_fields:
                raise GrowthRegistryError(
                    "template-variable-missing:" + ",".join(missing_template_fields)
                )
            binding = registry.brand_binding(row.brand_id)
            _verified_sender(db, binding)
            outreach = _queue_message(
                db,
                row,
                binding,
                step=0,
                available_at=utcnow(),
                enforce_recipient_cooldown=True,
                data=data,
                source_evidence_manifest_sha256=_source_evidence_manifest_sha256(
                    validated_evidence
                ),
            )
            row.status = "queued"
            row.rejection_reasons_json = "[]"
            outcome = "queued"
            error = None
        except (GrowthRegistryError, ValueError) as exc:
            error = str(exc)
            render_missing_prefix = "Canonical render field is missing: "
            if error.startswith(render_missing_prefix):
                error = "template-variable-missing:" + error.removeprefix(
                    render_missing_prefix
                )
            row.status = "suppressed" if "suppressed" in error else "blocked"
            row.rejection_reasons_json = canonical_json([error])
            outcome = row.status
        outcome_item = {
            "signal_id": row.signal_id,
            "outreach_id": outreach.outreach_id if outreach else None,
            "status": outcome,
            "error": error,
        }
        outcomes.append(outcome_item)
        audit(
            db,
            actor=actor,
            action="growth_public_land_name_fallback_signal_promoted",
            entity_type="growth_signal",
            entity_id=row.signal_id,
            before=before,
            after={
                **outcome_item,
                "policy_version": policy_version,
                "plan_sha256": plan_sha256,
                "recipient_role": row.recipient_role,
                "render_recipient_name": LAND_RENDER_RECIPIENT_NAME_BY_ROLE[
                    row.recipient_role
                ],
                "render_recipient_name_origin": "ROLE_FALLBACK",
                "source_evidence_manifest_sha256": plan_item[
                    "source_evidence_manifest_sha256"
                ],
            },
        )
    summary = {
        **result,
        "reason": reason.strip(),
        "queued": sum(item["status"] == "queued" for item in outcomes),
        "suppressed": sum(item["status"] == "suppressed" for item in outcomes),
        "blocked": sum(item["status"] == "blocked" for item in outcomes),
        "outcomes": outcomes,
    }
    audit(
        db,
        actor=actor,
        action="growth_public_land_name_fallback_promotion_applied",
        entity_type="growth_public_land_name_fallback_policy",
        entity_id=audit_entity_id,
        before={"template_variable_missing": len(rows), "queued": 0},
        after=summary,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise GrowthRegistryError("public_land_name_fallback_concurrent_conflict") from exc
    recorded_audit = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "growth_public_land_name_fallback_promotion_applied",
            AuditLog.entity_type == "growth_public_land_name_fallback_policy",
            AuditLog.entity_id == audit_entity_id,
        )
        .order_by(AuditLog.id.desc())
    )
    return {
        **summary,
        "audit_log_id": recorded_audit.id if recorded_audit else None,
    }


def automatic_public_land_name_fallback_promotion(db: Session) -> dict[str, Any]:
    if not settings().enabled:
        return {"status": "disabled", "queued": 0}
    if not writes_unlocked():
        return {"status": "writes_locked", "queued": 0}
    return promote_public_land_name_fallback_signals(
        db,
        policy_version=LAND_RENDER_RECIPIENT_NAME_POLICY_VERSION,
        max_rows=50,
        apply=True,
        expected_plan_sha256=None,
        reason="Daily automatic promotion of legacy name-only public listing blocks",
        actor="growth-worker",
        automatic=True,
    )


def run_motor(db: Session, motor_key: str, *, scheduled_for: datetime | None = None) -> GrowthRun:
    registry = GrowthRegistry.load()
    if motor_key not in registry.motors:
        raise KeyError(motor_key)
    run = GrowthRun(
        run_id=f"GRUN-{uuid4().hex[:20].upper()}",
        motor_key=motor_key,
        scheduled_for=scheduled_for or utcnow(),
        status="running",
    )
    db.add(run)
    db.commit()
    if not settings().enabled or not _control_enabled(db, motor_key):
        run.status = "disabled"
        run.completed_at = utcnow()
        db.commit()
        return run
    source_results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    limit = int(registry.motors[motor_key]["max_raw_signals_per_run"])
    remaining = limit
    for source_id, source in registry.sources_for(motor_key):
        if remaining <= 0:
            break
        run.attempted_sources += 1
        try:
            batch = fetch_source(source_id, source, limit=remaining)
            run.succeeded_sources += 1
            run.raw_signals += batch.raw_count
            accepted = queued = hard_gate_blocked = 0
            for signal in batch.signals:
                try:
                    receipt = ingest_signal(db, signal, run_id=run.run_id)
                except GrowthRegistryError as exc:
                    if not _is_recipient_hard_gate_error(exc):
                        raise
                    hard_gate_blocked += 1
                    continue
                accepted += receipt.status in {"accepted", "queued", "contacted"}
                queued += bool(receipt.outreach_id and not receipt.idempotent)
            run.accepted_signals += accepted
            run.queued_outreach += queued
            remaining -= batch.raw_count
            source_results.append(
                {
                    "source_id": source_id,
                    "status": "ok",
                    "raw": batch.raw_count,
                    "schema_rejected": batch.rejected_count,
                    "hard_gate_blocked": hard_gate_blocked,
                    "accepted": accepted,
                    "queued": queued,
                }
            )
        except (SourceError, GrowthRegistryError, ValueError) as exc:
            errors.append({"source_id": source_id, "error_type": type(exc).__name__})
            source_results.append(
                {"source_id": source_id, "status": "failed", "error_type": type(exc).__name__}
            )
    run.status = "completed" if not errors else "partial" if run.succeeded_sources else "failed"
    run.source_results_json = canonical_json(source_results)
    run.error_json = canonical_json(errors)
    run.completed_at = utcnow()
    audit(
        db,
        actor="growth-worker",
        action="growth_motor_run_completed",
        entity_type="growth_run",
        entity_id=run.run_id,
        after={
            "motor_key": motor_key,
            "status": run.status,
            "attempted": run.attempted_sources,
            "succeeded": run.succeeded_sources,
            "raw": run.raw_signals,
            "accepted": run.accepted_signals,
            "queued": run.queued_outreach,
        },
    )
    db.commit()
    return run


def run_due_motors(db: Session) -> list[GrowthRun]:
    if not settings().enabled:
        return []
    registry = GrowthRegistry.load()
    now = utcnow()
    result: list[GrowthRun] = []
    for motor_key, config in sorted(registry.motors.items()):
        last = db.scalar(
            select(GrowthRun)
            .where(GrowthRun.motor_key == motor_key)
            .order_by(GrowthRun.started_at.desc())
            .limit(1)
        )
        if _motor_is_due(now, last, config):
            result.append(run_motor(db, motor_key, scheduled_for=now))
    return result


def _motor_is_due(now: datetime, last: GrowthRun | None, config: dict[str, Any]) -> bool:
    if config.get("interval_minutes"):
        interval = timedelta(minutes=int(config["interval_minutes"]))
        return not last or now - _aware(last.started_at) >= interval
    try:
        zone = ZoneInfo(settings().timezone)
    except ZoneInfoNotFoundError as exc:
        raise GrowthRegistryError("Configured growth timezone is unavailable") from exc
    local_now = now.astimezone(zone)
    hour, minute = (int(part) for part in str(config["daily_at"]).split(":"))
    scheduled_local = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local_now < scheduled_local:
        return False
    if not last:
        return True
    return _aware(last.started_at).astimezone(zone).date() < local_now.date()


def _release_expired_claims(db: Session) -> None:
    now = utcnow()
    for row in db.scalars(
        select(OutreachMessage).where(
            OutreachMessage.status == "claimed",
            OutreachMessage.lease_expires_at.is_not(None),
            OutreachMessage.lease_expires_at <= now,
        )
    ).all():
        if not _delivery_verification_pending(row):
            try:
                receipt = json.loads(row.receipt_json or "{}")
            except (TypeError, json.JSONDecodeError):
                receipt = {}
            receipt["delivery_verification"] = {
                "status": "pending_verification",
                "retry_safe": False,
                "provider_message_id": row.provider_message_id,
                "reserved_at": now.isoformat(),
                "detail": {"reason": "worker_lease_expired_delivery_ambiguous"},
            }
            row.receipt_json = canonical_json(receipt)
            audit(
                db,
                actor="growth-worker",
                action="growth_outreach_delivery_pending_verification",
                entity_type="growth_outreach",
                entity_id=row.outreach_id,
                after={
                    "provider_message_id": row.provider_message_id,
                    "reason": "worker_lease_expired_delivery_ambiguous",
                    "retry_safe": False,
                },
            )
        # A worker may have died after Gmail accepted the POST but before the
        # provider id/readback could be committed. Gmail search is useful for
        # later recovery, but is not a safe automatic retry boundary because
        # SENT search visibility can lag. Keep every ambiguous claim held.
        row.status = "claimed"
        row.claimed_by = None
        row.lease_expires_at = None
        row.last_error = "delivery_ambiguous_pending_verification"


def _preclaim_outreach_readiness_reason(
    db: Session,
    registry: GrowthRegistry,
    row: OutreachMessage,
) -> str | None:
    signal = db.scalar(select(GrowthSignal).where(GrowthSignal.signal_id == row.signal_id))
    if signal is None:
        return "growth_signal_missing"
    reason = _authoritative_send_readiness_reason(db, registry, signal)
    if reason:
        return reason
    try:
        binding = registry.brand_binding(row.brand_id)
        _verified_sender(db, binding)
    except GrowthRegistryError as exc:
        return str(exc)
    if binding.sender_email != row.sender_email:
        return "brand_sender_changed_after_queue"
    return None


def _lock_outreach_claim_capacity(db: Session) -> None:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": OUTREACH_CAPACITY_ADVISORY_LOCK_KEY},
        )
    elif dialect == "sqlite":
        db.commit()
        db.execute(text("BEGIN IMMEDIATE"))


def _lock_outreach_transport_account(db: Session) -> None:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": OUTREACH_TRANSPORT_ADVISORY_LOCK_KEY},
        )
    elif dialect != "sqlite":
        raise GrowthRegistryError("gmail_account_transport_lock_unavailable_no_send")


@dataclass(frozen=True)
class OutreachCapacityUsage:
    rolling_24h_verified: int
    previous_24h_verified: int
    active_claimed: int
    pending_verification: int
    ready_queued: int
    last_verified_at: datetime | None


@dataclass(frozen=True)
class OutreachBudapestDayUsage:
    day_start: datetime
    day_end: datetime
    observed_at: datetime
    limit: int
    sent_first_contacts: int
    verified_first_contacts: int
    active_claim_reservations: int
    pending_verification_reservations: int
    ready_queued: int
    reservation_keys: frozenset[str]

    @property
    def effective_reserved_count(self) -> int:
        return self.sent_first_contacts + len(self.reservation_keys)

    @property
    def planned_count(self) -> int:
        return self.effective_reserved_count + self.ready_queued


@dataclass(frozen=True)
class OutreachReputationHealth:
    verified_sent: int
    bounced: int
    complained: int
    bounce_rate: float
    complaint_rate: float
    action: str

    @property
    def pacing_multiplier(self) -> float:
        if self.bounced <= 0 and self.complained <= 0:
            return 1.0
        return min(
            4.0,
            1.0 + self.bounce_rate * 20.0 + self.complaint_rate * 200.0,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_hours": 24,
            "verified_sent": self.verified_sent,
            "bounced": self.bounced,
            "complained": self.complained,
            "bounce_rate": self.bounce_rate,
            "complaint_rate": self.complaint_rate,
            "action": self.action,
            "pacing_multiplier": self.pacing_multiplier,
            "complaint_stop_rate": OUTREACH_COMPLAINT_STOP_RATE,
            "bounce_stop_rate": OUTREACH_BOUNCE_STOP_RATE,
            "bounce_stop_minimum": OUTREACH_BOUNCE_STOP_MINIMUM,
        }


def _outreach_capacity_usage(db: Session, now: datetime | None = None) -> OutreachCapacityUsage:
    current = _aware(now or utcnow())
    rolling_start = current - timedelta(hours=24)
    previous_start = current - timedelta(hours=48)
    sent_rows = db.scalars(
        select(OutreachMessage).where(
            OutreachMessage.sent_at >= previous_start,
            OutreachMessage.sent_at <= current,
        )
    ).all()
    verified_rows = [row for row in sent_rows if _gmail_sent_mime_verified(row)]
    rolling_rows = [row for row in verified_rows if _aware(row.sent_at) > rolling_start]
    previous_rows = [
        row
        for row in verified_rows
        if previous_start < _aware(row.sent_at) <= rolling_start
    ]
    claimed_rows = list(
        db.scalars(select(OutreachMessage).where(OutreachMessage.status == "claimed"))
    )
    pending_rows = [row for row in claimed_rows if _delivery_verification_pending(row)]
    active_rows = [
        row
        for row in claimed_rows
        if row.claimed_by is not None
        and row.lease_expires_at is not None
        and _aware(row.lease_expires_at) > current
        and row not in pending_rows
    ]
    ready_queued = int(
        db.scalar(
            select(func.count())
            .select_from(OutreachMessage)
            .where(
                OutreachMessage.status == "queued",
                OutreachMessage.available_at <= current,
            )
        )
        or 0
    )
    return OutreachCapacityUsage(
        rolling_24h_verified=len(rolling_rows),
        previous_24h_verified=len(previous_rows),
        active_claimed=len(active_rows),
        pending_verification=len(pending_rows),
        ready_queued=ready_queued,
        last_verified_at=max((_aware(row.sent_at) for row in rolling_rows), default=None),
    )


def _outreach_reputation_health(
    db: Session, now: datetime | None = None
) -> OutreachReputationHealth:
    current = _aware(now or utcnow())
    cutoff = current - timedelta(hours=24)
    rows = db.scalars(
        select(OutreachMessage).where(OutreachMessage.sent_at >= cutoff)
    ).all()
    verified = [row for row in rows if _gmail_sent_mime_verified(row)]
    sent_count = len(verified)
    bounced = sum(row.status == "bounced" for row in verified)
    complained = sum(row.status == "complained" for row in verified)
    denominator = max(1, sent_count)
    bounce_rate = bounced / denominator
    complaint_rate = complained / denominator
    if complained and complaint_rate >= OUTREACH_COMPLAINT_STOP_RATE:
        action = "pause_external_outreach"
    elif (
        bounced >= OUTREACH_BOUNCE_STOP_MINIMUM
        and bounce_rate >= OUTREACH_BOUNCE_STOP_RATE
    ):
        action = "pause_external_outreach"
    elif bounced or complained:
        action = "slow_external_outreach"
    else:
        action = "healthy"
    return OutreachReputationHealth(
        verified_sent=sent_count,
        bounced=bounced,
        complained=complained,
        bounce_rate=bounce_rate,
        complaint_rate=complaint_rate,
        action=action,
    )


def _assert_outreach_reputation_healthy(
    db: Session, now: datetime | None = None
) -> dict[str, Any]:
    health = _outreach_reputation_health(db, now)
    detail = health.as_dict()
    if health.action == "pause_external_outreach":
        raise EmailDeliveryError(
            "gmail_account_reputation_degraded_no_send",
            retry_safe=True,
            rate_limited=True,
            retry_after_seconds=3600,
            detail=detail,
        )
    return detail


def _outreach_window_seconds(config: Any) -> float:
    try:
        start = time.fromisoformat(str(config.outreach_send_start_local))
        end = time.fromisoformat(str(config.outreach_send_end_local))
    except ValueError as exc:
        raise GrowthRegistryError("Configured outreach sending window is invalid") from exc
    start_seconds = start.hour * 3600 + start.minute * 60 + start.second
    end_seconds = end.hour * 3600 + end.minute * 60 + end.second
    if start_seconds == end_seconds:
        return float(timedelta(days=1).total_seconds())
    if start_seconds > end_seconds:
        raise GrowthRegistryError("Outreach sending window must start before it ends")
    return float(end_seconds - start_seconds)


def _outreach_reputation_gap_seconds(
    usage: OutreachCapacityUsage,
    *,
    now: datetime | None = None,
    penalty_multiplier: float = 1.0,
) -> float:
    config = settings()
    absolute_limit = int(getattr(config, "outreach_budapest_day_max", 2000))
    bootstrap = int(
        getattr(config, "outreach_reputation_bootstrap_messages_per_window", 100)
    )
    growth_factor = float(
        getattr(config, "outreach_reputation_max_growth_factor", 1.25)
    )
    jitter_fraction = float(getattr(config, "outreach_reputation_jitter_fraction", 0.20))
    if not 1 <= absolute_limit <= 2000 or int(getattr(config, "outreach_send_concurrency", 1)) != 1:
        raise GrowthRegistryError("outreach_transport_policy_invalid_no_send")
    # Upward-only jitter deliberately sends fewer than the nominal target.
    # Qualify a healthy window against the worst-case achievable volume so
    # the warm-up can progress instead of becoming a permanent ~90/day cap.
    ramp_threshold = max(1, math.ceil(bootstrap / (1.0 + jitter_fraction)))
    if usage.previous_24h_verified >= ramp_threshold:
        paced_volume = min(
            absolute_limit,
            max(bootstrap, int(usage.previous_24h_verified * growth_factor)),
        )
    else:
        paced_volume = min(absolute_limit, bootstrap)
    window_seconds = _outreach_window_seconds(config)
    transport_floor = window_seconds / absolute_limit
    reputation_gap = window_seconds / max(1, paced_volume)
    current = _aware(now or utcnow())
    seed = hashlib.sha256(
        (
            f"{current.date().isoformat()}:{usage.rolling_24h_verified}:"
            f"{usage.previous_24h_verified}"
        ).encode()
    ).digest()
    unit = int.from_bytes(seed[:8], "big") / float(2**64 - 1)
    # Jitter may spread traffic later, but must never shorten the reputation
    # gap and silently exceed the configured +25% healthy-growth ceiling.
    jitter = 1.0 + unit * jitter_fraction
    return max(transport_floor, reputation_gap * jitter) * max(1.0, penalty_multiplier)


def _outreach_pacing_detail(db: Session, *, lock: bool = False) -> dict[str, Any]:
    query = select(GrowthControlState).where(
        GrowthControlState.key == OUTREACH_PACING_STATE_KEY
    )
    if lock:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None or not row.reason:
        return {}
    try:
        detail = json.loads(row.reason)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GrowthRegistryError("outreach_pacing_state_invalid_no_send") from exc
    if not isinstance(detail, dict):
        raise GrowthRegistryError("outreach_pacing_state_invalid_no_send")
    return detail


def _outreach_pacing_next_at(db: Session) -> datetime | None:
    raw = _outreach_pacing_detail(db).get("next_send_not_before")
    if not raw:
        return None
    try:
        return _aware(datetime.fromisoformat(str(raw)))
    except ValueError as exc:
        raise GrowthRegistryError("outreach_pacing_state_invalid_no_send") from exc


def _assert_gmail_account_pacing_due(
    db: Session, *, now: datetime | None = None
) -> None:
    current = _aware(now or utcnow())
    next_at = _outreach_pacing_next_at(db)
    if next_at is None or current >= next_at:
        return
    retry_after = max(1.0, (next_at - current).total_seconds())
    raise EmailDeliveryError(
        "gmail_account_pacing_not_due_no_send",
        retry_safe=True,
        retry_after_seconds=retry_after,
        detail={
            "next_send_not_before": next_at.isoformat(),
            "retry_after_seconds": retry_after,
        },
    )


def _write_outreach_pacing_state(db: Session, detail: dict[str, Any]) -> None:
    row = db.scalar(
        select(GrowthControlState)
        .where(GrowthControlState.key == OUTREACH_PACING_STATE_KEY)
        .with_for_update()
    )
    if row is None:
        row = GrowthControlState(key=OUTREACH_PACING_STATE_KEY)
        db.add(row)
    row.enabled = True
    row.reason = canonical_json(detail)
    row.changed_by = "growth-worker-pacing"
    row.changed_at = utcnow()


def _record_outreach_pacing_success(db: Session, *, now: datetime) -> None:
    current = _aware(now)
    usage = _outreach_capacity_usage(db, current)
    health = _outreach_reputation_health(db, current)
    prior = _outreach_pacing_detail(db, lock=True)
    penalty = max(
        health.pacing_multiplier,
        float(prior.get("penalty_multiplier") or 1.0) * 0.95,
    )
    gap = _outreach_reputation_gap_seconds(
        usage,
        now=current,
        penalty_multiplier=penalty,
    )
    _write_outreach_pacing_state(
        db,
        {
            "next_send_not_before": (current + timedelta(seconds=gap)).isoformat(),
            "penalty_multiplier": penalty,
            "last_success_at": current.isoformat(),
            "last_error": None,
            "gap_seconds": gap,
            "rolling_24h_verified": usage.rolling_24h_verified,
            "previous_24h_verified": usage.previous_24h_verified,
            "reputation_health": health.as_dict(),
        },
    )


def _record_outreach_pacing_backoff(
    db: Session,
    *,
    error: EmailDeliveryError,
    now: datetime,
) -> datetime:
    current = _aware(now)
    prior = _outreach_pacing_detail(db, lock=True)
    previous_penalty = max(1.0, float(prior.get("penalty_multiplier") or 1.0))
    penalty = (
        min(64.0, previous_penalty * 2.0)
        if error.rate_limited
        else previous_penalty
    )
    retry_after = error.retry_after_seconds
    if retry_after is None:
        retry_after = error.detail.get("retry_after_seconds")
    try:
        retry_seconds = max(1.0, float(retry_after))
    except (TypeError, ValueError):
        retry_seconds = min(900.0, max(15.0, penalty))
    next_at = current + timedelta(seconds=retry_seconds)
    if error.rate_limited:
        usage = _outreach_capacity_usage(db, current)
        next_at = max(
            next_at,
            current
            + timedelta(
                seconds=_outreach_reputation_gap_seconds(
                    usage,
                    now=current,
                    penalty_multiplier=penalty,
                )
            ),
        )
    existing_raw = prior.get("next_send_not_before")
    if existing_raw:
        try:
            next_at = max(next_at, _aware(datetime.fromisoformat(str(existing_raw))))
        except ValueError as exc:
            raise GrowthRegistryError("outreach_pacing_state_invalid_no_send") from exc
    _write_outreach_pacing_state(
        db,
        {
            **prior,
            "next_send_not_before": next_at.isoformat(),
            "penalty_multiplier": penalty,
            "last_error": error.error_type,
            "last_error_at": current.isoformat(),
        },
    )
    return next_at


def _budapest_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = _aware(now or utcnow())
    try:
        zone = ZoneInfo("Europe/Budapest")
    except ZoneInfoNotFoundError as exc:
        raise GrowthRegistryError("outreach_budapest_timezone_unavailable_no_send") from exc
    local_date = current.astimezone(zone).date()
    day_start = datetime.combine(local_date, time.min, tzinfo=zone).astimezone(UTC)
    day_end = datetime.combine(
        local_date + timedelta(days=1), time.min, tzinfo=zone
    ).astimezone(UTC)
    return day_start, day_end


def _outreach_budapest_day_usage(
    db: Session, now: datetime | None = None
) -> OutreachBudapestDayUsage:
    current = _aware(now or utcnow())
    day_start, day_end = _budapest_day_bounds(current)
    limit = int(getattr(settings(), "outreach_budapest_day_max", 2000))
    if limit != 2000:
        raise GrowthRegistryError("outreach_budapest_day_max_invalid_no_send")

    sent_rows = db.scalars(
        select(OutreachMessage).where(
            OutreachMessage.sequence_step == 0,
            OutreachMessage.sent_at >= day_start,
            OutreachMessage.sent_at < day_end,
        )
    ).all()
    # A sent_at row is a conservative quota consumer even if historic data is
    # missing readback fields. Production only writes sent_at after full Gmail
    # SENT/MIME verification; counting every such row prevents an undercount if
    # that invariant was violated by an older release.
    sent_first_contacts = len(sent_rows)
    verified_first_contacts = sum(_gmail_sent_mime_verified(row) for row in sent_rows)

    reservation_keys: set[str] = set()
    active_claims = 0
    pending_verification = 0
    for reserved in db.scalars(
        select(OutreachMessage).where(
            OutreachMessage.sequence_step == 0,
            OutreachMessage.status == "claimed",
        )
    ):
        # A crash can leave the business row claimed after sent_at was already
        # durably written. That identity is already in sent_rows and must not
        # consume a second slot as a reservation.
        if reserved.sent_at is not None:
            continue
        is_pending = _delivery_verification_pending(reserved) or (
            _delivery_acceptance_ambiguous(reserved)
            and reserved.lease_expires_at is None
        )
        is_active = bool(
            reserved.claimed_by
            and reserved.lease_expires_at
            and _aware(reserved.lease_expires_at) > current
        )
        if is_pending:
            reservation_at = _claimed_reservation_at(reserved)
            if (
                reservation_at is None
                or reservation_at < day_start
                or reservation_at >= day_end
            ):
                continue
        elif not is_active:
            continue
        reservation_keys.add(f"outreach:{reserved.outreach_id}")
        pending_verification += int(is_pending)
        active_claims += int(is_active and not is_pending)

    ready_queued = int(
        db.scalar(
            select(func.count())
            .select_from(OutreachMessage)
            .where(
                OutreachMessage.sequence_step == 0,
                OutreachMessage.status == "queued",
                OutreachMessage.available_at < day_end,
            )
        )
        or 0
    )
    return OutreachBudapestDayUsage(
        day_start=day_start,
        day_end=day_end,
        observed_at=current,
        limit=limit,
        sent_first_contacts=sent_first_contacts,
        verified_first_contacts=verified_first_contacts,
        active_claim_reservations=active_claims,
        pending_verification_reservations=pending_verification,
        ready_queued=ready_queued,
        reservation_keys=frozenset(reservation_keys),
    )


def _assert_outreach_budapest_day_quota_reserved(
    db: Session,
    row: OutreachMessage,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    usage = _outreach_budapest_day_usage(db, now)
    current_reservation_key = f"outreach:{row.outreach_id}"
    if current_reservation_key not in usage.reservation_keys:
        raise GrowthRegistryError("outreach_current_reservation_missing_no_send")
    if usage.effective_reserved_count > usage.limit:
        retry_after = max(60.0, (usage.day_end - usage.observed_at).total_seconds())
        raise EmailDeliveryError(
            "outreach_budapest_day_limit_reached_no_send",
            retry_safe=True,
            retry_after_seconds=retry_after,
            detail={
                "sent_first_contacts": usage.sent_first_contacts,
                "verified_first_contacts": usage.verified_first_contacts,
                "active_claim_reservations": usage.active_claim_reservations,
                "pending_verification_reservations": (
                    usage.pending_verification_reservations
                ),
                "effective_reserved_count": usage.effective_reserved_count,
                "limit": usage.limit,
                "day_start": usage.day_start.isoformat(),
                "day_end": usage.day_end.isoformat(),
                "retry_after_seconds": retry_after,
            },
        )
    return {
        "observed_at": usage.observed_at.isoformat(),
        "timezone": "Europe/Budapest",
        "day_start": usage.day_start.isoformat(),
        "day_end": usage.day_end.isoformat(),
        "sent_first_contacts": usage.sent_first_contacts,
        "verified_first_contacts": usage.verified_first_contacts,
        "active_claim_reservations": usage.active_claim_reservations,
        "pending_verification_reservations": usage.pending_verification_reservations,
        "effective_reserved_count": usage.effective_reserved_count,
        "ready_queued_for_capacity_planning": usage.ready_queued,
        "planned_count": usage.planned_count,
        "limit": usage.limit,
    }


def _outreach_transport_capacity_reserved(
    db: Session, row: OutreachMessage, now: datetime | None = None
) -> bool:
    current = _aware(now or utcnow())
    if (
        row.status != "claimed"
        or row.claimed_by != settings().worker_id
        or row.lease_expires_at is None
        or _aware(row.lease_expires_at) <= current
        or _delivery_verification_pending(row)
    ):
        return False
    active_claimed_ids = {
        candidate.outreach_id
        for candidate in db.scalars(
            select(OutreachMessage).where(
                OutreachMessage.status == "claimed",
                OutreachMessage.claimed_by.is_not(None),
                OutreachMessage.lease_expires_at.is_not(None),
                OutreachMessage.lease_expires_at > current,
            )
        )
        if not _delivery_verification_pending(candidate)
    }
    return active_claimed_ids == {row.outreach_id}


def claim_outreach(db: Session) -> OutreachMessage | None:
    if not _outreach_sending_window_open():
        return None
    _release_expired_claims(db)
    now = utcnow()
    _lock_outreach_claim_capacity(db)
    try:
        registry = GrowthRegistry.load()
    except GrowthRegistryError:
        db.commit()
        return None
    readiness_state = _outbound_send_readiness_state(db, registry)
    if readiness_state.get("ready") is not True:
        db.commit()
        return None
    if _outreach_send_capacity(db, now) <= 0:
        db.commit()
        return None
    query = (
        select(OutreachMessage)
        .outerjoin(GrowthSignal, GrowthSignal.signal_id == OutreachMessage.signal_id)
        .where(
            OutreachMessage.status == "queued",
            OutreachMessage.available_at <= now,
            OutreachMessage.attempt_count < OutreachMessage.max_attempts,
        )
    )
    if (
        readiness_state.get("canary_active") is True
        or int(readiness_state.get("scheduled_enabled_sources") or 0) <= 0
    ):
        query = query.where(
            GrowthSignal.signal_type == "residential_building_plot",
            GrowthSignal.contact_basis == "public_property_listing",
            GrowthSignal.recipient_role.in_(tuple(LAND_RECIPIENT_TYPES_BY_ROLE)),
            GrowthSignal.public_contact_url.is_not(None),
            GrowthSignal.public_contact_url == GrowthSignal.evidence_url,
        )
    candidates = db.scalars(
        query.order_by(OutreachMessage.available_at, OutreachMessage.id).with_for_update(
            skip_locked=True,
            of=OutreachMessage,
        )
    ).all()
    row = candidates[0] if candidates else None
    if not row:
        db.commit()
        return None
    if _preclaim_outreach_readiness_reason(db, registry, row):
        db.commit()
        return None
    row.status = "claimed"
    row.claimed_by = settings().worker_id
    row.claimed_at = now
    row.lease_expires_at = now + timedelta(seconds=settings().lease_seconds)
    row.attempt_count += 1
    row.last_error = None
    db.commit()
    return row


def _canonical_metadata(row: OutreachMessage) -> dict[str, Any]:
    try:
        receipt = json.loads(row.receipt_json or "{}")
    except json.JSONDecodeError as exc:
        raise GrowthRegistryError("canonical_outreach_metadata_unreadable") from exc
    metadata = receipt.get("canonical_template")
    if not isinstance(metadata, dict):
        raise GrowthRegistryError("canonical_outreach_metadata_missing")
    return metadata


def _canonical_metadata_sha256(metadata: dict[str, Any]) -> str:
    return sha(metadata)


def _outreach_payload_sha256(
    *,
    sender_email: str,
    recipient_email: str,
    subject: str,
    body_text: str,
    body_html: str | None,
    idempotency_key: str,
    unsubscribe_token_hash: str,
    canonical_metadata: dict[str, Any],
) -> str:
    return sha(
        {
            "from": sender_email,
            "to": recipient_email,
            "subject": subject,
            "body": body_text,
            "body_html": body_html,
            "idempotency_key": idempotency_key,
            "unsubscribe_token_hash": unsubscribe_token_hash,
            "canonical_metadata_sha256": _canonical_metadata_sha256(canonical_metadata),
        }
    )


def _payload_matches(row: OutreachMessage) -> bool:
    metadata = _canonical_metadata(row)
    expected = _outreach_payload_sha256(
        sender_email=row.sender_email,
        recipient_email=row.recipient_email,
        subject=row.subject,
        body_text=row.body_text,
        body_html=row.body_html,
        idempotency_key=row.idempotency_key,
        unsubscribe_token_hash=row.unsubscribe_token_hash,
        canonical_metadata=metadata,
    )
    return hmac.compare_digest(row.payload_sha256, expected)


def _current_canonical_screening_values(
    signal: GrowthSignal, render_input: dict[str, Any]
) -> list[str]:
    reference_names = render_input.get("reference_names")
    if not isinstance(reference_names, list) or not all(
        isinstance(value, str) for value in reference_names
    ):
        raise GrowthRegistryError("canonical_reference_names_unreadable")
    expected = [
        render_input.get("recipient_name"),
        signal.company_name,
        signal.recipient_organization_name,
        signal.recipient_office_name,
        signal.recipient_email,
        signal.recipient_role,
        render_input.get("sender_company_name"),
        *reference_names,
        render_input.get("business_context"),
        render_input.get("business_context_evidence_url"),
        signal.summary,
        signal.evidence_url,
        signal.public_contact_url,
    ]
    return [str(value or "") for value in expected]


def _assert_current_canonical_screening(
    signal: GrowthSignal, metadata: dict[str, Any]
) -> list[str]:
    render_input = metadata.get("render_input")
    if not isinstance(render_input, dict):
        raise GrowthRegistryError("canonical_render_input_missing")
    if (
        "source_evidence_manifest_sha256" in metadata
        or "recipient_name_render_policy" in metadata
    ) and not _public_land_signal(signal):
        raise GrowthRegistryError("public_land_source_evidence_classification_mismatch")
    if _public_land_signal(signal):
        render_policy = metadata.get("recipient_name_render_policy")
        if signal.company_name:
            if render_input.get("recipient_name") != signal.company_name:
                raise GrowthRegistryError("public_land_verified_recipient_name_binding_mismatch")
            # Preserve dispatch compatibility for already-queued, verified-name
            # rows that predate the explicit render-origin receipt. Every newly
            # rendered row must carry the exact policy receipt.
            if render_policy is not None and render_policy != {
                "policy_version": LAND_RENDER_RECIPIENT_NAME_POLICY_VERSION,
                "origin": "VERIFIED_LISTING_EVIDENCE",
                "recipient_role": signal.recipient_role,
                "evidence_recipient_name_present": True,
            }:
                raise GrowthRegistryError("public_land_recipient_name_render_policy_mismatch")
        else:
            fallback = LAND_RENDER_RECIPIENT_NAME_BY_ROLE.get(signal.recipient_role)
            if (
                not fallback
                or render_input.get("recipient_name") != fallback
                or render_policy
                != {
                    "policy_version": LAND_RENDER_RECIPIENT_NAME_POLICY_VERSION,
                    "origin": "ROLE_FALLBACK",
                    "recipient_role": signal.recipient_role,
                    "evidence_recipient_name_present": False,
                }
            ):
                raise GrowthRegistryError("public_land_recipient_name_render_policy_mismatch")
    expected_values = _current_canonical_screening_values(signal, render_input)
    registry = CanonicalFirstContactRegistry.load()
    hard_gate = registry.hard_gate_match(expected_values)
    if hard_gate:
        raise GrowthRegistryError(f"canonical_hard_gate_blocked:{hard_gate}")
    if render_input.get("screening_values") != expected_values:
        raise GrowthRegistryError("canonical_screening_values_changed_after_queue")
    return expected_values


def _assert_canonical_payload(row: OutreachMessage) -> tuple[dict[str, Any], str]:
    metadata = _canonical_metadata(row)
    if metadata.get("sender_brand_id") != row.brand_id:
        raise GrowthRegistryError("canonical_sender_brand_conflicts_with_outreach")
    expected_idempotency_key = sha(
        {
            "signal_id": row.signal_id,
            "brand_id": row.brand_id,
            "step": row.sequence_step,
        }
    )
    if not hmac.compare_digest(row.idempotency_key, expected_idempotency_key):
        raise GrowthRegistryError("outreach_idempotency_key_binding_mismatch")
    render_input = metadata.get("render_input")
    if not isinstance(render_input, dict):
        raise GrowthRegistryError("canonical_render_input_missing")
    unsubscribe_url = str(render_input.get("unsubscribe_url") or "")
    try:
        parsed_unsubscribe = urlsplit(unsubscribe_url)
    except ValueError as exc:
        raise GrowthRegistryError("canonical_unsubscribe_url_binding_mismatch") from exc
    token_match = re.search(r"(?:^|/)growth/unsubscribe/([^/]+)$", parsed_unsubscribe.path)
    if (
        parsed_unsubscribe.scheme != "https"
        or not parsed_unsubscribe.hostname
        or parsed_unsubscribe.username is not None
        or parsed_unsubscribe.password is not None
        or parsed_unsubscribe.query
        or parsed_unsubscribe.fragment
        or token_match is None
    ):
        raise GrowthRegistryError("canonical_unsubscribe_url_binding_mismatch")
    expected_token_hash = hashlib.sha256(token_match.group(1).encode()).hexdigest()
    if not hmac.compare_digest(row.unsubscribe_token_hash, expected_token_hash):
        raise GrowthRegistryError("canonical_unsubscribe_token_binding_mismatch")
    expected_unsubscribe_url = f"{settings().base_url}/growth/unsubscribe/{token_match.group(1)}"
    if not hmac.compare_digest(unsubscribe_url, expected_unsubscribe_url):
        raise GrowthRegistryError("canonical_unsubscribe_origin_binding_mismatch")
    body_html = CanonicalFirstContactRegistry.load().assert_current_render(
        metadata=metadata,
        subject=row.subject,
        body_text=row.body_text,
    )
    if row.body_html != body_html:
        raise GrowthRegistryError("canonical_rendered_html_payload_mismatch")
    return metadata, body_html


def _release_digest(row: OutreachMessage, approved_by: str) -> str:
    key = platform_settings.imperial_release_hmac_key
    if len(key) < 32:
        raise GrowthRegistryError("IMPERIAL_RELEASE_HMAC_KEY is not configured")
    value = canonical_json(
        {
            "outreach_id": row.outreach_id,
            "payload_sha256": row.payload_sha256,
            "idempotency_key": row.idempotency_key,
            "unsubscribe_token_hash": row.unsubscribe_token_hash,
            "canonical_metadata_sha256": _canonical_metadata_sha256(_canonical_metadata(row)),
            "approved_by": approved_by,
        }
    )
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def release_outreach(db: Session, outreach_id: str, data: OutreachReleaseIn) -> OutreachMessage:
    row = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == outreach_id).with_for_update()
    )
    if not row:
        raise KeyError(outreach_id)
    if row.status != "queued":
        raise GrowthRegistryError("Only queued outreach can be released")
    signal = db.scalar(select(GrowthSignal).where(GrowthSignal.signal_id == row.signal_id))
    if not signal:
        raise GrowthRegistryError("Signal record is missing")
    hard_gate_reason = _land_agent_gate_reason(signal)
    if hard_gate_reason:
        raise GrowthRegistryError(hard_gate_reason)
    if not _payload_matches(row):
        raise GrowthRegistryError("outreach_payload_hash_mismatch")
    if not hmac.compare_digest(row.payload_sha256, data.inspected_payload_sha256):
        raise GrowthRegistryError("Inspected outreach payload hash does not match")
    canonical_metadata, _body_html = _assert_canonical_payload(row)
    _assert_current_canonical_screening(signal, canonical_metadata)
    row.release_approved_by = data.approved_by.strip()
    row.release_approved_at = utcnow()
    row.release_token_hash = _release_digest(row, row.release_approved_by)
    audit(
        db,
        actor=row.release_approved_by,
        action="growth_outreach_exact_payload_released",
        entity_type="growth_outreach",
        entity_id=row.outreach_id,
        after={
            "payload_sha256": row.payload_sha256,
            "approval_note_sha256": hashlib.sha256(data.approval_note.encode()).hexdigest(),
        },
    )
    db.commit()
    return row


def _release_matches(row: OutreachMessage) -> bool:
    if (
        not row.release_token_hash
        or not row.release_approved_by
        or not row.release_approved_at
        or not _payload_matches(row)
    ):
        return False
    return hmac.compare_digest(
        row.release_token_hash, _release_digest(row, row.release_approved_by)
    )


def _trip_runtime_kill_switch() -> bool:
    try:
        Path(settings().runtime_kill_switch_file).write_text("KILLED\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _persist_database_emergency_stop(db: Session, *, reason: str) -> None:
    changed_at = utcnow()
    for motor_key in sorted(GrowthRegistry.REQUIRED_MOTORS):
        key = f"motor:{motor_key}"
        row = db.get(GrowthControlState, key)
        if row is None:
            row = GrowthControlState(key=key)
            db.add(row)
        row.enabled = False
        row.reason = reason
        row.changed_by = "growth-worker-emergency-stop"
        row.changed_at = changed_at
    audit(
        db,
        actor="growth-worker-emergency-stop",
        action="growth_runtime_kill_switch_persist_failed",
        entity_type="growth_control",
        entity_id="all-motors",
        after={"reason": reason, "writes_disabled": True},
    )
    db.commit()


def _require_runtime_kill_switch(db: Session, *, reason: str) -> None:
    if _trip_runtime_kill_switch():
        return
    try:
        _persist_database_emergency_stop(db, reason=reason)
    except Exception as exc:
        _PROCESS_EMERGENCY_SEND_STOP.set()
        try:
            db.rollback()
        except Exception:
            # The process-local latch is authoritative when both durable
            # emergency stops and even transaction cleanup are unavailable.
            pass
        raise RuntimeError(
            "runtime_kill_switch_and_database_emergency_stop_failed"
        ) from exc
    raise GrowthRegistryError("runtime_kill_switch_persist_failed_emergency_db_stop")


def _delivery_verification_pending(row: OutreachMessage) -> bool:
    if row.status != "claimed" or not row.receipt_json:
        return False
    try:
        receipt = json.loads(row.receipt_json)
    except (TypeError, json.JSONDecodeError):
        return False
    verification = receipt.get("delivery_verification")
    return isinstance(verification, dict) and verification.get("status") == ("pending_verification")


def _delivery_acceptance_ambiguous(row: OutreachMessage) -> bool:
    if row.status != "claimed":
        return False
    try:
        receipt = json.loads(row.receipt_json or "{}")
    except (TypeError, json.JSONDecodeError):
        receipt = {}
    return bool(
        row.provider_message_id
        or receipt.get("accepted") is True
        or _delivery_verification_pending(row)
    )


def _claimed_reservation_at(row: OutreachMessage) -> datetime | None:
    if _delivery_acceptance_ambiguous(row):
        # Keep a stable calendar-day identity. updated_at can move during
        # reconciliation and must never shift an accepted delivery into a later
        # Budapest quota day. New rows persist the containment instant; older
        # rows conservatively fall back to their immutable claim time.
        try:
            receipt = json.loads(row.receipt_json or "{}")
        except (TypeError, json.JSONDecodeError):
            receipt = {}
        verification = receipt.get("delivery_verification")
        if isinstance(verification, dict):
            raw_reserved_at = verification.get("reserved_at")
            if raw_reserved_at:
                try:
                    return _aware(datetime.fromisoformat(str(raw_reserved_at)))
                except ValueError:
                    pass
        fallback = row.claimed_at or row.created_at or row.available_at
        return _aware(fallback) if fallback is not None else None
    if row.claimed_at is None:
        return None
    fallback = row.claimed_at
    return _aware(fallback) if fallback is not None else None


def _release_untransported_claim(
    db: Session, row: OutreachMessage, *, reason: str
) -> OutreachMessage:
    if (
        row.status == "claimed"
        and row.claimed_by == settings().worker_id
        and row.provider_message_id is None
        and not _delivery_verification_pending(row)
    ):
        row.status = "queued"
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None
        row.attempt_count = max(0, row.attempt_count - 1)
        row.last_error = reason
        db.commit()
    return row


def _official_source_validation_values(
    signal: GrowthSignal,
    canonical_metadata: dict[str, Any],
) -> dict[str, Any]:
    render_input = canonical_metadata.get("render_input")
    if not isinstance(render_input, dict):
        raise OfficialSourceEvidenceError("official_source_canonical_input_missing")
    return {
        "source_id": signal.source_id,
        "motor_key": signal.motor_key,
        "source_bucket": signal.source_bucket,
        "recipient_type": render_input.get("recipient_type"),
        "recipient_email": signal.recipient_email,
        "recipient_email_type": signal.recipient_email_type,
        "contact_basis": signal.contact_basis,
        "recipient_name": render_input.get("recipient_name"),
        "company_name": signal.company_name,
        "recipient_organization_name": signal.recipient_organization_name,
        "evidence_url": signal.evidence_url,
        "public_contact_url": signal.public_contact_url,
        "source_payload_hash": signal.source_payload_hash,
    }


def _official_source_provenance_proven(
    db: Session,
    row: OutreachMessage,
    signal: GrowthSignal,
) -> bool:
    return _official_source_binding_proof_audit(db, row, signal) is not None


def _official_source_binding_proof_payload(
    row: OutreachMessage,
    signal: GrowthSignal,
    source: dict[str, Any],
    *,
    actor: str,
    proof_origin: str,
) -> dict[str, Any]:
    return {
        "signal_id": signal.signal_id,
        "source_id": signal.source_id,
        "source_kind": source.get("kind"),
        "source_fetch_mode": source.get("fetch_mode"),
        "source_enabled": source.get("enabled"),
        "binding_sha256": source.get("binding_sha256"),
        "signal_source_payload_hash": signal.source_payload_hash,
        "recipient_email": signal.recipient_email,
        "outreach_id": row.outreach_id,
        "payload_sha256": row.payload_sha256,
        "canonical_metadata_sha256": _canonical_metadata_sha256(_canonical_metadata(row)),
        "proof_actor": actor,
        "proof_origin": proof_origin,
        "attestation_scheme": ("HMAC-SHA256:IMPERIAL_RELEASE_HMAC_KEY:official-source-binding:v1"),
        "email_sent": False,
    }


def _official_source_binding_proof_audit(
    db: Session,
    row: OutreachMessage,
    signal: GrowthSignal,
) -> AuditLog | None:
    trusted = _trusted_official_source_binding_proof_audit(db, row, signal)
    if trusted is None:
        return None
    proof, payload = trusted
    if (
        payload.get("source_id") == signal.source_id
        and payload.get("binding_sha256") == signal.source_payload_hash
        and payload.get("signal_source_payload_hash") == signal.source_payload_hash
        and payload.get("recipient_email") == signal.recipient_email
        and payload.get("payload_sha256") == row.payload_sha256
        and payload.get("canonical_metadata_sha256")
        == _canonical_metadata_sha256(_canonical_metadata(row))
    ):
        return proof
    return None


def _trusted_official_source_binding_proof_audit(
    db: Session,
    row: OutreachMessage,
    signal: GrowthSignal,
) -> tuple[AuditLog, dict[str, Any]] | None:
    if row.signal_id != signal.signal_id or row.status not in {"queued", "claimed"}:
        return None
    signal_bound = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.entity_id == signal.signal_id,
            AuditLog.action == "growth_official_source_signal_bound",
        )
        .order_by(AuditLog.id.desc())
        .limit(20)
    ).all()
    for proof in signal_bound:
        try:
            payload = json.loads(proof.after_json or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        proof_hmac = str(payload.pop("binding_proof_hmac_sha256", ""))
        proof_origin = payload.get("proof_origin")
        expected_actor = {
            "signal_ingest": "growth-ops",
            "locked_one_time_migration": "codex-owner-authorized-automation",
        }.get(str(proof_origin or ""))
        if (
            proof.entity_type == "growth_signal"
            and proof.before_json is None
            and expected_actor is not None
            and proof.actor == expected_actor
            and payload.get("proof_actor") == expected_actor
            and payload.get("attestation_scheme")
            == "HMAC-SHA256:IMPERIAL_RELEASE_HMAC_KEY:official-source-binding:v1"
            and re.fullmatch(r"[0-9a-f]{64}", proof_hmac)
            and hmac.compare_digest(
                proof_hmac,
                _official_source_receipt_hmac(payload),
            )
            and payload.get("signal_id") == signal.signal_id
            and payload.get("source_kind") == GrowthRegistry.OFFICIAL_COMPANY_SOURCE_KIND
            and payload.get("source_fetch_mode") == GrowthRegistry.OFFICIAL_COMPANY_FETCH_MODE
            and payload.get("source_enabled") is True
            and payload.get("outreach_id") == row.outreach_id
            and payload.get("email_sent") is False
        ):
            return proof, payload
    return None


def _record_official_source_binding_proof(
    db: Session,
    row: OutreachMessage,
    signal: GrowthSignal,
    source: dict[str, Any],
    *,
    actor: str,
    proof_origin: str,
) -> AuditLog:
    existing = _official_source_binding_proof_audit(db, row, signal)
    if existing is not None:
        return existing
    if _trusted_official_source_binding_proof_audit(db, row, signal) is not None:
        raise OfficialSourceEvidenceError("official_source_binding_proof_conflict")
    payload = _official_source_binding_proof_payload(
        row,
        signal,
        source,
        actor=actor,
        proof_origin=proof_origin,
    )
    audit(
        db,
        actor=actor,
        action="growth_official_source_signal_bound",
        entity_type="growth_signal",
        entity_id=signal.signal_id,
        after={
            **payload,
            "binding_proof_hmac_sha256": _official_source_receipt_hmac(payload),
        },
    )
    db.flush()
    recorded = _official_source_binding_proof_audit(db, row, signal)
    if recorded is None:
        raise OfficialSourceEvidenceError("official_source_binding_proof_write_failed")
    return recorded


def migrate_official_source_binding_proofs_locked(
    db: Session,
    *,
    targets: tuple[OfficialSourceBindingProofTarget, ...],
    migration_id: str,
    expected_registry_version: str,
    expected_registry_sha256: str,
    expected_authority_registry_id: str,
    expected_authority_registry_version: int,
    expected_authority_registry_sha256: str,
) -> list[int]:
    """Atomically attest pre-existing official rows while the runtime is locked."""

    actor = "codex-owner-authorized-automation"
    config = settings()
    runtime_marker = Path(config.runtime_kill_switch_file)
    managed_gate = Path(config.kill_switch_file)
    if not runtime_marker.is_file() or not managed_gate.is_file() or writes_unlocked():
        raise OfficialSourceEvidenceError("official_source_binding_migration_requires_runtime_lock")
    if (
        not targets
        or len({target.signal_id for target in targets}) != len(targets)
        or len({target.outreach_id for target in targets}) != len(targets)
        or len({target.source_id for target in targets}) != len(targets)
    ):
        raise OfficialSourceEvidenceError("official_source_binding_migration_targets_invalid")
    registry_path = Path(config.registry_file)
    try:
        registry_sha256 = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise OfficialSourceEvidenceError(
            "official_source_binding_migration_registry_unreadable"
        ) from exc
    if not hmac.compare_digest(registry_sha256, expected_registry_sha256):
        raise OfficialSourceEvidenceError(
            "official_source_binding_migration_registry_hash_mismatch"
        )

    try:
        registry = GrowthRegistry.load()
        if registry.version != expected_registry_version:
            raise OfficialSourceEvidenceError(
                "official_source_binding_migration_registry_version_mismatch"
            )
        validated: list[
            tuple[
                OfficialSourceBindingProofTarget,
                OutreachMessage,
                GrowthSignal,
                dict[str, Any],
            ]
        ] = []
        for target in targets:
            row = db.scalar(
                select(OutreachMessage)
                .where(OutreachMessage.outreach_id == target.outreach_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise OfficialSourceEvidenceError(
                    "official_source_binding_migration_outreach_missing"
                )
            signal = db.scalar(
                select(GrowthSignal)
                .where(GrowthSignal.signal_id == target.signal_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                signal is None
                or row.signal_id != target.signal_id
                or signal.source_id != target.source_id
                or row.status != "queued"
                or signal.status != "queued"
                or row.sequence_step != 0
                or row.claimed_by is not None
                or row.claimed_at is not None
                or row.lease_expires_at is not None
                or row.provider_message_id is not None
                or row.sent_at is not None
                or _delivery_verification_pending(row)
            ):
                raise OfficialSourceEvidenceError(
                    "official_source_binding_migration_row_state_invalid"
                )
            source = _current_official_source(signal, registry)
            authority = source.get("authority")
            if (
                source.get("binding_sha256") != target.binding_sha256
                or signal.source_payload_hash != target.binding_sha256
                or not isinstance(authority, dict)
                or authority.get("registry_id") != expected_authority_registry_id
                or authority.get("version") != expected_authority_registry_version
                or authority.get("sha256") != expected_authority_registry_sha256
            ):
                raise OfficialSourceEvidenceError(
                    "official_source_binding_migration_source_mismatch"
                )
            _assert_official_source_recipient_binding(row, signal, source)
            metadata, _body_html = _assert_canonical_payload(row)
            _assert_current_canonical_screening(signal, metadata)
            if not _payload_matches(row) or not _release_matches(row):
                raise OfficialSourceEvidenceError(
                    "official_source_binding_migration_payload_release_invalid"
                )
            registry.validate_signal_source(
                **{
                    **_official_source_validation_values(signal, metadata),
                    "source_payload_hash": target.binding_sha256,
                },
                detected_at=utcnow(),
            )
            validated.append((target, row, signal, source))

        if (
            not runtime_marker.is_file()
            or writes_unlocked()
            or hashlib.sha256(registry_path.read_bytes()).hexdigest() != expected_registry_sha256
        ):
            raise OfficialSourceEvidenceError(
                "official_source_binding_migration_precommit_state_changed"
            )
        proof_ids: list[int] = []
        for _target, row, signal, source in validated:
            proof = _record_official_source_binding_proof(
                db,
                row,
                signal,
                source,
                actor=actor,
                proof_origin="locked_one_time_migration",
            )
            proof_ids.append(proof.id)
        completion_payload = {
            "migration_id": migration_id,
            "registry_version": expected_registry_version,
            "registry_sha256": expected_registry_sha256,
            "authority_registry_id": expected_authority_registry_id,
            "authority_registry_version": expected_authority_registry_version,
            "authority_registry_sha256": expected_authority_registry_sha256,
            "runtime_kill_switch_file": str(runtime_marker),
            "runtime_kill_switch_present": True,
            "managed_owner_gate_file": str(managed_gate),
            "managed_owner_gate_present": True,
            "targets": [
                {
                    "signal_id": target.signal_id,
                    "outreach_id": target.outreach_id,
                    "source_id": target.source_id,
                    "binding_sha256": target.binding_sha256,
                    "proof_audit_id": proof_id,
                }
                for (target, _row, _signal, _source), proof_id in zip(
                    validated,
                    proof_ids,
                    strict=True,
                )
            ],
            "email_sent": False,
        }
        existing_completion = db.scalars(
            select(AuditLog).where(
                AuditLog.action == "growth_official_source_binding_proof_migration_completed",
                AuditLog.entity_type == "growth_source_binding_migration",
                AuditLog.entity_id == migration_id,
            )
        ).all()
        if existing_completion:
            if len(existing_completion) != 1:
                raise OfficialSourceEvidenceError(
                    "official_source_binding_migration_audit_not_unique"
                )
            try:
                existing_payload = json.loads(existing_completion[0].after_json or "{}")
            except (TypeError, json.JSONDecodeError) as exc:
                raise OfficialSourceEvidenceError(
                    "official_source_binding_migration_audit_unreadable"
                ) from exc
            existing_hmac = str(existing_payload.pop("migration_hmac_sha256", ""))
            if (
                existing_completion[0].actor != actor
                or existing_completion[0].before_json is not None
                or existing_payload != completion_payload
                or not re.fullmatch(r"[0-9a-f]{64}", existing_hmac)
                or not hmac.compare_digest(
                    existing_hmac,
                    _official_source_receipt_hmac(existing_payload),
                )
            ):
                raise OfficialSourceEvidenceError(
                    "official_source_binding_migration_audit_mismatch"
                )
        else:
            audit(
                db,
                actor=actor,
                action="growth_official_source_binding_proof_migration_completed",
                entity_type="growth_source_binding_migration",
                entity_id=migration_id,
                after={
                    **completion_payload,
                    "migration_hmac_sha256": _official_source_receipt_hmac(completion_payload),
                },
            )
        if not runtime_marker.is_file() or writes_unlocked():
            raise OfficialSourceEvidenceError("official_source_binding_migration_lock_lost")
        db.commit()
        return proof_ids
    except Exception:
        db.rollback()
        raise


def _official_source_required(
    db: Session,
    row: OutreachMessage,
    signal: GrowthSignal,
    registry: GrowthRegistry,
) -> bool:
    sources = getattr(registry, "sources", {})
    source = sources.get(signal.source_id) if isinstance(sources, dict) else None
    current_kind_official = bool(
        isinstance(source, dict)
        and source.get("kind") == GrowthRegistry.OFFICIAL_COMPANY_SOURCE_KIND
    )
    return bool(
        current_kind_official
        or _trusted_official_source_binding_proof_audit(db, row, signal) is not None
    )


def _assert_official_source_provenance_consistent(
    db: Session,
    row: OutreachMessage,
    signal: GrowthSignal,
) -> None:
    if (
        _trusted_official_source_binding_proof_audit(db, row, signal) is not None
        and _official_source_binding_proof_audit(db, row, signal) is None
    ):
        raise OfficialSourceEvidenceError("official_source_provenance_binding_changed")


def _current_official_source(
    signal: GrowthSignal,
    registry: GrowthRegistry,
) -> dict[str, Any]:
    sources = getattr(registry, "sources", {})
    source = sources.get(signal.source_id) if isinstance(sources, dict) else None
    if (
        not isinstance(source, dict)
        or source.get("enabled") is not True
        or source.get("kind") != GrowthRegistry.OFFICIAL_COMPANY_SOURCE_KIND
        or source.get("fetch_mode") != GrowthRegistry.OFFICIAL_COMPANY_FETCH_MODE
    ):
        raise OfficialSourceEvidenceError("official_source_binding_missing_or_disabled")
    return source


def _official_source_entry(
    db: Session,
    row: OutreachMessage,
    signal: GrowthSignal,
    registry: GrowthRegistry,
) -> dict[str, Any] | None:
    if not _official_source_required(db, row, signal, registry):
        return None
    source = _current_official_source(signal, registry)
    _assert_official_source_provenance_consistent(db, row, signal)
    return source


def _assert_official_source_recipient_binding(
    row: OutreachMessage,
    signal: GrowthSignal,
    source: dict[str, Any],
) -> None:
    binding = source.get("recipient_binding")
    expected_email = (
        str(binding.get("recipient_email") or "").strip().casefold()
        if isinstance(binding, dict)
        else ""
    )
    if (
        not expected_email
        or str(signal.recipient_email or "").strip().casefold() != expected_email
        or row.recipient_email.strip().casefold() != expected_email
    ):
        raise OfficialSourceEvidenceError("official_source_recipient_binding_mismatch")


def _refresh_official_source_evidence(
    db: Session,
    row: OutreachMessage,
    signal: GrowthSignal,
    registry: GrowthRegistry,
    canonical_metadata: dict[str, Any],
) -> bool:
    payload_before = row.payload_sha256
    release_before = row.release_token_hash
    detected_before = _aware(signal.detected_at).astimezone(UTC)
    source_payload_hash_before = signal.source_payload_hash
    last_seen_before = signal.last_seen_at
    dedupe_hash_before = signal.dedupe_hash
    try:
        source = _official_source_entry(db, row, signal, registry)
        if source is None:
            return False
        _assert_official_source_recipient_binding(row, signal, source)
        validation_values = _official_source_validation_values(signal, canonical_metadata)
        screening_before = _current_canonical_screening_values(
            signal, canonical_metadata["render_input"]
        )
        # Validate every static identity/URL binding before network I/O while
        # intentionally substituting the current managed binding and clock.
        # This accepts a policy-evidence-only registry revision for the live
        # receipt without mutating the signal's dedupe-bound identity; every
        # recipient and URL field must still match before network I/O.
        registry.validate_signal_source(
            **{
                **validation_values,
                "source_payload_hash": source.get("binding_sha256"),
            },
            detected_at=utcnow(),
        )
        evidence = fetch_official_source_evidence(
            signal.source_id,
            source,
            expected_recipient_name=str(validation_values["recipient_name"] or ""),
            expected_organization_names=[
                str(value)
                for value in (
                    signal.company_name,
                    signal.recipient_organization_name,
                )
                if value
            ],
        )

        # The managed registry is a mounted artifact and may change during a
        # slow fetch. Re-read and require the exact same immutable binding.
        current_registry = GrowthRegistry.load()
        current_source = current_registry.sources.get(signal.source_id)
        if (
            not isinstance(current_source, dict)
            or current_source.get("binding_sha256") != evidence.binding_sha256
            or current_source.get("binding_sha256") != source.get("binding_sha256")
        ):
            raise OfficialSourceEvidenceError("official_source_registry_changed_during_fetch")
        _assert_official_source_recipient_binding(row, signal, current_source)

        current_values = _official_source_validation_values(signal, canonical_metadata)
        current_registry.validate_signal_source(
            **{
                **current_values,
                "source_payload_hash": evidence.binding_sha256,
            },
            detected_at=evidence.observed_at,
        )
        if (
            _current_canonical_screening_values(signal, canonical_metadata["render_input"])
            != screening_before
        ):
            raise OfficialSourceEvidenceError("official_source_screening_binding_changed")
        if (
            _aware(signal.detected_at).astimezone(UTC) != detected_before
            or signal.source_payload_hash != source_payload_hash_before
            or signal.last_seen_at != last_seen_before
            or signal.dedupe_hash != dedupe_hash_before
            or row.payload_sha256 != payload_before
            or row.release_token_hash != release_before
            or not _payload_matches(row)
            or not _release_matches(row)
        ):
            raise OfficialSourceEvidenceError("official_source_outreach_binding_changed")
        receipt_payload = {
            **evidence.audit_payload(),
            "outreach_id": row.outreach_id,
            "payload_sha256": row.payload_sha256,
            "signal_detected_at": detected_before.isoformat(),
            "signal_source_payload_hash": source_payload_hash_before,
            "signal_dedupe_hash": dedupe_hash_before,
            "recipient_email": signal.recipient_email,
            "release_token_sha256": hashlib.sha256(
                str(row.release_token_hash or "").encode()
            ).hexdigest(),
            "screening_binding_unchanged": True,
            "signal_identity_unchanged": True,
            "payload_and_release_unchanged": True,
            "attestation_scheme": "HMAC-SHA256:IMPERIAL_RELEASE_HMAC_KEY:v1",
            "email_sent": False,
        }
        audit(
            db,
            actor="growth-worker",
            action="growth_official_source_evidence_refreshed",
            entity_type="growth_signal",
            entity_id=signal.signal_id,
            before={
                "detected_at": detected_before.isoformat(),
                "source_payload_hash": validation_values["source_payload_hash"],
                "outreach_id": row.outreach_id,
                "payload_sha256": payload_before,
            },
            after={
                **receipt_payload,
                "receipt_hmac_sha256": _official_source_receipt_hmac(receipt_payload),
            },
        )
        db.flush()
        return True
    except Exception as exc:
        reason = str(exc)
        audit(
            db,
            actor="growth-worker",
            action="growth_official_source_evidence_refresh_failed",
            entity_type="growth_signal",
            entity_id=signal.signal_id,
            after={
                "outreach_id": row.outreach_id,
                "source_id": signal.source_id,
                "reason": reason,
                "error_type": type(exc).__name__,
                "provider_claimed": False,
                "email_sent": False,
            },
        )
        if isinstance(exc, OfficialSourceEvidenceError):
            raise
        if isinstance(exc, GrowthRegistryError):
            raise OfficialSourceEvidenceError(str(exc)) from exc
        raise OfficialSourceEvidenceError("official_source_live_check_failed") from exc


def _assert_official_source_evidence_fresh(
    db: Session,
    row: OutreachMessage,
    signal: GrowthSignal,
    *,
    official_required: bool,
    registry: GrowthRegistry | None = None,
) -> None:
    if not official_required:
        return
    current_registry = registry or GrowthRegistry.load()
    source = _current_official_source(signal, current_registry)
    _assert_official_source_provenance_consistent(db, row, signal)
    _assert_official_source_recipient_binding(row, signal, source)
    metadata = _canonical_metadata(row)
    latest = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "growth_official_source_evidence_refreshed",
            AuditLog.entity_id == signal.signal_id,
        )
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    try:
        receipt = json.loads(latest.after_json or "{}") if latest else {}
    except (TypeError, json.JSONDecodeError) as exc:
        raise OfficialSourceEvidenceError("official_source_evidence_receipt_unreadable") from exc
    receipt_hmac = str(receipt.pop("receipt_hmac_sha256", ""))
    if (
        receipt.get("attestation_scheme") != "HMAC-SHA256:IMPERIAL_RELEASE_HMAC_KEY:v1"
        or not re.fullmatch(r"[0-9a-f]{64}", receipt_hmac)
        or not hmac.compare_digest(
            receipt_hmac,
            _official_source_receipt_hmac(receipt),
        )
    ):
        raise OfficialSourceEvidenceError("official_source_evidence_receipt_attestation_failed")
    try:
        observed_at = datetime.fromisoformat(
            str(receipt.get("observed_at") or "").replace("Z", "+00:00")
        )
        if observed_at.tzinfo is None:
            raise ValueError("timezone missing")
        observed_at = observed_at.astimezone(UTC)
    except ValueError as exc:
        raise OfficialSourceEvidenceError("official_source_evidence_receipt_mismatch") from exc
    pages = receipt.get("pages")
    policy_evidence = source.get("policy_evidence")
    if not isinstance(policy_evidence, dict):
        raise OfficialSourceEvidenceError("official_source_evidence_receipt_mismatch")
    expected_requested_urls = {
        str(source.get("context_evidence_url") or ""),
        str(source.get("public_contact_url") or ""),
    }
    expected_final_urls = {
        requested: (
            str(policy_evidence.get("final_url") or "")
            if requested == str(policy_evidence.get("evidence_url") or "")
            else requested
        )
        for requested in expected_requested_urls
    }
    render_input = metadata.get("render_input")
    if not isinstance(render_input, dict):
        raise OfficialSourceEvidenceError("official_source_canonical_input_missing")
    expected_recipient_marker = normalize_official_source_marker(
        str(render_input.get("recipient_name") or "")
    )
    expected_organization_markers = {
        normalize_official_source_marker(str(value))
        for value in (signal.company_name, signal.recipient_organization_name)
        if value
    }
    expected_email = str(signal.recipient_email or "").strip().casefold()

    def valid_page(page: Any) -> bool:
        if not isinstance(page, dict):
            return False
        try:
            source_ip = ipaddress.ip_address(str(page.get("source_ip") or ""))
            content_bytes = int(page.get("content_bytes"))
        except (TypeError, ValueError):
            return False
        content_type = str(page.get("content_type") or "")
        requested_url = str(page.get("requested_url") or "")
        return bool(
            is_public_unicast_address(source_ip)
            and 0 < content_bytes <= OFFICIAL_SOURCE_MAX_RESPONSE_BYTES
            and content_type.split(";", 1)[0].strip().casefold() == "text/html"
            and page.get("http_status") == 200
            and page.get("final_url") == expected_final_urls.get(requested_url)
            and re.fullmatch(
                r"[0-9a-f]{64}",
                str(page.get("content_sha256") or ""),
            )
        )

    if (
        receipt.get("outreach_id") != row.outreach_id
        or receipt.get("source_id") != signal.source_id
        or receipt.get("binding_sha256") != source.get("binding_sha256")
        or receipt.get("observed_at") != observed_at.isoformat()
        or receipt.get("payload_sha256") != row.payload_sha256
        or receipt.get("signal_detected_at")
        != _aware(signal.detected_at).astimezone(UTC).isoformat()
        or receipt.get("signal_source_payload_hash") != signal.source_payload_hash
        or receipt.get("signal_dedupe_hash") != signal.dedupe_hash
        or receipt.get("recipient_email") != signal.recipient_email
        or receipt.get("matched_email") != expected_email
        or receipt.get("matched_recipient_marker") != expected_recipient_marker
        or receipt.get("matched_organization_marker") not in expected_organization_markers
        or receipt.get("signal_identity_unchanged") is not True
        or receipt.get("payload_and_release_unchanged") is not True
        or receipt.get("release_token_sha256")
        != hashlib.sha256(str(row.release_token_hash or "").encode()).hexdigest()
        or not isinstance(pages, list)
        or not pages
        or len(pages) != len(expected_requested_urls)
        or {str(page.get("requested_url") or "") for page in pages} != expected_requested_urls
        or any(not valid_page(page) for page in pages)
    ):
        raise OfficialSourceEvidenceError("official_source_evidence_receipt_mismatch")
    current_registry.validate_signal_source(
        **{
            **_official_source_validation_values(signal, metadata),
            "source_payload_hash": source.get("binding_sha256"),
        },
        detected_at=observed_at,
    )
    if not _payload_matches(row) or not _release_matches(row):
        raise OfficialSourceEvidenceError("official_source_outreach_binding_changed")
    _assert_current_canonical_screening(signal, metadata)


def _assert_outreach_pre_send_guard(
    db: Session,
    row: OutreachMessage,
    signal: GrowthSignal,
    *,
    official_required: bool,
) -> None:
    locked_row = db.scalar(
        select(OutreachMessage)
        .where(OutreachMessage.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_row is None or locked_row.outreach_id != row.outreach_id:
        raise GrowthRegistryError("outreach_pre_send_state_invalid_no_send")
    locked_signal = db.scalar(
        select(GrowthSignal)
        .where(GrowthSignal.id == signal.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_signal is None or locked_signal.signal_id != locked_row.signal_id:
        raise GrowthRegistryError("outreach_pre_send_state_invalid_no_send")
    if not _outreach_sending_window_open():
        raise GrowthRegistryError("outreach_sending_window_closed_no_send")
    if not _outreach_transport_capacity_reserved(db, locked_row):
        raise GrowthRegistryError("outreach_transport_capacity_not_reserved_no_send")
    if (
        not writes_unlocked()
        or locked_row.status != "claimed"
        or locked_row.claimed_by != settings().worker_id
        or locked_row.lease_expires_at is None
        or _aware(locked_row.lease_expires_at) <= utcnow()
        or locked_row.provider_message_id is not None
        or _delivery_verification_pending(locked_row)
    ):
        raise GrowthRegistryError("outreach_pre_send_state_invalid_no_send")
    try:
        _assert_official_source_evidence_fresh(
            db,
            locked_row,
            locked_signal,
            official_required=official_required,
        )
    except GrowthRegistryError as exc:
        audit(
            db,
            actor="growth-worker",
            action="growth_official_source_evidence_pre_send_failed",
            entity_type="growth_signal",
            entity_id=locked_signal.signal_id,
            after={
                "outreach_id": locked_row.outreach_id,
                "source_id": locked_signal.source_id,
                "reason": str(exc),
                "error_type": type(exc).__name__,
                "global_guard_claimed": True,
                "provider_transport_called": False,
                "email_sent": False,
            },
        )
        db.flush()
        raise


def dispatch_outreach(db: Session, row: OutreachMessage) -> OutreachMessage:
    if row.status != "claimed":
        return row
    if _delivery_verification_pending(row):
        return row
    locked_row = db.scalar(
        select(OutreachMessage)
        .where(OutreachMessage.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_row is None or locked_row.status != "claimed":
        return locked_row or row
    row = locked_row
    if _delivery_verification_pending(row):
        return row
    if row.claimed_by != settings().worker_id:
        return row
    if row.lease_expires_at is None or _aware(row.lease_expires_at) <= utcnow():
        return _release_untransported_claim(db, row, reason="outreach_claim_lease_expired_no_send")
    signal = db.scalar(
        select(GrowthSignal)
        .where(GrowthSignal.signal_id == row.signal_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    hard_gate_reason = _land_agent_gate_reason(signal) if signal else None
    if hard_gate_reason:
        row.status = "blocked"
        row.last_error = hard_gate_reason
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None
        signal.status = "blocked"
        signal.rejection_reasons_json = canonical_json([hard_gate_reason])
        audit(
            db,
            actor="growth-worker",
            action="growth_outreach_hard_gate_blocked",
            entity_type="growth_outreach",
            entity_id=row.outreach_id,
            after={"signal_id": row.signal_id, "reason": hard_gate_reason},
        )
        db.commit()
        return row
    if not _outreach_sending_window_open():
        return _release_untransported_claim(
            db, row, reason="outreach_sending_window_closed_no_send"
        )
    if not _outreach_transport_capacity_reserved(db, row):
        return _release_untransported_claim(
            db, row, reason="outreach_transport_capacity_not_reserved_no_send"
        )
    global_guard = None
    land_canary_claimed = False
    live_listing_evidence: dict[str, Any] | None = None
    official_required = False
    account_quota_attestation: dict[str, Any] = {}
    account_reputation_attestation: dict[str, Any] = {}
    try:
        registry = GrowthRegistry.load()
        if not signal:
            raise GrowthRegistryError("Signal record is missing")
        if not writes_unlocked() or not _control_enabled(db, row.motor_key):
            raise GrowthRegistryError("growth_writes_locked")
        if not _payload_matches(row):
            raise GrowthRegistryError("outreach_payload_hash_mismatch")
        canonical_metadata, body_html = _assert_canonical_payload(row)
        _assert_current_canonical_screening(signal, canonical_metadata)
        _assert_public_land_evidence_manifest(db, signal, canonical_metadata)
        if signal.signal_type == "residential_building_plot":
            required_recipient_type = LAND_RECIPIENT_TYPES_BY_ROLE.get(signal.recipient_role)
            if (
                not required_recipient_type
                or canonical_metadata.get("recipient_type") != required_recipient_type
            ):
                raise GrowthRegistryError("land_recipient_role_type_mismatch_no_send")
        if not _release_matches(row):
            raise GrowthRegistryError("outreach_exact_payload_release_missing_or_invalid")
        if _recipient_suppressed(db, row.recipient_email):
            row.status = "suppressed"
            row.last_error = "global_suppression"
            signal.status = "suppressed"
            db.commit()
            return row
        binding = registry.brand_binding(row.brand_id)
        _verified_sender(db, binding)
        if binding.sender_email != row.sender_email:
            raise GrowthRegistryError("brand_sender_changed_after_queue")
        readiness_reason = _authoritative_send_readiness_reason(db, registry, signal)
        if readiness_reason:
            raise GrowthRegistryError(readiness_reason)
        official_required = _refresh_official_source_evidence(
            db,
            row,
            signal,
            registry,
            canonical_metadata,
        )
        if official_required:
            _assert_official_source_evidence_fresh(
                db,
                row,
                signal,
                official_required=True,
            )
        if _public_land_signal(signal):
            from .public_land import live_listing_revalidation

            live_validation = live_listing_revalidation(db, signal)
            live_listing_evidence = _attest_live_listing_evidence(
                row, live_validation.audit_evidence
            )
            existing_receipt = json.loads(row.receipt_json or "{}")
            existing_receipt["live_listing_revalidation"] = live_listing_evidence
            row.receipt_json = canonical_json(existing_receipt)
            audit(
                db,
                actor="growth-worker",
                action=(
                    "growth_land_live_revalidation_blocked"
                    if live_validation.rejection_reason
                    else "growth_land_live_revalidation_passed"
                ),
                entity_type="growth_outreach",
                entity_id=row.outreach_id,
                after=live_listing_evidence,
            )
            if live_validation.rejection_reason:
                raise GrowthRegistryError(live_validation.rejection_reason)
            land_canary_claimed = _claim_land_canary_slot(db, row.outreach_id)
        global_guard = claim_global_recipient_delivery(
            db,
            recipients=[row.recipient_email],
            identity_sha256=row.idempotency_key,
            message_type="growth_outreach",
            tenant_scope="imperial-holding",
            now=utcnow(),
        )
        if not global_guard.may_send or not global_guard.claim_token:
            raise GrowthRegistryError(f"global_recipient_guard_no_send:{global_guard.decision}")

        def immediate_pre_send_guard() -> None:
            # Serialize every central external POST from the final database
            # recheck through Gmail SENT/MIME readback. The committed claim is
            # the crash-safe reservation if the process dies mid-transport.
            _lock_outreach_transport_account(db)
            _assert_gmail_account_pacing_due(db)
            account_reputation_attestation.update(
                _assert_outreach_reputation_healthy(db)
            )
            _assert_outreach_pre_send_guard(
                db,
                row,
                signal,
                official_required=official_required,
            )
            immediate_registry = GrowthRegistry.load()
            immediate_reason = _authoritative_send_readiness_reason(db, immediate_registry, signal)
            if immediate_reason:
                raise GrowthRegistryError(immediate_reason)
            immediate_binding = immediate_registry.brand_binding(row.brand_id)
            _verified_sender(db, immediate_binding)
            if immediate_binding.sender_email != row.sender_email:
                raise GrowthRegistryError("brand_sender_changed_after_queue")
            immediate_official_required = _official_source_required(
                db, row, signal, immediate_registry
            )
            if immediate_official_required:
                _assert_official_source_evidence_fresh(
                    db,
                    row,
                    signal,
                    official_required=True,
                    registry=immediate_registry,
                )
            _assert_public_land_evidence_manifest(db, signal, canonical_metadata)
            if live_listing_evidence is not None:
                _assert_live_listing_evidence_attestation(row, live_listing_evidence)

        def immediate_account_quota_guard() -> None:
            account_quota_attestation.update(
                _assert_outreach_budapest_day_quota_reserved(db, row)
            )

        if not _outreach_sending_window_open():
            raise GrowthRegistryError("outreach_sending_window_closed_no_send")
        if not _outreach_transport_capacity_reserved(db, row):
            raise GrowthRegistryError("outreach_transport_capacity_not_reserved_no_send")
        render_input = canonical_metadata.get("render_input")
        if not isinstance(render_input, dict):
            raise GrowthRegistryError("canonical_render_input_missing")
        receipt = SMTPEmailAdapter(binding).send(
            to_email=row.recipient_email,
            subject=row.subject,
            body_text=row.body_text,
            body_html=body_html,
            idempotency_key=row.idempotency_key,
            reply_to=str(binding.config.get("reply_to") or binding.sender_email),
            delivery_scope="external_customer",
            pre_send_guard=immediate_pre_send_guard,
            account_quota_guard=immediate_account_quota_guard,
            unsubscribe_url=str(render_input.get("unsubscribe_url") or ""),
        )
        if (
            receipt.provider != "gmail_api"
            or receipt.detail.get("readback_verified") is not True
            or not receipt.detail.get("readback_mime_sha256")
            or not receipt.detail.get("rfc_message_id")
        ):
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
                provider_message_id=receipt.provider_message_id,
                detail={
                    "reason": "external_delivery_receipt_not_gmail_readback_verified",
                    "provider": receipt.provider,
                },
            )
        try:
            provider_accepted_at = _aware(
                datetime.fromisoformat(
                    str(receipt.detail["provider_internal_date"]).replace("Z", "+00:00")
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
                provider_message_id=receipt.provider_message_id,
                detail={"reason": "gmail_provider_internal_date_invalid"},
            ) from exc
        completed_at = utcnow()
        verified_receipt_json = canonical_json(
            {
                "provider": receipt.provider,
                "accepted_recipient": receipt.accepted_recipient,
                "response_sha256": receipt.response_sha256,
                "accepted": True,
                "delivery_detail": receipt.detail,
                "account_quota_attestation": account_quota_attestation,
                "account_reputation_attestation": account_reputation_attestation,
                "canonical_template": canonical_metadata,
                "live_listing_revalidation": live_listing_evidence,
            }
        )
        # Persist the provider identity and verified MIME evidence in the same
        # commit that finalizes the global guard.  The row deliberately remains
        # claimed until the final business transition below, but it already
        # occupies the Budapest-day first-contact ledger if the process dies
        # in between.
        row.provider_message_id = receipt.provider_message_id
        row.receipt_json = verified_receipt_json
        # Quota-day attribution uses Gmail's provider acceptance timestamp,
        # not the later local readback/commit instant around a midnight edge.
        row.sent_at = provider_accepted_at
        if receipt.detail.get("recovered_existing_sent") is not True:
            _record_outreach_pacing_success(db, now=completed_at)
        try:
            finalize_global_recipient_delivery(
                db,
                recipients=[row.recipient_email],
                identity_sha256=row.idempotency_key,
                claim_token=global_guard.claim_token,
                provider_message_id=receipt.provider_message_id,
                now=completed_at,
            )
        except RuntimeError as exc:
            raise EmailDeliveryError(
                "global_recipient_guard_finalize_failed",
                retry_safe=False,
                accepted_but_unverified=True,
                provider_message_id=receipt.provider_message_id,
                detail={"reason": str(exc)},
            ) from exc
        if land_canary_claimed:
            _finish_land_canary_slot(
                db,
                row.outreach_id,
                outcome="sent",
                provider_message_id=receipt.provider_message_id,
            )
        row.status = "sent"
        row.provider_message_id = receipt.provider_message_id
        row.receipt_json = verified_receipt_json
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None
        signal.status = "contacted"
        audit(
            db,
            actor="growth-worker",
            action="growth_outreach_sent",
            entity_type="growth_outreach",
            entity_id=row.outreach_id,
            after={
                "signal_id": row.signal_id,
                "brand_id": row.brand_id,
                "sequence_step": row.sequence_step,
                "provider": receipt.provider,
                "response_sha256": receipt.response_sha256,
            },
        )
    except (GrowthRegistryError, EmailDeliveryError) as exc:
        transport_ambiguous = bool(
            isinstance(exc, EmailDeliveryError) and exc.accepted_but_unverified
        )
        if global_guard and global_guard.may_send and global_guard.claim_token:
            fail_global_recipient_delivery(
                db,
                recipients=[row.recipient_email],
                identity_sha256=row.idempotency_key,
                claim_token=global_guard.claim_token,
                error=(exc.error_type if isinstance(exc, EmailDeliveryError) else str(exc)),
                accepted_unverified=transport_ambiguous,
                provider_message_id=(
                    exc.provider_message_id if isinstance(exc, EmailDeliveryError) else None
                ),
                now=utcnow(),
            )
        if land_canary_claimed:
            _finish_land_canary_slot(
                db,
                row.outreach_id,
                outcome="consumed" if transport_ambiguous else "release",
                provider_message_id=(
                    exc.provider_message_id if isinstance(exc, EmailDeliveryError) else None
                ),
            )
        if transport_ambiguous:
            if isinstance(exc, EmailDeliveryError) and exc.rate_limited:
                _record_outreach_pacing_backoff(db, error=exc, now=utcnow())
            if isinstance(exc, EmailDeliveryError) and exc.authentication_failure:
                _require_runtime_kill_switch(
                    db, reason="provider_authentication_failure"
                )
            try:
                pending_receipt = json.loads(row.receipt_json or "{}")
            except (TypeError, json.JSONDecodeError):
                pending_receipt = {}
            pending_receipt.update(
                {
                    "provider": "gmail_api",
                    "accepted": True,
                    "delivery_verification": {
                        "status": "pending_verification",
                        "retry_safe": False,
                        "provider_message_id": exc.provider_message_id,
                        "reserved_at": utcnow().isoformat(),
                        "detail": exc.detail,
                    },
                }
            )
            row.status = "claimed"
            row.last_error = exc.error_type
            row.provider_message_id = exc.provider_message_id
            row.receipt_json = canonical_json(pending_receipt)
            row.claimed_by = None
            row.lease_expires_at = None
            audit(
                db,
                actor="growth-worker",
                action="growth_outreach_delivery_pending_verification",
                entity_type="growth_outreach",
                entity_id=row.outreach_id,
                after={
                    "signal_id": row.signal_id,
                    "provider_message_id": exc.provider_message_id,
                    "retry_safe": False,
                    "detail": exc.detail,
                },
            )
            db.commit()
            return row
        recipient_hard_gate = _is_recipient_hard_gate_error(exc)
        retryable_canary = str(exc).startswith("land_outreach_production_canary_")
        row.last_error = (
            str(exc)
            if recipient_hard_gate
            or retryable_canary
            or isinstance(exc, OfficialSourceEvidenceError)
            else exc.error_type
            if isinstance(exc, EmailDeliveryError)
            else type(exc).__name__
        )
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None
        if recipient_hard_gate:
            row.status = "blocked"
            signal.status = "blocked"
            signal.rejection_reasons_json = canonical_json([str(exc)])
            audit(
                db,
                actor="growth-worker",
                action="growth_outreach_hard_gate_blocked",
                entity_type="growth_outreach",
                entity_id=row.outreach_id,
                after={"signal_id": row.signal_id, "reason": str(exc)},
            )
        else:
            retry_safe = not isinstance(exc, EmailDeliveryError) or exc.retry_safe
            if (
                isinstance(exc, EmailDeliveryError)
                and exc.retry_safe
                and (not exc.transport_attempted or exc.rate_limited)
            ):
                row.attempt_count = max(0, row.attempt_count - 1)
                next_at = _record_outreach_pacing_backoff(db, error=exc, now=utcnow())
            elif isinstance(exc, EmailDeliveryError) and exc.retry_safe:
                next_at = _record_outreach_pacing_backoff(db, error=exc, now=utcnow())
            else:
                next_at = None
        if not recipient_hard_gate and (row.attempt_count >= row.max_attempts or not retry_safe):
            row.status = "dead_letter"
        elif not recipient_hard_gate:
            row.status = "queued"
            row.available_at = max(
                utcnow() + timedelta(minutes=2 ** min(row.attempt_count, 8)),
                next_at or utcnow(),
            )
        authentication_failure = isinstance(exc, EmailDeliveryError) and exc.authentication_failure
        if authentication_failure or "payload_hash" in str(exc):
            _require_runtime_kill_switch(
                db,
                reason=(
                    "provider_authentication_failure"
                    if authentication_failure
                    else "outreach_payload_hash_failure"
                ),
            )
    db.commit()
    return row


def _contain_unexpected_dispatch_exception(
    db: Session, row: OutreachMessage, exc: Exception
) -> None:
    # The exception boundary may be after bytes reached the provider. Roll back
    # uncommitted mutations, then hold only this row as delivery-ambiguous. It
    # remains a quota reservation and is never automatically retried.
    row_id = row.id
    db.rollback()
    held = db.scalar(select(OutreachMessage).where(OutreachMessage.id == row_id).with_for_update())
    if held is None or held.status != "claimed":
        db.commit()
        return
    try:
        receipt = json.loads(held.receipt_json or "{}")
    except (TypeError, json.JSONDecodeError):
        receipt = {}
    contained_at = utcnow()
    receipt["delivery_verification"] = {
        "status": "pending_verification",
        "retry_safe": False,
        "provider_message_id": held.provider_message_id,
        "reserved_at": contained_at.isoformat(),
        "detail": {"reason": "unexpected_dispatch_exception_isolated"},
    }
    held.receipt_json = canonical_json(receipt)
    held.last_error = f"unexpected_dispatch_exception:{type(exc).__name__}"
    held.claimed_by = None
    held.claimed_at = held.claimed_at or contained_at
    held.lease_expires_at = None
    audit(
        db,
        actor="growth-worker",
        action="growth_outreach_unexpected_dispatch_exception_isolated",
        entity_type="growth_outreach",
        entity_id=held.outreach_id,
        after={
            "error_type": type(exc).__name__,
            "provider_message_id": held.provider_message_id,
            "retry_safe": False,
            "batch_continued": True,
        },
    )
    db.commit()


def dispatch_batch(db: Session, *, limit: int = 20) -> int:
    if not _outreach_sending_window_open():
        return 0
    capacity = _outreach_send_capacity(db)
    if capacity <= 0:
        return 0
    sent = 0
    # One due item per worker tick. The persisted next-send timestamp prevents
    # restart/catch-up bursts without inventing an hourly or domain count cap;
    # the Budapest calendar-day ceiling is enforced independently above and
    # again under the transport lock immediately before POST.
    for _ in range(max(1, min(limit, capacity, 1))):
        row = claim_outreach(db)
        if not row:
            break
        try:
            result = dispatch_outreach(db, row)
        except Exception as exc:
            try:
                _contain_unexpected_dispatch_exception(db, row, exc)
            except Exception:
                # If containment itself cannot be committed, stop the batch.
                # The transaction is rolled back and no later item is touched.
                db.rollback()
                return sent
            if _PROCESS_EMERGENCY_SEND_STOP.is_set():
                return sent
            continue
        sent += result.status == "sent"
    return sent


def _outreach_sending_window_open(now: datetime | None = None) -> bool:
    config = settings()
    try:
        zone = ZoneInfo(config.timezone)
        start = time.fromisoformat(getattr(config, "outreach_send_start_local", "00:00"))
        end = time.fromisoformat(getattr(config, "outreach_send_end_local", "00:00"))
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise GrowthRegistryError("Configured outreach sending window is invalid") from exc
    if start == end:
        return True
    if start > end:
        raise GrowthRegistryError("Outreach sending window must start before it ends")
    local_time = (now or utcnow()).astimezone(zone).time().replace(tzinfo=None)
    return start <= local_time < end


def _outreach_send_capacity(db: Session, now: datetime | None = None) -> int:
    current = _aware(now or utcnow())
    usage = _outreach_capacity_usage(db, current)
    if usage.active_claimed > 0:
        return 0
    daily_usage = _outreach_budapest_day_usage(db, current)
    if daily_usage.effective_reserved_count >= daily_usage.limit:
        return 0
    next_at = _outreach_pacing_next_at(db)
    if next_at is None and usage.last_verified_at is not None:
        next_at = usage.last_verified_at + timedelta(
            seconds=_outreach_reputation_gap_seconds(usage, now=current)
        )
    return 0 if next_at is not None and current < next_at else 1


def schedule_followups(db: Session) -> int:
    # No owner-approved follow-up copy exists in the canonical registry. Any
    # automatic follow-up would therefore be an unapproved fallback.
    return 0


def record_outreach_event(db: Session, outreach_id: str, data: OutreachEventIn) -> OutreachMessage:
    row = db.scalar(select(OutreachMessage).where(OutreachMessage.outreach_id == outreach_id))
    if not row:
        raise KeyError(outreach_id)
    when = _aware(data.occurred_at) if data.occurred_at else utcnow()
    signal = db.scalar(select(GrowthSignal).where(GrowthSignal.signal_id == row.signal_id))
    if data.event_type == "delivered":
        row.status = "delivered"
        row.delivered_at = when
    elif data.event_type == "response":
        row.status = "responded"
        row.response_at = when
        if signal:
            signal.status = "responded"
    else:
        status = {"bounce": "bounced", "complaint": "complained", "unsubscribe": "unsubscribed"}[
            data.event_type
        ]
        row.status = status
        suppression = db.scalar(
            select(MailSuppression).where(MailSuppression.email == row.recipient_email)
        )
        if not suppression:
            suppression = MailSuppression(email=row.recipient_email)
            db.add(suppression)
        suppression.reason = data.event_type
        suppression.source = "growth_ops_provider_event"
        suppression.active = True
        suppression.details_json = canonical_json({"outreach_id": row.outreach_id})
        if signal:
            signal.status = "suppressed"
    audit(
        db,
        actor="growth-provider",
        action=f"growth_outreach_{data.event_type}",
        entity_type="growth_outreach",
        entity_id=outreach_id,
        after={"occurred_at": when, "provider_event_id": data.provider_event_id},
    )
    db.commit()
    return row


def unsubscribe(db: Session, token: str) -> OutreachMessage:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = db.scalar(
        select(OutreachMessage).where(OutreachMessage.unsubscribe_token_hash == token_hash)
    )
    if not row:
        raise KeyError(token)
    return record_outreach_event(db, row.outreach_id, OutreachEventIn(event_type="unsubscribe"))


def heartbeat(
    db: Session,
    *,
    status: str,
    motor_key: str | None = None,
    outreach_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    worker_id = settings().worker_id
    row = db.get(GrowthWorkerHeartbeat, worker_id)
    if not row:
        row = GrowthWorkerHeartbeat(worker_id=worker_id)
        db.add(row)
    row.status = status
    row.current_motor_key = motor_key
    row.current_outreach_id = outreach_id
    row.detail_json = canonical_json(detail or {})
    row.heartbeat_at = utcnow()
    db.commit()


def run_once(
    db: Session,
    *,
    write_terminal_heartbeat: bool = True,
) -> dict[str, Any]:
    from ..land_acquisition.service import (
        readiness as land_readiness,
    )
    from ..land_acquisition.service import (
        scan_authority_expiry,
        sync_growth_plot_signals,
    )
    from .catalog import scan_due_routes
    from .processing import (
        enqueue_daily_publications,
        generate_daily_content,
        generate_question_radar_answers,
        send_internal_handoff,
        send_publication_digest,
    )
    from .wide_service import run_due as run_due_wide

    try:
        transient_block_promotion = automatic_public_land_transient_block_promotion(db)
    except (GrowthRegistryError, ValueError) as exc:
        db.rollback()
        transient_block_promotion = {
            "status": "blocked",
            "queued": 0,
            "reason": str(exc),
        }
    try:
        name_fallback_promotion = automatic_public_land_name_fallback_promotion(db)
    except (GrowthRegistryError, ValueError) as exc:
        db.rollback()
        name_fallback_promotion = {
            "status": "blocked",
            "queued": 0,
            "reason": str(exc),
        }
    # Process already approved outreach before the slower discovery and content
    # pipelines. An unrelated source, content, or publishing failure must not
    # prevent the mail worker from serving its independently guarded queue.
    early_sent = dispatch_batch(db) if settings().enabled and writes_unlocked() else 0
    wide_run = run_due_wide(db)
    route_scan = scan_due_routes(db)
    question_answers = generate_question_radar_answers(db)
    content_factory = generate_daily_content(db)
    publication_queue = enqueue_daily_publications(db)
    # Refresh counts after evidence extraction and content generation. This does
    # not release or publish the quarantined assets.
    wide_run = run_due_wide(db) or wide_run
    internal_handoff = send_internal_handoff(db)
    land_sync = sync_growth_plot_signals(db)
    land_takedown = scan_authority_expiry(db)
    land_ready, land_readiness_detail = land_readiness(db)
    publication_digest = send_publication_digest(db)
    if not settings().enabled:
        if write_terminal_heartbeat:
            heartbeat(db, status="disabled")
        return {
            "status": "wide_shadow" if wide_run else "disabled",
            "runs": 0,
            "wide_run": wide_run.run_id if wide_run else None,
            "route_scan": route_scan,
            "question_answers": question_answers,
            "content_factory": content_factory,
            "publication_queue": publication_queue,
            "internal_handoff": internal_handoff,
            "land_sync": land_sync,
            "land_takedown": land_takedown,
            "land_readiness": land_readiness_detail,
            "publication_digest": publication_digest,
            "public_land_transient_block_promotion": transient_block_promotion,
            "public_land_name_fallback_promotion": name_fallback_promotion,
            "followups": 0,
            "sent": 0,
        }

    runs = run_due_motors(db)
    followups = schedule_followups(db) if writes_unlocked() else 0
    sent = early_sent + (dispatch_batch(db) if writes_unlocked() else 0)
    content_ok = content_factory.get("status") == "complete"
    promotion_ok = all(
        result.get("status") != "blocked"
        for result in (transient_block_promotion, name_fallback_promotion)
    )
    result = {
        "status": "healthy" if content_ok and land_ready and promotion_ok else "degraded",
        "runs": len(runs),
        "wide_run": wide_run.run_id if wide_run else None,
        "route_scan": route_scan,
        "question_answers": question_answers,
        "content_factory": content_factory,
        "publication_queue": publication_queue,
        "internal_handoff": internal_handoff,
        "land_sync": land_sync,
        "land_takedown": land_takedown,
        "land_readiness": land_readiness_detail,
        "publication_digest": publication_digest,
        "public_land_transient_block_promotion": transient_block_promotion,
        "public_land_name_fallback_promotion": name_fallback_promotion,
        "followups": followups,
        "sent": sent,
        "blocking_errors": (
            []
            if content_ok and land_ready and promotion_ok
            else [
                *([] if content_ok else ["daily_content_not_complete"]),
                *([] if land_ready else land_readiness_detail.get("blocking_reasons", [])),
                *(
                    []
                    if name_fallback_promotion.get("status") != "blocked"
                    else ["public_land_name_fallback_promotion_blocked"]
                ),
                *(
                    []
                    if transient_block_promotion.get("status") != "blocked"
                    else ["public_land_transient_block_promotion_blocked"]
                ),
                *[
                    f"unresolved_brand:{brand}"
                    for brand in content_factory.get("unresolved_brands", [])
                ],
            ]
        ),
    }
    if write_terminal_heartbeat:
        heartbeat(db, status=result["status"], detail=result)
    return result


def _degraded_worker_is_non_send_critical(hb: GrowthWorkerHeartbeat) -> bool:
    try:
        detail = json.loads(hb.detail_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    blockers = detail.get("blocking_errors") if isinstance(detail, dict) else None
    if not isinstance(blockers, list) or not blockers:
        return False
    allowed = {"daily_content_not_complete", "unrelated_content_not_complete"}
    return all(
        isinstance(blocker, str)
        and (blocker in allowed or blocker.startswith("unresolved_brand:"))
        for blocker in blockers
    )


def _production_daily_automation_state(config: Any) -> dict[str, Any]:
    expected = {
        "growth_ops_enabled": True,
        "canonical_growth_enabled": True,
        "canonical_route_scanning_enabled": True,
        "canonical_processing_enabled": True,
        "timezone": "Europe/Budapest",
        "daily_at": "05:30",
        "outreach_send_start_local": "00:00",
        "outreach_send_end_local": "00:00",
        "outreach_budapest_day_max": 2000,
        "outreach_send_concurrency": 1,
        "outreach_reputation_bootstrap_messages_per_window": 100,
        "outreach_reputation_max_growth_factor": 1.25,
        "outreach_reputation_jitter_fraction": 0.20,
    }
    actual = {
        "growth_ops_enabled": getattr(config, "enabled", False) is True,
        "canonical_growth_enabled": (
            getattr(config, "canonical_wide_enabled", False) is True
        ),
        "canonical_route_scanning_enabled": (
            getattr(config, "canonical_route_scanning_enabled", False) is True
        ),
        "canonical_processing_enabled": (
            getattr(config, "canonical_processing_enabled", False) is True
        ),
        "timezone": str(getattr(config, "timezone", "")),
        "daily_at": str(getattr(config, "canonical_daily_at", "")),
        "outreach_send_start_local": str(
            getattr(config, "outreach_send_start_local", "")
        ),
        "outreach_send_end_local": str(
            getattr(config, "outreach_send_end_local", "")
        ),
        "outreach_budapest_day_max": getattr(
            config, "outreach_budapest_day_max", None
        ),
        "outreach_send_concurrency": getattr(config, "outreach_send_concurrency", None),
        "outreach_reputation_bootstrap_messages_per_window": getattr(
            config, "outreach_reputation_bootstrap_messages_per_window", None
        ),
        "outreach_reputation_max_growth_factor": getattr(
            config, "outreach_reputation_max_growth_factor", None
        ),
        "outreach_reputation_jitter_fraction": getattr(
            config, "outreach_reputation_jitter_fraction", None
        ),
    }
    mismatches = {
        key: {"expected": expected_value, "actual": actual[key]}
        for key, expected_value in expected.items()
        if actual[key] != expected_value
    }
    return {
        "ready": not mismatches,
        "expected": expected,
        "actual": actual,
        "mismatches": mismatches,
    }


def readiness(
    db: Session,
    *,
    require_enabled: bool = True,
    live_provider_preflight: bool = True,
) -> tuple[bool, dict[str, Any]]:
    config = settings()
    automation_state = _production_daily_automation_state(config)
    registry: GrowthRegistry | None = None
    try:
        db.execute(select(func.count()).select_from(GrowthSignal))
        database_ok = True
    except Exception:
        db.rollback()
        database_ok = False
    try:
        registry = GrowthRegistry.load()
        registry_state = registry.readiness()
        sender_states: list[dict[str, Any]] = []
        for brand_id in sorted(registry.brands):
            try:
                binding = registry.brand_binding(brand_id)
                _verified_sender(db, binding)
                live_sender = (
                    SMTPEmailAdapter(binding).live_preflight(
                        delivery_scope="external_customer"
                    )
                    if live_provider_preflight
                    else {"live_preflight": "not_requested_for_platform_health"}
                )
                sender_states.append(
                    {"brand_id": brand_id, "ready": True, **live_sender}
                )
            except GrowthRegistryError as exc:
                sender_states.append({"brand_id": brand_id, "ready": False, "reason": str(exc)})
    except GrowthRegistryError as exc:
        registry_state = {"ready": False, "error": str(exc), "enabled_sources": 0}
        sender_states = []
    hb = db.get(GrowthWorkerHeartbeat, config.worker_id) if database_ok else None
    heartbeat_fresh = bool(
        hb
        and hb.heartbeat_at
        and (utcnow() - _aware(hb.heartbeat_at)).total_seconds()
        <= max(120, config.poll_seconds * 4)
    )
    # Only explicitly enumerated, non-send-critical content degradation may
    # coexist with serving outreach. Unknown/route/sender degradation is closed.
    heartbeat_serving = bool(
        hb
        and (
            hb.status in {"healthy", "working"}
            or (hb.status == "degraded" and _degraded_worker_is_non_send_critical(hb))
        )
    )
    heartbeat_ok = heartbeat_fresh and heartbeat_serving
    required = config.enabled
    senders_ok = bool(sender_states) and all(state["ready"] for state in sender_states)
    sources_ok = int(registry_state.get("enabled_sources", 0)) > 0
    if database_ok and registry is not None:
        outbound_state = _outbound_send_readiness_state(db, registry)
    else:
        outbound_state = {
            "ready": False,
            "reason": "growth_send_readiness_unavailable",
        }
    now = utcnow()
    today = datetime(now.year, now.month, now.day, tzinfo=UTC)
    construction_raw_today = (
        db.scalar(
            select(func.coalesce(func.sum(GrowthRun.raw_signals), 0)).where(
                GrowthRun.motor_key == "construction",
                GrowthRun.started_at >= today,
            )
        )
        or 0
        if database_ok
        else 0
    )
    ready = bool(
        database_ok
        and (
            not required
            and not require_enabled
            or required
            and automation_state["ready"]
            and registry_state.get("ready")
            and senders_ok
            and sources_ok
            and outbound_state.get("ready") is True
            and heartbeat_ok
            and writes_unlocked()
        )
    )
    return ready, {
        "enabled": required,
        "live_provider_preflight_required": live_provider_preflight,
        "daily_automation": automation_state,
        "database": "ok" if database_ok else "failed",
        "registry": registry_state,
        "outbound_send_readiness": outbound_state,
        "senders": sender_states,
        "worker_heartbeat": (
            "degraded_sla"
            if heartbeat_ok and hb and hb.status == "degraded"
            else "ok"
            if heartbeat_ok
            else "stale_or_missing"
        ),
        "worker_status": hb.status if hb else "missing",
        "writes_unlocked": writes_unlocked(),
        "construction_daily_raw_review": {
            "actual": int(construction_raw_today),
            "target": 300,
            "met": int(construction_raw_today) >= 300,
        },
        "queued_outreach": (
            db.scalar(
                select(func.count())
                .select_from(OutreachMessage)
                .where(OutreachMessage.status == "queued")
            )
            or 0
            if database_ok
            else None
        ),
    }
