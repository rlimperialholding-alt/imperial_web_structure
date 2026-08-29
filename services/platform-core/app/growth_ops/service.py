from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from secrets import token_urlsafe
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from publicsuffix2 import get_sld
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
from ..models import MailSendingDomain, MailSuppression
from .canonical_policy import (
    LAND_AGENT_HARD_GATE_REASONS,
    assert_outreach_copy,
    contains_no_monitoring_entity,
    land_agent_hard_gate_reason,
)
from .canonical_templates import CanonicalFirstContactRegistry
from .connectors import SourceError, fetch_source
from .email import GMAIL_OAUTH_FIELDS, EmailDeliveryError, SMTPEmailAdapter
from .models import (
    GrowthControlState,
    GrowthRun,
    GrowthSignal,
    GrowthWorkerHeartbeat,
    OutreachMessage,
)
from .registry import BrandBinding, GrowthRegistry, GrowthRegistryError, settings, writes_unlocked
from .schemas import GrowthSignalIn, GrowthSignalReceipt, OutreachEventIn, OutreachReleaseIn

LAND_RECIPIENT_TYPES_BY_ROLE = {
    "listing_agent": "real_estate_agent",
    "property_owner": "land_owner",
}

OUTREACH_CAPACITY_ADVISORY_LOCK_KEY = 3_292_944_878_079_892_252


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


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


def _canonical_screening_values(data: GrowthSignalIn) -> list[object]:
    return [
        data.recipient_name,
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
    )


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
    if score < 55:
        reasons.append("score_below_55")
    if utcnow() - _aware(data.detected_at) > timedelta(days=30):
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
    if data.signal_type == "residential_building_plot" and data.recipient_role == "property_owner":
        if not data.location or data.plot_size_sqm is None:
            reasons.append("template-variable-missing")
    if data.recipient_type == "unknown":
        reasons.append("recipient_type_unclassified_no_send")
    if not data.recipient_classification_verified:
        reasons.append("recipient_classification_not_verified_no_send")
    if not data.exclusion_screening_verified:
        reasons.append("exclusion_screening_not_verified_no_send")
    if data.recipient_type != "unknown" and not data.recipient_name:
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
            scope.endswith("/gmail.compose") or scope.endswith("/gmail.send")
            for scope in scopes
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
            or str(evidence.get("profile_email") or "").strip().lower()
            != binding.sender_email
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
    rendered = CanonicalFirstContactRegistry.load().render(
        recipient_type=data.recipient_type,
        recipient_name=data.recipient_name,
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
        screening_values=_canonical_screening_values(data),
    )
    if rendered.sender_brand_id != binding.brand_id:
        raise GrowthRegistryError("canonical_template_sender_brand_conflicts_with_routing")
    if not rendered.sendable or not rendered.subject:
        raise GrowthRegistryError(";".join(rendered.blocked_reasons))
    return rendered.subject, rendered.body_text, rendered.metadata()


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
    today = datetime(now.year, now.month, now.day, tzinfo=UTC)
    daily = (
        db.scalar(
            select(func.count())
            .select_from(OutreachMessage)
            .where(
                OutreachMessage.brand_id == binding.brand_id,
                OutreachMessage.created_at >= today,
                OutreachMessage.status.not_in(("blocked", "suppressed")),
            )
        )
        or 0
    )
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
    if daily >= int(binding.config.get("max_daily_messages", 100)):
        errors.append("brand_daily_rate_limit")
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
) -> OutreachMessage:
    hard_gate_reason = _land_agent_gate_reason(signal)
    if hard_gate_reason:
        raise GrowthRegistryError(hard_gate_reason)
    if _recipient_suppressed(db, signal.recipient_email or ""):
        raise GrowthRegistryError("Recipient is suppressed")
    if enforce_recipient_cooldown:
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
    registry = GrowthRegistry.load()
    registry.validate_signal_source(
        source_id=data.source_id,
        motor_key=data.motor_key,
        source_bucket=data.source_bucket,
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
    outreach: OutreachMessage | None = None
    if not reasons:
        try:
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
            )
            row.status = "queued"
        except (GrowthRegistryError, ValueError) as exc:
            reasons.append(str(exc))
            if "template-variable-missing" in str(exc):
                row.status = "template-variable-missing"
            else:
                row.status = "suppressed" if "suppressed" in str(exc) else "blocked"
            row.rejection_reasons_json = canonical_json(sorted(set(reasons)))
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
            _trip_runtime_kill_switch()
        # A worker may have died after Gmail accepted the POST but before the
        # provider id/readback could be committed. Gmail search is useful for
        # later recovery, but is not a safe automatic retry boundary because
        # SENT search visibility can lag. Keep every ambiguous claim held.
        row.status = "claimed"
        row.claimed_by = None
        row.lease_expires_at = None
        row.last_error = "delivery_ambiguous_pending_verification"


def _recipient_root_domain(email: str) -> str:
    value = str(email or "").strip()
    local_part, separator, domain = value.rpartition("@")
    domain = domain.strip().rstrip(".").casefold()
    if not separator or not local_part or not domain or ".." in domain:
        raise GrowthRegistryError("outreach_recipient_root_domain_invalid_no_send")
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise GrowthRegistryError("outreach_recipient_root_domain_invalid_no_send") from exc
    labels = ascii_domain.split(".")
    if any(not label or len(label) > 63 for label in labels):
        raise GrowthRegistryError("outreach_recipient_root_domain_invalid_no_send")
    root_domain = get_sld(ascii_domain, strict=False)
    if not root_domain:
        raise GrowthRegistryError("outreach_recipient_root_domain_invalid_no_send")
    return str(root_domain).casefold()


def _gmail_sent_mime_verified(row: OutreachMessage) -> bool:
    if not row.sent_at or not row.provider_message_id or not row.receipt_json:
        return False
    try:
        receipt = json.loads(row.receipt_json)
    except (TypeError, json.JSONDecodeError):
        return False
    detail = receipt.get("delivery_detail")
    return bool(
        receipt.get("provider") == "gmail_api"
        and receipt.get("accepted") is True
        and isinstance(detail, dict)
        and detail.get("readback_verified") is True
        and detail.get("readback_mime_sha256")
        and detail.get("rfc_message_id")
    )


def _outreach_period_bounds(
    now: datetime | None = None,
) -> tuple[datetime, datetime, datetime, datetime]:
    config = settings()
    try:
        zone = ZoneInfo(config.timezone)
    except ZoneInfoNotFoundError as exc:
        raise GrowthRegistryError("Configured growth timezone is unavailable") from exc
    local_now = (now or utcnow()).astimezone(zone)
    day_start = datetime.combine(local_now.date(), time.min, tzinfo=zone).astimezone(UTC)
    next_day = datetime.combine(
        local_now.date() + timedelta(days=1), time.min, tzinfo=zone
    ).astimezone(UTC)
    hour_start = local_now.replace(minute=0, second=0, microsecond=0).astimezone(UTC)
    next_hour = (
        local_now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    ).astimezone(UTC)
    return day_start, next_day, hour_start, next_hour


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


@dataclass(frozen=True)
class OutreachCapacityUsage:
    hourly_verified: int
    daily_verified: int
    hourly_claimed: int
    daily_claimed: int
    hourly_queued: int
    daily_queued: int
    daily_domain_reservations: dict[str, int]


def _outreach_capacity_usage(
    db: Session, now: datetime | None = None
) -> OutreachCapacityUsage:
    day_start, next_day, hour_start, next_hour = _outreach_period_bounds(now)
    sent_rows = db.scalars(
        select(OutreachMessage).where(
            OutreachMessage.sent_at >= day_start,
            OutreachMessage.sent_at < next_day,
        )
    ).all()
    verified_rows = [row for row in sent_rows if _gmail_sent_mime_verified(row)]
    claimed_rows = [
        row
        for row in db.scalars(
            select(OutreachMessage).where(OutreachMessage.status == "claimed")
        ).all()
        if (reservation_at := _claimed_reservation_at(row)) is not None
        and day_start <= reservation_at < next_day
    ]
    queued_rows = db.scalars(
        select(OutreachMessage).where(
            OutreachMessage.status == "queued",
            OutreachMessage.available_at >= day_start,
            OutreachMessage.available_at < next_day,
        )
    ).all()
    domain_usage: dict[str, int] = {}
    for row in [*verified_rows, *claimed_rows, *queued_rows]:
        try:
            root_domain = _recipient_root_domain(row.recipient_email)
        except GrowthRegistryError:
            continue
        domain_usage[root_domain] = domain_usage.get(root_domain, 0) + 1
    return OutreachCapacityUsage(
        hourly_verified=sum(
            hour_start <= _aware(row.sent_at) < next_hour for row in verified_rows
        ),
        daily_verified=len(verified_rows),
        hourly_claimed=sum(
            hour_start <= _claimed_reservation_at(row) < next_hour
            for row in claimed_rows
        ),
        daily_claimed=len(claimed_rows),
        hourly_queued=sum(
            hour_start <= _aware(row.available_at) < next_hour for row in queued_rows
        ),
        daily_queued=len(queued_rows),
        daily_domain_reservations=domain_usage,
    )


def _outreach_root_domain_capacity_available(
    db: Session, candidate: OutreachMessage, now: datetime | None = None
) -> bool:
    try:
        root_domain = _recipient_root_domain(candidate.recipient_email)
    except GrowthRegistryError:
        return False
    day_start, next_day, hour_start, next_hour = _outreach_period_bounds(now)
    usage = _outreach_capacity_usage(db, now)
    config = settings()
    hourly_limit = int(getattr(config, "outreach_max_per_hour", 5))
    daily_limit = int(getattr(config, "outreach_max_per_day", 50))
    root_limit = min(
        10,
        max(
            1,
            int(
                getattr(
                    config,
                    "outreach_max_per_recipient_root_domain_per_day",
                    10,
                )
            ),
        ),
    )
    available_at = _aware(candidate.available_at)
    already_hourly_reserved = hour_start <= available_at < next_hour
    already_daily_reserved = day_start <= available_at < next_day
    return bool(
        usage.hourly_verified
        + usage.hourly_claimed
        + usage.hourly_queued
        + (0 if already_hourly_reserved else 1)
        <= hourly_limit
        and usage.daily_verified
        + usage.daily_claimed
        + usage.daily_queued
        + (0 if already_daily_reserved else 1)
        <= daily_limit
        and usage.daily_domain_reservations.get(root_domain, 0)
        + (0 if already_daily_reserved else 1)
        <= root_limit
    )


def _outreach_transport_capacity_reserved(
    db: Session, row: OutreachMessage, now: datetime | None = None
) -> bool:
    if row.status != "claimed":
        return False
    day_start, next_day, hour_start, next_hour = _outreach_period_bounds(now)
    usage = _outreach_capacity_usage(db, now)
    config = settings()
    hourly_limit = int(getattr(config, "outreach_max_per_hour", 5))
    daily_limit = int(getattr(config, "outreach_max_per_day", 50))
    root_limit = min(
        10,
        max(
            1,
            int(
                getattr(
                    config,
                    "outreach_max_per_recipient_root_domain_per_day",
                    10,
                )
            ),
        ),
    )
    try:
        root_domain = _recipient_root_domain(row.recipient_email)
    except GrowthRegistryError:
        return False
    claimed_at = _aware(row.claimed_at) if row.claimed_at else None
    already_hourly_reserved = bool(
        claimed_at and hour_start <= claimed_at < next_hour
    )
    already_daily_reserved = bool(claimed_at and day_start <= claimed_at < next_day)
    return bool(
        usage.hourly_verified
        + usage.hourly_claimed
        + usage.hourly_queued
        + (0 if already_hourly_reserved else 1)
        <= hourly_limit
        and usage.daily_verified
        + usage.daily_claimed
        + usage.daily_queued
        + (0 if already_daily_reserved else 1)
        <= daily_limit
        and usage.daily_domain_reservations.get(root_domain, 0)
        + (0 if already_daily_reserved else 1)
        <= root_limit
    )


def claim_outreach(db: Session) -> OutreachMessage | None:
    if not _outreach_sending_window_open():
        return None
    _release_expired_claims(db)
    now = utcnow()
    _lock_outreach_claim_capacity(db)
    if _outreach_send_capacity(db, now) <= 0:
        db.commit()
        return None
    candidates = db.scalars(
        select(OutreachMessage)
        .where(
            OutreachMessage.status == "queued",
            OutreachMessage.available_at <= now,
            OutreachMessage.attempt_count < OutreachMessage.max_attempts,
        )
        .order_by(OutreachMessage.available_at, OutreachMessage.id)
        .with_for_update(skip_locked=True)
    ).all()
    row = next(
        (
            candidate
            for candidate in candidates
            if _outreach_root_domain_capacity_available(db, candidate, now)
        ),
        None,
    )
    if not row:
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
        Path("/app/runtime/growth-kill-switch").write_text("KILLED\n", encoding="utf-8")
    except OSError:
        return False
    return True


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
    if row.claimed_at is not None:
        return _aware(row.claimed_at)
    if not _delivery_acceptance_ambiguous(row):
        return None
    # Older ambiguous rows cleared claimed_at. updated_at is the persisted
    # acceptance/containment boundary for those rows; never make them retryable
    # merely because the original claim timestamp is missing.
    fallback = row.updated_at or row.available_at or row.created_at
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


def _assert_outreach_pre_send_guard(db: Session, row: OutreachMessage) -> None:
    if not _outreach_sending_window_open():
        raise GrowthRegistryError("outreach_sending_window_closed_no_send")
    if not _outreach_transport_capacity_reserved(db, row):
        raise GrowthRegistryError("outreach_transport_capacity_not_reserved_no_send")


def dispatch_outreach(db: Session, row: OutreachMessage) -> OutreachMessage:
    if row.status != "claimed":
        return row
    if _delivery_verification_pending(row):
        return row
    signal = db.scalar(
        select(GrowthSignal).where(GrowthSignal.signal_id == row.signal_id).with_for_update()
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
    registry = GrowthRegistry.load()
    global_guard = None
    try:
        if not signal:
            raise GrowthRegistryError("Signal record is missing")
        if not writes_unlocked() or not _control_enabled(db, row.motor_key):
            raise GrowthRegistryError("growth_writes_locked")
        if not _payload_matches(row):
            raise GrowthRegistryError("outreach_payload_hash_mismatch")
        canonical_metadata, body_html = _assert_canonical_payload(row)
        _assert_current_canonical_screening(signal, canonical_metadata)
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
        if not _outreach_sending_window_open():
            raise GrowthRegistryError("outreach_sending_window_closed_no_send")
        if not _outreach_transport_capacity_reserved(db, row):
            raise GrowthRegistryError("outreach_transport_capacity_not_reserved_no_send")
        receipt = SMTPEmailAdapter(binding).send(
            to_email=row.recipient_email,
            subject=row.subject,
            body_text=row.body_text,
            body_html=body_html,
            idempotency_key=row.idempotency_key,
            reply_to=str(binding.config.get("reply_to") or binding.sender_email),
            delivery_scope="external_customer",
            pre_send_guard=lambda: _assert_outreach_pre_send_guard(db, row),
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
            finalize_global_recipient_delivery(
                db,
                recipients=[row.recipient_email],
                identity_sha256=row.idempotency_key,
                claim_token=global_guard.claim_token,
                provider_message_id=receipt.provider_message_id,
                now=utcnow(),
            )
        except RuntimeError as exc:
            raise EmailDeliveryError(
                "global_recipient_guard_finalize_failed",
                retry_safe=False,
                accepted_but_unverified=True,
                provider_message_id=receipt.provider_message_id,
                detail={"reason": str(exc)},
            ) from exc
        row.status = "sent"
        row.provider_message_id = receipt.provider_message_id
        row.receipt_json = canonical_json(
            {
                "provider": receipt.provider,
                "accepted_recipient": receipt.accepted_recipient,
                "response_sha256": receipt.response_sha256,
                "accepted": True,
                "delivery_detail": receipt.detail,
                "canonical_template": canonical_metadata,
            }
        )
        row.sent_at = utcnow()
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
        if global_guard and global_guard.may_send and global_guard.claim_token:
            fail_global_recipient_delivery(
                db,
                recipients=[row.recipient_email],
                identity_sha256=row.idempotency_key,
                claim_token=global_guard.claim_token,
                error=(exc.error_type if isinstance(exc, EmailDeliveryError) else str(exc)),
                accepted_unverified=(
                    isinstance(exc, EmailDeliveryError) and exc.accepted_but_unverified
                ),
                provider_message_id=(
                    exc.provider_message_id if isinstance(exc, EmailDeliveryError) else None
                ),
                now=utcnow(),
            )
        if isinstance(exc, EmailDeliveryError) and exc.accepted_but_unverified:
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
            _trip_runtime_kill_switch()
            db.commit()
            return row
        recipient_hard_gate = _is_recipient_hard_gate_error(exc)
        row.last_error = str(exc) if recipient_hard_gate else type(exc).__name__
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
        if not recipient_hard_gate and (row.attempt_count >= row.max_attempts or not retry_safe):
            row.status = "dead_letter"
        elif not recipient_hard_gate:
            row.status = "queued"
            row.available_at = utcnow() + timedelta(minutes=2 ** min(row.attempt_count, 8))
        authentication_failure = isinstance(exc, EmailDeliveryError) and exc.authentication_failure
        if authentication_failure or "payload_hash" in str(exc):
            _trip_runtime_kill_switch()
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
    held = db.scalar(
        select(OutreachMessage)
        .where(OutreachMessage.id == row_id)
        .with_for_update()
    )
    if held is None or held.status != "claimed":
        db.commit()
        return
    try:
        receipt = json.loads(held.receipt_json or "{}")
    except (TypeError, json.JSONDecodeError):
        receipt = {}
    receipt["delivery_verification"] = {
        "status": "pending_verification",
        "retry_safe": False,
        "provider_message_id": held.provider_message_id,
        "detail": {"reason": "unexpected_dispatch_exception_isolated"},
    }
    held.receipt_json = canonical_json(receipt)
    held.last_error = f"unexpected_dispatch_exception:{type(exc).__name__}"
    held.claimed_by = None
    held.claimed_at = held.claimed_at or utcnow()
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
    for _ in range(max(1, min(limit, capacity, 100))):
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
            continue
        sent += result.status == "sent"
    return sent


def _outreach_sending_window_open(now: datetime | None = None) -> bool:
    config = settings()
    try:
        zone = ZoneInfo(config.timezone)
        start = time.fromisoformat(
            getattr(config, "outreach_send_start_local", "08:00")
        )
        end = time.fromisoformat(getattr(config, "outreach_send_end_local", "18:00"))
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise GrowthRegistryError("Configured outreach sending window is invalid") from exc
    if start >= end:
        raise GrowthRegistryError("Outreach sending window must start before it ends")
    local_time = (now or utcnow()).astimezone(zone).time().replace(tzinfo=None)
    return start <= local_time < end


def _outreach_send_capacity(db: Session, now: datetime | None = None) -> int:
    config = settings()
    usage = _outreach_capacity_usage(db, now)
    hourly_limit = int(getattr(config, "outreach_max_per_hour", 5))
    daily_limit = int(getattr(config, "outreach_max_per_day", 50))
    if (
        usage.hourly_verified + usage.hourly_claimed + usage.hourly_queued > hourly_limit
        or usage.daily_verified + usage.daily_claimed + usage.daily_queued > daily_limit
    ):
        return 0
    return max(
        0,
        min(
            hourly_limit - usage.hourly_verified - usage.hourly_claimed,
            daily_limit - usage.daily_verified - usage.daily_claimed,
        ),
    )


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


def run_once(db: Session) -> dict[str, Any]:
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

    # Process already approved outreach before the slower discovery and content
    # pipelines. An unrelated source, content, or publishing failure must not
    # prevent the mail worker from serving its independently guarded queue.
    early_sent = (
        dispatch_batch(db) if settings().enabled and writes_unlocked() else 0
    )
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
            "followups": 0,
            "sent": 0,
        }

    runs = run_due_motors(db)
    followups = schedule_followups(db) if writes_unlocked() else 0
    sent = early_sent + (dispatch_batch(db) if writes_unlocked() else 0)
    content_ok = content_factory.get("status") == "complete"
    result = {
        "status": "healthy" if content_ok and land_ready else "degraded",
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
        "followups": followups,
        "sent": sent,
        "blocking_errors": (
            []
            if content_ok and land_ready
            else [
                *([] if content_ok else ["daily_content_not_complete"]),
                *(
                    []
                    if land_ready
                    else land_readiness_detail.get("blocking_reasons", [])
                ),
                *[
                    f"unresolved_brand:{brand}"
                    for brand in content_factory.get("unresolved_brands", [])
                ],
            ]
        ),
    }
    heartbeat(db, status=result["status"], detail=result)
    return result


def readiness(db: Session) -> tuple[bool, dict[str, Any]]:
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
                SMTPEmailAdapter(binding).preflight()
                sender_states.append({"brand_id": brand_id, "ready": True})
            except GrowthRegistryError as exc:
                sender_states.append({"brand_id": brand_id, "ready": False, "reason": str(exc)})
    except GrowthRegistryError as exc:
        registry_state = {"ready": False, "error": str(exc), "enabled_sources": 0}
        sender_states = []
    hb = db.get(GrowthWorkerHeartbeat, settings().worker_id) if database_ok else None
    heartbeat_ok = bool(
        hb
        and hb.heartbeat_at
        and (utcnow() - _aware(hb.heartbeat_at)).total_seconds()
        <= max(120, settings().poll_seconds * 4)
        and hb.status in {"healthy", "working"}
    )
    required = settings().enabled
    senders_ok = bool(sender_states) and all(state["ready"] for state in sender_states)
    sources_ok = int(registry_state.get("enabled_sources", 0)) > 0
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
    ready = database_ok and (
        not required
        or (
            registry_state.get("ready")
            and senders_ok
            and sources_ok
            and heartbeat_ok
            and writes_unlocked()
        )
    )
    return ready, {
        "enabled": required,
        "database": "ok" if database_ok else "failed",
        "registry": registry_state,
        "senders": sender_states,
        "worker_heartbeat": "ok" if heartbeat_ok else "stale_or_missing",
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
