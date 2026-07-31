from __future__ import annotations

from copy_gate_fixtures import (
    assembly_submission,
    campaign_package,
    creative_director_review,
    editorial_review,
    generation_trace,
    imperial_asset,
    imperial_brief,
    mandatory_copy_gate_review,
    release_review,
    strategy_review,
    visual_submission,
)

from app.copy_gate.models import (
    Decision,
    ExternalActionType,
    FourGateSubmission,
    PrevalidatedSourceEvidence,
    PublicationState,
)
from app.services.commercial_prevalidation import (
    evaluate_commercial_prevalidation,
    load_prevalidated_registry,
)
from app.services.content_quality import (
    assemble_publication_bundle,
    create_content_asset,
    create_copy_brief,
    publish_content_asset,
    record_campaign_package_gate,
    record_creative_director_review,
    record_mandatory_copy_gate_review,
    record_release_review,
    record_strategy_review,
    run_copy_quality,
    submit_four_gates,
    submit_visual_production,
)


def _pass_mandatory_copy_gates(db, asset):
    for gate_id in ("MARKETING", "DIRECT_RESPONSE"):
        record_mandatory_copy_gate_review(
            db,
            asset.asset_id,
            mandatory_copy_gate_review(asset, gate_id),
            actor=f"{gate_id.lower()}-gate-verifier",
        )


def _fragment_evidence(
    brand_id: str,
    text_contains: str,
    *,
    category: str,
) -> tuple[PrevalidatedSourceEvidence, str]:
    registry = load_prevalidated_registry()
    fragment = next(
        item
        for item in registry["brands"][brand_id]["fragments"]
        if text_contains.casefold() in item["text"].casefold() and category in item["categories"]
    )
    claim = text_contains
    return (
        PrevalidatedSourceEvidence(
            evidence_id=f"WEB-{fragment['fragment_sha256'][:16]}",
            category=category,
            source_type="website_fragment",
            source_ref=fragment["fragment_sha256"],
            source_url=fragment["source_url"],
            source_version=registry["registry_version"],
            source_fragment=fragment["text"],
            source_fragment_sha256=fragment["fragment_sha256"],
            claim_text=claim,
        ),
        claim,
    )


def test_current_website_commercial_claim_is_prevalidated():
    evidence, claim = _fragment_evidence(
        "imperial",
        "FIX MINŐSÉG, FIX ÁR, FIX HATÁRIDŐ.",
        category="commercial",
    )
    asset = imperial_asset().model_copy(
        update={
            "body": imperial_asset().body + " " + claim,
            "factual_claims": [claim],
            "price_mentions": [],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [evidence],
        }
    )

    result = evaluate_commercial_prevalidation("imperial", asset)

    assert result.eligible is True
    assert result.gate_coverage["GATE_3_FINANCIAL_COMMERCIAL"] is True


def test_current_imperial_four_pillar_message_is_prevalidated():
    evidence, claim = _fragment_evidence(
        "imperial",
        "Előre kalkulálható, fix ár, fix határidő, fix feltételek.",
        category="commercial",
    )
    asset = imperial_asset().model_copy(
        update={
            "body": imperial_asset().body + " " + claim,
            "factual_claims": [claim],
            "price_mentions": [],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [evidence],
        }
    )

    result = evaluate_commercial_prevalidation("imperial", asset)

    assert result.eligible is True


def test_current_website_price_can_be_reused_with_its_exact_source():
    evidence, claim = _fragment_evidence(
        "imperial",
        "már 589.000 Ft/nm ártól",
        category="price",
    )
    asset = imperial_asset().model_copy(
        update={
            "body": imperial_asset().body + " " + claim,
            "factual_claims": [claim],
            "price_mentions": [claim],
            "condition_mentions": ["ártól", "+ ÁFA"],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [evidence],
        }
    )

    result = evaluate_commercial_prevalidation("imperial", asset)

    assert result.eligible is True
    assert result.gate_coverage["GATE_3_FINANCIAL_COMMERCIAL"] is True


def test_current_website_technical_and_legal_claims_are_source_bounded():
    technical, technical_claim = _fragment_evidence(
        "danish-fabrik",
        "2. Padozat rétegrend",
        category="technical",
    )
    legal, legal_claim = _fragment_evidence(
        "imperial",
        "Fix határidő, kötbérrel",
        category="legal",
    )
    technical_asset = imperial_asset().model_copy(
        update={
            "body": imperial_asset().body + f" {technical_claim}.",
            "factual_claims": [technical_claim],
            "detected_brand_ids": ["danish-fabrik"],
            "price_mentions": [],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [technical],
        }
    )
    legal_asset = imperial_asset().model_copy(
        update={
            "body": imperial_asset().body + f" {legal_claim}.",
            "factual_claims": [legal_claim],
            "price_mentions": [],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [legal],
        }
    )

    technical_result = evaluate_commercial_prevalidation("danish-fabrik", technical_asset)
    legal_result = evaluate_commercial_prevalidation("imperial", legal_asset)

    assert technical_result.eligible is True
    assert technical_result.gate_coverage["GATE_4_TECHNICAL_FACTUAL"] is True
    assert legal_result.eligible is True
    assert legal_result.gate_coverage["GATE_2_LEGAL_POLICY"] is True


def test_exact_drive_calculator_price_can_publish_without_human_price_review():
    registry = load_prevalidated_registry()
    source = next(
        item
        for item in registry["price_sources"]
        if item["registry_id"] == "drive-web-prices-2026-07"
    )
    evidence = PrevalidatedSourceEvidence(
        evidence_id="PRICE-IMP-FAVAZ-100M2",
        category="price",
        source_type="drive_price_calculator",
        source_ref=source["registry_id"],
        source_version=source["source_version"],
        source_sha256=source["sha256"],
        price_input={
            "technology": "Danish Fabrik",
            "completion_level": "Kulcsrakész",
            "package": "Alap",
            "gross_area_m2": "100",
            "vat_rate": "0.05",
        },
        price_output_field="estimated_net_total_huf",
        price_value_huf=68_000_000,
    )
    asset = imperial_asset().model_copy(
        update={
            "body": imperial_asset().body + " A kalkulált ár 68 000 000 Ft + ÁFA.",
            "factual_claims": [],
            "price_mentions": ["68 000 000 Ft + ÁFA"],
            "condition_mentions": ["+ ÁFA"],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [evidence],
        }
    )

    result = evaluate_commercial_prevalidation("imperial", asset)

    assert result.eligible is True
    assert result.metadata["drive_price_verified"] is True
    assert result.metadata["price_publication_policy"] == "NET_HUF_PLUS_VAT_2026-07-31"


def test_gross_calculator_output_never_qualifies_for_price_fast_lane():
    registry = load_prevalidated_registry()
    source = next(
        item
        for item in registry["price_sources"]
        if item["registry_id"] == "drive-web-prices-2026-07"
    )
    evidence = PrevalidatedSourceEvidence(
        evidence_id="PRICE-IMP-GROSS-PROHIBITED",
        category="price",
        source_type="drive_price_calculator",
        source_ref=source["registry_id"],
        source_version=source["source_version"],
        source_sha256=source["sha256"],
        price_input={
            "technology": "Danish Fabrik",
            "completion_level": "Kulcsrakész",
            "package": "Alap",
            "gross_area_m2": "100",
            "vat_rate": "0.05",
        },
        price_output_field="estimated_gross_total_huf",
        price_value_huf=71_400_000,
    )
    asset = imperial_asset().model_copy(
        update={
            "body": imperial_asset().body + " Bruttó ár 71 400 000 Ft.",
            "factual_claims": [],
            "price_mentions": ["Bruttó ár 71 400 000 Ft"],
            "condition_mentions": ["5% ÁFA-val"],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [evidence],
        }
    )

    result = evaluate_commercial_prevalidation("imperial", asset)

    assert result.eligible is False
    assert any("bruttó" in finding.lower() for finding in result.findings)


def test_net_price_without_plus_vat_suffix_fails_closed():
    evidence, claim = _fragment_evidence(
        "imperial",
        "már 589.000 Ft/nm ártól",
        category="price",
    )
    asset = imperial_asset().model_copy(
        update={
            "body": imperial_asset().body + " " + claim,
            "factual_claims": [claim],
            "price_mentions": [claim],
            "condition_mentions": ["ártól"],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [evidence],
        }
    )

    result = evaluate_commercial_prevalidation("imperial", asset)

    assert result.eligible is False
    assert any("+ ÁFA" in finding for finding in result.findings)


def test_changed_drive_price_fails_closed():
    registry = load_prevalidated_registry()
    source = next(
        item
        for item in registry["price_sources"]
        if item["registry_id"] == "drive-web-prices-2026-07"
    )
    evidence = PrevalidatedSourceEvidence(
        evidence_id="PRICE-IMP-TAMPERED",
        category="price",
        source_type="drive_price_calculator",
        source_ref=source["registry_id"],
        source_version=source["source_version"],
        source_sha256=source["sha256"],
        price_input={
            "technology": "Danish Fabrik",
            "completion_level": "Kulcsrakész",
            "package": "Alap",
            "gross_area_m2": "100",
            "vat_rate": "0.05",
        },
        price_output_field="estimated_net_total_huf",
        price_value_huf=67_900_000,
    )
    asset = imperial_asset().model_copy(
        update={
            "body": imperial_asset().body + " A kalkulált ár 67 900 000 Ft + ÁFA.",
            "factual_claims": [],
            "price_mentions": ["67 900 000 Ft + ÁFA"],
            "condition_mentions": ["+ ÁFA"],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [evidence],
        }
    )

    result = evaluate_commercial_prevalidation("imperial", asset)

    assert result.eligible is False
    assert any("eltér a kalkulátor" in finding for finding in result.findings)


def test_brand_without_active_drive_pricing_fails_closed():
    registry = load_prevalidated_registry()
    source = next(
        item
        for item in registry["price_sources"]
        if item["registry_id"] == "drive-web-prices-2026-07"
    )
    evidence = PrevalidatedSourceEvidence(
        evidence_id="PRICE-CASA-NOT-ACTIVE",
        category="price",
        source_type="drive_price_calculator",
        source_ref=source["registry_id"],
        source_version=source["source_version"],
        source_sha256=source["sha256"],
        price_input={
            "technology": "Danish Fabrik",
            "completion_level": "Kulcsrakész",
            "package": "Alap",
            "gross_area_m2": "100",
            "vat_rate": "0.05",
        },
        price_output_field="estimated_net_total_huf",
        price_value_huf=68_000_000,
    )
    asset = imperial_asset().model_copy(
        update={
            "detected_brand_ids": ["casa-moderna"],
            "factual_claims": [],
            "price_mentions": ["68 000 000 Ft + ÁFA"],
            "condition_mentions": ["100 m²", "+ ÁFA"],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [evidence],
        }
    )

    result = evaluate_commercial_prevalidation("casa-moderna", asset)

    assert result.eligible is False
    assert any("nem ehhez a márkához" in finding for finding in result.findings)


def test_current_typehouse_visual_reference_is_prevalidated():
    registry = load_prevalidated_registry()
    visual = registry["brands"]["prefab"]["typehouse_assets"][0]
    evidence = PrevalidatedSourceEvidence(
        evidence_id="VIS-PREFAB-CURRENT-001",
        category="typehouse",
        source_type="website_visual",
        source_ref=visual["reference_sha256"],
        source_url=visual["source_page"],
        source_version=registry["registry_version"],
        visual_asset_id="VIS-PREFAB-CURRENT-001",
        visual_asset_url=visual["asset_url"],
        visual_reference_sha256=visual["reference_sha256"],
    )
    asset = imperial_asset().model_copy(
        update={
            "detected_brand_ids": ["prefab"],
            "factual_claims": [],
            "price_mentions": [],
            "visual_asset_ids": ["VIS-PREFAB-CURRENT-001"],
            "prevalidated_source_evidence": [evidence],
        }
    )

    result = evaluate_commercial_prevalidation("prefab", asset)

    assert result.eligible is True
    assert result.gate_coverage["GATE_4_TECHNICAL_FACTUAL"] is True


def test_r6_r7_action_never_inherits_marketing_source_prevalidation():
    evidence, claim = _fragment_evidence(
        "imperial",
        "FIX MINŐSÉG, FIX ÁR, FIX HATÁRIDŐ.",
        category="commercial",
    )
    asset = imperial_asset().model_copy(
        update={
            "body": imperial_asset().body + " " + claim,
            "factual_claims": [claim],
            "price_mentions": [],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [evidence],
            "action_risk_level": 6,
            "external_action_type": ExternalActionType.CONTRACT_MODIFICATION,
        }
    )

    result = evaluate_commercial_prevalidation("imperial", asset)

    assert result.eligible is False
    assert any("R6–R7" in finding for finding in result.findings)


def test_prevalidated_asset_skips_human_editorial_and_owner_approval(db):
    evidence, claim = _fragment_evidence(
        "imperial",
        "FIX MINŐSÉG, FIX ÁR, FIX HATÁRIDŐ.",
        category="commercial",
    )
    brief = imperial_brief(copy_brief_id="CB-IMP-PREVALIDATED")
    source_asset = imperial_asset(asset_id="ASSET-IMP-PREVALIDATED")
    asset_payload = source_asset.model_copy(
        update={
            "body": source_asset.body + " " + claim,
            "factual_claims": [claim],
            "price_mentions": [],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [evidence],
        }
    )
    brief_row = create_copy_brief(db, brief.model_dump(mode="json"), actor="test")
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
        actor="test",
    )
    run_copy_quality(db, asset.asset_id, editorial_review(asset), actor="quality-worker")
    _pass_mandatory_copy_gates(db, asset)

    aggregate = submit_four_gates(
        db,
        asset.asset_id,
        FourGateSubmission(
            legal_relevant=False,
            financial_relevant=True,
            technical_relevant=False,
        ),
        actor="gate-orchestrator",
    )
    assert aggregate["state"] == PublicationState.VISUAL_PRODUCTION
    visual = submit_visual_production(
        db,
        asset.asset_id,
        visual_submission(),
        actor="creative-producer",
    )
    record_creative_director_review(
        db,
        asset.asset_id,
        creative_director_review(asset, visual),
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
        campaign_package(
            asset,
            visual,
            assembly,
            brand_guardian="campaign-package-gate@imperial.local",
        ),
        actor="campaign-package-gate@imperial.local",
    )
    record_release_review(
        db,
        asset.asset_id,
        release_review(),
        actor="marketing-manager@imperial.local",
    )

    proof = publish_content_asset(db, asset.asset_id, actor="owner@imperial.local")

    assert proof["approval_mode"] == "SOURCE_PREVALIDATED"
    assert proof["human_editorial_actor"] is None
    assert proof["owner_actor"] == "owner@imperial.local"


def test_adapted_copy_cannot_use_source_prevalidated_fast_lane(db):
    evidence, claim = _fragment_evidence(
        "imperial",
        "FIX MINŐSÉG, FIX ÁR, FIX HATÁRIDŐ.",
        category="commercial",
    )
    brief = imperial_brief(copy_brief_id="CB-IMP-ADAPTED")
    source_asset = imperial_asset(asset_id="ASSET-IMP-ADAPTED")
    asset_payload = source_asset.model_copy(
        update={
            "body": source_asset.body + " " + claim,
            "factual_claims": [claim],
            "price_mentions": [],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [evidence],
        }
    )
    adapted_trace = generation_trace()
    adapted_trace.update(
        {
            "copy_mode": "source_adaptation",
            "copy_fingerprint": "sha256:test-imperial-adapted-copy-v1",
            "copy_concept_id": "imperial-adapted-proof-v1",
            "source_text_usage_ratio": 0.6,
            "meaning_preservation_checked": True,
            "source_prevalidation_requested": False,
        }
    )
    brief_row = create_copy_brief(db, brief.model_dump(mode="json"), actor="test")
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
        generation_trace=adapted_trace,
        actor="test",
    )
    run_copy_quality(db, asset.asset_id, editorial_review(asset), actor="quality-worker")
    _pass_mandatory_copy_gates(db, asset)

    aggregate = submit_four_gates(
        db,
        asset.asset_id,
        FourGateSubmission(
            legal_relevant=False,
            financial_relevant=True,
            technical_relevant=False,
        ),
        actor="gate-orchestrator",
    )

    assert aggregate["decision"] == Decision.HUMAN_APPROVAL_REQUIRED
    assert aggregate["state"] == PublicationState.FOUR_GATE_QA
