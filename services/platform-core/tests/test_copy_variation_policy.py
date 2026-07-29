from __future__ import annotations

import pytest

from app.copy_gate.orchestrator import (
    copy_mode_allows_source_prevalidation,
    validate_copy_variation_trace,
)


def trace(mode: str, fingerprint: str, *, ratio: float, score: float = 9.1) -> dict:
    return {
        "copy_mode": mode,
        "copy_fingerprint": fingerprint,
        "copy_concept_id": f"concept-{fingerprint}",
        "source_text_usage_ratio": ratio,
        "professional_copy_quality_score": score,
        "creative_quality_benchmark_id": "prefab-facebook-etalon-v1",
        "creative_rationale": "Önálló direct-response koncepció hiteles márkaalappal.",
        "introduces_new_factual_claims": False,
        "human_fact_review_required": False,
        "meaning_preservation_checked": mode == "source_adaptation",
        "source_prevalidation_requested": mode == "verbatim_source",
    }


def test_copy_policy_accepts_verbatim_adaptation_and_original_modes():
    validate_copy_variation_trace(trace("verbatim_source", "A", ratio=1.0))
    validate_copy_variation_trace(trace("source_adaptation", "B", ratio=0.6))
    validate_copy_variation_trace(trace("original_concept", "C", ratio=0.2))


def test_copy_policy_requires_strong_professional_copywriting_score():
    with pytest.raises(ValueError, match="8.5/10"):
        validate_copy_variation_trace(trace("original_concept", "A", ratio=0.2, score=8.4))


def test_copy_policy_rejects_duplicate_copy_fingerprint():
    first = trace("source_adaptation", "A", ratio=0.6)
    duplicate = trace("original_concept", "A", ratio=0.2)

    with pytest.raises(ValueError, match="copy_fingerprint"):
        validate_copy_variation_trace(duplicate, sibling_traces=[first])


def test_copy_policy_prevents_all_verbatim_creative_sets():
    first = trace("verbatim_source", "A", ratio=1.0)
    second = trace("verbatim_source", "B", ratio=0.95)

    with pytest.raises(ValueError, match="legfeljebb fele"):
        validate_copy_variation_trace(second, sibling_traces=[first])


def test_copy_policy_requires_human_fact_review_for_new_claims():
    candidate = trace("original_concept", "A", ratio=0.1)
    candidate["introduces_new_factual_claims"] = True

    with pytest.raises(ValueError, match="emberi tényellenőrzést"):
        validate_copy_variation_trace(candidate)


def test_copy_policy_blocks_adaptation_from_source_prevalidated_fast_lane():
    candidate = trace("source_adaptation", "A", ratio=0.6)
    candidate["source_prevalidation_requested"] = True

    with pytest.raises(ValueError, match="SOURCE_PREVALIDATED"):
        validate_copy_variation_trace(candidate)
    assert not copy_mode_allows_source_prevalidation(candidate)


def test_only_verbatim_unchanged_copy_can_use_source_prevalidation():
    verbatim = trace("verbatim_source", "A", ratio=1.0)
    adaptation = trace("source_adaptation", "B", ratio=0.6)

    assert copy_mode_allows_source_prevalidation(verbatim)
    assert not copy_mode_allows_source_prevalidation(adaptation)
