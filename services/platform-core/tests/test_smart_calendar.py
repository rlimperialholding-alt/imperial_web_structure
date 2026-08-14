from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import (
    AuditLog,
    CalendarChangeRequest,
    CalendarDependency,
    CalendarEntry,
    EventRecord,
    ProjectRegistry,
    TaskRecord,
)

DEMO_PASSWORD = "Imperial2026!"
PROJECT_ID = "IMP-GOD-014"


def login(client, role: str) -> None:
    email = "owner@imperial.local" if role == "owner" else f"{role}@imperial.local"
    response = client.post(
        "/login",
        data={"email": email, "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    if role in {"project-manager", "owner"}:
        page = client.get("/smart-calendar")
        assert page.status_code == 200
        match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert match
        client.headers["x-csrf-token"] = match.group(1)


def window(days: int, hour: int = 8, duration_hours: int = 2) -> tuple[str, str]:
    start = (datetime.now(UTC) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return start.isoformat(), (start + timedelta(hours=duration_hours)).isoformat()


def ensure_project(db) -> None:
    db.add(
        ProjectRegistry(
            project_id=PROJECT_ID,
            name="Göd – éles projektütemezés",
            responsible="project-manager@imperial.local",
        )
    )
    db.commit()


def create_entry(client, *, title: str, days: int, **overrides):
    starts_at, ends_at = window(days, overrides.pop("hour", 8))
    payload = {
        "project_id": PROJECT_ID,
        "entry_type": "task",
        "title": title,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "assignee": "project-manager@imperial.local",
        "capacity_hours": "2",
        "create_task": True,
        **overrides,
    }
    return client.post("/api/smart-calendar/entries", json=payload)


def test_calendar_entry_creates_task_event_outbox_and_audit(client, db):
    ensure_project(db)
    login(client, "project-manager")
    created = create_entry(
        client,
        title="Alapozás műszaki átadása",
        days=8,
        entry_type="inspection",
        contractual_deadline=True,
        priority="critical",
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["entry_id"].startswith("CAL-")
    assert payload["linked_task_id"].startswith("TASK-")

    db.expire_all()
    row = db.scalar(select(CalendarEntry).where(CalendarEntry.entry_id == payload["entry_id"]))
    assert row is not None
    assert row.contractual_deadline is True
    task = db.scalar(select(TaskRecord).where(TaskRecord.task_id == row.linked_task_id))
    assert task is not None
    assert task.project_id == PROJECT_ID
    assert task.priority == "critical"
    event = db.scalar(
        select(EventRecord).where(
            EventRecord.object_id == row.entry_id,
            EventRecord.event_type == "CALENDAR_ENTRY_CREATED",
        )
    )
    assert event is not None
    assert db.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == row.entry_id,
            AuditLog.action == "calendar_entry_created",
        )
    ) is not None


def test_resource_conflict_requires_explicit_override(client, db):
    ensure_project(db)
    login(client, "project-manager")
    first = create_entry(client, title="Helyszíni kooperáció", days=10, hour=9)
    assert first.status_code == 200

    blocked = create_entry(client, title="Párhuzamos bejárás", days=10, hour=9)
    assert blocked.status_code == 409
    assert "felülbírálási indok" in blocked.json()["detail"]

    overridden = create_entry(
        client,
        title="Hatósági bejárás",
        days=10,
        hour=9,
        conflict_override_reason="A projektmenedzser delegált helyettese részt vesz.",
    )
    assert overridden.status_code == 200
    listed = client.get(f"/api/smart-calendar/entries?project_id={PROJECT_ID}")
    assert listed.status_code == 200
    assert listed.json()["metrics"]["conflicts"] >= 1


def test_dependency_blocks_invalid_schedule_and_premature_execution(client, db):
    ensure_project(db)
    login(client, "project-manager")
    predecessor = create_entry(client, title="Szerkezetkész állapot", days=12, hour=8).json()
    successor = create_entry(client, title="Gépészeti indulás", days=13, hour=8).json()

    dependency = client.post(
        "/api/smart-calendar/dependencies",
        json={
            "predecessor_entry_id": predecessor["entry_id"],
            "successor_entry_id": successor["entry_id"],
            "dependency_type": "finish_to_start",
            "lag_days": 0,
        },
    )
    assert dependency.status_code == 200, dependency.text
    assert db.scalar(select(CalendarDependency)) is not None

    confirmed = client.post(
        f"/api/smart-calendar/entries/{successor['entry_id']}/status",
        json={"status": "confirmed"},
    )
    assert confirmed.status_code == 200
    blocked = client.post(
        f"/api/smart-calendar/entries/{successor['entry_id']}/status",
        json={"status": "in_progress"},
    )
    assert blocked.status_code == 409
    assert predecessor["entry_id"] in blocked.json()["detail"]

    client.post(
        f"/api/smart-calendar/entries/{predecessor['entry_id']}/status",
        json={"status": "confirmed"},
    )
    completed = client.post(
        f"/api/smart-calendar/entries/{predecessor['entry_id']}/status",
        json={"status": "completed", "note": "Átvételi jegyzőkönyv rögzítve."},
    )
    assert completed.status_code == 200
    started = client.post(
        f"/api/smart-calendar/entries/{successor['entry_id']}/status",
        json={"status": "in_progress"},
    )
    assert started.status_code == 200


def test_contractual_deadline_requires_leadership_change_gate(client, db):
    ensure_project(db)
    login(client, "project-manager")
    created = create_entry(
        client,
        title="Szerződéses műszaki átadás",
        days=20,
        entry_type="deadline",
        contractual_deadline=True,
    ).json()
    new_start, new_end = window(22, 8)
    direct = client.post(
        f"/api/smart-calendar/entries/{created['entry_id']}/reschedule",
        json={"starts_at": new_start, "ends_at": new_end, "reason": "Megrendelői kérés"},
    )
    assert direct.status_code == 409
    assert "változáskérelemmel" in direct.json()["detail"]

    requested = client.post(
        f"/api/smart-calendar/entries/{created['entry_id']}/change-requests",
        json={
            "starts_at": new_start,
            "ends_at": new_end,
            "reason": "Megrendelő által kért műszaki tartalomváltozás",
            "impact_summary": "Két nap határidőhatás, pénzügyi hatás külön ChangeControlban.",
        },
    )
    assert requested.status_code == 200
    request_id = requested.json()["request_id"]

    denied = client.post(
        f"/api/smart-calendar/change-requests/{request_id}/decision",
        json={"decision": "approved", "note": "Jóváhagyva."},
    )
    assert denied.status_code == 403
    client.post("/logout")
    login(client, "owner")
    approved = client.post(
        f"/api/smart-calendar/change-requests/{request_id}/decision",
        json={"decision": "approved", "note": "Hatáselemzés és ügyféljóváhagyás ellenőrizve."},
    )
    assert approved.status_code == 200, approved.text

    db.expire_all()
    row = db.scalar(select(CalendarEntry).where(CalendarEntry.entry_id == created["entry_id"]))
    change = db.scalar(
        select(CalendarChangeRequest).where(CalendarChangeRequest.request_id == request_id)
    )
    assert change.status == "approved"
    assert change.decided_by == "owner@imperial.local"
    assert row.ends_at.replace(tzinfo=UTC) == datetime.fromisoformat(new_end)


def test_smart_calendar_ui_and_role_permissions(client):
    login(client, "project-manager")
    page = client.get("/smart-calendar")
    assert page.status_code == 200
    assert "Project Smart Calendar" in page.text
    assert "Új naptárelem" in page.text
    assert "Ütemezési függőség" in page.text
    client.post("/logout")

    login(client, "sales")
    assert client.get("/smart-calendar").status_code == 403
    assert client.get("/api/smart-calendar/entries").status_code == 403


def test_existing_task_sources_are_synchronized_idempotently(client, db):
    ensure_project(db)
    due_at = datetime.now(UTC) + timedelta(days=6)
    db.add(
        TaskRecord(
            task_id="TASK-MIGRATED-001",
            project_id=PROJECT_ID,
            title="Migrált ügyféldöntési feladat",
            assignee="project-manager@imperial.local",
            due_at=due_at,
            priority="high",
            status="open",
            executive_relevance=True,
        )
    )
    db.commit()
    login(client, "project-manager")

    first = client.post("/api/smart-calendar/sync", json={})
    second = client.post("/api/smart-calendar/sync", json={})
    assert first.status_code == 200
    assert first.json()["created"] == 1
    assert second.json()["created"] == 0

    db.expire_all()
    rows = db.scalars(
        select(CalendarEntry).where(
            CalendarEntry.source_module == "workflow-center",
            CalendarEntry.source_object_id == "TASK-MIGRATED-001",
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].linked_task_id == "TASK-MIGRATED-001"
    assert rows[0].contractual_deadline is True


def test_project_manager_scope_is_fail_closed_for_read_and_write(client, db):
    ensure_project(db)
    db.add(
        ProjectRegistry(
            project_id="IMP-FOREIGN-001",
            name="Másik projektmenedzser projektje",
            responsible="other-pm@imperial.local",
        )
    )
    foreign_start = datetime.now(UTC) + timedelta(days=3)
    foreign_entry = CalendarEntry(
        entry_id="CAL-FOREIGN-001",
        project_id="IMP-FOREIGN-001",
        entry_type="deadline",
        title="Bizalmas idegen projekt határideje",
        starts_at=foreign_start,
        ends_at=foreign_start + timedelta(hours=2),
        assignee="other-pm@imperial.local",
        participants_json="[]",
        contractual_deadline=True,
        created_by="other-pm@imperial.local",
        updated_by="other-pm@imperial.local",
    )
    db.add(foreign_entry)
    db.add(
        CalendarChangeRequest(
            request_id="CCR-FOREIGN-001",
            entry_id=foreign_entry.entry_id,
            requested_starts_at=foreign_start + timedelta(days=1),
            requested_ends_at=foreign_start + timedelta(days=1, hours=2),
            reason="Idegen projekt bizalmas módosítása",
            impact_summary="Nem jelenhet meg másik projektmenedzser munkaterében.",
            requested_by="other-pm@imperial.local",
        )
    )
    db.commit()
    login(client, "project-manager")

    denied_read = client.get("/api/smart-calendar/entries?project_id=IMP-FOREIGN-001")
    assert denied_read.status_code == 403
    start, end = window(5)
    denied_write = client.post(
        "/api/smart-calendar/entries",
        json={
            "project_id": "IMP-FOREIGN-001",
            "title": "Jogosulatlan bejegyzés",
            "starts_at": start,
            "ends_at": end,
        },
    )
    assert denied_write.status_code == 403
    visible = client.get("/api/smart-calendar/entries")
    assert visible.status_code == 200
    assert all(row["project_id"] == PROJECT_ID for row in visible.json()["entries"])
    assert visible.json()["metrics"]["pending_changes"] == 0
    page = client.get("/smart-calendar")
    assert "Bizalmas idegen projekt határideje" not in page.text


def test_calendar_write_requires_csrf_and_rejects_stale_version(client, db):
    ensure_project(db)
    login(client, "project-manager")
    start, end = window(7)
    without_csrf = client.post(
        "/api/smart-calendar/entries",
        headers={"x-csrf-token": ""},
        json={
            "project_id": PROJECT_ID,
            "title": "CSRF ellenőrzés",
            "starts_at": start,
            "ends_at": end,
        },
    )
    assert without_csrf.status_code == 403

    created = create_entry(client, title="Verziózott ütemezés", days=7).json()
    confirmed = client.post(
        f"/api/smart-calendar/entries/{created['entry_id']}/status",
        json={"status": "confirmed", "expected_version": created["version"]},
    )
    assert confirmed.status_code == 200
    new_start, new_end = window(8)
    stale = client.post(
        f"/api/smart-calendar/entries/{created['entry_id']}/reschedule",
        json={
            "starts_at": new_start,
            "ends_at": new_end,
            "reason": "Stale kliens próbája",
            "expected_version": created["version"],
        },
    )
    assert stale.status_code == 409
    assert "időközben módosult" in stale.json()["detail"]


def test_completion_and_cancellation_require_auditable_note(client, db):
    ensure_project(db)
    login(client, "project-manager")
    created = create_entry(client, title="Dokumentált lezárás", days=9).json()
    client.post(
        f"/api/smart-calendar/entries/{created['entry_id']}/status",
        json={"status": "confirmed", "expected_version": created["version"]},
    )
    db.expire_all()
    row = db.scalar(select(CalendarEntry).where(CalendarEntry.entry_id == created["entry_id"]))
    rejected = client.post(
        f"/api/smart-calendar/entries/{created['entry_id']}/status",
        json={"status": "completed", "note": "kész", "expected_version": row.version},
    )
    assert rejected.status_code == 409
    accepted = client.post(
        f"/api/smart-calendar/entries/{created['entry_id']}/status",
        json={
            "status": "completed",
            "note": "Átadás-átvételi jegyzőkönyv ellenőrizve.",
            "expected_version": row.version,
        },
    )
    assert accepted.status_code == 200
