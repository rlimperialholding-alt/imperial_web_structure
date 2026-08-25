from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
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


class LandOpportunity(Base):
    __tablename__ = "land_opportunities"
    __table_args__ = (
        CheckConstraint(
            "state IN ('DISCOVERED','SOURCE_VERIFIED','CONTACTED','REPLIED','DEAL_VALIDATED',"
            "'PACKAGE_READY','PUBLISH_APPROVED','PARTIAL_PUBLISH','PUBLISHED',"
            "'TAKEDOWN_REQUIRED','WITHDRAWN','CLOSED_NO_DEAL')",
            name="ck_land_opportunity_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_signal_id: Mapped[str] = mapped_column(
        ForeignKey("growth_signals.signal_id", ondelete="RESTRICT"), unique=True, index=True
    )
    source_code: Mapped[str] = mapped_column(String(120), index=True)
    external_key: Mapped[str] = mapped_column(String(255), index=True)
    source_content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_url: Mapped[str] = mapped_column(String(1500))
    title: Mapped[str] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(500), index=True)
    property_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(40), default="DISCOVERED", index=True)
    listing_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    source_status_evidence_ref: Mapped[str | None] = mapped_column(String(1500))
    source_status_changed_by: Mapped[str | None] = mapped_column(String(255))
    source_status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_verified_by: Mapped[str | None] = mapped_column(String(255))
    source_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_verification_note: Mapped[str | None] = mapped_column(Text)
    deal_evidence_ref: Mapped[str | None] = mapped_column(String(1500))
    deal_evidence_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    deal_recorded_by: Mapped[str | None] = mapped_column(String(255))
    deal_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LandAuthorityGrant(Base):
    __tablename__ = "land_authority_grants"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE','REVOKED','EXPIRED')", name="ck_land_authority_status"
        ),
        CheckConstraint("valid_until > valid_from", name="ck_land_authority_time_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    grant_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("land_opportunities.opportunity_id", ondelete="CASCADE"), index=True
    )
    grantor_reference: Mapped[str] = mapped_column(String(500))
    scopes_json: Mapped[str] = mapped_column(Text)
    evidence_ref: Mapped[str] = mapped_column(String(1500))
    evidence_sha256: Mapped[str] = mapped_column(String(64), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    approved_by: Mapped[str] = mapped_column(String(255))
    revoked_by: Mapped[str | None] = mapped_column(String(255))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LandListingPackage(Base):
    __tablename__ = "land_listing_packages"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_id", "version", name="uq_land_listing_package_opportunity_version"
        ),
        CheckConstraint(
            "status IN ('READY','APPROVED','SUPERSEDED','WITHDRAWN')",
            name="ck_land_listing_package_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("land_opportunities.opportunity_id", ondelete="CASCADE"), index=True
    )
    authority_grant_id: Mapped[str] = mapped_column(
        ForeignKey("land_authority_grants.grant_id", ondelete="RESTRICT"), index=True
    )
    plotcheck_case_id: Mapped[str] = mapped_column(
        ForeignKey("plotcheck_cases.case_id", ondelete="RESTRICT"), index=True
    )
    house_id: Mapped[str] = mapped_column(
        ForeignKey("house_catalog_plans.house_id", ondelete="RESTRICT"), index=True
    )
    catalog_version_id: Mapped[str] = mapped_column(
        ForeignKey("house_catalog_versions.catalog_version_id", ondelete="RESTRICT"),
        index=True,
    )
    buildconfig_case_id: Mapped[str] = mapped_column(
        ForeignKey("buildconfig_cases.case_id", ondelete="RESTRICT"), index=True
    )
    buildconfig_version_id: Mapped[str] = mapped_column(
        ForeignKey("buildconfig_versions.version_id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="READY", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    review_note: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LandPublicationAttempt(Base):
    __tablename__ = "land_publication_attempts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_land_publication_idempotency"),
        CheckConstraint("action IN ('PUBLISH','WITHDRAW')", name="ck_land_publication_action"),
        CheckConstraint(
            "status IN ('BLOCKED','QUEUED','EXPORTED','UNKNOWN','SUCCEEDED','FAILED',"
            "'WITHDRAWAL_REQUIRED','WITHDRAWN')",
            name="ck_land_publication_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("land_opportunities.opportunity_id", ondelete="CASCADE"), index=True
    )
    package_id: Mapped[str] = mapped_column(
        ForeignKey("land_listing_packages.package_id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str] = mapped_column(String(20), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), index=True)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    outbox_message_id: Mapped[str | None] = mapped_column(String(120), index=True)
    external_id: Mapped[str | None] = mapped_column(String(500), index=True)
    public_url: Mapped[str | None] = mapped_column(String(1500))
    proof_json: Mapped[str | None] = mapped_column(Text)
    proof_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
