from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class GrowthRun(Base):
    __tablename__ = "growth_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','completed','partial','failed','disabled')",
            name="ck_growth_run_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    motor_key: Mapped[str] = mapped_column(String(80), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    attempted_sources: Mapped[int] = mapped_column(Integer, default=0)
    succeeded_sources: Mapped[int] = mapped_column(Integer, default=0)
    raw_signals: Mapped[int] = mapped_column(Integer, default=0)
    accepted_signals: Mapped[int] = mapped_column(Integer, default=0)
    queued_outreach: Mapped[int] = mapped_column(Integer, default=0)
    sent_outreach: Mapped[int] = mapped_column(Integer, default=0)
    source_results_json: Mapped[str] = mapped_column(Text, default="[]")
    error_json: Mapped[str] = mapped_column(Text, default="[]")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GrowthSignal(Base):
    __tablename__ = "growth_signals"
    __table_args__ = (
        UniqueConstraint("source_id", "external_key", name="uq_growth_signal_source_external"),
        UniqueConstraint("dedupe_hash", name="uq_growth_signal_dedupe_hash"),
        CheckConstraint(
            "subject_type IN ('organization','natural_person','project')",
            name="ck_growth_signal_subject_type",
        ),
        CheckConstraint(
            "recipient_email_type IN ('role','named','unknown','none')",
            name="ck_growth_signal_email_type",
        ),
        CheckConstraint(
            "status IN ('accepted','rejected','blocked','queued',"
            "'contacted','responded','suppressed')",
            name="ck_growth_signal_status",
        ),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_growth_signal_score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(120), index=True)
    motor_key: Mapped[str] = mapped_column(String(80), index=True)
    source_id: Mapped[str] = mapped_column(String(120), index=True)
    source_bucket: Mapped[str] = mapped_column(String(100), index=True)
    external_key: Mapped[str] = mapped_column(String(255), index=True)
    signal_type: Mapped[str] = mapped_column(String(120), index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    company_name: Mapped[str | None] = mapped_column(String(500), index=True)
    company_registration_id: Mapped[str | None] = mapped_column(String(120), index=True)
    subject_type: Mapped[str] = mapped_column(String(30), index=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320), index=True)
    recipient_email_type: Mapped[str] = mapped_column(String(20), default="none", index=True)
    contact_basis: Mapped[str] = mapped_column(String(80), index=True)
    consent_evidence_id: Mapped[str | None] = mapped_column(String(200))
    public_contact_url: Mapped[str | None] = mapped_column(String(1500))
    location: Mapped[str | None] = mapped_column(String(500), index=True)
    summary: Mapped[str] = mapped_column(Text)
    evidence_url: Mapped[str] = mapped_column(String(1500))
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    urgency: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    dedupe_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="accepted", index=True)
    rejection_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OutreachMessage(Base):
    __tablename__ = "growth_outreach_messages"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_growth_outreach_idempotency"),
        UniqueConstraint("signal_id", "sequence_step", name="uq_growth_outreach_signal_step"),
        CheckConstraint(
            "status IN ('queued','claimed','sent','delivered','responded','bounced','complained',"
            "'unsubscribed','suppressed','blocked','failed','dead_letter')",
            name="ck_growth_outreach_status",
        ),
        CheckConstraint(
            "sequence_step >= 0 AND sequence_step <= 2", name="ck_growth_outreach_step"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    outreach_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    signal_id: Mapped[str] = mapped_column(String(120), index=True)
    motor_key: Mapped[str] = mapped_column(String(80), index=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    sender_email: Mapped[str] = mapped_column(String(320), index=True)
    recipient_email: Mapped[str] = mapped_column(String(320), index=True)
    sequence_step: Mapped[int] = mapped_column(Integer, default=0)
    subject: Mapped[str] = mapped_column(String(500))
    body_text: Mapped[str] = mapped_column(Text)
    unsubscribe_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), index=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    claimed_by: Mapped[str | None] = mapped_column(String(160), index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(500), index=True)
    receipt_json: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class GrowthWorkerHeartbeat(Base):
    __tablename__ = "growth_worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="starting", index=True)
    current_motor_key: Mapped[str | None] = mapped_column(String(80))
    current_outreach_id: Mapped[str | None] = mapped_column(String(120))
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class GrowthControlState(Base):
    __tablename__ = "growth_control_state"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[str | None] = mapped_column(String(255))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
