from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, date, datetime, time, timedelta
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings as platform_settings
from ..global_email_guard import (
    claim_global_recipient_delivery,
    fail_global_recipient_delivery,
)
from .email import EmailDeliveryError, SMTPEmailAdapter
from .models import (
    GrowthSignal,
    OutreachMessage,
    ScheduledGmailEscrowBundle,
    ScheduledGmailEscrowPermit,
    ScheduledGmailEscrowSyncEvent,
    ScheduledGmailLease,
    ScheduledGmailLeaseRequest,
)
from .registry import GrowthRegistry, GrowthRegistryError, writes_unlocked
from .scheduled_gmail_auth import ScheduledGmailClientPrincipal
from .scheduled_gmail_escrow import (
    escrow_sha256,
    escrow_signing_key_id,
    sign_escrow_manifest,
)
from .schemas import (
    ScheduledGmailEscrowAbortIn,
    ScheduledGmailEscrowBundleIn,
    ScheduledGmailEscrowSyncEventIn,
    ScheduledGmailEscrowSyncIn,
    ScheduledGmailFinalizeIn,
)
from .service import (
    _assert_current_canonical_screening,
    _assert_official_source_evidence_fresh,
    _assert_outreach_reputation_healthy,
    _assert_public_land_evidence_manifest,
    _authoritative_send_readiness_reason,
    _aware,
    _canonical_metadata,
    _control_enabled,
    _lock_outreach_claim_capacity,
    _official_source_required,
    _outreach_budapest_day_usage,
    _outreach_capacity_usage,
    _outreach_reputation_gap_seconds,
    _payload_matches,
    _preclaim_outreach_readiness_reason,
    _rate_errors,
    _recipient_suppressed,
    _record_outreach_pacing_success,
    _release_matches,
    _verified_sender,
    canonical_json,
    utcnow,
)

ESCROW_CLAIM_PREFIX = "scheduled-gmail-escrow:"
ESCROW_STABLE_RECIPIENT_TYPES = frozenset(
    {"architect_office", "referral_partner", "real_estate_agent"}
)


def _escrow_request_policy_sha256(data: ScheduledGmailEscrowBundleIn) -> str:
    return escrow_sha256(
        {
            "policy": "Budapest-calendar-day-first-contact-2000",
            "transport": "scheduled-connected-gmail-offline-escrow",
            "accepted_unverified_reserves": True,
            "public_land_live_evidence_excluded": True,
            "automatic_resend_after_consuming": False,
            "request": {
                "desired_permit_count": data.desired_permit_count,
                "quota_local_dates": [value.isoformat() for value in data.quota_local_dates],
                "candidates": [
                    {
                        "outreach_id": candidate.outreach_id,
                        "expected_payload_sha256": candidate.expected_payload_sha256,
                    }
                    for candidate in data.candidates
                ],
            },
        }
    )


def _escrow_claimed_by(client_id: str) -> str:
    value = f"{ESCROW_CLAIM_PREFIX}{client_id}"
    if len(value) > 160:
        raise GrowthRegistryError("scheduled_gmail_client_id_too_long")
    return value


def _escrow_permit_token(
    *, permit_id: str, client_id: str, outreach_id: str, nonce: str
) -> str:
    key = platform_settings.imperial_release_hmac_key
    if len(key) < 32:
        raise GrowthRegistryError("scheduled_gmail_escrow_hmac_key_missing")
    material = f"scheduled-gmail-escrow\0{permit_id}\0{client_id}\0{outreach_id}\0{nonce}"
    signature = hmac.new(key.encode(), material.encode(), hashlib.sha256).hexdigest()
    return f"{permit_id}.{signature}"


def _escrow_permit_token_matches(
    permit: ScheduledGmailEscrowPermit, supplied: str
) -> bool:
    expected = _escrow_permit_token(
        permit_id=permit.permit_id,
        client_id=permit.client_id,
        outreach_id=permit.outreach_id,
        nonce=permit.permit_token_nonce,
    )
    return hmac.compare_digest(expected, supplied) and hmac.compare_digest(
        permit.permit_token_sha256,
        hashlib.sha256(supplied.encode()).hexdigest(),
    )


def _registered_client_public_key_snapshot(
    principal: ScheduledGmailClientPrincipal,
) -> tuple[str, str]:
    pem = principal.offline_public_key_pem
    expected_sha256 = principal.offline_public_key_sha256
    if not pem or not expected_sha256 or "PRIVATE KEY" in pem:
        raise GrowthRegistryError("scheduled_gmail_escrow_client_public_key_invalid")
    try:
        raw = pem.encode("ascii")
    except UnicodeEncodeError as exc:
        raise GrowthRegistryError(
            "scheduled_gmail_escrow_client_public_key_invalid"
        ) from exc
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise GrowthRegistryError("scheduled_gmail_escrow_client_public_key_drift")
    return pem, actual_sha256


def _bundle_client_public_key_snapshot(
    bundle: ScheduledGmailEscrowBundle,
) -> tuple[str, str]:
    pem = bundle.client_public_key_pem
    expected_sha256 = bundle.client_public_key_sha256
    if not pem or not expected_sha256 or "PRIVATE KEY" in pem:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_client_key_missing")
    try:
        raw = pem.encode("ascii")
    except UnicodeEncodeError as exc:
        raise GrowthRegistryError(
            "scheduled_gmail_escrow_bundle_client_key_invalid"
        ) from exc
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_client_key_drift")
    return pem, actual_sha256


def _escrow_day_bounds(local_date: date) -> tuple[datetime, datetime]:
    zone = ZoneInfo("Europe/Budapest")
    start = datetime.combine(local_date, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=zone).astimezone(
        UTC
    )
    return start, end


def _exact_transport_payload(row: OutreachMessage) -> dict[str, Any]:
    metadata = _canonical_metadata(row)
    render_input = metadata.get("render_input")
    if not isinstance(render_input, dict):
        raise GrowthRegistryError("canonical_render_input_missing")
    binding = GrowthRegistry.load().brand_binding(row.brand_id)
    return {
        "outreach_id": row.outreach_id,
        "sender_email": row.sender_email,
        "recipient_email": row.recipient_email,
        "subject": row.subject,
        "body_text": row.body_text,
        "body_html": row.body_html or str(metadata.get("body_html") or ""),
        "reply_to": str(binding.config.get("reply_to") or binding.sender_email),
        "unsubscribe_url": str(render_input.get("unsubscribe_url") or ""),
        "idempotency_key": row.idempotency_key,
        "payload_sha256": row.payload_sha256,
    }


def _permit_manifest(
    permit: ScheduledGmailEscrowPermit,
    *,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": "scheduled-gmail-offline-permit-v1",
        "permit_id": permit.permit_id,
        "bundle_id": permit.bundle_id,
        "lease_id": permit.lease_id,
        "outreach_id": permit.outreach_id,
        "client_id": permit.client_id,
        "client_key_id": permit.client_key_id,
        "permit_index": permit.permit_index,
        "sender_email": permit.sender_email,
        "motor_key": permit.motor_key,
        "payload_sha256": permit.payload_sha256,
        "exact_payload_sha256": permit.exact_payload_sha256,
        "outreach_idempotency_key": permit.outreach_idempotency_key,
        "permit_token_sha256": permit.permit_token_sha256,
        "global_guard_claim_token_sha256": permit.global_guard_claim_token_sha256,
        "quota_local_date": permit.quota_local_date.isoformat(),
        "day_start_utc": _aware(permit.day_start_utc).isoformat(),
        "day_end_utc": _aware(permit.day_end_utc).isoformat(),
        "slot_not_before": _aware(permit.slot_not_before).isoformat(),
        "slot_not_after": _aware(permit.slot_not_after).isoformat(),
        "quota_reserved_at": _aware(permit.quota_reserved_at).isoformat(),
        "signing_key_id": permit.signing_key_id,
    }


def _permit_response(
    db: Session, permit: ScheduledGmailEscrowPermit
) -> dict[str, Any]:
    row = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == permit.outreach_id)
    )
    if row is None:
        raise GrowthRegistryError("scheduled_gmail_escrow_outreach_missing")
    payload = _exact_transport_payload(row)
    manifest = _permit_manifest(permit, payload=payload)
    if escrow_sha256(manifest) != permit.permit_manifest_sha256:
        raise GrowthRegistryError("scheduled_gmail_escrow_manifest_drift")
    token = _escrow_permit_token(
        permit_id=permit.permit_id,
        client_id=permit.client_id,
        outreach_id=permit.outreach_id,
        nonce=permit.permit_token_nonce,
    )
    if hashlib.sha256(token.encode()).hexdigest() != permit.permit_token_sha256:
        raise GrowthRegistryError("scheduled_gmail_escrow_token_drift")
    return {
        "permit_id": permit.permit_id,
        "bundle_id": permit.bundle_id,
        "lease_id": permit.lease_id,
        "outreach_id": permit.outreach_id,
        "status": permit.status,
        "permit_token": token,
        "permit_index": permit.permit_index,
        "client_id": permit.client_id,
        "client_key_id": permit.client_key_id,
        "sender_email": permit.sender_email,
        "motor_key": permit.motor_key,
        "payload_sha256": permit.payload_sha256,
        "exact_payload_sha256": permit.exact_payload_sha256,
        "outreach_idempotency_key": permit.outreach_idempotency_key,
        "permit_token_sha256": permit.permit_token_sha256,
        "global_guard_claim_token_sha256": permit.global_guard_claim_token_sha256,
        "quota_local_date": permit.quota_local_date.isoformat(),
        "day_start_utc": _aware(permit.day_start_utc).isoformat(),
        "day_end_utc": _aware(permit.day_end_utc).isoformat(),
        "slot_not_before": _aware(permit.slot_not_before).isoformat(),
        "slot_not_after": _aware(permit.slot_not_after).isoformat(),
        "quota_reserved_at": _aware(permit.quota_reserved_at).isoformat(),
        "payload": payload,
        "manifest": manifest,
        "permit_manifest_sha256": permit.permit_manifest_sha256,
        "signing_key_id": permit.signing_key_id,
        "permit_signature": permit.permit_signature,
    }


def _permit_status_response(permit: ScheduledGmailEscrowPermit) -> dict[str, Any]:
    """Return lifecycle metadata without any transport capability or message PII."""

    return {
        "permit_id": permit.permit_id,
        "bundle_id": permit.bundle_id,
        "outreach_id": permit.outreach_id,
        "status": permit.status,
        "permit_index": permit.permit_index,
        "quota_local_date": permit.quota_local_date.isoformat(),
        "slot_not_before": _aware(permit.slot_not_before).isoformat(),
        "slot_not_after": _aware(permit.slot_not_after).isoformat(),
        "last_client_sequence": permit.last_client_sequence,
        "last_synced_at": permit.last_synced_at,
        "provider_accepted_at": permit.provider_accepted_at,
        "verified_at": permit.verified_at,
    }


def _bundle_manifest(
    bundle: ScheduledGmailEscrowBundle,
    permits: list[ScheduledGmailEscrowPermit],
) -> dict[str, Any]:
    return {
        "version": "scheduled-gmail-offline-bundle-v1",
        "bundle_id": bundle.bundle_id,
        "request_id": bundle.request_id,
        "client_id": bundle.client_id,
        "client_key_id": bundle.client_key_id,
        "permit_count": len(permits),
        "first_quota_local_date": bundle.first_quota_local_date.isoformat(),
        "last_quota_local_date": bundle.last_quota_local_date.isoformat(),
        "valid_from": _aware(bundle.valid_from).isoformat(),
        "expires_at": _aware(bundle.expires_at).isoformat(),
        "policy_sha256": bundle.policy_sha256,
        "client_registry_sha256": bundle.client_registry_sha256,
        "client_public_key_sha256": bundle.client_public_key_sha256,
        "signing_key_id": bundle.signing_key_id,
        "issued_at": _aware(bundle.issued_at).isoformat() if bundle.issued_at else None,
        "permits": [
            {
                "permit_index": permit.permit_index,
                "permit_id": permit.permit_id,
                "permit_manifest_sha256": permit.permit_manifest_sha256,
            }
            for permit in permits
        ],
    }


def _bundle_response(
    db: Session,
    bundle: ScheduledGmailEscrowBundle,
    *,
    include_transport_secrets: bool,
) -> dict[str, Any]:
    if (
        bundle.status not in {"active", "pending_sync", "reconciled"}
        or not bundle.manifest_sha256
        or not bundle.manifest_signature
        or not bundle.issued_at
        or not bundle.client_public_key_sha256
    ):
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_not_ready")
    _bundle_client_public_key_snapshot(bundle)
    permits = list(
        db.scalars(
            select(ScheduledGmailEscrowPermit)
            .where(ScheduledGmailEscrowPermit.bundle_id == bundle.bundle_id)
            .order_by(ScheduledGmailEscrowPermit.permit_index)
        )
    )
    manifest = _bundle_manifest(bundle, permits)
    if escrow_sha256(manifest) != bundle.manifest_sha256:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_manifest_drift")
    return {
        "bundle_id": bundle.bundle_id,
        "request_id": bundle.request_id,
        "status": bundle.status,
        "client_id": bundle.client_id,
        "client_key_id": bundle.client_key_id,
        "permit_count": bundle.permit_count,
        "first_quota_local_date": bundle.first_quota_local_date.isoformat(),
        "last_quota_local_date": bundle.last_quota_local_date.isoformat(),
        "valid_from": _aware(bundle.valid_from).isoformat(),
        "expires_at": _aware(bundle.expires_at).isoformat(),
        "policy_sha256": bundle.policy_sha256,
        "client_registry_sha256": bundle.client_registry_sha256,
        "client_public_key_sha256": bundle.client_public_key_sha256,
        "manifest": manifest,
        "manifest_sha256": bundle.manifest_sha256,
        "signing_key_id": bundle.signing_key_id,
        "manifest_signature": bundle.manifest_signature,
        "issued_at": bundle.issued_at,
        "permits": [
            (
                _permit_response(db, permit)
                if include_transport_secrets
                else _permit_status_response(permit)
            )
            for permit in permits
        ],
    }


def _escrow_slots(
    db: Session,
    *,
    quota_dates: list[date],
    desired_count: int,
    now: datetime,
) -> list[tuple[date, datetime, datetime, datetime, datetime]]:
    usage = _outreach_capacity_usage(db, now)
    gap_seconds = _outreach_reputation_gap_seconds(usage, now=now)
    # Offline capacity is an interleaved reserve lane, not a wall across the
    # send day.  The online sender rejects central sends within +/- one
    # reputation gap of every permit, so four-gap spacing plus a narrow window
    # leaves a protected central-send interval between every two escrow slots.
    # At the 2,000/day transport floor this still permits hundreds per day; at
    # bootstrap reputation it permits hundreds across a multi-day bundle.
    slot_width = max(15.0, min(60.0, gap_seconds / 4.0))
    offline_spacing = gap_seconds * 4.0
    pacing_next = None
    try:
        from .service import _outreach_pacing_next_at

        pacing_next = _outreach_pacing_next_at(db)
    except GrowthRegistryError:
        raise
    slots: list[tuple[date, datetime, datetime, datetime, datetime]] = []
    for quota_date in quota_dates:
        day_start, day_end = _escrow_day_bounds(quota_date)
        current_local_date = now.astimezone(ZoneInfo("Europe/Budapest")).date()
        usage_at = now if quota_date == current_local_date else day_start
        day_usage = _outreach_budapest_day_usage(db, usage_at)
        day_headroom = max(0, day_usage.limit - day_usage.effective_reserved_count)
        if day_headroom == 0:
            continue
        latest_existing = db.scalar(
            select(func.max(ScheduledGmailEscrowPermit.slot_not_before)).where(
                ScheduledGmailEscrowPermit.quota_local_date == quota_date,
                ScheduledGmailEscrowPermit.status.in_(
                    {"reserved", "consuming", "accepted_unverified", "expired_unreconciled"}
                ),
            )
        )
        # Keep the beginning of each day available to the central sender, too.
        cursor = day_start + timedelta(seconds=gap_seconds * 2.0)
        if quota_date == now.astimezone(ZoneInfo("Europe/Budapest")).date():
            cursor = max(cursor, now + timedelta(seconds=gap_seconds * 2.0))
        if pacing_next is not None and day_start <= pacing_next < day_end:
            cursor = max(
                cursor,
                pacing_next + timedelta(seconds=gap_seconds * 2.0),
            )
        if latest_existing is not None:
            cursor = max(
                cursor,
                _aware(latest_existing) + timedelta(seconds=offline_spacing),
            )
        day_slots = 0
        while len(slots) < desired_count and day_slots < day_headroom:
            slot_end = cursor + timedelta(seconds=slot_width)
            if slot_end >= day_end:
                break
            slots.append((quota_date, day_start, day_end, cursor, slot_end))
            day_slots += 1
            cursor += timedelta(seconds=offline_spacing)
        if len(slots) >= desired_count:
            break
    return slots


def _escrow_candidate_preflight(
    db: Session,
    *,
    row: OutreachMessage,
    signal: GrowthSignal,
    principal: ScheduledGmailClientPrincipal,
) -> tuple[dict[str, Any], str]:
    principal.assert_scope(
        permission="escrow_prefetch",
        sender_email=row.sender_email,
        motor_key=row.motor_key,
    )
    if not writes_unlocked() or not _control_enabled(db, row.motor_key):
        raise GrowthRegistryError("growth_writes_locked")
    registry = GrowthRegistry.load()
    preclaim = _preclaim_outreach_readiness_reason(db, registry, row)
    if preclaim:
        raise GrowthRegistryError(preclaim)
    if not _payload_matches(row) or not _release_matches(row):
        raise GrowthRegistryError("outreach_payload_or_release_drift")
    metadata = _canonical_metadata(row)
    _assert_current_canonical_screening(signal, metadata)
    _assert_public_land_evidence_manifest(db, signal, metadata)
    recipient_type = str(metadata.get("recipient_type") or "")
    if (
        signal.signal_type == "residential_building_plot"
        or recipient_type not in ESCROW_STABLE_RECIPIENT_TYPES
    ):
        raise GrowthRegistryError("scheduled_gmail_escrow_live_evidence_required_no_send")
    if _recipient_suppressed(db, row.recipient_email):
        raise GrowthRegistryError("global_suppression")
    binding = registry.brand_binding(row.brand_id)
    _verified_sender(db, binding)
    SMTPEmailAdapter(binding).live_preflight(delivery_scope="external_customer")
    if binding.sender_email != row.sender_email:
        raise GrowthRegistryError("brand_sender_changed_after_queue")
    cooldown_errors = _rate_errors(
        db,
        binding,
        row.recipient_email,
        exclude_outreach_id=row.outreach_id,
    )
    if cooldown_errors:
        raise GrowthRegistryError(";".join(cooldown_errors))
    readiness_reason = _authoritative_send_readiness_reason(db, registry, signal)
    if readiness_reason:
        raise GrowthRegistryError(readiness_reason)
    official_required = _official_source_required(db, row, signal, registry)
    if official_required:
        _assert_official_source_evidence_fresh(
            db,
            row,
            signal,
            official_required=True,
            registry=registry,
        )
    _assert_outreach_reputation_healthy(db)
    return metadata, recipient_type


def _candidate_outreach_ids(
    db: Session,
    *,
    data: ScheduledGmailEscrowBundleIn,
    principal: ScheduledGmailClientPrincipal,
    already_reserved: set[str],
) -> list[str]:
    if data.candidates:
        return [
            candidate.outreach_id
            for candidate in data.candidates
            if candidate.outreach_id not in already_reserved
        ]
    rows = db.scalars(
        select(OutreachMessage)
        .where(
            OutreachMessage.sequence_step == 0,
            OutreachMessage.status == "queued",
            OutreachMessage.available_at <= utcnow(),
            func.lower(OutreachMessage.sender_email).in_(
                sorted(principal.sender_emails)
            ),
            func.lower(OutreachMessage.motor_key).in_(sorted(principal.motor_keys)),
        )
        .order_by(OutreachMessage.available_at, OutreachMessage.id)
        .limit(max(data.desired_permit_count * 5, data.desired_permit_count))
    )
    return [row.outreach_id for row in rows if row.outreach_id not in already_reserved]


def _assert_explicit_escrow_candidate_request_scope(
    db: Session,
    *,
    data: ScheduledGmailEscrowBundleIn,
    principal: ScheduledGmailClientPrincipal,
    already_reserved: set[str] | None = None,
) -> None:
    if not data.candidates:
        return
    skipped = already_reserved or set()
    requested = {
        candidate.outreach_id: candidate.expected_payload_sha256
        for candidate in data.candidates
        if candidate.outreach_id not in skipped
    }
    rows = {
        row.outreach_id: row
        for row in db.scalars(
            select(OutreachMessage).where(
                OutreachMessage.outreach_id.in_(sorted(requested))
            )
        )
    }
    for outreach_id in requested:
        row = rows.get(outreach_id)
        if row is None:
            continue
        # Request-level ownership and exact-hash conflicts are rejected before
        # the mutable per-candidate failure path.  A caller can therefore never
        # defer or annotate another scheduled client's queue row.
        principal.assert_scope(
            permission="escrow_prefetch",
            sender_email=row.sender_email,
            motor_key=row.motor_key,
        )
        # Missing/stale/hash-mismatched rows are isolated and audited in the
        # per-candidate loop.  Only an ownership/scope violation rejects the
        # complete request before any row can be mutated.


def _reject_escrow_candidate_without_mutation(
    db: Session,
    *,
    outreach_id: str,
    reason: str,
    principal: ScheduledGmailClientPrincipal,
) -> None:
    db.rollback()
    audit(
        db,
        actor=_escrow_claimed_by(principal.client_id),
        action="growth_scheduled_gmail_escrow_candidate_rejected_no_send",
        entity_type="growth_outreach",
        entity_id=outreach_id,
        after={"reason": reason, "next_candidate_continues": True},
    )
    db.commit()


def _defer_escrow_candidate(
    db: Session,
    *,
    outreach_id: str,
    reason: str,
    principal: ScheduledGmailClientPrincipal,
) -> None:
    db.rollback()
    row = db.scalar(
        select(OutreachMessage)
        .where(
            OutreachMessage.outreach_id == outreach_id,
            func.lower(OutreachMessage.sender_email).in_(
                sorted(principal.sender_emails)
            ),
            func.lower(OutreachMessage.motor_key).in_(
                sorted(principal.motor_keys)
            ),
        )
        .with_for_update()
    )
    if row is not None and row.status == "queued":
        row.last_error = f"scheduled_gmail_escrow_prefetch_deferred:{reason}"[:2000]
        row.available_at = max(
            _aware(row.available_at),
            utcnow() + timedelta(minutes=15),
        )
        audit(
            db,
            actor=_escrow_claimed_by(principal.client_id),
            action="growth_scheduled_gmail_escrow_candidate_deferred_no_send",
            entity_type="growth_outreach",
            entity_id=outreach_id,
            after={"reason": reason, "next_candidate_continues": True},
        )
    db.commit()


def issue_scheduled_gmail_escrow_bundle(
    db: Session,
    data: ScheduledGmailEscrowBundleIn,
    principal: ScheduledGmailClientPrincipal,
) -> dict[str, Any]:
    principal.assert_scope(permission="escrow_prefetch")
    now = utcnow()
    zone = ZoneInfo("Europe/Budapest")
    today = now.astimezone(zone).date()
    if not data.quota_local_dates or data.quota_local_dates[0] < today:
        raise GrowthRegistryError("scheduled_gmail_escrow_past_quota_date")
    horizon_days = (data.quota_local_dates[-1] - today).days + 1
    principal.assert_offline_escrow_scope(
        permit_count=data.desired_permit_count,
        horizon_days=horizon_days,
    )
    client_public_key_pem, client_public_key_sha256 = (
        _registered_client_public_key_snapshot(principal)
    )
    created_bundle = False
    request_policy_sha256 = _escrow_request_policy_sha256(data)

    existing = db.scalar(
        select(ScheduledGmailEscrowBundle)
        .where(ScheduledGmailEscrowBundle.request_id == data.request_id)
        .with_for_update()
    )
    if existing is not None:
        if existing.client_id != principal.client_id:
            raise GrowthRegistryError("scheduled_gmail_escrow_request_owned_by_other_client")
        if (
            existing.first_quota_local_date != data.quota_local_dates[0]
            or existing.last_quota_local_date != data.quota_local_dates[-1]
            or existing.policy_sha256 != request_policy_sha256
        ):
            raise GrowthRegistryError("scheduled_gmail_escrow_request_conflict")
        if existing.client_public_key_sha256 is None:
            if existing.client_key_id != principal.client_key_id:
                raise GrowthRegistryError(
                    "scheduled_gmail_escrow_building_client_key_changed"
                )
            existing.client_public_key_sha256 = client_public_key_sha256
            existing.client_public_key_pem = client_public_key_pem
            db.commit()
        else:
            _bundle_client_public_key_snapshot(existing)
        if existing.status != "building":
            db.commit()
            return _bundle_response(
                db,
                existing,
                include_transport_secrets=True,
            )
        bundle = existing
        desired_count = existing.permit_count
    else:
        _assert_explicit_escrow_candidate_request_scope(
            db,
            data=data,
            principal=principal,
        )
        first_start, _first_end = _escrow_day_bounds(data.quota_local_dates[0])
        _last_start, last_end = _escrow_day_bounds(data.quota_local_dates[-1])
        bundle = ScheduledGmailEscrowBundle(
            bundle_id="SGB-" + uuid4().hex.upper(),
            request_id=data.request_id,
            client_id=principal.client_id,
            client_key_id=str(principal.client_key_id),
            status="building",
            permit_count=data.desired_permit_count,
            first_quota_local_date=data.quota_local_dates[0],
            last_quota_local_date=data.quota_local_dates[-1],
            valid_from=max(now, first_start),
            expires_at=last_end,
            policy_sha256=request_policy_sha256,
            client_registry_sha256=principal.registry_sha256,
            client_public_key_sha256=client_public_key_sha256,
            client_public_key_pem=client_public_key_pem,
            manifest_sha256=None,
            signing_key_id=escrow_signing_key_id(),
            manifest_signature=None,
            issued_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(bundle)
        db.commit()
        created_bundle = True
        desired_count = data.desired_permit_count

    existing_permits = list(
        db.scalars(
            select(ScheduledGmailEscrowPermit)
            .where(ScheduledGmailEscrowPermit.bundle_id == bundle.bundle_id)
            .order_by(ScheduledGmailEscrowPermit.permit_index)
        )
    )
    remaining = max(0, desired_count - len(existing_permits))
    slot_probe = _escrow_slots(
        db,
        quota_dates=list(data.quota_local_dates),
        desired_count=1,
        now=now,
    )
    if remaining and not slot_probe:
        if created_bundle:
            db.delete(bundle)
            db.commit()
        raise GrowthRegistryError("outreach_budapest_day_limit_reached_no_send")
    existing_ids = {permit.outreach_id for permit in existing_permits}
    if not created_bundle:
        _assert_explicit_escrow_candidate_request_scope(
            db,
            data=data,
            principal=principal,
            already_reserved=existing_ids,
        )
    candidate_ids = _candidate_outreach_ids(
        db,
        data=data,
        principal=principal,
        already_reserved=existing_ids,
    )
    expected_hashes = {
        candidate.outreach_id: candidate.expected_payload_sha256
        for candidate in data.candidates
    }
    permit_index = len(existing_permits)

    for outreach_id in candidate_ids:
        if permit_index >= desired_count:
            break
        _lock_outreach_claim_capacity(db)
        # Slot selection must happen while the shared claim/capacity advisory
        # lock is held.  Two different clients may build bundles concurrently;
        # a pre-lock snapshot could otherwise allocate the same account pacing
        # window twice because the database intentionally has no cross-row
        # range exclusion constraint.
        available_slots = _escrow_slots(
            db,
            quota_dates=list(data.quota_local_dates),
            desired_count=1,
            now=now,
        )
        if not available_slots:
            db.rollback()
            break
        slot = available_slots[0]
        row = db.scalar(
            select(OutreachMessage)
            .where(OutreachMessage.outreach_id == outreach_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if row is None or row.status != "queued" or row.sequence_step != 0:
            if data.candidates:
                _reject_escrow_candidate_without_mutation(
                    db,
                    outreach_id=outreach_id,
                    reason="scheduled_gmail_escrow_candidate_conflict",
                    principal=principal,
                )
            else:
                db.rollback()
            continue
        try:
            principal.assert_scope(
                permission="escrow_prefetch",
                sender_email=row.sender_email,
                motor_key=row.motor_key,
            )
        except ValueError as exc:
            db.rollback()
            raise GrowthRegistryError(str(exc)) from exc
        expected_hash = expected_hashes.get(outreach_id)
        if expected_hash and not hmac.compare_digest(
            expected_hash, row.payload_sha256
        ):
            _reject_escrow_candidate_without_mutation(
                db,
                outreach_id=outreach_id,
                reason="scheduled_gmail_escrow_payload_hash_mismatch",
                principal=principal,
            )
            continue
        try:
            signal = db.scalar(
                select(GrowthSignal)
                .where(GrowthSignal.signal_id == row.signal_id)
                .with_for_update()
            )
            if signal is None:
                raise GrowthRegistryError("growth_signal_missing")
            _metadata, _recipient_type = _escrow_candidate_preflight(
                db,
                row=row,
                signal=signal,
                principal=principal,
            )
            quota_date, day_start, day_end, slot_start, slot_end = slot
            claimed_by = _escrow_claimed_by(principal.client_id)
            row.status = "claimed"
            row.claimed_by = claimed_by
            row.claimed_at = now
            row.lease_expires_at = None
            row.attempt_count += 1
            row.last_error = None
            guard = claim_global_recipient_delivery(
                db,
                recipients=[row.recipient_email],
                identity_sha256=row.idempotency_key,
                message_type="growth_outreach",
                tenant_scope="imperial-holding",
                now=now,
                commit=False,
            )
            if not guard.may_send or not guard.claim_token:
                raise GrowthRegistryError(
                    f"global_recipient_guard_no_send:{guard.decision}"
                )
            lease_id = "SGL-" + uuid4().hex.upper()
            lease_nonce = token_urlsafe(32)
            from .service import _scheduled_gmail_lease_token

            lease_token = _scheduled_gmail_lease_token(
                lease_id=lease_id,
                client_id=principal.client_id,
                outreach_id=row.outreach_id,
                token_nonce=lease_nonce,
            )
            lease = ScheduledGmailLease(
                lease_id=lease_id,
                outreach_id=row.outreach_id,
                client_id=principal.client_id,
                token_nonce=lease_nonce,
                lease_token_sha256=hashlib.sha256(lease_token.encode()).hexdigest(),
                payload_sha256=row.payload_sha256,
                quota_local_date=quota_date,
                status="authorized",
                global_guard_claim_token=guard.claim_token,
                expires_at=slot_end,
                authorized_at=slot_start,
                created_at=now,
                updated_at=now,
            )
            db.add(lease)
            db.add(
                ScheduledGmailLeaseRequest(
                    request_id=f"escrow:{lease_id}",
                    client_id=principal.client_id,
                    lease_id=lease_id,
                    outreach_id=row.outreach_id,
                    status="authorized",
                    created_at=now,
                    updated_at=now,
                )
            )
            # The production session disables autoflush.  Persist the lease
            # parent (and its request ledger row) before inserting the escrow
            # permit that references it; PostgreSQL enforces this FK ordering
            # even though SQLite fixtures may not.
            db.flush()
            payload = _exact_transport_payload(row)
            exact_payload_sha256 = escrow_sha256(payload)
            permit_id = "SGP-" + uuid4().hex.upper()
            permit_nonce = token_urlsafe(32)
            permit_token = _escrow_permit_token(
                permit_id=permit_id,
                client_id=principal.client_id,
                outreach_id=row.outreach_id,
                nonce=permit_nonce,
            )
            guard_hash = hashlib.sha256(guard.claim_token.encode()).hexdigest()
            permit = ScheduledGmailEscrowPermit(
                permit_id=permit_id,
                bundle_id=bundle.bundle_id,
                lease_id=lease_id,
                outreach_id=row.outreach_id,
                client_id=principal.client_id,
                client_key_id=str(principal.client_key_id),
                permit_index=permit_index,
                status="reserved",
                sender_email=row.sender_email,
                motor_key=row.motor_key,
                payload_sha256=row.payload_sha256,
                exact_payload_sha256=exact_payload_sha256,
                outreach_idempotency_key=row.idempotency_key,
                quota_local_date=quota_date,
                day_start_utc=day_start,
                day_end_utc=day_end,
                slot_not_before=slot_start,
                slot_not_after=slot_end,
                permit_token_nonce=permit_nonce,
                permit_token_sha256=hashlib.sha256(permit_token.encode()).hexdigest(),
                global_guard_claim_token=guard.claim_token,
                global_guard_claim_token_sha256=guard_hash,
                permit_manifest_sha256="0" * 64,
                signing_key_id=bundle.signing_key_id,
                permit_signature="pending",
                quota_reserved_at=now,
                last_client_sequence=0,
                created_at=now,
                updated_at=now,
            )
            manifest = _permit_manifest(permit, payload=payload)
            manifest_sha256, key_id, signature = sign_escrow_manifest(manifest)
            permit.permit_manifest_sha256 = manifest_sha256
            permit.signing_key_id = key_id
            permit.permit_signature = signature
            db.add(permit)
            try:
                current_receipt = json.loads(row.receipt_json or "{}")
            except (TypeError, json.JSONDecodeError):
                current_receipt = {}
            current_receipt["scheduled_gmail_offline_escrow"] = {
                "bundle_id": bundle.bundle_id,
                "permit_id": permit_id,
                "client_id": principal.client_id,
                "quota_local_date": quota_date.isoformat(),
                "slot_not_before": slot_start.isoformat(),
                "slot_not_after": slot_end.isoformat(),
                "provider_transport_called": False,
            }
            row.receipt_json = canonical_json(current_receipt)
            db.flush()
            usage = _outreach_budapest_day_usage(db, slot_start)
            if usage.effective_reserved_count > usage.limit:
                raise GrowthRegistryError("outreach_budapest_day_limit_reached_no_send")
            audit(
                db,
                actor=claimed_by,
                action="growth_scheduled_gmail_escrow_permit_reserved",
                entity_type="growth_outreach",
                entity_id=row.outreach_id,
                after={
                    "bundle_id": bundle.bundle_id,
                    "permit_id": permit_id,
                    "quota_local_date": quota_date.isoformat(),
                    "slot_not_before": slot_start.isoformat(),
                    "slot_not_after": slot_end.isoformat(),
                    "effective_reserved_count": usage.effective_reserved_count,
                },
            )
            db.commit()
            permit_index += 1
        except IntegrityError:
            db.rollback()
            if data.candidates:
                _reject_escrow_candidate_without_mutation(
                    db,
                    outreach_id=outreach_id,
                    reason="scheduled_gmail_escrow_candidate_conflict",
                    principal=principal,
                )
            continue
        except (GrowthRegistryError, EmailDeliveryError, RuntimeError, ValueError) as exc:
            _defer_escrow_candidate(
                db,
                outreach_id=outreach_id,
                reason=str(exc),
                principal=principal,
            )
            continue

    bundle = db.scalar(
        select(ScheduledGmailEscrowBundle)
        .where(ScheduledGmailEscrowBundle.bundle_id == bundle.bundle_id)
        .with_for_update()
    )
    if bundle is None:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_missing")
    permits = list(
        db.scalars(
            select(ScheduledGmailEscrowPermit)
            .where(ScheduledGmailEscrowPermit.bundle_id == bundle.bundle_id)
            .order_by(ScheduledGmailEscrowPermit.permit_index)
        )
    )
    if not permits:
        db.delete(bundle)
        db.commit()
        raise GrowthRegistryError("scheduled_gmail_escrow_no_safe_permits")
    bundle.permit_count = len(permits)
    issued_at = utcnow()
    bundle.issued_at = issued_at
    manifest = _bundle_manifest(bundle, permits)
    manifest_sha256, key_id, signature = sign_escrow_manifest(manifest)
    bundle.status = "active"
    bundle.manifest_sha256 = manifest_sha256
    bundle.signing_key_id = key_id
    bundle.manifest_signature = signature
    bundle.updated_at = issued_at
    audit(
        db,
        actor=_escrow_claimed_by(principal.client_id),
        action="growth_scheduled_gmail_escrow_bundle_issued",
        entity_type="growth_scheduled_gmail_escrow_bundle",
        entity_id=bundle.bundle_id,
        after={
            "request_id": data.request_id,
            "requested_permits": data.desired_permit_count,
            "issued_permits": len(permits),
            "first_quota_local_date": bundle.first_quota_local_date.isoformat(),
            "last_quota_local_date": bundle.last_quota_local_date.isoformat(),
            "manifest_sha256": manifest_sha256,
        },
    )
    db.commit()
    return _bundle_response(db, bundle, include_transport_secrets=True)


def scheduled_gmail_escrow_bundle_status(
    db: Session,
    bundle_id: str,
    principal: ScheduledGmailClientPrincipal,
) -> dict[str, Any]:
    principal.assert_scope(permission="read")
    bundle = db.scalar(
        select(ScheduledGmailEscrowBundle).where(
            ScheduledGmailEscrowBundle.bundle_id == bundle_id
        )
    )
    if bundle is None:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_missing")
    if bundle.client_id != principal.client_id:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_owned_by_other_client")
    return _bundle_response(db, bundle, include_transport_secrets=False)


def _escrow_event_manifest(
    event: ScheduledGmailEscrowSyncEventIn,
    *,
    permit: ScheduledGmailEscrowPermit,
    principal: ScheduledGmailClientPrincipal,
    bundle: ScheduledGmailEscrowBundle,
) -> dict[str, Any]:
    occurred_at = _aware(event.occurred_at).astimezone(UTC).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    return {
        "version": "scheduled-gmail-offline-sync-event-v1",
        "event_id": event.event_id,
        "permit_id": permit.permit_id,
        "bundle_id": permit.bundle_id,
        "client_id": principal.client_id,
        "client_key_id": event.client_key_id,
        "client_sequence": event.client_sequence,
        "event_type": event.event_type,
        "occurred_at": occurred_at,
        "payload_sha256": event.payload_sha256,
        "exact_payload_sha256": event.exact_payload_sha256,
        "permit_token_sha256": hashlib.sha256(event.permit_token.encode()).hexdigest(),
        "previous_event_sha256": event.previous_event_sha256,
        "client_public_key_sha256": bundle.client_public_key_sha256,
        "provider_transport_called": event.provider_transport_called,
        "provider_message_id": event.provider_message_id,
        "reason": event.reason,
    }


def _verify_escrow_event(
    event: ScheduledGmailEscrowSyncEventIn,
    *,
    permit: ScheduledGmailEscrowPermit,
    principal: ScheduledGmailClientPrincipal,
    bundle: ScheduledGmailEscrowBundle,
) -> dict[str, Any]:
    if permit.client_id != principal.client_id:
        raise GrowthRegistryError("scheduled_gmail_escrow_permit_owned_by_other_client")
    if bundle.client_id != principal.client_id or permit.bundle_id != bundle.bundle_id:
        raise GrowthRegistryError("scheduled_gmail_escrow_event_bundle_conflict")
    if (
        event.client_key_id != permit.client_key_id
        or event.client_key_id != bundle.client_key_id
    ):
        raise GrowthRegistryError("scheduled_gmail_escrow_client_key_mismatch")
    if event.payload_sha256 != permit.payload_sha256:
        raise GrowthRegistryError("scheduled_gmail_escrow_event_payload_hash_mismatch")
    if event.exact_payload_sha256 != permit.exact_payload_sha256:
        raise GrowthRegistryError("scheduled_gmail_escrow_event_exact_payload_hash_mismatch")
    if not _escrow_permit_token_matches(permit, event.permit_token):
        raise GrowthRegistryError("scheduled_gmail_escrow_permit_token_invalid")
    if event.client_sequence != permit.last_client_sequence + 1:
        raise GrowthRegistryError("scheduled_gmail_escrow_event_sequence_conflict")
    if event.previous_event_sha256 != permit.last_event_sha256:
        raise GrowthRegistryError("scheduled_gmail_escrow_event_chain_conflict")
    public_key_pem, public_key_sha256 = _bundle_client_public_key_snapshot(bundle)
    manifest = _escrow_event_manifest(
        event,
        permit=permit,
        principal=principal,
        bundle=bundle,
    )
    if manifest["client_public_key_sha256"] != public_key_sha256:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_client_key_drift")
    from .service import _verify_scheduled_gmail_escrow_client_event

    _verify_scheduled_gmail_escrow_client_event(
        manifest,
        expected_sha256=event.event_sha256,
        signature=event.client_signature,
        public_key_pem=public_key_pem,
    )
    return manifest


def _escrow_event_row(
    event: ScheduledGmailEscrowSyncEventIn,
    *,
    permit: ScheduledGmailEscrowPermit,
    principal: ScheduledGmailClientPrincipal,
    bundle: ScheduledGmailEscrowBundle,
    processing_status: str = "received",
) -> ScheduledGmailEscrowSyncEvent:
    now = utcnow()
    return ScheduledGmailEscrowSyncEvent(
        event_id=event.event_id,
        permit_id=permit.permit_id,
        bundle_id=permit.bundle_id,
        client_id=principal.client_id,
        client_sequence=event.client_sequence,
        event_type=event.event_type,
        processing_status=processing_status,
        occurred_at=_aware(event.occurred_at),
        payload_sha256=event.payload_sha256,
        exact_payload_sha256=event.exact_payload_sha256,
        permit_token_sha256=hashlib.sha256(event.permit_token.encode()).hexdigest(),
        previous_event_sha256=event.previous_event_sha256,
        event_sha256=event.event_sha256,
        client_key_id=event.client_key_id,
        client_public_key_sha256=str(bundle.client_public_key_sha256),
        client_signature=event.client_signature,
        provider_transport_called=event.provider_transport_called,
        provider_message_id=event.provider_message_id,
        reason=event.reason,
        received_at=now,
        processed_at=None,
        created_at=now,
        updated_at=now,
    )


def _update_escrow_bundle_status(
    db: Session,
    *,
    bundle_id: str,
    now: datetime,
) -> ScheduledGmailEscrowBundle:
    # SessionLocal deliberately disables autoflush.  Aggregate status must see
    # the permit transition made by the current event before it queries.
    db.flush()
    bundle = db.scalar(
        select(ScheduledGmailEscrowBundle)
        .where(ScheduledGmailEscrowBundle.bundle_id == bundle_id)
        .with_for_update()
    )
    if bundle is None:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_missing")
    statuses = set(
        db.scalars(
            select(ScheduledGmailEscrowPermit.status).where(
                ScheduledGmailEscrowPermit.bundle_id == bundle_id
            )
        )
    )
    if statuses and statuses <= {"sent", "aborted"}:
        bundle.status = "reconciled"
        bundle.reconciled_at = now
    elif statuses & {"consuming", "accepted_unverified", "expired_unreconciled"}:
        bundle.status = "pending_sync"
    else:
        bundle.status = "active"
    bundle.updated_at = now
    return bundle


def _load_escrow_event_context(
    db: Session,
    *,
    permit_id: str,
) -> tuple[
    OutreachMessage,
    ScheduledGmailEscrowPermit,
    ScheduledGmailLease,
    ScheduledGmailLeaseRequest,
]:
    permit_lookup = db.scalar(
        select(ScheduledGmailEscrowPermit).where(
            ScheduledGmailEscrowPermit.permit_id == permit_id
        )
    )
    if permit_lookup is None:
        raise GrowthRegistryError("scheduled_gmail_escrow_permit_missing")
    row = db.scalar(
        select(OutreachMessage)
        .where(OutreachMessage.outreach_id == permit_lookup.outreach_id)
        .with_for_update()
    )
    if row is None:
        raise GrowthRegistryError("scheduled_gmail_escrow_outreach_missing")
    permit = db.scalar(
        select(ScheduledGmailEscrowPermit)
        .where(ScheduledGmailEscrowPermit.permit_id == permit_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if permit is None or permit.outreach_id != row.outreach_id:
        raise GrowthRegistryError("scheduled_gmail_escrow_permit_state_conflict")
    lease = db.scalar(
        select(ScheduledGmailLease)
        .where(ScheduledGmailLease.lease_id == permit.lease_id)
        .with_for_update()
    )
    request = db.scalar(
        select(ScheduledGmailLeaseRequest)
        .where(ScheduledGmailLeaseRequest.lease_id == permit.lease_id)
        .order_by(ScheduledGmailLeaseRequest.id.desc())
        .limit(1)
        .with_for_update()
    )
    if lease is None or request is None:
        raise GrowthRegistryError("scheduled_gmail_escrow_lease_state_missing")
    return row, permit, lease, request


def _contain_escrow_transport_ambiguous(
    db: Session,
    *,
    row: OutreachMessage,
    permit: ScheduledGmailEscrowPermit,
    lease: ScheduledGmailLease,
    request: ScheduledGmailLeaseRequest,
    event_row: ScheduledGmailEscrowSyncEvent,
    event: ScheduledGmailEscrowSyncEventIn,
) -> None:
    contained_at = _aware(event.occurred_at)
    try:
        receipt = json.loads(row.receipt_json or "{}")
    except (TypeError, json.JSONDecodeError):
        receipt = {}
    receipt.update(
        {
            "provider": "gmail_api",
            "accepted": True,
            "scheduled_gmail_offline_escrow": {
                "bundle_id": permit.bundle_id,
                "permit_id": permit.permit_id,
                "client_id": permit.client_id,
                "provider_transport_called": True,
            },
            "delivery_verification": {
                "status": "pending_verification",
                "retry_safe": False,
                "provider_message_id": event.provider_message_id,
                "reserved_at": contained_at.isoformat(),
                "detail": {
                    "reason": event.reason or "scheduled_gmail_offline_transport_ambiguous"
                },
            },
        }
    )
    row.status = "claimed"
    row.claimed_by = None
    row.claimed_at = None
    row.lease_expires_at = None
    row.provider_message_id = event.provider_message_id
    row.receipt_json = canonical_json(receipt)
    row.last_error = event.reason or "scheduled_gmail_offline_transport_ambiguous"
    permit.status = "accepted_unverified"
    permit.consumed_at = permit.consumed_at or contained_at
    permit.provider_message_id = event.provider_message_id
    permit.provider_accepted_at = contained_at
    permit.last_client_sequence = event.client_sequence
    permit.last_event_sha256 = event.event_sha256
    permit.last_synced_at = utcnow()
    permit.updated_at = utcnow()
    lease.status = "accepted_unverified"
    lease.provider_message_id = event.provider_message_id
    lease.accepted_at = contained_at
    lease.quota_local_date = contained_at.astimezone(
        ZoneInfo("Europe/Budapest")
    ).date()
    lease.updated_at = utcnow()
    request.status = "accepted_unverified"
    request.updated_at = utcnow()
    event_row.processing_status = "pending_verification"
    event_row.processed_at = utcnow()
    event_row.updated_at = utcnow()
    try:
        _record_outreach_pacing_success(db, now=contained_at)
    except (GrowthRegistryError, RuntimeError, ValueError) as exc:
        receipt["delivery_verification"]["detail"]["pacing_error"] = str(exc)
        row.receipt_json = canonical_json(receipt)
    # Commit the no-resend state before secondary ledgers.  Any later error may
    # reduce availability but can never make this transport attempt sendable.
    db.commit()

    row, permit, lease, _request = _load_escrow_event_context(
        db, permit_id=permit.permit_id
    )
    try:
        fail_global_recipient_delivery(
            db,
            recipients=[row.recipient_email],
            identity_sha256=row.idempotency_key,
            claim_token=permit.global_guard_claim_token,
            error=row.last_error or "scheduled_gmail_offline_transport_ambiguous",
            accepted_unverified=True,
            provider_message_id=event.provider_message_id,
            now=contained_at,
            commit=False,
        )
        db.commit()
    except RuntimeError:
        db.rollback()


def _release_escrow_permit_pretransport(
    db: Session,
    *,
    row: OutreachMessage,
    permit: ScheduledGmailEscrowPermit,
    lease: ScheduledGmailLease,
    request: ScheduledGmailLeaseRequest,
    principal: ScheduledGmailClientPrincipal,
    reason: str,
    allow_consuming: bool,
    event: ScheduledGmailEscrowSyncEventIn | None = None,
    event_row: ScheduledGmailEscrowSyncEvent | None = None,
) -> ScheduledGmailEscrowBundle:
    previous_permit_status = permit.status
    allowed_statuses = {"reserved", "consuming"} if allow_consuming else {"reserved"}
    if permit.status not in allowed_statuses:
        raise GrowthRegistryError("scheduled_gmail_escrow_abort_not_pre_transport")
    if permit.status == "consuming":
        # Only a verified, exact-next signed journal event may unwind the local
        # READY -> CONSUMING transition.  The direct abort endpoint deliberately
        # cannot take this path.
        if (
            event is None
            or event_row is None
            or event.event_type not in {"pretransport_aborted", "expired_unused"}
            or event.provider_transport_called is not False
            or event.provider_message_id is not None
            or event.client_sequence != permit.last_client_sequence + 1
            or event.previous_event_sha256 != permit.last_event_sha256
        ):
            raise GrowthRegistryError("scheduled_gmail_escrow_abort_not_pre_transport")
    if event is not None and (
        event.provider_transport_called is not False
        or event.provider_message_id is not None
        or event_row is None
    ):
        raise GrowthRegistryError("scheduled_gmail_escrow_abort_not_pre_transport")
    if (
        lease.status != "authorized"
        or request.status != "authorized"
        or row.status != "claimed"
        or row.claimed_by != _escrow_claimed_by(principal.client_id)
        or row.provider_message_id is not None
        or lease.provider_message_id is not None
        or permit.provider_message_id is not None
        or permit.provider_accepted_at is not None
        or permit.verified_at is not None
    ):
        raise GrowthRegistryError("scheduled_gmail_escrow_abort_not_pre_transport")
    try:
        receipt = json.loads(row.receipt_json or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise GrowthRegistryError(
            "scheduled_gmail_escrow_abort_receipt_invalid"
        ) from exc
    escrow_receipt = receipt.get("scheduled_gmail_offline_escrow")
    verification = receipt.get("delivery_verification")
    if (
        not isinstance(escrow_receipt, dict)
        or escrow_receipt.get("provider_transport_called") is not False
        or (
            isinstance(verification, dict)
            and verification.get("status") == "pending_verification"
        )
    ):
        raise GrowthRegistryError("scheduled_gmail_escrow_abort_not_pre_transport")

    now = utcnow()
    fail_global_recipient_delivery(
        db,
        recipients=[row.recipient_email],
        identity_sha256=row.idempotency_key,
        claim_token=permit.global_guard_claim_token,
        error=reason,
        accepted_unverified=False,
        now=now,
        commit=False,
    )
    escrow_receipt["status"] = "aborted_pretransport"
    escrow_receipt["provider_transport_called"] = False
    escrow_receipt["aborted_at"] = now.isoformat()
    receipt["scheduled_gmail_offline_escrow"] = escrow_receipt
    row.receipt_json = canonical_json(receipt)
    row.status = "queued"
    row.claimed_by = None
    row.claimed_at = None
    row.lease_expires_at = None
    row.attempt_count = max(0, row.attempt_count - 1)
    row.last_error = "scheduled_gmail_escrow_pretransport_abort"
    lease.status = "aborted"
    lease.aborted_at = now
    lease.abort_reason = reason
    lease.global_guard_claim_token = None
    lease.updated_at = now
    request.status = "aborted"
    request.updated_at = now
    permit.status = "aborted"
    permit.aborted_at = now
    permit.abort_reason = reason
    permit.last_synced_at = now
    permit.updated_at = now
    if event is not None and event_row is not None:
        permit.last_client_sequence = event.client_sequence
        permit.last_event_sha256 = event.event_sha256
        event_row.processing_status = "applied"
        event_row.processed_at = now
        event_row.updated_at = now
    bundle = _update_escrow_bundle_status(
        db,
        bundle_id=permit.bundle_id,
        now=now,
    )
    audit(
        db,
        actor=_escrow_claimed_by(principal.client_id),
        action="growth_scheduled_gmail_escrow_permit_aborted_pretransport",
        entity_type="growth_outreach",
        entity_id=row.outreach_id,
        after={
            "bundle_id": permit.bundle_id,
            "permit_id": permit.permit_id,
            "provider_transport_called": False,
            "signed_event_id": event.event_id if event is not None else None,
            "previous_permit_status": previous_permit_status,
            "reason": reason,
        },
    )
    db.commit()
    return bundle


def _sync_single_scheduled_gmail_escrow_event(
    db: Session,
    data: ScheduledGmailEscrowSyncIn,
    principal: ScheduledGmailClientPrincipal,
) -> dict[str, Any]:
    if len(data.events) != 1:
        raise GrowthRegistryError("scheduled_gmail_escrow_single_event_required")
    principal.assert_scope(permission="escrow_sync")
    bundle = db.scalar(
        select(ScheduledGmailEscrowBundle).where(
            ScheduledGmailEscrowBundle.bundle_id == data.bundle_id
        )
    )
    if bundle is None:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_missing")
    if bundle.client_id != principal.client_id:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_owned_by_other_client")
    results: list[dict[str, Any]] = []

    for event in data.events:
        resumable_event: ScheduledGmailEscrowSyncEvent | None = None
        existing = db.scalar(
            select(ScheduledGmailEscrowSyncEvent).where(
                ScheduledGmailEscrowSyncEvent.event_id == event.event_id
            )
        )
        if existing is not None:
            if (
                existing.event_sha256 != event.event_sha256
                or existing.client_id != principal.client_id
                or existing.permit_id != event.permit_id
            ):
                raise GrowthRegistryError("scheduled_gmail_escrow_event_id_conflict")
            if (
                event.event_type == "provider_accepted"
                and existing.processing_status in {"received", "pending_verification"}
            ):
                # Finalization commits its no-resend containment before this
                # outer escrow transaction marks the event applied.  A crash
                # in that narrow interval must resume readback/finalization,
                # not remain permanently stuck at `received`.
                resumable_event = existing
            else:
                results.append(
                    {
                        "event_id": existing.event_id,
                        "permit_id": existing.permit_id,
                        "status": existing.processing_status,
                        "processing_status": existing.processing_status,
                        "permit_status": db.scalar(
                            select(ScheduledGmailEscrowPermit.status).where(
                                ScheduledGmailEscrowPermit.permit_id == existing.permit_id
                            )
                        ),
                        "idempotent": True,
                    }
                )
                continue

        row, permit, lease, request = _load_escrow_event_context(
            db, permit_id=event.permit_id
        )
        if permit.bundle_id != data.bundle_id:
            raise GrowthRegistryError("scheduled_gmail_escrow_event_bundle_conflict")
        principal.assert_scope(
            permission="escrow_sync",
            sender_email=row.sender_email,
            motor_key=row.motor_key,
        )
        if resumable_event is None:
            _verify_escrow_event(
                event,
                permit=permit,
                principal=principal,
                bundle=bundle,
            )
            event_row = _escrow_event_row(
                event,
                permit=permit,
                principal=principal,
                bundle=bundle,
            )
            db.add(event_row)
        else:
            event_row = resumable_event

        if event.event_type == "permit_consumed":
            if permit.status == "reserved":
                permit.status = "consuming"
                permit.consumed_at = _aware(event.occurred_at)
            elif permit.status != "consuming":
                raise GrowthRegistryError("scheduled_gmail_escrow_permit_not_consumable")
            permit.last_client_sequence = event.client_sequence
            permit.last_event_sha256 = event.event_sha256
            permit.last_synced_at = utcnow()
            permit.updated_at = utcnow()
            event_row.processing_status = "applied"
            event_row.processed_at = utcnow()
            event_row.updated_at = utcnow()
            _update_escrow_bundle_status(db, bundle_id=permit.bundle_id, now=utcnow())
            db.commit()
        elif event.event_type == "provider_accepted":
            if permit.status not in {"reserved", "consuming", "accepted_unverified"}:
                raise GrowthRegistryError("scheduled_gmail_escrow_permit_not_reconcilable")
            permit.status = "consuming"
            permit.consumed_at = permit.consumed_at or _aware(event.occurred_at)
            permit.last_client_sequence = event.client_sequence
            permit.last_event_sha256 = event.event_sha256
            permit.last_synced_at = utcnow()
            event_row.processing_status = "received"
            from .service import (
                _scheduled_gmail_lease_token,
                finalize_scheduled_gmail_outreach,
            )

            lease_token = _scheduled_gmail_lease_token(
                lease_id=lease.lease_id,
                client_id=lease.client_id,
                outreach_id=lease.outreach_id,
                token_nonce=lease.token_nonce,
            )
            finalize_scheduled_gmail_outreach(
                db,
                lease.lease_id,
                ScheduledGmailFinalizeIn(
                    lease_token=lease_token,
                    provider_message_id=str(event.provider_message_id),
                ),
                principal,
            )
            row, permit, lease, _request = _load_escrow_event_context(
                db, permit_id=event.permit_id
            )
            persisted_event = db.scalar(
                select(ScheduledGmailEscrowSyncEvent)
                .where(ScheduledGmailEscrowSyncEvent.event_id == event.event_id)
                .with_for_update()
            )
            if persisted_event is None:
                raise GrowthRegistryError("scheduled_gmail_escrow_event_missing_after_finalize")
            now = utcnow()
            if lease.status == "sent":
                permit.status = "sent"
                permit.provider_message_id = lease.provider_message_id
                permit.provider_accepted_at = lease.accepted_at
                permit.provider_internal_date = lease.provider_internal_date
                permit.readback_mime_sha256 = lease.readback_mime_sha256
                permit.verified_at = lease.verified_at or now
                persisted_event.processing_status = "applied"
            else:
                permit.status = "accepted_unverified"
                permit.provider_message_id = lease.provider_message_id
                permit.provider_accepted_at = lease.accepted_at or _aware(event.occurred_at)
                persisted_event.processing_status = "pending_verification"
            permit.last_client_sequence = event.client_sequence
            permit.last_event_sha256 = event.event_sha256
            permit.last_synced_at = now
            permit.updated_at = now
            persisted_event.processed_at = now
            persisted_event.updated_at = now
            bundle = _update_escrow_bundle_status(
                db, bundle_id=permit.bundle_id, now=now
            )
            db.commit()
        elif event.event_type == "transport_ambiguous":
            if permit.status not in {"reserved", "consuming", "accepted_unverified"}:
                raise GrowthRegistryError("scheduled_gmail_escrow_permit_not_reconcilable")
            _contain_escrow_transport_ambiguous(
                db,
                row=row,
                permit=permit,
                lease=lease,
                request=request,
                event_row=event_row,
                event=event,
            )
            bundle = _update_escrow_bundle_status(
                db, bundle_id=permit.bundle_id, now=utcnow()
            )
            db.commit()
        elif event.event_type in {"pretransport_aborted", "expired_unused"}:
            _release_escrow_permit_pretransport(
                db,
                row=row,
                permit=permit,
                lease=lease,
                request=request,
                principal=principal,
                reason=event.reason or "offline permit unused before transport",
                allow_consuming=True,
                event=event,
                event_row=event_row,
            )
        else:  # pragma: no cover - Pydantic rejects unknown values.
            raise GrowthRegistryError("scheduled_gmail_escrow_event_type_invalid")

        refreshed = db.scalar(
            select(ScheduledGmailEscrowPermit).where(
                ScheduledGmailEscrowPermit.permit_id == event.permit_id
            )
        )
        persisted_event = db.scalar(
            select(ScheduledGmailEscrowSyncEvent).where(
                ScheduledGmailEscrowSyncEvent.event_id == event.event_id
            )
        )
        results.append(
            {
                "event_id": event.event_id,
                "permit_id": event.permit_id,
                "status": refreshed.status if refreshed is not None else "missing",
                "processing_status": (
                    persisted_event.processing_status
                    if persisted_event is not None
                    else "rejected"
                ),
                "permit_status": refreshed.status if refreshed is not None else "missing",
                "idempotent": False,
            }
        )

    bundle = db.scalar(
        select(ScheduledGmailEscrowBundle).where(
            ScheduledGmailEscrowBundle.bundle_id == data.bundle_id
        )
    )
    if bundle is None:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_missing")
    permit_statuses = {item["status"] for item in results}
    if "accepted_unverified" in permit_statuses:
        status = "accepted_unverified"
    elif permit_statuses and permit_statuses <= {"sent", "aborted"}:
        status = "reconciled" if bundle.status == "reconciled" else "sent"
    elif "sent" in permit_statuses:
        status = "sent"
    else:
        status = bundle.status
    return {
        "request_id": data.request_id,
        "bundle_id": data.bundle_id,
        "status": status,
        "events": results,
    }


def sync_scheduled_gmail_escrow_events(
    db: Session,
    data: ScheduledGmailEscrowSyncIn,
    principal: ScheduledGmailClientPrincipal,
) -> dict[str, Any]:
    principal.assert_scope(permission="escrow_sync")
    bundle = db.scalar(
        select(ScheduledGmailEscrowBundle).where(
            ScheduledGmailEscrowBundle.bundle_id == data.bundle_id
        )
    )
    if bundle is None:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_missing")
    if bundle.client_id != principal.client_id:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_owned_by_other_client")

    results: list[dict[str, Any]] = []
    for event_index, supplied_event in enumerate(data.events):
        try:
            event = (
                supplied_event
                if isinstance(supplied_event, ScheduledGmailEscrowSyncEventIn)
                else ScheduledGmailEscrowSyncEventIn.model_validate(supplied_event)
            )
        except ValueError:
            db.rollback()
            raw_event = supplied_event if isinstance(supplied_event, dict) else {}
            event_id = str(raw_event.get("event_id") or f"invalid-event-{event_index}")
            permit_id = str(raw_event.get("permit_id") or "invalid-permit")
            results.append(
                {
                    "event_id": event_id[:255],
                    "permit_id": permit_id[:255],
                    "status": "rejected",
                    "processing_status": "rejected",
                    "permit_status": "unknown",
                    "idempotent": False,
                    "error": "scheduled_gmail_escrow_event_schema_invalid",
                }
            )
            continue
        single = ScheduledGmailEscrowSyncIn(
            request_id=data.request_id,
            bundle_id=data.bundle_id,
            events=[event],
        )
        try:
            response = _sync_single_scheduled_gmail_escrow_event(
                db,
                single,
                principal,
            )
            results.extend(response["events"])
        except (
            GrowthRegistryError,
            EmailDeliveryError,
            RuntimeError,
            ValueError,
            SQLAlchemyError,
        ) as exc:
            # Each event is its own transaction boundary.  A malformed event or
            # stale chain cannot suppress the later valid events in this batch.
            # Importantly, rollback cannot undo a no-resend containment state
            # already committed by finalization/ambiguity handling.
            db.rollback()
            permit_status = db.scalar(
                select(ScheduledGmailEscrowPermit.status).where(
                    ScheduledGmailEscrowPermit.permit_id == event.permit_id,
                    ScheduledGmailEscrowPermit.bundle_id == data.bundle_id,
                    ScheduledGmailEscrowPermit.client_id == principal.client_id,
                )
            )
            error = (
                "scheduled_gmail_escrow_event_database_conflict"
                if isinstance(exc, SQLAlchemyError)
                else str(exc)
            )
            results.append(
                {
                    "event_id": event.event_id,
                    "permit_id": event.permit_id,
                    "status": "rejected",
                    "processing_status": "rejected",
                    "permit_status": permit_status or "missing",
                    "idempotent": False,
                    "error": error,
                }
            )

    bundle = db.scalar(
        select(ScheduledGmailEscrowBundle).where(
            ScheduledGmailEscrowBundle.bundle_id == data.bundle_id
        )
    )
    if bundle is None:
        raise GrowthRegistryError("scheduled_gmail_escrow_bundle_missing")
    permit_statuses = {
        str(item.get("permit_status") or "")
        for item in results
        if item.get("processing_status") != "rejected"
    }
    if "accepted_unverified" in permit_statuses:
        status = "accepted_unverified"
    elif permit_statuses and permit_statuses <= {"sent", "aborted"}:
        status = "reconciled" if bundle.status == "reconciled" else "sent"
    elif "sent" in permit_statuses:
        status = "sent"
    else:
        status = bundle.status
    return {
        "request_id": data.request_id,
        "bundle_id": data.bundle_id,
        "status": status,
        "events": results,
    }


def abort_scheduled_gmail_escrow_permit(
    db: Session,
    permit_id: str,
    data: ScheduledGmailEscrowAbortIn,
    principal: ScheduledGmailClientPrincipal,
) -> dict[str, Any]:
    principal.assert_scope(permission="abort")
    row, permit, lease, request = _load_escrow_event_context(db, permit_id=permit_id)
    principal.assert_scope(
        permission="abort",
        sender_email=row.sender_email,
        motor_key=row.motor_key,
    )
    if permit.client_id != principal.client_id:
        raise GrowthRegistryError("scheduled_gmail_escrow_permit_owned_by_other_client")
    if not _escrow_permit_token_matches(permit, data.permit_token):
        raise GrowthRegistryError("scheduled_gmail_escrow_permit_token_invalid")
    if permit.status == "aborted":
        db.commit()
        return {
            "permit_id": permit.permit_id,
            "bundle_id": permit.bundle_id,
            "status": "aborted",
            "provider_transport_called": False,
        }
    if data.provider_transport_called is not False:
        raise GrowthRegistryError("scheduled_gmail_escrow_abort_not_pre_transport")
    bundle = _release_escrow_permit_pretransport(
        db,
        row=row,
        permit=permit,
        lease=lease,
        request=request,
        principal=principal,
        reason=data.reason,
        allow_consuming=False,
    )
    acknowledged_at = permit.aborted_at or utcnow()
    return {
        "permit_id": permit.permit_id,
        "bundle_id": permit.bundle_id,
        "status": "aborted",
        "bundle_status": bundle.status,
        "provider_transport_called": False,
        "acknowledged_at": acknowledged_at,
    }
