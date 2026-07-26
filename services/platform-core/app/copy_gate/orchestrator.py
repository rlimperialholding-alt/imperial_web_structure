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

    missing = [field for field in VISUAL_VARIANT_TRACE_FIELDS if not trace.get(field)]
    if missing:
        raise ValueError(
            "A vizuális variánsfutás kötelező trace mezői hiányoznak: " + ", ".join(missing)
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
