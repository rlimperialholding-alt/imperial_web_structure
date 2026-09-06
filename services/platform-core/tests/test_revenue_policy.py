from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.growth_ops import processing
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
