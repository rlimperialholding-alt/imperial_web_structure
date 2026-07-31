from types import SimpleNamespace

from copy_gate_fixtures import generation_trace, imperial_asset, imperial_brief, strategy_review
from sqlalchemy import select

from app.models import ContentAssetRecord, CopyBriefRecord, CopySourceRecord
from app.models import User
from app.seed import retire_seeded_content_quality_sources, seed_database
from app.services.content_quality import create_content_asset, create_copy_brief, record_strategy_review


PASSWORD = "Imperial2026!"


def login(client, role: str):
    email = "owner@imperial.local" if role == "owner" else f"{role}@imperial.local"
    response = client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
    assert response.status_code == 303


def logout(client):
    assert client.post("/logout", follow_redirects=False).status_code == 303


def brief_form(copy_brief_id: str) -> dict:
    brief = imperial_brief(copy_brief_id=copy_brief_id).model_dump(mode="json")
    for key in (
        "claim_ids", "proof_ids", "primary_objection_ids", "secondary_objection_ids",
        "forbidden_phrases", "required_keywords",
    ):
        brief[key] = "\n".join(brief[key])
    if brief["monthly_promotion_copy_required"]:
        brief["monthly_promotion_copy_required"] = "on"
    else:
        brief.pop("monthly_promotion_copy_required")
    return brief


def test_marketing_workspace_creates_brief_with_four_eye_strategy_and_asset(client, db):
    login(client, "marketing")
    page = client.get("/marketing")
    assert page.status_code == 200
    assert "Forrás → brief → stratégia → tartalom → publikáció" in page.text

    created = client.post("/marketing/briefs", data=brief_form("CB-UI-001"), follow_redirects=False)
    assert created.status_code == 303
    row = db.get(CopyBriefRecord, "CB-UI-001")
    db.refresh(row)
    assert row.status == "STRATEGY_QA"

    review = {
        "decision": "APPROVED",
        "strategist_run_id": "STRATEGY-UI-001",
        "objective_score": "9",
        "audience_score": "9",
        "offer_score": "9",
        "message_architecture_score": "9",
        "channel_plan_score": "9",
        "brand_fit_score": "9",
        "feasibility_score": "9",
        "tactical_plan": "A teljes csatornaterv, célcsoport, ajánlat és mérési rend ellenőrizve lett.",
        "asset_plan": "Landing oldal\nMeta hirdetés",
        "findings": "",
    }
    assert client.post("/marketing/briefs/CB-UI-001/strategy-review", data=review).status_code == 409

    logout(client)
    login(client, "owner")
    approved = client.post("/marketing/briefs/CB-UI-001/strategy-review", data=review, follow_redirects=False)
    assert approved.status_code == 303
    db.refresh(row)
    assert row.status == "STRATEGY_APPROVED"

    logout(client)
    login(client, "marketing")
    source_asset = imperial_asset(asset_id="ASSET-UI-001")
    trace = generation_trace()
    asset_form = {
        "copy_brief_id": "CB-UI-001",
        "asset_id": source_asset.asset_id,
        "project_id": "PRJ-UI-001",
        "copy_mode": trace["copy_mode"],
        "title": source_asset.title,
        "body": source_asset.body,
        "cta": source_asset.cta,
        "slogan": source_asset.slogan,
        "copy_concept_id": trace["copy_concept_id"],
        "copy_architecture_id": trace["copy_architecture_id"],
        "copy_structure_signature": trace["copy_structure_signature"],
        "source_text_usage_ratio": str(trace["source_text_usage_ratio"]),
        "creative_rationale": trace["creative_rationale"],
        "claim_ids_used": "\n".join(source_asset.claim_ids_used),
        "proof_ids_used": "\n".join(source_asset.proof_ids_used),
        "objection_ids_handled": "\n".join(source_asset.objection_ids_handled),
        "required_keywords_used": "\n".join(source_asset.required_keywords_used),
        "factual_claims": "\n".join(source_asset.factual_claims),
        "price_mentions": "\n".join(source_asset.price_mentions),
        "deadline_mentions": "\n".join(source_asset.deadline_mentions),
        "condition_mentions": "\n".join(source_asset.condition_mentions),
        "action_risk_level": str(source_asset.action_risk_level),
        "meaning_preservation_checked": "on",
    }
    response = client.post("/marketing/assets", data=asset_form, follow_redirects=False)
    assert response.status_code == 303, response.text
    asset_row = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == "ASSET-UI-001"))
    assert asset_row is not None
    assert asset_row.state == "DRAFT"


def test_marketing_source_review_is_role_separated(client, db):
    login(client, "marketing")
    response = client.post(
        "/marketing/sources",
        data={
            "source_key": "new-proof-source",
            "source_type": "proof",
            "brand_id": "imperial",
            "version": "1",
            "record_id": "PRF-NEW-001",
            "priority": "50",
            "payload_json": "{}",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    source = db.scalar(select(CopySourceRecord).where(CopySourceRecord.source_key == "new-proof-source"))
    assert source.status == "draft"
    assert source.approved is False
    assert client.post(f"/marketing/sources/{source.id}/review", data={"decision": "approved", "note": "rendben"}).status_code == 403

    logout(client)
    login(client, "managing-director")
    assert client.post(
        f"/marketing/sources/{source.id}/review",
        data={"decision": "approved", "note": "Forrás és jog ellenőrizve"},
        follow_redirects=False,
    ).status_code == 303
    db.refresh(source)
    assert source.status == "approved"
    assert source.approved is True


def test_production_retirement_fails_closed_for_synthetic_sources(db):
    source = db.scalar(select(CopySourceRecord).where(CopySourceRecord.source_key == "OFF-IMP-V1"))
    assert source.approved is True
    retire_seeded_content_quality_sources(db)
    db.commit()
    db.refresh(source)
    assert source.status == "retired"
    assert source.approved is False


def test_demo_disabled_deactivates_seed_accounts(monkeypatch, db):
    import app.seed as seed_module

    monkeypatch.setattr(
        seed_module,
        "settings",
        SimpleNamespace(demo_runtime_enabled=False, environment="staging"),
    )
    seed_database(db)
    owner = db.scalar(select(User).where(User.email == "owner@imperial.local"))
    assert owner.active is False


def test_authenticated_human_copy_and_mandatory_gates_are_role_separated(client, db):
    brief = imperial_brief(copy_brief_id="CB-HUMAN-QA")
    brief_row = create_copy_brief(db, brief.model_dump(mode="json"), actor="strategist@author.example")
    review = strategy_review(reviewer_identity="owner@imperial.local")
    record_strategy_review(db, brief_row.copy_brief_id, review, actor="owner@imperial.local")
    asset_payload = imperial_asset(asset_id="ASSET-HUMAN-QA")
    asset = create_content_asset(
        db,
        asset_payload,
        copy_brief_id=brief_row.copy_brief_id,
        project_id="PRJ-HUMAN-QA",
        generation_trace=generation_trace(),
        actor="content.author@example.com",
    )

    login(client, "copywriter")
    copy_scores = {
        key: "9"
        for key in (
            "idiomatic_hungarian_score", "grammar_score", "semantic_clarity_score",
            "terminology_score", "hook_strength_score", "offer_clarity_score",
            "specificity_score", "persuasion_score", "brand_voice_score",
            "conversion_path_score",
        )
    }
    copy_qa = client.post(
        f"/marketing/assets/{asset.asset_id}/copy-qa",
        data=copy_scores | {
            "decision": "APPROVED",
            "consumer_interpretation": "A fogyasztó pontosan érti a rögzített műszaki tartalom és ajánlat lényegét.",
            "offer_interpretation": "Az ajánlat fix hatókörét, árát és feltételeit egyértelműen olvassa.",
            "cta_interpretation": "A következő lépés egy minősített érdeklődői kapcsolatfelvétel elindítása.",
            "findings": "",
            "required_repairs": "",
        },
        follow_redirects=False,
    )
    assert copy_qa.status_code == 303, copy_qa.text
    db.refresh(asset)
    assert asset.state == "SPECIALIST_QA"

    logout(client)
    login(client, "marketing")
    marketing_scores = {key: "9" for key in (
        "objective_fit", "audience_fit", "offer_strength", "message_architecture",
        "conversion_path", "qualification_quality", "brand_specificity",
    )}
    marketing_gate = client.post(
        f"/marketing/assets/{asset.asset_id}/mandatory-gates/MARKETING",
        data=marketing_scores | {
            "decision": "APPROVED",
            "consumer_readback": "A célközönség az ajánlatot világos, konkrét és Imperial-specifikus megoldásként értelmezi.",
            "conversion_rationale": "A probléma, az ígéret, a bizonyíték és a következő lépés egy összefüggő konverziós utat alkot.",
            "strongest_objection": "A beruházó elsődleges kifogása a teljes költség és a vállalt határidő bizonyíthatósága.",
        },
        follow_redirects=False,
    )
    assert marketing_gate.status_code == 303, marketing_gate.text

    logout(client)
    login(client, "copywriter")
    direct_scores = {key: "9" for key in (
        "hook_strength", "emotional_tension", "specificity", "natural_hungarian",
        "direct_response_persuasion", "clarity", "cta_strength", "brand_voice",
    )}
    direct_gate = client.post(
        f"/marketing/assets/{asset.asset_id}/mandatory-gates/DIRECT_RESPONSE",
        data=direct_scores | {
            "decision": "APPROVED",
            "consumer_readback": "A szöveg természetes magyar nyelven mutatja be a problémát, az ígéretet és a konkrét ajánlatot.",
            "conversion_rationale": "A hooktól a bizonyítékon át a CTA-ig minden elem a minősített kapcsolatfelvételt támogatja.",
            "strongest_objection": "A legerősebb kifogás az, hogy a vállalt ár és határidő a szerződésben hogyan rögzíthető.",
        },
        follow_redirects=False,
    )
    assert direct_gate.status_code == 303, direct_gate.text
    db.refresh(asset)
    assert asset.expert_marketing_approved is True
    assert asset.copywriter_approved is True
    assert asset.state == "FOUR_GATE_QA"

    for role, gate_id, evidence in (
        ("legal", "GATE_2_LEGAL_POLICY", "A jogi állítások és közzétételi feltételek forrásai ellenőrizve."),
        ("finance", "GATE_3_FINANCIAL_COMMERCIAL", "Az ár, áfa, ajánlatverzió és kereskedelmi feltételek ellenőrizve."),
        ("technical-prep", "GATE_4_TECHNICAL_FACTUAL", "A műszaki tartalom és minden számszerű tény forrásból ellenőrizve."),
    ):
        logout(client)
        login(client, role)
        response = client.post(
            f"/marketing/assets/{asset.asset_id}/specialist-gates/{gate_id}",
            data={"relevant": "on", "decision": "APPROVED", "evidence": evidence},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
    db.refresh(asset)
    assert asset.four_gate_approved is True
    assert asset.state == "HUMAN_EDITORIAL"

    logout(client)
    login(client, "managing-director")
    editorial = client.post(
        f"/marketing/assets/{asset.asset_id}/editorial-approval",
        data={"decision": "APPROVED", "note": "A végleges szöveg, márkahang és állításkészlet szerkesztőileg rendben."},
        follow_redirects=False,
    )
    assert editorial.status_code == 303, editorial.text
    db.refresh(asset)
    assert asset.state == "OWNER_APPROVAL"

    logout(client)
    login(client, "owner")
    owner = client.post(
        f"/marketing/assets/{asset.asset_id}/owner-approval",
        data={"decision": "APPROVED", "note": "Az üzleti ajánlat és publikációs szándék tulajdonosként jóváhagyva."},
        follow_redirects=False,
    )
    assert owner.status_code == 303, owner.text
    db.refresh(asset)
    assert asset.owner_approved is True
    assert asset.state == "VISUAL_PRODUCTION"
