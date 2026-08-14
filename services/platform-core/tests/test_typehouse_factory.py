from __future__ import annotations

import hashlib

from sqlalchemy import select

from app.models import HouseVisionFactoryImportItem, HouseVisionRightsPolicy
from app.schemas import TypehouseArtifactIn, TypehouseJobIn, TypehouseQARunIn
from app.services.housevision import (
    AUTO_APPROVED_SOURCE_HOSTS,
    automatic_rights_grant_for_host,
    ensure_typehouse_auto_approved_rights,
)
from app.services.typehouse_factory import (
    REQUIRED_ARTIFACT_ROLES,
    create_job,
    create_source_import,
    dispatch_and_claim,
    import_status,
    process_job,
    record_qa_run,
    register_artifact,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_public_api_rejects_multi_house_payload(client):
    response = client.post(
        "/v1/type-house-jobs",
        headers={"Idempotency-Key": "multi-house-rejected"},
        json={
            "source_urls": ["https://example.com/a", "https://example.com/b"],
            "catalog_id": "factory-test",
            "rights_grant_id": "grant-test",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "SINGLE_HOUSE_REQUIRED"


def test_job_creation_is_idempotent_and_one_house(db):
    payload = TypehouseJobIn(
        source_url="https://example.com/typehouse-a",
        catalog_id="factory-test",
        rights_grant_id="grant-test",
    )
    first = create_job(db, payload, idempotency_key="stable-key", actor="generator")
    second = create_job(db, payload, idempotency_key="stable-key", actor="generator")
    assert first.job_id == second.job_id
    assert first.canonical_url == "https://example.com/typehouse-a"


def test_owner_directive_seeds_bare_and_www_auto_approved_domains(db):
    ensure_typehouse_auto_approved_rights(db)
    rows = list(
        db.scalars(
            select(HouseVisionRightsPolicy).where(
                HouseVisionRightsPolicy.grant_id.like("AUTO-RIGHTS-%")
            )
        )
    )
    assert {row.domain for row in rows} == set(AUTO_APPROVED_SOURCE_HOSTS)
    assert all(row.active for row in rows)
    assert all(row.owner_attestation_sha256 for row in rows)
    assert all(row.page_scope_sha256 for row in rows)


def test_api_uses_automatic_grant_for_approved_domain(client):
    response = client.post(
        "/v1/type-house-jobs",
        headers={"Idempotency-Key": "auto-approved-imperialholding"},
        json={
            "source_url": "https://imperialholding.hu/typehouse-auto-uat",
            "catalog_id": "auto-approved-test",
        },
    )
    assert response.status_code == 201
    assert response.json()["rights_grant_id"] == automatic_rights_grant_for_host(
        "imperialholding.hu"
    )


def test_auto_import_binds_each_domain_to_its_own_grant(db):
    ensure_typehouse_auto_approved_rights(db)
    row = create_source_import(
        db,
        catalog_id="mixed-auto-approved",
        rights_grant_id="auto",
        source_urls=[
            "https://imperialholding.hu/house-a",
            "https://www.prefab.hu/house-b",
        ],
        actor="tester",
    )
    items = list(
        db.scalars(
            select(HouseVisionFactoryImportItem)
            .where(HouseVisionFactoryImportItem.import_id == row.import_id)
            .order_by(HouseVisionFactoryImportItem.sequence)
        )
    )
    assert [item.rights_grant_id for item in items] == [
        automatic_rights_grant_for_host("imperialholding.hu"),
        automatic_rights_grant_for_host("www.prefab.hu"),
    ]


def test_extradom_auto_approval_does_not_relax_project_path_contract(client):
    response = client.post(
        "/v1/type-house-jobs",
        headers={"Idempotency-Key": "extradom-invalid-path"},
        json={
            "source_url": "https://extradom.pl/not-a-project-page",
            "catalog_id": "extradom-path-test",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "SOURCE_IDENTITY_FAIL"


def test_bulk_import_registers_thirty_without_combining_jobs(db):
    urls = [f"https://example.com/typehouse-{index:03d}" for index in range(30)]
    row = create_source_import(
        db,
        catalog_id="acceptance-thirty",
        rights_grant_id="grant-thirty",
        source_urls=urls,
        actor="tester",
        source_file_name="thirty.txt",
    )
    status = import_status(db, row.import_id)
    assert status["registered"] == 30
    assert status["generator_jobs_created"] == 0
    assert status["processing_mode"] == "SERIAL_SINGLE_HOUSE"


def test_bulk_import_accepts_one_thousand_queue_items(db):
    urls = [f"https://example.com/catalog/typehouse-{index:04d}" for index in range(1000)]
    row = create_source_import(
        db,
        catalog_id="durability-thousand",
        rights_grant_id="grant-thousand",
        source_urls=urls,
        actor="tester",
    )
    status = import_status(db, row.import_id)
    assert status["requested"] == 1000
    assert status["registered"] == 1000
    assert status["counts"] == {"PENDING": 1000}


def test_bulk_item_closes_against_existing_terminal_job(db):
    source_url = "https://example.com/already-reviewed"
    prior = create_job(
        db,
        TypehouseJobIn(
            source_url=source_url,
            catalog_id="existing-terminal",
            rights_grant_id="grant-existing",
        ),
        idempotency_key="existing-terminal-direct",
        actor="tester",
    )
    prior.status = "NEEDS_REVIEW"
    prior.stage = "HUMAN_VISUAL_REVIEW"
    prior.last_error_code = "HUMAN_VISUAL_REVIEW_REQUIRED"
    db.commit()
    imported = create_source_import(
        db,
        catalog_id="existing-terminal",
        rights_grant_id="grant-existing",
        source_urls=[source_url],
        actor="tester",
    )

    assert dispatch_and_claim(db, "worker-test") is None

    item = db.scalar(
        select(HouseVisionFactoryImportItem).where(
            HouseVisionFactoryImportItem.import_id == imported.import_id
        )
    )
    assert item is not None
    assert item.job_id == prior.job_id
    assert item.status == "NEEDS_REVIEW"
    assert item.terminal_reason == "HUMAN_VISUAL_REVIEW_REQUIRED"
    db.refresh(imported)
    assert imported.status == "COMPLETED"
    db.refresh(prior)
    assert prior.status == "NEEDS_REVIEW"


def test_worker_fails_closed_without_matching_rights_evidence(db):
    row = create_job(
        db,
        TypehouseJobIn(
            source_url="https://example.com/no-rights",
            catalog_id="rights-blocked",
            rights_grant_id="missing-grant",
        ),
        idempotency_key="rights-blocked",
        actor="generator",
    )
    claim = dispatch_and_claim(db, "worker-test")
    assert claim and claim[0] == row.job_id
    process_job(db, claim[0], "worker-test", claim[1])
    db.refresh(row)
    assert row.status == "BLOCKED"
    assert row.last_error_code == "RIGHTS_SCOPE_FAIL"


def test_same_manifest_needs_two_independent_full_qa_passes(db):
    source_url = "https://example.com/qa-house"
    row = create_job(
        db,
        TypehouseJobIn(
            source_url=source_url,
            catalog_id="qa-factory",
            rights_grant_id="qa-grant",
        ),
        idempotency_key="qa-house",
        actor="generator",
    )
    for role in sorted(REQUIRED_ARTIFACT_ROLES):
        width, height = (7680, 4320) if role == "master_8k" else (None, None)
        register_artifact(
            db,
            row.job_id,
            TypehouseArtifactIn(
                role=role,
                relative_path=f"{role}.bin",
                storage_ref=f"/app/data/qa/{role}.bin",
                mime_type="application/octet-stream",
                byte_size=100,
                width_px=width,
                height_px=height,
                sha256=_sha(role),
                source_page_url=source_url,
            ),
            actor="producer",
        )
    manifest = _sha("package_manifest")
    first = record_qa_run(
        db,
        row.job_id,
        TypehouseQARunIn(
            package_manifest_sha256=manifest,
            deterministic_pass=True,
            semantic_pass=True,
            semantic_score=99,
            verifier_id="verifier-a",
            verifier_model="vision-model-a",
        ),
        actor="orchestrator",
    )
    db.refresh(row)
    assert first.decision == "PASS"
    assert row.status == "QA_PASS_1"
    second = record_qa_run(
        db,
        row.job_id,
        TypehouseQARunIn(
            package_manifest_sha256=manifest,
            deterministic_pass=True,
            semantic_pass=True,
            semantic_score=99,
            verifier_id="verifier-b",
            verifier_model="vision-model-b",
        ),
        actor="orchestrator",
    )
    db.refresh(row)
    assert second.decision == "PASS"
    assert row.status == "COMPLETED"
    assert row.consecutive_passes == 2
