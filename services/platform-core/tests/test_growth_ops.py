from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.database import SessionLocal
from app.growth_ops import service
from app.growth_ops.canonical_policy import (
    LAND_AGENT_HARD_GATE_AFFILIATION_UNVERIFIED,
    LAND_AGENT_HARD_GATE_GDN,
    LAND_AGENT_HARD_GATE_OC_II_XII,
    LAND_AGENT_HARD_GATE_OC_UNVERIFIED,
    LAND_AGENT_HARD_GATE_TURCZER,
    land_agent_hard_gate_reason,
)
from app.growth_ops.connectors import SourceBatch, _timestamp
from app.growth_ops.email import EmailDeliveryError, SMTPEmailAdapter
from app.growth_ops.models import (
    GrowthRun,
    GrowthSignal,
    GrowthWorkerHeartbeat,
    OutreachMessage,
)
from app.growth_ops.registry import BrandBinding, GrowthRegistryError
from app.growth_ops.schemas import GrowthSignalIn, OutreachReleaseIn
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
    brands = {"imperial": {}}

    def readiness(self) -> dict[str, object]:
        return {"ready": True, "enabled_sources": 1, "version": "test-v1"}

    def validate_signal_source(
        self, *, source_id: str, motor_key: str, source_bucket: str, **_: object
    ) -> None:
        if (source_id, motor_key, source_bucket) != (
            "construction-etdr",
            "construction",
            "etdr",
        ):
            raise GrowthRegistryError("source mismatch")

    def brand_for(self, signal_type: str, requested: str | None = None) -> str:
        if signal_type not in {
            "residential_construction",
            "residential_building_plot",
        } or requested not in {None, "imperial"}:
            raise GrowthRegistryError("route mismatch")
        return "imperial"

    def brand_binding(self, brand_id: str) -> BrandBinding:
        assert brand_id == "imperial"
        return BrandBinding(
            brand_id="imperial",
            sender_email="info@imperialholding.test",
            domain_key="imperial-test",
            secret={
                "host": "smtp.imperialholding.test",
                "port": 465,
                "username": "test",
                "password": "test",
                "use_ssl": True,
            },
            config={
                "brand_name": "Imperial Holding",
                "recipient_cooldown_days": 30,
                "max_daily_messages": 100,
            },
        )


@pytest.fixture
def growth_runtime(monkeypatch, db):
    registry = FakeRegistry()
    canonical_path = (
        Path(os.environ["CANONICAL_FIRST_CONTACT_REGISTRY_FILE"])
        if "CANONICAL_FIRST_CONTACT_REGISTRY_FILE" in os.environ
        else Path(__file__).resolve().parents[3]
        / "config"
        / "outbound"
        / "canonical_first_contact_templates_hu_v1.json"
    )
    monkeypatch.setenv("CANONICAL_FIRST_CONTACT_REGISTRY_FILE", str(canonical_path))
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
            domain_key="imperial-test",
            domain_name="imperialholding.test",
            from_email="info@imperialholding.test",
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
        "recipient_type": "architect_office",
        "recipient_name": "Minta Építésziroda",
        "sender_company_name": "Imperial Holding",
        "reference_names": ["Referencia Ház", "Második Ház"],
        "reference_names_verified": True,
        "recipient_classification_verified": True,
        "exclusion_screening_verified": True,
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


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [(7, 59, False), (8, 0, True), (17, 59, True), (18, 0, False)],
)
def test_outreach_sending_window_is_enforced_in_budapest_time(
    growth_runtime, hour, minute, expected
):
    local_now = datetime(2026, 8, 28, hour, minute, tzinfo=ZoneInfo("Europe/Budapest"))

    assert service._outreach_sending_window_open(local_now.astimezone(UTC)) is expected


def test_dispatch_batch_does_not_claim_outside_sending_window(
    db, growth_runtime, monkeypatch
):
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: False)

    def unexpected_claim(_db):
        raise AssertionError("outreach must not be claimed outside the sending window")

    monkeypatch.setattr(service, "claim_outreach", unexpected_claim)

    assert service.dispatch_batch(db) == 0


def test_outreach_send_capacity_enforces_hourly_and_daily_limits(
    db, growth_runtime, monkeypatch
):
    local_now = datetime(2026, 8, 29, 10, 15, tzinfo=ZoneInfo("Europe/Budapest"))
    monkeypatch.setattr(
        service,
        "_outreach_capacity_usage",
        lambda _db, _now=None: service.OutreachCapacityUsage(
            2, 47, 0, 0, 0, 0, {}
        ),
    )
    assert service._outreach_send_capacity(db, local_now.astimezone(UTC)) == 3

    monkeypatch.setattr(
        service,
        "_outreach_capacity_usage",
        lambda _db, _now=None: service.OutreachCapacityUsage(
            5, 12, 0, 0, 0, 0, {}
        ),
    )
    assert service._outreach_send_capacity(db, local_now.astimezone(UTC)) == 0

    monkeypatch.setattr(
        service,
        "_outreach_capacity_usage",
        lambda _db, _now=None: service.OutreachCapacityUsage(
            1, 50, 0, 0, 0, 0, {}
        ),
    )
    assert service._outreach_send_capacity(db, local_now.astimezone(UTC)) == 0


def test_run_once_dispatches_approved_mail_before_unrelated_pipeline_failure(
    db, growth_runtime, monkeypatch
):
    from app.growth_ops import wide_service

    events = []
    monkeypatch.setattr(service, "dispatch_batch", lambda _db: events.append("mail") or 0)

    def fail_wide_pipeline(_db):
        events.append("wide")
        raise RuntimeError("unrelated pipeline failure")

    monkeypatch.setattr(wide_service, "run_due", fail_wide_pipeline)

    with pytest.raises(RuntimeError, match="unrelated pipeline failure"):
        service.run_once(db)

    assert events == ["mail", "wide"]


def test_readiness_accepts_fresh_degraded_worker_as_serving(db, growth_runtime):
    db.add(
        GrowthWorkerHeartbeat(
            worker_id="growth-test-worker",
            status="degraded",
            detail_json='{"blocking_errors":["unrelated_content_not_complete"]}',
            heartbeat_at=datetime.now(UTC),
        )
    )
    db.commit()

    ready, payload = service.readiness(db)

    assert ready is True
    assert payload["worker_heartbeat"] == "degraded_sla"
    assert payload["worker_status"] == "degraded"


def test_readiness_rejects_stale_degraded_worker(db, growth_runtime):
    db.add(
        GrowthWorkerHeartbeat(
            worker_id="growth-test-worker",
            status="degraded",
            heartbeat_at=datetime.now(UTC) - timedelta(seconds=121),
        )
    )
    db.commit()

    ready, payload = service.readiness(db)

    assert ready is False
    assert payload["worker_heartbeat"] == "stale_or_missing"
    assert payload["worker_status"] == "degraded"


@pytest.mark.parametrize("status", ["starting", "stopped", "failed"])
def test_readiness_rejects_fresh_non_serving_worker_state(db, growth_runtime, status):
    db.add(
        GrowthWorkerHeartbeat(
            worker_id="growth-test-worker",
            status=status,
            heartbeat_at=datetime.now(UTC),
        )
    )
    db.commit()

    ready, payload = service.readiness(db)

    assert ready is False
    assert payload["worker_heartbeat"] == "stale_or_missing"
    assert payload["worker_status"] == status


def test_internal_growth_routes_reject_unauthenticated_requests(client):
    readiness_response = client.get("/api/internal/growth-ops/readiness")
    ingest_response = client.post("/api/internal/growth-ops/signals", json={})

    assert readiness_response.status_code == 401
    assert readiness_response.json() == {"detail": "invalid internal token"}
    assert ingest_response.status_code == 401
    assert ingest_response.json() == {"detail": "invalid internal token"}


def test_growth_readiness_compose_override_only_enables_platform_core():
    override = (
        Path(__file__).resolve().parents[3]
        / "deploy"
        / "remote-test"
        / "docker-compose.growth-readiness.yml"
    )

    assert override.read_text(encoding="utf-8") == (
        "services:\n"
        "  platform-core:\n"
        "    environment:\n"
        '      GROWTH_OPS_ENABLED: "true"\n'
    )


def test_verified_business_role_signal_queues_once(db, growth_runtime):
    first = service.ingest_signal(db, _signal())
    second = service.ingest_signal(db, _signal())

    assert first.status == "queued" and first.outreach_id
    assert second.idempotent and second.outreach_id == first.outreach_id
    assert len(db.scalars(select(GrowthSignal)).all()) == 1
    assert len(db.scalars(select(OutreachMessage)).all()) == 1


def test_verified_sender_accepts_exact_gmail_oauth_profile_evidence(db):
    binding = BrandBinding(
        brand_id="imperial",
        sender_email="info@imperialholding.test",
        domain_key="imperial-gmail-test",
        secret={
            "client_id": "client",
            "client_secret": "secret",
            "refresh_token": "refresh",
            "scope": (
                "https://www.googleapis.com/auth/gmail.compose "
                "https://www.googleapis.com/auth/gmail.readonly"
            ),
        },
        config={},
    )
    db.add(
        MailSendingDomain(
            domain_key=binding.domain_key,
            domain_name="imperialholding.test",
            from_email=binding.sender_email,
            provider="gmail_api",
            spf_status="not_applicable_oauth",
            dkim_status="not_applicable_oauth",
            dmarc_status="not_applicable_oauth",
            verification_evidence_json=json.dumps(
                {
                    "verification_method": "gmail_oauth_profile",
                    "profile_email": binding.sender_email,
                }
            ),
            verified_at=datetime.now(UTC),
            active=True,
        )
    )
    db.commit()

    assert service._verified_sender(db, binding).provider == "gmail_api"


def test_verified_sender_rejects_gmail_oauth_profile_mismatch(db):
    binding = BrandBinding(
        brand_id="imperial",
        sender_email="info@imperialholding.test",
        domain_key="imperial-gmail-mismatch-test",
        secret={
            "client_id": "client",
            "client_secret": "secret",
            "refresh_token": "refresh",
            "scope": (
                "https://www.googleapis.com/auth/gmail.send "
                "https://www.googleapis.com/auth/gmail.readonly"
            ),
        },
        config={},
    )
    db.add(
        MailSendingDomain(
            domain_key=binding.domain_key,
            domain_name="imperialholding.test",
            from_email=binding.sender_email,
            provider="gmail_api",
            verification_evidence_json=json.dumps(
                {
                    "verification_method": "gmail_oauth_profile",
                    "profile_email": "other@imperialholding.test",
                }
            ),
            verified_at=datetime.now(UTC),
            active=True,
        )
    )
    db.commit()

    with pytest.raises(
        GrowthRegistryError,
        match="Gmail OAuth sender profile is not verified",
    ):
        service._verified_sender(db, binding)


def test_queued_payload_is_bound_to_the_canonical_registry(db, growth_runtime):
    result = service.ingest_signal(db, _signal())
    message = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == result.outreach_id)
    )
    assert message is not None and len(message.unsubscribe_token_hash) == 64
    assert message.subject == "együttműködés"
    assert message.body_text.startswith("Tisztelt Minta Építésziroda!")
    assert "Referencia Ház, Második Ház" in message.body_text
    assert "Szeretnénk felajánlani szakmai segítségünket" not in message.body_text
    metadata = service._canonical_metadata(message)
    assert metadata["template_id"] == "ARCHITECT_OFFICE_FIRST_CONTACT_HU"
    assert metadata["registry_sha256"]
    assert service._payload_matches(message)
    assert service._canonical_metadata_sha256(metadata)


def test_canonical_metadata_tampering_invalidates_payload_and_release(
    db, growth_runtime
):
    result = service.ingest_signal(
        db, _signal(external_key="ETDR-CANONICAL-METADATA-TAMPER")
    )
    message = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == result.outreach_id)
    )
    assert message is not None
    service.release_outreach(
        db,
        message.outreach_id,
        OutreachReleaseIn(
            approved_by="owner@test",
            inspected_payload_sha256=message.payload_sha256,
            approval_note="Exact canonical payload inspected and approved.",
        ),
    )
    assert service._release_matches(message)

    receipt = json.loads(message.receipt_json)
    receipt["canonical_template"]["render_input"]["screening_values"][0] = (
        "Tampered recipient"
    )
    message.receipt_json = service.canonical_json(receipt)

    assert not service._payload_matches(message)
    assert not service._release_matches(message)


@pytest.mark.parametrize(
    ("field", "replacement", "error"),
    [
        (
            "idempotency_key",
            "0" * 64,
            "outreach_idempotency_key_binding_mismatch",
        ),
        (
            "unsubscribe_token_hash",
            "0" * 64,
            "canonical_unsubscribe_token_binding_mismatch",
        ),
    ],
)
def test_operational_delivery_binding_tampering_invalidates_payload_and_release(
    db,
    growth_runtime,
    field,
    replacement,
    error,
):
    result = service.ingest_signal(
        db, _signal(external_key=f"ETDR-OPERATIONAL-TAMPER-{field}")
    )
    message = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == result.outreach_id)
    )
    assert message is not None
    service.release_outreach(
        db,
        message.outreach_id,
        OutreachReleaseIn(
            approved_by="owner@test",
            inspected_payload_sha256=message.payload_sha256,
            approval_note="Exact canonical payload inspected and approved.",
        ),
    )
    assert service._payload_matches(message)
    assert service._release_matches(message)

    setattr(message, field, replacement)

    assert not service._payload_matches(message)
    assert not service._release_matches(message)
    with pytest.raises(GrowthRegistryError, match=error):
        service._assert_canonical_payload(message)


def test_release_rejects_current_signal_leier_affiliation(db, growth_runtime):
    result = service.ingest_signal(
        db, _signal(external_key="ETDR-CURRENT-LEIER-RELEASE")
    )
    message = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == result.outreach_id)
    )
    signal = db.scalar(
        select(GrowthSignal).where(GrowthSignal.signal_id == result.signal_id)
    )
    assert message is not None and signal is not None
    signal.recipient_organization_name = "Leier Hungária"

    with pytest.raises(
        GrowthRegistryError,
        match="canonical_hard_gate_blocked:BLOCK_LEIER_INCIDENT_CONTAINMENT",
    ):
        service.release_outreach(
            db,
            message.outreach_id,
            OutreachReleaseIn(
                approved_by="owner@test",
                inspected_payload_sha256=message.payload_sha256,
                approval_note="Exact canonical payload inspected and approved.",
            ),
        )


def test_release_rejects_current_signal_screening_drift(db, growth_runtime):
    result = service.ingest_signal(
        db, _signal(external_key="ETDR-CURRENT-SCREENING-DRIFT")
    )
    message = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == result.outreach_id)
    )
    signal = db.scalar(
        select(GrowthSignal).where(GrowthSignal.signal_id == result.signal_id)
    )
    assert message is not None and signal is not None
    signal.summary = "The current screening facts changed after the message was queued."

    with pytest.raises(
        GrowthRegistryError,
        match="canonical_screening_values_changed_after_queue",
    ):
        service.release_outreach(
            db,
            message.outreach_id,
            OutreachReleaseIn(
                approved_by="owner@test",
                inspected_payload_sha256=message.payload_sha256,
                approval_note="Exact canonical payload inspected and approved.",
            ),
        )


def test_dispatch_blocks_current_signal_leier_affiliation(
    db, growth_runtime, monkeypatch
):
    result = service.ingest_signal(
        db, _signal(external_key="ETDR-CURRENT-LEIER-DISPATCH")
    )
    message = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == result.outreach_id)
    )
    signal = db.scalar(
        select(GrowthSignal).where(GrowthSignal.signal_id == result.signal_id)
    )
    assert message is not None and signal is not None
    service.release_outreach(
        db,
        message.outreach_id,
        OutreachReleaseIn(
            approved_by="owner@test",
            inspected_payload_sha256=message.payload_sha256,
            approval_note="Exact canonical payload inspected and approved.",
        ),
    )
    signal.recipient_organization_name = "Leier Hungária"
    message.status = "claimed"
    message.claimed_by = service.settings().worker_id
    message.claimed_at = datetime.now(UTC)
    message.lease_expires_at = message.claimed_at + timedelta(minutes=5)
    message.attempt_count = 1
    db.commit()
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)

    dispatched = service.dispatch_outreach(db, message)

    assert dispatched.status == "blocked"
    assert (
        dispatched.last_error
        == "canonical_hard_gate_blocked:BLOCK_LEIER_INCIDENT_CONTAINMENT"
    )
    assert signal.status == "blocked"


def test_dispatch_holds_gmail_accepted_unverified_without_second_send(
    db,
    growth_runtime,
    monkeypatch,
):
    result = service.ingest_signal(
        db, _signal(external_key="ETDR-GMAIL-PENDING-VERIFICATION")
    )
    message = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == result.outreach_id)
    )
    assert message is not None
    service.release_outreach(
        db,
        message.outreach_id,
        OutreachReleaseIn(
            approved_by="owner@test",
            inspected_payload_sha256=message.payload_sha256,
            approval_note="Exact canonical payload inspected and approved.",
        ),
    )
    message.status = "claimed"
    message.claimed_by = "growth-test-worker"
    message.claimed_at = datetime.now(UTC)
    message.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    message.attempt_count = 1
    db.commit()

    sends = 0

    class AcceptedUnverifiedAdapter:
        def __init__(self, _binding):
            pass

        def send(self, **_kwargs):
            nonlocal sends
            sends += 1
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
                provider_message_id="gmail-provider-id",
                detail={"reason": "gmail_readback_plain_body_mismatch"},
            )

    kill_switch_trips = 0

    def fake_trip():
        nonlocal kill_switch_trips
        kill_switch_trips += 1
        return True

    monkeypatch.setattr(service, "SMTPEmailAdapter", AcceptedUnverifiedAdapter)
    monkeypatch.setattr(service, "_trip_runtime_kill_switch", fake_trip)
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)

    first = service.dispatch_outreach(db, message)
    second = service.dispatch_outreach(db, message)

    receipt = json.loads(first.receipt_json)
    assert first.status == "claimed"
    assert first.last_error == "accepted_but_unverified"
    assert first.provider_message_id == "gmail-provider-id"
    assert first.claimed_by is None and first.lease_expires_at is None
    assert receipt["delivery_verification"]["status"] == "pending_verification"
    assert receipt["delivery_verification"]["retry_safe"] is False
    assert second.status == "claimed"
    assert sends == 1
    assert kill_switch_trips == 1


def test_expired_claim_is_held_pending_verification_and_never_requeued(
    db,
    growth_runtime,
    monkeypatch,
):
    kill_switch_trips = 0

    def fake_trip():
        nonlocal kill_switch_trips
        kill_switch_trips += 1
        return True

    monkeypatch.setattr(service, "_trip_runtime_kill_switch", fake_trip)
    result = service.ingest_signal(db, _signal(external_key="ETDR-EXPIRED-CLAIM"))
    message = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == result.outreach_id)
    )
    assert message is not None
    message.status = "claimed"
    message.claimed_by = "crashed-worker"
    message.claimed_at = datetime.now(UTC) - timedelta(minutes=10)
    message.lease_expires_at = datetime.now(UTC) - timedelta(minutes=5)
    message.attempt_count = 1
    db.commit()

    service._release_expired_claims(db)

    receipt = json.loads(message.receipt_json)
    assert message.status == "claimed"
    assert message.claimed_by is None and message.lease_expires_at is None
    assert receipt["delivery_verification"]["status"] == "pending_verification"
    assert receipt["delivery_verification"]["retry_safe"] is False
    assert receipt["delivery_verification"]["detail"] == {
        "reason": "worker_lease_expired_delivery_ambiguous"
    }
    assert kill_switch_trips == 1

    message.claimed_by = "verification-worker"
    message.claimed_at = datetime.now(UTC) - timedelta(minutes=10)
    message.lease_expires_at = datetime.now(UTC) - timedelta(minutes=5)

    service._release_expired_claims(db)

    assert message.status == "claimed"
    assert message.claimed_by is None and message.lease_expires_at is None
    assert service._delivery_verification_pending(message)
    assert kill_switch_trips == 1


def test_verified_referral_partner_queues_only_the_canonical_locked_template(
    db, growth_runtime
):
    result = service.ingest_signal(
        db,
        _signal(
            external_key="PARTNER-2026-0001",
            recipient_type="referral_partner",
            recipient_name="Kovács Anna",
            sender_company_name=None,
            reference_names=[],
            reference_names_verified=False,
            business_context="építőanyag-áruházi hálózat",
            business_context_verified=True,
            business_context_evidence_url="https://minta-epito.test/uzleteink",
        ),
    )
    message = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == result.outreach_id)
    )

    assert result.status == "queued"
    assert message is not None
    assert message.subject == "együttműködés"
    assert message.body_text.startswith("Tisztelt Kovács Anna!\n\nCégünk 1989 óta")
    assert "Az Önök építőanyag-áruházi hálózat vásárlói között" in message.body_text
    assert "1% új bevétel" not in message.subject
    assert "a teljes 1% jutalékot" not in message.body_text
    metadata = service._canonical_metadata(message)
    assert metadata["template_id"] == "REFERRAL_PARTNER_FIRST_CONTACT_HU"
    assert metadata["body_html"].count("<strong>") == 2


def test_referral_partner_without_verified_business_context_is_recorded_for_completion(
    db, growth_runtime
):
    result = service.ingest_signal(
        db,
        _signal(
            external_key="PARTNER-2026-0002",
            recipient_type="referral_partner",
            recipient_name="Kovács Anna",
            sender_company_name=None,
            reference_names=[],
            reference_names_verified=False,
        ),
    )

    assert result.status == "template-variable-missing"
    assert result.reasons == ["template-variable-missing"]
    assert not db.scalars(select(OutreachMessage)).all()


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


def test_public_building_plot_listing_allows_verified_listing_agent():
    signal = _signal(
        external_key="LAND-listing_agent",
        signal_type="residential_building_plot",
        company_name="Nyilvános hirdető",
        company_registration_id=None,
        subject_type="organization",
        recipient_role="listing_agent",
        recipient_type="real_estate_agent",
        recipient_name="Nyilvános hirdető",
        sender_company_name=None,
        reference_names=[],
        reference_names_verified=False,
        recipient_classification_verified=True,
        exclusion_screening_verified=True,
        recipient_email="hirdeto@example.test",
        recipient_email_type="role",
        contact_basis="public_property_listing",
        public_contact_url="https://property-listing.example.test/LAND-001",
        evidence_url="https://property-listing.example.test/LAND-001",
    )

    assert service._eligibility(signal, score=90) == []


def test_public_building_plot_listing_allows_verified_owner():
    signal = _signal(
        external_key="LAND-property_owner",
        signal_type="residential_building_plot",
        company_name="Nyilvános hirdető",
        company_registration_id=None,
        subject_type="natural_person",
        recipient_role="property_owner",
        recipient_type="land_owner",
        recipient_name="Nyilvános hirdető",
        sender_company_name=None,
        reference_names=[],
        reference_names_verified=False,
        recipient_classification_verified=True,
        exclusion_screening_verified=True,
        recipient_email="hirdeto@example.test",
        recipient_email_type="named",
        contact_basis="public_property_listing",
        public_contact_url="https://property-listing.example.test/LAND-001",
        location="Sülysáp",
        plot_size_sqm=605,
        evidence_url="https://property-listing.example.test/LAND-001",
    )

    assert service._land_agent_gate_reason(signal) is None
    assert service._eligibility(signal, score=90) == []


def test_public_building_plot_listing_allows_named_natural_person_agent():
    signal = _signal(
        external_key="LAND-natural-person-listing-agent",
        signal_type="residential_building_plot",
        company_name="Minta Értékesítő",
        company_registration_id=None,
        recipient_organization_name="Független Ingatlaniroda",
        subject_type="natural_person",
        recipient_role="listing_agent",
        recipient_type="real_estate_agent",
        recipient_name="Minta Értékesítő",
        sender_company_name=None,
        reference_names=[],
        reference_names_verified=False,
        recipient_classification_verified=True,
        exclusion_screening_verified=True,
        recipient_email="minta.ertekesito@example.test",
        recipient_email_type="named",
        contact_basis="public_property_listing",
        public_contact_url="https://property-listing.example.test/LAND-NAMED-AGENT",
        evidence_url="https://property-listing.example.test/LAND-NAMED-AGENT",
    )

    assert service._land_agent_gate_reason(signal) is None
    assert service._eligibility(signal, score=90) == []


@pytest.mark.parametrize(
    ("recipient_role", "recipient_type", "subject_type", "recipient_email_type"),
    [
        ("property_owner", "land_owner", "natural_person", "named"),
        ("listing_agent", "real_estate_agent", "natural_person", "named"),
    ],
)
def test_public_building_plot_listing_auto_releases_single_initial_message(
    db,
    growth_runtime,
    recipient_role,
    recipient_type,
    subject_type,
    recipient_email_type,
):
    result = service.ingest_signal(
        db,
        _signal(
            external_key=f"LAND-AUTO-RELEASE-{recipient_role}",
            signal_type="residential_building_plot",
            company_name="Minta Hirdető",
            company_registration_id=None,
            recipient_organization_name=(
                "Független Ingatlaniroda" if recipient_role == "listing_agent" else None
            ),
            subject_type=subject_type,
            recipient_role=recipient_role,
            recipient_type=recipient_type,
            recipient_name="Minta Hirdető",
            sender_company_name=None,
            reference_names=[],
            reference_names_verified=False,
            recipient_classification_verified=True,
            exclusion_screening_verified=True,
            recipient_email=f"{recipient_role}@example.test",
            recipient_email_type=recipient_email_type,
            contact_basis="public_property_listing",
            public_contact_url=(
                f"https://property-listing.example.test/AUTO-{recipient_role}"
            ),
            location="Sülysáp",
            plot_size_sqm=605,
            evidence_url=f"https://property-listing.example.test/AUTO-{recipient_role}",
        ),
    )
    message = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == result.outreach_id)
    )

    assert result.status == "queued"
    assert message is not None
    assert message.sequence_step == 0
    assert message.release_approved_by == (
        "owner-policy:land-public-listing-v3:2026-08-28"
    )
    assert message.release_approved_at is not None
    assert message.release_token_hash


def test_public_building_plot_owner_vs_agent_mismatch_fails_closed():
    signal = _signal(
        external_key="LAND-RECIPIENT-TYPE-MISMATCH",
        signal_type="residential_building_plot",
        company_name="Nyilvános hirdető",
        company_registration_id=None,
        subject_type="organization",
        recipient_role="listing_agent",
        recipient_type="land_owner",
        recipient_name="Nyilvános hirdető",
        sender_company_name=None,
        reference_names=[],
        reference_names_verified=False,
        recipient_classification_verified=True,
        exclusion_screening_verified=True,
        recipient_email="hirdeto@example.test",
        recipient_email_type="role",
        contact_basis="public_property_listing",
        public_contact_url="https://property-listing.example.test/LAND-002",
        evidence_url="https://property-listing.example.test/LAND-002",
    )

    assert "land_recipient_role_type_mismatch_no_send" in service._eligibility(
        signal, score=90
    )


def test_public_building_plot_uses_only_the_canonical_registry_template(
    db, growth_runtime
):
    result = service.ingest_signal(
        db,
        _signal(
            external_key="LAND-CANONICAL-AGENT",
            signal_type="residential_building_plot",
            company_name="Minta Értékesítő",
            company_registration_id=None,
            recipient_organization_name="Független Ingatlaniroda",
            subject_type="organization",
            recipient_role="listing_agent",
            recipient_type="real_estate_agent",
            recipient_name="Minta Értékesítő",
            sender_company_name=None,
            reference_names=[],
            reference_names_verified=False,
            recipient_classification_verified=True,
            exclusion_screening_verified=True,
            recipient_email="ertekesito@example.test",
            recipient_email_type="role",
            contact_basis="public_property_listing",
            public_contact_url="https://property-listing.example.test/LAND-003",
            evidence_url="https://property-listing.example.test/LAND-003",
        ),
    )
    message = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == result.outreach_id)
    )
    metadata = service._canonical_metadata(message)

    assert result.status == "queued"
    assert metadata["template_id"] == "REAL_ESTATE_AGENT_FIRST_CONTACT_HU"
    assert metadata["recipient_type"] == "real_estate_agent"
    assert "template_policy" not in metadata
    assert message.body_text.startswith("Tisztelt Minta Értékesítő!\nCégünk, az Imperial Holding")


def test_land_auto_release_failure_cannot_leave_a_partial_queued_message(
    db, growth_runtime, monkeypatch
):
    def fail_release(*_args, **_kwargs):
        raise GrowthRegistryError("IMPERIAL_RELEASE_HMAC_KEY is not configured")

    monkeypatch.setattr(service, "_release_digest", fail_release)
    result = service.ingest_signal(
        db,
        _signal(
            external_key="LAND-RELEASE-FAIL-NO-PARTIAL",
            signal_type="residential_building_plot",
            company_name="Minta Értékesítő",
            company_registration_id=None,
            recipient_organization_name="Független Ingatlaniroda",
            subject_type="organization",
            recipient_role="listing_agent",
            recipient_type="real_estate_agent",
            recipient_name="Minta Értékesítő",
            sender_company_name=None,
            reference_names=[],
            reference_names_verified=False,
            recipient_email="release-fail@example.test",
            recipient_email_type="role",
            contact_basis="public_property_listing",
            public_contact_url="https://property.example.test/release-fail",
            evidence_url="https://property.example.test/release-fail",
        ),
    )

    assert result.status == "blocked"
    assert not db.scalars(select(OutreachMessage)).all()


def test_land_copy_assertion_failure_cannot_leave_a_partial_queued_message(
    db, growth_runtime, monkeypatch
):
    def fail_copy(_body):
        raise ValueError("forced_copy_integrity_failure")

    monkeypatch.setattr(service, "assert_outreach_copy", fail_copy)
    result = service.ingest_signal(
        db,
        _signal(
            external_key="LAND-COPY-FAIL-NO-PARTIAL",
            signal_type="residential_building_plot",
            company_name="Minta Értékesítő",
            company_registration_id=None,
            recipient_organization_name="Független Ingatlaniroda",
            subject_type="organization",
            recipient_role="listing_agent",
            recipient_type="real_estate_agent",
            recipient_name="Minta Értékesítő",
            sender_company_name=None,
            reference_names=[],
            reference_names_verified=False,
            recipient_email="copy-fail@example.test",
            recipient_email_type="role",
            contact_basis="public_property_listing",
            public_contact_url="https://property.example.test/copy-fail",
            evidence_url="https://property.example.test/copy-fail",
        ),
    )

    assert result.status == "blocked"
    assert not db.scalars(select(OutreachMessage)).all()


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"contact_name": "Turczer József"}, LAND_AGENT_HARD_GATE_TURCZER),
        ({"contact_name": "József Turczer"}, LAND_AGENT_HARD_GATE_TURCZER),
        ({"recipient_email": "jozsef.turczer@example.test"}, LAND_AGENT_HARD_GATE_TURCZER),
        ({"organization_name": "GDN Ingatlanhálózat"}, LAND_AGENT_HARD_GATE_GDN),
        (
            {"public_contact_url": "https://gdn-ingatlan.hu/ingatlan/123"},
            LAND_AGENT_HARD_GATE_GDN,
        ),
        (
            {"public_contact_url": "https://g-d-n.hu/ingatlan/123"},
            LAND_AGENT_HARD_GATE_GDN,
        ),
        (
            {
                "organization_name": "Otthon Centrum",
                "office_name": "II. kerület - Bem rakpart",
            },
            LAND_AGENT_HARD_GATE_OC_II_XII,
        ),
        (
            {"organization_name": "Otthon Centrum", "office_name": "II. kerület - TDG"},
            LAND_AGENT_HARD_GATE_OC_II_XII,
        ),
        (
            {
                "organization_name": "Otthon Centrum",
                "office_name": "II/A kerület - Hidegkúti út",
            },
            LAND_AGENT_HARD_GATE_OC_II_XII,
        ),
        (
            {
                "organization_name": "Otthon Centrum",
                "office_name": "II/A. kerületi iroda",
            },
            LAND_AGENT_HARD_GATE_OC_II_XII,
        ),
        (
            {
                "organization_name": "Otthon Centrum",
                "office_name": "II. kerületi iroda",
            },
            LAND_AGENT_HARD_GATE_OC_II_XII,
        ),
        (
            {
                "organization_name": "Otthon Centrum",
                "office_name": "XII. kerületi iroda",
            },
            LAND_AGENT_HARD_GATE_OC_II_XII,
        ),
        (
            {
                "organization_name": "Otthon Centrum",
                "office_name": "2/A kerületi iroda",
                "public_contact_url": "https://oc.hu/iroda/2-a",
            },
            LAND_AGENT_HARD_GATE_OC_II_XII,
        ),
        (
            {
                "organization_name": "Otthon Centrum",
                "office_name": "II. kerület - Lajos utca",
            },
            LAND_AGENT_HARD_GATE_OC_II_XII,
        ),
        (
            {
                "organization_name": "Otthon Centrum",
                "office_name": "II. kerület - Ürömi utca",
            },
            LAND_AGENT_HARD_GATE_OC_II_XII,
        ),
        (
            {
                "organization_name": "Otthon Centrum",
                "office_name": "XII. kerület - MOM Park",
            },
            LAND_AGENT_HARD_GATE_OC_II_XII,
        ),
        (
            {
                "organization_name": "Otthon Centrum",
                "office_name": "XII. kerület - Városmajor utca",
            },
            LAND_AGENT_HARD_GATE_OC_II_XII,
        ),
        (
            {"organization_name": "Otthon Centrum", "office_name": None},
            LAND_AGENT_HARD_GATE_OC_UNVERIFIED,
        ),
        ({"organization_name": None}, LAND_AGENT_HARD_GATE_AFFILIATION_UNVERIFIED),
    ],
)
def test_land_agent_named_network_and_office_hard_gates(changes, expected):
    values = {
        "recipient_role": "listing_agent",
        "contact_name": "Minta Értékesítő",
        "organization_name": "Független Ingatlaniroda",
        "office_name": None,
        "recipient_email": "ertekesito@example.test",
        "public_contact_url": "https://property.example.test/listing/123",
        "evidence_url": "https://property.example.test/listing/123",
    }
    values.update(changes)

    assert land_agent_hard_gate_reason(**values) == expected


def test_land_agent_gate_allows_verified_nonblocked_office_and_does_not_cover_owner():
    values = {
        "recipient_role": "listing_agent",
        "contact_name": "Minta Értékesítő",
        "organization_name": "Otthon Centrum",
        "office_name": "XI. kerület - Bartók Béla út",
        "recipient_email": "ertekesito@oc.hu",
        "public_contact_url": "https://www.oc.hu/iroda/xi-kerulet-bartok-bela-ut",
        "evidence_url": "https://www.oc.hu/ingatlanok/UAT123",
    }
    assert land_agent_hard_gate_reason(**values) is None

    values.update(
        recipient_role="property_owner",
        contact_name="Turczer József",
        organization_name="GDN Ingatlanhálózat",
    )
    assert land_agent_hard_gate_reason(**values) is None


def test_land_agent_gdn_gate_blocks_before_storage(db, growth_runtime):
    signal = _signal(
        external_key="LAND-GDN-HARD-GATE",
        signal_type="residential_building_plot",
        company_name="Minta Értékesítő",
        company_registration_id=None,
        recipient_organization_name="GDN Ingatlanhálózat",
        subject_type="natural_person",
        recipient_role="listing_agent",
        recipient_email="ertekesito@gdn-ingatlan.hu",
        recipient_email_type="named",
        contact_basis="public_property_listing",
        public_contact_url="https://gdn-ingatlan.hu/ingatlan/123",
        evidence_url="https://gdn-ingatlan.hu/ingatlan/123",
    )

    with pytest.raises(GrowthRegistryError, match=LAND_AGENT_HARD_GATE_GDN):
        service.ingest_signal(db, signal)

    assert not db.scalars(select(GrowthSignal)).all()


def test_motor_skips_blocked_agent_and_continues_same_source_batch(
    db, growth_runtime, monkeypatch
):
    blocked = _signal(
        external_key="LAND-GDN-BATCH",
        signal_type="residential_building_plot",
        company_name="Minta GDN Értékesítő",
        company_registration_id=None,
        recipient_organization_name="GDN Ingatlanhálózat",
        subject_type="natural_person",
        recipient_role="listing_agent",
        recipient_email="batch@gdn-ingatlan.hu",
        recipient_email_type="named",
        contact_basis="public_property_listing",
        public_contact_url="https://gdn-ingatlan.hu/ingatlan/BATCH",
        evidence_url="https://gdn-ingatlan.hu/ingatlan/BATCH",
    )
    accepted = _signal(external_key="ETDR-2026-AFTER-HARD-GATE")
    growth_runtime.sources_for = lambda motor_key: [("construction-etdr", {"enabled": True})]
    monkeypatch.setattr(
        service,
        "fetch_source",
        lambda *_args, **_kwargs: SourceBatch(signals=[blocked, accepted], raw_count=2),
    )

    run = service.run_motor(db, "construction")

    assert run.status == "completed"
    assert run.raw_signals == 2
    assert run.accepted_signals == 1
    assert run.queued_outreach == 1
    source_result = json.loads(run.source_results_json)[0]
    assert source_result["hard_gate_blocked"] == 1


def test_motor_skips_canonical_leier_gate_and_continues_same_source_batch(
    db, growth_runtime, monkeypatch
):
    blocked = _signal(
        external_key="ETDR-LEIER-BATCH",
        company_name="Leier Hungária",
        evidence_url="https://source.test/etdr/LEIER-BATCH",
    )
    accepted = _signal(
        external_key="ETDR-SAFE-AFTER-GATE",
        evidence_url="https://source.test/etdr/SAFE-AFTER-GATE",
    )
    growth_runtime.sources_for = lambda motor_key: [
        ("construction-etdr", {"enabled": True})
    ]
    monkeypatch.setattr(
        service,
        "fetch_source",
        lambda *_args, **_kwargs: SourceBatch(
            signals=[blocked, accepted], raw_count=2
        ),
    )

    run = service.run_motor(db, "construction")

    assert run.status == "completed"
    assert run.raw_signals == 2
    assert run.accepted_signals == 1
    assert run.queued_outreach == 1
    source_result = json.loads(run.source_results_json)[0]
    assert source_result["hard_gate_blocked"] == 1


def test_new_duplicate_leier_affiliation_blocks_the_existing_released_outreach(
    db, growth_runtime, monkeypatch
):
    first = service.ingest_signal(
        db,
        _signal(external_key="ETDR-DUPLICATE-NEW-LEIER"),
    )
    outreach = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == first.outreach_id)
    )
    assert outreach is not None and outreach.status == "queued"

    newly_blocked = _signal(
        external_key="ETDR-DUPLICATE-NEW-LEIER",
        recipient_organization_name="Leier Hungária",
        source_payload_hash=hashlib.sha256(b"new-leier-evidence").hexdigest(),
    )
    with pytest.raises(
        GrowthRegistryError,
        match="canonical_hard_gate_blocked:BLOCK_LEIER_INCIDENT_CONTAINMENT",
    ):
        service.ingest_signal(db, newly_blocked)

    db.refresh(outreach)
    signal = db.scalar(
        select(GrowthSignal).where(GrowthSignal.signal_id == outreach.signal_id)
    )
    assert outreach.status == "blocked"
    assert "BLOCK_LEIER_INCIDENT_CONTAINMENT" in str(outreach.last_error)
    assert signal is not None and signal.status == "blocked"
    assert signal.recipient_organization_name == "Leier Hungária"

    class NetworkMustNotRun:
        def __init__(self, *_args, **_kwargs):
            pytest.fail("hard-gated duplicate reached the email transport")

    monkeypatch.setattr(service, "SMTPEmailAdapter", NetworkMustNotRun)
    result = service.dispatch_outreach(db, outreach)
    assert result.status == "blocked"
    db.close()
    with SessionLocal() as fresh_db:
        durable = fresh_db.scalar(
            select(OutreachMessage).where(
                OutreachMessage.outreach_id == outreach.outreach_id
            )
        )
        assert durable is not None and durable.status == "blocked"


def test_global_suppression_prevents_queue(db, growth_runtime):
    db.add(MailSuppression(email="iroda@minta-epito.test", reason="unsubscribe", active=True))
    db.commit()

    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0003"))

    assert result.status == "suppressed"
    assert not db.scalars(select(OutreachMessage)).all()


def test_invalid_source_binding_fails_closed(db, growth_runtime):
    with pytest.raises(GrowthRegistryError, match="source mismatch"):
        service.ingest_signal(db, _signal(source_bucket="public_request"))
    assert not db.scalars(select(GrowthSignal)).all()
    assert not db.scalars(select(OutreachMessage)).all()


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


@pytest.mark.parametrize(
    "recipient_email",
    [
        "safe@example.test,info@leier.hu",
        "safe@example.test, info@leier.hu",
        "Safe Person <safe@example.test>",
        "safe,other@example.test",
    ],
)
def test_signal_schema_requires_one_plain_addr_spec(recipient_email):
    with pytest.raises(ValidationError, match="Invalid recipient email address"):
        _signal(recipient_email=recipient_email)


def test_smtp_adapter_sends_internal_html_as_multipart_alternative(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, username, password):
            assert (username, password) == ("test", "test")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def send_message(self, message, **kwargs):
            sent["message"] = message
            return {}

    monkeypatch.setattr("app.growth_ops.email.smtplib.SMTP_SSL", FakeSMTP)
    base_binding = FakeRegistry().brand_binding("imperial")
    binding = BrandBinding(
        brand_id=base_binding.brand_id,
        sender_email="info@imperialholding.hu",
        domain_key=base_binding.domain_key,
        secret=base_binding.secret,
        config=base_binding.config,
    )

    SMTPEmailAdapter(binding).send(
        delivery_scope="internal",
        to_email="partner@imperialholding.hu",
        subject="ház eladásában kérnék segítséget",
        body_text="Az Imperial Holding 2,5% jutalékot fizet.",
        body_html=(
            "<p>Az Imperial Holding <strong>2,5% jutalékot fizet.</strong></p>"
        ),
        idempotency_key="a" * 64,
    )

    message = sent["message"]
    assert message.get_content_type() == "multipart/alternative"
    assert "2,5% jutalékot fizet." in message.get_body(("plain",)).get_content()
    assert "<strong>2,5% jutalékot fizet.</strong>" in message.get_body(
        ("html",)
    ).get_content()


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        (
            {"to_email": "info@leier.hu"},
            "outbound_recipient_hard_gate_no_send:BLOCK_LEIER_INCIDENT_CONTAINMENT",
        ),
        (
            {"to_email": "sales@eu.leier.hu"},
            "outbound_recipient_hard_gate_no_send:BLOCK_LEIER_INCIDENT_CONTAINMENT",
        ),
        (
            {"body_text": "Imperial Holding / Prefab.hu közös ajánlat"},
            "cross_brand_customer_facing_content_no_send:Prefab.hu",
        ),
        (
            {"reply_to": "info@prefab.hu"},
            "outbound_reply_to_brand_mismatch_no_send",
        ),
    ],
)
def test_smtp_adapter_brand_and_incident_gates_block_before_transport(changes, error):
    base_binding = FakeRegistry().brand_binding("imperial")
    binding = BrandBinding(
        brand_id="imperial",
        sender_email="info@imperialholding.hu",
        domain_key=base_binding.domain_key,
        secret=base_binding.secret,
        config=base_binding.config,
    )
    payload = {
        "to_email": "partner@example.test",
        "subject": "együttműködés",
        "body_text": "Az Imperial Holding ajánlata.",
        "body_html": "<p>Az Imperial Holding ajánlata.</p>",
        "idempotency_key": "b" * 64,
        "reply_to": "info@imperialholding.hu",
        "delivery_scope": "external_customer",
    }
    payload.update(changes)

    with pytest.raises(GrowthRegistryError, match=re.escape(error)):
        SMTPEmailAdapter(binding).send(**payload)


def test_smtp_adapter_rejects_sender_domain_brand_binding_mismatch():
    base_binding = FakeRegistry().brand_binding("imperial")
    binding = BrandBinding(
        brand_id="prefab",
        sender_email="info@imperialholding.hu",
        domain_key=base_binding.domain_key,
        secret=base_binding.secret,
        config=base_binding.config,
    )

    with pytest.raises(
        GrowthRegistryError,
        match="outbound_sender_brand_binding_mismatch_no_send",
    ):
        SMTPEmailAdapter(binding).send(
            delivery_scope="external_customer",
            to_email="partner@example.test",
            subject="együttműködés",
            body_text="Az Imperial Holding ajánlata.",
            idempotency_key="c" * 64,
        )


def test_rss_timestamp_accepts_standard_rfc_2822_date():
    value = _timestamp("Sun, 16 Aug 2026 06:15:00 +0000")
    assert value == datetime(2026, 8, 16, 6, 15, tzinfo=UTC)
