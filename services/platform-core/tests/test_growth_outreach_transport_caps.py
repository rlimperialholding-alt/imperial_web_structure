from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base, SessionLocal, engine
from app.global_email_guard import GlobalEmailRecipientGuard
from app.growth_ops import registry, service
from app.growth_ops.email import EmailDeliveryError, GmailRolling24hUsage
from app.growth_ops.models import CanonicalEmailDelivery, GrowthControlState, OutreachMessage
from app.growth_ops.registry import GrowthRegistryError
from app.growth_ops.registry import settings as growth_settings


@pytest.fixture(autouse=True)
def _isolate_transport_capacity_from_global_send_readiness(monkeypatch):
    monkeypatch.setattr(
        service.GrowthRegistry,
        "load",
        classmethod(lambda _cls: SimpleNamespace()),
    )
    monkeypatch.setattr(
        service,
        "_outbound_send_readiness_state",
        lambda *_args, **_kwargs: {
            "ready": True,
            "canary_active": False,
            "scheduled_enabled_sources": 1,
        },
    )
    monkeypatch.setattr(
        service,
        "_preclaim_outreach_readiness_reason",
        lambda *_args, **_kwargs: None,
    )


def _verified_gmail_receipt(provider_message_id: str, mime_sha256: str) -> str:
    return json.dumps(
        {
            "provider": "gmail_api",
            "accepted": True,
            "response_sha256": mime_sha256,
            "delivery_detail": {
                "readback_verified": True,
                "provider_message_id": provider_message_id,
                "label_ids": ["SENT"],
                "readback_mime_sha256": mime_sha256,
                "rfc_message_id": f"<{provider_message_id}@example.hu>",
            },
        }
    )


def _message(index: int, recipient: str, *, status: str = "queued") -> OutreachMessage:
    marker = f"{index:064x}"
    return OutreachMessage(
        outreach_id=f"OUT-CAP-{index}",
        signal_id=f"SIG-CAP-{index}",
        motor_key="construction",
        brand_id="imperial",
        sender_email="info@imperialholding.hu",
        recipient_email=recipient,
        sequence_step=0,
        subject="subject",
        body_text="body",
        body_html="<p>body</p>",
        unsubscribe_token_hash=marker,
        idempotency_key=marker,
        payload_sha256=marker,
        status=status,
        available_at=datetime(2026, 8, 28, 8, tzinfo=UTC),
        attempt_count=0,
        max_attempts=5,
    )


def _verified_sent_message(
    index: int,
    *,
    status: str,
    sent_at: datetime,
) -> OutreachMessage:
    row = _message(index, f"sent{index}@example.hu", status=status)
    provider_message_id = f"gmail-sent-{index}"
    row.provider_message_id = provider_message_id
    row.receipt_json = _verified_gmail_receipt(provider_message_id, f"{index:064x}")
    row.sent_at = sent_at
    return row


def _canonical_delivery(
    index: int,
    *,
    status: str,
    provider_message_id: str | None = None,
    at: datetime,
) -> CanonicalEmailDelivery:
    return CanonicalEmailDelivery(
        delivery_id=f"DEL-CAP-{index}",
        identity_sha256=f"{10_000 + index:064x}",
        recipient_normalized=f"internal{index}@imperialholding.hu",
        report_type="daily_executive",
        local_date=date(2026, 8, 31),
        tenant_scope="imperial",
        payload_sha256=f"{20_000 + index:064x}",
        status=status,
        provider_message_id=provider_message_id,
        accepted_at=at if status == "accepted_unverified" else None,
        verified_at=at if status == "sent" else None,
        created_at=at,
        updated_at=at,
    )


def _gmail_usage(
    current: datetime,
    provider_ids: set[str] | frozenset[str] = frozenset(),
    *,
    limit: int = 2000,
) -> GmailRolling24hUsage:
    return GmailRolling24hUsage(
        provider_ids=frozenset(provider_ids),
        limit=limit,
        cutoff=current - timedelta(hours=24),
        observed_at=current,
        pages=1,
    )


def _runtime_settings(**changes):
    values = {
        "timezone": "Europe/Budapest",
        "worker_id": "growth-cap-test",
        "lease_seconds": 300,
        "outreach_send_start_local": "00:00",
        "outreach_send_end_local": "00:00",
        "outreach_account_rolling_24h_max": 2000,
        "outreach_send_concurrency": 1,
        "outreach_reputation_bootstrap_messages_per_window": 100,
        "outreach_reputation_max_growth_factor": 1.25,
        "outreach_reputation_jitter_fraction": 0.20,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _capacity_usage(*, rolling: int = 0, previous: int = 0):
    return service.OutreachCapacityUsage(
        rolling_24h_verified=rolling,
        previous_24h_verified=previous,
        active_claimed=0,
        pending_verification=0,
        ready_queued=0,
        last_verified_at=None,
    )


def test_only_gmail_sent_with_full_mime_readback_is_locally_verified():
    current = datetime(2026, 8, 29, 9, tzinfo=UTC)
    row = SimpleNamespace(
        sent_at=current,
        provider_message_id="gmail-id",
        receipt_json=_verified_gmail_receipt("gmail-id", "a" * 64),
    )
    assert service._gmail_sent_mime_verified(row)

    receipt = json.loads(row.receipt_json)
    receipt["delivery_detail"].pop("readback_mime_sha256")
    row.receipt_json = json.dumps(receipt)
    assert not service._gmail_sent_mime_verified(row)


def test_default_outreach_window_is_explicit_all_day(monkeypatch):
    monkeypatch.delenv("GROWTH_OPS_OUTREACH_SEND_START_LOCAL", raising=False)
    monkeypatch.delenv("GROWTH_OPS_OUTREACH_SEND_END_LOCAL", raising=False)

    config = growth_settings()

    assert config.outreach_send_start_local == "00:00"
    assert config.outreach_send_end_local == "00:00"


def test_all_day_pacing_window_is_exactly_86400_seconds(monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())

    assert service._outreach_window_seconds(service.settings()) == 86_400.0


def test_inverted_partial_service_window_fails_closed(monkeypatch):
    config = _runtime_settings(
        outreach_send_start_local="18:00",
        outreach_send_end_local="08:00",
    )
    monkeypatch.setattr(service, "settings", lambda: config)

    with pytest.raises(
        GrowthRegistryError,
        match="Outreach sending window must start before it ends",
    ):
        service._outreach_window_seconds(config)
    with pytest.raises(
        GrowthRegistryError,
        match="Outreach sending window must start before it ends",
    ):
        service._outreach_sending_window_open(datetime.now(UTC))


@pytest.mark.parametrize(
    "name",
    [
        "GROWTH_OPS_OUTREACH_MAX_PER_HOUR",
        "GROWTH_OPS_OUTREACH_MAX_PER_DAY",
        "GROWTH_OPS_OUTREACH_MAX_PER_RECIPIENT_ROOT_DOMAIN_PER_DAY",
    ],
)
def test_legacy_static_count_cap_environment_fails_closed(monkeypatch, name):
    monkeypatch.setenv(name, "1")
    with pytest.raises(
        GrowthRegistryError,
        match="legacy_outreach_count_cap_environment_present_no_send",
    ):
        growth_settings()


@pytest.mark.parametrize("invalid", ["1", "50", "1999", "2001"])
def test_account_rolling_24h_limit_is_exactly_2000(monkeypatch, invalid):
    monkeypatch.setenv("GROWTH_OPS_OUTREACH_ACCOUNT_ROLLING_24H_MAX", "2000")
    assert growth_settings().outreach_account_rolling_24h_max == 2000

    monkeypatch.setenv("GROWTH_OPS_OUTREACH_ACCOUNT_ROLLING_24H_MAX", invalid)
    with pytest.raises(
        GrowthRegistryError,
        match="outreach_account_rolling_24h_max_invalid_no_send",
    ):
        growth_settings()


def test_account_send_concurrency_is_exactly_one(monkeypatch):
    monkeypatch.setenv("GROWTH_OPS_OUTREACH_SEND_CONCURRENCY", "1")
    assert growth_settings().outreach_send_concurrency == 1

    monkeypatch.setenv("GROWTH_OPS_OUTREACH_SEND_CONCURRENCY", "2")
    with pytest.raises(
        GrowthRegistryError,
        match="outreach_send_concurrency_must_be_one_no_send",
    ):
        growth_settings()


@pytest.mark.parametrize(
    ("name", "valid", "invalid", "error"),
    [
        (
            "GROWTH_OPS_OUTREACH_REPUTATION_BOOTSTRAP_MESSAGES_PER_WINDOW",
            "100",
            "50",
            "outreach_reputation_bootstrap_invalid_no_send",
        ),
        (
            "GROWTH_OPS_OUTREACH_REPUTATION_MAX_GROWTH_FACTOR",
            "1.25",
            "1.0",
            "outreach_reputation_growth_factor_invalid_no_send",
        ),
        (
            "GROWTH_OPS_OUTREACH_REPUTATION_JITTER_FRACTION",
            "0.20",
            "0.0",
            "outreach_reputation_jitter_invalid_no_send",
        ),
    ],
)
def test_reputation_pacing_policy_cannot_be_turned_into_a_shadow_cap(
    monkeypatch, name, valid, invalid, error
):
    monkeypatch.setenv(name, valid)
    growth_settings()

    monkeypatch.setenv(name, invalid)
    with pytest.raises(GrowthRegistryError, match=error):
        growth_settings()


def test_runtime_trip_uses_configured_writable_path_and_closes_writes(tmp_path, monkeypatch):
    owner_gate = tmp_path / "owner-gate"
    runtime_gate = tmp_path / "runtime" / "growth-kill-switch"
    runtime_gate.parent.mkdir()
    owner_gate.write_text("ALLOW_STAGING_WRITES\n", encoding="utf-8")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("GROWTH_OPS_KILL_SWITCH_FILE", str(owner_gate))
    monkeypatch.setenv("GROWTH_OPS_RUNTIME_KILL_SWITCH_FILE", str(runtime_gate))

    config = growth_settings()
    assert config.kill_switch_file == str(owner_gate)
    assert config.runtime_kill_switch_file == str(runtime_gate)
    assert registry.writes_unlocked()

    assert service._trip_runtime_kill_switch()
    assert runtime_gate.read_text(encoding="utf-8") == "KILLED\n"
    assert not registry.writes_unlocked()

    runtime_gate.unlink()
    assert registry.writes_unlocked()
    owner_gate.write_text("OWNER_STOP\n", encoding="utf-8")
    assert not registry.writes_unlocked()


def test_runtime_kill_write_failure_persists_database_emergency_stop(db, monkeypatch):
    service._PROCESS_EMERGENCY_SEND_STOP.clear()
    monkeypatch.setattr(service, "_trip_runtime_kill_switch", lambda: False)

    with pytest.raises(
        GrowthRegistryError,
        match="runtime_kill_switch_persist_failed_emergency_db_stop",
    ):
        service._require_runtime_kill_switch(
            db,
            reason="provider_acceptance_ambiguous_no_send",
        )

    for motor_key in sorted(service.GrowthRegistry.REQUIRED_MOTORS):
        row = db.get(service.GrowthControlState, f"motor:{motor_key}")
        assert row is not None
        assert row.enabled is False
        assert row.reason == "provider_acceptance_ambiguous_no_send"
        assert row.changed_by == "growth-worker-emergency-stop"
    assert not service._PROCESS_EMERGENCY_SEND_STOP.is_set()


def test_double_emergency_stop_failure_latches_process_and_aborts_batch(db, monkeypatch):
    first = _message(90, "first@example.hu", status="claimed")
    second = _message(91, "second@example.net", status="claimed")
    pending = [first, second]
    dispatch_calls: list[str] = []
    service._PROCESS_EMERGENCY_SEND_STOP.clear()
    monkeypatch.setattr(service, "_trip_runtime_kill_switch", lambda: False)

    def fail_database_stop(_db, *, reason):
        raise OSError(reason)

    monkeypatch.setattr(service, "_persist_database_emergency_stop", fail_database_stop)
    monkeypatch.setattr(
        db,
        "rollback",
        lambda: (_ for _ in ()).throw(OSError("database connection unavailable")),
    )
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)
    monkeypatch.setattr(service, "_outreach_send_capacity", lambda _db: 100)
    monkeypatch.setattr(
        service,
        "claim_outreach",
        lambda _db: pending.pop(0) if pending else None,
    )
    monkeypatch.setattr(
        service,
        "_contain_unexpected_dispatch_exception",
        lambda *_args, **_kwargs: None,
    )

    def dispatch_once(_db, row):
        dispatch_calls.append(row.outreach_id)
        service._require_runtime_kill_switch(
            _db,
            reason="provider_acceptance_ambiguous_no_send",
        )
        raise AssertionError("unreachable")

    monkeypatch.setattr(service, "dispatch_outreach", dispatch_once)
    try:
        assert service.dispatch_batch(db, limit=20) == 0
        assert dispatch_calls == [first.outreach_id]
        assert service._PROCESS_EMERGENCY_SEND_STOP.is_set()
        assert pending == [second]
    finally:
        service._PROCESS_EMERGENCY_SEND_STOP.clear()


@pytest.mark.parametrize(
    ("lock_function", "lock_key"),
    [
        (service._lock_outreach_claim_capacity, service.OUTREACH_CAPACITY_ADVISORY_LOCK_KEY),
        (service._lock_outreach_transport_account, service.OUTREACH_TRANSPORT_ADVISORY_LOCK_KEY),
    ],
)
def test_postgresql_capacity_and_account_transport_use_transaction_advisory_locks(
    lock_function,
    lock_key,
):
    calls = []

    class FakeDB:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement, params):
            calls.append((str(statement), params))

    lock_function(FakeDB())
    assert calls == [
        (
            "SELECT pg_advisory_xact_lock(:lock_key)",
            {"lock_key": lock_key},
        )
    ]


def test_claim_is_fail_closed_outside_window_without_queue_change(db, monkeypatch):
    row = _message(1, "office@example.hu")
    db.add(row)
    db.commit()
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: False)

    assert service.claim_outreach(db) is None
    db.refresh(row)
    assert row.status == "queued"
    assert row.attempt_count == 0
    assert row.claimed_at is None


def test_direct_dispatch_cannot_bypass_window_or_reach_transport(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    row = _message(2, "office@example.hu", status="claimed")
    row.claimed_by = "growth-cap-test"
    row.claimed_at = datetime.now(UTC)
    row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    row.attempt_count = 1
    db.add(row)
    db.commit()
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: False)

    class UnexpectedTransport:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("transport must not be constructed outside the window")

    monkeypatch.setattr(service, "SMTPEmailAdapter", UnexpectedTransport)
    result = service.dispatch_outreach(db, row)

    assert result is row
    assert row.status == "queued"
    assert row.attempt_count == 0
    assert row.claimed_by is None and row.claimed_at is None
    assert row.provider_message_id is None


def test_all_day_sentinel_allows_late_claim_and_dispatch(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    late_utc = datetime(2026, 8, 31, 21, 59, tzinfo=UTC)
    assert service._outreach_sending_window_open(late_utc) is True

    row = _message(3, "late@example.hu")
    db.add(row)
    db.commit()

    claimed = service.claim_outreach(db)
    assert claimed is not None and claimed.outreach_id == row.outreach_id

    claimed.status = "queued"
    claimed.claimed_by = None
    claimed.claimed_at = None
    claimed.lease_expires_at = None
    claimed.attempt_count = 0
    db.commit()
    dispatched: list[str] = []

    def dispatch_one(_db, candidate):
        dispatched.append(candidate.outreach_id)
        candidate.status = "sent"
        return candidate

    monkeypatch.setattr(service, "dispatch_outreach", dispatch_one)

    assert service.dispatch_batch(db, limit=100) == 1
    assert dispatched == [row.outreach_id]


def test_same_recipient_domain_history_does_not_create_a_static_quota(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)
    current = datetime.now(UTC)
    sent_rows = []
    for index in range(10, 35):
        row = _message(index, f"person{index}@branch.example.hu", status="sent")
        row.sent_at = current - timedelta(hours=2)
        row.provider_message_id = f"gmail-{index}"
        row.receipt_json = _verified_gmail_receipt(row.provider_message_id, f"{index:064x}")
        sent_rows.append(row)
    candidate = _message(100, "next@mail.example.hu")
    db.add_all([*sent_rows, candidate])
    db.commit()

    claimed = service.claim_outreach(db)

    assert claimed is not None
    assert claimed.outreach_id == candidate.outreach_id


def test_only_one_live_outreach_claim_can_exist(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)
    first = _message(110, "first@example.hu")
    second = _message(111, "second@example.net")
    db.add_all([first, second])
    db.commit()

    claimed = service.claim_outreach(db)

    assert claimed is not None and claimed.outreach_id == first.outreach_id
    assert service._outreach_transport_capacity_reserved(db, claimed)
    assert service.claim_outreach(db) is None
    db.refresh(second)
    assert second.status == "queued"
    assert second.attempt_count == 0


def test_pending_verification_row_reserves_quota_but_does_not_block_next_claim(
    db,
    monkeypatch,
):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)
    current = datetime.now(UTC)
    pending = _message(120, "held@example.hu", status="claimed")
    pending.claimed_at = current
    pending.claimed_by = None
    pending.lease_expires_at = None
    pending.provider_message_id = "gmail-possibly-accepted"
    pending.receipt_json = json.dumps(
        {
            "provider": "gmail_api",
            "accepted": True,
            "delivery_verification": {
                "status": "pending_verification",
                "retry_safe": False,
            },
        }
    )
    candidate = _message(121, "next@example.net")
    db.add_all([pending, candidate])
    db.commit()

    usage = _gmail_usage(current)
    assert service._gmail_account_unmatched_reservations(db, usage) == {
        "provider:gmail-possibly-accepted"
    }

    claimed = service.claim_outreach(db)
    assert claimed is not None and claimed.outreach_id == candidate.outreach_id


def test_composite_reservations_dedupe_the_same_provider_message_id(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    current = datetime.now(UTC)
    claimed = _message(130, "external@example.hu", status="claimed")
    claimed.claimed_at = current
    claimed.provider_message_id = "gmail-shared"
    sent = _message(131, "sent@example.net", status="sent")
    sent.sent_at = current
    sent.provider_message_id = "gmail-shared"
    sent.receipt_json = _verified_gmail_receipt("gmail-shared", "b" * 64)
    accepted_internal = _canonical_delivery(
        1,
        status="accepted_unverified",
        provider_message_id="gmail-shared",
        at=current,
    )
    sent_internal = _canonical_delivery(
        2,
        status="sent",
        provider_message_id="gmail-shared",
        at=current,
    )
    guard_sent = GlobalEmailRecipientGuard(
        recipient_normalized="guard@example.org",
        identity_sha256="d" * 64,
        message_type="growth_outreach",
        tenant_scope="imperial",
        status="sent",
        sent_at=current,
        provider_message_id="gmail-shared",
        created_at=current,
        updated_at=current,
    )
    db.add_all([claimed, sent, accepted_internal, sent_internal, guard_sent])
    db.commit()

    assert service._gmail_account_unmatched_reservations(
        db,
        _gmail_usage(current),
    ) == {"provider:gmail-shared"}
    assert service._gmail_account_unmatched_reservations(
        db,
        _gmail_usage(current, {"gmail-shared"}),
    ) == set()


def test_global_recipient_guard_sent_row_bridges_business_row_commit_gap(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    current = datetime.now(UTC)
    guard_sent = GlobalEmailRecipientGuard(
        recipient_normalized="guard-gap@example.org",
        identity_sha256="e" * 64,
        message_type="growth_outreach",
        tenant_scope="imperial",
        status="sent",
        sent_at=current,
        provider_message_id="gmail-guard-gap",
        created_at=current,
        updated_at=current,
    )
    db.add(guard_sent)
    db.commit()

    assert service._gmail_account_unmatched_reservations(
        db,
        _gmail_usage(current),
    ) == {"provider:gmail-guard-gap"}
    assert service._gmail_account_unmatched_reservations(
        db,
        _gmail_usage(current, {"gmail-guard-gap"}),
    ) == set()


def test_all_local_reservation_ledgers_include_the_exact_24h_cutoff(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    current = datetime.now(UTC)
    cutoff = current - timedelta(hours=24)
    claimed = _message(135, "claimed-cutoff@example.hu", status="claimed")
    claimed.claimed_at = cutoff
    claimed.provider_message_id = "gmail-claimed-cutoff"
    sent = _message(136, "sent-cutoff@example.net", status="delivered")
    sent.sent_at = cutoff
    sent.provider_message_id = "gmail-sent-cutoff"
    sent.receipt_json = _verified_gmail_receipt("gmail-sent-cutoff", "f" * 64)
    canonical_sending = _canonical_delivery(
        3,
        status="sending",
        provider_message_id="gmail-canonical-sending-cutoff",
        at=cutoff,
    )
    canonical_sent = _canonical_delivery(
        4,
        status="sent",
        provider_message_id="gmail-canonical-sent-cutoff",
        at=cutoff,
    )
    guard_sent = GlobalEmailRecipientGuard(
        recipient_normalized="guard-cutoff@example.org",
        identity_sha256="1" * 64,
        message_type="growth_outreach",
        tenant_scope="imperial",
        status="sent",
        sent_at=cutoff,
        provider_message_id="gmail-guard-cutoff",
        created_at=cutoff,
        updated_at=cutoff,
    )
    db.add_all([claimed, sent, canonical_sending, canonical_sent, guard_sent])
    db.commit()

    assert service._gmail_account_unmatched_reservations(
        db,
        _gmail_usage(current),
    ) == {
        "provider:gmail-claimed-cutoff",
        "provider:gmail-sent-cutoff",
        "provider:gmail-canonical-sending-cutoff",
        "provider:gmail-canonical-sent-cutoff",
        "provider:gmail-guard-cutoff",
    }


@pytest.mark.parametrize(
    "status",
    ["sent", "delivered", "responded", "bounced", "complained", "unsubscribed"],
)
def test_mime_verified_outreach_remains_a_local_24h_fallback_after_status_events(
    db,
    monkeypatch,
    status,
):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    current = datetime.now(UTC)
    row = _message(140, "sent@example.hu", status=status)
    row.sent_at = current
    row.provider_message_id = f"gmail-{status}"
    row.receipt_json = _verified_gmail_receipt(row.provider_message_id, "c" * 64)
    db.add(row)
    db.commit()

    assert service._gmail_account_unmatched_reservations(
        db,
        _gmail_usage(current),
    ) == {f"provider:gmail-{status}"}


def test_1999_gmail_sent_plus_current_reservation_is_allowed(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    current = datetime.now(UTC)
    row = _message(150, "current@example.hu", status="claimed")
    row.claimed_at = current
    db.add(row)
    db.commit()
    usage = _gmail_usage(current, {f"gmail-{index}" for index in range(1999)})

    attestation = service._assert_outreach_account_quota_reserved(db, row, usage)

    assert attestation["gmail_sent_messages"] == 1999
    assert attestation["unmatched_reservations"] == 1
    assert attestation["effective_reserved_count"] == 2000
    assert attestation["limit"] == 2000


def test_2000_gmail_sent_plus_current_reservation_is_blocked(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    current = datetime.now(UTC)
    row = _message(151, "current@example.hu", status="claimed")
    row.claimed_at = current
    db.add(row)
    db.commit()
    usage = _gmail_usage(current, {f"gmail-{index}" for index in range(2000)})

    with pytest.raises(
        EmailDeliveryError,
        match="gmail_account_rolling_24h_limit_reached_no_send",
    ) as raised:
        service._assert_outreach_account_quota_reserved(db, row, usage)

    assert raised.value.retry_safe is True
    assert raised.value.rate_limited is True
    assert raised.value.detail["effective_reserved_count"] == 2001
    assert raised.value.detail["limit"] == 2000


def test_pacing_adapts_to_verified_previous_window_without_static_hourly_quota(monkeypatch):
    current = datetime(2026, 8, 31, 9, tzinfo=UTC)
    monkeypatch.setattr(
        service,
        "settings",
        lambda: _runtime_settings(outreach_reputation_jitter_fraction=0.0),
    )

    bootstrap_gap = service._outreach_reputation_gap_seconds(
        _capacity_usage(previous=0),
        now=current,
    )
    grown_gap = service._outreach_reputation_gap_seconds(
        _capacity_usage(previous=400),
        now=current,
    )
    physical_floor = 24 * 60 * 60 / 2000

    assert bootstrap_gap == pytest.approx(24 * 60 * 60 / 100)
    assert grown_gap == pytest.approx(24 * 60 * 60 / 500)
    assert grown_gap < bootstrap_gap
    assert grown_gap >= physical_floor


def test_jitter_can_only_slow_pacing_not_exceed_growth_ceiling(monkeypatch):
    current = datetime(2026, 8, 31, 9, tzinfo=UTC)

    class ZeroDigest:
        def digest(self):
            return b"\0" * 32

    monkeypatch.setattr(service.hashlib, "sha256", lambda *_args, **_kwargs: ZeroDigest())
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    usage = _capacity_usage(previous=100)
    no_jitter_growth_ceiling_gap = 24 * 60 * 60 / 125

    gap = service._outreach_reputation_gap_seconds(usage, now=current)

    assert gap >= no_jitter_growth_ceiling_gap


def test_upward_jitter_cannot_trap_warmup_at_a_permanent_shadow_cap(monkeypatch):
    current = datetime(2026, 8, 31, 9, tzinfo=UTC)

    class MaxDigest:
        def digest(self):
            return b"\xff" * 32

    monkeypatch.setattr(service.hashlib, "sha256", lambda *_args, **_kwargs: MaxDigest())
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    bootstrap_gap = service._outreach_reputation_gap_seconds(
        _capacity_usage(previous=0),
        now=current,
    )
    reachable_worst_case_volume = 84
    ramped_gap = service._outreach_reputation_gap_seconds(
        _capacity_usage(previous=reachable_worst_case_volume),
        now=current,
    )

    assert ramped_gap < bootstrap_gap
    assert ramped_gap >= 24 * 60 * 60 / (
        reachable_worst_case_volume * 1.25
    )


def test_rate_limit_backoff_is_at_least_penalized_reputation_gap(db, monkeypatch):
    current = datetime(2026, 8, 31, 9, tzinfo=UTC)
    monkeypatch.setattr(
        service,
        "settings",
        lambda: _runtime_settings(outreach_reputation_jitter_fraction=0.0),
    )
    error = EmailDeliveryError(
        "gmail_api_rate_limited",
        retry_safe=True,
        rate_limited=True,
        retry_after_seconds=5,
    )

    next_at = service._record_outreach_pacing_backoff(db, error=error, now=current)

    assert next_at >= current + timedelta(seconds=1728)
    db.flush()
    state = db.get(GrowthControlState, service.OUTREACH_PACING_STATE_KEY)
    assert state is not None
    detail = json.loads(state.reason)
    assert detail["penalty_multiplier"] == 2.0
    assert detail["last_error"] == "gmail_api_rate_limited"


@pytest.mark.parametrize(
    ("sent_count", "complained", "bounced", "must_pause"),
    [
        (333, 1, 0, True),
        (334, 1, 0, False),
        (60, 0, 3, True),
        (40, 0, 2, False),
    ],
)
def test_account_reputation_health_pauses_or_slows_external_outreach(
    db,
    sent_count,
    complained,
    bounced,
    must_pause,
):
    current = datetime(2026, 8, 31, 9, tzinfo=UTC)
    rows = []
    for offset in range(sent_count):
        status = (
            "complained"
            if offset < complained
            else "bounced"
            if offset < complained + bounced
            else "sent"
        )
        rows.append(
            _verified_sent_message(
                10_000 + offset,
                status=status,
                sent_at=current - timedelta(hours=1),
            )
        )
    db.add_all(rows)
    db.commit()

    if must_pause:
        with pytest.raises(
            EmailDeliveryError,
            match="gmail_account_reputation_degraded_no_send",
        ) as raised:
            service._assert_outreach_reputation_healthy(db, current)
        assert raised.value.retry_safe is True
        assert raised.value.transport_attempted is False
        assert raised.value.detail["action"] == "pause_external_outreach"
    else:
        detail = service._assert_outreach_reputation_healthy(db, current)
        assert detail["action"] == "slow_external_outreach"
        assert detail["pacing_multiplier"] > 1.0


def test_persisted_pacing_gate_controls_when_one_slot_is_due(db, monkeypatch):
    current = datetime(2026, 8, 31, 9, tzinfo=UTC)
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    db.add(_message(160, "queued@example.hu"))
    state = GrowthControlState(
        key=service.OUTREACH_PACING_STATE_KEY,
        enabled=True,
        reason=json.dumps(
            {"next_send_not_before": (current + timedelta(minutes=1)).isoformat()}
        ),
        changed_by="test",
        changed_at=current,
    )
    db.add(state)
    db.commit()

    assert service._outreach_send_capacity(db, current) == 0
    state.reason = json.dumps(
        {"next_send_not_before": (current - timedelta(seconds=1)).isoformat()}
    )
    db.commit()
    assert service._outreach_send_capacity(db, current) == 1


def test_dispatch_batch_processes_at_most_one_due_item_per_tick(db, monkeypatch):
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)
    monkeypatch.setattr(service, "_outreach_send_capacity", lambda _db: 100)
    pending = [
        _message(170, "first@example.hu", status="claimed"),
        _message(171, "second@example.net", status="claimed"),
    ]
    dispatched: list[str] = []

    def claim_next(_db):
        return pending.pop(0) if pending else None

    def dispatch_one(_db, row):
        dispatched.append(row.outreach_id)
        row.status = "sent"
        return row

    monkeypatch.setattr(service, "claim_outreach", claim_next)
    monkeypatch.setattr(service, "dispatch_outreach", dispatch_one)

    assert service.dispatch_batch(db, limit=100) == 1
    assert dispatched == ["OUT-CAP-170"]
    assert [row.outreach_id for row in pending] == ["OUT-CAP-171"]


def test_parallel_sqlite_claims_reserve_exactly_one_active_sender(tmp_path, monkeypatch):
    database = tmp_path / "growth-outreach-concurrency.sqlite"
    sqlite_engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 20},
    )
    Base.metadata.create_all(sqlite_engine)
    sessions = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    with sessions() as db:
        db.add_all(
            [_message(200 + index, f"person{index}@branch.example.hu") for index in range(12)]
        )
        db.commit()

    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)

    def worker(_index):
        with sessions() as db:
            row = service.claim_outreach(db)
            return row.outreach_id if row else None

    with ThreadPoolExecutor(max_workers=12) as executor:
        claimed_ids = list(executor.map(worker, range(12)))

    assert len([value for value in claimed_ids if value]) == 1
    with sessions() as db:
        rows = db.scalars(select(OutreachMessage)).all()
        assert sum(row.status == "claimed" for row in rows) == 1
        assert sum(row.status == "queued" for row in rows) == 11
        assert sum(row.attempt_count for row in rows) == 1


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="requires the dedicated PostgreSQL integration-test database",
)
def test_postgresql_parallel_claims_reserve_exactly_one_with_advisory_lock(
    monkeypatch,
):
    with SessionLocal() as db:
        db.add_all(
            [_message(400 + index, f"person{index}@branch.example.hu") for index in range(12)]
        )
        db.commit()

    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)

    def worker(_index):
        with SessionLocal() as db:
            row = service.claim_outreach(db)
            return row.outreach_id if row else None

    with ThreadPoolExecutor(max_workers=12) as executor:
        claimed_ids = list(executor.map(worker, range(12)))

    assert len([value for value in claimed_ids if value]) == 1
    with SessionLocal() as db:
        rows = db.scalars(
            select(OutreachMessage).where(OutreachMessage.outreach_id.like("OUT-CAP-4%"))
        ).all()
        assert sum(row.status == "claimed" for row in rows) == 1
        assert sum(row.status == "queued" for row in rows) == 11
