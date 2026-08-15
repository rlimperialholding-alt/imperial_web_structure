from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from ..audit import audit
from ..models import (
    EventRecord,
    ProjectRegistry,
    TaskRecord,
    TenderBid,
    TenderBidEvidence,
    TenderBidItem,
    TenderClarification,
    TenderEvaluation,
    TenderInvitation,
    TenderBidVersion,
    TenderBidVersionItem,
    TenderClarificationRequest,
    TenderLineItem,
    TenderMailCampaign,
    TenderMailRecipient,
    TenderPackage,
    TenderPurchaseOrderPreparation,
)
from ..schemas import EventIn
from .integration import ingest_event
from .partner_control import create_partner, eligibility_report
from .tender_evidence_security import (
    TenderEvidenceUnavailable,
    TenderMalwareDetected,
    TenderScannerUnavailable,
    scan_tender_evidence,
    tender_av_configuration,
    validate_tender_evidence_content,
)

INTERNAL_ROLES = frozenset(
    {"owner", "managing-director", "platform-admin", "project-manager", "finance", "technical-prep"}
)
DECISION_ROLES = frozenset({"owner", "managing-director", "platform-admin"})
DEFAULT_CRITERIA = {"price": 40, "technical": 30, "timeline": 20, "references": 10}
TENDER_STATUSES = {"draft", "published", "closed", "evaluation", "awarded", "cancelled"}
MAX_EVIDENCE_BYTES = 25 * 1024 * 1024


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _email(user: object) -> str:
    return str(getattr(user, "email", "")).strip().lower()


def _role(user: object) -> str:
    return str(getattr(user, "role", ""))


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _criteria(value: str | dict[str, Any] | None) -> dict[str, int]:
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            raw = {}
    else:
        raw = value or {}
    result = {key: int(raw.get(key, weight)) for key, weight in DEFAULT_CRITERIA.items()}
    if any(weight < 0 or weight > 100 for weight in result.values()) or sum(result.values()) != 100:
        raise ValueError("Az értékelési súlyok összege pontosan 100% legyen.")
    return result


def _package_query(*, for_update: bool = False):
    query = select(TenderPackage).execution_options(populate_existing=True).options(
        selectinload(TenderPackage.invitations)
        .selectinload(TenderInvitation.bid)
        .selectinload(TenderBid.items),
        selectinload(TenderPackage.bids).selectinload(TenderBid.evidence),
        selectinload(TenderPackage.bids).selectinload(TenderBid.evaluations),
        selectinload(TenderPackage.clarifications),
        selectinload(TenderPackage.evaluations),
        selectinload(TenderPackage.line_items),
        selectinload(TenderPackage.clarification_requests),
    )
    return query.with_for_update() if for_update else query


def get_tender(
    db: Session, tender_id: str, *, for_update: bool = False
) -> TenderPackage:
    row = db.scalar(
        _package_query(for_update=for_update).where(TenderPackage.tender_id == tender_id)
    )
    if row is None:
        raise KeyError(tender_id)
    return row


def tender_workspace(db: Session) -> dict[str, Any]:
    tenders = list(db.scalars(_package_query().order_by(desc(TenderPackage.created_at))))
    return {
        "tenders": tenders,
        "metrics": {
            "active": sum(row.status in {"published", "closed", "evaluation"} for row in tenders),
            "published": sum(row.status == "published" for row in tenders),
            "submitted_bids": sum(bid.status == "submitted" for row in tenders for bid in row.bids),
            "awarded": sum(row.status == "awarded" for row in tenders),
        },
        "av": tender_av_configuration(),
    }


def bid_comparison(db: Session, tender_id: str) -> dict[str, Any]:
    tender = get_tender(db, tender_id)
    candidates = [
        bid for bid in tender.bids
        if bid.status in {"submitted", "awarded", "rejected"}
    ]
    rows: list[dict[str, Any]] = []
    for bid in candidates:
        scores = [Decimal(item.weighted_total) for item in bid.evaluations]
        average_score = (sum(scores, Decimal("0")) / len(scores)) if scores else None
        rows.append(
            {
                "bid": bid,
                "company_name": bid.invitation.company_name,
                "partner_id": bid.invitation.partner_id,
                "average_score": average_score,
                "evaluation_count": len(scores),
                "evidence_count": len(bid.evidence),
                "items_by_line": {item.line_no: item for item in bid.items},
                "complete": len(bid.items) == len(tender.line_items),
            }
        )
    ranked = sorted(
        rows,
        key=lambda item: (
            -(item["average_score"] if item["average_score"] is not None else Decimal("-1")),
            Decimal(item["bid"].net_total),
            item["bid"].bid_id,
        ),
    )
    for position, item in enumerate(ranked, 1):
        item["rank"] = position
    totals = [Decimal(item["bid"].net_total) for item in rows]
    line_matrix = [
        {
            "line": line,
            "offers": [
                {
                    "bid_id": item["bid"].bid_id,
                    "item": item["items_by_line"].get(line.line_no),
                }
                for item in ranked
            ],
        }
        for line in sorted(tender.line_items, key=lambda item: item.line_no)
    ]
    return {
        "tender": tender,
        "criteria": _criteria(tender.evaluation_criteria_json),
        "candidates": ranked,
        "line_matrix": line_matrix,
        "metrics": {
            "candidate_count": len(rows),
            "lowest_net_total": min(totals) if totals else None,
            "highest_net_total": max(totals) if totals else None,
            "price_spread": max(totals) - min(totals) if totals else None,
            "evaluated_count": sum(item["average_score"] is not None for item in rows),
            "complete_count": sum(item["complete"] for item in rows),
        },
        "av": tender_av_configuration(),
    }


def create_tender(
    db: Session,
    user: object,
    *,
    tender_id: str,
    project_id: str,
    title: str,
    scope: str,
    currency: str,
    question_deadline_at: datetime,
    submission_deadline_at: datetime,
    criteria: dict[str, int] | None = None,
    prequalification_required: bool = True,
    certificate_gate_enabled: bool = False,
    required_certificate_types: list[str] | None = None,
) -> TenderPackage:
    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs tender-létrehozási jogosultság.")
    tender_id = tender_id.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{4,119}", tender_id):
        raise ValueError(
            "A tenderazonosító legalább 5 karakteres, szóköz nélküli azonosító legyen."
        )
    if db.scalar(select(TenderPackage).where(TenderPackage.tender_id == tender_id)):
        raise ValueError("Ez a tenderazonosító már létezik.")
    if (
        db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id.strip()))
        is None
    ):
        raise ValueError("A ProjectID nem található a kanonikus projektregiszterben.")
    if len(title.strip()) < 5 or len(scope.strip()) < 20:
        raise ValueError("A tender címe és részletes műszaki/üzleti terjedelme kötelező.")
    question_deadline_at = _aware(question_deadline_at)
    submission_deadline_at = _aware(submission_deadline_at)
    if question_deadline_at >= submission_deadline_at:
        raise ValueError("A kérdezési határidőnek meg kell előznie az ajánlattételi határidőt.")
    if submission_deadline_at <= utcnow():
        raise ValueError("Az ajánlattételi határidőnek jövőbeli időpontnak kell lennie.")
    currency = currency.strip().upper()
    if currency not in {"HUF", "EUR"}:
        raise ValueError("A támogatott pénznem HUF vagy EUR.")
    row = TenderPackage(
        tender_id=tender_id,
        project_id=project_id.strip(),
        title=title.strip(),
        scope=scope.strip(),
        currency=currency,
        question_deadline_at=question_deadline_at,
        submission_deadline_at=submission_deadline_at,
        evaluation_criteria_json=json.dumps(_criteria(criteria), sort_keys=True),
        prequalification_required=prequalification_required,
        certificate_gate_enabled=certificate_gate_enabled,
        required_certificate_types_json=json.dumps(
            required_certificate_types or ["liability_insurance", "tax_clearance"], sort_keys=True
        ),
        created_by=_email(user),
    )
    db.add(row)
    db.flush()
    audit(
        db,
        actor=_email(user),
        action="tender.created",
        entity_type="tender",
        entity_id=tender_id,
        after={"project_id": row.project_id, "status": row.status, "criteria": _criteria(criteria)},
    )
    db.commit()
    return get_tender(db, tender_id)


def add_invitation(
    db: Session,
    tender_id: str,
    user: object,
    *,
    partner_email: str,
    company_name: str,
    contact_name: str = "",
    mail_recipient_id: str | None = None,
    access_token: str | None = None,
    partner_id: str | None = None,
) -> TenderInvitation:
    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs partnermeghívási jogosultság.")
    tender = get_tender(db, tender_id, for_update=True)
    if tender.status not in {"draft", "published"}:
        raise ValueError("Partner csak vázlat vagy közzétett tenderhez hívható meg.")
    email = partner_email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Érvénytelen partner e-mail-cím.")
    if len(company_name.strip()) < 2:
        raise ValueError("A partner cégneve kötelező.")
    existing = db.scalar(
        select(TenderInvitation).where(
            TenderInvitation.tender_id_fk == tender.id, TenderInvitation.partner_email == email
        )
    )
    if existing:
        return existing
    from ..models import PartnerProfile
    if partner_id:
        profile = db.scalar(select(PartnerProfile).where(PartnerProfile.partner_id == partner_id))
        if profile is None:
            raise ValueError("A megadott PartnerID nem található.")
        if profile.primary_email != email:
            raise ValueError("A PartnerID és a meghívási e-mail nem ugyanahhoz a partnerhez tartozik.")
    else:
        profile = db.scalar(select(PartnerProfile).where(PartnerProfile.primary_email == email))
        if profile is None:
            profile = create_partner(db, user, company_name=company_name, primary_email=email)
        partner_id = profile.partner_id
    row = TenderInvitation(
        invitation_id=_id("TINV"),
        tender_id_fk=tender.id,
        mail_recipient_id=mail_recipient_id,
        partner_id=partner_id,
        partner_email=email,
        company_name=company_name.strip(),
        contact_name=contact_name.strip() or None,
        access_token=access_token or secrets.token_urlsafe(48),
        token_revision=1,
        expires_at=tender.submission_deadline_at,
        status="invited",
    )
    db.add(row)
    audit(
        db,
        actor=_email(user),
        action="tender.invitation.created",
        entity_type="tender",
        entity_id=tender_id,
        after={"invitation_id": row.invitation_id, "partner_email": email},
    )
    db.commit()
    db.refresh(row)
    return row


def add_tender_line_item(
    db: Session,
    tender_id: str,
    user: object,
    *,
    line_code: str,
    category: str,
    name: str,
    unit: str,
    quantity: Any,
    required: bool = True,
) -> TenderLineItem:
    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs tendertétel-szerkesztési jogosultság.")
    tender = get_tender(db, tender_id, for_update=True)
    if tender.status != "draft":
        raise ValueError("Tendertétel csak vázlatban módosítható.")
    code = line_code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{1,99}", code):
        raise ValueError("A tételkód legalább két karakteres, szóköz nélküli azonosító legyen.")
    if db.scalar(select(TenderLineItem).where(TenderLineItem.tender_id_fk == tender.id, TenderLineItem.line_code == code)):
        raise ValueError("Ez a tételkód már szerepel a tenderben.")
    clean_unit = _canonical_unit(unit)
    amount = _decimal(quantity, "tendertétel mennyisége", positive=True)
    if min(len(category.strip()), len(name.strip())) < 2:
        raise ValueError("A tételkategória és megnevezés kötelező.")
    row = TenderLineItem(
        line_item_id=_id("TLINE"), tender_id_fk=tender.id,
        line_no=len(tender.line_items) + 1, line_code=code, category=category.strip(),
        name=name.strip(), unit=clean_unit, quantity=amount, required=required,
    )
    db.add(row)
    audit(db, actor=_email(user), action="tender.line_item.created", entity_type="tender", entity_id=tender_id, after={"line_item_id": row.line_item_id, "line_code": code, "quantity": str(amount), "unit": clean_unit, "required": required})
    db.commit()
    db.refresh(row)
    return row


def sync_mail_recipients(db: Session, tender_id: str, user: object) -> dict[str, int]:
    tender = get_tender(db, tender_id)
    campaigns = list(
        db.scalars(select(TenderMailCampaign).where(TenderMailCampaign.tender_id == tender_id))
    )
    added = existing = 0
    for campaign in campaigns:
        recipients = list(
            db.scalars(
                select(TenderMailRecipient).where(
                    TenderMailRecipient.campaign_id == campaign.campaign_id
                )
            )
        )
        for recipient in recipients:
            before = db.scalar(
                select(TenderInvitation).where(
                    TenderInvitation.tender_id_fk == tender.id,
                    TenderInvitation.partner_email == recipient.email,
                )
            )
            add_invitation(
                db,
                tender_id,
                user,
                partner_email=recipient.email,
                company_name=recipient.company_name or recipient.email,
                contact_name=recipient.contact_name or "",
                mail_recipient_id=recipient.recipient_id,
                access_token=recipient.tracking_token,
            )
            if before:
                existing += 1
            else:
                added += 1
    return {"added": added, "existing": existing, "campaigns": len(campaigns)}


def publish_tender(db: Session, tender_id: str, user: object) -> TenderPackage:
    tender = get_tender(db, tender_id, for_update=True)
    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs közzétételi jogosultság.")
    if tender.status != "draft":
        raise ValueError("Csak vázlat tender tehető közzé.")
    if not tender.invitations:
        raise ValueError("Közzététel előtt legalább egy partnert meg kell hívni.")
    if not tender.line_items:
        raise ValueError("Közzététel előtt legalább egy tételes műszaki/üzleti sor kötelező.")
    if _aware(tender.submission_deadline_at) <= utcnow():
        raise ValueError("Lejárt tender nem tehető közzé.")
    _criteria(tender.evaluation_criteria_json)
    tender.status = "published"
    tender.published_at = utcnow()
    tender.version += 1
    event, _ = ingest_event(
        db,
        EventIn(
            event_id=f"EVT-{tender.tender_id}",
            dedupe_key=f"TENDER_PUBLISHED:{tender.tender_id}",
            project_id=tender.project_id,
            source_module="tendermail",
            event_type="TENDER_PUBLISHED",
            object_type="TenderPackage",
            object_id=tender.tender_id,
            severity="medium",
            status="open",
            responsible="Projektvezetés / Beszerzés",
            next_action=f"Ajánlatok fogadása eddig: {tender.submission_deadline_at.isoformat()}",
            executive_relevance=False,
            payload={
                "title": tender.title,
                "submission_deadline_at": tender.submission_deadline_at.isoformat(),
            },
            route_to=["procurement", "project-control"],
        ),
        actor=_email(user),
    )
    audit(
        db,
        actor=_email(user),
        action="tender.published",
        entity_type="tender",
        entity_id=tender_id,
        after={"version": tender.version, "event_id": event.event_id},
    )
    db.commit()
    return get_tender(db, tender_id)


def close_tender(db: Session, tender_id: str, user: object) -> TenderPackage:
    tender = get_tender(db, tender_id, for_update=True)
    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs tenderzárási jogosultság.")
    if tender.status != "published":
        raise ValueError("Csak közzétett tender zárható le.")
    tender.status = "evaluation"
    tender.closed_at = utcnow()
    tender.version += 1
    audit(
        db,
        actor=_email(user),
        action="tender.closed",
        entity_type="tender",
        entity_id=tender_id,
        after={
            "status": tender.status,
            "submitted_bids": sum(b.status == "submitted" for b in tender.bids),
        },
    )
    db.commit()
    return get_tender(db, tender_id)


def partner_workspace(
    db: Session,
    tender_id: str,
    token: str,
    *,
    mark_viewed: bool = True,
    for_update: bool = False,
) -> dict[str, Any]:
    lock_rows = mark_viewed or for_update
    tender = get_tender(db, tender_id, for_update=lock_rows)
    invitation_query = (
        select(TenderInvitation)
        .options(
            selectinload(TenderInvitation.bid).selectinload(TenderBid.items),
            selectinload(TenderInvitation.bid).selectinload(TenderBid.evidence),
        )
        .where(TenderInvitation.tender_id_fk == tender.id, TenderInvitation.access_token == token)
    )
    invitation = db.scalar(
        invitation_query.with_for_update() if lock_rows else invitation_query
    )
    if invitation is None:
        recipient = db.scalar(
            select(TenderMailRecipient).where(TenderMailRecipient.tracking_token == token)
        )
        campaign = (
            db.scalar(
                select(TenderMailCampaign).where(
                    TenderMailCampaign.campaign_id == recipient.campaign_id,
                    TenderMailCampaign.tender_id == tender_id,
                )
            )
            if recipient
            else None
        )
        if recipient and campaign:
            invitation = TenderInvitation(
                invitation_id=_id("TINV"),
                tender_id_fk=tender.id,
                mail_recipient_id=recipient.recipient_id,
                partner_email=recipient.email,
                company_name=recipient.company_name or recipient.email,
                contact_name=recipient.contact_name,
                access_token=recipient.tracking_token,
                token_revision=1,
                expires_at=tender.submission_deadline_at,
                status="invited",
            )
            db.add(invitation)
            db.commit()
            db.refresh(invitation)
        else:
            raise PermissionError("Érvénytelen vagy más tenderhez tartozó meghívó.")
    if tender.status == "draft":
        raise PermissionError("A tender még nincs közzétéve.")
    if invitation.status == "revoked":
        raise PermissionError("A tendermeghívó hozzáférését visszavonták.")
    if utcnow() > _aware(invitation.expires_at):
        if invitation.status != "expired":
            invitation.status = "expired"
            audit(
                db,
                actor="system:tender-access",
                action="tender.invitation.expired",
                entity_type="tender",
                entity_id=tender_id,
                after={"invitation_id": invitation.invitation_id},
            )
            db.commit()
        raise PermissionError("A tendermeghívó hozzáférése lejárt.")
    if mark_viewed and invitation.viewed_at is None:
        invitation.viewed_at = utcnow()
        if invitation.status == "invited":
            invitation.status = "viewed"
        db.commit()
    clarifications = list(
        db.scalars(
            select(TenderClarification)
            .where(
                TenderClarification.tender_id_fk == tender.id,
                TenderClarification.partner_visible.is_(True),
                (TenderClarification.invitation_id_fk.is_(None))
                | (TenderClarification.invitation_id_fk == invitation.id),
            )
            .order_by(TenderClarification.created_at)
        )
    )
    db.refresh(invitation)
    formal_requests = (
        list(db.scalars(select(TenderClarificationRequest).where(
            TenderClarificationRequest.bid_id_fk == invitation.bid.id
        ).order_by(TenderClarificationRequest.created_at)))
        if invitation.bid else []
    )
    return {
        "tender": tender,
        "invitation": invitation,
        "bid": invitation.bid,
        "clarifications": clarifications,
        "clarification_requests": formal_requests,
        "token": token,
        "now": utcnow(),
        "question_open": tender.status == "published"
        and utcnow() <= _aware(tender.question_deadline_at),
        "submission_open": tender.status == "published"
        and utcnow() <= _aware(tender.submission_deadline_at),
        "av": tender_av_configuration(),
    }


def manage_invitation_access(
    db: Session,
    tender_id: str,
    invitation_id: str,
    user: object,
    *,
    action: str,
    reason: str = "",
) -> TenderInvitation:
    """Rotate or revoke one partner link without mutating the submitted bid."""

    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs tendermeghívó-kezelési jogosultság.")
    tender = get_tender(db, tender_id, for_update=True)
    invitation = db.scalar(
        select(TenderInvitation)
        .where(
            TenderInvitation.tender_id_fk == tender.id,
            TenderInvitation.invitation_id == invitation_id,
        )
        .with_for_update()
    )
    if invitation is None:
        raise KeyError(invitation_id)
    clean_reason = reason.strip()
    if action == "revoke":
        if len(clean_reason) < 5:
            raise ValueError("A hozzáférés visszavonásának indoka kötelező.")
        if invitation.status == "revoked":
            return invitation
        invitation.status = "revoked"
        invitation.revoked_at = utcnow()
        invitation.revoked_by = _email(user)
        invitation.revoke_reason = clean_reason
    elif action == "rotate":
        if tender.status not in {"draft", "published"}:
            raise ValueError("Lezárt tender meghívólinkje nem cserélhető.")
        if _aware(tender.submission_deadline_at) <= utcnow():
            raise ValueError("Lejárt tender meghívólinkje nem cserélhető.")
        invitation.access_token = secrets.token_urlsafe(48)
        invitation.token_revision += 1
        invitation.expires_at = tender.submission_deadline_at
        invitation.status = "viewed" if invitation.viewed_at else "invited"
        invitation.revoked_at = None
        invitation.revoked_by = None
        invitation.revoke_reason = None
    else:
        raise ValueError("Ismeretlen meghívólink-művelet.")
    audit(
        db,
        actor=_email(user),
        action=f"tender.invitation.{action}",
        entity_type="tender",
        entity_id=tender_id,
        after={
            "invitation_id": invitation.invitation_id,
            "token_revision": invitation.token_revision,
            "expires_at": invitation.expires_at.isoformat(),
            "reason": clean_reason or None,
        },
    )
    db.commit()
    db.refresh(invitation)
    return invitation


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Érvénytelen szám: {field}.") from exc
    if result < 0 or (positive and result <= 0):
        raise ValueError(f"A(z) {field} értéke nem megfelelő.")
    return result


UNIT_ALIASES: dict[str, tuple[str, Decimal]] = {
    "db": ("db", Decimal("1")), "pcs": ("db", Decimal("1")), "darab": ("db", Decimal("1")),
    "m": ("m", Decimal("1")), "fm": ("m", Decimal("1")),
    "m2": ("m2", Decimal("1")), "m²": ("m2", Decimal("1")),
    "m3": ("m3", Decimal("1")), "m³": ("m3", Decimal("1")),
    "kg": ("kg", Decimal("1")), "g": ("kg", Decimal("0.001")), "t": ("kg", Decimal("1000")),
    "óra": ("hour", Decimal("1")), "ora": ("hour", Decimal("1")), "hour": ("hour", Decimal("1")),
}


def _canonical_unit(unit: str) -> str:
    key = re.sub(r"\s+", "", str(unit or "").strip().lower())
    if key not in UNIT_ALIASES:
        raise ValueError(f"Nem normalizálható mértékegység: {unit}.")
    return UNIT_ALIASES[key][0]


def _normalize_item(source_unit: str, quantity: Decimal) -> tuple[str, Decimal]:
    key = re.sub(r"\s+", "", source_unit.strip().lower())
    if key not in UNIT_ALIASES:
        return source_unit.strip().lower(), quantity
    normalized, factor = UNIT_ALIASES[key]
    return normalized, (quantity * factor).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _snapshot_bid(db: Session, tender: TenderPackage, bid: TenderBid, *, lifecycle_status: str) -> TenderBidVersion:
    existing = db.scalar(select(TenderBidVersion).where(TenderBidVersion.bid_id_fk == bid.id, TenderBidVersion.version == bid.version))
    if existing:
        return existing
    tender_lines = sorted(tender.line_items, key=lambda row: row.line_no)
    bid_items = sorted(bid.items, key=lambda row: row.line_no)
    issues: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    matched_ids: set[str] = set()
    for index, item in enumerate(bid_items):
        master = tender_lines[index] if index < len(tender_lines) else None
        normalized_unit, normalized_quantity = _normalize_item(item.unit, item.quantity)
        reasons: list[str] = []
        if master is None:
            reasons.append("unmatched_extra_line")
        else:
            matched_ids.add(master.line_item_id)
            if normalized_unit != master.unit:
                reasons.append("unit_mismatch")
            elif master.quantity and abs(normalized_quantity - master.quantity) / master.quantity > Decimal("0.05"):
                reasons.append("quantity_variance_gt_5pct")
        if reasons:
            issues.append({"line_no": item.line_no, "reasons": reasons})
        rows.append({
            "line_no": item.line_no, "tender_line_item_id": master.line_item_id if master else None,
            "description": item.description, "source_unit": item.unit,
            "normalized_unit": normalized_unit, "source_quantity": str(item.quantity),
            "normalized_quantity": str(normalized_quantity), "unit_price": str(item.unit_price),
            "net_total": str(item.net_total), "review_required": bool(reasons),
            "review_reason": ",".join(reasons) or None,
        })
    for master in tender_lines:
        if master.required and master.line_item_id not in matched_ids:
            issues.append({"line_code": master.line_code, "reasons": ["missing_required_line"]})
    payload = {
        "bid_id": bid.bid_id, "version": bid.version, "currency": bid.currency,
        "net_total": str(bid.net_total), "vat_total": str(bid.vat_total), "gross_total": str(bid.gross_total),
        "summary": bid.summary, "exclusions": bid.exclusions, "items": rows,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    version = TenderBidVersion(
        bid_version_id=_id("TBVER"), bid_id_fk=bid.id, version=bid.version,
        lifecycle_status=lifecycle_status, currency=bid.currency, net_total=bid.net_total,
        vat_total=bid.vat_total, gross_total=bid.gross_total, summary=bid.summary,
        exclusions=bid.exclusions, normalization_status="review_required" if issues else "clean",
        normalization_issues_json=json.dumps(issues, ensure_ascii=False, sort_keys=True), content_sha256=digest,
    )
    db.add(version)
    db.flush()
    for normalized_row in rows:
        db.add(TenderBidVersionItem(
            version_item_id=_id("TBVITEM"), bid_version_id_fk=version.id,
            line_no=normalized_row["line_no"], tender_line_item_id=normalized_row["tender_line_item_id"],
            description=normalized_row["description"], source_unit=normalized_row["source_unit"],
            normalized_unit=normalized_row["normalized_unit"], source_quantity=Decimal(normalized_row["source_quantity"]),
            normalized_quantity=Decimal(normalized_row["normalized_quantity"]), unit_price=Decimal(normalized_row["unit_price"]),
            net_total=Decimal(normalized_row["net_total"]), review_required=normalized_row["review_required"],
            review_reason=normalized_row["review_reason"],
        ))
    return version


def save_bid(
    db: Session,
    tender_id: str,
    token: str,
    *,
    items: list[dict[str, Any]],
    vat_percent: Any,
    validity_days: int,
    lead_time_days: int,
    warranty_months: int,
    summary: str,
    exclusions: str,
) -> TenderBid:
    workspace = partner_workspace(
        db, tender_id, token, mark_viewed=False, for_update=True
    )
    tender: TenderPackage = workspace["tender"]
    invitation: TenderInvitation = workspace["invitation"]
    if not workspace["submission_open"]:
        raise ValueError("Az ajánlattételi határidő lejárt vagy a tender lezárult.")
    if invitation.status == "declined":
        raise ValueError("A meghívást korábban visszautasították.")
    bid = invitation.bid
    if bid and bid.status in {"submitted", "awarded", "rejected"}:
        raise ValueError("A beadott ajánlat csak visszavonás után módosítható.")
    if not bid:
        bid = TenderBid(
            bid_id=_id("TBID"),
            tender_id_fk=tender.id,
            invitation_id_fk=invitation.id,
            currency=tender.currency,
            status="draft",
        )
        db.add(bid)
        db.flush()
    else:
        bid.items.clear()
        # Flush removed line numbers before reusing them in the replacement
        # version; PostgreSQL and SQLite both enforce the per-bid line key.
        db.flush()
        bid.version += 1
        bid.status = "draft"
        bid.withdrawn_at = None
    clean_items: list[TenderBidItem] = []
    total = Decimal("0")
    for index, item in enumerate(items, start=1):
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        quantity = _decimal(item.get("quantity"), f"{index}. tétel mennyisége", positive=True)
        unit_price = _decimal(item.get("unit_price"), f"{index}. tétel egységára")
        net = (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total += net
        clean_items.append(
            TenderBidItem(
                item_id=_id("TITEM"),
                bid_id_fk=bid.id,
                line_no=len(clean_items) + 1,
                description=description,
                unit=str(item.get("unit") or "db").strip()[:40] or "db",
                quantity=quantity,
                unit_price=unit_price,
                net_total=net,
            )
        )
    if not clean_items:
        raise ValueError("Legalább egy tételes ajánlati sor kötelező.")
    vat = _decimal(vat_percent, "ÁFA-kulcs")
    if vat > 100:
        raise ValueError("Az ÁFA-kulcs legfeljebb 100% lehet.")
    if (
        not 1 <= int(validity_days) <= 365
        or not 0 <= int(lead_time_days) <= 3650
        or not 0 <= int(warranty_months) <= 240
    ):
        raise ValueError(
            "Az érvényesség, átfutás vagy garancia értéke kívül esik az engedélyezett tartományon."
        )
    bid.items.extend(clean_items)
    bid.net_total = total
    bid.vat_total = (total * vat / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    bid.gross_total = bid.net_total + bid.vat_total
    bid.validity_days = int(validity_days)
    bid.lead_time_days = int(lead_time_days)
    bid.warranty_months = int(warranty_months)
    bid.summary = summary.strip() or None
    bid.exclusions = exclusions.strip() or None
    invitation.status = "viewed"
    db.flush()
    version = _snapshot_bid(db, tender, bid, lifecycle_status="draft")
    audit(
        db,
        actor=invitation.partner_email,
        action="tender.bid.saved",
        entity_type="tender_bid",
        entity_id=bid.bid_id,
        after={
            "tender_id": tender_id,
            "version": bid.version,
            "net_total": str(total),
            "item_count": len(clean_items),
            "bid_version_id": version.bid_version_id,
            "content_sha256": version.content_sha256,
            "normalization_status": version.normalization_status,
        },
    )
    db.commit()
    db.refresh(bid)
    return bid


def submit_bid(db: Session, tender_id: str, token: str) -> TenderBid:
    workspace = partner_workspace(
        db, tender_id, token, mark_viewed=False, for_update=True
    )
    invitation: TenderInvitation = workspace["invitation"]
    bid = invitation.bid
    if not workspace["submission_open"]:
        raise ValueError("Az ajánlattételi határidő lejárt vagy a tender lezárult.")
    if bid is None or not bid.items or bid.net_total <= 0:
        raise ValueError("Beadás előtt mentett, pozitív összegű tételes ajánlat szükséges.")
    if bid.status != "draft":
        raise ValueError("Csak vázlat ajánlat adható be.")
    if not bid.summary or len(bid.summary) < 10:
        raise ValueError("Beadás előtt legalább 10 karakteres ajánlati összefoglaló kötelező.")
    bid.status = "submitted"
    bid.submitted_at = utcnow()
    invitation.status = "submitted"
    version = db.scalar(select(TenderBidVersion).where(TenderBidVersion.bid_id_fk == bid.id, TenderBidVersion.version == bid.version))
    if version is None:
        version = _snapshot_bid(db, workspace["tender"], bid, lifecycle_status="submitted")
    else:
        version.lifecycle_status = "submitted"
    audit(
        db,
        actor=invitation.partner_email,
        action="tender.bid.submitted",
        entity_type="tender_bid",
        entity_id=bid.bid_id,
        after={"version": bid.version, "gross_total": str(bid.gross_total)},
    )
    db.commit()
    db.refresh(bid)
    return bid


def create_clarification_request(
    db: Session, tender_id: str, bid_id: str, user: object, *, question: str, due_at: datetime
) -> TenderClarificationRequest:
    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs hiánypótlási jogosultság.")
    tender = get_tender(db, tender_id, for_update=True)
    bid = db.scalar(select(TenderBid).where(TenderBid.tender_id_fk == tender.id, TenderBid.bid_id == bid_id))
    if bid is None or bid.status != "submitted":
        raise ValueError("Hiánypótlás csak beadott ajánlathoz indítható.")
    if len(question.strip()) < 10 or _aware(due_at) <= utcnow():
        raise ValueError("Részletes hiánypótlási kérdés és jövőbeli határidő kötelező.")
    row = TenderClarificationRequest(
        request_id=_id("TCR"), tender_id_fk=tender.id, bid_id_fk=bid.id,
        question=question.strip(), due_at=_aware(due_at), status="open", created_by=_email(user),
    )
    db.add(row)
    audit(db, actor=_email(user), action="tender.clarification_request.created", entity_type="tender_bid", entity_id=bid_id, after={"request_id": row.request_id, "due_at": row.due_at})
    db.commit()
    db.refresh(row)
    return row


def respond_clarification_request(db: Session, tender_id: str, token: str, request_id: str, *, response: str) -> TenderClarificationRequest:
    workspace = partner_workspace(
        db, tender_id, token, mark_viewed=False, for_update=True
    )
    bid = workspace["invitation"].bid
    row = db.scalar(
        select(TenderClarificationRequest)
        .where(TenderClarificationRequest.request_id == request_id)
        .with_for_update()
    )
    if row is None or bid is None or row.bid_id_fk != bid.id:
        raise PermissionError("A hiánypótlás nem ehhez a meghíváshoz tartozik.")
    if row.status not in {"open", "answered"} or len(response.strip()) < 10:
        raise ValueError("A hiánypótlás nem válaszolható vagy a válasz túl rövid.")
    row.response = response.strip()
    row.responded_at = utcnow()
    row.status = "answered"
    audit(db, actor=workspace["invitation"].partner_email, action="tender.clarification_request.answered", entity_type="tender_bid", entity_id=bid.bid_id, after={"request_id": request_id})
    db.commit()
    return row


def accept_clarification_request(db: Session, request_id: str, user: object, *, note: str) -> TenderClarificationRequest:
    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs hiánypótlás-elfogadási jogosultság.")
    row = db.scalar(
        select(TenderClarificationRequest)
        .where(TenderClarificationRequest.request_id == request_id)
        .with_for_update()
    )
    if row is None:
        raise KeyError(request_id)
    if row.status != "answered" or len(note.strip()) < 5:
        raise ValueError("Csak megválaszolt hiánypótlás fogadható el indoklással.")
    row.status = "accepted"
    row.acceptance_note = note.strip()
    row.accepted_by = _email(user)
    row.accepted_at = utcnow()
    audit(db, actor=_email(user), action="tender.clarification_request.accepted", entity_type="tender_clarification_request", entity_id=request_id, after={"note": row.acceptance_note})
    db.commit()
    return row


def withdraw_bid(db: Session, tender_id: str, token: str) -> TenderBid:
    workspace = partner_workspace(
        db, tender_id, token, mark_viewed=False, for_update=True
    )
    bid = workspace["invitation"].bid
    if not workspace["submission_open"] or bid is None or bid.status != "submitted":
        raise ValueError("Csak határidőn belüli beadott ajánlat vonható vissza.")
    bid.status = "withdrawn"
    bid.withdrawn_at = utcnow()
    workspace["invitation"].status = "viewed"
    audit(
        db,
        actor=workspace["invitation"].partner_email,
        action="tender.bid.withdrawn",
        entity_type="tender_bid",
        entity_id=bid.bid_id,
        after={"version": bid.version},
    )
    db.commit()
    return bid


def decline_invitation(db: Session, tender_id: str, token: str, reason: str) -> TenderInvitation:
    workspace = partner_workspace(
        db, tender_id, token, mark_viewed=False, for_update=True
    )
    invitation = workspace["invitation"]
    if invitation.bid and invitation.bid.status == "submitted":
        raise ValueError("Beadott ajánlat mellett a meghívás nem utasítható vissza.")
    if len(reason.strip()) < 5:
        raise ValueError("A visszautasítás rövid indoklása kötelező.")
    invitation.status = "declined"
    invitation.declined_at = utcnow()
    invitation.decline_reason = reason.strip()
    audit(
        db,
        actor=invitation.partner_email,
        action="tender.invitation.declined",
        entity_type="tender",
        entity_id=tender_id,
        after={"invitation_id": invitation.invitation_id, "reason": reason.strip()},
    )
    db.commit()
    return invitation


def add_clarification(
    db: Session,
    tender_id: str,
    *,
    body: str,
    user: object | None = None,
    token: str = "",
    invitation_id: str = "",
    partner_visible: bool = True,
) -> TenderClarification:
    tender = get_tender(db, tender_id, for_update=True)
    if len(body.strip()) < 3:
        raise ValueError("A tisztázó kérdés vagy válasz nem lehet üres.")
    invitation: TenderInvitation | None
    if user is None:
        workspace = partner_workspace(
            db, tender_id, token, mark_viewed=False, for_update=True
        )
        if not workspace["question_open"]:
            raise ValueError("A tisztázó kérdések határideje lejárt.")
        invitation = workspace["invitation"]
        author_email = invitation.partner_email
        author_type = "partner"
        partner_visible = True
    else:
        if _role(user) not in INTERNAL_ROLES:
            raise PermissionError("Nincs tenderkommunikációs jogosultság.")
        invitation = (
            db.scalar(
                select(TenderInvitation).where(
                    TenderInvitation.tender_id_fk == tender.id,
                    TenderInvitation.invitation_id == invitation_id,
                )
            )
            if invitation_id
            else None
        )
        author_email = _email(user)
        author_type = "internal"
    row = TenderClarification(
        clarification_id=_id("TCLR"),
        tender_id_fk=tender.id,
        invitation_id_fk=invitation.id if invitation else None,
        author_email=author_email,
        author_type=author_type,
        body=body.strip(),
        partner_visible=partner_visible,
    )
    db.add(row)
    audit(
        db,
        actor=author_email,
        action="tender.clarification.added",
        entity_type="tender",
        entity_id=tender_id,
        after={
            "clarification_id": row.clarification_id,
            "author_type": author_type,
            "partner_visible": partner_visible,
            "invitation_id": invitation_id or None,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def save_bid_evidence(
    db: Session,
    tender_id: str,
    token: str,
    *,
    file_name: str,
    mime_type: str,
    raw: bytes,
    caption: str,
    storage_root: Path,
) -> TenderBidEvidence:
    workspace = partner_workspace(
        db, tender_id, token, mark_viewed=False, for_update=True
    )
    bid = workspace["invitation"].bid
    if not workspace["submission_open"] or bid is None or bid.status not in {"draft", "withdrawn"}:
        raise ValueError("Melléklet csak nyitott tender mentett vázlatához tölthető fel.")
    if not raw or len(raw) > MAX_EVIDENCE_BYTES:
        raise ValueError("A melléklet mérete 1 bájt és 25 MB között lehet.")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        validate_tender_evidence_content(file_name, mime_type, raw)
    except ValueError:
        audit(
            db,
            actor=workspace["invitation"].partner_email,
            action="tender.bid.evidence.rejected",
            entity_type="tender_bid",
            entity_id=bid.bid_id,
            after={
                "sha256": digest,
                "mime_type": mime_type,
                "scan_status": "content_rejected",
            },
        )
        db.commit()
        raise
    try:
        scan = scan_tender_evidence(raw)
    except TenderMalwareDetected:
        audit(
            db,
            actor=workspace["invitation"].partner_email,
            action="tender.bid.evidence.rejected",
            entity_type="tender_bid",
            entity_id=bid.bid_id,
            after={"sha256": digest, "mime_type": mime_type, "scan_status": "infected"},
        )
        db.commit()
        raise
    except TenderScannerUnavailable:
        audit(
            db,
            actor=workspace["invitation"].partner_email,
            action="tender.bid.evidence.rejected",
            entity_type="tender_bid",
            entity_id=bid.bid_id,
            after={"sha256": digest, "mime_type": mime_type, "scan_status": "unavailable"},
        )
        db.commit()
        raise
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file_name).name).strip("._") or "attachment"
    evidence_id = _id("TEV")
    target_dir = storage_root / tender_id / bid.bid_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{evidence_id}_{safe_name[:120]}"
    target.write_bytes(raw)
    row = TenderBidEvidence(
        evidence_id=evidence_id,
        bid_id_fk=bid.id,
        file_name=safe_name[:500],
        mime_type=mime_type,
        sha256=digest,
        storage_path=str(target),
        caption=caption.strip() or None,
        scan_status=scan.status,
        scan_engine=scan.engine,
        scan_engine_version=scan.engine_version,
        scan_signature=scan.signature,
        scanned_at=utcnow(),
    )
    db.add(row)
    audit(
        db,
        actor=workspace["invitation"].partner_email,
        action="tender.bid.evidence.added",
        entity_type="tender_bid",
        entity_id=bid.bid_id,
        after={
            "evidence_id": evidence_id,
            "sha256": digest,
            "mime_type": mime_type,
            "scan_status": scan.status,
            "scan_engine": scan.engine,
            "scan_engine_version": scan.engine_version,
        },
    )
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    db.refresh(row)
    return row


def evidence_for_partner(
    db: Session, evidence_id: str, tender_id: str, token: str
) -> TenderBidEvidence:
    workspace = partner_workspace(db, tender_id, token, mark_viewed=False)
    evidence = db.scalar(
        select(TenderBidEvidence).where(TenderBidEvidence.evidence_id == evidence_id)
    )
    if evidence is None:
        raise KeyError(evidence_id)
    bid = workspace["invitation"].bid
    if bid is None or evidence.bid_id_fk != bid.id:
        raise PermissionError(evidence_id)
    return evidence


def evidence_for_internal(db: Session, evidence_id: str, user: object) -> TenderBidEvidence:
    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs tenderdokumentum-letöltési jogosultság.")
    evidence = db.scalar(
        select(TenderBidEvidence).where(TenderBidEvidence.evidence_id == evidence_id)
    )
    if evidence is None:
        raise KeyError(evidence_id)
    return evidence


def verified_evidence_path(
    db: Session,
    evidence: TenderBidEvidence,
    *,
    storage_root: Path,
    actor: str,
    channel: str,
) -> Path:
    path = Path(evidence.storage_path).resolve()
    root = storage_root.resolve()
    failure: str | None = None
    if evidence.scan_status != "clean":
        failure = f"scan_status:{evidence.scan_status}"
    elif not path.is_relative_to(root) or not path.is_file():
        failure = "storage_path_unavailable"
    elif hashlib.sha256(path.read_bytes()).hexdigest() != evidence.sha256:
        failure = "sha256_mismatch"
    if failure:
        audit(
            db,
            actor=actor,
            action="tender.bid.evidence.download_blocked",
            entity_type="tender_bid_evidence",
            entity_id=evidence.evidence_id,
            after={"channel": channel, "reason": failure},
        )
        db.commit()
        raise TenderEvidenceUnavailable(
            "A melléklet nem rendelkezik érvényes tiszta scan- és integritásbizonyítékkal."
        )
    audit(
        db,
        actor=actor,
        action="tender.bid.evidence.downloaded",
        entity_type="tender_bid_evidence",
        entity_id=evidence.evidence_id,
        after={"channel": channel, "sha256": evidence.sha256},
    )
    db.commit()
    return path


def evaluate_bid(
    db: Session,
    tender_id: str,
    bid_id: str,
    user: object,
    *,
    price_score: int,
    technical_score: int,
    timeline_score: int,
    references_score: int,
    recommendation: str,
    notes: str,
) -> TenderEvaluation:
    tender = get_tender(db, tender_id, for_update=True)
    if _role(user) not in INTERNAL_ROLES:
        raise PermissionError("Nincs ajánlatértékelési jogosultság.")
    if tender.status not in {"evaluation", "closed"}:
        raise ValueError("Ajánlat csak lezárt tenderben értékelhető.")
    bid = db.scalar(
        select(TenderBid).where(TenderBid.tender_id_fk == tender.id, TenderBid.bid_id == bid_id)
    )
    if bid is None or bid.status != "submitted":
        raise ValueError("Csak beadott ajánlat értékelhető.")
    scores = {
        "price": int(price_score),
        "technical": int(technical_score),
        "timeline": int(timeline_score),
        "references": int(references_score),
    }
    if any(value < 0 or value > 100 for value in scores.values()):
        raise ValueError("Minden részpontszámnak 0 és 100 közé kell esnie.")
    if recommendation not in {"recommended", "reserve", "not_recommended"}:
        raise ValueError("Érvénytelen értékelői javaslat.")
    if len(notes.strip()) < 10:
        raise ValueError("Az értékelés szakmai indoklása kötelező.")
    weights = _criteria(tender.evaluation_criteria_json)
    weighted = sum(Decimal(scores[key]) * Decimal(weights[key]) for key in scores) / Decimal("100")
    row = db.scalar(
        select(TenderEvaluation).where(
            TenderEvaluation.bid_id_fk == bid.id, TenderEvaluation.evaluator_email == _email(user)
        )
    )
    if row is None:
        row = TenderEvaluation(
            evaluation_id=_id("TEVAL"),
            tender_id_fk=tender.id,
            bid_id_fk=bid.id,
            evaluator_email=_email(user),
            price_score=scores["price"],
            technical_score=scores["technical"],
            timeline_score=scores["timeline"],
            references_score=scores["references"],
            weighted_total=weighted,
            recommendation=recommendation,
            notes=notes.strip(),
        )
        db.add(row)
    else:
        row.price_score, row.technical_score = scores["price"], scores["technical"]
        row.timeline_score, row.references_score = scores["timeline"], scores["references"]
        row.weighted_total, row.recommendation, row.notes = weighted, recommendation, notes.strip()
    audit(
        db,
        actor=_email(user),
        action="tender.bid.evaluated",
        entity_type="tender_bid",
        entity_id=bid_id,
        after={"weighted_total": str(weighted), "recommendation": recommendation},
    )
    db.commit()
    db.refresh(row)
    return row


def award_bid(
    db: Session, tender_id: str, bid_id: str, user: object, *, summary: str
) -> TenderPackage:
    tender = get_tender(db, tender_id, for_update=True)
    if _role(user) not in DECISION_ROLES:
        raise PermissionError("Az eredményhirdetés vezetői döntési jogosultságot igényel.")
    if tender.status not in {"evaluation", "closed"}:
        raise ValueError("Eredmény csak lezárt, értékelés alatt álló tenderben hirdethető.")
    bid = db.scalar(
        select(TenderBid).where(TenderBid.tender_id_fk == tender.id, TenderBid.bid_id == bid_id)
    )
    if bid is None or bid.status != "submitted":
        raise ValueError("Csak beadott ajánlat nyerhet.")
    if not bid.evaluations:
        raise ValueError("Eredményhirdetés előtt legalább egy dokumentált értékelés kötelező.")
    if len(summary.strip()) < 15:
        raise ValueError("A vezetői odaítélési indoklás legalább 15 karakter legyen.")
    invitation = db.scalar(select(TenderInvitation).where(TenderInvitation.id == bid.invitation_id_fk))
    if invitation is None or not invitation.partner_id:
        raise ValueError("Az ajánlat nem kapcsolódik kanonikus PartnerID-hez.")
    version = db.scalar(select(TenderBidVersion).where(TenderBidVersion.bid_id_fk == bid.id, TenderBidVersion.version == bid.version))
    if version is None or version.normalization_status != "clean":
        raise ValueError("Az ajánlat tételes normalizálása hiányos vagy manuális felülvizsgálatot igényel.")
    outstanding = db.scalar(select(func.count()).select_from(TenderClarificationRequest).where(
        TenderClarificationRequest.bid_id_fk == bid.id,
        TenderClarificationRequest.status != "accepted",
    )) or 0
    if outstanding:
        raise ValueError("Nyitott vagy még el nem fogadott hiánypótlás mellett nem hirdethető eredmény.")
    eligibility = eligibility_report(db, invitation.partner_id, tender=tender, contract_value=bid.net_total)
    if tender.prequalification_required and not eligibility["eligible"]:
        raise ValueError("A partner nem felel meg az odaítélési kapunak: " + ", ".join(eligibility["blockers"]))
    tender.status = "awarded"
    tender.awarded_bid_id = bid.bid_id
    tender.award_summary = summary.strip()
    tender.awarded_by = _email(user)
    tender.awarded_at = utcnow()
    tender.version += 1
    for candidate in tender.bids:
        if candidate.status == "submitted":
            candidate.status = "awarded" if candidate.bid_id == bid_id else "rejected"
    event = db.scalar(
        select(EventRecord).where(
            EventRecord.source_module == "tendermail",
            EventRecord.object_type == "TenderPackage",
            EventRecord.object_id == tender_id,
        )
    )
    if event:
        event.status = "resolved"
        task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == event.event_id))
        if task:
            task.status = "done"
    version_items = list(db.scalars(select(TenderBidVersionItem).where(TenderBidVersionItem.bid_version_id_fk == version.id).order_by(TenderBidVersionItem.line_no)))
    line_snapshot = [{
        "line_no": item.line_no, "tender_line_item_id": item.tender_line_item_id,
        "description": item.description, "unit": item.normalized_unit,
        "quantity": str(item.normalized_quantity), "unit_price": str(item.unit_price),
        "net_total": str(item.net_total),
    } for item in version_items]
    po_payload = {
        "tender_id": tender_id, "project_id": tender.project_id,
        "partner_id": invitation.partner_id, "bid_id": bid.bid_id,
        "bid_version_id": version.bid_version_id, "lines": line_snapshot,
        "exclusions": bid.exclusions, "eligibility": eligibility,
    }
    po_json = json.dumps(po_payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    preparation = TenderPurchaseOrderPreparation(
        preparation_id=_id("POPREP"), tender_id=tender_id, project_id=tender.project_id,
        partner_id=invitation.partner_id, bid_id=bid.bid_id, bid_version_id=version.bid_version_id,
        line_snapshot_json=json.dumps(line_snapshot, ensure_ascii=False, sort_keys=True),
        exclusions=bid.exclusions, status="draft", eligibility_snapshot_json=json.dumps(eligibility, ensure_ascii=False, sort_keys=True),
        content_sha256=hashlib.sha256(po_json.encode("utf-8")).hexdigest(), prepared_by=_email(user),
    )
    db.add(preparation)
    audit(
        db,
        actor=_email(user),
        action="tender.awarded",
        entity_type="tender",
        entity_id=tender_id,
        after={
            "awarded_bid_id": bid_id,
            "award_summary": summary.strip(),
            "version": tender.version,
            "partner_id": invitation.partner_id,
            "bid_version_id": version.bid_version_id,
            "purchase_order_preparation_id": preparation.preparation_id,
        },
    )
    db.commit()
    return get_tender(db, tender_id)
