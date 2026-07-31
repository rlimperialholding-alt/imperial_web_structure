from __future__ import annotations

from datetime import date

from copy_gate_fixtures import (
    canonical_sources,
    editorial_review,
    imperial_asset,
    imperial_brief,
)

from app.copy_gate.engine import evaluate_content
from app.copy_gate.models import ContentEvaluationRequest, Decision
from app.copy_gate.promotions import (
    PromotionStatus,
    load_monthly_promotion_registry,
    resolve_monthly_promotion,
)
from app.services.content_quality import _enrich_monthly_promotion_sources


def finding_codes(result) -> set[str]:
    return {finding.code for finding in result.gate_1.findings}


def promotional_request(*, position: int = 0, publication_allowed: bool = False):
    promotion_id = "PROMO-IMP-2026-08"
    promotion_copy = (
        "Augusztusban válasszon akár 6% kedvezményt, vagy kérje a házhoz a bioklimatikus pergolát."
    )
    brief = imperial_brief().model_copy(
        update={
            "monthly_promotion_id": promotion_id,
            "monthly_promotion_copy_required": True,
        }
    )
    asset = imperial_asset().model_copy(
        update={
            "body": f"{promotion_copy} {imperial_asset().body}",
            "monthly_promotion_id_used": promotion_id,
            "monthly_promotion_copy_text": promotion_copy,
            "monthly_promotion_copy_position": position,
        }
    )
    sources = canonical_sources().model_copy(
        update={
            "monthly_promotion_id": promotion_id,
            "monthly_promotion_copy_required": True,
            "monthly_promotion_publication_allowed": publication_allowed,
        }
    )
    return ContentEvaluationRequest(
        brief=brief,
        sources=sources,
        asset=asset,
        editorial_review=editorial_review(asset),
        evaluated_on=date(2026, 8, 1),
    )


def test_august_registry_matches_the_gmail_directive_and_brand_policies():
    registry = load_monthly_promotion_registry()

    assert registry.source["message_id"] == "19f88e0de03c5a5e"
    assert registry.global_rules["promotion_copy_placement"] == "FIRST_BLOCK"
    assert registry.global_rules["promotion_on_creative"] == "OPTIONAL"
    assert registry.global_rules["discount_and_gift_stackable"] is False

    prepared = {
        brand_id
        for brand_id, record in registry.brands.items()
        if record.status == PromotionStatus.PREPARATION_ONLY
    }
    assert prepared == {
        "bautica",
        "timberhaus",
    }
    approved = {
        brand_id
        for brand_id, record in registry.brands.items()
        if record.status == PromotionStatus.ACTIVE
    }
    assert approved == {"imperial", "danish-fabrik", "prefab"}
    assert all(registry.brands[brand_id].publication_allowed for brand_id in approved)
    assert len(registry.brands["imperial"].models) == 10
    assert len(registry.brands["danish-fabrik"].models) == 10
    assert len(registry.brands["bautica"].models) == 10
    assert len(registry.brands["prefab"].models) == 10
    assert len(registry.brands["timberhaus"].models) == 8


def test_monthly_policy_distinguishes_no_promotion_never_and_missing_required():
    registry = load_monthly_promotion_registry()

    baufreund = resolve_monthly_promotion("baufreund", on_date=date(2026, 8, 1), registry=registry)
    casa = resolve_monthly_promotion("casa-moderna", on_date=date(2026, 8, 1), registry=registry)
    red = resolve_monthly_promotion("red", on_date=date(2026, 8, 1), registry=registry)

    assert baufreund.status == PromotionStatus.NO_PROMOTION_SOURCE
    assert baufreund.copy_required is False
    assert casa.status == PromotionStatus.NEVER_PROMOTION
    assert casa.copy_required is False
    assert red.status == PromotionStatus.MISSING_REQUIRED_SOURCE
    assert red.copy_required is False
    assert red.publication_allowed is False
    assert any("nincs hiteles havi ajánlatforrás" in item for item in red.blocking_reasons)


def test_preparation_requires_leading_copy_but_keeps_creative_badge_optional():
    requirement = resolve_monthly_promotion("bautica", on_date=date(2026, 7, 26))

    assert requirement.copy_required is True
    assert requirement.copy_position == "FIRST_BLOCK"
    assert requirement.promotion_on_creative_optional is True
    assert requirement.publication_allowed is False


def test_approved_promotions_are_publishable_only_inside_the_august_window():
    for brand_id in ("imperial", "danish-fabrik", "prefab"):
        before_window = resolve_monthly_promotion(brand_id, on_date=date(2026, 7, 27))
        inside_window = resolve_monthly_promotion(brand_id, on_date=date(2026, 8, 1))

        assert before_window.status == PromotionStatus.ACTIVE
        assert before_window.copy_required is False
        assert before_window.publication_allowed is False
        assert inside_window.copy_required is True
        assert inside_window.publication_allowed is True
        assert inside_window.blocking_reasons == []


def test_quality_source_snapshot_includes_active_monthly_promotion():
    brief = imperial_brief().model_copy(
        update={
            "brand_id": "prefab",
            "monthly_promotion_id": "PROMO-PREFAB-2026-08",
            "monthly_promotion_copy_required": True,
        }
    )

    sources, snapshot_hash = _enrich_monthly_promotion_sources(
        canonical_sources(),
        brief,
        evaluated_on=date(2026, 8, 1),
    )

    assert sources.monthly_promotion_id == "PROMO-PREFAB-2026-08"
    assert sources.monthly_promotion_copy_required is True
    assert sources.monthly_promotion_publication_allowed is True
    assert sources.source_versions["monthly_promotion"].startswith(
        "PROMO-PREFAB-2026-08@2026-08-01#"
    )
    assert len(snapshot_hash) == 64


def test_copy_gate_accepts_first_block_placement_when_approvals_are_active():
    result = evaluate_content(promotional_request(publication_allowed=True))

    assert result.final_decision == Decision.APPROVED
    assert "MONTHLY_PROMOTION_NOT_FIRST" not in finding_codes(result)


def test_copy_gate_blocks_promotion_that_is_not_the_first_copy_block():
    result = evaluate_content(promotional_request(position=1, publication_allowed=True))

    assert result.publication_blocked
    assert "MONTHLY_PROMOTION_NOT_FIRST" in finding_codes(result)


def test_copy_gate_keeps_preparation_only_offer_out_of_publication():
    result = evaluate_content(promotional_request(publication_allowed=False))

    assert result.publication_blocked
    assert "MONTHLY_PROMOTION_APPROVAL_PENDING" in finding_codes(result)


def test_copy_gate_rejects_promotion_without_an_active_source():
    payload = promotional_request(publication_allowed=True)
    payload.brief.monthly_promotion_id = None
    payload.brief.monthly_promotion_copy_required = False
    payload.sources.monthly_promotion_id = None
    payload.sources.monthly_promotion_copy_required = False

    result = evaluate_content(payload)

    assert result.publication_blocked
    assert "UNVALIDATED_MONTHLY_PROMOTION" in finding_codes(result)
