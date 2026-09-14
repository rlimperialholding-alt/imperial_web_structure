from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    EnterpriseCanonicalRecord, MailSendingDomain, MailSuppression, TenderMailCampaign,
    TenderMailEvent, TenderMailRecipient,
)
from ..schemas import (
    DomainVerificationIn, MailEventIn, SendingDomainIn, TenderCampaignIn, TenderRecipientIn,
)
from .email_guard import is_valid_email

REQUIRED_TEMPLATE_TOKENS = ("{{tender_link}}", "{{unsubscribe_url}}")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:20]}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return fallback


def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    # Lineáris, korlátos validáció (ReDoS-mentes): a cím szerkezetét
    # karakterenként ellenőrizzük, visszalépő reguláris kifejezés nélkül.
    if not is_valid_email(value):
        raise ValueError(f"Érvénytelen e-mail-cím: {email}")
    return value


def upsert_domain(db: Session, data: SendingDomainIn) -> MailSendingDomain:
    email = normalize_email(data.from_email)
    domain = data.domain_name.strip().lower()
    if not email.endswith("@" + domain):
        raise ValueError("A feladói e-mail-címnek a regisztrált küldési domainhez kell tartoznia.")
    row = db.scalar(select(MailSendingDomain).where(MailSendingDomain.domain_key == data.domain_key))
    if not row:
        row = MailSendingDomain(domain_key=data.domain_key, domain_name=domain, from_email=email)
        db.add(row)
    row.domain_name = domain
    row.from_email = email
    row.from_name = data.from_name
    row.provider = data.provider
    row.max_hourly_rate = data.max_hourly_rate
    db.commit()
    db.refresh(row)
    return row


def verify_domain(db: Session, domain_key: str, data: DomainVerificationIn) -> MailSendingDomain:
    row = db.scalar(select(MailSendingDomain).where(MailSendingDomain.domain_key == domain_key))
    if not row:
        raise ValueError("Küldési domain nem található.")
    allowed = {"pending", "pass", "fail"}
    if any(value not in allowed for value in (data.spf_status, data.dkim_status, data.dmarc_status, data.tracking_domain_status)):
        raise ValueError("A DNS-ellenőrzési státusz pending, pass vagy fail lehet.")
    row.spf_status = data.spf_status
    row.dkim_status = data.dkim_status
    row.dmarc_status = data.dmarc_status
    row.tracking_domain_status = data.tracking_domain_status
    row.warmup_status = data.warmup_status
    row.verification_evidence_json = dumps(data.evidence)
    if all(value == "pass" for value in (row.spf_status, row.dkim_status, row.dmarc_status)):
        row.verified_at = utcnow()
    db.commit()
    db.refresh(row)
    return row


def create_campaign(db: Session, data: TenderCampaignIn) -> TenderMailCampaign:
    domain = db.scalar(select(MailSendingDomain).where(MailSendingDomain.domain_key == data.domain_key, MailSendingDomain.active.is_(True)))
    if not domain:
        raise ValueError("Aktív küldési domain nem található.")
    if not data.subject_template.strip() or not data.text_template.strip():
        raise ValueError("A tárgy és a levélszöveg kötelező.")
    row = TenderMailCampaign(
        campaign_id=new_id("TMC"), name=data.name, campaign_type=data.campaign_type,
        tender_id=data.tender_id, project_id=data.project_id, domain_key=data.domain_key,
        subject_template=data.subject_template.strip(), text_template=data.text_template.strip(),
        hourly_rate=min(data.hourly_rate, domain.max_hourly_rate), created_by=data.created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _suppression(db: Session, email: str) -> MailSuppression | None:
    return db.scalar(select(MailSuppression).where(MailSuppression.email == email, MailSuppression.active.is_(True)))


def add_recipient(db: Session, campaign_id: str, data: TenderRecipientIn) -> TenderMailRecipient:
    campaign = db.scalar(select(TenderMailCampaign).where(TenderMailCampaign.campaign_id == campaign_id))
    if not campaign:
        raise ValueError("Kampány nem található.")
    if campaign.status not in {"draft", "ready"}:
        raise ValueError("Címzett csak vázlat vagy előkészített kampányhoz adható.")
    email = normalize_email(data.email)
    existing = db.scalar(select(TenderMailRecipient).where(
        TenderMailRecipient.campaign_id == campaign_id, TenderMailRecipient.email == email,
    ))
    if existing:
        return existing
    suppression = _suppression(db, email)
    row = TenderMailRecipient(
        recipient_id=new_id("TMR"), campaign_id=campaign_id, canonical_record_id=data.canonical_record_id,
        company_name=data.company_name, contact_name=data.contact_name, email=email,
        status="suppressed" if suppression else "pending",
        suppression_reason=suppression.reason if suppression else None,
        personalization_json=dumps(data.personalization), tracking_token=uuid.uuid4().hex,
    )
    db.add(row)
    campaign.recipient_count += 1
    db.commit()
    db.refresh(row)
    return row


def add_canonical_partner_recipients(db: Session, campaign_id: str) -> dict[str, int]:
    records = db.scalars(select(EnterpriseCanonicalRecord).where(
        EnterpriseCanonicalRecord.domain.in_(["partner", "customer"]),
        EnterpriseCanonicalRecord.status == "active",
    )).all()
    added = suppressed = skipped = 0
    for record in records:
        data = loads(record.data_json, {})
        email = data.get("email")
        if not email:
            skipped += 1
            continue
        try:
            row = add_recipient(db, campaign_id, TenderRecipientIn(
                email=str(email), company_name=data.get("company_name") or record.canonical_name,
                contact_name=data.get("contact_name"), canonical_record_id=record.record_id,
                personalization={"project_id": record.project_id, "source_record": record.record_id},
            ))
            if row.status == "suppressed":
                suppressed += 1
            else:
                added += 1
        except ValueError:
            skipped += 1
    return {"added": added, "suppressed": suppressed, "skipped": skipped}


def campaign_readiness(db: Session, campaign_id: str) -> dict[str, Any]:
    campaign = db.scalar(select(TenderMailCampaign).where(TenderMailCampaign.campaign_id == campaign_id))
    if not campaign:
        raise ValueError("Kampány nem található.")
    domain = db.scalar(select(MailSendingDomain).where(MailSendingDomain.domain_key == campaign.domain_key))
    recipients = db.scalars(select(TenderMailRecipient).where(TenderMailRecipient.campaign_id == campaign_id)).all()
    checks = {
        "domain_active": bool(domain and domain.active),
        "spf": bool(domain and domain.spf_status == "pass"),
        "dkim": bool(domain and domain.dkim_status == "pass"),
        "dmarc": bool(domain and domain.dmarc_status == "pass"),
        "provider_configured": bool(domain and domain.provider != "provider_not_configured"),
        "has_recipients": any(r.status == "pending" for r in recipients),
        "has_tender_link": "{{tender_link}}" in campaign.text_template,
        "has_unsubscribe": "{{unsubscribe_url}}" in campaign.text_template,
        "rate_within_domain_limit": bool(domain and campaign.hourly_rate <= domain.max_hourly_rate),
    }
    return {
        "campaign_id": campaign_id, "ready_for_approval": all(v for k, v in checks.items() if k != "provider_configured"),
        "ready_for_live_send": all(checks.values()), "checks": checks,
        "sendable_recipients": sum(1 for r in recipients if r.status == "pending"),
        "suppressed_recipients": sum(1 for r in recipients if r.status == "suppressed"),
    }


def approve_campaign(db: Session, campaign_id: str, actor: str) -> TenderMailCampaign:
    readiness = campaign_readiness(db, campaign_id)
    if not readiness["ready_for_approval"]:
        failed = [key for key, value in readiness["checks"].items() if not value and key != "provider_configured"]
        raise ValueError("A kampány nem hagyható jóvá. Hiányzó kapuk: " + ", ".join(failed))
    row = db.scalar(select(TenderMailCampaign).where(TenderMailCampaign.campaign_id == campaign_id))
    assert row is not None
    row.approval_status = "approved"
    row.status = "ready"
    row.approved_by = actor
    row.approved_at = utcnow()
    db.commit()
    db.refresh(row)
    return row


def queue_campaign(db: Session, campaign_id: str, simulate: bool = False) -> TenderMailCampaign:
    campaign = db.scalar(select(TenderMailCampaign).where(TenderMailCampaign.campaign_id == campaign_id))
    if not campaign:
        raise ValueError("Kampány nem található.")
    if campaign.approval_status != "approved":
        raise ValueError("Csak jóváhagyott kampány állítható küldési sorba.")
    readiness = campaign_readiness(db, campaign_id)
    if not simulate and not readiness["ready_for_live_send"]:
        raise ValueError("Éles küldéshez hitelesített domain és konfigurált szolgáltató szükséges.")
    recipients = db.scalars(select(TenderMailRecipient).where(
        TenderMailRecipient.campaign_id == campaign_id,
        TenderMailRecipient.status == "pending",
    )).all()
    now = utcnow()
    for row in recipients:
        if _suppression(db, row.email):
            row.status = "suppressed"
            row.suppression_reason = "global_suppression"
        else:
            row.status = "queued"
            row.queued_at = now
            campaign.queued_count += 1
    campaign.status = "queued"
    db.commit()
    db.refresh(campaign)
    return campaign


def _render(template: str, row: TenderMailRecipient, campaign: TenderMailCampaign, base_url: str) -> str:
    values = {
        "company_name": row.company_name or "Partnerünk",
        "contact_name": row.contact_name or "Partnerünk",
        "tender_id": campaign.tender_id or "",
        "project_id": campaign.project_id or "",
        "tender_link": f"{base_url.rstrip('/')}/tender/{campaign.tender_id or campaign.campaign_id}?recipient={row.tracking_token}",
        "unsubscribe_url": f"{base_url.rstrip('/')}/mail/preferences/{row.tracking_token}",
    }
    values.update(loads(row.personalization_json, {}))
    result = template
    for key, value in values.items():
        result = result.replace("{{" + key + "}}", str(value or ""))
    return result


def dispatch_batch(db: Session, campaign_id: str, *, simulate: bool, base_url: str, limit: int | None = None) -> dict[str, Any]:
    campaign = db.scalar(select(TenderMailCampaign).where(TenderMailCampaign.campaign_id == campaign_id))
    if not campaign:
        raise ValueError("Kampány nem található.")
    domain = db.scalar(select(MailSendingDomain).where(MailSendingDomain.domain_key == campaign.domain_key))
    if not domain:
        raise ValueError("Küldési domain nem található.")
    if campaign.status not in {"queued", "sending"}:
        raise ValueError("A kampány nincs küldési sorban.")
    if not simulate and domain.provider == "provider_not_configured":
        raise ValueError("Nincs éles levélküldő szolgáltató konfigurálva.")
    batch_limit = min(limit or campaign.hourly_rate, campaign.hourly_rate, domain.max_hourly_rate)
    recipients = db.scalars(select(TenderMailRecipient).where(
        TenderMailRecipient.campaign_id == campaign_id,
        TenderMailRecipient.status == "queued",
    ).order_by(TenderMailRecipient.id).limit(batch_limit)).all()
    sent_payloads: list[dict[str, Any]] = []
    now = utcnow()
    for row in recipients:
        subject = _render(campaign.subject_template, row, campaign, base_url)
        text = _render(campaign.text_template, row, campaign, base_url)
        if simulate:
            provider_message_id = "SIM-" + uuid.uuid4().hex
        else:
            # Provider adapter intentionally remains an explicit deployment dependency.
            raise ValueError("Az éles provider adapter még nincs bekötve ebbe a csomagba.")
        row.status = "sent"
        row.sent_at = now
        row.last_event_at = now
        row.provider_message_id = provider_message_id
        campaign.sent_count += 1
        event = TenderMailEvent(
            event_id=new_id("TME"), recipient_id=row.recipient_id, campaign_id=campaign_id,
            event_type="sent", provider_event_id=provider_message_id,
            payload_json=dumps({"simulate": simulate, "subject": subject}), occurred_at=now,
        )
        db.add(event)
        sent_payloads.append({"recipient_id": row.recipient_id, "email": row.email, "subject": subject, "text": text})
    db.flush()
    remaining = db.scalar(select(TenderMailRecipient.id).where(
        TenderMailRecipient.campaign_id == campaign_id, TenderMailRecipient.status == "queued",
    ).limit(1))
    campaign.status = "sending" if remaining else "completed"
    db.commit()
    return {"campaign_id": campaign_id, "simulate": simulate, "sent": len(sent_payloads), "messages": sent_payloads}


def record_event(db: Session, data: MailEventIn) -> TenderMailEvent:
    recipient = db.scalar(select(TenderMailRecipient).where(TenderMailRecipient.recipient_id == data.recipient_id))
    if not recipient:
        raise ValueError("Címzett nem található.")
    if data.provider_event_id:
        existing = db.scalar(select(TenderMailEvent).where(TenderMailEvent.provider_event_id == data.provider_event_id))
        if existing:
            return existing
    occurred = data.occurred_at or utcnow()
    event = TenderMailEvent(
        event_id=new_id("TME"), recipient_id=recipient.recipient_id, campaign_id=recipient.campaign_id,
        event_type=data.event_type, provider_event_id=data.provider_event_id,
        payload_json=dumps(data.payload), occurred_at=occurred,
    )
    db.add(event)
    recipient.last_event_at = occurred
    campaign = db.scalar(select(TenderMailCampaign).where(TenderMailCampaign.campaign_id == recipient.campaign_id))
    if data.event_type == "delivered":
        if recipient.status != "delivered" and campaign:
            campaign.delivered_count += 1
        recipient.status = "delivered"
        recipient.delivered_at = occurred
    elif data.event_type in {"bounce", "hard_bounce"}:
        if recipient.status != "bounced" and campaign:
            campaign.bounced_count += 1
        recipient.status = "bounced"
        suppress_email(db, recipient.email, "hard_bounce" if data.event_type == "hard_bounce" else "bounce", "provider_event")
    elif data.event_type == "complaint":
        if recipient.status != "complained" and campaign:
            campaign.complained_count += 1
        recipient.status = "complained"
        suppress_email(db, recipient.email, "complaint", "provider_event")
    elif data.event_type == "unsubscribe":
        if recipient.status != "unsubscribed" and campaign:
            campaign.unsubscribed_count += 1
        recipient.status = "unsubscribed"
        suppress_email(db, recipient.email, "unsubscribe", "recipient")
    db.commit()
    db.refresh(event)
    return event


def suppress_email(db: Session, email: str, reason: str, source: str | None = None) -> MailSuppression:
    normalized = normalize_email(email)
    row = db.scalar(select(MailSuppression).where(MailSuppression.email == normalized))
    if not row:
        row = MailSuppression(email=normalized, reason=reason, source=source, active=True)
        db.add(row)
    else:
        row.reason = reason
        row.source = source
        row.active = True
    db.flush()
    return row


def unsubscribe_by_token(db: Session, tracking_token: str) -> TenderMailRecipient:
    row = db.scalar(select(TenderMailRecipient).where(TenderMailRecipient.tracking_token == tracking_token))
    if not row:
        raise ValueError("Érvénytelen értesítési hivatkozás.")
    record_event(db, MailEventIn(recipient_id=row.recipient_id, event_type="unsubscribe", payload={"method": "one_click"}))
    db.refresh(row)
    return row


def tender_mail_metrics(db: Session) -> dict[str, Any]:
    domains = db.scalars(select(MailSendingDomain)).all()
    campaigns = db.scalars(select(TenderMailCampaign)).all()
    recipients = db.scalars(select(TenderMailRecipient)).all()
    suppressions = db.scalars(select(MailSuppression).where(MailSuppression.active.is_(True))).all()
    return {
        "domains": len(domains),
        "verified_domains": sum(1 for d in domains if all(x == "pass" for x in (d.spf_status, d.dkim_status, d.dmarc_status))),
        "campaigns": len(campaigns),
        "draft_campaigns": sum(1 for c in campaigns if c.status == "draft"),
        "recipients": len(recipients),
        "sent": sum(1 for r in recipients if r.status in {"sent", "delivered"}),
        "delivered": sum(1 for r in recipients if r.status == "delivered"),
        "suppressed": len(suppressions),
    }
