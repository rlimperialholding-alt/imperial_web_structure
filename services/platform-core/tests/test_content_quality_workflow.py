from __future__ import annotations

import json

import pytest
from copy_gate_fixtures import (
    editorial_review,
    generation_trace,
    imperial_asset,
    imperial_brief,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.copy_gate.models import (
    ApprovalSubmission,
    Decision,
    FourGateSubmission,
    PublicationState,
)
from app.models import (
    AuditLog,
    ContentAssetRecord,
    ContentGateDecision,
    OutboxMessage,
    TaskRecord,
)
from app.services.content_quality import (
    create_content_asset,
    create_copy_brief,
    publish_content_asset,
    record_approval,
    rollback_content_asset,
    run_copy_quality,
    submit_four_gates,
)


def create_pilot(db, *, suffix: str = "001"):
    brief = imperial_brief(copy_brief_id=f"CB-IMP-{suffix}")
    asset_payload = imperial_asset(asset_id=f"ASSET-IMP-{suffix}")
    brief_row = create_copy_brief(db, brief.model_dump(mode="json"), actor="pilot@imperial.local")
    asset = create_content_asset(
        db,
        asset_payload,
        copy_brief_id=brief_row.copy_brief_id,
        project_id="PRJ-DEMO-001",
        generation_trace=generation_trace(),
        actor="pilot@imperial.local",
    )
    return asset


def test_full_content_factory_to_four_gates_to_human_approvals_to_publish(db):
    asset = create_pilot(db)
    run = run_copy_quality(db, asset.asset_id, editorial_review(), actor="quality-worker")
    assert run.total_score >= 92
    assert run.final_decision == Decision.APPROVED

    aggregate = submit_four_gates(
        db,
        asset.asset_id,
        FourGateSubmission(
            legal_relevant=False,
            financial_relevant=False,
            technical_relevant=False,
        ),
        actor="gate-orchestrator",
    )
    assert aggregate["decision"] == Decision.APPROVED
    assert aggregate["state"] == PublicationState.HUMAN_EDITORIAL

    with pytest.raises(ValueError, match="állapotból"):
        publish_content_asset(db, asset.asset_id, actor="owner@imperial.local")

    record_approval(
        db,
        asset.asset_id,
        "HUMAN_EDITORIAL",
        ApprovalSubmission(decision="APPROVED", note="Nyelvi és márka review kész."),
        actor="editor@imperial.local",
    )
    with pytest.raises(ValueError, match="jóváhagyás"):
        publish_content_asset(db, asset.asset_id, actor="owner@imperial.local")

    record_approval(
        db,
        asset.asset_id,
        "OWNER",
        ApprovalSubmission(decision="APPROVED", note="Üzleti jóváhagyás."),
        actor="owner@imperial.local",
    )
    proof = publish_content_asset(db, asset.asset_id, actor="owner@imperial.local")

    refreshed = db.scalar(
        select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset.asset_id)
    )
    assert refreshed.state == PublicationState.PUBLISHED
    assert proof["external_delivery_enabled"] is False
    assert proof["publication_proof_id"] == refreshed.publication_proof_id
    assert db.scalars(select(AuditLog).where(AuditLog.entity_id == asset.asset_id)).all()

    rolled_back = rollback_content_asset(
        db,
        asset.asset_id,
        actor="owner@imperial.local",
        reason="Visszavont ajánlatverzió.",
    )
    assert rolled_back.state == PublicationState.DRAFT
    assert rolled_back.publication_proof_id is None
    assert rolled_back.content_version == 2


def test_relevant_specialist_gate_without_result_escalates_and_notifies(db):
    asset = create_pilot(db, suffix="002")
    run_copy_quality(db, asset.asset_id, editorial_review(), actor="quality-worker")

    aggregate = submit_four_gates(
        db,
        asset.asset_id,
        FourGateSubmission(
            legal_relevant=True,
            financial_relevant=True,
            technical_relevant=True,
        ),
        actor="gate-orchestrator",
    )

    assert aggregate["decision"] == Decision.HUMAN_APPROVAL_REQUIRED
    assert aggregate["state"] == PublicationState.FOUR_GATE_QA
    assert (
        len(db.scalars(select(TaskRecord).where(TaskRecord.task_id.like("TASK-CQ-%"))).all()) == 3
    )
    assert (
        len(
            db.scalars(
                select(OutboxMessage).where(
                    OutboxMessage.destination_module == "email-notification"
                )
            ).all()
        )
        == 3
    )


def test_database_check_constraint_rejects_unapproved_published_state(db):
    asset = create_pilot(db, suffix="003")
    asset.state = PublicationState.PUBLISHED
    asset.published_at = None
    asset.publication_proof_id = None

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_gate_decisions_keep_agent_contracts_and_source_versions(db):
    asset = create_pilot(db, suffix="004")
    run_copy_quality(db, asset.asset_id, editorial_review(), actor="quality-worker")
    submit_four_gates(
        db,
        asset.asset_id,
        FourGateSubmission(
            legal_relevant=False,
            financial_relevant=False,
            technical_relevant=False,
        ),
        actor="gate-orchestrator",
    )
    gates = db.scalars(
        select(ContentGateDecision).where(ContentGateDecision.asset_id == asset.asset_id)
    ).all()
    by_gate = {gate.gate_id: gate for gate in gates}
    assert by_gate["GATE_1_MARKETING_QUALITY"].agent_id == "AGT-017"
    assert json.loads(by_gate["GATE_1_MARKETING_QUALITY"].source_versions_json)["brand_master"]
    assert by_gate["GATE_2_LEGAL_POLICY"].agent_id == "AGT-016"
    assert by_gate["GATE_3_FINANCIAL_COMMERCIAL"].agent_id == "AGT-011"
    assert by_gate["GATE_4_TECHNICAL_FACTUAL"].agent_id == "AGT-013"
