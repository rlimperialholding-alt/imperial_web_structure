from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.audit import audit
from app.database import SessionLocal, engine
from app.growth_ops import service
from app.growth_ops.email import EmailReceipt
from app.growth_ops.models import GrowthSignal, OutreachMessage
from app.growth_ops.official_source import (
    OfficialSourceEvidenceError,
    OfficialSourceLiveEvidence,
    OfficialSourcePageEvidence,
)
from app.growth_ops.registry import BrandBinding, GrowthRegistryError
from app.growth_ops.schemas import GrowthSignalIn, OutreachReleaseIn
from app.models import AuditLog, MailSendingDomain

OFFICIAL_ID = "DYNAMIC_HU_EXAMPLE_HU"
JSON_ID = "construction-json-test"
RSS_ID = "construction-rss-test"
ROOT_URL = "https://example.hu/"
CONTACT_URL = "https://example.hu/contact"
WORKER_ID = "official-source-test-worker"


def _official_source(**changes: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        "enabled": True,
        "motor": "construction",
        "bucket": "architect_office",
        "kind": "official_company_html",
        "fetch_mode": "ingest_only",
        "url": ROOT_URL,
        "allowed_evidence_urls": [ROOT_URL, CONTACT_URL],
        "context_evidence_url": ROOT_URL,
        "public_contact_url": CONTACT_URL,
        "max_evidence_age_seconds": 3600,
        "binding_sha256": "b" * 64,
        "recipient_binding": {
            "recipient_type": "architect_office",
            "recipient_email": "office@example.hu",
            "recipient_email_type": "role",
            "contact_basis": "public_business_contact",
            "organization_names": ["Example Architects"],
            "recipient_names": ["Selected Studio", "Registry Alias"],
        },
        "policy_evidence": {
            "evidence_url": ROOT_URL,
            "final_url": ROOT_URL,
            "http_status": 200,
            "content_type": "text/html",
            "content_sha256": "a" * 64,
        },
    }
    source.update(changes)
    return source


def _passive_source(kind: str) -> dict[str, Any]:
    return {
        "enabled": True,
        "motor": "construction",
        "bucket": "architect_office",
        "kind": kind,
        "fetch_mode": "scheduled",
        "url": f"https://{kind}.test/source",
    }


def _binding() -> BrandBinding:
    return BrandBinding(
        brand_id="imperial",
        sender_email="info@imperialholding.test",
        domain_key="imperial-official-source-test",
        secret={
            "client_id": "client",
            "client_secret": "secret",
            "refresh_token": "refresh",
            "scope": (
                "https://www.googleapis.com/auth/gmail.compose "
                "https://www.googleapis.com/auth/gmail.readonly"
            ),
        },
        config={
            "brand_name": "Imperial Holding",
            "recipient_cooldown_days": 30,
        },
    )


class _Registry:
    def __init__(
        self,
        sources: dict[str, dict[str, Any]],
        *,
        version: str = "test-v1",
    ) -> None:
        self.sources = sources
        self.version = version
        self.validation_calls: list[dict[str, Any]] = []
        self.now = datetime.now(UTC)

    def validate_signal_source(self, **values: Any) -> None:
        self.validation_calls.append(values)
        source = self.sources.get(str(values["source_id"]))
        if source is None:
            raise GrowthRegistryError("source missing")
        if source.get("kind") != "official_company_html":
            return
        if values.get("source_payload_hash") != source.get("binding_sha256"):
            raise GrowthRegistryError("official source binding hash mismatch")
        observed_at = values.get("detected_at")
        if not isinstance(observed_at, datetime):
            raise GrowthRegistryError("official source timestamp missing")
        observed_at = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=UTC)
        if self.now - observed_at.astimezone(UTC) > timedelta(
            seconds=int(source["max_evidence_age_seconds"])
        ):
            raise GrowthRegistryError("Official-company source evidence is not fresh")

    def brand_for(self, signal_type: str, requested: str | None = None) -> str:
        assert signal_type == "residential_construction"
        assert requested in {None, "imperial"}
        return "imperial"

    def brand_binding(self, brand_id: str) -> BrandBinding:
        assert brand_id == "imperial"
        return _binding()


class _RegistryState:
    def __init__(self, current: _Registry) -> None:
        self.current = current
        self.loads = 0

    def load(self) -> _Registry:
        self.loads += 1
        return self.current


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        base_url="https://intelligence.test.example",
        worker_id=WORKER_ID,
        lease_seconds=300,
        poll_seconds=30,
        enabled=True,
        timezone="Europe/Budapest",
        outreach_send_start_local="08:00",
        outreach_send_end_local="18:00",
        outreach_account_rolling_24h_max=2000,
        outreach_send_concurrency=1,
        outreach_reputation_bootstrap_messages_per_window=100,
        outreach_reputation_max_growth_factor=1.25,
        outreach_reputation_jitter_fraction=0.20,
        runtime_kill_switch_file="unused-test-runtime-kill-switch",
    )


@pytest.fixture
def official_runtime(db, monkeypatch):
    sources = {
        OFFICIAL_ID: _official_source(),
        JSON_ID: _passive_source("json_api"),
        RSS_ID: _passive_source("rss"),
    }
    state = _RegistryState(_Registry(sources))
    canonical_path = (
        Path(__file__).resolve().parents[3]
        / "config"
        / "outbound"
        / "canonical_first_contact_templates_hu_v1.json"
    )
    monkeypatch.setenv("CANONICAL_FIRST_CONTACT_REGISTRY_FILE", str(canonical_path))
    monkeypatch.setattr(
        service.GrowthRegistry,
        "load",
        classmethod(lambda _cls: state.load()),
    )
    monkeypatch.setattr(service, "writes_unlocked", lambda: True)
    monkeypatch.setattr(service, "settings", _settings)
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda *_args: True)
    monkeypatch.setattr(
        service,
        "_authoritative_send_readiness_reason",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "_outreach_transport_capacity_reserved",
        lambda _db, _row: True,
    )
    db.add(
        MailSendingDomain(
            domain_key=_binding().domain_key,
            domain_name="imperialholding.test",
            from_email=_binding().sender_email,
            provider="gmail_api",
            spf_status="not_applicable_oauth",
            dkim_status="not_applicable_oauth",
            dmarc_status="not_applicable_oauth",
            verification_evidence_json=json.dumps(
                {
                    "verification_method": "gmail_oauth_profile",
                    "profile_email": _binding().sender_email,
                }
            ),
            verified_at=datetime.now(UTC),
            active=True,
        )
    )
    db.commit()
    return state


def _signal(
    *,
    source_id: str = OFFICIAL_ID,
    external_key: str = "OFFICIAL-1",
    recipient_email: str = "office@example.hu",
    company_name: str = "Example Architects",
    recipient_name: str = "Selected Studio",
    source_payload_hash: str | None = None,
) -> GrowthSignalIn:
    if source_id == OFFICIAL_ID:
        evidence_url = ROOT_URL
        public_contact_url = CONTACT_URL
        payload_hash = "b" * 64
    else:
        evidence_url = f"https://{source_id}.test/evidence"
        public_contact_url = f"https://{source_id}.test/contact"
        payload_hash = hashlib.sha256(source_id.encode()).hexdigest()
    return GrowthSignalIn.model_validate(
        {
            "source_id": source_id,
            "external_key": external_key,
            "motor_key": "construction",
            "source_bucket": "architect_office",
            "signal_type": "residential_construction",
            "detected_at": datetime.now(UTC),
            "company_name": company_name,
            "company_registration_id": "01-09-999999",
            "subject_type": "organization",
            "recipient_type": "architect_office",
            "recipient_name": recipient_name,
            "sender_company_name": "Imperial Holding",
            "reference_names": [],
            "reference_names_verified": True,
            "recipient_classification_verified": True,
            "exclusion_screening_verified": True,
            "recipient_email": recipient_email,
            "recipient_email_type": "role",
            "contact_basis": "public_business_contact",
            "public_contact_url": public_contact_url,
            "location": "Budapest",
            "summary": "Nyilvános építészirodai üzleti kapcsolat.",
            "evidence_url": evidence_url,
            "confidence": 95,
            "urgency": 80,
            "source_payload_hash": source_payload_hash or payload_hash,
        }
    )


def _prepare_claimed(
    db,
    data: GrowthSignalIn,
) -> tuple[GrowthSignal, OutreachMessage]:
    receipt = service.ingest_signal(db, data)
    signal = db.scalar(select(GrowthSignal).where(GrowthSignal.signal_id == receipt.signal_id))
    row = db.scalar(
        select(OutreachMessage).where(OutreachMessage.outreach_id == receipt.outreach_id)
    )
    assert signal is not None and row is not None
    service.release_outreach(
        db,
        row.outreach_id,
        OutreachReleaseIn(
            approved_by="owner@test",
            inspected_payload_sha256=row.payload_sha256,
            approval_note="Exact canonical payload inspected and approved.",
        ),
    )
    row.status = "claimed"
    row.claimed_by = WORKER_ID
    row.claimed_at = datetime.now(UTC)
    row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    row.attempt_count = 1
    db.commit()
    return signal, row


def _live_evidence(
    source: dict[str, Any],
    *,
    observed_at: datetime | None = None,
) -> OfficialSourceLiveEvidence:
    current = observed_at or datetime.now(UTC)
    pages = tuple(
        OfficialSourcePageEvidence(
            requested_url=url,
            final_url=url,
            http_status=200,
            content_type="text/html; charset=utf-8",
            content_bytes=100,
            content_sha256=hashlib.sha256(url.encode()).hexdigest(),
            source_ip="93.184.216.34",
        )
        for url in (ROOT_URL, CONTACT_URL)
    )
    return OfficialSourceLiveEvidence(
        source_id=OFFICIAL_ID,
        binding_sha256=str(source["binding_sha256"]),
        observed_at=current,
        pages=pages,
        matched_email="office@example.hu",
        matched_organization_marker="example architects",
        matched_recipient_marker="selected studio",
    )


def _install_guard_and_transport(monkeypatch, events: list[str]):
    def claim(*_args, **_kwargs):
        events.append("global_guard")
        return SimpleNamespace(may_send=True, claim_token="claim-token", decision="allow")

    def finalize(*_args, **_kwargs):
        events.append("global_finalize")

    monkeypatch.setattr(service, "claim_global_recipient_delivery", claim)
    monkeypatch.setattr(service, "finalize_global_recipient_delivery", finalize)
    monkeypatch.setattr(
        service,
        "fail_global_recipient_delivery",
        lambda *_args, **_kwargs: events.append("global_fail"),
    )

    class Adapter:
        def __init__(self, _binding):
            events.append("adapter_constructed")

        def send(self, *, pre_send_guard, to_email, **_kwargs):
            events.append("before_pre_send_callback")
            pre_send_guard()
            events.append("gmail_post")
            return EmailReceipt(
                provider_message_id=f"gmail-{to_email}",
                accepted_recipient=to_email,
                provider="gmail_api",
                response_sha256="c" * 64,
                detail={
                    "readback_verified": True,
                    "readback_mime_sha256": "d" * 64,
                    "rfc_message_id": f"<{to_email}>",
                },
            )

    monkeypatch.setattr(service, "SMTPEmailAdapter", Adapter)


def test_refresh_is_before_global_guard_and_callback_is_immediately_before_post(
    db,
    monkeypatch,
    official_runtime,
):
    signal, row = _prepare_claimed(db, _signal())
    events: list[str] = []
    source = official_runtime.current.sources[OFFICIAL_ID]

    def fetch(*_args, **_kwargs):
        events.append("live_refresh")
        return _live_evidence(source)

    monkeypatch.setattr(service, "fetch_official_source_evidence", fetch)
    original_fresh = service._assert_official_source_evidence_fresh
    fresh_calls = 0

    def fresh(*args, **kwargs):
        nonlocal fresh_calls
        fresh_calls += 1
        events.append("receipt_pre_global" if fresh_calls == 1 else "receipt_pre_post")
        return original_fresh(*args, **kwargs)

    monkeypatch.setattr(service, "_assert_official_source_evidence_fresh", fresh)
    _install_guard_and_transport(monkeypatch, events)

    result = service.dispatch_outreach(db, row)

    assert result.status == "sent"
    assert events == [
        "live_refresh",
        "receipt_pre_global",
        "global_guard",
        "adapter_constructed",
        "before_pre_send_callback",
        "receipt_pre_post",
        "receipt_pre_post",
        "gmail_post",
        "global_finalize",
    ]
    assert signal.status == "contacted"


def test_ingest_proof_hmac_binds_signal_id_and_immediately_verifies(
    db,
    official_runtime,
):
    signal, row = _prepare_claimed(db, _signal(external_key="PROOF-SIGNAL-ID"))

    proof = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "growth_official_source_signal_bound",
            AuditLog.entity_id == signal.signal_id,
        )
        .order_by(AuditLog.id.desc())
    )
    assert proof is not None
    payload = json.loads(proof.after_json)
    proof_hmac = payload.pop("binding_proof_hmac_sha256")
    assert payload["signal_id"] == signal.signal_id
    assert proof_hmac == service._official_source_receipt_hmac(payload)
    assert service._official_source_provenance_proven(db, row, signal)
    assert service._official_source_required(db, row, signal, official_runtime.current)


@pytest.mark.parametrize(
    "failure",
    [
        OfficialSourceEvidenceError("official_source_email_marker_missing"),
        OfficialSourceEvidenceError("official_source_fetch_timeout"),
        OfficialSourceEvidenceError("official_source_registry_changed_during_fetch"),
    ],
)
def test_live_fetch_or_receipt_failure_claims_no_global_guard_and_posts_no_gmail(
    db,
    monkeypatch,
    official_runtime,
    failure,
):
    _signal_row, row = _prepare_claimed(db, _signal())
    calls = {"global": 0, "gmail": 0}
    monkeypatch.setattr(
        service,
        "fetch_official_source_evidence",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    monkeypatch.setattr(
        service,
        "claim_global_recipient_delivery",
        lambda *_args, **_kwargs: calls.__setitem__("global", calls["global"] + 1),
    )

    class NoTransport:
        def __init__(self, *_args, **_kwargs):
            calls["gmail"] += 1

    monkeypatch.setattr(service, "SMTPEmailAdapter", NoTransport)

    result = service.dispatch_outreach(db, row)

    assert result.status == "queued"
    assert result.provider_message_id is None
    assert result.last_error == str(failure)
    assert calls == {"global": 0, "gmail": 0}


def test_registry_binding_drift_during_fetch_fails_before_global_guard(
    db,
    monkeypatch,
    official_runtime,
):
    _signal_row, row = _prepare_claimed(db, _signal())
    calls = {"global": 0}
    original = official_runtime.current.sources[OFFICIAL_ID]

    def fetch(*_args, **_kwargs):
        changed = deepcopy(original)
        changed["binding_sha256"] = "e" * 64
        official_runtime.current = _Registry({OFFICIAL_ID: changed})
        return _live_evidence(original)

    monkeypatch.setattr(service, "fetch_official_source_evidence", fetch)
    monkeypatch.setattr(
        service,
        "claim_global_recipient_delivery",
        lambda *_args, **_kwargs: calls.__setitem__("global", calls["global"] + 1),
    )

    result = service.dispatch_outreach(db, row)

    assert result.status == "queued"
    assert result.last_error == "official_source_registry_changed_during_fetch"
    assert result.provider_message_id is None
    assert calls["global"] == 0


def test_missing_or_invalid_refresh_receipt_fails_before_global_guard_and_gmail(
    db,
    monkeypatch,
    official_runtime,
):
    _signal_row, row = _prepare_claimed(db, _signal())
    calls = {"global": 0, "gmail_post": 0}
    monkeypatch.setattr(
        service,
        "_refresh_official_source_evidence",
        lambda *_args, **_kwargs: True,
    )

    def claim(*_args, **_kwargs):
        calls["global"] += 1
        return SimpleNamespace(may_send=True, claim_token="claim-token", decision="allow")

    monkeypatch.setattr(service, "claim_global_recipient_delivery", claim)
    monkeypatch.setattr(
        service,
        "fail_global_recipient_delivery",
        lambda *_args, **_kwargs: None,
    )

    class Adapter:
        def __init__(self, _binding):
            pass

        def send(self, *, pre_send_guard, **_kwargs):
            pre_send_guard()
            calls["gmail_post"] += 1
            raise AssertionError("unreachable after missing receipt")

    monkeypatch.setattr(service, "SMTPEmailAdapter", Adapter)

    result = service.dispatch_outreach(db, row)

    assert result.status == "queued"
    assert result.provider_message_id is None
    assert result.last_error in {
        "official_source_evidence_receipt_attestation_failed",
        "official_source_evidence_receipt_mismatch",
    }
    assert calls == {"global": 0, "gmail_post": 0}


def test_refresh_receipt_is_attested_and_signal_identity_is_immutable(
    db,
    monkeypatch,
    official_runtime,
):
    signal, row = _prepare_claimed(db, _signal())
    identity_before = (
        signal.detected_at,
        signal.source_payload_hash,
        signal.dedupe_hash,
        signal.last_seen_at,
        row.payload_sha256,
        row.release_token_hash,
    )
    source = official_runtime.current.sources[OFFICIAL_ID]
    monkeypatch.setattr(
        service,
        "fetch_official_source_evidence",
        lambda *_args, **_kwargs: _live_evidence(source),
    )

    required = service._refresh_official_source_evidence(
        db,
        row,
        signal,
        official_runtime.current,
        service._canonical_metadata(row),
    )
    db.flush()

    assert required is True
    assert identity_before == (
        signal.detected_at,
        signal.source_payload_hash,
        signal.dedupe_hash,
        signal.last_seen_at,
        row.payload_sha256,
        row.release_token_hash,
    )
    receipt_row = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "growth_official_source_evidence_refreshed",
            AuditLog.entity_id == signal.signal_id,
        )
        .order_by(AuditLog.id.desc())
    )
    receipt = json.loads(receipt_row.after_json)
    assert receipt["receipt_hmac_sha256"]
    assert receipt["signal_identity_unchanged"] is True
    service._assert_official_source_evidence_fresh(
        db,
        row,
        signal,
        official_required=True,
    )


def _refreshed_receipt(db, monkeypatch, official_runtime):
    signal, row = _prepare_claimed(db, _signal())
    source = official_runtime.current.sources[OFFICIAL_ID]
    monkeypatch.setattr(
        service,
        "fetch_official_source_evidence",
        lambda *_args, **_kwargs: _live_evidence(source),
    )
    service._refresh_official_source_evidence(
        db,
        row,
        signal,
        official_runtime.current,
        service._canonical_metadata(row),
    )
    db.flush()
    receipt_row = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "growth_official_source_evidence_refreshed",
            AuditLog.entity_id == signal.signal_id,
        )
        .order_by(AuditLog.id.desc())
    )
    assert receipt_row is not None
    return signal, row, receipt_row


@pytest.mark.parametrize("tamper", ["hmac", "release", "payload", "binding", "ttl"])
def test_receipt_ttl_current_binding_release_and_payload_invariants_fail_closed(
    db,
    monkeypatch,
    official_runtime,
    tamper,
):
    signal, row, receipt_row = _refreshed_receipt(db, monkeypatch, official_runtime)
    if tamper == "hmac":
        receipt = json.loads(receipt_row.after_json)
        receipt["receipt_hmac_sha256"] = "0" * 64
        receipt_row.after_json = service.canonical_json(receipt)
    elif tamper == "release":
        row.release_token_hash = "0" * 64
    elif tamper == "payload":
        row.payload_sha256 = "0" * 64
    elif tamper == "binding":
        changed = deepcopy(official_runtime.current.sources[OFFICIAL_ID])
        changed["binding_sha256"] = "e" * 64
        official_runtime.current = _Registry({OFFICIAL_ID: changed})
    elif tamper == "ttl":
        receipt = json.loads(receipt_row.after_json)
        receipt.pop("receipt_hmac_sha256")
        old = datetime.now(UTC) - timedelta(hours=2)
        receipt["observed_at"] = old.isoformat()
        receipt["receipt_hmac_sha256"] = service._official_source_receipt_hmac(receipt)
        receipt_row.after_json = service.canonical_json(receipt)
    db.flush()

    with pytest.raises((OfficialSourceEvidenceError, GrowthRegistryError)):
        service._assert_official_source_evidence_fresh(
            db,
            row,
            signal,
            official_required=True,
        )


@pytest.mark.parametrize(("source_id", "kind"), [(JSON_ID, "json_api"), (RSS_ID, "rss")])
def test_unproven_json_and_rss_sources_are_unaffected_and_never_live_fetched(
    db,
    monkeypatch,
    official_runtime,
    source_id,
    kind,
):
    _signal_row, row = _prepare_claimed(
        db,
        _signal(
            source_id=source_id,
            external_key=f"PASSIVE-{kind}",
            recipient_email=f"office@{kind.replace('_', '-')}.test",
            company_name=f"{kind} Architects",
            recipient_name=f"{kind} Studio",
        ),
    )
    events: list[str] = []
    monkeypatch.setattr(
        service,
        "fetch_official_source_evidence",
        lambda *_args, **_kwargs: pytest.fail("passive source must not be live fetched"),
    )
    _install_guard_and_transport(monkeypatch, events)
    loads_before = official_runtime.loads

    result = service.dispatch_outreach(db, row)

    assert result.status == "sent"
    assert official_runtime.loads - loads_before == 2
    assert "gmail_post" in events


def test_unproven_nonofficial_final_guard_blocks_promotion_race(
    db,
    monkeypatch,
    official_runtime,
):
    signal, row = _prepare_claimed(
        db,
        _signal(
            source_id=JSON_ID,
            external_key="JSON-TO-OFFICIAL",
            recipient_email="flip@json.test",
            company_name="Flip Architects",
            recipient_name="Flip Studio",
        ),
    )
    events: list[str] = []

    def claim(*_args, **_kwargs):
        events.append("global_guard")
        return SimpleNamespace(may_send=True, claim_token="claim-token", decision="allow")

    monkeypatch.setattr(service, "claim_global_recipient_delivery", claim)
    monkeypatch.setattr(
        service,
        "fail_global_recipient_delivery",
        lambda *_args, **_kwargs: events.append("global_fail"),
    )
    monkeypatch.setattr(
        service,
        "finalize_global_recipient_delivery",
        lambda *_args, **_kwargs: events.append("global_finalize"),
    )

    transitioned = _official_source(
        url=signal.evidence_url,
        allowed_evidence_urls=[signal.evidence_url, signal.public_contact_url],
        context_evidence_url=signal.evidence_url,
        public_contact_url=signal.public_contact_url,
        binding_sha256=signal.source_payload_hash,
        recipient_binding={
            "recipient_type": "architect_office",
            "recipient_email": signal.recipient_email,
            "recipient_email_type": "role",
            "contact_basis": "public_business_contact",
            "organization_names": [signal.company_name],
            "recipient_names": ["Flip Studio"],
        },
        policy_evidence={
            "evidence_url": signal.evidence_url,
            "final_url": signal.evidence_url,
            "http_status": 200,
            "content_type": "text/html",
            "content_sha256": "f" * 64,
        },
    )

    class FlipBeforePostAdapter:
        def __init__(self, _binding):
            events.append("adapter_constructed")

        def send(self, *, pre_send_guard, **_kwargs):
            events.append("before_pre_send_callback")
            official_runtime.current = _Registry({JSON_ID: transitioned})
            pre_send_guard()
            events.append("gmail_post")
            return EmailReceipt(
                provider_message_id="gmail-promotion-race",
                accepted_recipient=signal.recipient_email,
                provider="gmail_api",
                response_sha256="c" * 64,
                detail={
                    "readback_verified": True,
                    "readback_mime_sha256": "d" * 64,
                    "rfc_message_id": "<promotion-race@example.test>",
                },
            )

    monkeypatch.setattr(service, "SMTPEmailAdapter", FlipBeforePostAdapter)
    monkeypatch.setattr(
        service,
        "fetch_official_source_evidence",
        lambda *_args, **_kwargs: pytest.fail("initial JSON source must not be live fetched"),
    )

    loads_before = official_runtime.loads
    result = service.dispatch_outreach(db, row)

    assert result.status == "queued"
    assert result.provider_message_id is None
    assert result.last_error == "official_source_evidence_receipt_attestation_failed"
    assert official_runtime.loads - loads_before == 2
    assert events == [
        "global_guard",
        "adapter_constructed",
        "before_pre_send_callback",
        "global_fail",
    ]


@pytest.mark.parametrize("current_state", ["removed", "json", "disabled"])
def test_proven_official_source_removal_kind_change_or_disable_fails_closed(
    db,
    monkeypatch,
    official_runtime,
    current_state,
):
    _signal_row, row = _prepare_claimed(db, _signal())
    current = deepcopy(official_runtime.current.sources[OFFICIAL_ID])
    if current_state == "removed":
        sources = {}
    elif current_state == "json":
        current["kind"] = "json_api"
        sources = {OFFICIAL_ID: current}
    else:
        current["enabled"] = False
        sources = {OFFICIAL_ID: current}
    official_runtime.current = _Registry(sources)
    calls = {"fetch": 0, "global": 0, "gmail": 0}
    monkeypatch.setattr(
        service,
        "fetch_official_source_evidence",
        lambda *_args, **_kwargs: calls.__setitem__("fetch", calls["fetch"] + 1),
    )
    monkeypatch.setattr(
        service,
        "claim_global_recipient_delivery",
        lambda *_args, **_kwargs: calls.__setitem__("global", calls["global"] + 1),
    )

    class NoTransport:
        def __init__(self, *_args, **_kwargs):
            calls["gmail"] += 1

    monkeypatch.setattr(service, "SMTPEmailAdapter", NoTransport)

    result = service.dispatch_outreach(db, row)

    assert result.status == "queued"
    assert result.last_error == "official_source_binding_missing_or_disabled"
    assert result.provider_message_id is None
    assert calls == {"fetch": 0, "global": 0, "gmail": 0}


def _legacy_release_payloads() -> tuple[dict[str, Any], dict[str, Any]]:
    common = {
        "commit": "1111e759b0815e27d32b264790ec97f54bbb59e4",
        "release_path": (
            "/opt/imperial-intelligence/releases/architect-source-1111e75-20260829T024000Z"
        ),
        "image": "imperial-platform-core:architect-source-1111e75-20260829",
        "registry_sha256": ("be08f46c246cb4c67c70a1dfffd8d6c2d7c2c9a8d4f7aa6cd5490c1f87b10bd7"),
        "registry_version": "2026-08-29-architect-dynamic-v1",
        "candidate_artifact_sha256": (
            "be08f46c246cb4c67c70a1dfffd8d6c2d7c2c9a8d4f7aa6cd5490c1f87b10bd7"
        ),
        "authority_registry_id": "IMPERIAL_REAL_ESTATE_DISCOVERY_SOURCES_HU_V1",
        "authority_registry_version": 1,
        "authority_registry_sha256": (
            "38e3d2dda5dbed631e68cdf2a7c23208422fba50221bb961d318963a224d2b18"
        ),
        "owner_instruction_ref": ("imperial-kanonikus-els-megkeres-s-napi-canary/2026-08-27"),
    }
    deployed = {
        **common,
        "phase": "deployed_locked",
        "source_ids": [
            "DYNAMIC_HU_ARCHIKON_HU",
            "DYNAMIC_HU_KOZTI_HU",
            "DYNAMIC_HU_NAPUR_HU",
        ],
        "runtime_kill_switch_engaged": True,
        "building_material_retailer_sources_enabled": False,
        "email_sent": False,
    }
    unlocked = {
        **common,
        "phase": "unlocked",
        "independent_verifier_pass": True,
        "unlock": {
            "removed_only": "/app/runtime/growth-kill-switch",
            "managed_owner_gate": "/run/secrets/growth/kill-switch",
            "managed_owner_gate_present": True,
            "core_writes_unlocked": True,
            "worker_writes_unlocked": True,
        },
        "building_material_retailer_sources_enabled": False,
        "email_sent": False,
    }
    return deployed, unlocked


def test_legacy_4642_4644_release_pair_alone_no_longer_proves_provenance(
    db,
    official_runtime,
):
    legacy_id = "DYNAMIC_HU_ARCHIKON_HU"
    binding_hash = "f52deece65604c903af6c8b66497e3b15df5d6c7c77187f767f3e5bab1d88610"
    official_runtime.current.sources[legacy_id] = _passive_source("json_api")
    signal, row = _prepare_claimed(
        db,
        _signal(
            source_id=legacy_id,
            external_key="LEGACY-ARCHIKON",
            recipient_email="office@archikon.hu",
            company_name="Archikon",
            recipient_name="Archikon",
            source_payload_hash=binding_hash,
        ),
    )
    deployed, unlocked = _legacy_release_payloads()
    for action, payload in (
        ("growth_architect_source_release_deployed_locked", deployed),
        ("growth_architect_source_release_unlocked", unlocked),
    ):
        audit(
            db,
            actor="codex-owner-authorized-automation",
            action=action,
            entity_type="growth_source_registry_release",
            entity_id="architect-source:1111e75:be08f46c246c",
            after=payload,
        )
        db.flush()

    assert not service._official_source_provenance_proven(db, row, signal)
    assert not service._official_source_required(db, row, signal, official_runtime.current)


def _migration_setup(db, tmp_path, monkeypatch, official_runtime):
    legacy = (
        (
            "DYNAMIC_HU_ARCHIKON_HU",
            "f52deece65604c903af6c8b66497e3b15df5d6c7c77187f767f3e5bab1d88610",
            "office@archikon.hu",
            "Archikon",
        ),
        (
            "DYNAMIC_HU_KOZTI_HU",
            "51abeb398a860e9f72ae2edeb6299e7bc2619d484ccc6b16b3c39e2a50c6fc56",
            "info@kozti.hu",
            "KÖZTI",
        ),
        (
            "DYNAMIC_HU_NAPUR_HU",
            "eb6944f448d691ded455654ae8f64cfbc2c09eb47f98bf09c6073619547f692e",
            "info@napur.hu",
            "NAPUR",
        ),
    )
    prepared: list[tuple[GrowthSignal, OutreachMessage]] = []
    for index, (source_id, binding_hash, email, organization) in enumerate(legacy):
        official_runtime.current.sources[source_id] = _passive_source("json_api")
        signal, row = _prepare_claimed(
            db,
            _signal(
                source_id=source_id,
                external_key=f"LEGACY-BACKFILL-{index}",
                recipient_email=email,
                company_name=organization,
                recipient_name=organization,
                source_payload_hash=binding_hash,
            ),
        )
        row.status = "queued"
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None
        row.attempt_count = 0
        signal.status = "queued"
        prepared.append((signal, row))
    db.commit()

    for signal, row in prepared:
        assert not service._official_source_provenance_proven(db, row, signal)
    authority_registry_id = "IMPERIAL_REAL_ESTATE_DISCOVERY_SOURCES_HU_V1"
    authority_registry_version = 1
    authority_registry_sha256 = "3" * 64
    sources: dict[str, dict[str, Any]] = {}
    for signal, row in prepared:
        metadata = service._canonical_metadata(row)
        recipient_name = metadata["render_input"]["recipient_name"]
        sources[signal.source_id] = _official_source(
            url=signal.evidence_url,
            allowed_evidence_urls=[signal.evidence_url, signal.public_contact_url],
            context_evidence_url=signal.evidence_url,
            public_contact_url=signal.public_contact_url,
            binding_sha256=signal.source_payload_hash,
            recipient_binding={
                "recipient_type": "architect_office",
                "recipient_email": signal.recipient_email,
                "recipient_email_type": "role",
                "contact_basis": "public_business_contact",
                "organization_names": [signal.company_name],
                "recipient_names": [recipient_name],
            },
            policy_evidence={
                "evidence_url": signal.evidence_url,
                "final_url": signal.evidence_url,
                "http_status": 200,
                "content_type": "text/html",
                "content_sha256": "4" * 64,
            },
            authority={
                "registry_id": authority_registry_id,
                "version": authority_registry_version,
                "sha256": authority_registry_sha256,
            },
        )
    registry_version = "migration-test-v1"
    official_runtime.current = _Registry(sources, version=registry_version)
    registry_path = tmp_path / "managed-growth-registry.json"
    registry_path.write_text("locked migration registry", encoding="utf-8")
    registry_sha256 = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    runtime_marker = tmp_path / "runtime-kill-switch"
    managed_gate = tmp_path / "managed-owner-gate"
    runtime_marker.write_text("KILLED\n", encoding="utf-8")
    managed_gate.write_text("OWNER_STOP\n", encoding="utf-8")
    config = vars(_settings()).copy()
    config.update(
        runtime_kill_switch_file=str(runtime_marker),
        kill_switch_file=str(managed_gate),
        registry_file=str(registry_path),
    )
    monkeypatch.setattr(service, "settings", lambda: SimpleNamespace(**config))
    monkeypatch.setattr(service, "writes_unlocked", lambda: False)
    targets = tuple(
        service.OfficialSourceBindingProofTarget(
            signal_id=signal.signal_id,
            outreach_id=row.outreach_id,
            source_id=signal.source_id,
            binding_sha256=signal.source_payload_hash,
        )
        for signal, row in prepared
    )
    kwargs = {
        "targets": targets,
        "migration_id": "official-source-test-migration-v1",
        "expected_registry_version": registry_version,
        "expected_registry_sha256": registry_sha256,
        "expected_authority_registry_id": authority_registry_id,
        "expected_authority_registry_version": authority_registry_version,
        "expected_authority_registry_sha256": authority_registry_sha256,
    }
    return prepared, kwargs


def test_locked_backfill_is_three_of_three_atomic_idempotent_and_readable(
    db,
    tmp_path,
    monkeypatch,
    official_runtime,
):
    prepared, kwargs = _migration_setup(
        db,
        tmp_path,
        monkeypatch,
        official_runtime,
    )

    first_ids = service.migrate_official_source_binding_proofs_locked(db, **kwargs)
    second_ids = service.migrate_official_source_binding_proofs_locked(db, **kwargs)

    assert len(first_ids) == 3
    assert second_ids == first_ids
    proofs = db.scalars(
        select(AuditLog).where(AuditLog.action == "growth_official_source_signal_bound")
    ).all()
    completions = db.scalars(
        select(AuditLog).where(
            AuditLog.action == "growth_official_source_binding_proof_migration_completed"
        )
    ).all()
    assert len(proofs) == 3
    assert len(completions) == 1
    expected_signal_ids = {signal.signal_id for signal, _row in prepared}
    recorded_signal_ids: set[str] = set()
    for proof in proofs:
        proof_payload = json.loads(proof.after_json)
        proof_hmac = proof_payload.pop("binding_proof_hmac_sha256")
        assert proof_payload["signal_id"] == proof.entity_id
        assert proof_hmac == service._official_source_receipt_hmac(proof_payload)
        recorded_signal_ids.add(proof_payload["signal_id"])
    assert recorded_signal_ids == expected_signal_ids
    completion = json.loads(completions[0].after_json)
    completion_hmac = completion.pop("migration_hmac_sha256")
    assert completion_hmac == service._official_source_receipt_hmac(completion)
    assert completion["email_sent"] is False
    assert len(completion["targets"]) == 3
    assert all(
        service._official_source_provenance_proven(db, row, signal)
        and row.status == "queued"
        and row.provider_message_id is None
        and row.sent_at is None
        for signal, row in prepared
    )
    official_runtime.current = _Registry({})

    assert all(
        service._official_source_required(db, row, signal, official_runtime.current)
        for signal, row in prepared
    )


def test_locked_backfill_invalid_third_row_rolls_back_zero_of_three(
    db,
    tmp_path,
    monkeypatch,
    official_runtime,
):
    prepared, kwargs = _migration_setup(
        db,
        tmp_path,
        monkeypatch,
        official_runtime,
    )
    prepared[2][1].release_token_hash = "0" * 64
    db.commit()

    with pytest.raises(
        OfficialSourceEvidenceError,
        match="official_source_binding_migration_payload_release_invalid",
    ):
        service.migrate_official_source_binding_proofs_locked(db, **kwargs)

    assert not db.scalars(
        select(AuditLog).where(AuditLog.action == "growth_official_source_signal_bound")
    ).all()
    assert not db.scalars(
        select(AuditLog).where(
            AuditLog.action == "growth_official_source_binding_proof_migration_completed"
        )
    ).all()


@pytest.mark.parametrize(
    ("drift", "current_state"),
    [("source_id", "removed"), ("source_payload_hash", "retyped")],
)
def test_trusted_proof_field_drift_stays_required_then_fails_closed_zero_provider(
    db,
    tmp_path,
    monkeypatch,
    official_runtime,
    drift,
    current_state,
):
    prepared, kwargs = _migration_setup(
        db,
        tmp_path,
        monkeypatch,
        official_runtime,
    )
    service.migrate_official_source_binding_proofs_locked(db, **kwargs)
    signal, row = prepared[0]
    original_source_id = signal.source_id
    assert service._official_source_provenance_proven(db, row, signal)

    if drift == "source_id":
        signal.source_id = "DYNAMIC_HU_DRIFTED_SOURCE_ID"
    else:
        signal.source_payload_hash = "9" * 64
    row.status = "claimed"
    row.claimed_by = WORKER_ID
    row.claimed_at = datetime.now(UTC)
    row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    row.attempt_count = 1
    if current_state == "removed":
        official_runtime.current = _Registry({})
    else:
        official_runtime.current = _Registry({original_source_id: _passive_source("json_api")})
    monkeypatch.setattr(service, "writes_unlocked", lambda: True)
    db.commit()

    assert not service._official_source_provenance_proven(db, row, signal)
    assert service._official_source_required(db, row, signal, official_runtime.current)
    calls = {"fetch": 0, "global": 0, "gmail": 0}
    monkeypatch.setattr(
        service,
        "fetch_official_source_evidence",
        lambda *_args, **_kwargs: calls.__setitem__("fetch", calls["fetch"] + 1),
    )
    monkeypatch.setattr(
        service,
        "claim_global_recipient_delivery",
        lambda *_args, **_kwargs: calls.__setitem__("global", calls["global"] + 1),
    )

    class NoTransport:
        def __init__(self, *_args, **_kwargs):
            calls["gmail"] += 1

    monkeypatch.setattr(service, "SMTPEmailAdapter", NoTransport)

    result = service.dispatch_outreach(db, row)

    assert result.status == "queued"
    assert result.last_error == "official_source_binding_missing_or_disabled"
    assert result.provider_message_id is None
    assert calls == {"fetch": 0, "global": 0, "gmail": 0}


def test_forged_or_partial_provenance_does_not_reclassify_unproven_json(
    db,
    official_runtime,
):
    signal, row = _prepare_claimed(
        db,
        _signal(
            source_id=JSON_ID,
            external_key="FORGED-PROOF",
            recipient_email="forged@json.test",
            company_name="JSON Architects",
            recipient_name="JSON Studio",
        ),
    )
    forged = {
        "source_id": signal.source_id,
        "binding_sha256": signal.source_payload_hash,
        "signal_source_payload_hash": signal.source_payload_hash,
        "recipient_email": signal.recipient_email,
        "outreach_id": row.outreach_id,
        "payload_sha256": row.payload_sha256,
        "attestation_scheme": ("HMAC-SHA256:IMPERIAL_RELEASE_HMAC_KEY:official-source-binding:v1"),
        "binding_proof_hmac_sha256": "0" * 64,
        "email_sent": False,
    }
    audit(
        db,
        actor="attacker",
        action="growth_official_source_signal_bound",
        entity_type="growth_signal",
        entity_id=signal.signal_id,
        after=forged,
    )
    db.flush()

    assert not service._official_source_provenance_proven(db, row, signal)
    assert not service._official_source_required(db, row, signal, official_runtime.current)


def test_row_local_live_failure_retries_and_batch_continues_to_next_row(
    db,
    monkeypatch,
    official_runtime,
):
    _bad_signal, bad = _prepare_claimed(db, _signal(external_key="BATCH-BAD"))
    _good_signal, good = _prepare_claimed(
        db,
        _signal(
            source_id=JSON_ID,
            external_key="BATCH-GOOD",
            recipient_email="good@json.test",
            company_name="JSON Architects",
            recipient_name="JSON Studio",
        ),
    )
    monkeypatch.setattr(
        service,
        "fetch_official_source_evidence",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OfficialSourceEvidenceError("official_source_fetch_timeout")
        ),
    )
    events: list[str] = []
    _install_guard_and_transport(monkeypatch, events)
    claimed = iter([bad, good])
    monkeypatch.setattr(service, "claim_outreach", lambda _db: next(claimed))
    monkeypatch.setattr(service, "_outreach_send_capacity", lambda _db: 2)

    first_sent = service.dispatch_batch(db, limit=2)
    second_sent = service.dispatch_batch(db, limit=2)
    sent = first_sent + second_sent

    db.refresh(bad)
    db.refresh(good)
    assert sent == 1
    assert bad.status == "queued"
    assert bad.last_error == "official_source_fetch_timeout"
    assert bad.provider_message_id is None
    assert good.status == "sent"
    assert events.count("gmail_post") == 1


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="requires the dedicated PostgreSQL integration-test database",
)
def test_postgresql_concurrent_dispatch_honors_row_lease_and_posts_once(
    db,
    monkeypatch,
    official_runtime,
):
    _signal_row, row = _prepare_claimed(db, _signal(external_key="PG-CONCURRENT"))
    source = official_runtime.current.sources[OFFICIAL_ID]
    monkeypatch.setattr(
        service,
        "fetch_official_source_evidence",
        lambda *_args, **_kwargs: _live_evidence(source),
    )
    events: list[str] = []
    _install_guard_and_transport(monkeypatch, events)

    def worker(_index: int) -> str:
        with SessionLocal() as session:
            current = session.scalar(select(OutreachMessage).where(OutreachMessage.id == row.id))
            assert current is not None
            return service.dispatch_outreach(session, current).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(worker, range(2)))

    assert statuses.count("sent") == 2
    assert events.count("gmail_post") == 1
    with SessionLocal() as session:
        current = session.get(OutreachMessage, row.id)
        assert current is not None and current.status == "sent"
