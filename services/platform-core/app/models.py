from __future__ import annotations

from datetime import date as DateValue
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "cc_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="operator")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectObjectState(Base):
    __tablename__ = "cc_project_object_states"
    __table_args__ = (UniqueConstraint("project_id", "source_module", "object_type", "object_id", name="uq_cc_object_state"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    source_module: Mapped[str] = mapped_column(String(100), index=True)
    object_type: Mapped[str] = mapped_column(String(100))
    object_id: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(50))
    summary: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    last_event_id: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProjectFact(Base):
    __tablename__ = "cc_project_facts"
    __table_args__ = (UniqueConstraint("project_id", "source_module", "fact_key", name="uq_cc_project_fact"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    source_module: Mapped[str] = mapped_column(String(100), index=True)
    fact_key: Mapped[str] = mapped_column(String(150), index=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReleaseRecord(Base):
    __tablename__ = "cc_releases"
    __table_args__ = (UniqueConstraint("module_key", "version", name="uq_cc_release_module_version"),)
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    artifacts: Mapped[list["ArtifactRecord"]] = relationship(back_populates="release", cascade="all, delete-orphan")


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
        CheckConstraint("module_key IN ('housebuild-agent','plotcheck','buildconfig','plancheck')", name="ck_cc_technical_case_module"),
        CheckConstraint("status IN ('draft','review','approved','rejected')", name="ck_cc_technical_case_status"),
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TechnicalGate(Base):
    __tablename__ = "cc_technical_gates"
    __table_args__ = (
        UniqueConstraint("case_id", "gate_key", name="uq_cc_technical_gate_case_key"),
        CheckConstraint("status IN ('pending','pass','fail','not_applicable')", name="ck_cc_technical_gate_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cc_technical_cases.case_id", ondelete="CASCADE"), index=True)
    gate_key: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(255))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    evidence: Mapped[str | None] = mapped_column(Text)
    checked_by: Mapped[str | None] = mapped_column(String(255))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CampaignStrategyReviewRecord(Base):
    __tablename__ = "cq_strategy_reviews"
    review_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    copy_brief_id: Mapped[str] = mapped_column(ForeignKey("cq_copy_briefs.copy_brief_id", ondelete="CASCADE"), unique=True, index=True)
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
            "state NOT IN ('PUBLISHED', 'LIVE_QA', 'QUARANTINED') OR (gate_1_approved = true AND expert_language_approved = true AND expert_marketing_approved = true AND copywriter_approved = true AND four_gate_approved = true AND creative_director_approved = true AND assembly_approved = true AND release_approved = true AND active_bundle_id IS NOT NULL AND (source_prevalidated = true OR (editorial_approved = true AND owner_approved = true)) AND publication_proof_id IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_cq_published_requires_all_approvals",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    copy_brief_id: Mapped[str] = mapped_column(ForeignKey("cq_copy_briefs.copy_brief_id"), index=True)
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
    release_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    live_review_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    active_bundle_id: Mapped[str | None] = mapped_column(String(120), index=True)
    latest_run_id: Mapped[str | None] = mapped_column(String(120), index=True)
    publication_proof_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    run_id: Mapped[str] = mapped_column(ForeignKey("cq_review_runs.run_id", ondelete="CASCADE"), index=True)
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
    __table_args__ = (UniqueConstraint("asset_id", "content_version", "approval_type", name="uq_cq_asset_version_approval"),)
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
    __table_args__ = (UniqueConstraint("asset_id", "sequence_number", name="uq_cq_creative_asset_sequence"),)
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
    __table_args__ = (UniqueConstraint("asset_id", "content_version", "stage", "reviewer_run_id", name="uq_cq_workflow_stage_run"),)
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
    visual_generation_run_id: Mapped[str] = mapped_column(ForeignKey("cq_creative_runs.generation_run_id"), index=True)
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EnterpriseCanonicalRecord(Base):
    __tablename__ = "ic_canonical_records"
    __table_args__ = (UniqueConstraint("domain", "entity_type", "external_key", name="uq_ic_canonical_business_key"),)
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MailSuppression(Base):
    __tablename__ = "tm_suppressions"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    reason: Mapped[str] = mapped_column(String(80), index=True)
    source: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PMGateCheck(Base):
    __tablename__ = "ops_pm_gate_checks"
    __table_args__ = (UniqueConstraint("project_id", "work_package_id", "gate_code", name="uq_ops_gate_scope"),)
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SiteDailyReport(Base):
    __tablename__ = "ops_site_daily_reports"
    __table_args__ = (UniqueConstraint("project_id", "report_date", name="uq_ops_daily_project_date"),)
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    __table_args__ = (UniqueConstraint("worker_id", "project_id", "work_date", name="uq_ops_partner_attendance_day"),)
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
