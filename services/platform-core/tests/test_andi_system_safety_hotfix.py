from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.growth_ops import processing
from app.growth_ops.email import EmailDeliveryError
from app.growth_ops.models import (
    CanonicalEmailDelivery,
    CanonicalInternalHandoff,
    QuestionRadarIdentity,
    QuestionRadarTopic,
    SourceCoverageAttempt,
    SourceCoverageRoute,
)


def _settings():
    return SimpleNamespace(
        timezone="Europe/Budapest",
        canonical_publication_digest_enabled=True,
        canonical_publication_digest_at="10:00",
        canonical_publication_digest_recipient="molnar.andrea@imperialholding.hu",
    )


@pytest.mark.parametrize(
    ("raw", "expected_age", "expected_decision", "eligible"),
    [
        ("ma", 0, "preferred_0_30_days", True),
        ("tegnap", 1, "preferred_0_30_days", True),
        ("2 napja", 2, "preferred_0_30_days", True),
        ("2026-07-29", 29, "preferred_0_30_days", True),
        ("2 hete", 14, "preferred_0_30_days", True),
        ("2 hónapja", 60, "accepted_31_90_days", True),
        ("2026-05-30", 89, "accepted_31_90_days", True),
        ("6 hónapja", 180, "expired_over_90_days", False),
        ("1 éve", 365, "expired_over_90_days", False),
        ("ismeretlen", None, "unverified", False),
        ("2026-05-28", 91, "expired_over_90_days", False),
        ("2026-07-27", 31, "accepted_31_90_days", True),
    ],
)
def test_question_freshness_date_boundaries(
    monkeypatch, raw, expected_age, expected_decision, eligible
):
    monkeypatch.setattr(processing, "settings", _settings)
    evidence = f"{raw} Nyitott 0 válasz"
    result = processing._question_freshness(
        {
            "published_at_raw": raw,
            "active_status": "active",
            "active_status_raw": "Nyitott",
            "existing_answer_count": 0,
            "answer_count_raw": "0 válasz",
        },
        evidence_text=evidence,
        observed_at=datetime(2026, 8, 27, 10, tzinfo=UTC),
    )
    assert result["age_days"] == expected_age
    assert result["freshness_decision"] == expected_decision
    assert (result["eligibility_status"] == "eligible") is eligible


@pytest.mark.parametrize(
    ("status", "count", "missing_status", "reason"),
    [
        ("archived", 0, False, "source_inactive"),
        ("active", 1, False, "already_answered"),
        ("active", 0, True, "active_status_not_observed"),
    ],
)
def test_question_freshness_rejects_inactive_answered_or_unproven(
    monkeypatch, status, count, missing_status, reason
):
    monkeypatch.setattr(processing, "settings", _settings)
    raw_status = "" if missing_status else status
    evidence = f"ma {raw_status} {count} válasz"
    result = processing._question_freshness(
        {
            "published_at_raw": "ma",
            "active_status": status,
            "active_status_raw": raw_status,
            "existing_answer_count": count,
            "answer_count_raw": f"{count} válasz",
        },
        evidence_text=evidence,
        observed_at=datetime(2026, 8, 27, 10, tzinfo=UTC),
    )
    assert result["eligibility_status"] == "ineligible"
    assert reason in result["reasons"]


def test_question_identity_blocks_same_question_on_next_day(db, monkeypatch):
    monkeypatch.setattr(processing, "settings", _settings)
    question = "Milyen alapozás kell a tervezett családi házhoz?"
    permalink = "https://qjob.hu/tasks/999999"
    payload = {
        "leads": [],
        "questions": [
            {
                "question": question,
                "question_kind": "literal",
                "evidence_excerpt": question,
                "source_permalink": permalink,
                "published_at_raw": "2026-08-26",
                "active_status": "active",
                "active_status_raw": "Nyitott",
                "existing_answer_count": 0,
                "answer_count_raw": "0 válasz",
            }
        ],
    }
    monkeypatch.setattr(
        processing,
        "complete_json",
        lambda *_args, **_kwargs: SimpleNamespace(
            request_id="DS-STABLE", content=json.dumps(payload)
        ),
    )
    route = SourceCoverageRoute(
        route_key="stable-route",
        route_id="STABLE-ROUTE",
        catalog_sha256="a" * 64,
        motor="construction",
        category="marketplace",
        source_name="Qjob",
        search_signal="építés",
        route_url="https://qjob.hu/tasks",
        source_row_sha256="b" * 64,
        source_record_json="{}",
    )
    db.add(route)
    results = []
    for index, started_at in enumerate(
        (datetime(2026, 8, 26, 10, tzinfo=UTC), datetime(2026, 8, 27, 10, tzinfo=UTC))
    ):
        attempt = SourceCoverageAttempt(
            attempt_id=f"SCA-STABLE-{index}",
            route_key=route.route_key,
            catalog_sha256="a" * 64,
            status="succeeded",
            response_sha256="c" * 64,
            started_at=started_at,
            completed_at=started_at,
        )
        db.add(attempt)
        db.flush()
        results.append(
            processing.process_source_attempt(
                db,
                route=route,
                attempt=attempt,
                text=f"{question} 2026-08-26 Nyitott 0 válasz",
                link_candidates=[{"url": permalink, "label": question}],
            )
        )
        db.commit()
    assert [result["questions"] for result in results] == [1, 0]
    assert len(db.scalars(select(QuestionRadarTopic)).all()) == 1
    assert len(db.scalars(select(QuestionRadarIdentity)).all()) == 1


def _delivery() -> CanonicalEmailDelivery:
    return CanonicalEmailDelivery(
        delivery_id="CED-CONCURRENT",
        identity_sha256="a" * 64,
        recipient_normalized="test@imperialholding.hu",
        report_type="controlled",
        local_date=datetime(2026, 8, 27).date(),
        tenant_scope="imperial-holding",
        payload_sha256="b" * 64,
        status="pending",
    )


@pytest.mark.parametrize("workers", [2, 10])
def test_delivery_claim_allows_exactly_one_worker(tmp_path, workers):
    database = tmp_path / f"claim-{workers}.sqlite"
    engine = create_engine(
        f"sqlite:///{database}", connect_args={"check_same_thread": False, "timeout": 10}
    )
    CanonicalEmailDelivery.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as seed:
        seed.add(_delivery())
        seed.commit()

    def claim():
        with sessions() as session:
            return processing._claim_email_delivery(
                session,
                identity_sha256="a" * 64,
                current=datetime(2026, 8, 27, 10, tzinfo=UTC),
            )[1]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        statuses = list(executor.map(lambda _index: claim(), range(workers)))
    assert statuses.count("claimed") == 1
    assert statuses.count("in_progress") == workers - 1
    with sessions() as session:
        assert session.scalar(select(CanonicalEmailDelivery)).attempt_count == 1


def test_stale_sending_claim_is_reconcile_only(db):
    row = _delivery()
    row.status = "sending"
    row.lease_token = "dead-worker"
    row.lease_expires_at = datetime(2026, 8, 27, 9, tzinfo=UTC)
    db.add(row)
    db.commit()
    claimed, status, reconcile_only = processing._claim_email_delivery(
        db,
        identity_sha256=row.identity_sha256,
        current=datetime(2026, 8, 27, 10, tzinfo=UTC),
    )
    assert status == "claimed"
    assert reconcile_only is True
    assert claimed.attempt_count == 1


def test_digest_is_once_per_identity_but_new_day_and_recipient_are_independent(
    db, monkeypatch
):
    monkeypatch.setattr(processing, "settings", _settings)
    monkeypatch.setattr(processing, "_smtp_binding", lambda: SimpleNamespace())
    calls = []

    class Mailer:
        def __init__(self, _binding):
            pass

        def send(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                provider_message_id=f"MSG-{len(calls)}",
                detail={"readback_verified": True, "recovered_existing_sent": False},
            )

    monkeypatch.setattr(processing, "SMTPEmailAdapter", Mailer)
    day_one = datetime(2026, 8, 27, 10, 5, tzinfo=UTC)
    assert processing.send_publication_digest(db, now=day_one)["status"] == "sent"
    assert processing.send_publication_digest(db, now=day_one)["idempotent"] is True
    assert processing.send_publication_digest(
        db, now=day_one + timedelta(days=1)
    )["status"] == "sent"
    assert processing.send_publication_digest(
        db, now=day_one, recipient_email="control@imperialholding.hu"
    )["status"] == "sent"
    assert len(calls) == 3


def test_ambiguous_delivery_enters_reconcile_only_and_never_blindly_resends(
    db, monkeypatch
):
    monkeypatch.setattr(processing, "settings", _settings)
    monkeypatch.setattr(processing, "_smtp_binding", lambda: SimpleNamespace())
    calls = []

    class Mailer:
        def __init__(self, _binding):
            pass

        def send(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise EmailDeliveryError(
                    "accepted_but_unverified",
                    retry_safe=False,
                    accepted_but_unverified=True,
                    provider_message_id="GMAIL-1",
                )
            assert kwargs["reconcile_only"] is True
            return SimpleNamespace(
                provider_message_id="GMAIL-1",
                detail={"readback_verified": True, "recovered_existing_sent": True},
            )

    monkeypatch.setattr(processing, "SMTPEmailAdapter", Mailer)
    now = datetime(2026, 8, 27, 10, 5, tzinfo=UTC)
    first = processing.send_publication_digest(db, now=now)
    db.expire_all()
    held_delivery = db.scalar(select(CanonicalEmailDelivery))
    held_row = db.scalar(select(CanonicalInternalHandoff))
    assert held_delivery.status == "accepted_unverified"
    assert held_delivery.last_error == "accepted_but_unverified"
    assert held_delivery.lease_token is None
    assert held_delivery.lease_expires_at is None
    assert held_row.status == "dead_letter"
    assert held_row.last_error == "accepted_but_unverified"
    during_backoff = processing.send_publication_digest(db, now=now + timedelta(minutes=1))
    recovered = processing.send_publication_digest(db, now=now + timedelta(minutes=6))
    delivery = db.scalar(select(CanonicalEmailDelivery))
    assert first["status"] == "accepted_unverified"
    assert during_backoff["status"] == "backoff"
    assert recovered["status"] == "sent" and recovered["reconcile_only"] is True
    assert len(calls) == 2
    assert delivery.status == "sent" and delivery.provider_message_id == "GMAIL-1"


def test_known_pre_send_failure_backs_off_without_immediate_retry(db, monkeypatch):
    monkeypatch.setattr(processing, "settings", _settings)
    monkeypatch.setattr(processing, "_smtp_binding", lambda: SimpleNamespace())
    calls = []

    class Mailer:
        def __init__(self, _binding):
            pass

        def send(self, **kwargs):
            calls.append(kwargs)
            raise EmailDeliveryError("oauth_network_pre_send", retry_safe=True)

    monkeypatch.setattr(processing, "SMTPEmailAdapter", Mailer)
    now = datetime(2026, 8, 27, 10, 5, tzinfo=UTC)
    first = processing.send_publication_digest(db, now=now)
    db.expire_all()
    retry_delivery = db.scalar(select(CanonicalEmailDelivery))
    retry_row = db.scalar(select(CanonicalInternalHandoff))
    assert retry_delivery.status == "failed_retryable"
    assert retry_delivery.last_error == "oauth_network_pre_send"
    assert retry_delivery.lease_token is None
    assert retry_delivery.lease_expires_at is None
    assert retry_row.status == "failed"
    assert retry_row.last_error == "oauth_network_pre_send"
    second = processing.send_publication_digest(db, now=now + timedelta(seconds=10))
    assert first["status"] == "failed_retryable"
    assert second["status"] == "backoff"
    assert len(calls) == 1


def test_automatic_executive_handoff_never_calls_transport(db, monkeypatch):
    monkeypatch.setattr(
        processing,
        "settings",
        lambda: SimpleNamespace(
            timezone="Europe/Budapest",
            canonical_internal_handoff_at="18:30",
        ),
    )

    class MustNotRun:
        def __init__(self, _binding):
            raise AssertionError("automatic executive email transport must not be constructed")

    monkeypatch.setattr(processing, "SMTPEmailAdapter", MustNotRun)
    result = processing.send_internal_handoff(
        db, now=datetime(2026, 8, 27, 18, tzinfo=UTC)
    )
    row = db.scalar(select(CanonicalInternalHandoff))
    assert result["status"] == "blocked"
    assert row.last_error == "automatic_executive_delivery_prohibited"
