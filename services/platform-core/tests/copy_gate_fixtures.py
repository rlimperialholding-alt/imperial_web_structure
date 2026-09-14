from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import date
from typing import Any

from app.copy_gate.campaign_package import (
    CampaignArtifact,
    CampaignCopy,
    CampaignPackage,
    CampaignProgramContext,
    CampaignRelease,
    CampaignReview,
    CampaignSourceHashes,
    CampaignStrategy,
    CampaignVisual,
    RejectedCopyCandidate,
    artifact_set_digest,
)
from app.copy_gate.models import (
    AssemblySubmission,
    CanonicalSources,
    ContentAsset,
    ContentBlock,
    CopyBrief,
    CreativeDirectorReviewSubmission,
    EditorialReview,
    LiveReviewSubmission,
    MandatoryCopyGateReviewSubmission,
    PlatformExport,
    ReleaseReviewSubmission,
    StrategyReviewSubmission,
    VisualProductionSubmission,
)
from app.services.content_quality import GENERATION_STAGES


def imperial_brief(
    *,
    copy_brief_id: str = "CB-IMP-PILOT-001",
    asset_type: str = "landing",
    channel: str = "web",
) -> CopyBrief:
    return CopyBrief(
        copy_brief_id=copy_brief_id,
        brand_id="imperial",
        asset_type=asset_type,
        channel=channel,
        campaign_id="CMP-IMP-PILOT",
        campaign_objective="qualified_lead",
        primary_conversion="engineering_consultation",
        target_persona_id="family-solution-aware",
        awareness_level="solution-aware",
        market_sophistication_level="high",
        core_problem="Az építkezés ára és határideje menet közben bizonytalanná válhat.",
        desired_outcome="Előre átlátható döntés és nyugodtan követhető kivitelezés.",
        primary_promise="A szerződéskor rögzített keretekből átlátható építési folyamat.",
        unique_mechanism="fix ár + fix határidő + rögzített műszaki tartalom",
        offer_version_id="OFF-IMP-V1",
        price_snapshot_id="PS-IMP-2026-07",
        terms_version_id="TV-IMP-V1",
        claim_ids=["CLM-IMP-FIXED-SCOPE"],
        proof_ids=["PRF-IMP-CONTRACT"],
        house_plan_id="HP-IMP-126",
        primary_objection_ids=["OBJ-COST-OVERRUN"],
        secondary_objection_ids=["OBJ-DEADLINE"],
        risk_reversal="díjmentes mérnöki konzultáció",
        primary_cta_type="ENGINEERING_CONSULTATION",
        brand_voice_profile="imperial-v1",
        required_slogan="Csodálatos otthonok megfizethető áron.",
        required_slogan_version="IMP-SLOGAN-1",
        forbidden_phrases=["garantáltan a legolcsóbb"],
        required_keywords=["rögzített műszaki tartalom"],
        landing_message_match_id="MM-IMP-PILOT",
        valid_from=date(2026, 1, 1),
        valid_until=date(2027, 12, 31),
    )


def imperial_asset(
    *,
    asset_id: str = "ASSET-IMP-PILOT-001",
    asset_type: str = "landing",
) -> ContentAsset:
    return ContentAsset(
        asset_id=asset_id,
        title="Már a szerződéskor lássa otthona biztos kereteit",
        body=(
            "A fix ár, fix határidő és rögzített műszaki tartalom együtt teszi "
            "követhetővé a 126 m²-es ház döntéseit. A szerződés tételes scope-ja "
            "bizonyítja, mi tartozik az ajánlatba és milyen feltételekkel indulhat "
            "a kivitelezés. Ha a költségek elszabadulásától tart, a díjmentes "
            "mérnöki konzultáció még a döntés előtt tisztázza a kérdéseit."
        ),
        cta="Kérjen tételes mérnöki konzultációt",
        cta_type_used="ENGINEERING_CONSULTATION",
        slogan="Csodálatos otthonok megfizethető áron.",
        slogan_version_used="IMP-SLOGAN-1",
        content_blocks=[
            ContentBlock(
                block_id="hero",
                text="A szerződéskor látható keretek.",
                layout_signature=f"{asset_type}:hero-split",
            ),
            ContentBlock(
                block_id="proof",
                text="A tételes scope bizonyítja a vállalt tartalmat.",
                layout_signature=f"{asset_type}:proof-ledger",
            ),
        ],
        detected_brand_ids=["imperial"],
        claim_ids_used=["CLM-IMP-FIXED-SCOPE"],
        proof_ids_used=["PRF-IMP-CONTRACT"],
        objection_ids_handled=["OBJ-COST-OVERRUN"],
        required_keywords_used=["rögzített műszaki tartalom"],
        offer_version_id_used="OFF-IMP-V1",
        price_snapshot_id_used="PS-IMP-2026-07",
        terms_version_id_used="TV-IMP-V1",
        landing_message_match_id_used="MM-IMP-PILOT",
        factual_claims=["A mintaterv bruttó alapterülete 126 m²."],
        price_mentions=["A pontos ár az aktív PriceSnapshot szerint jelenik meg."],
        deadline_mentions=["A határidő az aktív TermsVersion része."],
        condition_mentions=["A tételes műszaki scope és az érvényesség feltételei."],
        visual_asset_ids=["VIS-IMP-126-HERO"],
        visual_quality_score=100,
    )


def canonical_sources() -> CanonicalSources:
    return CanonicalSources(
        source_resolution_pass=True,
        source_versions={"brand_master": "imperial@1.0"},
        active_offer=True,
        active_price=True,
        active_terms=True,
        active_product=True,
        claims_resolved=["CLM-IMP-FIXED-SCOPE"],
        proofs_resolved=["PRF-IMP-CONTRACT"],
        visuals_resolved=["VIS-IMP-126-HERO"],
        brand_addressing="formal",
        required_brand_concepts=[
            "fix ár",
            "fix határidő",
            "rögzített műszaki tartalom",
        ],
        forbidden_brand_phrases=["brutális akció"],
    )


def _reviewed_asset(asset: Any | None) -> ContentAsset:
    if asset is None:
        return imperial_asset()
    if isinstance(asset, ContentAsset):
        return asset
    content_json = getattr(asset, "content_json", None)
    if content_json:
        return ContentAsset.model_validate_json(content_json)
    return ContentAsset.model_validate(asset)


def editorial_review(asset: Any | None = None, **overrides: Any) -> EditorialReview:
    reviewed = _reviewed_asset(asset)
    serialized = json.dumps(
        reviewed.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    payload: dict[str, Any] = {
        "decision": "APPROVED",
        "reviewed_asset_id": reviewed.asset_id,
        "reviewed_content_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "reviewer_run_id": "EDITOR-IMP-001",
        "generation_run_id": "GEN-IMP-001",
        "reviewer_identity": "fixture-independent-hungarian-copy-expert",
        "reviewer_type": "independent_ai",
        "attestation_key_id": "test-expert-review-key-v1",
        "model_version": "editorial-model-test",
        "prompt_version": "expert-hungarian-direct-response-v2",
        "idiomatic_hungarian_score": 10,
        "grammar_score": 10,
        "semantic_clarity_score": 10,
        "terminology_score": 10,
        "hook_strength_score": 10,
        "offer_clarity_score": 10,
        "specificity_score": 10,
        "persuasion_score": 10,
        "brand_voice_score": 10,
        "conversion_path_score": 10,
        "consumer_interpretation": (
            "Az érdeklődő előre rögzített keretek között tervezhető otthonépítést kap."
        ),
        "offer_interpretation": (
            "A szolgáltatás a rögzített ár, határidő és műszaki tartalom áttekintését kínálja."
        ),
        "cta_interpretation": (
            "A CTA tételes mérnöki konzultáció kérésére viszi tovább az érdeklődőt."
        ),
    }
    payload.update(overrides)
    payload["attestation_sha256"] = "0" * 64
    review = EditorialReview(**payload)
    signed_payload = json.dumps(
        review.model_dump(mode="json", exclude={"attestation_sha256"}),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    review.attestation_sha256 = hmac.new(
        os.environ["CONTENT_EXPERT_REVIEW_SECRET"].encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return review


def generation_trace() -> dict:
    return {
        "brand_id": "imperial",
        "generation_run_id": "GEN-IMP-001",
        "model_version": "generator-model-test",
        "prompt_version": "copy-generation-v1",
        "stages": list(GENERATION_STAGES),
        "copy_mode": "verbatim_source",
        "copy_fingerprint": "sha256:test-imperial-copy-v1",
        "copy_concept_id": "imperial-source-proof-v1",
        "copy_architecture_id": "imperial-proof-led-declaration-v1",
        "copy_structure_signature": "offer>hard-claim>proof-stack>model>cta",
        "source_text_usage_ratio": 1.0,
        "creative_quality_benchmark_id": "prefab-facebook-etalon-v1",
        "creative_rationale": "Forráspontos, bizonyítékvezérelt Imperial tesztkreatív.",
        "introduces_new_factual_claims": False,
        "human_fact_review_required": False,
        "consumer_promise_plain_language": "Az ügyfél előre rögzített áron kap házat.",
        "promise_reason_or_mechanism": (
            "A szerződésben rögzített ár és határidő adja a tervezhetőséget."
        ),
        "offer_terms_plain_language": "A kanonikus forrásban jóváhagyott feltételek érvényesek.",
        "cta_next_step_plain_language": (
            "Az ügyfél megnyitja az alaprajz és az ár részletes oldalát."
        ),
        "source_prevalidation_requested": True,
    }


def strategy_review(
    *,
    reviewer_identity: str = "strategy-reviewer@imperial.local",
) -> StrategyReviewSubmission:
    return StrategyReviewSubmission(
        decision="APPROVED",
        strategist_run_id="STRATEGIST-RUN-001",
        reviewer_run_id="STRATEGY-REVIEW-001",
        reviewer_identity=reviewer_identity,
        objective_score=10,
        audience_score=10,
        offer_score=10,
        message_architecture_score=10,
        channel_plan_score=10,
        brand_fit_score=10,
        feasibility_score=10,
        tactical_plan=(
            "A kampány a tervezhetőségi kifogást kezeli, mérnöki konzultációra konvertál, "
            "és platformonként külön szöveg- és kreatív assetet használ."
        ),
        asset_plan=["facebook-feed-1080x1080", "facebook-story-1080x1920"],
    )


def visual_submission(
    *,
    generation_run_id: str = "VISUAL-RUN-001",
    visual_direction_id: str = "VISUAL-DIRECTION-001",
) -> VisualProductionSubmission:
    return VisualProductionSubmission(
        generation_run_id=generation_run_id,
        producer_identity="creative-producer@imperial.local",
        visual_direction_id=visual_direction_id,
        platform="facebook",
        width_px=1080,
        height_px=1080,
        output_uri=f"/artifacts/{generation_run_id}.png",
        output_sha256=hashlib.sha256(generation_run_id.encode("utf-8")).hexdigest(),
        generation_prompt_hash=hashlib.sha256(f"prompt:{generation_run_id}".encode()).hexdigest(),
        contains_text=False,
    )


def mandatory_copy_gate_review(
    reviewed,
    gate_id: str,
    *,
    reviewer_identity: str | None = None,
    reviewer_run_id: str | None = None,
    reviewer_model_version: str | None = None,
    **overrides: Any,
) -> MandatoryCopyGateReviewSubmission:
    if gate_id == "MARKETING":
        dimensions = {
            "objective_fit": 10,
            "audience_fit": 10,
            "offer_strength": 10,
            "message_architecture": 10,
            "conversion_path": 10,
            "qualification_quality": 10,
            "brand_specificity": 10,
        }
        secret_name = "CONTENT_MARKETING_REVIEW_SECRET"
        key_id = "test-marketing-review-key-v1"
        prompt_version = "marketing-gate-v1"
        reviewer_identity = reviewer_identity or "independent-marketing-gate@imperial.local"
        reviewer_run_id = reviewer_run_id or "MARKETING-GATE-RUN-001"
        reviewer_model_version = reviewer_model_version or "marketing-review-model-test"
    else:
        dimensions = {
            "hook_strength": 10,
            "emotional_tension": 10,
            "specificity": 10,
            "natural_hungarian": 10,
            "direct_response_persuasion": 10,
            "clarity": 10,
            "cta_strength": 10,
            "brand_voice": 10,
        }
        secret_name = "CONTENT_COPYWRITER_REVIEW_SECRET"
        key_id = "test-copywriter-review-key-v1"
        prompt_version = "direct-response-copy-gate-v1"
        reviewer_identity = reviewer_identity or "independent-copywriter-gate@imperial.local"
        reviewer_run_id = reviewer_run_id or "COPYWRITER-GATE-RUN-001"
        reviewer_model_version = reviewer_model_version or "copywriter-review-model-test"
    payload: dict[str, Any] = {
        "gate_id": gate_id,
        "decision": "APPROVED",
        "reviewed_asset_id": reviewed.asset_id,
        "reviewed_content_sha256": reviewed.content_hash,
        "generation_run_id": "GEN-IMP-001",
        "reviewer_run_id": reviewer_run_id,
        "reviewer_identity": reviewer_identity,
        "reviewer_model_version": reviewer_model_version,
        "prompt_version": prompt_version,
        "attestation_key_id": key_id,
        "attestation_sha256": "0" * 64,
        "dimension_scores": dimensions,
        "consumer_readback": (
            "Az érdeklődő pontosan érti az ajánlatot, annak következő lépését és a "
            "márkaspecifikus értékígéretet."
        ),
        "conversion_rationale": (
            "A konkrét előny, a hiteles bizonyíték és az alacsony súrlódású CTA együtt "
            "minősített érdeklődést terel."
        ),
        "strongest_objection": "Az érdeklődő bizonytalan a költség és határidő tervezhetőségében.",
        "dry_copy_detected": False,
        "generic_copy_detected": False,
        "brand_voice_violation_detected": False,
    }
    payload.update(overrides)
    review = MandatoryCopyGateReviewSubmission(**payload)
    signed_payload = json.dumps(
        review.model_dump(mode="json", exclude={"attestation_sha256"}),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    review.attestation_sha256 = hmac.new(
        os.environ[secret_name].encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return review


def creative_director_review(
    reviewed,
    visual,
    *,
    reviewer_identity: str = "creative-director@imperial.local",
    reviewer_run_id: str = "CREATIVE-DIRECTOR-RUN-001",
) -> CreativeDirectorReviewSubmission:
    review = CreativeDirectorReviewSubmission(
        decision="APPROVED",
        reviewed_asset_id=reviewed.asset_id,
        reviewed_content_sha256=reviewed.content_hash,
        reviewed_visual_sha256=visual.output_sha256,
        generation_run_id=visual.generation_run_id,
        reviewer_run_id=reviewer_run_id,
        reviewer_identity=reviewer_identity,
        reviewer_model_version="creative-director-model-test",
        prompt_version="visual-art-direction-gate-v1",
        attestation_key_id="test-visual-review-key-v1",
        attestation_sha256="0" * 64,
        brand_fidelity_score=10,
        composition_score=10,
        distinctiveness_score=10,
        typography_score=10,
        asset_accuracy_score=10,
        minimum_contrast_ratio=7.2,
        full_subject_expected=True,
        full_subject_contour_visible=True,
        accidental_crop_absent=True,
        text_boxes_within_bounds=True,
        text_background_clear=True,
        text_overlaps_primary_subject=False,
        text_background_overlaps_primary_subject=False,
        minimum_source_font_px=40,
        decorative_frame_area_ratio=0.0,
        primary_subject_dominance_required=True,
        primary_subject_area_ratio=0.8,
        typehouse_offer_creative=True,
        offer_block_contiguous=True,
        offer_current_month_present=True,
        offer_model_name_present=True,
        offer_gross_area_m2_present=True,
        offer_selling_price_present=True,
        offer_price_plus_vat_present=True,
        discount_percentage_on_creative=False,
        original_price_on_creative=False,
        net_price_word_on_creative=False,
        build_time_label_plain=True,
        legal_disclaimer_on_impulse_creative=False,
        logo_lockup_brand_native=True,
        proof_caption_present=False,
        proof_caption_semantically_complete=True,
    )
    signed_payload = json.dumps(
        review.model_dump(mode="json", exclude={"attestation_sha256"}),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    review.attestation_sha256 = hmac.new(
        os.environ["CONTENT_VISUAL_REVIEW_SECRET"].encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return review


def assembly_submission(
    content_hash: str,
    visual_generation_run_id: str,
) -> AssemblySubmission:
    return AssemblySubmission(
        assembly_run_id=f"ASSEMBLY-{visual_generation_run_id}",
        assembler_identity="production-designer@imperial.local",
        visual_generation_run_id=visual_generation_run_id,
        copy_content_sha256=content_hash,
        pairing_rationale=(
            "A jóváhagyott copy és a márkaspecifikus vizuális irány ugyanazt a "
            "tervezhetőségi értékígéretet támogatja."
        ),
        exports=[
            PlatformExport(
                platform="facebook",
                placement="feed",
                width_px=1080,
                height_px=1080,
                output_uri=f"/exports/{visual_generation_run_id}-feed.png",
                output_sha256=hashlib.sha256(
                    f"export:{visual_generation_run_id}".encode()
                ).hexdigest(),
                safe_zone_checked=True,
                text_legibility_checked=True,
            )
        ],
    )


def campaign_package(
    reviewed,
    visual,
    assembly: AssemblySubmission,
    *,
    brand_id: str = "imperial",
    campaign_id: str = "CMP-IMP-PILOT",
    concept_id: str = "imperial-contract-certainty-v1",
    layout_archetype: str = "imperial-proof-led-typehouse-stage-v1",
    brand_guardian: str = "editor@imperial.local",
    reviewer_overrides: dict[str, str] | None = None,
    photo_visible_ratio: float = 0.8,
    min_text_px: int = 40,
) -> CampaignPackage:
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def sentence(*parts: str) -> str:
        return "".join(parts)

    content = (
        ContentAsset.model_validate_json(reviewed.content_json)
        if hasattr(reviewed, "content_json")
        else reviewed
    )
    export = assembly.exports[0]
    artifacts = [
        CampaignArtifact(path="content.json", sha256=reviewed.content_hash, role="copy"),
        CampaignArtifact(
            path=visual.output_uri,
            sha256=visual.output_sha256,
            role="visual_source",
        ),
        CampaignArtifact(
            path=f"/masters/{campaign_id}.svg",
            sha256=digest(f"master:{campaign_id}"),
            role="canonical_master",
        ),
        CampaignArtifact(
            path=export.output_uri,
            sha256=export.output_sha256,
            role="render_1080",
        ),
        CampaignArtifact(
            path=f"/masks/{campaign_id}.png",
            sha256=digest(f"mask:{campaign_id}"),
            role="subject_mask",
        ),
        CampaignArtifact(
            path=export.output_uri,
            sha256=export.output_sha256,
            role="platform_export",
        ),
    ]
    artifact_hash = artifact_set_digest(artifacts)
    reviewers = {
        "marketing_strategist": "strategy-reviewer@imperial.local",
        "direct_response_copywriter": "independent-copywriter-gate@imperial.local",
        "hungarian_language_editor": "fixture-independent-hungarian-copy-expert",
        "brand_guardian": brand_guardian,
        "creative_director": "creative-director@imperial.local",
        "legal": "AGT-016",
        "financial": "AGT-011",
    }
    reviewers.update(reviewer_overrides or {})
    return CampaignPackage(
        schema_version="1.0",
        brand_id=brand_id,
        campaign_id=campaign_id,
        campaign_type="typehouse",
        period="2026-08",
        author_id="campaign-author@imperial.local",
        source_hashes=CampaignSourceHashes(
            brand_brief=digest("imperial-brand-brief-v1"),
            visual_guide=digest("imperial-visual-guide-v1"),
            conversion_architecture=digest("imperial-conversion-architecture-v1"),
        ),
        strategy=CampaignStrategy(
            concept_id=concept_id,
            target_segment="Fizetőképes családok, akik belátható időn belül építkezni akarnak.",
            life_situation=sentence(
                "A család kivitelezőt választ, és a költség- valamint ",
                "határidőkockázatot mérlegeli.",
            ),
            market_problem=sentence(
                "A változó költség és a bizonytalan átadás megingatja ",
                "az építési döntést.",
            ),
            fear_or_tension=sentence(
                "A család attól tart, hogy menet közben elszáll az ár ",
                "vagy csúszik az átadás.",
            ),
            desired_outcome=sentence(
                "Előre kiszámítható otthonépítés konkrét műszaki és ",
                "szerződéses bizonyítékokkal.",
            ),
            product_or_service="Imperial típusház rögzített műszaki tartalommal",
            primary_offer=sentence(
                "Típusház választása szerződésben rögzített ár-, ",
                "határidő- és műszaki kerettel.",
            ),
            brand_specific_mechanism=sentence(
                "A három fix vállalást tételes műszaki scope és bizonyítható ",
                "cégcsoportos tapasztalat támasztja alá.",
            ),
            brand_specific_differentiator=sentence(
                "Az Imperial nem hangulatígéretet ad: a fix ár, fix határidő ",
                "és fix minőség szerződéses keretét sok száz elkészült ház, ",
                "a 2024-es és 2025-ös MagyarBrands díj, valamint az AAA ",
                "panaszmentességi igazolás erősíti.",
            ),
            proof_stack=[
                "Kétszeres MagyarBrands díjazott márka",
                "AAA kategóriás panaszmentességi igazolás",
                "1989 óta működő cégcsoport és sok száz megépített családi ház",
            ],
            objection_answer=sentence(
                "A döntés előtt tételesen látható, mi kerül a szerződésbe ",
                "és milyen feltételek mellett tartható.",
            ),
            why_now=sentence(
                "A kiválasztott típusház és a finanszírozási keret most ",
                "összevethető a vállalt feltételekkel.",
            ),
            conversion_event="Típusház részleteinek és alaprajzának megnyitása",
            primary_concept_class="contractual_certainty_proof_stack",
        ),
        copy=CampaignCopy(
            headline=content.title,
            support="Fix ár, fix határidő és rögzített műszaki tartalom.",
            cta=content.cta,
            primary_text=content.body,
            concept_candidates=[
                "Szerződéses biztonság három konkrét vállalással",
                "Díjakkal és referenciákkal bizonyított építési kiszámíthatóság",
                "Típusház mint előre átlátható, megvásárolható termék",
            ],
            rejected_candidates=[
                RejectedCopyCandidate(
                    text="Kérjen ingyenes konzultációt",
                    reason=sentence(
                        "Önálló főüzenetként generikus, és nem mutatja meg ",
                        "az Imperial piaci erejét.",
                    ),
                ),
                RejectedCopyCandidate(
                    text="Megnézzük, mi építhető a telkére",
                    reason=sentence(
                        "Közös szolgáltatásállítás, ezért nem különíti el ",
                        "a márkát a többi cégtől.",
                    ),
                ),
            ],
        ),
        visual=CampaignVisual(
            canonical_master=f"/masters/{campaign_id}.svg",
            render_1080=export.output_uri,
            layout_archetype=layout_archetype,
            subject_mask=f"/masks/{campaign_id}.png",
            photo_visible_ratio=photo_visible_ratio,
            min_text_px=min_text_px,
            headline_lines=2,
            support_lines=1,
            cta_lines=1,
            text_subject_intersections=0,
            text_box_overflows=0,
            ocr_match=True,
            downscale_readable=True,
            official_brand_assets=True,
            gradient_used=False,
            typehouse_image_verified=True,
        ),
        program_context=CampaignProgramContext(
            residential_house_brand=True,
            product_led_share=0.8,
            cross_brand_registry="campaign-registry/2026-08.json",
            concept_unique=True,
            layout_unique=True,
            allowed_copy_similarity=0.62,
        ),
        artifacts=artifacts,
        reviews=[
            CampaignReview(
                role=role,
                reviewer_id=reviewer_id,
                decision="PASS",
                artifact_set_sha256=artifact_hash,
            )
            for role, reviewer_id in reviewers.items()
        ],
        release=CampaignRelease(publication_authorized=False, r6_r7="HUMAN_ONLY"),
    )


def release_review(
    *,
    reviewer_identity: str = "marketing-manager@imperial.local",
) -> ReleaseReviewSubmission:
    return ReleaseReviewSubmission(
        decision="APPROVED",
        reviewer_run_id="RELEASE-REVIEW-RUN-001",
        reviewer_identity=reviewer_identity,
        strategy_match_score=10,
        copy_visual_consistency_score=10,
        channel_fit_score=10,
        conversion_path_score=10,
        four_gate_recheck_passed=True,
        brand_recheck_passed=True,
        technical_export_check_passed=True,
    )


def live_review(
    role: str,
    reviewer_identity: str,
    content_hash: str,
    *,
    decision: str = "APPROVED",
    findings: list[str] | None = None,
) -> LiveReviewSubmission:
    return LiveReviewSubmission(
        reviewer_role=role,
        reviewer_identity=reviewer_identity,
        decision=decision,
        live_url="https://preview.imperial.local/campaign/asset",
        screenshot_sha256=hashlib.sha256(
            f"screenshot:{role}:{reviewer_identity}".encode()
        ).hexdigest(),
        rendered_copy_sha256=content_hash,
        findings=findings or [],
    )
