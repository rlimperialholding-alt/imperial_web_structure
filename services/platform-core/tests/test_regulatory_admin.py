from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.services.house_designer import ActorScope, apply_session_command, create_session
from app.services.house_designer_geometry import apply_command, empty_geometry
from app.services.regulatory_admin import (
    RegulatoryActor,
    RegulatoryAdminError,
    approve_source,
    create_interpretation,
    create_ruleset,
    create_source,
    revoke_source,
    transition_interpretation,
    transition_ruleset,
    verify_design_site,
)
from app.services.regulatory_compliance import run_compliance


def _verified_test_vector():
    geometry = apply_command(
        empty_geometry(10_000, 8_000),
        "set_roof",
        {"levelId": "L01", "roofType": "gable", "pitchDeg": 30},
    )
    return {
        "geometry": geometry,
        "site": {"verificationStatus": "verified"},
        "expectedOutcome": "PASS",
    }


def _approved_ruleset(db, *, source_key: str, scope_key: str = "HU:011:*"):
    author = RegulatoryActor(f"{source_key}-author", can_author=True, can_review=False)
    reviewer = RegulatoryActor(f"{source_key}-reviewer", can_author=False, can_review=True)
    now = datetime.now(UTC)
    source = create_source(
        db,
        actor=author,
        source_key=source_key,
        source_type="HESZ",
        issuer="Minta Önkormányzat",
        scope_key=scope_key,
        source_url=f"https://example.com/{source_key.lower()}.pdf",
        effective_from=now - timedelta(days=1),
        effective_to=None,
        content_sha256="a" * 64,
        normalized_text_sha256="b" * 64,
        storage_ref=f"drive:{source_key.lower()}-v1",
    )
    source = approve_source(
        db,
        actor=reviewer,
        source_snapshot_id=source["sourceSnapshotId"],
        row_version=source["rowVersion"],
    )
    interpretation = create_interpretation(
        db,
        actor=author,
        source_snapshot_id=source["sourceSnapshotId"],
        source_span="12. § (3)",
        rules={"maxStoreys": 2, "maxGrossAreaM2": 160, "allowedRoofTypes": ["gable"]},
        test_vectors=[_verified_test_vector()],
    )
    interpretation = transition_interpretation(
        db,
        actor=author,
        interpretation_id=interpretation["interpretationId"],
        row_version=interpretation["rowVersion"],
        action="submit_review",
    )
    interpretation = transition_interpretation(
        db,
        actor=reviewer,
        interpretation_id=interpretation["interpretationId"],
        row_version=interpretation["rowVersion"],
        action="approve",
    )
    ruleset = create_ruleset(
        db,
        actor=author,
        scope_key=scope_key,
        national_basis="TÉKA",
        local_plan_basis="HÉSZ teszt v1",
        effective_from=now - timedelta(days=1),
        effective_to=None,
        interpretation_ids=[interpretation["interpretationId"]],
    )
    ruleset = transition_ruleset(
        db,
        actor=author,
        ruleset_id=ruleset["rulesetId"],
        row_version=ruleset["rowVersion"],
        action="submit_review",
    )
    ruleset = transition_ruleset(
        db,
        actor=reviewer,
        ruleset_id=ruleset["rulesetId"],
        row_version=ruleset["rowVersion"],
        action="approve",
    )
    return author, reviewer, source, ruleset


def _verified_design(db, reviewer: RegulatoryActor, *, command_prefix: str):
    customer = ActorScope("customer", "imperial-holding", frozenset({"imperial"}))
    design = create_session(
        db,
        actor=customer,
        brand_id="imperial",
        title="Regulatory binding test",
        command_id=f"{command_prefix}-create",
    )
    revision = design["revision"]
    design = apply_session_command(
        db,
        session_id=design["sessionId"],
        actor=customer,
        base_revision_id=revision["revisionId"],
        base_canonical_sha256=revision["canonicalSha256"],
        command_id=f"{command_prefix}-roof",
        command_type="set_roof",
        payload={"levelId": "L01", "roofType": "gable", "pitchDeg": 30},
    )
    revision = design["revision"]
    design = apply_session_command(
        db,
        session_id=design["sessionId"],
        actor=customer,
        base_revision_id=revision["revisionId"],
        base_canonical_sha256=revision["canonicalSha256"],
        command_id=f"{command_prefix}-site",
        command_type="set_site",
        payload={"municipalityCode": "011", "parcelNumber": "12345/6"},
    )
    verify_design_site(
        db,
        actor=reviewer,
        tenant_id="imperial-holding",
        session_id=design["sessionId"],
        proof_ref=f"drive:{command_prefix}-proof",
        proof_sha256="c" * 64,
        verification_method="official_cadastral_extract",
        command_id=f"{command_prefix}-verify",
    )
    return design["sessionId"]


def test_governed_source_interpretation_ruleset_and_site_produce_pass(db):
    author = RegulatoryActor("reg-author", can_author=True, can_review=False)
    reviewer = RegulatoryActor("reg-reviewer", can_author=False, can_review=True)
    now = datetime.now(UTC)
    source = create_source(
        db,
        actor=author,
        source_key="HESZ-011",
        source_type="HESZ",
        issuer="Minta Önkormányzat",
        scope_key="HU:011:*",
        source_url="https://example.com/hesz-011.pdf",
        effective_from=now - timedelta(days=1),
        effective_to=None,
        content_sha256="a" * 64,
        normalized_text_sha256="b" * 64,
        storage_ref="drive:test-hesz-011-v1",
    )
    with pytest.raises(RegulatoryAdminError) as self_approval:
        approve_source(
            db,
            actor=RegulatoryActor("reg-author", can_author=True, can_review=True),
            source_snapshot_id=source["sourceSnapshotId"],
            row_version=source["rowVersion"],
        )
    assert self_approval.value.code == "four_eyes_required"
    db.rollback()
    source = approve_source(
        db,
        actor=reviewer,
        source_snapshot_id=source["sourceSnapshotId"],
        row_version=source["rowVersion"],
    )
    interpretation = create_interpretation(
        db,
        actor=author,
        source_snapshot_id=source["sourceSnapshotId"],
        source_span="12. § (3)",
        rules={
            "maxStoreys": 2,
            "maxGrossAreaM2": 160,
            "allowedRoofTypes": ["gable", "hip"],
        },
        test_vectors=[_verified_test_vector()],
    )
    interpretation = transition_interpretation(
        db,
        actor=author,
        interpretation_id=interpretation["interpretationId"],
        row_version=interpretation["rowVersion"],
        action="submit_review",
    )
    interpretation = transition_interpretation(
        db,
        actor=reviewer,
        interpretation_id=interpretation["interpretationId"],
        row_version=interpretation["rowVersion"],
        action="approve",
    )
    ruleset = create_ruleset(
        db,
        actor=author,
        scope_key="HU:011:*",
        national_basis="TÉKA",
        local_plan_basis="HÉSZ 12/2025 v1",
        effective_from=now - timedelta(days=1),
        effective_to=None,
        interpretation_ids=[interpretation["interpretationId"]],
    )
    ruleset = transition_ruleset(
        db,
        actor=author,
        ruleset_id=ruleset["rulesetId"],
        row_version=ruleset["rowVersion"],
        action="submit_review",
    )
    ruleset = transition_ruleset(
        db,
        actor=reviewer,
        ruleset_id=ruleset["rulesetId"],
        row_version=ruleset["rowVersion"],
        action="approve",
    )
    assert ruleset["status"] == "APPROVED"

    customer = ActorScope("customer", "imperial-holding", frozenset({"imperial"}))
    design = create_session(
        db,
        actor=customer,
        brand_id="imperial",
        title="Regulatory PASS house",
        command_id=str(uuid4()),
    )
    revision = design["revision"]
    design = apply_session_command(
        db,
        session_id=design["sessionId"],
        actor=customer,
        base_revision_id=revision["revisionId"],
        base_canonical_sha256=revision["canonicalSha256"],
        command_id=str(uuid4()),
        command_type="set_roof",
        payload={"levelId": "L01", "roofType": "gable", "pitchDeg": 30},
    )
    revision = design["revision"]
    design = apply_session_command(
        db,
        session_id=design["sessionId"],
        actor=customer,
        base_revision_id=revision["revisionId"],
        base_canonical_sha256=revision["canonicalSha256"],
        command_id=str(uuid4()),
        command_type="set_site",
        payload={"municipalityCode": "011", "parcelNumber": "12345/6"},
    )
    verification_command_id = str(uuid4())
    verification = verify_design_site(
        db,
        actor=reviewer,
        tenant_id="imperial-holding",
        session_id=design["sessionId"],
        proof_ref="drive:cadastral-proof-v1",
        proof_sha256="c" * 64,
        verification_method="official_cadastral_extract",
        command_id=verification_command_id,
    )
    replay = verify_design_site(
        db,
        actor=reviewer,
        tenant_id="imperial-holding",
        session_id=design["sessionId"],
        proof_ref="drive:cadastral-proof-v1",
        proof_sha256="c" * 64,
        verification_method="official_cadastral_extract",
        command_id=verification_command_id,
    )
    assert replay == verification
    with pytest.raises(RegulatoryAdminError) as collision:
        verify_design_site(
            db,
            actor=reviewer,
            tenant_id="imperial-holding",
            session_id=design["sessionId"],
            proof_ref="drive:different-proof",
            proof_sha256="d" * 64,
            verification_method="official_cadastral_extract",
            command_id=verification_command_id,
        )
    assert collision.value.code == "idempotency_collision"
    db.rollback()
    result = run_compliance(
        db,
        session_id=design["sessionId"],
        tenant_id="imperial-holding",
        actor_subject_id="reg-reviewer",
    )
    assert verification["verifiedRevisionId"]
    assert result["rulesetId"] == ruleset["rulesetId"]
    assert result["outcome"] == "PASS"


def test_interpretation_rejects_unproven_test_vector(db):
    author = RegulatoryActor("author", can_author=True, can_review=False)
    reviewer = RegulatoryActor("reviewer", can_author=False, can_review=True)
    source = create_source(
        db,
        actor=author,
        source_key="HESZ-FAIL",
        source_type="HESZ",
        issuer="Minta Önkormányzat",
        scope_key="HU:011:*",
        source_url="https://example.com/hesz-fail.pdf",
        effective_from=datetime.now(UTC),
        effective_to=None,
        content_sha256="d" * 64,
        normalized_text_sha256="e" * 64,
        storage_ref="drive:hesz-fail",
    )
    source = approve_source(
        db,
        actor=reviewer,
        source_snapshot_id=source["sourceSnapshotId"],
        row_version=source["rowVersion"],
    )
    vector = _verified_test_vector()
    vector["expectedOutcome"] = "FAIL"
    with pytest.raises(RegulatoryAdminError) as error:
        create_interpretation(
            db,
            actor=author,
            source_snapshot_id=source["sourceSnapshotId"],
            source_span="12. §",
            rules={"maxStoreys": 2},
            test_vectors=[vector],
        )
    assert error.value.code == "test_vector_failed"


def test_newer_or_inactive_source_blocks_new_compliance_pass(db):
    author, reviewer, source, ruleset = _approved_ruleset(db, source_key="HESZ-BINDING")
    session_id = _verified_design(db, reviewer, command_prefix="binding")

    initial = run_compliance(
        db,
        session_id=session_id,
        tenant_id="imperial-holding",
        actor_subject_id=reviewer.subject_id,
    )
    assert initial["rulesetId"] == ruleset["rulesetId"]
    assert initial["outcome"] == "PASS"

    create_source(
        db,
        actor=author,
        source_key="HESZ-BINDING",
        source_type="HESZ",
        issuer="Minta Önkormányzat",
        scope_key="HU:011:*",
        source_url="https://example.com/hesz-binding-v2.pdf",
        effective_from=datetime.now(UTC),
        effective_to=None,
        content_sha256="d" * 64,
        normalized_text_sha256="e" * 64,
        storage_ref="drive:hesz-binding-v2",
    )
    changed = run_compliance(
        db,
        session_id=session_id,
        tenant_id="imperial-holding",
        actor_subject_id=reviewer.subject_id,
    )
    assert changed["outcome"] == "UNKNOWN"
    assert changed["findings"][0]["code"] == "RULESET_CHANGED"

    revoked_source = revoke_source(
        db,
        actor=reviewer,
        source_snapshot_id=source["sourceSnapshotId"],
        row_version=source["rowVersion"],
    )
    assert revoked_source["status"] == "revoked"
    revoked = run_compliance(
        db,
        session_id=session_id,
        tenant_id="imperial-holding",
        actor_subject_id=reviewer.subject_id,
    )
    assert revoked["outcome"] == "UNKNOWN"
    assert revoked["findings"][0]["code"] == "RULESET_CHANGED"

    revoked_ruleset = transition_ruleset(
        db,
        actor=reviewer,
        ruleset_id=ruleset["rulesetId"],
        row_version=ruleset["rowVersion"],
        action="revoke",
    )
    assert revoked_ruleset["status"] == "REVOKED"
    after_ruleset_revoke = run_compliance(
        db,
        session_id=session_id,
        tenant_id="imperial-holding",
        actor_subject_id=reviewer.subject_id,
    )
    assert after_ruleset_revoke["outcome"] == "UNKNOWN"
    assert after_ruleset_revoke["findings"][0]["code"] == "RULESET_MISSING"
