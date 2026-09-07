"""Preserve real language judgments; recheck explicit self-contradictions once."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_content_model_output_contract as harness

from app.growth_ops import processing

FIXTURE = Path(__file__).parent / "fixtures/content_factory_v11_review_contradiction_20260907.json"


def recorded():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["review"]


def test_recorded_self_contradiction_is_not_silently_approved():
    review = recorded()
    before = deepcopy(review)
    assert processing._review_decision_contradiction(
        review, {"artifact_sha256": review["artifact_sha256"]},
    )
    assert review == before
    assert review["overall_decision"] == "BLOCK"
    assert review["gate_results"]["natural_hungarian"]["decision"] == "BLOCK"


@pytest.mark.parametrize("mutation", [
    "real_grammar_objection", "no_self_correction", "other_block", "low_score",
    "wrong_hash", "missing_gate", "extra_gate", "invalid_score", "extra_root",
])
def test_objections_or_invalid_metadata_do_not_get_a_consistency_retry(monkeypatch, mutation):
    review = recorded()
    request = {"artifact_sha256": review["artifact_sha256"]}
    if mutation == "real_grammar_objection":
        review["gate_results"]["natural_hungarian"]["reason"] = "A birtokos személyrag hibás."
    elif mutation == "no_self_correction":
        review["findings"] = ["A hangvétel személytelen, konkrétabb megfogalmazás szükséges."]
    elif mutation == "other_block":
        review["gate_results"]["claim_coverage"] = {
            "decision": "BLOCK", "reason": "Igazolatlan ár.",
        }
    elif mutation == "low_score":
        review["scores"]["natural_hungarian"] = 79
    elif mutation == "wrong_hash":
        review["artifact_sha256"] = "b" * 64
    elif mutation == "missing_gate":
        review["gate_results"].pop("conversion")
    elif mutation == "extra_gate":
        review["gate_results"]["extra"] = {"decision": "PASS", "reason": "Extra"}
    elif mutation == "invalid_score":
        review["scores"]["natural_hungarian"] = True
    else:
        review["override"] = True
    calls = []

    def complete(*_args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=json.dumps(review))

    monkeypatch.setattr(processing, "complete_json", complete)
    assert not processing._review_decision_contradiction(review, request)
    result = processing._complete_content_review(None, user_prompt=json.dumps(request))
    assert json.loads(result.content) == review
    assert len(calls) == 1


@pytest.mark.parametrize("second", ["pass", "valid_block", "contradiction", "tampered_hash"])
def test_same_artifact_is_rechecked_and_only_new_valid_pass_can_be_signed(db, monkeypatch, second):
    requests = []

    def reviewer(request):
        requests.append(deepcopy(request))
        response = recorded()
        response["artifact_sha256"] = request["artifact_sha256"]
        if len(requests) == 1:
            return response
        for key in ("artifact", "artifact_sha256", "source_evidence", "trusted_revenue_intent"):
            assert request[key] == requests[0][key]
        old_review = request["review_consistency_recheck"]["previous_review"]
        assert old_review["overall_decision"] == "BLOCK"
        assert old_review["findings"] == recorded()["findings"]
        assert "nem PASS-t kérünk" in request["review_consistency_recheck"]["instruction_hu"]
        if second == "pass":
            return harness._review(request)
        if second == "valid_block":
            response["gate_results"]["natural_hungarian"]["reason"] = "Hibás személyrag."
            response["findings"] = ["A birtokos személyragot javítani kell."]
        elif second == "tampered_hash":
            response = harness._review(request)
            response["artifact_sha256"] = "b" * 64
        return response

    result, row, calls = harness._run(
        db, monkeypatch,
        lambda request: {"package": harness._copy_only(
            request.get("revenue_intent") or request["trusted_revenue_intent"],
        )},
        reviewer=reviewer,
    )
    assert len(requests) == 2
    assert sum("release_review" in purpose for purpose, _ in calls) == 2
    evidence = json.loads(row.evidence_json)
    assert result["generated"] == (1 if second == "pass" else 0), row.evidence_json
    if second == "pass":
        assert evidence["quality_gate_manifest"]["review_request_id"] == "TEST-3"
        assert (
            evidence["quality_gate_manifest"]["artifact_sha256"] == requests[0]["artifact_sha256"]
        )
        assert evidence["content_repair_attempts"] == 0
        assert evidence["revenue_intent"]["publication_allowed"] is False
        assert evidence["revenue_intent"]["send_allowed"] is False
    else:
        assert "quality_gate_manifest" not in evidence
        assert evidence["review_pending_draft"]["body"]
        assert row.content_asset_id is None


@pytest.mark.parametrize("transport_first", [False, True])
def test_transport_and_self_contradiction_share_existing_two_call_limit(
    monkeypatch, transport_first,
):
    review = recorded()
    calls = []

    def complete(*_args, **kwargs):
        calls.append(kwargs)
        if (len(calls) == 1) == transport_first:
            raise processing.GrowthRegistryError("DeepSeek request failed: ReadTimeout")
        return SimpleNamespace(content=json.dumps(review))

    monkeypatch.setattr(processing, "complete_json", complete)
    expected = ValueError if transport_first else processing.GrowthRegistryError
    with pytest.raises(expected):
        processing._complete_content_review(
            None, user_prompt=json.dumps({"artifact_sha256": review["artifact_sha256"]}),
        )
    assert len(calls) == 2
