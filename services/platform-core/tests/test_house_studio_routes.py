from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import (
    HouseBuildCase,
    HouseBuildVariant,
    HousePlanBatch,
    HousePlanRecord,
    HousePlanSource,
    TaskRecord,
)
from app.routes.house_studio import _parse_budapest_datetime_local, _sample_rows
from app.services.house_batch import HouseBatchError
from app.services.house_catalog import public_catalog
from app.services.house_plan_execution import (
    active_source_for_house,
    approve_source,
    create_source_revision,
    revoke_source,
)


def _csrf(client) -> str:
    page = client.get("/house-studio")
    assert page.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match
    return match.group(1)


def test_budapest_datetime_local_rejects_dst_gap_and_fold():
    with pytest.raises(ValueError, match="nem létezik"):
        _parse_budapest_datetime_local("2026-03-29T02:30")
    with pytest.raises(ValueError, match="kétértelmű"):
        _parse_budapest_datetime_local("2026-10-25T02:30")
    assert _parse_budapest_datetime_local("2026-07-01T10:00") == datetime(
        2026, 7, 1, 8, 0, tzinfo=UTC
    )


def test_house_studio_screen_and_signed_dry_run_are_operational(logged_in_client, db):
    page = logged_in_client.get("/house-studio")
    assert page.status_code == 200
    assert "Kötegelt típusház-generátor" in page.text
    assert "1–100 terv ellenőrzése írás nélkül" in page.text
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match
    csrf_token = match.group(1)

    source = public_catalog(db)[0]
    response = logged_in_client.post(
        "/house-studio/dry-run",
        data={
            "csrf_token": csrf_token,
            "source_house_id": source["house_id"],
            "batch_json": json.dumps(_sample_rows(), ensure_ascii=False),
        },
    )
    assert response.status_code == 200
    assert "data-geometry-signature" in response.text
    assert "Batch SHA-256" in response.text
    assert "geometry_validation_failed" not in response.text

    missing_csrf = logged_in_client.post(
        "/house-studio/dry-run",
        data={
            "source_house_id": source["house_id"],
            "batch_json": json.dumps(_sample_rows(), ensure_ascii=False),
        },
    )
    assert missing_csrf.status_code == 403


def test_project_scope_is_fail_closed(logged_in_client, db):
    source = logged_in_client.get("/house-studio")
    assert source.status_code == 200
    catalog = public_catalog(db)
    rows = _sample_rows()
    rows[0]["project_id"] = "NON-EXISTENT-PROJECT"
    response = logged_in_client.post(
        "/api/house-studio/dry-run",
        json={"source_house_id": catalog[0]["house_id"], "rows": rows},
    )
    assert response.status_code == 403


def test_execute_is_persistent_idempotent_and_requires_four_eyes(logged_in_client, db):
    csrf = _csrf(logged_in_client)
    source = public_catalog(db)[0]
    rows = _sample_rows()
    rows[0]["project_id"] = "HOUSE-CATALOG-GOVERNANCE"
    rows[0]["name"] = "Imperial 126 tesztterv"
    dry_run = logged_in_client.post(
        "/api/house-studio/dry-run",
        json={"source_house_id": source["house_id"], "rows": rows},
    )
    assert dry_run.status_code == 200
    preview = dry_run.json()
    assert preview["executionAllowed"] is True
    payload = {
        "source_house_id": source["house_id"],
        "rows": rows,
        "dry_run_token": preview["dryRunToken"],
        "idempotency_key": "houseplan-route-test-001",
    }
    missing_csrf = logged_in_client.post("/api/house-studio/execute", json=payload)
    assert missing_csrf.status_code == 403
    text_plain = logged_in_client.post(
        "/api/house-studio/execute",
        content=json.dumps(payload),
        headers={"Content-Type": "text/plain", "X-CSRF-Token": csrf},
    )
    assert text_plain.status_code == 415
    executed = logged_in_client.post(
        "/api/house-studio/execute",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert executed.status_code == 200
    result = executed.json()
    assert result["status"] == "completed"
    assert result["counts"] == {
        "total": 1,
        "created": 1,
        "invalid": 0,
        "duplicate": 0,
        "blocked": 0,
    }
    plan_id = result["results"][0]["planId"]
    plan = db.scalar(select(HousePlanRecord).where(HousePlanRecord.plan_id == plan_id))
    assert plan is not None
    assert plan.status == "plancheck_review"
    plan_page = logged_in_client.get(f"/house-studio/plans/{plan_id}")
    assert plan_page.status_code == 200
    assert "houseplan_created" in plan_page.text
    assert db.scalar(
        select(HouseBuildCase).where(HouseBuildCase.case_id == plan.housebuild_case_id)
    )
    assert db.scalar(
        select(HouseBuildVariant).where(HouseBuildVariant.variant_id == plan.housebuild_variant_id)
    )
    assert db.scalar(select(TaskRecord).where(TaskRecord.task_id == plan.plancheck_task_id))
    replay = logged_in_client.post(
        "/api/house-studio/execute", json=payload, headers={"X-CSRF-Token": csrf}
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert db.scalar(select(HousePlanBatch).where(HousePlanBatch.batch_id == result["batchId"]))
    batch_page = logged_in_client.get(f"/house-studio/batches/{result['batchId']}")
    assert batch_page.status_code == 200
    assert "Soronkénti végrehajtási napló" in batch_page.text
    assert plan_id in batch_page.text
    filtered = logged_in_client.get(
        "/house-studio",
        params={
            "project_id": "HOUSE-CATALOG-GOVERNANCE",
            "batch_status": "completed",
            "plan_status": "plancheck_review",
        },
    )
    assert filtered.status_code == 200
    assert result["batchId"] in filtered.text
    assert plan_id in filtered.text
    duplicate_preview = logged_in_client.post(
        "/api/house-studio/dry-run",
        json={"source_house_id": source["house_id"], "rows": rows},
    )
    assert duplicate_preview.status_code == 200
    assert duplicate_preview.json()["counts"] == {
        "ready": 0,
        "invalid": 0,
        "duplicate": 1,
        "blocked": 0,
    }
    self_review = logged_in_client.post(
        f"/api/house-studio/plans/{plan_id}/review",
        headers={"If-Match": 'W/"1"', "X-CSRF-Token": csrf},
        json={"decision": "approve"},
    )
    assert self_review.status_code == 409

    login = logged_in_client.post(
        "/login",
        data={
            "email": "technical-prep@imperial.local",
            "password": "Imperial2026!",
        },
        follow_redirects=False,
    )
    assert login.status_code == 303
    csrf = _csrf(logged_in_client)
    approved = logged_in_client.post(
        f"/api/house-studio/plans/{plan_id}/review",
        headers={"If-Match": 'W/"1"', "X-CSRF-Token": csrf},
        json={"decision": "approve"},
    )
    assert approved.status_code == 200
    assert approved.json() == {"planId": plan_id, "status": "approved", "rowVersion": 2}

    version_rows = _sample_rows()
    version_rows[0]["project_id"] = "HOUSE-CATALOG-GOVERNANCE"
    version_rows[0]["family_id"] = plan.family_id
    version_rows[0]["gross_area_m2"] = "128"
    version_rows[0]["name"] = "Imperial 128 tesztterv v2"
    version_preview = logged_in_client.post(
        "/api/house-studio/dry-run",
        json={"source_house_id": source["house_id"], "rows": version_rows},
    ).json()
    version_execute = logged_in_client.post(
        "/api/house-studio/execute",
        json={
            "source_house_id": source["house_id"],
            "rows": version_rows,
            "dry_run_token": version_preview["dryRunToken"],
            "idempotency_key": "houseplan-route-version-002",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert version_execute.status_code == 200
    version_plan_id = version_execute.json()["results"][0]["planId"]
    version_plan = db.scalar(
        select(HousePlanRecord).where(HousePlanRecord.plan_id == version_plan_id)
    )
    assert version_plan is not None
    assert version_plan.version_number == 2
    assert version_plan.predecessor_plan_id == plan_id
    comparison_page = logged_in_client.get(f"/house-studio/plans/{version_plan_id}")
    assert comparison_page.status_code == 200
    assert plan_id in comparison_page.text
    assert "v2" in comparison_page.text

    source_id = plan.source_id
    revoked = revoke_source(db, source_id, "ITEP-LEGAL-REVIEWER", "Jogosulti visszavonás.")
    assert revoked.status == "revoked"
    db.refresh(plan)
    assert plan.status == "rights_recheck"
    db.refresh(version_plan)
    assert version_plan.status == "rights_recheck"
    audit_page = logged_in_client.get(f"/house-studio/plans/{version_plan_id}")
    assert "houseplan_rights_recheck_required" in audit_page.text
    with pytest.raises(HouseBatchError, match="revoked"):
        active_source_for_house(db, source["house_id"])

    other_source = next(
        item for item in public_catalog(db) if item["house_id"] != source["house_id"]
    )
    revision = create_source_revision(
        db,
        catalog_version_id=other_source["catalog_version_id"],
        legal_basis="licensed",
        licence_scope="Belső tervezés és ügyfélprojekt.",
        evidence_ref="drive:test-rights-evidence",
        evidence_sha256="b" * 64,
        actor_subject="ITEP-SOURCE-CREATOR",
    )
    with pytest.raises(PermissionError, match="saját"):
        approve_source(db, revision.source_id, "ITEP-SOURCE-CREATOR")
    approved_source = approve_source(db, revision.source_id, "ITEP-LEGAL-REVIEWER")
    assert approved_source.status == "approved"


def test_plan_approval_rechecks_source_expiry_and_persists_rights_hold(logged_in_client, db):
    csrf = _csrf(logged_in_client)
    source = public_catalog(db)[0]
    rows = _sample_rows()
    rows[0]["project_id"] = "HOUSE-CATALOG-GOVERNANCE"
    rows[0]["name"] = "LejĂˇrĂł forrĂˇs tesztterv"
    preview = logged_in_client.post(
        "/api/house-studio/dry-run",
        json={"source_house_id": source["house_id"], "rows": rows},
    ).json()
    executed = logged_in_client.post(
        "/api/house-studio/execute",
        json={
            "source_house_id": source["house_id"],
            "rows": rows,
            "dry_run_token": preview["dryRunToken"],
            "idempotency_key": "houseplan-expired-source-review",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert executed.status_code == 200
    plan_id = executed.json()["results"][0]["planId"]
    plan = db.scalar(select(HousePlanRecord).where(HousePlanRecord.plan_id == plan_id))
    assert plan is not None
    rights = db.scalar(select(HousePlanSource).where(HousePlanSource.source_id == plan.source_id))
    assert rights is not None
    rights.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    logged_in_client.post(
        "/login",
        data={"email": "technical-prep@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    csrf = _csrf(logged_in_client)
    reviewed = logged_in_client.post(
        f"/api/house-studio/plans/{plan_id}/review",
        headers={"If-Match": 'W/"1"', "X-CSRF-Token": csrf},
        json={"decision": "approve"},
    )
    assert reviewed.status_code == 422
    db.expire_all()
    persisted_plan = db.scalar(select(HousePlanRecord).where(HousePlanRecord.plan_id == plan_id))
    persisted_rights = db.scalar(
        select(HousePlanSource).where(HousePlanSource.source_id == plan.source_id)
    )
    assert persisted_plan and persisted_plan.status == "rights_recheck"
    assert persisted_rights and persisted_rights.status == "expired"
