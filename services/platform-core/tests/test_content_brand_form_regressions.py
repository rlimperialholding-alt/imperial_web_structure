"""Replay public provider copy: formatting must not consume content repair calls."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_content_model_output_contract import NOW, _review

from app.growth_ops import processing
from app.growth_ops.models import DailyContentObligation

FIXTURES = Path(__file__).parent / "fixtures"


def recorded(brand, *, radar=False):
    records = json.loads(
        (FIXTURES / "content_factory_brand_form_failures_20260907.json").read_text("utf-8")
    )
    return next(
        row
        for row in records
        if row["brand_id"] == brand and (brand != "BauFreund" or (len(row["calls"]) > 1) == radar)
    )


def intent_for(db, brand):
    return processing._prepare_content_revenue_intent(
        [],
        processing._approved_brand_facts(db, brand, current=NOW),
        brand_id=brand,
        now=NOW,
    )


def run_brand(db, monkeypatch, brand, generate):
    calls = []
    monkeypatch.setattr(
        processing,
        "settings",
        lambda: SimpleNamespace(
            timezone="Europe/Budapest",
            canonical_content_factory_enabled=True,
            canonical_revenue_policy_enabled=True,
        ),
    )
    monkeypatch.setattr(processing, "ACTIVE_CONTENT_BRANDS", (brand,))
    monkeypatch.setattr(processing, "_quality_release_secret", lambda: b"r" * 32)
    monkeypatch.setattr(processing, "submit_job", lambda *a, **kw: pytest.fail("No publication"))

    def complete(*args, **kwargs):
        request = json.loads(kwargs["user_prompt"])
        calls.append(dict(kwargs, request=request))
        response = (
            _review(request)
            if "release_review" in kwargs["purpose"]
            else generate(request, kwargs["system_prompt"])
        )
        return SimpleNamespace(
            request_id=f"OFFLINE-{len(calls)}", model="offline-test", content=json.dumps(response)
        )

    monkeypatch.setattr(processing, "complete_json", complete)
    result = processing.generate_daily_content(db, now=NOW)
    return result, db.scalar(select(DailyContentObligation)), calls


def test_recorded_red_missing_hashtags_reaches_review_without_generation_retry(db, monkeypatch):
    response = deepcopy(recorded("RED Property")["calls"][-1]["output"])
    # This test isolates missing hashtag formatting. The original unsupported
    # outcome promise is independently covered by the actual V8 claim fixtures.
    response["package"]["body"] = response["package"]["body"].replace(
        "Így nem érhet meglepetés.",
        "Így előre tisztázhatod a műszaki tartalommal kapcsolatos kérdéseket.",
    )
    original = deepcopy(response)

    def generate(request, system):
        assert "végig TEGEZD" in system
        assert request["evidence_policy"].startswith("SOURCE_BOUND")
        assert request["evidence"]["approved_brand_facts"]
        return deepcopy(response)

    result, row, calls = run_brand(db, monkeypatch, "RED Property", generate)
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 2
    assert "release_review" in calls[-1]["purpose"]
    output = json.loads(row.evidence_json)
    old_social = original["package"]["facebook_post"]
    assert output["facebook_post"].startswith(old_social)
    assert output["facebook_post"].endswith("#REDProperty #ingatlanfejlesztés #ingatlan")
    reviewed = calls[-1]["request"]["artifact"]
    assert reviewed["facebook_post"] == output["facebook_post"]
    assert processing._sha(reviewed) == output["quality_gate_manifest"]["artifact_sha256"]
    assert output["revenue_intent"]["send_allowed"] is False
    assert response == original


@pytest.mark.parametrize("existing", ["#Saját", "#Saját #építés", "#Saját #építés #döntés"])
def test_good_existing_hashtags_are_preserved_and_completion_is_idempotent(existing):
    source = {
        "facebook_post": "A konkrét felújítási feladatot érdemes előre tisztázni. " + existing
    }
    output = processing._complete_content_hashtags(
        source, brand_id="Bautica", focus=("felújítás", "építés")
    )
    assert output["facebook_post"].startswith(source["facebook_post"])
    assert (
        processing._complete_content_hashtags(
            output, brand_id="Bautica", focus=("felújítás", "építés")
        )
        == output
    )
    if existing.count("#") == 3:
        assert output == source


def test_hashtag_completion_never_removes_excess_or_unsafe_claims():
    source = {
        "brand_id": "Bautica",
        "facebook_post": "Ingyenes vizsgálat. " + " ".join(f"#tag{i}" for i in range(9)),
    }
    output = processing._complete_content_hashtags(
        source, brand_id="Bautica", focus=("felújítás", "építés")
    )
    assert output == source
    errors = processing._content_repair_errors(
        output, processing.publication_contract_for_brand("Bautica")
    )
    assert "facebook_hashtag_count_invalid" in errors
    assert "unverified_offer_condition" in errors
    assert "unverified_numeric_claim" in errors


def test_generated_hashtags_cannot_make_an_unrelated_recipe_on_brand():
    brand = "Imperial"
    focus = processing.content_focus_for_brand(brand)
    contract = processing.publication_contract_for_brand(brand)
    recipe = {
        "brand_id": brand,
        "title": "A kenyértészta összeállítása",
        "body": ("A kenyértésztát keverjük össze, majd pihentessük. " * 16),
        "facebook_post": ("A kenyértésztát óvatosan keverjük össze, majd hagyjuk pihenni. " * 4),
        "cta": {"label": "Írja össze a hozzávalókat.", "intent": "lead"},
    }
    completed = processing._complete_content_hashtags(recipe, brand_id=brand, focus=focus)
    assert "#Imperial" in completed["facebook_post"]
    assert completed["body"] == recipe["body"]
    assert "off_brand_topic" in processing._content_candidate_errors(
        completed, brand_id=brand, focus=focus, contract=contract, revenue_intent=None,
    )
    assert processing._content_topic_text(completed) == processing._content_topic_text(recipe)
    meaningful = dict(completed, title="Az építkezés előkészítésének döntési pontjai")
    assert "off_brand_topic" not in processing._content_candidate_errors(
        meaningful, brand_id=brand, focus=focus, contract=contract, revenue_intent=None,
    )


@pytest.mark.parametrize(
    "text",
    [
        "Az építési döntések előkészítése a kivitelezés része.",
        "Az építés során a terveket és a helyszíni adottságokat együtt érdemes vizsgálni.",
        "Az építés tudománya.",
    ],
)
def test_optional_bautica_slogan_does_not_reject_normal_professional_sentences(text):
    assert not processing._locked_slogan_modified(text, "Az építés tudománya.", "Bautica")


@pytest.mark.parametrize(
    "text",
    [
        "Az építés tudománya!",
        "Az építés új tudománya.",
        "Bautica – Az építés művészete.",
        "Szlogen: Az építés művészete.",
        "Az építés tudománya. Az építés új tudománya.",
    ],
)
def test_actual_modified_slogan_still_fails(text):
    assert processing._locked_slogan_modified(text, "Az építés tudománya.", "Bautica")


@pytest.mark.parametrize("brand", ["Bautica", "Prefab"])
def test_real_informal_formal_brand_copy_is_repaired_with_explicit_voice(db, monkeypatch, brand):
    response = recorded(brand)["calls"][-1]["output"]
    contract = processing.publication_contract_for_brand(brand)
    package, _ = processing._normalize_generated_content_package(
        response,
        brand_id=brand,
        revenue_intent=intent_for(db, brand),
    )
    errors = processing._deterministic_publication_errors(package, contract)
    assert "brand_address_mode_violation" in errors
    assert "locked_slogan_modified" not in errors

    def generate(request, system):
        assert "végig MAGÁZD" in system
        if "repair_round" not in request:
            return deepcopy(response)
        assert request["repair_round"] == 1
        assert request["evidence_policy"].startswith("SOURCE_BOUND")
        assert request["source_evidence"]["approved_brand_facts"]
        assert any(
            item["error"] == "brand_address_mode_violation" and "MAGÁZD" in item["instruction_hu"]
            for item in request["field_corrections"]
        )
        intent = request["trusted_revenue_intent"]
        body = (
            " ".join(processing._required_copy_spans(intent))
            + "\n\n"
            + (
                "Az építés során a terveket és a helyszíni adottságokat együtt érdemes vizsgálni. "
                "A kivitelezés előkészítésénél tisztázandó, melyik munka szerepel az ajánlatban, "
                "és melyik feladathoz szükséges további adat. A terv és a helyszín összevetése "
                "segít pontosan megfogalmazni a nyitott kérdéseket. "
                "A szerkezeti csatlakozásokat és a kivitelezési határokat érdemes a tervezővel "
                "egyeztetni. Milyen feltételhez kötött az ajánlat műszaki tartalma? "
                "Ki ad választ az eltérő megoldásokkal kapcsolatos kérdésekre? "
                "Az egyeztetésre készítse elő a tervet és a még tisztázatlan feladatok listáját."
            )
        )
        return {
            "package": {
                "title": "Kivitelezés előtt: a terv és az ajánlat összevetése",
                "body": body,
                "facebook_post": body[:700] + " #kivitelezés #terv #előkészítés",
                "cta": {"label": intent["next_step"], "intent": "lead"},
            }
        }

    result, row, calls = run_brand(db, monkeypatch, brand, generate)
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 3


def test_real_invented_prices_get_facebook_and_body_specific_corrections():
    raw = recorded("BauFreund", radar=True)["calls"][0]["output"]["package"]
    package = dict(raw, brand_id="BauFreund")
    contract = processing.publication_contract_for_brand("BauFreund")
    errors = processing._deterministic_publication_errors(package, contract)
    assert "unverified_numeric_claim" in errors
    corrections = processing._content_repair_instructions(package, errors, contract)
    numeric = {
        item["field"]: item for item in corrections if item["error"] == "unverified_numeric_claim"
    }
    assert {"body", "facebook_post"}.issubset(numeric)
    assert "200 ezer" in " ".join(numeric["facebook_post"]["excerpts"])
    assert "600 ezer" in " ".join(numeric["facebook_post"]["excerpts"])
    assert "2 nap" in " ".join(numeric["body"]["excerpts"])
    assert "kötőjeles" in numeric["body"]["instruction_hu"]
    assert "teljes állítását" in numeric["facebook_post"]["instruction_hu"]
    assert "unverified_numeric_claim" in processing._deterministic_publication_errors(
        package, contract
    )


def test_recorded_price_examples_are_repaired_in_both_fields_before_review(db, monkeypatch):
    actual = recorded("BauFreund", radar=True)["calls"][0]["output"]

    def generate(request, system):
        if "repair_round" not in request:
            return deepcopy(actual)
        assert request["repair_round"] == 1
        numeric = {
            item["field"]: item
            for item in request["field_corrections"]
            if item["error"] == "unverified_numeric_claim"
        }
        assert {"body", "facebook_post"}.issubset(numeric)
        assert "field_corrections" in system
        assert "Facebook" in system
        intent = request["trusted_revenue_intent"]
        copy = deepcopy(actual["package"])
        copy["body"] = " ".join(processing._required_copy_spans(intent)) + "\n\n" + (
            "A laminált padlónál nem mindegy, hogy az aljzatot is ki kell-e egyenlíteni, "
            "kell-e párazáró fólia, és mi történik a lábazattal. A festésnél azt is érdemes "
            "tisztázni, hogy glettelésre van-e szükség. Az eltérő árajánlatok mögött eltérő "
            "feladatok is állhatnak. Ezért az ajánlatok tartalmát érdemes összevetni.\n\n"
            "- Mi szerepel pontosan az árban? Kérd el tételesen az anyagot, a munkadíjat, "
            "a kiszállást és az esetleges hulladékszállítást.\n"
            "- Milyen állapotban van most a helyiség? Kérdezd meg, szükséges-e helyszíni "
            "felmérés az ajánlat pontosításához.\n"
            "- Mi alapján áll össze az ütemezés? A határidőt a tervezett feladatokkal "
            "együtt tisztázd, és kérdezz rá az előkészítésre is."
        )
        copy["facebook_post"] = copy["facebook_post"].replace(
            "Laminált padló + festés: az egyik árajánlat 200 ezer, a másik 600 ezer. "
            "Melyik az igazi?",
            "Laminált padló és festés: mi magyarázza az eltérő árajánlatokat?",
        )
        copy["cta"] = {"label": intent["next_step"], "intent": "lead"}
        return {"package": copy}

    result, row, calls = run_brand(db, monkeypatch, "BauFreund", generate)
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 3
    reviewed = calls[-1]["request"]["artifact"]
    assert "200 ezer" not in reviewed["facebook_post"]
    assert "2 nap" not in reviewed["body"]
    assert "- Mi szerepel" in reviewed["body"]
    assert "unverified_numeric_claim" not in processing._deterministic_publication_errors(
        reviewed, processing.publication_contract_for_brand("BauFreund")
    )


def test_short_reviewer_schema_and_recorded_truncation_evidence():
    records = json.loads(
        (FIXTURES / "content_factory_reviewer_failures_20260907.json").read_text("utf-8")
    )
    truncated = [row for row in records if row["brand_id"] == "TimberHaus"]
    assert len(truncated) == 2
    for row in truncated:
        assert row["finish_reason"] == "length"
        assert row["usage"]["completion_tokens"] == 3500
        assert row["message_content_chars"] > 9000
        with pytest.raises(json.JSONDecodeError):
            json.loads(row["recorded_content"])
    request = {"artifact_sha256": "a" * 64, "required_gate_ids": sorted(processing.MANDATORY_GATES)}
    schema = processing._content_review_schema(request["artifact_sha256"])
    review = _review(request)
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(review)
    assert set(schema["properties"]["gate_results"]["properties"]) == set(review["gate_results"])
    assert len(json.dumps(review).encode()) < 3500  # bytes, stricter than a 3500-token budget
    assert "artifact" not in schema["properties"]
    assert "source_evidence" not in schema["properties"]


def test_reviewer_prompt_accepts_standalone_linkless_post_without_overriding_review(
    db, monkeypatch
):
    records = json.loads(
        (FIXTURES / "content_factory_reviewer_failures_20260907.json").read_text("utf-8")
    )
    recorded_danish = next(row for row in records if row["brand_id"] == "Danish Fabrik")
    actual = recorded_danish["model_output"]
    assert "konyhaszekrény" in actual["package"]["facebook_post"].casefold()
    assert "http" not in actual["package"]["facebook_post"]
    result, row, calls = run_brand(
        db, monkeypatch, "Danish Fabrik", lambda request, system: deepcopy(actual)
    )
    assert result["generated"] == 1, row.evidence_json
    review_prompt = calls[-1]["system_prompt"]
    assert "a link hiánya önmagában nem hiba" in review_prompt
    assert "önmagában érthető vevői probléma" in review_prompt
    assert "Nem kell a teljes márkát vagy rendszert bemutatni" in review_prompt
    assert "SOHA ne másold" in review_prompt
    assert "legfeljebb 120 karakteres reason" in review_prompt
    assert calls[-1]["max_tokens"] == 3500
    assert (
        len(calls) == 2
    )  # offline PASS proves the request contract, not actual provider acceptance
