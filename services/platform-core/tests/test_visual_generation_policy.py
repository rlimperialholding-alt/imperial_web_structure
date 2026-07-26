from __future__ import annotations

import pytest

from app.copy_gate.orchestrator import validate_visual_variant_trace


def trace(
    variant: str,
    direction: str,
    run: str,
    *,
    variant_set: str = "VS-BAUTICA-FB-001",
) -> dict[str, str]:
    return {
        "variant_set_id": variant_set,
        "creative_variant_id": variant,
        "visual_direction_id": direction,
        "generation_run_id": run,
    }


def test_visual_variants_require_separate_generation_runs_and_directions():
    first = trace("A", "documentary-site-control", "GEN-A")
    second = trace("B", "blueprint-proof-grid", "GEN-B")

    validate_visual_variant_trace(first)
    validate_visual_variant_trace(second, sibling_traces=[first])


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (trace("B", "blueprint-proof-grid", "GEN-A"), "generation_run_id"),
        (trace("A", "blueprint-proof-grid", "GEN-B"), "creative_variant_id"),
        (trace("B", "documentary-site-control", "GEN-B"), "visual_direction_id"),
    ],
)
def test_visual_variants_reject_reused_identity_direction_or_run(candidate, message):
    first = trace("A", "documentary-site-control", "GEN-A")

    with pytest.raises(ValueError, match=message):
        validate_visual_variant_trace(candidate, sibling_traces=[first])


def test_partial_visual_variant_trace_is_rejected():
    with pytest.raises(ValueError, match="kötelező trace mezői"):
        validate_visual_variant_trace(
            {
                "creative_variant_id": "A",
                "generation_run_id": "GEN-A",
            }
        )
