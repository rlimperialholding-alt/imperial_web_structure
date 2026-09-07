"""Actual V8 copy defects use existing source-bound repair, without broad morphology rules."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_content_brand_form_regressions import run_brand
from test_content_model_output_contract import NOW

from app.growth_ops import processing

FIXTURE = Path(__file__).parent / "fixtures/content_factory_v8_language_scope_20260907.json"
GRAMMAR = "mixed_formal_informal_address"
STRUCTURE = "hungarian_sentence_structure"
CAPABILITY = "unverified_case_or_capability_claim"
ABSOLUTE = "unsupported_absolute_claim"
INSTANT = (
    "Ha a terv és a valós helyszín eltér, a mérnök azonnal tud döntést hozni, "
    "és ezt a döntést a teljes folyamatban következetesen érvényesíti."
)
FEAR = "nem kell attól tartania, hogy egy apró eltérésből később nagyobb probléma lesz"
BAD_SENTENCE = (
    "Az előszoba, a kamra és a háztartási helyiség elhelyezése sok családnál utólag "
    "derül ki, hogy nem a napi útvonalakat követi."
)
GOOD_SENTENCE = (
    "Sok családnál csak utólag derül ki, hogy az előszoba, a kamra és a háztartási "
    "helyiség elhelyezése nem a napi útvonalakat követi."
)


def recorded(brand):
    return next(row for row in json.loads(FIXTURE.read_text("utf-8")) if row["brand_id"] == brand)


def contract_for(db, brand):
    return processing._contract_with_approved_claims(
        processing.publication_contract_for_brand(brand),
        processing._approved_brand_facts(db, brand, current=NOW), brand_id=brand,
    )


@pytest.mark.parametrize("noun", ["projektje", "terve", "háza", "otthona", "telke", "építkezése"])
def test_known_second_person_possessive_mismatch_is_a_grammar_error(noun):
    assert GRAMMAR in processing._deterministic_publication_errors(
        {"body": f"A te {noun} is így indulhat."}, {},
    )


@pytest.mark.parametrize("text", [
    "A te projekted is így indulhat.", "Az Ön projektje így indulhat.",
    "Az ő projektje is így indulhat.", "A te terved és házad.",
    "A te otthonod, telked és építkezésed.", "A te projektvezetője.",
    "A te terveidről beszélünk.", "A te házadnak a terve.",
])
def test_correct_person_and_unlisted_compound_forms_are_not_rewritten(text):
    assert GRAMMAR not in processing._deterministic_publication_errors({"body": text}, {})


@pytest.mark.parametrize("field", ["title", "body", "facebook_post", "cta"])
def test_possessive_mismatch_has_exact_span_in_every_public_field(field):
    text = "Ha szeretnéd, hogy a te projektje is így induljon, érdemes előre egyeztetni."
    value = {"label": text, "intent": "lead"} if field == "cta" else text
    findings = processing._content_repair_instructions({field: value}, [GRAMMAR], {})
    finding = next(item for item in findings if item["error"] == GRAMMAR)
    assert finding["field"] == field
    assert finding["spans"] == [{"start": 0, "end": len(text), "text": text}]
    assert "a te projekted" in finding["instruction_hu"]


@pytest.mark.parametrize("text", [
    "Csak utólag derül ki, hogy az előszoba elhelyezése rossz.",
    "Az előszoba elhelyezéséről utólag derül ki, hogy nem praktikus.",
    "Az előszoba elhelyezése csak később derül ki.",
    "A terv hibája utólag derül ki, hogyha az árajánlatot is ellenőrzöd.",
    "Az előszoba elhelyezése után utólag derül ki, hogy a lépcső nem fér el.",
    GOOD_SENTENCE,
])
def test_correct_hungarian_main_and_subordinate_clause_constructions_survive(text):
    assert STRUCTURE not in processing._deterministic_publication_errors({"body": text}, {})


@pytest.mark.parametrize("text", [
    "Az előszoba elhelyezése utólag derül ki, hogy rossz.", BAD_SENTENCE,
])
def test_only_specific_broken_placement_sentence_needs_full_sentence_repair(text):
    assert STRUCTURE in processing._deterministic_publication_errors({"facebook_post": text}, {})
    finding = processing._content_repair_instructions(
        {"facebook_post": text}, [STRUCTURE], {},
    )[0]
    assert finding["field"] == "facebook_post" and finding["spans"][0]["text"] == text


@pytest.mark.parametrize("text", [
    "A mérnöki ellenőrzés segíthet az eltérések korai felismerésében és az egyeztetésben.",
    "Eltérés esetén érdemes azonnal egyeztetést kérni.",
    "Nem állítjuk, hogy a mérnök azonnal döntést tud hozni.",
    "A mérnök nem tud azonnal döntést hozni.",
    "A mérnök azonnal nem dönthet.",
    "A mérnök azonnal jelzi, ha hiányzik egy terv.",
    "Érdemes tisztázni, hogy egy apró eltérésből lehet-e később nagyobb probléma.",
    "Nem állítjuk, hogy " + FEAR + ".",
])
def test_advice_and_warnings_do_not_become_unconditional_service_time_promises(text):
    errors = processing._deterministic_publication_errors({"body": text}, {})
    assert CAPABILITY not in errors and ABSOLUTE not in errors


def test_warning_does_not_hide_a_later_actual_capability_or_risk_promise():
    errors = processing._deterministic_publication_errors(
        {"body": "Nem állítjuk, hogy a mérnök azonnal döntést tud hozni. " + INSTANT}, {},
    )
    assert CAPABILITY in errors
    assert ABSOLUTE in processing._deterministic_publication_errors(
        {"body": "Nem állítjuk, hogy " + FEAR + ". Önnek " + FEAR + "."}, {},
    )


def test_immediate_decision_requires_the_same_full_source_sentence_and_cannot_drop_conditions():
    sentence = "A mérnök azonnal döntést tud hozni."
    approved = processing._contract_with_approved_claims(
        {}, [{"brand_id": "Example", "payload": {"statement": sentence}}], brand_id="Example",
    )
    assert CAPABILITY not in processing._deterministic_publication_errors(
        {"body": sentence}, approved,
    )
    for statement in [
        "A mérnök megérti a tervet és ellenőrzi az építést.",
        "A mérnök azonnal döntést tud hozni, ha az összes feltétel előre tisztázott.",
        "Nem állítjuk, hogy a mérnök azonnal döntést tud hozni.",
    ]:
        scoped = processing._contract_with_approved_claims(
            {}, [{"brand_id": "Example", "payload": {"statement": statement}}],
            brand_id="Example",
        )
        assert CAPABILITY in processing._deterministic_publication_errors(
            {"body": sentence}, scoped,
        )
    assert CAPABILITY in processing._deterministic_publication_errors(
        {"body": sentence, "_approved_scope_claims": [sentence]}, {},
    )
    other_brand = processing._contract_with_approved_claims(
        {}, [{"brand_id": "Other", "payload": {"statement": sentence}}], brand_id="Example",
    )
    assert CAPABILITY in processing._deterministic_publication_errors(
        {"body": sentence}, other_brand,
    )


def test_negating_waiting_does_not_authorize_immediate_engineering_decision():
    assert CAPABILITY in processing._deterministic_publication_errors(
        {"body": "A mérnök nem vár egyeztetésre, azonnal döntést hoz."}, {},
    )


@pytest.mark.parametrize("field", ["title", "body", "facebook_post", "cta"])
def test_verified_full_source_sentence_keeps_its_field_boundary(field):
    sentence = "A mérnök azonnal döntést tud hozni."
    contract = processing._contract_with_approved_claims(
        {}, [{"brand_id": "Example", "payload": {"statement": sentence}}], brand_id="Example",
    )
    package = dict.fromkeys(("title", "body", "facebook_post"), "Műszaki döntés előkészítése")
    package["cta"] = {"label": "Egyeztetés előkészítése", "intent": "lead"}
    package[field] = {"label": sentence, "intent": "lead"} if field == "cta" else sentence
    assert CAPABILITY not in processing._deterministic_publication_errors(package, contract)
    assert CAPABILITY in processing._deterministic_publication_errors(package, {})


def test_denial_in_another_field_cannot_hide_an_unverified_immediate_decision():
    assert CAPABILITY in processing._deterministic_publication_errors(
        {"title": "Nem állítjuk, hogy", "body": "A mérnök azonnal döntést tud hozni."}, {},
    )


def test_actual_bautica_sources_locate_both_new_promises_without_losing_engineering_fact(db):
    sample = recorded("Bautica")
    package = dict(sample["package"], brand_id="Bautica")
    contract = contract_for(db, "Bautica")
    assert any("helyszínt felméri" in span for span in contract["_approved_scope_claims"])
    findings = processing._content_repair_instructions(package, [CAPABILITY, ABSOLUTE], contract)
    assert {CAPABILITY, ABSOLUTE}.issubset({item["error"] for item in findings})
    for item in findings:
        assert item["field"] == "body"
        for span in item["spans"]:
            assert package["body"][span["start"]:span["end"]] == span["text"]
    assert any(INSTANT in span["text"] for item in findings for span in item["spans"])
    assert any(FEAR in span["text"] for item in findings for span in item["spans"])


def repair_copy(package, brand):
    result = deepcopy(package)
    if brand == "Property360":
        result["body"] = result["body"].replace("a te projektje", "a te projekted")
    elif brand == "Bautica":
        result["body"] = result["body"].replace(
            INSTANT,
            "Ha a terv és a helyszín eltér, érdemes az eltérés szakmai vizsgálatát "
            "és a szükséges egyeztetést előkészíteni.",
        ).replace(
            FEAR,
            "érdemes időben megvizsgáltatnia az eltéréseket és tisztáznia a következő lépést",
        )
    else:
        result["facebook_post"] = result["facebook_post"].replace(BAD_SENTENCE, GOOD_SENTENCE)
    return result


@pytest.mark.parametrize(("brand", "errors"), [
    ("Property360", {GRAMMAR}), ("Bautica", {CAPABILITY, ABSOLUTE}),
    ("Everyday Homes", {STRUCTURE}),
])
def test_real_copy_errors_use_existing_repair_then_same_final_review_and_signature(
    db, monkeypatch, brand, errors,
):
    sample = recorded(brand)

    def generate(request, system):
        assert "approved statement az igazolt márkatény" in system
        assert "főmondat és mellékmondat" in system
        package = deepcopy(sample["package"])
        if "repair_round" in request:
            assert request["repair_round"] == 1
            assert errors.issubset(set(request["gate_errors"]))
            assert all(item["spans"] for item in request["field_corrections"])
            package = repair_copy(package, brand)
        return {"package": package}

    result, row, calls = run_brand(db, monkeypatch, brand, generate)
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 3 and all(call["high_stakes"] for call in calls)
    output = json.loads(row.evidence_json)
    assert output["content_repair_attempts"] == 1
    assert output["cta"] == sample["package"]["cta"]
    assert output["revenue_intent"]["publication_allowed"] is False
    assert output["revenue_intent"]["send_allowed"] is False
    assert output["quality_gate_manifest"]["review_request_id"] == "OFFLINE-3"
    assert processing._verified_quality_manifest(output, now=NOW)
    assert output["quality_gate_manifest"]["artifact_sha256"] == processing._sha(
        calls[-1]["request"]["artifact"],
    )
    assert "főmondat és mellékmondat" in calls[-1]["system_prompt"]
    assert "source_evidence exact_excerpts" in calls[-1]["system_prompt"]
    assert calls[0]["request"]["revenue_intent"] == output["revenue_intent"]
    facts = output["revenue_intent"]["approved_brand_facts"]
    assert facts[0]["payload"]["statement"].rstrip(" .!?") in output["body"]


def test_unrepaired_real_grammar_error_stops_at_the_same_two_repairs(db, monkeypatch):
    sample = recorded("Property360")
    result, row, calls = run_brand(
        db, monkeypatch, "Property360", lambda *_: {"package": deepcopy(sample["package"])},
    )
    assert result["generated"] == 0 and result["failed"] == 1
    assert len(calls) == 3 and not any("release_review" in c["purpose"] for c in calls)
    output = json.loads(row.evidence_json)
    assert output["content_repair_attempts"] == 2
    assert "quality_gate_manifest" not in output
    assert "a te projektje" in output["review_pending_draft"]["body"]
