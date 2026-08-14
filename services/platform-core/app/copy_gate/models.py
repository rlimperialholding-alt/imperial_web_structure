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
    SPECIALIST_QA = "SPECIALIST_QA"
    FOUR_GATE_QA = "FOUR_GATE_QA"
    HUMAN_EDITORIAL = "HUMAN_EDITORIAL"
    OWNER_APPROVAL = "OWNER_APPROVAL"
    SOURCE_PREVALIDATED = "SOURCE_PREVALIDATED"
    VISUAL_PRODUCTION = "VISUAL_PRODUCTION"
    CREATIVE_DIRECTOR_QA = "CREATIVE_DIRECTOR_QA"
    ASSEMBLY_QA = "ASSEMBLY_QA"
    RELEASE_QA = "RELEASE_QA"
    RELEASE_APPROVED = "RELEASE_APPROVED"
    LIVE_QA = "LIVE_QA"
    QUARANTINED = "QUARANTINED"
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
    monthly_promotion_id: str | None = Field(default=None, max_length=160)
    monthly_promotion_copy_required: bool = False
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
        if self.monthly_promotion_copy_required and not self.monthly_promotion_id:
            raise ValueError("Kötelező havi akciós szöveghez monthly_promotion_id szükséges.")
        return self


class ContentBlock(BaseModel):
    block_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1)
    layout_signature: str = Field(min_length=1, max_length=255)


class ExternalActionType(StrEnum):
    MARKETING_COMMUNICATION = "marketing_communication"
    EXTERNAL_COMMITMENT = "external_commitment"
    CONTRACT_MODIFICATION = "contract_modification"
    LIABILITY_ADMISSION = "liability_admission"
    PERFORMANCE_ACCEPTANCE = "performance_acceptance"


class PrevalidatedSourceEvidence(BaseModel):
    evidence_id: str = Field(min_length=3, max_length=160)
    category: str = Field(pattern="^(commercial|price|technical|legal|typehouse|floorplan)$")
    source_type: str = Field(pattern="^(website_fragment|website_visual|drive_price_calculator)$")
    source_ref: str = Field(min_length=3, max_length=200)
    source_url: str | None = Field(default=None, max_length=2000)
    source_version: str = Field(min_length=3, max_length=200)
    source_sha256: str | None = Field(default=None, pattern="^[0-9a-fA-F]{64}$")
    source_fragment: str | None = None
    source_fragment_sha256: str | None = Field(default=None, pattern="^[0-9a-fA-F]{64}$")
    claim_text: str | None = None
    visual_asset_id: str | None = Field(default=None, max_length=200)
    visual_asset_url: str | None = Field(default=None, max_length=2000)
    visual_reference_sha256: str | None = Field(default=None, pattern="^[0-9a-fA-F]{64}$")
    price_input: dict[str, str] = Field(default_factory=dict)
    price_output_field: str | None = Field(default=None, max_length=120)
    price_value_huf: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_source_shape(self) -> PrevalidatedSourceEvidence:
        if self.source_type == "website_fragment":
            if not all(
                [
                    self.source_url,
                    self.source_fragment,
                    self.source_fragment_sha256,
                    self.claim_text,
                ]
            ):
                raise ValueError("A website_fragment bizonyíték forrása vagy fragmentuma hiányzik.")
        elif self.source_type == "website_visual":
            if not all(
                [
                    self.source_url,
                    self.visual_asset_id,
                    self.visual_asset_url,
                    self.visual_reference_sha256,
                ]
            ):
                raise ValueError(
                    "A website_visual bizonyíték assetazonosítója vagy URL-je hiányzik."
                )
        elif not all(
            [
                self.source_sha256,
                self.price_input,
                self.price_output_field,
                self.price_value_huf is not None,
            ]
        ):
            raise ValueError("A drive_price_calculator bizonyíték számítási adatai hiányoznak.")
        return self


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
    monthly_promotion_id_used: str | None = Field(default=None, max_length=160)
    monthly_promotion_copy_text: str | None = None
    monthly_promotion_copy_position: int | None = Field(default=None, ge=0)
    monthly_promotion_on_creative: bool = False
    factual_claims: list[str] = Field(default_factory=list)
    price_mentions: list[str] = Field(default_factory=list)
    deadline_mentions: list[str] = Field(default_factory=list)
    condition_mentions: list[str] = Field(default_factory=list)
    visual_asset_ids: list[str] = Field(default_factory=list)
    visual_quality_score: int | None = Field(default=None, ge=0, le=100)
    visual_findings: list[str] = Field(default_factory=list)
    prevalidated_source_evidence: list[PrevalidatedSourceEvidence] = Field(default_factory=list)
    action_risk_level: int = Field(default=0, ge=0, le=7)
    external_action_type: ExternalActionType = ExternalActionType.MARKETING_COMMUNICATION


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
    monthly_promotion_id: str | None = Field(default=None, max_length=160)
    monthly_promotion_copy_required: bool = False
    monthly_promotion_publication_allowed: bool = False


class EditorialReview(BaseModel):
    decision: Decision
    reviewed_asset_id: str = Field(min_length=3, max_length=120)
    reviewed_content_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    reviewer_run_id: str = Field(min_length=3, max_length=120)
    generation_run_id: str = Field(min_length=3, max_length=120)
    reviewer_identity: str = Field(min_length=3, max_length=160)
    reviewer_type: str = Field(pattern="^(independent_ai|human_expert)$")
    attestation_key_id: str = Field(min_length=3, max_length=120)
    attestation_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    model_version: str = Field(min_length=2, max_length=120)
    prompt_version: str = Field(min_length=2, max_length=120)
    idiomatic_hungarian_score: int = Field(ge=0, le=10)
    grammar_score: int = Field(ge=0, le=10)
    semantic_clarity_score: int = Field(ge=0, le=10)
    terminology_score: int = Field(ge=0, le=10)
    hook_strength_score: int = Field(ge=0, le=10)
    offer_clarity_score: int = Field(ge=0, le=10)
    specificity_score: int = Field(ge=0, le=10)
    persuasion_score: int = Field(ge=0, le=10)
    brand_voice_score: int = Field(ge=0, le=10)
    conversion_path_score: int = Field(ge=0, le=10)
    consumer_interpretation: str = Field(min_length=20, max_length=2000)
    offer_interpretation: str = Field(min_length=20, max_length=2000)
    cta_interpretation: str = Field(min_length=20, max_length=1000)
    ambiguous_phrases: list[str] = Field(default_factory=list)
    unnatural_phrases: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    required_repairs: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_expert_review(self) -> EditorialReview:
        if self.reviewer_run_id == self.generation_run_id:
            raise ValueError("A generáló és a szakértői ellenőrző futás nem lehet azonos.")
        if self.decision != Decision.APPROVED:
            return self
        scores = {
            "idiomatic_hungarian_score": self.idiomatic_hungarian_score,
            "grammar_score": self.grammar_score,
            "semantic_clarity_score": self.semantic_clarity_score,
            "terminology_score": self.terminology_score,
            "hook_strength_score": self.hook_strength_score,
            "offer_clarity_score": self.offer_clarity_score,
            "specificity_score": self.specificity_score,
            "persuasion_score": self.persuasion_score,
            "brand_voice_score": self.brand_voice_score,
            "conversion_path_score": self.conversion_path_score,
        }
        weak = [name for name, score in scores.items() if score < 9]
        if weak:
            raise ValueError(
                "APPROVED szakértői döntéshez minden nyelvi és marketingdimenzió "
                f"minimuma 9/10. Gyenge dimenziók: {', '.join(weak)}."
            )
        unresolved = (
            self.ambiguous_phrases
            + self.unnatural_phrases
            + self.unsupported_claims
            + self.required_repairs
            + self.findings
        )
        if unresolved:
            raise ValueError(
                "APPROVED szakértői döntés nem tartalmazhat nyitott nyelvi, "
                "jelentéstani, állítás- vagy javítási hibát."
            )
        return self


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


class StrategyReviewSubmission(BaseModel):
    decision: Decision
    strategist_run_id: str = Field(min_length=3, max_length=120)
    reviewer_run_id: str = Field(min_length=3, max_length=120)
    reviewer_identity: str = Field(min_length=3, max_length=160)
    objective_score: int = Field(ge=0, le=10)
    audience_score: int = Field(ge=0, le=10)
    offer_score: int = Field(ge=0, le=10)
    message_architecture_score: int = Field(ge=0, le=10)
    channel_plan_score: int = Field(ge=0, le=10)
    brand_fit_score: int = Field(ge=0, le=10)
    feasibility_score: int = Field(ge=0, le=10)
    tactical_plan: str = Field(min_length=40, max_length=5000)
    asset_plan: list[str] = Field(min_length=1)
    findings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_strategy_review(self) -> StrategyReviewSubmission:
        if self.strategist_run_id == self.reviewer_run_id:
            raise ValueError("A stratéga és a stratégiai reviewer futása nem lehet azonos.")
        scores = (
            self.objective_score,
            self.audience_score,
            self.offer_score,
            self.message_architecture_score,
            self.channel_plan_score,
            self.brand_fit_score,
            self.feasibility_score,
        )
        if self.decision == Decision.APPROVED and (min(scores) < 9 or self.findings):
            raise ValueError(
                "APPROVED stratégiai döntéshez minden dimenzió minimuma 9/10, "
                "és nem maradhat nyitott finding."
            )
        return self


class VisualProductionSubmission(BaseModel):
    generation_run_id: str = Field(min_length=3, max_length=120)
    producer_identity: str = Field(min_length=3, max_length=160)
    visual_direction_id: str = Field(min_length=3, max_length=160)
    platform: str = Field(min_length=2, max_length=80)
    width_px: int = Field(ge=320, le=10000)
    height_px: int = Field(ge=320, le=10000)
    output_uri: str = Field(min_length=3, max_length=2000)
    output_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    generation_prompt_hash: str = Field(pattern="^[0-9a-f]{64}$")
    contains_text: bool = False


MANDATORY_COPY_GATE_DIMENSIONS = {
    "MARKETING": {
        "objective_fit",
        "audience_fit",
        "offer_strength",
        "message_architecture",
        "conversion_path",
        "qualification_quality",
        "brand_specificity",
    },
    "DIRECT_RESPONSE": {
        "hook_strength",
        "emotional_tension",
        "specificity",
        "natural_hungarian",
        "direct_response_persuasion",
        "clarity",
        "cta_strength",
        "brand_voice",
    },
}


class MandatoryCopyGateReviewSubmission(BaseModel):
    gate_id: str = Field(pattern="^(MARKETING|DIRECT_RESPONSE)$")
    decision: Decision
    reviewed_asset_id: str = Field(min_length=3, max_length=120)
    reviewed_content_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    generation_run_id: str = Field(min_length=3, max_length=120)
    reviewer_run_id: str = Field(min_length=3, max_length=120)
    reviewer_identity: str = Field(min_length=3, max_length=160)
    reviewer_model_version: str = Field(min_length=2, max_length=120)
    prompt_version: str = Field(min_length=2, max_length=120)
    attestation_key_id: str = Field(min_length=3, max_length=120)
    attestation_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    dimension_scores: dict[str, int]
    consumer_readback: str = Field(min_length=30, max_length=3000)
    conversion_rationale: str = Field(min_length=30, max_length=3000)
    strongest_objection: str = Field(min_length=10, max_length=1500)
    dry_copy_detected: bool
    generic_copy_detected: bool
    brand_voice_violation_detected: bool
    findings: list[str] = Field(default_factory=list)
    required_repairs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mandatory_copy_gate(self) -> MandatoryCopyGateReviewSubmission:
        if self.reviewer_run_id == self.generation_run_id:
            raise ValueError("A generáló és a kötelező szakértői reviewer futása nem lehet azonos.")
        expected = MANDATORY_COPY_GATE_DIMENSIONS[self.gate_id]
        if set(self.dimension_scores) != expected:
            missing = sorted(expected - set(self.dimension_scores))
            extra = sorted(set(self.dimension_scores) - expected)
            raise ValueError(
                f"A {self.gate_id} kapu dimenziókészlete nem teljes. "
                f"Hiányzó: {missing}; ismeretlen: {extra}."
            )
        if any(score < 0 or score > 10 for score in self.dimension_scores.values()):
            raise ValueError("Minden kötelező kapupontszámnak 0 és 10 között kell lennie.")
        if self.decision == Decision.APPROVED and (
            min(self.dimension_scores.values()) < 9
            or self.dry_copy_detected
            or self.generic_copy_detected
            or self.brand_voice_violation_detected
            or self.findings
            or self.required_repairs
        ):
            raise ValueError(
                "APPROVED marketing- vagy direct-response döntéshez minden dimenzió "
                "minimuma 9/10; száraz, generikus vagy márkaidegen szöveg és nyitott "
                "finding/javítás nem maradhat."
            )
        return self


class CreativeDirectorReviewSubmission(BaseModel):
    decision: Decision
    reviewed_asset_id: str = Field(min_length=3, max_length=120)
    reviewed_content_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    reviewed_visual_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    generation_run_id: str = Field(min_length=3, max_length=120)
    reviewer_run_id: str = Field(min_length=3, max_length=120)
    reviewer_identity: str = Field(min_length=3, max_length=160)
    reviewer_model_version: str = Field(min_length=2, max_length=120)
    prompt_version: str = Field(min_length=2, max_length=120)
    attestation_key_id: str = Field(min_length=3, max_length=120)
    attestation_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    brand_fidelity_score: int = Field(ge=0, le=10)
    composition_score: int = Field(ge=0, le=10)
    distinctiveness_score: int = Field(ge=0, le=10)
    typography_score: int = Field(ge=0, le=10)
    asset_accuracy_score: int = Field(ge=0, le=10)
    minimum_contrast_ratio: float = Field(ge=1, le=21)
    full_subject_expected: bool
    full_subject_contour_visible: bool
    declared_crop_intent: str | None = Field(default=None, max_length=1000)
    accidental_crop_absent: bool
    text_boxes_within_bounds: bool
    text_background_clear: bool
    text_overlaps_primary_subject: bool
    text_background_overlaps_primary_subject: bool
    minimum_source_font_px: int = Field(ge=1, le=1000)
    decorative_frame_area_ratio: float = Field(ge=0, le=1)
    primary_subject_dominance_required: bool
    primary_subject_area_ratio: float = Field(ge=0, le=1)
    typehouse_offer_creative: bool = False
    offer_block_contiguous: bool | None = None
    offer_current_month_present: bool | None = None
    offer_model_name_present: bool | None = None
    offer_gross_area_m2_present: bool | None = None
    offer_selling_price_present: bool | None = None
    offer_price_plus_vat_present: bool | None = None
    discount_percentage_on_creative: bool | None = None
    original_price_on_creative: bool | None = None
    net_price_word_on_creative: bool | None = None
    build_time_label_plain: bool | None = None
    legal_disclaimer_on_impulse_creative: bool | None = None
    logo_lockup_brand_native: bool
    proof_caption_present: bool
    proof_caption_semantically_complete: bool
    findings: list[str] = Field(default_factory=list)
    repair_brief: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_creative_review(self) -> CreativeDirectorReviewSubmission:
        scores = (
            self.brand_fidelity_score,
            self.composition_score,
            self.distinctiveness_score,
            self.typography_score,
            self.asset_accuracy_score,
        )
        if self.decision == Decision.APPROVED and (
            min(scores) < 9
            or self.minimum_contrast_ratio < 4.5
            or not self.accidental_crop_absent
            or not self.text_boxes_within_bounds
            or not self.text_background_clear
            or self.text_overlaps_primary_subject
            or self.text_background_overlaps_primary_subject
            or self.minimum_source_font_px < 32
            or not self.logo_lockup_brand_native
            or (self.proof_caption_present and not self.proof_caption_semantically_complete)
            or (self.full_subject_expected and not self.full_subject_contour_visible)
            or (
                not self.full_subject_expected
                and len((self.declared_crop_intent or "").strip()) < 20
            )
            or self.decorative_frame_area_ratio > 0.08
            or (self.primary_subject_dominance_required and self.primary_subject_area_ratio < 0.45)
            or (
                self.typehouse_offer_creative
                and (
                    self.primary_subject_area_ratio < 0.75
                    or self.offer_block_contiguous is not True
                    or self.offer_current_month_present is not True
                    or self.offer_model_name_present is not True
                    or self.offer_gross_area_m2_present is not True
                    or self.offer_selling_price_present is not True
                    or self.offer_price_plus_vat_present is not True
                    or self.discount_percentage_on_creative is not False
                    or self.original_price_on_creative is not False
                    or self.net_price_word_on_creative is not False
                    or self.build_time_label_plain is not True
                    or self.legal_disclaimer_on_impulse_creative is not False
                )
            )
            or self.findings
            or self.repair_brief
        ):
            raise ValueError(
                "APPROVED kreatív igazgatói döntéshez minden dimenzió minimuma 9/10, "
                "a kontraszt minimuma 4.5:1, minden szövegnek képhatáron belül kell "
                "maradnia, a háttér nem zavarhatja az olvasást, szöveg és szövegháttér "
                "nem takarhatja a házat, a szerkesztett betűméret legalább 32 px, a "
                "teljes ház kontúrja nem vágható le, a dekoratív keret legfeljebb 8%, "
                "a típusház képi aránya pedig legalább 75%; a logó lockupja márkanatív, a bizalmi "
                "jelzések képaláírása pedig teljes jelentésű legyen; nyitott hiba "
                "nem maradhat."
            )
        return self


class PlatformExport(BaseModel):
    platform: str = Field(min_length=2, max_length=80)
    placement: str = Field(min_length=2, max_length=120)
    width_px: int = Field(ge=320, le=10000)
    height_px: int = Field(ge=320, le=10000)
    output_uri: str = Field(min_length=3, max_length=2000)
    output_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    safe_zone_checked: bool
    text_legibility_checked: bool


class AssemblySubmission(BaseModel):
    assembly_run_id: str = Field(min_length=3, max_length=120)
    assembler_identity: str = Field(min_length=3, max_length=160)
    visual_generation_run_id: str = Field(min_length=3, max_length=120)
    copy_content_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    pairing_rationale: str = Field(min_length=30, max_length=3000)
    exports: list[PlatformExport] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_exports(self) -> AssemblySubmission:
        if not all(
            export.safe_zone_checked and export.text_legibility_checked for export in self.exports
        ):
            raise ValueError(
                "Minden platformexportnál kötelező a safe-zone és olvashatósági check."
            )
        targets = {(item.platform, item.placement) for item in self.exports}
        if len(targets) != len(self.exports):
            raise ValueError("Egy platform/placement export csak egyszer szerepelhet.")
        return self


class ReleaseReviewSubmission(BaseModel):
    decision: Decision
    reviewer_run_id: str = Field(min_length=3, max_length=120)
    reviewer_identity: str = Field(min_length=3, max_length=160)
    strategy_match_score: int = Field(ge=0, le=10)
    copy_visual_consistency_score: int = Field(ge=0, le=10)
    channel_fit_score: int = Field(ge=0, le=10)
    conversion_path_score: int = Field(ge=0, le=10)
    four_gate_recheck_passed: bool
    brand_recheck_passed: bool
    technical_export_check_passed: bool
    findings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_release_review(self) -> ReleaseReviewSubmission:
        checks = (
            self.four_gate_recheck_passed,
            self.brand_recheck_passed,
            self.technical_export_check_passed,
        )
        scores = (
            self.strategy_match_score,
            self.copy_visual_consistency_score,
            self.channel_fit_score,
            self.conversion_path_score,
        )
        if self.decision == Decision.APPROVED and (
            min(scores) < 9 or not all(checks) or self.findings
        ):
            raise ValueError(
                "APPROVED release QA döntéshez minden dimenzió minimuma 9/10, "
                "minden recheck sikeres, és nem maradhat nyitott finding."
            )
        return self


class LiveReviewSubmission(BaseModel):
    reviewer_role: str = Field(
        pattern="^(ONLINE_MARKETING_MANAGER|CREATIVE_DIRECTOR|DIRECT_RESPONSE_COPYWRITER)$"
    )
    reviewer_identity: str = Field(min_length=3, max_length=160)
    decision: str = Field(pattern="^(APPROVED|REJECTED)$")
    live_url: str = Field(min_length=3, max_length=2000)
    screenshot_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    rendered_copy_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    findings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_live_review(self) -> LiveReviewSubmission:
        if self.decision == "APPROVED" and self.findings:
            raise ValueError("APPROVED élő review nem tartalmazhat nyitott findingot.")
        if self.decision == "REJECTED" and not self.findings:
            raise ValueError("REJECTED élő review-hoz legalább egy finding szükséges.")
        return self


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
