from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class AuthorityReaderRun(Base):
    __tablename__ = "authority_reader_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','completed','partial','failed','blocked','disabled')",
            name="ck_authority_reader_run_status",
        ),
        CheckConstraint(
            "mode IN ('baseline','delta','pilot')", name="ck_authority_reader_run_mode"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_key: Mapped[str] = mapped_column(String(160), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    trigger: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    filter_json: Mapped[str] = mapped_column(Text, default="{}")
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    total_reported: Mapped[int | None] = mapped_column(Integer)
    pages_completed: Mapped[int] = mapped_column(Integer, default=0)
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(120), index=True)
    error_detail_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthorityCheckpoint(Base):
    __tablename__ = "authority_reader_checkpoints"

    source_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    cursor_json: Mapped[str] = mapped_column(Text, default="{}")
    cursor_sha256: Mapped[str] = mapped_column(String(64), default="")
    generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(160), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuthorityRecord(Base):
    __tablename__ = "authority_records"
    __table_args__ = (
        UniqueConstraint("source_key", "external_key_hmac", name="uq_authority_record_external"),
        CheckConstraint(
            "status IN ('active','excluded','quarantined')", name="ck_authority_record_status"
        ),
        CheckConstraint(
            "detail_status IN ('held','pending','current','blocked','failed')",
            name="ck_authority_record_detail_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_key: Mapped[str] = mapped_column(String(160), index=True)
    external_key_hmac: Mapped[str] = mapped_column(String(64), index=True)
    public_process_number: Mapped[str] = mapped_column(String(40), index=True)
    city: Mapped[str] = mapped_column(String(200), index=True)
    topographical_number: Mapped[str | None] = mapped_column(String(100), index=True)
    procedure_type: Mapped[str] = mapped_column(String(500), index=True)
    construction_activity: Mapped[str] = mapped_column(Text)
    submission_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    evidence_url: Mapped[str] = mapped_column(String(1500))
    current_revision_no: Mapped[int] = mapped_column(Integer, default=1)
    current_payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    current_detail_revision_no: Mapped[int] = mapped_column(Integer, default=0)
    current_detail_payload_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    detail_status: Mapped[str] = mapped_column(String(30), default="held", index=True)
    detail_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthorityRecordRevision(Base):
    __tablename__ = "authority_record_revisions"
    __table_args__ = (
        UniqueConstraint("record_id", "payload_sha256", name="uq_authority_revision_payload"),
        UniqueConstraint("record_id", "revision_no", name="uq_authority_revision_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    record_id: Mapped[str] = mapped_column(
        ForeignKey("authority_records.record_id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(String(120), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    normalized_json: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(String(40), default="etdr-v1")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthorityDetailQueue(Base):
    __tablename__ = "authority_detail_queue"
    __table_args__ = (
        UniqueConstraint("record_id", "listing_payload_sha256", name="uq_authority_detail_queue"),
        CheckConstraint(
            "status IN ('held','pending','claimed','completed','blocked','failed')",
            name="ck_authority_detail_queue_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[str] = mapped_column(
        ForeignKey("authority_records.record_id", ondelete="CASCADE"), index=True
    )
    source_revision_id: Mapped[str] = mapped_column(String(120), index=True)
    listing_payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="held", index=True)
    reason_code: Mapped[str] = mapped_column(String(120), default="detail_policy_gate")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(120), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuthorityDetailRevision(Base):
    __tablename__ = "authority_detail_revisions"
    __table_args__ = (
        UniqueConstraint("record_id", "payload_sha256", name="uq_authority_detail_payload"),
        UniqueConstraint("record_id", "revision_no", name="uq_authority_detail_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    detail_revision_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    record_id: Mapped[str] = mapped_column(
        ForeignKey("authority_records.record_id", ondelete="CASCADE"), index=True
    )
    source_revision_id: Mapped[str] = mapped_column(String(120), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    normalized_json: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(String(40), default="etdr-detail-v1")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthorityEnrichmentQueue(Base):
    __tablename__ = "authority_enrichment_queue"
    __table_args__ = (
        UniqueConstraint("record_id", "payload_sha256", name="uq_authority_enrichment_payload"),
        CheckConstraint(
            "status IN ('held','pending','completed','ambiguous','blocked','failed')",
            name="ck_authority_enrichment_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[str] = mapped_column(
        ForeignKey("authority_records.record_id", ondelete="CASCADE"), index=True
    )
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="held", index=True)
    reason_code: Mapped[str] = mapped_column(String(120), default="policy_gate")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuthoritySignalOutbox(Base):
    __tablename__ = "authority_signal_outbox"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_authority_signal_outbox_key"),
        CheckConstraint(
            "status IN ('held','pending','claimed','delivered','blocked','dead_letter')",
            name="ck_authority_signal_outbox_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), index=True)
    record_id: Mapped[str] = mapped_column(
        ForeignKey("authority_records.record_id", ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[str] = mapped_column(String(120), index=True)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="held", index=True)
    reason_code: Mapped[str] = mapped_column(String(120), default="manual_promotion_required")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(120))
    delivery_ref: Mapped[str | None] = mapped_column(String(120), index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
