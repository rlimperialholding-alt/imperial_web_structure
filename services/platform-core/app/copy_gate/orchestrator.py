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
