from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    EventRecord,
    ModuleInboxDelivery,
    ModuleRegistry,
    OutboxMessage,
    ProjectObjectState,
    ProjectRegistry,
    TaskRecord,
)
from ..schemas import EventIn, HeartbeatIn
from .catalog import get_event_definition
from .content_quality import validate_publication_adapter_envelope
from .publication_delivery import stage_publication_deliveries

DESTINATION_ALIASES = {
    "analytics": "executive-dashboard",
    "calendar": "smart-calendar",
    "change_control": "change-control",
    "commercial_integration": "integration-control-room",
    "contract_generator": "contract-generator",
    "control_center": "control-center",
    "field_pwa": "field-pwa",
    "finance": "finance-intelligence",
    "imperial_care": "imperial-care",
    "import_center": "import-center",
    "myimperial": "my-imperial",
    "operations_workspace": "operations-workspace",
    "partner_connect": "partner-connect",
    "project_control": "pm-cockpit",
    "tender_mail": "tendermail",
}
EXTERNAL_ADAPTER_DESTINATIONS = {"email-notification"}


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


def _canonical_payload(message: OutboxMessage) -> tuple[dict, str, str]:
    payload = json.loads(message.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("Az outbox payload csak JSON objektum lehet.")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return payload, canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _schedule_retry(
    message: OutboxMessage, now: datetime, error: str, *, delivery_mode: str
) -> str:
    message.retry_count += 1
    message.last_error = error[:2000]
    message.delivery_mode = delivery_mode
    if message.retry_count >= max(1, message.max_retries):
        message.status = "dead_letter"
        message.next_attempt_at = None
        return "dead_letter"
    message.status = "retry"
    message.next_attempt_at = now + timedelta(minutes=2 ** min(message.retry_count, 8))
    return "retry"


def _deliver_internal(
    db: Session,
    message: OutboxMessage,
    *,
    destination: str,
    canonical_payload: str,
    payload_sha256: str,
    now: datetime,
) -> bool:
    existing = db.scalar(
        select(ModuleInboxDelivery).where(ModuleInboxDelivery.message_id == message.message_id)
    )
    idempotent = existing is not None
    if existing:
        if (
            existing.destination_module != destination
            or existing.payload_sha256 != payload_sha256
            or existing.payload_json != canonical_payload
        ):
            raise ValueError(
                "SECURITY_GATE_BLOCKED: az idempotencia-kulcshoz eltérő inbox tartalom tartozik."
            )
        delivery = existing
    else:
        delivery = ModuleInboxDelivery(
            delivery_id=f"INBOX-{uuid.uuid4().hex[:16].upper()}",
            message_id=message.message_id,
            source_event_id=message.source_event_id,
            requested_destination=message.destination_module,
            destination_module=destination,
            endpoint=message.endpoint,
            payload_json=canonical_payload,
            payload_sha256=payload_sha256,
            schema_version="1.0",
            status="received",
            received_at=now,
        )
        db.add(delivery)
        db.flush()
    receipt = {
        "delivery_id": delivery.delivery_id,
        "message_id": message.message_id,
        "requested_destination": message.destination_module,
        "destination_module": destination,
        "payload_sha256": payload_sha256,
        "received_at": delivery.received_at.isoformat(),
        "status": delivery.status,
    }
    message.payload_sha256 = payload_sha256
    message.delivery_mode = "internal_inbox"
    message.delivery_receipt_json = json.dumps(
        receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    message.delivered_at = delivery.received_at
    message.status = "sent"
    message.last_error = None
    message.next_attempt_at = None
    audit(
        db,
        actor="platform-outbox-worker",
        action="outbox_internal_delivery_received",
        entity_type="module_inbox_delivery",
        entity_id=delivery.delivery_id,
        after={**receipt, "idempotent": idempotent},
    )
    return idempotent


def process_outbox(
    db: Session, *, limit: int = 100, simulate_success: bool = False
) -> dict[str, int]:
    if simulate_success:
        raise ValueError(
            "A szimulált outbox-siker le van tiltva; csak bizonyított kézbesítés engedélyezett."
        )
    now = utcnow()
    messages = db.scalars(
        select(OutboxMessage)
        .where(
            OutboxMessage.status.in_(["pending", "retry"]),
            (OutboxMessage.next_attempt_at.is_(None)) | (OutboxMessage.next_attempt_at <= now),
        )
        .order_by(OutboxMessage.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    sent = retried = dead = staged = idempotent = 0
    for message in messages:
        if message.destination_module == "publication-adapter":
            try:
                payload = json.loads(message.payload_json)
                validation = validate_publication_adapter_envelope(db, payload)
                deliveries = stage_publication_deliveries(db, message, payload, validation)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                message.status = "dead_letter"
                message.last_error = f"SECURITY_GATE_BLOCKED: {exc}"
                message.next_attempt_at = None
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
            staged += len(deliveries)
            continue

        try:
            _payload, canonical_payload, payload_sha256 = _canonical_payload(message)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            message.status = "dead_letter"
            message.last_error = f"SECURITY_GATE_BLOCKED: {exc}"
            message.next_attempt_at = None
            dead += 1
            audit(
                db,
                actor="platform-outbox-worker",
                action="outbox_payload_blocked",
                entity_type="outbox_message",
                entity_id=message.message_id,
                after={"destination_module": message.destination_module, "reason": str(exc)},
            )
            continue

        destination = DESTINATION_ALIASES.get(
            message.destination_module, message.destination_module
        )
        module = db.scalar(select(ModuleRegistry).where(ModuleRegistry.module_key == destination))
        if module:
            try:
                was_idempotent = _deliver_internal(
                    db,
                    message,
                    destination=destination,
                    canonical_payload=canonical_payload,
                    payload_sha256=payload_sha256,
                    now=now,
                )
            except ValueError as exc:
                message.status = "dead_letter"
                message.last_error = str(exc)[:2000]
                message.next_attempt_at = None
                dead += 1
                audit(
                    db,
                    actor="platform-outbox-worker",
                    action="outbox_idempotency_conflict_blocked",
                    entity_type="outbox_message",
                    entity_id=message.message_id,
                    after={"destination_module": destination, "reason": str(exc)},
                )
                continue
            sent += 1
            idempotent += int(was_idempotent)
            continue

        external_adapter = (
            message.destination_module in EXTERNAL_ADAPTER_DESTINATIONS
            or message.destination_module.startswith("website-adapter:")
            or (message.endpoint or "").startswith(("http://", "https://"))
        )
        error = (
            "EXTERNAL_ADAPTER_REQUIRED: a célhoz nincs igazolt adapter-receipt."
            if external_adapter
            else f"UNKNOWN_DESTINATION_MODULE: {message.destination_module}"
        )
        delivery_mode = "external_adapter" if external_adapter else "unknown"
        outcome = _schedule_retry(message, now, error, delivery_mode=delivery_mode)
        retried += int(outcome == "retry")
        dead += int(outcome == "dead_letter")
        audit(
            db,
            actor="platform-outbox-worker",
            action="outbox_delivery_failed",
            entity_type="outbox_message",
            entity_id=message.message_id,
            after={
                "destination_module": message.destination_module,
                "delivery_mode": delivery_mode,
                "outcome": outcome,
                "reason": error,
            },
        )
    db.commit()
    return {
        "processed": len(messages),
        "sent": sent,
        "idempotent": idempotent,
        "staged": staged,
        "retried": retried,
        "dead_letter": dead,
    }
