from __future__ import annotations

from io import BytesIO
from pathlib import Path

from sqlalchemy import select

from app.models import (
    CareCase,
    CareEvidence,
    CustomerPortalAccess,
    EventRecord,
    ProjectObjectState,
    ProjectRegistry,
    TaskRecord,
)

CUSTOMER = "customer@imperial.local"
PASSWORD = "Imperial2026!"


def _grant_customer_project(db, project_id: str = "CARE-UAT-001") -> ProjectRegistry:
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if project is None:
        project = ProjectRegistry(
            project_id=project_id,
            name="Imperial Care UAT projekt",
            customer_name="Care Teszt Ügyfél",
            project_type="Átadott családi ház",
            status="active",
            responsible="project.manager@imperial.local",
        )
        db.add(project)
    access = db.scalar(
        select(CustomerPortalAccess).where(
            CustomerPortalAccess.project_id == project_id,
            CustomerPortalAccess.customer_email == CUSTOMER,
        )
    )
    if access is None:
        db.add(
            CustomerPortalAccess(
                access_id=f"CPA-{project_id}",
                project_id=project_id,
                customer_email=CUSTOMER,
                contact_name="Care Teszt Ügyfél",
                source_type="uat",
                source_id=f"UAT-{project_id}",
                active=True,
                created_by="test",
            )
        )
    db.commit()
    return project


def _login(client, email: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/login",
        data={"email": email, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _create_case(client, db) -> CareCase:
    _grant_customer_project(db)
    _login(client, CUSTOMER)
    response = client.post(
        "/imperial-care/cases",
        data={
            "project_id": "CARE-UAT-001",
            "category": "warranty",
            "severity": "high",
            "title": "Bejárati ajtó záródási hiba",
            "description": "Az ajtó három napja csak erős nyomással zárható, ideiglenes javítás nem történt.",
            "location": "Földszinti előtér",
            "preferred_contact": "+36 30 123 4567, munkanap 9–12",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    row = db.scalar(select(CareCase).where(CareCase.project_id == "CARE-UAT-001"))
    assert row is not None
    return row


def test_customer_opens_exclusive_care_case_with_sla_event_and_task(client, db):
    row = _create_case(client, db)

    assert row.customer_email == CUSTOMER
    assert row.status == "submitted"
    assert row.source_channel == "imperial-care"
    assert row.sla_due_at > row.created_at
    event = db.scalar(
        select(EventRecord).where(
            EventRecord.object_type == "CareCase", EventRecord.object_id == row.case_id
        )
    )
    assert event is not None
    assert event.source_module == "imperial-care"
    assert event.event_type == "WARRANTY_CASE_OPENED"
    task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == event.event_id))
    assert task is not None
    assert task.due_at == row.sla_due_at
    assert task.priority == "high"
    state = db.scalar(
        select(ProjectObjectState).where(
            ProjectObjectState.source_module == "imperial-care",
            ProjectObjectState.object_id == row.case_id,
        )
    )
    assert state is not None and state.status == "submitted"

    page = client.get("/imperial-care")
    assert page.status_code == 200
    assert row.case_id in page.text
    assert "KIZÁRÓLAGOS ÜGYFÉL-HIBABEJELENTÉSI CSATORNA" in page.text
    assert "Hiba vagy garanciális ügy bejelentése" in client.get("/my-imperial").text
    assert row.case_id in client.get(
        "/imperial-care", params={"status": "submitted", "query": row.case_id}
    ).text
    assert row.case_id not in client.get(
        "/imperial-care", params={"query": "NINCS-ILYEN-CARE-UGY"}
    ).text


def test_deactivated_myimperial_access_hides_existing_case(client, db):
    row = _create_case(client, db)
    access = db.scalar(
        select(CustomerPortalAccess).where(
            CustomerPortalAccess.project_id == row.project_id,
            CustomerPortalAccess.customer_email == CUSTOMER,
        )
    )
    access.active = False
    db.commit()

    listing = client.get("/imperial-care")
    assert listing.status_code == 200
    assert row.case_id not in listing.text
    assert client.get(f"/imperial-care/{row.case_id}").status_code == 403


def test_customer_cannot_report_foreign_project_or_use_generic_care_workbench(client, db):
    _grant_customer_project(db)
    db.add(ProjectRegistry(project_id="CARE-FOREIGN", name="Másik ügyfél projektje"))
    db.commit()
    _login(client, CUSTOMER)

    foreign = client.post(
        "/imperial-care/cases",
        data={
            "project_id": "CARE-FOREIGN",
            "category": "defect",
            "severity": "medium",
            "title": "Idegen projektre küldött hiba",
            "description": "Ehhez a projekthez a tesztügyfélnek nincs aktív hozzáférése.",
        },
    )
    assert foreign.status_code == 403

    generic = client.post(
        "/workbench/imperial-care/records",
        data={"title": "Tiltott kerülőút", "record_type": "Garanciális ügy"},
    )
    assert generic.status_code == 400
    assert "kizárólag" in generic.text


def test_project_manager_triages_resolves_and_customer_confirms_without_private_note_leak(client, db):
    row = _create_case(client, db)
    _login(client, "project-manager@imperial.local")

    triage = client.post(
        f"/imperial-care/{row.case_id}/status",
        data={
            "status": "triaged",
            "assigned_to": "service.manager@imperial.local",
            "expected_version": str(row.version),
        },
        follow_redirects=False,
    )
    assert triage.status_code == 303
    stale = client.post(
        f"/imperial-care/{row.case_id}/status",
        data={
            "status": "in_progress",
            "assigned_to": "service.manager@imperial.local",
            "expected_version": "1",
        },
    )
    assert stale.status_code == 400
    assert "időközben más módosította" in stale.text
    private = client.post(
        f"/imperial-care/{row.case_id}/messages",
        data={"body": "Belső ellenőrzés: a szerelési jegyzőkönyvet még be kell kérni."},
        follow_redirects=False,
    )
    assert private.status_code == 303
    db.refresh(row)
    assert client.post(
        f"/imperial-care/{row.case_id}/status",
        data={
            "status": "in_progress",
            "assigned_to": "service.manager@imperial.local",
            "expected_version": str(row.version),
        },
        follow_redirects=False,
    ).status_code == 303
    db.refresh(row)
    resolved = client.post(
        f"/imperial-care/{row.case_id}/status",
        data={
            "status": "resolved",
            "assigned_to": "service.manager@imperial.local",
            "resolution_summary": "A záródási pontot beállítottuk, a működést az ügyféllel közösen ellenőriztük.",
            "expected_version": str(row.version),
        },
        follow_redirects=False,
    )
    assert resolved.status_code == 303

    _login(client, CUSTOMER)
    db.refresh(row)
    detail = client.get(f"/imperial-care/{row.case_id}")
    assert detail.status_code == 200
    assert "A záródási pontot beállítottuk" in detail.text
    assert "Belső ellenőrzés" not in detail.text
    close = client.post(
        f"/imperial-care/{row.case_id}/status",
        data={"status": "closed", "expected_version": str(row.version)},
        follow_redirects=False,
    )
    assert close.status_code == 303
    db.refresh(row)
    assert row.status == "closed"
    assert row.customer_confirmed is True
    event = db.scalar(select(EventRecord).where(EventRecord.object_id == row.case_id))
    task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == event.event_id))
    assert event.status == "resolved"
    assert task.status == "done"
    assert client.post(
        f"/imperial-care/{row.case_id}/messages",
        data={"body": "Lezárás utáni tiltott üzenet."},
    ).status_code == 400


def test_care_evidence_is_type_checked_hashed_and_access_controlled(client, db):
    row = _create_case(client, db)
    png = b"\x89PNG\r\n\x1a\n" + b"imperial-care-test-image"
    upload = client.post(
        f"/imperial-care/{row.case_id}/evidence",
        files={"file": ("hiba.png", BytesIO(png), "image/png")},
        data={"caption": "Az ajtó felső záródási pontja."},
        follow_redirects=False,
    )
    assert upload.status_code == 303
    evidence = db.scalar(select(CareEvidence).where(CareEvidence.case_id_fk == row.id))
    assert evidence is not None
    assert len(evidence.sha256) == 64
    download = client.get(f"/imperial-care/evidence/{evidence.evidence_id}")
    assert download.status_code == 200
    assert download.content == png
    Path(evidence.storage_path).write_bytes(png + b"tampered")
    tampered = client.get(f"/imperial-care/evidence/{evidence.evidence_id}")
    assert tampered.status_code == 409
    assert "SHA-256" in tampered.text

    invalid = client.post(
        f"/imperial-care/{row.case_id}/evidence",
        files={"file": ("hamis.png", BytesIO(b"not-a-png"), "image/png")},
    )
    assert invalid.status_code == 400


def test_subcontractor_never_sees_internal_care_notes(client, db):
    row = _create_case(client, db)
    _login(client, "project-manager@imperial.local")
    assert client.post(
        f"/imperial-care/{row.case_id}/status",
        data={
            "status": "triaged",
            "assigned_to": "subcontractor@imperial.local",
            "expected_version": str(row.version),
        },
        follow_redirects=False,
    ).status_code == 303
    assert client.post(
        f"/imperial-care/{row.case_id}/messages",
        data={"body": "Belső költség- és felelősségi vizsgálat, ügyfélnek nem látható."},
        follow_redirects=False,
    ).status_code == 303

    _login(client, "subcontractor@imperial.local")
    detail = client.get(f"/imperial-care/{row.case_id}")
    assert detail.status_code == 200
    assert "Belső költség- és felelősségi vizsgálat" not in detail.text
