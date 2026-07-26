from __future__ import annotations

import pytest

from app.copy_gate.orchestrator import validate_visual_variant_trace


def trace(
    variant: str,
    direction: str,
    run: str,
    *,
    variant_set: str = "VS-BAUTICA-FB-001",
    layout: str | None = None,
    composition: str | None = None,
    text_zone: str | None = None,
    image_treatment: str | None = None,
    background_treatment: str | None = None,
    contrast: float = 7.0,
) -> dict[str, str | float]:
    return {
        "variant_set_id": variant_set,
        "creative_variant_id": variant,
        "visual_direction_id": direction,
        "generation_run_id": run,
        "layout_archetype_id": layout or f"layout-{variant}",
        "composition_signature": composition or f"composition-{variant}",
        "primary_text_zone": text_zone or f"zone-{variant}",
        "image_treatment": image_treatment or f"image-{variant}",
        "background_treatment": background_treatment or f"solid-{variant}",
        "minimum_text_contrast_ratio": contrast,
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


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (
            trace(
                "B",
                "blueprint-proof-grid",
                "GEN-B",
                layout="layout-A",
            ),
            "layout_archetype_id",
        ),
        (
            trace(
                "B",
                "blueprint-proof-grid",
                "GEN-B",
                composition="composition-A",
            ),
            "composition_signature",
        ),
        (
            trace(
                "B",
                "blueprint-proof-grid",
                "GEN-B",
                text_zone="zone-A",
                image_treatment="image-A",
                background_treatment="solid-A",
            ),
            "együttes",
        ),
    ],
)
def test_visual_variants_reject_reused_composition_structure(candidate, message):
    first = trace("A", "documentary-site-control", "GEN-A")

    with pytest.raises(ValueError, match=message):
        validate_visual_variant_trace(candidate, sibling_traces=[first])


def test_visual_variant_rejects_low_text_contrast():
    with pytest.raises(ValueError, match="4.5:1"):
        validate_visual_variant_trace(trace("A", "documentary-site-control", "GEN-A", contrast=3.4))


def test_visual_variant_rejects_gradient_without_human_exception():
    with pytest.raises(ValueError, match="alapértelmezetten tiltott"):
        validate_visual_variant_trace(
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                background_treatment="navy-to-photo-gradient",
            )
        )


def test_visual_variant_allows_documented_human_gradient_exception():
    candidate = trace(
        "A",
        "documentary-site-control",
        "GEN-A",
        background_treatment="approved-editorial-gradient",
    )
    candidate["background_gradient_exception_approved_by"] = "human-art-director"

    validate_visual_variant_trace(candidate)
