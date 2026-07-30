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
from app.services.content_quality import validate_copy_brief


def request():
    asset = imperial_asset()
    return ContentEvaluationRequest(
        brief=imperial_brief(),
        sources=canonical_sources(),
        asset=asset,
        editorial_review=editorial_review(asset),
        evaluated_on=date(2026, 7, 26),
    )


def test_approved_copy_meets_all_ten_dimensions_and_threshold():
    result = evaluate_content(request())

    assert result.final_decision == Decision.APPROVED
    assert result.total_score >= 92
    assert len(result.dimensions) == 10
    assert all(dimension.passed for dimension in result.dimensions)
    assert result.publication_blocked is False


def test_generic_brand_mixed_copy_is_critically_blocked():
    payload = request()
    payload.asset.detected_brand_ids = ["imperial", "prefab"]
    payload.asset.body += " Innovatív technológia kompromisszumok nélkül."

    result = evaluate_content(payload)

    assert result.final_decision == Decision.RETURN_FOR_REVISION
    assert result.publication_blocked
    codes = {finding.code for finding in result.gate_1.findings}
    assert {"BRAND_CONTAMINATION", "FORBIDDEN_LANGUAGE"} <= codes


def test_duplicate_content_or_layout_is_not_compensable():
    payload = request()
    payload.asset.content_blocks[1].text = payload.asset.content_blocks[0].text
    payload.asset.content_blocks[1].layout_signature = payload.asset.content_blocks[
        0
    ].layout_signature

    result = evaluate_content(payload)

    codes = {finding.code for finding in result.gate_1.findings}
    assert result.publication_blocked
    assert {"DUPLICATE_CONTENT_BLOCK", "DUPLICATE_LAYOUT_BLOCK"} <= codes


def test_offer_message_proof_and_review_independence_are_fail_closed():
    payload = request()
    payload.asset.offer_version_id_used = "OFF-WRONG"
    payload.asset.landing_message_match_id_used = "MM-WRONG"
    payload.asset.proof_ids_used = []
    payload.editorial_review.reviewer_run_id = payload.editorial_review.generation_run_id

    result = evaluate_content(payload)

    codes = {finding.code for finding in result.gate_1.findings}
    assert result.publication_blocked
    assert {
        "OFFER_VERSION_MISMATCH",
        "MESSAGE_MATCH_FAILED",
        "CLAIM_PROOF_COVERAGE_FAILED",
        "REVIEW_INDEPENDENCE_FAILED",
    } <= codes


def test_known_nonsense_and_internal_offer_shorthand_are_critically_blocked():
    payload = request()
    payload.asset.body += (
        " A fal már azelőtt ellenőrizhető, hogy az otthona köré zárulna. "
        "Válasszon 6% kedvezményt vagy kész kertkapcsolatot."
    )
    payload.editorial_review = editorial_review(payload.asset)

    result = evaluate_content(payload)

    codes = {finding.code for finding in result.gate_1.findings}
    assert result.publication_blocked
    assert {
        "UNNATURAL_HOME_CLOSURE_METAPHOR",
        "UNEXPLAINED_OFFER_SHORTHAND",
    } <= codes


def test_unexplained_lifestyle_promise_is_critically_blocked():
    payload = request()
    payload.asset.body += " Több idő élni. 6% augusztusi kedvezménnyel."
    payload.editorial_review = editorial_review(payload.asset)

    result = evaluate_content(payload)

    codes = {finding.code for finding in result.gate_1.findings}
    assert result.publication_blocked
    assert "UNEXPLAINED_LIFESTYLE_PROMISE" in codes


def test_internal_copy_critique_and_administrative_offer_language_are_blocked():
    payload = request()
    payload.asset.body += (
        " A gyorsaság oka nem egy ködös életérzés. "
        "A vállalás fix árhoz és díjmentes tervezéshez kapcsolódik."
    )
    payload.editorial_review = editorial_review(payload.asset)

    result = evaluate_content(payload)

    codes = {finding.code for finding in result.gate_1.findings}
    assert result.publication_blocked
    assert {
        "INTERNAL_CRITIQUE_LEAKED_TO_CONSUMER_COPY",
        "ADMINISTRATIVE_OFFER_LANGUAGE",
    } <= codes


def test_bare_aaa_and_noncanonical_magyarbrands_name_are_blocked():
    payload = request()
    payload.asset.body += " Kétszeres Magyar Brands díjazott márka. AAA."
    payload.editorial_review = editorial_review(payload.asset)

    result = evaluate_content(payload)

    codes = {finding.code for finding in result.gate_1.findings}
    assert result.publication_blocked
    assert {
        "NONCANONICAL_AWARD_NAME",
        "UNEXPLAINED_TRUST_ACRONYM",
    } <= codes


def test_danish_included_design_must_not_be_called_free():
    payload = request()
    payload.brief.brand_id = "danish-fabrik"
    payload.asset.detected_brand_ids = ["danish-fabrik"]
    payload.asset.body += " Fix ár, fix határidő, tervezési díj nélkül."
    payload.editorial_review = editorial_review(payload.asset)

    result = evaluate_content(payload)

    codes = {finding.code for finding in result.gate_1.findings}
    assert result.publication_blocked
    assert "DANISH_INCLUDED_DESIGN_WORDING_REQUIRED" in codes


def test_expert_review_for_different_content_hash_is_critically_blocked():
    payload = request()
    payload.asset.body += " Ez már egy másik, felülvizsgálatlan tartalomverzió."

    result = evaluate_content(payload)

    codes = {finding.code for finding in result.gate_1.findings}
    assert result.publication_blocked
    assert "EXPERT_REVIEW_HASH_MISMATCH" in codes


def test_incomplete_copy_brief_returns_structured_error_ticket():
    result = validate_copy_brief({"copy_brief_id": "CB-MISSING"})

    assert result["valid"] is False
    assert result["decision"] == Decision.RETURN_FOR_REVISION
    assert result["error_ticket"]["code"] == "COPY_BRIEF_INCOMPLETE"
    assert result["error_ticket"]["errors"]
