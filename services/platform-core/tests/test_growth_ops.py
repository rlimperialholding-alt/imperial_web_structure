from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.growth_ops import service
from app.growth_ops.connectors import _timestamp
from app.growth_ops.models import GrowthRun, GrowthSignal, OutreachMessage
from app.growth_ops.registry import BrandBinding, GrowthRegistryError
from app.growth_ops.schemas import GrowthSignalIn
from app.models import MailSendingDomain, MailSuppression


class FakeRegistry:
    motors = {
        "construction": {
            "interval_minutes": 60,
            "max_raw_signals_per_run": 500,
            "daily_raw_review_target": 300,
        },
        "distress": {"interval_minutes": 60, "max_raw_signals_per_run": 500},
        "ivs": {"daily_at": "08:00", "max_raw_signals_per_run": 500},
    }
    brands = {"bautica": {}}

    def validate_signal_source(self, *, source_id: str, motor_key: str, source_bucket: str) -> None:
        if (source_id, motor_key, source_bucket) != (
            "construction-etdr",
            "construction",
            "etdr",
        ):
            raise GrowthRegistryError("source mismatch")

    def brand_for(self, signal_type: str, requested: str | None = None) -> str:
        if signal_type != "residential_construction" or requested not in {None, "bautica"}:
            raise GrowthRegistryError("route mismatch")
        return "bautica"

    def brand_binding(self, brand_id: str) -> BrandBinding:
        assert brand_id == "bautica"
        body = (
            "{company_name}! Releváns üzleti jelzés: {signal_summary}. "
            "Forrás: {evidence_url}. Kapcsolatfelvétel válaszban. Leiratkozás: {unsubscribe_url}"
        )
        return BrandBinding(
            brand_id="bautica",
            sender_email="info@bautica.test",
            domain_key="bautica-test",
            secret={
                "host": "smtp.bautica.test",
                "port": 465,
                "username": "test",
                "password": "test",
                "use_ssl": True,
            },
            config={
                "brand_name": "Bautica",
                "templates": {
                    "default": {
                        "initial": {"subject": "Szakmai egyeztetés", "body": body},
                        "followup_1": {"subject": "Rövid utánkövetés", "body": body},
                        "followup_2": {"subject": "Utolsó utánkövetés", "body": body},
                    }
                },
                "followup_delays_days": [4, 8],
                "recipient_cooldown_days": 30,
                "max_daily_messages": 100,
            },
        )


@pytest.fixture
def growth_runtime(monkeypatch, db):
    registry = FakeRegistry()
    monkeypatch.setattr(service.GrowthRegistry, "load", classmethod(lambda cls: registry))
    monkeypatch.setattr(service, "writes_unlocked", lambda: True)
    monkeypatch.setattr(
        service,
        "settings",
        lambda: SimpleNamespace(
            base_url="https://intelligence.test.example",
            worker_id="growth-test-worker",
            lease_seconds=300,
            poll_seconds=30,
            enabled=True,
            timezone="Europe/Budapest",
        ),
    )
    db.add(
        MailSendingDomain(
            domain_key="bautica-test",
            domain_name="bautica.test",
            from_email="info@bautica.test",
            provider="smtp",
            spf_status="pass",
            dkim_status="pass",
            dmarc_status="pass",
            active=True,
        )
    )
    db.commit()
    return registry


def _signal(**changes) -> GrowthSignalIn:
    payload = {
        "source_id": "construction-etdr",
        "external_key": "ETDR-2026-0001",
        "motor_key": "construction",
        "source_bucket": "etdr",
        "signal_type": "residential_construction",
        "detected_at": datetime.now(UTC) - timedelta(hours=1),
        "company_name": "Minta Építő Kft.",
        "company_registration_id": "01-09-999999",
        "subject_type": "organization",
        "recipient_email": "iroda@minta-epito.test",
        "recipient_email_type": "role",
        "contact_basis": "public_business_contact",
        "public_contact_url": "https://minta-epito.test/kapcsolat",
        "location": "Budapest",
        "summary": "Nyilvánosan közzétett új lakóépület építési jelzés.",
        "evidence_url": "https://source.test/etdr/2026-0001",
        "confidence": 90,
        "urgency": 80,
        "source_payload_hash": hashlib.sha256(b"source-row").hexdigest(),
    }
    payload.update(changes)
    return GrowthSignalIn.model_validate(payload)


def test_verified_business_role_signal_queues_once(db, growth_runtime):
    first = service.ingest_signal(db, _signal())
    second = service.ingest_signal(db, _signal())

    assert first.status == "queued" and first.outreach_id
    assert second.idempotent and second.outreach_id == first.outreach_id
    assert len(db.scalars(select(GrowthSignal)).all()) == 1
    assert len(db.scalars(select(OutreachMessage)).all()) == 1


def test_unsubscribe_token_is_hashed_and_globally_suppresses(db, growth_runtime):
    result = service.ingest_signal(db, _signal())
    message = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == result.outreach_id)
    )
    assert message is not None and len(message.unsubscribe_token_hash) == 64
    match = re.search(r"/growth/unsubscribe/([^\s]+)", message.body_text)
    assert match and match.group(1) != message.unsubscribe_token_hash

    service.unsubscribe(db, match.group(1))

    assert message.status == "unsubscribed"
    suppression = db.scalar(
        select(MailSuppression).where(MailSuppression.email == message.recipient_email)
    )
    assert suppression and suppression.active


def test_natural_person_without_request_is_rejected(db, growth_runtime):
    result = service.ingest_signal(
        db,
        _signal(
            external_key="ETDR-2026-0002",
            company_name=None,
            company_registration_id=None,
            subject_type="natural_person",
            recipient_email="maganszemely@example.test",
            recipient_email_type="named",
        ),
    )

    assert result.status == "rejected"
    assert "natural_person_without_prior_consent_or_request" in result.reasons
    assert not db.scalars(select(OutreachMessage)).all()


def test_global_suppression_prevents_queue(db, growth_runtime):
    db.add(MailSuppression(email="iroda@minta-epito.test", reason="unsubscribe", active=True))
    db.commit()

    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0003"))

    assert result.status == "suppressed"
    assert not db.scalars(select(OutreachMessage)).all()


def test_invalid_source_binding_fails_closed(db, growth_runtime):
    with pytest.raises(GrowthRegistryError, match="source mismatch"):
        service.ingest_signal(db, _signal(source_bucket="public_request"))


def test_daily_schedule_runs_once_after_budapest_0800(growth_runtime):
    config = {"daily_at": "08:00"}
    before = datetime(2026, 8, 16, 5, 59, tzinfo=UTC)
    after = datetime(2026, 8, 16, 6, 1, tzinfo=UTC)

    assert not service._motor_is_due(before, None, config)
    assert service._motor_is_due(after, None, config)
    last = GrowthRun(
        run_id="GRUN-DAILY-TEST",
        motor_key="ivs",
        scheduled_for=after,
        started_at=after,
    )
    assert not service._motor_is_due(after + timedelta(hours=2), last, config)


def test_signal_schema_requires_contact_evidence():
    with pytest.raises(ValidationError, match="Public business contact URL is required"):
        _signal(public_contact_url=None)


def test_rss_timestamp_accepts_standard_rfc_2822_date():
    value = _timestamp("Sun, 16 Aug 2026 06:15:00 +0000")
    assert value == datetime(2026, 8, 16, 6, 15, tzinfo=UTC)
