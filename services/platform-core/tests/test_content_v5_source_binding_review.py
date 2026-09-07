"""Actual v4 failures: source vocabulary, exact context and contradictory review."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_content_brand_form_regressions as harness

from app.growth_ops import processing

RECORDED = Path(__file__).parent / "fixtures/content_factory_v4_three_failures_20260907.json"


def record(brand):
    return next(row for row in json.loads(RECORDED.read_text("utf-8")) if row["brand_id"] == brand)


@pytest.mark.parametrize("call_index", [0, 1, 2])
def test_real_red_typeplan_copy_matches_the_documented_brand_focus(db, call_index):
    brand = "RED Property"
    source = record(brand)["calls"][call_index]["output"]
    intent = harness.intent_for(db, brand)
    package, issues = processing._normalize_generated_content_package(
        source,
        brand_id=brand,
        revenue_intent=intent,
    )
    assert not issues
    assert "típusterv" in intent["approved_brand_facts"][0]["payload"]["statement"]
    assert "off_brand_topic" not in processing._content_candidate_errors(
        package,
        brand_id=brand,
        focus=processing.content_focus_for_brand(brand),
        contract=processing.publication_contract_for_brand(brand),
        revenue_intent=intent,
    )


def test_real_bautica_paraphrase_binds_context_without_regeneration(db, monkeypatch):
    brand = "Bautica"
    response = record(brand)["calls"][0]["output"]
    original = deepcopy(response)
    intent = harness.intent_for(db, brand)
    assert processing._norm(intent["buyer_problem"]) not in processing._norm(
        response["package"]["body"]
    )
    result, row, calls = harness.run_brand(
        db,
        monkeypatch,
        brand,
        lambda request, system: deepcopy(response),
    )
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 2
    output = json.loads(row.evidence_json)
    assert output["body"].startswith(intent["buyer_problem"])
    assert "Fórumkérdés" not in output["body"]
    assert processing._revenue_package_errors(output, output["revenue_intent"]) == []
    assert calls[-1]["request"]["artifact"]["body"] == output["body"]
    assert output["quality_gate_manifest"]["artifact_sha256"] == processing._sha(
        calls[-1]["request"]["artifact"]
    )
    assert response == original


@pytest.mark.parametrize("bad_copy", ["short", "recipe"])
def test_trusted_context_cannot_rescue_an_empty_or_unrelated_original(db, bad_copy):
    intent = harness.intent_for(db, "Bautica")
    body = (
        "Kivitelezés előtt egyeztessünk."
        if bad_copy == "short"
        else "A kenyértésztát pihentessük. " * 40
    )
    package = {
        "brand_id": "Bautica",
        "title": "",
        "body": body,
        "facebook_post": "#Bautica #felújítás #kivitelezés",
    }
    output, issues = processing._bind_required_content_context(
        package,
        brand_id="Bautica",
        revenue_intent=intent,
    )
    assert output == package
    assert ("body_too_short" if bad_copy == "short" else "off_brand_topic") in issues
    normalized, normalization_issues = processing._normalize_generated_content_package(
        package,
        brand_id="Bautica",
        revenue_intent=intent,
    )
    assert set(issues).issubset(normalization_issues)
    assert normalized["body"] == package["body"]


@pytest.mark.parametrize(
    "bad_intent",
    [
        None,
        {},
        {"buyer_problem": "Van konkrét probléma."},
        {"buyer_problem": "Van konkrét probléma.", "approved_brand_facts": [{"payload": None}]},
    ],
)
def test_incomplete_context_input_returns_an_explicit_issue(bad_intent):
    package = {"body": "Megőrzendő vázlat."}
    assert processing._bind_required_content_context(
        package,
        brand_id="Bautica",
        revenue_intent=bad_intent,
    ) == (package, ["source_context_input_invalid"])


def test_context_and_tail_fact_survive_length_normalization_idempotently(db):
    intent = harness.intent_for(db, "Bautica")
    statement = intent["approved_brand_facts"][0]["payload"]["statement"]
    package = {
        "body": "A kivitelezés előtt a helyszínt és a tervet egyeztetni kell. " * 45 + statement
    }
    bound, issues = processing._bind_required_content_context(
        package,
        brand_id="Bautica",
        revenue_intent=intent,
    )
    assert not issues
    assert len(bound["body"]) <= 2200
    assert intent["buyer_problem"] in bound["body"]
    assert statement in bound["body"]
    assert processing._bind_required_content_context(
        bound,
        brand_id="Bautica",
        revenue_intent=intent,
    ) == (bound, [])


def test_real_radar_problem_is_attributed_and_private_evidence_is_unchanged():
    sample = record("BauFreund")
    intent = deepcopy(sample["trusted_intent"])
    original_intent = deepcopy(intent)
    package = deepcopy(sample["calls"][0]["output"]["package"])
    bound, issues = processing._bind_required_content_context(
        package,
        brand_id="BauFreund",
        revenue_intent=intent,
    )
    assert not issues
    assert bound["body"].startswith(
        "Fórumkérdés, szerkesztett részlet: „" + intent["buyer_problem"]
    )
    assert bound["body"].count(intent["buyer_problem"]) == 1
    assert intent == original_intent
    assert intent["source_problem_evidence"]["published_at"]
    assert intent["source_problem_evidence"]["source_identity"]
    assert processing._bind_required_content_context(
        bound,
        brand_id="BauFreund",
        revenue_intent=intent,
    ) == (bound, [])


def contradiction():
    return deepcopy(record("BauFreund")["calls"][-1]["output"])


@pytest.mark.parametrize(
    "corruption",
    [
        "gate_block",
        "score_low",
        "gate_missing",
        "gate_extra",
        "hash",
        "gates_shape",
        "score_bool",
        "score_string",
        "score_nan",
        "score_infinite",
        "root_extra",
        "findings_shape",
    ],
)
def test_noneligible_review_shapes_never_get_a_consistency_recheck(db, monkeypatch, corruption):
    review = contradiction()
    request = {"artifact_sha256": review["artifact_sha256"]}
    if corruption == "gate_block":
        review["gate_results"]["conversion"]["decision"] = "BLOCK"
    elif corruption.startswith("score_"):
        review["scores"]["conversion_strength"] = {
            "score_low": 79,
            "score_bool": True,
            "score_string": "85",
            "score_nan": float("nan"),
            "score_infinite": float("inf"),
        }[corruption]
    elif corruption == "gate_missing":
        review["gate_results"].pop("conversion")
    elif corruption == "gate_extra":
        review["gate_results"]["extra"] = {"decision": "PASS", "reason": "Extra"}
    elif corruption == "hash":
        review["artifact_sha256"] = "b" * 64
    elif corruption == "gates_shape":
        review["gate_results"] = []
    elif corruption == "root_extra":
        review["unknown"] = True
    else:
        review["findings"] = "invalid"
    calls = []

    def complete(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=json.dumps(review))

    monkeypatch.setattr(processing, "complete_json", complete)
    assert not processing._review_decision_contradiction(review, request)
    result = processing._complete_content_review(db, user_prompt=json.dumps(request))
    assert json.loads(result.content)["overall_decision"] == "BLOCK"
    assert len(calls) == 1


@pytest.mark.parametrize("second", ["pass", "block", "tamper", "contradiction", "score_low"])
def test_contradictory_review_rechecks_same_artifact_once_and_only_pass_can_be_signed(
    db,
    monkeypatch,
    second,
):
    sample = record("BauFreund")
    monkeypatch.setattr(
        processing,
        "_prepare_content_revenue_intent",
        lambda *a, **kw: deepcopy(sample["trusted_intent"]),
    )
    requests = []

    def review(request):
        requests.append(request)
        response = contradiction()
        response["artifact_sha256"] = request["artifact_sha256"]
        if len(requests) == 1:
            return response
        first = requests[0]
        for field in ("artifact", "artifact_sha256", "source_evidence", "trusted_revenue_intent"):
            assert request[field] == first[field]
        assert (
            request["review_consistency_recheck"]["previous_review"]["findings"]
            == contradiction()["findings"]
        )
        assert "nem PASS-t kérünk" in request["review_consistency_recheck"]["instruction_hu"]
        if second == "pass":
            response["overall_decision"] = "PASS"
            response["findings"] = []
        elif second == "block":
            response["gate_results"]["conversion"]["decision"] = "BLOCK"
        elif second == "tamper":
            response["overall_decision"] = "PASS"
            response["artifact_sha256"] = "b" * 64
        elif second == "score_low":
            response["overall_decision"] = "PASS"
            response["scores"]["conversion_strength"] = 79
        return response

    monkeypatch.setattr(harness, "_review", review)
    result, row, calls = harness.run_brand(
        db,
        monkeypatch,
        "BauFreund",
        lambda request, system: deepcopy(sample["calls"][0]["output"]),
    )
    assert len(calls) == 3  # One generator, exactly two review calls; no third review.
    output = json.loads(row.evidence_json)
    assert result["generated"] == (1 if second == "pass" else 0), row.evidence_json
    if second == "pass":
        assert output["quality_gate_manifest"]["review_request_id"] == "OFFLINE-3"
        assert output["revenue_intent"]["publication_allowed"] is False
        assert output["revenue_intent"]["send_allowed"] is False
    else:
        assert "quality_gate_manifest" not in output
        assert output["draft_requires_review"] is True
        assert output["publication_state"] == "BLOCKED"


@pytest.mark.parametrize("transport_first", [True, False])
def test_transport_and_consistency_share_two_review_calls(db, monkeypatch, transport_first):
    review = contradiction()
    request = {"artifact_sha256": review["artifact_sha256"], "artifact": {"body": "Unchanged"}}
    calls = []

    def complete(*args, **kwargs):
        calls.append(kwargs)
        if (len(calls) == 1) == transport_first:
            raise processing.GrowthRegistryError("DeepSeek request failed: JSONDecodeError")
        return SimpleNamespace(content=json.dumps(review))

    monkeypatch.setattr(processing, "complete_json", complete)
    expected = ValueError if transport_first else processing.GrowthRegistryError
    with pytest.raises(expected):
        processing._complete_content_review(db, user_prompt=json.dumps(request))
    assert len(calls) == 2
