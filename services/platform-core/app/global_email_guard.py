from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import Base

RECIPIENT_GUARD_WINDOW = timedelta(hours=24)
RECIPIENT_GUARD_LEASE = timedelta(minutes=5)
IDENTITY_RE = re.compile(r"^[0-9a-f]{64}$")
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$"
)


class GlobalEmailRecipientGuard(Base):
    __tablename__ = "global_email_recipient_guards"

    recipient_normalized: Mapped[str] = mapped_column(String(320), primary_key=True)
    identity_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    message_type: Mapped[str | None] = mapped_column(String(120), index=True)
    tenant_scope: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(32), default="idle", index=True)
    claim_token: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(500), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class GlobalEmailGuardEvent(Base):
    __tablename__ = "global_email_guard_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_normalized: Mapped[str] = mapped_column(String(320), index=True)
    identity_sha256: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    claim_token: Mapped[str | None] = mapped_column(String(120), index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(500), index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True)
class GlobalEmailGuardDecision:
    decision: str
    claim_token: str | None = None
    provider_message_id: str | None = None

    @property
    def may_send(self) -> bool:
        return self.decision == "claimed"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def normalize_recipients(recipients: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(sorted({str(value).strip().casefold() for value in recipients}))
    if not normalized or len(normalized) != len(recipients) or len(normalized) > 20:
        raise ValueError("global_email_guard_recipient_set_invalid")
    for recipient in normalized:
        if len(recipient) > 320 or not EMAIL_RE.fullmatch(recipient) or ".." in recipient:
            raise ValueError("global_email_guard_recipient_invalid")
    return normalized


def _validate_identity(identity_sha256: str) -> str:
    value = str(identity_sha256 or "").strip().casefold()
    if not IDENTITY_RE.fullmatch(value):
        raise ValueError("global_email_guard_identity_invalid")
    return value


def _claim_postgresql(
    db: Session,
    *,
    recipients: tuple[str, ...],
    identity_sha256: str,
    message_type: str,
    tenant_scope: str,
    current: datetime,
) -> GlobalEmailGuardDecision:
    row = db.execute(
        text(
            "SELECT decision, claim_token, provider_message_id "
            "FROM public.claim_global_email_recipient_guard("
            ":recipients, :identity_sha256, :message_type, :tenant_scope, :current)"
        ),
        {
            "recipients": list(recipients),
            "identity_sha256": identity_sha256,
            "message_type": message_type,
            "tenant_scope": tenant_scope,
            "current": current,
        },
    ).one()
    db.commit()
    return GlobalEmailGuardDecision(str(row[0]), row[1], row[2])


def claim_global_recipient_delivery(
    db: Session,
    *,
    recipients: list[str] | tuple[str, ...],
    identity_sha256: str,
    message_type: str,
    tenant_scope: str = "imperial-holding",
    now: datetime | None = None,
) -> GlobalEmailGuardDecision:
    normalized = normalize_recipients(recipients)
    identity = _validate_identity(identity_sha256)
    current = _aware(now) or datetime.now(UTC)
    if db.get_bind().dialect.name == "postgresql":
        return _claim_postgresql(
            db,
            recipients=normalized,
            identity_sha256=identity,
            message_type=message_type,
            tenant_scope=tenant_scope,
            current=current,
        )

    if db.get_bind().dialect.name == "sqlite":
        db.commit()
        db.execute(text("BEGIN IMMEDIATE"))
        insert = sqlite_insert(GlobalEmailRecipientGuard)
    else:
        insert = postgresql_insert(GlobalEmailRecipientGuard)
    db.execute(
        insert.values(
            [
                {
                    "recipient_normalized": recipient,
                    "status": "idle",
                    "created_at": current,
                    "updated_at": current,
                }
                for recipient in normalized
            ]
        ).on_conflict_do_nothing(index_elements=["recipient_normalized"])
    )
    states = db.scalars(
        select(GlobalEmailRecipientGuard)
        .where(GlobalEmailRecipientGuard.recipient_normalized.in_(normalized))
        .order_by(GlobalEmailRecipientGuard.recipient_normalized)
        .with_for_update()
    ).all()
    if len(states) != len(normalized):
        db.rollback()
        raise RuntimeError("global_email_guard_state_missing")

    same_sent = True
    provider_ids: set[str] = set()
    for state in states:
        sent_at = _aware(state.sent_at)
        lease_expires_at = _aware(state.lease_expires_at)
        if sent_at and sent_at > current - RECIPIENT_GUARD_WINDOW:
            if state.identity_sha256 != identity:
                db.rollback()
                return GlobalEmailGuardDecision("blocked_rolling_24h")
            if state.provider_message_id:
                provider_ids.add(state.provider_message_id)
            continue
        same_sent = False
        if state.status in {"claimed", "sending"}:
            if lease_expires_at and lease_expires_at > current:
                db.rollback()
                return GlobalEmailGuardDecision(
                    "in_progress" if state.identity_sha256 == identity else "blocked_active_claim"
                )
            db.rollback()
            return GlobalEmailGuardDecision(
                "reconcile_required"
                if state.identity_sha256 == identity
                else "blocked_stale_claim",
                claim_token=state.claim_token if state.identity_sha256 == identity else None,
                provider_message_id=(
                    state.provider_message_id if state.identity_sha256 == identity else None
                ),
            )
        if state.status == "accepted_unverified":
            db.rollback()
            return GlobalEmailGuardDecision(
                "reconcile_required" if state.identity_sha256 == identity else "blocked_ambiguous",
                claim_token=state.claim_token if state.identity_sha256 == identity else None,
                provider_message_id=(
                    state.provider_message_id if state.identity_sha256 == identity else None
                ),
            )

    if same_sent:
        db.rollback()
        provider_id = next(iter(provider_ids)) if len(provider_ids) == 1 else None
        return GlobalEmailGuardDecision("already_sent", provider_message_id=provider_id)

    claim_token = "GERG-" + uuid4().hex.upper()
    for state in states:
        state.identity_sha256 = identity
        state.message_type = message_type[:120]
        state.tenant_scope = tenant_scope[:120]
        state.status = "claimed"
        state.claim_token = claim_token
        state.claimed_at = current
        state.lease_expires_at = current + RECIPIENT_GUARD_LEASE
        state.provider_message_id = None
        state.last_error = None
        state.updated_at = current
        db.add(
            GlobalEmailGuardEvent(
                recipient_normalized=state.recipient_normalized,
                identity_sha256=identity,
                event_type="claimed",
                claim_token=claim_token,
                created_at=current,
            )
        )
    db.commit()
    return GlobalEmailGuardDecision("claimed", claim_token=claim_token)


def finalize_global_recipient_delivery(
    db: Session,
    *,
    recipients: list[str] | tuple[str, ...],
    identity_sha256: str,
    claim_token: str,
    provider_message_id: str,
    now: datetime | None = None,
) -> None:
    normalized = normalize_recipients(recipients)
    identity = _validate_identity(identity_sha256)
    current = _aware(now) or datetime.now(UTC)
    if db.get_bind().dialect.name == "postgresql":
        ok = db.scalar(
            text(
                "SELECT public.finalize_global_email_recipient_guard("
                ":recipients, :identity_sha256, :claim_token, :provider_message_id, :current)"
            ),
            {
                "recipients": list(normalized),
                "identity_sha256": identity,
                "claim_token": claim_token,
                "provider_message_id": provider_message_id,
                "current": current,
            },
        )
        if ok is not True:
            db.rollback()
            raise RuntimeError("global_email_guard_finalize_rejected")
        db.commit()
        return

    if db.get_bind().dialect.name == "sqlite":
        db.commit()
        db.execute(text("BEGIN IMMEDIATE"))
    states = db.scalars(
        select(GlobalEmailRecipientGuard)
        .where(GlobalEmailRecipientGuard.recipient_normalized.in_(normalized))
        .order_by(GlobalEmailRecipientGuard.recipient_normalized)
        .with_for_update()
    ).all()
    if len(states) != len(normalized) or any(
        state.identity_sha256 != identity
        or state.claim_token != claim_token
        or state.status not in {"claimed", "accepted_unverified"}
        for state in states
    ):
        db.rollback()
        raise RuntimeError("global_email_guard_finalize_rejected")
    for state in states:
        state.status = "sent"
        state.sent_at = current
        state.provider_message_id = provider_message_id
        state.lease_expires_at = None
        state.updated_at = current
        db.add(
            GlobalEmailGuardEvent(
                recipient_normalized=state.recipient_normalized,
                identity_sha256=identity,
                event_type="sent",
                claim_token=claim_token,
                provider_message_id=provider_message_id,
                created_at=current,
            )
        )
    db.commit()


def fail_global_recipient_delivery(
    db: Session,
    *,
    recipients: list[str] | tuple[str, ...],
    identity_sha256: str,
    claim_token: str,
    error: str,
    accepted_unverified: bool,
    provider_message_id: str | None = None,
    now: datetime | None = None,
) -> None:
    normalized = normalize_recipients(recipients)
    identity = _validate_identity(identity_sha256)
    current = _aware(now) or datetime.now(UTC)
    status = "accepted_unverified" if accepted_unverified else "failed_pre_send"
    if db.get_bind().dialect.name == "postgresql":
        ok = db.scalar(
            text(
                "SELECT public.fail_global_email_recipient_guard("
                ":recipients, :identity_sha256, :claim_token, :status, "
                ":provider_message_id, :error, :current)"
            ),
            {
                "recipients": list(normalized),
                "identity_sha256": identity,
                "claim_token": claim_token,
                "status": status,
                "provider_message_id": provider_message_id,
                "error": error[:2000],
                "current": current,
            },
        )
        if ok is not True:
            db.rollback()
            raise RuntimeError("global_email_guard_failure_record_rejected")
        db.commit()
        return

    if db.get_bind().dialect.name == "sqlite":
        db.commit()
        db.execute(text("BEGIN IMMEDIATE"))
    states = db.scalars(
        select(GlobalEmailRecipientGuard)
        .where(GlobalEmailRecipientGuard.recipient_normalized.in_(normalized))
        .order_by(GlobalEmailRecipientGuard.recipient_normalized)
        .with_for_update()
    ).all()
    if len(states) != len(normalized) or any(
        state.identity_sha256 != identity or state.claim_token != claim_token for state in states
    ):
        db.rollback()
        raise RuntimeError("global_email_guard_failure_record_rejected")
    for state in states:
        state.status = status
        state.provider_message_id = provider_message_id
        state.last_error = error[:2000]
        state.lease_expires_at = None
        state.updated_at = current
        db.add(
            GlobalEmailGuardEvent(
                recipient_normalized=state.recipient_normalized,
                identity_sha256=identity,
                event_type=status,
                claim_token=claim_token,
                provider_message_id=provider_message_id,
                detail=error[:2000],
                created_at=current,
            )
        )
    db.commit()


def guard_identity(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
