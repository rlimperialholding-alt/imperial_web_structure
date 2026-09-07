"""Offline subprocess checks; never reads a provider key or calls the network."""

from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_content_factory_live_model.py"
PLATFORM = ROOT / "services" / "platform-core"

# Reuse the checked full-pipeline fake instead of inventing a second article.
# AST extraction avoids importing the application's pytest fixture/production DB.
BOOTSTRAP = r"""
import ast, json, os, runpy, sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
script, platform, mode = sys.argv[1:]
namespace = runpy.run_path(script)
tree = ast.parse((Path(platform)/"tests/test_content_revenue_integration.py").read_text(encoding="utf-8"))
test = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
    and node.name == "test_source_bound_content_passes_existing_review_and_keeps_delivery_separate")
fake = next(node for node in test.body if isinstance(node, ast.FunctionDef) and node.name == "complete")
fake_globals = {"json":json, "SimpleNamespace":SimpleNamespace, "generated_inputs":[]}
exec(compile(ast.Module(body=[fake], type_ignores=[]), "checked_pipeline_stub", "exec"), fake_globals)
original_fake = fake_globals["complete"]
def complete(db, **kwargs):
    assert os.environ["DATABASE_URL"].startswith("sqlite:///")
    assert "DATABASE_PASSWORD_FILE" not in os.environ
    assert "CONTENT_EXPERT_REVIEW_SECRET" not in os.environ
    if mode == "send_attempt":
        from app.growth_ops import processing
        processing.submit_job(db)
    if mode == "network_attempt":
        import httpx
        httpx.get("https://example.invalid/never-requested")
    if mode == "provider_failure":
        raise RuntimeError("FAKE_SECRET_MUST_NOT_BE_EXPORTED")
    if mode == "radar_problem":
        prompt = json.loads(kwargs["user_prompt"])
        intent = prompt["revenue_intent"]
        assert intent["radar_topic_id"] == "QRT-TRIAL-ORIGINAL-MUNKADIJAK"
        assert "20 m2" not in intent["buyer_problem"]
        assert "laminált padló" in intent["buyer_problem"]
        assert intent["brand_id"] == "BauFreund"
        raise RuntimeError("bounded_after_checked_real_radar_input")
    result = original_fake(db, **kwargs)
    if mode == "review_failure" and "release_review" in kwargs["purpose"]:
        result.content = json.dumps({"artifact_sha256":json.loads(kwargs["user_prompt"])["artifact_sha256"],
                                    "overall_decision":"BLOCK", "findings":["Offline rejection"]})
    return result
os.environ["DATABASE_URL"]="postgresql://this-production-database-must-never-be-used.invalid/prod"
os.environ["DATABASE_PASSWORD_FILE"]="/never/read/production/database/password"
os.environ["CONTENT_EXPERT_REVIEW_SECRET"]="FAKE_SECRET_MUST_NOT_BE_EXPORTED"
report=namespace["run_trial"](Path(platform), model_client=complete,
    now=datetime(2026,9,7,8,0,tzinfo=UTC), max_calls=1 if mode=="call_limit" else 6,
    brand_id="BauFreund" if mode=="radar_problem" else "Property360",
    radar_fixture=(Path(platform)/"tests/fixtures/forum_real_sources/reddit_lakokozosseg.atom") if mode=="radar_problem" else None)
print(json.dumps(report,ensure_ascii=True))
"""


def replay(mode: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", BOOTSTRAP, str(SCRIPT), str(PLATFORM), mode],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "FAKE_SECRET_MUST_NOT_BE_EXPORTED" not in result.stdout
    return json.loads(result.stdout)


def test_real_pipeline_with_offline_stub_isolated_and_marked():
    report = replay("success")
    assert report["status"] == "passed", report
    assert report["mode"] == "offline_test_double"
    assert len(report["obligations"]) == 1
    output = report["obligations"][0]["output"]
    assert output["brand_id"] == "Property360"
    assert output["revenue_intent"]["approved_brand_facts"]
    assert output["revenue_intent"]["send_allowed"] is False
    assert len(report["model_calls"]) == 2
    assert all(call["actual_output"] for call in report["model_calls"])
    assert report["provider_responses"] == []
    assert all(source["brand_id"] == "Property360" for source in report["sources"])
    assert {source["version"] for source in report["sources"]} == {"2026-09-07.v1"}
    assert report["temporary_database_removed"] is True
    assert report["production_database_used"] is False
    assert (
        report["external_sends"]
        == report["publications"]
        == report["enqueue_calls"]
        == 0
    )
    assert all(count == 0 for count in report["delivery_database_rows"].values())
    assert report["obligations"][0]["trial_signature_present"]
    assert "hmac_sha256" not in output["quality_gate_manifest"]


@pytest.mark.parametrize(
    "mode",
    [
        "review_failure",
        "send_attempt",
        "network_attempt",
        "provider_failure",
        "call_limit",
    ],
)
def test_failures_never_become_passed_or_send(mode):
    report = replay(mode)
    assert report["status"] == "failed", report
    assert report["temporary_database_removed"] is True
    assert report["external_sends"] == report["publications"] == 0
    assert not any(report["delivery_database_rows"].values())
    if mode in {"send_attempt", "network_attempt"}:
        assert report["forbidden_action_attempts"]


def test_cli_has_no_stub_switch():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert "--stub" not in result.stdout
    assert "--local-stub" not in result.stdout


def test_real_radar_replay_reaches_correct_brand_generator_without_delivery():
    report = replay("radar_problem")
    assert report["source_mode"] == "anonymized_original_source_replay"
    assert report["radar_replay"]["source_revalidation_calls"] == 1
    assert report["radar_replay"]["published_at_raw"] == "2026-09-06T09:45:34+00:00"
    assert "20 m2" in report["radar_replay"]["original_problem"]
    assert report["model_calls"]
    assert {row.get("error_type") for row in report["model_calls"]} == {"RuntimeError"}
    assert not report["forbidden_action_attempts"]
    assert not any(report["delivery_database_rows"].values())
    assert report["temporary_database_removed"] is True


def test_provider_diagnostic_captures_malformed_final_json_without_reasoning_or_headers():
    diagnose = runpy.run_path(str(SCRIPT))["_provider_response_diagnostics"]
    final_text = '{"overall_decision":"PASS",'
    result = diagnose(
        {
            "id": "provider-id",
            "model": "deepseek-v4-pro",
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {
                        "content": final_text,
                        "reasoning_content": "DO_NOT_EXPORT_REASONING",
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 1500,
                "completion_tokens": 3500,
                "total_tokens": 5000,
                "other_field": "DO_NOT_EXPORT_AUTH",
            },
            "headers": {"Authorization": "DO_NOT_EXPORT_AUTH"},
        }
    )
    assert result["message_content"] == final_text
    assert result["finish_reason"] == "length"
    assert result["message_content_chars"] == len(final_text)
    assert (
        result["message_content_sha256"]
        == hashlib.sha256(final_text.encode()).hexdigest()
    )
    assert result["usage"] == {
        "prompt_tokens": 1500,
        "completion_tokens": 3500,
        "total_tokens": 5000,
    }
    assert "DO_NOT_EXPORT" not in json.dumps(result)


def test_provider_diagnostic_bounds_unicode_copy_but_hashes_full_content():
    diagnose = runpy.run_path(str(SCRIPT))["_provider_response_diagnostics"]
    final_text = "árvíztűrő " * 2000
    result = diagnose(
        {"choices": [{"message": {"content": final_text}, "finish_reason": "stop"}]}
    )
    assert len(result["message_content"]) == 16000
    assert result["message_content_chars"] == len(final_text)
    assert result["message_content_truncated"] is True
    assert (
        result["message_content_sha256"]
        == hashlib.sha256(final_text.encode()).hexdigest()
    )


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"message": {"content": None}}]},
    ],
)
def test_provider_diagnostic_handles_empty_final_content(data):
    diagnose = runpy.run_path(str(SCRIPT))["_provider_response_diagnostics"]
    result = diagnose(data)
    assert result["message_content_chars"] == 0
    assert result["message_content"] == ""
    assert result["message_content_truncated"] is False


@pytest.mark.parametrize("brand", ["Property360", "RED Property", "Venture Studio", "Bautica"])
def test_model_purposes_are_scoped_to_exact_selected_brand(brand):
    module = runpy.run_path(str(SCRIPT))
    purposes = module["_allowed_model_purposes"](brand)
    assert len(purposes) == 3
    assert all(purpose.endswith(":" + brand) for purpose in purposes)
    assert all(purpose.startswith("canonical_daily_content_") for purpose in purposes)


def test_unknown_brand_cannot_start_a_model_trial():
    module = runpy.run_path(str(SCRIPT))
    with pytest.raises(module["TrialIsolationError"], match="unsupported_trial_brand"):
        module["_allowed_model_purposes"]("Not a registered brand")
