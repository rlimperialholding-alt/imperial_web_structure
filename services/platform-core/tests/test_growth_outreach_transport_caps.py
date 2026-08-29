from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base, SessionLocal, engine
from app.growth_ops import registry, service
from app.growth_ops.models import OutreachMessage
from app.growth_ops.registry import settings as growth_settings


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


def _runtime_settings(**changes):
    values = {
        "timezone": "Europe/Budapest",
        "worker_id": "growth-cap-test",
        "lease_seconds": 300,
        "outreach_send_start_local": "08:00",
        "outreach_send_end_local": "18:00",
        "outreach_max_per_hour": 100,
        "outreach_max_per_day": 100,
        "outreach_max_per_recipient_root_domain_per_day": 10,
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("Sales@Example.HU", "example.hu"),
        ("office@mail.example.hu.", "example.hu"),
        ("hello@branch.example.co.uk", "example.co.uk"),
        ("hello@branch.example.com.au", "example.com.au"),
        ("hello@a.b.ide.kyoto.jp", "b.ide.kyoto.jp"),
        ("hello@foo.blogspot.com", "foo.blogspot.com"),
        ("hello@BÜRO.at", "xn--bro-hoa.at"),
    ],
)
def test_recipient_root_domain_normalization(email, expected):
    assert service._recipient_root_domain(email) == expected


@pytest.mark.parametrize("email", ["missing-at", "x@", "x@bad..hu"])
def test_recipient_root_domain_rejects_invalid_values(email):
    with pytest.raises(ValueError, match="root_domain_invalid_no_send"):
        service._recipient_root_domain(email)


def test_only_gmail_sent_with_full_mime_readback_consumes_verified_quota():
    current = datetime(2026, 8, 29, 9, tzinfo=UTC)
    row = SimpleNamespace(
        sent_at=current,
        provider_message_id="gmail-id",
        receipt_json=json.dumps(
            {
                "provider": "gmail_api",
                "accepted": True,
                "delivery_detail": {
                    "readback_verified": True,
                    "readback_mime_sha256": "a" * 64,
                    "rfc_message_id": "<message@example.hu>",
                },
            }
        ),
    )
    assert service._gmail_sent_mime_verified(row)

    receipt = json.loads(row.receipt_json)
    receipt["delivery_detail"].pop("readback_mime_sha256")
    row.receipt_json = json.dumps(receipt)
    assert not service._gmail_sent_mime_verified(row)


def test_root_domain_cap_cannot_be_relaxed_above_ten(monkeypatch):
    monkeypatch.setenv(
        "GROWTH_OPS_OUTREACH_MAX_PER_RECIPIENT_ROOT_DOMAIN_PER_DAY",
        "99",
    )

    assert growth_settings().outreach_max_per_recipient_root_domain_per_day == 10


def test_hour_and_day_caps_cannot_be_relaxed(monkeypatch):
    monkeypatch.setenv("GROWTH_OPS_OUTREACH_MAX_PER_HOUR", "100")
    monkeypatch.setenv("GROWTH_OPS_OUTREACH_MAX_PER_DAY", "1000")

    config = growth_settings()
    assert config.outreach_max_per_hour == 5
    assert config.outreach_max_per_day == 50


def test_runtime_trip_uses_configured_writable_path_and_closes_writes(
    tmp_path, monkeypatch
):
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


def test_postgresql_claim_uses_transaction_advisory_lock():
    calls = []

    class FakeDB:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement, params):
            calls.append((str(statement), params))

    service._lock_outreach_claim_capacity(FakeDB())

    assert calls == [
        (
            "SELECT pg_advisory_xact_lock(:lock_key)",
            {"lock_key": service.OUTREACH_CAPACITY_ADVISORY_LOCK_KEY},
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


def test_exact_root_domain_cap_skips_capped_domain_without_claiming(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)
    for index in range(10):
        row = _message(index + 10, f"person{index}@sub.example.hu", status="claimed")
        row.claimed_at = datetime.now(UTC)
        row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        db.add(row)
    capped = _message(100, "next@mail.example.hu")
    available = _message(101, "next@different.hu")
    db.add_all([capped, available])
    db.commit()

    claimed = service.claim_outreach(db)

    assert claimed is not None and claimed.outreach_id == available.outreach_id
    db.refresh(capped)
    assert capped.status == "queued"
    assert capped.attempt_count == 0


def test_capacity_usage_buckets_queued_and_claimed_by_budapest_hour_and_day(
    db, monkeypatch
):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    local_now = datetime(2026, 8, 29, 10, 15, tzinfo=ZoneInfo("Europe/Budapest"))
    current = local_now.astimezone(UTC)
    hourly_queued = _message(102, "hourly@one.hu")
    hourly_queued.available_at = current - timedelta(minutes=5)
    daily_queued = _message(103, "daily@two.hu")
    daily_queued.available_at = current - timedelta(hours=2)
    future_queued = _message(104, "future@three.hu")
    future_queued.available_at = current + timedelta(days=1)
    hourly_claimed = _message(105, "claimed@four.hu", status="claimed")
    hourly_claimed.claimed_at = current - timedelta(minutes=2)
    daily_claimed = _message(106, "claimed@five.hu", status="claimed")
    daily_claimed.claimed_at = current - timedelta(hours=2)
    old_claimed = _message(107, "claimed@six.hu", status="claimed")
    old_claimed.claimed_at = current - timedelta(days=1)
    db.add_all(
        [
            hourly_queued,
            daily_queued,
            future_queued,
            hourly_claimed,
            daily_claimed,
            old_claimed,
        ]
    )
    db.commit()

    usage = service._outreach_capacity_usage(db, current)

    assert usage.hourly_queued == 1
    assert usage.daily_queued == 2
    assert usage.hourly_claimed == 1
    assert usage.daily_claimed == 2


def test_ambiguous_accepted_claim_without_claimed_at_still_reserves_capacity(
    db, monkeypatch
):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    local_now = datetime(2026, 8, 29, 10, 15, tzinfo=ZoneInfo("Europe/Budapest"))
    current = local_now.astimezone(UTC)
    ambiguous = _message(108, "held@branch.example.hu", status="claimed")
    ambiguous.claimed_at = None
    ambiguous.claimed_by = None
    ambiguous.lease_expires_at = None
    ambiguous.provider_message_id = "gmail-possibly-accepted"
    ambiguous.receipt_json = json.dumps(
        {
            "provider": "gmail_api",
            "accepted": True,
            "delivery_verification": {
                "status": "pending_verification",
                "retry_safe": False,
            },
        }
    )
    ambiguous.updated_at = current - timedelta(minutes=1)
    db.add(ambiguous)
    db.commit()

    usage = service._outreach_capacity_usage(db, current)

    assert usage.hourly_claimed == 1
    assert usage.daily_claimed == 1
    assert usage.daily_domain_reservations == {"example.hu": 1}


def test_ten_ambiguous_claims_without_claimed_at_block_same_domain(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)
    current = datetime.now(UTC)
    for index in range(10):
        ambiguous = _message(
            160 + index,
            f"held{index}@branch.example.hu",
            status="claimed",
        )
        ambiguous.claimed_at = None
        ambiguous.claimed_by = None
        ambiguous.lease_expires_at = None
        ambiguous.provider_message_id = f"gmail-ambiguous-{index}"
        ambiguous.receipt_json = json.dumps(
            {
                "provider": "gmail_api",
                "accepted": True,
                "delivery_verification": {
                    "status": "pending_verification",
                    "retry_safe": False,
                },
            }
        )
        ambiguous.updated_at = current
        db.add(ambiguous)
    candidate = _message(170, "next@mail.example.hu")
    db.add(candidate)
    db.commit()

    assert service.claim_outreach(db) is None
    db.refresh(candidate)
    assert candidate.status == "queued"
    assert candidate.attempt_count == 0


def test_expired_ambiguous_claim_preserves_reservation_timestamp(db, monkeypatch):
    monkeypatch.setattr(service, "_trip_runtime_kill_switch", lambda: True)
    claimed_at = datetime.now(UTC) - timedelta(minutes=10)
    ambiguous = _message(109, "held@example.hu", status="claimed")
    ambiguous.claimed_by = "dead-worker"
    ambiguous.claimed_at = claimed_at
    ambiguous.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.add(ambiguous)
    db.commit()

    service._release_expired_claims(db)
    db.commit()
    db.refresh(ambiguous)

    assert ambiguous.status == "claimed"
    assert service._aware(ambiguous.claimed_at) == claimed_at
    assert ambiguous.claimed_by is None
    assert ambiguous.lease_expires_at is None
    assert service._delivery_verification_pending(ambiguous)


def test_verified_sent_plus_claimed_reservations_reach_exact_domain_cap(
    db, monkeypatch
):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)
    current = datetime.now(UTC)
    verified = _message(110, "sent@example.hu", status="sent")
    verified.sent_at = current
    verified.provider_message_id = "gmail-verified-id"
    verified.receipt_json = json.dumps(
        {
            "provider": "gmail_api",
            "accepted": True,
            "delivery_detail": {
                "readback_verified": True,
                "readback_mime_sha256": "b" * 64,
                "rfc_message_id": "<verified@example.hu>",
            },
        }
    )
    db.add(verified)
    for index in range(9):
        reserved = _message(
            111 + index,
            f"person{index}@sub.example.hu",
            status="claimed",
        )
        reserved.claimed_at = current
        reserved.lease_expires_at = current + timedelta(minutes=5)
        db.add(reserved)
    candidate = _message(121, "next@mail.example.hu")
    db.add(candidate)
    db.commit()

    assert service.claim_outreach(db) is None
    db.refresh(candidate)
    assert candidate.status == "queued"
    assert candidate.attempt_count == 0


def test_dispatch_batch_isolates_unexpected_row_and_continues(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)
    monkeypatch.setattr(service, "_outreach_send_capacity", lambda _db: 2)
    bad = _message(150, "bad@example.hu", status="claimed")
    bad.claimed_by = "growth-cap-test"
    bad.claimed_at = datetime.now(UTC)
    bad.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    good = _message(151, "good@different.hu", status="claimed")
    good.claimed_by = "growth-cap-test"
    good.claimed_at = datetime.now(UTC)
    good.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    db.add_all([bad, good])
    db.commit()
    claimed_ids = iter([bad.id, good.id])

    def claim_next(current_db):
        return current_db.get(OutreachMessage, next(claimed_ids))

    def dispatch_one(current_db, row):
        if row.id == bad.id:
            raise RuntimeError("malformed isolated row")
        row.status = "sent"
        current_db.commit()
        return row

    monkeypatch.setattr(service, "claim_outreach", claim_next)
    monkeypatch.setattr(service, "dispatch_outreach", dispatch_one)

    assert service.dispatch_batch(db, limit=2) == 1
    db.refresh(bad)
    db.refresh(good)
    assert bad.status == "claimed"
    assert bad.claimed_by is None
    assert bad.claimed_at is not None
    assert bad.lease_expires_at is None
    assert bad.last_error == "unexpected_dispatch_exception:RuntimeError"
    assert service._delivery_verification_pending(bad)
    assert good.status == "sent"


def test_direct_dispatch_cannot_bypass_reserved_root_domain_cap(db, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: _runtime_settings())
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)
    for index in range(10):
        reserved = _message(
            120 + index,
            f"person{index}@sub.example.hu",
            status="claimed",
        )
        reserved.claimed_at = datetime.now(UTC)
        reserved.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        db.add(reserved)
    row = _message(140, "direct@mail.example.hu", status="claimed")
    row.claimed_by = "growth-cap-test"
    row.claimed_at = datetime.now(UTC)
    row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    row.attempt_count = 1
    db.add(row)
    db.commit()

    class UnexpectedTransport:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("transport must not run without reserved domain capacity")

    monkeypatch.setattr(service, "SMTPEmailAdapter", UnexpectedTransport)
    result = service.dispatch_outreach(db, row)

    assert result is row
    assert row.status == "queued"
    assert row.attempt_count == 0
    assert row.claimed_by is None and row.claimed_at is None
    assert row.provider_message_id is None


def test_parallel_claims_reserve_exactly_ten_per_root_domain(tmp_path, monkeypatch):
    database = tmp_path / "growth-outreach-domain-cap.sqlite"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 20},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
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

    assert len([value for value in claimed_ids if value]) == 10
    with sessions() as db:
        rows = db.scalars(select(OutreachMessage)).all()
        assert sum(row.status == "claimed" for row in rows) == 10
        assert sum(row.status == "queued" for row in rows) == 2
        assert sum(row.attempt_count for row in rows) == 10


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="requires the dedicated PostgreSQL integration-test database",
)
def test_postgresql_parallel_claims_reserve_exactly_ten_with_advisory_lock(
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

    assert len([value for value in claimed_ids if value]) == 10
    with SessionLocal() as db:
        rows = db.scalars(
            select(OutreachMessage).where(OutreachMessage.outreach_id.like("OUT-CAP-4%"))
        ).all()
        assert sum(row.status == "claimed" for row in rows) == 10
        assert sum(row.status == "queued" for row in rows) == 2
