"""Real reversed-word-order request plus independent false-positive controls."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.growth_ops import processing, revenue_policy
from app.growth_ops.models import QuestionRadarTopic, SourceCoverageAttempt, SourceCoverageRoute


NOW = datetime(2026, 9, 7, 8, 30, tzinfo=UTC)
FIXTURE = Path(__file__).parent / "fixtures/forum_real_sources/reddit_statikus.json"


def _assess(text: str, *, age_hours: int = 1):
    return revenue_policy.assess_signal({
        "source_url": "https://forum.example/post/123456",
        "text": text, "observed_at": NOW, "source_scoped": True,
        "permalink_verified": True, "timestamp_proof": "post_published",
        "published_at_raw": (NOW - timedelta(hours=age_hours)).isoformat(),
    }, now=NOW)


@pytest.mark.parametrize("specialist", [
    "statikust", "építészmérnököt", "tetőfedőt", "villanyszerelőt", "vízszerelőt",
    "gázszerelőt", "burkolót", "festőt", "ácsot", "bádogost", "kivitelezőt",
])
def test_concrete_specialists_are_buying_requests_in_both_hungarian_word_orders(specialist):
    for text in (
        f"Budapesten keresek megbízható, korrekt {specialist} a ház felújításához.",
        f"A ház felújításához {specialist} keresünk.",
        f"Tudtok ajánlani megbízható {specialist} a ház felújításához?",
    ):
        result = _assess(text)
        assert result["queue"] == "WARM", (text, result)
        assert result["intent_score"] == 45
        assert result["lead_eligible"] is True
        assert result["contact_allowed"] is False
        assert revenue_policy.is_purchase_signal(text)


@pytest.mark.parametrize("text", [
    'A szomszédom írta: "Budapesten keresek statikust." Ennyit tudok a projektről.',
    "A szomszédom írta: statikust keresek. Ennyit tudok a projektről.",
    "Ezt írta az ismerősöm: keresek statikust. Én nem építkezem.",
    "Idézet: villanyszerelőt keresek. Miért gyakori ez a kérdés?",
    "„Keresek lelkiismeretes statikust.” Ez egy másik fórumozó kérdése.",
    "> Budapesten keresek statikust.\nEzt írta tegnap valaki, én csak idézem.",
    "<blockquote>Statikust keresek.</blockquote> Ez egy idézett kérdés.",
    "Nem keresek statikust, már megoldódott a problémám.",
    "Statikust keresek? Statikusként vállalok felmérést, keressen bizalommal!",
    "Villanyszerelőt keresünk csapatunkba, alkalmazotti munkára.",
    "Új ügyfeleket keresek statikusként Budapesten.",
    "Ezt olvastam: keresek megbízható statikust. Ez kinek a kérdése?",
])
def test_quoted_negated_advertising_or_job_requests_do_not_become_current_buyers(text):
    result = _assess(text)
    assert result["lead_eligible"] is False
    assert result["contact_allowed"] is False
    assert revenue_policy.is_purchase_signal(text) is False
    assert "explicit_request" not in result["features"]


def test_own_request_after_an_unrelated_quote_is_retained_and_old_request_stays_old():
    text = 'A szomszéd ezt írta: "Már találtam kivitelezőt." Én keresek statikust a házamhoz.'
    assert _assess(text)["queue"] == "WARM"
    assert _assess(text, age_hours=31 * 24)["queue"] == "RESEARCH_ONLY"


def test_actual_new_reddit_request_keeps_original_date_and_survives_empty_model_twice(db, monkeypatch):
    actual = json.loads(FIXTURE.read_text(encoding="utf-8"))
    label = (
        actual["source_text"] + "\n[SOURCE_PAGE_EVIDENCE] published_at_raw="
        + actual["published_at_raw"] + "; published_at_source=source_page"
    )
    candidate = {"url": actual["source_url"], "label": label}
    monkeypatch.setattr(processing, "settings", lambda: SimpleNamespace(
        timezone="Europe/Budapest", canonical_question_require_source_date_proof=True,
    ))
    monkeypatch.setattr(processing, "complete_json", lambda *args, **kwargs: SimpleNamespace(
        request_id="STUB-REAL-STATIKUS-NO-SEND", content='{"leads":[],"questions":[]}',
    ))

    def no_transport(*args, **kwargs):
        pytest.fail("real-source fixture replay must not send or publish")

    monkeypatch.setattr(processing, "submit_job", no_transport)
    monkeypatch.setattr(processing, "SMTPEmailAdapter", no_transport)
    route = SourceCoverageRoute(
        route_key="STATIKUS-REPLAY", route_id="STATIKUS-REPLAY", catalog_sha256="a" * 64,
        motor="construction", category="fórum", source_type="fórum", source_name="Reddit",
        brand_fit="BauFreund", search_signal="felújítás; szakember", route_url=actual["feed_url"],
        source_row_sha256="b" * 64, source_record_json="{}",
    )
    db.add(route)
    db.flush()
    for scan in range(2):
        attempt = SourceCoverageAttempt(
            attempt_id=f"STATIKUS-{scan}", route_key=route.route_key,
            catalog_sha256="a" * 64, status="succeeded",
            response_sha256=actual["original_feed_sha256"],
            started_at=NOW + timedelta(days=scan), completed_at=NOW + timedelta(days=scan),
        )
        db.add(attempt)
        db.flush()
        processing.process_source_attempt(db, route=route, attempt=attempt, text=label, link_candidates=[candidate])
        db.commit()
        topics = db.scalars(select(QuestionRadarTopic)).all()
        assert len(topics) == 1
        assert "statikust" in topics[0].question
        assert topics[0].brand_id == "BauFreund"
        assert topics[0].published_at.replace(tzinfo=UTC) == datetime.fromisoformat(actual["published_at_raw"])
        assert topics[0].freshness_decision == "WARM"
        assert topics[0].eligibility_status == "eligible"
        # Demand classification is not permission to send an unverified reply.
        assert not processing._reply_eligibility(topics[0])["eligible"]
