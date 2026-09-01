from __future__ import annotations

import hashlib
import hmac
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter

import pytest
from sqlalchemy import select

from app.models import (
    HousePlanBatch,
    HousePlanRecord,
    HousePlanSource,
    HouseStudioPermissionGrant,
    User,
)
from app.routes.house_studio import _sample_rows
from app.services import house_plan_execution as execution_service
from app.services.house_batch import HouseBatchError, dry_run_batch
from app.services.house_catalog import ensure_house_catalog_seed, public_catalog
from app.services.house_geometry import canonical_json
from app.services.house_plan_execution import (
    NEAR_DUPLICATE_BLOCK,
    NEAR_DUPLICATE_WARNING,
    active_source_for_house,
    authorize_house_studio,
    block_source,
    create_source_revision,
    ensure_houseplan_source_cutover,
    execute_batch,
    ingest_signed_permission_replica,
    revoke_source,
    weighted_similarity,
)


def test_weighted_similarity_has_frozen_warning_and_block_boundaries():
    blocked = weighted_similarity(
        storey=Decimal("1"),
        ratio=Decimal("1"),
        counts=Decimal("1"),
        areas=Decimal("1"),
        adjacency=Decimal("0.88"),
    )
    warning = weighted_similarity(
        storey=Decimal("1"),
        ratio=Decimal("1"),
        counts=Decimal("1"),
        areas=Decimal("1"),
        adjacency=Decimal("0.8796"),
    )
    assert blocked == NEAR_DUPLICATE_BLOCK
    assert warning == Decimal("0.96990")
    assert NEAR_DUPLICATE_WARNING <= warning < NEAR_DUPLICATE_BLOCK


def test_weighted_similarity_rejects_out_of_range_components():
    with pytest.raises(ValueError, match="0 és 1"):
        weighted_similarity(
            storey=Decimal("1.01"),
            ratio=Decimal("1"),
            counts=Decimal("1"),
            areas=Decimal("1"),
            adjacency=Decimal("1"),
        )


def test_similarity_index_keeps_100_row_lookup_below_five_seconds(db):
    house = public_catalog(db)[0]
    ensure_houseplan_source_cutover(db, demo_auto_approve=True)
    source = active_source_for_house(db, house["house_id"])
    generated = execution_service.generate_houseplan(_sample_rows()[0], source)
    matching_features = execution_service._similarity_features(
        generated["normalizedInput"], generated["geometry"]
    )
    unrelated_features = deepcopy(matching_features)
    unrelated_features["adjacency"] = {"unrelated|outside"}
    index = execution_service._SimilarityIndex()
    for number in range(9_900):
        index.add(HousePlanRecord(plan_id=f"UNRELATED-{number}"), unrelated_features)
    matching_plan = HousePlanRecord(plan_id="MATCHING-PLAN")
    for number in range(100):
        index.add(
            matching_plan if number == 0 else HousePlanRecord(plan_id=f"MATCH-{number}"),
            matching_features,
        )

    started = perf_counter()
    for _ in range(100):
        nearest, score = execution_service._nearest_plan(
            db, generated, candidates=index
        )
        assert nearest is not None and score == Decimal("1.00000")
    assert perf_counter() - started < 5.0


def test_project_filtered_batches_are_selected_before_page_limit(db):
    house = public_catalog(db)[0]
    ensure_houseplan_source_cutover(db, demo_auto_approve=True)
    source = active_source_for_house(db, house["house_id"])
    now = datetime.now(UTC)

    def batch(number: int, project_id: str, created_at: datetime) -> HousePlanBatch:
        suffix = f"{number:064x}"
        return HousePlanBatch(
            batch_id=f"FILTER-BATCH-{number}",
            source_id=source["id"],
            source_revision=source["revision"],
            source_sha256=source["sha256"],
            actor_subject="ITEP-FILTER-TEST",
            permission_revision="itep-filter-test",
            pricing_revision="pricing-filter-test",
            ruleset_version="hb-grid-v1.0.0",
            batch_hash=suffix,
            request_sha256=suffix,
            request_json=canonical_json([{"project_id": project_id}]),
            idempotency_key=f"filter-batch-{number}",
            dry_run_token_sha256=suffix,
            status="completed",
            total_count=1,
            created_at=created_at,
            completed_at=created_at,
        )

    db.add(
        batch(
            10_000,
            "TARGET-PROJECT",
            now - timedelta(days=1),
        )
    )
    db.add_all(
        [batch(number, "OTHER-PROJECT", now + timedelta(seconds=number)) for number in range(101)]
    )
    db.commit()

    workspace = execution_service.house_studio_workspace(
        db, project_id="TARGET-PROJECT"
    )
    assert [row.batch_id for row in workspace["batches"]] == ["FILTER-BATCH-10000"]


def test_signed_itep_permission_replica_binds_identity_and_is_replay_safe(db):
    ensure_house_catalog_seed(db)
    now = datetime.now(UTC)
    payload = {
        "issuer": "itep",
        "subjectId": "ITEP-DESIGNER-SIGNED",
        "email": "designer@imperial.local",
        "revision": "itep-r42",
        "sequence": 42,
        "validFrom": (now - timedelta(minutes=1)).isoformat(),
        "expiresAt": (now + timedelta(hours=1)).isoformat(),
        "grants": [
            {
                "permission": "ii.houseplan.read",
                "effect": "allow",
                "scopeType": "global",
            },
            {
                "permission": "ii.house-designer.read",
                "effect": "allow",
                "scopeType": "global",
            },
        ],
    }
    secret = "test-itep-permission-replica-secret-at-least-32-bytes"
    signature = hmac.new(
        secret.encode(), canonical_json(payload).encode(), hashlib.sha256
    ).hexdigest()
    with pytest.raises(PermissionError, match="signature"):
        ingest_signed_permission_replica(db, payload=payload, signature="0" * 64, secret=secret)
    assert (
        ingest_signed_permission_replica(db, payload=payload, signature=signature, secret=secret)
        == 2
    )
    assert (
        ingest_signed_permission_replica(db, payload=payload, signature=signature, secret=secret)
        == 0
    )
    user = db.scalar(select(User).where(User.email == "designer@imperial.local"))
    assert user and user.itep_subject_id == "ITEP-DESIGNER-SIGNED"
    grant = db.scalar(
        select(HouseStudioPermissionGrant).where(
            HouseStudioPermissionGrant.subject_id == "ITEP-DESIGNER-SIGNED",
            HouseStudioPermissionGrant.permission == "ii.house-designer.read",
        )
    )
    assert grant and grant.claim_issuer == "itep" and grant.revision == "itep-r42"
    assert grant.claim_sequence == 42 and grant.effect == "allow"

    stale = {**payload, "revision": "itep-r41", "sequence": 41}
    stale_signature = hmac.new(
        secret.encode(), canonical_json(stale).encode(), hashlib.sha256
    ).hexdigest()
    with pytest.raises(ValueError, match="rollback"):
        ingest_signed_permission_replica(
            db, payload=stale, signature=stale_signature, secret=secret
        )

    denied = {
        **payload,
        "revision": "itep-r43",
        "sequence": 43,
        "grants": [
            {
                "permission": "ii.houseplan.read",
                "effect": "allow",
                "scopeType": "global",
            },
            {
                "permission": "ii.houseplan.read",
                "effect": "deny",
                "scopeType": "project",
                "projectId": "HOUSE-CATALOG-GOVERNANCE",
            },
        ],
    }
    denied_signature = hmac.new(
        secret.encode(), canonical_json(denied).encode(), hashlib.sha256
    ).hexdigest()
    assert (
        ingest_signed_permission_replica(
            db, payload=denied, signature=denied_signature, secret=secret
        )
        == 2
    )
    with pytest.raises(PermissionError, match="deny"):
        authorize_house_studio(
            db,
            user,
            "ii.houseplan.read",
            project_id="HOUSE-CATALOG-GOVERNANCE",
        )
    with pytest.raises(PermissionError, match="explicit project_id"):
        authorize_house_studio(db, user, "ii.houseplan.read")


def test_production_source_cutover_quarantines_without_legal_attestation(db):
    ensure_house_catalog_seed(db)
    inserted = ensure_houseplan_source_cutover(db, demo_auto_approve=False)
    assert inserted > 0
    source = db.scalar(select(HousePlanSource))
    assert source is not None
    assert source.status == "rights_review"
    assert source.legal_basis == "unknown"
    assert source.approved_by_subject is None
    assert source.created_by_subject == "MIGRATION-QUARANTINE"
    blocked = block_source(db, source.source_id, "ITEP-LEGAL-REVIEWER", "Evidence missing")
    assert blocked.status == "blocked"


def test_unexpected_batch_failure_is_recoverable_not_left_running(db, monkeypatch):
    house = public_catalog(db)[0]
    ensure_houseplan_source_cutover(db, demo_auto_approve=True)
    source = active_source_for_house(db, house["house_id"])
    rows = _sample_rows()
    rows[0]["project_id"] = "HOUSE-CATALOG-GOVERNANCE"
    actor = "ITEP-TEST-BATCH-ACTOR"
    revision = "itep-permissions:test"
    pricing = "preview:no-pricing:v1"
    preview = dry_run_batch(
        rows,
        source=source,
        actor_subject=actor,
        permission_revision=revision,
        pricing_revision=pricing,
        secret="test-session-secret-which-is-long-enough",
        execution_allowed=True,
    )
    monkeypatch.setattr(
        "app.services.house_plan_execution.generate_houseplan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    with pytest.raises(RuntimeError, match="database unavailable"):
        execute_batch(
            db,
            rows=rows,
            source=source,
            actor_subject=actor,
            permission_revision=revision,
            pricing_revision=pricing,
            dry_run_token=preview["dryRunToken"],
            idempotency_key="recoverable-batch-failure",
            secret="test-session-secret-which-is-long-enough",
            authorized_project_ids={"HOUSE-CATALOG-GOVERNANCE"},
        )
    batch = db.scalar(
        select(HousePlanBatch).where(HousePlanBatch.idempotency_key == "recoverable-batch-failure")
    )
    assert batch and batch.status == "failed" and batch.completed_at is not None

    monkeypatch.setattr(
        "app.services.house_plan_execution._execute_batch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(HouseBatchError("idempotency_in_progress")),
    )
    with pytest.raises(HouseBatchError, match="idempotency_in_progress"):
        execute_batch(
            db,
            rows=rows,
            source=source,
            actor_subject=actor,
            permission_revision=revision,
            pricing_revision=pricing,
            dry_run_token=preview["dryRunToken"],
            idempotency_key="concurrent-running-batch",
            secret="test-session-secret-which-is-long-enough",
            authorized_project_ids={"HOUSE-CATALOG-GOVERNANCE"},
        )
    assert (
        db.scalar(
            select(HousePlanBatch).where(
                HousePlanBatch.idempotency_key == "concurrent-running-batch"
            )
        )
        is None
    )

    monkeypatch.undo()
    race_house = public_catalog(db)[1]
    race_source = active_source_for_house(db, race_house["house_id"])
    race_rows = _sample_rows()
    race_rows[0]["project_id"] = "HOUSE-CATALOG-GOVERNANCE"
    race_rows[0]["name"] = "Source revoke race"
    race_preview = dry_run_batch(
        race_rows,
        source=race_source,
        actor_subject=actor,
        permission_revision=revision,
        pricing_revision=pricing,
        secret="test-session-secret-which-is-long-enough",
        execution_allowed=True,
    )
    original_lock = execution_service._lock_executable_source
    calls = 0

    def revoke_before_first_row(session, snapshot):
        nonlocal calls
        calls += 1
        if calls == 2:
            revoke_source(
                session,
                snapshot["id"],
                "ITEP-LEGAL-RACE-TEST",
                "Concurrent legal revoke",
            )
        return original_lock(session, snapshot)

    monkeypatch.setattr(execution_service, "_lock_executable_source", revoke_before_first_row)
    race_result = execute_batch(
        db,
        rows=race_rows,
        source=race_source,
        actor_subject=actor,
        permission_revision=revision,
        pricing_revision=pricing,
        dry_run_token=race_preview["dryRunToken"],
        idempotency_key="source-revoke-race-batch",
        secret="test-session-secret-which-is-long-enough",
        authorized_project_ids={"HOUSE-CATALOG-GOVERNANCE"},
    )
    assert race_result["status"] == "failed"
    assert race_result["counts"]["created"] == 0
    assert race_result["results"][0]["errorCode"] == "source_not_executable"

    monkeypatch.undo()
    revision_house = public_catalog(db)[2]
    revision_source = active_source_for_house(db, revision_house["house_id"])
    revision_rows = _sample_rows()
    revision_rows[0]["project_id"] = "HOUSE-CATALOG-GOVERNANCE"
    revision_rows[0]["name"] = "New source revision race"
    revision_preview = dry_run_batch(
        revision_rows,
        source=revision_source,
        actor_subject=actor,
        permission_revision=revision,
        pricing_revision=pricing,
        secret="test-session-secret-which-is-long-enough",
        execution_allowed=True,
    )
    original_lock = execution_service._lock_executable_source
    calls = 0

    def create_revision_before_first_row(session, snapshot):
        nonlocal calls
        calls += 1
        if calls == 2:
            create_source_revision(
                session,
                catalog_version_id=revision_house["catalog_version_id"],
                legal_basis="licensed",
                licence_scope="Concurrent legal review",
                evidence_ref="test:new-source-race",
                evidence_sha256="c" * 64,
                actor_subject="ITEP-RIGHTS-RACE-CREATOR",
            )
        return original_lock(session, snapshot)

    monkeypatch.setattr(
        execution_service,
        "_lock_executable_source",
        create_revision_before_first_row,
    )
    revision_race_result = execute_batch(
        db,
        rows=revision_rows,
        source=revision_source,
        actor_subject=actor,
        permission_revision=revision,
        pricing_revision=pricing,
        dry_run_token=revision_preview["dryRunToken"],
        idempotency_key="source-new-revision-race-batch",
        secret="test-session-secret-which-is-long-enough",
        authorized_project_ids={"HOUSE-CATALOG-GOVERNANCE"},
    )
    assert revision_race_result["status"] == "failed"
    assert revision_race_result["counts"]["created"] == 0
    assert "not_latest_revision" in revision_race_result["results"][0]["message"]
