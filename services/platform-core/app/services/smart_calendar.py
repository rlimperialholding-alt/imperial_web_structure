from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    CalendarChangeRequest,
    CalendarDependency,
    CalendarEntry,
    EngineeringCase,
    PMPhase,
    PMWorkPackage,
    ProjectRegistry,
    TaskRecord,
)
from ..schemas import (
    CalendarChangeRequestIn,
    CalendarDependencyIn,
    CalendarEntryIn,
    CalendarRescheduleIn,
    EventIn,
)
from .integration import ingest_event

ACTIVE_STATUSES = {"planned", "confirmed", "in_progress"}
COMPLETED_STATUSES = {"completed", "cancelled"}
CALENDAR_PORTFOLIO_ROLES = {"owner", "managing-director", "platform-admin"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _validate_window(starts_at: datetime, ends_at: datetime) -> None:
    if _aware(ends_at) <= _aware(starts_at):
        raise ValueError("A befejezésnek a kezdés után kell lennie.")


def _participants(row: CalendarEntry) -> list[str]:
    try:
        value = json.loads(row.participants_json or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value if str(item).strip()]


def _entry_people(assignee: str | None, participants: list[str]) -> set[str]:
    values = [assignee, *participants]
    return {value.strip().casefold() for value in values if value and value.strip()}


def _overlaps(
    left_start: datetime,
    left_end: datetime,
    right_start: datetime,
    right_end: datetime,
) -> bool:
    return _aware(left_start) < _aware(right_end) and _aware(right_start) < _aware(left_end)


def get_entry(db: Session, entry_id: str) -> CalendarEntry:
    row = db.scalar(select(CalendarEntry).where(CalendarEntry.entry_id == entry_id))
    if not row:
        raise KeyError(entry_id)
    return row


def get_entry_for_update(db: Session, entry_id: str) -> CalendarEntry:
    row = db.scalar(
        select(CalendarEntry)
        .where(CalendarEntry.entry_id == entry_id)
        .with_for_update()
    )
    if not row:
        raise KeyError(entry_id)
    return row


def calendar_project_ids_for_user(db: Session, user: object) -> set[str] | None:
    """Return the effective calendar project scope; ``None`` means portfolio access."""

    role = str(getattr(user, "role", ""))
    if role in CALENDAR_PORTFOLIO_ROLES:
        return None
    if role != "project-manager":
        return set()
    email = str(getattr(user, "email", "")).strip().casefold()
    if not email:
        return set()
    result = set(
        db.scalars(
            select(ProjectRegistry.project_id).where(
                func.lower(ProjectRegistry.responsible) == email
            )
        ).all()
    )
    result.update(
        db.scalars(
            select(EngineeringCase.project_id).where(
                func.lower(EngineeringCase.project_manager) == email
            )
        ).all()
    )
    result.update(
        db.scalars(
            select(PMPhase.project_id).where(func.lower(PMPhase.owner) == email)
        ).all()
    )
    result.update(
        db.scalars(
            select(PMWorkPackage.project_id).where(
                func.lower(PMWorkPackage.assignee) == email
            )
        ).all()
    )
    result.update(
        db.scalars(
            select(CalendarEntry.project_id).where(
                or_(
                    func.lower(CalendarEntry.assignee) == email,
                    func.lower(CalendarEntry.created_by) == email,
                )
            )
        ).all()
    )
    result.update(
        db.scalars(
            select(TaskRecord.project_id).where(func.lower(TaskRecord.assignee) == email)
        ).all()
    )
    return result


def assert_calendar_project_access(db: Session, user: object, project_id: str) -> None:
    allowed = calendar_project_ids_for_user(db, user)
    if allowed is not None and project_id not in allowed:
        raise PermissionError(
            "A projekt nincs a felhasználó kanonikus projektmenedzseri felelősségi körében."
        )


def _check_expected_version(row: CalendarEntry, expected_version: int | None) -> None:
    if expected_version is not None and row.version != expected_version:
        raise ValueError(
            f"A naptárelem időközben módosult (várt verzió: {expected_version}, "
            f"aktuális: {row.version}). Frissítse az oldalt."
        )


def detect_resource_conflicts(
    db: Session,
    *,
    starts_at: datetime,
    ends_at: datetime,
    assignee: str | None,
    participants: list[str],
    capacity_hours: Decimal = Decimal("0"),
    exclude_entry_id: str | None = None,
) -> list[dict[str, Any]]:
    people = _entry_people(assignee, participants)
    if not people:
        return []
    rows = db.scalars(
        select(CalendarEntry).where(CalendarEntry.status.in_(ACTIVE_STATUSES))
    ).all()
    conflicts: list[dict[str, Any]] = []
    for row in rows:
        if row.entry_id == exclude_entry_id:
            continue
        shared = people & _entry_people(row.assignee, _participants(row))
        if shared and _overlaps(starts_at, ends_at, row.starts_at, row.ends_at):
            conflicts.append(
                {
                    "kind": "overlap",
                    "entry_id": row.entry_id,
                    "title": row.title,
                    "people": sorted(shared),
                    "starts_at": row.starts_at,
                    "ends_at": row.ends_at,
                }
            )

    if capacity_hours > 0 and assignee:
        day = _aware(starts_at).date()
        daily = sum(
            (
                Decimal(str(row.capacity_hours or 0))
                for row in rows
                if row.entry_id != exclude_entry_id
                and row.assignee
                and row.assignee.casefold() == assignee.casefold()
                and _aware(row.starts_at).date() == day
            ),
            Decimal("0"),
        )
        if daily + capacity_hours > Decimal("8"):
            conflicts.append(
                {
                    "kind": "capacity",
                    "entry_id": None,
                    "title": "Napi kapacitás túllépése",
                    "people": [assignee.casefold()],
                    "capacity_hours": str(daily + capacity_hours),
                }
            )
    return conflicts


def _project_exists(db: Session, project_id: str) -> bool:
    return bool(
        db.scalar(select(ProjectRegistry.id).where(ProjectRegistry.project_id == project_id))
    )


def _emit(
    db: Session,
    row: CalendarEntry,
    event_type: str,
    *,
    actor: str,
    summary: str,
    severity: str = "info",
    deadline_impact_days: int = 0,
) -> None:
    ingest_event(
        db,
        EventIn(
            event_id=f"EVT-{uuid.uuid4().hex[:12].upper()}",
            dedupe_key=f"smart-calendar:{row.entry_id}:{row.version}:{event_type}",
            project_id=row.project_id,
            source_module="smart-calendar",
            event_type=event_type,
            object_type="CalendarEntry",
            object_id=row.entry_id,
            severity=severity,
            status=row.status,
            responsible=row.assignee,
            deadline_impact_days=deadline_impact_days,
            next_action=summary if severity in {"high", "critical"} else None,
            executive_relevance=severity in {"high", "critical"},
            payload={
                "summary": summary,
                "entry_type": row.entry_type,
                "starts_at": row.starts_at.isoformat(),
                "ends_at": row.ends_at.isoformat(),
                "contractual_deadline": row.contractual_deadline,
            },
            route_to=["project-control", "workflow-center"],
        ),
        actor=actor,
    )


def create_entry(
    db: Session,
    payload: CalendarEntryIn,
    *,
    actor: str,
) -> CalendarEntry:
    _validate_window(payload.starts_at, payload.ends_at)
    if not _project_exists(db, payload.project_id):
        raise ValueError("A naptárbejegyzéshez létező kanonikus ProjectID szükséges.")
    conflicts = detect_resource_conflicts(
        db,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        assignee=payload.assignee,
        participants=payload.participants,
        capacity_hours=payload.capacity_hours,
    )
    if conflicts and not (payload.conflict_override_reason or "").strip():
        raise ValueError(
            "Erőforrás- vagy kapacitásütközés van; felülbírálási indok nélkül nem menthető."
        )
    row = CalendarEntry(
        entry_id=f"CAL-{uuid.uuid4().hex[:12].upper()}",
        project_id=payload.project_id,
        entry_type=payload.entry_type,
        title=payload.title.strip(),
        description=payload.description,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        all_day=payload.all_day,
        assignee=payload.assignee or None,
        participants_json=json.dumps(payload.participants, ensure_ascii=False),
        location=payload.location or None,
        priority=payload.priority,
        source_module=payload.source_module,
        source_object_id=payload.source_object_id or None,
        contractual_deadline=payload.contractual_deadline,
        capacity_hours=payload.capacity_hours,
        conflict_override_reason=payload.conflict_override_reason or None,
        created_by=actor,
        updated_by=actor,
    )
    db.add(row)
    db.flush()
    if payload.create_task and payload.entry_type in {
        "task",
        "milestone",
        "inspection",
        "deadline",
        "customer_decision",
        "delivery",
    }:
        task = TaskRecord(
            task_id=f"TASK-{uuid.uuid4().hex[:12].upper()}",
            project_id=row.project_id,
            title=row.title,
            description=row.description,
            assignee=row.assignee,
            due_at=row.ends_at,
            priority=row.priority,
            status="open",
            executive_relevance=row.contractual_deadline or row.priority == "critical",
        )
        db.add(task)
        db.flush()
        row.linked_task_id = task.task_id
    audit(
        db,
        actor=actor,
        action="calendar_entry_created",
        entity_type="calendar_entry",
        entity_id=row.entry_id,
        after={**payload.model_dump(mode="json"), "conflicts": conflicts},
    )
    _emit(
        db,
        row,
        "CALENDAR_ENTRY_CREATED",
        actor=actor,
        summary=f"Naptárbejegyzés létrehozva: {row.title}",
    )
    db.refresh(row)
    return row


def _dependency_rows(db: Session, entry_id: str) -> tuple[list[CalendarDependency], list[CalendarDependency]]:
    predecessors = list(
        db.scalars(
            select(CalendarDependency).where(
                CalendarDependency.successor_entry_id == entry_id,
                CalendarDependency.active.is_(True),
            )
        ).all()
    )
    successors = list(
        db.scalars(
            select(CalendarDependency).where(
                CalendarDependency.predecessor_entry_id == entry_id,
                CalendarDependency.active.is_(True),
            )
        ).all()
    )
    return predecessors, successors


def _dependency_minimum_start(
    dependency: CalendarDependency,
    predecessor: CalendarEntry,
) -> datetime:
    base = predecessor.starts_at if dependency.dependency_type == "start_to_start" else predecessor.ends_at
    return _aware(base) + timedelta(days=dependency.lag_days)


def _has_path(db: Session, start_entry_id: str, target_entry_id: str) -> bool:
    edges = db.scalars(
        select(CalendarDependency).where(CalendarDependency.active.is_(True))
    ).all()
    graph: dict[str, list[str]] = {}
    for edge in edges:
        graph.setdefault(edge.predecessor_entry_id, []).append(edge.successor_entry_id)
    stack = [start_entry_id]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current == target_entry_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(graph.get(current, []))
    return False


def add_dependency(
    db: Session,
    payload: CalendarDependencyIn,
    *,
    actor: str,
) -> CalendarDependency:
    predecessor = get_entry(db, payload.predecessor_entry_id)
    successor = get_entry(db, payload.successor_entry_id)
    if predecessor.project_id != successor.project_id:
        raise ValueError("Függőség csak azonos projekten belüli naptárelemek között hozható létre.")
    if predecessor.entry_id == successor.entry_id:
        raise ValueError("Egy naptárelem nem függhet saját magától.")
    if _has_path(db, successor.entry_id, predecessor.entry_id):
        raise ValueError("A függőség ciklust hozna létre az ütemtervben.")
    minimum = _dependency_minimum_start(
        CalendarDependency(
            dependency_type=payload.dependency_type,
            lag_days=payload.lag_days,
        ),
        predecessor,
    )
    comparison = successor.ends_at if payload.dependency_type == "finish_to_finish" else successor.starts_at
    if _aware(comparison) < minimum:
        raise ValueError("A jelenlegi dátumok megsértik a megadott ütemezési függőséget.")
    row = CalendarDependency(
        dependency_id=f"DEP-{uuid.uuid4().hex[:12].upper()}",
        predecessor_entry_id=predecessor.entry_id,
        successor_entry_id=successor.entry_id,
        dependency_type=payload.dependency_type,
        lag_days=payload.lag_days,
        created_by=actor,
    )
    db.add(row)
    audit(
        db,
        actor=actor,
        action="calendar_dependency_created",
        entity_type="calendar_dependency",
        entity_id=row.dependency_id,
        after=payload.model_dump(),
    )
    db.commit()
    db.refresh(row)
    return row


def _schedule_violations_for_window(
    db: Session,
    row: CalendarEntry,
    starts_at: datetime,
    ends_at: datetime,
) -> list[str]:
    predecessor_edges, successor_edges = _dependency_rows(db, row.entry_id)
    violations: list[str] = []
    for edge in predecessor_edges:
        predecessor = get_entry(db, edge.predecessor_entry_id)
        minimum = _dependency_minimum_start(edge, predecessor)
        comparison = ends_at if edge.dependency_type == "finish_to_finish" else starts_at
        if _aware(comparison) < minimum:
            violations.append(
                f"{predecessor.entry_id} → {row.entry_id}: {edge.dependency_type} + {edge.lag_days} nap"
            )
    for edge in successor_edges:
        successor = get_entry(db, edge.successor_entry_id)
        base = starts_at if edge.dependency_type == "start_to_start" else ends_at
        minimum = _aware(base) + timedelta(days=edge.lag_days)
        comparison = successor.ends_at if edge.dependency_type == "finish_to_finish" else successor.starts_at
        if _aware(comparison) < minimum:
            violations.append(
                f"{row.entry_id} → {successor.entry_id}: {edge.dependency_type} + {edge.lag_days} nap"
            )
    return violations


def _apply_reschedule(
    db: Session,
    row: CalendarEntry,
    *,
    starts_at: datetime,
    ends_at: datetime,
    reason: str,
    conflict_override_reason: str | None,
    actor: str,
    contractual_approval_id: str | None = None,
) -> CalendarEntry:
    _validate_window(starts_at, ends_at)
    conflicts = detect_resource_conflicts(
        db,
        starts_at=starts_at,
        ends_at=ends_at,
        assignee=row.assignee,
        participants=_participants(row),
        capacity_hours=Decimal(str(row.capacity_hours or 0)),
        exclude_entry_id=row.entry_id,
    )
    if conflicts and not (conflict_override_reason or "").strip():
        raise ValueError(
            "Az új időpont erőforrás- vagy kapacitásütközést okoz; felülbírálási indok szükséges."
        )
    dependency_violations = _schedule_violations_for_window(db, row, starts_at, ends_at)
    if dependency_violations:
        raise ValueError("Az átütemezés függőséget sért: " + "; ".join(dependency_violations))
    old_start = row.starts_at
    old_end = row.ends_at
    row.starts_at = starts_at
    row.ends_at = ends_at
    row.conflict_override_reason = conflict_override_reason or None
    row.version += 1
    row.updated_by = actor
    row.updated_at = utcnow()
    if row.linked_task_id:
        task = db.scalar(select(TaskRecord).where(TaskRecord.task_id == row.linked_task_id))
        if task:
            task.due_at = ends_at
            task.updated_at = utcnow()
    audit(
        db,
        actor=actor,
        action="calendar_entry_rescheduled",
        entity_type="calendar_entry",
        entity_id=row.entry_id,
        before={"starts_at": old_start, "ends_at": old_end},
        after={
            "starts_at": starts_at,
            "ends_at": ends_at,
            "reason": reason,
            "contractual_approval_id": contractual_approval_id,
            "conflicts": conflicts,
        },
    )
    delay_days = max(0, (_aware(ends_at).date() - _aware(old_end).date()).days)
    event_type = "MILESTONE_DELAYED" if delay_days else "CALENDAR_ENTRY_RESCHEDULED"
    _emit(
        db,
        row,
        event_type,
        actor=actor,
        summary=f"{row.title} átütemezve. Indok: {reason}",
        severity="high" if delay_days and row.entry_type in {"milestone", "deadline"} else "info",
        deadline_impact_days=delay_days,
    )
    db.refresh(row)
    return row


def reschedule_entry(
    db: Session,
    entry_id: str,
    payload: CalendarRescheduleIn,
    *,
    actor: str,
) -> CalendarEntry:
    row = get_entry_for_update(db, entry_id)
    _check_expected_version(row, payload.expected_version)
    if row.status in COMPLETED_STATUSES:
        raise ValueError("Lezárt vagy törölt naptárelem nem ütemezhető át.")
    if row.contractual_deadline:
        raise ValueError(
            "Szerződéses határidő csak jóváhagyott változáskérelemmel módosítható."
        )
    return _apply_reschedule(
        db,
        row,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        reason=payload.reason,
        conflict_override_reason=payload.conflict_override_reason,
        actor=actor,
    )


def request_contractual_change(
    db: Session,
    entry_id: str,
    payload: CalendarChangeRequestIn,
    *,
    actor: str,
) -> CalendarChangeRequest:
    row = get_entry_for_update(db, entry_id)
    _check_expected_version(row, payload.expected_version)
    if not row.contractual_deadline:
        raise ValueError("Változáskérelem csak szerződéses határidőhöz szükséges.")
    if row.status in COMPLETED_STATUSES:
        raise ValueError("Lezárt vagy törölt határidő nem módosítható.")
    _validate_window(payload.starts_at, payload.ends_at)
    pending = db.scalar(
        select(CalendarChangeRequest).where(
            CalendarChangeRequest.entry_id == entry_id,
            CalendarChangeRequest.status == "pending",
        )
    )
    if pending:
        raise ValueError("Ehhez a határidőhöz már van nyitott változáskérelem.")
    change = CalendarChangeRequest(
        request_id=f"CCR-{uuid.uuid4().hex[:12].upper()}",
        entry_id=entry_id,
        requested_starts_at=payload.starts_at,
        requested_ends_at=payload.ends_at,
        reason=payload.reason,
        impact_summary=payload.impact_summary,
        requested_by=actor,
    )
    db.add(change)
    audit(
        db,
        actor=actor,
        action="calendar_contractual_change_requested",
        entity_type="calendar_change_request",
        entity_id=change.request_id,
        after=payload.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(change)
    return change


def decide_contractual_change(
    db: Session,
    request_id: str,
    *,
    decision: str,
    note: str,
    conflict_override_reason: str | None,
    expected_entry_version: int | None = None,
    actor: str,
) -> CalendarChangeRequest:
    change = db.scalar(
        select(CalendarChangeRequest)
        .where(CalendarChangeRequest.request_id == request_id)
        .with_for_update()
    )
    if not change:
        raise KeyError(request_id)
    if change.status != "pending":
        raise ValueError("A változáskérelmet már elbírálták.")
    if decision not in {"approved", "rejected"}:
        raise ValueError("Érvénytelen döntés.")
    row = get_entry_for_update(db, change.entry_id)
    _check_expected_version(row, expected_entry_version)
    change.status = decision
    change.decided_by = actor
    change.decision_note = note
    change.decided_at = utcnow()
    audit(
        db,
        actor=actor,
        action=f"calendar_contractual_change_{decision}",
        entity_type="calendar_change_request",
        entity_id=change.request_id,
        after={"note": note, "entry_id": row.entry_id},
    )
    if decision == "approved":
        _apply_reschedule(
            db,
            row,
            starts_at=change.requested_starts_at,
            ends_at=change.requested_ends_at,
            reason=change.reason,
            conflict_override_reason=conflict_override_reason,
            actor=actor,
            contractual_approval_id=change.request_id,
        )
    else:
        db.commit()
    db.refresh(change)
    return change


def update_entry_status(
    db: Session,
    entry_id: str,
    *,
    status: str,
    note: str | None,
    expected_version: int | None = None,
    actor: str,
) -> CalendarEntry:
    row = get_entry_for_update(db, entry_id)
    _check_expected_version(row, expected_version)
    allowed = {
        "planned": {"confirmed", "cancelled"},
        "confirmed": {"in_progress", "completed", "cancelled"},
        "in_progress": {"completed", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    }
    if status not in allowed.get(row.status, set()):
        raise ValueError(f"A(z) {row.status} állapotból nem váltható {status} állapotba.")
    if status in {"completed", "cancelled"} and len((note or "").strip()) < 10:
        raise ValueError(
            "Lezáráshoz vagy törléshez legalább 10 karakteres, ellenőrizhető indok szükséges."
        )
    if status in {"in_progress", "completed"}:
        predecessor_edges, _ = _dependency_rows(db, row.entry_id)
        open_predecessors = [
            edge.predecessor_entry_id
            for edge in predecessor_edges
            if get_entry(db, edge.predecessor_entry_id).status != "completed"
        ]
        if open_predecessors:
            raise ValueError(
                "A műveletet nyitott előfeltételek blokkolják: " + ", ".join(open_predecessors)
            )
    before = row.status
    row.status = status
    row.version += 1
    row.updated_by = actor
    row.updated_at = utcnow()
    if row.linked_task_id:
        task = db.scalar(select(TaskRecord).where(TaskRecord.task_id == row.linked_task_id))
        if task:
            task.status = "done" if status == "completed" else "cancelled" if status == "cancelled" else "in_progress" if status == "in_progress" else task.status
            task.updated_at = utcnow()
    audit(
        db,
        actor=actor,
        action=f"calendar_entry_{status}",
        entity_type="calendar_entry",
        entity_id=row.entry_id,
        before={"status": before},
        after={"status": status, "note": note},
    )
    _emit(
        db,
        row,
        "CALENDAR_ENTRY_COMPLETED" if status == "completed" else "CALENDAR_ENTRY_STATUS_CHANGED",
        actor=actor,
        summary=f"{row.title}: {status}. {note or ''}".strip(),
    )
    db.refresh(row)
    return row


def serialize_entry(row: CalendarEntry) -> dict[str, Any]:
    return {
        "entry_id": row.entry_id,
        "project_id": row.project_id,
        "entry_type": row.entry_type,
        "title": row.title,
        "description": row.description,
        "starts_at": row.starts_at,
        "ends_at": row.ends_at,
        "all_day": row.all_day,
        "assignee": row.assignee,
        "participants": _participants(row),
        "location": row.location,
        "status": row.status,
        "priority": row.priority,
        "source_module": row.source_module,
        "source_object_id": row.source_object_id,
        "linked_task_id": row.linked_task_id,
        "contractual_deadline": row.contractual_deadline,
        "capacity_hours": Decimal(str(row.capacity_hours or 0)),
        "conflict_override_reason": row.conflict_override_reason,
        "version": row.version,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def synchronize_schedule_sources(
    db: Session, *, actor: str, project_ids: set[str] | None = None
) -> dict[str, int]:
    """Project existing operational plans and task cards into the canonical calendar.

    The projection is deliberately create-only. Once a calendar entry exists, its
    audited schedule is never overwritten by a background synchronization.
    """

    existing_keys = {
        (row.source_module, row.source_object_id)
        for row in db.scalars(
            select(CalendarEntry).where(CalendarEntry.source_object_id.is_not(None))
        ).all()
    }
    created = skipped = 0

    def add_projection(
        *,
        project_id: str,
        entry_type: str,
        title: str,
        description: str | None,
        starts_at: datetime,
        ends_at: datetime,
        assignee: str | None,
        status: str,
        priority: str,
        source_module: str,
        source_object_id: str,
        linked_task_id: str | None = None,
        contractual_deadline: bool = False,
    ) -> None:
        nonlocal created, skipped
        key = (source_module, source_object_id)
        if key in existing_keys:
            skipped += 1
            return
        safe_end = ends_at if _aware(ends_at) > _aware(starts_at) else starts_at + timedelta(hours=1)
        db.add(
            CalendarEntry(
                entry_id=f"CAL-{uuid.uuid4().hex[:12].upper()}",
                project_id=project_id,
                entry_type=entry_type,
                title=title,
                description=description,
                starts_at=starts_at,
                ends_at=safe_end,
                assignee=assignee,
                participants_json="[]",
                status=status,
                priority=priority,
                source_module=source_module,
                source_object_id=source_object_id,
                linked_task_id=linked_task_id,
                contractual_deadline=contractual_deadline,
                capacity_hours=Decimal("0"),
                created_by=actor,
                updated_by=actor,
            )
        )
        existing_keys.add(key)
        created += 1

    phase_query = select(PMPhase).where(
        PMPhase.planned_start.is_not(None), PMPhase.planned_end.is_not(None)
    )
    package_query = select(PMWorkPackage).where(
        PMWorkPackage.planned_start.is_not(None), PMWorkPackage.planned_end.is_not(None)
    )
    task_query = select(TaskRecord).where(TaskRecord.due_at.is_not(None))
    if project_ids is not None:
        scoped_ids = project_ids or {"-"}
        phase_query = phase_query.where(PMPhase.project_id.in_(scoped_ids))
        package_query = package_query.where(PMWorkPackage.project_id.in_(scoped_ids))
        task_query = task_query.where(TaskRecord.project_id.in_(scoped_ids))

    for phase in db.scalars(
        phase_query
    ).all():
        if phase.planned_start is None or phase.planned_end is None:
            continue
        add_projection(
            project_id=phase.project_id,
            entry_type="milestone",
            title=f"Projektfázis: {phase.name}",
            description=f"Készültség: {phase.progress_pct}% · readiness: {phase.readiness_status}",
            starts_at=phase.planned_start,
            ends_at=phase.planned_end,
            assignee=phase.owner,
            status="completed" if phase.status == "done" else "in_progress" if phase.status == "in_progress" else "planned",
            priority="high" if phase.readiness_status == "at_risk" else "normal",
            source_module="operations-workspace",
            source_object_id=phase.phase_id,
        )

    for package in db.scalars(package_query).all():
        if package.planned_start is None or package.planned_end is None:
            continue
        add_projection(
            project_id=package.project_id,
            entry_type="task",
            title=f"Munkacsomag: {package.name}",
            description=package.block_reason or package.next_action,
            starts_at=package.planned_start,
            ends_at=package.planned_end,
            assignee=package.assignee,
            status="completed" if package.status == "done" else "in_progress" if package.status == "in_progress" else "planned",
            priority="critical" if package.blocked else "normal",
            source_module="operations-workspace",
            source_object_id=package.work_package_id,
        )

    for task in db.scalars(task_query).all():
        if task.due_at is None:
            continue
        add_projection(
            project_id=task.project_id,
            entry_type="deadline" if task.executive_relevance else "task",
            title=task.title,
            description=task.description,
            starts_at=task.due_at - timedelta(hours=1),
            ends_at=task.due_at,
            assignee=task.assignee,
            status="completed" if task.status == "done" else "cancelled" if task.status == "cancelled" else "in_progress" if task.status == "in_progress" else "planned",
            priority=task.priority,
            source_module="workflow-center",
            source_object_id=task.task_id,
            linked_task_id=task.task_id,
            contractual_deadline=task.executive_relevance,
        )

    if created:
        audit(
            db,
            actor=actor,
            action="calendar_sources_synchronized",
            entity_type="smart_calendar",
            entity_id="canonical-schedule",
            after={"created": created, "skipped": skipped},
        )
    db.commit()
    return {"created": created, "skipped": skipped}


def calendar_portfolio(
    db: Session,
    *,
    project_id: str | None = None,
    assignee: str | None = None,
    project_ids: set[str] | None = None,
    status: str | None = None,
    entry_type: str | None = None,
    query_text: str | None = None,
    starts_from: datetime | None = None,
    starts_until: datetime | None = None,
    days: int = 42,
) -> dict[str, Any]:
    query = select(CalendarEntry)
    if project_ids is not None:
        query = query.where(CalendarEntry.project_id.in_(project_ids or {"-"}))
    if project_id:
        query = query.where(CalendarEntry.project_id == project_id)
    if assignee:
        query = query.where(
            or_(CalendarEntry.assignee == assignee, CalendarEntry.assignee.is_(None))
        )
    if status:
        query = query.where(CalendarEntry.status == status)
    if entry_type:
        query = query.where(CalendarEntry.entry_type == entry_type)
    if query_text:
        needle = f"%{query_text.strip().casefold()}%"
        query = query.where(
            or_(
                func.lower(CalendarEntry.title).like(needle),
                func.lower(func.coalesce(CalendarEntry.description, "")).like(needle),
                func.lower(CalendarEntry.project_id).like(needle),
            )
        )
    if starts_from:
        query = query.where(CalendarEntry.ends_at >= starts_from)
    if starts_until:
        query = query.where(CalendarEntry.starts_at <= starts_until)
    rows = list(db.scalars(query.order_by(CalendarEntry.starts_at, CalendarEntry.title)).all())
    now = utcnow()
    horizon = now + timedelta(days=days)
    active = [row for row in rows if row.status in ACTIVE_STATUSES]
    upcoming = [
        row for row in active if now.date() <= _aware(row.starts_at).date() <= horizon.date()
    ]
    overdue = [
        row for row in active if _aware(row.ends_at) < now and row.entry_type != "meeting"
    ]
    conflicts: list[dict[str, Any]] = []
    for index, row in enumerate(active):
        row_people = _entry_people(row.assignee, _participants(row))
        for other in active[index + 1 :]:
            shared = row_people & _entry_people(other.assignee, _participants(other))
            if shared and _overlaps(row.starts_at, row.ends_at, other.starts_at, other.ends_at):
                conflicts.append(
                    {
                        "left": row,
                        "right": other,
                        "people": sorted(shared),
                    }
                )
    dependency_query = select(CalendarDependency).where(CalendarDependency.active.is_(True))
    if project_id or assignee or project_ids is not None:
        visible_entry_ids = [row.entry_id for row in rows]
        dependency_query = dependency_query.where(
            CalendarDependency.predecessor_entry_id.in_(visible_entry_ids or ["-"]),
            CalendarDependency.successor_entry_id.in_(visible_entry_ids or ["-"]),
        )
    dependencies = list(
        db.scalars(dependency_query.order_by(CalendarDependency.created_at)).all()
    )
    dependency_violations: list[dict[str, Any]] = []
    row_map = {row.entry_id: row for row in rows}
    for edge in dependencies:
        predecessor = row_map.get(edge.predecessor_entry_id) or db.scalar(
            select(CalendarEntry).where(CalendarEntry.entry_id == edge.predecessor_entry_id)
        )
        successor = row_map.get(edge.successor_entry_id) or db.scalar(
            select(CalendarEntry).where(CalendarEntry.entry_id == edge.successor_entry_id)
        )
        if not predecessor or not successor:
            continue
        minimum = _dependency_minimum_start(edge, predecessor)
        comparison = successor.ends_at if edge.dependency_type == "finish_to_finish" else successor.starts_at
        if _aware(comparison) < minimum:
            dependency_violations.append(
                {"dependency": edge, "predecessor": predecessor, "successor": successor}
            )
    change_query = select(CalendarChangeRequest).where(
        CalendarChangeRequest.status == "pending"
    )
    if project_id or project_ids is not None:
        project_entries = [row.entry_id for row in rows]
        change_query = change_query.where(CalendarChangeRequest.entry_id.in_(project_entries or ["-"]))
    pending_changes = list(
        db.scalars(change_query.order_by(desc(CalendarChangeRequest.requested_at))).all()
    )
    days_map: dict[Any, list[CalendarEntry]] = {}
    for row in upcoming:
        days_map.setdefault(_aware(row.starts_at).date(), []).append(row)
    return {
        "entries": rows,
        "active_entries": active,
        "upcoming": upcoming,
        "calendar_days": [
            {"date": date_value, "entries": day_rows}
            for date_value, day_rows in sorted(days_map.items())
        ],
        "overdue": overdue,
        "conflicts": conflicts,
        "dependencies": dependencies,
        "dependency_violations": dependency_violations,
        "pending_changes": pending_changes,
        "entry_map": row_map,
        "metrics": {
            "active": len(active),
            "milestones": sum(1 for row in active if row.entry_type in {"milestone", "deadline"}),
            "overdue": len(overdue),
            "conflicts": len(conflicts),
            "dependency_violations": len(dependency_violations),
            "pending_changes": len(pending_changes),
        },
    }
