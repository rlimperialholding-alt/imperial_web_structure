from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


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


class TechnicalDecisionIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    reason: str = Field(default="", max_length=5000)


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

class WorkPackageUpdateIn(BaseModel):
    status: str | None = None
    progress_pct: int | None = Field(default=None, ge=0, le=100)
    assignee: str | None = None
    blocked: bool | None = None
    block_reason: str | None = None
    next_action: str | None = None


class GateCheckIn(BaseModel):
    status: str
    evidence_url: str | None = None
    notes: str | None = None
    checked_by: str | None = None


class DailyReportIn(BaseModel):
    project_id: str
    report_date: datetime | None = None
    reporter: str
    weather: str | None = None
    workers_total: int = Field(default=0, ge=0, le=999)
    summary: str = Field(min_length=3)
    blockers: str | None = None
    safety_status: str = "ok"
    quality_status: str = "ok"
    evidence_url: str | None = None
    voice_note_text: str | None = None
    source_device_id: str | None = None


class SiteIssueIn(BaseModel):
    project_id: str
    report_id: str | None = None
    work_package_id: str | None = None
    issue_type: str = "other"
    severity: str = "medium"
    title: str = Field(min_length=3, max_length=255)
    description: str | None = None
    location: str | None = None
    responsible: str | None = None
    due_at: datetime | None = None
    evidence_url: str | None = None
    financial_impact_huf: Decimal = Decimal("0")
    deadline_impact_days: int = 0


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
