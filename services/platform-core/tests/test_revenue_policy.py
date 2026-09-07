from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.growth_ops import catalog, processing
from app.growth_ops.models import (
    QuestionRadarTopic,
    SourceCoverageAttempt,
    SourceCoverageRoute,
)
from app.growth_ops.revenue_policy import (
    SourceReplenishmentRequired,
    build_revenue_intent,
    evaluate_revenue_intent,
    is_purchase_signal,
    revalidate_topic_for_use,
)


def _topic(**overrides):
    value = {
        "topic_id": "QRT-1",
        "brand_id": "Bautica",
        "question": "Ajánlatot kérek a családi ház kivitelezésére Győrben",
        "source_url": "https://forum.example/post/123456",
        "eligibility_status": "eligible",
        "freshness_decision": "preferred_0_30_days",
        "published_at": datetime.now(UTC) - timedelta(days=4),
        "age_days": 4,
        "active_status": "active",
        "existing_answer_count": 0,
    }
    value.update(overrides)
    return value


def test_purchase_signal_accepts_no_question_mark():
    assert is_purchase_signal("Ajánlatot kérek családi ház kivitelezésére")


def test_gyakori_kerdesek_permalink_and_relative_date_are_source_page_safe():
    permalink = (
        "https://www.gyakorikerdesek.hu/otthon__epitkezes__13249178-"
        "piteszmernokot-keresek-miskolcon-kit-ajanlanatok"
    )
    assert processing._specific_reply_permalink(permalink)
    parsed = processing._parse_observed_date(
        "júl. 23. 09:43",
        observed_at=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
    )
    assert parsed == datetime(2026, 7, 23, 7, 43, tzinfo=UTC)


def test_gyakori_kerdesek_page_metadata_proves_zero_answers():
    body = """
    <html><head><title>Építészmérnököt keresek</title></head><body>
    <div class="kerdes"><h1>Építészmérnököt keresek Miskolcon. Kit ajánlanátok?</h1>
    Családi ház bővítéséhez keresek tervezőt.
    <div title="A kérdés kiírásának időpontja">júl. 23. 09:43</div></div>
    <div class="sajnosmeg">Sajnos még nem érkezett válasz a kérdésre.</div>
    </body></html>
    """
    metadata = catalog._reply_page_metadata(
        body,
        source_url=(
            "https://www.gyakorikerdesek.hu/otthon__epitkezes__13249178-"
            "piteszmernokot-keresek-miskolcon-kit-ajanlanatok"
        ),
    )
    assert metadata is not None
    assert metadata["published_at_raw"] == "júl. 23. 09:43"
    assert metadata["published_at_source"] == "source_page"
    assert metadata["active_status"] == "active"
    assert metadata["existing_answer_count"] == "0"


def test_direct_question_routes_are_registered_with_current_catalog_revision(db):
    catalog.ensure_question_radar_direct_routes(db, catalog_sha256="a" * 64)
    rows = db.scalars(
        select(SourceCoverageRoute).where(
            SourceCoverageRoute.route_key.like("QUESTION-RADAR:%")
        )
    ).all()
    assert {row.route_url for row in rows} == {
        "https://www.gyakorikerdesek.hu/otthon__epitkezes__valasz-nelkul",
        "https://www.gyakorikerdesek.hu/otthon__felujitas__valasz-nelkul",
        "https://forum.index.hu/Topic/showTopicList?t=52",
        "https://www.reddit.com/r/hungary/new/.rss?limit=25",
        "https://www.reddit.com/r/askhungary/new/.rss?limit=25",
        "https://www.reddit.com/r/kiszamolo/new/.rss?limit=25",
        "https://www.reddit.com/r/lakokozosseg/new/.rss?limit=25",
        (
            "https://prohardver.hu/tema/lakasfelujito_szerelo_szakemberkereso_nagy_topic_"
            "viz_gaz_villany_futes_festes_burkolas_stb/friss.html"
        ),
        "https://lite.duckduckgo.com/lite/?q=epitkezes+forum",
        "https://lite.duckduckgo.com/lite/?q=felujitas+forum",
        "https://www.bing.com/search?q=megbizhato+kivitelezo+ajanlas+arajanlat+epitkezes",
    }
    assert all(row.enabled is True and row.catalog_sha256 == "a" * 64 for row in rows)


def test_search_discovered_forum_permalink_is_idempotent(db):
    catalog.ensure_question_radar_direct_routes(db, catalog_sha256="a" * 64)
    parent = db.scalar(
        select(SourceCoverageRoute).where(
            SourceCoverageRoute.route_key == "QUESTION-RADAR:FORUM-DISCOVERY-CONSTRUCTION"
        )
    )
    assert parent is not None
    link = {
        "url": "https://forum.example.hu/threads/kivitelezo-ajanlas.12345/",
        "label": "Tudtok megbízható kivitelezőt? Építkezés fórum",
    }
    assert catalog._upsert_discovered_forum_routes(
        db,
        catalog_sha256="a" * 64,
        parent_route=parent,
        links=[link],
        now=datetime.now(UTC),
    ) == 1
    assert catalog._upsert_discovered_forum_routes(
        db,
        catalog_sha256="a" * 64,
        parent_route=parent,
        links=[link],
        now=datetime.now(UTC),
    ) == 1
    rows = db.scalars(
        select(SourceCoverageRoute).where(
            SourceCoverageRoute.route_key.like("QUESTION-RADAR:DISCOVERED:%")
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].route_mode == "direct_post"
    assert rows[0].route_url == link["url"]


def test_revalidation_rejects_changed_source_identity():
    decision = revalidate_topic_for_use(
        _topic(),
        source_snapshot={
            "source_url": "https://forum.example/post/999999",
            "published_at": _topic()["published_at"],
            "active_status": "active",
            "existing_answer_count": 0,
        },
    )
    assert decision["eligible"] is False
    assert "source_identity_changed" in decision["reasons"]


def test_build_intent_requires_approved_facts():
    with pytest.raises(SourceReplenishmentRequired) as error:
        build_revenue_intent(
            _topic(),
            approved_brand_facts=[],
            sales_goal="minősített érdeklődőből ajánlatkérés",
            next_step="Rövid helyzetleírás bekérése",
        )
    assert "approved_brand_fact_missing" in error.value.reasons


def test_evaluate_intent_never_grants_delivery_authority():
    decision = evaluate_revenue_intent(
        {
            "brand_id": "Bautica",
            "buyer_problem": "Kivitelezőt keresek ellenőrizhető feltételekkel",
            "sales_goal": "minősített ajánlatkérés",
            "approved_brand_facts": [{"source_key": "brand.fact.1"}],
            "next_step": "Kérjünk rövid helyzetleírást",
            "source_refs": ["https://forum.example/post/123456"],
        },
        brand_id="Bautica",
    )
    assert decision["eligible"] is True
    assert decision["publication_allowed"] is False
    assert decision["send_allowed"] is False


def test_revalidation_rejects_old_topic_before_use():
    decision = revalidate_topic_for_use(
        _topic(
            published_at=datetime.now(UTC) - timedelta(days=120),
            age_days=120,
            freshness_decision="expired_over_90_days",
            eligibility_status="ineligible",
        )
    )
    assert decision["eligible"] is False
    assert "freshness_not_eligible" in decision["reasons"]


def test_source_extraction_retains_questionless_purchase_signal(db, monkeypatch):
    route = SourceCoverageRoute(
        route_key="purchase-route",
        route_id="PURCHASE-ROUTE",
        catalog_sha256="a" * 64,
        motor="construction",
        category="forum",
        source_name="Purchase forum",
        search_signal="kivitelező ajánlat",
        route_url="https://forum.example/thread/123456",
        source_row_sha256="b" * 64,
        source_record_json="{}",
    )
    attempt = SourceCoverageAttempt(
        attempt_id="SCA-PURCHASE",
        route_key=route.route_key,
        catalog_sha256=route.catalog_sha256,
        status="succeeded",
        response_sha256="c" * 64,
        started_at=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
        completed_at=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
    )
    db.add_all([route, attempt])
    db.flush()
    monkeypatch.setattr(
        processing,
        "settings",
        lambda: SimpleNamespace(
            timezone="Europe/Budapest",
            canonical_question_require_source_date_proof=True,
        ),
    )
    monkeypatch.setattr(
        processing,
        "complete_json",
        lambda *args, **kwargs: SimpleNamespace(
            request_id="DS-PURCHASE",
            content=json.dumps(
                {
                    "leads": [],
                    "questions": [
                        {
                            "question": "Ajánlatot kérek a családi ház kivitelezésére Győrben",
                            "question_kind": "purchase_signal",
                            "signal_kind": "purchase_signal",
                            "evidence_excerpt": (
                                "Ajánlatot kérek a családi ház kivitelezésére Győrben"
                            ),
                            "source_permalink": "https://forum.example/thread/123456",
                            "published_at_raw": "2026-08-20",
                            "published_at_source": "source_page",
                            "active_status": "active",
                            "active_status_raw": "active",
                            "existing_answer_count": 0,
                            "answer_count_raw": "0 válasz",
                        }
                    ],
                }
            ),
        ),
    )
    result = processing.process_source_attempt(
        db,
        route=route,
        attempt=attempt,
        text=(
            "Ajánlatot kérek a családi ház kivitelezésére Győrben. "
            "2026-08-20 active 0 válasz"
        ),
        link_candidates=[{"url": route.route_url, "label": "post"}],
    )
    db.commit()
    assert result["questions"] == 1
    topic = db.scalar(select(QuestionRadarTopic))
    assert topic is not None
    assert topic.classification == "observed_purchase_signal"
    assert topic.use_case == "exact_source_purchase_signal_candidate"
