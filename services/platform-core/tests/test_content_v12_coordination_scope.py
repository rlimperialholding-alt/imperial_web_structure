"""Full coordination exemption keeps its meaning across pronouns and synonyms."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_content_brand_form_regressions import run_brand
from test_content_model_output_contract import NOW, _copy_only
from test_content_v7_grammar_scope import trusted_contract

from app.growth_ops import processing

FIXTURE = Path(__file__).parent / "fixtures/content_factory_v11_coordination_20260907.json"
ERROR = "unverified_case_or_capability_claim"
BODY_BAD = (
    "Így Ön nem marad egyedül a műszaki kérdésekkel, és nem kell különböző "
    "szakemberek között közvetítenie."
)
FACEBOOK_BAD = (
    "Így Ön nem marad egyedül a műszaki döntésekkel, és nem kell különböző "
    "szakemberek között egyeztetnie."
)
HELP = (
    "A mérnöki ellenőrzés segíthet a műszaki eltérések felismerésében; "
    "az egyeztetés és a döntések felelősségét érdemes előre tisztázni."
)


@pytest.mark.parametrize("action", [
    "koordinálnia", "összehangolnia", "egyeztetnie", "egyeztessen",
    "közvetítenie", "szerveznie", "megszerveznie",
])
@pytest.mark.parametrize("form", [
    "Nem kell a különböző szakemberek között {action}.",
    "Nem az Ön feladata, hogy a kivitelezők és az alvállalkozók között {action}.",
    "A te feladatod nem az, hogy a szereplők között {action}.",
])
def test_same_full_exemption_is_detected_without_relying_on_one_quote_or_pronoun(action, form):
    assert processing._has_coordination_exemption(form.format(action=action))


@pytest.mark.parametrize("text", [
    "Nem kell egyeztetnie a különböző szakemberekkel.",
    "A különböző szakemberek között nem kell közvetítenie.",
    "Nem a feladata a szakemberek munkájának összehangolása.",
    "Nem a feladatod az alvállalkozók szervezése.",
    "Nem kell a kivitelezőivel egyeztetnie.",
    "Nem kell a szakemberei között közvetítenie.",
    "Nem kell a műszaki részleteket egyeztetnie.",
    "Nem kell a teljes projektet koordinálnia.",
    "Nem kell a szakemberekkel egyetlen műszaki részletről sem egyeztetnie.",
    "A szakemberek teljes összehangolása nem az Ön feladata.",
    "A szakemberek koordinálása nem a feladatod.",
    "Az alvállalkozók szervezése nem az Ön feladata.",
    "Önnek nem kell koordinálnia a szakemberek munkáját, csak kiválasztania a burkolat színét.",
    "Nem kell a szakemberek között közvetítenie, elég kiválasztania a burkolat színét.",
    "Válassza ki a burkolat színét, nem kell a szakemberek között egyeztetnie.",
])
def test_inflected_actions_and_group_scope_are_detected_in_either_order(text):
    assert processing._has_coordination_exemption(text)


@pytest.mark.parametrize("text", [
    HELP,
    "A mérnök segít a műszaki egyeztetés előkészítésében.",
    "Érdemes előre egyeztetni a szakemberekkel.",
    "Tisztázza, kinek a feladata a szakemberek összehangolása.",
    "Egyeztessen a szakemberrel a burkolat színéről.",
    "Nem kell azonnal egyeztetnie a szakemberekkel.",
    "Nem kell újra egyeztetnie ugyanarról a méretről a szakemberekkel.",
    "Nem kell egy csomópontról külön egyeztetnie a szakemberekkel.",
    "Nem kell a szakemberrel egyeztetnie a csap színéről.",
    "Nem kell a burkolat színéről külön egyeztetnie a szakemberekkel.",
    "Nem kell a szakemberekkel a kilincs színét egyeztetnie.",
    "A szakemberekkel egyeztetnie érdemes, de nem a feladata az anyagbeszerzés.",
    "Nem kell-e a szakemberek között egyeztetnie?",
    "Nem kellene a szakemberekkel egyeztetnie?",
    "Nem állítjuk, hogy nem kell különböző szakemberek között közvetítenie.",
    "Ez nem jelenti azt, hogy nem a feladata a szakemberek munkájának összehangolása.",
    "Ne gondolja, hogy Önnek így nem kell a szereplők között koordinálnia.",
    "Nem állítjuk, hogy a szakemberek teljes összehangolása nem az Ön feladata.",
])
def test_real_partial_help_single_technical_advice_and_denied_promises_are_retained(text):
    assert not processing._has_coordination_exemption(text)


def test_denied_warning_does_not_hide_later_assertion_or_cross_public_fields():
    warning = "Nem állítjuk, hogy nem kell a szakemberek között közvetítenie."
    assertion = "Nem kell a szakemberek között egyeztetnie."
    assert processing._has_coordination_exemption(warning + " " + assertion)
    assert ERROR in processing._deterministic_publication_errors(
        {"title": "Nem állítjuk, hogy", "body": assertion}, {},
    )


def test_actual_bautica_provider_and_final_copy_both_keep_the_same_unverified_scope(db):
    sample = json.loads(FIXTURE.read_text("utf-8"))
    contract = trusted_contract(db, "Bautica")
    for package in [*sample["provider_packages"], sample["recorded_final_package"]]:
        assert BODY_BAD in package["body"] and FACEBOOK_BAD in package["facebook_post"]
        errors = processing._deterministic_publication_errors(package, contract)
        assert ERROR in errors
        corrections = processing._content_repair_instructions(package, errors, contract)
        for field, bad in (("body", BODY_BAD), ("facebook_post", FACEBOOK_BAD)):
            finding = next(item for item in corrections
                           if item["error"] == ERROR and item["field"] == field)
            span = next(item for item in finding["spans"] if bad in item["text"])
            assert package[field][span["start"]:span["end"]] == span["text"]
            assert span["start"] > 240
            assert "ne írd át puszta szinonimára" in finding["instruction_hu"]


@pytest.mark.parametrize("field", ["title", "body", "facebook_post", "cta"])
def test_same_brand_verified_full_scope_is_required_in_every_public_field(db, field):
    value = {"label": FACEBOOK_BAD} if field == "cta" else FACEBOOK_BAD
    package = {field: value, "_approved_scope_claims": ["Teljes projektkoordinációt vállalunk."]}
    assert ERROR in processing._deterministic_publication_errors(
        package, trusted_contract(db, "Bautica"),
    )
    assert ERROR not in processing._deterministic_publication_errors(
        package, trusted_contract(db, "Property360"),
    )
    wrong_brand = processing._contract_with_approved_claims(
        {}, processing._approved_brand_facts(db, "Property360", current=NOW), brand_id="Bautica",
    )
    assert ERROR in processing._deterministic_publication_errors(package, wrong_brand)


@pytest.mark.parametrize("repair_mode", ["complete", "body_then_facebook", "synonym", "forged"])
def test_actual_copy_repair_must_change_the_scope_not_only_its_words(db, monkeypatch, repair_mode):
    sample = json.loads(FIXTURE.read_text("utf-8"))
    original = sample["recorded_final_package"]

    def generate(request, system):
        assert "ne írd át puszta szinonimára" in system
        package = deepcopy(original)
        if "repair_round" in request:
            assert ERROR in request["gate_errors"]
            correction = request["field_corrections"][0]
            assert "ne írd át puszta szinonimára" in correction["instruction_hu"]
            if repair_mode in ("complete", "body_then_facebook"):
                package["body"] = package["body"].replace(BODY_BAD, HELP)
                if repair_mode == "complete" or request["repair_round"] == 2:
                    package["facebook_post"] = package["facebook_post"].replace(FACEBOOK_BAD, HELP)
            else:
                for field in ("body", "facebook_post"):
                    package[field] = package[field].replace(
                        "közvetítenie", "koordinálnia",
                    ).replace("egyeztetnie", "összehangolnia")
                if repair_mode == "forged":
                    package["_approved_scope_claims"] = ["Teljes projektkoordinációt vállalunk."]
        return {"package": package}

    result, row, calls = run_brand(db, monkeypatch, "Bautica", generate)
    output = json.loads(row.evidence_json)
    if repair_mode in ("synonym", "forged"):
        assert result["failed"] == 1 and result["generated"] == 0
        assert output["content_repair_attempts"] == 2
        assert len(calls) == 3
        assert not any("release_review" in call["purpose"] for call in calls)
        assert "quality_gate_manifest" not in output
        assert "review_pending_draft" in output
        for field in ("body", "facebook_post"):
            assert processing._has_coordination_exemption(output["review_pending_draft"][field])
        return
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == (3 if repair_mode == "complete" else 4)
    assert all(call["high_stakes"] for call in calls)
    assert "release_review" in calls[-1]["purpose"]
    assert "ne írd át puszta szinonimára" in calls[-1]["system_prompt"]
    for field in ("body", "facebook_post"):
        assert HELP in output[field]
        assert not processing._has_coordination_exemption(output[field])
    assert output["cta"] == original["cta"]
    assert output["revenue_intent"] == calls[0]["request"]["revenue_intent"]
    assert output["revenue_intent"]["send_allowed"] is False
    assert output["revenue_intent"]["publication_allowed"] is False
    assert processing._verified_quality_manifest(output, now=NOW)
    assert output["quality_gate_manifest"]["artifact_sha256"] == processing._sha(
        calls[-1]["request"]["artifact"],
    )
    changed = deepcopy(output)
    changed["facebook_post"] = original["facebook_post"]
    with pytest.raises(ValueError):
        processing._verified_quality_manifest(changed, now=NOW)


def test_p360_coordination_survives_existing_delivery_readback_and_does_not_authorize_prices(
    db, monkeypatch,
):
    phrase = "Nem kell a különböző szakemberek között egyeztetned."

    def generate(request, _system):
        package = _copy_only(request["revenue_intent"])
        package["body"] += " " + phrase
        return {"package": package}

    result, row, calls = run_brand(db, monkeypatch, "Property360", generate)
    assert result["generated"] == 1 and len(calls) == 2, row.evidence_json
    images = []

    def pending_image(package, **kwargs):
        images.append(package)
        assert phrase in package["body"]
        assert processing._verified_quality_manifest(package, now=NOW)
        return "pending", {}

    monkeypatch.setattr(processing, "sync_canonical_image", pending_image)
    result = processing.enqueue_daily_publications(db, now=NOW)
    assert result["blocked"] == result["queued"] == 0 and len(images) == 1
    assert json.loads(row.evidence_json)["publication_state"] == "WAITING_FOR_IMAGE"
    errors = processing._deterministic_publication_errors(
        {"brand_id": "Property360", "body": phrase + " Ingyenes felmérés, 200 ezer megtakarítás."},
        trusted_contract(db, "Property360"),
    )
    assert {"unverified_offer_condition", "unverified_numeric_claim"}.issubset(errors)
