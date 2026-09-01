from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class RunStatus(str, enum.Enum):
    started = "started"
    succeeded = "succeeded"
    failed = "failed"


class PublicationStatus(str, enum.Enum):
    queued = "queued"
    publishing = "publishing"
    published = "published"
    failed = "failed"


class IntegrationRun(Base):
    __tablename__ = "integration_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(64), index=True)
    entity_key: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.started)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source", "entity_key", "metric_date", "dimension_hash", name="uq_metric_snapshot"
        ),
        Index("ix_metric_snapshots_source_date", "source", "metric_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(64))
    brand: Mapped[str] = mapped_column(String(64), index=True)
    entity_key: Mapped[str] = mapped_column(String(255), index=True)
    metric_date: Mapped[date] = mapped_column(Date)
    dimension_hash: Mapped[str] = mapped_column(String(64))
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class PublicationJob(Base):
    __tablename__ = "publication_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(index=True, default=uuid.uuid4)
    content_id: Mapped[str] = mapped_column(String(255), index=True)
    website_key: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[PublicationStatus] = mapped_column(
        Enum(PublicationStatus), default=PublicationStatus.queued
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ListingSyncRecord(Base):
    __tablename__ = "listing_sync_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    own_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    remote_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BusinessProfileLocation(Base):
    __tablename__ = "business_profile_locations"
    __table_args__ = (
        UniqueConstraint("account_id", "location_id", name="uq_business_profile_location"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    brand: Mapped[str] = mapped_column(String(64), index=True)
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    location_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255))
    store_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    website_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    phone_numbers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    regular_hours: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    storefront_address: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BusinessProfileReview(Base):
    __tablename__ = "business_profile_reviews"
    __table_args__ = (
        UniqueConstraint("review_name", name="uq_business_profile_review_name"),
        Index("ix_business_profile_reviews_location", "account_id", "location_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    brand: Mapped[str] = mapped_column(String(64), index=True)
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    location_id: Mapped[str] = mapped_column(String(128), index=True)
    review_name: Mapped[str] = mapped_column(String(512))
    review_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewer: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    star_rating: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_reply: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessCardStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"
    published = "published"
    archived = "archived"


class ChecklistInstanceDbStatus(str, enum.Enum):
    open = "open"
    hold = "hold"
    ready_for_approval = "ready_for_approval"
    approved = "approved"
    closed = "closed"


class OperationalProcessRecord(Base):
    __tablename__ = "operational_processes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    process_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    family: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    source_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gate_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    checklist_template_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    checklist_required: Mapped[bool] = mapped_column(Boolean, default=False)
    source_version: Mapped[str] = mapped_column(String(32), default="1.0")
    source_checksum: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ChecklistTemplateRecord(Base):
    __tablename__ = "checklist_templates"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_checklist_template_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    template_id: Mapped[str] = mapped_column(String(128), index=True)
    process_key: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    primary_role: Mapped[str] = mapped_column(String(64), index=True)
    gate_id: Mapped[str] = mapped_column(String(128), index=True)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProcessCardVersionRecord(Base):
    __tablename__ = "process_card_versions"
    __table_args__ = (UniqueConstraint("process_key", "version", name="uq_process_card_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    process_key: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[ProcessCardStatus] = mapped_column(Enum(ProcessCardStatus), default=ProcessCardStatus.draft)
    role: Mapped[str] = mapped_column(String(64), index=True)
    checklist_template_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_checksum: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChecklistInstanceRecord(Base):
    __tablename__ = "checklist_instances"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    template_id: Mapped[str] = mapped_column(String(128), index=True)
    template_version: Mapped[str] = mapped_column(String(32))
    process_key: Mapped[str] = mapped_column(String(64), index=True)
    gate_id: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(64), index=True)
    object_id: Mapped[str] = mapped_column(String(255), index=True)
    object_type: Mapped[str] = mapped_column(String(64), default="BusinessObject")
    status: Mapped[ChecklistInstanceDbStatus] = mapped_column(Enum(ChecklistInstanceDbStatus), default=ChecklistInstanceDbStatus.open)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), default="http_request", index=True)
    actor_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    actor_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(1024), index=True)
    status_code: Mapped[int] = mapped_column(Integer, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
