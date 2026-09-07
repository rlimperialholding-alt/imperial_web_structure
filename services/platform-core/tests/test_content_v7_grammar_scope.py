"""Real V6 editorial defects use existing bounded repair and trusted scope facts."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_content_brand_form_regressions import run_brand
from test_content_model_output_contract import NOW

from app.growth_ops import processing

FIXTURE = Path(__file__).parent / "fixtures/content_factory_v6_grammar_scope_20260907.json"
TAKEOVER = "Önnek így nem kell különböző szereplők között koordinálnia"
CAPABILITY_ERROR = "unverified_case_or_capability_claim"
GRAMMAR_ERROR = "mixed_formal_informal_address"


def recorded(brand, *, radar=False):
    return next(row for row in json.loads(FIXTURE.read_text("utf-8"))
                if row["brand_id"] == brand
                and (row["source_mode"] == "anonymized_original_source_replay") == radar)


def trusted_contract(db, brand):
    return processing._contract_with_approved_claims(
        processing.publication_contract_for_brand(brand),
        processing._approved_brand_facts(db, brand, current=NOW), brand_id=brand,
    )


@pytest.mark.parametrize(("radar", "bad"), [(False, "maga dönts"), (True, "maga tudod")])
def test_both_real_baufreund_grammatical_mismatches_get_exact_sentence_feedback(radar, bad):
    package = dict(recorded("BauFreund", radar=radar)["package"], brand_id="BauFreund")
    contract = processing.publication_contract_for_brand("BauFreund")
    errors = processing._deterministic_publication_errors(package, contract)
    assert GRAMMAR_ERROR in errors
    corrections = processing._content_repair_instructions(package, errors, contract)
    finding = next(item for item in corrections
                   if item["error"] == GRAMMAR_ERROR)
    assert finding["field"] == "body"
    span = finding["spans"][0]
    assert bad in span["text"]
    assert package["body"][span["start"]:span["end"]] == span["text"]
    assert "te dönts" in finding["instruction_hu"] and "te tudod" in finding["instruction_hu"]


@pytest.mark.parametrize("text", [
    "Maga az ár nem elég az összehasonlításhoz.",
    "A terv önmagában nem ad teljes képet.",
    "Ezt magában is átgondolhatja.",
    "Fontos, hogy maga döntsön a lehetőségek között.",
    "Fontos, hogy magad dönts.",
    "A döntést maga is meghozhatja.",
])
def test_legitimate_formal_reflexive_and_emphatic_forms_are_not_mismatch(text):
    assert GRAMMAR_ERROR not in processing._deterministic_publication_errors({"body": text}, {})


@pytest.mark.parametrize("field", ["title", "body", "facebook_post", "cta"])
def test_scope_claim_is_checked_in_every_public_field_with_actual_source(db, field):
    value = {"label": TAKEOVER + ".", "intent": "lead"} if field == "cta" else TAKEOVER + "."
    package = {"brand_id": "Bautica", field: value}
    contract = trusted_contract(db, "Bautica")
    errors = processing._deterministic_publication_errors(package, contract)
    assert CAPABILITY_ERROR in errors
    corrections = processing._content_repair_instructions(package, errors, contract)
    finding = next(item for item in corrections
                   if item["error"] == CAPABILITY_ERROR)
    assert finding["field"] == field
    assert finding["spans"] == [{"start": 0, "end": len(TAKEOVER) + 1, "text": TAKEOVER + "."}]


def test_actual_bautica_source_does_not_prove_complete_takeover_but_p360_source_does(db):
    bautica = trusted_contract(db, "Bautica")
    p360 = trusted_contract(db, "Property360")
    assert any("helyszínt felméri" in text for text in bautica["_approved_scope_claims"])
    assert any("Egyetlen projektben hangolja össze" in text
               for text in p360["_approved_scope_claims"])
    assert CAPABILITY_ERROR in processing._deterministic_publication_errors(
        dict(recorded("Bautica")["package"], brand_id="Bautica"), bautica,
    )
    assert CAPABILITY_ERROR not in processing._deterministic_publication_errors(
        {"brand_id": "Property360", "body": TAKEOVER + "."}, p360,
    )


def test_other_brand_source_and_model_claim_annotations_do_not_authorize_takeover(db):
    contract = processing._contract_with_approved_claims(
        processing.publication_contract_for_brand("Bautica"),
        processing._approved_brand_facts(db, "Property360", current=NOW), brand_id="Bautica",
    )
    assert contract["_approved_scope_claims"] == []
    package = {"brand_id": "Bautica", "body": TAKEOVER + ".",
               "_approved_scope_claims": ["Teljes projektkoordinációt vállalunk."],
               "approved_brand_facts": [{"statement": "Teljes projektkoordinációt vállalunk."}]}
    assert CAPABILITY_ERROR in processing._deterministic_publication_errors(package, contract)


@pytest.mark.parametrize("prefix", [
    "Ez nem jelenti azt, hogy ", "Ebből nem következik, hogy ", "Ne feltételezze, hogy ",
])
def test_warning_against_unproven_takeover_is_retained_and_cannot_hide_later_assertion(prefix):
    warning = prefix + TAKEOVER + "."
    assert CAPABILITY_ERROR not in processing._deterministic_publication_errors(
        {"body": warning}, {},
    )
    assert CAPABILITY_ERROR in processing._deterministic_publication_errors(
        {"body": warning + " " + TAKEOVER + "."}, {},
    )


@pytest.mark.parametrize(("statement", "supported"), [
    ("Teljes projektkoordinációt vállalunk.", True),
    ("Vállaljuk a teljes projektkoordinációt.", True),
    ("Nem vállaljuk a teljes projektkoordinációt.", False),
    ("A teljes projektkoordinációt nem vállaljuk.", False),
    ("A mérnök ellenőrzi a tervet.", False),
])
def test_scope_evidence_is_brand_agnostic_and_requires_positive_full_scope(statement, supported):
    contract = processing._contract_with_approved_claims(
        {}, [{"brand_id": "Example", "payload": {"statement": statement}}], brand_id="Example",
    )
    errors = processing._deterministic_publication_errors(
        {"brand_id": "Example", "body": TAKEOVER + "."}, contract,
    )
    assert (CAPABILITY_ERROR not in errors) == supported


def test_malformed_optional_evidence_is_ignored_without_inventing_scope():
    contract = processing._contract_with_approved_claims(
        {}, [{"brand_id": "Example", "payload": {
            "statement": "A mérnök ellenőrzi a tervet.",
            "source_evidence": ["invalid", {"exact_excerpts": "not a list"}],
        }}], brand_id="Example",
    )
    assert contract["_approved_scope_claims"] == ["A mérnök ellenőrzi a tervet."]


def test_valid_scope_never_authorizes_unrelated_price_or_fee_claims(db):
    errors = processing._deterministic_publication_errors(
        {"brand_id": "Property360",
         "body": TAKEOVER + ". Ingyenes vizsgálat, 200 ezer megtakarítás."},
        trusted_contract(db, "Property360"),
    )
    assert CAPABILITY_ERROR not in errors
    assert {"unverified_numeric_claim", "unverified_offer_condition"}.issubset(errors)


@pytest.mark.parametrize(("brand", "radar", "error"), [
    ("Bautica", False, CAPABILITY_ERROR),
    ("BauFreund", False, GRAMMAR_ERROR),
    ("BauFreund", True, GRAMMAR_ERROR),
])
def test_actual_defect_is_repaired_before_same_artifact_review_and_signature(
    db, monkeypatch, brand, radar, error,
):
    record = recorded(brand, radar=radar)
    intent = deepcopy(record["trusted_intent"])
    monkeypatch.setattr(processing, "_prepare_content_revenue_intent", lambda *a, **kw: intent)

    def generate(request, system):
        assert "részfeladat nem jelent teljes felelősségátvállalást" in system
        package = deepcopy(record["package"])
        if "repair_round" in request:
            assert request["repair_round"] == 1
            assert error in request["gate_errors"]
            finding = next(item for item in request["field_corrections"] if item["error"] == error)
            assert finding["spans"] and finding["field"] == "body"
            package["body"] = package["body"].replace("maga dönts", "te dönts").replace(
                "maga tudod", "te tudod",
            ).replace(
                TAKEOVER,
                "Érdemes előre tisztázni, kinek melyik koordinációs feladat a felelőssége",
            )
        return {"package": package}

    result, row, calls = run_brand(db, monkeypatch, brand, generate)
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 3 and all(call["high_stakes"] for call in calls)
    assert "release_review" in calls[-1]["purpose"]
    assert "részfeladat nem jelent teljes felelősségátvállalást" in calls[-1]["system_prompt"]
    evidence = json.loads(row.evidence_json)
    assert evidence["revenue_intent"] == intent
    assert evidence["cta"] == record["package"]["cta"]
    statement = intent["approved_brand_facts"][0]["payload"]["statement"].rstrip(" .?!")
    assert statement in evidence["body"]
    assert TAKEOVER not in evidence["body"] and "maga dönts" not in evidence["body"]
    assert "maga tudod" not in evidence["body"]
    assert processing._verified_quality_manifest(evidence, now=NOW)
    assert processing._sha(calls[-1]["request"]["artifact"]) == (
        evidence["quality_gate_manifest"]["artifact_sha256"]
    )
    assert evidence["revenue_intent"]["publication_allowed"] is False
    assert (
        calls[0]["request"]["publication_contract"] == calls[-1]["request"]["publication_contract"]
    )


def test_p360_supported_coordination_survives_delivery_readback_and_existing_image_gate(
    db, monkeypatch,
):
    package = deepcopy(recorded("Property360")["package"])
    package["body"] += " Neked így nem kell különböző szereplők között koordinálnod."
    result, row, calls = run_brand(
        db, monkeypatch, "Property360", lambda *args: {"package": package},
    )
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 2  # supported scope needs no repair
    evidence = json.loads(row.evidence_json)
    assert "koordinálnod" in evidence["body"]
    image_calls = []

    def pending_image(package, **kwargs):
        image_calls.append(package)
        assert processing._verified_quality_manifest(package, now=NOW)
        return "pending", {}

    monkeypatch.setattr(processing, "sync_canonical_image", pending_image)
    delivery = processing.enqueue_daily_publications(db, now=NOW)
    assert delivery["blocked"] == delivery["queued"] == 0
    assert len(image_calls) == 1
    assert row.status == "release_passed"
    assert json.loads(row.evidence_json)["publication_state"] == "WAITING_FOR_IMAGE"
    # The exact source-supported text is signed. Alteration cannot reuse its release.
    changed = json.loads(row.evidence_json)
    changed["body"] += " Megváltozott vállalás."
    row.evidence_json = json.dumps(changed)
    db.commit()
    assert processing.enqueue_daily_publications(db, now=NOW)["blocked"] == 1
    assert len(image_calls) == 1


def test_unrepaired_scope_or_forged_model_fact_cannot_bypass_two_repair_limit(db, monkeypatch):
    package = deepcopy(recorded("Bautica")["package"])
    package["_approved_scope_claims"] = ["Teljes projektkoordinációt vállalunk."]
    result, row, calls = run_brand(db, monkeypatch, "Bautica", lambda *args: {"package": package})
    assert result["failed"] == 1 and result["generated"] == 0
    assert len(calls) == 3
    assert [call["request"].get("repair_round") for call in calls] == [None, 1, 2]
    assert not any("release_review" in call["purpose"] for call in calls)
    assert "quality_gate_manifest" not in json.loads(row.evidence_json)
