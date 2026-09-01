from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import select

from app.models import (
    DevelopmentDiscoveryRecord,
    ProjectObjectState,
    ReleaseRecord,
    TaskRecord,
    WorkspaceDocument,
)
from app.services.commercial_integration import (
    build_contract_intake_payload,
    contract_form_values,
    validate_contract_payload,
)
from app.seed import DEMO_PASSWORD

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "integrations" / "contract_generator_v0_4" / "examples" / "customer_construction_valid.json"


def unique_contract_payload() -> dict:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    token = uuid.uuid4().hex[:10].upper()
    project_id = f"PRJ-COMM-{token}"
    contract_number = f"VEVO-KIV-{token}"
    payload["contract_number"] = contract_number
    payload["ids"]["ProjectID"] = project_id
    payload["ids"]["OpportunityID"] = f"OPP-{token}"
    payload["ids"]["CompanyID"] = f"COM-{token}"
    payload["ids"]["PersonID"] = f"PER-{token}"
    payload["ids"]["PartnerID"] = f"PAR-{token}"
    for attachment in payload["attachments"]:
        attachment["file_id"] = f"EVIDENCE-{token}-{attachment['type']}"
    return payload


def test_canonical_source_is_hash_verified(client):
    response = client.get("/api/commercial/source-status")
    assert response.status_code == 200
    data = response.json()
    assert data["healthy"] is True
    assert data["canonical_source"] is True
    assert data["version"] == "0.4.0"
    assert len(data["templates"]) == 5
    assert {row["contract_type"] for row in data["templates"]} == {
        "customer_type_house_design_build",
        "customer_construction",
        "customer_design_execution_plans",
        "subcontractor_design",
        "subcontractor_execution",
    }
    assert data["provenance_mode"] in {"verified_archive", "verified_source_tree"}
    if data["archive_present"]:
        assert data["zip_actual_sha256"] == data["zip_expected_sha256"]
    assert all(item["ok"] for item in data["templates"])


def test_contract_generation_reuses_canonical_engine_and_registers_projection(client, db):
    payload = unique_contract_payload()
    response = client.post("/api/commercial/contracts/generate", json={"payload": payload})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["canonical_source"]["version"] == "0.4.0"
    assert data["canonical_source"]["healthy"] is True
    assert Path(data["zip_path"]).exists()
    assert Path(data["zip_path"]).is_relative_to(
        ROOT / "runtime" / "contract_packages"
    )

    docs = db.scalars(select(WorkspaceDocument).where(
        WorkspaceDocument.project_id == payload["ids"]["ProjectID"],
        WorkspaceDocument.source_system == "contract_generator",
    )).all()
    assert {doc.category for doc in docs} == {"contract_package", "contract_manifest"}

    state = db.scalar(select(ProjectObjectState).where(
        ProjectObjectState.project_id == payload["ids"]["ProjectID"],
        ProjectObjectState.source_module == "contract_generator",
        ProjectObjectState.object_id == payload["contract_number"],
    ))
    assert state is not None
    state_payload = json.loads(state.payload_json)
    assert state_payload["duplicate_business_engine_created"] is False
    assert state_payload["canonical_source_sha256"] == data["canonical_source"]["zip_expected_sha256"]
    workflow_tasks = db.scalars(select(TaskRecord).where(
        TaskRecord.project_id == payload["ids"]["ProjectID"],
        TaskRecord.task_id.in_(data["workflow_task_ids"]),
    )).all()
    assert len(workflow_tasks) >= 5
    assert any("Kettős kézbesítés" in task.title for task in workflow_tasks)


def test_contract_generation_cannot_silently_duplicate_same_contract(client):
    payload = unique_contract_payload()
    first = client.post("/api/commercial/contracts/generate", json={"payload": payload})
    assert first.status_code == 200, first.text
    second = client.post("/api/commercial/contracts/generate", json={"payload": payload})
    assert second.status_code == 400
    assert "már létezik generált csomag" in second.json()["detail"]


def test_raw_contract_api_rejects_missing_attachment_evidence(client):
    payload = unique_contract_payload()
    for attachment in payload["attachments"]:
        attachment.pop("file_id", None)
    response = client.post(
        "/api/commercial/contracts/generate", json={"payload": payload}
    )
    assert response.status_code == 400
    assert "melléklethez Drive- vagy dokumentumbizonyíték" in response.json()["detail"]


def test_structured_contract_intake_covers_all_five_contract_types():
    examples = ROOT / "integrations" / "contract_generator_v0_4" / "examples"
    for path in sorted(examples.glob("*_valid.json")):
        if path.name.startswith("invoice"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for attachment in payload["attachments"]:
            attachment["file_id"] = f"EVIDENCE-{attachment['type']}"
        values = contract_form_values(payload)
        rebuilt = build_contract_intake_payload(values)
        validation = validate_contract_payload(rebuilt)
        assert validation["valid"] is True, (path.name, validation["issues"])
        assert all(row.get("file_id") for row in rebuilt["attachments"])
        assert rebuilt["status"]["commercial_approval"] == "PENDING"
        assert rebuilt["status"]["technical_approval"] == "PENDING"


def test_structured_contract_form_generates_without_raw_json(logged_in_client):
    payload = unique_contract_payload()
    for attachment in payload["attachments"]:
        attachment["file_id"] = f"DRIVE-{attachment['type']}"
    response = logged_in_client.post(
        "/commercial/contracts/generate",
        data=contract_form_values(payload),
    )
    assert response.status_code == 200, response.text
    assert payload["contract_number"] in response.text
    assert "payload_json" not in response.text


def test_contract_download_is_role_scoped_and_hash_verified(
    client, logged_in_client, db
):
    payload = unique_contract_payload()
    generated = client.post(
        "/api/commercial/contracts/generate", json={"payload": payload}
    )
    assert generated.status_code == 200, generated.text
    package = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.project_id == payload["ids"]["ProjectID"],
            WorkspaceDocument.category == "contract_package",
        )
    )
    assert package is not None
    download = logged_in_client.get(f"/commercial/files/{package.document_id}")
    assert download.status_code == 200
    assert download.content

    original_metadata = package.metadata_json
    metadata = json.loads(original_metadata)
    metadata["sha256"] = "0" * 64
    package.metadata_json = json.dumps(metadata)
    db.commit()
    blocked = logged_in_client.get(f"/commercial/files/{package.document_id}")
    assert blocked.status_code == 409
    package.metadata_json = original_metadata
    db.commit()

    logged_in_client.post("/logout")
    login = logged_in_client.post(
        "/login",
        data={"email": "finance@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert logged_in_client.get("/commercial/contracts/new").status_code == 403
    assert logged_in_client.get(f"/commercial/files/{package.document_id}").status_code == 200
    logged_in_client.post("/logout")
    logged_in_client.post(
        "/login",
        data={"email": "customer@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert logged_in_client.get(f"/commercial/files/{package.document_id}").status_code == 403


def test_change_control_is_projection_only(client, db):
    token = uuid.uuid4().hex[:10].upper()
    payload = {
        "change_id": f"CHG-{token}",
        "project_id": f"PRJ-{token}",
        "status": "customer_accepted",
        "version": 2,
        "summary": "Ügyfél által elfogadott változás, munkakezdési engedély szükséges.",
        "net_revenue_huf": "2500000",
        "net_cost_huf": "1500000",
        "deadline_impact_days": 4,
        "customer_decision": "accepted",
        "source_url": "https://example.invalid/change-control/source",
    }
    response = client.post("/api/commercial/change-events", json=payload)
    assert response.status_code == 200, response.text
    state = db.scalar(select(ProjectObjectState).where(
        ProjectObjectState.project_id == payload["project_id"],
        ProjectObjectState.source_module == "change_control",
        ProjectObjectState.object_id == payload["change_id"],
    ))
    assert state is not None
    data = json.loads(state.payload_json)
    assert data["source_module_is_authoritative"] is True
    assert data["workspace_is_projection_only"] is True


def test_unknown_module_release_is_discovery_blocked(client, db):
    response = client.post("/api/releases", json={
        "release_id": "REL-DUPLICATE-ENGINE-1.0",
        "module_key": "parallel_change_engine",
        "version": "1.0.0",
        "tests_total": 10,
        "tests_passed": 10,
    })
    assert response.status_code == 200
    assert response.json()["status"] == "discovery_blocked"
    row = db.scalar(select(ReleaseRecord).where(ReleaseRecord.release_id == "REL-DUPLICATE-ENGINE-1.0"))
    assert row.reuse_gate_passed is False
    assert row.discovery_request_id is None


def test_approved_integration_discovery_opens_release_gate(client, db):
    discovery_id = f"DISC-TEST-{uuid.uuid4().hex[:8].upper()}"
    create = client.post("/api/development-discoveries", json={
        "discovery_id": discovery_id,
        "requested_capability": "Contract Generator további Workspace integráció",
        "requested_module_key": "commercial_integration",
        "searched_terms": ["Contract Generator", "commercial_integration", "v0.4"],
        "candidate_artifacts": [{"drive_file_id": "1kL92i1Z8Zk5V_1W4wmTbJB0pRAVVhSHV"}],
        "canonical_module_key": "contract_generator",
        "canonical_object_owner": "Jogi / operáció",
        "source_version": "0.4.0",
        "source_sha256": "3634378bbc90f885b54e787f6de06e57cabf4d6a594e1351463388814e191a42",
        "decision": "integrate",
        "implementation_gap": "Kizárólag új adapter és közös nézet; új szerződésmotor nem készül.",
        "requested_by": "test",
    })
    assert create.status_code == 200, create.text
    review = client.post(f"/api/development-discoveries/{discovery_id}/review", json={
        "status": "approved", "reviewed_by": "owner", "exception_approved": False,
    })
    assert review.status_code == 200, review.text

    release = client.post("/api/releases", json={
        "release_id": "REL-COMMERCIAL-TEST-1.0",
        "module_key": "commercial_integration",
        "version": "1.0.0",
        "tests_total": 1,
        "tests_passed": 1,
        "discovery_request_id": discovery_id,
    })
    assert release.status_code == 200
    assert release.json()["status"] == "archive_pending"
    row = db.scalar(select(ReleaseRecord).where(ReleaseRecord.release_id == "REL-COMMERCIAL-TEST-1.0"))
    assert row.reuse_gate_passed is True
    assert row.discovery_request_id == discovery_id


def test_seeded_discovery_records_prove_reuse(db):
    rows = db.scalars(select(DevelopmentDiscoveryRecord).where(
        DevelopmentDiscoveryRecord.requested_module_key == "commercial_integration"
    )).all()
    decisions = {(row.canonical_module_key, row.decision, row.status) for row in rows}
    assert ("contract_generator", "integrate", "approved") in decisions
    assert ("change_control", "integrate", "approved") in decisions


def test_commercial_ui_pages(logged_in_client):
    for path in ["/commercial", "/commercial/contracts/new", "/smart-calendar", "/development-governance"]:
        response = logged_in_client.get(path)
        assert response.status_code == 200
        assert "Imperial" in response.text
