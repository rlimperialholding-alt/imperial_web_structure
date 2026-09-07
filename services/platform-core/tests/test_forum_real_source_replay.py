"""No-network replay of anonymized original forum sources fetched 2026-09-07.

The model is deliberately stubbed. This verifies deterministic retention and DB
identity, not provider quality, sending, or publishing. Source provenance is in
the adjacent fixtures README.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.growth_ops import catalog, processing
from app.growth_ops.models import QuestionRadarTopic, SourceCoverageAttempt, SourceCoverageRoute

FIXTURES = Path(__file__).parent / "fixtures" / "forum_real_sources"
OBSERVED_AT = datetime(2026, 9, 7, 6, tzinfo=UTC)
PH_TOPIC = (
    "https://prohardver.hu/tema/"
    "lakasfelujito_szerelo_szakemberkereso_nagy_topic_viz_gaz_villany_futes_festes_burkolas_stb"
)
SOURCES = [
    ("reddit", "reddit_lakokozosseg.atom", "https://www.reddit.com/r/lakokozosseg/new/.rss?limit=25"),
    ("index", "index_building.html", "https://forum.index.hu/Article/showArticle?t=9004917"),
    ("prohardver", "prohardver_kitchen.html", PH_TOPIC + "/friss.html"),
]


def _candidates(filename: str, url: str):
    return catalog._page_evidence(
        (FIXTURES / filename).read_text(encoding="utf-8"), base_url=url, limit=24000,
    )


def test_actual_source_parsers_bind_original_body_and_date_to_exact_post():
    _text, reddit = _candidates(SOURCES[0][1], SOURCES[0][2])
    assert len(reddit) == 4
    labor = next(item for item in reddit if "/1w8rs4c/" in item["url"])
    assert "Munkadíjak?" in labor["label"]
    assert "laminált padló lerakása" in labor["label"]
    assert "published_at_raw=2026-09-06T09:45:34+00:00" in labor["label"]
    assert "existing_answer_count=0" not in labor["label"]

    _text, index = _candidates(SOURCES[1][1], SOURCES[1][2])
    assert len(index) == 3
    insulation = next(item for item in index if "a=172270043" in item["url"])
    assert "published_at_raw=2026.09.06 11:18:01" in insulation["label"]
    assert "10 és 15 cm homlokzati hőszigetelés" in insulation["label"]
    assert "5000Ft/m2" not in insulation["label"]

    _text, prohardver = _candidates(SOURCES[2][1], SOURCES[2][2])
    assert len(prohardver) == 1
    assert prohardver[0]["url"] == PH_TOPIC + "/hsz_171759-171759.html"
    assert "A felső és alsó konyhaszekrény" in prohardver[0]["label"]
    # This sentence belongs to a quoted earlier post, not this author/post.
    assert "miért fentől nem tudod bekötni" not in prohardver[0]["label"]


@pytest.mark.parametrize("model_mode", ["empty", "short_title", "literal_question", "old_sources"])
def test_real_useful_questions_survive_and_repeated_scan_does_not_duplicate(
    db, monkeypatch, model_mode,
):
    monkeypatch.setattr(processing, "settings", lambda: SimpleNamespace(
        timezone="Europe/Budapest", canonical_question_require_source_date_proof=True,
    ))
    observed_at = OBSERVED_AT + timedelta(days=45 if model_mode == "old_sources" else 0)

    def model(*args, **kwargs):
        prompt = json.loads(kwargs["user_prompt"])
        questions = []
        if model_mode == "short_title":
            for link in prompt["same_site_link_candidates"]:
                if "/1w8rs4c/" in link["url"]:
                    questions.append({
                        "question": "Munkadíjak?", "question_kind": "literal",
                        "evidence_excerpt": "Egy 20 m2-es szobában laminált padló lerakása",
                        "source_permalink": link["url"],
                    })
        elif model_mode == "literal_question":
            for link in prompt["same_site_link_candidates"]:
                if "/1w80vox/" in link["url"]:
                    questions.append({
                        "question": "Milyen garázst építenétek?", "question_kind": "literal",
                        "evidence_excerpt": "Milyen garázst építenétek?",
                        "source_permalink": link["url"],
                        "published_at_raw": "2026-09-05T13:32:22+00:00",
                        "published_at_source": "source_page",
                    })
        return SimpleNamespace(
            request_id="STUB-NO-SEND-REAL-SOURCE-REPLAY",
            content=json.dumps({"leads": [], "questions": questions}),
        )

    def no_transport(*args, **kwargs):
        pytest.fail("source replay must never send or publish")

    monkeypatch.setattr(processing, "complete_json", model)
    monkeypatch.setattr(processing, "submit_job", no_transport)
    monkeypatch.setattr(processing, "SMTPEmailAdapter", no_transport)
    routes = []
    for key, filename, url in SOURCES:
        route = SourceCoverageRoute(
            route_key="REPLAY-" + key, route_id="REPLAY-" + key,
            catalog_sha256="a" * 64, motor="construction", category="fórum",
            source_type="fórum", source_name=key, brand_fit="BauFreund",
            search_signal="építkezés; felújítás; költség; kivitelező",
            route_url=url, source_row_sha256="b" * 64, source_record_json="{}",
        )
        db.add(route)
        routes.append((route, filename, url))
    db.flush()
    for scan in range(2):
        for route, filename, url in routes:
            attempt = SourceCoverageAttempt(
                attempt_id=f"REPLAY-{route.route_key}-{scan}", route_key=route.route_key,
                catalog_sha256="a" * 64, status="succeeded", response_sha256="c" * 64,
                started_at=observed_at + timedelta(days=scan),
                completed_at=observed_at + timedelta(days=scan),
            )
            db.add(attempt)
            db.flush()
            text, links = _candidates(filename, url)
            processing.process_source_attempt(
                db, route=route, attempt=attempt, text=text, link_candidates=links,
            )
            db.commit()
        topics = db.scalars(select(QuestionRadarTopic)).all()
        assert len(topics) == 7, [
            {"source": topic.source_url, "question": topic.question} for topic in topics
        ]
        assert len({topic.source_url for topic in topics}) == 7
        assert all("1w9ierm" not in topic.source_url for topic in topics)
        assert all(topic.brand_id == "BauFreund" for topic in topics)
        # Missing reply count/status affects direct replies; useful source text
        # must remain available for content and research.
        assert all(topic.published_at is not None for topic in topics)
        assert all(not processing._reply_eligibility(topic)["eligible"] for topic in topics)
        if model_mode == "old_sources":
            assert all(topic.freshness_decision == "RESEARCH_ONLY" for topic in topics)
        labor = next(topic for topic in topics if "/1w8rs4c/" in topic.source_url)
        assert "padló" in labor.question or "Munkadíjak" in labor.question
