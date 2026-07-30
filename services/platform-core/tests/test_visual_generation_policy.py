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
    full_subject_expected: bool = True,
    full_subject_contour_visible: bool = True,
    accidental_crop_absent: bool = True,
    text_boxes_within_bounds: bool = True,
    text_background_clear: bool = True,
    text_overlaps_primary_subject: bool = False,
    text_background_overlaps_primary_subject: bool = False,
    minimum_source_font_px: int = 32,
    decorative_frame_area_ratio: float = 0.0,
    primary_subject_area_ratio: float = 0.8,
    typehouse_offer_creative: bool = True,
    offer_block_contiguous: bool = True,
    offer_current_month_present: bool = True,
    offer_model_name_present: bool = True,
    offer_gross_area_m2_present: bool = True,
    offer_selling_price_present: bool = True,
    offer_price_plus_vat_present: bool = True,
    discount_percentage_on_creative: bool = False,
    original_price_on_creative: bool = False,
    net_price_word_on_creative: bool = False,
    build_time_label_plain: bool = True,
    legal_disclaimer_on_impulse_creative: bool = False,
    logo_lockup_brand_native: bool = True,
    proof_caption_present: bool = False,
    proof_caption_semantically_complete: bool = True,
) -> dict[str, object]:
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
        "full_subject_expected": full_subject_expected,
        "full_subject_contour_visible": full_subject_contour_visible,
        "accidental_crop_absent": accidental_crop_absent,
        "text_boxes_within_bounds": text_boxes_within_bounds,
        "text_background_clear": text_background_clear,
        "text_overlaps_primary_subject": text_overlaps_primary_subject,
        "text_background_overlaps_primary_subject": text_background_overlaps_primary_subject,
        "minimum_source_font_px": minimum_source_font_px,
        "decorative_frame_area_ratio": decorative_frame_area_ratio,
        "primary_subject_dominance_required": True,
        "primary_subject_area_ratio": primary_subject_area_ratio,
        "typehouse_offer_creative": typehouse_offer_creative,
        "offer_block_contiguous": offer_block_contiguous,
        "offer_current_month_present": offer_current_month_present,
        "offer_model_name_present": offer_model_name_present,
        "offer_gross_area_m2_present": offer_gross_area_m2_present,
        "offer_selling_price_present": offer_selling_price_present,
        "offer_price_plus_vat_present": offer_price_plus_vat_present,
        "discount_percentage_on_creative": discount_percentage_on_creative,
        "original_price_on_creative": original_price_on_creative,
        "net_price_word_on_creative": net_price_word_on_creative,
        "build_time_label_plain": build_time_label_plain,
        "legal_disclaimer_on_impulse_creative": legal_disclaimer_on_impulse_creative,
        "logo_lockup_brand_native": logo_lockup_brand_native,
        "proof_caption_present": proof_caption_present,
        "proof_caption_semantically_complete": proof_caption_semantically_complete,
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


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                full_subject_contour_visible=False,
            ),
            "épületsaroknak",
        ),
        (
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                accidental_crop_absent=False,
            ),
            "Véletlen képkivágás",
        ),
        (
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                text_boxes_within_bounds=False,
            ),
            "képhatáron belül",
        ),
        (
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                text_background_clear=False,
            ),
            "képzaj",
        ),
        (
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                text_overlaps_primary_subject=True,
            ),
            "Szöveg nem takarhat",
        ),
        (
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                text_background_overlaps_primary_subject=True,
            ),
            "Szövegdoboz",
        ),
        (
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                minimum_source_font_px=24,
            ),
            "32 px",
        ),
        (
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                decorative_frame_area_ratio=0.2,
            ),
            "8%",
        ),
        (
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                primary_subject_area_ratio=0.3,
            ),
            "45%",
        ),
        (
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                primary_subject_area_ratio=0.7,
            ),
            "75%",
        ),
        (
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                logo_lockup_brand_native=False,
            ),
            "márkanatív",
        ),
        (
            trace(
                "A",
                "documentary-site-control",
                "GEN-A",
                proof_caption_present=True,
                proof_caption_semantically_complete=False,
            ),
            "teljes jelentésével",
        ),
    ],
)
def test_visual_variant_blocks_crop_overflow_interference_and_weak_subject(candidate, message):
    with pytest.raises(ValueError, match=message):
        validate_visual_variant_trace(candidate)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"offer_block_contiguous": False}, "egyetlen összefüggő"),
        ({"offer_current_month_present": False}, "akció hónapja"),
        ({"offer_model_name_present": False}, "típusház neve"),
        ({"offer_gross_area_m2_present": False}, "bruttó m²"),
        ({"offer_selling_price_present": False}, "eladási ára"),
        ({"offer_price_plus_vat_present": False}, r"\+ ÁFA"),
        ({"build_time_label_plain": False}, "Építési idő"),
        ({"discount_percentage_on_creative": True}, "kedvezményszázalék"),
        ({"original_price_on_creative": True}, "eredeti ár"),
        ({"net_price_word_on_creative": True}, "nettó"),
        ({"legal_disclaimer_on_impulse_creative": True}, "jogi apróbetű"),
    ],
)
def test_typehouse_impulse_offer_blocks_fragmented_or_excessive_copy(overrides, message):
    candidate = trace("A", "documentary-site-control", "GEN-A", **overrides)

    with pytest.raises(ValueError, match=message):
        validate_visual_variant_trace(candidate)


def test_visual_variant_allows_declared_intentional_crop():
    candidate = trace(
        "A",
        "editorial-detail-crop",
        "GEN-A",
        full_subject_expected=False,
        full_subject_contour_visible=False,
    )
    candidate["declared_crop_intent"] = (
        "Az építészeti részletet dokumentáló, előre tervezett homlokzati kivágás."
    )

    validate_visual_variant_trace(candidate)
