from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Decision(StrEnum):
    APPROVED = "APPROVED"
    RETURN_FOR_REVISION = "RETURN_FOR_REVISION"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    SKIPPED_NOT_RELEVANT = "SKIPPED_NOT_RELEVANT"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class PublicationState(StrEnum):
    DRAFT = "DRAFT"
    COPY_QA = "COPY_QA"
    FOUR_GATE_QA = "FOUR_GATE_QA"
    HUMAN_EDITORIAL = "HUMAN_EDITORIAL"
    OWNER_APPROVAL = "OWNER_APPROVAL"
    PUBLISHED = "PUBLISHED"
    BLOCKED = "BLOCKED"


class CopyBrief(BaseModel):
    copy_brief_id: str = Field(min_length=3, max_length=120)
    brand_id: str = Field(min_length=2, max_length=100)
    asset_type: str = Field(min_length=2, max_length=80)
    channel: str = Field(min_length=2, max_length=80)
    page_id: str | None = Field(default=None, max_length=120)
    campaign_id: str | None = Field(default=None, max_length=120)
    campaign_objective: str = Field(min_length=3)
    primary_conversion: str = Field(min_length=2)
    target_persona_id: str = Field(min_length=2, max_length=120)
    awareness_level: str = Field(min_length=2, max_length=80)
    market_sophistication_level: str = Field(min_length=2, max_length=80)
    core_problem: str = Field(min_length=8)
    desired_outcome: str = Field(min_length=8)
    primary_promise: str = Field(min_length=8)
    unique_mechanism: str = Field(min_length=8)
    offer_version_id: str = Field(min_length=2, max_length=120)
    price_snapshot_id: str = Field(min_length=2, max_length=120)
    terms_version_id: str = Field(min_length=2, max_length=120)
    claim_ids: list[str] = Field(min_length=1)
    proof_ids: list[str] = Field(min_length=1)
    product_id: str | None = Field(default=None, max_length=120)
    house_plan_id: str | None = Field(default=None, max_length=120)
    primary_objection_ids: list[str] = Field(min_length=1)
    secondary_objection_ids: list[str] = Field(default_factory=list)
    risk_reversal: str = Field(min_length=5)
    urgency_reason: str | None = None
    scarcity_reason: str | None = None
    primary_cta_type: str = Field(min_length=2, max_length=80)
    secondary_cta_type: str | None = Field(default=None, max_length=80)
    brand_voice_profile: str = Field(min_length=2, max_length=120)
    required_slogan: str = Field(min_length=3)
    required_slogan_version: str = Field(min_length=1, max_length=80)
    forbidden_phrases: list[str] = Field(default_factory=list)
    required_keywords: list[str] = Field(default_factory=list)
    landing_message_match_id: str = Field(min_length=2, max_length=120)
    valid_from: date
    valid_until: date

    @model_validator(mode="after")
    def validate_scope(self) -> CopyBrief:
        if bool(self.page_id) == bool(self.campaign_id):
            raise ValueError("Pontosan az egyik kötelező: page_id vagy campaign_id.")
        if bool(self.product_id) == bool(self.house_plan_id):
            raise ValueError("Pontosan az egyik kötelező: product_id vagy house_plan_id.")
        if self.valid_until < self.valid_from:
            raise ValueError("A valid_until nem lehet korábbi a valid_from dátumnál.")
        return self


class ContentBlock(BaseModel):
    block_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1)
    layout_signature: str = Field(min_length=1, max_length=255)


class ContentAsset(BaseModel):
    asset_id: str = Field(min_length=3, max_length=120)
    title: str = Field(min_length=8)
    body: str = Field(min_length=20)
    cta: str = Field(min_length=3)
    cta_type_used: str = Field(min_length=2, max_length=80)
    slogan: str = Field(min_length=3)
    slogan_version_used: str = Field(min_length=1, max_length=80)
    content_blocks: list[ContentBlock] = Field(default_factory=list)
    detected_brand_ids: list[str] = Field(min_length=1)
    claim_ids_used: list[str] = Field(default_factory=list)
    proof_ids_used: list[str] = Field(default_factory=list)
    objection_ids_handled: list[str] = Field(default_factory=list)
    required_keywords_used: list[str] = Field(default_factory=list)
    offer_version_id_used: str = Field(min_length=2, max_length=120)
    price_snapshot_id_used: str = Field(min_length=2, max_length=120)
    terms_version_id_used: str = Field(min_length=2, max_length=120)
    landing_message_match_id_used: str = Field(min_length=2, max_length=120)
    factual_claims: list[str] = Field(default_factory=list)
    price_mentions: list[str] = Field(default_factory=list)
    deadline_mentions: list[str] = Field(default_factory=list)
    condition_mentions: list[str] = Field(default_factory=list)
    visual_asset_ids: list[str] = Field(default_factory=list)
    visual_quality_score: int | None = Field(default=None, ge=0, le=100)
    visual_findings: list[str] = Field(default_factory=list)


class CanonicalSources(BaseModel):
    source_resolution_pass: bool
    source_versions: dict[str, str] = Field(default_factory=dict)
    source_conflicts: list[str] = Field(default_factory=list)
    active_offer: bool
    active_price: bool
    active_terms: bool
    active_product: bool
    claims_resolved: list[str] = Field(default_factory=list)
    proofs_resolved: list[str] = Field(default_factory=list)
    visuals_resolved: list[str] = Field(default_factory=list)
    brand_addressing: str
    required_brand_concepts: list[str] = Field(default_factory=list)
    forbidden_brand_phrases: list[str] = Field(default_factory=list)


class EditorialReview(BaseModel):
    decision: Decision
    reviewer_run_id: str = Field(min_length=3, max_length=120)
    generation_run_id: str = Field(min_length=3, max_length=120)
    model_version: str = Field(min_length=2, max_length=120)
    prompt_version: str = Field(min_length=2, max_length=120)
    findings: list[str] = Field(default_factory=list)


class ContentEvaluationRequest(BaseModel):
    brief: CopyBrief
    sources: CanonicalSources
    asset: ContentAsset
    editorial_review: EditorialReview
    evaluated_on: date


class Finding(BaseModel):
    code: str
    message: str
    severity: Severity
    location: str | None = None
    violated_source: str | None = None
    repair_instruction: str | None = None


class DimensionScore(BaseModel):
    name: str
    score: int
    max_score: int = 10
    pass_threshold: int = 8
    passed: bool
    findings: list[Finding] = Field(default_factory=list)


class GateResult(BaseModel):
    gate_id: str
    agent_id: str
    decision: Decision
    relevance: bool
    certainty: str
    findings: list[Finding] = Field(default_factory=list)
    source_versions: dict[str, str] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    total_score: int
    max_score: int = 100
    threshold: int = 92
    dimensions: list[DimensionScore]
    gate_1: GateResult
    final_decision: Decision
    publication_blocked: bool
    repair_brief: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpecialistGateSubmission(BaseModel):
    gate_id: str
    agent_id: str
    decision: Decision
    certainty: str = Field(pattern="^(LOW|MEDIUM|HIGH)$")
    findings: list[Finding] = Field(default_factory=list)
    source_versions: dict[str, str] = Field(default_factory=dict)


class FourGateSubmission(BaseModel):
    legal_relevant: bool
    financial_relevant: bool
    technical_relevant: bool
    specialist_results: list[SpecialistGateSubmission] = Field(default_factory=list)


class ApprovalSubmission(BaseModel):
    decision: str = Field(pattern="^(APPROVED|REJECTED)$")
    note: str | None = Field(default=None, max_length=2000)


class PerformanceMetricIn(BaseModel):
    metric_type: str = Field(
        pattern=(
            "^(read_depth|form_start|form_complete|qualified_lead|appointment|"
            "offer|contract|margin|cancellation|bad_lead_reason|ctr)$"
        )
    )
    numeric_value: float | None = None
    text_value: str | None = Field(default=None, max_length=2000)
    occurred_on: date


class CopySourceIn(BaseModel):
    source_key: str = Field(min_length=3, max_length=160)
    source_type: str = Field(min_length=2, max_length=80)
    brand_id: str = Field(min_length=2, max_length=100)
    page_id: str | None = Field(default=None, max_length=120)
    campaign_id: str | None = Field(default=None, max_length=120)
    asset_type: str | None = Field(default=None, max_length=80)
    version: str = Field(min_length=1, max_length=80)
    priority: int = Field(default=100, ge=1, le=1000)
    status: str = Field(default="approved", pattern="^(draft|approved|retired)$")
    approved: bool = False
    valid_from: date | None = None
    valid_until: date | None = None
    source_url: str | None = Field(default=None, max_length=1000)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_validity(self) -> CopySourceIn:
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("A valid_until nem lehet korábbi a valid_from dátumnál.")
        if self.status == "approved" and not self.approved:
            raise ValueError("Approved státuszhoz approved=true szükséges.")
        return self


class ContentAssetCreateRequest(BaseModel):
    copy_brief_id: str = Field(min_length=3, max_length=120)
    project_id: str | None = Field(default=None, max_length=100)
    asset: ContentAsset
    generation_trace: dict[str, Any]


class CopyQualityRequest(BaseModel):
    editorial_review: EditorialReview
    evaluated_on: date | None = None


class PerformanceSubmission(BaseModel):
    source_system: str = Field(min_length=2, max_length=100)
    metric: PerformanceMetricIn
