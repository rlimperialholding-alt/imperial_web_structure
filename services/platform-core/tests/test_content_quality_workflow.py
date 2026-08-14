from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest
from copy_gate_fixtures import (
    assembly_submission,
    campaign_package,
    creative_director_review,
    editorial_review,
    generation_trace,
    imperial_asset,
    imperial_brief,
    live_review,
    mandatory_copy_gate_review,
    release_review,
    strategy_review,
    visual_submission,
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
    ContentWorkflowReviewRecord,
    OutboxMessage,
    PublicationDelivery,
    TaskRecord,
)
from app.services.content_quality import (
    _delivery_targets,
    assemble_publication_bundle,
    create_content_asset,
    create_copy_brief,
    publish_content_asset,
    record_approval,
    record_campaign_package_gate,
    record_creative_director_review,
    record_live_publication_review,
    record_mandatory_copy_gate_review,
    record_release_review,
    record_strategy_review,
    rollback_content_asset,
    run_copy_quality,
    submit_four_gates,
    submit_visual_production,
)
from app.services.integration import process_outbox


def pass_mandatory_copy_gates(db, asset):
    record_mandatory_copy_gate_review(
        db,
        asset.asset_id,
        mandatory_copy_gate_review(asset, "MARKETING"),
        actor="marketing-gate-verifier",
    )
    record_mandatory_copy_gate_review(
        db,
        asset.asset_id,
        mandatory_copy_gate_review(asset, "DIRECT_RESPONSE"),
        actor="copywriter-gate-verifier",
    )


def create_pilot(db, *, suffix: str = "001"):
    brief = imperial_brief(copy_brief_id=f"CB-IMP-{suffix}")
    asset_payload = imperial_asset(asset_id=f"ASSET-IMP-{suffix}")
    brief_row = create_copy_brief(db, brief.model_dump(mode="json"), actor="pilot@imperial.local")
    record_strategy_review(
        db,
        brief_row.copy_brief_id,
        strategy_review(),
        actor="strategy-reviewer@imperial.local",
    )
    asset = create_content_asset(
        db,
        asset_payload,
        copy_brief_id=brief_row.copy_brief_id,
        project_id="PRJ-DEMO-001",
        generation_trace=generation_trace(),
        actor="pilot@imperial.local",
    )
    return asset


def test_publication_adapter_contract_maps_meta_and_google_ads_targets():
    assert _delivery_targets(
        [
            {"platform": "facebook"},
            {"platform": "instagram"},
            {"platform": "google_ads"},
        ]
    ) == ["GOOGLE_ADS", "META_ADS"]


def test_full_content_factory_to_four_gates_to_human_approvals_to_publish(db):
    asset = create_pilot(db)
    run = run_copy_quality(
        db,
        asset.asset_id,
        editorial_review(asset),
        actor="quality-worker",
        evaluated_on=date(2026, 7, 27),
    )
    assert run.total_score >= 92
    assert run.final_decision == Decision.APPROVED
    refreshed = db.scalar(
        select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset.asset_id)
    )
    assert refreshed.expert_language_approved is True
    assert refreshed.expert_marketing_approved is False
    assert refreshed.copywriter_approved is False
    assert refreshed.state == PublicationState.SPECIALIST_QA
    expert_gate_ids = {
        gate.gate_id
        for gate in db.scalars(
            select(ContentGateDecision).where(ContentGateDecision.run_id == run.run_id)
        ).all()
    }
    assert "GATE_HU_LANGUAGE_EXPERT" in expert_gate_ids
    assert "GATE_MARKETING_COPY_EXPERT" not in expert_gate_ids

    with pytest.raises(ValueError):
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
    pass_mandatory_copy_gates(db, asset)

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
    with pytest.raises(ValueError, match="állapotból"):
        publish_content_asset(db, asset.asset_id, actor="owner@imperial.local")

    record_approval(
        db,
        asset.asset_id,
        "OWNER",
        ApprovalSubmission(decision="APPROVED", note="Üzleti jóváhagyás."),
        actor="owner@imperial.local",
    )
    visual = submit_visual_production(
        db,
        asset.asset_id,
        visual_submission(),
        actor="creative-producer",
    )
    with pytest.raises(ValueError, match="állapotból"):
        submit_visual_production(
            db,
            asset.asset_id,
            visual_submission(
                generation_run_id="VISUAL-RUN-PARALLEL",
                visual_direction_id="VISUAL-DIRECTION-PARALLEL",
            ),
            actor="creative-producer",
        )
    forged_visual_review = creative_director_review(asset, visual)
    forged_visual_review.attestation_sha256 = "0" * 64
    with pytest.raises(ValueError, match="attestation"):
        record_creative_director_review(
            db,
            asset.asset_id,
            forged_visual_review,
            actor="creative-director@imperial.local",
        )
    record_creative_director_review(
        db,
        asset.asset_id,
        creative_director_review(asset, visual),
        actor="creative-director@imperial.local",
    )
    assembly = assembly_submission(asset.content_hash, visual.generation_run_id)
    bundle = assemble_publication_bundle(
        db,
        asset.asset_id,
        assembly,
        actor="production-designer",
    )
    with pytest.raises(ValueError, match="kampánycsomag"):
        record_release_review(
            db,
            asset.asset_id,
            release_review(),
            actor="marketing-manager@imperial.local",
        )
    record_campaign_package_gate(
        db,
        asset.asset_id,
        campaign_package(asset, visual, assembly),
        actor="campaign-package-gate@imperial.local",
    )
    record_release_review(
        db,
        asset.asset_id,
        release_review(),
        actor="marketing-manager@imperial.local",
    )
    refreshed.expert_language_approved = False
    db.commit()
    with pytest.raises(ValueError, match="kötelező"):
        publish_content_asset(db, asset.asset_id, actor="owner@imperial.local")
    refreshed.expert_language_approved = True
    db.commit()

    original_review_json = run.expert_review_json
    original_review_hash = run.expert_review_hash
    tampered_review = json.loads(run.expert_review_json)
    tampered_review["attestation_sha256"] = "0" * 64
    run.expert_review_json = json.dumps(
        tampered_review,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    run.expert_review_hash = hashlib.sha256(run.expert_review_json.encode("utf-8")).hexdigest()
    db.commit()
    with pytest.raises(ValueError, match="attestation"):
        publish_content_asset(db, asset.asset_id, actor="owner@imperial.local")
    run.expert_review_json = original_review_json
    run.expert_review_hash = original_review_hash
    db.commit()

    marketing_review = db.scalar(
        select(ContentWorkflowReviewRecord).where(
            ContentWorkflowReviewRecord.asset_id == asset.asset_id,
            ContentWorkflowReviewRecord.stage == "MARKETING_QA",
        )
    )
    original_marketing_json = marketing_review.review_json
    tampered_marketing = json.loads(marketing_review.review_json)
    tampered_marketing["consumer_readback"] += " Jogosulatlan utólagos módosítás."
    marketing_review.review_json = json.dumps(
        tampered_marketing,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    db.commit()
    with pytest.raises(ValueError, match="attestation"):
        publish_content_asset(db, asset.asset_id, actor="owner@imperial.local")
    marketing_review.review_json = original_marketing_json
    db.commit()

    proof = publish_content_asset(db, asset.asset_id, actor="owner@imperial.local")

    refreshed = db.scalar(
        select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset.asset_id)
    )
    assert refreshed.state == PublicationState.LIVE_QA
    assert proof["publication_bundle_id"] == bundle.bundle_id
    assert set(proof["mandatory_gate_manifest"]) == {
        "MARKETING",
        "DIRECT_RESPONSE",
        "VISUAL",
    }
    assert len(proof["mandatory_gate_manifest_hash"]) == 64
    assert proof["adapter_contract"]["version"] == "publication-gate-envelope-v2"
    assert proof["campaign_package_hash"] == refreshed.campaign_package_hash
    assert proof["campaign_artifact_set_hash"] == refreshed.campaign_artifact_set_hash
    assert proof["release_token"]
    assert proof["adapter_contract"]["idempotency_key"] == proof["publication_proof_id"]
    assert proof["adapter_contract"]["delivery_targets"] == ["META_ADS"]

    valid_adapter_message = OutboxMessage(
        message_id="MSG-VALID-PUBLICATION-GATE",
        destination_module="publication-adapter",
        payload_json=json.dumps(proof, ensure_ascii=False, sort_keys=True, default=str),
        status="pending",
    )
    tampered_proof = json.loads(json.dumps(proof, default=str))
    tampered_proof["mandatory_gate_manifest_hash"] = "0" * 64
    tampered_adapter_message = OutboxMessage(
        message_id="MSG-TAMPERED-PUBLICATION-GATE",
        destination_module="publication-adapter",
        payload_json=json.dumps(tampered_proof, ensure_ascii=False, sort_keys=True, default=str),
        status="pending",
    )
    db.add_all([valid_adapter_message, tampered_adapter_message])
    db.commit()
    delivery_result = process_outbox(db)
    assert delivery_result["staged"] == 1
    assert delivery_result["dead_letter"] == 1
    db.refresh(valid_adapter_message)
    db.refresh(tampered_adapter_message)
    assert valid_adapter_message.status == "staged"
    staged_delivery = db.scalar(
        select(PublicationDelivery).where(
            PublicationDelivery.publication_proof_id == proof["publication_proof_id"]
        )
    )
    assert staged_delivery and staged_delivery.status == "ready"
    assert tampered_adapter_message.status == "dead_letter"
    assert tampered_adapter_message.last_error.startswith("SECURITY_GATE_BLOCKED:")
    for role, reviewer in (
        ("ONLINE_MARKETING_MANAGER", "live-marketing@imperial.local"),
        ("CREATIVE_DIRECTOR", "live-creative@imperial.local"),
        ("DIRECT_RESPONSE_COPYWRITER", "live-copywriter@imperial.local"),
    ):
        record_live_publication_review(
            db,
            asset.asset_id,
            live_review(role, reviewer, asset.content_hash),
            actor=reviewer,
        )
    db.refresh(refreshed)
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


def test_content_asset_requires_independently_approved_strategy(db):
    brief = imperial_brief(copy_brief_id="CB-STRATEGY-BLOCK")
    brief_row = create_copy_brief(
        db,
        brief.model_dump(mode="json"),
        actor="strategist@imperial.local",
    )

    with pytest.raises(ValueError, match="stratégiai kapun"):
        create_content_asset(
            db,
            imperial_asset(asset_id="ASSET-STRATEGY-BLOCK"),
            copy_brief_id=brief_row.copy_brief_id,
            project_id="PRJ-DEMO-001",
            generation_trace=generation_trace(),
            actor="copywriter@imperial.local",
        )


def test_rejected_live_double_check_quarantines_without_automatic_republish(db):
    asset = create_pilot(db, suffix="LIVE-REJECT")
    run_copy_quality(
        db,
        asset.asset_id,
        editorial_review(asset),
        actor="quality-worker",
        evaluated_on=date(2026, 7, 27),
    )
    pass_mandatory_copy_gates(db, asset)
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
    record_approval(
        db,
        asset.asset_id,
        "HUMAN_EDITORIAL",
        ApprovalSubmission(decision="APPROVED", note="Szerkesztői approval."),
        actor="editor@imperial.local",
    )
    record_approval(
        db,
        asset.asset_id,
        "OWNER",
        ApprovalSubmission(decision="APPROVED", note="Tulajdonosi approval."),
        actor="owner@imperial.local",
    )
    visual = submit_visual_production(
        db,
        asset.asset_id,
        visual_submission(generation_run_id="VISUAL-LIVE-REJECT"),
        actor="creative-producer",
    )
    record_creative_director_review(
        db,
        asset.asset_id,
        creative_director_review(asset, visual, reviewer_run_id="CDR-LIVE-REJECT"),
        actor="creative-director@imperial.local",
    )
    assembly = assembly_submission(asset.content_hash, visual.generation_run_id)
    assemble_publication_bundle(
        db,
        asset.asset_id,
        assembly,
        actor="production-designer",
    )
    record_campaign_package_gate(
        db,
        asset.asset_id,
        campaign_package(asset, visual, assembly),
        actor="campaign-package-gate@imperial.local",
    )
    record_release_review(
        db,
        asset.asset_id,
        release_review(),
        actor="marketing-manager@imperial.local",
    )
    publish_content_asset(db, asset.asset_id, actor="owner@imperial.local")

    result = record_live_publication_review(
        db,
        asset.asset_id,
        live_review(
            "CREATIVE_DIRECTOR",
            "live-reject-director@imperial.local",
            asset.content_hash,
            decision="REJECTED",
            findings=["A mobil crop levágja a fő termékelőnyt."],
        ),
        actor="live-reject-director@imperial.local",
    )

    assert result["state"] == PublicationState.QUARANTINED
    pause_message = db.scalar(
        select(OutboxMessage).where(
            OutboxMessage.destination_module == "publication-adapter",
            OutboxMessage.payload_json.contains("PAUSE_OR_UNPUBLISH"),
        )
    )
    assert pause_message is not None
    assert '"automatic_republish_allowed": false' in pause_message.payload_json
    process_outbox(db)
    db.refresh(pause_message)
    assert pause_message.status == "staged"
    pause_delivery = db.scalar(
        select(PublicationDelivery).where(
            PublicationDelivery.publication_proof_id == asset.publication_proof_id,
            PublicationDelivery.action == "PAUSE_OR_UNPUBLISH",
        )
    )
    assert pause_delivery and pause_delivery.target == "META_ADS"


def test_relevant_specialist_gate_without_result_escalates_and_notifies(db):
    asset = create_pilot(db, suffix="002")
    run_copy_quality(
        db,
        asset.asset_id,
        editorial_review(asset),
        actor="quality-worker",
        evaluated_on=date(2026, 7, 27),
    )
    pass_mandatory_copy_gates(db, asset)

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


def test_copy_qa_rejects_forged_expert_review_attestation(db):
    asset = create_pilot(db, suffix="FORGED")
    forged = editorial_review(asset)
    forged.attestation_sha256 = "0" * 64

    with pytest.raises(ValueError, match="attestation"):
        run_copy_quality(db, asset.asset_id, forged, actor="quality-worker")

    db.refresh(asset)
    assert asset.state == PublicationState.DRAFT
    assert asset.latest_run_id is None
    assert asset.expert_language_approved is False
    assert asset.expert_marketing_approved is False
    assert asset.copywriter_approved is False


def test_mandatory_marketing_gate_rejects_forged_attestation(db):
    asset = create_pilot(db, suffix="FORGED-MARKETING")
    run_copy_quality(
        db,
        asset.asset_id,
        editorial_review(asset),
        actor="quality-worker",
        evaluated_on=date(2026, 7, 27),
    )
    forged = mandatory_copy_gate_review(asset, "MARKETING")
    forged.attestation_sha256 = "0" * 64

    with pytest.raises(ValueError, match="attestation"):
        record_mandatory_copy_gate_review(
            db,
            asset.asset_id,
            forged,
            actor="marketing-gate-verifier",
        )

    db.refresh(asset)
    assert asset.state == PublicationState.SPECIALIST_QA
    assert asset.expert_marketing_approved is False


def test_marketing_and_copywriter_gate_must_be_independent(db):
    asset = create_pilot(db, suffix="NON-INDEPENDENT")
    run_copy_quality(
        db,
        asset.asset_id,
        editorial_review(asset),
        actor="quality-worker",
        evaluated_on=date(2026, 7, 27),
    )
    marketing = mandatory_copy_gate_review(asset, "MARKETING")
    record_mandatory_copy_gate_review(
        db,
        asset.asset_id,
        marketing,
        actor="marketing-gate-verifier",
    )
    not_independent = mandatory_copy_gate_review(
        asset,
        "DIRECT_RESPONSE",
        reviewer_identity=marketing.reviewer_identity,
    )

    with pytest.raises(ValueError, match="külön reviewer"):
        record_mandatory_copy_gate_review(
            db,
            asset.asset_id,
            not_independent,
            actor="copywriter-gate-verifier",
        )


def test_dry_copy_cannot_receive_approved_copywriter_decision(db):
    asset = create_pilot(db, suffix="DRY-COPY")
    with pytest.raises(ValueError, match="száraz"):
        mandatory_copy_gate_review(
            asset,
            "DIRECT_RESPONSE",
            dry_copy_detected=True,
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
    run_copy_quality(
        db,
        asset.asset_id,
        editorial_review(asset),
        actor="quality-worker",
        evaluated_on=date(2026, 7, 27),
    )
    pass_mandatory_copy_gates(db, asset)
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
