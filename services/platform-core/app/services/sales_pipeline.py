from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    EnterpriseCanonicalRecord,
    MarketingLead,
    ModuleBusinessRecord,
    ProjectObjectState,
    ProjectRegistry,
    SalesOpportunity,
    SalesProposalVersion,
)
from ..schemas import (
    EventIn,
    SalesOpportunityCloseIn,
    SalesOpportunityIn,
    SalesOpportunityStageIn,
    SalesProposalDecisionIn,
    SalesProposalIn,
    SalesProposalReviewIn,
    SalesProposalSendIn,
)
from .integration import ingest_event

SALES_ROLES = {"owner", "managing-director", "platform-admin", "sales"}
PIPELINE_VIEW_ROLES = SALES_ROLES | {"finance", "legal", "technical-prep"}
OPEN_STAGES = {"new", "qualified", "discovery", "proposal", "negotiation", "contracting"}
MINIMUM_MARGIN_PERCENT = Decimal("35.00")
PIPELINE_PROJECT_ID = "COMMERCIAL-PIPELINE"


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _require(user: object, roles: set[str]) -> tuple[str, str]:
    role = str(getattr(user, "role", ""))
    email = str(getattr(user, "email", "")).strip().lower()
    if role not in roles or "@" not in email:
        raise PermissionError("A művelethez nincs megfelelő értékesítési jogosultság.")
    return role, email


def _ensure_pipeline(db: Session, responsible: str) -> ProjectRegistry:
    row = db.scalar(
        select(ProjectRegistry).where(ProjectRegistry.project_id == PIPELINE_PROJECT_ID)
    )
    if row:
        return row
    row = ProjectRegistry(
        project_id=PIPELINE_PROJECT_ID,
        name="Értékesítési opportunity pipeline",
        project_type="commercial_pipeline",
        status="active",
        responsible=responsible,
        next_action="Nyitott opportunity-k következő lépéseinek végrehajtása.",
    )
    db.add(row)
    db.flush()
    return row


def _opportunity(db: Session, opportunity_id: str, *, lock: bool = False) -> SalesOpportunity:
    stmt = select(SalesOpportunity).where(SalesOpportunity.opportunity_id == opportunity_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(opportunity_id)
    return row


def _proposal(db: Session, proposal_version_id: str, *, lock: bool = False) -> SalesProposalVersion:
    stmt = select(SalesProposalVersion).where(
        SalesProposalVersion.proposal_version_id == proposal_version_id
    )
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(proposal_version_id)
    return row


def _canonical_customer_reference(
    db: Session, *, lead_id: str | None, customer_id: str | None
) -> EnterpriseCanonicalRecord:
    if not lead_id and not customer_id:
        raise ValueError("LeadID vagy kanonikus CustomerID megadása kötelező.")
    candidates = [value for value in (lead_id, customer_id) if value]
    row = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.domain == "customer",
            EnterpriseCanonicalRecord.external_key.in_(candidates),
        )
    )
    if row:
        return row
    if lead_id:
        lead = db.scalar(select(MarketingLead).where(MarketingLead.lead_id == lead_id))
        if lead:
            raise ValueError("A lead még nincs kanonikusan átadva a CRM-nek.")
    raise ValueError("A megadott LeadID/CustomerID nem található a kanonikus CRM-törzsben.")


def _proposal_payload(row: SalesProposalVersion) -> dict[str, Any]:
    return {
        "opportunity_id": row.opportunity_id,
        "version": row.version,
        "currency": row.currency,
        "vat_rate": str(row.vat_rate),
        "cost_net": str(row.cost_net),
        "sale_net": str(row.sale_net),
        "vat_amount": str(row.vat_amount),
        "sale_gross": str(row.sale_gross),
        "margin_net": str(row.margin_net),
        "margin_percent": str(row.margin_percent),
        "price_snapshot_id": row.price_snapshot_id,
        "terms_version_id": row.terms_version_id,
        "technical_scope_version_id": row.technical_scope_version_id,
        "scope_summary": row.scope_summary,
        "exclusions": row.exclusions,
        "payment_terms": row.payment_terms,
        "valid_until": _aware(row.valid_until).isoformat(),
    }


def _proposal_hash(row: SalesProposalVersion) -> str:
    encoded = json.dumps(
        _proposal_payload(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sync_canonical(db: Session, row: SalesOpportunity) -> None:
    payload = {
        "id": row.opportunity_id,
        "leadId": row.lead_id,
        "customerId": row.customer_id,
        "crmRecordId": row.crm_record_id,
        "brandId": row.brand_id,
        "name": row.title,
        "customerName": row.customer_name,
        "customerEmail": row.customer_email,
        "ownerEmail": row.owner_email,
        "stage": row.stage,
        "estimatedValueHuf": str(row.estimated_value_huf),
        "probabilityPercent": row.probability_percent,
        "expectedCloseDate": row.expected_close_date.isoformat()
        if row.expected_close_date
        else None,
        "nextAction": row.next_action,
        "acceptedProposalVersionId": row.accepted_proposal_version_id,
        "contractId": row.contract_id,
        "deliveryProjectId": row.delivery_project_id,
        "version": row.version,
    }
    canonical = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.domain == "customer",
            EnterpriseCanonicalRecord.entity_type == "opportunity",
            EnterpriseCanonicalRecord.external_key == row.opportunity_id,
        )
    )
    if not canonical:
        canonical = EnterpriseCanonicalRecord(
            record_id=f"CAN-{row.opportunity_id}",
            domain="customer",
            entity_type="opportunity",
            external_key=row.opportunity_id,
            canonical_name=row.title,
            target_module="crm",
        )
        db.add(canonical)
    canonical.status = "closed" if row.stage in {"won", "lost"} else "active"
    canonical.data_json = json.dumps(payload, ensure_ascii=False, default=str)
    canonical.provenance_json = json.dumps(
        {"source": "sales", "opportunityId": row.opportunity_id}, ensure_ascii=False
    )

    crm_projection_id = f"CRM-OPP-{row.opportunity_id}"
    projection = db.scalar(
        select(ModuleBusinessRecord).where(ModuleBusinessRecord.record_id == crm_projection_id)
    )
    if not projection:
        projection = ModuleBusinessRecord(
            record_id=crm_projection_id,
            module_key="crm",
            record_type="OpportunityProjection",
            title=row.title,
            status=row.stage,
            customer_reference=row.customer_id or row.lead_id,
            assignee=row.owner_email,
            amount_huf=row.estimated_value_huf,
            data_json="{}",
            created_by=row.created_by,
            updated_by=row.updated_by,
        )
        db.add(projection)
    projection.title = row.title
    projection.status = row.stage
    projection.assignee = row.owner_email
    projection.amount_huf = row.estimated_value_huf
    projection.data_json = json.dumps(payload, ensure_ascii=False, default=str)
    projection.updated_by = row.updated_by
    projection.version = row.version

    if row.lead_id:
        lead = db.scalar(
            select(EnterpriseCanonicalRecord).where(
                EnterpriseCanonicalRecord.domain == "customer",
                EnterpriseCanonicalRecord.entity_type == "lead",
                EnterpriseCanonicalRecord.external_key == row.lead_id,
            )
        )
        if lead:
            lead_payload = json.loads(lead.data_json or "{}")
            lead_payload.update({"opportunityId": row.opportunity_id, "salesStage": row.stage})
            lead.data_json = json.dumps(lead_payload, ensure_ascii=False, default=str)


def _emit(
    db: Session,
    row: SalesOpportunity,
    *,
    event_type: str,
    actor: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    route_to: list[str] | None = None,
) -> None:
    ingest_event(
        db,
        EventIn(
            event_id=_new_id("EVT"),
            dedupe_key=f"sales:{row.opportunity_id}:{event_type}:v{row.version}",
            project_id=PIPELINE_PROJECT_ID,
            source_module="sales",
            event_type=event_type,
            object_type="SalesOpportunity",
            object_id=row.opportunity_id,
            status=row.stage,
            financial_impact_huf=row.estimated_value_huf,
            responsible=row.owner_email,
            next_action=row.next_action,
            payload={"summary": summary, **(payload or {})},
            route_to=route_to or ["crm"],
        ),
        actor=actor,
    )
    db.commit()


def create_opportunity(db: Session, data: SalesOpportunityIn, user: object) -> SalesOpportunity:
    _role, email = _require(user, SALES_ROLES)
    canonical = _canonical_customer_reference(
        db, lead_id=data.lead_id, customer_id=data.customer_id
    )
    owner = data.owner_email.strip().lower()
    if "@" not in owner:
        raise ValueError("Érvényes opportunity-felelős e-mail-cím kötelező.")
    reference_filters = []
    if data.lead_id:
        reference_filters.append(SalesOpportunity.lead_id == data.lead_id)
    if data.customer_id:
        reference_filters.append(SalesOpportunity.customer_id == data.customer_id)
    duplicate = db.scalar(
        select(SalesOpportunity).where(
            SalesOpportunity.brand_id == data.brand_id,
            SalesOpportunity.stage.in_(OPEN_STAGES),
            or_(*reference_filters),
        )
    )
    if duplicate:
        raise ValueError(
            "Ehhez a kanonikus ügyfélhez már nyitott opportunity tartozik: "
            f"{duplicate.opportunity_id}."
        )
    _ensure_pipeline(db, owner)
    row = SalesOpportunity(
        opportunity_id=_new_id("OPP"),
        lead_id=data.lead_id,
        customer_id=data.customer_id
        or (canonical.external_key if canonical.entity_type != "lead" else None),
        crm_record_id=(f"CRM-{data.lead_id}" if data.lead_id else f"CRM-{canonical.external_key}"),
        brand_id=data.brand_id,
        title=data.title,
        customer_name=data.customer_name,
        customer_email=data.customer_email.strip().lower() if data.customer_email else None,
        owner_email=owner,
        estimated_value_huf=data.estimated_value_huf,
        probability_percent=data.probability_percent,
        expected_close_date=data.expected_close_date,
        needs_summary=data.needs_summary,
        budget_confirmed=data.budget_confirmed,
        decision_process=data.decision_process,
        next_action=data.next_action,
        created_by=email,
        updated_by=email,
    )
    db.add(row)
    db.flush()
    _sync_canonical(db, row)
    audit(
        db,
        actor=email,
        action="sales_opportunity_created",
        entity_type="sales_opportunity",
        entity_id=row.opportunity_id,
        after=data.model_dump(mode="json"),
    )
    _emit(
        db,
        row,
        event_type="OPPORTUNITY_CREATED",
        actor=email,
        summary="Kanonikus CRM-hivatkozású értékesítési opportunity létrejött.",
        payload={"lead_id": row.lead_id, "customer_id": row.customer_id},
        route_to=["crm", "lead-intelligence"],
    )
    db.refresh(row)
    return row


def transition_opportunity(
    db: Session, opportunity_id: str, data: SalesOpportunityStageIn, user: object
) -> SalesOpportunity:
    role, email = _require(user, SALES_ROLES)
    row = _opportunity(db, opportunity_id, lock=True)
    if role == "sales" and row.owner_email != email:
        raise PermissionError("Az opportunity másik értékesítőhöz van rendelve.")
    allowed = {
        "new": {"qualified"},
        "qualified": {"discovery"},
        "discovery": {"proposal"},
        "proposal": {"negotiation"},
        "negotiation": {"contracting", "discovery"},
        "contracting": {"negotiation"},
    }
    if data.stage not in allowed.get(row.stage, set()):
        raise ValueError(f"Tiltott opportunity-állapotváltás: {row.stage} → {data.stage}.")
    if data.stage == "proposal" and not db.scalar(
        select(SalesProposalVersion).where(SalesProposalVersion.opportunity_id == opportunity_id)
    ):
        raise ValueError(
            "Proposal szakaszhoz legalább egy ügyfélspecifikus ajánlatverzió kötelező."
        )
    before = {"stage": row.stage, "version": row.version}
    row.stage = data.stage
    row.probability_percent = data.probability_percent
    row.next_action = data.next_action
    row.updated_by = email
    row.version += 1
    _sync_canonical(db, row)
    audit(
        db,
        actor=email,
        action="sales_opportunity_stage_changed",
        entity_type="sales_opportunity",
        entity_id=row.opportunity_id,
        before=before,
        after=data.model_dump(),
    )
    _emit(
        db,
        row,
        event_type="OPPORTUNITY_STAGE_CHANGED",
        actor=email,
        summary=f"Az opportunity új szakasza: {row.stage}. {data.note}",
        payload={"note": data.note, "probability_percent": row.probability_percent},
        route_to=["crm", "finance-intelligence"],
    )
    db.refresh(row)
    return row


def create_proposal(
    db: Session, opportunity_id: str, data: SalesProposalIn, user: object
) -> SalesProposalVersion:
    role, email = _require(user, SALES_ROLES)
    opportunity = _opportunity(db, opportunity_id, lock=True)
    if opportunity.stage in {"won", "lost"}:
        raise ValueError("Lezárt opportunity-hoz nem készíthető új ajánlat.")
    if opportunity.stage not in {"discovery", "proposal"}:
        raise ValueError(
            "Ajánlatverzió csak qualified és discovery szakaszon végigvezetett "
            "opportunity-hoz készíthető."
        )
    if role == "sales" and opportunity.owner_email != email:
        raise PermissionError("Az opportunity másik értékesítőhöz van rendelve.")
    live = db.scalar(
        select(SalesProposalVersion).where(
            SalesProposalVersion.opportunity_id == opportunity_id,
            SalesProposalVersion.status.in_(
                {"draft", "internal_review", "approved", "sent", "accepted"}
            ),
        )
    )
    if live:
        raise ValueError(
            f"Az opportunity-hoz már van aktív ajánlatverzió: {live.proposal_version_id}."
        )
    previous = db.scalar(
        select(SalesProposalVersion)
        .where(SalesProposalVersion.opportunity_id == opportunity_id)
        .order_by(desc(SalesProposalVersion.version))
    )
    if previous and previous.status in {"rejected", "customer_rejected", "expired"}:
        previous.status = "superseded"
    version = (previous.version + 1) if previous else 1
    sale_net = Decimal(data.sale_net)
    cost_net = Decimal(data.cost_net)
    vat_rate = Decimal(data.vat_rate)
    vat_amount = (sale_net * vat_rate / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    margin_net = sale_net - cost_net
    margin_percent = (margin_net * Decimal("100") / sale_net).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    row = SalesProposalVersion(
        proposal_version_id=f"PROP-{opportunity_id}-V{version}",
        opportunity_id=opportunity_id,
        version=version,
        currency=data.currency.upper(),
        vat_rate=vat_rate,
        cost_net=cost_net,
        sale_net=sale_net,
        vat_amount=vat_amount,
        sale_gross=sale_net + vat_amount,
        margin_net=margin_net,
        margin_percent=margin_percent,
        price_snapshot_id=data.price_snapshot_id,
        terms_version_id=data.terms_version_id,
        technical_scope_version_id=data.technical_scope_version_id,
        scope_summary=data.scope_summary,
        exclusions=data.exclusions,
        payment_terms=data.payment_terms,
        valid_until=data.valid_until,
        created_by=email,
    )
    db.add(row)
    opportunity.stage = "proposal"
    opportunity.probability_percent = max(opportunity.probability_percent, 40)
    opportunity.next_action = "Az ajánlatverzió belső műszaki, pénzügyi és jogi jóváhagyása."
    opportunity.updated_by = email
    opportunity.version += 1
    _sync_canonical(db, opportunity)
    audit(
        db,
        actor=email,
        action="sales_proposal_created",
        entity_type="sales_proposal",
        entity_id=row.proposal_version_id,
        after=_proposal_payload(row),
    )
    _emit(
        db,
        opportunity,
        event_type="PROPOSAL_VERSION_CREATED",
        actor=email,
        summary=f"Ügyfélspecifikus ajánlatverzió létrejött: {row.proposal_version_id}.",
        payload={"proposal_version_id": row.proposal_version_id, "version": row.version},
        route_to=["crm", "financial-control", "contract-generator"],
    )
    db.refresh(row)
    return row


def submit_proposal(db: Session, proposal_version_id: str, user: object) -> SalesProposalVersion:
    role, email = _require(user, SALES_ROLES)
    row = _proposal(db, proposal_version_id, lock=True)
    opportunity = _opportunity(db, row.opportunity_id, lock=True)
    if role == "sales" and opportunity.owner_email != email:
        raise PermissionError("Az opportunity másik értékesítőhöz van rendelve.")
    if row.status != "draft":
        raise ValueError("Csak draft ajánlat küldhető belső jóváhagyásra.")
    if _aware(row.valid_until) <= utcnow():
        raise ValueError("Lejárt ajánlat nem küldhető jóváhagyásra.")
    if row.margin_percent < MINIMUM_MARGIN_PERCENT:
        raise ValueError(
            f"A {row.margin_percent}% fedezet nem éri el a kötelező "
            f"{MINIMUM_MARGIN_PERCENT}% kaput."
        )
    row.content_sha256 = _proposal_hash(row)
    row.status = "internal_review"
    opportunity.next_action = "Műszaki ajánlatjóváhagyás elvégzése."
    opportunity.updated_by = email
    opportunity.version += 1
    audit(
        db,
        actor=email,
        action="sales_proposal_submitted",
        entity_type="sales_proposal",
        entity_id=row.proposal_version_id,
        after={"content_sha256": row.content_sha256, "margin_percent": str(row.margin_percent)},
    )
    _emit(
        db,
        opportunity,
        event_type="PROPOSAL_SUBMITTED",
        actor=email,
        summary="Az ajánlat változtathatatlan tartalmi hash-sel belső review-ba került.",
        payload={
            "proposal_version_id": row.proposal_version_id,
            "content_sha256": row.content_sha256,
        },
        route_to=["crm", "financial-control", "contract-generator"],
    )
    db.refresh(row)
    return row


def review_proposal(
    db: Session, proposal_version_id: str, data: SalesProposalReviewIn, user: object
) -> SalesProposalVersion:
    role, email = _require(user, PIPELINE_VIEW_ROLES)
    row = _proposal(db, proposal_version_id, lock=True)
    opportunity = _opportunity(db, row.opportunity_id, lock=True)
    if row.status != "internal_review":
        raise ValueError("Csak belső review-ban lévő ajánlat bírálható.")
    role_map = {
        "technical": {"technical-prep", "platform-admin"},
        "finance": {"finance", "platform-admin"},
        "legal": {"legal", "platform-admin"},
    }
    if role not in role_map[data.gate]:
        raise PermissionError("A felhasználó nem jogosult erre az ajánlati kapura.")
    prior = {
        "technical": [],
        "finance": [row.technical_approved_by],
        "legal": [row.technical_approved_by, row.finance_approved_by],
    }[data.gate]
    if any(value is None for value in prior):
        raise ValueError("Az ajánlati jóváhagyási kapuk csak sorrendben végezhetők el.")
    reviewers = [row.created_by, row.technical_approved_by, row.finance_approved_by]
    if email in {value for value in reviewers if value}:
        raise ValueError("Az ajánlat készítője és korábbi bírálója nem hagyhat jóvá újabb kaput.")
    if data.decision == "reject":
        row.status = "rejected"
        opportunity.stage = "discovery"
        opportunity.next_action = f"Új ajánlatverzió készítése a(z) {data.gate} elutasítás alapján."
    else:
        setattr(row, f"{data.gate}_approved_by", email)
        setattr(row, f"{data.gate}_approval_note", data.note)
        setattr(row, f"{data.gate}_approved_at", utcnow())
        if data.gate == "legal":
            row.status = "approved"
            opportunity.next_action = (
                "A jóváhagyott, hash-azonos ajánlat igazolt kézbesítése az ügyfélnek."
            )
        else:
            next_gate = "pénzügyi" if data.gate == "technical" else "jogi"
            opportunity.next_action = f"A következő, {next_gate} ajánlati kapu elvégzése."
    opportunity.updated_by = email
    opportunity.version += 1
    audit(
        db,
        actor=email,
        action=f"sales_proposal_{data.gate}_{data.decision}",
        entity_type="sales_proposal",
        entity_id=row.proposal_version_id,
        after=data.model_dump(),
    )
    _emit(
        db,
        opportunity,
        event_type=f"PROPOSAL_{data.gate.upper()}_{data.decision.upper()}",
        actor=email,
        summary=f"Az ajánlat {data.gate} kapujának eredménye: {data.decision}.",
        payload={"proposal_version_id": row.proposal_version_id, "note": data.note},
        route_to=["crm", "financial-control", "contract-generator"],
    )
    db.refresh(row)
    return row


def send_proposal(
    db: Session, proposal_version_id: str, data: SalesProposalSendIn, user: object
) -> SalesProposalVersion:
    role, email = _require(user, SALES_ROLES)
    row = _proposal(db, proposal_version_id, lock=True)
    opportunity = _opportunity(db, row.opportunity_id, lock=True)
    if role == "sales" and opportunity.owner_email != email:
        raise PermissionError("Az opportunity másik értékesítőhöz van rendelve.")
    if row.status != "approved":
        raise ValueError("Csak mindhárom kapun jóváhagyott ajánlat küldhető ki.")
    if _aware(row.valid_until) <= utcnow():
        row.status = "expired"
        db.commit()
        raise ValueError("A jóváhagyott ajánlat időközben lejárt.")
    if row.content_sha256 != _proposal_hash(row):
        raise ValueError("Az ajánlat tartalma a jóváhagyás óta megváltozott; kiküldése tiltott.")
    row.status = "sent"
    row.sent_by = email
    row.sent_at = utcnow()
    row.delivery_evidence_url = data.delivery_evidence_url
    opportunity.stage = "negotiation"
    opportunity.probability_percent = max(opportunity.probability_percent, 60)
    opportunity.next_action = "Ügyféldöntés és azonosítható döntési bizonyíték rögzítése."
    opportunity.updated_by = email
    opportunity.version += 1
    _sync_canonical(db, opportunity)
    audit(
        db,
        actor=email,
        action="sales_proposal_sent",
        entity_type="sales_proposal",
        entity_id=row.proposal_version_id,
        after={
            "delivery_evidence_url": data.delivery_evidence_url,
            "content_sha256": row.content_sha256,
        },
    )
    _emit(
        db,
        opportunity,
        event_type="PROPOSAL_SENT",
        actor=email,
        summary="A jóváhagyott ajánlat igazolt csatornán kézbesítve.",
        payload={
            "proposal_version_id": row.proposal_version_id,
            "delivery_evidence_url": data.delivery_evidence_url,
        },
        route_to=["crm", "contract-generator"],
    )
    db.refresh(row)
    return row


def record_proposal_decision(
    db: Session, proposal_version_id: str, data: SalesProposalDecisionIn, user: object
) -> SalesProposalVersion:
    role, email = _require(user, SALES_ROLES | {"legal"})
    row = _proposal(db, proposal_version_id, lock=True)
    opportunity = _opportunity(db, row.opportunity_id, lock=True)
    if role == "sales" and opportunity.owner_email != email:
        raise PermissionError("Az opportunity másik értékesítőhöz van rendelve.")
    if row.status != "sent":
        raise ValueError("Csak kiküldött ajánlathoz rögzíthető ügyféldöntés.")
    row.customer_decision_reference = data.customer_decision_reference
    row.customer_decision_note = data.note
    row.customer_decided_at = utcnow()
    if data.decision == "accept":
        row.status = "accepted"
        opportunity.stage = "contracting"
        opportunity.probability_percent = 90
        opportunity.accepted_proposal_version_id = row.proposal_version_id
        opportunity.next_action = "Aláírt szerződés és delivery ProjectID összekapcsolása."
    else:
        row.status = "customer_rejected"
        opportunity.stage = "discovery"
        opportunity.probability_percent = 25
        opportunity.next_action = "Ügyfélellenvetések feldolgozása vagy új ajánlatverzió készítése."
    opportunity.updated_by = email
    opportunity.version += 1
    _sync_canonical(db, opportunity)
    audit(
        db,
        actor=email,
        action=f"sales_proposal_customer_{data.decision}",
        entity_type="sales_proposal",
        entity_id=row.proposal_version_id,
        after=data.model_dump(),
    )
    _emit(
        db,
        opportunity,
        event_type=f"PROPOSAL_CUSTOMER_{data.decision.upper()}",
        actor=email,
        summary=f"Az ügyfél ajánlati döntése: {data.decision}.",
        payload={
            "proposal_version_id": row.proposal_version_id,
            "decision_reference": data.customer_decision_reference,
        },
        route_to=["crm", "contract-generator", "finance-intelligence"],
    )
    db.refresh(row)
    return row


def close_opportunity(
    db: Session, opportunity_id: str, data: SalesOpportunityCloseIn, user: object
) -> SalesOpportunity:
    role, email = _require(user, SALES_ROLES)
    row = _opportunity(db, opportunity_id, lock=True)
    if role == "sales" and row.owner_email != email:
        raise PermissionError("Az opportunity másik értékesítőhöz van rendelve.")
    if row.stage in {"won", "lost"}:
        raise ValueError("Az opportunity már lezárt.")
    if data.outcome == "won":
        if row.stage != "contracting" or not row.accepted_proposal_version_id:
            raise ValueError(
                "Nyerés csak elfogadott ajánlat és contracting szakasz után rögzíthető."
            )
        if not data.contract_id or not data.delivery_project_id:
            raise ValueError("Nyeréshez aláírt ContractID és delivery ProjectID kötelező.")
        project = db.scalar(
            select(ProjectRegistry).where(ProjectRegistry.project_id == data.delivery_project_id)
        )
        contract = db.scalar(
            select(ProjectObjectState).where(
                ProjectObjectState.project_id == data.delivery_project_id,
                ProjectObjectState.source_module == "contract_generator",
                ProjectObjectState.object_type == "Contract",
                ProjectObjectState.object_id == data.contract_id,
                ProjectObjectState.status == "signed",
            )
        )
        if not project or not contract:
            raise ValueError("A delivery ProjectID-hoz nem található igazolt, aláírt ContractID.")
        row.stage = "won"
        row.probability_percent = 100
        row.contract_id = data.contract_id
        row.delivery_project_id = data.delivery_project_id
        row.next_action = "Projektmenedzseri átadás és MyImperial projektaktiválás."
    else:
        row.stage = "lost"
        row.probability_percent = 0
        row.loss_reason = data.reason
        row.competitor = data.competitor
        row.next_action = "Veszteségi ok elemzése és tanulság rögzítése."
    row.updated_by = email
    row.version += 1
    _sync_canonical(db, row)
    audit(
        db,
        actor=email,
        action=f"sales_opportunity_{data.outcome}",
        entity_type="sales_opportunity",
        entity_id=row.opportunity_id,
        after=data.model_dump(),
    )
    _emit(
        db,
        row,
        event_type=f"OPPORTUNITY_{data.outcome.upper()}",
        actor=email,
        summary=f"Az opportunity lezárult: {data.outcome}. {data.reason}",
        payload={
            "contract_id": row.contract_id,
            "delivery_project_id": row.delivery_project_id,
            "competitor": row.competitor,
        },
        route_to=[
            "crm",
            "financial-control",
            "finance-intelligence",
            "contract-generator",
            "project-control",
            "my-imperial",
        ],
    )
    db.refresh(row)
    return row


def sales_pipeline_workspace(db: Session) -> dict[str, Any]:
    opportunities = db.scalars(
        select(SalesOpportunity).order_by(desc(SalesOpportunity.updated_at)).limit(200)
    ).all()
    proposals = db.scalars(
        select(SalesProposalVersion).order_by(desc(SalesProposalVersion.created_at)).limit(300)
    ).all()
    proposal_by_opportunity: dict[str, list[SalesProposalVersion]] = {}
    for proposal in proposals:
        proposal_by_opportunity.setdefault(proposal.opportunity_id, []).append(proposal)
    weighted_pipeline = sum(
        Decimal(row.estimated_value_huf) * Decimal(row.probability_percent) / Decimal("100")
        for row in opportunities
        if row.stage in OPEN_STAGES
    )
    return {
        "opportunities": opportunities,
        "proposals": proposals,
        "proposal_by_opportunity": proposal_by_opportunity,
        "metrics": {
            "open_opportunities": sum(1 for row in opportunities if row.stage in OPEN_STAGES),
            "weighted_pipeline_huf": weighted_pipeline,
            "proposals_in_review": sum(1 for row in proposals if row.status == "internal_review"),
            "proposals_waiting_customer": sum(1 for row in proposals if row.status == "sent"),
            "won_count": sum(1 for row in opportunities if row.stage == "won"),
            "lost_count": sum(1 for row in opportunities if row.stage == "lost"),
        },
    }


def serialize_opportunity(row: SalesOpportunity) -> dict[str, Any]:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name != "id"
    }


def serialize_proposal(row: SalesProposalVersion) -> dict[str, Any]:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name != "id"
    }
