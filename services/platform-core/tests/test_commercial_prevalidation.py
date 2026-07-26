from __future__ import annotations

from copy_gate_fixtures import (
    editorial_review,
    generation_trace,
    imperial_asset,
    imperial_brief,
)

from app.copy_gate.models import (
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
    create_content_asset,
    create_copy_brief,
    publish_content_asset,
    run_copy_quality,
    submit_four_gates,
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
            "condition_mentions": ["ártól"],
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
        price_output_field="estimated_gross_total_huf",
        price_value_huf=68_000_000,
    )
    asset = imperial_asset().model_copy(
        update={
            "body": imperial_asset().body + " A kalkulált bruttó ár 68 000 000 Ft.",
            "factual_claims": [],
            "price_mentions": ["68 000 000 Ft"],
            "visual_asset_ids": [],
            "prevalidated_source_evidence": [evidence],
        }
    )

    result = evaluate_commercial_prevalidation("imperial", asset)

    assert result.eligible is True
    assert result.metadata["drive_price_verified"] is True


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
        price_output_field="estimated_gross_total_huf",
        price_value_huf=67_900_000,
    )
    asset = imperial_asset().model_copy(
        update={
            "body": imperial_asset().body + " A kalkulált bruttó ár 67 900 000 Ft.",
            "factual_claims": [],
            "price_mentions": ["67 900 000 Ft"],
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
        price_output_field="estimated_gross_total_huf",
        price_value_huf=68_000_000,
    )
    asset = imperial_asset().model_copy(
        update={
            "detected_brand_ids": ["casa-moderna"],
            "factual_claims": [],
            "price_mentions": ["68 000 000 Ft"],
            "condition_mentions": ["100 m², 5% áfa"],
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
    asset = create_content_asset(
        db,
        asset_payload,
        copy_brief_id=brief_row.copy_brief_id,
        project_id="PRJ-DEMO-001",
        generation_trace=generation_trace(),
        actor="test",
    )
    run_copy_quality(db, asset.asset_id, editorial_review(), actor="quality-worker")

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
    assert aggregate["state"] == PublicationState.SOURCE_PREVALIDATED

    proof = publish_content_asset(db, asset.asset_id, actor="publication-worker")

    assert proof["approval_mode"] == "SOURCE_PREVALIDATED"
    assert proof["human_editorial_actor"] is None
    assert proof["owner_actor"] is None
