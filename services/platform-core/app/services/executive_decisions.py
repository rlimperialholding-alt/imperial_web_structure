from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import ConsistencyIssue, EventRecord, ProjectRegistry, TaskRecord


BLOCKING_EVENT_TYPES = {
    "WORK_START_BLOCKED",
    "CONTRACT_EVIDENCE_MISSING",
    "CHANGE_NOT_APPROVED",
    "PERFORMANCE_DECLARATION_MISSING",
    "PROJECT_MARGIN_AT_RISK",
    "MODULE_HEALTH_FAILED",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _refresh_project_exposure(db: Session, project_id: str) -> None:
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if not project:
        return
    open_events = list(
        db.scalars(
            select(EventRecord)
            .where(EventRecord.project_id == project_id, EventRecord.status == "open")
            .order_by(desc(EventRecord.received_at))
        )
    )
    project.financial_impact_huf = sum(
        (abs(Decimal(str(item.financial_impact_huf or 0))) for item in open_events),
        Decimal("0"),
    )
    project.deadline_impact_days = max(
        (item.deadline_impact_days or 0 for item in open_events), default=0
    )
    project.blocked = any(item.event_type in BLOCKING_EVENT_TYPES for item in open_events)
    severities = {item.severity for item in open_events}
    project.risk_level = "red" if "critical" in severities else "amber" if "high" in severities else "green"
    project.next_action = next((item.next_action for item in open_events if item.next_action), None)
    project.responsible = next((item.responsible for item in open_events if item.responsible), None)


def resolve_executive_event(
    db: Session,
    event_id: str,
    *,
    resolution_note: str,
    actor: str,
    close_related_tasks: bool = True,
) -> EventRecord:
    row = db.scalar(select(EventRecord).where(EventRecord.event_id == event_id))
    if not row:
        raise KeyError(event_id)
    if row.status != "open":
        raise ValueError("Csak nyitott vezetői esemény zárható le.")
    note = resolution_note.strip()
    if len(note) < 10:
        raise ValueError("A lezárási bizonyíték legalább 10 karakter legyen.")
    before = {"status": row.status, "project_id": row.project_id}
    row.status = "resolved"
    row.resolution_note = note
    row.resolved_by = actor
    row.resolved_at = utcnow()
    closed_tasks: list[str] = []
    if close_related_tasks:
        tasks = db.scalars(
            select(TaskRecord).where(
                TaskRecord.source_event_id == event_id,
                TaskRecord.status.not_in(("done", "cancelled")),
            )
        ).all()
        for task in tasks:
            task.status = "done"
            closed_tasks.append(task.task_id)
    db.flush()
    _refresh_project_exposure(db, row.project_id)
    audit(
        db,
        actor=actor,
        action="executive_event_resolved",
        entity_type="event",
        entity_id=event_id,
        before=before,
        after={"status": row.status, "resolution_note": note, "closed_tasks": closed_tasks},
    )
    db.commit()
    db.refresh(row)
    return row


def assign_consistency_issue(
    db: Session,
    fingerprint: str,
    *,
    responsible: str,
    assignment_note: str,
    actor: str,
) -> ConsistencyIssue:
    row = db.scalar(select(ConsistencyIssue).where(ConsistencyIssue.fingerprint == fingerprint))
    if not row:
        raise KeyError(fingerprint)
    owner = responsible.strip()
    note = assignment_note.strip()
    if len(owner) < 3:
        raise ValueError("A felelős megadása kötelező.")
    if len(note) < 10:
        raise ValueError("A felelőshöz rendelés indoklása legalább 10 karakter legyen.")
    before = {"responsible": row.responsible, "assignment_note": row.assignment_note}
    row.responsible = owner
    row.assignment_note = note
    audit(
        db,
        actor=actor,
        action="consistency_issue_assigned",
        entity_type="consistency_issue",
        entity_id=fingerprint,
        before=before,
        after={"responsible": owner, "assignment_note": note},
    )
    db.commit()
    db.refresh(row)
    return row
