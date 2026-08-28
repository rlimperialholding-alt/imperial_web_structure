from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Lock

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.global_email_guard import (
    GlobalEmailGuardEvent,
    GlobalEmailRecipientGuard,
    claim_global_recipient_delivery,
    finalize_global_recipient_delivery,
    guard_identity,
)


def test_four_parallel_brand_engines_produce_exactly_one_provider_send(tmp_path):
    database = tmp_path / "global-email-guard.sqlite"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 20},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    current = datetime(2026, 8, 28, 18, tzinfo=UTC)
    recipient = "controlled.guard@imperialholding.hu"
    send_count = 0
    send_lock = Lock()

    def worker(brand: str):
        nonlocal send_count
        identity = guard_identity("controlled_parallel", brand, current.isoformat())
        with sessions() as db:
            decision = claim_global_recipient_delivery(
                db,
                recipients=[recipient],
                identity_sha256=identity,
                message_type=f"controlled_{brand}",
                now=current,
            )
            if decision.may_send:
                with send_lock:
                    send_count += 1
                finalize_global_recipient_delivery(
                    db,
                    recipients=[recipient],
                    identity_sha256=identity,
                    claim_token=str(decision.claim_token),
                    provider_message_id="CONTROLLED-PROVIDER-1",
                    now=current,
                )
            return decision.decision

    with ThreadPoolExecutor(max_workers=4) as executor:
        decisions = list(executor.map(worker, ("imperial", "prefab", "bautica", "baufreund")))

    assert send_count == 1
    assert decisions.count("claimed") == 1
    assert all(
        value in {"claimed", "blocked_active_claim", "blocked_rolling_24h"} for value in decisions
    )
    with sessions() as db:
        state = db.get(GlobalEmailRecipientGuard, recipient)
        assert state is not None
        assert state.status == "sent"
        assert state.provider_message_id == "CONTROLLED-PROVIDER-1"
        assert len(db.scalars(select(GlobalEmailGuardEvent)).all()) == 2
        blocked = claim_global_recipient_delivery(
            db,
            recipients=[recipient],
            identity_sha256=guard_identity("later_same_day"),
            message_type="later_same_day",
            now=current + timedelta(hours=23, minutes=59),
        )
        assert blocked.decision == "blocked_rolling_24h"
        released = claim_global_recipient_delivery(
            db,
            recipients=[recipient],
            identity_sha256=guard_identity("next_day"),
            message_type="next_day",
            now=current + timedelta(hours=24, seconds=1),
        )
        assert released.decision == "claimed"


def test_multi_recipient_claim_is_all_or_nothing(db):
    current = datetime(2026, 8, 28, 18, tzinfo=UTC)
    first_identity = guard_identity("first")
    first = claim_global_recipient_delivery(
        db,
        recipients=["one@imperialholding.hu"],
        identity_sha256=first_identity,
        message_type="first",
        now=current,
    )
    finalize_global_recipient_delivery(
        db,
        recipients=["one@imperialholding.hu"],
        identity_sha256=first_identity,
        claim_token=str(first.claim_token),
        provider_message_id="MSG-ONE",
        now=current,
    )

    blocked = claim_global_recipient_delivery(
        db,
        recipients=["one@imperialholding.hu", "two@imperialholding.hu"],
        identity_sha256=guard_identity("multi"),
        message_type="multi",
        now=current + timedelta(hours=1),
    )
    assert blocked.decision == "blocked_rolling_24h"
    second_state = db.get(GlobalEmailRecipientGuard, "two@imperialholding.hu")
    assert second_state is None or second_state.status == "idle"
