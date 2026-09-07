"""A no-obligation promise cannot escape the existing rule by adding a particle/pronoun."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_content_brand_form_regressions import run_brand
from test_content_model_output_contract import NOW

from app.growth_ops import processing

FIXTURE = Path(__file__).parent / "fixtures/content_factory_v9_offer_variant_20260907.json"
ERROR = "unverified_offer_condition"
BAD = "nem is kötelez semmire"
FIRST_CLAUSE = "A becslés kérése nem jelenti azt, hogy azonnal szerződést kell kötnöd"


@pytest.mark.parametrize("text", [
    "A becslés kérése nem is kötelez semmire.",
    "A becslés kérése nem kötelez téged semmire.",
    "A becslés kérése nem kötelez Önt semmire.",
    "A becslés kérése nem is kötelez Önt semmire.",
    "A becslés kérése nem kötelezi Önt semmire.",
    "Az ajánlatkérés semmire nem kötelez.",
    "Az ajánlatkérés semmire sem kötelez.",
    "Az ajánlatkérés semmire nem is kötelez.",
])
def test_no_obligation_particle_and_pronoun_variants_need_same_existing_repair(text):
    assert ERROR in processing._deterministic_publication_errors({"body": text}, {})


@pytest.mark.parametrize("text", [
    FIRST_CLAUSE + ".",
    "A becslés kérése nem jelenti automatikusan a szerződéskötést.",
    "A becslés még nem tételes vállalási ajánlat.",
    "A megkeresés pontos feltételeit érdemes előre tisztáznod.",
    "Kérdezze meg, milyen feltételekkel vehető igénybe a becslés.",
    "Tisztázd, hogy milyen kötelezettségekkel jár a megkeresés.",
])
def test_limited_process_explanation_and_condition_clarification_are_preserved(text):
    assert ERROR not in processing._deterministic_publication_errors({"body": text}, {})


@pytest.mark.parametrize("field", ["title", "body", "facebook_post", "cta"])
def test_same_no_obligation_rule_covers_every_public_field_and_returns_exact_sentence(field):
    text = FIRST_CLAUSE + ", és " + BAD + "."
    value = {"label": text, "intent": "lead"} if field == "cta" else text
    findings = processing._content_repair_instructions({field: value}, [ERROR], {})
    finding = next(item for item in findings if item["error"] == ERROR)
    assert finding["field"] == field
    assert finding["spans"] == [{"start": 0, "end": len(text), "text": text}]


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_actual_baufreund_promise_uses_two_existing_repairs_then_only_corrected_copy_is_signed(
    db, monkeypatch, repair_succeeds,
):
    sample = json.loads(FIXTURE.read_text("utf-8"))
    original = sample["package"]
    assert BAD in original["body"] and FIRST_CLAUSE in original["body"]

    def generate(request, _system):
        package = deepcopy(original)
        if "repair_round" in request:
            assert ERROR in request["gate_errors"]
            finding = next(item for item in request["field_corrections"] if item["error"] == ERROR)
            assert finding["field"] == "body"
            span = finding["spans"][0]
            assert span["start"] > 240 and BAD in span["text"]
            assert request["blocked_package"]["body"][span["start"]:span["end"]] == span["text"]
            if repair_succeeds:
                package["body"] = package["body"].replace(
                    ", és " + BAD,
                    "; a megkeresés pontos feltételeit érdemes előre tisztáznod",
                )
        return {"package": package}

    result, row, calls = run_brand(db, monkeypatch, "BauFreund", generate)
    assert len(calls) == 3 and all(call["high_stakes"] for call in calls)
    output = json.loads(row.evidence_json)
    if not repair_succeeds:
        assert result["generated"] == 0 and result["failed"] == 1
        assert output["content_repair_attempts"] == 2
        assert not any("release_review" in call["purpose"] for call in calls)
        assert "quality_gate_manifest" not in output
        assert BAD in output["review_pending_draft"]["body"]
        return
    assert result["generated"] == 1, row.evidence_json
    assert "release_review" in calls[-1]["purpose"]
    assert output["content_repair_attempts"] == 1
    assert BAD not in output["body"] and FIRST_CLAUSE in output["body"]
    assert output["cta"] == original["cta"]
    assert output["facebook_post"] == original["facebook_post"]
    assert output["revenue_intent"]["publication_allowed"] is False
    assert output["revenue_intent"]["send_allowed"] is False
    assert output["revenue_intent"] == calls[0]["request"]["revenue_intent"]
    assert processing._verified_quality_manifest(output, now=NOW)
    assert output["quality_gate_manifest"]["review_request_id"] == "OFFLINE-3"
    assert output["quality_gate_manifest"]["artifact_sha256"] == processing._sha(
        calls[-1]["request"]["artifact"],
    )
