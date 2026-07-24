import uuid
from decimal import Decimal

from sqlalchemy import select

from app.models import EventRecord, OutboxMessage, ProjectObjectState, ProjectRegistry, TaskRecord


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
    assert db.scalar(select(ProjectObjectState).where(ProjectObjectState.object_id == "DEL-001")) is not None
    assert db.scalar(select(OutboxMessage).where(OutboxMessage.destination_module == "finance")) is not None


def test_heartbeat_updates_module(client, db):
    response = client.post("/api/heartbeats", json={"module_key": "procurement", "version": "1.0.1", "status": "healthy"})
    assert response.status_code == 200
    db.expire_all()
    from app.models import ModuleRegistry
    module = db.scalar(select(ModuleRegistry).where(ModuleRegistry.module_key == "procurement"))
    assert module.version == "1.0.1"
    assert module.integration_status == "healthy"


def test_outbox_retry_and_dead_letter(client, db):
    data = event_payload(event_type="SCHEDULE_APPROVED", source_module="project_control")
    client.post("/api/events", json=data)
    for _ in range(5):
        result = client.post("/api/outbox/process?simulate_success=false").json()
        for msg in db.scalars(select(OutboxMessage)).all():
            msg.next_attempt_at = None
        db.commit()
    db.expire_all()
    statuses = {m.status for m in db.scalars(select(OutboxMessage)).all()}
    assert "dead_letter" in statuses


def test_unknown_informational_event_does_not_force_task(client, db):
    data = event_payload(event_type="CUSTOM_INFORMATION", source_module="crm", severity="info", next_action=None, executive_relevance=False)
    response = client.post("/api/events", json=data)
    assert response.status_code == 200
    db.expire_all()
    assert db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == data["event_id"])) is None


def test_outbox_successful_delivery(client, db):
    client.post("/api/events", json=event_payload(event_type="SCHEDULE_APPROVED", source_module="project_control"))
    result = client.post("/api/outbox/process?simulate_success=true").json()
    assert result["sent"] >= 1
    db.expire_all()
    assert all(m.status == "sent" for m in db.scalars(select(OutboxMessage)).all())
