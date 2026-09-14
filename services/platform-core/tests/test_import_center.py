from __future__ import annotations

from sqlalchemy import select

from app.models import EnterpriseCanonicalRecord, ImportJob, ProjectFact, ProjectRegistry, StagedEnterpriseRecord


def test_enterprise_import_process_commit_and_rollback(client, db):
    response = client.post("/api/imports/jobs", json={
        "source_key": "google_sheets_enterprise",
        "name": "Pénzügyi és projekt legacy import",
        "domain_hint": "enterprise",
        "requested_by": "test",
    })
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    records = [
        {
            "Projektazonosító": "IMP-TEST-001",
            "Projekt": "Teszt családi ház",
            "Ügyfél": "Minta Megrendelő",
            "Státusz": "szerkezetépítés",
            "Határidő": "2026-10-20",
        },
        {
            "Projektazonosító": "IMP-TEST-001",
            "Számlaszám": "SZLA-2026-001",
            "Cégnév": "Minta Beszállító Kft.",
            "Adószám": "12345678-2-41",
            "Nettó": 1_000_000,
            "Bruttó": 1_270_000,
            "Esedékesség": "2026-08-15",
        },
    ]
    item_response = client.post(f"/api/imports/jobs/{job_id}/items", json={
        "file_name": "legacy.xlsx", "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "content": {"records": records},
    })
    assert item_response.status_code == 200

    process_response = client.post(f"/api/imports/jobs/{job_id}/process")
    assert process_response.status_code == 200
    assert process_response.json()["records_extracted"] == 2

    staged = db.scalars(select(StagedEnterpriseRecord).where(StagedEnterpriseRecord.job_id == job_id)).all()
    assert {row.domain for row in staged} >= {"project", "finance"}
    assert all(row.project_id == "IMP-TEST-001" for row in staged)

    for row in staged:
        review = client.post(f"/api/imports/staged/{row.staged_id}/review", json={"review_status": "approved"})
        assert review.status_code == 200

    committed = client.post(f"/api/imports/jobs/{job_id}/commit", json={"staged_ids": [], "actor": "test"})
    assert committed.status_code == 200
    batch_id = committed.json()["batch_id"]
    assert committed.json()["committed_count"] == 2

    db.expire_all()
    assert db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == "IMP-TEST-001")) is not None
    assert len(db.scalars(select(ProjectFact).where(ProjectFact.project_id == "IMP-TEST-001")).all()) == 2
    assert len(db.scalars(select(EnterpriseCanonicalRecord)).all()) == 2

    rolled = client.post(f"/api/imports/batches/{batch_id}/rollback")
    assert rolled.status_code == 200
    assert rolled.json()["rollback_count"] == 2
    db.expire_all()
    assert len(db.scalars(select(EnterpriseCanonicalRecord)).all()) == 0
    # The audit-oriented project facts remain as source history; canonical records are rolled back.


def test_connector_push_classifies_partner(client, db):
    response = client.post("/api/imports/push", json={
        "source_key": "gmail_enterprise",
        "external_id": "gmail-message-1",
        "file_name": "partner-level.txt",
        "text": "Kapcsolattartó: Kovács Péter, e-mail: peter@example.hu, telefon: +36 30 123 4567, adószám 12345678-2-41",
        "metadata": {"thread_id": "thread-1"},
    })
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    row = db.scalar(select(StagedEnterpriseRecord).where(StagedEnterpriseRecord.job_id == job_id))
    assert row is not None
    assert row.domain == "partner"
    assert row.target_module == "partner_connect"
