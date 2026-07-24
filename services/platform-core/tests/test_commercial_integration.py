from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import select

from app.models import (
    DevelopmentDiscoveryRecord,
    ProjectObjectState,
    ReleaseRecord,
    WorkspaceDocument,
)

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
    return payload


def test_canonical_source_is_hash_verified(client):
    response = client.get("/api/commercial/source-status")
    assert response.status_code == 200
    data = response.json()
    assert data["healthy"] is True
    assert data["canonical_source"] is True
    assert data["version"] == "0.4.0"
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


def test_contract_generation_cannot_silently_duplicate_same_contract(client):
    payload = unique_contract_payload()
    first = client.post("/api/commercial/contracts/generate", json={"payload": payload})
    assert first.status_code == 200, first.text
    second = client.post("/api/commercial/contracts/generate", json={"payload": payload})
    assert second.status_code == 400
    assert "már létezik generált csomag" in second.json()["detail"]


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
    for path in ["/commercial", "/commercial/contracts/new", "/development-governance"]:
        response = logged_in_client.get(path)
        assert response.status_code == 200
        assert "Imperial" in response.text
