from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    ConsistencyIssue,
    EnterpriseCanonicalRecord,
    EventRecord,
    ModuleRegistry,
    ProjectFact,
    ProjectObjectState,
    ProjectRegistry,
    TaskRecord,
    User,
    WorkspaceDocument,
)
from ..schemas import TaskUpdateIn, WorkspaceDocumentIn


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def workspace_summary(db: Session, user: User) -> dict[str, Any]:
    now = utcnow()
    open_tasks = db.scalars(select(TaskRecord).where(TaskRecord.status.in_(["open", "in_progress", "blocked"]))).all()
    assigned_tasks = [t for t in open_tasks if not t.assignee or t.assignee in {user.email, user.name}]
    overdue = [t for t in assigned_tasks if _aware(t.due_at) and _aware(t.due_at) < now]
    today = [t for t in assigned_tasks if _aware(t.due_at) and _aware(t.due_at).date() == now.date()]
    blocked_projects = db.scalars(select(ProjectRegistry).where(ProjectRegistry.blocked.is_(True)).order_by(desc(ProjectRegistry.financial_impact_huf))).all()
    executive_events = db.scalars(select(EventRecord).where(
        EventRecord.status == "open", EventRecord.executive_relevance.is_(True)
    ).order_by(desc(EventRecord.received_at)).limit(8)).all()
    recent_projects = db.scalars(select(ProjectRegistry).order_by(desc(ProjectRegistry.updated_at)).limit(8)).all()
    recent_documents = db.scalars(select(WorkspaceDocument).order_by(desc(WorkspaceDocument.updated_at)).limit(8)).all()
    modules = db.scalars(select(ModuleRegistry).order_by(ModuleRegistry.name)).all()
    open_issues = db.scalars(select(ConsistencyIssue).where(ConsistencyIssue.status == "open")).all()
    return {
        "open_tasks": len(assigned_tasks),
        "overdue_tasks": len(overdue),
        "today_tasks": len(today),
        "blocked_projects": len(blocked_projects),
        "financial_impact_huf": sum((Decimal(str(p.financial_impact_huf or 0)) for p in blocked_projects), Decimal("0")),
        "open_issues": len(open_issues),
        "healthy_modules": sum(1 for m in modules if m.integration_status == "healthy"),
        "module_count": len(modules),
        "tasks": sorted(assigned_tasks, key=lambda t: (_aware(t.due_at) is None, _aware(t.due_at) or now))[:8],
        "blocked_project_rows": blocked_projects[:5],
        "executive_events": executive_events,
        "recent_projects": recent_projects,
        "recent_documents": recent_documents,
        "modules": modules,
    }


def task_metrics(db: Session, *, assignee: str | None = None) -> dict[str, int]:
    query = select(TaskRecord)
    if assignee:
        query = query.where(or_(TaskRecord.assignee == assignee, TaskRecord.assignee.is_(None)))
    tasks = db.scalars(query).all()
    now = utcnow()
    return {
        "total": len(tasks),
        "open": sum(1 for t in tasks if t.status == "open"),
        "in_progress": sum(1 for t in tasks if t.status == "in_progress"),
        "blocked": sum(1 for t in tasks if t.status == "blocked"),
        "done": sum(1 for t in tasks if t.status == "done"),
        "overdue": sum(1 for t in tasks if t.status not in {"done", "cancelled"} and _aware(t.due_at) and _aware(t.due_at) < now),
    }


def list_tasks(
    db: Session,
    *,
    status: str | None = None,
    priority: str | None = None,
    project_id: str | None = None,
    assignee: str | None = None,
    query_text: str | None = None,
) -> list[TaskRecord]:
    query = select(TaskRecord)
    if status:
        query = query.where(TaskRecord.status == status)
    if priority:
        query = query.where(TaskRecord.priority == priority)
    if project_id:
        query = query.where(TaskRecord.project_id == project_id)
    if assignee:
        query = query.where(or_(TaskRecord.assignee == assignee, TaskRecord.assignee.is_(None)))
    if query_text:
        needle = f"%{query_text.strip()}%"
        query = query.where(or_(TaskRecord.title.ilike(needle), TaskRecord.description.ilike(needle), TaskRecord.project_id.ilike(needle)))
    return db.scalars(query.order_by(TaskRecord.status, TaskRecord.due_at, desc(TaskRecord.updated_at))).all()


def update_task(db: Session, task_id: str, payload: TaskUpdateIn, *, actor: str) -> TaskRecord:
    task = db.scalar(select(TaskRecord).where(TaskRecord.task_id == task_id))
    if not task:
        raise KeyError(task_id)
    before = {
        "status": task.status,
        "assignee": task.assignee,
        "due_at": task.due_at,
        "priority": task.priority,
        "description": task.description,
    }
    for field in ("status", "assignee", "due_at", "priority", "description"):
        value = getattr(payload, field)
        if value is not None:
            setattr(task, field, value)
    audit(db, actor=actor, action="workspace_task_updated", entity_type="task", entity_id=task.task_id, before=before, after=payload.model_dump(exclude_none=True, mode="json"))
    db.commit()
    db.refresh(task)
    return task


def create_document(db: Session, payload: WorkspaceDocumentIn, *, actor: str) -> WorkspaceDocument:
    record = WorkspaceDocument(
        document_id=f"DOC-{uuid.uuid4().hex[:12].upper()}",
        project_id=payload.project_id,
        title=payload.title,
        category=payload.category,
        source_system=payload.source_system,
        source_url=payload.source_url,
        drive_file_id=payload.drive_file_id,
        mime_type=payload.mime_type,
        version_label=payload.version_label,
        approval_status=payload.approval_status,
        verification_status=payload.verification_status,
        confidentiality=payload.confidentiality,
        owner=payload.owner,
        expires_at=payload.expires_at,
        extracted_summary=payload.extracted_summary,
        metadata_json=json.dumps(payload.metadata, ensure_ascii=False, default=str),
    )
    db.add(record)
    audit(db, actor=actor, action="workspace_document_registered", entity_type="document", entity_id=record.document_id, after=payload.model_dump(mode="json"))
    db.commit()
    db.refresh(record)
    return record


def update_document_status(
    db: Session,
    document_id: str,
    *,
    approval_status: str | None = None,
    verification_status: str | None = None,
    actor: str,
) -> WorkspaceDocument:
    record = db.scalar(select(WorkspaceDocument).where(WorkspaceDocument.document_id == document_id))
    if not record:
        raise KeyError(document_id)
    before = {"approval_status": record.approval_status, "verification_status": record.verification_status}
    if approval_status:
        record.approval_status = approval_status
    if verification_status:
        record.verification_status = verification_status
    audit(db, actor=actor, action="workspace_document_status_updated", entity_type="document", entity_id=record.document_id, before=before, after={"approval_status": record.approval_status, "verification_status": record.verification_status})
    db.commit()
    db.refresh(record)
    return record


def list_documents(
    db: Session,
    *,
    project_id: str | None = None,
    category: str | None = None,
    approval_status: str | None = None,
    query_text: str | None = None,
) -> list[WorkspaceDocument]:
    query = select(WorkspaceDocument)
    if project_id:
        query = query.where(WorkspaceDocument.project_id == project_id)
    if category:
        query = query.where(WorkspaceDocument.category == category)
    if approval_status:
        query = query.where(WorkspaceDocument.approval_status == approval_status)
    if query_text:
        needle = f"%{query_text.strip()}%"
        query = query.where(or_(WorkspaceDocument.title.ilike(needle), WorkspaceDocument.extracted_summary.ilike(needle), WorkspaceDocument.project_id.ilike(needle)))
    return db.scalars(query.order_by(desc(WorkspaceDocument.updated_at))).all()


def document_metrics(db: Session) -> dict[str, int]:
    rows = db.scalars(select(WorkspaceDocument)).all()
    now = utcnow()
    return {
        "total": len(rows),
        "approved": sum(1 for r in rows if r.approval_status == "approved"),
        "pending": sum(1 for r in rows if r.approval_status in {"draft", "pending_review"}),
        "unverified": sum(1 for r in rows if r.verification_status != "verified"),
        "expiring": sum(1 for r in rows if _aware(r.expires_at) and 0 <= (_aware(r.expires_at) - now).days <= 30),
    }


def _fact_value(row: ProjectFact) -> Any:
    try:
        return json.loads(row.value_json)
    except Exception:
        return row.value_json


def project_360(db: Session, project_id: str) -> dict[str, Any]:
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if not project:
        raise KeyError(project_id)
    events = db.scalars(select(EventRecord).where(EventRecord.project_id == project_id).order_by(desc(EventRecord.occurred_at))).all()
    objects = db.scalars(select(ProjectObjectState).where(ProjectObjectState.project_id == project_id).order_by(desc(ProjectObjectState.updated_at))).all()
    tasks = db.scalars(select(TaskRecord).where(TaskRecord.project_id == project_id).order_by(TaskRecord.status, TaskRecord.due_at)).all()
    issues = db.scalars(select(ConsistencyIssue).where(ConsistencyIssue.project_id == project_id).order_by(desc(ConsistencyIssue.last_detected_at))).all()
    facts = db.scalars(select(ProjectFact).where(ProjectFact.project_id == project_id).order_by(ProjectFact.source_module, ProjectFact.fact_key)).all()
    documents = db.scalars(select(WorkspaceDocument).where(WorkspaceDocument.project_id == project_id).order_by(desc(WorkspaceDocument.updated_at))).all()
    canonical = db.scalars(select(EnterpriseCanonicalRecord).where(EnterpriseCanonicalRecord.project_id == project_id).order_by(desc(EnterpriseCanonicalRecord.updated_at))).all()
    fact_groups: dict[str, list[dict[str, Any]]] = {}
    for row in facts:
        fact_groups.setdefault(row.source_module, []).append({"key": row.fact_key, "value": _fact_value(row), "updated_at": row.updated_at})
    now = utcnow()
    return {
        "project": project,
        "events": events,
        "objects": objects,
        "tasks": tasks,
        "issues": issues,
        "facts": fact_groups,
        "documents": documents,
        "canonical": canonical,
        "open_task_count": sum(1 for t in tasks if t.status not in {"done", "cancelled"}),
        "overdue_task_count": sum(1 for t in tasks if t.status not in {"done", "cancelled"} and _aware(t.due_at) and _aware(t.due_at) < now),
        "open_issue_count": sum(1 for i in issues if i.status == "open"),
        "verified_document_count": sum(1 for d in documents if d.verification_status == "verified"),
    }


def global_search(db: Session, query_text: str, *, limit: int = 12) -> dict[str, list[dict[str, Any]]]:
    q = query_text.strip()
    if len(q) < 2:
        return {"projects": [], "tasks": [], "events": [], "documents": [], "records": []}
    needle = f"%{q}%"
    projects = db.scalars(select(ProjectRegistry).where(or_(ProjectRegistry.project_id.ilike(needle), ProjectRegistry.name.ilike(needle), ProjectRegistry.customer_name.ilike(needle))).limit(limit)).all()
    tasks = db.scalars(select(TaskRecord).where(or_(TaskRecord.title.ilike(needle), TaskRecord.description.ilike(needle), TaskRecord.project_id.ilike(needle))).limit(limit)).all()
    events = db.scalars(select(EventRecord).where(or_(EventRecord.event_type.ilike(needle), EventRecord.next_action.ilike(needle), EventRecord.project_id.ilike(needle))).limit(limit)).all()
    documents = db.scalars(select(WorkspaceDocument).where(or_(WorkspaceDocument.title.ilike(needle), WorkspaceDocument.extracted_summary.ilike(needle), WorkspaceDocument.project_id.ilike(needle))).limit(limit)).all()
    records = db.scalars(select(EnterpriseCanonicalRecord).where(or_(EnterpriseCanonicalRecord.canonical_name.ilike(needle), EnterpriseCanonicalRecord.entity_type.ilike(needle), EnterpriseCanonicalRecord.project_id.ilike(needle))).limit(limit)).all()
    return {
        "projects": [{"id": p.project_id, "title": p.name, "subtitle": p.customer_name or p.project_type or "Projekt", "url": f"/projects/{p.project_id}"} for p in projects],
        "tasks": [{"id": t.task_id, "title": t.title, "subtitle": f"{t.project_id} · {t.status}", "url": f"/tasks?project_id={t.project_id}"} for t in tasks],
        "events": [{"id": e.event_id, "title": e.event_type, "subtitle": f"{e.project_id} · {e.severity}", "url": f"/projects/{e.project_id}#timeline"} for e in events],
        "documents": [{"id": d.document_id, "title": d.title, "subtitle": f"{d.project_id or 'Általános'} · {d.category}", "url": d.source_url or f"/documents?q={d.document_id}"} for d in documents],
        "records": [{"id": r.record_id, "title": r.canonical_name, "subtitle": f"{r.entity_type} · {r.project_id or 'nincs ProjectID'}", "url": f"/imports?record={r.record_id}"} for r in records],
    }
