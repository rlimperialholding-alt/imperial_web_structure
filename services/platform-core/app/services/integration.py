from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    EventRecord,
    ModuleRegistry,
    OutboxMessage,
    ProjectObjectState,
    ProjectRegistry,
    TaskRecord,
)
from ..schemas import EventIn, HeartbeatIn
from .catalog import get_event_definition
from .content_quality import validate_publication_adapter_envelope


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_project(db: Session, project_id: str, payload: dict) -> ProjectRegistry:
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if not project:
        project = ProjectRegistry(
            project_id=project_id,
            name=str(payload.get("project_name") or project_id),
            customer_name=payload.get("customer_name"),
            project_type=payload.get("project_type"),
            responsible=payload.get("responsible"),
        )
        db.add(project)
        db.flush()
    return project


def update_project_risk(project: ProjectRegistry, event: EventRecord) -> None:
    rank = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    color = {0: "green", 1: "green", 2: "yellow", 3: "red", 4: "critical"}
    current_rank = {"green": 0, "yellow": 2, "red": 3, "critical": 4}.get(project.risk_level, 0)
    event_rank = rank.get(event.severity, 0)
    if event.status == "open" and event_rank >= current_rank:
        project.risk_level = color[event_rank]
    if event.severity in {"high", "critical"} and event.status == "open":
        project.blocked = event.event_type in {
            "PAYMENT_BLOCKED",
            "DELIVERY_NOTE_MISSING",
            "QUALITY_VARIANCE_DETECTED",
            "PERFORMANCE_DECLARATION_MISSING",
            "PROJECT_MARGIN_AT_RISK",
            "MODULE_HEALTH_FAILED",
        }
    project.financial_impact_huf = Decimal(str(project.financial_impact_huf or 0)) + abs(
        Decimal(str(event.financial_impact_huf or 0))
    )
    project.deadline_impact_days = max(
        project.deadline_impact_days or 0, event.deadline_impact_days or 0
    )
    if event.next_action:
        project.next_action = event.next_action
    if event.responsible:
        project.responsible = event.responsible


def ingest_event(db: Session, event_in: EventIn, *, actor: str = "api") -> tuple[EventRecord, bool]:
    existing = db.scalar(select(EventRecord).where(EventRecord.dedupe_key == event_in.dedupe_key))
    if existing:
        return existing, False

    definition = get_event_definition(event_in.event_type)
    severity = event_in.severity if event_in.severity != "info" else definition.default_severity
    exec_relevance = event_in.executive_relevance or definition.executive_relevance
    next_action = event_in.next_action or (
        definition.task_title if definition.create_task else None
    )
    occurred_at = event_in.occurred_at or utcnow()

    project = ensure_project(db, event_in.project_id, event_in.payload)
    record = EventRecord(
        event_id=event_in.event_id,
        dedupe_key=event_in.dedupe_key,
        project_id=event_in.project_id,
        source_module=event_in.source_module,
        event_type=event_in.event_type,
        object_type=event_in.object_type,
        object_id=event_in.object_id,
        severity=severity,
        status=event_in.status,
        financial_impact_huf=event_in.financial_impact_huf,
        deadline_impact_days=event_in.deadline_impact_days,
        responsible=event_in.responsible,
        next_action=next_action,
        executive_relevance=exec_relevance,
        evidence_url=event_in.evidence_url,
        payload_json=json.dumps(event_in.payload, ensure_ascii=False, default=str),
        occurred_at=occurred_at,
    )
    db.add(record)
    db.flush()

    if event_in.object_type and event_in.object_id:
        state = db.scalar(
            select(ProjectObjectState).where(
                ProjectObjectState.project_id == event_in.project_id,
                ProjectObjectState.source_module == event_in.source_module,
                ProjectObjectState.object_type == event_in.object_type,
                ProjectObjectState.object_id == event_in.object_id,
            )
        )
        if not state:
            state = ProjectObjectState(
                project_id=event_in.project_id,
                source_module=event_in.source_module,
                object_type=event_in.object_type,
                object_id=event_in.object_id,
                status=event_in.status,
            )
            db.add(state)
        state.status = event_in.status
        state.summary = event_in.payload.get("summary") or next_action
        state.payload_json = json.dumps(event_in.payload, ensure_ascii=False, default=str)
        state.last_event_id = event_in.event_id

    if definition.create_task or next_action:
        task = TaskRecord(
            task_id=f"TASK-{uuid.uuid4().hex[:12].upper()}",
            project_id=event_in.project_id,
            source_event_id=event_in.event_id,
            title=definition.task_title or next_action or event_in.event_type,
            description=event_in.payload.get("summary") or next_action,
            assignee=event_in.responsible,
            due_at=utcnow() + timedelta(days=1 if severity == "critical" else 3),
            priority="critical"
            if severity == "critical"
            else "high"
            if severity == "high"
            else "normal",
            executive_relevance=exec_relevance,
        )
        db.add(task)

    routes = list(dict.fromkeys([*definition.default_route_to, *event_in.route_to]))
    for destination in routes:
        if destination == event_in.source_module:
            continue
        db.add(
            OutboxMessage(
                message_id=f"MSG-{uuid.uuid4().hex[:12].upper()}",
                source_event_id=event_in.event_id,
                destination_module=destination,
                payload_json=json.dumps(event_in.model_dump(mode="json"), ensure_ascii=False),
                status="pending",
                next_attempt_at=utcnow(),
            )
        )

    update_project_risk(project, record)
    audit(
        db,
        actor=actor,
        action="event_ingested",
        entity_type="event",
        entity_id=record.event_id,
        after=event_in.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(record)
    return record, True


def register_heartbeat(
    db: Session, heartbeat: HeartbeatIn, *, actor: str = "api"
) -> ModuleRegistry:
    module = db.scalar(
        select(ModuleRegistry).where(ModuleRegistry.module_key == heartbeat.module_key)
    )
    if not module:
        module = ModuleRegistry(
            module_key=heartbeat.module_key, name=heartbeat.module_key.replace("_", " ").title()
        )
        db.add(module)
    module.version = heartbeat.version
    module.last_heartbeat_at = utcnow()
    module.integration_status = "healthy" if heartbeat.status == "healthy" else "degraded"
    if heartbeat.status == "healthy" and module.lifecycle_status == "registered":
        module.lifecycle_status = "pilot"
    audit(
        db,
        actor=actor,
        action="heartbeat",
        entity_type="module",
        entity_id=heartbeat.module_key,
        after=heartbeat.model_dump(),
    )
    db.commit()
    db.refresh(module)
    return module


def process_outbox(
    db: Session, *, limit: int = 100, simulate_success: bool = True
) -> dict[str, int]:
    now = utcnow()
    messages = db.scalars(
        select(OutboxMessage)
        .where(
            OutboxMessage.status.in_(["pending", "retry"]),
            (OutboxMessage.next_attempt_at.is_(None)) | (OutboxMessage.next_attempt_at <= now),
        )
        .order_by(OutboxMessage.id)
        .limit(limit)
    ).all()
    sent = retried = dead = 0
    for message in messages:
        if message.destination_module == "publication-adapter":
            try:
                payload = json.loads(message.payload_json)
                validation = validate_publication_adapter_envelope(db, payload)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                message.status = "dead_letter"
                message.last_error = f"SECURITY_GATE_BLOCKED: {exc}"
                dead += 1
                audit(
                    db,
                    actor="publication-adapter-gate",
                    action="publication_adapter_message_blocked",
                    entity_type="outbox_message",
                    entity_id=message.message_id,
                    after={
                        "destination_module": message.destination_module,
                        "reason": str(exc),
                    },
                )
                continue
            audit(
                db,
                actor="publication-adapter-gate",
                action="publication_adapter_envelope_validated",
                entity_type="outbox_message",
                entity_id=message.message_id,
                after=validation,
            )
        if simulate_success:
            message.status = "sent"
            message.last_error = None
            sent += 1
        else:
            message.retry_count += 1
            message.last_error = "Szimulált célrendszeri hiba"
            if message.retry_count >= message.max_retries:
                message.status = "dead_letter"
                dead += 1
            else:
                message.status = "retry"
                message.next_attempt_at = now + timedelta(minutes=2 ** min(message.retry_count, 8))
                retried += 1
    db.commit()
    return {"processed": len(messages), "sent": sent, "retried": retried, "dead_letter": dead}
