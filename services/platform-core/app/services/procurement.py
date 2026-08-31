from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    DeliveryNoteProjection,
    EventRecord,
    OutboxMessage,
    ProcurementDeviation,
    ProcurementInvoiceMatch,
    ProcurementOffer,
    ProcurementOrderProjection,
    ProcurementRequirement,
    ProcurementSelection,
    ProcurementSubstitutionReview,
    ProjectRegistry,
)
from ..schemas import (
    ProcurementInvoiceMatchIn,
    ProcurementOfferIn,
    ProcurementOrderIn,
    ProcurementRequirementIn,
    ProcurementSelectionIn,
    ProcurementSubstitutionIn,
)


DUAL_APPROVAL_LIMIT_HUF = Decimal("20000000")
MINIMUM_SAVINGS_PCT = Decimal("8")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or 0))


def _event(
    db: Session,
    *,
    project_id: str,
    event_type: str,
    object_type: str,
    object_id: str,
    title: str,
    severity: str = "info",
    financial_impact_huf: Decimal = Decimal("0"),
    executive: bool = False,
) -> None:
    db.add(EventRecord(
        event_id=_id("EVT"), dedupe_key=f"PROC:{event_type}:{object_id}",
        project_id=project_id, source_module="procurement", event_type=event_type,
        object_type=object_type, object_id=object_id, severity=severity, status="open",
        financial_impact_huf=financial_impact_huf, deadline_impact_days=0,
        responsible="Beszerzés", next_action=title, executive_relevance=executive,
        payload_json=json.dumps({"summary": title}, ensure_ascii=False),
    ))


def _outbox(db: Session, destination: str, endpoint: str, payload: dict) -> None:
    db.add(OutboxMessage(
        message_id=_id("MSG"), destination_module=destination, endpoint=endpoint,
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
        status="pending", max_retries=5,
    ))


def create_requirement(db: Session, data: ProcurementRequirementIn, actor: str) -> ProcurementRequirement:
    if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == data.project_id)):
        raise KeyError(data.project_id)
    maximum = data.net_quantity * (Decimal("1") + data.waste_pct / Decimal("100"))
    row = ProcurementRequirement(
        requirement_id=_id("PREQ"), project_id=data.project_id,
        work_package_id=data.work_package_id, category=data.category.strip(),
        scope_description=data.scope_description.strip(), specification=data.specification.strip(),
        net_quantity=data.net_quantity, waste_pct=data.waste_pct,
        max_orderable_quantity=maximum, unit=data.unit.strip(), required_at=data.required_at,
        budget_huf=data.budget_huf, target_huf=data.target_huf,
        status="approval_pending", created_by=actor,
    )
    db.add(row)
    audit(db, actor=actor, action="procurement.requirement.create", entity_type="procurement_requirement", entity_id=row.requirement_id, after={"project_id": row.project_id, "budget_huf": str(row.budget_huf), "max_orderable_quantity": str(row.max_orderable_quantity)})
    db.commit(); db.refresh(row)
    return row


def approve_requirement(db: Session, requirement_id: str, stage: str, actor: str, actor_role: str) -> ProcurementRequirement:
    row = db.scalar(select(ProcurementRequirement).where(ProcurementRequirement.requirement_id == requirement_id))
    if not row:
        raise KeyError(requirement_id)
    now = utcnow()
    if stage == "technical":
        if actor_role not in {"technical-prep", "project-manager", "managing-director", "owner", "platform-admin"}:
            raise PermissionError("Műszaki jóváhagyásra nincs jogosultság.")
        row.technical_approved_by, row.technical_approved_at = actor, now
    elif stage == "budget_cash":
        if actor_role not in {"finance", "managing-director", "owner", "platform-admin"}:
            raise PermissionError("Költségkeret- és cash-jóváhagyásra nincs jogosultság.")
        row.budget_approved_by = row.cash_approved_by = actor
        row.budget_approved_at = row.cash_approved_at = now
    else:
        raise ValueError("Ismeretlen jóváhagyási lépés.")
    if row.technical_approved_at and row.budget_approved_at and row.cash_approved_at:
        row.status = "ready_for_tender"
        _event(db, project_id=row.project_id, event_type="PROCUREMENT_REQUIREMENT_APPROVED", object_type="ProcurementRequirement", object_id=row.requirement_id, title="Jóváhagyott beszerzési igény versenyeztethető")
    audit(db, actor=actor, action=f"procurement.requirement.approve.{stage}", entity_type="procurement_requirement", entity_id=row.requirement_id, after={"status": row.status})
    db.commit(); db.refresh(row)
    return row


def revise_requirement(
    db: Session, requirement_id: str, *, net_quantity: Decimal, waste_pct: Decimal,
    budget_huf: Decimal, target_huf: Decimal, reason: str, actor: str,
) -> ProcurementRequirement:
    row = db.scalar(select(ProcurementRequirement).where(ProcurementRequirement.requirement_id == requirement_id))
    if not row:
        raise KeyError(requirement_id)
    confirmed = db.scalar(select(ProcurementOrderProjection).where(ProcurementOrderProjection.requirement_id == requirement_id, ProcurementOrderProjection.confirmation_status == "confirmed"))
    if confirmed:
        raise ValueError("Visszaigazolt rendelés igénye csak Change Control folyamatban módosítható.")
    row.net_quantity, row.waste_pct = net_quantity, waste_pct
    row.max_orderable_quantity = net_quantity * (Decimal("1") + waste_pct / Decimal("100"))
    row.budget_huf, row.target_huf = budget_huf, target_huf
    row.revision_no += 1; row.revision_reason = reason.strip(); row.status = "approval_pending"
    row.technical_approved_by = row.technical_approved_at = None
    row.budget_approved_by = row.budget_approved_at = None
    row.cash_approved_by = row.cash_approved_at = None
    audit(db, actor=actor, action="procurement.requirement.revise", entity_type="procurement_requirement", entity_id=row.requirement_id, after={"revision_no": row.revision_no, "reason": reason})
    db.commit(); db.refresh(row)
    return row


def add_offer(db: Session, data: ProcurementOfferIn, actor: str) -> ProcurementOffer:
    requirement = db.scalar(select(ProcurementRequirement).where(ProcurementRequirement.requirement_id == data.requirement_id))
    if not requirement:
        raise KeyError(data.requirement_id)
    if requirement.status not in {"ready_for_tender", "offers_received", "comparison"}:
        raise ValueError("Csak jóváhagyott igényre rögzíthető ajánlat.")
    total = data.net_total_huf + data.delivery_cost_huf + data.other_landed_cost_huf
    row = ProcurementOffer(
        offer_id=_id("POFF"), requirement_id=data.requirement_id,
        supplier_name=data.supplier_name.strip(), partner_id=data.partner_id,
        net_total_huf=data.net_total_huf, delivery_cost_huf=data.delivery_cost_huf,
        other_landed_cost_huf=data.other_landed_cost_huf, total_landed_cost_huf=total,
        lead_time_days=data.lead_time_days, warranty_months=data.warranty_months,
        payment_terms=data.payment_terms.strip(), risk_score=data.risk_score,
        technical_compliant=data.technical_compliant, valid_until=data.valid_until,
        document_ref=data.document_ref.strip(), notes=data.notes, created_by=actor,
    )
    db.add(row); requirement.status = "offers_received"
    audit(db, actor=actor, action="procurement.offer.create", entity_type="procurement_offer", entity_id=row.offer_id, after={"requirement_id": row.requirement_id, "total_landed_cost_huf": str(total), "technical_compliant": row.technical_compliant})
    db.commit(); db.refresh(row)
    return row


def select_offer(db: Session, data: ProcurementSelectionIn, actor: str) -> ProcurementSelection:
    requirement = db.scalar(select(ProcurementRequirement).where(ProcurementRequirement.requirement_id == data.requirement_id))
    offer = db.scalar(select(ProcurementOffer).where(ProcurementOffer.offer_id == data.offer_id, ProcurementOffer.requirement_id == data.requirement_id))
    if not requirement or not offer:
        raise KeyError(data.requirement_id if not requirement else data.offer_id)
    if not offer.technical_compliant:
        raise ValueError("Műszakilag nem megfelelő ajánlat nem választható.")
    offer_count = db.scalar(
        select(func.count())
        .select_from(ProcurementOffer)
        .where(ProcurementOffer.requirement_id == data.requirement_id)
    ) or 0
    if offer_count < 2 and not data.market_evidence_ref:
        raise ValueError("Legalább két összehasonlítható ajánlat vagy dokumentált piaci bizonyíték szükséges.")
    savings = ((requirement.target_huf - offer.total_landed_cost_huf) / requirement.target_huf * Decimal("100")).quantize(Decimal("0.0001"))
    if savings < MINIMUM_SAVINGS_PCT and not data.market_evidence_ref:
        raise ValueError("8% alatti megtakarításhoz dokumentált piaci bizonyíték szükséges.")
    row = ProcurementSelection(
        selection_id=_id("PSEL"), requirement_id=requirement.requirement_id,
        offer_id=offer.offer_id, total_landed_cost_huf=offer.total_landed_cost_huf,
        savings_pct=savings, market_evidence_ref=data.market_evidence_ref,
        rationale=data.rationale.strip(), risk_rationale=data.risk_rationale.strip(),
        dual_approval_required=offer.total_landed_cost_huf > DUAL_APPROVAL_LIMIT_HUF,
        prepared_by=actor,
    )
    db.add(row); requirement.status = "approval_pending"; offer.status = "selected"
    audit(db, actor=actor, action="procurement.selection.create", entity_type="procurement_selection", entity_id=row.selection_id, after={"total_landed_cost_huf": str(row.total_landed_cost_huf), "savings_pct": str(savings), "dual_approval_required": row.dual_approval_required})
    db.commit(); db.refresh(row)
    return row


def approve_selection(db: Session, selection_id: str, stage: str, actor: str, actor_role: str, approve: bool = True, note: str | None = None) -> ProcurementSelection:
    row = db.scalar(select(ProcurementSelection).where(ProcurementSelection.selection_id == selection_id))
    if not row:
        raise KeyError(selection_id)
    requirement = db.scalar(select(ProcurementRequirement).where(ProcurementRequirement.requirement_id == row.requirement_id))
    if requirement is None:
        raise KeyError(row.requirement_id)
    if not approve:
        if actor_role not in {"finance", "managing-director", "owner", "platform-admin"}:
            raise PermissionError("Elutasításra nincs jogosultság.")
        row.status = "rejected"; row.rejection_reason = note or "Elutasítva"
        requirement.status = "comparison"
    else:
        now = utcnow()
        if stage == "finance":
            if actor_role not in {"finance", "owner", "platform-admin"}:
                raise PermissionError("Pénzügyi jóváhagyásra nincs jogosultság.")
            row.finance_approved_by, row.finance_approved_at = actor, now
        elif stage == "managing_director":
            if actor_role not in {"managing-director", "owner", "platform-admin"}:
                raise PermissionError("Ügyvezetői jóváhagyásra nincs jogosultság.")
            row.md_approved_by, row.md_approved_at = actor, now
        elif stage == "owner":
            if actor_role not in {"owner", "platform-admin"}:
                raise PermissionError("Tulajdonosi jóváhagyásra nincs jogosultság.")
            if not row.dual_approval_required:
                raise ValueError("Ehhez az értékhez nem szükséges tulajdonosi kettős jóváhagyás.")
            if not row.md_approved_at:
                raise ValueError("A tulajdonosi jóváhagyás előtt ügyvezetői jóváhagyás szükséges.")
            if row.md_approved_by == actor:
                raise ValueError("A kettős jóváhagyást két külön személynek kell megadnia.")
            row.owner_approved_by, row.owner_approved_at = actor, now
        else:
            raise ValueError("Ismeretlen jóváhagyási lépés.")
        complete = bool(row.finance_approved_at and row.md_approved_at and (not row.dual_approval_required or row.owner_approved_at))
        if complete:
            row.status = "approved"; row.approved_at = now; requirement.status = "selected"
            _event(db, project_id=requirement.project_id, event_type="PROCUREMENT_SELECTION_APPROVED", object_type="ProcurementSelection", object_id=row.selection_id, title="Beszerzési döntés jóváhagyva", financial_impact_huf=row.total_landed_cost_huf, executive=row.dual_approval_required)
    audit(db, actor=actor, action=f"procurement.selection.{stage}.{'approve' if approve else 'reject'}", entity_type="procurement_selection", entity_id=row.selection_id, after={"status": row.status})
    db.commit(); db.refresh(row)
    return row


def create_order(db: Session, data: ProcurementOrderIn, actor: str) -> ProcurementOrderProjection:
    selection = db.scalar(select(ProcurementSelection).where(ProcurementSelection.selection_id == data.selection_id))
    if not selection:
        raise KeyError(data.selection_id)
    if selection.status != "approved":
        raise ValueError("Rendelés csak teljesen jóváhagyott kiválasztásból hozható létre.")
    requirement = db.scalar(select(ProcurementRequirement).where(ProcurementRequirement.requirement_id == selection.requirement_id))
    offer = db.scalar(select(ProcurementOffer).where(ProcurementOffer.offer_id == selection.offer_id))
    if requirement is None:
        raise KeyError(selection.requirement_id)
    if offer is None:
        raise KeyError(selection.offer_id)
    if data.ordered_quantity > requirement.max_orderable_quantity:
        raise ValueError("A rendelt mennyiség meghaladja a jóváhagyott nettó mennyiség + káló maximumot; igényrevízió szükséges.")
    content = f"{selection.selection_id}|{requirement.requirement_id}|{offer.offer_id}|{data.ordered_quantity}|{selection.total_landed_cost_huf}|{data.delivery_due.isoformat()}"
    row = ProcurementOrderProjection(
        order_id=_id("PO"), project_id=requirement.project_id,
        work_package_id=requirement.work_package_id, supplier_name=offer.supplier_name,
        item_summary=requirement.scope_description, status="ordered",
        total_huf=selection.total_landed_cost_huf, delivery_due=data.delivery_due,
        delivery_status="not_started", document_status="pending", variance_status="none",
        source_module="procurement", source_object_id=selection.selection_id,
        source_url=offer.document_ref, source_version=str(requirement.revision_no),
        requirement_id=requirement.requirement_id, selection_id=selection.selection_id,
        ordered_quantity=data.ordered_quantity, unit=requirement.unit,
        approval_status="approved", confirmation_status="pending",
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(), created_by=actor,
    )
    db.add(row); requirement.status = "ordered"
    _outbox(db, "finance", "/procurement/commitments", {
        "order_id": row.order_id, "project_id": row.project_id,
        "supplier_name": row.supplier_name, "committed_huf": str(row.total_huf),
        "approval_status": row.approval_status, "selection_id": row.selection_id,
    })
    _outbox(db, "smart-calendar", "/procurement/deliveries", {
        "order_id": row.order_id, "project_id": row.project_id,
        "delivery_due": data.delivery_due.isoformat(), "supplier_name": row.supplier_name,
    })
    _event(db, project_id=requirement.project_id, event_type="PROCUREMENT_ORDERED", object_type="ProcurementOrder", object_id=row.order_id, title="Jóváhagyott megrendelés létrejött", financial_impact_huf=row.total_huf)
    audit(db, actor=actor, action="procurement.order.create", entity_type="procurement_order", entity_id=row.order_id, after={"selection_id": selection.selection_id, "sha256": row.content_sha256, "ordered_quantity": str(row.ordered_quantity)})
    db.commit(); db.refresh(row)
    return row


def confirm_order(db: Session, order_id: str, actor: str) -> ProcurementOrderProjection:
    row = db.scalar(select(ProcurementOrderProjection).where(ProcurementOrderProjection.order_id == order_id))
    if not row:
        raise KeyError(order_id)
    if row.approval_status != "approved":
        raise ValueError("Jóváhagyás nélküli rendelés nem igazolható vissza.")
    row.confirmation_status = "confirmed"; row.confirmed_by = actor; row.confirmed_at = utcnow(); row.status = "confirmed"
    audit(db, actor=actor, action="procurement.order.confirm", entity_type="procurement_order", entity_id=row.order_id, after={"confirmation_status": row.confirmation_status})
    db.commit(); db.refresh(row)
    return row


def create_substitution_review(db: Session, data: ProcurementSubstitutionIn, actor: str) -> ProcurementSubstitutionReview:
    if not db.scalar(select(ProcurementRequirement).where(ProcurementRequirement.requirement_id == data.requirement_id)):
        raise KeyError(data.requirement_id)
    row = ProcurementSubstitutionReview(
        review_id=_id("PSUB"), requirement_id=data.requirement_id,
        proposed_product=data.proposed_product, proposed_specification=data.proposed_specification,
        technical_equivalence=data.technical_equivalence, declaration_ref=data.declaration_ref,
        price_impact_huf=data.price_impact_huf, schedule_impact_days=data.schedule_impact_days,
        risk_assessment=data.risk_assessment, rationale=data.rationale, requested_by=actor,
    )
    db.add(row); audit(db, actor=actor, action="procurement.substitution.create", entity_type="procurement_substitution", entity_id=row.review_id, after={"requirement_id": row.requirement_id})
    db.commit(); db.refresh(row); return row


def review_substitution(db: Session, review_id: str, decision: str, actor: str, actor_role: str) -> ProcurementSubstitutionReview:
    if actor_role not in {"technical-prep", "managing-director", "owner", "platform-admin"}:
        raise PermissionError("Termékhelyettesítés műszaki felülvizsgálatára nincs jogosultság.")
    row = db.scalar(select(ProcurementSubstitutionReview).where(ProcurementSubstitutionReview.review_id == review_id))
    if not row: raise KeyError(review_id)
    if decision not in {"approved", "rejected"}: raise ValueError("Érvénytelen döntés.")
    row.status = decision; row.reviewed_by = actor; row.reviewed_at = utcnow()
    audit(db, actor=actor, action=f"procurement.substitution.{decision}", entity_type="procurement_substitution", entity_id=row.review_id, after={"status": row.status})
    db.commit(); db.refresh(row); return row


def register_deviation(
    db: Session, *, order_id: str, delivery_note_id: str | None, deviation_type: str,
    description: str, owner: str, due_at: datetime, corrective_action: str,
    financial_impact_huf: Decimal, actor: str, commit: bool = True,
) -> ProcurementDeviation:
    order = db.scalar(select(ProcurementOrderProjection).where(ProcurementOrderProjection.order_id == order_id))
    if not order: raise KeyError(order_id)
    row = ProcurementDeviation(
        deviation_id=_id("PDEV"), project_id=order.project_id, order_id=order_id,
        delivery_note_id=delivery_note_id, deviation_type=deviation_type,
        description=description, owner=owner, due_at=due_at,
        corrective_action=corrective_action, financial_impact_huf=financial_impact_huf,
        created_by=actor,
    )
    db.add(row)
    _event(db, project_id=order.project_id, event_type="PROCUREMENT_DEVIATION_OPENED", object_type="ProcurementDeviation", object_id=row.deviation_id, title=description, severity="high", financial_impact_huf=financial_impact_huf)
    audit(db, actor=actor, action="procurement.deviation.create", entity_type="procurement_deviation", entity_id=row.deviation_id, after={"order_id": order_id, "type": deviation_type, "owner": owner})
    if commit: db.commit(); db.refresh(row)
    return row


def resolve_deviation(db: Session, deviation_id: str, resolution: str, actor: str) -> ProcurementDeviation:
    row = db.scalar(select(ProcurementDeviation).where(ProcurementDeviation.deviation_id == deviation_id))
    if not row: raise KeyError(deviation_id)
    row.status = "resolved"; row.resolution = resolution; row.resolved_by = actor; row.resolved_at = utcnow()
    audit(db, actor=actor, action="procurement.deviation.resolve", entity_type="procurement_deviation", entity_id=row.deviation_id, after={"resolution": resolution})
    db.commit(); db.refresh(row); return row


def create_invoice_match(db: Session, data: ProcurementInvoiceMatchIn, actor: str) -> ProcurementInvoiceMatch:
    order = db.scalar(select(ProcurementOrderProjection).where(ProcurementOrderProjection.order_id == data.order_id))
    delivery = db.scalar(select(DeliveryNoteProjection).where(DeliveryNoteProjection.delivery_note_id == data.delivery_note_id, DeliveryNoteProjection.order_id == data.order_id))
    if not order or not delivery: raise KeyError(data.order_id if not order else data.delivery_note_id)
    blockers: list[str] = []
    if not delivery.supplier_signed or not delivery.receiver_signed: blockers.append("signed_delivery_note_missing")
    if not delivery.signature_evidence_ref: blockers.append("signature_evidence_missing")
    if delivery.document_status != "complete": blockers.append("delivery_document_incomplete")
    if delivery.performance_declaration_status != "complete": blockers.append("performance_declaration_incomplete")
    if delivery.elog_evidence_status != "complete": blockers.append("elog_evidence_incomplete")
    if delivery.quality_status != "accepted": blockers.append("quality_not_accepted")
    if delivery.plan_match != "matched": blockers.append("specification_variance")
    if delivery.received_quantity != delivery.ordered_quantity: blockers.append("quantity_variance")
    if data.invoice_total_huf > order.total_huf: blockers.append("invoice_exceeds_order")
    if db.scalar(select(ProcurementDeviation).where(ProcurementDeviation.order_id == order.order_id, ProcurementDeviation.status == "open")):
        blockers.append("open_deviation")
    accepted_value = min(_decimal(data.invoice_total_huf), _decimal(order.total_huf))
    row = ProcurementInvoiceMatch(
        match_id=_id("PMATCH"), order_id=order.order_id,
        delivery_note_id=delivery.delivery_note_id, invoice_reference=data.invoice_reference,
        invoice_total_huf=data.invoice_total_huf, ordered_total_huf=order.total_huf,
        accepted_value_huf=accepted_value, blockers_json=json.dumps(blockers),
        status="payment_ready" if not blockers else "blocked", payment_ready=not blockers,
        matched_by=actor,
    )
    db.add(row)
    _outbox(db, "finance", "/procurement/invoice-matches", {
        "match_id": row.match_id, "order_id": row.order_id,
        "invoice_reference": row.invoice_reference, "invoice_total_huf": str(row.invoice_total_huf),
        "payment_ready": row.payment_ready, "blockers": blockers,
    })
    _event(db, project_id=order.project_id, event_type="PROCUREMENT_INVOICE_MATCHED" if not blockers else "PROCUREMENT_INVOICE_BLOCKED", object_type="ProcurementInvoiceMatch", object_id=row.match_id, title="Számla fizetésre kész" if not blockers else "Számla blokkolva: " + ", ".join(blockers), severity="info" if not blockers else "high", financial_impact_huf=data.invoice_total_huf)
    audit(db, actor=actor, action="procurement.invoice_match.create", entity_type="procurement_invoice_match", entity_id=row.match_id, after={"payment_ready": row.payment_ready, "blockers": blockers})
    db.commit(); db.refresh(row); return row


def procurement_workspace(db: Session, project_id: str | None = None) -> dict:
    requirement_query = select(ProcurementRequirement)
    if project_id: requirement_query = requirement_query.where(ProcurementRequirement.project_id == project_id)
    requirements = db.scalars(requirement_query.order_by(desc(ProcurementRequirement.updated_at))).all()
    ids = [row.requirement_id for row in requirements]
    offers = db.scalars(select(ProcurementOffer).where(ProcurementOffer.requirement_id.in_(ids)).order_by(ProcurementOffer.total_landed_cost_huf)).all() if ids else []
    selections = db.scalars(select(ProcurementSelection).where(ProcurementSelection.requirement_id.in_(ids)).order_by(desc(ProcurementSelection.created_at))).all() if ids else []
    order_query = select(ProcurementOrderProjection)
    if project_id: order_query = order_query.where(ProcurementOrderProjection.project_id == project_id)
    orders = db.scalars(order_query.order_by(desc(ProcurementOrderProjection.updated_at))).all()
    order_ids = [row.order_id for row in orders]
    deviations = db.scalars(select(ProcurementDeviation).where(ProcurementDeviation.order_id.in_(order_ids)).order_by(desc(ProcurementDeviation.created_at))).all() if order_ids else []
    matches = db.scalars(select(ProcurementInvoiceMatch).where(ProcurementInvoiceMatch.order_id.in_(order_ids)).order_by(desc(ProcurementInvoiceMatch.matched_at))).all() if order_ids else []
    substitutions = db.scalars(select(ProcurementSubstitutionReview).where(ProcurementSubstitutionReview.requirement_id.in_(ids)).order_by(desc(ProcurementSubstitutionReview.created_at))).all() if ids else []
    return {
        "requirements": requirements, "offers": offers, "selections": selections,
        "native_orders": orders, "deviations": deviations, "invoice_matches": matches,
        "substitutions": substitutions,
        "procurement_metrics": {
            "requirements": len(requirements),
            "approval_queue": sum(1 for r in requirements if r.status == "approval_pending") + sum(1 for s in selections if s.status == "approval_pending"),
            "committed_huf": sum((_decimal(o.total_huf) for o in orders), Decimal("0")),
            "open_deviations": sum(1 for d in deviations if d.status == "open"),
            "payment_ready": sum(1 for m in matches if m.payment_ready),
            "savings_huf": sum((max(Decimal("0"), _decimal(r.target_huf) - _decimal(s.total_landed_cost_huf)) for r in requirements for s in selections if s.requirement_id == r.requirement_id), Decimal("0")),
        },
    }
