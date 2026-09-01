from __future__ import annotations

import base64
import hashlib
import importlib
import json
import runpy
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.database import SessionLocal, engine
from app.growth_ops import scheduled_gmail_escrow_service as escrow_service
from app.growth_ops import service
from app.growth_ops.email import EmailDeliveryError, EmailReceipt, SMTPEmailAdapter
from app.growth_ops.models import (
    CanonicalEmailDelivery,
    GrowthSignal,
    OutreachMessage,
    ScheduledGmailEscrowBundle,
    ScheduledGmailEscrowPermit,
    ScheduledGmailLease,
)
from app.growth_ops.registry import BrandBinding, GrowthRegistryError

SENDER = "info@imperialholding.hu"
NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
ZONE = ZoneInfo("Europe/Budapest")


def _schema(name: str, **values: Any):
    schemas = importlib.import_module("app.growth_ops.schemas")
    model = getattr(schemas, name, None)
    assert model is not None, f"missing offline escrow schema: {name}"
    return model(**values)


def _service_call(name: str):
    call = getattr(service, name, None) or getattr(escrow_service, name, None)
    assert callable(call), f"missing offline escrow service function: {name}"
    return call


def _value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key)


def _canonical_sha256(value: dict[str, Any]) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sign_manifest(
    private_key: Ed25519PrivateKey,
    manifest: dict[str, Any],
) -> tuple[str, str]:
    signature = private_key.sign(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return (
        _canonical_sha256(manifest),
        base64.urlsafe_b64encode(signature).decode("ascii").rstrip("="),
    )


def _utc_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


class _Principal:
    def __init__(self, client_id: str) -> None:
        private_key = Ed25519PrivateKey.from_private_bytes(
            hashlib.sha256(f"offline-key:{client_id}".encode()).digest()
        )
        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        self.client_id = client_id
        self.permissions = frozenset(
            {"lease", "finalize", "abort", "read", "escrow_prefetch", "escrow_sync"}
        )
        self.sender_emails = frozenset({SENDER})
        self.motor_keys = frozenset({"construction"})
        self.registry_version = "offline-escrow-test-v1"
        self.registry_sha256 = "d" * 64
        self.offline_escrow_enabled = True
        self.client_key_id = f"{client_id}-key-v1"
        self.offline_public_key_pem = public_key_pem
        self.offline_public_key_sha256 = hashlib.sha256(
            public_key_pem.encode("ascii")
        ).hexdigest()
        self.offline_max_permits = 2000
        self.offline_max_horizon_days = 31
        self._offline_private_key = private_key

    def assert_scope(
        self,
        *,
        permission: str,
        sender_email: str | None = None,
        motor_key: str | None = None,
    ) -> None:
        if permission not in self.permissions:
            raise ValueError("scheduled_gmail_client_permission_denied")
        if sender_email and sender_email.casefold() not in self.sender_emails:
            raise ValueError("scheduled_gmail_client_sender_scope_denied")
        if motor_key and motor_key.casefold() not in self.motor_keys:
            raise ValueError("scheduled_gmail_client_motor_scope_denied")

    def assert_offline_escrow_scope(
        self,
        *,
        permit_count: int,
        horizon_days: int,
        client_key_id: str | None = None,
    ) -> None:
        if not 1 <= permit_count <= self.offline_max_permits:
            raise ValueError("scheduled_gmail_client_offline_permit_scope_denied")
        if not 1 <= horizon_days <= self.offline_max_horizon_days:
            raise ValueError("scheduled_gmail_client_offline_horizon_scope_denied")
        if client_key_id is not None and client_key_id != self.client_key_id:
            raise ValueError("scheduled_gmail_client_offline_key_scope_denied")


def _binding() -> BrandBinding:
    return BrandBinding(
        brand_id="imperial",
        sender_email=SENDER,
        domain_key="imperialholding-hu",
        secret={
            "client_id": "client",
            "client_secret": "secret",
            "refresh_token": "refresh-token",
            "access_token": "test-access-token",
            "scope": (
                "https://www.googleapis.com/auth/gmail.compose "
                "https://www.googleapis.com/auth/gmail.readonly"
            ),
        },
        config={"recipient_cooldown_days": 30},
    )


class _Registry:
    def brand_binding(self, brand_id: str) -> BrandBinding:
        assert brand_id == "imperial"
        return _binding()


def _settings(tmp_path: Path) -> SimpleNamespace:
    signing_key = tmp_path / "escrow-signing-key"
    signing_key.write_bytes(b"offline-escrow-test-signing-key-32-bytes-minimum")
    signing_key.chmod(0o600)
    return SimpleNamespace(
        base_url="https://intelligence.test.example",
        timezone="Europe/Budapest",
        worker_id="offline-escrow-test-worker",
        lease_seconds=300,
        outreach_send_start_local="00:00",
        outreach_send_end_local="00:00",
        outreach_budapest_day_max=2000,
        outreach_send_concurrency=1,
        outreach_reputation_bootstrap_messages_per_window=2000,
        outreach_reputation_max_growth_factor=1.25,
        outreach_reputation_jitter_fraction=0.20,
        scheduled_gmail_escrow_enabled=True,
        scheduled_gmail_escrow_max_days=31,
        scheduled_gmail_escrow_signing_key_id="test-escrow-key-v1",
        scheduled_gmail_escrow_signing_key_file=str(signing_key),
    )


@pytest.fixture
def escrow_runtime(monkeypatch, tmp_path):
    signing_private_key = Ed25519PrivateKey.generate()
    signing_private_path = tmp_path / "escrow-signing-private.pem"
    signing_public_path = tmp_path / "escrow-signing-public.pem"
    signing_private_path.write_bytes(
        signing_private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    signing_public_path.write_bytes(
        signing_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    signing_private_path.chmod(0o600)
    signing_public_path.chmod(0o600)
    monkeypatch.setenv(
        "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_SIGNING_PRIVATE_KEY_FILE",
        str(signing_private_path),
    )
    monkeypatch.setenv(
        "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_SIGNING_PUBLIC_KEY_FILE",
        str(signing_public_path),
    )
    monkeypatch.setenv(
        "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_SIGNING_KEY_ID",
        "test-escrow-key-v1",
    )
    monkeypatch.setattr(service, "utcnow", lambda: NOW)
    monkeypatch.setattr(service, "settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        service.GrowthRegistry,
        "load",
        classmethod(lambda _cls: _Registry()),
    )
    monkeypatch.setattr(service, "writes_unlocked", lambda: True)
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda *_args: True)
    monkeypatch.setattr(service, "_control_enabled", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        service,
        "_authoritative_send_readiness_reason",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "_preclaim_outreach_readiness_reason",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "_assert_outreach_pre_send_guard",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(service, "_recipient_suppressed", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(service, "_rate_errors", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        service,
        "_verified_sender",
        lambda *_args, **_kwargs: SimpleNamespace(provider="gmail_api"),
    )
    monkeypatch.setattr(
        service,
        "claim_global_recipient_delivery",
        lambda *_args, **_kwargs: SimpleNamespace(
            may_send=True,
            decision="claimed",
            claim_token="offline-global-claim-token",
        ),
    )
    monkeypatch.setattr(
        service,
        "finalize_global_recipient_delivery",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "fail_global_recipient_delivery",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "_assert_canonical_payload",
        lambda row: (service._canonical_metadata(row), row.body_html),
    )
    monkeypatch.setattr(
        service,
        "_assert_current_canonical_screening",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        service,
        "_assert_public_land_evidence_manifest",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "_assert_official_source_evidence_fresh",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "_assert_gmail_account_pacing_due",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "_assert_outreach_reputation_healthy",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        service,
        "_record_outreach_pacing_success",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        SMTPEmailAdapter,
        "live_preflight",
        lambda *_args, **_kwargs: {
            "provider": "gmail_api",
            "profile_email": SENDER,
        },
    )
    monkeypatch.setattr(escrow_service, "utcnow", lambda: NOW)
    monkeypatch.setattr(escrow_service, "writes_unlocked", lambda: True)
    monkeypatch.setattr(
        escrow_service,
        "_control_enabled",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        escrow_service,
        "_preclaim_outreach_readiness_reason",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        escrow_service,
        "_assert_current_canonical_screening",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        escrow_service,
        "_assert_public_land_evidence_manifest",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        escrow_service,
        "_assert_official_source_evidence_fresh",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        escrow_service,
        "_official_source_required",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        escrow_service,
        "_authoritative_send_readiness_reason",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        escrow_service,
        "_recipient_suppressed",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        escrow_service,
        "_rate_errors",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        escrow_service,
        "_verified_sender",
        lambda *_args, **_kwargs: SimpleNamespace(provider="gmail_api"),
    )
    monkeypatch.setattr(
        escrow_service,
        "_assert_outreach_reputation_healthy",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        escrow_service,
        "_outreach_reputation_gap_seconds",
        lambda *_args, **_kwargs: 60.0,
    )
    monkeypatch.setattr(
        escrow_service,
        "claim_global_recipient_delivery",
        lambda *_args, **_kwargs: SimpleNamespace(
            may_send=True,
            decision="claimed",
            claim_token="offline-global-claim-token",
        ),
    )
    monkeypatch.setattr(
        escrow_service,
        "fail_global_recipient_delivery",
        lambda *_args, **_kwargs: None,
    )


def _message(
    index: int,
    *,
    status: str = "queued",
    sent_at: datetime | None = None,
    public_land: bool = False,
    motor_key: str = "construction",
) -> tuple[GrowthSignal, OutreachMessage]:
    outreach_id = f"OUT-OFFLINE-{index:05d}"
    signal_id = f"SIG-OFFLINE-{index:05d}"
    recipient = f"partner{index}@example.test"
    token = f"offline-unsubscribe-{index}"
    body_html = f"<p>Exact offline body {index}</p>"
    canonical = {
        "template_id": "LAND_OWNER_FIRST_CONTACT_HU"
        if public_land
        else "ARCHITECT_OFFICE_FIRST_CONTACT_HU",
        "sender_brand_id": "imperial",
        "recipient_type": "land_owner" if public_land else "architect_office",
        "body_html": body_html,
        "render_input": {
            "unsubscribe_url": (
                f"https://intelligence.test.example/growth/unsubscribe/{token}"
            )
        },
    }
    row = OutreachMessage(
        outreach_id=outreach_id,
        signal_id=signal_id,
        motor_key=motor_key,
        brand_id="imperial",
        sender_email=SENDER,
        recipient_email=recipient,
        sequence_step=0,
        subject=f"Exact offline subject {index}",
        body_text=f"Exact offline body {index}",
        body_html=body_html,
        unsubscribe_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        idempotency_key=hashlib.sha256(f"identity-{index}".encode()).hexdigest(),
        payload_sha256="0" * 64,
        release_approved_by="owner@test",
        release_approved_at=NOW - timedelta(minutes=2),
        status=status,
        available_at=NOW - timedelta(minutes=1),
        attempt_count=0,
        max_attempts=5,
        sent_at=sent_at,
        receipt_json=json.dumps({"canonical_template": canonical}),
        created_at=NOW - timedelta(minutes=3),
        updated_at=NOW - timedelta(minutes=3),
    )
    row.payload_sha256 = service._outreach_payload_sha256(
        sender_email=row.sender_email,
        recipient_email=row.recipient_email,
        subject=row.subject,
        body_text=row.body_text,
        body_html=row.body_html,
        idempotency_key=row.idempotency_key,
        unsubscribe_token_hash=row.unsubscribe_token_hash,
        canonical_metadata=canonical,
    )
    row.release_token_hash = service._release_digest(row, row.release_approved_by)
    public_url = f"https://example.test/listing/{signal_id}"
    signal = GrowthSignal(
        signal_id=signal_id,
        motor_key=motor_key,
        source_id=f"OFFLINE_ESCROW_TEST_{signal_id}",
        source_bucket="public_land_listing" if public_land else "architect_office",
        external_key=signal_id,
        signal_type="residential_building_plot"
        if public_land
        else "residential_construction",
        detected_at=NOW - timedelta(minutes=5),
        company_name="Example Architects",
        recipient_organization_name=None if public_land else "Example Architects",
        subject_type="natural_person" if public_land else "organization",
        recipient_role="property_owner" if public_land else "unknown",
        recipient_email=recipient,
        recipient_email_type="named" if public_land else "role",
        contact_basis="public_property_listing"
        if public_land
        else "public_business_contact",
        public_contact_url=public_url,
        location="Budapest",
        summary="Verified exact offline escrow test candidate.",
        evidence_url=public_url,
        brand_id="imperial",
        score=95,
        urgency=80,
        confidence=95,
        dedupe_hash=hashlib.sha256(f"dedupe-{index}".encode()).hexdigest(),
        source_payload_hash=hashlib.sha256(f"source-{index}".encode()).hexdigest(),
        status="queued",
        rejection_reasons_json="[]",
        first_seen_at=NOW - timedelta(minutes=5),
        last_seen_at=NOW - timedelta(minutes=5),
        created_at=NOW - timedelta(minutes=5),
        updated_at=NOW - timedelta(minutes=5),
    )
    return signal, row


def _add_candidate(db, index: int, **values: Any) -> OutreachMessage:
    signal, row = _message(index, **values)
    db.add(signal)
    db.add(row)
    return row


def _bundle_input(
    rows: list[OutreachMessage],
    *,
    request_id: str,
    quota_dates: list[date],
):
    return _schema(
        "ScheduledGmailEscrowBundleIn",
        request_id=request_id,
        desired_permit_count=len(rows),
        quota_local_dates=quota_dates,
        candidates=[
            {
                "outreach_id": row.outreach_id,
                "expected_payload_sha256": row.payload_sha256,
            }
            for row in rows
        ],
    )


def _issue(db, rows: list[OutreachMessage], principal: _Principal, *, request_id: str):
    return _service_call("issue_scheduled_gmail_escrow_bundle")(
        db,
        _bundle_input(
            rows,
            request_id=request_id,
            quota_dates=[date(2026, 9, 1)],
        ),
        principal,
    )


def _sync_event(
    principal: _Principal,
    permit: dict[str, Any],
    *,
    event_id: str,
    client_sequence: int,
    event_type: str,
    occurred_at: datetime,
    previous_event_sha256: str | None = None,
    provider_transport_called: bool,
    provider_message_id: str | None = None,
    reason: str | None = None,
):
    signed_event = {
        "version": "scheduled-gmail-offline-sync-event-v1",
        "event_id": event_id,
        "permit_id": permit["permit_id"],
        "bundle_id": permit["bundle_id"],
        "client_id": principal.client_id,
        "client_key_id": principal.client_key_id,
        "client_sequence": client_sequence,
        "event_type": event_type,
        "occurred_at": _utc_z(occurred_at),
        "payload_sha256": permit["payload_sha256"],
        "exact_payload_sha256": permit["exact_payload_sha256"],
        "permit_token_sha256": hashlib.sha256(
            permit["permit_token"].encode()
        ).hexdigest(),
        "previous_event_sha256": previous_event_sha256,
        "client_public_key_sha256": principal.offline_public_key_sha256,
        "provider_transport_called": provider_transport_called,
        "provider_message_id": provider_message_id,
        "reason": reason,
    }
    event_sha256, client_signature = _sign_manifest(
        principal._offline_private_key,
        signed_event,
    )
    return _schema(
        "ScheduledGmailEscrowSyncEventIn",
        event_id=event_id,
        permit_id=permit["permit_id"],
        client_sequence=client_sequence,
        event_type=event_type,
        occurred_at=occurred_at,
        payload_sha256=permit["payload_sha256"],
        exact_payload_sha256=permit["exact_payload_sha256"],
        previous_event_sha256=previous_event_sha256,
        event_sha256=event_sha256,
        client_key_id=principal.client_key_id,
        client_signature=client_signature,
        permit_token=permit["permit_token"],
        provider_transport_called=provider_transport_called,
        provider_message_id=provider_message_id,
        reason=reason,
    )


def _permits(result: Any) -> list[dict[str, Any]]:
    permits = _value(result, "permits")
    assert isinstance(permits, list)
    normalized: list[dict[str, Any]] = []
    for raw_item in permits:
        item = raw_item if isinstance(raw_item, dict) else raw_item.model_dump()
        item = dict(item)
        manifest = item.get("manifest")
        if isinstance(manifest, dict):
            for key, value in manifest.items():
                item.setdefault(key, value)
        if "signature" in item:
            item.setdefault("permit_signature", item["signature"])
        if "manifest_sha256" in item:
            item.setdefault("permit_manifest_sha256", item["manifest_sha256"])
        normalized.append(item)
    return normalized


def _day_bounds(local_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(local_date, time.min, tzinfo=ZONE).astimezone(UTC)
    end = datetime.combine(
        local_date + timedelta(days=1),
        time.min,
        tzinfo=ZONE,
    ).astimezone(UTC)
    return start, end


def _add_reserved_permit(
    db,
    *,
    bundle: ScheduledGmailEscrowBundle,
    row: OutreachMessage,
    permit_index: int,
    quota_local_date: date,
) -> ScheduledGmailEscrowPermit:
    day_start, day_end = _day_bounds(quota_local_date)
    slot_start = day_start + timedelta(minutes=permit_index)
    slot_end = min(slot_start + timedelta(minutes=1), day_end)
    lease_id = f"SGL-OFFLINE-{row.outreach_id}"
    raw_token = f"offline-permit-token-{row.outreach_id}-with-enough-entropy"
    db.add(
        ScheduledGmailLease(
            lease_id=lease_id,
            outreach_id=row.outreach_id,
            client_id=bundle.client_id,
            token_nonce=hashlib.sha256(f"nonce-{lease_id}".encode()).hexdigest(),
            lease_token_sha256=hashlib.sha256(f"lease-{lease_id}".encode()).hexdigest(),
            payload_sha256=row.payload_sha256,
            quota_local_date=quota_local_date,
            status="authorized",
            global_guard_claim_token=f"guard-{row.outreach_id}",
            expires_at=day_end,
            authorized_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    permit = ScheduledGmailEscrowPermit(
        permit_id=f"SGP-{row.outreach_id}",
        bundle_id=bundle.bundle_id,
        lease_id=lease_id,
        outreach_id=row.outreach_id,
        client_id=bundle.client_id,
        client_key_id=bundle.client_key_id,
        permit_index=permit_index,
        status="reserved",
        sender_email=row.sender_email,
        motor_key=row.motor_key,
        payload_sha256=row.payload_sha256,
        exact_payload_sha256=hashlib.sha256(
            f"exact-{row.outreach_id}".encode()
        ).hexdigest(),
        outreach_idempotency_key=row.idempotency_key,
        quota_local_date=quota_local_date,
        day_start_utc=day_start,
        day_end_utc=day_end,
        slot_not_before=slot_start,
        slot_not_after=slot_end,
        permit_token_nonce=hashlib.sha256(f"permit-{row.outreach_id}".encode()).hexdigest(),
        permit_token_sha256=hashlib.sha256(raw_token.encode()).hexdigest(),
        global_guard_claim_token=f"guard-{row.outreach_id}",
        global_guard_claim_token_sha256=hashlib.sha256(
            f"guard-{row.outreach_id}".encode()
        ).hexdigest(),
        permit_manifest_sha256=hashlib.sha256(
            f"manifest-{row.outreach_id}".encode()
        ).hexdigest(),
        signing_key_id=bundle.signing_key_id,
        permit_signature=f"signature-{row.outreach_id}",
        quota_reserved_at=NOW,
        last_client_sequence=0,
        created_at=NOW,
        updated_at=NOW,
    )
    row.status = "claimed"
    row.claimed_by = f"scheduled-gmail-escrow:{bundle.client_id}"
    row.claimed_at = NOW
    row.lease_expires_at = None
    db.add(permit)
    return permit


def _add_sent_first_contacts(db, count: int, *, start_index: int = 30_000) -> None:
    for offset in range(count):
        _signal, row = _message(
            start_index + offset,
            status="sent",
            sent_at=NOW - timedelta(minutes=5),
        )
        row.provider_message_id = f"gmail-sent-{start_index + offset}"
        row.receipt_json = json.dumps(
            {
                "provider": "gmail_api",
                "accepted": True,
                "delivery_detail": {
                    "readback_verified": True,
                    "provider_message_id": row.provider_message_id,
                    "label_ids": ["SENT"],
                    "readback_mime_sha256": f"{start_index + offset:064x}",
                },
            }
        )
        db.add(row)


def _offline_bundle_payload(
    signing_private_key: Ed25519PrivateKey,
    *,
    permits: int = 2,
) -> dict[str, Any]:
    bundle_id = "SGB-JOURNAL-0001"
    signing_key_id = "test-escrow-key-v1"
    items: list[dict[str, Any]] = []
    for index in range(permits):
        payload = {
            "outreach_id": f"OUT-JOURNAL-{index:04d}",
            "sender_email": SENDER,
            "recipient_email": f"journal{index}@example.test",
            "subject": f"Exact journal subject {index}",
            "body_text": f"Exact journal body {index}",
            "body_html": f"<p>Exact journal body {index}</p>",
            "payload_sha256": f"{index + 101:064x}",
        }
        permit_token = f"journal-permit-token-{index}-with-sufficient-entropy"
        permit_id = f"SGP-JOURNAL-{index:04d}"
        slot_not_before = NOW - timedelta(minutes=1) + timedelta(
            minutes=2 * index
        )
        permit_manifest = {
            "version": "scheduled-gmail-offline-permit-v1",
            "permit_id": permit_id,
            "bundle_id": bundle_id,
            "lease_id": f"SGL-JOURNAL-{index:04d}",
            "outreach_id": payload["outreach_id"],
            "client_id": "client-a",
            "client_key_id": "client-a-key-v1",
            "permit_index": index,
            "sender_email": SENDER,
            "motor_key": "construction",
            "payload_sha256": payload["payload_sha256"],
            "exact_payload_sha256": _canonical_sha256(payload),
            "outreach_idempotency_key": f"{index + 301:064x}",
            "quota_local_date": "2026-09-01",
            "day_start_utc": "2026-08-31T22:00:00.000000Z",
            "day_end_utc": "2026-09-01T22:00:00.000000Z",
            "slot_not_before": _utc_z(slot_not_before),
            "slot_not_after": _utc_z(slot_not_before + timedelta(minutes=2)),
            "permit_token_sha256": hashlib.sha256(permit_token.encode()).hexdigest(),
            "global_guard_claim_token_sha256": f"{index + 401:064x}",
            "quota_reserved_at": _utc_z(NOW - timedelta(minutes=2)),
            "signing_key_id": signing_key_id,
        }
        permit_manifest_sha256, permit_signature = _sign_manifest(
            signing_private_key,
            permit_manifest,
        )
        items.append(
            {
                **permit_manifest,
                "permit_token": permit_token,
                "manifest": permit_manifest,
                "permit_manifest_sha256": permit_manifest_sha256,
                "permit_signature": permit_signature,
                "signing_key_id": signing_key_id,
                "payload": payload,
            }
        )
    valid_from = _utc_z(NOW - timedelta(hours=1))
    expires_at = _utc_z(NOW + timedelta(hours=2))
    bundle_manifest = {
        "version": "scheduled-gmail-offline-bundle-v1",
        "bundle_id": bundle_id,
        "request_id": "REQ-JOURNAL-OFFLINE-0001",
        "client_id": "client-a",
        "client_key_id": "client-a-key-v1",
        "permit_count": permits,
        "first_quota_local_date": "2026-09-01",
        "last_quota_local_date": "2026-09-01",
        "valid_from": valid_from,
        "expires_at": expires_at,
        "policy_sha256": "a" * 64,
        "client_registry_sha256": "b" * 64,
        "signing_key_id": signing_key_id,
        "issued_at": _utc_z(NOW - timedelta(hours=1)),
        "permits": [
            {
                "permit_index": item["permit_index"],
                "permit_id": item["permit_id"],
                "permit_manifest_sha256": item["permit_manifest_sha256"],
            }
            for item in items
        ],
    }
    bundle_manifest_sha256, bundle_signature = _sign_manifest(
        signing_private_key,
        bundle_manifest,
    )
    return {
        **bundle_manifest,
        "manifest": bundle_manifest,
        "manifest_sha256": bundle_manifest_sha256,
        "manifest_signature": bundle_signature,
        "signing_key_id": signing_key_id,
        "permits": items,
    }


def _coordination_script() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "scheduled_gmail_coordination.py"
    )
    return runpy.run_path(str(path))


def _journal(script: dict[str, Any], path: Path, server_public_key_file: Path):
    journal_class = script.get("OfflineEscrowJournal")
    assert journal_class is not None, "missing OfflineEscrowJournal"
    return journal_class(
        path,
        encryption_key=b"j" * 32,
        client_id="client-a",
        sender_email=SENDER,
        motor_keys=frozenset({"construction"}),
        server_public_key_file=str(server_public_key_file),
    )


def _journal_bundle(
    monkeypatch,
    tmp_path: Path,
    *,
    permits: int = 2,
    slot_offsets: list[timedelta] | None = None,
    slot_width: timedelta = timedelta(minutes=5),
) -> tuple[dict[str, Any], Path]:
    private_key = Ed25519PrivateKey.generate()
    public_key_file = tmp_path / "escrow-server-public.pem"
    public_key_file.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    public_key_file.chmod(0o600)
    monkeypatch.setenv(
        "GROWTH_OPS_SCHEDULED_GMAIL_ESCROW_SIGNING_KEY_ID",
        "test-escrow-key-v1",
    )
    bundle = _offline_bundle_payload(private_key, permits=permits)
    if slot_offsets is not None:
        assert len(slot_offsets) == permits
        for item, offset in zip(bundle["permits"], slot_offsets, strict=True):
            permit_manifest = dict(item["manifest"])
            permit_manifest["slot_not_before"] = _utc_z(NOW + offset)
            permit_manifest["slot_not_after"] = _utc_z(NOW + offset + slot_width)
            manifest_sha256, signature = _sign_manifest(
                private_key,
                permit_manifest,
            )
            item.update(permit_manifest)
            item["manifest"] = permit_manifest
            item["permit_manifest_sha256"] = manifest_sha256
            item["permit_signature"] = signature
        permit_items = list(bundle["permits"])
        bundle_manifest = dict(bundle["manifest"])
        bundle_manifest["permits"] = [
            {
                "permit_index": item["permit_index"],
                "permit_id": item["permit_id"],
                "permit_manifest_sha256": item["permit_manifest_sha256"],
            }
            for item in bundle["permits"]
        ]
        manifest_sha256, signature = _sign_manifest(private_key, bundle_manifest)
        bundle.update(
            {key: value for key, value in bundle_manifest.items() if key != "permits"}
        )
        bundle["permits"] = permit_items
        bundle["manifest"] = bundle_manifest
        bundle["manifest_sha256"] = manifest_sha256
        bundle["manifest_signature"] = signature
    return bundle, public_key_file


def test_offline_escrow_schemas_reject_ambiguous_or_unsafe_states():
    candidate = {
        "outreach_id": "OUT-OFFLINE-SCHEMA",
        "expected_payload_sha256": "a" * 64,
    }
    with pytest.raises(ValueError, match="unique and sorted"):
        _schema(
            "ScheduledGmailEscrowBundleIn",
            request_id="REQ-OFFLINE-SCHEMA-0001",
            desired_permit_count=1,
            quota_local_dates=[date(2026, 9, 2), date(2026, 9, 1)],
            candidates=[candidate],
        )
    with pytest.raises(ValueError, match="match desired"):
        _schema(
            "ScheduledGmailEscrowBundleIn",
            request_id="REQ-OFFLINE-SCHEMA-0002",
            desired_permit_count=2,
            quota_local_dates=[date(2026, 9, 1)],
            candidates=[candidate],
        )
    with pytest.raises(ValueError, match="acceptance requires"):
        _schema(
            "ScheduledGmailEscrowSyncEventIn",
            event_id="EVT-OFFLINE-SCHEMA-0001",
            permit_id="SGP-OFFLINE-SCHEMA",
            client_sequence=1,
            event_type="provider_accepted",
            occurred_at=NOW,
            payload_sha256="b" * 64,
            exact_payload_sha256="f" * 64,
            event_sha256="c" * 64,
            client_key_id="test-client-key",
            client_signature="d" * 43,
            permit_token="e" * 32,
            provider_transport_called=False,
        )
    with pytest.raises(ValueError, match="provably pre-transport"):
        _schema(
            "ScheduledGmailEscrowSyncEventIn",
            event_id="EVT-OFFLINE-SCHEMA-0002",
            permit_id="SGP-OFFLINE-SCHEMA",
            client_sequence=1,
            event_type="expired_unused",
            occurred_at=NOW,
            payload_sha256="b" * 64,
            exact_payload_sha256="f" * 64,
            event_sha256="c" * 64,
            client_key_id="test-client-key",
            client_signature="d" * 43,
            permit_token="e" * 32,
            provider_transport_called=True,
            reason="transport was called",
        )


def test_bundle_issue_is_idempotent_and_binds_each_signed_exact_payload(
    db,
    escrow_runtime,
):
    rows = [_add_candidate(db, index) for index in range(1, 4)]
    db.commit()
    principal = _Principal("client-a")
    data = _bundle_input(
        rows,
        request_id="REQ-OFFLINE-IDEMPOTENT-0001",
        quota_dates=[date(2026, 9, 1)],
    )
    issue = _service_call("issue_scheduled_gmail_escrow_bundle")

    first = issue(db, data, principal)
    second = issue(db, data, principal)

    assert _value(second, "bundle_id") == _value(first, "bundle_id")
    assert _value(second, "manifest_sha256") == _value(first, "manifest_sha256")
    assert (
        _value(second, "manifest_signature") or _value(second, "signature")
    ) == (_value(first, "manifest_signature") or _value(first, "signature"))
    bundle_manifest = _value(first, "manifest")
    assert bundle_manifest["version"] == "scheduled-gmail-offline-bundle-v1"
    assert bundle_manifest["client_id"] == principal.client_id
    assert bundle_manifest["permit_count"] == 3
    assert _canonical_sha256(bundle_manifest) == _value(first, "manifest_sha256")
    first_permits = _permits(first)
    second_permits = _permits(second)
    assert [item["permit_id"] for item in second_permits] == [
        item["permit_id"] for item in first_permits
    ]
    assert db.query(ScheduledGmailEscrowBundle).count() == 1
    assert db.query(ScheduledGmailEscrowPermit).count() == 3
    assert len({item["permit_token"] for item in first_permits}) == 3
    assert len({item["permit_signature"] for item in first_permits}) == 3
    for item, row in zip(first_permits, rows, strict=True):
        manifest = item["manifest"]
        assert manifest["version"] == "scheduled-gmail-offline-permit-v1"
        assert manifest["permit_id"] == item["permit_id"]
        assert _canonical_sha256(manifest) == item["permit_manifest_sha256"]
        assert item["client_id"] == principal.client_id
        assert item["sender_email"] == row.sender_email
        assert item["motor_key"] == row.motor_key
        assert item["payload_sha256"] == row.payload_sha256
        assert item["exact_payload_sha256"] == _canonical_sha256(item["payload"])
        assert item["payload"]["subject"] == row.subject
        assert item["payload"]["body_text"] == row.body_text
        assert item["payload"]["body_html"] == row.body_html
    assert bundle_manifest["permits"] == [
        {
            "permit_index": item["permit_index"],
            "permit_id": item["permit_id"],
            "permit_manifest_sha256": item["permit_manifest_sha256"],
        }
        for item in first_permits
    ]


def test_read_only_bundle_status_never_returns_transport_tokens_or_message_payload(
    db,
    escrow_runtime,
):
    row = _add_candidate(db, 90)
    db.commit()
    issuing_principal = _Principal("client-a")
    issued = _issue(
        db,
        [row],
        issuing_principal,
        request_id="REQ-OFFLINE-STATUS-REDACTED",
    )
    read_only_principal = _Principal("client-a")
    read_only_principal.permissions = frozenset({"read"})

    status = _service_call("scheduled_gmail_escrow_bundle_status")(
        db,
        _value(issued, "bundle_id"),
        read_only_principal,
    )

    permit = _permits(status)[0]
    assert permit["status"] == "reserved"
    assert "permit_token" not in permit
    assert "payload" not in permit
    assert "subject" not in permit
    assert "body_text" not in permit
    assert "body_html" not in permit


def test_bundle_request_id_cannot_be_reused_for_different_candidates(
    db,
    escrow_runtime,
):
    first = _add_candidate(db, 101)
    replacement = _add_candidate(db, 102)
    db.commit()
    principal = _Principal("client-a")
    request_id = "REQ-OFFLINE-IDEMPOTENCY-CONFLICT"
    issue = _service_call("issue_scheduled_gmail_escrow_bundle")
    issued = issue(
        db,
        _bundle_input(
            [first],
            request_id=request_id,
            quota_dates=[date(2026, 9, 1)],
        ),
        principal,
    )
    assert _permits(issued)[0]["outreach_id"] == first.outreach_id

    with pytest.raises(GrowthRegistryError, match="request_conflict|idempotency"):
        issue(
            db,
            _bundle_input(
                [replacement],
                request_id=request_id,
                quota_dates=[date(2026, 9, 1)],
            ),
            principal,
        )
    db.refresh(replacement)
    assert replacement.status == "queued"
    assert db.query(ScheduledGmailEscrowPermit).count() == 1


def test_bad_explicit_candidate_is_audited_without_stopping_later_good_rows(
    db,
    escrow_runtime,
):
    first = _add_candidate(db, 103)
    bad = _add_candidate(db, 104)
    last = _add_candidate(db, 105)
    db.commit()
    data = _schema(
        "ScheduledGmailEscrowBundleIn",
        request_id="REQ-OFFLINE-ROW-ISOLATION-0001",
        desired_permit_count=3,
        quota_local_dates=[date(2026, 9, 1)],
        candidates=[
            {
                "outreach_id": first.outreach_id,
                "expected_payload_sha256": first.payload_sha256,
            },
            {
                "outreach_id": bad.outreach_id,
                "expected_payload_sha256": "f" * 64,
            },
            {
                "outreach_id": last.outreach_id,
                "expected_payload_sha256": last.payload_sha256,
            },
        ],
    )

    issued = _service_call("issue_scheduled_gmail_escrow_bundle")(
        db,
        data,
        _Principal("client-a"),
    )

    assert [item["outreach_id"] for item in _permits(issued)] == [
        first.outreach_id,
        last.outreach_id,
    ]
    db.refresh(bad)
    assert bad.status == "queued"
    rejection = db.query(service.AuditLog).filter_by(
        action="growth_scheduled_gmail_escrow_candidate_rejected_no_send",
        entity_id=bad.outreach_id,
    ).one()
    assert "payload_hash_mismatch" in rejection.after_json


def test_hundreds_of_permits_reserve_their_own_slots_across_budapest_days(
    db,
    escrow_runtime,
):
    quota_dates = [date(2026, 10, 24), date(2026, 10, 25), date(2026, 10, 26)]
    bundle = ScheduledGmailEscrowBundle(
        bundle_id="SGB-MULTIDAY-0300",
        request_id="REQ-OFFLINE-MULTIDAY-0300",
        client_id="client-a",
        client_key_id="client-a-key-v1",
        status="active",
        permit_count=300,
        first_quota_local_date=quota_dates[0],
        last_quota_local_date=quota_dates[-1],
        valid_from=_day_bounds(quota_dates[0])[0],
        expires_at=_day_bounds(quota_dates[-1])[1],
        policy_sha256="1" * 64,
        client_registry_sha256="2" * 64,
        manifest_sha256="3" * 64,
        signing_key_id="test-escrow-key-v1",
        manifest_signature="signed-multiday-manifest",
        issued_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(bundle)
    for index in range(300):
        row = _add_candidate(db, 1_000 + index)
        _add_reserved_permit(
            db,
            bundle=bundle,
            row=row,
            permit_index=index,
            quota_local_date=quota_dates[index // 100],
        )
    db.commit()

    permits = db.query(ScheduledGmailEscrowPermit).all()
    assert len(permits) == 300
    assert len({item.outreach_id for item in permits}) == 300
    assert len({item.permit_manifest_sha256 for item in permits}) == 300
    for local_date in quota_dates:
        day_start, day_end = _day_bounds(local_date)
        usage = service._outreach_budapest_day_usage(
            db,
            day_start + (day_end - day_start) / 2,
        )
        assert usage.effective_reserved_count == 100
        assert len(usage.reservation_keys) == 100


def test_central_online_and_escrow_share_the_exact_2000_boundary(
    db,
    escrow_runtime,
):
    _add_sent_first_contacts(db, 1998)
    online = _add_candidate(db, 40_001, status="claimed")
    online.claimed_by = "scheduled-gmail:client-online"
    online.claimed_at = NOW
    online.lease_expires_at = NOW + timedelta(minutes=5)
    offline = _add_candidate(db, 40_002)
    bundle = ScheduledGmailEscrowBundle(
        bundle_id="SGB-BOUNDARY-0001",
        request_id="REQ-OFFLINE-BOUNDARY-0001",
        client_id="client-offline",
        client_key_id="client-offline-key-v1",
        status="active",
        permit_count=1,
        first_quota_local_date=date(2026, 9, 1),
        last_quota_local_date=date(2026, 9, 1),
        valid_from=_day_bounds(date(2026, 9, 1))[0],
        expires_at=_day_bounds(date(2026, 9, 1))[1],
        policy_sha256="4" * 64,
        client_registry_sha256="5" * 64,
        manifest_sha256="6" * 64,
        signing_key_id="test-escrow-key-v1",
        manifest_signature="signed-boundary-manifest",
        issued_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(bundle)
    _add_reserved_permit(
        db,
        bundle=bundle,
        row=offline,
        permit_index=0,
        quota_local_date=date(2026, 9, 1),
    )
    extra = _add_candidate(db, 40_003)
    db.commit()

    usage = service._outreach_budapest_day_usage(db, NOW)
    assert usage.sent_first_contacts == 1998
    assert usage.active_claim_reservations == 2
    assert usage.effective_reserved_count == 2000
    with pytest.raises(
        (EmailDeliveryError, GrowthRegistryError),
        match="2000|limit|quota",
    ):
        _issue(
            db,
            [extra],
            _Principal("client-extra"),
            request_id="REQ-OFFLINE-BOUNDARY-EXTRA",
        )


def test_public_land_live_evidence_rows_are_never_escrowed(
    db,
    escrow_runtime,
):
    public_land = _add_candidate(db, 41_001, public_land=True)
    db.commit()

    with pytest.raises(
        (EmailDeliveryError, GrowthRegistryError),
        match="public_land|live.*evidence|escrow",
    ):
        _issue(
            db,
            [public_land],
            _Principal("client-a"),
            request_id="REQ-OFFLINE-PUBLIC-LAND",
        )
    db.refresh(public_land)
    assert public_land.status == "queued"
    assert db.query(ScheduledGmailEscrowPermit).count() == 0


def test_two_clients_cannot_obtain_overlapping_permits_for_one_outreach(
    db,
    escrow_runtime,
):
    row = _add_candidate(db, 42_001)
    db.commit()
    issue = _service_call("issue_scheduled_gmail_escrow_bundle")
    inputs = [
        (
            _bundle_input(
                [row],
                request_id=f"REQ-OFFLINE-COMPETING-{suffix}",
                quota_dates=[date(2026, 9, 1)],
            ),
            _Principal(f"client-{suffix}"),
        )
        for suffix in ("a", "b")
    ]

    first = issue(db, *inputs[0])
    assert len(_permits(first)) == 1
    with pytest.raises(
        (EmailDeliveryError, GrowthRegistryError, ValueError),
        match="claimed|reserved|client|permit|conflict|unavailable",
    ):
        issue(db, *inputs[1])
    assert db.query(ScheduledGmailEscrowPermit).count() == 1


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="the real row-lock race is a PostgreSQL integration contract",
)
def test_two_concurrent_clients_issue_at_most_one_permit_for_one_outreach(
    db,
    escrow_runtime,
):
    row = _add_candidate(db, 42_002)
    db.commit()
    barrier = __import__("threading").Barrier(2)

    def run(suffix: str) -> str:
        with SessionLocal() as session:
            candidate = session.get(OutreachMessage, row.id)
            assert candidate is not None
            barrier.wait(timeout=5)
            try:
                _issue(
                    session,
                    [candidate],
                    _Principal(f"client-{suffix}"),
                    request_id=f"REQ-OFFLINE-RACE-{suffix}-0001",
                )
            except (EmailDeliveryError, GrowthRegistryError, ValueError):
                return "blocked"
            return "issued"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, ("a", "b")))
    assert sorted(results) == ["blocked", "issued"]
    db.expire_all()
    assert db.query(ScheduledGmailEscrowPermit).count() == 1


def test_offline_fallback_allows_network_and_transient_server_unavailability():
    script = _coordination_script()
    allowed = script.get("_offline_fallback_allowed")
    error_class = script.get("CoordinationError")
    assert callable(allowed), "missing _offline_fallback_allowed"
    assert error_class is not None

    assert allowed(error_class("coordination_api_unavailable:URLError")) is True
    assert allowed(error_class("coordination_api_unavailable:TimeoutError")) is True
    assert allowed(error_class("coordination_api_http_502")) is True
    assert allowed(error_class("coordination_api_http_503")) is True
    assert allowed(error_class("coordination_api_http_504")) is True
    assert allowed(error_class("coordination_api_http_400")) is False
    assert allowed(error_class("coordination_api_http_409")) is False
    assert allowed(error_class("coordination_api_http_429")) is False
    assert (
        allowed(
            urllib.error.HTTPError(
                "http://127.0.0.1/coordination",
                503,
                "unavailable",
                {},
                None,
            )
        )
        is True
    )
    assert allowed(ValueError("server_response_invalid")) is False


def test_journal_rejects_payload_tampering_before_caching(tmp_path, monkeypatch):
    script = _coordination_script()
    error_class = script["CoordinationError"]
    bundle, public_key_file = _journal_bundle(monkeypatch, tmp_path, permits=1)
    bundle["permits"][0]["payload"]["subject"] = "Tampered subject"
    journal = _journal(
        script,
        tmp_path / "offline-tampered.sqlite3",
        public_key_file,
    )

    with pytest.raises(error_class, match="exact_payload_hash_mismatch"):
        journal.import_bundle(bundle, now=NOW)
    assert journal.claim_next(
        now=NOW,
        coordination_error=error_class("coordination_api_unavailable:URLError"),
    ) is None


def test_bundle_client_public_key_binding_is_checked_at_import_and_claim(
    tmp_path,
    monkeypatch,
):
    script = _coordination_script()
    journal_class = script["OfflineEscrowJournal"]
    error_class = script["CoordinationError"]
    bundle, public_key_file = _journal_bundle(monkeypatch, tmp_path, permits=1)
    journal_path = tmp_path / "offline-client-key-binding.sqlite3"
    journal = _journal(script, journal_path, public_key_file)

    bundle["client_public_key_sha256"] = "f" * 64
    with pytest.raises(error_class, match="client_public_key_mismatch"):
        journal.import_bundle(bundle, now=NOW)
    bundle["client_public_key_sha256"] = ""
    with pytest.raises(error_class, match="client_public_key_mismatch"):
        journal.import_bundle(bundle, now=NOW)

    bundle["client_public_key_sha256"] = journal.client_public_key_sha256
    assert journal.import_bundle(bundle, now=NOW) == 1
    replacement_key = Ed25519PrivateKey.generate()
    replacement_key_file = tmp_path / "replacement-client-private.pem"
    replacement_key_file.write_bytes(
        replacement_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    replacement_key_file.chmod(0o600)
    reopened = journal_class(
        journal_path,
        encryption_key=b"j" * 32,
        client_id="client-a",
        sender_email=SENDER,
        motor_keys=frozenset({"construction"}),
        client_signing_key_file=str(replacement_key_file),
        server_public_key_file=str(public_key_file),
    )
    with pytest.raises(error_class, match="client_public_key_mismatch"):
        reopened.claim_next(
            now=NOW,
            coordination_error=error_class("coordination_api_http_503"),
        )


def test_pending_event_hash_and_signature_reconstruct_from_bound_metadata(
    tmp_path,
    monkeypatch,
):
    script = _coordination_script()
    error_class = script["CoordinationError"]
    canonical_json = script["canonical_escrow_json"]
    bundle, public_key_file = _journal_bundle(monkeypatch, tmp_path, permits=1)
    journal = _journal(
        script,
        tmp_path / "offline-event-signature.sqlite3",
        public_key_file,
    )
    journal.import_bundle(bundle, now=NOW)
    journal.claim_next(
        now=NOW,
        coordination_error=error_class("coordination_api_unavailable:URLError"),
    )
    event = journal.pending_events(bundle["bundle_id"])[0]
    permit = bundle["permits"][0]
    signed_event = {
        "version": "scheduled-gmail-offline-sync-event-v1",
        "event_id": event["event_id"],
        "permit_id": event["permit_id"],
        "bundle_id": permit["bundle_id"],
        "client_id": permit["client_id"],
        "client_key_id": event["client_key_id"],
        "client_sequence": event["client_sequence"],
        "event_type": event["event_type"],
        "occurred_at": event["occurred_at"],
        "payload_sha256": event["payload_sha256"],
        "exact_payload_sha256": event["exact_payload_sha256"],
        "permit_token_sha256": permit["permit_token_sha256"],
        "previous_event_sha256": event["previous_event_sha256"],
        "client_public_key_sha256": journal.client_public_key_sha256,
        "provider_transport_called": event["provider_transport_called"],
        "provider_message_id": event["provider_message_id"],
        "reason": event["reason"],
    }
    assert _canonical_sha256(signed_event) == event["event_sha256"]
    signature = str(event["client_signature"])
    signature_bytes = base64.urlsafe_b64decode(
        (signature + "=" * (-len(signature) % 4)).encode("ascii")
    )
    journal._client_private_key.public_key().verify(
        signature_bytes,
        canonical_json(signed_event).encode("utf-8"),
    )


def test_journal_encrypts_payload_and_never_resets_consuming_to_ready(
    tmp_path,
    monkeypatch,
):
    script = _coordination_script()
    error_class = script["CoordinationError"]
    journal_path = tmp_path / "offline-escrow.sqlite3"
    bundle, public_key_file = _journal_bundle(monkeypatch, tmp_path, permits=1)
    journal = _journal(script, journal_path, public_key_file)

    assert journal.import_bundle(bundle, now=NOW) == 1
    claimed = journal.claim_next(
        now=NOW,
        coordination_error=error_class("coordination_api_unavailable:URLError"),
    )
    assert claimed["permit_id"] == "SGP-JOURNAL-0000"
    assert claimed["payload"]["recipient_email"] == "journal0@example.test"
    assert journal.claim_next(
        now=NOW,
        coordination_error=error_class("coordination_api_unavailable:URLError"),
    ) is None

    reopened = _journal(script, journal_path, public_key_file)
    assert reopened.claim_next(
        now=NOW,
        coordination_error=error_class("coordination_api_unavailable:URLError"),
    ) is None
    raw = journal_path.read_bytes()
    assert b"journal0@example.test" not in raw
    assert b"Exact journal body 0" not in raw
    assert b"journal-permit-token" not in raw
    assert reopened.journal_mode().casefold() == "wal"


def test_two_local_workers_cannot_consume_one_permit_twice(tmp_path, monkeypatch):
    script = _coordination_script()
    error_class = script["CoordinationError"]
    bundle, public_key_file = _journal_bundle(monkeypatch, tmp_path, permits=1)
    journal_path = tmp_path / "offline-concurrent.sqlite3"
    _journal(script, journal_path, public_key_file).import_bundle(bundle, now=NOW)

    def claim() -> str | None:
        result = _journal(script, journal_path, public_key_file).claim_next(
            now=NOW,
            coordination_error=error_class("coordination_api_unavailable:URLError"),
        )
        return None if result is None else str(result["permit_id"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: claim(), range(2)))

    assert results.count("SGP-JOURNAL-0000") == 1
    assert results.count(None) == 1


def test_hourly_task_waits_into_offset_narrow_slots_without_burst(
    tmp_path,
    monkeypatch,
):
    script = _coordination_script()
    run = script["_run"]
    parser = script["_parser"]()
    error_class = script["CoordinationError"]
    assert parser.parse_args(
        ["offline-next", "--wait-seconds", "3600"]
    ).wait_seconds == 3_600
    with pytest.raises(SystemExit):
        parser.parse_args(["offline-next", "--wait-seconds", "3601"])
    bundle, public_key_file = _journal_bundle(
        monkeypatch,
        tmp_path,
        permits=2,
        slot_offsets=[timedelta(minutes=17), timedelta(minutes=47)],
        slot_width=timedelta(seconds=8),
    )
    journal = _journal(
        script,
        tmp_path / "offline-hourly-offset.sqlite3",
        public_key_file,
    )
    journal.import_bundle(bundle, now=NOW)
    outage = error_class("coordination_api_http_503")
    sleeps: list[float] = []
    probes: list[str] = []
    monkeypatch.setitem(run.__globals__, "_offline_journal", lambda _args: journal)
    monkeypatch.setitem(run.__globals__, "_client_token", lambda _value=None: "token")
    monkeypatch.setitem(run.__globals__, "_monotonic", lambda: 0.0)
    monkeypatch.setitem(run.__globals__, "_sleep_seconds", sleeps.append)

    def probe(**_values):
        probes.append("outage")
        return outage

    monkeypatch.setitem(run.__globals__, "_coordination_outage", probe)
    args = SimpleNamespace(
        api_base_url=(
            "http://127.0.0.1:8000/api/internal/growth-ops/scheduled-gmail"
        ),
        client_token_file=None,
        command="offline-next",
        now=_utc_z(NOW),
        wait_seconds=0,
    )

    due = run(args)

    assert due == {
        "status": "WAITING_FOR_PERMIT_SLOT",
        "next_due_at": _utc_z(NOW + timedelta(minutes=17)),
        "wait_seconds": 17 * 60,
    }
    assert "payload" not in due
    assert "permit_token" not in json.dumps(due)

    args.wait_seconds = 3_600
    first = run(args)
    assert first["permit_id"] == "SGP-JOURNAL-0000"
    assert sum(sleeps) == pytest.approx(17 * 60)
    assert max(sleeps) <= 60

    sleeps.clear()
    args.now = _utc_z(NOW + timedelta(minutes=17))
    second = run(args)
    assert second["permit_id"] == "SGP-JOURNAL-0001"
    assert sum(sleeps) == pytest.approx(30 * 60)
    assert max(sleeps) <= 60
    assert len(probes) > 2

    args.now = _utc_z(NOW + timedelta(minutes=47))
    assert run(args) == {"status": "NO_READY_PERMIT"}
    consumed = [
        event
        for event in journal.pending_events(bundle["bundle_id"])
        if event["event_type"] == "permit_consumed"
    ]
    assert [event["occurred_at"] for event in consumed] == [
        _utc_z(NOW + timedelta(minutes=17)),
        _utc_z(NOW + timedelta(minutes=47)),
    ]


def test_signed_overlapping_slots_are_rejected_before_they_can_burst(
    tmp_path,
    monkeypatch,
):
    script = _coordination_script()
    error_class = script["CoordinationError"]
    bundle, public_key_file = _journal_bundle(
        monkeypatch,
        tmp_path,
        permits=2,
        slot_offsets=[timedelta(minutes=17), timedelta(minutes=17)],
        slot_width=timedelta(seconds=8),
    )
    journal = _journal(
        script,
        tmp_path / "offline-overlapping-slots.sqlite3",
        public_key_file,
    )

    with pytest.raises(error_class, match="slots_overlap"):
        journal.import_bundle(bundle, now=NOW)


def test_corrupt_event_chain_is_quarantined_without_blocking_other_permits(
    tmp_path,
    monkeypatch,
):
    script = _coordination_script()
    error_class = script["CoordinationError"]
    bundle, public_key_file = _journal_bundle(monkeypatch, tmp_path, permits=2)
    journal = _journal(
        script,
        tmp_path / "offline-corrupt-event.sqlite3",
        public_key_file,
    )
    journal.import_bundle(bundle, now=NOW)
    outage = error_class("coordination_api_http_503")
    first = journal.claim_next(NOW, outage)
    journal.record_provider_accepted(
        first["permit_id"],
        "gmail-corrupt-chain-first",
        NOW + timedelta(seconds=1),
    )
    second = journal.claim_next(NOW + timedelta(minutes=1), outage)
    journal.record_ambiguous(
        second["permit_id"],
        "second_permit_transport_is_ambiguous",
        NOW + timedelta(minutes=1, seconds=2),
    )
    with journal._immediate() as connection:
        connection.execute(
            """
            UPDATE escrow_events SET encrypted_event = ?
            WHERE permit_id = ? AND event_type = 'provider_accepted'
            """,
            (b"locally-corrupted-ciphertext", first["permit_id"]),
        )

    events, errors = journal.pending_events_with_errors(bundle["bundle_id"])

    assert {event["permit_id"] for event in events} == {second["permit_id"]}
    assert {error["permit_id"] for error in errors} == {first["permit_id"]}
    assert {error["error"] for error in errors} >= {
        "escrow_event_decryption_failed",
        "escrow_event_chain_quarantined",
    }


def test_policy_http_failure_does_not_consume_but_server_outage_does(
    tmp_path,
    monkeypatch,
):
    script = _coordination_script()
    error_class = script["CoordinationError"]
    bundle, public_key_file = _journal_bundle(monkeypatch, tmp_path, permits=1)
    journal = _journal(
        script,
        tmp_path / "offline-http.sqlite3",
        public_key_file,
    )
    journal.import_bundle(bundle, now=NOW)

    for status in (400, 401, 403, 409, 429):
        with pytest.raises(error_class, match=f"http_{status}"):
            journal.claim_next(
                now=NOW,
                coordination_error=error_class(f"coordination_api_http_{status}"),
            )
    claimed = journal.claim_next(
        now=NOW,
        coordination_error=error_class("coordination_api_http_503"),
    )
    assert claimed["permit_id"] == "SGP-JOURNAL-0000"


def test_accepted_or_ambiguous_journal_entries_are_never_auto_resent(
    tmp_path,
    monkeypatch,
):
    script = _coordination_script()
    error_class = script["CoordinationError"]
    journal_path = tmp_path / "offline-no-resend.sqlite3"
    bundle, public_key_file = _journal_bundle(monkeypatch, tmp_path, permits=2)
    journal = _journal(script, journal_path, public_key_file)
    journal.import_bundle(bundle, now=NOW)
    unavailable = error_class("coordination_api_unavailable:URLError")

    accepted = journal.claim_next(now=NOW, coordination_error=unavailable)
    accepted_event = journal.record_provider_accepted(
        accepted["permit_id"],
        provider_message_id="gmail-offline-accepted",
        occurred_at=NOW + timedelta(seconds=10),
    )
    assert accepted_event["event_type"] == "provider_accepted"
    ambiguous = journal.claim_next(
        now=NOW + timedelta(minutes=1),
        coordination_error=unavailable,
    )
    ambiguous_event = journal.record_ambiguous(
        ambiguous["permit_id"],
        reason="gmail_call_returned_without_a_verifiable_response",
        occurred_at=NOW + timedelta(minutes=1, seconds=20),
    )
    assert ambiguous_event["event_type"] == "transport_ambiguous"

    reopened = _journal(script, journal_path, public_key_file)
    assert reopened.claim_next(now=NOW, coordination_error=unavailable) is None
    pending = reopened.pending_events(bundle_id="SGB-JOURNAL-0001")
    assert {item["event_type"] for item in pending} >= {
        "provider_accepted",
        "transport_ambiguous",
    }
    assert all(item["provider_transport_called"] for item in pending if item["event_type"] in {
        "provider_accepted",
        "transport_ambiguous",
    })


def test_pretransport_abort_is_signed_from_consuming_without_transport(
    tmp_path,
    monkeypatch,
):
    script = _coordination_script()
    error_class = script["CoordinationError"]
    bundle, public_key_file = _journal_bundle(monkeypatch, tmp_path, permits=1)
    journal = _journal(
        script,
        tmp_path / "offline-pretransport-abort.sqlite3",
        public_key_file,
    )
    journal.import_bundle(bundle, now=NOW)
    claimed = journal.claim_next(
        now=NOW,
        coordination_error=error_class("coordination_api_http_503"),
    )

    aborted = journal.record_pretransport_abort(
        claimed["permit_id"],
        reason="gmail_transport_was_provably_not_called",
        occurred_at=NOW + timedelta(seconds=5),
    )

    assert aborted["event_type"] == "pretransport_aborted"
    assert aborted["provider_transport_called"] is False
    events = journal.pending_events(bundle["bundle_id"])
    assert [event["event_type"] for event in events] == [
        "permit_consumed",
        "pretransport_aborted",
    ]
    assert [event["client_sequence"] for event in events] == [1, 2]
    assert events[1]["previous_event_sha256"] == events[0]["event_sha256"]


def test_unused_permit_is_released_only_after_central_ack(tmp_path, monkeypatch):
    script = _coordination_script()
    error_class = script["CoordinationError"]
    bundle, public_key_file = _journal_bundle(monkeypatch, tmp_path, permits=1)
    journal = _journal(
        script,
        tmp_path / "offline-release.sqlite3",
        public_key_file,
    )
    journal.import_bundle(bundle, now=NOW)
    permit_id = "SGP-JOURNAL-0000"

    with pytest.raises(error_class, match="not_prepared"):
        journal.release_unused_after_ack(
            permit_id,
            central_ack={},
            occurred_at=NOW,
        )
    prepared = journal.prepare_expired_unused(NOW + timedelta(hours=2))
    assert len(prepared) == 1
    assert prepared[0]["event_type"] == "expired_unused"
    assert prepared[0]["provider_transport_called"] is False
    assert journal.prepare_expired_unused(NOW + timedelta(hours=2)) == []
    with journal._connect() as connection:
        assert connection.execute(
            "SELECT status FROM escrow_permits WHERE permit_id = ?",
            (permit_id,),
        ).fetchone()[0] == "READY"
    assert journal.claim_next(
        now=NOW,
        coordination_error=error_class("coordination_api_http_503"),
    ) is None

    with pytest.raises(error_class, match="not_acknowledged"):
        journal.release_unused_after_ack(
            permit_id,
            central_ack={"events": []},
            occurred_at=NOW + timedelta(hours=2),
        )
    released = journal.release_unused_after_ack(
        permit_id,
        central_ack={
            "permit_id": permit_id,
            "event_id": prepared[0]["event_id"],
            "processing_status": "applied",
            "status": "aborted",
            "provider_transport_called": False,
            "acknowledged_at": NOW.isoformat(),
        },
        occurred_at=NOW + timedelta(hours=2),
    )
    assert released["event_type"] == "expired_unused"
    assert released["provider_transport_called"] is False
    assert journal.claim_next(
        now=NOW,
        coordination_error=error_class("coordination_api_unavailable:URLError"),
    ) is None


def test_sync_automatically_prepares_expired_unused_events_before_upload():
    script = _coordination_script()
    run = script["_run"]
    calls: list[str] = []

    class FakeJournal:
        def prepare_expired_unused(self, now, *, bundle_ids=None):
            assert now.tzinfo is not None
            assert bundle_ids is None
            calls.append("prepare")
            return [{"event_id": "SGE-EXPIRED-0001"}]

        def bundle_ids_with_pending_events(self):
            calls.append("list")
            return ["SGB-JOURNAL-0001"]

        def pending_events(self, bundle_id):
            assert bundle_id == "SGB-JOURNAL-0001"
            calls.append("pending")
            return [
                {
                    "event_id": "SGE-EXPIRED-0001",
                    "permit_id": "SGP-JOURNAL-0000",
                    "permit_token": "offline-permit-token-with-enough-entropy",
                }
            ]

        def pending_events_with_errors(self, bundle_id):
            return self.pending_events(bundle_id), []

        def apply_sync_acknowledgements(self, response, *, now):
            assert response["events"][0]["event_id"] == "SGE-EXPIRED-0001"
            assert now.tzinfo is not None
            calls.append("ack")
            return 1

    def fake_request(**kwargs):
        assert kwargs["method"] == "POST"
        assert kwargs["payload"]["events"][0]["event_id"] == "SGE-EXPIRED-0001"
        calls.append("upload")
        return {
            "status": "reconciled",
            "events": [
                {
                    "event_id": "SGE-EXPIRED-0001",
                    "permit_id": "SGP-JOURNAL-0000",
                    "processing_status": "applied",
                    "permit_status": "aborted",
                }
            ],
        }

    run.__globals__["_client_token"] = lambda _value: "test-bearer-token"
    run.__globals__["_offline_journal"] = lambda _args: FakeJournal()
    run.__globals__["_request"] = fake_request
    result = run(
        SimpleNamespace(
            command="sync",
            api_base_url=(
                "http://127.0.0.1:8000/api/internal/growth-ops/scheduled-gmail"
            ),
            client_token_file=None,
            bundle_id=None,
        )
    )

    assert calls == ["prepare", "list", "pending", "upload", "ack"]
    assert result["expired_unused_prepared"] == 1
    assert result["bundles"][0]["events_applied"] == 1


def _verified_receipt(
    provider_message_id: str,
    *,
    accepted_at: datetime,
) -> EmailReceipt:
    mime_sha256 = hashlib.sha256(provider_message_id.encode()).hexdigest()
    return EmailReceipt(
        provider_message_id=provider_message_id,
        accepted_recipient="partner@example.test",
        provider="gmail_api",
        response_sha256=mime_sha256,
        detail={
            "accepted": True,
            "readback_verified": True,
            "provider_message_id": provider_message_id,
            "provider_internal_date": accepted_at.isoformat(),
            "readback_mime_sha256": mime_sha256,
            "rfc_message_id": f"<{provider_message_id}@example.test>",
            "label_ids": ["SENT"],
        },
    )


def test_provider_accepted_sync_requires_gmail_sent_exact_mime_readback(
    db,
    escrow_runtime,
    monkeypatch,
):
    row = _add_candidate(db, 43_001)
    db.commit()
    principal = _Principal("client-a")
    issued = _issue(
        db,
        [row],
        principal,
        request_id="REQ-OFFLINE-SYNC-ACCEPTED",
    )
    permit = _permits(issued)[0]
    provider_id = "gmail-offline-exact-readback"
    verify_calls: list[dict[str, Any]] = []
    transport_at = datetime.fromisoformat(
        str(permit["slot_not_before"]).replace("Z", "+00:00")
    ) + timedelta(seconds=1)
    accepted_at = transport_at + timedelta(seconds=10)
    monkeypatch.setattr(service, "utcnow", lambda: accepted_at)
    monkeypatch.setattr(escrow_service, "utcnow", lambda: accepted_at)

    def verify(_adapter, **values):
        verify_calls.append(values)
        assert values["provider_message_id"] == provider_id
        assert values["to_email"] == row.recipient_email
        assert values["subject"] == row.subject
        assert values["body_text"] == row.body_text
        assert values["body_html"] == row.body_html
        return _verified_receipt(provider_id, accepted_at=accepted_at)

    monkeypatch.setattr(
        SMTPEmailAdapter,
        "verify_scheduled_gmail_delivery",
        verify,
    )
    event = _sync_event(
        principal,
        permit,
        event_id="EVT-OFFLINE-SYNC-CONSUME",
        client_sequence=1,
        event_type="permit_consumed",
        occurred_at=transport_at,
        provider_transport_called=False,
    )
    accepted = _sync_event(
        principal,
        permit,
        event_id="EVT-OFFLINE-SYNC-ACCEPTED",
        client_sequence=2,
        event_type="provider_accepted",
        occurred_at=accepted_at,
        previous_event_sha256=event.event_sha256,
        provider_transport_called=True,
        provider_message_id=provider_id,
    )
    result = _service_call("sync_scheduled_gmail_escrow_events")(
        db,
        _schema(
            "ScheduledGmailEscrowSyncIn",
            request_id="REQ-OFFLINE-SYNC-BATCH-0001",
            bundle_id=_value(issued, "bundle_id"),
            events=[event, accepted],
        ),
        principal,
    )

    assert _value(result, "status") in {"sent", "reconciled"}
    assert len(verify_calls) == 1
    db.refresh(row)
    assert row.status == "sent"
    assert row.provider_message_id == provider_id
    persisted = db.query(ScheduledGmailEscrowPermit).filter_by(
        permit_id=permit["permit_id"]
    ).one()
    assert persisted.status == "sent"
    assert persisted.readback_mime_sha256


def test_malformed_sync_event_does_not_block_a_later_valid_event(
    db,
    escrow_runtime,
):
    row = _add_candidate(db, 43_003)
    db.commit()
    principal = _Principal("client-a")
    issued = _issue(
        db,
        [row],
        principal,
        request_id="REQ-OFFLINE-SYNC-ROW-ISOLATION",
    )
    permit = _permits(issued)[0]
    transport_at = datetime.fromisoformat(
        str(permit["slot_not_before"]).replace("Z", "+00:00")
    ) + timedelta(seconds=1)
    valid = _sync_event(
        principal,
        permit,
        event_id="EVT-OFFLINE-SYNC-VALID-AFTER-BAD",
        client_sequence=1,
        event_type="permit_consumed",
        occurred_at=transport_at,
        provider_transport_called=False,
    )

    result = _service_call("sync_scheduled_gmail_escrow_events")(
        db,
        _schema(
            "ScheduledGmailEscrowSyncIn",
            request_id="REQ-OFFLINE-SYNC-MIXED-BATCH",
            bundle_id=_value(issued, "bundle_id"),
            events=[
                {
                    "event_id": "EVT-OFFLINE-SYNC-MALFORMED",
                    "permit_id": permit["permit_id"],
                    "event_type": "not-a-real-event",
                },
                valid,
            ],
        ),
        principal,
    )

    events = _value(result, "events")
    assert events[0]["processing_status"] == "rejected"
    assert events[1]["processing_status"] == "applied"
    persisted = db.query(ScheduledGmailEscrowPermit).filter_by(
        permit_id=permit["permit_id"]
    ).one()
    assert persisted.status == "consuming"


def test_provider_accepted_retry_resumes_after_finalize_commit_crash_window(
    db,
    escrow_runtime,
    monkeypatch,
):
    row = _add_candidate(db, 43_004)
    db.commit()
    principal = _Principal("client-a")
    issued = _issue(
        db,
        [row],
        principal,
        request_id="REQ-OFFLINE-SYNC-RESUME",
    )
    permit = _permits(issued)[0]
    provider_id = "gmail-offline-resume-after-commit"
    transport_at = datetime.fromisoformat(
        str(permit["slot_not_before"]).replace("Z", "+00:00")
    ) + timedelta(seconds=1)
    accepted_at = transport_at + timedelta(seconds=5)
    monkeypatch.setattr(service, "utcnow", lambda: accepted_at)
    monkeypatch.setattr(escrow_service, "utcnow", lambda: accepted_at)
    monkeypatch.setattr(
        SMTPEmailAdapter,
        "verify_scheduled_gmail_delivery",
        lambda *_args, **_kwargs: _verified_receipt(
            provider_id,
            accepted_at=accepted_at,
        ),
    )
    consumed = _sync_event(
        principal,
        permit,
        event_id="EVT-OFFLINE-RESUME-CONSUMED",
        client_sequence=1,
        event_type="permit_consumed",
        occurred_at=transport_at,
        provider_transport_called=False,
    )
    accepted = _sync_event(
        principal,
        permit,
        event_id="EVT-OFFLINE-RESUME-ACCEPTED",
        client_sequence=2,
        event_type="provider_accepted",
        occurred_at=accepted_at,
        previous_event_sha256=consumed.event_sha256,
        provider_transport_called=True,
        provider_message_id=provider_id,
    )
    sync = _service_call("sync_scheduled_gmail_escrow_events")
    sync(
        db,
        _schema(
            "ScheduledGmailEscrowSyncIn",
            request_id="REQ-OFFLINE-RESUME-CONSUME-BATCH",
            bundle_id=_value(issued, "bundle_id"),
            events=[consumed],
        ),
        principal,
    )
    original_finalize = service.finalize_scheduled_gmail_outreach
    crashed = False

    def finalize_then_crash(*args, **kwargs):
        nonlocal crashed
        result = original_finalize(*args, **kwargs)
        if not crashed:
            crashed = True
            raise RuntimeError("simulated_post_finalize_process_crash")
        return result

    monkeypatch.setattr(
        service,
        "finalize_scheduled_gmail_outreach",
        finalize_then_crash,
    )
    first = sync(
        db,
        _schema(
            "ScheduledGmailEscrowSyncIn",
            request_id="REQ-OFFLINE-RESUME-FIRST",
            bundle_id=_value(issued, "bundle_id"),
            events=[accepted],
        ),
        principal,
    )
    assert _value(first, "events")[0]["processing_status"] == "rejected"
    persisted_event = db.query(escrow_service.ScheduledGmailEscrowSyncEvent).filter_by(
        event_id=accepted.event_id
    ).one()
    assert persisted_event.processing_status == "received"

    second = sync(
        db,
        _schema(
            "ScheduledGmailEscrowSyncIn",
            request_id="REQ-OFFLINE-RESUME-SECOND",
            bundle_id=_value(issued, "bundle_id"),
            events=[accepted],
        ),
        principal,
    )

    assert _value(second, "events")[0]["processing_status"] == "applied"
    persisted = db.query(ScheduledGmailEscrowPermit).filter_by(
        permit_id=permit["permit_id"]
    ).one()
    assert persisted.status == "sent"


def test_ambiguous_sync_holds_quota_and_cannot_be_aborted_or_reissued(
    db,
    escrow_runtime,
    monkeypatch,
):
    row = _add_candidate(db, 43_002)
    db.commit()
    principal = _Principal("client-a")
    issued = _issue(
        db,
        [row],
        principal,
        request_id="REQ-OFFLINE-SYNC-AMBIGUOUS",
    )
    permit = _permits(issued)[0]
    transport_at = datetime.fromisoformat(
        str(permit["slot_not_before"]).replace("Z", "+00:00")
    ) + timedelta(seconds=1)
    monkeypatch.setattr(service, "utcnow", lambda: transport_at)
    monkeypatch.setattr(escrow_service, "utcnow", lambda: transport_at)
    ambiguous = _sync_event(
        principal,
        permit,
        event_id="EVT-OFFLINE-SYNC-AMBIGUOUS",
        client_sequence=1,
        event_type="transport_ambiguous",
        occurred_at=transport_at,
        provider_transport_called=True,
        reason="gmail_transport_result_cannot_be_verified",
    )
    held = _service_call("sync_scheduled_gmail_escrow_events")(
        db,
        _schema(
            "ScheduledGmailEscrowSyncIn",
            request_id="REQ-OFFLINE-SYNC-BATCH-0002",
            bundle_id=_value(issued, "bundle_id"),
            events=[ambiguous],
        ),
        principal,
    )

    assert _value(held, "status") in {"accepted_unverified", "pending_sync"}
    persisted = db.query(ScheduledGmailEscrowPermit).filter_by(
        permit_id=permit["permit_id"]
    ).one()
    assert persisted.status == "accepted_unverified"
    assert service._outreach_budapest_day_usage(db, NOW).effective_reserved_count == 1
    with pytest.raises(
        (EmailDeliveryError, GrowthRegistryError),
        match="transport|verification|abort|unverified",
    ):
        _service_call("abort_scheduled_gmail_escrow_permit")(
            db,
            permit["permit_id"],
            _schema(
                "ScheduledGmailEscrowAbortIn",
                permit_token=permit["permit_token"],
                reason="cannot prove that Gmail transport was not called",
                provider_transport_called=False,
            ),
            principal,
        )
    with pytest.raises(
        (EmailDeliveryError, GrowthRegistryError, ValueError),
        match="claimed|reserved|permit|conflict|unavailable",
    ):
        _issue(
            db,
            [row],
            principal,
            request_id="REQ-OFFLINE-AMBIGUOUS-REISSUE",
        )


def test_dst_day_reservations_use_budapest_calendar_not_fixed_24_hours():
    spring_start, spring_end = _day_bounds(date(2026, 3, 29))
    autumn_start, autumn_end = _day_bounds(date(2026, 10, 25))

    assert spring_end - spring_start == timedelta(hours=23)
    assert autumn_end - autumn_start == timedelta(hours=25)
    assert spring_start.astimezone(ZONE).date() == date(2026, 3, 29)
    assert autumn_start.astimezone(ZONE).date() == date(2026, 10, 25)
    for instant, expected in (
        (spring_start + timedelta(hours=10), (spring_start, spring_end)),
        (autumn_start + timedelta(hours=12), (autumn_start, autumn_end)),
    ):
        assert service._budapest_day_bounds(instant) == expected


def test_iora_internal_delivery_never_consumes_offline_first_contact_quota(
    db,
    escrow_runtime,
):
    for index in range(500):
        db.add(
            CanonicalEmailDelivery(
                delivery_id=f"DEL-OFFLINE-IORA-{index:05d}",
                identity_sha256=f"{index + 1:064x}",
                recipient_normalized="ugyvezeto@imperialholding.hu",
                report_type="iora_internal_opportunity_review",
                local_date=date(2026, 9, 1),
                tenant_scope="imperial",
                payload_sha256=f"{index + 10_001:064x}",
                status="sent",
                provider_message_id=f"gmail-offline-iora-{index}",
                verified_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    db.commit()

    usage = service._outreach_budapest_day_usage(db, NOW)
    assert usage.sent_first_contacts == 0
    assert usage.effective_reserved_count == 0
