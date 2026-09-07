"""The actual Everyday sentence needs correct argument structure, not word substitution."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_content_brand_form_regressions import run_brand
from test_content_model_output_contract import NOW

from app.growth_ops import processing

FIXTURE = Path(__file__).parent / "fixtures/content_factory_v11_everyday_case_20260907.json"
ERROR = "hungarian_sentence_structure"
BAD = (
    "Az előszoba, a kamra és a háztartási helyiség elrendezése sok múlik azon, "
    "milyen lesz a hétköznap."
)
GOOD = (
    "Az előszoba, a kamra és a háztartási helyiség elrendezésén sok múlik a hétköznapokban."
)


@pytest.mark.parametrize("noun", ["elrendezése", "elhelyezése"])
@pytest.mark.parametrize("extra", ["", "nagyon ", "igen "])
def test_mismatched_subject_and_argument_is_detected(noun, extra):
    package = {"body": f"Az előszoba {noun} {extra}sok múlik azon, milyen lesz a hétköznap."}
    assert ERROR in processing._deterministic_publication_errors(package, {})


@pytest.mark.parametrize("sentence", [
    GOOD,
    "Az előszoba elhelyezésén sok múlik a hétköznapokban.",
    "Az előszoba elrendezése az Ön döntésén múlik.",
    "Sok múlik azon, milyen lesz az előszoba elrendezése.",
    "Az előszoba elhelyezése jó. Sok múlik az előkészítésen.",
    "Az elrendezése sok család számára fontos.",
])
def test_correct_locative_or_genuine_subject_and_unrelated_sok_are_preserved(sentence):
    assert ERROR not in processing._deterministic_publication_errors({"body": sentence}, {})


def test_correct_title_and_separate_article_do_not_form_a_false_sentence_error():
    package = {
        "title": "Az előszoba és a kamra elrendezése",
        "body": "Sok múlik a napi útvonalak előzetes átgondolásán.",
    }
    assert ERROR not in processing._deterministic_publication_errors(package, {})
    assert ERROR in processing._deterministic_publication_errors(
        {"body": package["title"] + " " + package["body"]}, {},
    )


@pytest.mark.parametrize("field", ["title", "body", "facebook_post", "cta"])
def test_same_whole_sentence_feedback_is_bound_to_each_public_field(field):
    value = {"label": BAD} if field == "cta" else BAD
    corrections = processing._content_repair_instructions({field: value}, [ERROR], {})
    assert corrections[0]["field"] == field
    assert corrections[0]["spans"] == [{"start": 0, "end": len(BAD), "text": BAD}]
    assert "sok múlik" in corrections[0]["instruction_hu"]
    assert "min múlik" in corrections[0]["instruction_hu"]


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_real_everyday_sentence_uses_existing_whole_sentence_repair_and_fresh_review(
    db, monkeypatch, repair_succeeds,
):
    sample = json.loads(FIXTURE.read_text("utf-8"))
    original = sample["package"]
    assert BAD in original["facebook_post"]
    assert BAD in sample["provider_package"]["facebook_post"]

    def generate(request, system):
        assert "min múlik" in system
        package = deepcopy(original)
        if "repair_round" in request:
            assert ERROR in request["gate_errors"]
            finding = next(item for item in request["field_corrections"] if item["error"] == ERROR)
            assert finding["field"] == "facebook_post"
            assert finding["spans"][0]["text"] == BAD + " "
            if repair_succeeds:
                package["facebook_post"] = package["facebook_post"].replace(BAD, GOOD)
        return {"package": package}

    result, row, calls = run_brand(db, monkeypatch, "Everyday Homes", generate)
    output = json.loads(row.evidence_json)
    assert len(calls) == 3
    if not repair_succeeds:
        assert result["failed"] == 1 and result["generated"] == 0
        assert output["content_repair_attempts"] == 2
        assert "quality_gate_manifest" not in output
        assert BAD in output["review_pending_draft"]["facebook_post"]
        return
    assert result["generated"] == 1, row.evidence_json
    assert "release_review" in calls[-1]["purpose"]
    assert GOOD in output["facebook_post"] and BAD not in output["facebook_post"]
    assert output["body"] == original["body"]
    assert output["cta"] == original["cta"]
    assert output["revenue_intent"] == calls[0]["request"]["revenue_intent"]
    assert output["revenue_intent"]["publication_allowed"] is False
    assert output["revenue_intent"]["send_allowed"] is False
    assert processing._verified_quality_manifest(output, now=NOW)
    assert output["quality_gate_manifest"]["artifact_sha256"] == processing._sha(
        calls[-1]["request"]["artifact"],
    )
