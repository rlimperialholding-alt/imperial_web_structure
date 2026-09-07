"""The actual RED no-surprise promise must be repaired without banning useful benefits."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_content_brand_form_regressions import run_brand
from test_content_model_output_contract import NOW

from app.growth_ops import processing

FIXTURE = Path(__file__).parent / "fixtures/content_factory_v7_no_surprise_20260907.json"
BAD = "nem érhet meglepetés a kivitelezés közben"
REPAIR = "csökkentheted a hiányosan tisztázott műszaki tartalomból eredő félreértések kockázatát"
ERROR = "unsupported_absolute_claim"


def recorded(brand):
    return next(row for row in json.loads(FIXTURE.read_text("utf-8")) if row["brand_id"] == brand)


def test_actual_red_sentence_is_located_and_still_rejected_with_its_approved_brand_sources(db):
    row = recorded("RED Property")
    package = dict(row["package"], brand_id=row["brand_id"])
    contract = processing._contract_with_approved_claims(
        processing.publication_contract_for_brand(row["brand_id"]),
        processing._approved_brand_facts(db, row["brand_id"], current=NOW),
        brand_id=row["brand_id"],
    )
    errors = processing._deterministic_publication_errors(package, contract)
    assert ERROR in errors
    corrections = processing._content_repair_instructions(package, errors, contract)
    finding = next(item for item in corrections if item["error"] == ERROR)
    assert finding["field"] == "body"
    span = finding["spans"][0]
    assert span["start"] > 240
    assert package["body"][span["start"]:span["end"]] == span["text"]
    assert BAD in span["text"]


@pytest.mark.parametrize("field", ["title", "body", "facebook_post", "cta"])
def test_categorical_promise_is_checked_in_every_public_field(field):
    text = "Így " + BAD + "."
    value = {"label": text, "intent": "lead"} if field == "cta" else text
    assert ERROR in processing._deterministic_publication_errors({field: value}, {})


@pytest.mark.parametrize("text", [
    "Önt nem érheti meglepetés.",
    "Így nem érhet téged semmilyen meglepetés.",
    "Nem lehet váratlan költség az építkezésben.",
    "Nem lehet semmilyen váratlan helyzet.",
    "Nem lehet váratlan fordulat a kivitelezésben.",
    "Így a kivitelezés nem hagy nyitott kérdéseket.",
])
def test_categorical_variants_require_repair(text):
    assert ERROR in processing._deterministic_publication_errors({"body": text}, {})


def test_useful_conditional_benefits_and_explicit_warnings_are_retained():
    texts = [
        "A feltételek tisztázása segít elkerülni a kellemetlen meglepetéseket.",
        "Ha a műszaki tartalmat előre tisztázod, csökkentheted a félreértések kockázatát.",
        "Az összehangolás révén elkerülheted a felesleges köröket.",
        "Érdemes felkészülni a váratlan helyzetekre is.",
        "Érdemes tisztázni a rögzítési igényeket, hogy ne maradjon nyitott kérdés.",
        "Ez nem jelenti azt, hogy a kivitelezés nem hagy nyitott kérdéseket.",
        "Ez nem jelenti azt, hogy nem érhet meglepetés.",
        "Nem állítjuk, hogy Önt nem érheti meglepetés.",
        "Nem lehet garantálni, hogy nem lehet váratlan költség.",
        "Ne feltételezd, hogy nem érhet meglepetés.",
        'Nem ígérjük, hogy „nem érhet meglepetés”.',
    ]
    for text in texts:
        assert ERROR not in processing._deterministic_publication_errors({"body": text}, {}), text
        # A warning does not hide a subsequent genuine unsupported assertion.
        assert ERROR in processing._deterministic_publication_errors(
            {"body": text + " Így " + BAD + "."}, {},
        ), text


def test_actual_p360_process_benefit_keeps_source_facts_and_reaches_review_without_repair(
    db, monkeypatch,
):
    original = deepcopy(recorded("Property360")["package"])
    assert "elkerülheted a későbbi kellemetlen meglepetéseket" in original["body"]
    result, row, calls = run_brand(
        db, monkeypatch, "Property360", lambda *args: {"package": deepcopy(original)},
    )
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 2
    evidence = json.loads(row.evidence_json)
    assert "elkerülheted a későbbi kellemetlen meglepetéseket" in evidence["body"]
    assert evidence["cta"] == original["cta"]
    assert processing._verified_quality_manifest(evidence, now=NOW)


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_real_red_promise_uses_existing_two_repairs_and_only_corrected_copy_can_be_signed(
    db, monkeypatch, repair_succeeds,
):
    original = recorded("RED Property")["package"]

    def generate(request, system):
        assert "kockázat csökkentése nem jelenti minden váratlan helyzet kizárását" in system
        package = deepcopy(original)
        if "repair_round" in request:
            assert ERROR in request["gate_errors"]
            finding = next(item for item in request["field_corrections"] if item["error"] == ERROR)
            span = finding["spans"][0]
            assert BAD in span["text"]
            assert request["blocked_package"]["body"][span["start"]:span["end"]] == span["text"]
            if repair_succeeds:
                package["body"] = package["body"].replace(BAD, REPAIR)
        return {"package": package}

    result, row, calls = run_brand(db, monkeypatch, "RED Property", generate)
    assert len(calls) == 3
    assert all(call["high_stakes"] for call in calls)
    evidence = json.loads(row.evidence_json)
    if repair_succeeds:
        assert result["generated"] == 1, row.evidence_json
        assert "release_review" in calls[-1]["purpose"]
        assert "kockázat csökkentése nem jelenti" in calls[-1]["system_prompt"]
        assert BAD not in evidence["body"] and REPAIR in evidence["body"]
        assert evidence["cta"] == original["cta"]
        statement = evidence["revenue_intent"]["approved_brand_facts"][0]["payload"]["statement"]
        assert statement.rstrip(" .?!") in evidence["body"]
        assert processing._verified_quality_manifest(evidence, now=NOW)
        assert processing._sha(calls[-1]["request"]["artifact"]) == (
            evidence["quality_gate_manifest"]["artifact_sha256"]
        )
        assert evidence["revenue_intent"]["publication_allowed"] is False
    else:
        assert result["failed"] == 1 and result["generated"] == 0
        assert [call["request"].get("repair_round") for call in calls] == [None, 1, 2]
        assert "quality_gate_manifest" not in evidence
        assert not any("release_review" in call["purpose"] for call in calls)
