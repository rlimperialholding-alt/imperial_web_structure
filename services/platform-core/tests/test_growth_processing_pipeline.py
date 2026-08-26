from __future__ import annotations

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

from sqlalchemy import select

from app.growth_ops import processing
from app.growth_ops.canonical_policy import ACTIVE_CONTENT_BRANDS, IORA_EXECUTIVE_EMAIL
from app.growth_ops.models import (
    CanonicalInternalHandoff,
    DailyContentObligation,
    GrowthSignal,
    QuestionRadarTopic,
    SourceCoverageAttempt,
    SourceCoverageRoute,
)


def _route() -> SourceCoverageRoute:
    return SourceCoverageRoute(
        route_key="test-route",
        route_id="TEST-ROUTE",
        catalog_sha256="a" * 64,
        motor="construction",
        category="projekt",
        source_name="Teszt forrás",
        search_signal="építési projekt",
        route_url="https://source.test/project",
        source_row_sha256="b" * 64,
        source_record_json="{}",
    )


def _attempt() -> SourceCoverageAttempt:
    return SourceCoverageAttempt(
        attempt_id="SCA-TEST",
        route_key="test-route",
        catalog_sha256="a" * 64,
        status="succeeded",
        response_sha256="c" * 64,
        started_at=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
        completed_at=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
    )


def _settings(**overrides):
    values = {
        "timezone": "Europe/Budapest",
        "canonical_content_factory_enabled": True,
        "canonical_internal_handoff_at": "18:30",
        "canonical_internal_handoff_enabled": True,
        "canonical_internal_handoff_secret_file": "unused-by-test",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_source_extraction_accepts_only_literal_evidence(db, monkeypatch):
    source_permalink = "https://source.test/project/liget-projekt-123"
    text = (
        "A Minta Építő Kft. bejelentette a Liget projekt előkészítését. "
        f"Mikor indulhat el a kivitelezés? {source_permalink}"
    )
    response = {
        "leads": [
            {
                "organization_name": "Minta Építő Kft.",
                "project_title": "Liget projekt",
                "summary": "A Liget projekt előkészítése megjelent a forrásban.",
                "evidence_excerpt": (
                    "A Minta Építő Kft. bejelentette a Liget projekt előkészítését."
                ),
                "confidence": 91,
                "urgency": 65,
            },
            {
                "organization_name": "Kitalált Kft.",
                "summary": "Nincs a forrásban.",
                "evidence_excerpt": "Kitalált bizonyíték.",
                "confidence": 99,
                "urgency": 99,
            },
        ],
        "questions": [
            {
                "question": "Mikor indulhat el a kivitelezés?",
                "question_kind": "literal",
                "evidence_excerpt": "Mikor indulhat el a kivitelezés?",
                "source_permalink": source_permalink,
            },
            {
                "question": "Mennyi lesz az ára?",
                "evidence_excerpt": "Mennyi lesz az ára?",
            },
        ],
    }
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(
        processing,
        "complete_json",
        lambda *args, **kwargs: SimpleNamespace(request_id="DS-TEST", content=json.dumps(response)),
    )
    route = _route()
    attempt = _attempt()
    db.add_all([route, attempt])
    db.flush()

    result = processing.process_source_attempt(db, route=route, attempt=attempt, text=text)
    db.commit()

    assert result == {"status": "completed", "leads": 1, "questions": 1}
    signal = db.scalar(select(GrowthSignal))
    assert signal.company_name == "Minta Építő Kft."
    assert signal.subject_type == "organization"
    assert signal.recipient_email is None
    assert signal.status == "blocked"
    assert "internal_review_only" in signal.rejection_reasons_json
    topic = db.scalar(select(QuestionRadarTopic))
    assert topic.question == "Mikor indulhat el a kivitelezés?"
    assert topic.source_url == source_permalink


def test_source_hard_gate_blocks_before_model(db, monkeypatch):
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("model must not be called")

    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(processing, "complete_json", fail_if_called)
    route = _route()
    attempt = _attempt()
    result = processing.process_source_attempt(
        db, route=route, attempt=attempt, text="Homes4you projektinformáció"
    )

    assert result["status"] == "skipped"
    assert called is False
    assert "no_monitoring_hard_gate" in attempt.analysis_json


def test_anonymous_project_is_retained_but_inferred_question_is_rejected(db, monkeypatch):
    text = "Új projekt: 140 m2 családi ház generálkivitelezése Győrben."
    response = {
        "leads": [
            {
                "organization_name": None,
                "project_title": "140 m2 családi ház generálkivitelezése",
                "summary": "Projektjelzés.",
                "location": "Győr",
                "evidence_excerpt": text,
                "confidence": 82,
                "urgency": 60,
            }
        ],
        "questions": [
            {
                "question": "Milyen kivitelezési kapacitás szükséges a 140 m2-es házhoz?",
                "question_kind": "inferred_from_evidence",
                "evidence_excerpt": text,
            }
        ],
    }
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    captured = {}

    def fake_complete(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(request_id="DS-PROJECT", content=json.dumps(response))

    monkeypatch.setattr(processing, "complete_json", fake_complete)
    route = _route()
    route.route_key = "project-route"
    route.route_id = "PROJECT-ROUTE"
    attempt = _attempt()
    attempt.attempt_id = "SCA-PROJECT"
    attempt.route_key = route.route_key
    db.add_all([route, attempt])
    db.flush()

    result = processing.process_source_attempt(db, route=route, attempt=attempt, text=text)
    db.commit()

    signal = db.scalar(select(GrowthSignal))
    topic = db.scalar(select(QuestionRadarTopic))
    assert result == {"status": "completed", "leads": 1, "questions": 0}
    assert signal.subject_type == "project"
    assert signal.company_name is None
    assert signal.status == "blocked"
    assert topic is None
    assert "question_kind=inferred_from_evidence" in captured["system_prompt"]
    assert "kikövetkeztetett kérdést ne adj vissza" not in captured["system_prompt"]


def test_content_factory_quarantines_all_nineteen_brands(db, monkeypatch):
    local_day = date(2026, 8, 21)
    for brand in ACTIVE_CONTENT_BRANDS:
        db.add(DailyContentObligation(local_date=local_day, brand_id=brand))
    db.commit()
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    calls = []

    def fake_complete(*args, **kwargs):
        request = json.loads(kwargs["user_prompt"])
        brand_id = request["brand_id"]
        calls.append(brand_id)
        return SimpleNamespace(
            request_id="DS-CONTENT",
            content=json.dumps(
                {
                    "package": {
                        "brand_id": brand_id,
                        "title": "Napi szakmai téma",
                        "format": "faq",
                        "body": "Bizonyíték-alapú belső szakmai vázlat. " * 20,
                        "source_urls": [],
                    }
                }
            ),
        )

    monkeypatch.setattr(processing, "complete_json", fake_complete)

    result = processing.generate_daily_content(db, now=datetime(2026, 8, 21, 8, 0, tzinfo=UTC))

    rows = db.scalars(select(DailyContentObligation)).all()
    assert result["status"] == "complete"
    assert result["generated"] == result["required"] == result["completed"] == 19
    assert result["failed_brands"] == result["unresolved_brands"] == []
    assert calls == list(ACTIVE_CONTENT_BRANDS)
    assert len(rows) == 19
    assert all(row.status == "quarantined" for row in rows)
    assert all("QUARANTINED_INTERNAL_DRAFT" in row.evidence_json for row in rows)
    assert all(row.release_token_hash is None for row in rows)


def test_internal_handoff_is_fixed_recipient_and_idempotent(db, monkeypatch):
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    monkeypatch.setattr(processing, "_smtp_binding", lambda: SimpleNamespace())
    sent = []

    class FakeAdapter:
        def __init__(self, _binding):
            pass

        def send(self, **kwargs):
            sent.append(kwargs)
            return SimpleNamespace(provider_message_id="message-1")

    monkeypatch.setattr(processing, "SMTPEmailAdapter", FakeAdapter)
    now = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)  # 20:00 Budapest

    first = processing.send_internal_handoff(db, now=now)
    second = processing.send_internal_handoff(db, now=now)

    row = db.scalar(select(CanonicalInternalHandoff))
    assert first["status"] == second["status"] == "sent"
    assert second["idempotent"] is True
    assert len(sent) == 1
    assert sent[0]["to_email"] == IORA_EXECUTIVE_EMAIL
    assert row.recipient_email == IORA_EXECUTIVE_EMAIL
    assert "IORA" in row.body_text
    assert "nem indult közvetlen megkeresés" in row.body_text


def test_source_extraction_retries_one_transient_model_failure(db, monkeypatch):
    monkeypatch.setattr(processing, "settings", lambda: _settings())
    calls = 0

    def flaky_complete(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise processing.GrowthRegistryError("transient invalid model JSON")
        return SimpleNamespace(request_id="DS-RETRY", content='{"leads":[],"questions":[]}')

    monkeypatch.setattr(processing, "complete_json", flaky_complete)
    route = _route()
    attempt = _attempt()

    result = processing.process_source_attempt(
        db, route=route, attempt=attempt, text="Érvényes forrásszöveg egy projektről."
    )

    assert calls == 2
    assert result == {"status": "completed", "leads": 0, "questions": 0}
