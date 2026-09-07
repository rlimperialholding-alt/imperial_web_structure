"""Original Hungarian claims reach bounded repair without lexical corruption."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_content_brand_form_regressions import run_brand
from test_content_model_output_contract import NOW, _copy_only
from test_content_v7_grammar_scope import trusted_contract

from app.growth_ops import processing

FIXTURE = Path(__file__).parent / "fixtures/content_factory_v10_lexical_scope_20260907.json"
ABSOLUTE = "unsupported_absolute_claim"
CAPABILITY = "unverified_case_or_capability_claim"
TAKEOVER = (
    "Így az Ön feladata nem az, hogy műszaki részleteket egyeztessen, "
    "hanem hogy a kalkuláció alapján megalapozott döntést hozzon."
)
SUPPORTED_HELP = (
    "A mérnöki ellenőrzés segíthet a műszaki kérdések tisztázásában; "
    "érdemes előre egyeztetni a feladatokat és a döntési felelősségeket."
)


def recorded(brand):
    return next(row for row in json.loads(FIXTURE.read_text("utf-8"))
                if row["brand_id"] == brand)


@pytest.mark.parametrize("text", [
    "Ne pusztán a legolcsóbbat válassza.",
    "Az összehangolás jelenti a legnagyobb kihívást.",
    "Ez a leggyakoribb hiba az ajánlatok összehasonlításakor.",
    "Ez minden esetben megfelelő megoldás.",
    "A terv biztosan elkészül.",
    "A terv garantáltan elkészül.",
])
@pytest.mark.parametrize("field", ["title", "body", "facebook_post"])
def test_original_claim_and_suffix_are_preserved_for_the_existing_error(text, field):
    package = {field: text}
    sanitized = processing._sanitize_unbound_claims(package)
    assert sanitized[field] == text
    assert ABSOLUTE in processing._deterministic_publication_errors(sanitized, {})
    finding = next(item for item in processing._content_repair_instructions(
        sanitized, [ABSOLUTE], {},
    ) if item["field"] == field)
    assert finding["spans"] == [{"start": 0, "end": len(text), "text": text}]


def test_real_imperial_provider_sentence_is_no_longer_corrupted_before_repair():
    sample = recorded("Imperial")
    assert "jelenti a legnagyobb kihívást" in sample["package"]["facebook_post"]
    assert "jelenti jelentős kihívást" in sample["recorded_final_package"]["facebook_post"]
    clean = processing._sanitize_unbound_claims(sample["package"])
    assert clean["facebook_post"] == sample["package"]["facebook_post"]
    assert ABSOLUTE in processing._deterministic_publication_errors(clean, {})


@pytest.mark.parametrize("text", [
    TAKEOVER,
    "Az Ön feladata nem az, hogy műszaki részleteket egyeztessen.",
    "Nem az Ön feladata, hogy műszaki részleteket egyeztessen.",
    "A te feladatod nem az, hogy műszaki részleteket egyeztess.",
    "Nem a te feladatod, hogy műszaki részleteket egyeztess.",
])
def test_customer_task_exemption_requires_verified_coordination_scope(db, text):
    assert CAPABILITY in processing._deterministic_publication_errors(
        {"body": text}, trusted_contract(db, "Bautica"),
    )
    assert CAPABILITY not in processing._deterministic_publication_errors(
        {"body": text}, trusted_contract(db, "Property360"),
    )


@pytest.mark.parametrize("text", [
    SUPPORTED_HELP,
    "Az Ön feladata, hogy a műszaki részleteket egyeztesse a tervezővel.",
    "Érdemes tisztázni, kinek a feladata a műszaki egyeztetés.",
    "Ha a tervet együtt áttekintik, a nyitott kérdések könnyebben tisztázhatók.",
    "Nem állítjuk, hogy az Ön feladata nem az, hogy műszaki részleteket egyeztessen.",
    "Ez nem jelenti azt, hogy nem a te feladatod, hogy műszaki részleteket egyeztess.",
])
def test_real_engineering_help_and_warning_against_task_exemption_are_retained(db, text):
    assert CAPABILITY not in processing._deterministic_publication_errors(
        {"body": text}, trusted_contract(db, "Bautica"),
    )


@pytest.mark.parametrize("field", ["title", "body", "facebook_post", "cta"])
def test_scope_feedback_preserves_exact_field_sentence_and_cannot_borrow_other_field_negation(
    db, field,
):
    package = {"title": "Nem állítjuk, hogy"}
    package[field] = {"label": TAKEOVER} if field == "cta" else TAKEOVER
    contract = trusted_contract(db, "Bautica")
    assert CAPABILITY in processing._deterministic_publication_errors(package, contract)
    finding = next(item for item in processing._content_repair_instructions(
        package, [CAPABILITY], contract,
    ) if item["field"] == field)
    assert finding["spans"] == [{"start": 0, "end": len(TAKEOVER), "text": TAKEOVER}]


def test_forged_or_other_brand_scope_is_rejected_and_valid_scope_does_not_authorize_price(db):
    package = {
        "body": TAKEOVER, "_approved_scope_claims": ["Teljes projektkoordinációt vállalunk."],
    }
    wrong_brand = processing._contract_with_approved_claims(
        {}, processing._approved_brand_facts(db, "Property360", current=NOW), brand_id="Bautica",
    )
    assert CAPABILITY in processing._deterministic_publication_errors(package, wrong_brand)
    package["body"] += " Ingyenes egyeztetés és 200 ezer megtakarítás."
    sanitized = processing._sanitize_unbound_claims(package)
    assert sanitized["body"] == package["body"]
    errors = processing._deterministic_publication_errors(
        sanitized, trusted_contract(db, "Property360"),
    )
    assert CAPABILITY not in errors
    assert {"unverified_numeric_claim", "unverified_offer_condition"}.issubset(errors)


@pytest.mark.parametrize(("brand", "field", "error"), [
    ("Imperial", "facebook_post", ABSOLUTE),
    ("Bautica", "body", CAPABILITY),
])
@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_actual_v10_claims_use_shared_repairs_and_only_corrected_artifact_is_signed(
    db, monkeypatch, brand, field, error, repair_succeeds,
):
    sample = recorded(brand)
    original = sample["package"]

    def generate(request, _system):
        package = deepcopy(original)
        if "repair_round" in request:
            assert error in request["gate_errors"]
            assert request["blocked_package"][field] == original[field]
            finding = next(item for item in request["field_corrections"]
                           if item["error"] == error and item["field"] == field)
            assert finding["spans"]
            for span in finding["spans"]:
                assert original[field][span["start"]:span["end"]] == span["text"]
            if repair_succeeds:
                package[field] = package[field].replace(
                    "jelenti a legnagyobb kihívást", "jelenthet nehézséget",
                ).replace(TAKEOVER, SUPPORTED_HELP)
        return {"package": package}

    result, row, calls = run_brand(db, monkeypatch, brand, generate)
    output = json.loads(row.evidence_json)
    assert len(calls) == 3 and all(call["high_stakes"] for call in calls)
    if not repair_succeeds:
        assert result["failed"] == 1 and result["generated"] == 0
        assert output["content_repair_attempts"] == 2
        assert not any("release_review" in call["purpose"] for call in calls)
        assert output["review_pending_draft"][field] == original[field]
        assert "quality_gate_manifest" not in output
        return
    assert result["generated"] == 1, row.evidence_json
    assert "release_review" in calls[-1]["purpose"]
    assert output["content_repair_attempts"] == 1
    assert output["cta"] == original["cta"]
    assert output["revenue_intent"] == calls[0]["request"]["revenue_intent"]
    assert output["revenue_intent"]["send_allowed"] is False
    assert output["revenue_intent"]["publication_allowed"] is False
    assert processing._verified_quality_manifest(output, now=NOW)
    assert output["quality_gate_manifest"]["artifact_sha256"] == processing._sha(
        calls[-1]["request"]["artifact"],
    )
    assert output["quality_gate_manifest"]["review_request_id"] == "OFFLINE-3"
    tampered = deepcopy(output)
    tampered[field] = original[field]
    with pytest.raises(ValueError):
        processing._verified_quality_manifest(tampered, now=NOW)


def test_p360_actual_coordination_and_conditional_benefit_pass_delivery_readback(db, monkeypatch):
    def generate(request, _system):
        package = _copy_only(request["revenue_intent"])
        package["body"] += (
            " A te feladatod nem az, hogy műszaki részleteket egyeztess. "
            "Az összehangolt előkészítés segíthet a nyitott kérdések tisztázásában."
        )
        return {"package": package}

    result, row, calls = run_brand(db, monkeypatch, "Property360", generate)
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 2
    image_calls = []

    def pending_image(package, **kwargs):
        image_calls.append(package)
        assert processing._verified_quality_manifest(package, now=NOW)
        return "pending", {}

    monkeypatch.setattr(processing, "sync_canonical_image", pending_image)
    result = processing.enqueue_daily_publications(db, now=NOW)
    assert result["blocked"] == result["queued"] == 0
    assert len(image_calls) == 1
    assert json.loads(row.evidence_json)["publication_state"] == "WAITING_FOR_IMAGE"
