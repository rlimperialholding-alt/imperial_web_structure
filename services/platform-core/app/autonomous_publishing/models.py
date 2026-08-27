from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..models import utcnow


class PublishingJobRecord(Base):
    __tablename__ = "pub_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','BLOCKED','RUNNING','VERIFIED','FAILED',"
            "'ROLLING_BACK','ROLLED_BACK','ROLLBACK_FAILED')",
            name="ck_pub_jobs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    content_asset_id: Mapped[str] = mapped_column(String(120), index=True)
    content_version_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    cms_route: Mapped[str] = mapped_column(String(30), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(120), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    desired_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    attempt_count: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=5)
    claimed_by: Mapped[str | None] = mapped_column(String(160), index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_successful_step: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PublishingChannelState(Base):
    __tablename__ = "pub_channel_states"
    __table_args__ = (
        UniqueConstraint("job_id", "channel", name="uq_pub_channel_job_channel"),
        UniqueConstraint(
            "brand_id",
            "content_asset_id",
            "content_version_id",
            "channel",
            name="uq_pub_channel_content_idempotency",
        ),
        CheckConstraint(
            "status IN ('QUEUED','BLOCKED','DRAFT_CREATED','PUBLISHING','PUBLISHED',"
            "'READBACK_VERIFIED','FAILED','ROLLING_BACK','ROLLED_BACK',"
            "'ROLLBACK_FAILED','DRAFT_ONLY')",
            name="ck_pub_channel_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_state_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("pub_jobs.job_id", ondelete="CASCADE"), index=True
    )
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    content_asset_id: Mapped[str] = mapped_column(String(120), index=True)
    content_version_id: Mapped[str] = mapped_column(String(120), index=True)
    channel: Mapped[str] = mapped_column(String(40), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    public_url: Mapped[str | None] = mapped_column(String(1000))
    admin_url: Mapped[str | None] = mapped_column(String(1000))
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    canonical_url: Mapped[str | None] = mapped_column(String(1000))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    rollback_status: Mapped[str | None] = mapped_column(String(30), index=True)
    rollback_readback_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PublicationProofRecord(Base):
    __tablename__ = "pub_proofs"

    id: Mapped[int] = mapped_column(primary_key=True)
    proof_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("pub_jobs.job_id", ondelete="CASCADE"), index=True
    )
    channel_state_id: Mapped[str] = mapped_column(
        ForeignKey("pub_channel_states.channel_state_id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    channel: Mapped[str] = mapped_column(String(40), index=True)
    external_id: Mapped[str] = mapped_column(String(255), index=True)
    public_url: Mapped[str] = mapped_column(String(1000))
    content_asset_id: Mapped[str] = mapped_column(String(120), index=True)
    content_version_id: Mapped[str] = mapped_column(String(120), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    canonical_url: Mapped[str | None] = mapped_column(String(1000))
    readback_json: Mapped[str] = mapped_column(Text)
    readback_sha256: Mapped[str] = mapped_column(String(64), index=True)
    analytics_event_id: Mapped[str | None] = mapped_column(String(160), index=True)
    crm_event_id: Mapped[str | None] = mapped_column(String(160), index=True)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class PublishingExceptionRecord(Base):
    __tablename__ = "pub_exceptions"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('BLOCKER','CRITICAL','MAJOR','MINOR')",
            name="ck_pub_exception_severity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exception_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("pub_jobs.job_id", ondelete="CASCADE"), index=True
    )
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    content_asset_id: Mapped[str] = mapped_column(String(120), index=True)
    content_version_id: Mapped[str] = mapped_column(String(120), index=True)
    channel: Mapped[str | None] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    error_type: Mapped[str] = mapped_column(String(100), index=True)
    last_successful_step: Mapped[str | None] = mapped_column(String(100))
    redacted_response_json: Mapped[str] = mapped_column(Text, default="{}")
    admin_url: Mapped[str | None] = mapped_column(String(1000))
    public_url: Mapped[str | None] = mapped_column(String(1000))
    publication_proof_id: Mapped[str | None] = mapped_column(String(120), index=True)
    rollback_status: Mapped[str | None] = mapped_column(String(30), index=True)
    recommended_action: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(
        String(255), default="SYSTEM-TECHNICAL-INCIDENTS", index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="OPEN", index=True)
    retry_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    regate_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class PublishingEventRecord(Base):
    __tablename__ = "pub_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    content_asset_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    channel: Mapped[str | None] = mapped_column(String(40), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class PublishingWorkerHeartbeat(Base):
    __tablename__ = "pub_worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="healthy", index=True)
    current_job_id: Mapped[str | None] = mapped_column(String(120), index=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
