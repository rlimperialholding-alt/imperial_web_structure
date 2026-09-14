from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import (
    AuditLog,
    CustomerDecisionRequest,
    CustomerDecisionResponse,
    CustomerPortalAccess,
    CustomerPortalUpdate,
    CustomerPortalUpdateAcknowledgement,
    ProjectObjectState,
    ProjectRegistry,
    TaskRecord,
)
from app.seed import DEMO_PASSWORD

PASSWORD = DEMO_PASSWORD
PROJECT_ID = "MYI-UAT-001"


def _login(client, email: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/login", data={"email": email, "password": PASSWORD}, follow_redirects=False
    )
    assert response.status_code == 303


def _project(db, *, customer_email: str = "customer@imperial.local") -> None:
    db.add(
        ProjectRegistry(
            project_id=PROJECT_ID,
            name="MyImperial UAT építési projekt",
            customer_name="Teszt Ügyfél",
            project_type="new_build",
            status="active",
            responsible="project-manager@imperial.local",
        )
    )
    db.add(
        CustomerPortalAccess(
            access_id="MYI-UAT-ACCESS-001",
            project_id=PROJECT_ID,
            customer_email=customer_email,
            contact_name="Teszt Ügyfél",
            source_type="contract",
            source_id="CON-MYI-UAT-001",
            active=True,
            created_by="platform-admin@imperial.local",
        )
    )
    db.commit()


def test_project_manager_publishes_and_customer_acknowledges_update(client, db):
    _project(db)
    _login(client, "project-manager@imperial.local")
    created = client.post(
        f"/my-imperial/{PROJECT_ID}/updates",
        data={
            "title": "Szerkezetépítés lezárva",
            "body": "A szerkezetépítési mérföldkő dokumentáltan elkészült.",
            "progress_percent": "42",
            "requires_acknowledgement": "on",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    update = db.scalar(
        select(CustomerPortalUpdate).where(CustomerPortalUpdate.project_id == PROJECT_ID)
    )
    assert update is not None and update.progress_percent == 42
    task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == update.update_id))
    assert task is not None and task.status == "waiting_customer"

    _login(client, "customer@imperial.local")
    page = client.get(f"/my-imperial/{PROJECT_ID}")
    assert page.status_code == 200
    assert "Szerkezetépítés lezárva" in page.text
    assert "Imperial Care" in page.text
    acknowledged = client.post(
        f"/my-imperial/{PROJECT_ID}/updates/{update.update_id}/acknowledge",
        follow_redirects=False,
    )
    assert acknowledged.status_code == 303
    db.expire_all()
    assert db.scalar(select(CustomerPortalUpdateAcknowledgement)) is not None
    assert db.scalar(select(TaskRecord).where(TaskRecord.task_id == task.task_id)).status == "done"
    assert db.scalar(
        select(AuditLog).where(AuditLog.action == "myimperial_update_acknowledged")
    )


def test_customer_decision_is_option_bound_final_and_cross_module_visible(client, db):
    _project(db)
    _login(client, "project-manager@imperial.local")
    due = (datetime.now(UTC) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
    created = client.post(
        f"/my-imperial/{PROJECT_ID}/decisions",
        data={
            "title": "Burkolat kiválasztása",
            "description": "A beszerzés indításához végleges döntés szükséges.",
            "options": "Világos tölgy\nNatúr tölgy\nDió",
            "due_at": due,
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    decision = db.scalar(
        select(CustomerDecisionRequest).where(CustomerDecisionRequest.project_id == PROJECT_ID)
    )
    assert decision is not None and decision.status == "open"

    _login(client, "customer@imperial.local")
    invalid = client.post(
        f"/my-imperial/{PROJECT_ID}/decisions/{decision.decision_id}/respond",
        data={"selected_option": "Nem kiadott opció", "note": ""},
    )
    assert invalid.status_code == 400
    response = client.post(
        f"/my-imperial/{PROJECT_ID}/decisions/{decision.decision_id}/respond",
        data={"selected_option": "Natúr tölgy", "note": "Ezt választjuk."},
        follow_redirects=False,
    )
    assert response.status_code == 303
    replay = client.post(
        f"/my-imperial/{PROJECT_ID}/decisions/{decision.decision_id}/respond",
        data={"selected_option": "Dió", "note": "Mégis módosítanánk."},
    )
    assert replay.status_code == 400
    db.expire_all()
    assert db.scalar(select(CustomerDecisionResponse)).selected_option == "Natúr tölgy"
    assert db.scalar(select(CustomerDecisionRequest)).status == "responded"
    state = db.scalar(
        select(ProjectObjectState).where(
            ProjectObjectState.source_module == "my-imperial",
            ProjectObjectState.object_id == decision.decision_id,
        )
    )
    assert state is not None and state.status == "responded"


def test_customer_project_isolation_and_internal_write_gate(client, db):
    _project(db, customer_email="other.customer@example.com")
    _login(client, "customer@imperial.local")
    assert client.get(f"/my-imperial/{PROJECT_ID}").status_code == 403
    assert (
        client.post(
            f"/my-imperial/{PROJECT_ID}/updates",
            data={"title": "Tiltott", "body": "Nem publikálható.", "progress_percent": "1"},
        ).status_code
        == 403
    )

    _login(client, "sales@imperial.local")
    assert client.get(f"/my-imperial/{PROJECT_ID}").status_code == 200
    assert (
        client.post(
            f"/my-imperial/{PROJECT_ID}/updates",
            data={"title": "Értékesítő", "body": "Olvasási szerepkör.", "progress_percent": "1"},
        ).status_code
        == 403
    )


def test_myimperial_has_no_issue_submission_route(client, db):
    _project(db)
    _login(client, "customer@imperial.local")
    page = client.get(f"/my-imperial/{PROJECT_ID}")
    assert page.status_code == 200
    assert "kizárólag az Imperial Care" in page.text
    assert client.post(f"/my-imperial/{PROJECT_ID}/issues").status_code == 404
