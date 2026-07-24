from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    DeliveryNoteProjection,
    EventRecord,
    MaterialLot,
    MaterialMovement,
    MaterialUsageControl,
    OutboxMessage,
    PMGateCheck,
    PMPhase,
    PMWorkPackage,
    ProcurementOrderProjection,
    ProjectRegistry,
    SiteDailyReport,
    SiteIssue,
    TaskRecord,
)
from ..schemas import (
    DailyReportIn,
    DeliveryNoteIn,
    GateCheckIn,
    MaterialMovementIn,
    MaterialUsageIn,
    OperationsCommandIn,
    SiteIssueIn,
    WorkPackageUpdateIn,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def _is_past(value: datetime | None) -> bool:
    if not value:
        return False
    now = utcnow()
    if value.tzinfo is None:
        now = now.replace(tzinfo=None)
    return value < now


def operations_summary(db: Session) -> dict:
    active_projects = db.scalar(select(func.count(ProjectRegistry.id)).where(ProjectRegistry.status.in_(["active", "planning"]))) or 0
    blocked_projects = db.scalar(select(func.count(ProjectRegistry.id)).where(ProjectRegistry.blocked.is_(True))) or 0
    blocked_packages = db.scalar(select(func.count(PMWorkPackage.id)).where(PMWorkPackage.blocked.is_(True), PMWorkPackage.status != "done")) or 0
    open_issues = db.scalar(select(func.count(SiteIssue.id)).where(SiteIssue.status == "open")) or 0
    overdue_packages = db.scalar(select(func.count(PMWorkPackage.id)).where(PMWorkPackage.planned_end < utcnow(), PMWorkPackage.status.notin_(["done", "cancelled"]))) or 0
    pending_gates = db.scalar(select(func.count(PMGateCheck.id)).where(PMGateCheck.required.is_(True), PMGateCheck.status != "passed")) or 0
    pending_delivery_docs = db.scalar(select(func.count(DeliveryNoteProjection.id)).where(
        (DeliveryNoteProjection.document_status != "complete") |
        (DeliveryNoteProjection.performance_declaration_status != "complete") |
        (DeliveryNoteProjection.elog_evidence_status != "complete")
    )) or 0
    inventory_value = Decimal("0")
    lots = db.scalars(select(MaterialLot)).all()
    controls = db.scalars(select(MaterialUsageControl)).all()
    unit_cost_by_lot = {c.lot_id: _decimal(c.unit_cost_huf) for c in controls if c.lot_id}
    for lot in lots:
        inventory_value += _decimal(lot.current_quantity) * unit_cost_by_lot.get(lot.lot_id, Decimal("0"))
    return {
        "active_projects": active_projects,
        "blocked_projects": blocked_projects,
        "blocked_packages": blocked_packages,
        "open_issues": open_issues,
        "overdue_packages": overdue_packages,
        "pending_gates": pending_gates,
        "pending_delivery_docs": pending_delivery_docs,
        "inventory_value_huf": inventory_value,
    }


def operations_portfolio(db: Session) -> list[dict]:
    projects = db.scalars(select(ProjectRegistry).order_by(desc(ProjectRegistry.updated_at))).all()
    result: list[dict] = []
    for project in projects:
        packages = db.scalars(select(PMWorkPackage).where(PMWorkPackage.project_id == project.project_id)).all()
        phases = db.scalars(select(PMPhase).where(PMPhase.project_id == project.project_id).order_by(PMPhase.sequence)).all()
        issues = db.scalars(select(SiteIssue).where(SiteIssue.project_id == project.project_id, SiteIssue.status == "open")).all()
        total_budget = sum((_decimal(p.budget_huf) for p in packages), Decimal("0"))
        total_actual = sum((_decimal(p.actual_huf) for p in packages), Decimal("0"))
        weighted_progress = 0
        if packages:
            weights = [max(_decimal(p.budget_huf), Decimal("1")) for p in packages]
            weighted_progress = int(sum(Decimal(p.progress_pct) * w for p, w in zip(packages, weights)) / sum(weights))
        elif phases:
            weighted_progress = int(sum(p.progress_pct for p in phases) / len(phases))
        result.append({
            "project": project,
            "phases": phases,
            "packages": packages,
            "open_issues": issues,
            "progress_pct": weighted_progress,
            "budget_huf": total_budget,
            "actual_huf": total_actual,
            "variance_huf": total_actual - total_budget,
            "blocked_packages": sum(1 for p in packages if p.blocked and p.status != "done"),
        })
    return result


def project_operations(db: Session, project_id: str) -> dict:
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if not project:
        raise KeyError(project_id)
    phases = db.scalars(select(PMPhase).where(PMPhase.project_id == project_id).order_by(PMPhase.sequence)).all()
    packages = db.scalars(select(PMWorkPackage).where(PMWorkPackage.project_id == project_id).order_by(PMWorkPackage.planned_start, PMWorkPackage.name)).all()
    gates = db.scalars(select(PMGateCheck).where(PMGateCheck.project_id == project_id).order_by(PMGateCheck.work_package_id, PMGateCheck.gate_code)).all()
    reports = db.scalars(select(SiteDailyReport).where(SiteDailyReport.project_id == project_id).order_by(desc(SiteDailyReport.report_date)).limit(30)).all()
    issues = db.scalars(select(SiteIssue).where(SiteIssue.project_id == project_id).order_by(SiteIssue.status, desc(SiteIssue.created_at))).all()
    orders = db.scalars(select(ProcurementOrderProjection).where(ProcurementOrderProjection.project_id == project_id).order_by(desc(ProcurementOrderProjection.updated_at))).all()
    deliveries = db.scalars(select(DeliveryNoteProjection).where(DeliveryNoteProjection.project_id == project_id).order_by(desc(DeliveryNoteProjection.received_at))).all()
    lots = db.scalars(select(MaterialLot).where(MaterialLot.project_id == project_id).order_by(MaterialLot.material)).all()
    movements = db.scalars(select(MaterialMovement).where(MaterialMovement.project_id == project_id).order_by(desc(MaterialMovement.occurred_at)).limit(50)).all()
    controls = db.scalars(select(MaterialUsageControl).where(MaterialUsageControl.project_id == project_id).order_by(desc(MaterialUsageControl.updated_at))).all()
    gate_map: dict[str, list[PMGateCheck]] = {}
    for gate in gates:
        gate_map.setdefault(gate.work_package_id or "project", []).append(gate)
    budget = sum((_decimal(p.budget_huf) for p in packages), Decimal("0"))
    committed = sum((_decimal(p.committed_huf) for p in packages), Decimal("0"))
    actual = sum((_decimal(p.actual_huf) for p in packages), Decimal("0"))
    progress = int(sum(p.progress_pct for p in packages) / len(packages)) if packages else 0
    return {
        "project": project,
        "phases": phases,
        "packages": packages,
        "gates": gates,
        "gate_map": gate_map,
        "reports": reports,
        "issues": issues,
        "orders": orders,
        "deliveries": deliveries,
        "lots": lots,
        "movements": movements,
        "controls": controls,
        "metrics": {
            "progress_pct": progress,
            "budget_huf": budget,
            "committed_huf": committed,
            "actual_huf": actual,
            "forecast_variance_huf": actual - budget,
            "blocked_packages": sum(1 for p in packages if p.blocked and p.status != "done"),
            "open_issues": sum(1 for i in issues if i.status == "open"),
            "pending_gates": sum(1 for g in gates if g.required and g.status != "passed"),
            "pending_delivery_docs": sum(1 for d in deliveries if d.document_status != "complete" or d.performance_declaration_status != "complete" or d.elog_evidence_status != "complete"),
        },
    }


def update_work_package(db: Session, work_package_id: str, data: WorkPackageUpdateIn, actor: str) -> PMWorkPackage:
    row = db.scalar(select(PMWorkPackage).where(PMWorkPackage.work_package_id == work_package_id))
    if not row:
        raise KeyError(work_package_id)
    before = {"status": row.status, "progress_pct": row.progress_pct, "blocked": row.blocked, "block_reason": row.block_reason}
    for field in ("status", "progress_pct", "assignee", "blocked", "block_reason", "next_action"):
        value = getattr(data, field)
        if value is not None:
            setattr(row, field, value)
    if row.status == "done":
        row.progress_pct = 100
        row.blocked = False
        row.actual_end = row.actual_end or utcnow()
    if row.status == "in_progress" and not row.actual_start:
        row.actual_start = utcnow()
    row.updated_at = utcnow()
    audit(db, actor=actor, action="operations.work_package.update", entity_type="work_package", entity_id=row.work_package_id, before=before, after={"status": row.status, "progress_pct": row.progress_pct, "blocked": row.blocked, "block_reason": row.block_reason})
    db.commit()
    db.refresh(row)
    return row


def update_gate(db: Session, gate_id: str, data: GateCheckIn, actor: str) -> PMGateCheck:
    row = db.scalar(select(PMGateCheck).where(PMGateCheck.gate_id == gate_id))
    if not row:
        raise KeyError(gate_id)
    before = {"status": row.status, "evidence_url": row.evidence_url}
    row.status = data.status
    row.evidence_url = data.evidence_url or row.evidence_url
    row.notes = data.notes if data.notes is not None else row.notes
    row.checked_by = data.checked_by or actor
    row.checked_at = utcnow() if data.status in {"passed", "failed", "waived"} else None
    audit(db, actor=actor, action="operations.gate.update", entity_type="gate", entity_id=row.gate_id, before=before, after={"status": row.status, "evidence_url": row.evidence_url})
    db.commit()
    db.refresh(row)
    return row


def create_daily_report(db: Session, data: DailyReportIn, actor: str) -> SiteDailyReport:
    if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == data.project_id)):
        raise KeyError(data.project_id)
    report_date = data.report_date or utcnow()
    existing = db.scalar(select(SiteDailyReport).where(
        SiteDailyReport.project_id == data.project_id,
        func.date(SiteDailyReport.report_date) == report_date.date(),
    ))
    if existing:
        before = {"summary": existing.summary, "blockers": existing.blockers, "status": existing.status}
        existing.reporter = data.reporter
        existing.weather = data.weather
        existing.workers_total = data.workers_total
        existing.summary = data.summary
        existing.blockers = data.blockers
        existing.safety_status = data.safety_status
        existing.quality_status = data.quality_status
        existing.status = "submitted"
        existing.evidence_url = data.evidence_url
        existing.voice_note_text = data.voice_note_text
        existing.source_device_id = data.source_device_id
        existing.submitted_at = utcnow()
        row = existing
        action = "operations.daily_report.update"
    else:
        row = SiteDailyReport(
            report_id=_id("RPT"), project_id=data.project_id, report_date=report_date,
            reporter=data.reporter, weather=data.weather, workers_total=data.workers_total,
            summary=data.summary, blockers=data.blockers, safety_status=data.safety_status,
            quality_status=data.quality_status, evidence_url=data.evidence_url,
            voice_note_text=data.voice_note_text, source_device_id=data.source_device_id,
        )
        db.add(row)
        before = None
        action = "operations.daily_report.create"
    audit(db, actor=actor, action=action, entity_type="daily_report", entity_id=row.report_id, before=before, after={"project_id": row.project_id, "summary": row.summary, "blockers": row.blockers})
    if data.blockers:
        create_issue(db, SiteIssueIn(
            project_id=data.project_id, report_id=row.report_id, issue_type="blocker", severity="high",
            title="Napi jelentésben rögzített blokkoló akadály", description=data.blockers,
            responsible="Projektvezetés", due_at=utcnow() + timedelta(days=1), deadline_impact_days=1,
            evidence_url=data.evidence_url,
        ), actor=actor, commit=False)
    db.commit()
    db.refresh(row)
    return row


def create_issue(db: Session, data: SiteIssueIn, actor: str, commit: bool = True) -> SiteIssue:
    row = SiteIssue(
        issue_id=_id("ISS"), project_id=data.project_id, report_id=data.report_id,
        work_package_id=data.work_package_id, issue_type=data.issue_type, severity=data.severity,
        title=data.title, description=data.description, location=data.location,
        responsible=data.responsible, due_at=data.due_at, evidence_url=data.evidence_url,
        financial_impact_huf=data.financial_impact_huf, deadline_impact_days=data.deadline_impact_days,
    )
    db.add(row)
    task = TaskRecord(
        task_id=_id("TASK"), project_id=data.project_id, title=data.title,
        description=data.description, assignee=data.responsible, due_at=data.due_at,
        priority="critical" if data.severity == "critical" else "high" if data.severity == "high" else "normal",
        status="open", executive_relevance=data.severity in {"critical", "high"},
    )
    db.add(task)
    event_type = "QUALITY_VARIANCE_DETECTED" if data.issue_type == "quality" else "SITE_BLOCKER_RECORDED"
    event = EventRecord(
        event_id=_id("EVT"), dedupe_key=f"SITE:{row.issue_id}", project_id=data.project_id,
        source_module="project_control", event_type=event_type, object_type="SiteIssue", object_id=row.issue_id,
        severity=data.severity, status="open", financial_impact_huf=data.financial_impact_huf,
        deadline_impact_days=data.deadline_impact_days, responsible=data.responsible,
        next_action=data.title, executive_relevance=data.severity in {"critical", "high"},
        evidence_url=data.evidence_url, payload_json=json.dumps({"issue_type": data.issue_type, "title": data.title}, ensure_ascii=False),
    )
    db.add(event)
    audit(db, actor=actor, action="operations.site_issue.create", entity_type="site_issue", entity_id=row.issue_id, after={"project_id": data.project_id, "severity": data.severity, "title": data.title})
    if commit:
        db.commit()
        db.refresh(row)
    return row


def create_delivery_note(db: Session, data: DeliveryNoteIn, actor: str) -> tuple[DeliveryNoteProjection, MaterialLot | None]:
    order = db.scalar(select(ProcurementOrderProjection).where(ProcurementOrderProjection.order_id == data.order_id))
    if not order:
        raise KeyError(data.order_id)
    row = DeliveryNoteProjection(
        delivery_note_id=_id("DN"), order_id=data.order_id, project_id=data.project_id,
        note_number=data.note_number, source_url=data.source_url, received_at=data.received_at or utcnow(),
        receiver=data.receiver, item_summary=data.item_summary, ordered_quantity=data.ordered_quantity,
        received_quantity=data.received_quantity, unit=data.unit, actual_specification=data.actual_specification,
        quality_status=data.quality_status, damage_or_shortage=data.damage_or_shortage,
        plan_match=data.plan_match, document_status=data.document_status,
        performance_declaration_status=data.performance_declaration_status,
        elog_evidence_status=data.elog_evidence_status,
    )
    db.add(row)
    variance = data.received_quantity != data.ordered_quantity or data.plan_match != "matched" or data.quality_status != "accepted"
    docs_missing = data.document_status != "complete"
    evidence_missing = data.performance_declaration_status != "complete" or data.elog_evidence_status != "complete"
    order.delivery_status = "received_with_variance" if variance else "received"
    order.document_status = "missing" if docs_missing or evidence_missing else "complete"
    order.variance_status = "variance" if variance else "none"
    lot = None
    if data.received_quantity > 0:
        lot = MaterialLot(
            lot_id=_id("LOT"), project_id=data.project_id, delivery_note_id=row.delivery_note_id,
            material=data.item_summary, received_quantity=data.received_quantity,
            current_quantity=data.received_quantity, unit=data.unit, storage_location=data.storage_location,
            planned_use_location=None, custodian=data.custodian or data.receiver,
            weather_protection=data.weather_protection, evidence_url=data.evidence_url or data.source_url,
        )
        db.add(lot)
    if docs_missing:
        _procurement_event(db, row, "DELIVERY_NOTE_MISSING", "critical", "Hiányzó vagy nem teljes szállítólevél", actor)
    if evidence_missing:
        _procurement_event(db, row, "PERFORMANCE_DECLARATION_MISSING", "critical", "Teljesítménynyilatkozat vagy e-napló bizonyíték hiányzik", actor)
    if variance:
        _procurement_event(db, row, "QUANTITY_VARIANCE_DETECTED", "high", "Szállított mennyiség vagy minőség eltér a rendeléstől", actor)
    audit(db, actor=actor, action="operations.delivery_note.create", entity_type="delivery_note", entity_id=row.delivery_note_id, after={"order_id": data.order_id, "received_quantity": str(data.received_quantity), "variance": variance, "documents_complete": not docs_missing and not evidence_missing})
    db.commit()
    db.refresh(row)
    if lot:
        db.refresh(lot)
    return row, lot


def _procurement_event(db: Session, delivery: DeliveryNoteProjection, event_type: str, severity: str, title: str, actor: str) -> None:
    event = EventRecord(
        event_id=_id("EVT"), dedupe_key=f"{event_type}:{delivery.delivery_note_id}",
        project_id=delivery.project_id, source_module="procurement", event_type=event_type,
        object_type="DeliveryNote", object_id=delivery.delivery_note_id, severity=severity,
        status="open", responsible="Beszerzés / projektvezetés", next_action=title,
        executive_relevance=True, evidence_url=delivery.source_url,
        payload_json=json.dumps({"order_id": delivery.order_id, "delivery_note_id": delivery.delivery_note_id}, ensure_ascii=False),
    )
    db.add(event)
    task = TaskRecord(
        task_id=_id("TASK"), project_id=delivery.project_id, source_event_id=event.event_id,
        title=title, description=f"Rendelés: {delivery.order_id}; szállítólevél: {delivery.note_number or delivery.delivery_note_id}",
        assignee="Beszerzés / projektvezetés", due_at=utcnow() + timedelta(days=1),
        priority="critical" if severity == "critical" else "high", status="open", executive_relevance=True,
    )
    db.add(task)


def create_material_movement(db: Session, data: MaterialMovementIn, actor: str) -> MaterialMovement:
    lot = db.scalar(select(MaterialLot).where(MaterialLot.lot_id == data.lot_id))
    if not lot:
        raise KeyError(data.lot_id)
    before_qty = _decimal(lot.current_quantity)
    outbound = data.movement_type in {"use", "transfer_out", "damage", "return"}
    inbound = data.movement_type in {"receipt", "return_in", "adjustment_in"}
    if outbound and before_qty < data.quantity:
        raise ValueError("A mozgás után a készlet nem lehet negatív.")
    if outbound:
        lot.current_quantity = before_qty - data.quantity
    elif inbound:
        lot.current_quantity = before_qty + data.quantity
    if data.to_location:
        lot.actual_use_location = data.to_location
        if data.movement_type in {"transfer", "transfer_out", "transfer_in"}:
            lot.storage_location = data.to_location
    if lot.current_quantity == 0:
        lot.status = "depleted"
    row = MaterialMovement(
        movement_id=_id("MOV"), lot_id=lot.lot_id, project_id=lot.project_id,
        movement_type=data.movement_type, quantity=data.quantity, from_location=data.from_location,
        to_location=data.to_location, responsible=data.responsible, note=data.note,
        occurred_at=data.occurred_at or utcnow(),
    )
    db.add(row)
    audit(db, actor=actor, action="operations.material_movement.create", entity_type="material_lot", entity_id=lot.lot_id, before={"current_quantity": str(before_qty)}, after={"current_quantity": str(lot.current_quantity), "movement_type": data.movement_type, "quantity": str(data.quantity)})
    db.commit()
    db.refresh(row)
    return row


def create_usage_control(db: Session, data: MaterialUsageIn, actor: str) -> MaterialUsageControl:
    allowed = data.planned_quantity * (Decimal("1") + data.waste_pct / Decimal("100"))
    overuse = max(data.actual_quantity - allowed, Decimal("0"))
    proposed_value = overuse * data.unit_cost_huf + data.damage_huf
    row = MaterialUsageControl(
        control_id=_id("USE"), project_id=data.project_id, work_package_id=data.work_package_id,
        lot_id=data.lot_id, subcontractor=data.subcontractor, planned_quantity=data.planned_quantity,
        waste_pct=data.waste_pct, allowed_quantity=allowed, actual_quantity=data.actual_quantity,
        unit=data.unit, unit_cost_huf=data.unit_cost_huf, damage_huf=data.damage_huf,
        decision_status="review_required" if proposed_value > 0 else "no_variance",
        contractual_basis=data.contractual_basis,
    )
    db.add(row)
    if proposed_value > 0:
        event = EventRecord(
            event_id=_id("EVT"), dedupe_key=f"MATERIAL_OVERUSE:{row.control_id}",
            project_id=data.project_id, source_module="procurement", event_type="MATERIAL_OVERUSE_DETECTED",
            object_type="MaterialUsageControl", object_id=row.control_id, severity="high", status="open",
            financial_impact_huf=proposed_value, responsible="PM + pénzügy",
            next_action="Szerződéses jogalap és emberi jóváhagyás vizsgálata; automatikus levonás tilos.",
            executive_relevance=True,
            payload_json=json.dumps({"overuse_quantity": str(overuse), "proposed_value_huf": str(proposed_value), "automatic_deduction": False}, ensure_ascii=False),
        )
        db.add(event)
    audit(db, actor=actor, action="operations.material_usage.create", entity_type="material_usage", entity_id=row.control_id, after={"allowed_quantity": str(allowed), "actual_quantity": str(data.actual_quantity), "proposed_value_huf": str(proposed_value), "automatic_deduction": False})
    db.commit()
    db.refresh(row)
    return row


def create_operations_command(db: Session, data: OperationsCommandIn, actor: str) -> OutboxMessage:
    message = OutboxMessage(
        message_id=_id("CMD"), destination_module=data.destination_module,
        endpoint=f"/commands/{data.command_type}",
        payload_json=json.dumps({
            "project_id": data.project_id, "command_type": data.command_type,
            "object_type": data.object_type, "object_id": data.object_id,
            "payload": data.payload, "requested_by": actor,
        }, ensure_ascii=False),
        status="pending", max_retries=5,
    )
    db.add(message)
    audit(db, actor=actor, action="operations.command.request", entity_type="outbox_message", entity_id=message.message_id, after={"destination_module": data.destination_module, "command_type": data.command_type, "project_id": data.project_id})
    db.commit()
    db.refresh(message)
    return message


def field_projects(db: Session) -> list[dict]:
    rows = operations_portfolio(db)
    for row in rows:
        project_id = row["project"].project_id
        row["latest_report"] = db.scalar(select(SiteDailyReport).where(SiteDailyReport.project_id == project_id).order_by(desc(SiteDailyReport.report_date)).limit(1))
        row["deliveries_today"] = db.scalar(select(func.count(DeliveryNoteProjection.id)).where(
            DeliveryNoteProjection.project_id == project_id,
            func.date(DeliveryNoteProjection.received_at) == utcnow().date(),
        )) or 0
    return rows


def procurement_summary(db: Session, project_id: str | None = None) -> dict:
    filters = []
    if project_id:
        filters.append(ProcurementOrderProjection.project_id == project_id)
    orders = db.scalars(select(ProcurementOrderProjection).where(*filters).order_by(desc(ProcurementOrderProjection.updated_at))).all()
    delivery_filters = [DeliveryNoteProjection.project_id == project_id] if project_id else []
    deliveries = db.scalars(select(DeliveryNoteProjection).where(*delivery_filters).order_by(desc(DeliveryNoteProjection.received_at))).all()
    lot_filters = [MaterialLot.project_id == project_id] if project_id else []
    lots = db.scalars(select(MaterialLot).where(*lot_filters).order_by(MaterialLot.material)).all()
    control_filters = [MaterialUsageControl.project_id == project_id] if project_id else []
    controls = db.scalars(select(MaterialUsageControl).where(*control_filters).order_by(desc(MaterialUsageControl.updated_at))).all()
    return {
        "orders": orders,
        "deliveries": deliveries,
        "lots": lots,
        "controls": controls,
        "metrics": {
            "orders_total": len(orders),
            "ordered_huf": sum((_decimal(o.total_huf) for o in orders), Decimal("0")),
            "late_orders": sum(1 for o in orders if _is_past(o.delivery_due) and o.delivery_status not in {"received", "complete"}),
            "document_blocks": sum(1 for d in deliveries if d.document_status != "complete" or d.performance_declaration_status != "complete" or d.elog_evidence_status != "complete"),
            "quantity_variances": sum(1 for d in deliveries if d.received_quantity != d.ordered_quantity or d.plan_match != "matched"),
            "lots_in_stock": sum(1 for l in lots if l.status == "in_stock"),
            "usage_reviews": sum(1 for c in controls if c.decision_status == "review_required"),
        },
    }
