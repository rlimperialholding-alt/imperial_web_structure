"""Actual V5 RED failure: repair sees the late offending sentence and uses Pro.

Provider output fixtures are genuine; replacement responses below are explicit
offline stubs. They prove routing/repair boundaries, not provider writing quality.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_content_brand_form_regressions import intent_for, run_brand

from app.growth_ops import processing

FIXTURE = Path(__file__).parent / "fixtures/content_factory_v5_repair_excerpt_20260907.json"


def recorded(brand):
    return next(row for row in json.loads(FIXTURE.read_text("utf-8")) if row["brand_id"] == brand)


def test_every_actual_red_attempt_locates_the_unchanged_late_claim(db):
    brand = "RED Property"
    intent = intent_for(db, brand)
    contract = processing.publication_contract_for_brand(brand)
    responses = recorded(brand)["calls"]
    assert len(responses) == 3
    assert responses[1]["response_sha256"] == responses[2]["response_sha256"]
    for call in responses:
        package, _ = processing._normalize_generated_content_package(
            call["output"], brand_id=brand, revenue_intent=intent,
        )
        package = processing._normalize_content_lengths(
            processing._sanitize_unbound_claims(package),
        )
        body = package["body"]
        assert body.index("legszebb") > 1300
        assert "legszebb" not in body[:240]  # the previous repair excerpt missed the defect
        corrections = processing._content_repair_instructions(
            package, processing._deterministic_publication_errors(package, contract), contract,
        )
        finding = next(item for item in corrections
                       if item["field"] == "body" and item["error"] == "unsupported_absolute_claim")
        assert len(finding["spans"]) == 1
        span = finding["spans"][0]
        assert span["start"] > 1200
        assert body[span["start"]:span["end"]] == span["text"]
        assert "házválasztás nem arról szól" in span["text"]
        assert "legszebb" in span["text"]
        assert finding["excerpts"] == [span["text"]]
        assert "unsupported_absolute_claim" in processing._deterministic_publication_errors(
            {"brand_id": brand, "body": span["text"]}, contract,
        )


@pytest.mark.parametrize("field", ["title", "body", "facebook_post", "cta"])
@pytest.mark.parametrize(("bad", "error", "contract"), [
    ("Ez a legszebb házterv.", "unsupported_absolute_claim", {}),
    ("Az ára 200 ezer forint.", "unverified_numeric_claim", {}),
    ("Ez a feladat két hét alatt lezárul.", "unverified_numeric_claim", {}),
    ("Egy ügyfelünk telkét vizsgáltuk.", "unverified_case_or_capability_claim", {}),
    ("Ez a felmérés ingyenes.", "unverified_offer_condition", {}),
    ("Nézd meg a tervet.", "brand_address_mode_violation", {"voice": "magázó"}),
    ("Bautica – Az építés gyorsasága.", "locked_slogan_modified",
     {"locked_slogan": "Az építés szabadsága."}),
])
def test_original_claim_matrix_stays_rejected_with_exact_public_field_locations(
    field, bad, error, contract,
):
    prefix = "A műszaki tartalmat előre tisztázni érdemes. " * 32
    text = prefix + bad + " A tervet a telekkel együtt kell áttekinteni."
    value = {"label": text, "intent": "lead"} if field == "cta" else text
    package = {"brand_id": "Bautica", field: value}
    before = deepcopy(package)
    errors = processing._deterministic_publication_errors(package, contract)
    assert error in errors
    corrections = processing._content_repair_instructions(package, errors, contract)
    finding = next(item for item in corrections if item["error"] == error)
    assert finding["field"] == field
    assert len(finding["spans"]) == 1
    span = finding["spans"][0]
    assert span["start"] == len(prefix)
    assert text[span["start"]:span["end"]] == span["text"]
    assert span["text"].strip() == bad
    assert package == before  # diagnostics neither fix the text nor authorize it
    assert processing._deterministic_publication_errors(package, contract) == errors


def test_safe_negated_offer_and_brand_number_are_not_reported_as_bad_numeric_or_offer_spans():
    package = {"brand_id": "Property360", "body": (
        "A Property360 dokumentumát nézzük át. A konzultáció nem ingyenes. "
        "A másik felmérés díjmentes. A munka két hét alatt lezárul."
    )}
    errors = processing._deterministic_publication_errors(package, {})
    corrections = processing._content_repair_instructions(package, errors, {})
    assert {item["error"] for item in corrections} == {
        "unverified_numeric_claim", "unverified_offer_condition",
    }
    excerpts = " ".join(part for item in corrections for part in item["excerpts"])
    assert "két hét" in excerpts and "díjmentes" in excerpts
    assert "Property360" not in excerpts and "nem ingyenes" not in excerpts


def test_soft_line_break_keeps_negation_with_the_same_sentence():
    package = {"body": "A konzultáció nem\ningyenes. A másik felmérés díjmentes."}
    assert processing._deterministic_publication_errors(
        {"body": "A konzultáció nem\ningyenes."}, {},
    ) == []
    corrections = processing._content_repair_instructions(
        package, ["unverified_offer_condition"], {},
    )
    assert len(corrections[0]["spans"]) == 1
    assert corrections[0]["excerpts"] == ["A másik felmérés díjmentes."]


def test_mixed_voice_error_preserves_both_actual_markers_across_sentences():
    package = {"body": (
        "A tervet előre kell egyeztetni. Ön kérjen részletes ajánlatot. "
        "A műszaki tartalom számít. Nézd meg a tervet. Az előkészítés hasznos."
    )}
    corrections = processing._content_repair_instructions(
        package, ["mixed_formal_informal_address"], {},
    )
    span = corrections[0]["spans"][0]
    assert "Ön kérjen" in span["text"] and "Nézd meg" in span["text"]
    assert "A tervet előre" not in span["text"]
    assert "Az előkészítés" not in span["text"]
    assert package["body"][span["start"]:span["end"]] == span["text"]
    assert "mixed_formal_informal_address" in processing._deterministic_publication_errors(
        {"body": span["text"]}, {},
    )


def test_long_sentence_does_not_hide_a_late_trigger_or_clip_it_to_first_characters():
    text = "A terv " + "tartalmát " * 100 + "garantáltan megfelelőnek tekintjük."
    corrections = processing._content_repair_instructions(
        {"body": text}, ["unsupported_absolute_claim"], {},
    )
    span = corrections[0]["spans"][0]
    assert span == {"start": 0, "end": len(text), "text": text}
    assert "garantáltan" in span["text"]


def test_facebook_link_dependency_gets_its_actual_late_sentence():
    prefix = "A műszaki tartalom összevetése segíti a döntést. " * 10
    text = prefix + "A részletek a cikkünkben találhatók."
    corrections = processing._content_repair_instructions(
        {"facebook_post": text}, ["facebook_not_standalone"], {},
    )
    assert corrections[0]["spans"][0]["start"] == len(prefix)
    assert "cikkünkben" in corrections[0]["excerpts"][0]


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_actual_red_copy_repair_and_original_generation_use_high_stakes_with_same_bounds(
    db, monkeypatch, repair_succeeds,
):
    actual = recorded("RED Property")["calls"][-1]["output"]

    def generate(request, system):
        if "repair_round" not in request:
            return deepcopy(actual)
        assert "spans start/end" in system
        finding = next(item for item in request["field_corrections"]
                       if item["error"] == "unsupported_absolute_claim")
        span = finding["spans"][0]
        assert span["start"] > 1200
        assert request["blocked_package"]["body"][span["start"]:span["end"]] == span["text"]
        assert "legszebb" in span["text"]
        response = deepcopy(actual)
        if repair_succeeds:
            response["package"]["body"] = response["package"]["body"].replace(
                "legszebb", "neked tetsző",
            )
        return response

    result, row, calls = run_brand(db, monkeypatch, "RED Property", generate)
    assert len(calls) == 3  # generation + repair + review OR generation + two failed repairs
    assert all(call["high_stakes"] is True for call in calls)
    assert calls[0]["max_tokens"] == 3000
    assert calls[1]["max_tokens"] == 3500
    assert calls[0]["purpose"] == "canonical_daily_content_factory:RED Property"
    assert calls[1]["request"]["repair_round"] == 1
    evidence = json.loads(row.evidence_json)
    if repair_succeeds:
        assert result["generated"] == 1, row.evidence_json
        assert "release_review" in calls[-1]["purpose"]
        assert "legszebb" not in evidence["body"]
        assert "neked tetsző" in evidence["body"]
        assert evidence["quality_gate_manifest"]["artifact_sha256"] == processing._sha(
            calls[-1]["request"]["artifact"],
        )
        assert evidence["revenue_intent"]["send_allowed"] is False
    else:
        assert result["failed"] == 1 and result["generated"] == 0
        assert calls[-1]["request"]["repair_round"] == 2
        assert not any("release_review" in call["purpose"] for call in calls)
        assert "quality_gate_manifest" not in evidence


def test_v5_radar_title_is_actual_quality_evidence_not_a_new_literal_filter():
    record = recorded("BauFreund")
    assert record["calls"][0]["model_id"] == "deepseek-v4-flash"
    assert record["calls"][0]["output"]["package"]["title"].startswith(
        "Végletes árajánlatok kaptál?",
    )
    # All brands share the high_stakes CF call path tested above. We do not
    # rewrite this one title or add a hardcoded word ban to mask provider quality.
