from __future__ import annotations

import hashlib
import json
import re
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

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
from app.growth_ops.email import SMTPEmailAdapter
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
    brands = {"imperial": {}}

    def validate_signal_source(self, *, source_id: str, motor_key: str, source_bucket: str) -> None:
        if (source_id, motor_key, source_bucket) != (
            "construction-etdr",
            "construction",
            "etdr",
        ):
            raise GrowthRegistryError("source mismatch")

    def brand_for(self, signal_type: str, requested: str | None = None) -> str:
        if signal_type != "residential_construction" or requested not in {None, "imperial"}:
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


def test_verified_business_role_signal_queues_once(db, growth_runtime):
    first = service.ingest_signal(db, _signal())
    second = service.ingest_signal(db, _signal())

    assert first.status == "queued" and first.outreach_id
    assert second.idempotent and second.outreach_id == first.outreach_id
    assert len(db.scalars(select(GrowthSignal)).all()) == 1
    assert len(db.scalars(select(OutreachMessage)).all()) == 1


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


@pytest.mark.parametrize("recipient_role", ["listing_agent", "property_owner"])
def test_public_building_plot_listing_allows_named_recipient(recipient_role):
    signal = _signal(
        external_key=f"LAND-{recipient_role}",
        signal_type="residential_building_plot",
        company_name="Nyilvános hirdető",
        company_registration_id=None,
        subject_type="natural_person",
        recipient_role=recipient_role,
        recipient_email="hirdeto@example.test",
        recipient_email_type="named",
        contact_basis="public_property_listing",
        public_contact_url="https://property-listing.example.test/LAND-001",
        evidence_url="https://property-listing.example.test/LAND-001",
    )

    assert service._eligibility(signal, score=90) == []


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"contact_name": "Turczer József"}, LAND_AGENT_HARD_GATE_TURCZER),
        ({"recipient_email": "jozsef.turczer@example.test"}, LAND_AGENT_HARD_GATE_TURCZER),
        ({"organization_name": "GDN Ingatlanhálózat"}, LAND_AGENT_HARD_GATE_GDN),
        (
            {"public_contact_url": "https://gdn-ingatlan.hu/ingatlan/123"},
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


def test_smtp_adapter_sends_reviewed_html_as_multipart_alternative(monkeypatch):
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
    binding = FakeRegistry().brand_binding("imperial")

    SMTPEmailAdapter(binding).send(
        to_email="partner@example.test",
        subject="ház eladásában kérnék segítséget",
        body_text="2,5% jutalékot fizetünk.",
        body_html="<p><strong>2,5% jutalékot fizetünk.</strong></p>",
        idempotency_key="a" * 64,
    )

    message = sent["message"]
    assert message.get_content_type() == "multipart/alternative"
    assert "2,5% jutalékot fizetünk." in message.get_body(("plain",)).get_content()
    assert "<strong>2,5% jutalékot fizetünk.</strong>" in message.get_body(
        ("html",)
    ).get_content()


def test_rss_timestamp_accepts_standard_rfc_2822_date():
    value = _timestamp("Sun, 16 Aug 2026 06:15:00 +0000")
    assert value == datetime(2026, 8, 16, 6, 15, tzinfo=UTC)
