from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as DateValue
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "cc_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="operator")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    itep_subject_id: Mapped[str | None] = mapped_column(String(140), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModuleRegistry(Base):
    __tablename__ = "cc_modules"
    id: Mapped[int] = mapped_column(primary_key=True)
    module_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(50), default="0.0.0")
    owner: Mapped[str | None] = mapped_column(String(255))
    criticality: Mapped[str] = mapped_column(String(30), default="medium")
    lifecycle_status: Mapped[str] = mapped_column(String(30), default="registered")
    integration_status: Mapped[str] = mapped_column(String(30), default="not_connected")
    api_base_url: Mapped[str | None] = mapped_column(String(500))
    health_url: Mapped[str | None] = mapped_column(String(500))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_integration_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_integration_test_status: Mapped[str | None] = mapped_column(String(30))
    drive_folder_id: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ModuleBusinessRecord(Base):
    """Canonical, user-managed business object available in every module."""

    __tablename__ = "cc_module_business_records"
    __table_args__ = (
        UniqueConstraint("module_key", "record_id", name="uq_cc_module_business_record"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    module_key: Mapped[str] = mapped_column(String(100), index=True)
    record_type: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    customer_reference: Mapped[str | None] = mapped_column(String(255), index=True)
    assignee: Mapped[str | None] = mapped_column(String(255), index=True)
    priority: Mapped[str] = mapped_column(String(30), default="normal", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    amount_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    updated_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    comments: Mapped[list[ModuleBusinessComment]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[ModuleBusinessApproval]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )


class ModuleBusinessComment(Base):
    __tablename__ = "cc_module_business_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    record_id_fk: Mapped[int] = mapped_column(
        ForeignKey("cc_module_business_records.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    record: Mapped[ModuleBusinessRecord] = relationship(back_populates="comments")


class ModuleBusinessApproval(Base):
    __tablename__ = "cc_module_business_approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    record_id_fk: Mapped[int] = mapped_column(
        ForeignKey("cc_module_business_records.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(100), default="business_approval")
    decision: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    note: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(255))
    decided_by: Mapped[str | None] = mapped_column(String(255))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record: Mapped[ModuleBusinessRecord] = relationship(back_populates="approvals")


class ProjectRegistry(Base):
    __tablename__ = "cc_projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    customer_name: Mapped[str | None] = mapped_column(String(255))
    project_type: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="active")
    risk_level: Mapped[str] = mapped_column(String(30), default="green")
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    financial_impact_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    deadline_impact_days: Mapped[int] = mapped_column(Integer, default=0)
    responsible: Mapped[str | None] = mapped_column(String(255))
    next_action: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EventRecord(Base):
    __tablename__ = "cc_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    source_module: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    object_type: Mapped[str | None] = mapped_column(String(100))
    object_id: Mapped[str | None] = mapped_column(String(150))
    severity: Mapped[str] = mapped_column(String(30), default="info")
    status: Mapped[str] = mapped_column(String(30), default="open")
    financial_impact_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    deadline_impact_days: Mapped[int] = mapped_column(Integer, default=0)
    responsible: Mapped[str | None] = mapped_column(String(255))
    next_action: Mapped[str | None] = mapped_column(Text)
    executive_relevance: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_url: Mapped[str | None] = mapped_column(String(1000))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(255))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectObjectState(Base):
    __tablename__ = "cc_project_object_states"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "source_module", "object_type", "object_id", name="uq_cc_object_state"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    source_module: Mapped[str] = mapped_column(String(100), index=True)
    object_type: Mapped[str] = mapped_column(String(100))
    object_id: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(50))
    summary: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    last_event_id: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TaskRecord(Base):
    __tablename__ = "cc_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    source_event_id: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    assignee: Mapped[str | None] = mapped_column(String(255))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[str] = mapped_column(String(30), default="normal")
    status: Mapped[str] = mapped_column(String(30), default="open")
    executive_relevance: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CalendarEntry(Base):
    """A project schedule item with an auditable, role-owned lifecycle."""

    __tablename__ = "cc_calendar_entries"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_cc_calendar_entry_time_order"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    entry_type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    assignee: Mapped[str | None] = mapped_column(String(255), index=True)
    participants_json: Mapped[str] = mapped_column(Text, default="[]")
    location: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="planned", index=True)
    priority: Mapped[str] = mapped_column(String(30), default="normal", index=True)
    source_module: Mapped[str] = mapped_column(String(100), default="smart-calendar")
    source_object_id: Mapped[str | None] = mapped_column(String(160), index=True)
    linked_task_id: Mapped[str | None] = mapped_column(String(120), index=True)
    contractual_deadline: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    capacity_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    conflict_override_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(255))
    updated_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CalendarDependency(Base):
    __tablename__ = "cc_calendar_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "predecessor_entry_id",
            "successor_entry_id",
            name="uq_cc_calendar_dependency_pair",
        ),
        CheckConstraint(
            "predecessor_entry_id <> successor_entry_id",
            name="ck_cc_calendar_dependency_distinct",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    dependency_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    predecessor_entry_id: Mapped[str] = mapped_column(
        ForeignKey("cc_calendar_entries.entry_id", ondelete="CASCADE"), index=True
    )
    successor_entry_id: Mapped[str] = mapped_column(
        ForeignKey("cc_calendar_entries.entry_id", ondelete="CASCADE"), index=True
    )
    dependency_type: Mapped[str] = mapped_column(String(30), default="finish_to_start")
    lag_days: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CalendarChangeRequest(Base):
    __tablename__ = "cc_calendar_change_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("cc_calendar_entries.entry_id", ondelete="CASCADE"), index=True
    )
    requested_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    impact_summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(255))
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decision_note: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BookingExperienceVersion(Base):
    """Brand-owned public booking presentation bound to the shared booking engine."""

    __tablename__ = "cc_booking_experiences"
    __table_args__ = (
        UniqueConstraint("brand_id", "version", name="uq_cc_booking_experience_brand_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    experience_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[str] = mapped_column(String(50))
    display_name: Mapped[str] = mapped_column(String(255))
    cta_label: Mapped[str] = mapped_column(String(255))
    trust_copy: Mapped[str] = mapped_column(Text)
    confirmation_copy: Mapped[str] = mapped_column(Text)
    theme_key: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    policy_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class BookingSlot(Base):
    __tablename__ = "cc_booking_slots"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_cc_booking_slot_time_order"),
        UniqueConstraint(
            "calendar_resource_id",
            "starts_at",
            "ends_at",
            name="uq_cc_booking_slot_resource_window",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    slot_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    experience_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    booking_type: Mapped[str] = mapped_column(String(40), index=True)
    calendar_resource_id: Mapped[str] = mapped_column(String(160), index=True)
    advisor_email: Mapped[str] = mapped_column(String(255), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    location: Mapped[str | None] = mapped_column(String(500))
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="available", index=True)
    held_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class BookingRecord(Base):
    __tablename__ = "cc_booking_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    slot_id: Mapped[str] = mapped_column(
        ForeignKey("cc_booking_slots.slot_id", ondelete="RESTRICT"), index=True
    )
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    lead_id: Mapped[str | None] = mapped_column(String(120), index=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    booking_type: Mapped[str] = mapped_column(String(40), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), index=True)
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    customer_phone: Mapped[str] = mapped_column(String(80))
    project_description: Mapped[str] = mapped_column(Text)
    plot_status: Mapped[str] = mapped_column(String(80))
    planned_start: Mapped[str] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str | None] = mapped_column(String(120))
    street_address: Mapped[str | None] = mapped_column(String(500))
    access_notes: Mapped[str | None] = mapped_column(Text)
    document_url: Mapped[str | None] = mapped_column(String(1000))
    consent_version_id: Mapped[str] = mapped_column(String(120))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="calendar_locked", index=True)
    external_sync_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    calendar_entry_id: Mapped[str | None] = mapped_column(String(120), index=True)
    calendar_event_id: Mapped[str | None] = mapped_column(String(255), index=True)
    meeting_link: Mapped[str | None] = mapped_column(String(1000))
    cancellation_token: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    attribution_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ReservationOfferVersion(Base):
    __tablename__ = "cc_reservation_offer_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_version_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    public_name: Mapped[str] = mapped_column(String(255))
    cta_label: Mapped[str] = mapped_column(String(255))
    reservation_amount_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    target_start_months_min: Mapped[int] = mapped_column(Integer, default=6)
    target_start_months_max: Mapped[int] = mapped_column(Integer, default=12)
    price_lock_months: Mapped[int] = mapped_column(Integer, default=12)
    price_snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    terms_version_id: Mapped[str] = mapped_column(String(120), index=True)
    technical_scope_version_id: Mapped[str] = mapped_column(String(120), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    public_summary: Mapped[str] = mapped_column(Text)
    exclusions_summary: Mapped[str] = mapped_column(Text)
    refund_rule: Mapped[str] = mapped_column(Text)
    transfer_rule: Mapped[str] = mapped_column(Text)
    intent_declaration_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    intent_valid_days: Mapped[int] = mapped_column(Integer, default=30)
    intent_public_summary: Mapped[str] = mapped_column(Text, default="")
    legal_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    finance_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    pricing_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ReservationRecord(Base):
    __tablename__ = "cc_reservation_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    lead_id: Mapped[str | None] = mapped_column(String(120), index=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    offer_version_id: Mapped[str] = mapped_column(
        ForeignKey("cc_reservation_offer_versions.offer_version_id", ondelete="RESTRICT"),
        index=True,
    )
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    house_plan_id: Mapped[str] = mapped_column(String(120), index=True)
    house_config_id: Mapped[str] = mapped_column(String(120), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), index=True)
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    billing_name: Mapped[str] = mapped_column(String(255))
    billing_address: Mapped[str] = mapped_column(String(500))
    tax_number: Mapped[str | None] = mapped_column(String(80))
    amount_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    price_snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    terms_version_id: Mapped[str] = mapped_column(String(120), index=True)
    technical_scope_version_id: Mapped[str] = mapped_column(String(120), index=True)
    terms_accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="payment_pending", index=True)
    price_lock_status: Mapped[str] = mapped_column(String(40), default="inactive", index=True)
    price_lock_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    payment_id: Mapped[str | None] = mapped_column(String(120), index=True)
    invoice_id: Mapped[str | None] = mapped_column(String(120), index=True)
    contract_id: Mapped[str | None] = mapped_column(String(120), index=True)
    next_action: Mapped[str] = mapped_column(Text)
    attribution_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ReservationPaymentRecord(Base):
    __tablename__ = "cc_reservation_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    reservation_id: Mapped[str] = mapped_column(
        ForeignKey("cc_reservation_records.reservation_id", ondelete="RESTRICT"), index=True
    )
    provider: Mapped[str] = mapped_column(String(80))
    provider_reference: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    amount_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(40), index=True)
    evidence_url: Mapped[str | None] = mapped_column(String(1000))
    raw_result_json: Mapped[str] = mapped_column(Text, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SalesOpportunity(Base):
    """Customer-specific commercial pipeline object backed by canonical CRM references."""

    __tablename__ = "sales_opportunities"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('new','qualified','discovery','proposal','negotiation',"
            "'contracting','won','lost')",
            name="ck_sales_opportunity_stage",
        ),
        CheckConstraint(
            "probability_percent >= 0 AND probability_percent <= 100",
            name="ck_sales_opportunity_probability",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    lead_id: Mapped[str | None] = mapped_column(String(120), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(120), index=True)
    crm_record_id: Mapped[str | None] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), index=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), index=True)
    owner_email: Mapped[str] = mapped_column(String(255), index=True)
    stage: Mapped[str] = mapped_column(String(30), default="new", index=True)
    estimated_value_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    probability_percent: Mapped[int] = mapped_column(Integer, default=10)
    expected_close_date: Mapped[DateValue | None] = mapped_column(Date, index=True)
    needs_summary: Mapped[str] = mapped_column(Text)
    budget_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    decision_process: Mapped[str] = mapped_column(Text)
    next_action: Mapped[str] = mapped_column(Text)
    loss_reason: Mapped[str | None] = mapped_column(Text)
    competitor: Mapped[str | None] = mapped_column(String(255))
    accepted_proposal_version_id: Mapped[str | None] = mapped_column(String(120), index=True)
    contract_id: Mapped[str | None] = mapped_column(String(120), index=True)
    delivery_project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(255))
    updated_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SalesProposalVersion(Base):
    """Immutable-after-submission customer proposal version with independent gates."""

    __tablename__ = "sales_proposal_versions"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "version", name="uq_sales_proposal_version"),
        CheckConstraint(
            "status IN ('draft','internal_review','rejected','approved','sent',"
            "'accepted','customer_rejected','expired','superseded')",
            name="ck_sales_proposal_status",
        ),
        CheckConstraint("vat_rate >= 0 AND vat_rate <= 100", name="ck_sales_proposal_vat"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_version_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("sales_opportunities.opportunity_id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="HUF")
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("27"))
    cost_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    sale_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    sale_gross: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    margin_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    margin_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    price_snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    terms_version_id: Mapped[str] = mapped_column(String(120), index=True)
    technical_scope_version_id: Mapped[str] = mapped_column(String(120), index=True)
    scope_summary: Mapped[str] = mapped_column(Text)
    exclusions: Mapped[str] = mapped_column(Text)
    payment_terms: Mapped[str] = mapped_column(Text)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    technical_approved_by: Mapped[str | None] = mapped_column(String(255))
    technical_approval_note: Mapped[str | None] = mapped_column(Text)
    technical_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finance_approved_by: Mapped[str | None] = mapped_column(String(255))
    finance_approval_note: Mapped[str | None] = mapped_column(Text)
    finance_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legal_approved_by: Mapped[str | None] = mapped_column(String(255))
    legal_approval_note: Mapped[str | None] = mapped_column(Text)
    legal_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    sent_by: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_evidence_url: Mapped[str | None] = mapped_column(String(1000))
    customer_decision_reference: Mapped[str | None] = mapped_column(String(255))
    customer_decision_note: Mapped[str | None] = mapped_column(Text)
    customer_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IntentDeclarationRecord(Base):
    """A non-payment Prefab intent, version-bound and contract-preparatory only."""

    __tablename__ = "cc_intent_declarations"
    id: Mapped[int] = mapped_column(primary_key=True)
    intent_declaration_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    lead_id: Mapped[str | None] = mapped_column(String(120), index=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    offer_version_id: Mapped[str] = mapped_column(
        ForeignKey("cc_reservation_offer_versions.offer_version_id", ondelete="RESTRICT"),
        index=True,
    )
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    house_plan_id: Mapped[str] = mapped_column(String(120), index=True)
    house_config_id: Mapped[str] = mapped_column(String(120), index=True)
    customer_name: Mapped[str] = mapped_column(String(255), index=True)
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    customer_phone: Mapped[str] = mapped_column(String(80))
    target_start_window: Mapped[str] = mapped_column(String(120))
    project_scope: Mapped[str] = mapped_column(Text)
    plot_status: Mapped[str] = mapped_column(String(120))
    price_snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    terms_version_id: Mapped[str] = mapped_column(String(120), index=True)
    technical_scope_version_id: Mapped[str] = mapped_column(String(120), index=True)
    consent_version_id: Mapped[str] = mapped_column(String(120))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(40), default="submitted", index=True)
    delivery_evidence_url: Mapped[str | None] = mapped_column(String(1000))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    contract_id: Mapped[str | None] = mapped_column(String(120), index=True)
    cancellation_token: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    next_action: Mapped[str] = mapped_column(Text)
    attribution_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CustomerPortalAccess(Base):
    """Explicit customer-to-project visibility grant used by MyImperial."""

    __tablename__ = "cc_customer_portal_access"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "customer_email", name="uq_cc_customer_portal_project_email"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    access_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    contact_name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(80), index=True)
    source_id: Mapped[str] = mapped_column(String(120), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CustomerPortalUpdate(Base):
    """A deliberately published, customer-visible project progress update."""

    __tablename__ = "cc_customer_portal_updates"
    __table_args__ = (
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_customer_portal_update_progress",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    update_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    requires_acknowledgement: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    published_by: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class CustomerPortalUpdateAcknowledgement(Base):
    __tablename__ = "cc_customer_portal_update_acknowledgements"
    __table_args__ = (
        UniqueConstraint(
            "update_id_fk",
            "customer_email",
            name="uq_customer_portal_update_ack_email",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    acknowledgement_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    update_id_fk: Mapped[int] = mapped_column(
        ForeignKey("cc_customer_portal_updates.id", ondelete="CASCADE"), index=True
    )
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustomerDecisionRequest(Base):
    """An explicit customer decision gate; never doubles as an issue channel."""

    __tablename__ = "cc_customer_decision_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open','responded','cancelled','expired')",
            name="ck_customer_decision_request_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    options_json: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    source_module: Mapped[str | None] = mapped_column(String(100), index=True)
    source_object_id: Mapped[str | None] = mapped_column(String(160), index=True)
    source_version: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CustomerDecisionResponse(Base):
    __tablename__ = "cc_customer_decision_responses"
    __table_args__ = (
        UniqueConstraint(
            "decision_id_fk",
            "customer_email",
            name="uq_customer_decision_response_email",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    decision_id_fk: Mapped[int] = mapped_column(
        ForeignKey("cc_customer_decision_requests.id", ondelete="CASCADE"), index=True
    )
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    selected_option: Mapped[str] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(Text)
    responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectFinancePlan(Base):
    """Versioned project budget, margin and forecast baseline."""

    __tablename__ = "finance_project_plans"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_finance_project_plan_version"),
        CheckConstraint(
            "status IN ('draft','review','finance_approved','approved','superseded','rejected')",
            name="ck_finance_project_plan_status",
        ),
        CheckConstraint(
            "target_margin_percent >= 0 AND target_margin_percent <= 100",
            name="ck_finance_plan_target_margin",
        ),
        Index(
            "uq_finance_project_single_open_plan",
            "project_id",
            unique=True,
            postgresql_where=text("status IN ('draft','review','finance_approved')"),
            sqlite_where=text("status IN ('draft','review','finance_approved')"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="HUF")
    contract_revenue_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    approved_change_revenue_net: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0")
    )
    contingency_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    target_margin_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    forecast_note: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[str | None] = mapped_column(String(255))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finance_approved_by: Mapped[str | None] = mapped_column(String(255))
    finance_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leadership_approved_by: Mapped[str | None] = mapped_column(String(255))
    leadership_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    margin_exception_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    budget_lines: Mapped[list[ProjectFinanceBudgetLine]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    cashflow_lines: Mapped[list[ProjectFinanceCashflowLine]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class ProjectFinanceBudgetLine(Base):
    __tablename__ = "finance_project_budget_lines"
    __table_args__ = (
        UniqueConstraint("plan_id_fk", "cost_code", name="uq_finance_plan_cost_code"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    plan_id_fk: Mapped[int] = mapped_column(
        ForeignKey("finance_project_plans.id", ondelete="CASCADE"), index=True
    )
    cost_code: Mapped[str] = mapped_column(String(100), index=True)
    category: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(String(500))
    budget_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    committed_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    actual_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    estimate_to_complete_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    source_type: Mapped[str | None] = mapped_column(String(80))
    source_id: Mapped[str | None] = mapped_column(String(160), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    plan: Mapped[ProjectFinancePlan] = relationship(back_populates="budget_lines")


class ProjectFinanceCashflowLine(Base):
    __tablename__ = "finance_project_cashflow_lines"
    __table_args__ = (
        CheckConstraint("direction IN ('inflow','outflow')", name="ck_finance_cashflow_direction"),
        CheckConstraint(
            "status IN ('forecast','committed','actual')", name="ck_finance_cashflow_status"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    flow_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    plan_id_fk: Mapped[int] = mapped_column(
        ForeignKey("finance_project_plans.id", ondelete="CASCADE"), index=True
    )
    period_date: Mapped[DateValue] = mapped_column(Date, index=True)
    direction: Mapped[str] = mapped_column(String(20), index=True)
    category: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(String(500))
    amount_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(30), default="forecast", index=True)
    source_type: Mapped[str | None] = mapped_column(String(80))
    source_id: Mapped[str | None] = mapped_column(String(160), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    plan: Mapped[ProjectFinancePlan] = relationship(back_populates="cashflow_lines")


class ChangeControlCase(Base):
    __tablename__ = "change_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','internal_review','internal_rejected','customer_review','customer_rejected','approved','work_authorized','completed','cancelled')",
            name="ck_change_case_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    change_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    responsible: Mapped[str] = mapped_column(String(255), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ChangeControlVersion(Base):
    __tablename__ = "change_versions"
    __table_args__ = (
        UniqueConstraint("change_id_fk", "version", name="uq_change_case_version"),
        CheckConstraint(
            "status IN ('draft','internal_review','internal_rejected','customer_review','customer_accepted','customer_rejected','work_authorized','completed','superseded')",
            name="ck_change_version_status",
        ),
        CheckConstraint("vat_rate >= 0 AND vat_rate <= 100", name="ck_change_vat_rate"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    change_id_fk: Mapped[int] = mapped_column(
        ForeignKey("change_cases.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    reason: Mapped[str] = mapped_column(Text)
    technical_scope: Mapped[str] = mapped_column(Text)
    exclusions: Mapped[str] = mapped_column(Text)
    assumptions: Mapped[str] = mapped_column(Text)
    deadline_impact_days: Mapped[int] = mapped_column(Integer, default=0)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("27"))
    customer_advance_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    cost_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    sale_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    sale_gross: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    margin_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    margin_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    early_direct_cost_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    leadership_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    technical_approved_by: Mapped[str | None] = mapped_column(String(255))
    technical_approval_note: Mapped[str | None] = mapped_column(Text)
    technical_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finance_approved_by: Mapped[str | None] = mapped_column(String(255))
    finance_approval_note: Mapped[str | None] = mapped_column(Text)
    finance_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leadership_approved_by: Mapped[str | None] = mapped_column(String(255))
    leadership_approval_note: Mapped[str | None] = mapped_column(Text)
    leadership_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer_decision_id: Mapped[str | None] = mapped_column(String(120), index=True)
    work_authorized_by: Mapped[str | None] = mapped_column(String(255))
    work_authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendar_entry_id: Mapped[str | None] = mapped_column(String(120), index=True)
    completion_evidence_url: Mapped[str | None] = mapped_column(String(1000))
    completed_by: Mapped[str | None] = mapped_column(String(255))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ChangeControlLine(Base):
    __tablename__ = "change_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_change_line_quantity"),
        CheckConstraint(
            "unit_cost_net >= 0 AND unit_sale_net >= 0",
            name="ck_change_line_nonnegative_prices",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    version_id_fk: Mapped[int] = mapped_column(
        ForeignKey("change_versions.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(40))
    unit_cost_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    unit_sale_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total_cost_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total_sale_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    early_direct_cost: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CareCase(Base):
    __tablename__ = "care_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted','triaged','in_progress','waiting_customer','resolved','closed','rejected')",
            name="ck_care_case_status",
        ),
        CheckConstraint(
            "severity IN ('low','medium','high','urgent')",
            name="ck_care_case_severity",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    reporter_name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(60), index=True)
    severity: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(500))
    preferred_contact: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="submitted", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(255), index=True)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    customer_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_channel: Mapped[str] = mapped_column(String(50), default="imperial-care")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    messages: Mapped[list[CareMessage]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    evidence: Mapped[list[CareEvidence]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class CareMessage(Base):
    __tablename__ = "care_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    case_id_fk: Mapped[int] = mapped_column(
        ForeignKey("care_cases.id", ondelete="CASCADE"), index=True
    )
    author_email: Mapped[str] = mapped_column(String(255), index=True)
    author_role: Mapped[str] = mapped_column(String(50))
    body: Mapped[str] = mapped_column(Text)
    customer_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[CareCase] = relationship(back_populates="messages")


class CareEvidence(Base):
    __tablename__ = "care_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    case_id_fk: Mapped[int] = mapped_column(
        ForeignKey("care_cases.id", ondelete="CASCADE"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(1000))
    caption: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[CareCase] = relationship(back_populates="evidence")


class CommunicationThread(Base):
    __tablename__ = "cc_communication_threads"
    thread_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), index=True)
    thread_type: Mapped[str] = mapped_column(String(30), index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    task_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("cc_users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, index=True
    )


class CommunicationParticipant(Base):
    __tablename__ = "cc_communication_participants"
    __table_args__ = (
        UniqueConstraint("thread_id", "user_id", name="uq_cc_communication_participant"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("cc_communication_threads.thread_id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("cc_users.id", ondelete="CASCADE"), index=True)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    muted: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CommunicationMessage(Base):
    __tablename__ = "cc_communication_messages"
    message_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("cc_communication_threads.thread_id", ondelete="CASCADE"), index=True
    )
    sender_user_id: Mapped[int] = mapped_column(
        ForeignKey("cc_users.id", ondelete="RESTRICT"), index=True
    )
    body: Mapped[str] = mapped_column(Text)
    reply_to_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("cc_communication_messages.message_id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class InternalNotification(Base):
    __tablename__ = "cc_internal_notifications"
    notification_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cc_users.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str | None] = mapped_column(
        ForeignKey("cc_communication_threads.thread_id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)
    target_url: Mapped[str] = mapped_column(String(1000))
    actor_email: Mapped[str | None] = mapped_column(String(255))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class OutboxMessage(Base):
    __tablename__ = "cc_outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_event_id: Mapped[str | None] = mapped_column(String(120))
    destination_module: Mapped[str] = mapped_column(String(100), index=True)
    endpoint: Mapped[str | None] = mapped_column(String(500))
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    delivery_mode: Mapped[str | None] = mapped_column(String(30), index=True)
    delivery_receipt_json: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ModuleInboxDelivery(Base):
    """Immutable receipt proving that an internal module accepted an outbox message."""

    __tablename__ = "cc_module_inbox"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_cc_module_inbox_message"),
        CheckConstraint("status IN ('received','consumed')", name="ck_cc_module_inbox_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("cc_outbox.message_id", ondelete="RESTRICT"), index=True
    )
    source_event_id: Mapped[str | None] = mapped_column(String(120), index=True)
    requested_destination: Mapped[str] = mapped_column(String(100), index=True)
    destination_module: Mapped[str] = mapped_column(String(100), index=True)
    endpoint: Mapped[str | None] = mapped_column(String(500))
    payload_json: Mapped[str] = mapped_column(Text)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    schema_version: Mapped[str] = mapped_column(String(20), default="1.0")
    status: Mapped[str] = mapped_column(String(30), default="received", index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublicationDelivery(Base):
    __tablename__ = "cq_publication_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "publication_proof_id",
            "target",
            "action",
            name="uq_cq_publication_delivery_proof_target_action",
        ),
        CheckConstraint(
            "action IN ('PUBLISH','PAUSE_OR_UNPUBLISH')",
            name="ck_cq_publication_delivery_action",
        ),
        CheckConstraint(
            "status IN ('ready','claimed','retry','delivered','dead_letter')",
            name="ck_cq_publication_delivery_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("cc_outbox.message_id", ondelete="RESTRICT"), index=True
    )
    asset_id: Mapped[str] = mapped_column(String(120), index=True)
    publication_proof_id: Mapped[str] = mapped_column(String(120), index=True)
    publication_bundle_id: Mapped[str | None] = mapped_column(String(120), index=True)
    target: Mapped[str] = mapped_column(String(120), index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="ready", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    claimed_by: Mapped[str | None] = mapped_column(String(160), index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_reference: Mapped[str | None] = mapped_column(String(500), index=True)
    receipt_json: Mapped[str | None] = mapped_column(Text)
    receipt_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProjectFact(Base):
    __tablename__ = "cc_project_facts"
    __table_args__ = (
        UniqueConstraint("project_id", "source_module", "fact_key", name="uq_cc_project_fact"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    source_module: Mapped[str] = mapped_column(String(100), index=True)
    fact_key: Mapped[str] = mapped_column(String(150), index=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ConsistencyIssue(Base):
    __tablename__ = "cc_consistency_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    rule_code: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    details: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(30), default="high")
    status: Mapped[str] = mapped_column(String(30), default="open")
    source_a: Mapped[str | None] = mapped_column(String(100))
    value_a: Mapped[str | None] = mapped_column(Text)
    source_b: Mapped[str | None] = mapped_column(String(100))
    value_b: Mapped[str | None] = mapped_column(Text)
    financial_impact_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    responsible: Mapped[str | None] = mapped_column(String(255))
    assignment_note: Mapped[str | None] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReleaseRecord(Base):
    __tablename__ = "cc_releases"
    __table_args__ = (
        UniqueConstraint("module_key", "version", name="uq_cc_release_module_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    module_key: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    tests_total: Mapped[int] = mapped_column(Integer, default=0)
    tests_passed: Mapped[int] = mapped_column(Integer, default=0)
    migration_tested: Mapped[bool] = mapped_column(Boolean, default=False)
    uat_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    security_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_restore_tested: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    package_sha256: Mapped[str | None] = mapped_column(String(64))
    discovery_request_id: Mapped[str | None] = mapped_column(String(120), index=True)
    reuse_gate_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    packaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    artifacts: Mapped[list[ArtifactRecord]] = relationship(
        back_populates="release", cascade="all, delete-orphan"
    )


class ArtifactRecord(Base):
    __tablename__ = "cc_artifacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    release_id_fk: Mapped[int] = mapped_column(ForeignKey("cc_releases.id", ondelete="CASCADE"))
    artifact_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    artifact_type: Mapped[str] = mapped_column(String(50))
    file_name: Mapped[str] = mapped_column(String(255))
    local_path: Mapped[str | None] = mapped_column(String(1000))
    file_size: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    cloud_status: Mapped[str] = mapped_column(String(30), default="pending")
    drive_file_id: Mapped[str | None] = mapped_column(String(255))
    drive_url: Mapped[str | None] = mapped_column(String(1000))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release: Mapped[ReleaseRecord] = relationship(back_populates="artifacts")


class EnvironmentRecord(Base):
    __tablename__ = "cc_environments"
    id: Mapped[int] = mapped_column(primary_key=True)
    environment_key: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str | None] = mapped_column(String(500))
    database_type: Mapped[str | None] = mapped_column(String(100))
    sso_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    https_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="planned")


class DeploymentRecord(Base):
    __tablename__ = "cc_deployments"
    id: Mapped[int] = mapped_column(primary_key=True)
    deployment_id: Mapped[str] = mapped_column(String(120), unique=True)
    release_id: Mapped[str] = mapped_column(String(120), index=True)
    environment_key: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="planned")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    health_status: Mapped[str | None] = mapped_column(String(30))
    rollback_tested: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)


class PilotRun(Base):
    __tablename__ = "cc_pilot_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    pilot_id: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    scenario: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="planned")
    steps_total: Mapped[int] = mapped_column(Integer, default=0)
    steps_passed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_json: Mapped[str] = mapped_column(Text, default="{}")


class AuditLog(Base):
    __tablename__ = "cc_audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(150))
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TechnicalCase(Base):
    __tablename__ = "cc_technical_cases"
    __table_args__ = (
        UniqueConstraint("module_key", "case_id", name="uq_cc_technical_case_module_id"),
        CheckConstraint(
            "module_key IN ('housebuild-agent','plotcheck','buildconfig','plancheck')",
            name="ck_cc_technical_case_module",
        ),
        CheckConstraint(
            "status IN ('draft','review','approved','rejected')", name="ck_cc_technical_case_status"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    module_key: Mapped[str] = mapped_column(String(50), index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    source_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[str] = mapped_column(String(255))
    assigned_to: Mapped[str | None] = mapped_column(String(255))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TechnicalGate(Base):
    __tablename__ = "cc_technical_gates"
    __table_args__ = (
        UniqueConstraint("case_id", "gate_key", name="uq_cc_technical_gate_case_key"),
        CheckConstraint(
            "status IN ('pending','pass','fail','not_applicable')",
            name="ck_cc_technical_gate_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("cc_technical_cases.case_id", ondelete="CASCADE"), index=True
    )
    gate_key: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(255))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    evidence: Mapped[str | None] = mapped_column(Text)
    checked_by: Mapped[str | None] = mapped_column(String(255))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PlotRuleSet(Base):
    __tablename__ = "plotcheck_rule_sets"
    __table_args__ = (
        UniqueConstraint(
            "municipality", "zoning_code", "version", name="uq_plotcheck_rule_version"
        ),
        CheckConstraint(
            "lifecycle_status IN ('draft','verified','demo','uat','retired')",
            name="ck_plotcheck_rule_lifecycle",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_set_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    municipality: Mapped[str] = mapped_column(String(255), index=True)
    zoning_code: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[str] = mapped_column(String(80))
    lifecycle_status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    source_url: Mapped[str] = mapped_column(String(1200))
    source_document_version: Mapped[str] = mapped_column(String(120))
    source_note: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[DateValue | None] = mapped_column(Date)
    maximum_coverage_percent: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    maximum_floor_area_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    maximum_height_m: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    minimum_green_percent: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    front_setback_m: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    side_setback_m: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    rear_setback_m: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    allowed_uses_json: Mapped[str] = mapped_column(Text, default="[]")
    verified_by: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PlotCheckCase(Base):
    __tablename__ = "plotcheck_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('intake','review','fit','fit_with_conditions','redesign_required','not_suitable')",
            name="ck_plotcheck_case_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    address: Mapped[str] = mapped_column(String(800))
    parcel_number: Mapped[str] = mapped_column(String(120), index=True)
    municipality: Mapped[str] = mapped_column(String(255), index=True)
    zoning_code: Mapped[str] = mapped_column(String(100), index=True)
    rule_set_id: Mapped[str] = mapped_column(
        ForeignKey("plotcheck_rule_sets.rule_set_id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(40), default="intake", index=True)
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    geometry_json: Mapped[str] = mapped_column(Text)
    geometry_crs: Mapped[str] = mapped_column(String(80), default="LOCAL-METRIC")
    geometry_sha256: Mapped[str] = mapped_column(String(64), index=True)
    declared_plot_area_m2: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    proposed_footprint_m2: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    proposed_gross_floor_area_m2: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    proposed_paved_area_m2: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    proposed_height_m: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    proposed_use: Mapped[str] = mapped_column(String(120), default="residential")
    proposed_width_m: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    proposed_depth_m: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    house_id: Mapped[str | None] = mapped_column(String(120), index=True)
    final_assessment_id: Mapped[str | None] = mapped_column(String(140), index=True)
    final_report_document_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    finalized_by: Mapped[str | None] = mapped_column(String(255))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PlotCheckEvidence(Base):
    __tablename__ = "plotcheck_evidence"
    __table_args__ = (
        CheckConstraint(
            "category IN ('land_registry','cadastral_map','hesz','townscape','geodesy','soil','utilities','access','logistics','legal','other')",
            name="ck_plotcheck_evidence_category",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("plotcheck_cases.case_id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(50), index=True)
    source_reference: Mapped[str] = mapped_column(String(1200))
    source_version: Mapped[str] = mapped_column(String(120))
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    legal_blocker: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text)
    verified_by: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlotCheckAction(Base):
    __tablename__ = "plotcheck_actions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open','completed','cancelled')", name="ck_plotcheck_action_status"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("plotcheck_cases.case_id", ondelete="CASCADE"), index=True
    )
    condition: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(255))
    estimated_cost_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    deadline_impact_days: Mapped[int] = mapped_column(Integer)
    design_impact: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    completion_evidence_ref: Mapped[str | None] = mapped_column(String(1200))
    completion_evidence_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    completed_by: Mapped[str | None] = mapped_column(String(255))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlotCheckGate(Base):
    __tablename__ = "plotcheck_gates"
    __table_args__ = (
        UniqueConstraint("case_id", "gate_key", name="uq_plotcheck_gate_case_key"),
        CheckConstraint(
            "gate_key IN ('identity','zoning','geodesy','soil','utilities','access','logistics','engineering')",
            name="ck_plotcheck_gate_key",
        ),
        CheckConstraint(
            "decision IN ('pending','approved','rejected')", name="ck_plotcheck_gate_decision"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("plotcheck_cases.case_id", ondelete="CASCADE"), index=True
    )
    gate_key: Mapped[str] = mapped_column(String(40), index=True)
    decision: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    evidence_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PlotCheckAssessment(Base):
    __tablename__ = "plotcheck_assessments"
    __table_args__ = (
        UniqueConstraint("case_id", "revision", name="uq_plotcheck_assessment_revision"),
        CheckConstraint(
            "outcome IN ('FIT','FIT WITH CONDITIONS','RE-DESIGN REQUIRED','NOT SUITABLE')",
            name="ck_plotcheck_assessment_outcome",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("plotcheck_cases.case_id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(40), index=True)
    confidence_class: Mapped[str] = mapped_column(String(1), default="D")
    metrics_json: Mapped[str] = mapped_column(Text)
    stop_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    conditions_json: Mapped[str] = mapped_column(Text, default="[]")
    snapshot_sha256: Mapped[str] = mapped_column(String(64), index=True)
    preliminary: Mapped[bool] = mapped_column(Boolean, default=True)
    assessed_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseBuildCase(Base):
    __tablename__ = "housebuild_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('intake','variant_selected','review','released','rejected')",
            name="ck_housebuild_case_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    source_house_id: Mapped[str] = mapped_column(String(120), index=True)
    source_catalog_version_id: Mapped[str] = mapped_column(String(140), index=True)
    source_snapshot_json: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    rights_evidence_ref: Mapped[str] = mapped_column(String(1200))
    rights_evidence_sha256: Mapped[str] = mapped_column(String(64), index=True)
    requirement_json: Mapped[str] = mapped_column(Text)
    requirement_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="intake", index=True)
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    selected_variant_id: Mapped[str | None] = mapped_column(String(140), index=True)
    plotcheck_case_id: Mapped[str | None] = mapped_column(String(140), index=True)
    buildconfig_case_id: Mapped[str | None] = mapped_column(String(140), index=True)
    plancheck_case_id: Mapped[str | None] = mapped_column(String(140), index=True)
    final_report_document_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    released_by: Mapped[str | None] = mapped_column(String(255))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseBuildVariant(Base):
    __tablename__ = "housebuild_variants"
    __table_args__ = (
        UniqueConstraint("case_id", "variant_no", name="uq_housebuild_variant_no"),
        CheckConstraint(
            "status IN ('generated','selected','superseded','released','rejected')",
            name="ck_housebuild_variant_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("housebuild_cases.case_id", ondelete="CASCADE"), index=True
    )
    variant_no: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(255))
    strategy: Mapped[str] = mapped_column(Text)
    gross_area_m2: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    net_area_m2: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    footprint_m2: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    width_m: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    depth_m: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    floors: Mapped[int] = mapped_column(Integer)
    bedrooms: Mapped[int] = mapped_column(Integer)
    bathrooms: Mapped[int] = mapped_column(Integer)
    garage_spaces: Mapped[int] = mapped_column(Integer)
    roof_style: Mapped[str] = mapped_column(String(100))
    facade_style: Mapped[str] = mapped_column(String(100))
    orientation: Mapped[str] = mapped_column(String(100))
    accessibility: Mapped[bool] = mapped_column(Boolean, default=False)
    estimated_catalog_price_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    rooms_json: Mapped[str] = mapped_column(Text)
    adjacency_json: Mapped[str] = mapped_column(Text)
    geometry_json: Mapped[str] = mapped_column(Text)
    geometry_signature: Mapped[str] = mapped_column(String(64), index=True)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="generated", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseBuildValidation(Base):
    __tablename__ = "housebuild_validations"
    __table_args__ = (
        UniqueConstraint("variant_id", "validation_key", name="uq_housebuild_variant_validation"),
        CheckConstraint(
            "decision IN ('pass','fail','warning')", name="ck_housebuild_validation_decision"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    validation_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    variant_id: Mapped[str] = mapped_column(
        ForeignKey("housebuild_variants.variant_id", ondelete="CASCADE"), index=True
    )
    validation_key: Mapped[str] = mapped_column(String(80), index=True)
    decision: Mapped[str] = mapped_column(String(20), index=True)
    measured_json: Mapped[str] = mapped_column(Text, default="{}")
    note: Mapped[str] = mapped_column(Text)
    evidence_sha256: Mapped[str] = mapped_column(String(64), index=True)
    checked_by: Mapped[str] = mapped_column(String(255))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseBuildGate(Base):
    __tablename__ = "housebuild_gates"
    __table_args__ = (
        UniqueConstraint("case_id", "gate_key", name="uq_housebuild_gate_case_key"),
        CheckConstraint(
            "gate_key IN ('source_rights','program','deduplication','topology','plotcheck','buildconfig','plancheck','technical')",
            name="ck_housebuild_gate_key",
        ),
        CheckConstraint(
            "decision IN ('pending','approved','rejected')", name="ck_housebuild_gate_decision"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("housebuild_cases.case_id", ondelete="CASCADE"), index=True
    )
    gate_key: Mapped[str] = mapped_column(String(40), index=True)
    decision: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class BuildConfigCase(Base):
    __tablename__ = "buildconfig_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','calculated','review','approved','rejected','superseded')",
            name="ck_buildconfig_case_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    housebuild_case_id: Mapped[str] = mapped_column(String(140), index=True)
    housebuild_variant_id: Mapped[str] = mapped_column(String(140), index=True)
    current_version_id: Mapped[str] = mapped_column(String(140), index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_report_document_id: Mapped[str | None] = mapped_column(String(120), index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class BuildConfigVersion(Base):
    __tablename__ = "buildconfig_versions"
    __table_args__ = (
        UniqueConstraint("case_id", "version_no", name="uq_buildconfig_case_version"),
        CheckConstraint(
            "status IN ('draft','submitted','approved','rejected','superseded')",
            name="ck_buildconfig_version_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("buildconfig_cases.case_id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    brand: Mapped[str] = mapped_column(String(100))
    technology: Mapped[str] = mapped_column(String(120))
    completion_level: Mapped[str] = mapped_column(String(100))
    package_name: Mapped[str] = mapped_column(String(100))
    gross_area_m2: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    currency: Mapped[str] = mapped_column(String(3), default="HUF")
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(8, 5))
    option_json: Mapped[str] = mapped_column(Text, default="[]")
    bom_json: Mapped[str] = mapped_column(Text)
    payment_schedule_json: Mapped[str] = mapped_column(Text)
    capacity_json: Mapped[str] = mapped_column(Text)
    pricing_snapshot_json: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    config_sha256: Mapped[str] = mapped_column(String(64), index=True)
    bom_sha256: Mapped[str] = mapped_column(String(64), index=True)
    net_cost_huf: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    net_price_huf: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    vat_huf: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    gross_price_huf: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    margin_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    duration_days: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(255))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BuildConfigValidation(Base):
    __tablename__ = "buildconfig_validations"
    __table_args__ = (
        UniqueConstraint("version_id", "validation_key", name="uq_buildconfig_version_validation"),
        CheckConstraint(
            "decision IN ('pass','fail','warning')",
            name="ck_buildconfig_validation_decision",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    validation_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("buildconfig_versions.version_id", ondelete="CASCADE"), index=True
    )
    validation_key: Mapped[str] = mapped_column(String(80), index=True)
    decision: Mapped[str] = mapped_column(String(20), index=True)
    measured_json: Mapped[str] = mapped_column(Text, default="{}")
    note: Mapped[str] = mapped_column(Text)
    evidence_sha256: Mapped[str] = mapped_column(String(64), index=True)
    checked_by: Mapped[str] = mapped_column(String(255))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BuildConfigGate(Base):
    __tablename__ = "buildconfig_gates"
    __table_args__ = (
        UniqueConstraint("version_id", "gate_key", name="uq_buildconfig_version_gate"),
        CheckConstraint(
            "gate_key IN ('source','houseplan','compatibility','bom','pricing','margin',"
            "'cashflow','capacity','technical','finance')",
            name="ck_buildconfig_gate_key",
        ),
        CheckConstraint(
            "decision IN ('pending','approved','rejected')",
            name="ck_buildconfig_gate_decision",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("buildconfig_versions.version_id", ondelete="CASCADE"), index=True
    )
    gate_key: Mapped[str] = mapped_column(String(40), index=True)
    decision: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PlanCheckCase(Base):
    __tablename__ = "plancheck_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('intake','review','sendable','not_sendable')",
            name="ck_plancheck_case_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    contact_name: Mapped[str] = mapped_column(String(255))
    contact_email: Mapped[str] = mapped_column(String(320), index=True)
    status: Mapped[str] = mapped_column(String(30), default="intake", index=True)
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    current_revision_id: Mapped[str] = mapped_column(String(140), index=True)
    upload_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    upload_token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    final_report_document_id: Mapped[str | None] = mapped_column(String(120), index=True)
    finalized_by: Mapped[str | None] = mapped_column(String(255))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PlanCheckRevision(Base):
    __tablename__ = "plancheck_revisions"
    __table_args__ = (
        UniqueConstraint("case_id", "version", name="uq_plancheck_revision_case_version"),
        CheckConstraint("confidence_class IN ('A','B','C','D')", name="ck_plancheck_confidence"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("plancheck_cases.case_id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    snapshot_sha256: Mapped[str] = mapped_column(String(64), index=True)
    confidence_class: Mapped[str] = mapped_column(String(1), default="D", index=True)
    missing_items_json: Mapped[str] = mapped_column(Text, default="[]")
    final_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanCheckDocument(Base):
    __tablename__ = "plancheck_documents"
    __table_args__ = (
        UniqueConstraint("revision_id", "document_id", name="uq_plancheck_revision_document"),
        CheckConstraint(
            "validation_status IN ('verified','rejected')", name="ck_plancheck_document_validation"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("plancheck_revisions.revision_id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(100), index=True)
    file_name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(160))
    extension: Mapped[str] = mapped_column(String(20))
    file_size: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(1000))
    page_count: Mapped[int | None] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String(30), default="verified")
    uploaded_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanCheckAssumption(Base):
    __tablename__ = "plancheck_assumptions"
    __table_args__ = (
        CheckConstraint("impact IN ('low','medium','high')", name="ck_plancheck_assumption_impact"),
        CheckConstraint("status IN ('open','resolved')", name="ck_plancheck_assumption_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    assumption_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("plancheck_revisions.revision_id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(String(20), index=True)
    owner: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(255))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanCheckGate(Base):
    __tablename__ = "plancheck_gates"
    __table_args__ = (
        UniqueConstraint("revision_id", "gate_key", name="uq_plancheck_gate_revision_key"),
        CheckConstraint(
            "gate_key IN ('input','engineering','commercial','finance','executive')",
            name="ck_plancheck_gate_key",
        ),
        CheckConstraint(
            "decision IN ('pending','approved','rejected')", name="ck_plancheck_gate_decision"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("plancheck_revisions.revision_id", ondelete="CASCADE"), index=True
    )
    gate_key: Mapped[str] = mapped_column(String(40), index=True)
    decision: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseCatalogPlan(Base):
    __tablename__ = "house_catalog_plans"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_status IN ('active','withdrawn')",
            name="ck_house_catalog_plan_lifecycle",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    house_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    brand: Mapped[str] = mapped_column(String(120), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    current_released_version: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseCatalogVersion(Base):
    __tablename__ = "house_catalog_versions"
    __table_args__ = (
        UniqueConstraint("house_id", "version", name="uq_house_catalog_plan_version"),
        CheckConstraint(
            "status IN ('draft','review','rejected','approved','released',"
            "'superseded','withdrawn')",
            name="ck_house_catalog_version_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    catalog_version_id: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    house_id: Mapped[str] = mapped_column(
        ForeignKey("house_catalog_plans.house_id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    catalog_price_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    gross_area_m2: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    rooms: Mapped[str] = mapped_column(String(120))
    price_status: Mapped[str] = mapped_column(String(80))
    data_quality: Mapped[str] = mapped_column(String(80))
    lifestyles_json: Mapped[str] = mapped_column(Text, default="[]")
    source_type: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str] = mapped_column(String(1000))
    source_verified_at: Mapped[str] = mapped_column(String(120))
    rights_evidence: Mapped[str] = mapped_column(Text)
    technical_summary: Mapped[str] = mapped_column(Text)
    change_summary: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    source_approved_by: Mapped[str | None] = mapped_column(String(255))
    source_approval_note: Mapped[str | None] = mapped_column(Text)
    source_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    technical_approved_by: Mapped[str | None] = mapped_column(String(255))
    technical_approval_note: Mapped[str | None] = mapped_column(Text)
    technical_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commercial_approved_by: Mapped[str | None] = mapped_column(String(255))
    commercial_approval_note: Mapped[str | None] = mapped_column(Text)
    commercial_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[str | None] = mapped_column(String(255))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_by: Mapped[str | None] = mapped_column(String(255))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawal_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HousePlanSource(Base):
    """Versioned source-rights decision used by every executable HousePlan batch."""

    __tablename__ = "houseplan_sources"
    __table_args__ = (
        UniqueConstraint(
            "catalog_version_id", "source_revision", name="uq_houseplan_source_revision"
        ),
        CheckConstraint(
            "legal_basis IN ('owned','licensed','public_domain','customer_authorized','unknown')",
            name="ck_houseplan_source_legal_basis",
        ),
        CheckConstraint(
            "status IN ('draft','rights_review','approved','blocked','expired','revoked')",
            name="ck_houseplan_source_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    catalog_version_id: Mapped[str] = mapped_column(
        ForeignKey("house_catalog_versions.catalog_version_id", ondelete="RESTRICT"),
        index=True,
    )
    source_revision: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    legal_basis: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    licence_scope: Mapped[str] = mapped_column(Text)
    evidence_ref: Mapped[str] = mapped_column(String(1200))
    evidence_sha256: Mapped[str] = mapped_column(String(64), index=True)
    rights_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="rights_review", index=True)
    approved_by_subject: Mapped[str | None] = mapped_column(String(140), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revoked_by_subject: Mapped[str | None] = mapped_column(String(140))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    created_by_subject: Mapped[str] = mapped_column(String(140))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HousePlanBatch(Base):
    __tablename__ = "houseplan_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','completed','partial','failed')",
            name="ck_houseplan_batch_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("houseplan_sources.source_id", ondelete="RESTRICT"), index=True
    )
    source_revision: Mapped[int] = mapped_column(Integer)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    actor_subject: Mapped[str] = mapped_column(String(140), index=True)
    permission_revision: Mapped[str] = mapped_column(String(160))
    pricing_revision: Mapped[str] = mapped_column(String(160))
    ruleset_version: Mapped[str] = mapped_column(String(100))
    batch_hash: Mapped[str] = mapped_column(String(64), index=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    request_json: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    dry_run_token_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HousePlanRecord(Base):
    __tablename__ = "houseplan_records"
    __table_args__ = (
        UniqueConstraint("plan_id", name="uq_houseplan_record_plan_id"),
        UniqueConstraint("batch_id", "row_number", name="uq_houseplan_batch_row"),
        UniqueConstraint("family_id", "version_number", name="uq_houseplan_family_version"),
        UniqueConstraint("geometry_signature", name="uq_houseplan_geometry_signature"),
        CheckConstraint(
            "status IN ('draft','qa_failed','rights_recheck','plancheck_review','approved',"
            "'rejected','catalog_ready','published','archived')",
            name="ck_houseplan_record_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("houseplan_batches.batch_id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    family_id: Mapped[str] = mapped_column(String(140), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    predecessor_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("houseplan_records.plan_id", ondelete="RESTRICT"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("houseplan_sources.source_id", ondelete="RESTRICT"), index=True
    )
    input_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    geometry_signature: Mapped[str] = mapped_column(String(64), index=True)
    normalized_input_json: Mapped[str] = mapped_column(Text)
    geometry_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    near_duplicate_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    near_duplicate_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("houseplan_records.plan_id", ondelete="RESTRICT"), index=True
    )
    housebuild_case_id: Mapped[str | None] = mapped_column(
        ForeignKey("housebuild_cases.case_id", ondelete="RESTRICT"), index=True
    )
    housebuild_variant_id: Mapped[str | None] = mapped_column(
        ForeignKey("housebuild_variants.variant_id", ondelete="RESTRICT"), index=True
    )
    plancheck_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("cc_tasks.task_id", ondelete="RESTRICT"), index=True
    )
    created_by_subject: Mapped[str] = mapped_column(String(140), index=True)
    reviewed_by_subject: Mapped[str | None] = mapped_column(String(140))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HousePlanBatchItem(Base):
    """Immutable row outcome, including failures that intentionally create no plan."""

    __tablename__ = "houseplan_batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_number", name="uq_houseplan_batch_item_row"),
        CheckConstraint(
            "status IN ('created','invalid','duplicate','near_duplicate_blocked')",
            name="ck_houseplan_batch_item_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("houseplan_batches.batch_id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), index=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    geometry_signature: Mapped[str | None] = mapped_column(String(64), index=True)
    plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("houseplan_records.plan_id", ondelete="RESTRICT"), index=True
    )
    duplicate_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("houseplan_records.plan_id", ondelete="RESTRICT"), index=True
    )
    similarity_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    error_code: Mapped[str | None] = mapped_column(String(100), index=True)
    message: Mapped[str | None] = mapped_column(Text)
    input_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseStudioPermissionGrant(Base):
    __tablename__ = "house_studio_permission_grants"
    __table_args__ = (
        UniqueConstraint(
            "subject_id",
            "permission",
            "project_id",
            "effect",
            "revision",
            name="uq_house_studio_permission_revision",
        ),
        CheckConstraint(
            "scope_type IN ('global','project')",
            name="ck_house_studio_permission_scope",
        ),
        CheckConstraint(
            "effect IN ('allow','deny')",
            name="ck_house_studio_permission_effect",
        ),
        CheckConstraint(
            "status IN ('active','revoked','expired')",
            name="ck_house_studio_permission_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    grant_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    subject_id: Mapped[str] = mapped_column(String(140), index=True)
    permission: Mapped[str] = mapped_column(String(100), index=True)
    effect: Mapped[str] = mapped_column(String(10), default="allow", index=True)
    scope_type: Mapped[str] = mapped_column(String(20), index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    revision: Mapped[str] = mapped_column(String(100))
    claim_sequence: Mapped[int] = mapped_column(Integer, index=True)
    claim_issuer: Mapped[str] = mapped_column(String(255))
    claim_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EngineeringCase(Base):
    """Project-level design orchestration without duplicating source-module engines."""

    __tablename__ = "engineering_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planned','in_design','coordination','hold','construction_ready','closed')",
            name="ck_engineering_case_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    engineering_case_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(40), default="planned", index=True)
    lead_designer: Mapped[str] = mapped_column(String(255), index=True)
    project_manager: Mapped[str] = mapped_column(String(255), index=True)
    contract_date: Mapped[DateValue] = mapped_column(Date, index=True)
    consultation_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    absolute_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consultation_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_authority_json: Mapped[str] = mapped_column(Text, default="{}")
    readiness_version: Mapped[int] = mapped_column(Integer, default=0)
    readiness_blockers_json: Mapped[str] = mapped_column(Text, default="[]")
    construction_ready_by: Mapped[str | None] = mapped_column(String(255))
    construction_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EngineeringDeliverable(Base):
    __tablename__ = "engineering_deliverables"
    __table_args__ = (
        UniqueConstraint(
            "engineering_case_id",
            "discipline",
            "deliverable_code",
            name="uq_engineering_deliverable_case_discipline_code",
        ),
        CheckConstraint(
            "status IN ('planned','drafting','review','released','hold','not_required')",
            name="ck_engineering_deliverable_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    deliverable_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    engineering_case_id: Mapped[str] = mapped_column(
        ForeignKey("engineering_cases.engineering_case_id", ondelete="CASCADE"), index=True
    )
    discipline: Mapped[str] = mapped_column(String(80), index=True)
    deliverable_code: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    document_type: Mapped[str] = mapped_column(String(100), index=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="planned", index=True)
    responsible: Mapped[str] = mapped_column(String(255), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    current_released_revision: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EngineeringRevision(Base):
    __tablename__ = "engineering_revisions"
    __table_args__ = (
        UniqueConstraint("deliverable_id", "revision", name="uq_engineering_deliverable_revision"),
        UniqueConstraint(
            "source_document_id", "source_version", name="uq_engineering_source_document_version"
        ),
        CheckConstraint(
            "status IN ('draft','review','rejected','approved','released','superseded','withdrawn')",
            name="ck_engineering_revision_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    deliverable_id: Mapped[str] = mapped_column(
        ForeignKey("engineering_deliverables.deliverable_id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    revision_label: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    source_document_id: Mapped[str] = mapped_column(String(160), index=True)
    source_version: Mapped[str] = mapped_column(String(80))
    source_url: Mapped[str] = mapped_column(String(1000))
    file_name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(120))
    file_size: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    change_summary: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    submitted_by: Mapped[str | None] = mapped_column(String(255))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[str | None] = mapped_column(String(255))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_by: Mapped[str | None] = mapped_column(String(255))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawal_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EngineeringFinding(Base):
    __tablename__ = "engineering_findings"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('low','medium','high','critical')",
            name="ck_engineering_finding_severity",
        ),
        CheckConstraint(
            "status IN ('open','resolution_proposed','resolved','superseded')",
            name="ck_engineering_finding_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("engineering_revisions.revision_id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(30), index=True)
    blocking: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(500))
    responsible: Mapped[str] = mapped_column(String(255), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_module: Mapped[str] = mapped_column(String(100), default="plancheck")
    source_fingerprint: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolution_revision_id: Mapped[str | None] = mapped_column(String(160), index=True)
    resolution_proposed_by: Mapped[str | None] = mapped_column(String(255))
    resolved_by: Mapped[str | None] = mapped_column(String(255))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EngineeringTransmittal(Base):
    __tablename__ = "engineering_transmittals"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('review','information','construction','authority','supersession')",
            name="ck_engineering_transmittal_purpose",
        ),
        CheckConstraint(
            "status IN ('issued','acknowledged','rejected','cancelled')",
            name="ck_engineering_transmittal_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    transmittal_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    engineering_case_id: Mapped[str] = mapped_column(
        ForeignKey("engineering_cases.engineering_case_id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    subject: Mapped[str] = mapped_column(String(255))
    recipient_name: Mapped[str] = mapped_column(String(255))
    recipient_email: Mapped[str] = mapped_column(String(320), index=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="issued", index=True)
    package_sha256: Mapped[str] = mapped_column(String(64), index=True)
    issued_by: Mapped[str] = mapped_column(String(255))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    acknowledged_by: Mapped[str | None] = mapped_column(String(255))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledgement_note: Mapped[str | None] = mapped_column(Text)


class EngineeringTransmittalItem(Base):
    __tablename__ = "engineering_transmittal_items"
    __table_args__ = (
        UniqueConstraint(
            "transmittal_id", "revision_id", name="uq_engineering_transmittal_revision"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    transmittal_item_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    transmittal_id: Mapped[str] = mapped_column(
        ForeignKey("engineering_transmittals.transmittal_id", ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("engineering_revisions.revision_id", ondelete="RESTRICT"), index=True
    )
    revision_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectControlBaseline(Base):
    """Immutable, approved control baseline bound to canonical source versions."""

    __tablename__ = "project_control_baselines"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_project_control_baseline_version"),
        CheckConstraint(
            "status IN ('draft','review','approved','superseded','rejected')",
            name="ck_project_control_baseline_status",
        ),
        CheckConstraint("planned_end >= planned_start", name="ck_project_control_baseline_dates"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    baseline_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    finance_plan_id: Mapped[str] = mapped_column(String(120), index=True)
    scope_document_id: Mapped[str] = mapped_column(String(160), index=True)
    scope_version: Mapped[str] = mapped_column(String(80))
    scope_sha256: Mapped[str] = mapped_column(String(64), index=True)
    planned_start: Mapped[DateValue] = mapped_column(Date, index=True)
    planned_end: Mapped[DateValue] = mapped_column(Date, index=True)
    schedule_snapshot_json: Mapped[str] = mapped_column(Text)
    financial_snapshot_json: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    note: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    submitted_by: Mapped[str | None] = mapped_column(String(255))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    technical_approved_by: Mapped[str | None] = mapped_column(String(255))
    technical_note: Mapped[str | None] = mapped_column(Text)
    technical_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finance_approved_by: Mapped[str | None] = mapped_column(String(255))
    finance_note: Mapped[str | None] = mapped_column(Text)
    finance_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leadership_approved_by: Mapped[str | None] = mapped_column(String(255))
    leadership_note: Mapped[str | None] = mapped_column(Text)
    leadership_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProjectControlForecast(Base):
    """Point-in-time plan/actual/EAC snapshot computed from source authorities."""

    __tablename__ = "project_control_forecasts"
    __table_args__ = (
        UniqueConstraint("baseline_id", "version", name="uq_project_control_forecast_version"),
        CheckConstraint(
            "status IN ('draft','finance_review','leadership_review','approved','superseded','rejected')",
            name="ck_project_control_forecast_status",
        ),
        CheckConstraint(
            "planned_progress_pct >= 0 AND planned_progress_pct <= 100 AND actual_progress_pct >= 0 AND actual_progress_pct <= 100",
            name="ck_project_control_forecast_progress",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    forecast_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    baseline_id: Mapped[str] = mapped_column(
        ForeignKey("project_control_baselines.baseline_id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    as_of_date: Mapped[DateValue] = mapped_column(Date, index=True)
    planned_progress_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    actual_progress_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    schedule_variance_pct: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    forecast_completion_date: Mapped[DateValue] = mapped_column(Date, index=True)
    deadline_variance_days: Mapped[int] = mapped_column(Integer, default=0)
    revenue_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    budget_cost_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    committed_cost_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    actual_cost_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    estimate_to_complete_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    eac_cost_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cost_variance_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    forecast_margin_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    forecast_margin_percent: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    approved_change_revenue_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    approved_change_cost_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    unauthorized_change_count: Mapped[int] = mapped_column(Integer, default=0)
    source_snapshot_json: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    note: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    submitted_by: Mapped[str | None] = mapped_column(String(255))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finance_approved_by: Mapped[str | None] = mapped_column(String(255))
    finance_note: Mapped[str | None] = mapped_column(Text)
    finance_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leadership_approved_by: Mapped[str | None] = mapped_column(String(255))
    leadership_note: Mapped[str | None] = mapped_column(Text)
    leadership_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProjectControlVariance(Base):
    __tablename__ = "project_control_variances"
    __table_args__ = (
        CheckConstraint(
            "category IN ('schedule','progress','cost','margin','change','scope','quality','risk')",
            name="ck_project_control_variance_category",
        ),
        CheckConstraint(
            "severity IN ('low','medium','high','critical')",
            name="ck_project_control_variance_severity",
        ),
        CheckConstraint(
            "status IN ('open','classified','recovery','resolved','accepted')",
            name="ck_project_control_variance_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    variance_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    forecast_id: Mapped[str] = mapped_column(
        ForeignKey("project_control_forecasts.forecast_id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    amount_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    impact_days: Mapped[int] = mapped_column(Integer, default=0)
    impact_percent: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    root_cause: Mapped[str | None] = mapped_column(String(80), index=True)
    source_module: Mapped[str] = mapped_column(String(100))
    source_object_id: Mapped[str] = mapped_column(String(180), index=True)
    recovery_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    classified_by: Mapped[str | None] = mapped_column(String(255))
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(255))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectControlRecoveryAction(Base):
    __tablename__ = "project_control_recovery_actions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open','in_progress','completed','verified','rejected')",
            name="ck_project_control_recovery_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    variance_id: Mapped[str] = mapped_column(
        ForeignKey("project_control_variances.variance_id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    owner: Mapped[str] = mapped_column(String(255), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    target_amount_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    target_days: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    completion_note: Mapped[str | None] = mapped_column(Text)
    evidence_url: Mapped[str | None] = mapped_column(String(1000))
    completed_by: Mapped[str | None] = mapped_column(String(255))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProjectControlWeeklyReport(Base):
    __tablename__ = "project_control_weekly_reports"
    __table_args__ = (
        UniqueConstraint("project_id", "week_ending", name="uq_project_control_weekly_report"),
        CheckConstraint(
            "status IN ('draft','submitted','approved','rejected')",
            name="ck_project_control_weekly_report_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    forecast_id: Mapped[str] = mapped_column(
        ForeignKey("project_control_forecasts.forecast_id", ondelete="RESTRICT"), index=True
    )
    week_ending: Mapped[DateValue] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    report_json: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    management_summary: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    submitted_by: Mapped[str | None] = mapped_column(String(255))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approval_note: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CopySourceRecord(Base):
    __tablename__ = "cq_source_records"
    __table_args__ = (UniqueConstraint("source_key", "version", name="uq_cq_source_key_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(160), index=True)
    source_type: Mapped[str] = mapped_column(String(80), index=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    page_id: Mapped[str | None] = mapped_column(String(120), index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(120), index=True)
    asset_type: Mapped[str | None] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(80))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(30), default="approved", index=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    content_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CopyBriefRecord(Base):
    __tablename__ = "cq_copy_briefs"
    copy_brief_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    asset_type: Mapped[str] = mapped_column(String(80), index=True)
    channel: Mapped[str] = mapped_column(String(80), index=True)
    page_id: Mapped[str | None] = mapped_column(String(120), index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    brief_json: Mapped[str] = mapped_column(Text)
    source_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CampaignStrategyReviewRecord(Base):
    __tablename__ = "cq_strategy_reviews"
    review_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    copy_brief_id: Mapped[str] = mapped_column(
        ForeignKey("cq_copy_briefs.copy_brief_id", ondelete="CASCADE"), unique=True, index=True
    )
    brief_hash: Mapped[str] = mapped_column(String(64), index=True)
    strategist_run_id: Mapped[str] = mapped_column(String(120))
    reviewer_run_id: Mapped[str] = mapped_column(String(120), unique=True)
    reviewer_identity: Mapped[str] = mapped_column(String(160))
    decision: Mapped[str] = mapped_column(String(40), index=True)
    review_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentAssetRecord(Base):
    __tablename__ = "cq_content_assets"
    __table_args__ = (
        CheckConstraint(
            "state NOT IN ('PUBLISHED', 'LIVE_QA', 'QUARANTINED') OR (gate_1_approved = true AND expert_language_approved = true AND expert_marketing_approved = true AND copywriter_approved = true AND four_gate_approved = true AND creative_director_approved = true AND assembly_approved = true AND campaign_package_approved = true AND campaign_package_hash IS NOT NULL AND campaign_artifact_set_hash IS NOT NULL AND release_approved = true AND active_bundle_id IS NOT NULL AND (source_prevalidated = true OR (editorial_approved = true AND owner_approved = true)) AND publication_proof_id IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_cq_published_requires_all_approvals",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    copy_brief_id: Mapped[str] = mapped_column(
        ForeignKey("cq_copy_briefs.copy_brief_id"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    asset_type: Mapped[str] = mapped_column(String(80), index=True)
    channel: Mapped[str] = mapped_column(String(80), index=True)
    state: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    content_version: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_json: Mapped[str] = mapped_column(Text)
    generation_trace_json: Mapped[str] = mapped_column(Text, default="{}")
    gate_1_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    expert_language_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    expert_marketing_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    copywriter_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    four_gate_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    editorial_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    source_prevalidated: Mapped[bool] = mapped_column(Boolean, default=False)
    creative_director_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    assembly_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    campaign_package_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    campaign_package_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    campaign_artifact_set_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    release_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    live_review_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    active_bundle_id: Mapped[str | None] = mapped_column(String(120), index=True)
    latest_run_id: Mapped[str | None] = mapped_column(String(120), index=True)
    publication_proof_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MarketingCampaign(Base):
    __tablename__ = "mkt_campaigns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','review','approved','active','paused','completed','cancelled')",
            name="ck_mkt_campaign_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    objective: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(Text)
    channels_json: Mapped[str] = mapped_column(Text, default="[]")
    budget_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="HUF")
    target_leads: Mapped[int] = mapped_column(Integer, default=0)
    target_cpl_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    start_date: Mapped[DateValue] = mapped_column(Date, index=True)
    end_date: Mapped[DateValue] = mapped_column(Date, index=True)
    utm_source: Mapped[str] = mapped_column(String(120))
    utm_medium: Mapped[str] = mapped_column(String(120))
    utm_campaign: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    landing_page_url: Mapped[str | None] = mapped_column(String(1200))
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    owner_email: Mapped[str] = mapped_column(String(255), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    submitted_by: Mapped[str | None] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MarketingLead(Base):
    __tablename__ = "mkt_leads"
    __table_args__ = (
        CheckConstraint(
            "status IN ('new','scored','marketing_qualified','crm_handoff',"
            "'sales_accepted','sales_rejected','disqualified','converted')",
            name="ck_mkt_lead_status",
        ),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_mkt_lead_score"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(120), index=True)
    source: Mapped[str] = mapped_column(String(120), index=True)
    channel: Mapped[str] = mapped_column(String(80), index=True)
    landing_page_url: Mapped[str | None] = mapped_column(String(1200))
    utm_source: Mapped[str | None] = mapped_column(String(120), index=True)
    utm_medium: Mapped[str | None] = mapped_column(String(120))
    utm_campaign: Mapped[str | None] = mapped_column(String(160), index=True)
    utm_content: Mapped[str | None] = mapped_column(String(160))
    full_name: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(80), index=True)
    company: Mapped[str | None] = mapped_column(String(255), index=True)
    lead_type: Mapped[str] = mapped_column(String(20), default="b2c", index=True)
    project_location: Mapped[str | None] = mapped_column(String(255))
    estimated_budget_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    timeframe_months: Mapped[int | None] = mapped_column(Integer)
    intent_summary: Mapped[str | None] = mapped_column(Text)
    privacy_notice_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_notice_version: Mapped[str] = mapped_column(String(80))
    marketing_consent: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    marketing_consent_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marketing_consent_source: Mapped[str | None] = mapped_column(String(120))
    marketing_consent_evidence: Mapped[str | None] = mapped_column(Text)
    marketing_consent_withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_management_token: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    signal_count: Mapped[int] = mapped_column(Integer, default=1)
    assigned_sales_email: Mapped[str | None] = mapped_column(String(255), index=True)
    qualification_note: Mapped[str | None] = mapped_column(Text)
    crm_record_id: Mapped[str | None] = mapped_column(String(120), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MarketingLeadActivity(Base):
    __tablename__ = "mkt_lead_activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    lead_id: Mapped[str] = mapped_column(String(120), index=True)
    activity_type: Mapped[str] = mapped_column(String(80), index=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    actor: Mapped[str | None] = mapped_column(String(255), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketingCampaignDailyMetric(Base):
    __tablename__ = "mkt_campaign_daily_metrics"
    __table_args__ = (
        UniqueConstraint("source_system", "external_key", name="uq_mkt_metric_source_key"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    metric_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    campaign_id: Mapped[str] = mapped_column(String(120), index=True)
    asset_id: Mapped[str | None] = mapped_column(String(120), index=True)
    metric_date: Mapped[DateValue] = mapped_column(Date, index=True)
    channel: Mapped[str] = mapped_column(String(80), index=True)
    source_system: Mapped[str] = mapped_column(String(100), index=True)
    external_key: Mapped[str] = mapped_column(String(255), index=True)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    landing_sessions: Mapped[int] = mapped_column(Integer, default=0)
    form_starts: Mapped[int] = mapped_column(Integer, default=0)
    form_completes: Mapped[int] = mapped_column(Integer, default=0)
    platform_conversions: Mapped[int] = mapped_column(Integer, default=0)
    spend_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="HUF")
    raw_payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    imported_by: Mapped[str] = mapped_column(String(255))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MarketingOptimizationDecision(Base):
    __tablename__ = "mkt_optimization_decisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','approved','rejected','executed')",
            name="ck_mkt_optimization_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    campaign_id: Mapped[str] = mapped_column(String(120), index=True)
    decision_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    rationale: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text)
    proposed_budget_net: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    proposed_by: Mapped[str] = mapped_column(String(255))
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_by: Mapped[str | None] = mapped_column(String(255))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CopyReviewRun(Base):
    __tablename__ = "cq_review_runs"
    run_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(120), index=True)
    copy_brief_id: Mapped[str] = mapped_column(String(120), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_snapshot_hash: Mapped[str] = mapped_column(String(64))
    source_versions_json: Mapped[str] = mapped_column(Text, default="{}")
    model_versions_json: Mapped[str] = mapped_column(Text, default="{}")
    prompt_versions_json: Mapped[str] = mapped_column(Text, default="{}")
    total_score: Mapped[int] = mapped_column(Integer, default=0)
    final_decision: Mapped[str] = mapped_column(String(40), index=True)
    scorecard_json: Mapped[str] = mapped_column(Text)
    expert_review_json: Mapped[str] = mapped_column(Text)
    expert_review_hash: Mapped[str] = mapped_column(String(64), index=True)
    repair_brief_json: Mapped[str] = mapped_column(Text, default="[]")
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentGateDecision(Base):
    __tablename__ = "cq_gate_decisions"
    __table_args__ = (UniqueConstraint("run_id", "gate_id", name="uq_cq_run_gate"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("cq_review_runs.run_id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[str] = mapped_column(String(120), index=True)
    gate_id: Mapped[str] = mapped_column(String(80))
    agent_id: Mapped[str] = mapped_column(String(80))
    decision: Mapped[str] = mapped_column(String(40), index=True)
    relevant: Mapped[bool] = mapped_column(Boolean, default=True)
    certainty: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    findings_json: Mapped[str] = mapped_column(Text, default="[]")
    source_versions_json: Mapped[str] = mapped_column(Text, default="{}")
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentApprovalRecord(Base):
    __tablename__ = "cq_approvals"
    __table_args__ = (
        UniqueConstraint(
            "asset_id", "content_version", "approval_type", name="uq_cq_asset_version_approval"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(120), index=True)
    content_version: Mapped[int] = mapped_column(Integer)
    approval_type: Mapped[str] = mapped_column(String(40), index=True)
    decision: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreativeProductionRunRecord(Base):
    __tablename__ = "cq_creative_runs"
    __table_args__ = (
        UniqueConstraint("asset_id", "sequence_number", name="uq_cq_creative_asset_sequence"),
    )
    generation_run_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(120), index=True)
    content_version: Mapped[int] = mapped_column(Integer)
    sequence_number: Mapped[int] = mapped_column(Integer)
    producer_identity: Mapped[str] = mapped_column(String(160))
    visual_direction_id: Mapped[str] = mapped_column(String(160))
    platform: Mapped[str] = mapped_column(String(80))
    width_px: Mapped[int] = mapped_column(Integer)
    height_px: Mapped[int] = mapped_column(Integer)
    output_uri: Mapped[str] = mapped_column(String(2000))
    output_sha256: Mapped[str] = mapped_column(String(64), index=True)
    generation_prompt_hash: Mapped[str] = mapped_column(String(64))
    contains_text: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default="DIRECTOR_QA", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentWorkflowReviewRecord(Base):
    __tablename__ = "cq_workflow_reviews"
    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "content_version",
            "stage",
            "reviewer_run_id",
            name="uq_cq_workflow_stage_run",
        ),
    )
    review_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(120), index=True)
    content_version: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(80), index=True)
    reviewer_role: Mapped[str] = mapped_column(String(80))
    reviewer_identity: Mapped[str] = mapped_column(String(160))
    reviewer_run_id: Mapped[str | None] = mapped_column(String(120))
    decision: Mapped[str] = mapped_column(String(40), index=True)
    artifact_hash: Mapped[str] = mapped_column(String(64), index=True)
    review_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PublicationBundleRecord(Base):
    __tablename__ = "cq_publication_bundles"
    bundle_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(120), index=True)
    content_version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    visual_generation_run_id: Mapped[str] = mapped_column(
        ForeignKey("cq_creative_runs.generation_run_id"), index=True
    )
    assembly_run_id: Mapped[str] = mapped_column(String(120), unique=True)
    assembler_identity: Mapped[str] = mapped_column(String(160))
    bundle_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    exports_json: Mapped[str] = mapped_column(Text)
    pairing_rationale: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="RELEASE_QA", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoldenCopySample(Base):
    __tablename__ = "cq_golden_copy_samples"
    id: Mapped[int] = mapped_column(primary_key=True)
    sample_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    asset_type: Mapped[str] = mapped_column(String(80), index=True)
    content_json: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[str] = mapped_column(String(255))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentPerformanceMetric(Base):
    __tablename__ = "cq_performance_metrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    metric_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    asset_id: Mapped[str] = mapped_column(String(120), index=True)
    metric_type: Mapped[str] = mapped_column(String(50), index=True)
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    text_value: Mapped[str | None] = mapped_column(Text)
    occurred_on: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_system: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportDataSource(Base):
    __tablename__ = "ic_data_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(50), index=True)
    domain_scope: Mapped[str] = mapped_column(String(255), default="enterprise")
    connector_reference: Mapped[str | None] = mapped_column(String(1000))
    query_or_path: Mapped[str | None] = mapped_column(Text)
    sync_mode: Mapped[str] = mapped_column(String(30), default="manual")
    owner: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ImportJob(Base):
    __tablename__ = "ic_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="created", index=True)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    domain_hint: Mapped[str | None] = mapped_column(String(100))
    items_total: Mapped[int] = mapped_column(Integer, default=0)
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    records_extracted: Mapped[int] = mapped_column(Integer, default=0)
    records_review_required: Mapped[int] = mapped_column(Integer, default=0)
    records_committed: Mapped[int] = mapped_column(Integer, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ImportItem(Base):
    __tablename__ = "ic_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    file_name: Mapped[str | None] = mapped_column(String(500))
    mime_type: Mapped[str | None] = mapped_column(String(150))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="received")
    domain_hint: Mapped[str | None] = mapped_column(String(100))
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StagedEnterpriseRecord(Base):
    __tablename__ = "ic_staged_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    staged_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    item_id: Mapped[str | None] = mapped_column(String(120), index=True)
    domain: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100), index=True)
    external_key: Mapped[str | None] = mapped_column(String(255), index=True)
    canonical_name: Mapped[str | None] = mapped_column(String(500), index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    target_module: Mapped[str] = mapped_column(String(100), default="control_center")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    review_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    duplicate_status: Mapped[str] = mapped_column(String(30), default="unknown")
    duplicate_record_id: Mapped[str | None] = mapped_column(String(120))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    normalized_json: Mapped[str] = mapped_column(Text, default="{}")
    provenance_json: Mapped[str] = mapped_column(Text, default="{}")
    validation_json: Mapped[str] = mapped_column(Text, default="{}")
    committed_record_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EnterpriseCanonicalRecord(Base):
    __tablename__ = "ic_canonical_records"
    __table_args__ = (
        UniqueConstraint(
            "domain", "entity_type", "external_key", name="uq_ic_canonical_business_key"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100), index=True)
    external_key: Mapped[str | None] = mapped_column(String(255), index=True)
    canonical_name: Mapped[str | None] = mapped_column(String(500), index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    target_module: Mapped[str] = mapped_column(String(100), default="control_center")
    status: Mapped[str] = mapped_column(String(30), default="active")
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    provenance_json: Mapped[str] = mapped_column(Text, default="{}")
    source_job_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CanonicalDeliveryRecord(Base):
    __tablename__ = "ic_canonical_deliveries"
    __table_args__ = (UniqueConstraint("event_id", name="uq_ic_canonical_delivery_event"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    target_system: Mapped[str] = mapped_column(String(80), index=True)
    domain: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100), index=True)
    external_key: Mapped[str] = mapped_column(String(255), index=True)
    source_version: Mapped[str] = mapped_column(String(80))
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    project_id: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    remote_id: Mapped[str | None] = mapped_column(String(160))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CanonicalReconciliationRun(Base):
    __tablename__ = "ic_canonical_reconciliation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    target_system: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(30), default="processing", index=True)
    local_count: Mapped[int] = mapped_column(Integer, default=0)
    remote_count: Mapped[int] = mapped_column(Integer, default=0)
    matching_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_remote_count: Mapped[int] = mapped_column(Integer, default=0)
    hash_mismatch_count: Mapped[int] = mapped_column(Integer, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportCommitBatch(Base):
    __tablename__ = "ic_commit_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(30), default="committed")
    actor: Mapped[str | None] = mapped_column(String(255))
    committed_count: Mapped[int] = mapped_column(Integer, default=0)
    rollback_count: Mapped[int] = mapped_column(Integer, default=0)
    record_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CalculationSourceRegistry(Base):
    __tablename__ = "ic_calculation_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(500))
    source_role: Mapped[str] = mapped_column(String(100), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    drive_file_id: Mapped[str | None] = mapped_column(String(255))
    drive_url: Mapped[str | None] = mapped_column(String(1000))
    sha256: Mapped[str | None] = mapped_column(String(64))
    effective_date: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="active")
    owner: Mapped[str | None] = mapped_column(String(255))
    usage_rule: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WorkspaceDocument(Base):
    __tablename__ = "ws_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    category: Mapped[str] = mapped_column(String(100), index=True, default="other")
    source_system: Mapped[str] = mapped_column(String(100), default="google_drive")
    source_url: Mapped[str | None] = mapped_column(String(1200))
    drive_file_id: Mapped[str | None] = mapped_column(String(255), index=True)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    version_label: Mapped[str | None] = mapped_column(String(80))
    approval_status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    verification_status: Mapped[str] = mapped_column(String(40), default="unverified", index=True)
    confidentiality: Mapped[str] = mapped_column(String(40), default="internal")
    owner: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extracted_summary: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ContractWorkflowRecord(Base):
    __tablename__ = "contract_workflows"
    __table_args__ = (
        CheckConstraint(
            "status IN ('generated','review','approved','signed','dispatched','active','rejected')",
            name="ck_contract_workflow_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    contract_number: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    opportunity_id: Mapped[str] = mapped_column(String(120), index=True)
    partner_id: Mapped[str] = mapped_column(String(120), index=True)
    contract_type: Mapped[str] = mapped_column(String(100), index=True)
    counterparty_name: Mapped[str] = mapped_column(String(500), index=True)
    status: Mapped[str] = mapped_column(String(30), default="generated", index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    package_document_id: Mapped[str] = mapped_column(String(120), index=True)
    manifest_document_id: Mapped[str] = mapped_column(String(120), index=True)
    generated_by: Mapped[str] = mapped_column(String(255))
    submitted_by: Mapped[str | None] = mapped_column(String(255))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commercial_approved_by: Mapped[str | None] = mapped_column(String(255))
    commercial_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commercial_note: Mapped[str | None] = mapped_column(Text)
    technical_approved_by: Mapped[str | None] = mapped_column(String(255))
    technical_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    technical_note: Mapped[str | None] = mapped_column(Text)
    legal_required: Mapped[bool] = mapped_column(Boolean, default=True)
    legal_approved_by: Mapped[str | None] = mapped_column(String(255))
    legal_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legal_note: Mapped[str | None] = mapped_column(Text)
    owner_approved_by: Mapped[str | None] = mapped_column(String(255))
    owner_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_note: Mapped[str | None] = mapped_column(Text)
    rejected_by: Mapped[str | None] = mapped_column(String(255))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    signed_file_id: Mapped[str | None] = mapped_column(String(255), index=True)
    signed_document_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_recorded_by: Mapped[str | None] = mapped_column(String(255))
    postal_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    postal_tracking_number: Mapped[str | None] = mapped_column(String(255), index=True)
    postal_proof_file_id: Mapped[str | None] = mapped_column(String(255))
    electronic_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    electronic_message_id: Mapped[str | None] = mapped_column(String(500), index=True)
    electronic_recipient: Mapped[str | None] = mapped_column(String(320))
    electronic_attachment_sha256: Mapped[str | None] = mapped_column(String(64))
    dispatch_recorded_by: Mapped[str | None] = mapped_column(String(255))
    work_start_allowed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    activated_by: Mapped[str | None] = mapped_column(String(255))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MailSendingDomain(Base):
    __tablename__ = "tm_sending_domains"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    domain_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    from_email: Mapped[str] = mapped_column(String(255))
    from_name: Mapped[str] = mapped_column(String(255), default="Imperial Tender")
    provider: Mapped[str] = mapped_column(String(80), default="provider_not_configured")
    spf_status: Mapped[str] = mapped_column(String(30), default="pending")
    dkim_status: Mapped[str] = mapped_column(String(30), default="pending")
    dmarc_status: Mapped[str] = mapped_column(String(30), default="pending")
    tracking_domain_status: Mapped[str] = mapped_column(String(30), default="pending")
    warmup_status: Mapped[str] = mapped_column(String(30), default="not_started")
    max_hourly_rate: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MailSuppression(Base):
    __tablename__ = "tm_suppressions"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    reason: Mapped[str] = mapped_column(String(80), index=True)
    source: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TenderMailCampaign(Base):
    __tablename__ = "tm_campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    campaign_type: Mapped[str] = mapped_column(String(50), default="tender_invitation")
    tender_id: Mapped[str | None] = mapped_column(String(120), index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    domain_key: Mapped[str] = mapped_column(String(120), index=True)
    subject_template: Mapped[str] = mapped_column(String(500))
    text_template: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    approval_status: Mapped[str] = mapped_column(String(30), default="pending")
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hourly_rate: Mapped[int] = mapped_column(Integer, default=100)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0)
    bounced_count: Mapped[int] = mapped_column(Integer, default=0)
    complained_count: Mapped[int] = mapped_column(Integer, default=0)
    unsubscribed_count: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TenderMailRecipient(Base):
    __tablename__ = "tm_recipients"
    __table_args__ = (UniqueConstraint("campaign_id", "email", name="uq_tm_campaign_email"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    campaign_id: Mapped[str] = mapped_column(String(120), index=True)
    canonical_record_id: Mapped[str | None] = mapped_column(String(120), index=True)
    company_name: Mapped[str | None] = mapped_column(String(500))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    suppression_reason: Mapped[str | None] = mapped_column(String(120))
    personalization_json: Mapped[str] = mapped_column(Text, default="{}")
    tracking_token: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TenderMailEvent(Base):
    __tablename__ = "tm_delivery_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    recipient_id: Mapped[str] = mapped_column(String(120), index=True)
    campaign_id: Mapped[str] = mapped_column(String(120), index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TenderPackage(Base):
    """Audited tender package that is evaluated independently from mail delivery."""

    __tablename__ = "tender_packages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','published','closed','evaluation','awarded','cancelled')",
            name="ck_tender_package_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tender_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    scope: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3), default="HUF")
    question_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    submission_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    evaluation_criteria_json: Mapped[str] = mapped_column(Text, default="{}")
    prequalification_required: Mapped[bool] = mapped_column(Boolean, default=True)
    certificate_gate_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    required_certificate_types_json: Mapped[str] = mapped_column(
        Text, default='["liability_insurance","tax_clearance"]'
    )
    created_by: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    awarded_bid_id: Mapped[str | None] = mapped_column(String(120), index=True)
    award_summary: Mapped[str | None] = mapped_column(Text)
    awarded_by: Mapped[str | None] = mapped_column(String(255))
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    invitations: Mapped[list[TenderInvitation]] = relationship(
        back_populates="tender", cascade="all, delete-orphan"
    )
    bids: Mapped[list[TenderBid]] = relationship(
        back_populates="tender", cascade="all, delete-orphan"
    )
    clarifications: Mapped[list[TenderClarification]] = relationship(
        back_populates="tender", cascade="all, delete-orphan"
    )
    evaluations: Mapped[list[TenderEvaluation]] = relationship(
        back_populates="tender", cascade="all, delete-orphan"
    )
    line_items: Mapped[list[TenderLineItem]] = relationship(
        back_populates="tender", cascade="all, delete-orphan"
    )
    clarification_requests: Mapped[list[TenderClarificationRequest]] = relationship(
        back_populates="tender", cascade="all, delete-orphan"
    )


class TenderInvitation(Base):
    __tablename__ = "tender_invitations"
    __table_args__ = (
        UniqueConstraint("tender_id_fk", "partner_email", name="uq_tender_invitation_email"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    invitation_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tender_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_packages.id", ondelete="CASCADE"), index=True
    )
    mail_recipient_id: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
    partner_id: Mapped[str | None] = mapped_column(String(120), index=True)
    partner_email: Mapped[str] = mapped_column(String(320), index=True)
    company_name: Mapped[str] = mapped_column(String(500))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    access_token: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    token_revision: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="invited", index=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decline_reason: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(String(255))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    tender: Mapped[TenderPackage] = relationship(back_populates="invitations")
    bid: Mapped[TenderBid | None] = relationship(back_populates="invitation", uselist=False)


class TenderBid(Base):
    __tablename__ = "tender_bids"
    __table_args__ = (UniqueConstraint("invitation_id_fk", name="uq_tender_bid_invitation"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    bid_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tender_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_packages.id", ondelete="CASCADE"), index=True
    )
    invitation_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_invitations.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="HUF")
    net_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    vat_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    gross_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    validity_days: Mapped[int] = mapped_column(Integer, default=30)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=0)
    warranty_months: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text)
    exclusions: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    tender: Mapped[TenderPackage] = relationship(back_populates="bids")
    invitation: Mapped[TenderInvitation] = relationship(back_populates="bid")
    items: Mapped[list[TenderBidItem]] = relationship(
        back_populates="bid", cascade="all, delete-orphan"
    )
    evidence: Mapped[list[TenderBidEvidence]] = relationship(
        back_populates="bid", cascade="all, delete-orphan"
    )
    evaluations: Mapped[list[TenderEvaluation]] = relationship(
        back_populates="bid", cascade="all, delete-orphan"
    )


class TenderBidItem(Base):
    __tablename__ = "tender_bid_items"
    __table_args__ = (UniqueConstraint("bid_id_fk", "line_no", name="uq_tender_bid_line"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    bid_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_bids.id", ondelete="CASCADE"), index=True
    )
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(1000))
    unit: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    bid: Mapped[TenderBid] = relationship(back_populates="items")


class TenderClarification(Base):
    __tablename__ = "tender_clarifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    clarification_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tender_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_packages.id", ondelete="CASCADE"), index=True
    )
    invitation_id_fk: Mapped[int | None] = mapped_column(
        ForeignKey("tender_invitations.id", ondelete="CASCADE"), index=True
    )
    author_email: Mapped[str] = mapped_column(String(320))
    author_type: Mapped[str] = mapped_column(String(30))
    body: Mapped[str] = mapped_column(Text)
    partner_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tender: Mapped[TenderPackage] = relationship(back_populates="clarifications")


class TenderBidEvidence(Base):
    __tablename__ = "tender_bid_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    bid_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_bids.id", ondelete="CASCADE"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(1000))
    caption: Mapped[str | None] = mapped_column(Text)
    scan_status: Mapped[str] = mapped_column(String(30), default="legacy_unverified", index=True)
    scan_engine: Mapped[str | None] = mapped_column(String(120))
    scan_engine_version: Mapped[str | None] = mapped_column(String(255))
    scan_signature: Mapped[str | None] = mapped_column(String(255))
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    bid: Mapped[TenderBid] = relationship(back_populates="evidence")


class TenderEvaluation(Base):
    __tablename__ = "tender_evaluations"
    __table_args__ = (
        UniqueConstraint("bid_id_fk", "evaluator_email", name="uq_tender_bid_evaluator"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tender_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_packages.id", ondelete="CASCADE"), index=True
    )
    bid_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_bids.id", ondelete="CASCADE"), index=True
    )
    evaluator_email: Mapped[str] = mapped_column(String(320), index=True)
    price_score: Mapped[int] = mapped_column(Integer)
    technical_score: Mapped[int] = mapped_column(Integer)
    timeline_score: Mapped[int] = mapped_column(Integer)
    references_score: Mapped[int] = mapped_column(Integer)
    weighted_total: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    recommendation: Mapped[str] = mapped_column(String(30))
    notes: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    tender: Mapped[TenderPackage] = relationship(back_populates="evaluations")
    bid: Mapped[TenderBid] = relationship(back_populates="evaluations")


class PartnerProfile(Base):
    """Canonical supplier/subcontractor identity and current engagement eligibility."""

    __tablename__ = "partner_profiles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','conditional','suspended','excluded','reinstatement_review')",
            name="ck_partner_profile_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    partner_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(500), index=True)
    tax_number: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    primary_email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    trade_categories_json: Mapped[str] = mapped_column(Text, default="[]")
    territories_json: Mapped[str] = mapped_column(Text, default="[]")
    external_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    internal_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    combined_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    external_evidence_ref: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    current_decision_id: Mapped[str | None] = mapped_column(String(120), index=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PartnerCertificate(Base):
    __tablename__ = "partner_certificates"
    __table_args__ = (
        UniqueConstraint(
            "partner_id",
            "certificate_type",
            "document_sha256",
            name="uq_partner_certificate_document",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    certificate_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    partner_id: Mapped[str] = mapped_column(String(120), index=True)
    certificate_type: Mapped[str] = mapped_column(String(60), index=True)
    issuer: Mapped[str] = mapped_column(String(500))
    reference_number: Mapped[str | None] = mapped_column(String(255))
    valid_from: Mapped[DateValue | None] = mapped_column(Date)
    valid_until: Mapped[DateValue | None] = mapped_column(Date, index=True)
    document_ref: Mapped[str] = mapped_column(String(1000))
    document_sha256: Mapped[str] = mapped_column(String(64), index=True)
    verification_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    verified_by: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PartnerCapacityDeclaration(Base):
    __tablename__ = "partner_capacity_declarations"
    id: Mapped[int] = mapped_column(primary_key=True)
    declaration_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    partner_id: Mapped[str] = mapped_column(String(120), index=True)
    trade_category: Mapped[str] = mapped_column(String(120), index=True)
    territory: Mapped[str] = mapped_column(String(255), index=True)
    available_from: Mapped[DateValue] = mapped_column(Date, index=True)
    available_until: Mapped[DateValue] = mapped_column(Date, index=True)
    crew_count: Mapped[int] = mapped_column(Integer)
    monthly_capacity: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    committed_capacity: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(30), default="submitted", index=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(1000))
    declared_by: Mapped[str] = mapped_column(String(255))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TenderLineItem(Base):
    __tablename__ = "tender_line_items"
    __table_args__ = (UniqueConstraint("tender_id_fk", "line_code", name="uq_tender_line_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    line_item_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tender_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_packages.id", ondelete="CASCADE"), index=True
    )
    line_no: Mapped[int] = mapped_column(Integer)
    line_code: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(1000))
    unit: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    tender: Mapped[TenderPackage] = relationship(back_populates="line_items")


class TenderBidVersion(Base):
    __tablename__ = "tender_bid_versions"
    __table_args__ = (UniqueConstraint("bid_id_fk", "version", name="uq_tender_bid_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    bid_version_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    bid_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_bids.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    lifecycle_status: Mapped[str] = mapped_column(String(30), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    net_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    vat_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    gross_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    summary: Mapped[str | None] = mapped_column(Text)
    exclusions: Mapped[str | None] = mapped_column(Text)
    normalization_status: Mapped[str] = mapped_column(String(30), index=True)
    normalization_issues_json: Mapped[str] = mapped_column(Text, default="[]")
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TenderBidVersionItem(Base):
    __tablename__ = "tender_bid_version_items"
    __table_args__ = (
        UniqueConstraint("bid_version_id_fk", "line_no", name="uq_tender_bid_version_line"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_item_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    bid_version_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_bid_versions.id", ondelete="CASCADE"), index=True
    )
    line_no: Mapped[int] = mapped_column(Integer)
    tender_line_item_id: Mapped[str | None] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(String(1000))
    source_unit: Mapped[str] = mapped_column(String(40))
    normalized_unit: Mapped[str] = mapped_column(String(40))
    source_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    normalized_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[str | None] = mapped_column(Text)


class TenderClarificationRequest(Base):
    __tablename__ = "tender_clarification_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tender_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_packages.id", ondelete="CASCADE"), index=True
    )
    bid_id_fk: Mapped[int] = mapped_column(
        ForeignKey("tender_bids.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    response: Mapped[str | None] = mapped_column(Text)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acceptance_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    accepted_by: Mapped[str | None] = mapped_column(String(255))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tender: Mapped[TenderPackage] = relationship(back_populates="clarification_requests")


class PartnerProjectEvaluation(Base):
    __tablename__ = "partner_project_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "partner_id", "project_id", "evaluator_email", name="uq_partner_project_evaluator"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    partner_id: Mapped[str] = mapped_column(String(120), index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    quality_score: Mapped[int] = mapped_column(Integer)
    deadline_score: Mapped[int] = mapped_column(Integer)
    documentation_score: Mapped[int] = mapped_column(Integer)
    hse_score: Mapped[int] = mapped_column(Integer)
    cooperation_score: Mapped[int] = mapped_column(Integer)
    commercial_score: Mapped[int] = mapped_column(Integer)
    warranty_score: Mapped[int] = mapped_column(Integer)
    weighting_version: Mapped[str] = mapped_column(String(60), default="partner-score-v1")
    score_100: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    notes: Mapped[str] = mapped_column(Text)
    evaluator_email: Mapped[str] = mapped_column(String(320), index=True)
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PartnerIncident(Base):
    __tablename__ = "partner_incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    partner_id: Mapped[str] = mapped_column(String(120), index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    contract_id: Mapped[str | None] = mapped_column(String(120), index=True)
    incident_type: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    facts: Mapped[str] = mapped_column(Text)
    requirement_breached: Mapped[str] = mapped_column(Text)
    immediate_risk: Mapped[str] = mapped_column(Text)
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    immediate_suspension: Mapped[bool] = mapped_column(Boolean, default=False)
    partner_statement: Mapped[str | None] = mapped_column(Text)
    response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    corrective_action: Mapped[str | None] = mapped_column(Text)
    corrective_owner: Mapped[str | None] = mapped_column(String(255))
    corrective_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    closed_by: Mapped[str | None] = mapped_column(String(255))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PartnerDecision(Base):
    __tablename__ = "partner_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    partner_id: Mapped[str] = mapped_column(String(120), index=True)
    decision_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    basis_json: Mapped[str] = mapped_column(Text)
    conditions_json: Mapped[str] = mapped_column(Text, default="{}")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    proposed_by: Mapped[str] = mapped_column(String(255))
    pm_reviewed_by: Mapped[str | None] = mapped_column(String(255))
    finance_legal_reviewed_by: Mapped[str | None] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notification_evidence_ref: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TenderPurchaseOrderPreparation(Base):
    __tablename__ = "tender_purchase_order_preparations"
    id: Mapped[int] = mapped_column(primary_key=True)
    preparation_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tender_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    partner_id: Mapped[str] = mapped_column(String(120), index=True)
    bid_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    bid_version_id: Mapped[str] = mapped_column(String(120), index=True)
    line_snapshot_json: Mapped[str] = mapped_column(Text)
    exclusions: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    eligibility_snapshot_json: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    prepared_by: Mapped[str] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PMPhase(Base):
    __tablename__ = "ops_pm_phases"
    __table_args__ = (UniqueConstraint("project_id", "phase_key", name="uq_ops_phase_project_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    phase_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    phase_key: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="planned", index=True)
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    readiness_status: Mapped[str] = mapped_column(String(40), default="not_checked")
    owner: Mapped[str | None] = mapped_column(String(255))
    source_module: Mapped[str] = mapped_column(String(100), default="project_control")
    source_object_id: Mapped[str | None] = mapped_column(String(150))
    source_version: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PMWorkPackage(Base):
    __tablename__ = "ops_pm_work_packages"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_package_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    phase_id: Mapped[str | None] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255))
    trade: Mapped[str | None] = mapped_column(String(120), index=True)
    assignee: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="planned", index=True)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    budget_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    committed_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    actual_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    block_reason: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(Text)
    source_module: Mapped[str] = mapped_column(String(100), default="project_control")
    source_object_id: Mapped[str | None] = mapped_column(String(150))
    source_version: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PMGateCheck(Base):
    __tablename__ = "ops_pm_gate_checks"
    __table_args__ = (
        UniqueConstraint("project_id", "work_package_id", "gate_code", name="uq_ops_gate_scope"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    gate_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    work_package_id: Mapped[str | None] = mapped_column(String(120), index=True)
    gate_code: Mapped[str] = mapped_column(String(100), index=True)
    label: Mapped[str] = mapped_column(String(255))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    checked_by: Mapped[str | None] = mapped_column(String(255))
    evidence_url: Mapped[str | None] = mapped_column(String(1200))
    notes: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SiteDailyReport(Base):
    __tablename__ = "ops_site_daily_reports"
    __table_args__ = (
        UniqueConstraint("project_id", "report_date", name="uq_ops_daily_project_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    report_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reporter: Mapped[str] = mapped_column(String(255))
    weather: Mapped[str | None] = mapped_column(String(255))
    workers_total: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text)
    blockers: Mapped[str | None] = mapped_column(Text)
    safety_status: Mapped[str] = mapped_column(String(40), default="ok")
    quality_status: Mapped[str] = mapped_column(String(40), default="ok")
    status: Mapped[str] = mapped_column(String(40), default="submitted", index=True)
    evidence_url: Mapped[str | None] = mapped_column(String(1200))
    voice_note_text: Mapped[str | None] = mapped_column(Text)
    source_device_id: Mapped[str | None] = mapped_column(String(255))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SiteIssue(Base):
    __tablename__ = "ops_site_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    report_id: Mapped[str | None] = mapped_column(String(120), index=True)
    work_package_id: Mapped[str | None] = mapped_column(String(120), index=True)
    issue_type: Mapped[str] = mapped_column(String(80), default="other", index=True)
    severity: Mapped[str] = mapped_column(String(30), default="medium", index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))
    responsible: Mapped[str | None] = mapped_column(String(255))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    evidence_url: Mapped[str | None] = mapped_column(String(1200))
    financial_impact_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    deadline_impact_days: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcurementOrderProjection(Base):
    __tablename__ = "ops_procurement_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    work_package_id: Mapped[str | None] = mapped_column(String(120), index=True)
    supplier_name: Mapped[str] = mapped_column(String(500), index=True)
    item_summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="approved", index=True)
    total_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    delivery_due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[str] = mapped_column(String(40), default="not_started")
    document_status: Mapped[str] = mapped_column(String(40), default="pending")
    variance_status: Mapped[str] = mapped_column(String(40), default="none")
    source_module: Mapped[str] = mapped_column(String(100), default="procurement")
    source_object_id: Mapped[str | None] = mapped_column(String(150))
    source_url: Mapped[str | None] = mapped_column(String(1200))
    source_version: Mapped[str | None] = mapped_column(String(80))
    requirement_id: Mapped[str | None] = mapped_column(String(120), index=True)
    selection_id: Mapped[str | None] = mapped_column(String(120), index=True)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    unit: Mapped[str] = mapped_column(String(40), default="db")
    approval_status: Mapped[str] = mapped_column(String(40), default="approved", index=True)
    confirmation_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(String(255))
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class DeliveryNoteProjection(Base):
    __tablename__ = "ops_delivery_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_note_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    order_id: Mapped[str] = mapped_column(String(120), index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    note_number: Mapped[str | None] = mapped_column(String(150), index=True)
    source_url: Mapped[str | None] = mapped_column(String(1200))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    receiver: Mapped[str] = mapped_column(String(255))
    item_summary: Mapped[str] = mapped_column(Text)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    unit: Mapped[str] = mapped_column(String(40), default="db")
    actual_specification: Mapped[str | None] = mapped_column(Text)
    quality_status: Mapped[str] = mapped_column(String(40), default="accepted")
    damage_or_shortage: Mapped[str | None] = mapped_column(Text)
    plan_match: Mapped[str] = mapped_column(String(40), default="matched")
    document_status: Mapped[str] = mapped_column(String(40), default="complete")
    performance_declaration_status: Mapped[str] = mapped_column(String(40), default="pending")
    elog_evidence_status: Mapped[str] = mapped_column(String(40), default="pending")
    supplier_signed: Mapped[bool] = mapped_column(Boolean, default=False)
    receiver_signed: Mapped[bool] = mapped_column(Boolean, default=False)
    signature_evidence_ref: Mapped[str | None] = mapped_column(String(1200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcurementRequirement(Base):
    __tablename__ = "procurement_requirements"
    id: Mapped[int] = mapped_column(primary_key=True)
    requirement_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    work_package_id: Mapped[str | None] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(120), index=True)
    scope_description: Mapped[str] = mapped_column(Text)
    specification: Mapped[str] = mapped_column(Text)
    net_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    waste_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0"))
    max_orderable_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit: Mapped[str] = mapped_column(String(40))
    required_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    budget_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    target_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(40), default="spec_pending", index=True)
    revision_no: Mapped[int] = mapped_column(Integer, default=1)
    revision_reason: Mapped[str | None] = mapped_column(Text)
    technical_approved_by: Mapped[str | None] = mapped_column(String(255))
    technical_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    budget_approved_by: Mapped[str | None] = mapped_column(String(255))
    budget_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cash_approved_by: Mapped[str | None] = mapped_column(String(255))
    cash_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProcurementOffer(Base):
    __tablename__ = "procurement_offers"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    requirement_id: Mapped[str] = mapped_column(String(120), index=True)
    supplier_name: Mapped[str] = mapped_column(String(500), index=True)
    partner_id: Mapped[str | None] = mapped_column(String(120), index=True)
    net_total_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    delivery_cost_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    other_landed_cost_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    total_landed_cost_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    lead_time_days: Mapped[int] = mapped_column(Integer, default=0)
    warranty_months: Mapped[int] = mapped_column(Integer, default=0)
    payment_terms: Mapped[str] = mapped_column(String(500))
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    technical_compliant: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_ref: Mapped[str] = mapped_column(String(1200))
    status: Mapped[str] = mapped_column(String(40), default="received", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcurementSelection(Base):
    __tablename__ = "procurement_selections"
    id: Mapped[int] = mapped_column(primary_key=True)
    selection_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    requirement_id: Mapped[str] = mapped_column(String(120), index=True)
    offer_id: Mapped[str] = mapped_column(String(120), index=True)
    total_landed_cost_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    savings_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    market_evidence_ref: Mapped[str | None] = mapped_column(String(1200))
    rationale: Mapped[str] = mapped_column(Text)
    risk_rationale: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="approval_pending", index=True)
    dual_approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    prepared_by: Mapped[str] = mapped_column(String(255))
    finance_approved_by: Mapped[str | None] = mapped_column(String(255))
    finance_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    md_approved_by: Mapped[str | None] = mapped_column(String(255))
    md_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_approved_by: Mapped[str | None] = mapped_column(String(255))
    owner_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcurementSubstitutionReview(Base):
    __tablename__ = "procurement_substitution_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    requirement_id: Mapped[str] = mapped_column(String(120), index=True)
    proposed_product: Mapped[str] = mapped_column(String(1000))
    proposed_specification: Mapped[str] = mapped_column(Text)
    technical_equivalence: Mapped[str] = mapped_column(Text)
    declaration_ref: Mapped[str] = mapped_column(String(1200))
    price_impact_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    schedule_impact_days: Mapped[int] = mapped_column(Integer, default=0)
    risk_assessment: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(255))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcurementDeviation(Base):
    __tablename__ = "procurement_deviations"
    id: Mapped[int] = mapped_column(primary_key=True)
    deviation_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    order_id: Mapped[str] = mapped_column(String(120), index=True)
    delivery_note_id: Mapped[str | None] = mapped_column(String(120), index=True)
    deviation_type: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(255))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    corrective_action: Mapped[str] = mapped_column(Text)
    financial_impact_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(255))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcurementInvoiceMatch(Base):
    __tablename__ = "procurement_invoice_matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    order_id: Mapped[str] = mapped_column(String(120), index=True)
    delivery_note_id: Mapped[str] = mapped_column(String(120), index=True)
    invoice_reference: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    invoice_total_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    ordered_total_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    accepted_value_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    blockers_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(40), default="blocked", index=True)
    payment_ready: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    matched_by: Mapped[str] = mapped_column(String(255))
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseVisionRightsPolicy(Base):
    __tablename__ = "housevision_rights_policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    path_prefix: Mapped[str] = mapped_column(String(1000), default="/")
    rights_status: Mapped[str] = mapped_column(String(40), index=True)
    evidence_ref: Mapped[str] = mapped_column(String(1200))
    grant_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    owner_attestation_sha256: Mapped[str | None] = mapped_column(String(64))
    page_scope_sha256: Mapped[str | None] = mapped_column(String(64))
    attribution_required: Mapped[bool] = mapped_column(Boolean, default=False)
    attribution_text: Mapped[str | None] = mapped_column(Text)
    crawl_delay_seconds: Mapped[int] = mapped_column(Integer, default=2)
    max_assets_per_page: Mapped[int] = mapped_column(Integer, default=12)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseVisionJob(Base):
    __tablename__ = "housevision_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    source_url: Mapped[str] = mapped_column(String(1200))
    source_page_id: Mapped[str] = mapped_column(String(120), index=True)
    rights_policy_id: Mapped[str | None] = mapped_column(String(120), index=True)
    house_id: Mapped[str | None] = mapped_column(String(120), index=True)
    house_name_id: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(50), default="RECEIVED", index=True)
    operation_mode: Mapped[str] = mapped_column(String(30), default="package_only")
    render_provider: Mapped[str] = mapped_column(String(50), default="mock")
    render_prompt_version: Mapped[str] = mapped_column(String(120), default="housevision-v1")
    brand_policy_version: Mapped[str] = mapped_column(String(120), default="brand-visual-v1")
    accepted_source_count: Mapped[int] = mapped_column(Integer, default=0)
    output_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    publication_eligibility: Mapped[str] = mapped_column(String(40), default="blocked", index=True)
    provider_cost_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseVisionSourceAsset(Base):
    __tablename__ = "housevision_source_assets"
    __table_args__ = (
        UniqueConstraint("job_id", "content_sha256", name="uq_housevision_source_hash"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_visual_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    source_url: Mapped[str] = mapped_column(String(1200))
    asset_type: Mapped[str] = mapped_column(String(30), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    width_px: Mapped[int] = mapped_column(Integer)
    height_px: Mapped[int] = mapped_column(Integer)
    magic_mime_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), default="accepted", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseVisionGeometryLock(Base):
    __tablename__ = "housevision_geometry_locks"
    id: Mapped[int] = mapped_column(primary_key=True)
    geometry_lock_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    floorplan_topology_sha256: Mapped[str] = mapped_column(String(64))
    massing_signature: Mapped[str] = mapped_column(String(500))
    roof_form: Mapped[str] = mapped_column(String(255))
    roof_pitch_deg: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    storey_count: Mapped[int] = mapped_column(Integer)
    window_count: Mapped[int] = mapped_column(Integer)
    door_count: Mapped[int] = mapped_column(Integer)
    width_depth_height_ratio: Mapped[str] = mapped_column(String(120))
    immutable_features_json: Mapped[str] = mapped_column(Text, default="[]")
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseVisionOutputAsset(Base):
    __tablename__ = "housevision_output_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    output_visual_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    source_visual_id: Mapped[str] = mapped_column(String(120), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    provider_job_id: Mapped[str] = mapped_column(String(255))
    output_ref: Mapped[str] = mapped_column(String(1200))
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    width_px: Mapped[int] = mapped_column(Integer)
    height_px: Mapped[int] = mapped_column(Integer)
    edge_overlap: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    roof_match: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    opening_match: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    floorplan_fidelity: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    full_house_in_frame: Mapped[bool] = mapped_column(Boolean, default=False)
    daylight_pass: Mapped[bool] = mapped_column(Boolean, default=False)
    photorealism_pass: Mapped[bool] = mapped_column(Boolean, default=False)
    brand_identity_pass: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_pass: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default="qa_pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseVisionQAReport(Base):
    __tablename__ = "housevision_qa_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    qa_report_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    gates_json: Mapped[str] = mapped_column(Text)
    critical_failures_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), index=True)
    automatic_retry: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseVisionPackage(Base):
    __tablename__ = "housevision_packages"
    __table_args__ = (UniqueConstraint("job_id", "version", name="uq_housevision_package_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer)
    house_id: Mapped[str | None] = mapped_column(String(120), index=True)
    storage_ref: Mapped[str] = mapped_column(String(1200))
    manifest_sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_count: Mapped[int] = mapped_column(Integer)
    output_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="ready", index=True)
    dam_handoff_status: Mapped[str] = mapped_column(String(40), default="pending")
    buildconfig_handoff_status: Mapped[str] = mapped_column(String(40), default="pending")
    publication_status: Mapped[str] = mapped_column(String(40), default="blocked")
    supersedes_package_id: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseVisionName(Base):
    __tablename__ = "housevision_names"
    id: Mapped[int] = mapped_column(primary_key=True)
    house_name_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    public_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="reserved", index=True)
    job_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentImageFactoryRequest(Base):
    __tablename__ = "cq_image_factory_requests"
    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "content_version",
            name="uq_cq_image_factory_asset_version",
        ),
        CheckConstraint(
            "status IN ('QUEUED','BLOCKED','SUBMITTED','PROCESSING','IMPORTED',"
            "'NEEDS_REVIEW','FAILED','STALE')",
            name="ck_cq_image_factory_request_status",
        ),
    )
    request_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(120), index=True)
    content_version: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), index=True)
    image_factory_batch_id: Mapped[str | None] = mapped_column(String(80), index=True)
    image_factory_job_id: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    requested_role: Mapped[str] = mapped_column(String(40), default="hero")
    output_role: Mapped[str] = mapped_column(String(40), default="web_hero")
    request_payload_json: Mapped[str] = mapped_column(Text)
    response_json: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    output_uri: Mapped[str | None] = mapped_column(String(2000))
    output_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    qa_score: Mapped[int | None] = mapped_column(Integer)
    release_state: Mapped[str | None] = mapped_column(String(40), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseVisionFactoryStream(Base):
    __tablename__ = "housevision_factory_streams"
    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    catalog_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    pause_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseVisionFactoryImport(Base):
    __tablename__ = "housevision_factory_imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    stream_id: Mapped[str] = mapped_column(String(120), index=True)
    catalog_id: Mapped[str] = mapped_column(String(160), index=True)
    source_file_name: Mapped[str | None] = mapped_column(String(500))
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    requested_count: Mapped[int] = mapped_column(Integer)
    registered_count: Mapped[int] = mapped_column(Integer)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="REGISTERED", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseVisionFactoryImportItem(Base):
    __tablename__ = "housevision_factory_import_items"
    __table_args__ = (
        UniqueConstraint("import_id", "sequence", name="uq_hvf_import_sequence"),
        UniqueConstraint(
            "catalog_id", "requested_url_sha256", name="uq_hvf_catalog_requested_url"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    import_item_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    import_id: Mapped[str] = mapped_column(String(120), index=True)
    stream_id: Mapped[str] = mapped_column(String(120), index=True)
    catalog_id: Mapped[str] = mapped_column(String(160), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    requested_url: Mapped[str] = mapped_column(String(1600))
    requested_url_sha256: Mapped[str] = mapped_column(String(64), index=True)
    rights_grant_id: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    job_id: Mapped[str | None] = mapped_column(String(120), index=True)
    terminal_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseVisionFactoryJob(Base):
    __tablename__ = "housevision_factory_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_hvf_job_idempotency_key"),
        UniqueConstraint(
            "catalog_id", "canonical_url", "source_revision_hash", "job_revision",
            name="uq_hvf_job_source_revision",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_revision: Mapped[int] = mapped_column(Integer, default=1)
    stream_id: Mapped[str] = mapped_column(String(120), index=True)
    catalog_id: Mapped[str] = mapped_column(String(160), index=True)
    import_item_id: Mapped[str | None] = mapped_column(String(120), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(500), index=True)
    requested_url: Mapped[str] = mapped_column(String(1600))
    canonical_url: Mapped[str] = mapped_column(String(1600))
    final_url: Mapped[str | None] = mapped_column(String(1600))
    requested_url_sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_revision_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_page_id: Mapped[str] = mapped_column(String(120), index=True)
    project_code: Mapped[str | None] = mapped_column(String(160), index=True)
    house_plan_id: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
    housevision_job_id: Mapped[str | None] = mapped_column(
        String(120), unique=True, index=True
    )
    geographic_name: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    rights_grant_id: Mapped[str] = mapped_column(String(255), index=True)
    rights_policy_id: Mapped[str | None] = mapped_column(String(120), index=True)
    visual_profile_id: Mapped[str] = mapped_column(
        String(120), default="california_ultra_v1"
    )
    output_profile_id: Mapped[str] = mapped_column(
        String(120), default="web_8k_master_v1"
    )
    render_provider: Mapped[str] = mapped_column(String(120), default="disabled")
    status: Mapped[str] = mapped_column(String(50), default="PENDING", index=True)
    stage: Mapped[str] = mapped_column(String(80), default="PENDING", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    render_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    repair_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_passes: Mapped[int] = mapped_column(Integer, default=0)
    package_manifest_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    package_url: Mapped[str | None] = mapped_column(String(1600))
    lease_owner: Mapped[str | None] = mapped_column(String(255), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    source_title: Mapped[str | None] = mapped_column(String(1000))
    gross_floor_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    net_floor_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    levels: Mapped[int | None] = mapped_column(Integer)
    rooms_total: Mapped[int | None] = mapped_column(Integer)
    finding_summary_json: Mapped[str] = mapped_column(Text, default="[]")
    last_error_code: Mapped[str | None] = mapped_column(String(120), index=True)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseVisionFactoryArtifact(Base):
    __tablename__ = "housevision_factory_artifacts"
    __table_args__ = (
        UniqueConstraint("job_id", "relative_path", name="uq_hvf_artifact_path"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    role: Mapped[str] = mapped_column(String(80), index=True)
    relative_path: Mapped[str] = mapped_column(String(1200))
    storage_ref: Mapped[str] = mapped_column(String(1600))
    mime_type: Mapped[str] = mapped_column(String(160))
    byte_size: Mapped[int] = mapped_column(Integer)
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_page_url: Mapped[str] = mapped_column(String(1600))
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseVisionFactoryQARun(Base):
    __tablename__ = "housevision_factory_qa_runs"
    __table_args__ = (
        UniqueConstraint("job_id", "run_number", name="uq_hvf_qa_run_number"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    qa_run_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    run_number: Mapped[int] = mapped_column(Integer)
    package_manifest_sha256: Mapped[str] = mapped_column(String(64), index=True)
    deterministic_pass: Mapped[bool] = mapped_column(Boolean, default=False)
    semantic_pass: Mapped[bool] = mapped_column(Boolean, default=False)
    semantic_score: Mapped[int] = mapped_column(Integer, default=0)
    decision: Mapped[str] = mapped_column(String(30), index=True)
    verifier_id: Mapped[str] = mapped_column(String(255))
    verifier_model: Mapped[str] = mapped_column(String(255))
    findings_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseVisionFactoryRepair(Base):
    __tablename__ = "housevision_factory_repairs"
    id: Mapped[int] = mapped_column(primary_key=True)
    repair_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    finding_code: Mapped[str] = mapped_column(String(120), index=True)
    action_type: Mapped[str] = mapped_column(String(120))
    before_sha256: Mapped[str | None] = mapped_column(String(64))
    after_sha256: Mapped[str | None] = mapped_column(String(64))
    instruction: Mapped[str] = mapped_column(Text)
    provider_ref: Mapped[str | None] = mapped_column(String(500))
    result: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebsiteSite(Base):
    __tablename__ = "website_sites"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255))
    base_url: Mapped[str] = mapped_column(String(1200), unique=True)
    adapter_endpoint: Mapped[str] = mapped_column(String(1200))
    credential_ref: Mapped[str] = mapped_column(String(1200))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    kill_switch_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WebsiteRelease(Base):
    __tablename__ = "website_releases"
    __table_args__ = (
        UniqueConstraint("asset_id", "version", name="uq_website_asset_release_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    asset_id: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content_version: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    publication_bundle_id: Mapped[str] = mapped_column(String(120), index=True)
    publication_proof_id: Mapped[str] = mapped_column(String(120), index=True)
    release_manifest_sha256: Mapped[str] = mapped_column(String(64), index=True)
    target_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="ready", index=True)
    auto_rollback_status: Mapped[str] = mapped_column(
        String(40), default="not_required", index=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_by: Mapped[str | None] = mapped_column(String(255))


class WebsiteReleaseTarget(Base):
    __tablename__ = "website_release_targets"
    __table_args__ = (
        UniqueConstraint(
            "release_id", "site_id", "route_path", "locale", name="uq_website_release_target"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    release_id: Mapped[str] = mapped_column(String(120), index=True)
    site_id: Mapped[str] = mapped_column(String(120), index=True)
    route_path: Mapped[str] = mapped_column(String(1000), index=True)
    locale: Mapped[str] = mapped_column(String(20), default="hu-HU")
    canonical_url: Mapped[str] = mapped_column(String(1200))
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    external_version_id: Mapped[str | None] = mapped_column(String(255))
    published_url: Mapped[str | None] = mapped_column(String(1200))
    rendered_content_sha256: Mapped[str | None] = mapped_column(String(64))
    previous_target_id: Mapped[str | None] = mapped_column(String(120), index=True)
    receipt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    smoke_http_status: Mapped[int | None] = mapped_column(Integer)
    smoke_json: Mapped[str] = mapped_column(Text, default="{}")
    smoke_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebsiteRouteState(Base):
    __tablename__ = "website_route_states"
    __table_args__ = (
        UniqueConstraint("site_id", "route_path", "locale", name="uq_website_route_state"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    route_state_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    site_id: Mapped[str] = mapped_column(String(120), index=True)
    route_path: Mapped[str] = mapped_column(String(1000), index=True)
    locale: Mapped[str] = mapped_column(String(20), default="hu-HU")
    current_release_id: Mapped[str] = mapped_column(String(120), index=True)
    current_target_id: Mapped[str] = mapped_column(String(120), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseDesignerEntitlement(Base):
    __tablename__ = "house_designer_entitlements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "brand_id", name="uq_hd_entitlement_tenant_brand"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    entitlement_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(30), default="sandbox", index=True)
    standalone_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    order_intake_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    production_render_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    production_pricing_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    production_capacity_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_json: Mapped[str] = mapped_column(Text, default="{}")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    activation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    readiness_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseDesignSession(Base):
    __tablename__ = "house_design_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','CHECK_REQUIRED','CHECKED','ESTIMATED',"
            "'CUSTOMER_APPROVED','SUBMITTED','STALE','ARCHIVED','CANCELLED')",
            name="ck_hd_session_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    owner_subject_id: Mapped[str | None] = mapped_column(String(160), index=True)
    project_id: Mapped[str | None] = mapped_column(String(120), index=True)
    origin: Mapped[str] = mapped_column(String(30), default="blank", index=True)
    template_plan_id: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    current_revision_id: Mapped[str | None] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(20), default="hu-HU")
    currency: Mapped[str] = mapped_column(String(3), default="HUF")
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(255))
    updated_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseDesignRevision(Base):
    __tablename__ = "house_design_revisions"
    __table_args__ = (
        UniqueConstraint("session_id", "revision_no", name="uq_hd_revision_session_no"),
        UniqueConstraint("session_id", "command_id", name="uq_hd_revision_command"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("house_design_sessions.session_id", ondelete="RESTRICT"), index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer)
    predecessor_revision_id: Mapped[str | None] = mapped_column(String(120), index=True)
    command_id: Mapped[str] = mapped_column(String(120), index=True)
    command_type: Mapped[str] = mapped_column(String(80), index=True)
    command_sha256: Mapped[str] = mapped_column(String(64))
    geometry_json: Mapped[str] = mapped_column(Text)
    configuration_json: Mapped[str] = mapped_column(Text, default="{}")
    site_json: Mapped[str] = mapped_column(Text, default="{}")
    canonical_sha256: Mapped[str] = mapped_column(String(64), index=True)
    change_summary: Mapped[str] = mapped_column(Text, default="")
    schema_version: Mapped[str] = mapped_column(String(40), default="house-design-v1")
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseDesignGuestClaim(Base):
    __tablename__ = "house_design_guest_claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("house_design_sessions.session_id", ondelete="RESTRICT"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    guest_session_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    claimed_by_subject_id: Mapped[str | None] = mapped_column(String(160), index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseDesignerGuestRateLimit(Base):
    __tablename__ = "house_designer_guest_rate_limits"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "brand_id",
            "fingerprint_hash",
            name="uq_hd_guest_rate_scope_fingerprint",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    rate_limit_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), index=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseDesignSiteVerification(Base):
    __tablename__ = "house_design_site_verifications"
    __table_args__ = (
        UniqueConstraint("session_id", "verified_revision_id", name="uq_hd_site_verified_revision"),
        UniqueConstraint("session_id", "proof_sha256", name="uq_hd_site_session_proof"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    verification_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    source_revision_id: Mapped[str] = mapped_column(String(120), index=True)
    verified_revision_id: Mapped[str] = mapped_column(String(120), index=True)
    municipality_code: Mapped[str] = mapped_column(String(80), index=True)
    parcel_number: Mapped[str] = mapped_column(String(120), index=True)
    proof_ref: Mapped[str] = mapped_column(String(1200))
    proof_sha256: Mapped[str] = mapped_column(String(64), index=True)
    verification_method: Mapped[str] = mapped_column(String(120))
    verified_by: Mapped[str] = mapped_column(String(255), index=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RegulatorySourceSnapshot(Base):
    __tablename__ = "regulatory_source_snapshots"
    __table_args__ = (
        UniqueConstraint("source_key", "revision", name="uq_reg_source_key_revision"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_snapshot_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_key: Mapped[str] = mapped_column(String(180), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(50), index=True)
    issuer: Mapped[str] = mapped_column(String(255))
    jurisdiction: Mapped[str] = mapped_column(String(160), index=True)
    scope_key: Mapped[str] = mapped_column(String(255), index=True)
    source_url: Mapped[str] = mapped_column(String(1200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    normalized_text_sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_ref: Mapped[str] = mapped_column(String(1200))
    parser_version: Mapped[str] = mapped_column(String(120))
    security_status: Mapped[str] = mapped_column(String(30), default="pending_review", index=True)
    status: Mapped[str] = mapped_column(String(30), default="captured", index=True)
    supersedes_snapshot_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RegulatoryRuleSet(Base):
    __tablename__ = "regulatory_rule_sets"
    __table_args__ = (
        UniqueConstraint("family_key", "revision", name="uq_reg_ruleset_family_revision"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    ruleset_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    family_key: Mapped[str] = mapped_column(String(255), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    jurisdiction: Mapped[str] = mapped_column(String(160), index=True)
    scope_key: Mapped[str] = mapped_column(String(255), index=True)
    national_basis: Mapped[str] = mapped_column(String(50), index=True)
    local_plan_basis: Mapped[str] = mapped_column(String(255))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    source_snapshot_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    interpretation_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    interpreter_version: Mapped[str] = mapped_column(String(120))
    rules_json: Mapped[str] = mapped_column(Text)
    canonical_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    authored_by: Mapped[str] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_ruleset_id: Mapped[str | None] = mapped_column(String(120), index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RegulatoryRuleInterpretation(Base):
    __tablename__ = "regulatory_rule_interpretations"
    __table_args__ = (
        UniqueConstraint(
            "source_snapshot_id", "revision", name="uq_reg_interpretation_source_revision"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    interpretation_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    source_spans_json: Mapped[str] = mapped_column(Text, default="[]")
    interpreted_rules_json: Mapped[str] = mapped_column(Text)
    test_vectors_json: Mapped[str] = mapped_column(Text, default="[]")
    interpreter_version: Mapped[str] = mapped_column(String(120))
    canonical_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    authored_by: Mapped[str] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RegulatoryComplianceRun(Base):
    __tablename__ = "regulatory_compliance_runs"
    __table_args__ = (
        UniqueConstraint("revision_id", "ruleset_id", "input_sha256", name="uq_reg_run_input"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    revision_id: Mapped[str] = mapped_column(String(120), index=True)
    ruleset_id: Mapped[str | None] = mapped_column(String(120), index=True)
    ruleset_sha256: Mapped[str | None] = mapped_column(String(64))
    input_sha256: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(20), index=True)
    blocker_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    engine_version: Mapped[str] = mapped_column(String(120))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))


class RegulatoryComplianceFinding(Base):
    __tablename__ = "regulatory_compliance_findings"
    __table_args__ = (UniqueConstraint("run_id", "finding_key", name="uq_reg_finding_run_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("regulatory_compliance_runs.run_id", ondelete="CASCADE"), index=True
    )
    finding_key: Mapped[str] = mapped_column(String(180))
    code: Mapped[str] = mapped_column(String(120), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    outcome: Mapped[str] = mapped_column(String(20), index=True)
    rule_ref: Mapped[str] = mapped_column(String(500))
    source_ref: Mapped[str] = mapped_column(String(1200))
    geometry_path: Mapped[str | None] = mapped_column(String(1000))
    measured_json: Mapped[str] = mapped_column(Text, default="{}")
    limit_json: Mapped[str] = mapped_column(Text, default="{}")
    explanation: Mapped[str] = mapped_column(Text)
    remediation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseDesignRenderRevision(Base):
    __tablename__ = "house_design_render_revisions"
    __table_args__ = (
        UniqueConstraint("session_id", "revision_no", name="uq_hd_render_session_revision"),
        UniqueConstraint("provider_job_id", name="uq_hd_render_provider_job"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    render_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    design_revision_id: Mapped[str] = mapped_column(String(120), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    parent_render_id: Mapped[str | None] = mapped_column(String(120), index=True)
    geometry_lock_sha256: Mapped[str] = mapped_column(String(64), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(80))
    provider_job_id: Mapped[str | None] = mapped_column(String(255), index=True)
    asset_ref: Mapped[str | None] = mapped_column(String(1200))
    asset_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    qa_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    non_production: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    accepted_by: Mapped[str | None] = mapped_column(String(255))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseDesignEstimateSnapshot(Base):
    __tablename__ = "house_design_estimate_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    estimate_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    design_revision_id: Mapped[str] = mapped_column(String(120), index=True)
    buildconfig_case_id: Mapped[str | None] = mapped_column(String(120), index=True)
    buildconfig_revision_id: Mapped[str | None] = mapped_column(String(120), index=True)
    input_sha256: Mapped[str] = mapped_column(String(64), index=True)
    net_min_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_max_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    gross_min_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    gross_max_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_items_json: Mapped[str] = mapped_column(Text, default="[]")
    assumptions_json: Mapped[str] = mapped_column(Text, default="[]")
    exclusions_json: Mapped[str] = mapped_column(Text, default="[]")
    provider: Mapped[str] = mapped_column(String(80))
    non_production: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    canonical_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseDesignScheduleSnapshot(Base):
    __tablename__ = "house_design_schedule_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    design_revision_id: Mapped[str] = mapped_column(String(120), index=True)
    input_sha256: Mapped[str] = mapped_column(String(64), index=True)
    earliest_start: Mapped[DateValue | None] = mapped_column(Date)
    latest_start: Mapped[DateValue | None] = mapped_column(Date)
    duration_min_workdays: Mapped[int] = mapped_column(Integer)
    duration_max_workdays: Mapped[int] = mapped_column(Integer)
    phases_json: Mapped[str] = mapped_column(Text, default="[]")
    assumptions_json: Mapped[str] = mapped_column(Text, default="[]")
    capacity_snapshot_id: Mapped[str | None] = mapped_column(String(120), index=True)
    provider: Mapped[str] = mapped_column(String(80))
    non_production: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    canonical_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseDesignerAdapterRegistration(Base):
    __tablename__ = "house_designer_adapter_registrations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "brand_id", "adapter_type", "revision_no",
            name="uq_hd_adapter_scope_revision",
        ),
        CheckConstraint(
            "adapter_type IN ('pricing','capacity','render')",
            name="ck_hd_adapter_type",
        ),
        CheckConstraint(
            "status IN ('DRAFT','IN_REVIEW','ACTIVE','SUSPENDED','REVOKED')",
            name="ck_hd_adapter_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    adapter_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    adapter_type: Mapped[str] = mapped_column(String(30), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(120))
    endpoint: Mapped[str] = mapped_column(String(1200))
    key_id: Mapped[str] = mapped_column(String(160))
    contract_version: Mapped[str] = mapped_column(
        String(80), default="house-designer-adapter-v1"
    )
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    health_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN", index=True)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authored_by: Mapped[str] = mapped_column(String(255), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseDesignerAdapterJob(Base):
    __tablename__ = "house_designer_adapter_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_hd_adapter_job_idempotency"),
        CheckConstraint(
            "adapter_type IN ('pricing','capacity','render')",
            name="ck_hd_adapter_job_type",
        ),
        CheckConstraint(
            "status IN ('QUEUED','DISPATCHED','SUCCEEDED','FAILED','EXPIRED')",
            name="ck_hd_adapter_job_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    design_revision_id: Mapped[str] = mapped_column(String(120), index=True)
    adapter_id: Mapped[str] = mapped_column(String(120), index=True)
    adapter_type: Mapped[str] = mapped_column(String(30), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    request_json: Mapped[str] = mapped_column(Text)
    request_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(255), index=True)
    result_object_id: Mapped[str | None] = mapped_column(String(120), index=True)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_detail: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseDesignerAdapterReceipt(Base):
    __tablename__ = "house_designer_adapter_receipts"
    __table_args__ = (
        UniqueConstraint("job_id", "response_sha256", name="uq_hd_adapter_receipt_response"),
        UniqueConstraint("adapter_id", "provider_job_id", name="uq_hd_adapter_provider_job"),
        CheckConstraint(
            "status IN ('ACCEPTED','REJECTED')", name="ck_hd_adapter_receipt_status"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    job_id: Mapped[str] = mapped_column(String(120), index=True)
    adapter_id: Mapped[str] = mapped_column(String(120), index=True)
    provider_job_id: Mapped[str] = mapped_column(String(255), index=True)
    key_id: Mapped[str] = mapped_column(String(160))
    request_sha256: Mapped[str] = mapped_column(String(64), index=True)
    response_sha256: Mapped[str] = mapped_column(String(64), index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(30), index=True)
    rejection_code: Mapped[str | None] = mapped_column(String(120))
    evidence_json: Mapped[str] = mapped_column(Text)


class HouseDesignSnapshot(Base):
    __tablename__ = "house_design_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    design_revision_id: Mapped[str] = mapped_column(String(120), index=True)
    compliance_run_id: Mapped[str] = mapped_column(String(120), index=True)
    estimate_id: Mapped[str] = mapped_column(String(120), index=True)
    schedule_id: Mapped[str] = mapped_column(String(120), index=True)
    selected_render_id: Mapped[str] = mapped_column(String(120), index=True)
    terms_version_id: Mapped[str] = mapped_column(String(120), index=True)
    consent_version_id: Mapped[str] = mapped_column(String(120), index=True)
    manifest_json: Mapped[str] = mapped_column(Text)
    manifest_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    approved_by_subject_id: Mapped[str] = mapped_column(String(160), index=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseDesignSubmission(Base):
    __tablename__ = "house_design_submissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_hd_submission_idempotency"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), index=True)
    submission_type: Mapped[str] = mapped_column(String(30), default="ORDER_REQUEST")
    status: Mapped[str] = mapped_column(String(40), default="RECEIVED", index=True)
    customer_subject_id: Mapped[str] = mapped_column(String(160), index=True)
    lead_id: Mapped[str | None] = mapped_column(String(120), index=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    project_id: Mapped[str | None] = mapped_column(String(120), index=True)
    booking_id: Mapped[str | None] = mapped_column(String(120), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    attribution_json: Mapped[str] = mapped_column(Text, default="{}")
    notice_version_id: Mapped[str] = mapped_column(String(120))
    notice_accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HouseDesignSubmissionDecision(Base):
    __tablename__ = "house_design_submission_decisions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_hd_submission_decision_idempotency"
        ),
        CheckConstraint(
            "review_lane IN ('sales','design','compliance','pricing','customer')",
            name="ck_hd_submission_decision_lane",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("house_design_submissions.submission_id", ondelete="RESTRICT"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    project_id: Mapped[str] = mapped_column(String(120), index=True)
    review_lane: Mapped[str] = mapped_column(String(30), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    from_status: Mapped[str] = mapped_column(String(40), index=True)
    to_status: Mapped[str] = mapped_column(String(40), index=True)
    note: Mapped[str] = mapped_column(Text)
    expected_row_version: Mapped[int] = mapped_column(Integer)
    resulting_row_version: Mapped[int] = mapped_column(Integer)
    actor_subject_id: Mapped[str] = mapped_column(String(160), index=True)
    actor_role: Mapped[str] = mapped_column(String(60), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketSourceTarget(Base):
    __tablename__ = "market_source_targets"
    __table_args__ = (
        UniqueConstraint("family_id", "revision_no", name="uq_mkt_target_family_revision"),
        CheckConstraint(
            "status IN ('DRAFT','IN_REVIEW','APPROVED','REVOKED','SUPERSEDED')",
            name="ck_mkt_target_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    family_id: Mapped[str] = mapped_column(String(120), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    market_id: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    source_type: Mapped[str] = mapped_column(String(60))
    normalized_origin: Mapped[str] = mapped_column(String(1200))
    allowed_path: Mapped[str] = mapped_column(String(1200), default="/")
    capture_mode: Mapped[str] = mapped_column(String(40), default="manual")
    rights_status: Mapped[str] = mapped_column(String(40))
    pii_policy: Mapped[str] = mapped_column(String(80), default="reject")
    policy_json: Mapped[str] = mapped_column(Text, default="{}")
    policy_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    author_subject_id: Mapped[str] = mapped_column(String(160), index=True)
    reviewer_subject_id: Mapped[str | None] = mapped_column(String(160))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MarketCaptureJob(Base):
    __tablename__ = "market_capture_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_mkt_capture_idempotency"),
        Index(
            "ix_mkt_capture_scope_created",
            "tenant_id",
            "brand_id",
            "market_id",
            "created_at",
        ),
        Index(
            "ix_mkt_capture_scope_status_finished",
            "tenant_id",
            "brand_id",
            "market_id",
            "status",
            "finished_at",
        ),
        Index(
            "ix_mkt_capture_target_created",
            "tenant_id",
            "target_id",
            "created_at",
        ),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','PARTIAL','FAILED','CANCELLED')",
            name="ck_mkt_capture_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    market_id: Mapped[str] = mapped_column(String(120), index=True)
    target_id: Mapped[str] = mapped_column(String(120), index=True)
    requested_url: Mapped[str | None] = mapped_column(String(1600))
    target_revision_no: Mapped[int] = mapped_column(Integer)
    policy_sha256: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(160), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MarketSourceSnapshot(Base):
    __tablename__ = "market_source_snapshots"
    __table_args__ = (
        UniqueConstraint("target_id", "content_sha256", name="uq_mkt_snapshot_target_content"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    market_id: Mapped[str] = mapped_column(String(120), index=True)
    target_id: Mapped[str] = mapped_column(String(120), index=True)
    capture_job_id: Mapped[str] = mapped_column(String(120), index=True)
    resolved_url: Mapped[str] = mapped_column(String(1600))
    http_status: Mapped[int | None] = mapped_column(Integer)
    response_headers_json: Mapped[str] = mapped_column(Text, default="{}")
    source_ip: Mapped[str | None] = mapped_column(String(80))
    mime_type: Mapped[str] = mapped_column(String(120))
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    normalized_text_sha256: Mapped[str] = mapped_column(String(64), index=True)
    normalized_text: Mapped[str] = mapped_column(Text)
    encrypted_content: Mapped[str | None] = mapped_column(Text)
    content_nonce: Mapped[str | None] = mapped_column(String(32))
    encrypted_dek: Mapped[str | None] = mapped_column(Text)
    dek_nonce: Mapped[str | None] = mapped_column(String(32))
    encryption_key_id: Mapped[str | None] = mapped_column(String(120), index=True)
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    policy_sha256: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(120))
    parser_digest: Mapped[str] = mapped_column(String(160))
    privacy_classification: Mapped[str] = mapped_column(String(40), default="PUBLIC")
    quarantine_state: Mapped[str] = mapped_column(String(40), default="CLEAN", index=True)
    storage_ref: Mapped[str | None] = mapped_column(String(1200))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(160), index=True)


class MarketEvidenceRedaction(Base):
    __tablename__ = "market_evidence_redactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    redaction_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    action: Mapped[str] = mapped_column(String(40))
    legal_basis: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(Text)
    actor_subject_id: Mapped[str] = mapped_column(String(160), index=True)
    reviewer_subject_id: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketAsset(Base):
    __tablename__ = "market_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    market_id: Mapped[str] = mapped_column(String(120), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    channel: Mapped[str] = mapped_column(String(60), index=True)
    asset_type: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(500))
    source_span_json: Mapped[str] = mapped_column(Text)
    claims_json: Mapped[str] = mapped_column(Text, default="[]")
    extraction_version: Mapped[str] = mapped_column(String(120))
    canonical_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketObservation(Base):
    __tablename__ = "market_observations"
    __table_args__ = (
        CheckConstraint(
            "evidence_level IN ('OBSERVED','INFERRED','VALIDATED_INTERNAL')",
            name="ck_mkt_observation_evidence",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    market_id: Mapped[str] = mapped_column(String(120), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    source_span_json: Mapped[str] = mapped_column(Text)
    statement: Mapped[str] = mapped_column(Text)
    evidence_level: Mapped[str] = mapped_column(String(40), index=True)
    method: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    canonical_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketVocSignal(Base):
    __tablename__ = "market_voc_signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    market_id: Mapped[str] = mapped_column(String(120), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(120), index=True)
    source_span_json: Mapped[str] = mapped_column(Text)
    masked_quote: Mapped[str] = mapped_column(Text)
    theme: Mapped[str] = mapped_column(String(160), index=True)
    sentiment: Mapped[str | None] = mapped_column(String(40))
    canonical_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketPatternCluster(Base):
    __tablename__ = "market_pattern_clusters"
    __table_args__ = (
        UniqueConstraint("family_id", "revision_no", name="uq_mkt_cluster_family_revision"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    family_id: Mapped[str] = mapped_column(String(120), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    market_id: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text)
    algorithm_version: Mapped[str] = mapped_column(String(120))
    member_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketResearchHypothesis(Base):
    __tablename__ = "market_research_hypotheses"
    id: Mapped[int] = mapped_column(primary_key=True)
    hypothesis_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    market_id: Mapped[str] = mapped_column(String(120), index=True)
    statement: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(String(255))
    supporting_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    contradicting_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    falsification_criterion: Mapped[str] = mapped_column(Text)
    evidence_level: Mapped[str] = mapped_column(String(40), default="INFERRED")
    canonical_sha256: Mapped[str] = mapped_column(String(64), index=True)
    owner_subject_id: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MarketValidation(Base):
    __tablename__ = "market_validations"
    id: Mapped[int] = mapped_column(primary_key=True)
    validation_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    market_id: Mapped[str] = mapped_column(String(120), index=True)
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str] = mapped_column(String(120), index=True)
    subject_sha256: Mapped[str] = mapped_column(String(64), index=True)
    method: Mapped[str] = mapped_column(Text)
    metric_json: Mapped[str] = mapped_column(Text, default="{}")
    sample_json: Mapped[str] = mapped_column(Text, default="{}")
    outcome: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    author_subject_id: Mapped[str] = mapped_column(String(160), index=True)
    reviewer_subject_id: Mapped[str | None] = mapped_column(String(160))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketResearchPack(Base):
    __tablename__ = "market_research_packs"
    __table_args__ = (
        UniqueConstraint("family_id", "revision_no", name="uq_mkt_pack_family_revision"),
        CheckConstraint(
            "status IN ('DRAFT','IN_REVIEW','APPROVED','FROZEN','HANDED_OFF','EXPIRED',"
            "'REVOKED','SUPERSEDED','CHANGES_REQUESTED','REJECTED')",
            name="ck_mkt_pack_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    family_id: Mapped[str] = mapped_column(String(120), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    sequence_no: Mapped[int] = mapped_column(Integer)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    market_id: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    summary: Mapped[str] = mapped_column(Text)
    intended_use: Mapped[str] = mapped_column(String(255))
    channels_json: Mapped[str] = mapped_column(Text, default="[]")
    member_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    manifest_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    author_subject_id: Mapped[str] = mapped_column(String(160), index=True)
    reviewer_subject_id: Mapped[str | None] = mapped_column(String(160))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    frozen_by: Mapped[str | None] = mapped_column(String(160))
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MarketPackHandoff(Base):
    __tablename__ = "market_pack_handoffs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_mkt_handoff_idempotency"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    handoff_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    market_id: Mapped[str] = mapped_column(String(120), index=True)
    pack_id: Mapped[str] = mapped_column(String(120), index=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64), index=True)
    downstream_purpose: Mapped[str] = mapped_column(String(120), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="ACCEPTED", index=True)
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketHandoffWatermark(Base):
    __tablename__ = "market_handoff_watermarks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "brand_id",
            "market_id",
            "downstream_purpose",
            name="uq_mkt_handoff_watermark_scope",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    market_id: Mapped[str] = mapped_column(String(120), index=True)
    downstream_purpose: Mapped[str] = mapped_column(String(120), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    pack_id: Mapped[str] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MarketPermissionGrant(Base):
    __tablename__ = "market_permission_grants"
    __table_args__ = (
        UniqueConstraint(
            "subject_id",
            "permission",
            "scope_key",
            "effect",
            "revision",
            name="uq_mkt_permission_revision",
        ),
        CheckConstraint("effect IN ('allow','deny')", name="ck_mkt_permission_effect"),
        CheckConstraint("scope_type IN ('global','brand_market')", name="ck_mkt_permission_scope"),
        CheckConstraint(
            "status IN ('active','revoked','expired')", name="ck_mkt_permission_status"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    grant_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    subject_id: Mapped[str] = mapped_column(String(140), index=True)
    permission: Mapped[str] = mapped_column(String(100), index=True)
    effect: Mapped[str] = mapped_column(String(10), index=True)
    scope_type: Mapped[str] = mapped_column(String(20), index=True)
    scope_key: Mapped[str] = mapped_column(String(500), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(120), index=True)
    brand_id: Mapped[str | None] = mapped_column(String(120), index=True)
    market_id: Mapped[str | None] = mapped_column(String(120), index=True)
    revision: Mapped[str] = mapped_column(String(100))
    claim_sequence: Mapped[int] = mapped_column(Integer, index=True)
    claim_issuer: Mapped[str] = mapped_column(String(255))
    claim_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebsitePublicationIncident(Base):
    __tablename__ = "website_publication_incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    release_id: Mapped[str] = mapped_column(String(120), index=True)
    target_id: Mapped[str | None] = mapped_column(String(120), index=True)
    severity: Mapped[str] = mapped_column(String(30), default="critical", index=True)
    incident_type: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text)
    rollback_action: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnswerKnowledgeSource(Base):
    __tablename__ = "answer_knowledge_sources"
    __table_args__ = (
        UniqueConstraint("canonical_ref", "version", name="uq_answer_source_ref_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    source_type: Mapped[str] = mapped_column(String(60), index=True)
    canonical_ref: Mapped[str] = mapped_column(String(1200), index=True)
    version: Mapped[str] = mapped_column(String(100))
    domain: Mapped[str] = mapped_column(String(60), index=True)
    visibility: Mapped[str] = mapped_column(String(40), default="internal", index=True)
    allowed_roles_json: Mapped[str] = mapped_column(Text, default="[]")
    project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    owner_role: Mapped[str] = mapped_column(String(60), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(String(255))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AnswerKnowledgeExcerpt(Base):
    __tablename__ = "answer_knowledge_excerpts"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "locator", "excerpt_sha256", name="uq_answer_excerpt_source_locator_hash"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    excerpt_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_id: Mapped[str] = mapped_column(String(120), index=True)
    locator: Mapped[str] = mapped_column(String(500))
    excerpt_text: Mapped[str] = mapped_column(Text)
    excerpt_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnswerQuestion(Base):
    __tablename__ = "answer_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    question_text: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(60), index=True)
    channel: Mapped[str] = mapped_column(String(40), default="internal", index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    customer_reference: Mapped[str | None] = mapped_column(String(255), index=True)
    asked_by: Mapped[str] = mapped_column(String(255), index=True)
    asker_role: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    assigned_role: Mapped[str] = mapped_column(String(60), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnswerVersion(Base):
    __tablename__ = "answer_versions"
    __table_args__ = (
        UniqueConstraint("question_id", "version", name="uq_answer_question_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    answer_version_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    question_id: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer)
    answer_text: Mapped[str] = mapped_column(Text)
    answer_sha256: Mapped[str] = mapped_column(String(64), index=True)
    certainty: Mapped[str] = mapped_column(String(30), index=True)
    source_conflict: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnswerCitation(Base):
    __tablename__ = "answer_citations"
    __table_args__ = (
        UniqueConstraint("answer_version_id", "claim_key", name="uq_answer_citation_claim"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    citation_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    answer_version_id: Mapped[str] = mapped_column(String(120), index=True)
    claim_key: Mapped[str] = mapped_column(String(160))
    claim_text: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(String(120), index=True)
    source_version: Mapped[str] = mapped_column(String(100))
    source_content_sha256: Mapped[str] = mapped_column(String(64))
    excerpt_id: Mapped[str] = mapped_column(String(120), index=True)
    excerpt_sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnswerReview(Base):
    __tablename__ = "answer_reviews"
    __table_args__ = (
        UniqueConstraint("answer_version_id", "reviewer_role", name="uq_answer_review_role"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    answer_version_id: Mapped[str] = mapped_column(String(120), index=True)
    reviewer_role: Mapped[str] = mapped_column(String(60), index=True)
    decision: Mapped[str] = mapped_column(String(30), index=True)
    note: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnswerPublication(Base):
    __tablename__ = "answer_publications"
    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    answer_version_id: Mapped[str] = mapped_column(String(120), index=True)
    audience: Mapped[str] = mapped_column(String(40), index=True)
    destination: Mapped[str] = mapped_column(String(100), index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), index=True)
    publication_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="published", index=True)
    published_by: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    retracted_by: Mapped[str | None] = mapped_column(String(255))
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retraction_reason: Mapped[str | None] = mapped_column(Text)


class B2BProjectIntake(Base):
    __tablename__ = "b2b_project_intakes"
    __table_args__ = (
        UniqueConstraint("source_system", "source_external_id", name="uq_b2b_intake_source_key"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    intake_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_system: Mapped[str] = mapped_column(String(100), index=True)
    source_external_id: Mapped[str] = mapped_column(String(255))
    source_reference: Mapped[str] = mapped_column(String(1200))
    source_content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    lawful_basis: Mapped[str] = mapped_column(String(120))
    source_use_approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    linked_marketing_lead_id: Mapped[str | None] = mapped_column(String(120), index=True)
    organization_name: Mapped[str] = mapped_column(String(500), index=True)
    organization_name_normalized: Mapped[str] = mapped_column(String(500), index=True)
    tax_number: Mapped[str | None] = mapped_column(String(80), index=True)
    website_domain: Mapped[str | None] = mapped_column(String(255), index=True)
    contact_name: Mapped[str] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(String(255), index=True)
    contact_phone: Mapped[str | None] = mapped_column(String(80), index=True)
    project_type: Mapped[str] = mapped_column(String(80), index=True)
    country: Mapped[str] = mapped_column(String(100), default="HU")
    city: Mapped[str] = mapped_column(String(255), index=True)
    site_address: Mapped[str | None] = mapped_column(String(500))
    gross_floor_area_m2: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    planned_start: Mapped[DateValue | None] = mapped_column(Date, index=True)
    requested_deadline: Mapped[DateValue | None] = mapped_column(Date, index=True)
    estimated_budget_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    project_summary: Mapped[str] = mapped_column(Text)
    document_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    company_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    project_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    missing_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    base_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    complexity: Mapped[str] = mapped_column(String(30), default="medium", index=True)
    strategic_review_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="captured", index=True)
    signal_count: Mapped[int] = mapped_column(Integer, default=1)
    assigned_sales_email: Mapped[str | None] = mapped_column(String(255), index=True)
    canonical_record_id: Mapped[str | None] = mapped_column(String(120), index=True)
    crm_record_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    updated_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class B2BDuplicateMatch(Base):
    __tablename__ = "b2b_duplicate_matches"
    __table_args__ = (
        UniqueConstraint(
            "intake_id", "candidate_intake_id", "match_scope", name="uq_b2b_duplicate_pair_scope"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    intake_id: Mapped[str] = mapped_column(String(120), index=True)
    candidate_intake_id: Mapped[str] = mapped_column(String(120), index=True)
    match_scope: Mapped[str] = mapped_column(String(40), index=True)
    match_score: Mapped[int] = mapped_column(Integer, index=True)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class B2BTechnicalReview(Base):
    __tablename__ = "b2b_technical_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    intake_id: Mapped[str] = mapped_column(String(120), index=True)
    decision: Mapped[str] = mapped_column(String(30), index=True)
    delivery_model: Mapped[str] = mapped_column(String(80))
    capacity_fit: Mapped[str] = mapped_column(String(30))
    site_feasibility: Mapped[str] = mapped_column(String(30))
    complexity: Mapped[str] = mapped_column(String(30))
    assumptions_json: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class B2BFinancialReview(Base):
    __tablename__ = "b2b_financial_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    intake_id: Mapped[str] = mapped_column(String(120), index=True)
    decision: Mapped[str] = mapped_column(String(30), index=True)
    budget_credibility: Mapped[str] = mapped_column(String(30))
    funding_status: Mapped[str] = mapped_column(String(40))
    preliminary_margin_band: Mapped[str] = mapped_column(String(40))
    assumptions_json: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class B2BQualificationDecision(Base):
    __tablename__ = "b2b_qualification_decisions"
    __table_args__ = (UniqueConstraint("intake_id", "decision_type", name="uq_b2b_decision_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    intake_id: Mapped[str] = mapped_column(String(120), index=True)
    decision_type: Mapped[str] = mapped_column(String(40), index=True)
    decision: Mapped[str] = mapped_column(String(30), index=True)
    route: Mapped[str] = mapped_column(String(80))
    next_action: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[str] = mapped_column(String(255), index=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class B2BCRMDelivery(Base):
    __tablename__ = "b2b_crm_deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    intake_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    external_crm_id: Mapped[str | None] = mapped_column(String(255), index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    queued_by: Mapped[str] = mapped_column(String(255))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    receipt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MaterialLot(Base):
    __tablename__ = "ops_material_lots"
    id: Mapped[int] = mapped_column(primary_key=True)
    lot_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    delivery_note_id: Mapped[str | None] = mapped_column(String(120), index=True)
    material: Mapped[str] = mapped_column(String(500), index=True)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    current_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    unit: Mapped[str] = mapped_column(String(40), default="db")
    storage_location: Mapped[str | None] = mapped_column(String(255))
    planned_use_location: Mapped[str | None] = mapped_column(String(255))
    actual_use_location: Mapped[str | None] = mapped_column(String(255))
    custodian: Mapped[str | None] = mapped_column(String(255))
    weather_protection: Mapped[str] = mapped_column(String(40), default="not_checked")
    evidence_url: Mapped[str | None] = mapped_column(String(1200))
    status: Mapped[str] = mapped_column(String(40), default="in_stock", index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MaterialMovement(Base):
    __tablename__ = "ops_material_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    movement_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    lot_id: Mapped[str] = mapped_column(String(120), index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    movement_type: Mapped[str] = mapped_column(String(50), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    from_location: Mapped[str | None] = mapped_column(String(255))
    to_location: Mapped[str | None] = mapped_column(String(255))
    responsible: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MaterialUsageControl(Base):
    __tablename__ = "ops_material_usage_controls"
    id: Mapped[int] = mapped_column(primary_key=True)
    control_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    work_package_id: Mapped[str | None] = mapped_column(String(120), index=True)
    lot_id: Mapped[str | None] = mapped_column(String(120), index=True)
    subcontractor: Mapped[str | None] = mapped_column(String(500))
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    waste_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0"))
    allowed_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    actual_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    unit: Mapped[str] = mapped_column(String(40), default="db")
    unit_cost_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    damage_huf: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    decision_status: Mapped[str] = mapped_column(String(40), default="review_required")
    contractual_basis: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PartnerFieldAccess(Base):
    __tablename__ = "ops_partner_field_access"
    id: Mapped[int] = mapped_column(primary_key=True)
    access_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(500), index=True)
    company_tax_number: Mapped[str | None] = mapped_column(String(50), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(80))
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    work_package_id: Mapped[str | None] = mapped_column(String(120), index=True)
    access_code_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attendance_required: Mapped[bool] = mapped_column(Boolean, default=True)
    can_report_changes: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PartnerWorker(Base):
    __tablename__ = "ops_partner_workers"
    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    access_id: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str | None] = mapped_column(String(120))
    external_identifier: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PartnerAttendance(Base):
    __tablename__ = "ops_partner_attendance"
    __table_args__ = (
        UniqueConstraint(
            "worker_id", "project_id", "work_date", name="uq_ops_partner_attendance_day"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    attendance_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    access_id: Mapped[str] = mapped_column(String(120), index=True)
    worker_id: Mapped[str] = mapped_column(String(120), index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    work_package_id: Mapped[str | None] = mapped_column(String(120), index=True)
    work_date: Mapped[DateValue] = mapped_column(Date, index=True)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_in_latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    check_in_longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    check_out_latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    check_out_longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    location_accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    source_device_id: Mapped[str | None] = mapped_column(String(255))
    declaration_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PartnerProgressReport(Base):
    __tablename__ = "ops_partner_progress_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    progress_report_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    access_id: Mapped[str] = mapped_column(String(120), index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    work_package_id: Mapped[str | None] = mapped_column(String(120), index=True)
    report_date: Mapped[DateValue] = mapped_column(Date, index=True)
    reported_progress_pct: Mapped[int | None] = mapped_column(Integer)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit: Mapped[str | None] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text)
    problem_text: Mapped[str | None] = mapped_column(Text)
    safety_note: Mapped[str | None] = mapped_column(Text)
    quality_note: Mapped[str | None] = mapped_column(Text)
    source_device_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="pending_review", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PartnerChangeNotice(Base):
    __tablename__ = "ops_partner_change_notices"
    id: Mapped[int] = mapped_column(primary_key=True)
    change_notice_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    access_id: Mapped[str] = mapped_column(String(120), index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    work_package_id: Mapped[str | None] = mapped_column(String(120), index=True)
    change_type: Mapped[str] = mapped_column(String(80), default="scope", index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    deadline_impact_days: Mapped[int] = mapped_column(Integer, default=0)
    source_device_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="reported", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PartnerEvidence(Base):
    __tablename__ = "ops_partner_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    access_id: Mapped[str] = mapped_column(String(120), index=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    work_package_id: Mapped[str | None] = mapped_column(String(120), index=True)
    progress_report_id: Mapped[str | None] = mapped_column(String(120), index=True)
    issue_id: Mapped[str | None] = mapped_column(String(120), index=True)
    change_notice_id: Mapped[str | None] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(80), default="progress", index=True)
    file_name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(1200))
    caption: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    source_device_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DevelopmentDiscoveryRecord(Base):
    __tablename__ = "cc_development_discovery"
    id: Mapped[int] = mapped_column(primary_key=True)
    discovery_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    requested_capability: Mapped[str] = mapped_column(String(500), index=True)
    requested_module_key: Mapped[str | None] = mapped_column(String(100), index=True)
    searched_terms_json: Mapped[str] = mapped_column(Text, default="[]")
    candidate_artifacts_json: Mapped[str] = mapped_column(Text, default="[]")
    canonical_module_key: Mapped[str | None] = mapped_column(String(100), index=True)
    canonical_object_owner: Mapped[str | None] = mapped_column(String(255))
    source_version: Mapped[str | None] = mapped_column(String(80))
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(40), index=True)
    implementation_gap: Mapped[str] = mapped_column(Text)
    exception_reason: Mapped[str | None] = mapped_column(Text)
    exception_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default="pending_review", index=True)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
