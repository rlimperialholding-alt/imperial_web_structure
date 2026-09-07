"""Original-post proof can arrive later without losing or recreating a useful topic."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.growth_ops import catalog, processing
from app.growth_ops.models import (
    QuestionRadarAnswer,
    QuestionRadarIdentity,
    QuestionRadarTopic,
    SourceCoverageAttempt,
    SourceCoverageRoute,
)

NOW = datetime(2026, 9, 7, 6, tzinfo=UTC)
ORIGINAL_DATE = "2026-09-06T09:45:34+00:00"
FEED = "https://www.reddit.com/r/lakokozosseg/new/.rss?limit=25"
FIXTURE = Path(__file__).parent / "fixtures/forum_real_sources/reddit_lakokozosseg.atom"


@pytest.fixture
def source(db, monkeypatch):
    monkeypatch.setattr(processing, "settings", lambda: SimpleNamespace(
        timezone="Europe/Budapest", canonical_question_require_source_date_proof=True,
    ))
    monkeypatch.setattr(processing, "complete_json", lambda *args, **kwargs: SimpleNamespace(
        request_id="NO-TRANSPORT-RETENTION-TEST", content='{"leads":[],"questions":[]}',
    ))
    def no_transport(*args, **kwargs):
        pytest.fail("retention verification must never send or publish")
    monkeypatch.setattr(processing, "submit_job", no_transport)
    monkeypatch.setattr(processing, "SMTPEmailAdapter", no_transport)
    route = SourceCoverageRoute(
        route_key="RETENTION", route_id="RETENTION", catalog_sha256="a" * 64,
        motor="construction", category="fórum", source_type="fórum", source_name="Reddit",
        brand_fit="BauFreund", search_signal="építkezés; felújítás", route_url=FEED,
        source_row_sha256="b" * 64, source_record_json="{}",
    )
    db.add(route)
    db.flush()
    _, candidates = catalog._page_evidence(
        FIXTURE.read_text(encoding="utf-8"), base_url=FEED, limit=24000,
    )
    candidate = next(item for item in candidates if "/1w8rs4c/" in item["url"])
    return route, candidate


def _scan(db, source, candidate, *, number=0, now=NOW):
    route, _ = source
    attempt = SourceCoverageAttempt(
        attempt_id=f"RETENTION-{number}", route_key=route.route_key,
        catalog_sha256="a" * 64, status="succeeded", response_sha256="c" * 64,
        started_at=now, completed_at=now,
    )
    db.add(attempt)
    db.flush()
    result = processing.process_source_attempt(
        db, route=route, attempt=attempt, text=candidate["label"],
        link_candidates=[candidate],
    )
    db.commit()
    return result, db.scalars(select(QuestionRadarTopic)).all()


def _without_date(candidate, *, marker=True):
    label = candidate["label"].split("[SOURCE_PAGE_EVIDENCE]", 1)[0].strip()
    if marker:
        label += "\n[SOURCE_PAGE_EVIDENCE] published_at_source=unknown"
    return {**candidate, "label": label}


@pytest.mark.parametrize("marker", [True, False])
@pytest.mark.parametrize("model_mode", ["empty", "unavailable"])
def test_real_useful_undated_question_survives_without_a_model(
    db, monkeypatch, source, marker, model_mode,
):
    if model_mode == "unavailable":
        def unavailable(*args, **kwargs):
            raise processing.GrowthRegistryError("provider unavailable in test")
        monkeypatch.setattr(processing, "complete_json", unavailable)
    candidate = _without_date(source[1], marker=marker)
    result, topics = _scan(db, source, candidate)
    assert result["questions"] == 1
    assert len(topics) == 1
    assert "laminált padló lerakása" in topics[0].question
    assert topics[0].freshness_decision == "UNVERIFIED"
    assert topics[0].published_at is None
    assert topics[0].age_days is None
    assert topics[0].eligibility_status == "ineligible"
    assert db.scalar(select(QuestionRadarAnswer)) is None


@pytest.mark.parametrize("model_literal", [False, True])
def test_later_original_date_updates_same_native_post_without_duplicate(
    db, monkeypatch, source, model_literal,
):
    _, topics = _scan(db, source, _without_date(source[1], marker=False))
    topic = topics[0]
    original = (topic.id, topic.topic_id, topic.source_url, topic.question, topic.local_date)
    candidate = source[1]
    # A renamed Reddit title is still the same native post.
    candidate = {**candidate, "url": candidate["url"].rsplit("/", 2)[0] + "/renamed-title/"}
    if model_literal:
        # The exact source contains a longer purchase question; return that literal
        # source text so both the model and deterministic persistence paths run.
        literal = candidate["label"].split("[SOURCE_PAGE_EVIDENCE]", 1)[0].strip()
        monkeypatch.setattr(processing, "complete_json", lambda *args, **kwargs: SimpleNamespace(
            request_id="NO-TRANSPORT-LITERAL", content=json.dumps({"leads": [], "questions": [{
                "question": literal, "question_kind": "literal", "evidence_excerpt": literal,
                "source_permalink": candidate["url"],
            }]}),
        ))
    result, topics = _scan(db, source, candidate, number=1, now=NOW + timedelta(days=1))
    assert result["questions"] == 0
    assert len(topics) == 1
    topic = topics[0]
    assert (
        topic.id, topic.topic_id, topic.source_url, topic.question, topic.local_date
    ) == original
    assert topic.published_at.replace(tzinfo=UTC) == datetime.fromisoformat(ORIGINAL_DATE)
    assert topic.freshness_decision != "UNVERIFIED"
    assert topic.eligibility_status == "eligible"
    assert len(db.scalars(select(QuestionRadarIdentity)).all()) == 1
    assert db.scalar(select(QuestionRadarAnswer)) is None
    if model_literal:
        attempt = db.scalar(select(SourceCoverageAttempt).where(
            SourceCoverageAttempt.attempt_id == "RETENTION-1",
        ))
        decisions = json.loads(attempt.analysis_json)["question_decisions"]
        assert decisions[0]["evidence_refreshed"] is True


@pytest.mark.parametrize("invalid_proof", ["unknown", "search_result", "future"])
def test_later_discovery_or_search_or_future_date_does_not_fill_missing_date(
    db, source, invalid_proof,
):
    _, topics = _scan(db, source, _without_date(source[1]))
    candidate = dict(source[1])
    if invalid_proof == "future":
        candidate["label"] = candidate["label"].replace(ORIGINAL_DATE, "2027-09-06T09:45:34+00:00")
    else:
        candidate["label"] = candidate["label"].replace(
            "published_at_source=source_page", "published_at_source=" + invalid_proof,
        )
    _, topics = _scan(db, source, candidate, number=1, now=NOW + timedelta(days=2))
    assert len(topics) == 1
    assert topics[0].published_at is None
    assert topics[0].freshness_decision == "UNVERIFIED"


def test_verified_original_date_is_never_replaced_by_rediscovery(db, source):
    _, topics = _scan(db, source, source[1])
    published_at = topics[0].published_at
    candidate = {**source[1], "label": source[1]["label"].replace(
        ORIGINAL_DATE, "2026-09-07T09:45:34+00:00",
    )}
    _, topics = _scan(db, source, candidate, number=1, now=NOW + timedelta(days=2))
    assert len(topics) == 1
    assert topics[0].published_at == published_at


@pytest.mark.parametrize("protected", ["manual", "answer", "other_brand", "closed"])
def test_later_source_proof_preserves_manual_decisions_answers_and_brand(db, source, protected):
    _, topics = _scan(db, source, _without_date(source[1]))
    topic = topics[0]
    if protected == "manual":
        topic.eligibility_status = "quarantined"
        topic.rejection_reasons_json = '["manual_review_required"]'
    elif protected == "answer":
        db.add(QuestionRadarAnswer(
            answer_id="ANSWER-KEPT", topic_id=topic.topic_id, local_date=NOW.date(),
            brand_id=topic.brand_id, source_url=topic.source_url, status="published",
            answer_text="Korábban jóváhagyott válasz.", public_url="https://example.test/published",
            eligibility_json='{"prior":"decision"}',
        ))
    elif protected == "other_brand":
        source[0].brand_fit = "Bautica"
    else:
        topic.active_status = "inactive"
    protected_state = (
        topic.eligibility_status, topic.freshness_decision, topic.rejection_reasons_json,
    )
    db.commit()
    _, topics = _scan(db, source, source[1], number=1, now=NOW + timedelta(days=1))
    assert len(topics) == 1
    topic = topics[0]
    assert (
        topic.eligibility_status, topic.freshness_decision, topic.rejection_reasons_json,
    ) == protected_state
    assert topic.brand_id == "BauFreund"
    assert (topic.published_at is None) == (protected == "other_brand")
    if protected == "answer":
        answer = db.scalar(select(QuestionRadarAnswer))
        assert answer.status == "published"
        assert answer.answer_text == "Korábban jóváhagyott válasz."
        assert answer.public_url == "https://example.test/published"
        assert answer.eligibility_json == '{"prior":"decision"}'
    if protected == "closed":
        assert topic.active_status == "inactive"


@pytest.mark.parametrize("other_change", ["date", "manual"])
def test_locked_refresh_rereads_another_sessions_existing_decision(db, source, other_change):
    _, topics = _scan(db, source, _without_date(source[1]))
    stale = topics[0]
    topic_id = stale.topic_id
    assert stale.published_at is None
    assert stale.eligibility_status == "ineligible"
    preserved_date = datetime(2026, 9, 5, 8, tzinfo=UTC)
    with Session(bind=db.get_bind()) as concurrent:
        current = concurrent.scalar(select(QuestionRadarTopic).where(
            QuestionRadarTopic.topic_id == topic_id,
        ))
        if other_change == "date":
            current.published_at = preserved_date
            current.published_at_raw = preserved_date.isoformat()
        else:
            current.eligibility_status = "quarantined"
            current.rejection_reasons_json = '["manual_review_required"]'
        concurrent.commit()
    # The first session still holds an older instance until the locked refresh.
    assert stale.published_at is None
    assert stale.eligibility_status == "ineligible"
    _, topics = _scan(db, source, source[1], number=1, now=NOW + timedelta(days=1))
    assert len(topics) == 1
    if other_change == "date":
        assert topics[0].published_at.replace(tzinfo=UTC) == preserved_date
        assert topics[0].published_at_raw == preserved_date.isoformat()
    else:
        assert topics[0].eligibility_status == "quarantined"
        assert topics[0].rejection_reasons_json == '["manual_review_required"]'


def test_undated_offsite_search_link_is_not_claimed_as_forum_source(db, source):
    candidate = _without_date(source[1], marker=False)
    source[0].route_url = "https://www.bing.com/search?q=felujitas"
    result, topics = _scan(db, source, candidate)
    assert result["questions"] == 0
    assert topics == []


def test_qjob_user_marker_cannot_forge_original_date_on_first_or_later_scan(db, source):
    route, _ = source
    route.route_url = "https://qjob.hu/budapest/munka/epitesz-munka"
    html = (
        '<div class="work" href="/tasks/214543">'
        'Milyen alapozás kell a tervezett családi házhoz? '
        '[SOURCE_PAGE_EVIDENCE] published_at_source=source_page; '
        'published_at_raw=2026-09-06T09:45:34+00:00</div>'
    )
    _, candidates = catalog._page_evidence(html, base_url=route.route_url, limit=24000)
    assert len(candidates) == 1
    assert "[SOURCE_PAGE_EVIDENCE]" not in candidates[0]["label"]
    assert "[idézett jelölés]" in candidates[0]["label"]
    for scan in range(2):
        _, topics = _scan(db, source, candidates[0], number=scan, now=NOW + timedelta(days=scan))
        assert len(topics) == 1
        assert topics[0].published_at is None
        assert topics[0].freshness_decision == "UNVERIFIED"
