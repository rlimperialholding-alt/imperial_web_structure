from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
            "recipient_role IN ('listing_agent','property_owner','unknown')",
            name="ck_growth_signal_recipient_role",
        ),
        CheckConstraint(
            "status IN ('accepted','rejected','blocked','queued',"
            "'contacted','responded','suppressed','template-variable-missing')",
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
    recipient_organization_name: Mapped[str | None] = mapped_column(String(500), index=True)
    recipient_office_name: Mapped[str | None] = mapped_column(String(500), index=True)
    subject_type: Mapped[str] = mapped_column(String(30), index=True)
    recipient_role: Mapped[str] = mapped_column(String(30), default="unknown", index=True)
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
    body_html: Mapped[str | None] = mapped_column(Text)
    unsubscribe_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), index=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    release_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    release_approved_by: Mapped[str | None] = mapped_column(String(255))
    release_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class CanonicalGrowthDailyRun(Base):
    __tablename__ = "canonical_growth_daily_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','full','partial','blocked','failed')",
            name="ck_canonical_growth_daily_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    local_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    spec_version: Mapped[str] = mapped_column(String(120), index=True)
    source_manifest_sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_route_catalog_size: Mapped[int] = mapped_column(Integer, default=0)
    route_attempts: Mapped[int] = mapped_column(Integer, default=0)
    unique_leads: Mapped[int] = mapped_column(Integer, default=0)
    question_topics: Mapped[int] = mapped_column(Integer, default=0)
    content_brands: Mapped[int] = mapped_column(Integer, default=0)
    iora_opportunities: Mapped[int] = mapped_column(Integer, default=0)
    etdr_new_or_changed: Mapped[int] = mapped_column(Integer, default=0)
    etdr_start_not_verified: Mapped[int] = mapped_column(Integer, default=0)
    etdr_completion_not_verified: Mapped[int] = mapped_column(Integer, default=0)
    internal_handoff_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    external_publication_status: Mapped[str] = mapped_column(
        String(40), default="blocked", index=True
    )
    external_outreach_status: Mapped[str] = mapped_column(String(40), default="blocked", index=True)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    gate_errors_json: Mapped[str] = mapped_column(Text, default="[]")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailyContentObligation(Base):
    __tablename__ = "daily_content_obligations"
    __table_args__ = (
        UniqueConstraint("local_date", "brand_id", name="uq_daily_content_brand"),
        CheckConstraint(
            "status IN ('pending','drafted','quarantined','release_passed','published','failed')",
            name="ck_daily_content_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    local_date: Mapped[date] = mapped_column(Date, index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    content_asset_id: Mapped[str | None] = mapped_column(String(120), index=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    release_token_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class QuestionRadarTopic(Base):
    __tablename__ = "question_radar_topics"
    __table_args__ = (
        UniqueConstraint("local_date", "dedupe_hash", name="uq_question_radar_daily_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    local_date: Mapped[date] = mapped_column(Date, index=True)
    question: Mapped[str] = mapped_column(Text)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    use_case: Mapped[str] = mapped_column(String(120), index=True)
    source_url: Mapped[str | None] = mapped_column(String(1500))
    classification: Mapped[str] = mapped_column(String(40), default="observed")
    dedupe_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuestionRadarAnswer(Base):
    __tablename__ = "question_radar_answers"
    __table_args__ = (
        UniqueConstraint("topic_id", name="uq_question_radar_answer_topic"),
        CheckConstraint(
            "status IN ('ineligible','quarantined','release_ready','channel_blocked','published','failed')",
            name="ck_question_radar_answer_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    topic_id: Mapped[str] = mapped_column(String(120), index=True)
    local_date: Mapped[date] = mapped_column(Date, index=True)
    brand_id: Mapped[str] = mapped_column(String(120), index=True)
    source_url: Mapped[str | None] = mapped_column(String(1500))
    source_host: Mapped[str | None] = mapped_column(String(500), index=True)
    disclosure_text: Mapped[str | None] = mapped_column(Text)
    answer_text: Mapped[str | None] = mapped_column(Text)
    answer_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    eligibility_json: Mapped[str] = mapped_column(Text, default="{}")
    review_manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    publication_job_id: Mapped[str | None] = mapped_column(String(120), index=True)
    public_url: Mapped[str | None] = mapped_column(String(1500))
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CanonicalLLMUsage(Base):
    __tablename__ = "canonical_llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(120), index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(120), index=True)
    purpose: Mapped[str] = mapped_column(String(80), index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    response_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="completed", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceCatalogRevision(Base):
    __tablename__ = "source_catalog_revisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('importing','active','retired','failed')",
            name="ck_source_catalog_revision_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    spreadsheet_id: Mapped[str] = mapped_column(String(120), index=True)
    sheet_id: Mapped[int] = mapped_column(Integer, index=True)
    source_modified_time: Mapped[str] = mapped_column(String(80))
    catalog_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    route_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="importing", index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceCoverageRoute(Base):
    __tablename__ = "source_coverage_routes"
    __table_args__ = (
        UniqueConstraint("route_id", name="uq_source_coverage_route_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    route_key: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    route_id: Mapped[str] = mapped_column(String(180), index=True)
    catalog_sha256: Mapped[str] = mapped_column(String(64), index=True)
    motor: Mapped[str] = mapped_column(String(160), index=True)
    catalog_part: Mapped[str | None] = mapped_column(String(160), index=True)
    country: Mapped[str | None] = mapped_column(String(120), index=True)
    brand_fit: Mapped[str | None] = mapped_column(String(240), index=True)
    category: Mapped[str | None] = mapped_column(String(240), index=True)
    source_name: Mapped[str | None] = mapped_column(String(500))
    source_type: Mapped[str | None] = mapped_column(String(120), index=True)
    search_signal: Mapped[str | None] = mapped_column(Text)
    route_url: Mapped[str] = mapped_column(String(3000))
    base_url: Mapped[str | None] = mapped_column(String(3000))
    route_mode: Mapped[str | None] = mapped_column(String(80), index=True)
    priority: Mapped[str | None] = mapped_column(String(80), index=True)
    validation: Mapped[str | None] = mapped_column(String(120), index=True)
    catalog_status: Mapped[str | None] = mapped_column(String(120), index=True)
    source_updated_value: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    source_row_sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_record_json: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[str | None] = mapped_column(String(80), index=True)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SourceCoverageAttempt(Base):
    __tablename__ = "source_coverage_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded','blocked','failed','rejected')",
            name="ck_source_coverage_attempt_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    route_key: Mapped[str] = mapped_column(String(500), index=True)
    catalog_sha256: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, index=True)
    response_sha256: Mapped[str | None] = mapped_column(String(64))
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    analysis_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    analysis_json: Mapped[str] = mapped_column(Text, default="{}")
    analysis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    error_type: Mapped[str | None] = mapped_column(String(120), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CanonicalInternalHandoff(Base):
    __tablename__ = "canonical_internal_handoffs"
    __table_args__ = (
        UniqueConstraint("local_date", "handoff_type", name="uq_canonical_handoff_day_type"),
        CheckConstraint(
            "status IN ('pending','sent','failed','blocked')",
            name="ck_canonical_handoff_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    handoff_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    local_date: Mapped[date] = mapped_column(Date, index=True)
    handoff_type: Mapped[str] = mapped_column(String(80), default="daily_executive", index=True)
    recipient_email: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500))
    body_text: Mapped[str] = mapped_column(Text)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    counts_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    provider_message_id: Mapped[str | None] = mapped_column(String(500), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
