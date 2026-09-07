from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.growth_ops import catalog, processing
from app.growth_ops.models import ContentSourceReplenishmentTask, DailyContentObligation
from app.growth_ops.revenue_policy import (
    SourceReplenishmentRequired,
    assess_signal,
    build_brand_source_intent,
    revalidate_topic_for_use,
)
from app.models import CopySourceRecord

NOW = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "buyer_text",
    [
        "Burkolót keresek a lakásfelújításhoz.",
        "Tudtok megbízható kivitelezőt?",
        "Félbemaradt az építkezésem, a folytatáshoz segítséget keresek.",
    ],
)
def test_actual_service_requests_are_buying_signals(buyer_text):
    result = assess_signal(
        {
            "text": buyer_text,
            "source_url": "https://forum.example.hu/posts/12345",
            "observed_at": NOW,
            "source_scoped": True,
            "permalink_verified": True,
            "timestamp_proof": "post_published",
            "published_at_raw": (NOW - timedelta(hours=6)).isoformat(),
        },
        now=NOW,
    )
    assert result["queue"] == "WARM"
    assert result["contact_allowed"] is False


def _settings():
    return SimpleNamespace(
        timezone="Europe/Budapest",
        canonical_content_factory_enabled=True,
        canonical_revenue_policy_enabled=True,
    )


def _topic(**changes):
    value = {
        "topic_id": "QRT-REPLAY",
        "brand_id": "Property360",
        "question": "Burkolót keresek a lakásfelújításhoz, megvannak a tervek.",
        "source_url": "https://forum.index.hu/Article/viewArticle?a=172254254&t=9004917",
        "published_at": NOW - timedelta(hours=12),
        "published_at_raw": "2026-09-06T20:00:00+00:00",
        "freshness_decision": "HOT",
        "eligibility_status": "eligible",
        "active_status": "active",
        "existing_answer_count": 4,
    }
    value.update(changes)
    return SimpleNamespace(**value)


def test_answered_but_open_question_is_still_content_evidence():
    result = revalidate_topic_for_use(_topic(), now=NOW)
    assert result["eligible"] is True
    assert "already_answered" not in result["reasons"]


def test_old_cached_hot_demand_is_research_at_use_time():
    result = revalidate_topic_for_use(_topic(published_at=NOW - timedelta(days=31)), now=NOW)
    assert result["eligible"] is False
    assert result["demand_decision"]["queue"] == "RESEARCH_ONLY"


def test_refresh_reads_original_again_and_detects_changed_post(monkeypatch):
    calls = []

    def refresh(url):
        calls.append(url)
        return {
            "source_url": url,
            "source_text": "Már találtam kivitelezőt, a kérdés tárgytalan.",
            "published_at_raw": "2026-09-06T20:00:00+00:00",
            "published_at_source": "source_page",
            "active_status": "closed",
        }

    monkeypatch.setattr(catalog, "refresh_question_source", refresh)
    snapshot = processing._refresh_topic_source(_topic(), now=NOW)
    assert calls == [_topic().source_url]
    assert snapshot["error"] == "source_question_changed"
    assert (
        revalidate_topic_for_use(_topic(), now=NOW, source_snapshot=snapshot)["eligible"] is False
    )


@pytest.mark.parametrize("brand", ["Property360", "RED Property", "Venture Studio"])
def test_real_brand_sources_provide_problem_and_supported_next_step(db, brand):
    facts = processing._approved_brand_facts(db, brand, current=NOW)
    assert facts and all(fact["brand_id"] == brand for fact in facts)
    intent = build_brand_source_intent(brand, facts)
    assert intent["input_type"] == "approved_brand_customer_problem"
    assert intent["radar_topic_id"] is None
    assert intent["publication_allowed"] is False and intent["send_allowed"] is False
    assert len(intent["buyer_problem"]) >= 12 and len(intent["next_step"]) >= 8


def test_empty_and_tampered_approved_source_is_not_used(db):
    source = db.scalar(select(CopySourceRecord).where(CopySourceRecord.brand_id == "Property360"))
    assert source
    source.payload_json = '{"statement":"unsupported new capability"}'
    db.flush()
    assert source.source_key not in {
        fact["source_key"]
        for fact in processing._approved_brand_facts(db, "Property360", current=NOW)
    }
    with pytest.raises(SourceReplenishmentRequired):
        build_brand_source_intent("Property360", [{"source_key": "empty", "payload": {}}])


def test_existing_api_json_serialization_remains_usable_and_styles_do_not_hide_facts(db):
    for index in range(45):
        db.add(
            CopySourceRecord(
                source_key=f"p360-style-{index}",
                version="test",
                source_type="style",
                brand_id="Property360",
                priority=1,
                approved=True,
                status="approved",
                source_url="https://example.hu/style",
                content_hash="a" * 64,
                payload_json="{}",
            )
        )
    payload_json = json.dumps(
        {"statement": "Approved API brand fact."}, ensure_ascii=False, sort_keys=True
    )
    db.add(
        CopySourceRecord(
            source_key="p360-api-brand-fact",
            version="test",
            source_type="brand_fact",
            brand_id="Property360",
            priority=2,
            approved=True,
            status="approved",
            source_url="https://example.hu/brand-fact",
            content_hash=hashlib.sha256(payload_json.encode()).hexdigest(),
            payload_json=payload_json,
        )
    )
    db.flush()
    facts = processing._approved_brand_facts(db, "Property360", current=NOW)
    assert "p360-api-brand-fact" in {fact["source_key"] for fact in facts}
    assert not any(fact["source_type"] == "style" for fact in facts)


def test_missing_source_creates_one_task_without_calling_generator(db, monkeypatch):
    monkeypatch.setattr(processing, "settings", _settings)
    monkeypatch.setattr(processing, "ACTIVE_CONTENT_BRANDS", ("Property360",))
    db.execute(delete(CopySourceRecord).where(CopySourceRecord.brand_id == "Property360"))
    db.commit()
    monkeypatch.setattr(
        processing,
        "_complete_json_payload",
        lambda *a, **kw: pytest.fail("No source: no model call"),
    )
    processing.generate_daily_content(db, now=NOW)
    processing.generate_daily_content(db, now=NOW + timedelta(minutes=6))
    rows = db.scalars(select(ContentSourceReplenishmentTask)).all()
    assert len(rows) == 1
    assert rows[0].brand_id == "Property360"


def test_documented_customer_problem_reaches_generator_without_fake_radar(db, monkeypatch):
    monkeypatch.setattr(processing, "settings", _settings)
    monkeypatch.setattr(processing, "ACTIVE_CONTENT_BRANDS", ("Property360",))
    captured = []

    def inspect_prompt(*args, **kwargs):
        captured.append(json.loads(kwargs["user_prompt"]))
        raise processing.GrowthRegistryError("bounded_test_stops_before_model")

    monkeypatch.setattr(processing, "_complete_json_payload", inspect_prompt)
    processing.generate_daily_content(db, now=NOW)
    assert len(captured) == 1
    intent = captured[0]["revenue_intent"]
    assert intent["input_type"] == "approved_brand_customer_problem"
    assert intent["source_refs"] and intent["approved_brand_facts"]
    assert captured[0]["evidence"]["approved_brand_facts"] == intent["approved_brand_facts"]
    assert not db.scalars(select(ContentSourceReplenishmentTask)).all()
    assert db.scalar(select(DailyContentObligation)).status == "failed"


def test_unavailable_forum_does_not_discard_usable_documented_brand_problem(db, monkeypatch):
    facts = processing._approved_brand_facts(db, "Property360", current=NOW)
    monkeypatch.setattr(processing, "_refresh_topic_source", lambda *a, **kw: {"error": "http_429"})
    intent = processing._prepare_content_revenue_intent(
        [_topic()], facts, brand_id="Property360", now=NOW
    )
    assert intent["input_type"] == "approved_brand_customer_problem"
    assert intent["radar_topic_id"] is None


def test_final_repair_must_keep_actual_problem_and_fact_not_only_metadata(db):
    facts = processing._approved_brand_facts(db, "Property360", current=NOW)
    intent = build_brand_source_intent("Property360", facts)
    package = {"revenue_intent": intent, "body": "Általános, bármely márkára ráhúzható tanács."}
    errors = processing._revenue_package_errors(package, intent)
    assert "buyer_problem_missing_from_copy" in errors
    assert "approved_brand_fact_missing_from_copy" in errors
    package["body"] = intent["buyer_problem"] + " " + facts[0]["payload"]["statement"]
    assert processing._revenue_package_errors(package, intent) == []
    package["revenue_intent"] = dict(intent, buyer_problem="A modell által kitalált új probléma")
    assert "revenue_brief_changed" in processing._revenue_package_errors(package, intent)


def test_source_bound_content_passes_existing_review_and_keeps_delivery_separate(db, monkeypatch):
    """Real seeded source inputs, deterministic generator/reviewer doubles; no provider calls."""
    monkeypatch.setattr(processing, "settings", _settings)
    monkeypatch.setattr(processing, "ACTIVE_CONTENT_BRANDS", ("Property360",))
    monkeypatch.setattr(processing, "_quality_release_secret", lambda: b"q" * 32)
    monkeypatch.setattr(processing, "submit_job", lambda *a, **kw: pytest.fail("No publication"))
    generated_inputs = []

    def complete(*args, **kwargs):
        request = json.loads(kwargs["user_prompt"])
        if kwargs["purpose"].startswith("canonical_daily_content_release_review:"):
            payload = {
                "artifact_sha256": request["artifact_sha256"],
                "overall_decision": "PASS",
                "gate_results": {
                    gate: {"decision": "PASS", "reason": "Test reviewer"}
                    for gate in request["required_gate_ids"]
                },
                "scores": dict.fromkeys(
                    [
                        "natural_hungarian",
                        "brand_distinctiveness",
                        "conversion_strength",
                        "claim_safety",
                    ],
                    90,
                ),
                "findings": [],
            }
        else:
            assert kwargs["purpose"] == "canonical_daily_content_factory:Property360"
            intent = request["revenue_intent"]
            generated_inputs.append(intent)
            fact = intent["approved_brand_facts"][0]["payload"]["statement"]
            body = (
                intent["buyer_problem"] + " " + fact + "\n\n"
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
            )
            payload = {
                "package": {
                    "brand_id": "Property360",
                    "title": "Telek, házterv és finanszírozás: együtt tervezd",
                    "format": "professional_article",
                    "body": body,
                    "facebook_post": (
                        "A telek ára csak a projekt egyik tétele. A házterv, a közművek, a "
                        "helyszíni munkák és a finanszírozás együtt határozzák meg, milyen "
                        "döntések várnak rád a költözésig. Írd össze, mi szerepel már az "
                        "ajánlatban, mi vár külön becslésre, és mihez hiányzik terv. A "
                        "Property360 ingatlanos ügyfélútja a telek és a ház összehangolására "
                        "épül. Indulj telek–ház elővizsgálattal! #telek #házterv #finanszírozás"
                    ),
                    "cta": {"label": intent["next_step"], "intent": "lead"},
                    "source_urls": intent["source_refs"],
                    "revenue_intent": intent,
                }
            }
        return SimpleNamespace(
            request_id="TEST-GENERATOR", model="test-double", content=json.dumps(payload)
        )

    monkeypatch.setattr(processing, "complete_json", complete)
    result = processing.generate_daily_content(db, now=NOW)
    row = db.scalar(select(DailyContentObligation))
    assert result["generated"] == 1, row.evidence_json
    package = json.loads(row.evidence_json)
    assert package["revenue_intent"] == generated_inputs[0]
    assert package["source_urls"] == generated_inputs[0]["source_refs"]
    assert row.status == "release_passed"
    assert package["quality_gate_manifest"]["hmac_sha256"]
    assert "publication_job_id" not in package
    if output := os.environ.get("CONTENT_FACTORY_REPLAY_OUTPUT"):
        Path(output).write_text(
            json.dumps(
                {
                    "source_inputs": (
                        "Existing brand documents read back from Google Drive on 2026-09-07"
                    ),
                    "generator": "deterministic test double",
                    "reviewer": "deterministic test double",
                    "external_sends": 0,
                    "publications": 0,
                    "package": package,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
