"""The real provider's copy shape must reach repair/review without model-owned facts."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.growth_ops import processing
from app.growth_ops.models import DailyContentObligation, QuestionRadarTopic

NOW = datetime(2026, 9, 7, 8, tzinfo=UTC)
RECORDED = Path(__file__).parent / "fixtures" / "content_factory_live_model_20260907.json"


def _copy_only(intent):
    return {
        "title": "Telek, házterv és finanszírozás: együtt tervezd",
        "body": (
            intent["buyer_problem"]
            + " "
            + intent["approved_brand_facts"][0]["payload"]["statement"]
            + "\n\n"
            "A telek kiválasztásakor a háztervet és a finanszírozást együtt érdemes "
            "vizsgálni. A megvásárolható telek még nem bizonyítja, hogy a kiválasztott "
            "ház a tervezett feltételekkel megépíthető. A beépíthetőség, a közművek és "
            "a megközelítés tisztázása ezért az ajánlatok összehasonlításának része.\n\n"
            "Készíts listát a ház kivitelezéséről, a helyszíni munkákról és a költözésig "
            "felmerülő feladatokról. Minden tételnél jelöld, hogy szerepel-e az ajánlatban, "
            "külön becslésre vár, vagy még hiányzik hozzá egy terv. A finanszírozásnál "
            "azt is tisztázd, melyik munkát mikor kell kifizetni.\n\n"
            "A Property360 nézőpontjában a telek, a ház és a finanszírozás összehangolása "
            "adja az ingatlanos ügyfélút alapját. A következő egyeztetésre ezért a telek "
            "adatait, a házzal kapcsolatos elképzeléseidet és a még nyitott kérdéseidet "
            "vidd magaddal. Így az elővizsgálat a tényleges döntési pontokkal kezdődhet."
        ),
        "facebook_post": (
            "A telek ára csak a projekt egyik tétele. A házterv, a közművek, a "
            "helyszíni munkák és a finanszírozás együtt határozzák meg, milyen "
            "döntések várnak rád a költözésig. Írd össze, mi szerepel már az "
            "ajánlatban, mi vár külön becslésre, és mihez hiányzik terv. A "
            "Property360 ingatlanos ügyfélútja a telek és a ház összehangolására "
            "épül. Indulj telek–ház elővizsgálattal! #telek #házterv #finanszírozás"
        ),
        "cta": {"label": intent["next_step"], "intent": "lead"},
    }


def _review(request):
    return {
        "artifact_sha256": request["artifact_sha256"],
        "overall_decision": "PASS",
        "gate_results": {
            gate: {"decision": "PASS", "reason": "Offline test reviewer"}
            for gate in request["required_gate_ids"]
        },
        "scores": dict.fromkeys(
            ("natural_hungarian", "brand_distinctiveness", "conversion_strength", "claim_safety"),
            90,
        ),
        "findings": [],
    }


def _run(db, monkeypatch, generator, *, reviewer=None, revenue_enabled=True):
    calls = []
    monkeypatch.setattr(
        processing,
        "settings",
        lambda: SimpleNamespace(
            timezone="Europe/Budapest",
            canonical_content_factory_enabled=True,
            canonical_revenue_policy_enabled=revenue_enabled,
        ),
    )
    monkeypatch.setattr(processing, "ACTIVE_CONTENT_BRANDS", ("Property360",))
    monkeypatch.setattr(processing, "_quality_release_secret", lambda: b"q" * 32)
    monkeypatch.setattr(processing, "submit_job", lambda *a, **kw: pytest.fail("No publication"))

    def complete(*_args, **kwargs):
        request = json.loads(kwargs["user_prompt"])
        calls.append((kwargs["purpose"], request))
        payload = (
            (reviewer or _review)(request)
            if "release_review" in kwargs["purpose"]
            else generator(request)
        )
        return SimpleNamespace(
            request_id=f"TEST-{len(calls)}",
            model="offline-test-double",
            content=json.dumps(payload),
        )

    monkeypatch.setattr(processing, "complete_json", complete)
    result = processing.generate_daily_content(db, now=NOW)
    row = db.scalar(select(DailyContentObligation))
    return result, row, calls


def test_copy_only_output_binds_trusted_brief_and_reaches_existing_reviewer(db, monkeypatch):
    def generate(request):
        assert "article_body_chars" not in request["requirements"]
        assert request["requirements"]["body_chars"] == "900-1600"
        schema = request["schema"]["properties"]["package"]
        assert set(schema["properties"]) == {"title", "body", "facebook_post", "cta"}
        assert "revenue_intent" not in schema["properties"]
        assert request["requirements"]["body_must_include"]
        return {"package": _copy_only(request["revenue_intent"])}

    result, row, calls = _run(db, monkeypatch, generate)
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 2
    output = json.loads(row.evidence_json)
    assert output["revenue_intent"] == calls[0][1]["revenue_intent"]
    assert output["source_urls"] == output["revenue_intent"]["source_refs"]
    assert output["revenue_intent"]["send_allowed"] is False
    assert output["generator_output_issues"] == []
    assert processing._revenue_package_errors(output, output["revenue_intent"]) == []


def test_recorded_real_response_is_repaired_once_then_independently_reviewed(db, monkeypatch):
    recorded = json.loads(RECORDED.read_text(encoding="utf-8"))["model_output"]

    def generate(request):
        if "repair_round" not in request:
            return deepcopy(recorded)
        assert request["repair_round"] == 1
        assert "model_revenue_metadata_untrusted" in request["gate_errors"]
        assert "buyer_problem_missing_from_copy" not in request["gate_errors"]
        assert "approved_brand_fact_missing_from_copy" not in request["gate_errors"]
        for required in processing._required_copy_spans(request["trusted_revenue_intent"]):
            body = processing._norm(request["blocked_package"]["body"])
            assert processing._norm(required) in body
        assert "revenue_intent" not in request["blocked_package"]
        assert len(request["blocked_package"]["body"]) >= 600
        assert (
            request["blocked_package"]["cta"]["label"]
            == request["trusted_revenue_intent"]["next_step"]
        )
        return {"package": _copy_only(request["trusted_revenue_intent"])}

    result, row, calls = _run(db, monkeypatch, generate)
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 3
    output = json.loads(row.evidence_json)
    assert "model_revenue_metadata_untrusted" in output["generator_output_issues"]
    assert output["quality_gate_manifest"]["repair_request_id"] == "TEST-2"
    assert output["quality_gate_manifest"]["review_request_id"] == "TEST-3"


@pytest.mark.parametrize("forgery", ["intent", "source", "permission", "cta"])
def test_repeated_forged_metadata_never_passes_or_reaches_reviewer(db, monkeypatch, forgery):
    def generate(request):
        intent = request.get("revenue_intent") or request["trusted_revenue_intent"]
        package = _copy_only(intent)
        if forgery == "intent":
            package["revenue_intent"] = dict(intent, publication_allowed=True)
        elif forgery == "source":
            package["source_urls"] = ["https://unapproved.example/invented-proof"]
        elif forgery == "permission":
            package["quality_gate_manifest"] = {"decision": "PASS"}
        else:
            package["cta"] = "Fizess elő egy nem jóváhagyott szolgáltatásra!"
        return {"package": package}

    result, row, calls = _run(db, monkeypatch, generate)
    assert result["generated"] == 0
    assert row.status == "failed"
    assert len(calls) == 3  # initial draft + at most two repairs
    assert not any("release_review" in purpose for purpose, _ in calls)
    assert "source_bound_content_repair_failed" in row.evidence_json


@pytest.mark.parametrize("location", ["package", "envelope", "repair"])
def test_explicit_other_brand_is_never_relabelled(db, monkeypatch, location):
    def generate(request):
        intent = request.get("revenue_intent") or request["trusted_revenue_intent"]
        package = _copy_only(intent)
        if location == "repair" and "repair_round" not in request:
            package["body"] = "Hiányos cikk."
            return {"package": package}
        if location == "envelope":
            return {"brand_id": "RED Property", "package": package}
        return {"package": dict(package, brand_id="RED Property")}

    result, row, calls = _run(db, monkeypatch, generate)
    assert result["generated"] == 0
    assert "model_brand_mismatch" in row.evidence_json
    assert not any("release_review" in purpose for purpose, _ in calls)
    assert len(calls) == (2 if location == "repair" else 1)


def test_alias_and_approved_cta_string_keep_actual_text_and_do_not_modify_input(db):
    intent = processing._prepare_content_revenue_intent(
        [],
        processing._approved_brand_facts(db, "Property360", current=NOW),
        brand_id="Property360",
        now=NOW,
    )
    response = _copy_only(intent)
    response["article_body"] = response.pop("body")
    response["cta"] = intent["next_step"]
    original = deepcopy(response)
    output, errors = processing._normalize_generated_content_package(
        response,
        brand_id="Property360",
        revenue_intent=intent,
    )
    assert errors == []
    assert output["body"] == original["article_body"]
    assert output["cta"] == {"label": intent["next_step"], "intent": "lead"}
    assert response == original
    output["revenue_intent"]["buyer_problem"] = "Changed output"
    assert intent["buyer_problem"] != "Changed output"


def test_metadata_or_social_post_cannot_replace_problem_and_fact_in_article(db):
    intent = processing._prepare_content_revenue_intent(
        [],
        processing._approved_brand_facts(db, "Property360", current=NOW),
        brand_id="Property360",
        now=NOW,
    )
    output = _copy_only(intent)
    output["revenue_intent"] = intent
    output["facebook_post"] = output["body"]
    output["body"] = "Tartalmatlan, általános cikk."
    errors = processing._revenue_package_errors(output, intent)
    assert "buyer_problem_missing_from_copy" in errors
    assert "approved_brand_fact_missing_from_copy" in errors


@pytest.mark.parametrize(
    "question",
    [
        "Padlás szigetelés: Kell-e párazáró?",
        "Padlas szigeteles: Kell-e parazaro?",
    ],
)
def test_real_reddit_attic_question_is_retained(question):
    assert processing._useful_forum_question(question)
    assert not processing._useful_forum_question("Párazáró fólia termékadatlap")


@pytest.mark.parametrize("needs_repair", [False, True])
def test_legacy_mode_keeps_same_brand_evidence_without_model_source_metadata(
    db, monkeypatch, needs_repair
):
    intent = processing._prepare_content_revenue_intent(
        [],
        processing._approved_brand_facts(db, "Property360", current=NOW),
        brand_id="Property360",
        now=NOW,
    )
    trusted_url = "https://forum.example.test/post/property-telek"
    for number, (brand, question, url) in enumerate(
        (
            (
                "Property360",
                "Hogyan hangoljam össze a telek és a ház finanszírozását?",
                trusted_url,
            ),
            (
                "RED Property",
                "Hogyan hangoljam össze a telek és a ház finanszírozását?",
                "https://forum.example.test/post/red",
            ),
            (
                "Property360",
                "Mi legyen a palacsintában?",
                "https://forum.example.test/post/unrelated",
            ),
        ),
        start=1,
    ):
        db.add(
            QuestionRadarTopic(
                topic_id=f"LEGACY-FACT-{number}",
                local_date=NOW.date(),
                brand_id=brand,
                question=question,
                source_url=url,
                classification="observed_literal",
                use_case="source_observed_question",
                dedupe_hash=str(number) * 64,
                published_at=NOW,
                active_status="active",
                existing_answer_count=0,
            )
        )
    db.commit()

    def generate(request):
        if "repair_round" not in request:
            assert request["revenue_intent"] is None
            assert [item["source_url"] for item in request["evidence"]["questions"]] == [
                trusted_url
            ]
        package = _copy_only(intent)
        if needs_repair and "repair_round" not in request:
            package["body"] = "Rövid, még javítandó cikk."
        # An invented URL is not a source permission, even in legacy mode.
        package["source_urls"] = ["https://unapproved.example/invented-proof"]
        return {"package": package}

    result, row, calls = _run(db, monkeypatch, generate, revenue_enabled=False)
    assert result["generated"] == 1, row.evidence_json
    output = json.loads(row.evidence_json)
    assert output["source_urls"] == [trusted_url]
    assert calls[-1][1]["artifact"]["source_urls"] == [trusted_url]
    assert len(calls) == (3 if needs_repair else 2)


def test_review_invalid_json_retries_once_with_the_same_artifact_and_prompt(db, monkeypatch):
    reviews = []

    def review(request):
        reviews.append(deepcopy(request))
        if len(reviews) == 1:
            try:
                json.loads('{"overall_decision":')
            except json.JSONDecodeError as exc:
                raise processing.GrowthRegistryError(
                    "DeepSeek request failed: JSONDecodeError"
                ) from exc
        return _review(request)

    result, row, calls = _run(
        db,
        monkeypatch,
        lambda request: {"package": _copy_only(request["revenue_intent"])},
        reviewer=review,
    )
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 3
    assert len(reviews) == 2 and reviews[0] == reviews[1]
    manifest = json.loads(row.evidence_json)["quality_gate_manifest"]
    assert manifest["artifact_sha256"] == reviews[0]["artifact_sha256"]
    assert manifest["generator_request_id"] == "TEST-1"
    assert manifest["review_request_id"] == "TEST-3"


@pytest.mark.parametrize(
    "error",
    [
        "DeepSeek monthly budget exhausted",
        "DeepSeek request failed: GrowthRegistryError",
    ],
)
def test_review_budget_or_credential_error_is_not_retried_and_draft_is_preserved(
    db, monkeypatch, error
):
    def review(_request):
        raise processing.GrowthRegistryError(error)

    result, row, calls = _run(
        db,
        monkeypatch,
        lambda request: {"package": _copy_only(request["revenue_intent"])},
        reviewer=review,
    )
    assert result["generated"] == 0
    assert len(calls) == 2
    evidence = json.loads(row.evidence_json)
    draft = evidence["review_pending_draft"]
    assert draft["body"] and draft["source_urls"]
    assert processing._sha(processing._quality_artifact(draft)) == evidence["artifact_sha256"]
    assert evidence["draft_requires_review"] is True
    assert row.status == "failed" and row.content_asset_id is None
    assert "publication_state" not in draft and "quality_gate_manifest" not in draft
    assert draft["revenue_intent"]["publication_allowed"] is False


def test_reviewer_content_block_is_not_a_technical_retry(db, monkeypatch):
    def review(request):
        response = dict(_review(request), overall_decision="BLOCK", findings=["Unverified content"])
        response["gate_results"]["claim_coverage"] = {
            "decision": "BLOCK", "reason": "Unverified content",
        }
        return response

    result, row, calls = _run(
        db,
        monkeypatch,
        lambda request: {"package": _copy_only(
            request.get("revenue_intent") or request["trusted_revenue_intent"],
        )},
        reviewer=review,
    )
    assert result["generated"] == 0
    assert len(calls) == 4  # One review BLOCK and two bounded copy repairs, not review retries.
    assert sum("release_review" in purpose for purpose, _ in calls) == 1
    assert "review_content_repair_unchanged" in row.evidence_json
    assert json.loads(row.evidence_json)["review_pending_draft"]["body"]


def test_repeated_review_transport_failure_stops_after_two_calls(db, monkeypatch):
    def review(_request):
        raise processing.GrowthRegistryError("DeepSeek request failed: ReadTimeout")

    result, row, calls = _run(
        db,
        monkeypatch,
        lambda request: {"package": _copy_only(request["revenue_intent"])},
        reviewer=review,
    )
    assert result["generated"] == 0
    assert len(calls) == 3
    assert json.loads(row.evidence_json)["review_pending_draft"]["body"]


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_review_http_retry_distinguishes_transient_status_from_auth(monkeypatch, status):
    requests = []
    completed_result = SimpleNamespace(content=json.dumps({"overall_decision": "PASS"}))

    def complete(_db, **kwargs):
        requests.append(dict(kwargs))
        if len(requests) == 1:
            response = httpx.Response(
                status, request=httpx.Request("POST", "https://api.deepseek.com/chat/completions")
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise processing.GrowthRegistryError(
                    "DeepSeek request failed: HTTPStatusError"
                ) from exc
        return completed_result

    monkeypatch.setattr(processing, "complete_json", complete)
    kwargs = {"user_prompt": '{"artifact_sha256":"fixed-hash"}', "system_prompt": "unchanged"}
    if status in {401, 403}:
        with pytest.raises(processing.GrowthRegistryError):
            processing._complete_content_review(None, **kwargs)
        assert len(requests) == 1
    else:
        assert processing._complete_content_review(None, **kwargs) is completed_result
        assert requests == [kwargs, kwargs]


def test_new_contract_version_gets_three_bounded_attempts_after_old_version_exhausted(
    db, monkeypatch
):
    db.add(
        DailyContentObligation(
            local_date=NOW.date(),
            brand_id="Property360",
            status="failed",
            evidence_json=json.dumps(
                {"attempts": 3, "repair_version": "20260907-model-contract-v8"}
            ),
            updated_at=NOW,
        )
    )
    db.commit()

    def review(_request):
        raise processing.GrowthRegistryError("DeepSeek monthly budget exhausted")

    result, row, calls = _run(
        db,
        monkeypatch,
        lambda request: {"package": _copy_only(request["revenue_intent"])},
        reviewer=review,
    )
    assert result["failed"] == 1
    assert json.loads(row.evidence_json)["attempts"] == 1
    assert processing.CONTENT_FACTORY_REPAIR_VERSION == "20260907-model-contract-v9"
    for attempt in (2, 3):
        row.updated_at = NOW + timedelta(minutes=(attempt - 2) * 6)
        db.commit()
        result = processing.generate_daily_content(
            db, now=NOW + timedelta(minutes=(attempt - 1) * 6)
        )
        assert result["failed"] == 1
        assert json.loads(row.evidence_json)["attempts"] == attempt
    result = processing.generate_daily_content(db, now=NOW + timedelta(minutes=18))
    assert result["generated"] == result["failed"] == 0
    assert len(calls) == 6  # exactly three generations and three non-retried reviews
