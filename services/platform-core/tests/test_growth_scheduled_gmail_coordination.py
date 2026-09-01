from __future__ import annotations

import base64
import hashlib
import importlib
import json
import runpy
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.growth_ops import email as growth_email
from app.growth_ops import service
from app.growth_ops.email import EmailDeliveryError, EmailReceipt, SMTPEmailAdapter
from app.growth_ops.models import (
    CanonicalEmailDelivery,
    GrowthSignal,
    OutreachMessage,
    ScheduledGmailLease,
    ScheduledGmailLeaseRequest,
)
from app.growth_ops.registry import BrandBinding, GrowthRegistryError

NOW = datetime(2026, 8, 31, 10, tzinfo=UTC)
SENDER = "info@imperialholding.hu"


def _scheduled_schema(name: str, **values: Any):
    schemas = importlib.import_module("app.growth_ops.schemas")
    model = getattr(schemas, name, None)
    assert model is not None, f"missing scheduled Gmail schema: {name}"
    return model(**values)


def _service_call(name: str):
    call = getattr(service, name, None)
    assert callable(call), f"missing scheduled Gmail service function: {name}"
    return call


def _value(result: Any, name: str) -> Any:
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name)


def _payload_value(result: Any, name: str) -> Any:
    payload = _value(result, "payload") if _value(result, "payload") is not None else result
    if isinstance(payload, dict):
        return payload.get(name)
    return getattr(payload, name)


class _TestPrincipal:
    def __init__(
        self,
        client_id: str,
        *,
        permissions: frozenset[str],
        sender_emails: frozenset[str],
        motor_keys: frozenset[str],
    ) -> None:
        self.client_id = client_id
        self.permissions = permissions
        self.sender_emails = sender_emails
        self.motor_keys = motor_keys
        self.registry_version = "scheduled-gmail-test-v1"
        self.registry_sha256 = "d" * 64

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


def _principal(
    client_id: str,
    *,
    permissions: frozenset[str] | None = None,
    sender_emails: frozenset[str] | None = None,
    motor_keys: frozenset[str] | None = None,
) -> _TestPrincipal:
    return _TestPrincipal(
        client_id=client_id,
        permissions=permissions or frozenset({"lease", "finalize", "abort", "read"}),
        sender_emails=sender_emails or frozenset({SENDER}),
        motor_keys=motor_keys or frozenset({"construction"}),
    )


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


def _runtime_settings() -> SimpleNamespace:
    return SimpleNamespace(
        base_url="https://intelligence.test.example",
        timezone="Europe/Budapest",
        worker_id="growth-coordination-test",
        lease_seconds=300,
        outreach_send_start_local="00:00",
        outreach_send_end_local="00:00",
        outreach_budapest_day_max=2000,
        outreach_send_concurrency=1,
        outreach_reputation_bootstrap_messages_per_window=100,
        outreach_reputation_max_growth_factor=1.25,
        outreach_reputation_jitter_fraction=0.20,
    )


@pytest.fixture
def scheduled_runtime(monkeypatch):
    monkeypatch.setattr(service, "utcnow", lambda: NOW)
    monkeypatch.setattr(service, "settings", _runtime_settings)
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
            claim_token="global-claim-token",
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
        "_refresh_official_source_evidence",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        service,
        "_official_source_required",
        lambda *_args, **_kwargs: False,
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
        "_outreach_reputation_gap_seconds",
        lambda *_args, **_kwargs: 0.0,
    )
    monkeypatch.setattr(
        service,
        "_record_outreach_pacing_success",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "_finish_land_canary_slot",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        SMTPEmailAdapter,
        "preflight",
        lambda *_args, **_kwargs: {
            "provider": "gmail_api",
            "profile_email": SENDER,
        },
    )
    monkeypatch.setattr(
        SMTPEmailAdapter,
        "live_preflight",
        lambda *_args, **_kwargs: {
            "provider": "gmail_api",
            "profile_email": SENDER,
        },
    )


def _message(
    index: int,
    *,
    recipient: str | None = None,
    status: str = "queued",
    sequence_step: int = 0,
    released: bool = True,
    sent_at: datetime | None = None,
) -> OutreachMessage:
    outreach_id = f"OUT-SCHEDULED-{index:05d}"
    signal_id = f"SIG-SCHEDULED-{index:05d}"
    idempotency_key = service.sha(
        {"signal_id": signal_id, "brand_id": "imperial", "step": sequence_step}
    )
    token = f"scheduled-unsubscribe-{index}"
    unsubscribe_token_hash = hashlib.sha256(token.encode()).hexdigest()
    body_html = f"<p>Exact body {index}</p>"
    metadata = {
        "template_id": "ARCHITECT_OFFICE_FIRST_CONTACT_HU",
        "sender_brand_id": "imperial",
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
        motor_key="construction",
        brand_id="imperial",
        sender_email=SENDER,
        recipient_email=recipient or f"partner{index}@example.test",
        sequence_step=sequence_step,
        subject=f"Exact subject {index}",
        body_text=f"Exact body {index}",
        body_html=body_html,
        unsubscribe_token_hash=unsubscribe_token_hash,
        idempotency_key=idempotency_key,
        payload_sha256="0" * 64,
        receipt_json=json.dumps({"canonical_template": metadata}),
        status=status,
        available_at=NOW - timedelta(minutes=1),
        attempt_count=0,
        max_attempts=5,
        sent_at=sent_at,
        created_at=NOW - timedelta(minutes=2),
        updated_at=NOW - timedelta(minutes=2),
    )
    row.payload_sha256 = service._outreach_payload_sha256(
        sender_email=row.sender_email,
        recipient_email=row.recipient_email,
        subject=row.subject,
        body_text=row.body_text,
        body_html=row.body_html,
        idempotency_key=row.idempotency_key,
        unsubscribe_token_hash=row.unsubscribe_token_hash,
        canonical_metadata=metadata,
    )
    if released:
        row.release_approved_by = "owner@test"
        row.release_approved_at = NOW - timedelta(minutes=1)
        row.release_token_hash = service._release_digest(row, row.release_approved_by)
    return row


def _add_candidate(db, row: OutreachMessage) -> None:
    evidence_hash = hashlib.sha256(row.signal_id.encode()).hexdigest()
    db.add(
        GrowthSignal(
            signal_id=row.signal_id,
            motor_key=row.motor_key,
            source_id=f"SCHEDULED_GMAIL_TEST_{row.signal_id}",
            source_bucket="architect_office",
            external_key=row.signal_id,
            signal_type="residential_construction",
            detected_at=NOW - timedelta(minutes=3),
            company_name="Example Architects",
            recipient_organization_name="Example Architects",
            subject_type="organization",
            recipient_role="unknown",
            recipient_email=row.recipient_email,
            recipient_email_type="role",
            contact_basis="public_business_contact",
            public_contact_url=f"https://example.test/contact/{row.signal_id}",
            location="Budapest",
            summary="Verified public business contact for coordination testing.",
            evidence_url=f"https://example.test/evidence/{row.signal_id}",
            brand_id=row.brand_id,
            score=95,
            urgency=80,
            confidence=95,
            dedupe_hash=evidence_hash,
            source_payload_hash=evidence_hash,
            status="queued",
            rejection_reasons_json="[]",
            first_seen_at=NOW - timedelta(minutes=3),
            last_seen_at=NOW - timedelta(minutes=3),
            created_at=NOW - timedelta(minutes=3),
            updated_at=NOW - timedelta(minutes=3),
        )
    )
    db.add(row)


def _request_id(row: OutreachMessage, suffix: str = "default") -> str:
    return f"REQ:{row.outreach_id}:{suffix}"


def _lease_in(
    row: OutreachMessage,
    *,
    request_id: str | None = None,
):
    return _scheduled_schema(
        "ScheduledGmailLeaseIn",
        request_id=request_id or _request_id(row),
        outreach_id=row.outreach_id,
        expected_payload_sha256=row.payload_sha256,
    )


def _finalize_in(*, lease_token: str, provider_message_id: str):
    return _scheduled_schema(
        "ScheduledGmailFinalizeIn",
        lease_token=lease_token,
        provider_message_id=provider_message_id,
    )


def _abort_in(*, lease_token: str, reason: str = "connector_not_called"):
    return _scheduled_schema(
        "ScheduledGmailAbortIn",
        lease_token=lease_token,
        reason=reason,
        provider_transport_called=False,
    )


def _lease(
    db,
    row: OutreachMessage,
    principal: Any,
    *,
    request_id: str | None = None,
):
    return _service_call("lease_scheduled_gmail_outreach")(
        db,
        _lease_in(row, request_id=request_id),
        principal,
    )


def _verified_receipt(provider_message_id: str) -> EmailReceipt:
    mime_sha256 = hashlib.sha256(provider_message_id.encode()).hexdigest()
    provider_internal_date = NOW + timedelta(seconds=30)
    return EmailReceipt(
        provider_message_id=provider_message_id,
        accepted_recipient="partner@example.test",
        provider="gmail_api",
        response_sha256=mime_sha256,
        detail={
            "accepted": True,
            "readback_verified": True,
            "provider_message_id": provider_message_id,
            "provider_internal_date": provider_internal_date.isoformat(),
            "readback_mime_sha256": mime_sha256,
            "rfc_message_id": f"<{provider_message_id}@example.test>",
            "label_ids": ["SENT"],
        },
    )


def _add_sent_first_contacts(db, count: int, *, start_index: int = 10_000) -> None:
    for offset in range(count):
        row = _message(
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
    db.commit()


def _configure_auth_registry(
    monkeypatch,
    tmp_path: Path,
    *,
    token: str,
    client_id: str = "scheduled-partner-finder",
    permissions: list[str] | None = None,
    expires_at: datetime | None = None,
) -> Path:
    registry_path = tmp_path / "scheduled-gmail-clients.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "clients": [
                    {
                        "client_id": client_id,
                        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                        "enabled": True,
                        "expires_at": (
                            expires_at or datetime.now(UTC) + timedelta(hours=1)
                        ).isoformat(),
                        "permissions": permissions
                        or ["lease", "finalize", "abort", "read"],
                        "sender_emails": [SENDER],
                        "motor_keys": ["construction"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GROWTH_OPS_SCHEDULED_GMAIL_ENABLED", "true")
    monkeypatch.setenv("GROWTH_OPS_SCHEDULED_GMAIL_CLIENTS_FILE", str(registry_path))
    return registry_path


def test_scheduled_gmail_bearer_registry_is_fail_closed_and_scope_bound(
    monkeypatch,
    tmp_path,
):
    auth = importlib.import_module("app.growth_ops.scheduled_gmail_auth")
    authenticate = auth.authenticate_scheduled_gmail_client
    auth_error = auth.ScheduledGmailAuthError
    authorization_error = auth.ScheduledGmailAuthorizationError
    token = "scheduled-gmail-client-token-with-sufficient-entropy"
    _configure_auth_registry(monkeypatch, tmp_path, token=token, permissions=["lease"])

    principal = authenticate(
        f"Bearer {token}",
        required_permission="lease",
        sender_email=SENDER,
        motor_key="construction",
        now=NOW,
    )
    assert principal.client_id == "scheduled-partner-finder"

    for authorization in (None, "Bearer wrong-token"):
        with pytest.raises(auth_error, match="authentication_failed"):
            authenticate(
                authorization,
                required_permission="lease",
                sender_email=SENDER,
                motor_key="construction",
                now=NOW,
            )

    with pytest.raises(authorization_error, match="permission_denied"):
        authenticate(
            f"Bearer {token}",
            required_permission="finalize",
            sender_email=SENDER,
            motor_key="construction",
            now=NOW,
        )

    with pytest.raises(authorization_error, match="sender_scope_denied"):
        authenticate(
            f"Bearer {token}",
            required_permission="lease",
            sender_email="other@example.test",
            motor_key="construction",
            now=NOW,
        )

    monkeypatch.setenv("GROWTH_OPS_SCHEDULED_GMAIL_ENABLED", "false")
    with pytest.raises(auth_error, match="scheduled_gmail_disabled"):
        authenticate(
            f"Bearer {token}",
            required_permission="lease",
            now=NOW,
        )


def test_scheduled_gmail_routes_use_bearer_auth_and_are_documented(
    client,
    monkeypatch,
    tmp_path,
):
    token = "scheduled-gmail-route-token-with-sufficient-entropy"
    _configure_auth_registry(monkeypatch, tmp_path, token=token, permissions=["read"])

    missing = client.post(
        "/api/internal/growth-ops/scheduled-gmail/lease",
        json={
            "request_id": "REQ-ROUTE-AUTH-000001",
            "outreach_id": "OUT-NOT-USED",
        },
    )
    assert missing.status_code == 401

    denied = client.post(
        "/api/internal/growth-ops/scheduled-gmail/lease",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "request_id": "REQ-ROUTE-AUTH-000002",
            "outreach_id": "OUT-NOT-USED",
        },
    )
    assert denied.status_code == 403

    openapi = client.get("/openapi.json").json()
    paths = openapi["paths"]
    assert "/api/internal/growth-ops/scheduled-gmail/lease" in paths
    assert "/api/internal/growth-ops/scheduled-gmail/readiness" in paths
    assert "/api/internal/growth-ops/scheduled-gmail/{lease_id}/finalize" in paths
    assert "/api/internal/growth-ops/scheduled-gmail/{lease_id}/abort" in paths
    assert "/api/internal/growth-ops/scheduled-gmail/{lease_id}" in paths


def test_lease_requires_exact_released_queued_payload(
    db,
    scheduled_runtime,
):
    unreleased = _message(1, released=False)
    _add_candidate(db, unreleased)
    db.commit()

    with pytest.raises((GrowthRegistryError, ValueError), match="release|approved|payload"):
        _lease(db, unreleased, _principal("client-a"))

    db.delete(unreleased)
    exact = _message(2)
    _add_candidate(db, exact)
    db.commit()

    leased = _lease(db, exact, _principal("client-a"))

    assert _value(leased, "status") == "authorized"
    assert _payload_value(leased, "outreach_id") == exact.outreach_id
    assert _payload_value(leased, "sender_email") == exact.sender_email
    assert _payload_value(leased, "recipient_email") == exact.recipient_email
    assert _payload_value(leased, "subject") == exact.subject
    assert _payload_value(leased, "body_text") == exact.body_text
    assert _payload_value(leased, "body_html") == exact.body_html
    assert _payload_value(leased, "payload_sha256") == exact.payload_sha256
    assert _payload_value(leased, "idempotency_key") == exact.idempotency_key


def test_same_client_lease_is_idempotent_and_cross_client_is_denied(
    db,
    scheduled_runtime,
):
    row = _message(3)
    _add_candidate(db, row)
    db.commit()
    client_a = _principal("client-a")

    first = _lease(db, row, client_a)
    second = _lease(db, row, client_a)

    assert _value(second, "lease_id") == _value(first, "lease_id")
    assert _value(second, "lease_token") == _value(first, "lease_token")
    assert _value(first, "request_id") == _request_id(row)
    assert _value(second, "request_id") == _request_id(row)
    requests = db.scalars(service.select(ScheduledGmailLeaseRequest)).all()
    assert len(requests) == 1
    assert requests[0].request_id == _request_id(row)
    db.refresh(row)
    assert row.status == "claimed"
    assert row.attempt_count == 1

    with pytest.raises(
        (GrowthRegistryError, ValueError),
        match="active_lease_request_id_mismatch",
    ):
        _lease(
            db,
            row,
            client_a,
            request_id=_request_id(row, "different-invocation"),
        )

    with pytest.raises((GrowthRegistryError, ValueError), match="client|owned|active"):
        _lease(db, row, _principal("client-b"))


@pytest.mark.parametrize(
    ("already_sent", "allowed"),
    [(1999, True), (2000, False)],
)
def test_lease_enforces_exact_budapest_day_1999_2000_boundary(
    db,
    scheduled_runtime,
    already_sent,
    allowed,
):
    _add_sent_first_contacts(db, already_sent)
    candidate = _message(4)
    _add_candidate(db, candidate)
    db.commit()

    if allowed:
        leased = _lease(db, candidate, _principal("client-a"))
        assert _value(leased, "status") == "authorized"
        usage = service._outreach_budapest_day_usage(db, NOW)
        assert usage.effective_reserved_count == 2000
    else:
        with pytest.raises(
            (EmailDeliveryError, GrowthRegistryError, ValueError),
            match="2000|limit|quota|capacity",
        ):
            _lease(db, candidate, _principal("client-a"))
        db.refresh(candidate)
        assert candidate.status == "queued"


def test_online_lease_expires_at_the_budapest_quota_day_boundary(
    db,
    scheduled_runtime,
    monkeypatch,
):
    authorized_at = datetime(2026, 8, 31, 21, 58, 30, tzinfo=UTC)
    quota_day_end = datetime(2026, 8, 31, 22, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(service, "utcnow", lambda: authorized_at)
    row = _message(4004)
    _add_candidate(db, row)
    db.commit()

    leased = _lease(db, row, _principal("client-a"))
    lease = db.scalar(
        service.select(ScheduledGmailLease).where(
            ScheduledGmailLease.lease_id == _value(leased, "lease_id")
        )
    )

    assert lease is not None
    safe_expiry = quota_day_end - timedelta(
        seconds=service.SCHEDULED_GMAIL_PROVIDER_ACCEPTANCE_GRACE_SECONDS
    )
    assert service._aware(lease.expires_at) == safe_expiry
    assert service._aware(row.lease_expires_at) == safe_expiry


def test_online_lease_fails_closed_when_budapest_midnight_is_too_close(
    db,
    scheduled_runtime,
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "utcnow",
        lambda: datetime(2026, 8, 31, 21, 59, 45, tzinfo=UTC),
    )
    row = _message(4005)
    _add_candidate(db, row)
    db.commit()

    with pytest.raises(
        GrowthRegistryError,
        match="quota_day_boundary_too_close",
    ):
        _lease(db, row, _principal("client-a"))

    db.refresh(row)
    assert row.status == "queued"
    assert row.provider_message_id is None


def test_previous_day_boundary_lease_reserves_one_next_day_quota_slot(
    db,
    scheduled_runtime,
    monkeypatch,
):
    previous_day_authorized_at = datetime(2026, 8, 31, 21, 58, 30, tzinfo=UTC)
    current_day_start = datetime(2026, 8, 31, 22, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(service, "utcnow", lambda: previous_day_authorized_at)
    boundary_row = _message(4006)
    _add_candidate(db, boundary_row)
    db.commit()

    _lease(db, boundary_row, _principal("client-a"))

    for offset in range(1999):
        sent = _message(
            40_000 + offset,
            status="sent",
            sent_at=current_day_start + timedelta(minutes=5),
        )
        sent.provider_message_id = f"gmail-next-day-{offset}"
        db.add(sent)
    db.commit()

    usage = service._outreach_budapest_day_usage(db, current_day_start)
    assert usage.sent_first_contacts == 1999
    assert usage.active_claim_reservations == 1
    assert usage.effective_reserved_count == 2000


def test_only_one_active_gmail_account_reservation_is_authorized(
    db,
    scheduled_runtime,
):
    first = _message(5)
    second = _message(6)
    _add_candidate(db, first)
    _add_candidate(db, second)
    db.commit()

    _lease(db, first, _principal("client-a"))

    with pytest.raises((GrowthRegistryError, ValueError), match="active|reservation|capacity"):
        _lease(db, second, _principal("client-b"))
    db.refresh(second)
    assert second.status == "queued"


def test_central_gmail_auth_backoff_does_not_block_registered_scheduled_sender(
    db,
    scheduled_runtime,
):
    service._record_central_gmail_authentication_failure(
        db,
        reason="provider_authentication_failure",
        now=NOW,
    )
    db.commit()
    row = _message(7)
    _add_candidate(db, row)
    db.commit()

    leased = _lease(db, row, _principal("client-a"))

    assert _value(leased, "status") == "authorized"
    state = db.get(
        service.GrowthControlState,
        service.CENTRAL_GMAIL_TRANSPORT_STATE_KEY,
    )
    assert state is not None and state.enabled is False


def test_recipient_cooldown_is_cross_brand_and_at_least_thirty_days(
    db,
    monkeypatch,
):
    monkeypatch.setattr(service, "utcnow", lambda: NOW)
    recipient = "Cross.Brand@Example.Test"
    prior = _message(
        13,
        recipient=recipient.casefold(),
        status="sent",
        sent_at=NOW - timedelta(days=29, hours=23),
    )
    prior.brand_id = "imperial"
    _add_candidate(db, prior)
    db.commit()
    other_brand = BrandBinding(
        brand_id="prefab",
        sender_email=SENDER,
        domain_key="imperialholding-hu",
        secret={},
        config={"recipient_cooldown_days": 7},
    )

    assert service._rate_errors(db, other_brand, recipient) == [
        "recipient_brand_cooldown"
    ]

    prior.created_at = NOW - timedelta(days=30, seconds=1)
    prior.sent_at = NOW - timedelta(days=30, seconds=1)
    db.commit()
    assert service._rate_errors(db, other_brand, recipient) == []


def test_abort_is_allowed_only_before_provider_transport(
    db,
    scheduled_runtime,
):
    row = _message(7)
    _add_candidate(db, row)
    db.commit()
    principal = _principal("client-a")
    leased = _lease(db, row, principal)

    aborted = _service_call("abort_scheduled_gmail_outreach")(
        db,
        _value(leased, "lease_id"),
        _abort_in(lease_token=_value(leased, "lease_token")),
        principal,
    )

    assert _value(aborted, "status") == "aborted"
    db.refresh(row)
    assert row.status == "queued"
    assert row.provider_message_id is None

    with pytest.raises(ValidationError):
        _scheduled_schema(
            "ScheduledGmailAbortIn",
            lease_token="not-a-real-token",
            reason="caller_says_transport_was_called",
            provider_transport_called=True,
        )


def test_preclaim_row_failure_is_deferred_and_next_candidate_continues(
    db,
    scheduled_runtime,
    monkeypatch,
):
    first = _message(20)
    second = _message(21)
    _add_candidate(db, first)
    _add_candidate(db, second)
    db.commit()

    monkeypatch.setattr(
        service,
        "_preclaim_outreach_readiness_reason",
        lambda _db, _registry, row: (
            "row_local_test_failure" if row.outreach_id == first.outreach_id else None
        ),
    )
    leased = _service_call("lease_scheduled_gmail_outreach")(
        db,
        _scheduled_schema(
            "ScheduledGmailLeaseIn",
            request_id="REQ-PRECLAIM-ROW-SCAN-0001",
        ),
        _principal("client-a"),
    )

    assert _payload_value(leased, "outreach_id") == second.outreach_id
    db.refresh(first)
    assert first.status == "queued"
    assert service._aware(first.available_at) >= NOW + timedelta(minutes=15)
    assert first.last_error == "scheduled_gmail_authorization_failed_no_send"


def test_live_gmail_readback_preflight_is_required_before_authorization(
    db,
    scheduled_runtime,
    monkeypatch,
):
    row = _message(22)
    _add_candidate(db, row)
    db.commit()
    calls = 0

    def unavailable(_adapter, **_values):
        nonlocal calls
        calls += 1
        raise GrowthRegistryError("gmail_live_preflight_http_401_no_send")

    monkeypatch.setattr(SMTPEmailAdapter, "live_preflight", unavailable)
    with pytest.raises(GrowthRegistryError, match="live_preflight"):
        _lease(db, row, _principal("client-a"))

    assert calls == 1
    db.refresh(row)
    assert row.status == "queued"
    assert service._aware(row.available_at) >= NOW + timedelta(minutes=15)


def test_abort_allows_request_b_without_leaking_its_token_to_request_a_retry(
    db,
    scheduled_runtime,
):
    row = _message(14)
    _add_candidate(db, row)
    db.commit()
    principal = _principal("client-a")
    request_a = _request_id(row, "invocation-a")
    request_b = _request_id(row, "invocation-b")
    first = _lease(db, row, principal, request_id=request_a)
    _service_call("abort_scheduled_gmail_outreach")(
        db,
        _value(first, "lease_id"),
        _abort_in(lease_token=_value(first, "lease_token")),
        principal,
    )

    second = _lease(db, row, principal, request_id=request_b)
    retried_a = _lease(db, row, principal, request_id=request_a)

    assert _value(second, "lease_token") != _value(first, "lease_token")
    assert _value(second, "request_id") == request_b
    assert _value(second, "status") == "authorized"
    assert _value(retried_a, "request_id") == request_a
    assert _value(retried_a, "status") == "aborted"
    assert _value(retried_a, "send_authorized") is False
    assert _value(retried_a, "lease_token") is None
    with pytest.raises((GrowthRegistryError, ValueError), match="token_invalid"):
        _service_call("abort_scheduled_gmail_outreach")(
            db,
            _value(second, "lease_id"),
            _abort_in(lease_token=_value(first, "lease_token")),
            principal,
        )
    requests = {
        request.request_id: request.status
        for request in db.scalars(service.select(ScheduledGmailLeaseRequest)).all()
    }
    assert requests == {request_a: "aborted", request_b: "authorized"}
    db.refresh(row)
    assert row.status == "claimed"
    assert row.claimed_by == "scheduled-gmail:client-a"


def test_provider_hold_is_committed_before_guard_failure_and_readback(
    db,
    scheduled_runtime,
    monkeypatch,
):
    row = _message(23, recipient="partner@example.test")
    _add_candidate(db, row)
    db.commit()
    principal = _principal("client-a")
    leased = _lease(db, row, principal)
    provider_id = "gmail-durable-before-guard"
    commit_calls = 0
    original_commit = db.commit

    def tracked_commit():
        nonlocal commit_calls
        commit_calls += 1
        return original_commit()

    def fail_guard(_db, **_values):
        assert commit_calls >= 1
        _db.expire_all()
        held_row = _db.get(OutreachMessage, row.id)
        held_lease = _db.scalar(
            service.select(ScheduledGmailLease).where(
                ScheduledGmailLease.lease_id == _value(leased, "lease_id")
            )
        )
        assert held_row is not None and held_row.status == "claimed"
        assert held_row.provider_message_id == provider_id
        assert held_row.lease_expires_at is None
        assert held_lease is not None and held_lease.status == "accepted_unverified"
        raise RuntimeError("simulated_guard_transition_failure")

    monkeypatch.setattr(db, "commit", tracked_commit)
    monkeypatch.setattr(service, "fail_global_recipient_delivery", fail_guard)
    monkeypatch.setattr(
        SMTPEmailAdapter,
        "verify_scheduled_gmail_delivery",
        lambda _adapter, **_values: _verified_receipt(provider_id),
    )

    result = _service_call("finalize_scheduled_gmail_outreach")(
        db,
        _value(leased, "lease_id"),
        _finalize_in(
            lease_token=_value(leased, "lease_token"),
            provider_message_id=provider_id,
        ),
        principal,
    )

    assert _value(result, "status") == "sent"
    assert commit_calls >= 2


def test_reused_provider_id_is_contained_without_abort_or_readback(
    db,
    scheduled_runtime,
    monkeypatch,
):
    prior = _message(24, status="sent", sent_at=NOW - timedelta(minutes=1))
    prior.provider_message_id = "gmail-provider-already-used"
    current = _message(25, recipient="new-partner@example.test")
    _add_candidate(db, prior)
    _add_candidate(db, current)
    db.commit()
    principal = _principal("client-a")
    leased = _lease(db, current, principal)

    monkeypatch.setattr(
        SMTPEmailAdapter,
        "verify_scheduled_gmail_delivery",
        lambda *_args, **_kwargs: pytest.fail("duplicate provider id must not be read back"),
    )
    held = _service_call("finalize_scheduled_gmail_outreach")(
        db,
        _value(leased, "lease_id"),
        _finalize_in(
            lease_token=_value(leased, "lease_token"),
            provider_message_id=prior.provider_message_id,
        ),
        principal,
    )

    assert _value(held, "status") == "accepted_unverified"
    db.refresh(current)
    assert current.status == "claimed"
    assert current.provider_message_id is None
    assert current.lease_expires_at is None
    verification = json.loads(current.receipt_json)["delivery_verification"]
    assert verification["detail"]["reported_provider_message_id"] == (
        prior.provider_message_id
    )
    with pytest.raises(
        GrowthRegistryError,
        match="abort|verification|transport|active_request_missing",
    ):
        _service_call("abort_scheduled_gmail_outreach")(
            db,
            _value(leased, "lease_id"),
            _abort_in(lease_token=_value(leased, "lease_token")),
            principal,
        )


def test_finalize_requires_exact_gmail_sent_mime_receipt_and_is_idempotent(
    db,
    scheduled_runtime,
    monkeypatch,
):
    row = _message(8, recipient="partner@example.test")
    _add_candidate(db, row)
    db.commit()
    principal = _principal("client-a")
    leased = _lease(db, row, principal)
    provider_id = "gmail-exact-provider-id"
    verify_calls = 0

    def verify(_adapter, **values):
        nonlocal verify_calls
        verify_calls += 1
        assert values == {
            "provider_message_id": provider_id,
            "to_email": row.recipient_email,
            "subject": row.subject,
            "body_text": row.body_text,
            "body_html": row.body_html,
            "reply_to": SENDER,
            "unsubscribe_url": service._canonical_metadata(row)["render_input"][
                "unsubscribe_url"
            ],
            "idempotency_key": row.idempotency_key,
        }
        return _verified_receipt(provider_id)

    monkeypatch.setattr(
        SMTPEmailAdapter,
        "verify_scheduled_gmail_delivery",
        verify,
        raising=False,
    )
    data = _finalize_in(
        lease_token=_value(leased, "lease_token"),
        provider_message_id=provider_id,
    )

    first = _service_call("finalize_scheduled_gmail_outreach")(
        db,
        _value(leased, "lease_id"),
        data,
        principal,
    )
    second = _service_call("finalize_scheduled_gmail_outreach")(
        db,
        _value(leased, "lease_id"),
        data,
        principal,
    )

    assert _value(first, "status") == "sent"
    assert _value(second, "status") == "sent"
    assert _value(first, "provider_message_id") == provider_id
    assert _value(first, "provider_internal_date") == NOW + timedelta(seconds=30)
    assert _value(second, "readback_mime_sha256") == _value(
        first, "readback_mime_sha256"
    )
    assert verify_calls == 1
    db.refresh(row)
    assert row.status == "sent"
    assert row.provider_message_id == provider_id
    assert service._aware(row.sent_at) == NOW + timedelta(seconds=30)


@pytest.mark.parametrize(
    "reason",
    ["gmail_readback_plain_body_mismatch", "gmail_readback_transport_ambiguous"],
)
def test_finalize_mismatch_or_ambiguity_is_held_without_resend(
    db,
    scheduled_runtime,
    monkeypatch,
    reason,
):
    row = _message(9, recipient="partner@example.test")
    _add_candidate(db, row)
    db.commit()
    principal = _principal("client-a")
    leased = _lease(db, row, principal)
    provider_id = f"gmail-{reason}"

    def verify(_adapter, **_values):
        raise EmailDeliveryError(
            "accepted_but_unverified",
            retry_safe=False,
            accepted_but_unverified=True,
            transport_attempted=True,
            provider_message_id=provider_id,
            detail={"reason": reason, "provider_message_id": provider_id},
        )

    monkeypatch.setattr(
        SMTPEmailAdapter,
        "verify_scheduled_gmail_delivery",
        verify,
        raising=False,
    )

    held = _service_call("finalize_scheduled_gmail_outreach")(
        db,
        _value(leased, "lease_id"),
        _finalize_in(
            lease_token=_value(leased, "lease_token"),
            provider_message_id=provider_id,
        ),
        principal,
    )

    assert _value(held, "status") in {"accepted_unverified", "reconcile_required"}
    db.refresh(row)
    assert row.status == "claimed"
    assert row.sent_at is None
    assert row.provider_message_id == provider_id
    assert row.lease_expires_at is None
    assert service._delivery_verification_pending(row)

    with pytest.raises(
        (GrowthRegistryError, ValueError),
        match="transport|verification|abort|active_request_missing",
    ):
        _service_call("abort_scheduled_gmail_outreach")(
            db,
            _value(leased, "lease_id"),
            _abort_in(lease_token=_value(leased, "lease_token")),
            principal,
        )


def test_ambiguous_finalize_after_budapest_midnight_reserves_the_new_day(
    db,
    scheduled_runtime,
    monkeypatch,
):
    row = _message(15, recipient="partner@example.test")
    _add_candidate(db, row)
    db.commit()
    principal = _principal("client-a")
    leased = _lease(db, row, principal)
    lease = db.scalar(
        service.select(ScheduledGmailLease).where(
            ScheduledGmailLease.lease_id == _value(leased, "lease_id")
        )
    )
    assert lease is not None
    lease.authorized_at = datetime(2026, 8, 31, 21, 59, 50, tzinfo=UTC)
    lease.quota_local_date = date(2026, 8, 31)
    db.commit()
    contained_at = datetime(2026, 8, 31, 22, 0, 10, tzinfo=UTC)
    monkeypatch.setattr(service, "utcnow", lambda: contained_at)

    def verify(_adapter, **_values):
        raise EmailDeliveryError(
            "accepted_but_unverified",
            retry_safe=False,
            accepted_but_unverified=True,
            transport_attempted=True,
            provider_message_id="gmail-midnight-ambiguous",
            detail={"reason": "gmail_readback_transport_ambiguous"},
        )

    monkeypatch.setattr(
        SMTPEmailAdapter,
        "verify_scheduled_gmail_delivery",
        verify,
        raising=False,
    )
    held = _service_call("finalize_scheduled_gmail_outreach")(
        db,
        _value(leased, "lease_id"),
        _finalize_in(
            lease_token=_value(leased, "lease_token"),
            provider_message_id="gmail-midnight-ambiguous",
        ),
        principal,
    )

    assert _value(held, "status") == "accepted_unverified"
    db.refresh(row)
    verification = json.loads(row.receipt_json)["delivery_verification"]
    assert service._aware(datetime.fromisoformat(verification["reserved_at"])) == contained_at
    new_day_usage = service._outreach_budapest_day_usage(db, contained_at)
    assert new_day_usage.pending_verification_reservations == 1
    assert new_day_usage.effective_reserved_count == 1


@pytest.mark.parametrize("event_type", ["bounce", "unsubscribe"])
def test_provider_event_does_not_release_pending_scheduled_quota(
    db,
    scheduled_runtime,
    monkeypatch,
    event_type,
):
    row = _message(26, recipient="pending-event@example.test")
    _add_candidate(db, row)
    db.commit()
    principal = _principal("client-a")
    leased = _lease(db, row, principal)
    provider_id = f"gmail-pending-{event_type}"

    def unverifiable(_adapter, **_values):
        raise EmailDeliveryError(
            "gmail_readback_transport_ambiguous",
            retry_safe=False,
            accepted_but_unverified=True,
            transport_attempted=True,
            provider_message_id=provider_id,
        )

    monkeypatch.setattr(
        SMTPEmailAdapter,
        "verify_scheduled_gmail_delivery",
        unverifiable,
    )
    _service_call("finalize_scheduled_gmail_outreach")(
        db,
        _value(leased, "lease_id"),
        _finalize_in(
            lease_token=_value(leased, "lease_token"),
            provider_message_id=provider_id,
        ),
        principal,
    )
    assert service._outreach_budapest_day_usage(db, NOW).effective_reserved_count == 1

    service.record_outreach_event(
        db,
        row.outreach_id,
        _scheduled_schema("OutreachEventIn", event_type=event_type),
    )

    db.refresh(row)
    assert row.status == ("bounced" if event_type == "bounce" else "unsubscribed")
    usage = service._outreach_budapest_day_usage(db, NOW)
    assert usage.pending_verification_reservations == 1
    assert usage.effective_reserved_count == 1


@pytest.mark.parametrize("event_type", ["bounce", "unsubscribe"])
def test_provider_event_does_not_release_central_pending_quota(
    db,
    scheduled_runtime,
    event_type,
):
    row = _message(
        27,
        recipient="central-pending-event@example.test",
        status="claimed",
    )
    row.claimed_by = None
    row.claimed_at = NOW - timedelta(minutes=2)
    row.lease_expires_at = None
    row.provider_message_id = f"gmail-central-pending-{event_type}"
    receipt = json.loads(row.receipt_json)
    receipt.update(
        {
            "provider": "gmail_api",
            "accepted": True,
            "delivery_verification": {
                "status": "pending_verification",
                "retry_safe": False,
                "provider_message_id": row.provider_message_id,
                "reserved_at": NOW.isoformat(),
                "detail": {"reason": "central_worker_readback_ambiguous"},
            },
        }
    )
    row.receipt_json = service.canonical_json(receipt)
    _add_candidate(db, row)
    db.commit()

    assert (
        db.scalar(
            service.select(ScheduledGmailLease).where(
                ScheduledGmailLease.outreach_id == row.outreach_id
            )
        )
        is None
    )
    initial_usage = service._outreach_budapest_day_usage(db, NOW)
    assert initial_usage.pending_verification_reservations == 1
    assert initial_usage.effective_reserved_count == 1

    service.record_outreach_event(
        db,
        row.outreach_id,
        _scheduled_schema("OutreachEventIn", event_type=event_type),
    )

    db.refresh(row)
    assert row.status == ("bounced" if event_type == "bounce" else "unsubscribed")
    usage = service._outreach_budapest_day_usage(db, NOW)
    assert usage.pending_verification_reservations == 1
    assert usage.effective_reserved_count == 1


def test_expired_lease_becomes_reconciliation_hold_not_a_new_send(
    db,
    scheduled_runtime,
):
    row = _message(10)
    _add_candidate(db, row)
    db.commit()
    principal = _principal("client-a")
    leased = _lease(db, row, principal)
    row.lease_expires_at = NOW - timedelta(seconds=1)
    db.commit()

    held = _lease(db, row, principal)

    assert _value(held, "status") in {"accepted_unverified", "reconcile_required"}
    assert _value(held, "send_authorized") is False
    assert _value(held, "lease_token") is None
    db.refresh(row)
    assert row.status == "claimed"
    assert row.claimed_by is None
    assert row.lease_expires_at is None
    assert row.sent_at is None
    assert service._delivery_verification_pending(row)
    assert _value(leased, "lease_id")


def test_internal_iora_deliveries_do_not_consume_first_contact_quota(
    db,
    scheduled_runtime,
):
    internal = []
    for index in range(2000):
        internal.append(
            CanonicalEmailDelivery(
                delivery_id=f"DEL-IORA-{index:05d}",
                identity_sha256=f"{index + 1:064x}",
                recipient_normalized="ugyvezeto@imperialholding.hu",
                report_type="iora_internal_opportunity_review",
                local_date=date(2026, 8, 31),
                tenant_scope="imperial",
                payload_sha256=f"{index + 20_001:064x}",
                status="sent",
                provider_message_id=f"gmail-iora-{index}",
                verified_at=NOW - timedelta(minutes=5),
                created_at=NOW - timedelta(minutes=5),
                updated_at=NOW - timedelta(minutes=5),
            )
        )
    db.add_all(internal)
    candidate = _message(11)
    _add_candidate(db, candidate)
    db.commit()

    usage = service._outreach_budapest_day_usage(db, NOW)
    assert usage.sent_first_contacts == 0
    assert usage.effective_reserved_count == 0

    leased = _lease(db, candidate, _principal("client-a"))
    assert _value(leased, "status") == "authorized"
    assert _payload_value(leased, "outreach_id") == candidate.outreach_id


def test_coordination_readiness_is_mutation_free(
    db,
    scheduled_runtime,
):
    candidate = _message(12)
    _add_candidate(db, candidate)
    db.commit()

    result = _service_call("scheduled_gmail_coordination_readiness")(
        db,
        _principal("client-a"),
    )

    assert result["status"] == "ready"
    assert result["budapest_day"]["limit"] == 2000
    assert result["budapest_day"]["effective_reserved_count"] == 0
    db.refresh(candidate)
    assert candidate.status == "queued"
    assert candidate.claimed_by is None
    assert candidate.attempt_count == 0


class _JSONResponse:
    def __init__(self, value: dict[str, Any]) -> None:
        self.raw = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback
        return False

    def read(self, _limit: int) -> bytes:
        return self.raw


def _scheduled_gmail_mime(*, optional_identity_header: str | None = None) -> bytes:
    unsubscribe_url = "https://intelligence.test.example/growth/unsubscribe/exact-token"
    message = EmailMessage()
    message["From"] = f"Imperial Holding <{SENDER}>"
    message["To"] = "Example Architects <partner@example.test>"
    message["Reply-To"] = f"Imperial Team <{SENDER}>"
    message["Subject"] = "Exact scheduled Gmail subject"
    message["Message-ID"] = "<scheduled-gmail-provider@example.test>"
    if optional_identity_header is not None:
        message["X-Imperial-Idempotency-Key"] = optional_identity_header
    message.set_content(f"Exact scheduled Gmail body.\n\n{unsubscribe_url}")
    message.add_alternative(
        f"<p>Exact scheduled Gmail body.</p><p><a href=\"{unsubscribe_url}\">Leiratkozás</a></p>",
        subtype="html",
    )
    return message.as_bytes()


def test_scheduled_gmail_readback_accepts_display_names_and_never_posts(
    monkeypatch,
):
    raw_mime = _scheduled_gmail_mime()
    provider_id = "gmail-readback-only-id"
    urls: list[tuple[str, str, bytes | None]] = []

    def urlopen(request, timeout):
        assert timeout == 30
        urls.append((request.get_method(), request.full_url, request.data))
        if request.full_url.endswith("/users/me/profile"):
            return _JSONResponse({"emailAddress": SENDER})
        if request.full_url.endswith(f"/messages/{provider_id}?format=raw"):
            return _JSONResponse(
                {
                    "id": provider_id,
                    "labelIds": ["SENT"],
                    "internalDate": str(int(NOW.timestamp() * 1000)),
                    "raw": base64.urlsafe_b64encode(raw_mime).rstrip(b"=").decode(),
                }
            )
        raise AssertionError(f"unexpected Gmail URL: {request.full_url}")

    monkeypatch.setattr(growth_email.urllib.request, "urlopen", urlopen)
    unsubscribe_url = "https://intelligence.test.example/growth/unsubscribe/exact-token"
    body_text = f"Exact scheduled Gmail body.\n\n{unsubscribe_url}"
    body_html = (
        "<p>Exact scheduled Gmail body.</p>"
        f"<p><a href=\"{unsubscribe_url}\">Leiratkozás</a></p>"
    )

    receipt = SMTPEmailAdapter(_binding()).verify_scheduled_gmail_delivery(
        provider_message_id=provider_id,
        to_email="partner@example.test",
        subject="Exact scheduled Gmail subject",
        body_text=body_text,
        body_html=body_html,
        reply_to=SENDER,
        unsubscribe_url=unsubscribe_url,
        idempotency_key="a" * 64,
    )

    assert receipt.provider_message_id == provider_id
    assert receipt.detail["readback_verified"] is True
    assert receipt.detail["label_ids"] == ["SENT"]
    assert urls
    assert all(method == "GET" and data is None for method, _url, data in urls)
    assert all(not url.endswith("/messages/send") for _method, url, _data in urls)

    with pytest.raises(ValueError, match="idempotency-key_mismatch"):
        growth_email._verify_scheduled_gmail_readback(
            raw_mime=_scheduled_gmail_mime(optional_identity_header="b" * 64),
            sender_email=SENDER,
            to_email="partner@example.test",
            subject="Exact scheduled Gmail subject",
            body_text=body_text,
            body_html=body_html,
            reply_to=SENDER,
            unsubscribe_url=unsubscribe_url,
            idempotency_key="a" * 64,
        )


def test_coordination_cli_uses_lease_endpoint_and_redacts_tokens(
    monkeypatch,
    tmp_path,
):
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "scheduled_gmail_coordination.py"
    )
    script = runpy.run_path(str(script_path))
    run = script["_run"]
    validate_base_url = script["_validated_api_base_url"]
    coordination_error = script["CoordinationError"]
    base_url = "http://127.0.0.1:8091/api/internal/growth-ops/scheduled-gmail"
    assert validate_base_url(base_url) == base_url
    with pytest.raises(coordination_error, match="loopback_coordination_endpoint"):
        validate_base_url("https://example.test/api/internal/growth-ops/scheduled-gmail")

    bearer_token = "scheduled-client-bearer-secret"
    lease_token = "scheduled-lease-token-secret-with-sufficient-entropy"
    request_id = "SGR-CLI-REQUEST-000001"
    calls: list[dict[str, Any]] = []

    def request(**values):
        calls.append(values)
        return {
            "lease_id": "SGL-TEST",
            "lease_token": lease_token,
            "diagnostic": (
                f"never expose {bearer_token} or {lease_token} or {request_id}"
            ),
        }

    monkeypatch.setitem(
        run.__globals__,
        "_client_token",
        lambda _value=None: bearer_token,
    )
    monkeypatch.setitem(run.__globals__, "_request", request)
    lease_token_file = tmp_path / "lease-token"
    request_id_file = tmp_path / "request-id"
    request_id_file.write_text(request_id, encoding="utf-8")
    args = SimpleNamespace(
        api_base_url=base_url,
        client_token_file=None,
        command="lease",
        outreach_id="OUT-SCHEDULED-CLI",
        expected_payload_sha256="c" * 64,
        lease_token_file=str(lease_token_file),
        request_id_file=str(request_id_file),
    )

    result = run(args)

    assert calls == [
        {
            "method": "POST",
            "url": f"{base_url}/lease",
            "bearer_token": bearer_token,
            "payload": {
                "request_id": request_id,
                "outreach_id": "OUT-SCHEDULED-CLI",
                "expected_payload_sha256": "c" * 64,
            },
            "expected_statuses": {200, 201},
        }
    ]
    assert lease_token_file.read_text(encoding="utf-8") == lease_token
    assert request_id_file.read_text(encoding="utf-8") == request_id
    serialized = json.dumps(result)
    assert bearer_token not in serialized
    assert lease_token not in serialized
    assert request_id not in serialized
    assert result["diagnostic"] == (
        "never expose <redacted> or <redacted> or <redacted>"
    )
    assert result["lease_file_written"] is True
