import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    EventRecord,
    ModuleInboxDelivery,
    OutboxMessage,
    ProjectObjectState,
    ProjectRegistry,
    TaskRecord,
)
from app.services.catalog import EVENT_CATALOG
from app.services.integration import DESTINATION_ALIASES, process_outbox


def event_payload(**overrides):
    token = uuid.uuid4().hex[:8]
    data = {
        "event_id": f"EVT-{token}",
        "dedupe_key": f"TEST-{token}",
        "project_id": "PRJ-001",
        "source_module": "procurement",
        "event_type": "DELIVERY_NOTE_MISSING",
        "object_type": "Delivery",
        "object_id": "DEL-001",
        "financial_impact_huf": "2500000",
        "payload": {"project_name": "Teszt projekt", "summary": "Szállítólevél hiányzik"},
    }
    data.update(overrides)
    return data


def test_event_ingestion_is_idempotent(client, db):
    data = event_payload()
    first = client.post("/api/events", json=data)
    second = client.post("/api/events", json=data)
    assert first.status_code == 200 and first.json()["created"] is True
    assert second.status_code == 200 and second.json()["created"] is False
    assert len(db.scalars(select(EventRecord)).all()) == 1


def test_event_creates_project_task_object_and_outbox(client, db):
    response = client.post("/api/events", json=event_payload())
    assert response.json()["severity"] == "critical"
    db.expire_all()
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == "PRJ-001"))
    assert project is not None and project.blocked is True and project.risk_level == "critical"
    assert Decimal(str(project.financial_impact_huf)) == Decimal("2500000")
    assert db.scalar(select(TaskRecord).where(TaskRecord.project_id == "PRJ-001")) is not None
    assert (
        db.scalar(select(ProjectObjectState).where(ProjectObjectState.object_id == "DEL-001"))
        is not None
    )
    assert (
        db.scalar(select(OutboxMessage).where(OutboxMessage.destination_module == "finance"))
        is not None
    )


def test_heartbeat_updates_module(client, db):
    response = client.post(
        "/api/heartbeats",
        json={"module_key": "procurement", "version": "1.0.1", "status": "healthy"},
    )
    assert response.status_code == 200
    db.expire_all()
    from app.models import ModuleRegistry

    module = db.scalar(select(ModuleRegistry).where(ModuleRegistry.module_key == "procurement"))
    assert module.version == "1.0.1"
    assert module.integration_status == "healthy"


def test_every_catalog_route_resolves_to_a_registered_module(db):
    from app.models import ModuleRegistry

    registered = set(db.scalars(select(ModuleRegistry.module_key)).all())
    routed = {
        destination
        for definition in EVENT_CATALOG.values()
        for destination in definition.default_route_to
    }
    unresolved = {
        destination
        for destination in routed
        if DESTINATION_ALIASES.get(destination, destination) not in registered
    }
    assert unresolved == set()


def test_unknown_outbox_destination_retries_then_dead_letters(db):
    db.add(
        OutboxMessage(
            message_id="MSG-UNKNOWN-DESTINATION",
            destination_module="not-a-registered-module",
            payload_json='{"event":"TEST"}',
            status="pending",
            max_retries=5,
        )
    )
    db.commit()
    for _ in range(5):
        process_outbox(db)
        for msg in db.scalars(select(OutboxMessage)).all():
            msg.next_attempt_at = None
        db.commit()
    db.expire_all()
    message = db.scalar(
        select(OutboxMessage).where(OutboxMessage.message_id == "MSG-UNKNOWN-DESTINATION")
    )
    assert message.status == "dead_letter"
    assert message.retry_count == 5
    assert message.last_error.startswith("UNKNOWN_DESTINATION_MODULE")
    assert (
        db.scalar(
            select(ModuleInboxDelivery).where(
                ModuleInboxDelivery.message_id == "MSG-UNKNOWN-DESTINATION"
            )
        )
        is None
    )


def test_unknown_informational_event_does_not_force_task(client, db):
    data = event_payload(
        event_type="CUSTOM_INFORMATION",
        source_module="crm",
        severity="info",
        next_action=None,
        executive_relevance=False,
    )
    response = client.post("/api/events", json=data)
    assert response.status_code == 200
    db.expire_all()
    assert (
        db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == data["event_id"])) is None
    )


def test_outbox_successful_delivery_has_durable_receipt_and_alias(client, db):
    client.post(
        "/api/events",
        json=event_payload(event_type="SCHEDULE_APPROVED", source_module="project_control"),
    )
    result = client.post("/api/outbox/process").json()
    assert result["sent"] >= 1
    db.expire_all()
    assert all(m.status == "sent" for m in db.scalars(select(OutboxMessage)).all())
    messages = db.scalars(select(OutboxMessage)).all()
    receipts = db.scalars(select(ModuleInboxDelivery)).all()
    assert len(receipts) == len(messages)
    assert {receipt.destination_module for receipt in receipts} == {
        "smart-calendar",
        "finance-intelligence",
        "procurement",
    }
    assert all(message.payload_sha256 for message in messages)
    assert all(message.delivery_mode == "internal_inbox" for message in messages)
    assert all(message.delivery_receipt_json for message in messages)
    assert all(message.delivered_at for message in messages)


def test_internal_delivery_is_idempotent_and_rejects_simulated_success(client, db):
    client.post(
        "/api/events",
        json=event_payload(event_type="DELIVERY_NOTE_MISSING", source_module="procurement"),
    )
    first = process_outbox(db)
    assert first["sent"] == 1
    message = db.scalar(select(OutboxMessage))
    receipt = db.scalar(select(ModuleInboxDelivery))
    message.status = "retry"
    message.next_attempt_at = None
    db.commit()

    second = process_outbox(db)
    assert second["sent"] == 1
    assert second["idempotent"] == 1
    assert db.scalar(select(ModuleInboxDelivery)).delivery_id == receipt.delivery_id
    assert len(db.scalars(select(ModuleInboxDelivery)).all()) == 1
    with pytest.raises(ValueError, match="szimulált outbox-siker"):
        process_outbox(db, simulate_success=True)


def test_outbox_rejects_non_object_payload(db):
    db.add(
        OutboxMessage(
            message_id="MSG-INVALID-PAYLOAD",
            destination_module="crm",
            payload_json='["not", "an", "object"]',
            status="pending",
        )
    )
    db.commit()
    result = process_outbox(db)
    assert result["dead_letter"] == 1
    message = db.scalar(
        select(OutboxMessage).where(OutboxMessage.message_id == "MSG-INVALID-PAYLOAD")
    )
    assert message.status == "dead_letter"
    assert message.last_error.startswith("SECURITY_GATE_BLOCKED")
