from __future__ import annotations

from datetime import date

from app.copy_gate.models import (
    CanonicalSources,
    ContentAsset,
    ContentBlock,
    CopyBrief,
    EditorialReview,
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
        title="Már a szerződéskor lássa, milyen keretek között készül el az otthona",
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


def editorial_review() -> EditorialReview:
    return EditorialReview(
        decision="APPROVED",
        reviewer_run_id="EDITOR-IMP-001",
        generation_run_id="GEN-IMP-001",
        model_version="editorial-model-test",
        prompt_version="copy-editor-v1",
    )


def generation_trace() -> dict:
    return {
        "generation_run_id": "GEN-IMP-001",
        "model_version": "generator-model-test",
        "prompt_version": "copy-generation-v1",
        "stages": list(GENERATION_STAGES),
    }
