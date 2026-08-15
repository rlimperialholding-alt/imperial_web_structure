from __future__ import annotations

import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any, TypeVar

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import CanonicalSyncLease

LEASE_KEYS = frozenset(
    {"crm-import", "crm-push", "crm-reconcile", "itep-pull", "itep-push"}
)
LEASE_TTL = timedelta(minutes=15)
HEARTBEAT_INTERVAL = timedelta(minutes=5)


class CanonicalSyncBusy(RuntimeError):
    """Raised when a non-expired owner already holds a canonical sync lease."""

    def __init__(self, lease_key: str):
        self.lease_key = lease_key
        super().__init__(
            f"A(z) {lease_key} kanonikus szinkron már fut; párhuzamos indítás tiltott."
        )


class CanonicalSyncLeaseLost(RuntimeError):
    """Raised when a running operation can no longer renew its own lease."""

    def __init__(self, lease_key: str, detail: str = "lease elveszett"):
        self.lease_key = lease_key
        super().__init__(f"A(z) {lease_key} kanonikus szinkron {detail}.")


class LeaseHandle:
    def __init__(self, lease_key: str, holder_token: str, heartbeat_at: datetime):
        self.lease_key = lease_key
        self.holder_token = holder_token
        self.heartbeat_at = heartbeat_at

    def renew_if_due(self) -> None:
        now = datetime.now(UTC)
        if now - self.heartbeat_at < HEARTBEAT_INTERVAL:
            return
        with SessionLocal() as lease_db:
            result = lease_db.execute(
                update(CanonicalSyncLease)
                .where(
                    CanonicalSyncLease.lease_key == self.lease_key,
                    CanonicalSyncLease.holder_token == self.holder_token,
                    CanonicalSyncLease.expires_at > now,
                )
                .values(
                    heartbeat_at=now,
                    expires_at=now + LEASE_TTL,
                    updated_at=now,
                )
            )
            lease_db.commit()
        if result.rowcount != 1:
            raise CanonicalSyncLeaseLost(self.lease_key)
        self.heartbeat_at = now

    def release(self) -> bool:
        now = datetime.now(UTC)
        with SessionLocal() as lease_db:
            result = lease_db.execute(
                update(CanonicalSyncLease)
                .where(
                    CanonicalSyncLease.lease_key == self.lease_key,
                    CanonicalSyncLease.holder_token == self.holder_token,
                )
                .values(
                    holder_token=None,
                    heartbeat_at=None,
                    expires_at=None,
                    last_released_at=now,
                    updated_at=now,
                )
            )
            lease_db.commit()
        return result.rowcount == 1


_current_lease: ContextVar[LeaseHandle | None] = ContextVar(
    "canonical_sync_lease", default=None
)


def _ensure_lease_row(lease_db: Session, lease_key: str, now: datetime) -> None:
    row = lease_db.scalar(
        select(CanonicalSyncLease).where(CanonicalSyncLease.lease_key == lease_key)
    )
    if row is not None:
        return
    lease_db.add(
        CanonicalSyncLease(
            lease_key=lease_key,
            generation=0,
            contention_count=0,
            updated_at=now,
        )
    )
    try:
        lease_db.commit()
    except IntegrityError:
        # A concurrent first owner inserted the unique lease row.
        lease_db.rollback()


def acquire_canonical_sync_lease(lease_key: str) -> LeaseHandle:
    if lease_key not in LEASE_KEYS:
        raise ValueError(f"Ismeretlen kanonikus sync lease: {lease_key}.")
    now = datetime.now(UTC)
    holder_token = uuid.uuid4().hex
    with SessionLocal() as lease_db:
        _ensure_lease_row(lease_db, lease_key, now)
        result = lease_db.execute(
            update(CanonicalSyncLease)
            .where(
                CanonicalSyncLease.lease_key == lease_key,
                or_(
                    CanonicalSyncLease.holder_token.is_(None),
                    CanonicalSyncLease.expires_at.is_(None),
                    CanonicalSyncLease.expires_at <= now,
                ),
            )
            .values(
                holder_token=holder_token,
                acquired_at=now,
                heartbeat_at=now,
                expires_at=now + LEASE_TTL,
                generation=CanonicalSyncLease.generation + 1,
                updated_at=now,
            )
        )
        lease_db.commit()
        acquired = result.rowcount == 1
        if not acquired:
            lease_db.execute(
                update(CanonicalSyncLease)
                .where(CanonicalSyncLease.lease_key == lease_key)
                .values(
                    contention_count=CanonicalSyncLease.contention_count + 1,
                    last_contention_at=now,
                    updated_at=now,
                )
            )
            lease_db.commit()
    if not acquired:
        raise CanonicalSyncBusy(lease_key)
    return LeaseHandle(lease_key, holder_token, now)


def heartbeat_canonical_sync_lease() -> None:
    lease = _current_lease.get()
    if lease is None:
        raise CanonicalSyncLeaseLost("unknown", "futásához nincs aktív lease")
    lease.renew_if_due()


F = TypeVar("F", bound=Callable[..., Any])


def serialized_canonical_sync(lease_key: str) -> Callable[[F], F]:
    if lease_key not in LEASE_KEYS:
        raise ValueError(f"Ismeretlen kanonikus sync lease: {lease_key}.")

    def decorator(function: F) -> F:
        @wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            lease = acquire_canonical_sync_lease(lease_key)
            context_token = _current_lease.set(lease)
            try:
                result = function(*args, **kwargs)
            except BaseException:
                _current_lease.reset(context_token)
                try:
                    lease.release()
                except Exception:
                    # Keep the business failure authoritative; expiry recovers the lease.
                    pass
                raise
            _current_lease.reset(context_token)
            if not lease.release():
                raise CanonicalSyncLeaseLost(lease_key, "lease lezárása sikertelen")
            return result

        return wrapper  # type: ignore[return-value]

    return decorator
