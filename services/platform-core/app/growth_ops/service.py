from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings as platform_settings
from ..models import MailSendingDomain, MailSuppression
from .canonical_policy import (
    LAND_AGENT_COMMISSION_ANCHOR,
    LAND_AGENT_HARD_GATE_REASONS,
    LAND_AGENT_SUBJECT,
    LAND_CATALOG_URL,
    LAND_OUTREACH_SERVICE_ANCHOR,
    LAND_OWNER_FREE_AD_ANCHOR,
    LAND_OWNER_SUBJECT,
    assert_outreach_copy,
    contains_no_monitoring_entity,
    land_agent_hard_gate_reason,
)
from .canonical_templates import CanonicalFirstContactRegistry
from .connectors import SourceError, fetch_source
from .email import EmailDeliveryError, SMTPEmailAdapter
from .models import (
    GrowthControlState,
    GrowthRun,
    GrowthSignal,
    GrowthWorkerHeartbeat,
    OutreachMessage,
)
from .registry import BrandBinding, GrowthRegistry, GrowthRegistryError, settings, writes_unlocked
from .schemas import GrowthSignalIn, GrowthSignalReceipt, OutreachEventIn, OutreachReleaseIn


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
        and data.recipient_role in {"listing_agent", "property_owner"}
        and bool(data.public_contact_url)
    )


def _land_agent_gate_reason(signal: GrowthSignalIn | GrowthSignal) -> str | None:
    if signal.signal_type != "residential_building_plot":
        return None
    return land_agent_hard_gate_reason(
        recipient_role=signal.recipient_role,
        contact_name=signal.company_name,
        organization_name=signal.recipient_organization_name,
        office_name=signal.recipient_office_name,
        recipient_email=signal.recipient_email,
        public_contact_url=signal.public_contact_url,
        evidence_url=signal.evidence_url,
    )


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
    if not public_land_contact:
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
    if signal.signal_type == "residential_building_plot":
        recipient = signal.company_name or (data.recipient_name if data else None) or "Címzett"
        brand_name = str(binding.config.get("brand_name") or binding.brand_id)
        if signal.recipient_role == "listing_agent":
            subject = LAND_AGENT_SUBJECT
            body = (
                f"Tisztelt {recipient}!\n\n"
                f"Cégünk, az {brand_name}, {LAND_OUTREACH_SERVICE_ANCHOR}, "
                "és úgy gondoljuk, hogy az Ön által hirdetett telekben van lehetőség.\n\n"
                f"{LAND_AGENT_COMMISSION_ANCHOR}\n\n"
                "Jelenleg is számos ingatlan-irodával dolgozunk együtt az ország "
                "minden pontján. Mi elkészítjük a hirdetést Önnek egy olyan "
                "típusházzal, ami építhető erre a telekre, látványtervvel, "
                "alaprajzzal és műszaki leírással. Ha Ön meghirdeti a telekkel "
                "együtt, és érkezik rá vevő, 2,5% jutalékot fizetünk Önnek a "
                "típusterv árából.\n\nÉrdekli ez a lehetőség?\n\n"
                f"Üdvözlettel:\n{brand_name}\n{binding.sender_email}\n\n"
                f"Leiratkozás: {unsubscribe_url}"
            )
            body_html = _email_html(body, bold_sentence=LAND_AGENT_COMMISSION_ANCHOR)
        elif signal.recipient_role == "property_owner":
            subject = LAND_OWNER_SUBJECT
            body = (
                f"Tisztelt {recipient}!\n\n"
                f"Cégünk, az {brand_name}, {LAND_OUTREACH_SERVICE_ANCHOR}, "
                "és úgy gondoljuk, hogy az Ön telkében van lehetőség.\n\n"
                f"{LAND_OWNER_FREE_AD_ANCHOR}\n\n"
                "Itt meg tudja nézni a weboldalunkon, milyen telkekkel dolgozunk "
                f"jelenleg: {LAND_CATALOG_URL}\n\n"
                "Nem kérünk Öntől pénzt semmilyen formában, jutalékot sem: a "
                "lehetőség mindkettőnknek előnyös, mi a típusházat adjuk el, Ön "
                "pedig a telket. Nem kérünk semmilyen kötelezettséget, csak "
                "szeretnénk együttműködni Önnel.\n\nÉrdekli?\n\n"
                f"Üdvözlettel:\n{brand_name}\n{binding.sender_email}\n\n"
                f"Leiratkozás: {unsubscribe_url}"
            )
            body_html = _email_html(body)
        else:
            raise GrowthRegistryError("Building-plot recipient role is required")
        assert_outreach_copy(body)
        return subject, body, {
            "template_policy": "owner_locked_land_outreach_v1",
            "sender_brand_id": binding.brand_id,
            "recipient_role": signal.recipient_role,
            "body_html": body_html,
        }
    if data is None:
        raise GrowthRegistryError("canonical_first_contact_input_missing")
    rendered = CanonicalFirstContactRegistry.load().render(
        recipient_type=data.recipient_type,
        recipient_name=data.recipient_name,
        sender_company_name=data.sender_company_name,
        reference_names=data.reference_names,
        reference_names_verified=data.reference_names_verified,
        business_context=data.business_context,
        business_context_verified=data.business_context_verified,
        business_context_evidence_url=data.business_context_evidence_url,
        unsubscribe_url=unsubscribe_url,
        recipient_classification_verified=data.recipient_classification_verified,
        exclusion_screening_verified=data.exclusion_screening_verified,
        screening_values=[
            data.recipient_name,
            data.company_name,
            data.recipient_email,
            data.business_context,
            data.business_context_evidence_url,
            data.summary,
            data.evidence_url,
            data.public_contact_url,
        ],
    )
    if rendered.sender_brand_id != binding.brand_id:
        raise GrowthRegistryError("canonical_template_sender_brand_conflicts_with_routing")
    if not rendered.sendable or not rendered.subject:
        raise GrowthRegistryError(";".join(rendered.blocked_reasons))
    return rendered.subject, rendered.body_text, rendered.metadata()


def _email_html(body_text: str, *, bold_sentence: str | None = None) -> str:
    paragraphs: list[str] = []
    bold_escaped = escape(bold_sentence) if bold_sentence else None
    for paragraph in body_text.split("\n\n"):
        safe = escape(paragraph).replace("\n", "<br>\n")
        if bold_escaped and bold_escaped in safe:
            safe = safe.replace(bold_escaped, f"<strong>{bold_escaped}</strong>", 1)
        paragraphs.append(f"<p>{safe}</p>")
    return "<!doctype html><html><body>" + "".join(paragraphs) + "</body></html>"


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
    payload_hash = sha(
        {
            "from": binding.sender_email,
            "to": signal.recipient_email,
            "subject": subject,
            "body": body,
            "body_html": canonical_metadata["body_html"],
        }
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
    db.add(row)
    if (
        step == 0
        and signal.signal_type == "residential_building_plot"
        and signal.contact_basis == "public_property_listing"
        and signal.recipient_role in {"listing_agent", "property_owner"}
    ):
        assert_outreach_copy(row.body_text)
        row.release_approved_by = "owner-policy:land-public-listing-v1:2026-08-25"
        row.release_approved_at = utcnow()
        row.release_token_hash = _release_digest(row, row.release_approved_by)
        audit(
            db,
            actor=row.release_approved_by,
            action="growth_outreach_policy_released",
            entity_type="growth_outreach",
            entity_id=row.outreach_id,
            after={
                "payload_sha256": row.payload_sha256,
                "signal_id": signal.signal_id,
                "recipient_role": signal.recipient_role,
                "policy_scope": "single_initial_public_building_plot_outreach",
            },
        )
    return row


def ingest_signal(
    db: Session,
    data: GrowthSignalIn,
    *,
    run_id: str | None = None,
) -> GrowthSignalReceipt:
    land_agent_gate = _land_agent_gate_reason(data)
    if land_agent_gate:
        raise GrowthRegistryError(land_agent_gate)
    hard_gate_values = "\n".join(
        value
        for value in (
            data.company_name,
            data.summary,
            data.evidence_url,
            data.public_contact_url,
        )
        if value
    )
    if contains_no_monitoring_entity(hard_gate_values):
        raise GrowthRegistryError("no_monitoring_hard_gate_blocked")
    canonical_registry = CanonicalFirstContactRegistry.load()
    hard_gate = canonical_registry.hard_gate_match(
        [
            data.recipient_name,
            data.company_name,
            data.recipient_email,
            data.business_context,
            data.business_context_evidence_url,
            data.summary,
            data.evidence_url,
            data.public_contact_url,
        ]
    )
    if hard_gate:
        raise GrowthRegistryError(f"canonical_hard_gate_blocked:{hard_gate}")
    registry = GrowthRegistry.load()
    registry.validate_signal_source(
        source_id=data.source_id,
        motor_key=data.motor_key,
        source_bucket=data.source_bucket,
    )
    brand_id = registry.brand_for(data.signal_type, data.brand_id)
    dedupe_hash = _signal_dedupe(data, brand_id)
    existing = db.scalar(
        select(GrowthSignal).where(
            or_(
                and_(
                    GrowthSignal.source_id == data.source_id,
                    GrowthSignal.external_key == data.external_key,
                ),
                GrowthSignal.dedupe_hash == dedupe_hash,
            )
        )
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
            else "rejected" if reasons else "accepted"
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
        except GrowthRegistryError as exc:
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
                    if str(exc) not in LAND_AGENT_HARD_GATE_REASONS:
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
        row.status = "dead_letter" if row.attempt_count >= row.max_attempts else "queued"
        row.available_at = now
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None
        row.last_error = "worker lease expired"


def claim_outreach(db: Session) -> OutreachMessage | None:
    _release_expired_claims(db)
    now = utcnow()
    row = db.scalar(
        select(OutreachMessage)
        .where(
            OutreachMessage.status == "queued",
            OutreachMessage.available_at <= now,
            OutreachMessage.attempt_count < OutreachMessage.max_attempts,
        )
        .order_by(OutreachMessage.available_at, OutreachMessage.id)
        .limit(1)
        .with_for_update(skip_locked=True)
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


def _payload_matches(row: OutreachMessage) -> bool:
    metadata = _canonical_metadata(row)
    return hmac.compare_digest(
        row.payload_sha256,
        sha(
            {
                "from": row.sender_email,
                "to": row.recipient_email,
                "subject": row.subject,
                "body": row.body_text,
                "body_html": metadata.get("body_html"),
            }
        ),
    )


def _canonical_metadata(row: OutreachMessage) -> dict[str, Any]:
    try:
        receipt = json.loads(row.receipt_json or "{}")
    except json.JSONDecodeError as exc:
        raise GrowthRegistryError("canonical_outreach_metadata_unreadable") from exc
    metadata = receipt.get("canonical_template")
    if not isinstance(metadata, dict):
        raise GrowthRegistryError("canonical_outreach_metadata_missing")
    return metadata


def _assert_canonical_payload(row: OutreachMessage) -> tuple[dict[str, Any], str]:
    metadata = _canonical_metadata(row)
    if metadata.get("sender_brand_id") != row.brand_id:
        raise GrowthRegistryError("canonical_sender_brand_conflicts_with_outreach")
    if metadata.get("template_policy") == "owner_locked_land_outreach_v1":
        assert_outreach_copy(row.body_text)
        body_html = str(metadata.get("body_html") or "")
        if not body_html or row.body_html != body_html:
            raise GrowthRegistryError("owner_locked_land_html_mismatch")
        if metadata.get("recipient_role") == "listing_agent":
            required_bold = f"<strong>{escape(LAND_AGENT_COMMISSION_ANCHOR)}</strong>"
            if required_bold not in body_html:
                raise GrowthRegistryError("land_agent_commission_bold_format_missing")
        return metadata, body_html
    body_html = CanonicalFirstContactRegistry.load().assert_current_render(
        metadata=metadata,
        subject=row.subject,
        body_text=row.body_text,
    )
    return metadata, body_html


def _release_digest(row: OutreachMessage, approved_by: str) -> str:
    key = platform_settings.imperial_release_hmac_key
    if len(key) < 32:
        raise GrowthRegistryError("IMPERIAL_RELEASE_HMAC_KEY is not configured")
    value = canonical_json(
        {
            "outreach_id": row.outreach_id,
            "payload_sha256": row.payload_sha256,
            "approved_by": approved_by,
        }
    )
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def release_outreach(
    db: Session, outreach_id: str, data: OutreachReleaseIn
) -> OutreachMessage:
    row = db.scalar(select(OutreachMessage).where(OutreachMessage.outreach_id == outreach_id))
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
    if not hmac.compare_digest(row.payload_sha256, data.inspected_payload_sha256):
        raise GrowthRegistryError("Inspected outreach payload hash does not match")
    _assert_canonical_payload(row)
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
    if not row.release_token_hash or not row.release_approved_by or not row.release_approved_at:
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


def dispatch_outreach(db: Session, row: OutreachMessage) -> OutreachMessage:
    signal = db.scalar(select(GrowthSignal).where(GrowthSignal.signal_id == row.signal_id))
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
    registry = GrowthRegistry.load()
    try:
        if not signal:
            raise GrowthRegistryError("Signal record is missing")
        if not writes_unlocked() or not _control_enabled(db, row.motor_key):
            raise GrowthRegistryError("growth_writes_locked")
        if not _payload_matches(row):
            raise GrowthRegistryError("outreach_payload_hash_mismatch")
        canonical_metadata, body_html = _assert_canonical_payload(row)
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
        receipt = SMTPEmailAdapter(binding).send(
            to_email=row.recipient_email,
            subject=row.subject,
            body_text=row.body_text,
            body_html=body_html,
            idempotency_key=row.idempotency_key,
            reply_to=str(binding.config.get("reply_to") or binding.sender_email),
        )
        row.status = "sent"
        row.provider_message_id = receipt.provider_message_id
        row.receipt_json = canonical_json(
            {
                "provider": receipt.provider,
                "accepted_recipient": receipt.accepted_recipient,
                "response_sha256": receipt.response_sha256,
                "accepted": True,
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
        row.last_error = type(exc).__name__
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None
        retry_safe = not isinstance(exc, EmailDeliveryError) or exc.retry_safe
        if row.attempt_count >= row.max_attempts or not retry_safe:
            row.status = "dead_letter"
        else:
            row.status = "queued"
            row.available_at = utcnow() + timedelta(minutes=2 ** min(row.attempt_count, 8))
        authentication_failure = isinstance(exc, EmailDeliveryError) and exc.authentication_failure
        if authentication_failure or "payload_hash" in str(exc):
            _trip_runtime_kill_switch()
    db.commit()
    return row


def dispatch_batch(db: Session, *, limit: int = 20) -> int:
    sent = 0
    for _ in range(max(1, min(limit, 100))):
        row = claim_outreach(db)
        if not row:
            break
        result = dispatch_outreach(db, row)
        sent += result.status == "sent"
    return sent


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
    from ..land_acquisition.service import scan_authority_expiry, sync_growth_plot_signals
    from .catalog import scan_due_routes
    from .processing import (
        enqueue_daily_publications,
        generate_daily_content,
        generate_question_radar_answers,
        send_internal_handoff,
        send_publication_digest,
    )
    from .wide_service import run_due as run_due_wide

    route_scan = scan_due_routes(db)
    wide_run = run_due_wide(db)
    question_answers = generate_question_radar_answers(db)
    content_factory = generate_daily_content(db)
    publication_queue = enqueue_daily_publications(db)
    # Refresh counts after evidence extraction and content generation. This does
    # not release or publish the quarantined assets.
    wide_run = run_due_wide(db) or wide_run
    internal_handoff = send_internal_handoff(db)
    land_sync = sync_growth_plot_signals(db)
    land_takedown = scan_authority_expiry(db)
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
            "publication_digest": publication_digest,
            "followups": 0,
            "sent": 0,
        }

    runs = run_due_motors(db)
    followups = schedule_followups(db) if writes_unlocked() else 0
    sent = dispatch_batch(db) if writes_unlocked() else 0
    content_ok = content_factory.get("status") == "complete"
    result = {
        "status": "healthy" if content_ok else "degraded",
        "runs": len(runs),
        "wide_run": wide_run.run_id if wide_run else None,
        "route_scan": route_scan,
        "question_answers": question_answers,
        "content_factory": content_factory,
        "publication_queue": publication_queue,
        "internal_handoff": internal_handoff,
        "land_sync": land_sync,
        "land_takedown": land_takedown,
        "publication_digest": publication_digest,
        "followups": followups,
        "sent": sent,
        "blocking_errors": (
            []
            if content_ok
            else [
                "daily_content_not_complete",
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
