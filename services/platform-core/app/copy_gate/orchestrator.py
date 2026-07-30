from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .models import CopyBrief

GENERATION_STAGES = (
    "SOURCE_RESOLUTION",
    "OFFER_CORE",
    "HOOK_AND_BIG_IDEA",
    "FIRST_DRAFT",
    "BRAND_VOICE_EDIT",
    "DIRECT_RESPONSE_CRITIQUE",
    "HUNGARIAN_EDIT",
    "CLAIM_FACT_VALIDATION",
    "MESSAGE_MATCH",
)

VISUAL_VARIANT_TRACE_FIELDS = (
    "variant_set_id",
    "creative_variant_id",
    "visual_direction_id",
    "generation_run_id",
)

VISUAL_LAYOUT_TRACE_FIELDS = (
    "layout_archetype_id",
    "composition_signature",
    "primary_text_zone",
    "image_treatment",
    "background_treatment",
    "minimum_text_contrast_ratio",
    "full_subject_expected",
    "full_subject_contour_visible",
    "accidental_crop_absent",
    "text_boxes_within_bounds",
    "text_background_clear",
    "text_overlaps_primary_subject",
    "text_background_overlaps_primary_subject",
    "minimum_source_font_px",
    "decorative_frame_area_ratio",
    "primary_subject_dominance_required",
    "primary_subject_area_ratio",
    "logo_lockup_brand_native",
    "proof_caption_present",
    "proof_caption_semantically_complete",
)

COPY_VARIATION_MODES = {
    "verbatim_source",
    "source_adaptation",
    "original_concept",
}

COPY_VARIATION_TRACE_FIELDS = (
    "brand_id",
    "generation_run_id",
    "copy_mode",
    "copy_fingerprint",
    "copy_concept_id",
    "copy_architecture_id",
    "copy_structure_signature",
    "source_text_usage_ratio",
    "creative_quality_benchmark_id",
    "creative_rationale",
    "introduces_new_factual_claims",
    "human_fact_review_required",
    "consumer_promise_plain_language",
    "promise_reason_or_mechanism",
    "offer_terms_plain_language",
    "cta_next_step_plain_language",
)

CREATIVE_QUALITY_BENCHMARKS = {
    "prefab-facebook-etalon-v1",
}


def validate_copy_variation_trace(
    trace: dict[str, Any],
    *,
    sibling_traces: list[dict[str, Any]] | None = None,
) -> None:
    """Require original, professional copy without inventing unvalidated facts."""

    sibling_traces = sibling_traces or []
    missing = [field for field in COPY_VARIATION_TRACE_FIELDS if trace.get(field) in (None, "")]
    if missing:
        raise ValueError("A kreatív szöveg kötelező trace mezői hiányoznak: " + ", ".join(missing))

    copy_mode = str(trace["copy_mode"])
    if copy_mode not in COPY_VARIATION_MODES:
        raise ValueError("Ismeretlen copy_mode.")

    try:
        source_text_usage_ratio = float(trace["source_text_usage_ratio"])
    except (TypeError, ValueError) as exc:
        raise ValueError("A szöveghasználati arány szám kell legyen.") from exc
    if not 0 <= source_text_usage_ratio <= 1:
        raise ValueError("A source_text_usage_ratio 0 és 1 közötti érték.")
    if "professional_copy_quality_score" in trace:
        raise ValueError(
            "A professional_copy_quality_score nem lehet generátori önminősítés. "
            "A minőséget a kötelező, független szakértői GateResult igazolja."
        )

    benchmark_id = str(trace["creative_quality_benchmark_id"])
    if benchmark_id not in CREATIVE_QUALITY_BENCHMARKS:
        raise ValueError("Ismeretlen creative_quality_benchmark_id.")
    if len(str(trace["creative_rationale"]).strip()) < 20:
        raise ValueError("A kreatív koncepció indoklása legalább 20 karakter.")
    clarity_fields = {
        "consumer_promise_plain_language": 10,
        "promise_reason_or_mechanism": 10,
        "offer_terms_plain_language": 10,
        "cta_next_step_plain_language": 10,
    }
    weak_clarity = [
        field
        for field, minimum_length in clarity_fields.items()
        if len(str(trace[field]).strip()) < minimum_length
    ]
    if weak_clarity:
        raise ValueError(
            "A fogyasztói ígéret, annak oka, az ajánlat és a következő lépés "
            "köznyelvi magyarázata kötelező: " + ", ".join(weak_clarity)
        )

    copy_architecture_id = str(trace["copy_architecture_id"])
    copy_structure_signature = str(trace["copy_structure_signature"])
    if len(copy_architecture_id.strip()) < 8 or len(copy_structure_signature.strip()) < 12:
        raise ValueError(
            "A copy_architecture_id és copy_structure_signature nem lehet általános "
            "vagy üres szerkezeti címke."
        )

    introduces_new_facts = trace["introduces_new_factual_claims"] is True
    human_fact_review_required = trace["human_fact_review_required"] is True
    requests_source_prevalidation = trace.get("source_prevalidation_requested") is True

    if copy_mode == "verbatim_source":
        if source_text_usage_ratio < 0.9:
            raise ValueError("A verbatim_source mód legalább 90% forrásszöveg-használatot jelent.")
        if introduces_new_facts:
            raise ValueError("A verbatim_source mód nem tartalmazhat új tényállítást.")
    elif copy_mode == "source_adaptation":
        if source_text_usage_ratio >= 0.9:
            raise ValueError("A source_adaptation mód nem lehet szinte teljesen betű szerinti.")
        if trace.get("meaning_preservation_checked") is not True:
            raise ValueError("Átfogalmazásnál kötelező a jelentésmegőrzési ellenőrzés.")
    elif source_text_usage_ratio > 0.5:
        raise ValueError("Az original_concept mód legfeljebb 50% forrásszöveget használhat.")

    if introduces_new_facts and not human_fact_review_required:
        raise ValueError("Új tény, ár, garancia vagy vállalás emberi tényellenőrzést igényel.")
    if requests_source_prevalidation and copy_mode != "verbatim_source":
        raise ValueError(
            "Csak betű szerinti forrás használhat SOURCE_PREVALIDATED gyorsított utat."
        )

    copy_fingerprint = str(trace["copy_fingerprint"])
    for sibling in sibling_traces:
        if sibling.get("copy_fingerprint") == copy_fingerprint:
            raise ValueError("A copy_fingerprint nem ismétlődhet ugyanazon brief assetjei között.")
        if sibling.get("generation_run_id") == trace["generation_run_id"]:
            raise ValueError(
                "Külön kreatívhoz és külön márkához külön generation_run_id szükséges."
            )
        if sibling.get("copy_architecture_id") == copy_architecture_id:
            raise ValueError(
                "A copy_architecture_id nem ismétlődhet ugyanazon kampánycsalád "
                "assetjei vagy márkái között."
            )
        if sibling.get("copy_structure_signature") == copy_structure_signature:
            raise ValueError(
                "A bekezdéssorrend és érvelési szerkezet nem ismétlődhet ugyanazon "
                "kampánycsalád assetjei vagy márkái között."
            )

    copy_traces = [item for item in sibling_traces if item.get("copy_mode")] + [trace]
    if len(copy_traces) >= 2:
        verbatim_share = sum(
            item.get("copy_mode") == "verbatim_source" for item in copy_traces
        ) / len(copy_traces)
        if verbatim_share > 0.5:
            raise ValueError(
                "Egy kreatív készlet legfeljebb fele lehet betű szerinti forrásmásolat; "
                "kreatív átfogalmazás vagy új koncepció szükséges."
            )


def copy_mode_allows_source_prevalidation(trace: dict[str, Any]) -> bool:
    """Only unchanged source copy can use the shortened publication path."""

    return (
        trace.get("copy_mode") == "verbatim_source"
        and trace.get("introduces_new_factual_claims") is False
    )


def validate_visual_variant_trace(
    trace: dict[str, Any],
    *,
    sibling_traces: list[dict[str, Any]] | None = None,
) -> None:
    """Enforce independent runs and directions for A/B/C visual variants."""

    sibling_traces = sibling_traces or []
    variant_fields_present = any(trace.get(field) for field in VISUAL_VARIANT_TRACE_FIELDS[:-1])
    if not variant_fields_present:
        return

    required_fields = VISUAL_VARIANT_TRACE_FIELDS + VISUAL_LAYOUT_TRACE_FIELDS
    missing = [field for field in required_fields if trace.get(field) in (None, "")]
    if missing:
        raise ValueError(
            "A vizuális variánsfutás kötelező trace mezői hiányoznak: " + ", ".join(missing)
        )

    try:
        minimum_text_contrast_ratio = float(trace["minimum_text_contrast_ratio"])
    except (TypeError, ValueError) as exc:
        raise ValueError("A minimum_text_contrast_ratio szám kell legyen.") from exc
    if minimum_text_contrast_ratio < 4.5:
        raise ValueError("A kreatív normál szövegének WCAG-kontrasztja legalább 4.5:1 legyen.")

    if trace["accidental_crop_absent"] is not True:
        raise ValueError("Véletlen képkivágás mellett kreatív nem hagyható jóvá.")
    if trace["text_boxes_within_bounds"] is not True:
        raise ValueError("Minden szövegdoboznak és címkének a képhatáron belül kell maradnia.")
    if trace["text_background_clear"] is not True:
        raise ValueError("Dekoratív minta vagy képzaj nem ronthatja a szöveg olvashatóságát.")
    if trace["text_overlaps_primary_subject"] is not False:
        raise ValueError("Szöveg nem takarhat rá a típusházra vagy más elsődleges képi témára.")
    if trace["text_background_overlaps_primary_subject"] is not False:
        raise ValueError(
            "Szövegdoboz vagy annak háttere nem takarhat rá az elsődleges képi témára."
        )
    try:
        minimum_source_font_px = int(trace["minimum_source_font_px"])
    except (TypeError, ValueError) as exc:
        raise ValueError("A minimum_source_font_px egész szám kell legyen.") from exc
    if minimum_source_font_px < 32:
        raise ValueError(
            "Facebook-kreatívon a legkisebb szerkesztett betűméret legalább 32 px "
            "legyen 1080 px széles forrásképen; a hivatalos tanúsítási logók kivételek."
        )
    if trace["logo_lockup_brand_native"] is not True:
        raise ValueError("A logó csak márkanatív, arculatilag jóváhagyott lockupban helyezhető el.")
    if (
        trace["proof_caption_present"] is True
        and trace["proof_caption_semantically_complete"] is not True
    ):
        raise ValueError(
            "Bizalmi jelzés képaláírása csak a díj vagy minősítés teljes jelentésével "
            "együtt használható; önálló rövidítés nem engedélyezett."
        )

    full_subject_expected = trace["full_subject_expected"] is True
    if full_subject_expected and trace["full_subject_contour_visible"] is not True:
        raise ValueError(
            "Teljes típusház-bemutatásnál minden tető-, fal- és épületsaroknak látszania kell."
        )
    if not full_subject_expected and len(str(trace.get("declared_crop_intent") or "").strip()) < 20:
        raise ValueError(
            "Részleges képkivágás csak előre deklarált, legalább 20 karakteres "
            "kompozíciós céllal engedélyezett."
        )

    try:
        decorative_frame_area_ratio = float(trace["decorative_frame_area_ratio"])
        primary_subject_area_ratio = float(trace["primary_subject_area_ratio"])
    except (TypeError, ValueError) as exc:
        raise ValueError("A keret- és főtéma-terület aránya szám kell legyen.") from exc
    if not 0 <= decorative_frame_area_ratio <= 1 or not 0 <= primary_subject_area_ratio <= 1:
        raise ValueError("A keret- és főtéma-terület aránya 0 és 1 közötti érték.")
    if decorative_frame_area_ratio > 0.08 and not trace.get(
        "decorative_frame_exception_approved_by"
    ):
        raise ValueError("A céltalan dekoratív keret legfeljebb a kreatív 8%-át foglalhatja el.")
    if trace["primary_subject_dominance_required"] is True and primary_subject_area_ratio < 0.45:
        raise ValueError("Főtémás kreatívnál az elsődleges képi téma legalább 45% legyen.")
    if trace.get("typehouse_offer_creative") is True:
        if primary_subject_area_ratio < 0.75:
            raise ValueError("Típusház-fókuszú kreatívnál a ház képi területe legalább 75% legyen.")
        offer_fields = (
            "offer_block_contiguous",
            "offer_current_month_present",
            "offer_model_name_present",
            "offer_gross_area_m2_present",
            "offer_selling_price_present",
            "offer_price_plus_vat_present",
            "discount_percentage_on_creative",
            "original_price_on_creative",
            "net_price_word_on_creative",
            "build_time_label_plain",
            "legal_disclaimer_on_impulse_creative",
        )
        missing_offer_fields = [
            field for field in offer_fields if field not in trace or trace[field] is None
        ]
        if missing_offer_fields:
            raise ValueError(
                "A típusház-ajánlat kötelező vizuális trace mezői hiányoznak: "
                + ", ".join(missing_offer_fields)
            )
        required_offer_truths = (
            "offer_block_contiguous",
            "offer_current_month_present",
            "offer_model_name_present",
            "offer_gross_area_m2_present",
            "offer_selling_price_present",
            "offer_price_plus_vat_present",
            "build_time_label_plain",
        )
        if any(trace[field] is not True for field in required_offer_truths):
            raise ValueError(
                "Az akció hónapja, a típusház neve, bruttó m²-e, eladási ára és + ÁFA "
                "jelölése egyetlen összefüggő ajánlati blokkban kötelező; az építési "
                "idő felirata csak „Építési idő” lehet."
            )
        forbidden_impulse_details = (
            "discount_percentage_on_creative",
            "original_price_on_creative",
            "net_price_word_on_creative",
            "legal_disclaimer_on_impulse_creative",
        )
        if any(trace[field] is not False for field in forbidden_impulse_details):
            raise ValueError(
                "Első impulzusos típusház-kreatívon nem szerepelhet kedvezményszázalék, "
                "eredeti ár, „nettó” felirat vagy jogi apróbetű."
            )

    background_treatment = str(trace["background_treatment"]).casefold()
    uses_gradient = "gradient" in background_treatment or bool(
        trace.get("uses_background_gradient")
    )
    if uses_gradient and not trace.get("background_gradient_exception_approved_by"):
        raise ValueError(
            "A színátmenetes kreatívháttér alapértelmezetten tiltott; "
            "csak dokumentált emberi kivétellel használható."
        )

    variant_set_id = trace["variant_set_id"]
    for sibling in sibling_traces:
        if sibling.get("variant_set_id") != variant_set_id:
            continue
        if sibling.get("generation_run_id") == trace["generation_run_id"]:
            raise ValueError("Azonos brief A/B/C variánsaihoz külön generation_run_id szükséges.")
        if sibling.get("creative_variant_id") == trace["creative_variant_id"]:
            raise ValueError("A creative_variant_id a variánskészleten belül egyedi.")
        if sibling.get("visual_direction_id") == trace["visual_direction_id"]:
            raise ValueError(
                "Azonos brief valódi A/B/C variánsaihoz külön visual_direction_id szükséges."
            )
        if sibling.get("layout_archetype_id") == trace["layout_archetype_id"]:
            raise ValueError("A variánskészletben a layout_archetype_id nem ismétlődhet.")
        if sibling.get("composition_signature") == trace["composition_signature"]:
            raise ValueError("A variánskészletben a composition_signature nem ismétlődhet.")
        sibling_structure = (
            sibling.get("primary_text_zone"),
            sibling.get("image_treatment"),
            sibling.get("background_treatment"),
        )
        candidate_structure = (
            trace["primary_text_zone"],
            trace["image_treatment"],
            trace["background_treatment"],
        )
        if sibling_structure == candidate_structure:
            raise ValueError(
                "A szövegpozíció, képhasználat és háttérkezelés együttes "
                "szerkezete nem ismétlődhet."
            )


class CopyStageAdapter(Protocol):
    """External model adapter; credentials stay in the platform secret manager."""

    model_version: str
    prompt_version: str

    def run_stage(
        self,
        *,
        stage: str,
        brief: CopyBrief,
        canonical_sources: dict[str, Any],
        previous_output: dict[str, Any],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GenerationResult:
    output: dict[str, Any]
    trace: dict[str, Any]


class CopyGenerationOrchestrator:
    """Runs every copy-production stage explicitly and records its provenance."""

    def __init__(self, adapter: CopyStageAdapter):
        self.adapter = adapter

    def generate(
        self,
        *,
        generation_run_id: str,
        brief: CopyBrief,
        canonical_sources: dict[str, Any],
    ) -> GenerationResult:
        if not generation_run_id:
            raise ValueError("generation_run_id kötelező.")
        output: dict[str, Any] = {}
        stage_hashes: dict[str, str] = {}
        for stage in GENERATION_STAGES:
            output = self.adapter.run_stage(
                stage=stage,
                brief=brief,
                canonical_sources=canonical_sources,
                previous_output=output,
            )
            if not isinstance(output, dict) or not output:
                raise ValueError(f"A(z) {stage} szakasz nem adott strukturált kimenetet.")
            stage_hashes[stage] = str(output.get("artifact_hash") or "")
        return GenerationResult(
            output=output,
            trace={
                "generation_run_id": generation_run_id,
                "model_version": self.adapter.model_version,
                "prompt_version": self.adapter.prompt_version,
                "stages": list(GENERATION_STAGES),
                "stage_hashes": stage_hashes,
            },
        )
