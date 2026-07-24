from sqlalchemy import select

from app.models import ReleaseRecord


def release_payload(**overrides):
    data = {
        "release_id": "REL-CONTROL-1.0.0",
        "module_key": "control_center",
        "version": "1.0.0",
        "tests_total": 24,
        "tests_passed": 24,
        "migration_tested": False,
        "uat_approved": False,
        "security_reviewed": False,
        "backup_restore_tested": False,
        "owner_approved": False,
    }
    data.update(overrides)
    return data


def test_release_requires_verified_zip_and_sha(client, db):
    response = client.post("/api/releases", json=release_payload())
    assert response.json()["status"] == "archive_pending"
    for aid, atype in [("ART-ZIP", "source_zip"), ("ART-SHA", "sha256")]:
        r = client.post("/api/releases/REL-CONTROL-1.0.0/artifacts", json={
            "artifact_id": aid, "artifact_type": atype, "file_name": f"{aid}.bin", "cloud_status": "verified"
        })
        assert r.status_code == 200
    gate = client.get("/api/releases/REL-CONTROL-1.0.0/gate").json()
    assert gate["status"] == "uat_ready"
    assert gate["production_allowed"] is False


def test_release_production_gate(client, db):
    client.post("/api/releases", json=release_payload(
        migration_tested=True, uat_approved=True, security_reviewed=True,
        backup_restore_tested=True, owner_approved=True,
    ))
    client.post("/api/releases/REL-CONTROL-1.0.0/artifacts", json={"artifact_id": "ART-ZIP", "artifact_type": "source_zip", "file_name": "release.zip", "cloud_status": "verified"})
    client.post("/api/releases/REL-CONTROL-1.0.0/artifacts", json={"artifact_id": "ART-SHA", "artifact_type": "sha256", "file_name": "sha256.txt", "cloud_status": "verified"})
    gate = client.get("/api/releases/REL-CONTROL-1.0.0/gate").json()
    assert gate["production_allowed"] is True
    assert gate["status"] == "production_ready"


def test_release_upsert_is_idempotent(client, db):
    client.post("/api/releases", json=release_payload())
    client.post("/api/releases", json=release_payload(tests_total=30, tests_passed=30))
    rows = db.scalars(select(ReleaseRecord)).all()
    assert len(rows) == 1
    assert rows[0].tests_total == 30


def test_artifact_upsert_is_idempotent(client, db):
    from app.models import ArtifactRecord
    client.post("/api/releases", json=release_payload())
    payload = {"artifact_id": "ART-ONE", "artifact_type": "source_zip", "file_name": "a.zip", "cloud_status": "pending"}
    client.post("/api/releases/REL-CONTROL-1.0.0/artifacts", json=payload)
    payload["cloud_status"] = "verified"
    client.post("/api/releases/REL-CONTROL-1.0.0/artifacts", json=payload)
    rows = db.scalars(select(ArtifactRecord)).all()
    assert len(rows) == 1 and rows[0].cloud_status == "verified"
