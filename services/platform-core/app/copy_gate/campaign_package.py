from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REQUIRED_REVIEW_ROLES = {
    "marketing_strategist",
    "direct_response_copywriter",
    "hungarian_language_editor",
    "brand_guardian",
    "creative_director",
    "legal",
    "financial",
}

SHARED_SUPPORT_ONLY = {
    "plot_review",
    "engineering_consultation",
    "free_quote",
    "fixed_price",
    "fixed_deadline",
    "fast_construction",
    "transparent_process",
    "helpful_team",
}

FORBIDDEN_CUSTOMER_PHRASES = {
    "házirányt kérek",
    "telket küldök",
    "lehetőséget kérek",
    "projektet indítok",
    "kérem egy kézben",
    "megnézem, hogyan",
    "mindent megszervezünk",
    "akkor kész, amikor költözhető",
    "a ház ne legyen okosabb nálad",
    "terv keret határidő egy asztalon",
    "ne a folyosót fizesd",
}

VAGUE_CTAS = {"tovább", "érdekel", "részletek", "megnézem", "kérem", "indulok"}


def normalized(text: str) -> str:
    value = unicodedata.normalize("NFKD", text).casefold()
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def artifact_set_digest(artifacts: list[CampaignArtifact]) -> str:
    payload = "\n".join(
        f"{artifact.path}\t{artifact.sha256}"
        for artifact in sorted(artifacts, key=lambda item: item.path)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CampaignSourceHashes(StrictModel):
    brand_brief: str = Field(pattern="^[0-9a-f]{64}$")
    visual_guide: str = Field(pattern="^[0-9a-f]{64}$")
    conversion_architecture: str = Field(pattern="^[0-9a-f]{64}$")
    offer_source: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    price_source: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")


class CampaignStrategy(StrictModel):
    concept_id: str = Field(min_length=3, max_length=160)
    target_segment: str = Field(min_length=10, max_length=1000)
    life_situation: str = Field(min_length=10, max_length=1000)
    market_problem: str = Field(min_length=10, max_length=1000)
    fear_or_tension: str = Field(min_length=10, max_length=1000)
    desired_outcome: str = Field(min_length=10, max_length=1000)
    product_or_service: str = Field(min_length=3, max_length=500)
    primary_offer: str = Field(min_length=10, max_length=1000)
    brand_specific_mechanism: str = Field(min_length=10, max_length=1000)
    brand_specific_differentiator: str = Field(min_length=10, max_length=1500)
    proof_stack: list[str] = Field(min_length=2)
    objection_answer: str = Field(min_length=10, max_length=1500)
    why_now: str = Field(min_length=10, max_length=1000)
    conversion_event: str = Field(min_length=3, max_length=300)
    primary_concept_class: str = Field(min_length=3, max_length=120)

    @model_validator(mode="after")
    def reject_generic_primary_concept(self) -> CampaignStrategy:
        if self.primary_concept_class in SHARED_SUPPORT_ONLY and (
            len(self.brand_specific_differentiator) < 60 or len(self.proof_stack) < 3
        ):
            raise ValueError(
                "Közös szolgáltatásállítás csak érdemi márkaspecifikus megkülönböztetéssel "
                "és legalább három bizonyítékkal lehet elsődleges kampánykoncepció."
            )
        return self


class RejectedCopyCandidate(StrictModel):
    text: str = Field(min_length=3, max_length=1500)
    reason: str = Field(min_length=10, max_length=1500)


class CampaignCopy(StrictModel):
    headline: str = Field(min_length=3, max_length=500)
    support: str = Field(min_length=3, max_length=800)
    cta: str = Field(min_length=3, max_length=120)
    primary_text: str = Field(min_length=40, max_length=8000)
    concept_candidates: list[str] = Field(min_length=3)
    rejected_candidates: list[RejectedCopyCandidate] = Field(min_length=2)

    @model_validator(mode="after")
    def enforce_customer_facing_copy(self) -> CampaignCopy:
        if word_count(self.headline) > 10:
            raise ValueError("A képi főcím legfeljebb 10 szóból állhat.")
        if word_count(self.support) > 18:
            raise ValueError("A képi kiegészítő szöveg legfeljebb 18 szóból állhat.")
        if not 2 <= word_count(self.cta) <= 5:
            raise ValueError("A CTA 2–5 szóból állhat.")
        if normalized(self.cta) in {normalized(value) for value in VAGUE_CTAS}:
            raise ValueError("Homályos, önmagában nem értelmezhető CTA nem használható.")
        combined = normalized(" ".join((self.headline, self.support, self.cta, self.primary_text)))
        for phrase in FORBIDDEN_CUSTOMER_PHRASES:
            if normalized(phrase) in combined:
                raise ValueError(f"Korábban elutasított kifejezés szerepel a copyban: {phrase}")
        if re.search(r"\b(kapu|gate|snapshotid|offerversionid|termsversionid)\b", combined):
            raise ValueError("Belső validációs szakzsargon nem kerülhet ügyfélszövegbe.")
        return self


class CampaignVisual(StrictModel):
    canonical_master: str = Field(min_length=3, max_length=2000)
    render_1080: str = Field(min_length=3, max_length=2000)
    layout_archetype: str = Field(min_length=3, max_length=160)
    subject_mask: str = Field(min_length=3, max_length=2000)
    photo_visible_ratio: float = Field(ge=0.75, le=1)
    min_text_px: int = Field(ge=40, le=1000)
    headline_lines: int = Field(ge=1, le=2)
    support_lines: int = Field(ge=1, le=2)
    cta_lines: Literal[1]
    text_subject_intersections: Literal[0]
    text_box_overflows: Literal[0]
    ocr_match: Literal[True]
    downscale_readable: Literal[True]
    official_brand_assets: Literal[True]
    gradient_used: bool = False
    gradient_exception_approved: bool = False
    typehouse_image_verified: bool = False

    @model_validator(mode="after")
    def enforce_editable_master_and_no_gradient(self) -> CampaignVisual:
        lower = self.canonical_master.casefold()
        if not lower.endswith((".svg", ".html")):
            raise ValueError("A kanonikus szerkeszthető master csak SVG vagy HTML lehet.")
        if self.gradient_used and not self.gradient_exception_approved:
            raise ValueError(
                "Színátmenet csak dokumentált kreatívigazgatói kivétellel használható."
            )
        return self


class CampaignProgramContext(StrictModel):
    residential_house_brand: bool
    product_led_share: float = Field(ge=0, le=1)
    cross_brand_registry: str = Field(min_length=3, max_length=2000)
    concept_unique: Literal[True]
    layout_unique: Literal[True]
    allowed_copy_similarity: float = Field(default=0.62, ge=0, le=0.72)

    @model_validator(mode="after")
    def enforce_product_led_residential_program(self) -> CampaignProgramContext:
        if self.residential_house_brand and self.product_led_share < 0.60:
            raise ValueError(
                "Lakóházas márkánál legalább 60% termék-/típusházvezérelt arány kötelező."
            )
        return self


class CampaignArtifact(StrictModel):
    path: str = Field(min_length=1, max_length=2000)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    role: Literal[
        "copy",
        "visual_source",
        "canonical_master",
        "render_1080",
        "subject_mask",
        "platform_export",
    ]


class CampaignReview(StrictModel):
    role: Literal[
        "marketing_strategist",
        "direct_response_copywriter",
        "hungarian_language_editor",
        "brand_guardian",
        "creative_director",
        "legal",
        "financial",
    ]
    reviewer_id: str = Field(min_length=3, max_length=160)
    decision: Literal["PASS"]
    artifact_set_sha256: str = Field(pattern="^[0-9a-f]{64}$")


class CampaignRelease(StrictModel):
    publication_authorized: Literal[False]
    r6_r7: Literal["HUMAN_ONLY"]


class CampaignPackage(StrictModel):
    schema_version: Literal["1.0"]
    brand_id: str = Field(min_length=2, max_length=100)
    campaign_id: str = Field(min_length=3, max_length=160)
    campaign_type: Literal[
        "promotion",
        "typehouse",
        "typehouse_promotion",
        "lead_form",
        "traffic",
        "conversion",
        "general",
        "b2b",
    ]
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    author_id: str = Field(min_length=3, max_length=160)
    source_hashes: CampaignSourceHashes
    strategy: CampaignStrategy
    copy_spec: CampaignCopy = Field(alias="copy", serialization_alias="copy")
    visual: CampaignVisual
    program_context: CampaignProgramContext
    artifacts: list[CampaignArtifact] = Field(min_length=5)
    reviews: list[CampaignReview] = Field(min_length=7)
    release: CampaignRelease

    @model_validator(mode="after")
    def enforce_complete_package(self) -> CampaignPackage:
        if self.campaign_type in {"promotion", "typehouse_promotion"} and (
            not self.source_hashes.offer_source or not self.source_hashes.price_source
        ):
            raise ValueError("Akciós kampányhoz ajánlat- és árforrás-hash kötelező.")
        if self.campaign_type in {"typehouse", "typehouse_promotion"} and (
            not self.visual.typehouse_image_verified
        ):
            raise ValueError("Típusházkampányhoz igazolt típusházkép kötelező.")
        roles = [review.role for review in self.reviews]
        if set(roles) != REQUIRED_REVIEW_ROLES or len(roles) != len(REQUIRED_REVIEW_ROLES):
            raise ValueError(
                "A hét kötelező, különálló review-szerep mindegyike pontosan egyszer kell."
            )
        reviewers = [review.reviewer_id.casefold() for review in self.reviews]
        if self.author_id.casefold() in reviewers:
            raise ValueError("A szerző nem hagyhatja jóvá a saját kampánycsomagját.")
        if len(reviewers) != len(set(reviewers)):
            raise ValueError("A hét review-t hét külön reviewer identitásnak kell elvégeznie.")
        expected_artifact_set = artifact_set_digest(self.artifacts)
        if any(review.artifact_set_sha256 != expected_artifact_set for review in self.reviews):
            raise ValueError(
                "Minden review-nak ugyanahhoz az aktuális artifact-set hashhez kell kötődnie."
            )
        roles_present = {artifact.role for artifact in self.artifacts}
        required_artifacts = {
            "copy",
            "visual_source",
            "canonical_master",
            "render_1080",
            "subject_mask",
        }
        if not required_artifacts.issubset(roles_present):
            raise ValueError(
                "Hiányzik copy-, vizuál-, master-, render- vagy subject-mask artifact."
            )
        return self


class CampaignPackageGateSubmission(StrictModel):
    package: CampaignPackage
    gate_run_id: str = Field(min_length=3, max_length=160)
    reviewer_identity: str = Field(min_length=3, max_length=160)
    attestation_key_id: str = Field(min_length=3, max_length=120)
    attestation_sha256: str = Field(pattern="^[0-9a-f]{64}$")


def cross_brand_failures(
    package: CampaignPackage,
    other_packages: list[CampaignPackage],
) -> list[str]:
    failures: list[str] = []
    current_copy = normalized(
        " ".join(
            (
                package.copy_spec.headline,
                package.copy_spec.support,
                package.copy_spec.primary_text,
            )
        )
    )
    for other in other_packages:
        if other.brand_id == package.brand_id or other.period != package.period:
            continue
        if other.strategy.concept_id == package.strategy.concept_id:
            failures.append(f"A concept_id már foglalt ennél a márkánál: {other.brand_id}.")
        if other.visual.layout_archetype == package.visual.layout_archetype:
            failures.append(f"A layout_archetype már foglalt ennél a márkánál: {other.brand_id}.")
        other_copy = normalized(
            " ".join(
                (
                    other.copy_spec.headline,
                    other.copy_spec.support,
                    other.copy_spec.primary_text,
                )
            )
        )
        similarity = SequenceMatcher(None, current_copy, other_copy).ratio()
        if similarity > package.program_context.allowed_copy_similarity:
            failures.append(
                f"A márkaközi copy-hasonlóság {similarity:.3f}, a megengedett "
                f"{package.program_context.allowed_copy_similarity:.3f} helyett ({other.brand_id})."
            )
    return failures


def package_hash(package: CampaignPackage) -> str:
    payload = json.dumps(
        package.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
