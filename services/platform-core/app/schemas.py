from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EventIn(BaseModel):
    event_id: str = Field(min_length=3, max_length=120)
    dedupe_key: str = Field(min_length=3, max_length=255)
    project_id: str = Field(min_length=3, max_length=100)
    source_module: str = Field(min_length=2, max_length=100)
    event_type: str = Field(min_length=3, max_length=100)
    object_type: str | None = None
    object_id: str | None = None
    severity: str = "info"
    status: str = "open"
    financial_impact_huf: Decimal = Decimal("0")
    deadline_impact_days: int = 0
    responsible: str | None = None
    next_action: str | None = None
    executive_relevance: bool = False
    evidence_url: str | None = None
    occurred_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    route_to: list[str] = Field(default_factory=list)


class HeartbeatIn(BaseModel):
    module_key: str
    version: str
    status: str = "healthy"
    details: dict[str, Any] = Field(default_factory=dict)


class ModuleBusinessRecordIn(BaseModel):
    record_type: str | None = Field(default=None, max_length=100)
    title: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    status: str | None = Field(default=None, max_length=50)
    project_id: str | None = Field(default=None, max_length=100)
    customer_reference: str | None = Field(default=None, max_length=255)
    assignee: str | None = Field(default=None, max_length=255)
    priority: str = Field(default="normal", pattern="^(low|normal|high|critical)$")
    due_at: datetime | None = None
    amount_huf: Decimal = Field(default=Decimal("0"))
    data: dict[str, Any] = Field(default_factory=dict)


class ModuleBusinessRecordUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    status: str | None = Field(default=None, max_length=50)
    project_id: str | None = Field(default=None, max_length=100)
    customer_reference: str | None = Field(default=None, max_length=255)
    assignee: str | None = Field(default=None, max_length=255)
    priority: str | None = Field(default=None, pattern="^(low|normal|high|critical)$")
    due_at: datetime | None = None
    amount_huf: Decimal | None = None
    data: dict[str, Any] | None = None
    archived: bool | None = None


class ModuleBusinessCommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ModuleBusinessApprovalIn(BaseModel):
    stage: str = Field(default="business_approval", min_length=2, max_length=100)
    decision: str = Field(default="pending", pattern="^(pending|approved|rejected)$")
    note: str | None = Field(default=None, max_length=5000)


class ModuleBusinessTransitionIn(BaseModel):
    action_id: str = Field(min_length=2, max_length=100)
    project_id: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=5000)


class FactIn(BaseModel):
    project_id: str
    source_module: str
    fact_key: str
    value: Any


class ReleaseIn(BaseModel):
    release_id: str
    module_key: str
    version: str
    tests_total: int = 0
    tests_passed: int = 0
    migration_tested: bool = False
    uat_approved: bool = False
    security_reviewed: bool = False
    backup_restore_tested: bool = False
    owner_approved: bool = False
    package_sha256: str | None = None
    discovery_request_id: str | None = None


class ArtifactIn(BaseModel):
    artifact_id: str
    artifact_type: str
    file_name: str
    local_path: str | None = None
    file_size: int | None = None
    sha256: str | None = None
    cloud_status: str = "pending"
    drive_file_id: str | None = None
    drive_url: str | None = None


class EnvironmentIn(BaseModel):
    environment_key: str
    name: str
    base_url: str | None = None
    database_type: str | None = None
    sso_enabled: bool = False
    https_enabled: bool = False
    backup_enabled: bool = False
    monitoring_enabled: bool = False
    status: str = "planned"


class ImportSourceIn(BaseModel):
    source_key: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=255)
    source_type: str = Field(min_length=2, max_length=50)
    domain_scope: str = "enterprise"
    connector_reference: str | None = None
    query_or_path: str | None = None
    sync_mode: str = "manual"
    owner: str | None = None
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class ImportJobIn(BaseModel):
    source_key: str
    name: str
    domain_hint: str | None = None
    requested_by: str | None = None


class ImportItemIn(BaseModel):
    external_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    source_url: str | None = None
    sha256: str | None = None
    domain_hint: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)


class ImportPushIn(BaseModel):
    source_key: str
    external_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    source_url: str | None = None
    domain_hint: str | None = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportReviewIn(BaseModel):
    review_status: str
    canonical_name: str | None = None
    target_module: str | None = None
    project_id: str | None = None
    normalized: dict[str, Any] | None = None


class ImportCommitIn(BaseModel):
    staged_ids: list[str] = Field(default_factory=list)
    actor: str | None = None
    auto_approve_high_confidence: bool = False


class CalculationRequest(BaseModel):
    brand: str
    technology: str
    completion_level: str = "Kulcsrakész"
    package: str = "Alap"
    gross_area_m2: Decimal = Decimal("100")
    vat_rate: Decimal = Decimal("0.05")


class TechnicalCaseIn(BaseModel):
    module_key: str = Field(min_length=3, max_length=50)
    project_id: str = Field(min_length=3, max_length=100)
    title: str = Field(min_length=2, max_length=255)
    assigned_to: str | None = Field(default=None, max_length=255)
    input: dict[str, Any] = Field(default_factory=dict)


class TechnicalGateReviewIn(BaseModel):
    status: str = Field(pattern="^(pass|fail|not_applicable)$")
    evidence: str = Field(min_length=3, max_length=5000)


class TechnicalVariantSelectionIn(BaseModel):
    variant_id: str = Field(min_length=8, max_length=160)


class TechnicalDecisionIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    reason: str = Field(default="", max_length=5000)


class HouseCatalogVersionIn(BaseModel):
    house_id: str = Field(min_length=2, max_length=120)
    brand: str = Field(min_length=2, max_length=120)
    canonical_name: str = Field(min_length=2, max_length=255)
    catalog_price_huf: Decimal = Field(gt=0)
    gross_area_m2: Decimal = Field(gt=0, le=1000)
    rooms: str = Field(min_length=1, max_length=120)
    price_status: str = Field(min_length=2, max_length=80)
    data_quality: str = Field(min_length=2, max_length=80)
    lifestyles: list[str] = Field(default_factory=list, max_length=50)
    source_type: str = Field(min_length=2, max_length=100)
    source_url: str = Field(min_length=8, max_length=1000)
    source_verified_at: str = Field(min_length=4, max_length=120)
    rights_evidence: str = Field(min_length=8, max_length=10000)
    technical_summary: str = Field(min_length=10, max_length=20000)
    change_summary: str = Field(min_length=5, max_length=10000)


class HouseCatalogReviewIn(BaseModel):
    gate: str = Field(pattern="^(source|technical|commercial)$")
    decision: str = Field(pattern="^(approve|reject)$")
    note: str = Field(min_length=10, max_length=5000)


class HouseCatalogWithdrawIn(BaseModel):
    reason: str = Field(min_length=10, max_length=5000)


class EngineeringCaseIn(BaseModel):
    project_id: str = Field(min_length=3, max_length=100)
    title: str = Field(min_length=3, max_length=255)
    lead_designer: str = Field(min_length=5, max_length=255)
    project_manager: str = Field(min_length=5, max_length=255)
    contract_date: date


class EngineeringDeliverableIn(BaseModel):
    discipline: str = Field(min_length=2, max_length=80)
    deliverable_code: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=3, max_length=255)
    document_type: str = Field(min_length=2, max_length=100)
    responsible: str = Field(min_length=5, max_length=255)
    due_at: datetime
    required: bool = True


class EngineeringRevisionIn(BaseModel):
    source_document_id: str = Field(min_length=3, max_length=160)
    source_version: str = Field(min_length=1, max_length=80)
    source_url: str = Field(min_length=8, max_length=1000)
    file_name: str = Field(min_length=3, max_length=500)
    mime_type: str = Field(min_length=3, max_length=120)
    file_size: int = Field(gt=0, le=2_000_000_000)
    content_sha256: str = Field(pattern="^[0-9a-fA-F]{64}$")
    change_summary: str = Field(min_length=10, max_length=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EngineeringRevisionReviewIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    note: str = Field(min_length=10, max_length=5000)


class EngineeringFindingIn(BaseModel):
    revision_id: str = Field(min_length=3, max_length=160)
    category: str = Field(min_length=2, max_length=100)
    severity: str = Field(pattern="^(low|medium|high|critical)$")
    blocking: bool = True
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=10, max_length=10000)
    location: str | None = Field(default=None, max_length=500)
    responsible: str = Field(min_length=5, max_length=255)
    due_at: datetime
    source_module: str = Field(default="plancheck", min_length=2, max_length=100)
    source_fingerprint: str = Field(min_length=8, max_length=255)


class EngineeringFindingResolutionIn(BaseModel):
    resolution_revision_id: str = Field(min_length=3, max_length=160)
    note: str = Field(min_length=10, max_length=5000)


class EngineeringTransmittalIn(BaseModel):
    purpose: str = Field(pattern="^(review|information|construction|authority|supersession)$")
    subject: str = Field(min_length=3, max_length=255)
    recipient_name: str = Field(min_length=2, max_length=255)
    recipient_email: str = Field(min_length=5, max_length=320)
    message: str = Field(min_length=10, max_length=10000)
    revision_ids: list[str] = Field(min_length=1, max_length=100)


class EngineeringTransmittalAckIn(BaseModel):
    decision: str = Field(pattern="^(acknowledge|reject)$")
    note: str = Field(min_length=5, max_length=5000)


class ProjectControlBaselineIn(BaseModel):
    project_id: str = Field(min_length=2, max_length=100)
    scope_document_id: str = Field(min_length=2, max_length=160)
    scope_version: str = Field(min_length=1, max_length=80)
    scope_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    planned_start: date
    planned_end: date
    note: str = Field(min_length=10, max_length=4000)


class ProjectControlBaselineReviewIn(BaseModel):
    gate: Literal["technical", "finance"]
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=5, max_length=2000)


class ProjectControlLeadershipDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=5, max_length=2000)


class ProjectControlForecastIn(BaseModel):
    as_of_date: date
    forecast_completion_date: date
    note: str = Field(min_length=10, max_length=4000)


class ProjectControlFinanceReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=5, max_length=2000)


class ProjectControlVarianceClassifyIn(BaseModel):
    root_cause: Literal[
        "price", "quantity", "productivity", "design", "change", "defect", "delay", "scope", "other"
    ]
    note: str = Field(min_length=5, max_length=2000)


class ProjectControlRecoveryActionIn(BaseModel):
    title: str = Field(min_length=5, max_length=255)
    owner: str = Field(min_length=3, max_length=255)
    due_at: datetime
    target_amount_net: Decimal = Field(default=Decimal("0"), ge=0)
    target_days: int = Field(default=0, ge=0, le=3650)


class ProjectControlRecoveryCompleteIn(BaseModel):
    completion_note: str = Field(min_length=10, max_length=4000)
    evidence_url: str = Field(min_length=5, max_length=1000)


class ProjectControlRecoveryVerifyIn(BaseModel):
    decision: Literal["verify", "reject"]
    note: str = Field(min_length=5, max_length=2000)


class ProjectControlWeeklyReportIn(BaseModel):
    week_ending: date
    management_summary: str = Field(min_length=20, max_length=6000)


class ProjectControlWeeklyReportDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=5, max_length=2000)


class RenovationLineIn(BaseModel):
    item_id: str = Field(min_length=2, max_length=120)
    quantity: Decimal = Field(gt=0)


class RenovationCalculationIn(BaseModel):
    lines: list[RenovationLineIn] = Field(min_length=1)
    vat_rate: Decimal = Decimal("0.27")


class HouseMatchIn(BaseModel):
    budget_huf: Decimal = Field(gt=0)
    target_area_m2: Decimal = Field(gt=0)
    lifestyle: str | None = None
    allowed_brands: list[str] = Field(default_factory=list)
    score_profile: str = "Kiegyensúlyozott"
    limit: int = Field(default=6, ge=1, le=12)


class SendingDomainIn(BaseModel):
    domain_key: str
    domain_name: str
    from_email: str
    from_name: str = "Imperial Tender"
    provider: str = "provider_not_configured"
    max_hourly_rate: int = Field(default=100, ge=1, le=5000)


class DomainVerificationIn(BaseModel):
    spf_status: str
    dkim_status: str
    dmarc_status: str
    tracking_domain_status: str = "pending"
    warmup_status: str = "not_started"
    evidence: dict[str, Any] = Field(default_factory=dict)


class TenderCampaignIn(BaseModel):
    name: str
    domain_key: str
    subject_template: str
    text_template: str
    campaign_type: str = "tender_invitation"
    tender_id: str | None = None
    project_id: str | None = None
    hourly_rate: int = Field(default=100, ge=1, le=5000)
    created_by: str | None = None


class TenderRecipientIn(BaseModel):
    email: str
    company_name: str | None = None
    contact_name: str | None = None
    canonical_record_id: str | None = None
    personalization: dict[str, Any] = Field(default_factory=dict)


class TenderRecipientBatchIn(BaseModel):
    recipients: list[TenderRecipientIn] = Field(default_factory=list)
    include_canonical_partner_records: bool = False


class MailEventIn(BaseModel):
    provider_event_id: str | None = None
    recipient_id: str
    event_type: str
    occurred_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkspaceDocumentIn(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    project_id: str | None = None
    category: str = "other"
    source_system: str = "google_drive"
    source_url: str | None = None
    drive_file_id: str | None = None
    mime_type: str | None = None
    version_label: str | None = None
    approval_status: str = "draft"
    verification_status: str = "unverified"
    confidentiality: str = "internal"
    owner: str | None = None
    expires_at: datetime | None = None
    extracted_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskUpdateIn(BaseModel):
    status: str | None = None
    assignee: str | None = None
    due_at: datetime | None = None
    priority: str | None = None
    description: str | None = None


class CalendarEntryIn(BaseModel):
    project_id: str = Field(min_length=3, max_length=100)
    entry_type: str = Field(
        default="task",
        pattern="^(task|milestone|meeting|inspection|deadline|customer_decision|delivery)$",
    )
    title: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    starts_at: datetime
    ends_at: datetime
    all_day: bool = False
    assignee: str | None = Field(default=None, max_length=255)
    participants: list[str] = Field(default_factory=list)
    location: str | None = Field(default=None, max_length=500)
    priority: str = Field(default="normal", pattern="^(low|normal|high|critical)$")
    source_module: str = Field(default="smart-calendar", max_length=100)
    source_object_id: str | None = Field(default=None, max_length=160)
    contractual_deadline: bool = False
    capacity_hours: Decimal = Field(default=Decimal("0"), ge=0, le=24)
    create_task: bool = True
    conflict_override_reason: str | None = Field(default=None, max_length=5000)


class CalendarDependencyIn(BaseModel):
    predecessor_entry_id: str = Field(min_length=3, max_length=120)
    successor_entry_id: str = Field(min_length=3, max_length=120)
    dependency_type: str = Field(
        default="finish_to_start",
        pattern="^(finish_to_start|start_to_start|finish_to_finish)$",
    )
    lag_days: int = Field(default=0, ge=0, le=365)


class CalendarRescheduleIn(BaseModel):
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(min_length=3, max_length=5000)
    conflict_override_reason: str | None = Field(default=None, max_length=5000)
    expected_version: int | None = Field(default=None, ge=1)


class CalendarStatusIn(BaseModel):
    status: str = Field(pattern="^(confirmed|in_progress|completed|cancelled)$")
    note: str | None = Field(default=None, max_length=5000)
    expected_version: int | None = Field(default=None, ge=1)


class CalendarChangeRequestIn(BaseModel):
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(min_length=3, max_length=5000)
    impact_summary: str = Field(min_length=3, max_length=5000)
    expected_version: int | None = Field(default=None, ge=1)


class CalendarChangeDecisionIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    note: str = Field(min_length=3, max_length=5000)
    conflict_override_reason: str | None = Field(default=None, max_length=5000)
    expected_entry_version: int | None = Field(default=None, ge=1)


class BookingExperienceIn(BaseModel):
    experience_id: str = Field(min_length=3, max_length=120)
    brand_id: str = Field(min_length=2, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    display_name: str = Field(min_length=3, max_length=255)
    cta_label: str = Field(min_length=2, max_length=255)
    trust_copy: str = Field(min_length=3, max_length=10000)
    confirmation_copy: str = Field(min_length=3, max_length=10000)
    theme_key: str = Field(min_length=2, max_length=100)
    active: bool = False
    policy: dict[str, Any] = Field(default_factory=dict)


class BookingSlotIn(BaseModel):
    experience_id: str = Field(min_length=3, max_length=120)
    booking_type: str = Field(pattern="^(personal|online|site_visit)$")
    calendar_resource_id: str = Field(min_length=2, max_length=160)
    advisor_email: str = Field(min_length=5, max_length=255)
    starts_at: datetime
    ends_at: datetime
    location: str | None = Field(default=None, max_length=500)


class BookingCreateIn(BaseModel):
    slot_id: str = Field(min_length=3, max_length=120)
    project_id: str | None = Field(default=None, max_length=100)
    lead_id: str | None = Field(default=None, max_length=120)
    opportunity_id: str | None = Field(default=None, max_length=120)
    customer_name: str = Field(min_length=2, max_length=255)
    customer_email: str = Field(min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    customer_phone: str = Field(min_length=5, max_length=80)
    project_description: str = Field(min_length=10, max_length=10000)
    plot_status: str = Field(min_length=2, max_length=80)
    planned_start: str = Field(min_length=2, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)
    city: str | None = Field(default=None, max_length=120)
    street_address: str | None = Field(default=None, max_length=500)
    access_notes: str | None = Field(default=None, max_length=5000)
    document_url: str | None = Field(default=None, max_length=1000)
    consent_version_id: str = Field(min_length=3, max_length=120)
    consent: bool
    attribution: dict[str, Any] = Field(default_factory=dict)


class BookingCalendarSyncIn(BaseModel):
    success: bool
    calendar_event_id: str | None = Field(default=None, max_length=255)
    meeting_link: str | None = Field(default=None, max_length=1000)
    error: str | None = Field(default=None, max_length=5000)


class BookingRescheduleIn(BaseModel):
    new_slot_id: str = Field(min_length=3, max_length=120)
    reason: str = Field(min_length=3, max_length=5000)


class BookingOutcomeIn(BaseModel):
    status: str = Field(pattern="^(reminded|completed|no_show)$")
    note: str = Field(min_length=3, max_length=5000)


class VersionActivationIn(BaseModel):
    active: bool
    note: str = Field(min_length=3, max_length=5000)


class ReservationOfferIn(BaseModel):
    offer_version_id: str = Field(min_length=3, max_length=120)
    brand_id: str = Field(min_length=2, max_length=100)
    public_name: str = Field(min_length=3, max_length=255)
    cta_label: str = Field(min_length=2, max_length=255)
    reservation_amount_huf: Decimal = Field(ge=0)
    target_start_months_min: int = Field(default=6, ge=1, le=60)
    target_start_months_max: int = Field(default=12, ge=1, le=60)
    price_lock_months: int = Field(default=12, ge=1, le=60)
    price_snapshot_id: str = Field(min_length=3, max_length=120)
    terms_version_id: str = Field(min_length=3, max_length=120)
    technical_scope_version_id: str = Field(min_length=3, max_length=120)
    valid_from: datetime
    valid_to: datetime
    public_summary: str = Field(min_length=3, max_length=10000)
    exclusions_summary: str = Field(min_length=3, max_length=10000)
    refund_rule: str = Field(min_length=3, max_length=10000)
    transfer_rule: str = Field(min_length=3, max_length=10000)
    intent_declaration_enabled: bool = False
    intent_valid_days: int = Field(default=30, ge=1, le=365)
    intent_public_summary: str = Field(default="", max_length=10000)
    legal_approved: bool = False
    finance_approved: bool = False
    pricing_approved: bool = False
    active: bool = False


class ReservationCreateIn(BaseModel):
    project_id: str | None = Field(default=None, max_length=100)
    lead_id: str | None = Field(default=None, max_length=120)
    opportunity_id: str | None = Field(default=None, max_length=120)
    offer_version_id: str = Field(min_length=3, max_length=120)
    house_plan_id: str = Field(min_length=3, max_length=120)
    house_config_id: str = Field(min_length=3, max_length=120)
    customer_name: str = Field(min_length=2, max_length=255)
    customer_email: str = Field(min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    billing_name: str = Field(min_length=2, max_length=255)
    billing_address: str = Field(min_length=5, max_length=500)
    tax_number: str | None = Field(default=None, max_length=80)
    terms_accepted: bool
    attribution: dict[str, Any] = Field(default_factory=dict)


class ReservationPaymentResultIn(BaseModel):
    provider: str = Field(min_length=2, max_length=80)
    provider_reference: str = Field(min_length=3, max_length=255)
    idempotency_key: str = Field(min_length=3, max_length=255)
    amount_huf: Decimal = Field(ge=0)
    status: str = Field(pattern="^(succeeded|failed)$")
    evidence_url: str | None = Field(default=None, max_length=1000)
    raw_result: dict[str, Any] = Field(default_factory=dict)


class ReservationLifecycleIn(BaseModel):
    action: str = Field(pattern="^(cancel|expire|refund)$")
    reason: str = Field(min_length=3, max_length=5000)
    evidence_url: str | None = Field(default=None, max_length=1000)


class ReservationConvertIn(BaseModel):
    contract_id: str = Field(min_length=3, max_length=120)


class SalesOpportunityIn(BaseModel):
    lead_id: str | None = Field(default=None, max_length=120)
    customer_id: str | None = Field(default=None, max_length=120)
    brand_id: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=3, max_length=255)
    customer_name: str = Field(min_length=2, max_length=255)
    customer_email: str | None = Field(default=None, max_length=255)
    owner_email: str = Field(min_length=5, max_length=255)
    estimated_value_huf: Decimal = Field(ge=0)
    probability_percent: int = Field(default=10, ge=0, le=100)
    expected_close_date: date | None = None
    needs_summary: str = Field(min_length=10, max_length=10000)
    budget_confirmed: bool = False
    decision_process: str = Field(min_length=5, max_length=10000)
    next_action: str = Field(min_length=5, max_length=10000)


class SalesOpportunityStageIn(BaseModel):
    stage: str = Field(pattern="^(qualified|discovery|proposal|negotiation|contracting)$")
    note: str = Field(min_length=10, max_length=5000)
    probability_percent: int = Field(ge=0, le=100)
    next_action: str = Field(min_length=5, max_length=10000)


class SalesProposalIn(BaseModel):
    currency: str = Field(default="HUF", min_length=3, max_length=3)
    vat_rate: Decimal = Field(default=Decimal("27"), ge=0, le=100)
    cost_net: Decimal = Field(ge=0)
    sale_net: Decimal = Field(gt=0)
    price_snapshot_id: str = Field(min_length=3, max_length=120)
    terms_version_id: str = Field(min_length=3, max_length=120)
    technical_scope_version_id: str = Field(min_length=3, max_length=120)
    scope_summary: str = Field(min_length=10, max_length=20000)
    exclusions: str = Field(min_length=3, max_length=10000)
    payment_terms: str = Field(min_length=5, max_length=10000)
    valid_until: datetime


class SalesProposalReviewIn(BaseModel):
    gate: str = Field(pattern="^(technical|finance|legal)$")
    decision: str = Field(pattern="^(approve|reject)$")
    note: str = Field(min_length=10, max_length=5000)


class SalesProposalSendIn(BaseModel):
    delivery_evidence_url: str = Field(min_length=8, max_length=1000)


class SalesProposalDecisionIn(BaseModel):
    decision: str = Field(pattern="^(accept|reject)$")
    customer_decision_reference: str = Field(min_length=3, max_length=255)
    note: str = Field(min_length=10, max_length=5000)


class SalesOpportunityCloseIn(BaseModel):
    outcome: str = Field(pattern="^(won|lost)$")
    reason: str = Field(min_length=10, max_length=5000)
    contract_id: str | None = Field(default=None, max_length=120)
    delivery_project_id: str | None = Field(default=None, max_length=100)
    competitor: str | None = Field(default=None, max_length=255)


class IntentDeclarationCreateIn(BaseModel):
    project_id: str | None = Field(default=None, max_length=100)
    lead_id: str | None = Field(default=None, max_length=120)
    opportunity_id: str | None = Field(default=None, max_length=120)
    offer_version_id: str = Field(min_length=3, max_length=120)
    house_plan_id: str = Field(min_length=3, max_length=120)
    house_config_id: str = Field(min_length=3, max_length=120)
    customer_name: str = Field(min_length=2, max_length=255)
    customer_email: str = Field(min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    customer_phone: str = Field(min_length=5, max_length=80)
    target_start_window: str = Field(min_length=2, max_length=120)
    project_scope: str = Field(min_length=10, max_length=10000)
    plot_status: str = Field(min_length=2, max_length=120)
    consent_version_id: str = Field(min_length=3, max_length=120)
    terms_accepted: bool
    consent: bool
    attribution: dict[str, Any] = Field(default_factory=dict)


class IntentDeclarationReviewIn(BaseModel):
    action: str = Field(pattern="^(approve|reject|request_changes)$")
    note: str = Field(min_length=3, max_length=5000)
    delivery_evidence_url: str | None = Field(default=None, max_length=1000)


class IntentDeclarationWithdrawIn(BaseModel):
    reason: str = Field(min_length=3, max_length=5000)


class IntentDeclarationUpdateIn(BaseModel):
    house_plan_id: str = Field(min_length=3, max_length=120)
    house_config_id: str = Field(min_length=3, max_length=120)
    customer_phone: str = Field(min_length=5, max_length=80)
    target_start_window: str = Field(min_length=2, max_length=120)
    project_scope: str = Field(min_length=10, max_length=10000)
    plot_status: str = Field(min_length=2, max_length=120)
    consent: bool


class IntentDeclarationConvertIn(BaseModel):
    contract_id: str = Field(min_length=3, max_length=120)


class WorkPackageUpdateIn(BaseModel):
    status: str | None = Field(default=None, pattern="^(planned|ready|in_progress|done|blocked)$")
    progress_pct: int | None = Field(default=None, ge=0, le=100)
    assignee: str | None = Field(default=None, max_length=255)
    blocked: bool | None = None
    block_reason: str | None = Field(default=None, max_length=5000)
    next_action: str | None = Field(default=None, max_length=5000)
    expected_updated_at: datetime | None = None


class GateCheckIn(BaseModel):
    status: str = Field(pattern="^(pending|passed|failed|waived)$")
    evidence_url: str | None = Field(default=None, max_length=1200)
    notes: str | None = Field(default=None, max_length=5000)
    checked_by: str | None = Field(default=None, max_length=255)
    expected_updated_at: datetime | None = None


class DailyReportIn(BaseModel):
    project_id: str
    report_date: datetime | None = None
    reporter: str
    weather: str | None = None
    workers_total: int = Field(default=0, ge=0, le=999)
    summary: str = Field(min_length=3)
    blockers: str | None = None
    safety_status: str = Field(default="ok", pattern="^(ok|attention|stop)$")
    quality_status: str = Field(default="ok", pattern="^(ok|attention|failed)$")
    evidence_url: str | None = None
    voice_note_text: str | None = None
    source_device_id: str | None = None


class SiteIssueIn(BaseModel):
    project_id: str
    report_id: str | None = None
    work_package_id: str | None = None
    issue_type: str = Field(
        default="other",
        pattern="^(blocker|quality|safety|delivery|design|documentation|quantity|damage|other)$",
    )
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    title: str = Field(min_length=3, max_length=255)
    description: str | None = None
    location: str | None = None
    responsible: str | None = None
    due_at: datetime | None = None
    evidence_url: str | None = None
    financial_impact_huf: Decimal = Field(default=Decimal("0"), ge=0)
    deadline_impact_days: int = Field(default=0, ge=0, le=3650)


class DeliveryNoteIn(BaseModel):
    order_id: str
    project_id: str
    note_number: str | None = None
    source_url: str | None = None
    received_at: datetime | None = None
    receiver: str
    item_summary: str = Field(min_length=2)
    ordered_quantity: Decimal = Field(ge=0)
    received_quantity: Decimal = Field(ge=0)
    unit: str = "db"
    actual_specification: str | None = None
    quality_status: str = "accepted"
    damage_or_shortage: str | None = None
    plan_match: str = "matched"
    document_status: str = "complete"
    performance_declaration_status: str = "pending"
    elog_evidence_status: str = "pending"
    storage_location: str | None = None
    custodian: str | None = None
    weather_protection: str = "not_checked"
    evidence_url: str | None = None
    supplier_signed: bool = False
    receiver_signed: bool = False
    signature_evidence_ref: str | None = None


class ProcurementRequirementIn(BaseModel):
    project_id: str
    work_package_id: str | None = None
    category: str = Field(min_length=2, max_length=120)
    scope_description: str = Field(min_length=3)
    specification: str = Field(min_length=3)
    net_quantity: Decimal = Field(gt=0)
    waste_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    unit: str = Field(min_length=1, max_length=40)
    required_at: datetime
    budget_huf: Decimal = Field(gt=0)
    target_huf: Decimal = Field(gt=0)


class ProcurementOfferIn(BaseModel):
    requirement_id: str
    supplier_name: str = Field(min_length=2, max_length=500)
    partner_id: str | None = None
    net_total_huf: Decimal = Field(gt=0)
    delivery_cost_huf: Decimal = Field(default=Decimal("0"), ge=0)
    other_landed_cost_huf: Decimal = Field(default=Decimal("0"), ge=0)
    lead_time_days: int = Field(default=0, ge=0)
    warranty_months: int = Field(default=0, ge=0)
    payment_terms: str = Field(min_length=2, max_length=500)
    risk_score: int = Field(default=0, ge=0, le=100)
    technical_compliant: bool = False
    valid_until: datetime | None = None
    document_ref: str = Field(min_length=3, max_length=1200)
    notes: str | None = None


class ProcurementSelectionIn(BaseModel):
    requirement_id: str
    offer_id: str
    market_evidence_ref: str | None = None
    rationale: str = Field(min_length=3)
    risk_rationale: str = Field(min_length=3)


class ProcurementOrderIn(BaseModel):
    selection_id: str
    ordered_quantity: Decimal = Field(gt=0)
    delivery_due: datetime


class ProcurementSubstitutionIn(BaseModel):
    requirement_id: str
    proposed_product: str = Field(min_length=2, max_length=1000)
    proposed_specification: str = Field(min_length=3)
    technical_equivalence: str = Field(min_length=3)
    declaration_ref: str = Field(min_length=3, max_length=1200)
    price_impact_huf: Decimal = Decimal("0")
    schedule_impact_days: int = 0
    risk_assessment: str = Field(min_length=3)
    rationale: str = Field(min_length=3)


class ProcurementInvoiceMatchIn(BaseModel):
    order_id: str
    delivery_note_id: str
    invoice_reference: str = Field(min_length=2, max_length=255)
    invoice_total_huf: Decimal = Field(gt=0)


class HouseVisionRightsPolicyIn(BaseModel):
    domain: str = Field(min_length=3, max_length=255)
    path_prefix: str = "/"
    rights_status: str
    evidence_ref: str = Field(min_length=3, max_length=1200)
    grant_id: str | None = Field(default=None, min_length=3, max_length=255)
    owner_attestation_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    page_scope_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    attribution_required: bool = False
    attribution_text: str | None = None
    crawl_delay_seconds: int = Field(default=2, ge=0, le=3600)
    max_assets_per_page: int = Field(default=12, ge=1, le=100)


class HouseVisionJobIn(BaseModel):
    brand_id: str = Field(min_length=2, max_length=120)
    source_url: str = Field(min_length=8, max_length=1200)
    operation_mode: str = Field(default="package_only", max_length=30)
    render_provider: str = Field(default="mock", max_length=50)


class HouseVisionSourceAssetIn(BaseModel):
    source_url: str = Field(min_length=8, max_length=1200)
    asset_type: str
    sequence: int = Field(ge=1)
    content_sha256: str = Field(min_length=64, max_length=64)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    magic_mime_type: str = Field(min_length=3, max_length=100)


class HouseVisionGeometryLockIn(BaseModel):
    floorplan_topology_sha256: str = Field(min_length=64, max_length=64)
    massing_signature: str = Field(min_length=3, max_length=500)
    roof_form: str = Field(min_length=2, max_length=255)
    roof_pitch_deg: Decimal | None = None
    storey_count: int = Field(ge=1, le=10)
    window_count: int = Field(ge=0)
    door_count: int = Field(ge=1)
    width_depth_height_ratio: str = Field(min_length=3, max_length=120)
    immutable_features: list[str] = Field(min_length=1)


class HouseVisionOutputAssetIn(BaseModel):
    source_visual_id: str
    provider_job_id: str = Field(min_length=2, max_length=255)
    output_ref: str = Field(min_length=3, max_length=1200)
    content_sha256: str = Field(min_length=64, max_length=64)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    edge_overlap: Decimal = Field(ge=0, le=1)
    roof_match: Decimal = Field(ge=0, le=1)
    opening_match: Decimal = Field(ge=0, le=1)
    floorplan_fidelity: Decimal | None = Field(default=None, ge=0, le=1)
    full_house_in_frame: bool
    daylight_pass: bool
    photorealism_pass: bool
    brand_identity_pass: bool
    privacy_pass: bool


class TypehouseStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TypehouseJobIn(TypehouseStrictModel):
    source_url: str = Field(min_length=12, max_length=1600)
    catalog_id: str = Field(default="imperial-typehouses-hu", min_length=3, max_length=160)
    rights_grant_id: str = Field(default="auto", min_length=3, max_length=255)
    visual_profile_id: str = Field(default="california_ultra_v1", max_length=120)
    output_profile_id: str = Field(default="web_8k_master_v1", max_length=120)
    soft_style_defaults: bool = True
    overrides: dict[str, Any] = Field(default_factory=dict)
    regenerate: bool = False


class TypehouseSourceImportIn(TypehouseStrictModel):
    catalog_id: str = Field(default="imperial-typehouses-hu", min_length=3, max_length=160)
    rights_grant_id: str = Field(default="auto", min_length=3, max_length=255)
    source_urls: list[str] = Field(min_length=1, max_length=1000)
    preserve_order: bool = True
    generator_concurrency: Literal[1] = 1


class TypehouseArtifactIn(TypehouseStrictModel):
    role: Literal[
        "source_manifest",
        "geometry_lock",
        "metadata",
        "life_situations",
        "floorplan_clean",
        "floorplan_catalog",
        "master_8k",
        "responsive_avif",
        "responsive_webp",
        "repair_log",
        "package_manifest",
    ]
    relative_path: str = Field(min_length=1, max_length=1200)
    storage_ref: str = Field(min_length=3, max_length=1600)
    mime_type: str = Field(min_length=3, max_length=160)
    byte_size: int = Field(ge=0, le=2_147_483_647)
    width_px: int | None = Field(default=None, ge=1, le=32768)
    height_px: int | None = Field(default=None, ge=1, le=32768)
    sha256: str = Field(min_length=64, max_length=64)
    source_page_url: str = Field(min_length=12, max_length=1600)
    evidence: dict[str, Any] = Field(default_factory=dict)


class TypehouseQARunIn(TypehouseStrictModel):
    package_manifest_sha256: str = Field(min_length=64, max_length=64)
    deterministic_pass: bool
    semantic_pass: bool
    semantic_score: int = Field(ge=0, le=100)
    verifier_id: str = Field(min_length=3, max_length=255)
    verifier_model: str = Field(min_length=2, max_length=255)
    findings: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class WebsiteSiteIn(BaseModel):
    brand_id: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=255)
    base_url: str = Field(min_length=8, max_length=1200)
    adapter_endpoint: str = Field(min_length=8, max_length=500)
    credential_ref: str = Field(min_length=3, max_length=1200)


class WebsiteTargetIn(BaseModel):
    site_id: str
    route_path: str = Field(min_length=1, max_length=1000)
    locale: str = Field(default="hu-HU", min_length=2, max_length=20)


class WebsiteReleaseIn(BaseModel):
    asset_id: str
    targets: list[WebsiteTargetIn] = Field(min_length=1, max_length=30)


class WebsiteDeliveryReceiptIn(BaseModel):
    target_id: str
    idempotency_key: str
    success: bool
    external_version_id: str | None = Field(default=None, max_length=255)
    published_url: str | None = Field(default=None, max_length=1200)
    rendered_content_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    error_message: str | None = None


class WebsiteSmokeTestIn(BaseModel):
    http_status: int = Field(ge=100, le=599)
    rendered_content_sha256: str = Field(min_length=64, max_length=64)
    link_pass: bool
    form_pass: bool
    schema_pass: bool
    canonical_pass: bool
    accessibility_pass: bool
    analytics_pass: bool
    crm_pass: bool
    privacy_pass: bool
    mobile_render_pass: bool


class AnswerKnowledgeSourceIn(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    source_type: str = Field(min_length=2, max_length=60)
    canonical_ref: str = Field(min_length=3, max_length=1200)
    version: str = Field(min_length=1, max_length=100)
    domain: str = Field(min_length=2, max_length=60)
    visibility: str = "internal"
    allowed_roles: list[str] = Field(default_factory=list)
    project_id: str | None = None
    content_sha256: str = Field(min_length=64, max_length=64)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    owner_role: str = Field(min_length=2, max_length=60)


class AnswerKnowledgeExcerptIn(BaseModel):
    locator: str = Field(min_length=1, max_length=500)
    excerpt_text: str = Field(min_length=3)


class AnswerQuestionIn(BaseModel):
    question_text: str = Field(min_length=5)
    domain: str = Field(min_length=2, max_length=60)
    channel: str = "internal"
    project_id: str | None = None
    customer_reference: str | None = None


class AnswerDraftIn(BaseModel):
    answer_text: str = Field(min_length=10)
    certainty: str
    source_conflict: bool = False


class AnswerCitationIn(BaseModel):
    claim_key: str = Field(min_length=1, max_length=160)
    claim_text: str = Field(min_length=3)
    source_id: str
    excerpt_id: str


class AnswerReviewIn(BaseModel):
    decision: str
    note: str = Field(min_length=5)


class AnswerPublicationIn(BaseModel):
    audience: str
    destination: str = Field(min_length=2, max_length=100)
    project_id: str | None = None


class B2BProjectIntakeIn(BaseModel):
    source_system: str = Field(min_length=2, max_length=100)
    source_external_id: str = Field(min_length=1, max_length=255)
    source_reference: str = Field(min_length=3, max_length=1200)
    source_content_sha256: str = Field(min_length=64, max_length=64)
    lawful_basis: str = Field(min_length=3, max_length=120)
    source_use_approved: bool
    linked_marketing_lead_id: str | None = None
    organization_name: str = Field(min_length=2, max_length=500)
    tax_number: str | None = None
    website_domain: str | None = None
    contact_name: str = Field(min_length=2, max_length=255)
    contact_email: str | None = None
    contact_phone: str | None = None
    project_type: str
    country: str = "HU"
    city: str
    site_address: str | None = None
    gross_floor_area_m2: Decimal = Field(ge=0)
    planned_start: date | None = None
    requested_deadline: date | None = None
    estimated_budget_huf: Decimal = Field(ge=0)
    project_summary: str = Field(min_length=10)
    document_ids: list[str] = Field(default_factory=list, max_length=50)


class B2BDuplicateDecisionIn(BaseModel):
    decision: str
    note: str = Field(min_length=10)


class B2BTechnicalReviewIn(BaseModel):
    decision: str
    delivery_model: str
    capacity_fit: str
    site_feasibility: str
    complexity: str
    assumptions: list[str] = Field(default_factory=list)
    note: str = Field(min_length=10)


class B2BFinancialReviewIn(BaseModel):
    decision: str
    budget_credibility: str
    funding_status: str
    preliminary_margin_band: str
    assumptions: list[str] = Field(default_factory=list)
    note: str = Field(min_length=10)


class B2BQualificationDecisionIn(BaseModel):
    decision: str
    route: str
    assigned_sales_email: str
    next_action: str = Field(min_length=5)
    note: str = Field(min_length=10)


class B2BCRMReceiptIn(BaseModel):
    delivery_id: str
    idempotency_key: str
    payload_sha256: str = Field(min_length=64, max_length=64)
    accepted: bool
    external_crm_id: str | None = None
    error_message: str | None = None


class MaterialMovementIn(BaseModel):
    lot_id: str
    movement_type: str
    quantity: Decimal = Field(gt=0)
    from_location: str | None = None
    to_location: str | None = None
    responsible: str | None = None
    note: str | None = None
    occurred_at: datetime | None = None


class MaterialUsageIn(BaseModel):
    project_id: str
    work_package_id: str | None = None
    lot_id: str | None = None
    subcontractor: str | None = None
    planned_quantity: Decimal = Field(ge=0)
    waste_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    actual_quantity: Decimal = Field(ge=0)
    unit: str = "db"
    unit_cost_huf: Decimal = Field(default=Decimal("0"), ge=0)
    damage_huf: Decimal = Field(default=Decimal("0"), ge=0)
    contractual_basis: str | None = None


class OperationsCommandIn(BaseModel):
    project_id: str
    destination_module: str
    command_type: str
    object_type: str
    object_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class PublicationDeliveryClaimIn(BaseModel):
    adapter_id: str = Field(min_length=3, max_length=160)
    targets: list[str] = Field(min_length=1, max_length=20)
    limit: int = Field(default=20, ge=1, le=100)
    lease_minutes: int = Field(default=15, ge=2, le=60)


class PublicationDeliveryReceiptIn(BaseModel):
    adapter_id: str = Field(min_length=3, max_length=160)
    idempotency_key: str = Field(min_length=64, max_length=64)
    payload_sha256: str = Field(min_length=64, max_length=64)
    status: Literal["delivered", "failed"]
    external_reference: str | None = Field(default=None, max_length=500)
    receipt: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = Field(default=None, max_length=4000)


class PartnerAccessCreateIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=500)
    project_id: str
    work_package_id: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    company_tax_number: str | None = None
    access_code: str = Field(min_length=6, max_length=64)
    worker_names: list[str] = Field(default_factory=list)
    valid_until: datetime | None = None


class PartnerAttendanceActionIn(BaseModel):
    worker_ids: list[str] = Field(min_length=1)
    action: str
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    accuracy_m: Decimal | None = None
    source_device_id: str | None = None
    declaration_accepted: bool = False
    note: str | None = None


class PartnerProgressIn(BaseModel):
    reported_progress_pct: int | None = Field(default=None, ge=0, le=100)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = None
    summary: str = Field(min_length=3)
    problem_text: str | None = None
    safety_note: str | None = None
    quality_note: str | None = None
    source_device_id: str | None = None


class PartnerChangeIn(BaseModel):
    change_type: str = "scope"
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=3)
    requested_by: str | None = None
    deadline_impact_days: int = 0
    source_device_id: str | None = None


class DevelopmentDiscoveryIn(BaseModel):
    discovery_id: str = Field(min_length=3, max_length=120)
    requested_capability: str = Field(min_length=3, max_length=500)
    requested_module_key: str | None = None
    searched_terms: list[str] = Field(min_length=1)
    candidate_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    canonical_module_key: str | None = None
    canonical_object_owner: str | None = None
    source_version: str | None = None
    source_sha256: str | None = None
    decision: str
    implementation_gap: str = Field(min_length=3)
    exception_reason: str | None = None
    requested_by: str | None = None


class DevelopmentDiscoveryReviewIn(BaseModel):
    status: str
    reviewed_by: str
    exception_approved: bool = False
    review_note: str | None = None


class ContractGenerateIn(BaseModel):
    payload: dict[str, Any]


class ChangeControlEventIn(BaseModel):
    change_id: str
    project_id: str
    status: str
    version: int = 1
    summary: str
    net_revenue_huf: Decimal = Decimal("0")
    net_cost_huf: Decimal = Decimal("0")
    deadline_impact_days: int = 0
    customer_decision: str | None = None
    source_url: str | None = None
