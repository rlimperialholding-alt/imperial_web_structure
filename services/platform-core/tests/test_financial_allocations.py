from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app import __version__
from app.models import AuditLog, EnterpriseCanonicalRecord, ProjectRegistry
from app.services.financial_allocations import (
    allocate_financial_record,
    allocation_scope,
    allocation_workspace,
)
from app.services.financial_intelligence import finance_intelligence_dashboard
from app.seed import DEMO_PASSWORD


def _finance_record(db, *, record_id: str = "FIN-ALLOC-1") -> EnterpriseCanonicalRecord:
    row = EnterpriseCanonicalRecord(
        record_id=record_id,
        domain="finance",
        entity_type="supplier_invoice",
        external_key=f"test:{record_id}",
        canonical_name="Teszt beszállítói számla",
        target_module="financial-control",
        status="active",
        data_json=json.dumps(
            {
                "invoiceNumber": "TEST-ALLOC-001",
                "sellerName": "Teszt Szállító Kft.",
                "grossAmount": 127000,
                "currency": "HUF",
            }
        ),
        provenance_json=json.dumps({"source": "allocation-test"}),
    )
    db.add(row)
    db.commit()
    return row


def test_allocation_workspace_and_project_assignment_are_audited(db):
    project = ProjectRegistry(project_id="PRJ-ALLOC-1", name="Besorolási tesztprojekt")
    db.add(project)
    row = _finance_record(db)

    workspace = allocation_workspace(db, scope="unassigned", search="TEST-ALLOC-001")
    assert workspace["total"] == 1
    assert workspace["items"][0]["record"].record_id == row.record_id

    result = allocate_financial_record(
        db,
        row.record_id,
        scope="project",
        project_id=project.project_id,
        note="A számla a kiválasztott kivitelezési projekthez tartozik.",
        actor="finance@example.invalid",
        actor_role="finance",
    )

    assert result.project_id == project.project_id
    assert allocation_scope(result) == "project"
    manual = json.loads(result.provenance_json)["manualAllocation"]
    assert manual["projectId"] == project.project_id
    assert manual["actor"] == "finance@example.invalid"
    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "financial_record_allocated",
            AuditLog.entity_id == row.record_id,
        )
    )
    assert audit is not None
    assert json.loads(audit.after_json)["allocation_scope"] == "project"


def test_corporate_allocation_requires_reason_and_clears_unallocated_warning(db):
    row = _finance_record(db, record_id="FIN-ALLOC-CORP")
    before = finance_intelligence_dashboard(db)
    assert before["unallocated"] >= 1

    with pytest.raises(ValueError, match="indoklás"):
        allocate_financial_record(
            db,
            row.record_id,
            scope="corporate",
            project_id=None,
            note="",
            actor="finance@example.invalid",
            actor_role="finance",
        )

    allocate_financial_record(
        db,
        row.record_id,
        scope="corporate",
        project_id=None,
        note="Igazolt központi működési költség.",
        actor="finance@example.invalid",
        actor_role="finance",
    )
    after = finance_intelligence_dashboard(db)
    assert after["unallocated"] == before["unallocated"] - 1
    assert after["corporate"] == before["corporate"] + 1


def test_project_allocation_rejects_unknown_project(db):
    row = _finance_record(db, record_id="FIN-ALLOC-UNKNOWN")
    with pytest.raises(ValueError, match="nem található"):
        allocate_financial_record(
            db,
            row.record_id,
            scope="project",
            project_id="PRJ-DOES-NOT-EXIST",
            note="Téves projektpróba",
            actor="finance@example.invalid",
            actor_role="finance",
        )


def test_project_manager_cannot_allocate_canonical_financial_record(db):
    row = _finance_record(db, record_id="FIN-ALLOC-PM-DENIED")

    with pytest.raises(PermissionError, match="csak a pénzügy"):
        allocate_financial_record(
            db,
            row.record_id,
            scope="corporate",
            project_id=None,
            note="Projektmenedzseri besorolási kísérlet.",
            actor="project-manager@example.invalid",
            actor_role="project-manager",
        )

    assert allocation_scope(row) == "unassigned"


def test_financial_allocation_screen_is_available_to_authorized_user(logged_in_client, db):
    _finance_record(db, record_id="FIN-ALLOC-UI")
    response = logged_in_client.get("/financial/allocations")
    assert response.status_code == 200
    assert "Pénzügyi projektbesorolás" in response.text
    assert "TEST-ALLOC-001" in response.text
    assert response.text.count('class="metric-card-link"') == 3
    assert f'/static/style.css?v={__version__}' in response.text


def test_project_manager_cannot_view_or_change_global_financial_allocation(client, db):
    row = _finance_record(db, record_id="FIN-ALLOC-PM-HTTP")
    login = client.post(
        "/login",
        data={
            "email": "project-manager@imperial.local",
            "password": DEMO_PASSWORD,
        },
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert client.get("/financial/allocations").status_code == 403

    response = client.post(
        f"/financial/allocations/{row.record_id}",
        data={"scope": "corporate", "note": "Tiltott PM könyvelési besorolás."},
        follow_redirects=False,
    )

    assert response.status_code == 403
    db.refresh(row)
    assert allocation_scope(row) == "unassigned"
