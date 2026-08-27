from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models import (
    DeliveryNoteProjection,
    EventRecord,
    MaterialLot,
    MaterialMovement,
    MaterialUsageControl,
    OutboxMessage,
    PMGateCheck,
    PMPhase,
    PMWorkPackage,
    ProcurementOrderProjection,
    ProjectRegistry,
    SiteDailyReport,
    SiteIssue,
    TaskRecord,
)
from app.seed import DEMO_PASSWORD


def seed_operations(db):
    now = datetime.now(timezone.utc)
    db.add(ProjectRegistry(
        project_id="IMP-OPS-001", name="Operations tesztprojekt", customer_name="Teszt Ügyfél",
        project_type="Aktív kivitelezés", status="active", risk_level="yellow", blocked=False,
        responsible="project-manager@imperial.local", next_action="Munkacsomag indítása",
    ))
    db.add(PMPhase(
        phase_id="PH-OPS-001", project_id="IMP-OPS-001", phase_key="structure", name="Szerkezet",
        sequence=10, status="in_progress", planned_start=now-timedelta(days=3), planned_end=now+timedelta(days=10),
        actual_start=now-timedelta(days=2), progress_pct=35, readiness_status="passed", owner="project-manager@imperial.local",
    ))
    db.add(PMWorkPackage(
        work_package_id="WP-OPS-001", project_id="IMP-OPS-001", phase_id="PH-OPS-001", name="Falazás",
        trade="Kőműves", assignee="project-manager@imperial.local", status="in_progress", progress_pct=35,
        planned_start=now-timedelta(days=2), planned_end=now+timedelta(days=5), actual_start=now-timedelta(days=1),
        budget_huf=Decimal("5000000"), committed_huf=Decimal("4700000"), actual_huf=Decimal("1500000"),
    ))
    db.add(PMGateCheck(
        gate_id="GATE-OPS-001", project_id="IMP-OPS-001", work_package_id="WP-OPS-001",
        gate_code="material", label="Anyag biztosítva", required=True, status="pending",
    ))
    db.add(ProcurementOrderProjection(
        order_id="ORD-OPS-001", project_id="IMP-OPS-001", work_package_id="WP-OPS-001",
        supplier_name="Teszt Beszállító Kft.", item_summary="Falazóanyag", status="ordered",
        total_huf=Decimal("1900000"), delivery_due=now+timedelta(days=1), delivery_status="not_started",
        document_status="pending", variance_status="none",
    ))
    db.add(MaterialLot(
        lot_id="LOT-OPS-001", project_id="IMP-OPS-001", material="Ragasztó",
        received_quantity=Decimal("20"), current_quantity=Decimal("20"), unit="zsák",
        storage_location="Konténer", weather_protection="adequate", status="in_stock",
    ))
    db.commit()


def csrf_token(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def test_operations_pages_and_work_package_update(logged_in_client, db):
    seed_operations(db)
    for path in ["/operations", "/operations/projects/IMP-OPS-001", "/field", "/field/IMP-OPS-001", "/procurement/workbench", "/procurement/projects/IMP-OPS-001"]:
        response = logged_in_client.get(path)
        assert response.status_code == 200
        assert "Imperial" in response.text or "Operations" in response.text
    response = logged_in_client.post(
        "/operations/work-packages/WP-OPS-001",
        data={
            "project_id": "IMP-OPS-001",
            "status": "blocked",
            "progress_pct": "55",
            "blocked": "true",
            "block_reason": "Teszt blokk",
            "csrf_token": csrf_token(
                logged_in_client, "/operations/projects/IMP-OPS-001"
            ),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db.expire_all()
    row = db.scalar(select(PMWorkPackage).where(PMWorkPackage.work_package_id == "WP-OPS-001"))
    assert row.progress_pct == 55
    assert row.blocked is True


def test_daily_report_blocker_creates_issue_task_and_event(logged_in_client, db):
    seed_operations(db)
    csrf = csrf_token(logged_in_client, "/field/IMP-OPS-001")
    response = logged_in_client.post(
        "/field/IMP-OPS-001/daily-report",
        data={
            "report_date": "2026-07-19", "reporter": "Teszt PM", "weather": "Napos",
            "workers_total": "6", "summary": "Falazás folytatódott.",
            "blockers": "Hiányzik a jóváhagyott részletrajz.", "safety_status": "ok", "quality_status": "attention",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    report = db.scalar(select(SiteDailyReport).where(SiteDailyReport.project_id == "IMP-OPS-001"))
    assert report is not None
    issue = db.scalar(select(SiteIssue).where(SiteIssue.report_id == report.report_id))
    assert issue is not None and issue.severity == "high"
    assert db.scalar(select(TaskRecord).where(TaskRecord.project_id == "IMP-OPS-001", TaskRecord.title.like("Napi jelentés%"))) is not None
    assert db.scalar(select(EventRecord).where(EventRecord.object_id == issue.issue_id)) is not None

    repeated = logged_in_client.post(
        "/field/IMP-OPS-001/daily-report",
        data={
            "report_date": "2026-07-19",
            "reporter": "Teszt PM",
            "workers_total": "6",
            "summary": "Falazás folytatódott.",
            "blockers": "Hiányzik a jóváhagyott részletrajz.",
            "safety_status": "ok",
            "quality_status": "attention",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert repeated.status_code == 303
    assert len(
        db.scalars(select(SiteIssue).where(SiteIssue.report_id == report.report_id)).all()
    ) == 1


def test_operations_requires_csrf_and_gate_evidence(logged_in_client, db):
    seed_operations(db)
    missing_csrf = logged_in_client.post(
        "/operations/work-packages/WP-OPS-001",
        data={"project_id": "IMP-OPS-001", "status": "blocked"},
        follow_redirects=False,
    )
    assert missing_csrf.status_code == 403

    csrf = csrf_token(logged_in_client, "/operations/projects/IMP-OPS-001")
    missing_evidence = logged_in_client.post(
        "/operations/gates/GATE-OPS-001",
        data={
            "project_id": "IMP-OPS-001",
            "status": "passed",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert missing_evidence.status_code == 409
    accepted = logged_in_client.post(
        "/operations/gates/GATE-OPS-001",
        data={
            "project_id": "IMP-OPS-001",
            "status": "passed",
            "evidence_url": "https://drive.google.com/evidence",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert accepted.status_code == 303


def test_project_manager_scope_and_subcontractor_denial(client, db):
    seed_operations(db)
    db.add(
        ProjectRegistry(
            project_id="IMP-OPS-OTHER",
            name="Tiltott projekt",
            project_type="Aktív kivitelezés",
            status="active",
            risk_level="green",
            responsible="someone-else@imperial.local",
        )
    )
    db.add(
        PMWorkPackage(
            work_package_id="WP-OPS-OTHER",
            project_id="IMP-OPS-OTHER",
            name="Idegen csomag",
            assignee="someone-else@imperial.local",
            status="planned",
            progress_pct=0,
        )
    )
    db.commit()

    assert (
        client.post(
            "/login",
            data={
                "email": "project-manager@imperial.local",
                "password": DEMO_PASSWORD,
            },
            follow_redirects=False,
        ).status_code
        == 303
    )
    portfolio = client.get("/operations")
    assert portfolio.status_code == 200
    assert "Operations tesztprojekt" in portfolio.text
    assert "Tiltott projekt" not in portfolio.text
    assert client.get("/operations/projects/IMP-OPS-OTHER").status_code == 403
    csrf = csrf_token(client, "/operations/projects/IMP-OPS-001")
    denied_write = client.post(
        "/operations/work-packages/WP-OPS-OTHER",
        data={
            "project_id": "IMP-OPS-OTHER",
            "status": "planned",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert denied_write.status_code == 403

    client.cookies.clear()
    assert (
        client.post(
            "/login",
            data={
                "email": "subcontractor@imperial.local",
                "password": DEMO_PASSWORD,
            },
            follow_redirects=False,
        ).status_code
        == 303
    )
    subcontractor_portfolio = client.get("/operations")
    assert subcontractor_portfolio.status_code == 200
    assert "Operations tesztprojekt" not in subcontractor_portfolio.text
    assert "Tiltott projekt" not in subcontractor_portfolio.text
    subcontractor_field = client.get("/field")
    assert subcontractor_field.status_code == 200
    assert "Operations tesztprojekt" not in subcontractor_field.text
    assert "Tiltott projekt" not in subcontractor_field.text
    assert client.get("/operations/projects/IMP-OPS-001").status_code == 403
    assert client.get("/field/IMP-OPS-001").status_code == 403


def test_delivery_note_variance_creates_lot_and_control_events(client, db):
    seed_operations(db)
    response = client.post("/api/procurement/delivery-notes", json={
        "order_id": "ORD-OPS-001", "project_id": "IMP-OPS-001", "receiver": "Teszt PM",
        "item_summary": "Falazóanyag", "ordered_quantity": "12", "received_quantity": "10", "unit": "raklap",
        "plan_match": "variance", "document_status": "incomplete",
        "performance_declaration_status": "missing", "elog_evidence_status": "pending",
        "storage_location": "Depó", "weather_protection": "adequate",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["lot_id"]
    delivery = db.scalar(select(DeliveryNoteProjection).where(DeliveryNoteProjection.delivery_note_id == payload["delivery_note_id"]))
    assert delivery.received_quantity == Decimal("10")
    lot = db.scalar(select(MaterialLot).where(MaterialLot.lot_id == payload["lot_id"]))
    assert lot.current_quantity == Decimal("10")
    event_types = set(db.scalars(select(EventRecord.event_type).where(EventRecord.project_id == "IMP-OPS-001")).all())
    assert {"DELIVERY_NOTE_MISSING", "PERFORMANCE_DECLARATION_MISSING", "QUANTITY_VARIANCE_DETECTED"}.issubset(event_types)


def test_material_movement_blocks_negative_stock(client, db):
    seed_operations(db)
    too_much = client.post("/api/procurement/material-movements", json={
        "lot_id": "LOT-OPS-001", "movement_type": "use", "quantity": "25", "responsible": "Teszt PM"
    })
    assert too_much.status_code == 409
    ok = client.post("/api/procurement/material-movements", json={
        "lot_id": "LOT-OPS-001", "movement_type": "use", "quantity": "5", "responsible": "Teszt PM"
    })
    assert ok.status_code == 200
    db.expire_all()
    lot = db.scalar(select(MaterialLot).where(MaterialLot.lot_id == "LOT-OPS-001"))
    assert lot.current_quantity == Decimal("15")
    assert db.scalar(select(MaterialMovement).where(MaterialMovement.lot_id == "LOT-OPS-001")) is not None


def test_usage_control_is_review_only_and_command_uses_outbox(client, db):
    seed_operations(db)
    response = client.post("/api/procurement/usage-controls", json={
        "project_id": "IMP-OPS-001", "work_package_id": "WP-OPS-001", "lot_id": "LOT-OPS-001",
        "subcontractor": "Teszt brigád", "planned_quantity": "100", "waste_pct": "5",
        "actual_quantity": "110", "unit": "db", "unit_cost_huf": "1000", "damage_huf": "2000",
        "contractual_basis": "Teszt szerződés",
    })
    assert response.status_code == 200
    control = db.scalar(select(MaterialUsageControl).where(MaterialUsageControl.control_id == response.json()["control_id"]))
    assert control.allowed_quantity == Decimal("105")
    assert control.decision_status == "review_required"
    event = db.scalar(select(EventRecord).where(EventRecord.object_id == control.control_id))
    assert event is not None
    assert '"automatic_deduction": false' in event.payload_json

    command = client.post("/api/operations/commands", json={
        "project_id": "IMP-OPS-001", "destination_module": "procurement",
        "command_type": "approve_exception", "object_type": "MaterialUsageControl",
        "object_id": control.control_id, "payload": {"decision": "review"},
    })
    assert command.status_code == 200
    outbox = db.scalar(select(OutboxMessage).where(OutboxMessage.message_id == command.json()["message_id"]))
    assert outbox.status == "pending"


def test_operations_summary_api(client, db):
    seed_operations(db)
    response = client.get("/api/operations/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["active_projects"] == 1
    assert data["pending_gates"] == 1
