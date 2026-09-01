from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    CalendarEntry,
    CustomerDecisionRequest,
    CustomerDecisionResponse,
    CustomerPortalAccess,
    CustomerPortalUpdate,
    CustomerPortalUpdateAcknowledgement,
    ProjectObjectState,
    ProjectRegistry,
    TaskRecord,
    WorkspaceDocument,
)

INTERNAL_READ_ROLES = {
    "owner",
    "managing-director",
    "platform-admin",
    "project-manager",
    "sales",
    "finance",
    "legal",
    "designer",
}
INTERNAL_WRITE_ROLES = {"owner", "managing-director", "platform-admin", "project-manager"}
CUSTOMER_VISIBLE_SOURCES = {
    "buildconfig",
    "change-control",
    "contract-generator",
    "housebuild-agent",
    "imperial-care",
    "intent-declaration",
    "plancheck",
    "project-control",
    "reservation-engine",
}


def _identity(user: object) -> tuple[str, str]:
    return (
        str(getattr(user, "role", "")),
        str(getattr(user, "email", "")).strip().lower(),
    )


def _active_accesses(db: Session, project_id: str) -> list[CustomerPortalAccess]:
    return list(db.scalars(
        select(CustomerPortalAccess).where(
            CustomerPortalAccess.project_id == project_id,
            CustomerPortalAccess.active.is_(True),
        )
    ).all())


def assert_project_access(
    db: Session, project_id: str, user: object, *, internal_write: bool = False
) -> list[CustomerPortalAccess]:
    role, email = _identity(user)
    accesses = _active_accesses(db, project_id)
    if internal_write:
        if role not in INTERNAL_WRITE_ROLES:
            raise PermissionError("Ezt a MyImperial műveletet csak projektfelelős végezheti.")
        if not accesses:
            raise ValueError("A projektnek nincs aktív MyImperial-hozzáférése.")
        return accesses
    if role in INTERNAL_READ_ROLES:
        if not accesses:
            raise PermissionError("A projekt nincs kiadva a MyImperial portálra.")
        return accesses
    if role != "customer" or not any(row.customer_email.lower() == email for row in accesses):
        raise PermissionError("Nincs MyImperial-hozzáférése ehhez a projekthez.")
    return accesses


def project_portal_detail(db: Session, project_id: str, user: object) -> dict:
    accesses = assert_project_access(db, project_id, user)
    role, email = _identity(user)
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if not project:
        raise KeyError(project_id)
    updates = db.scalars(
        select(CustomerPortalUpdate)
        .where(CustomerPortalUpdate.project_id == project_id)
        .order_by(desc(CustomerPortalUpdate.published_at))
    ).all()
    acknowledgements = db.scalars(
        select(CustomerPortalUpdateAcknowledgement).where(
            CustomerPortalUpdateAcknowledgement.update_id_fk.in_(
                [row.id for row in updates] or [-1]
            )
        )
    ).all()
    ack_by_update: dict[int, list[CustomerPortalUpdateAcknowledgement]] = {}
    for acknowledgement in acknowledgements:
        ack_by_update.setdefault(acknowledgement.update_id_fk, []).append(acknowledgement)

    decisions = db.scalars(
        select(CustomerDecisionRequest)
        .where(CustomerDecisionRequest.project_id == project_id)
        .order_by(desc(CustomerDecisionRequest.created_at))
    ).all()
    responses = db.scalars(
        select(CustomerDecisionResponse).where(
            CustomerDecisionResponse.decision_id_fk.in_([row.id for row in decisions] or [-1])
        )
    ).all()
    response_by_decision = {row.decision_id_fk: row for row in responses}
    tasks_stmt = select(TaskRecord).where(
        TaskRecord.project_id == project_id,
        TaskRecord.status.in_(["open", "in_progress", "waiting_customer"]),
    )
    if role == "customer":
        tasks_stmt = tasks_stmt.where(TaskRecord.assignee == email)
    tasks = db.scalars(tasks_stmt.order_by(TaskRecord.due_at)).all()
    milestones = db.scalars(
        select(CalendarEntry)
        .where(
            CalendarEntry.project_id == project_id,
            CalendarEntry.status.in_(["planned", "confirmed", "in_progress", "done"]),
        )
        .order_by(CalendarEntry.starts_at)
        .limit(50)
    ).all()
    states = db.scalars(
        select(ProjectObjectState)
        .where(
            ProjectObjectState.project_id == project_id,
            ProjectObjectState.source_module.in_(sorted(CUSTOMER_VISIBLE_SOURCES)),
        )
        .order_by(desc(ProjectObjectState.updated_at))
    ).all()
    documents = db.scalars(
        select(WorkspaceDocument)
        .where(
            WorkspaceDocument.project_id == project_id,
            WorkspaceDocument.source_system == "change-control",
            WorkspaceDocument.confidentiality == "customer",
            WorkspaceDocument.approval_status == "approved",
            WorkspaceDocument.verification_status == "sha256_verified",
        )
        .order_by(desc(WorkspaceDocument.created_at))
    ).all()
    return {
        "internal": role in INTERNAL_READ_ROLES,
        "can_publish": role in INTERNAL_WRITE_ROLES,
        "project": project,
        "accesses": accesses,
        "updates": [
            {
                "row": row,
                "acknowledged": any(
                    a.customer_email.lower() == email
                    for a in ack_by_update.get(row.id, [])
                ),
                "acknowledgements": ack_by_update.get(row.id, []),
            }
            for row in updates
        ],
        "decisions": [
            {
                "row": row,
                "options": json.loads(row.options_json),
                "response": response_by_decision.get(row.id),
            }
            for row in decisions
        ],
        "tasks": tasks,
        "milestones": milestones,
        "states": states,
        "documents": documents,
        "metrics": {
            "progress": max([row.progress_percent for row in updates], default=0),
            "open_decisions": sum(1 for row in decisions if row.status == "open"),
            "open_tasks": len(tasks),
            "milestones": len(milestones),
        },
    }


def publish_project_update(
    db: Session,
    project_id: str,
    user: object,
    *,
    title: str,
    body: str,
    progress_percent: int,
    requires_acknowledgement: bool,
) -> CustomerPortalUpdate:
    accesses = assert_project_access(db, project_id, user, internal_write=True)
    _role, email = _identity(user)
    title, body = title.strip(), body.strip()
    if not title or not body:
        raise ValueError("A cím és a publikált projektfrissítés kötelező.")
    if not 0 <= progress_percent <= 100:
        raise ValueError("A készültség 0 és 100 százalék közötti érték lehet.")
    row = CustomerPortalUpdate(
        update_id=f"MYI-UPD-{uuid4().hex[:12].upper()}",
        project_id=project_id,
        title=title,
        body=body,
        progress_percent=progress_percent,
        requires_acknowledgement=requires_acknowledgement,
        published_by=email,
    )
    db.add(row)
    db.flush()
    if requires_acknowledgement:
        for access in accesses:
            db.add(
                TaskRecord(
                    task_id=f"TASK-MYI-ACK-{uuid4().hex[:12].upper()}",
                    project_id=project_id,
                    source_event_id=row.update_id,
                    title=f"Projektfrissítés visszaigazolása: {title}",
                    description=body,
                    assignee=access.customer_email.lower(),
                    priority="normal",
                    status="waiting_customer",
                )
            )
    audit(
        db,
        actor=email,
        action="myimperial_update_published",
        entity_type="customer_portal_update",
        entity_id=row.update_id,
        after={"project_id": project_id, "progress_percent": progress_percent},
    )
    db.commit()
    db.refresh(row)
    return row


def acknowledge_project_update(
    db: Session, project_id: str, update_id: str, user: object
) -> CustomerPortalUpdateAcknowledgement:
    role, email = _identity(user)
    if role != "customer":
        raise PermissionError("A visszaigazolást az ügyfélnek kell megtennie.")
    assert_project_access(db, project_id, user)
    update = db.scalar(
        select(CustomerPortalUpdate).where(
            CustomerPortalUpdate.project_id == project_id,
            CustomerPortalUpdate.update_id == update_id,
        )
    )
    if not update:
        raise KeyError(update_id)
    existing = db.scalar(
        select(CustomerPortalUpdateAcknowledgement).where(
            CustomerPortalUpdateAcknowledgement.update_id_fk == update.id,
            CustomerPortalUpdateAcknowledgement.customer_email == email,
        )
    )
    if existing:
        return existing
    row = CustomerPortalUpdateAcknowledgement(
        acknowledgement_id=f"MYI-ACK-{uuid4().hex[:12].upper()}",
        update_id_fk=update.id,
        customer_email=email,
    )
    db.add(row)
    for task in db.scalars(
        select(TaskRecord).where(
            TaskRecord.project_id == project_id,
            TaskRecord.source_event_id == update.update_id,
            TaskRecord.assignee == email,
        )
    ).all():
        task.status = "done"
    audit(
        db,
        actor=email,
        action="myimperial_update_acknowledged",
        entity_type="customer_portal_update",
        entity_id=update_id,
        after={"project_id": project_id},
    )
    db.commit()
    db.refresh(row)
    return row


def create_decision_request(
    db: Session,
    project_id: str,
    user: object,
    *,
    title: str,
    description: str,
    options: list[str],
    due_at: datetime | None,
    source_module: str | None = None,
    source_object_id: str | None = None,
    source_version: int | None = None,
) -> CustomerDecisionRequest:
    accesses = assert_project_access(db, project_id, user, internal_write=True)
    _role, email = _identity(user)
    title, description = title.strip(), description.strip()
    clean_options = list(dict.fromkeys(option.strip() for option in options if option.strip()))
    if not title or not description:
        raise ValueError("A döntés címe és leírása kötelező.")
    if not 2 <= len(clean_options) <= 6:
        raise ValueError("A döntéshez 2–6 egyértelmű opció szükséges.")
    if due_at and due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=UTC)
    if due_at and due_at <= datetime.now(UTC):
        raise ValueError("A döntési határidőnek jövőbeli időpontnak kell lennie.")
    row = CustomerDecisionRequest(
        decision_id=f"MYI-DEC-{uuid4().hex[:12].upper()}",
        project_id=project_id,
        title=title,
        description=description,
        options_json=json.dumps(clean_options, ensure_ascii=False),
        due_at=due_at,
        source_module=source_module.strip() if source_module else None,
        source_object_id=source_object_id.strip() if source_object_id else None,
        source_version=source_version,
        created_by=email,
    )
    db.add(row)
    db.flush()
    for access in accesses:
        db.add(
            TaskRecord(
                task_id=f"TASK-MYI-DEC-{uuid4().hex[:12].upper()}",
                project_id=project_id,
                source_event_id=row.decision_id,
                title=f"Ügyféldöntés szükséges: {title}",
                description=description,
                assignee=access.customer_email.lower(),
                due_at=due_at,
                priority="high",
                status="waiting_customer",
            )
        )
    audit(
        db,
        actor=email,
        action="myimperial_decision_requested",
        entity_type="customer_decision",
        entity_id=row.decision_id,
        after={"project_id": project_id, "options": clean_options, "due_at": due_at},
    )
    db.commit()
    db.refresh(row)
    return row


def respond_to_decision(
    db: Session,
    project_id: str,
    decision_id: str,
    user: object,
    *,
    selected_option: str,
    note: str,
) -> CustomerDecisionResponse:
    role, email = _identity(user)
    if role != "customer":
        raise PermissionError("Az ügyféldöntést az ügyfélnek kell rögzítenie.")
    assert_project_access(db, project_id, user)
    decision = db.scalar(
        select(CustomerDecisionRequest).where(
            CustomerDecisionRequest.project_id == project_id,
            CustomerDecisionRequest.decision_id == decision_id,
        )
    )
    if not decision:
        raise KeyError(decision_id)
    if decision.status != "open":
        raise ValueError("A döntési kérés már nem nyitott.")
    options = json.loads(decision.options_json)
    if selected_option not in options:
        raise ValueError("Csak a kiadott döntési opciók egyike választható.")
    existing = db.scalar(
        select(CustomerDecisionResponse).where(
            CustomerDecisionResponse.decision_id_fk == decision.id,
            CustomerDecisionResponse.customer_email == email,
        )
    )
    if existing:
        raise ValueError(
            "A döntés már rögzítve van; módosítás csak "
            "ChangeControl-folyamatban lehetséges."
        )
    row = CustomerDecisionResponse(
        response_id=f"MYI-RSP-{uuid4().hex[:12].upper()}",
        decision_id_fk=decision.id,
        customer_email=email,
        selected_option=selected_option,
        note=note.strip() or None,
    )
    db.add(row)
    decision.status = "responded"
    for task in db.scalars(
        select(TaskRecord).where(
            TaskRecord.project_id == project_id,
            TaskRecord.source_event_id == decision.decision_id,
            TaskRecord.assignee == email,
        )
    ).all():
        task.status = "done"
    state = db.scalar(
        select(ProjectObjectState).where(
            ProjectObjectState.project_id == project_id,
            ProjectObjectState.source_module == "my-imperial",
            ProjectObjectState.object_type == "CustomerDecision",
            ProjectObjectState.object_id == decision.decision_id,
        )
    )
    if not state:
        state = ProjectObjectState(
            project_id=project_id,
            source_module="my-imperial",
            object_type="CustomerDecision",
            object_id=decision.decision_id,
            status="responded",
        )
        db.add(state)
    state.status = "responded"
    state.summary = f"Ügyféldöntés: {selected_option}"
    state.payload_json = json.dumps(
        {"customer_email": email, "selected_option": selected_option}, ensure_ascii=False
    )
    audit(
        db,
        actor=email,
        action="myimperial_decision_responded",
        entity_type="customer_decision",
        entity_id=decision_id,
        after={"project_id": project_id, "selected_option": selected_option},
    )
    db.commit()
    db.refresh(row)
    return row


def complete_customer_task(db: Session, project_id: str, task_id: str, user: object) -> TaskRecord:
    role, email = _identity(user)
    if role != "customer":
        raise PermissionError("Az ügyfélteendőt az érintett ügyfél zárhatja le.")
    assert_project_access(db, project_id, user)
    task = db.scalar(
        select(TaskRecord).where(
            TaskRecord.project_id == project_id,
            TaskRecord.task_id == task_id,
            TaskRecord.assignee == email,
        )
    )
    if not task:
        raise KeyError(task_id)
    if task.status not in {"open", "in_progress", "waiting_customer"}:
        raise ValueError("A teendő már nem zárható le.")
    task.status = "done"
    audit(
        db,
        actor=email,
        action="myimperial_customer_task_completed",
        entity_type="task",
        entity_id=task_id,
        after={"project_id": project_id},
    )
    db.commit()
    db.refresh(task)
    return task
