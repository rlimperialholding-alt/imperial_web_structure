from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, Literal, cast
from urllib.parse import urlencode
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session, selectinload
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .audit import audit
from .autonomous_publishing.routes import router as autonomous_publishing_router
from .autonomous_publishing.service import readiness as autonomous_publishing_readiness
from .config import settings
from .copy_gate.campaign_package import CampaignPackage
from .copy_gate.models import (
    ApprovalSubmission,
    AssemblySubmission,
    ContentAsset,
    ContentAssetCreateRequest,
    CopyBrief,
    CopyQualityRequest,
    CopySourceIn,
    CreativeDirectorReviewSubmission,
    Decision,
    FourGateSubmission,
    LiveReviewSubmission,
    MandatoryCopyGateReviewSubmission,
    PerformanceSubmission,
    PlatformExport,
    ReleaseReviewSubmission,
    StrategyReviewSubmission,
    VisualProductionSubmission,
)
from .copy_gate.orchestrator import GENERATION_STAGES
from .database import Base, SessionLocal, engine, get_db
from .demo_runtime import DemoRuntimeError, demo_runtime
from .growth_ops.routes import router as growth_ops_router
from .growth_ops.service import readiness as growth_ops_readiness
from .models import (
    BookingExperienceVersion,
    BookingRecord,
    BookingSlot,
    CalculationSourceRegistry,
    CalendarChangeRequest,
    CanonicalDeliveryRecord,
    CanonicalReconciliationRun,
    ConsistencyIssue,
    ContentAssetRecord,
    ContentGateDecision,
    CopyBriefRecord,
    CopySourceRecord,
    CreativeProductionRunRecord,
    DeploymentRecord,
    EnterpriseCanonicalRecord,
    EnvironmentRecord,
    EventRecord,
    ImportCommitBatch,
    ImportDataSource,
    ImportItem,
    ImportJob,
    IntentDeclarationRecord,
    MailSendingDomain,
    MailSuppression,
    ModuleRegistry,
    PartnerEvidence,
    PartnerFieldAccess,
    PartnerProgressReport,
    PilotRun,
    PMGateCheck,
    PMWorkPackage,
    ProjectRegistry,
    PublicationBundleRecord,
    ReleaseRecord,
    ReservationOfferVersion,
    StagedEnterpriseRecord,
    TaskRecord,
    TenderBidVersion,
    TenderClarificationRequest,
    TenderMailCampaign,
    TenderMailEvent,
    TenderMailRecipient,
    TenderPurchaseOrderPreparation,
    User,
    WorkspaceDocument,
)
from .roles import (
    ROLE_DEFINITIONS,
    can_access,
    modules_for_path,
    public_role_payload,
    role_definition,
)
from .routes.house_designer import build_house_designer_router
from .routes.house_studio import build_house_studio_router
from .routes.market_intelligence import build_market_intelligence_router
from .routes.regulatory_admin import build_regulatory_admin_router
from .routes.typehouse_factory import build_typehouse_factory_router
from .schemas import (
    AnswerCitationIn,
    AnswerDraftIn,
    AnswerKnowledgeExcerptIn,
    AnswerKnowledgeSourceIn,
    AnswerPublicationIn,
    AnswerQuestionIn,
    AnswerReviewIn,
    ArtifactIn,
    B2BCRMReceiptIn,
    B2BDuplicateDecisionIn,
    B2BFinancialReviewIn,
    B2BProjectIntakeIn,
    B2BQualificationDecisionIn,
    B2BTechnicalReviewIn,
    BookingCalendarSyncIn,
    BookingCreateIn,
    BookingExperienceIn,
    BookingOutcomeIn,
    BookingRescheduleIn,
    BookingSlotIn,
    CalculationRequest,
    CalendarChangeDecisionIn,
    CalendarChangeRequestIn,
    CalendarDependencyIn,
    CalendarEntryIn,
    CalendarRescheduleIn,
    CalendarStatusIn,
    ChangeControlEventIn,
    ContractGenerateIn,
    DailyReportIn,
    DeliveryNoteIn,
    DevelopmentDiscoveryIn,
    DevelopmentDiscoveryReviewIn,
    DomainVerificationIn,
    EngineeringCaseIn,
    EngineeringDeliverableIn,
    EngineeringFindingIn,
    EngineeringFindingResolutionIn,
    EngineeringRevisionIn,
    EngineeringRevisionReviewIn,
    EngineeringTransmittalAckIn,
    EngineeringTransmittalIn,
    EventIn,
    FactIn,
    GateCheckIn,
    HeartbeatIn,
    HouseCatalogReviewIn,
    HouseCatalogVersionIn,
    HouseCatalogWithdrawIn,
    HouseMatchIn,
    HouseVisionGeometryLockIn,
    HouseVisionJobIn,
    HouseVisionOutputAssetIn,
    HouseVisionRightsPolicyIn,
    HouseVisionSourceAssetIn,
    ImportCommitIn,
    ImportItemIn,
    ImportJobIn,
    ImportPushIn,
    ImportReviewIn,
    ImportSourceIn,
    IntentDeclarationConvertIn,
    IntentDeclarationCreateIn,
    IntentDeclarationReviewIn,
    IntentDeclarationUpdateIn,
    MailEventIn,
    MaterialMovementIn,
    MaterialUsageIn,
    ModuleBusinessApprovalIn,
    ModuleBusinessCommentIn,
    ModuleBusinessRecordIn,
    ModuleBusinessRecordUpdateIn,
    ModuleBusinessTransitionIn,
    OperationsCommandIn,
    PartnerAccessCreateIn,
    PartnerAttendanceActionIn,
    PartnerChangeIn,
    PartnerProgressIn,
    ProcurementInvoiceMatchIn,
    ProcurementOfferIn,
    ProcurementOrderIn,
    ProcurementRequirementIn,
    ProcurementSelectionIn,
    ProcurementSubstitutionIn,
    ProjectControlBaselineIn,
    ProjectControlBaselineReviewIn,
    ProjectControlFinanceReviewIn,
    ProjectControlForecastIn,
    ProjectControlLeadershipDecisionIn,
    ProjectControlRecoveryActionIn,
    ProjectControlRecoveryCompleteIn,
    ProjectControlRecoveryVerifyIn,
    ProjectControlVarianceClassifyIn,
    ProjectControlWeeklyReportDecisionIn,
    ProjectControlWeeklyReportIn,
    PublicationDeliveryClaimIn,
    PublicationDeliveryReceiptIn,
    ReleaseIn,
    RenovationCalculationIn,
    ReservationConvertIn,
    ReservationCreateIn,
    ReservationLifecycleIn,
    ReservationOfferIn,
    ReservationPaymentResultIn,
    SalesOpportunityCloseIn,
    SalesOpportunityIn,
    SalesOpportunityStageIn,
    SalesProposalDecisionIn,
    SalesProposalIn,
    SalesProposalReviewIn,
    SalesProposalSendIn,
    SendingDomainIn,
    SiteIssueIn,
    TaskUpdateIn,
    TechnicalCaseIn,
    TechnicalDecisionIn,
    TechnicalGateReviewIn,
    TechnicalVariantSelectionIn,
    TenderCampaignIn,
    TenderRecipientBatchIn,
    TenderRecipientIn,
    VersionActivationIn,
    WebsiteDeliveryReceiptIn,
    WebsiteReleaseIn,
    WebsiteSiteIn,
    WebsiteSmokeTestIn,
    WebsiteTargetIn,
    WorkPackageUpdateIn,
    WorkspaceDocumentIn,
)
from .security import (
    current_partner_access,
    current_user,
    hash_password,
    require_api_token,
    require_internal_job_token,
    require_role,
    require_session_user,
    verify_password,
)
from .seed import DEMO_PASSWORD, seed_database
from .session_write_guard import SessionWriteOriginMiddleware
from .services.answer_center import (
    add_citation as add_answer_citation,
)
from .services.answer_center import (
    add_excerpt as add_answer_excerpt,
)
from .services.answer_center import (
    approve_source as approve_answer_source,
)
from .services.answer_center import (
    create_draft as create_answer_draft,
)
from .services.answer_center import (
    create_question as create_answer_question,
)
from .services.answer_center import (
    publish_answer,
    review_answer,
)
from .services.answer_center import (
    register_source as register_answer_source,
)
from .services.answer_center import (
    retract_publication as retract_answer_publication,
)
from .services.answer_center import (
    revoke_source as revoke_answer_source,
)
from .services.answer_center import (
    submit_for_review as submit_answer_for_review,
)
from .services.answer_center import (
    workspace as answer_center_workspace,
)
from .services.b2b_project_intake import (
    capture_intake as capture_b2b_intake,
)
from .services.b2b_project_intake import (
    leadership_decision as decide_b2b_leadership,
)
from .services.b2b_project_intake import (
    qualify_intake as qualify_b2b_intake,
)
from .services.b2b_project_intake import (
    queue_crm_handoff as queue_b2b_crm_handoff,
)
from .services.b2b_project_intake import (
    record_crm_receipt as record_b2b_crm_receipt,
)
from .services.b2b_project_intake import (
    record_financial_review as review_b2b_financial,
)
from .services.b2b_project_intake import (
    record_technical_review as review_b2b_technical,
)
from .services.b2b_project_intake import (
    resolve_duplicate as resolve_b2b_duplicate,
)
from .services.b2b_project_intake import (
    workspace as b2b_intake_workspace,
)
from .services.booking_reservation import (
    cancel_booking,
    commercial_sales_workspace,
    convert_intent_declaration,
    convert_reservation,
    create_booking,
    create_booking_experience,
    create_booking_slot,
    create_intent_declaration,
    create_offer_version,
    create_reservation,
    my_imperial_workspace,
    record_booking_calendar_sync,
    record_payment_result,
    reschedule_booking,
    review_intent_declaration,
    serialize_booking,
    serialize_intent_declaration,
    serialize_reservation,
    set_booking_experience_active,
    set_offer_active,
    transition_reservation,
    update_booking_outcome,
    update_intent_declaration,
    withdraw_intent_declaration,
)
from .services.buildconfig import (
    FINANCE_REVIEW_ROLES as BUILDCONFIG_FINANCE_REVIEW_ROLES,
)
from .services.buildconfig import (
    RELEASE_ROLES as BUILDCONFIG_RELEASE_ROLES,
)
from .services.buildconfig import (
    TECHNICAL_REVIEW_ROLES as BUILDCONFIG_TECHNICAL_REVIEW_ROLES,
)
from .services.buildconfig import (
    case_detail as buildconfig_case_detail,
)
from .services.buildconfig import (
    compare_versions as compare_buildconfig_versions,
)
from .services.buildconfig import (
    create_case as create_buildconfig_case,
)
from .services.buildconfig import (
    create_revision as create_buildconfig_revision,
)
from .services.buildconfig import (
    housebuild_variants as buildconfig_housebuild_variants,
)
from .services.buildconfig import (
    list_cases as list_buildconfig_cases,
)
from .services.buildconfig import (
    option_catalog as buildconfig_option_catalog,
)
from .services.buildconfig import (
    reject_case as reject_buildconfig_case,
)
from .services.buildconfig import (
    release_case as release_buildconfig_case,
)
from .services.buildconfig import (
    report_path as buildconfig_report_path,
)
from .services.buildconfig import (
    review_gate as review_buildconfig_gate,
)
from .services.buildconfig import (
    submit_case as submit_buildconfig_case,
)
from .services.canonical_bridge import (
    CanonicalBridgeError,
    canonical_integrity_report,
    pull_itep_tasks_to_platform,
    push_canonical_to_crm,
    push_platform_events_to_itep,
    reconcile_canonical_with_crm,
)
from .services.canonical_sync_lease import CanonicalSyncBusy, CanonicalSyncLeaseLost
from .services.canonical_documents import (
    canonical_template_status,
    get_canonical_template,
    instantiate_canonical_template,
    list_canonical_templates,
)
from .services.change_control import (
    add_change_line,
    authorize_change_work,
    change_control_detail,
    change_control_workspace,
    complete_change,
    create_change_case,
    create_change_revision,
    delete_change_line,
    review_change,
    submit_change,
    sync_customer_decision,
    update_change_draft,
)
from .services.commercial_integration import (
    blank_contract_form_values,
    build_contract_intake_payload,
    commercial_workspace,
    contract_intake_options,
    contract_source_status,
    generate_contract_package,
    ingest_change_control_event,
    resolve_contract_artifact,
    validate_contract_payload,
)
from .services.communications import (
    create_thread,
    get_thread,
    list_notifications,
    list_threads,
    mark_notifications_read,
    post_message,
    unread_notification_count,
)
from .services.consistency import scan_consistency, upsert_fact
from .services.content_quality import (
    assemble_publication_bundle,
    build_human_creative_director_review,
    build_human_editorial_review,
    build_human_mandatory_gate_review,
    create_content_asset,
    create_copy_brief,
    publish_content_asset,
    record_approval,
    record_campaign_package_gate,
    record_creative_director_review,
    record_live_publication_review,
    record_mandatory_copy_gate_review,
    record_performance_metric,
    record_release_review,
    record_strategy_review,
    register_copy_source,
    review_copy_source,
    review_human_specialist_gate,
    rollback_content_asset,
    run_copy_quality,
    submit_four_gates,
    submit_visual_production,
    validate_copy_brief,
)
from .services.content_image_factory import list_requests as list_content_image_requests
from .services.content_image_factory import process_content_image_factory
from .services.contract_workflow import (
    activate_contract,
    contract_workflow_detail,
    record_contract_dispatch,
    record_signed_contract,
    review_contract,
    submit_contract_review,
)
from .services.crm_canonical_sync import CrmCanonicalSyncError, sync_crm_canonical
from .services.dashboard import dashboard_metrics
from .services.development_governance import create_discovery, list_discoveries, review_discovery
from .services.dpm_gateway import DpmGatewayError, dpm_gateway
from .services.engineering_workspace import (
    acknowledge_transmittal,
    approve_finding_resolution,
    complete_consultation,
    create_engineering_case,
    engineering_workspace,
    issue_transmittal,
    mark_construction_ready,
    propose_finding_resolution,
)
from .services.engineering_workspace import (
    create_deliverable as create_engineering_deliverable,
)
from .services.engineering_workspace import (
    create_finding as create_engineering_finding,
)
from .services.engineering_workspace import (
    create_revision as create_engineering_revision,
)
from .services.engineering_workspace import (
    release_revision as release_engineering_revision,
)
from .services.engineering_workspace import (
    review_revision as review_engineering_revision,
)
from .services.engineering_workspace import (
    serialize as serialize_engineering,
)
from .services.engineering_workspace import (
    submit_revision as submit_engineering_revision,
)
from .services.executive_decisions import assign_consistency_issue, resolve_executive_event
from .services.file_ingestion import parse_upload
from .services.financial_allocations import allocate_financial_record, allocation_workspace
from .services.financial_intelligence import finance_intelligence_dashboard
from .services.house_catalog import (
    catalog_workspace,
    create_catalog_version,
    ensure_house_catalog_seed,
    public_catalog,
    release_catalog_version,
    review_catalog_version,
    serialize_catalog_plan,
    serialize_catalog_version,
    submit_catalog_version,
    withdraw_catalog_plan,
)
from .services.house_designer import HouseDesignerError
from .services.house_designer_privacy import migrate_house_designer_site_encryption
from .services.house_designer_guest import (
    GUEST_CLAIM_COOKIE,
    GUEST_SESSION_COOKIE,
    claim_guest_design,
)
from .services.house_plan_execution import (
    ensure_house_studio_demo_grants,
    ensure_houseplan_source_cutover,
)
from .services.housebuild import (
    RELEASE_ROLES as HOUSEBUILD_RELEASE_ROLES,
)
from .services.housebuild import (
    case_detail as housebuild_case_detail,
)
from .services.housebuild import (
    create_case as create_housebuild_case,
)
from .services.housebuild import (
    list_cases as list_housebuild_cases,
)
from .services.housebuild import (
    reject_case as reject_housebuild_case,
)
from .services.housebuild import (
    release_case as release_housebuild_case,
)
from .services.housebuild import (
    report_path as housebuild_report_path,
)
from .services.housebuild import (
    review_gate as review_housebuild_gate,
)
from .services.housebuild import (
    select_variant as select_housebuild_canonical_variant,
)
from .services.housebuild import (
    submit_case as submit_housebuild_case,
)
from .services.housematch import HouseProfile, housematch_repository
from .services.housevision import (
    action_permissions as housevision_action_permissions,
)
from .services.housevision import (
    add_output_asset as add_housevision_output,
)
from .services.housevision import (
    add_source_asset as add_housevision_source,
)
from .services.housevision import (
    auto_ingest_source_assets as auto_ingest_housevision_sources,
)
from .services.housevision import auto_lock_geometry as auto_lock_housevision_geometry
from .services.housevision_render_bridge import (
    create_source_preserved_baseline as create_housevision_source_baseline,
)
from .services.housevision_render_bridge import generate_typehouse_renders
from .services.housevision import (
    approve_rights_policy as approve_housevision_rights,
)
from .services.housevision import (
    assign_name as assign_housevision_name,
)
from .services.housevision import (
    bind_houseplan as bind_housevision_houseplan,
)
from .services.housevision import (
    create_job as create_housevision_job,
)
from .services.housevision import (
    create_rights_policy as create_housevision_rights,
)
from .services.housevision import (
    ensure_action_allowed as ensure_housevision_action,
)
from .services.housevision import ensure_typehouse_auto_approved_rights
from .services.housevision import (
    job_detail as housevision_job_detail,
)
from .services.housevision import (
    lock_geometry as lock_housevision_geometry,
)
from .services.housevision import (
    package_job as package_housevision_job,
)
from .services.housevision import (
    recheck_rights as recheck_housevision_rights,
)
from .services.housevision import (
    run_qa as run_housevision_qa,
)
from .services.housevision import (
    workspace as housevision_workspace,
)
from .services.imperial_care import (
    CareEvidenceUnavailable,
    add_care_message,
    care_case_for_user,
    care_evidence_for_user,
    care_workspace,
    create_care_case,
    save_care_evidence,
    transition_care_case,
    verified_care_evidence_path,
)
from .services.import_center import (
    add_item,
    commit_records,
    create_job,
    create_source,
    import_metrics,
    process_job,
    review_record,
    rollback_batch,
)
from .services.integration import ingest_event, process_outbox, register_heartbeat
from .services.itep_finance import ItepFinanceError, incoming_invoices
from .services.market_intelligence import (
    ensure_market_demo_grants,
    migrate_market_snapshot_encryption,
)
from .services.marketing_automation import (
    activate_campaign as activate_marketing_campaign,
)
from .services.marketing_automation import (
    approve_campaign as approve_marketing_campaign,
)
from .services.marketing_automation import (
    capture_lead as capture_marketing_lead,
)
from .services.marketing_automation import (
    complete_campaign as complete_marketing_campaign,
)
from .services.marketing_automation import (
    create_campaign as create_marketing_campaign,
)
from .services.marketing_automation import (
    decide_optimization,
    decide_sales_lead,
    execute_optimization,
    handoff_lead_to_crm,
    ingest_campaign_metric,
    marketing_automation_workspace,
    marketing_lead_by_consent_token,
    propose_optimization,
    set_marketing_consent,
    withdraw_marketing_consent_by_token,
)
from .services.marketing_automation import (
    pause_campaign as pause_marketing_campaign,
)
from .services.marketing_automation import (
    qualify_lead as qualify_marketing_lead,
)
from .services.marketing_automation import (
    submit_campaign as submit_marketing_campaign,
)
from .services.module_business import (
    add_approval as add_module_approval,
)
from .services.module_business import (
    add_comment as add_module_comment,
)
from .services.module_business import (
    create_record as create_module_record,
)
from .services.module_business import (
    get_record as get_module_record,
)
from .services.module_business import (
    list_records as list_module_records,
)
from .services.module_business import (
    module_profile,
    module_source_projection,
)
from .services.module_business import (
    serialize_record as serialize_module_record,
)
from .services.module_business import (
    transition_record as transition_module_record,
)
from .services.module_business import (
    update_record as update_module_record,
)
from .services.my_imperial import (
    acknowledge_project_update,
    assert_project_access,
    complete_customer_task,
    create_decision_request,
    project_portal_detail,
    publish_project_update,
    respond_to_decision,
)
from .services.operations import (
    create_daily_report,
    create_delivery_note,
    create_issue,
    create_material_movement,
    create_operations_command,
    create_usage_control,
    field_projects,
    operations_portfolio,
    operations_summary,
    procurement_summary,
    project_operations,
    update_gate,
    update_work_package,
)
from .services.partner_control import (
    add_certificate as add_partner_certificate,
)
from .services.partner_control import (
    approve_decision as approve_partner_decision,
)
from .services.partner_control import (
    approve_partner,
    create_partner,
    record_incident_response,
)
from .services.partner_control import (
    close_incident as close_partner_incident,
)
from .services.partner_control import (
    create_incident as create_partner_incident,
)
from .services.partner_control import (
    create_project_evaluation as create_partner_project_evaluation,
)
from .services.partner_control import (
    declare_capacity as declare_partner_capacity,
)
from .services.partner_control import (
    partner_workspace as partner_control_workspace,
)
from .services.partner_control import (
    propose_decision as propose_partner_decision,
)
from .services.partner_control import (
    review_capacity as review_partner_capacity,
)
from .services.partner_control import (
    review_decision as review_partner_decision,
)
from .services.partner_control import (
    set_external_score as set_partner_external_score,
)
from .services.partner_control import (
    verify_certificate as verify_partner_certificate,
)
from .services.partner_field import (
    access_is_valid,
    attendance_action,
    authenticate_access,
    create_access,
    create_change,
    create_partner_issue,
    create_progress,
    deactivate_access,
    internal_partner_projection,
    partner_dashboard,
    review_progress,
    save_evidence,
)
from .services.pilots import run_all_pilots, run_pilot_scenario
from .services.plancheck import (
    FINAL_ROLES as PLANCHECK_FINAL_ROLES,
)
from .services.plancheck import (
    GATE_ROLES as PLANCHECK_GATE_ROLES,
)
from .services.plancheck import (
    add_assumption as add_plancheck_assumption,
)
from .services.plancheck import (
    case_detail as plancheck_case_detail,
)
from .services.plancheck import (
    case_for_token as plancheck_case_for_token,
)
from .services.plancheck import (
    create_case as create_plancheck_case,
)
from .services.plancheck import (
    finalize_case as finalize_plancheck_case,
)
from .services.plancheck import (
    list_cases as list_plancheck_cases,
)
from .services.plancheck import (
    resolve_assumption as resolve_plancheck_assumption,
)
from .services.plancheck import (
    review_gate as review_plancheck_gate,
)
from .services.plancheck import (
    revoke_upload_link as revoke_plancheck_upload_link,
)
from .services.plancheck import (
    rotate_upload_link as rotate_plancheck_upload_link,
)
from .services.plancheck import (
    submit_review as submit_plancheck_review,
)
from .services.plancheck import (
    upload_document as upload_plancheck_document,
)
from .services.plotcheck import (
    FINAL_ROLES as PLOTCHECK_FINAL_ROLES,
)
from .services.plotcheck import (
    RULE_ADMIN_ROLES as PLOTCHECK_RULE_ADMIN_ROLES,
)
from .services.plotcheck import (
    add_action as add_plotcheck_action,
)
from .services.plotcheck import (
    add_evidence as add_plotcheck_evidence,
)
from .services.plotcheck import (
    assess_case as assess_plotcheck_case,
)
from .services.plotcheck import (
    case_detail as plotcheck_case_detail,
)
from .services.plotcheck import (
    complete_action as complete_plotcheck_action,
)
from .services.plotcheck import (
    create_case as create_plotcheck_case,
)
from .services.plotcheck import (
    create_rule_set as create_plotcheck_rule_set,
)
from .services.plotcheck import (
    finalize_case as finalize_plotcheck_case,
)
from .services.plotcheck import (
    list_cases as list_plotcheck_cases,
)
from .services.plotcheck import (
    list_rule_sets as list_plotcheck_rule_sets,
)
from .services.plotcheck import (
    review_gate as review_plotcheck_gate,
)
from .services.plotcheck import (
    verify_evidence as verify_plotcheck_evidence,
)
from .services.plotcheck import (
    verify_rule_set as verify_plotcheck_rule_set,
)
from .services.pricing import pricing_repository
from .services.procurement import (
    add_offer as add_procurement_offer,
)
from .services.procurement import (
    approve_requirement as approve_procurement_requirement,
)
from .services.procurement import (
    approve_selection as approve_procurement_selection,
)
from .services.procurement import (
    confirm_order as confirm_procurement_order,
)
from .services.procurement import (
    create_invoice_match as create_procurement_invoice_match,
)
from .services.procurement import (
    create_order as create_procurement_order,
)
from .services.procurement import (
    create_requirement as create_procurement_requirement,
)
from .services.procurement import (
    create_substitution_review as create_procurement_substitution_review,
)
from .services.procurement import (
    procurement_workspace,
)
from .services.procurement import (
    resolve_deviation as resolve_procurement_deviation,
)
from .services.procurement import (
    review_substitution as review_procurement_substitution,
)
from .services.procurement import (
    revise_requirement as revise_procurement_requirement,
)
from .services.procurement import (
    select_offer as select_procurement_offer,
)
from .services.project_control import (
    classify_variance as classify_project_control_variance,
)
from .services.project_control import (
    complete_recovery_action as complete_project_control_recovery,
)
from .services.project_control import (
    create_baseline as create_project_control_baseline,
)
from .services.project_control import (
    create_forecast as create_project_control_forecast,
)
from .services.project_control import (
    create_recovery_action as create_project_control_recovery,
)
from .services.project_control import (
    decide_baseline as decide_project_control_baseline,
)
from .services.project_control import (
    decide_forecast as decide_project_control_forecast,
)
from .services.project_control import (
    decide_weekly_report as decide_project_control_report,
)
from .services.project_control import (
    generate_weekly_report as generate_project_control_report,
)
from .services.project_control import (
    project_control_workspace,
)
from .services.project_control import (
    review_baseline as review_project_control_baseline,
)
from .services.project_control import (
    review_forecast as review_project_control_forecast,
)
from .services.project_control import (
    serialize as serialize_project_control,
)
from .services.project_control import (
    submit_baseline as submit_project_control_baseline,
)
from .services.project_control import (
    submit_forecast as submit_project_control_forecast,
)
from .services.project_control import (
    submit_weekly_report as submit_project_control_report,
)
from .services.project_control import (
    verify_recovery_action as verify_project_control_recovery,
)
from .services.project_finance import (
    add_budget_line as add_project_finance_budget_line,
)
from .services.project_finance import (
    add_cashflow_line as add_project_finance_cashflow_line,
)
from .services.project_finance import (
    FinanceConcurrencyError,
    clone_finance_plan,
    create_finance_plan,
    finance_approve_plan,
    finance_plan_workspace,
    leadership_approve_plan,
    reject_finance_plan,
    submit_finance_plan,
)
from .services.project_finance import (
    plan_summary as project_finance_plan_summary,
)
from .services.publication_delivery import (
    claim_publication_deliveries,
    publication_delivery_workspace,
    record_publication_receipt,
    retry_publication_delivery,
)
from .services.publication_delivery import (
    serialize_delivery as serialize_publication_delivery,
)
from .services.releases import add_artifact, create_release, release_gate
from .services.sales_pipeline import (
    close_opportunity,
    create_opportunity,
    create_proposal,
    record_proposal_decision,
    review_proposal,
    sales_pipeline_workspace,
    send_proposal,
    serialize_opportunity,
    serialize_proposal,
    submit_proposal,
    transition_opportunity,
)
from .services.smart_calendar import (
    add_dependency as add_calendar_dependency,
)
from .services.smart_calendar import (
    assert_calendar_project_access,
    calendar_portfolio,
    calendar_project_ids_for_user,
    decide_contractual_change,
    request_contractual_change,
    reschedule_entry,
    synchronize_schedule_sources,
    update_entry_status,
)
from .services.smart_calendar import (
    create_entry as create_calendar_entry,
)
from .services.smart_calendar import (
    get_entry as get_calendar_entry,
)
from .services.smart_calendar import (
    serialize_entry as serialize_calendar_entry,
)
from .services.technical_products import (
    create_case,
    decide_case,
    get_case,
    list_cases,
    review_gate,
    submit_case,
)
from .services.tender_mail import (
    add_canonical_partner_recipients,
    add_recipient,
    approve_campaign,
    campaign_readiness,
    create_campaign,
    dispatch_batch,
    queue_campaign,
    record_event,
    tender_mail_metrics,
    unsubscribe_by_token,
    upsert_domain,
    verify_domain,
)
from .services.tender_portal import (
    accept_clarification_request,
    add_clarification,
    add_invitation,
    add_tender_line_item,
    award_bid,
    close_tender,
    create_clarification_request,
    create_tender,
    decline_invitation,
    evaluate_bid,
    evidence_for_internal,
    evidence_for_partner,
    get_tender,
    manage_invitation_access,
    publish_tender,
    respond_clarification_request,
    save_bid,
    save_bid_evidence,
    submit_bid,
    sync_mail_recipients,
    tender_workspace,
    verified_evidence_path,
    withdraw_bid,
)
from .services.tender_evidence_security import (
    TenderEvidenceUnavailable,
    TenderMalwareDetected,
    TenderScannerUnavailable,
)
from .services.tender_portal import (
    bid_comparison as tender_bid_comparison,
)
from .services.tender_portal import (
    partner_workspace as tender_partner_workspace,
)
from .services.website_content import (
    create_release as create_website_release,
)
from .services.website_content import (
    dispatch_release as dispatch_website_release,
)
from .services.website_content import (
    record_delivery_receipt as record_website_receipt,
)
from .services.website_content import (
    record_smoke_test as record_website_smoke,
)
from .services.website_content import (
    register_site as register_website_site,
)
from .services.website_content import (
    rollback_release as rollback_website_release,
)
from .services.website_content import (
    set_kill_switch as set_website_kill_switch,
)
from .services.website_content import (
    workspace as website_content_workspace,
)
from .services.workspace import (
    create_document,
    document_metrics,
    global_search,
    list_documents,
    list_tasks,
    project_360,
    task_metrics,
    update_document_status,
    update_task,
    workspace_summary,
)

BASE_DIR = Path(__file__).resolve().parent
PARTNER_EVIDENCE_DIR = BASE_DIR.parent / "data" / "partner_evidence"
CARE_EVIDENCE_DIR = BASE_DIR.parent / "data" / "care_evidence"
TENDER_EVIDENCE_DIR = BASE_DIR.parent / "data" / "tender_evidence"
MARKETING_CREATIVE_DIR = BASE_DIR.parent / "runtime" / "marketing_creatives"
_INTERNAL_COMMUNICATION_ROLES = {item.id for item in ROLE_DEFINITIONS} - {
    "customer",
    "subcontractor",
}
_CALENDAR_APPROVER_ROLES = {"owner", "managing-director", "platform-admin"}
_LEADERSHIP_ROLES = {"owner", "managing-director", "platform-admin"}
_SALES_COMMERCIAL_INTERNAL_ROLES = {
    "owner",
    "managing-director",
    "platform-admin",
    "sales",
    "finance",
    "legal",
    "technical-prep",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    errors = settings.validate()
    if errors:
        raise RuntimeError(" | ".join(errors))
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
        ensure_typehouse_auto_approved_rights(db)
        ensure_house_catalog_seed(db)
        ensure_houseplan_source_cutover(db, demo_auto_approve=settings.demo_runtime_enabled)
        ensure_house_studio_demo_grants(db, enabled=settings.demo_runtime_enabled)
        ensure_market_demo_grants(db, enabled=settings.demo_runtime_enabled)
        migrate_market_snapshot_encryption(db)
        migrate_house_designer_site_encryption(db)
        synchronize_schedule_sources(db, actor="system:startup")
    yield


app = FastAPI(title="Imperial Intelligence Control Center", version=__version__, lifespan=lifespan)


def _audit_canonical_sync_runtime_exception(
    request: Request,
    exc: CanonicalSyncBusy | CanonicalSyncLeaseLost,
    *,
    action: str,
) -> None:
    with SessionLocal() as audit_db:
        user = current_user(request, audit_db)
        actor = user.email if user else "anonymous"
        if user is None and request.url.path.startswith("/api/"):
            actor = "internal-job"
        audit(
            audit_db,
            actor=actor,
            action=action,
            entity_type="canonical_sync_lease",
            entity_id=exc.lease_key,
            after={"path": request.url.path},
        )
        audit_db.commit()


@app.exception_handler(CanonicalSyncBusy)
def canonical_sync_busy_handler(request: Request, exc: CanonicalSyncBusy):
    _audit_canonical_sync_runtime_exception(
        request, exc, action="canonical_sync.lease_busy"
    )
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(CanonicalSyncLeaseLost)
def canonical_sync_lease_lost_handler(request: Request, exc: CanonicalSyncLeaseLost):
    _audit_canonical_sync_runtime_exception(
        request, exc, action="canonical_sync.lease_lost"
    )
    return JSONResponse(status_code=503, content={"detail": str(exc)})
app.add_middleware(SessionWriteOriginMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=settings.is_production,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["huf"] = lambda v: f"{Decimal(str(v or 0)):,.0f} Ft".replace(",", " ")
templates.env.filters["amount"] = lambda v: f"{Decimal(str(v or 0)):,.2f}".replace(
    ",", " "
).replace(".", ",")
templates.env.filters["dt"] = lambda v: v.astimezone().strftime("%Y.%m.%d. %H:%M") if v else "—"
_BUDAPEST = ZoneInfo("Europe/Budapest")
templates.env.filters["calendar_local"] = lambda v: (
    (v if v.tzinfo else v.replace(tzinfo=timezone.utc))
    .astimezone(_BUDAPEST)
    .strftime("%Y-%m-%dT%H:%M")
    if v
    else ""
)
_WEEKDAYS_HU = ("hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap")
templates.env.filters["weekday_hu"] = lambda v: _WEEKDAYS_HU[v.weekday()] if v else "—"
templates.env.globals["demo_password"] = None if settings.is_production else DEMO_PASSWORD
templates.env.globals["can_access"] = can_access
templates.env.globals["asset_version"] = __version__
app.include_router(build_house_studio_router(templates))
app.include_router(build_house_designer_router(templates))
app.include_router(build_market_intelligence_router(templates))
app.include_router(build_regulatory_admin_router(templates))
app.include_router(build_typehouse_factory_router(templates))
app.include_router(autonomous_publishing_router)
app.include_router(growth_ops_router)


class DemoActionIn(BaseModel):
    module_id: str = Field(min_length=2, max_length=80)
    action_id: str = Field(min_length=2, max_length=80)
    project_id: str = Field(default="PRJ-DEMO-001", min_length=3, max_length=80)
    actor: str = Field(default="demo.user@imperial.local", min_length=3, max_length=160)
    correlation_id: str | None = Field(default=None, max_length=120)
    idempotency_key: str | None = Field(default=None, max_length=200)
    payload: dict = Field(default_factory=dict)


class DemoJourneyIn(BaseModel):
    actor: str = Field(default="demo.user@imperial.local", min_length=3, max_length=160)


class DemoFailureIn(BaseModel):
    consumer: str = Field(min_length=2, max_length=80)


def _ui_csrf_token(request: Request) -> str:
    token = request.session.get("ui_csrf_token")
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        request.session["ui_csrf_token"] = token
    return token


def _require_ui_csrf(request: Request, supplied: object) -> None:
    expected = str(request.session.get("ui_csrf_token") or "")
    candidate = str(supplied or "")
    if not expected or not candidate or not hmac.compare_digest(expected, candidate):
        raise HTTPException(403, "A munkamenet-védelmi token hiányzik vagy érvénytelen.")


def _require_calendar_api_csrf(request: Request) -> None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(415, "A naptár API kizárólag application/json kérést fogad.")
    _require_ui_csrf(request, request.headers.get("x-csrf-token"))


def _calendar_local_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value or ""))
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    candidates: list[datetime] = []
    for fold in (0, 1):
        localized = parsed.replace(tzinfo=_BUDAPEST, fold=fold)
        if localized.astimezone(timezone.utc).astimezone(_BUDAPEST).replace(tzinfo=None) == parsed:
            candidates.append(localized)
    unique_offsets = {candidate.utcoffset() for candidate in candidates}
    if not candidates:
        raise ValueError("A megadott helyi idő a nyári időszámítás átállása miatt nem létezik.")
    if len(unique_offsets) > 1:
        raise ValueError(
            "A megadott helyi idő az óraátállítás miatt nem egyértelmű; válasszon másik időpontot."
        )
    return candidates[0].astimezone(timezone.utc)


def _calendar_entry_for_user(db: Session, user: User, entry_id: str):
    row = get_calendar_entry(db, entry_id)
    assert_calendar_project_access(db, user, row.project_id)
    return row


def auth_or_redirect(request: Request, db: Session):
    user = current_user(request, db)
    if not user or not user.active:
        return None, RedirectResponse(
            f"/login?return_to={request.url.path}",
            status_code=303,
        )
    if user.must_change_password and request.url.path != "/account/password":
        return None, RedirectResponse("/account/password", status_code=303)
    required_modules = modules_for_path(request.url.path)
    if required_modules and not can_access(user, *required_modules):
        raise HTTPException(
            status_code=403,
            detail="Ehhez a felülethez nincs szerepkör-jogosultság.",
        )
    return user, None


def module_auth_or_redirect(request: Request, db: Session, module_key: str):
    """Authenticate and enforce the requested module's role grant."""
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return None, redirect
    if not can_access(user, module_key):
        raise HTTPException(
            status_code=403,
            detail="Ehhez az üzleti modulhoz nincs szerepkör-jogosultság.",
        )
    return user, None


def partner_auth_or_redirect(request: Request, db: Session):
    access = current_partner_access(request, db)
    if not access_is_valid(access):
        request.session.pop("partner_access_id", None)
        return None, RedirectResponse("/partner-field/login", status_code=303)
    return access, None


@app.get("/health")
def health(db: Session = Depends(get_db)):
    publishing_ready, publishing = autonomous_publishing_readiness(db)
    growth_ready, growth = growth_ops_readiness(db)
    ready = publishing_ready and growth_ready
    return {
        "status": "ok" if ready else "degraded",
        "service": "imperial-intelligence-control-center",
        "version": __version__,
        "platform_version": "5.0.0",
        "autonomous_publishing": (
            "disabled" if not publishing["enabled"] else "ready" if publishing_ready else "not_ready"
        ),
        "growth_ops": "disabled" if not growth["enabled"] else "ready" if growth_ready else "not_ready",
    }


@app.get("/financial/incoming-invoices", response_class=HTMLResponse)
def financial_incoming_invoices(
    request: Request,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "platform-admin", "finance", "managing-director"}:
        raise HTTPException(
            403, "A teljes bejövőszámla-állomány csak pénzügyi jogosultsággal érhető el."
        )
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    try:
        data = incoming_invoices(
            user,
            page=page,
            page_size=50,
            search=request.query_params.get("search", ""),
            payment_status=request.query_params.get("paymentStatus", ""),
            currency=request.query_params.get("currency", ""),
        )
    except ItepFinanceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="incoming_invoices.html",
        context={"user": user, "data": data, "active": "financial"},
    )


@app.get("/financial/intelligence", response_class=HTMLResponse)
def financial_intelligence(
    request: Request, project_id: str | None = None, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "financial-control", "finance-intelligence"):
        raise HTTPException(403, "A pénzügyi intelligencia ehhez a szerepkörhöz nem érhető el.")
    try:
        data = finance_intelligence_dashboard(db, project_id=project_id, user=user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="financial_intelligence.html",
        context={"user": user, "data": data, "active": "finance-intelligence"},
    )


@app.get("/financial/allocations", response_class=HTMLResponse)
def financial_allocations(
    request: Request,
    scope: str = "unassigned",
    entity_type: str = "",
    search: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "financial-control", "finance-intelligence"):
        raise HTTPException(403, "A pénzügyi projektbesorolás ehhez a szerepkörhöz nem érhető el.")
    if user.role not in {"owner", "platform-admin", "finance", "managing-director"}:
        raise HTTPException(
            403, "A teljes pénzügyi besorolási lista csak pénzügyi jogosultsággal érhető el."
        )
    data = allocation_workspace(
        db,
        scope=scope,
        entity_type=entity_type,
        search=search,
        page=page,
        page_size=50,
    )
    return templates.TemplateResponse(
        request=request,
        name="financial_allocations.html",
        context={"user": user, "data": data, "active": "financial-allocations"},
    )


@app.get("/financial/plans", response_class=HTMLResponse)
def financial_plans_page(
    request: Request,
    project_id: str | None = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "financial-control", "finance-intelligence"):
        raise HTTPException(403)
    try:
        workspace = finance_plan_workspace(db, project_id=project_id, user=user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="financial_plans.html",
        context={
            "user": user,
            "data": workspace,
            "active": "finance-intelligence",
        },
    )


@app.post("/financial/plans")
async def financial_plan_create(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        row = create_finance_plan(
            db,
            user,
            project_id=str(form.get("project_id") or ""),
            currency=str(form.get("currency") or "HUF"),
            contract_revenue_net=form.get("contract_revenue_net") or "0",
            approved_change_revenue_net=form.get("approved_change_revenue_net") or "0",
            contingency_net=form.get("contingency_net") or "0",
            target_margin_percent=form.get("target_margin_percent") or "0",
            forecast_note=str(form.get("forecast_note") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except FinanceConcurrencyError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/financial/plans/{row.plan_id}", status_code=303)


@app.get("/financial/plans/{plan_id}", response_class=HTMLResponse)
def financial_plan_detail(request: Request, plan_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "financial-control", "finance-intelligence"):
        raise HTTPException(403)
    try:
        data = finance_plan_workspace(db, user=user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    plans = cast(list[dict[str, Any]], data["plans"])
    item = next((entry for entry in plans if entry["row"].plan_id == plan_id), None)
    if not item:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request=request,
        name="financial_plan_detail.html",
        context={
            "user": user,
            "plan": item["row"],
            "summary": project_finance_plan_summary(item["row"]),
            "active": "finance-intelligence",
        },
    )


@app.post("/financial/plans/{plan_id}/budget-lines")
async def financial_plan_budget_line_create(
    request: Request, plan_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        add_project_finance_budget_line(
            db,
            plan_id,
            user,
            cost_code=str(form.get("cost_code") or ""),
            category=str(form.get("category") or ""),
            description=str(form.get("description") or ""),
            budget_net=form.get("budget_net") or "0",
            committed_net=form.get("committed_net") or "0",
            actual_net=form.get("actual_net") or "0",
            estimate_to_complete_net=form.get("estimate_to_complete_net") or "0",
            source_type=str(form.get("source_type") or ""),
            source_id=str(form.get("source_id") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/financial/plans/{plan_id}#budget", status_code=303)


@app.post("/financial/plans/{plan_id}/cashflow-lines")
async def financial_plan_cashflow_line_create(
    request: Request, plan_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        add_project_finance_cashflow_line(
            db,
            plan_id,
            user,
            period_date=datetime.fromisoformat(str(form.get("period_date") or "")).date(),
            direction=str(form.get("direction") or ""),
            category=str(form.get("category") or ""),
            description=str(form.get("description") or ""),
            amount_net=form.get("amount_net") or "0",
            status=str(form.get("status") or "forecast"),
            source_type=str(form.get("source_type") or ""),
            source_id=str(form.get("source_id") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/financial/plans/{plan_id}#cashflow", status_code=303)


@app.post("/financial/plans/{plan_id}/submit")
def financial_plan_submit(request: Request, plan_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        submit_finance_plan(db, plan_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/financial/plans/{plan_id}", status_code=303)


@app.post("/financial/plans/{plan_id}/finance-approve")
async def financial_plan_finance_approve(
    request: Request, plan_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        finance_approve_plan(db, plan_id, user, note=str(form.get("note") or ""))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/financial/plans/{plan_id}", status_code=303)


@app.post("/financial/plans/{plan_id}/leadership-approve")
async def financial_plan_leadership_approve(
    request: Request, plan_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        leadership_approve_plan(
            db,
            plan_id,
            user,
            note=str(form.get("note") or ""),
            margin_exception_reason=str(form.get("margin_exception_reason") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/financial/plans/{plan_id}", status_code=303)


@app.post("/financial/plans/{plan_id}/clone")
def financial_plan_clone(request: Request, plan_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        clone = clone_finance_plan(db, plan_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except FinanceConcurrencyError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/financial/plans/{clone.plan_id}", status_code=303)


@app.post("/financial/plans/{plan_id}/reject")
async def financial_plan_reject(request: Request, plan_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        reject_finance_plan(db, plan_id, user, reason=str(form.get("reason") or ""))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/financial/plans/{plan_id}", status_code=303)


@app.post("/financial/allocations/{record_id}")
def financial_allocation_update(
    request: Request,
    record_id: str,
    scope: Annotated[str, Form()],
    project_id: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "financial-control", "finance-intelligence"):
        raise HTTPException(403, "A pénzügyi projektbesorolás ehhez a szerepkörhöz nem érhető el.")
    try:
        allocate_financial_record(
            db,
            record_id,
            scope=scope,
            project_id=project_id,
            note=note or "",
            actor=user.email,
            actor_role=user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, "A pénzügyi rekord nem található.") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/financial/allocations?scope=unassigned", status_code=303)


@app.get(
    "/api/content-quality/image-factory/requests",
    dependencies=[Depends(require_api_token)],
)
def api_content_image_factory_requests(
    status: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return {"requests": list_content_image_requests(db, status=status, limit=limit)}


@app.post(
    "/api/content-quality/image-factory/run",
    dependencies=[Depends(require_api_token)],
)
def api_content_image_factory_run(db: Session = Depends(get_db)):
    return process_content_image_factory(db)


@app.post("/api/content-quality/sources", dependencies=[Depends(require_api_token)])
def api_content_quality_source(payload: CopySourceIn, db: Session = Depends(get_db)):
    try:
        row = register_copy_source(db, payload, actor="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "source_key": row.source_key,
        "version": row.version,
        "content_hash": row.content_hash,
        "approved": row.approved,
    }


@app.post("/api/content-quality/briefs/validate", dependencies=[Depends(require_api_token)])
def api_content_quality_brief_validate(payload: dict):
    return validate_copy_brief(payload)


@app.post("/api/content-quality/briefs", dependencies=[Depends(require_api_token)])
def api_content_quality_brief_create(payload: dict, db: Session = Depends(get_db)):
    try:
        row = create_copy_brief(db, payload, actor="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "copy_brief_id": row.copy_brief_id,
        "status": row.status,
        "source_snapshot_hash": row.source_snapshot_hash,
    }


@app.post("/api/content-quality/briefs/{copy_brief_id}/strategy-review")
def api_content_quality_strategy_review(
    copy_brief_id: str,
    payload: StrategyReviewSubmission,
    user: User = Depends(require_role("owner", "managing-director", "marketing", "platform-admin")),
    db: Session = Depends(get_db),
):
    try:
        row = record_strategy_review(db, copy_brief_id, payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "CopyBrief nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "copy_brief_id": row.copy_brief_id,
        "review_id": row.review_id,
        "decision": row.decision,
    }


@app.post("/api/content-quality/assets", dependencies=[Depends(require_api_token)])
def api_content_quality_asset_create(
    payload: ContentAssetCreateRequest, db: Session = Depends(get_db)
):
    try:
        row = create_content_asset(
            db,
            payload.asset,
            copy_brief_id=payload.copy_brief_id,
            project_id=payload.project_id,
            generation_trace=payload.generation_trace,
            actor="api",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "state": row.state, "content_hash": row.content_hash}


@app.post(
    "/api/content-quality/assets/{asset_id}/copy-qa",
    dependencies=[Depends(require_internal_job_token)],
)
def api_content_quality_copy_qa(
    asset_id: str, payload: CopyQualityRequest, db: Session = Depends(get_db)
):
    try:
        run = run_copy_quality(
            db,
            asset_id,
            payload.editorial_review,
            actor="quality-worker",
            evaluated_on=payload.evaluated_on,
        )
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return json.loads(run.scorecard_json) | {
        "run_id": run.run_id,
        "source_snapshot_hash": run.source_snapshot_hash,
    }


def _record_mandatory_copy_gate(
    asset_id: str, payload: MandatoryCopyGateReviewSubmission, expected_gate_id: str, db: Session
):
    if payload.gate_id != expected_gate_id:
        raise HTTPException(400, f"Ehhez az endpointhoz gate_id={expected_gate_id} kötelező.")
    try:
        row = record_mandatory_copy_gate_review(
            db, asset_id, payload, actor=f"{expected_gate_id.lower()}-gate-verifier"
        )
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "asset_id": row.asset_id,
        "review_id": row.review_id,
        "gate_id": expected_gate_id,
        "decision": row.decision,
    }


@app.post(
    "/api/content-quality/assets/{asset_id}/marketing-gate",
    dependencies=[Depends(require_internal_job_token)],
)
def api_content_quality_marketing_gate(
    asset_id: str, payload: MandatoryCopyGateReviewSubmission, db: Session = Depends(get_db)
):
    return _record_mandatory_copy_gate(asset_id, payload, "MARKETING", db)


@app.post(
    "/api/content-quality/assets/{asset_id}/copywriter-gate",
    dependencies=[Depends(require_internal_job_token)],
)
def api_content_quality_copywriter_gate(
    asset_id: str, payload: MandatoryCopyGateReviewSubmission, db: Session = Depends(get_db)
):
    return _record_mandatory_copy_gate(asset_id, payload, "DIRECT_RESPONSE", db)


@app.post(
    "/api/content-quality/assets/{asset_id}/four-gates",
    dependencies=[Depends(require_internal_job_token)],
)
def api_content_quality_four_gates(
    asset_id: str, payload: FourGateSubmission, db: Session = Depends(get_db)
):
    try:
        return submit_four_gates(db, asset_id, payload, actor="gate-orchestrator")
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/content-quality/assets/{asset_id}/editorial-approval")
def api_content_quality_editorial_approval(
    asset_id: str,
    payload: ApprovalSubmission,
    user: User = Depends(require_role("owner", "managing-director", "marketing", "platform-admin")),
    db: Session = Depends(get_db),
):
    try:
        row = record_approval(db, asset_id, "HUMAN_EDITORIAL", payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "state": row.state}


@app.post("/api/content-quality/assets/{asset_id}/owner-approval")
def api_content_quality_owner_approval(
    asset_id: str,
    payload: ApprovalSubmission,
    user: User = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    try:
        row = record_approval(db, asset_id, "OWNER", payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "state": row.state}


@app.post(
    "/api/content-quality/assets/{asset_id}/visual-production",
    dependencies=[Depends(require_internal_job_token)],
)
def api_content_quality_visual_production(
    asset_id: str, payload: VisualProductionSubmission, db: Session = Depends(get_db)
):
    try:
        row = submit_visual_production(db, asset_id, payload, actor="creative-producer")
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "asset_id": row.asset_id,
        "generation_run_id": row.generation_run_id,
        "sequence_number": row.sequence_number,
        "status": row.status,
    }


@app.post(
    "/api/content-quality/assets/{asset_id}/creative-director-review",
    dependencies=[Depends(require_internal_job_token)],
)
def api_content_quality_creative_director_review(
    asset_id: str, payload: CreativeDirectorReviewSubmission, db: Session = Depends(get_db)
):
    try:
        row = record_creative_director_review(
            db, asset_id, payload, actor=payload.reviewer_identity
        )
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "review_id": row.review_id, "decision": row.decision}


@app.post(
    "/api/content-quality/assets/{asset_id}/assembly",
    dependencies=[Depends(require_internal_job_token)],
)
def api_content_quality_assembly(
    asset_id: str, payload: AssemblySubmission, db: Session = Depends(get_db)
):
    try:
        row = assemble_publication_bundle(db, asset_id, payload, actor="production-designer")
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "asset_id": row.asset_id,
        "bundle_id": row.bundle_id,
        "bundle_hash": row.bundle_hash,
        "status": row.status,
    }


@app.post("/api/content-quality/assets/{asset_id}/campaign-package")
def api_content_quality_campaign_package(
    asset_id: str,
    payload: CampaignPackage,
    user: User = Depends(require_role("owner", "managing-director", "marketing", "platform-admin")),
    db: Session = Depends(get_db),
):
    try:
        review = record_campaign_package_gate(db, asset_id, payload, actor=user.email)
        asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
        if asset is None:
            raise KeyError(asset_id)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "asset_id": asset.asset_id,
        "review_id": review.review_id,
        "campaign_package_approved": asset.campaign_package_approved,
        "campaign_package_hash": asset.campaign_package_hash,
        "campaign_artifact_set_hash": asset.campaign_artifact_set_hash,
    }


@app.post("/api/content-quality/assets/{asset_id}/release-review")
def api_content_quality_release_review(
    asset_id: str,
    payload: ReleaseReviewSubmission,
    user: User = Depends(require_role("owner", "managing-director", "marketing", "platform-admin")),
    db: Session = Depends(get_db),
):
    try:
        row = record_release_review(db, asset_id, payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "review_id": row.review_id, "decision": row.decision}


@app.post("/api/content-quality/assets/{asset_id}/publish")
def api_content_quality_publish(
    asset_id: str, user: User = Depends(require_role("owner")), db: Session = Depends(get_db)
):
    try:
        return publish_content_asset(db, asset_id, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/content-quality/assets/{asset_id}/live-review")
def api_content_quality_live_review(
    asset_id: str,
    payload: LiveReviewSubmission,
    user: User = Depends(
        require_role("owner", "managing-director", "marketing", "designer", "platform-admin")
    ),
    db: Session = Depends(get_db),
):
    try:
        return record_live_publication_review(db, asset_id, payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/content-quality/assets/{asset_id}/rollback")
def api_content_quality_rollback(
    asset_id: str,
    reason: str,
    user: User = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    try:
        row = rollback_content_asset(db, asset_id, actor=user.email, reason=reason)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    return {"asset_id": row.asset_id, "state": row.state, "content_version": row.content_version}


@app.post(
    "/api/content-quality/assets/{asset_id}/performance", dependencies=[Depends(require_api_token)]
)
def api_content_quality_performance(
    asset_id: str, payload: PerformanceSubmission, db: Session = Depends(get_db)
):
    try:
        row = record_performance_metric(
            db, asset_id, payload.metric, source_system=payload.source_system, actor="api"
        )
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"metric_id": row.metric_id, "asset_id": row.asset_id}


_MARKETING_OPERATORS = {"marketing", "owner", "managing-director", "platform-admin"}
_MARKETING_APPROVERS = {"owner", "managing-director", "platform-admin"}
_COPY_SOURCE_TYPES = (
    "brand_master",
    "brand_voice_profile",
    "conversion_guide",
    "design_system",
    "offer_version",
    "price_snapshot",
    "terms_version",
    "channel_rules",
    "product",
    "house_plan",
    "claim",
    "proof",
    "visual_rights",
)


@app.get("/marketing/automation", response_class=HTMLResponse)
def marketing_automation_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "lead-intelligence", "campaign-factory"):
        raise HTTPException(403)
    return templates.TemplateResponse(
        request=request,
        name="marketing_automation.html",
        context={
            "user": user,
            "data": marketing_automation_workspace(db),
            "active": "marketing",
        },
    )


@app.get("/marketing/deliveries", response_class=HTMLResponse)
def publication_delivery_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "marketing-control", "campaign-factory", "content-factory"):
        raise HTTPException(403)
    return templates.TemplateResponse(
        request=request,
        name="publication_deliveries.html",
        context={
            "user": user,
            "data": publication_delivery_workspace(db),
            "active": "marketing",
        },
    )


@app.post("/marketing/deliveries/{delivery_id}/retry")
async def publication_delivery_retry_ui(
    delivery_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        row = retry_publication_delivery(
            db, delivery_id, user, reason=str(form.get("reason") or "")
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/marketing/deliveries#{row.delivery_id}", status_code=303)


@app.post(
    "/api/publication-adapter/deliveries/claim",
    dependencies=[Depends(require_internal_job_token)],
)
def publication_delivery_claim_api(
    payload: PublicationDeliveryClaimIn, db: Session = Depends(get_db)
):
    try:
        rows = claim_publication_deliveries(db, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "deliveries": [serialize_publication_delivery(row, include_payload=True) for row in rows]
    }


@app.post(
    "/api/publication-adapter/deliveries/{delivery_id}/receipt",
    dependencies=[Depends(require_internal_job_token)],
)
def publication_delivery_receipt_api(
    delivery_id: str,
    payload: PublicationDeliveryReceiptIn,
    db: Session = Depends(get_db),
):
    try:
        row = record_publication_receipt(db, delivery_id, payload)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return serialize_publication_delivery(row)


@app.post("/marketing/automation/campaigns")
async def marketing_campaign_create(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        row = create_marketing_campaign(
            db,
            user,
            name=str(form.get("name") or ""),
            brand_id=str(form.get("brand_id") or ""),
            objective=str(form.get("objective") or ""),
            audience=str(form.get("audience") or ""),
            channels=_form_values(form.get("channels")),
            budget_net=form.get("budget_net") or "0",
            currency=str(form.get("currency") or "HUF"),
            target_leads=int(str(form.get("target_leads") or "0")),
            target_cpl_net=form.get("target_cpl_net") or "0",
            start_date=datetime.fromisoformat(str(form.get("start_date") or "")).date(),
            end_date=datetime.fromisoformat(str(form.get("end_date") or "")).date(),
            utm_source=str(form.get("utm_source") or ""),
            utm_medium=str(form.get("utm_medium") or ""),
            utm_campaign=str(form.get("utm_campaign") or ""),
            landing_page_url=str(form.get("landing_page_url") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/marketing/automation#campaign-{row.campaign_id}", status_code=303)


def _campaign_transition_response(
    db: Session, campaign_id: str, user: User, action: str
) -> RedirectResponse:
    try:
        if action == "submit":
            submit_marketing_campaign(db, campaign_id, user)
        elif action == "approve":
            approve_marketing_campaign(db, campaign_id, user)
        elif action == "activate":
            activate_marketing_campaign(db, campaign_id, user)
        elif action == "pause":
            pause_marketing_campaign(db, campaign_id, user)
        elif action == "complete":
            complete_marketing_campaign(db, campaign_id, user)
        else:
            raise HTTPException(404)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/marketing/automation#campaign-{campaign_id}", status_code=303)


@app.post("/marketing/automation/campaigns/{campaign_id}/{action}")
def marketing_campaign_transition(
    request: Request,
    campaign_id: str,
    action: str,
    db: Session = Depends(get_db),
):
    return _campaign_transition_response(db, campaign_id, require_session_user(request, db), action)


@app.post("/marketing/automation/leads")
async def marketing_lead_capture(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    timeframe = str(form.get("timeframe_months") or "").strip()
    try:
        row = capture_marketing_lead(
            db,
            user,
            campaign_id=str(form.get("campaign_id") or ""),
            source=str(form.get("source") or ""),
            channel=str(form.get("channel") or ""),
            landing_page_url=str(form.get("landing_page_url") or ""),
            utm_source=str(form.get("utm_source") or ""),
            utm_medium=str(form.get("utm_medium") or ""),
            utm_campaign=str(form.get("utm_campaign") or ""),
            utm_content=str(form.get("utm_content") or ""),
            full_name=str(form.get("full_name") or ""),
            email=str(form.get("email") or ""),
            phone=str(form.get("phone") or ""),
            company=str(form.get("company") or ""),
            lead_type=str(form.get("lead_type") or "b2c"),
            project_location=str(form.get("project_location") or ""),
            estimated_budget_huf=form.get("estimated_budget_huf") or "0",
            timeframe_months=int(timeframe) if timeframe else None,
            intent_summary=str(form.get("intent_summary") or ""),
            privacy_notice_accepted=form.get("privacy_notice_accepted") == "on",
            privacy_notice_version=str(form.get("privacy_notice_version") or ""),
            marketing_consent=form.get("marketing_consent") == "on",
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/marketing/automation#lead-{row.lead_id}", status_code=303)


@app.post("/marketing/automation/leads/{lead_id}/consent")
async def marketing_lead_consent_update(
    lead_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    decision = str(form.get("decision") or "")
    if decision not in {"grant", "withdraw"}:
        raise HTTPException(400, "A hozzájárulási döntés grant vagy withdraw lehet.")
    try:
        row = set_marketing_consent(
            db,
            lead_id,
            user,
            consent=decision == "grant",
            source=str(form.get("source") or "internal_record"),
            evidence=str(form.get("evidence") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/marketing/automation#lead-{row.lead_id}", status_code=303)


@app.get("/marketing/consent/{token}", response_class=HTMLResponse)
def marketing_consent_self_service(token: str, request: Request, db: Session = Depends(get_db)):
    try:
        lead = marketing_lead_by_consent_token(db, token)
    except KeyError as exc:
        raise HTTPException(404, "Érvénytelen hozzájárulás-kezelési hivatkozás.") from exc
    return templates.TemplateResponse(
        request=request,
        name="marketing_consent.html",
        context={"lead": lead, "token": token, "withdrawn": False},
    )


@app.post("/marketing/consent/{token}", response_class=HTMLResponse)
def marketing_consent_self_service_withdraw(
    token: str, request: Request, db: Session = Depends(get_db)
):
    try:
        lead = withdraw_marketing_consent_by_token(db, token)
    except KeyError as exc:
        raise HTTPException(404, "Érvénytelen hozzájárulás-kezelési hivatkozás.") from exc
    return templates.TemplateResponse(
        request=request,
        name="marketing_consent.html",
        context={"lead": lead, "token": token, "withdrawn": True},
    )


@app.post("/api/marketing/leads", dependencies=[Depends(require_api_token)])
def api_marketing_lead_capture(payload: dict, db: Session = Depends(get_db)):
    timeframe = payload.get("timeframeMonths")
    try:
        row = capture_marketing_lead(
            db,
            SimpleNamespace(role="marketing", email="marketing-api@imperial.local"),
            campaign_id=str(payload.get("campaignId") or ""),
            source=str(payload.get("source") or "api"),
            channel=str(payload.get("channel") or "web"),
            landing_page_url=str(payload.get("landingPageUrl") or ""),
            utm_source=str(payload.get("utmSource") or ""),
            utm_medium=str(payload.get("utmMedium") or ""),
            utm_campaign=str(payload.get("utmCampaign") or ""),
            utm_content=str(payload.get("utmContent") or ""),
            full_name=str(payload.get("fullName") or ""),
            email=str(payload.get("email") or ""),
            phone=str(payload.get("phone") or ""),
            company=str(payload.get("company") or ""),
            lead_type=str(payload.get("leadType") or "b2c"),
            project_location=str(payload.get("projectLocation") or ""),
            estimated_budget_huf=payload.get("estimatedBudgetHuf") or "0",
            timeframe_months=int(timeframe) if timeframe is not None else None,
            intent_summary=str(payload.get("intentSummary") or ""),
            privacy_notice_accepted=payload.get("privacyNoticeAccepted") is True,
            privacy_notice_version=str(payload.get("privacyNoticeVersion") or ""),
            marketing_consent=payload.get("marketingConsent") is True,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "lead_id": row.lead_id,
        "status": row.status,
        "score": row.score,
        "signal_count": row.signal_count,
        "marketing_consent": row.marketing_consent,
    }


def _ingest_marketing_metric_payload(db: Session, user: object, payload: dict):
    try:
        return ingest_campaign_metric(
            db,
            user,
            campaign_id=str(payload.get("campaign_id") or payload.get("campaignId") or ""),
            asset_id=str(payload.get("asset_id") or payload.get("assetId") or ""),
            metric_date=datetime.fromisoformat(
                str(payload.get("metric_date") or payload.get("metricDate") or "")
            ).date(),
            channel=str(payload.get("channel") or ""),
            source_system=str(payload.get("source_system") or payload.get("sourceSystem") or ""),
            external_key=str(payload.get("external_key") or payload.get("externalKey") or ""),
            impressions=int(payload.get("impressions") or 0),
            clicks=int(payload.get("clicks") or 0),
            landing_sessions=int(
                payload.get("landing_sessions") or payload.get("landingSessions") or 0
            ),
            form_starts=int(payload.get("form_starts") or payload.get("formStarts") or 0),
            form_completes=int(payload.get("form_completes") or payload.get("formCompletes") or 0),
            platform_conversions=int(
                payload.get("platform_conversions") or payload.get("platformConversions") or 0
            ),
            spend_net=payload.get("spend_net") or payload.get("spendNet") or "0",
            currency=str(payload.get("currency") or "HUF"),
            raw_payload=payload,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/marketing/campaign-metrics", dependencies=[Depends(require_api_token)])
def api_marketing_campaign_metric(payload: dict, db: Session = Depends(get_db)):
    row = _ingest_marketing_metric_payload(
        db,
        SimpleNamespace(role="marketing", email="marketing-metric-api@imperial.local"),
        payload,
    )
    return {
        "metric_id": row.metric_id,
        "campaign_id": row.campaign_id,
        "external_key": row.external_key,
        "raw_payload_hash": row.raw_payload_hash,
    }


@app.post("/marketing/automation/metrics")
async def marketing_campaign_metric_create(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    row = _ingest_marketing_metric_payload(db, user, dict(form))
    return RedirectResponse(f"/marketing/automation#campaign-{row.campaign_id}", status_code=303)


@app.post("/marketing/automation/optimization-proposals/{campaign_id}")
async def marketing_campaign_optimize(
    request: Request, campaign_id: str, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        row = propose_optimization(
            db,
            campaign_id,
            user,
            rationale=str(form.get("rationale") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/marketing/automation#decision-{row.decision_id}", status_code=303)


@app.post("/marketing/automation/optimizations/{decision_id}/decide")
async def marketing_optimization_decide(
    request: Request, decision_id: str, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        decide_optimization(
            db,
            decision_id,
            user,
            decision=str(form.get("decision") or ""),
            note=str(form.get("note") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/marketing/automation#decision-{decision_id}", status_code=303)


@app.post("/marketing/automation/optimizations/{decision_id}/execute")
def marketing_optimization_execute(
    request: Request, decision_id: str, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    try:
        execute_optimization(db, decision_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/marketing/automation#decision-{decision_id}", status_code=303)


@app.post("/marketing/automation/leads/{lead_id}/qualify")
async def marketing_lead_qualify(request: Request, lead_id: str, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        qualify_marketing_lead(
            db,
            lead_id,
            user,
            note=str(form.get("note") or ""),
            override_reason=str(form.get("override_reason") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/marketing/automation#lead-{lead_id}", status_code=303)


@app.post("/marketing/automation/leads/{lead_id}/handoff")
async def marketing_lead_handoff(request: Request, lead_id: str, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        handoff_lead_to_crm(
            db,
            lead_id,
            user,
            assigned_sales_email=str(form.get("assigned_sales_email") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/marketing/automation#lead-{lead_id}", status_code=303)


@app.post("/marketing/automation/leads/{lead_id}/sales-decision")
async def marketing_lead_sales_decision(
    request: Request, lead_id: str, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        decide_sales_lead(
            db,
            lead_id,
            user,
            decision=str(form.get("decision") or ""),
            note=str(form.get("note") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/marketing/automation#lead-{lead_id}", status_code=303)


def _form_values(value: object) -> list[str]:
    return [
        item.strip() for item in str(value or "").replace(",", "\n").splitlines() if item.strip()
    ]


def _form_text(value: object, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, StarletteUploadFile):
        raise ValueError("Szöveges mező helyett fájl érkezett.")
    return str(value)


def _optional_form_text(value: object) -> str | None:
    text_value = _form_text(value).strip()
    return text_value or None


def _form_int(value: object, default: int = 0) -> int:
    text_value = _form_text(value).strip()
    return int(text_value) if text_value else default


def _required_form_datetime(value: object) -> datetime:
    parsed = _form_datetime(_form_text(value))
    if parsed is None:
        raise ValueError("A dátum és idő megadása kötelező.")
    return parsed


def _marketing_payload(value: str) -> dict:
    try:
        payload = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "A kiegészítő forrásadat nem érvényes JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "A kiegészítő forrásadatnak objektumnak kell lennie.")
    return payload


@app.get("/marketing", response_class=HTMLResponse)
def marketing_workspace(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    sources = list(
        db.scalars(select(CopySourceRecord).order_by(CopySourceRecord.id.desc()).limit(250))
    )
    brief_rows = list(
        db.scalars(select(CopyBriefRecord).order_by(CopyBriefRecord.created_at.desc()).limit(150))
    )
    asset_rows = list(
        db.scalars(
            select(ContentAssetRecord).order_by(ContentAssetRecord.updated_at.desc()).limit(150)
        )
    )
    run_ids = [row.latest_run_id for row in asset_rows if row.latest_run_id]
    specialist_by_run: dict[str, dict[str, str]] = {}
    if run_ids:
        for gate in db.scalars(
            select(ContentGateDecision).where(
                ContentGateDecision.run_id.in_(run_ids),
                ContentGateDecision.gate_id.in_(
                    (
                        "GATE_2_LEGAL_POLICY",
                        "GATE_3_FINANCIAL_COMMERCIAL",
                        "GATE_4_TECHNICAL_FACTUAL",
                    )
                ),
            )
        ):
            specialist_by_run.setdefault(gate.run_id, {})[gate.gate_id] = gate.decision
    asset_ids = [row.asset_id for row in asset_rows]
    creative_by_asset: dict[str, CreativeProductionRunRecord] = {}
    bundle_by_asset: dict[str, PublicationBundleRecord] = {}
    if asset_ids:
        for creative in db.scalars(
            select(CreativeProductionRunRecord)
            .where(CreativeProductionRunRecord.asset_id.in_(asset_ids))
            .order_by(CreativeProductionRunRecord.sequence_number.desc())
        ):
            creative_by_asset.setdefault(creative.asset_id, creative)
        for bundle in db.scalars(
            select(PublicationBundleRecord)
            .where(PublicationBundleRecord.asset_id.in_(asset_ids))
            .order_by(PublicationBundleRecord.created_at.desc())
        ):
            bundle_by_asset.setdefault(bundle.asset_id, bundle)
    briefs = []
    for brief_row in brief_rows:
        data = json.loads(brief_row.brief_json or "{}")
        briefs.append({"row": brief_row, "data": data})
    assets = []
    for asset_row in asset_rows:
        data = json.loads(asset_row.content_json or "{}")
        trace = json.loads(asset_row.generation_trace_json or "{}")
        assets.append(
            {
                "row": asset_row,
                "data": data,
                "trace": trace,
                "specialist": specialist_by_run.get(asset_row.latest_run_id or "", {}),
                "creative": creative_by_asset.get(asset_row.asset_id),
                "bundle": bundle_by_asset.get(asset_row.asset_id),
            }
        )
    return templates.TemplateResponse(
        request=request,
        name="marketing.html",
        context={
            "user": user,
            "active": "marketing",
            "sources": sources,
            "briefs": briefs,
            "assets": assets,
            "source_types": _COPY_SOURCE_TYPES,
            "can_operate": user.role in _MARKETING_OPERATORS,
            "can_approve_source": user.role in _MARKETING_APPROVERS,
        },
    )


@app.post("/marketing/sources")
async def marketing_source_create(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if user.role not in _MARKETING_OPERATORS:
        raise HTTPException(403, "Nincs marketing forráskezelési jogosultság.")
    form = await request.form()
    payload = _marketing_payload(str(form.get("payload_json") or "{}"))
    record_id = str(form.get("record_id") or "").strip()
    if record_id:
        payload.setdefault("record_id", record_id)
    addressing = str(form.get("addressing") or "").strip()
    if addressing:
        payload.setdefault("addressing", addressing)
    try:
        source = CopySourceIn(
            source_key=str(form.get("source_key") or ""),
            source_type=str(form.get("source_type") or ""),
            brand_id=str(form.get("brand_id") or ""),
            page_id=str(form.get("page_id") or "") or None,
            campaign_id=str(form.get("campaign_id") or "") or None,
            asset_type=str(form.get("asset_type") or "") or None,
            version=str(form.get("version") or ""),
            priority=int(str(form.get("priority") or "100")),
            status="draft",
            approved=False,
            valid_from=date.fromisoformat(str(form.get("valid_from")))
            if form.get("valid_from")
            else None,
            valid_until=date.fromisoformat(str(form.get("valid_until")))
            if form.get("valid_until")
            else None,
            source_url=str(form.get("source_url") or "") or None,
            payload=payload,
        )
        row = register_copy_source(db, source, actor=user.email)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/marketing#source-{row.id}", status_code=303)


@app.post("/marketing/sources/{source_id}/review")
async def marketing_source_review(source_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if user.role not in _MARKETING_APPROVERS:
        raise HTTPException(403, "Forrás jóváhagyásához vezetői jogosultság szükséges.")
    form = await request.form()
    try:
        row = review_copy_source(
            db,
            source_id,
            str(form.get("decision") or ""),
            str(form.get("note") or ""),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, "A forrásverzió nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#source-{row.id}", status_code=303)


@app.post("/marketing/briefs")
async def marketing_brief_create(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if user.role not in _MARKETING_OPERATORS:
        raise HTTPException(403, "Nincs kampánybrief-kezelési jogosultság.")
    form = await request.form()
    payload = {
        "copy_brief_id": str(form.get("copy_brief_id") or ""),
        "brand_id": str(form.get("brand_id") or ""),
        "asset_type": str(form.get("asset_type") or ""),
        "channel": str(form.get("channel") or ""),
        "page_id": str(form.get("page_id") or "") or None,
        "campaign_id": str(form.get("campaign_id") or "") or None,
        "campaign_objective": str(form.get("campaign_objective") or ""),
        "primary_conversion": str(form.get("primary_conversion") or ""),
        "target_persona_id": str(form.get("target_persona_id") or ""),
        "awareness_level": str(form.get("awareness_level") or ""),
        "market_sophistication_level": str(form.get("market_sophistication_level") or ""),
        "core_problem": str(form.get("core_problem") or ""),
        "desired_outcome": str(form.get("desired_outcome") or ""),
        "primary_promise": str(form.get("primary_promise") or ""),
        "unique_mechanism": str(form.get("unique_mechanism") or ""),
        "offer_version_id": str(form.get("offer_version_id") or ""),
        "price_snapshot_id": str(form.get("price_snapshot_id") or ""),
        "terms_version_id": str(form.get("terms_version_id") or ""),
        "claim_ids": _form_values(form.get("claim_ids")),
        "proof_ids": _form_values(form.get("proof_ids")),
        "product_id": str(form.get("product_id") or "") or None,
        "house_plan_id": str(form.get("house_plan_id") or "") or None,
        "primary_objection_ids": _form_values(form.get("primary_objection_ids")),
        "secondary_objection_ids": _form_values(form.get("secondary_objection_ids")),
        "risk_reversal": str(form.get("risk_reversal") or ""),
        "urgency_reason": str(form.get("urgency_reason") or "") or None,
        "scarcity_reason": str(form.get("scarcity_reason") or "") or None,
        "primary_cta_type": str(form.get("primary_cta_type") or ""),
        "secondary_cta_type": str(form.get("secondary_cta_type") or "") or None,
        "brand_voice_profile": str(form.get("brand_voice_profile") or ""),
        "required_slogan": str(form.get("required_slogan") or ""),
        "required_slogan_version": str(form.get("required_slogan_version") or ""),
        "forbidden_phrases": _form_values(form.get("forbidden_phrases")),
        "required_keywords": _form_values(form.get("required_keywords")),
        "landing_message_match_id": str(form.get("landing_message_match_id") or ""),
        "monthly_promotion_id": str(form.get("monthly_promotion_id") or "") or None,
        "monthly_promotion_copy_required": form.get("monthly_promotion_copy_required") is not None,
        "valid_from": str(form.get("valid_from") or ""),
        "valid_until": str(form.get("valid_until") or ""),
    }
    try:
        row = create_copy_brief(db, payload, actor=user.email)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#brief-{row.copy_brief_id}", status_code=303)


@app.post("/marketing/briefs/{copy_brief_id}/strategy-review")
async def marketing_strategy_review(
    copy_brief_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in _MARKETING_OPERATORS:
        raise HTTPException(403, "Nincs stratégiai review jogosultság.")
    form = await request.form()
    try:
        payload = StrategyReviewSubmission(
            decision=Decision(str(form.get("decision") or "")),
            strategist_run_id=str(form.get("strategist_run_id") or ""),
            reviewer_run_id=f"STR-REV-{uuid4().hex[:12].upper()}",
            reviewer_identity=user.email,
            objective_score=int(str(form.get("objective_score") or "0")),
            audience_score=int(str(form.get("audience_score") or "0")),
            offer_score=int(str(form.get("offer_score") or "0")),
            message_architecture_score=int(str(form.get("message_architecture_score") or "0")),
            channel_plan_score=int(str(form.get("channel_plan_score") or "0")),
            brand_fit_score=int(str(form.get("brand_fit_score") or "0")),
            feasibility_score=int(str(form.get("feasibility_score") or "0")),
            tactical_plan=str(form.get("tactical_plan") or ""),
            asset_plan=_form_values(form.get("asset_plan")),
            findings=_form_values(form.get("findings")),
        )
        record_strategy_review(db, copy_brief_id, payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "A CopyBrief nem található.") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#brief-{copy_brief_id}", status_code=303)


@app.post("/marketing/assets")
async def marketing_asset_create(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if user.role not in _MARKETING_OPERATORS:
        raise HTTPException(403, "Nincs tartalom-előállítási jogosultság.")
    form = await request.form()
    copy_brief_id = str(form.get("copy_brief_id") or "")
    brief_row = db.get(CopyBriefRecord, copy_brief_id)
    if not brief_row:
        raise HTTPException(404, "A CopyBrief nem található.")
    try:
        brief = CopyBrief.model_validate_json(brief_row.brief_json)
        title = str(form.get("title") or "")
        body = str(form.get("body") or "")
        cta = str(form.get("cta") or "")
        asset = ContentAsset(
            asset_id=str(form.get("asset_id") or ""),
            title=title,
            body=body,
            cta=cta,
            cta_type_used=brief.primary_cta_type,
            slogan=str(form.get("slogan") or brief.required_slogan),
            slogan_version_used=brief.required_slogan_version,
            detected_brand_ids=[brief.brand_id],
            claim_ids_used=_form_values(form.get("claim_ids_used")) or brief.claim_ids,
            proof_ids_used=_form_values(form.get("proof_ids_used")) or brief.proof_ids,
            objection_ids_handled=_form_values(form.get("objection_ids_handled"))
            or brief.primary_objection_ids,
            required_keywords_used=_form_values(form.get("required_keywords_used"))
            or brief.required_keywords,
            offer_version_id_used=brief.offer_version_id,
            price_snapshot_id_used=brief.price_snapshot_id,
            terms_version_id_used=brief.terms_version_id,
            landing_message_match_id_used=brief.landing_message_match_id,
            monthly_promotion_id_used=brief.monthly_promotion_id,
            monthly_promotion_copy_text=str(form.get("monthly_promotion_copy_text") or "") or None,
            factual_claims=_form_values(form.get("factual_claims")),
            price_mentions=_form_values(form.get("price_mentions")),
            deadline_mentions=_form_values(form.get("deadline_mentions")),
            condition_mentions=_form_values(form.get("condition_mentions")),
            action_risk_level=int(str(form.get("action_risk_level") or "0")),
        )
        copy_mode = str(form.get("copy_mode") or "original_concept")
        trace = {
            "stages": list(GENERATION_STAGES),
            "brand_id": brief.brand_id,
            "generation_run_id": f"GEN-{uuid4().hex[:16].upper()}",
            "copy_mode": copy_mode,
            "copy_fingerprint": hashlib.sha256(
                f"{title}\n{body}\n{cta}".encode("utf-8")
            ).hexdigest(),
            "copy_concept_id": str(form.get("copy_concept_id") or ""),
            "copy_architecture_id": str(form.get("copy_architecture_id") or ""),
            "copy_structure_signature": str(form.get("copy_structure_signature") or ""),
            "source_text_usage_ratio": float(str(form.get("source_text_usage_ratio") or "0")),
            "creative_quality_benchmark_id": "prefab-facebook-etalon-v1",
            "creative_rationale": str(form.get("creative_rationale") or ""),
            "introduces_new_factual_claims": form.get("introduces_new_factual_claims") is not None,
            "human_fact_review_required": form.get("human_fact_review_required") is not None,
            "meaning_preservation_checked": form.get("meaning_preservation_checked") is not None,
            "source_prevalidation_requested": False,
            "consumer_promise_plain_language": brief.primary_promise,
            "promise_reason_or_mechanism": brief.unique_mechanism,
            "offer_terms_plain_language": brief.risk_reversal,
            "cta_next_step_plain_language": cta,
        }
        row = create_content_asset(
            db,
            asset,
            copy_brief_id=copy_brief_id,
            project_id=str(form.get("project_id") or "") or None,
            generation_trace=trace,
            actor=user.email,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#asset-{row.asset_id}", status_code=303)


@app.post("/marketing/assets/{asset_id}/copy-qa")
async def marketing_asset_copy_qa(asset_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if user.role not in {"language-editor", "owner", "managing-director", "platform-admin"}:
        raise HTTPException(
            403, "Copy QA-hoz független szövegírói vagy vezetői jogosultság szükséges."
        )
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise HTTPException(404, "A tartalomasset nem található.")
    form = await request.form()
    score_keys = (
        "idiomatic_hungarian_score",
        "grammar_score",
        "semantic_clarity_score",
        "terminology_score",
        "hook_strength_score",
        "offer_clarity_score",
        "specificity_score",
        "persuasion_score",
        "brand_voice_score",
        "conversion_path_score",
    )
    try:
        review = build_human_editorial_review(
            asset,
            reviewer_identity=user.email,
            decision=str(form.get("decision") or ""),
            scores={key: int(str(form.get(key) or "0")) for key in score_keys},
            consumer_interpretation=str(form.get("consumer_interpretation") or ""),
            offer_interpretation=str(form.get("offer_interpretation") or ""),
            cta_interpretation=str(form.get("cta_interpretation") or ""),
            findings=_form_values(form.get("findings")),
            required_repairs=_form_values(form.get("required_repairs")),
        )
        run_copy_quality(db, asset_id, review, actor=user.email)
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#asset-{asset_id}", status_code=303)


@app.post("/marketing/assets/{asset_id}/mandatory-gates/{gate_id}")
async def marketing_asset_mandatory_gate(
    asset_id: str, gate_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    allowed = {
        "MARKETING": {"marketing", "owner", "managing-director", "platform-admin"},
        "DIRECT_RESPONSE": {"copywriter", "owner", "managing-director", "platform-admin"},
    }
    if gate_id not in allowed or user.role not in allowed[gate_id]:
        raise HTTPException(403, "Ehhez a kötelező tartalomkapuhoz nincs jogosultság.")
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise HTTPException(404, "A tartalomasset nem található.")
    form = await request.form()
    dimensions = {
        "MARKETING": (
            "objective_fit",
            "audience_fit",
            "offer_strength",
            "message_architecture",
            "conversion_path",
            "qualification_quality",
            "brand_specificity",
        ),
        "DIRECT_RESPONSE": (
            "hook_strength",
            "emotional_tension",
            "specificity",
            "natural_hungarian",
            "direct_response_persuasion",
            "clarity",
            "cta_strength",
            "brand_voice",
        ),
    }
    try:
        review = build_human_mandatory_gate_review(
            asset,
            gate_id=gate_id,
            reviewer_identity=user.email,
            decision=str(form.get("decision") or ""),
            dimension_scores={key: int(str(form.get(key) or "0")) for key in dimensions[gate_id]},
            consumer_readback=str(form.get("consumer_readback") or ""),
            conversion_rationale=str(form.get("conversion_rationale") or ""),
            strongest_objection=str(form.get("strongest_objection") or ""),
            dry_copy_detected=form.get("dry_copy_detected") is not None,
            generic_copy_detected=form.get("generic_copy_detected") is not None,
            brand_voice_violation_detected=form.get("brand_voice_violation_detected") is not None,
            findings=_form_values(form.get("findings")),
            required_repairs=_form_values(form.get("required_repairs")),
        )
        record_mandatory_copy_gate_review(db, asset_id, review, actor=user.email)
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#asset-{asset_id}", status_code=303)


@app.post("/marketing/assets/{asset_id}/specialist-gates/{gate_id}")
async def marketing_asset_specialist_gate(
    asset_id: str, gate_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    allowed = {
        "GATE_2_LEGAL_POLICY": {"legal", "owner", "managing-director", "platform-admin"},
        "GATE_3_FINANCIAL_COMMERCIAL": {"finance", "owner", "managing-director", "platform-admin"},
        "GATE_4_TECHNICAL_FACTUAL": {
            "technical-prep",
            "designer",
            "owner",
            "managing-director",
            "platform-admin",
        },
    }
    if gate_id not in allowed or user.role not in allowed[gate_id]:
        raise HTTPException(403, "Ehhez a specialistakapuhoz nincs jogosultság.")
    form = await request.form()
    try:
        review_human_specialist_gate(
            db,
            asset_id,
            gate_id,
            str(form.get("decision") or ""),
            form.get("relevant") is not None,
            str(form.get("evidence") or ""),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, "A tartalomasset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#asset-{asset_id}", status_code=303)


@app.post("/marketing/assets/{asset_id}/editorial-approval")
async def marketing_asset_editorial_approval(
    asset_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in {"marketing", "copywriter", "managing-director", "platform-admin"}:
        raise HTTPException(403, "Szerkesztői döntéshez nincs jogosultság.")
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise HTTPException(404, "A tartalomasset nem található.")
    if asset.created_by.strip().lower() == user.email.strip().lower():
        raise HTTPException(409, "A tartalom létrehozója nem hagyhatja jóvá a saját assetjét.")
    form = await request.form()
    try:
        record_approval(
            db,
            asset_id,
            "HUMAN_EDITORIAL",
            ApprovalSubmission(
                decision=str(form.get("decision") or ""), note=str(form.get("note") or "") or None
            ),
            actor=user.email,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#asset-{asset_id}", status_code=303)


@app.post("/marketing/assets/{asset_id}/owner-approval")
async def marketing_asset_owner_approval(
    asset_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role != "owner":
        raise HTTPException(403, "Tulajdonosi döntéshez tulajdonosi jogosultság szükséges.")
    form = await request.form()
    try:
        record_approval(
            db,
            asset_id,
            "OWNER",
            ApprovalSubmission(
                decision=str(form.get("decision") or ""), note=str(form.get("note") or "") or None
            ),
            actor=user.email,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#asset-{asset_id}", status_code=303)


async def _save_marketing_upload(upload: object, file_stem: str) -> tuple[Path, str]:
    if not hasattr(upload, "read"):
        raise HTTPException(400, "A képfájl feltöltése kötelező.")
    content_type = str(getattr(upload, "content_type", "") or "").lower()
    extensions = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
    if content_type not in extensions:
        raise HTTPException(400, "Csak PNG, JPEG vagy WebP képfájl tölthető fel.")
    content = await upload.read(20 * 1024 * 1024 + 1)
    if not content or len(content) > 20 * 1024 * 1024:
        raise HTTPException(400, "A képfájl mérete 1 bájt és 20 MB között lehet.")
    MARKETING_CREATIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = MARKETING_CREATIVE_DIR / f"{file_stem}{extensions[content_type]}"
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def _marketing_artifact_path(file_stem: str) -> Path | None:
    matches = (
        list(MARKETING_CREATIVE_DIR.glob(f"{file_stem}.*"))
        if MARKETING_CREATIVE_DIR.exists()
        else []
    )
    return matches[0] if len(matches) == 1 else None


@app.post("/marketing/assets/{asset_id}/visual-production")
async def marketing_visual_production(
    asset_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in {"marketing", "designer", "creative-director", "platform-admin"}:
        raise HTTPException(403, "Vizuális gyártáshoz nincs jogosultság.")
    form = await request.form()
    run_id = f"VIS-{uuid4().hex[:16].upper()}"
    path, output_sha = await _save_marketing_upload(form.get("creative_file"), run_id)
    try:
        row = submit_visual_production(
            db,
            asset_id,
            VisualProductionSubmission(
                generation_run_id=run_id,
                producer_identity=user.email,
                visual_direction_id=str(form.get("visual_direction_id") or ""),
                platform=str(form.get("platform") or ""),
                width_px=int(str(form.get("width_px") or "0")),
                height_px=int(str(form.get("height_px") or "0")),
                output_uri=f"/marketing/assets/{asset_id}/creative/{run_id}",
                output_sha256=output_sha,
                generation_prompt_hash=hashlib.sha256(
                    str(form.get("creative_rationale") or "").encode("utf-8")
                ).hexdigest(),
                contains_text=form.get("contains_text") is not None,
            ),
            actor=user.email,
        )
    except (KeyError, TypeError, ValueError) as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#asset-{row.asset_id}", status_code=303)


@app.get("/marketing/assets/{asset_id}/creative/{run_id}")
def marketing_creative_file(
    asset_id: str, run_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if not can_access(user, "marketing-control", "content-factory"):
        raise HTTPException(403, "Nincs jogosultság.")
    row = db.get(CreativeProductionRunRecord, run_id)
    path = _marketing_artifact_path(run_id)
    if not row or row.asset_id != asset_id or not path:
        raise HTTPException(404, "A kreatív fájl nem található.")
    return FileResponse(path)


@app.post("/marketing/assets/{asset_id}/creative-director-review")
async def marketing_creative_director_review(
    asset_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in {"creative-director", "platform-admin"}:
        raise HTTPException(403, "Kreatív igazgatói review jogosultság szükséges.")
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    creative = db.scalar(
        select(CreativeProductionRunRecord)
        .where(
            CreativeProductionRunRecord.asset_id == asset_id,
            CreativeProductionRunRecord.status == "DIRECTOR_QA",
        )
        .order_by(CreativeProductionRunRecord.sequence_number.desc())
    )
    if not asset or not creative:
        raise HTTPException(404, "A review-ra váró kreatív nem található.")
    form = await request.form()
    try:
        review = build_human_creative_director_review(
            asset,
            creative,
            reviewer_identity=user.email,
            decision=str(form.get("decision") or ""),
            review={
                "brand_fidelity_score": int(str(form.get("brand_fidelity_score") or "0")),
                "composition_score": int(str(form.get("composition_score") or "0")),
                "distinctiveness_score": int(str(form.get("distinctiveness_score") or "0")),
                "typography_score": int(str(form.get("typography_score") or "0")),
                "asset_accuracy_score": int(str(form.get("asset_accuracy_score") or "0")),
                "minimum_contrast_ratio": float(str(form.get("minimum_contrast_ratio") or "0")),
                "full_subject_expected": form.get("full_subject_expected") is not None,
                "full_subject_contour_visible": form.get("full_subject_contour_visible")
                is not None,
                "declared_crop_intent": str(form.get("declared_crop_intent") or "") or None,
                "accidental_crop_absent": form.get("accidental_crop_absent") is not None,
                "text_boxes_within_bounds": form.get("text_boxes_within_bounds") is not None,
                "text_background_clear": form.get("text_background_clear") is not None,
                "text_overlaps_primary_subject": form.get("text_overlaps_primary_subject")
                is not None,
                "text_background_overlaps_primary_subject": form.get(
                    "text_background_overlaps_primary_subject"
                )
                is not None,
                "minimum_source_font_px": int(str(form.get("minimum_source_font_px") or "0")),
                "decorative_frame_area_ratio": float(
                    str(form.get("decorative_frame_area_ratio") or "0")
                ),
                "primary_subject_dominance_required": form.get("primary_subject_dominance_required")
                is not None,
                "primary_subject_area_ratio": float(
                    str(form.get("primary_subject_area_ratio") or "0")
                ),
                "logo_lockup_brand_native": form.get("logo_lockup_brand_native") is not None,
                "proof_caption_present": form.get("proof_caption_present") is not None,
                "proof_caption_semantically_complete": form.get(
                    "proof_caption_semantically_complete"
                )
                is not None,
                "findings": _form_values(form.get("findings")),
                "repair_brief": _form_values(form.get("repair_brief")),
            },
        )
        record_creative_director_review(db, asset_id, review, actor=user.email)
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#asset-{asset_id}", status_code=303)


@app.post("/marketing/assets/{asset_id}/assembly")
async def marketing_asset_assembly(asset_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if user.role not in {"marketing", "designer", "copywriter", "platform-admin"}:
        raise HTTPException(403, "Publikációs assembly jogosultság szükséges.")
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    creative = db.scalar(
        select(CreativeProductionRunRecord)
        .where(
            CreativeProductionRunRecord.asset_id == asset_id,
            CreativeProductionRunRecord.status == "APPROVED",
        )
        .order_by(CreativeProductionRunRecord.sequence_number.desc())
    )
    if not asset or not creative:
        raise HTTPException(404, "A jóváhagyott kreatív nem található.")
    form = await request.form()
    assembly_run_id = f"ASM-{uuid4().hex[:16].upper()}"
    path, output_sha = await _save_marketing_upload(form.get("export_file"), assembly_run_id)
    try:
        row = assemble_publication_bundle(
            db,
            asset_id,
            AssemblySubmission(
                assembly_run_id=assembly_run_id,
                assembler_identity=user.email,
                visual_generation_run_id=creative.generation_run_id,
                copy_content_sha256=asset.content_hash,
                pairing_rationale=str(form.get("pairing_rationale") or ""),
                exports=[
                    PlatformExport(
                        platform=str(form.get("platform") or ""),
                        placement=str(form.get("placement") or ""),
                        width_px=int(str(form.get("width_px") or "0")),
                        height_px=int(str(form.get("height_px") or "0")),
                        output_uri=f"/marketing/assets/{asset_id}/exports/{assembly_run_id}",
                        output_sha256=output_sha,
                        safe_zone_checked=form.get("safe_zone_checked") is not None,
                        text_legibility_checked=form.get("text_legibility_checked") is not None,
                    )
                ],
            ),
            actor=user.email,
        )
    except (TypeError, ValueError) as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#asset-{row.asset_id}", status_code=303)


@app.get("/marketing/assets/{asset_id}/exports/{assembly_run_id}")
def marketing_export_file(
    asset_id: str, assembly_run_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if not can_access(user, "marketing-control", "content-factory"):
        raise HTTPException(403, "Nincs jogosultság.")
    row = db.scalar(
        select(PublicationBundleRecord).where(
            PublicationBundleRecord.asset_id == asset_id,
            PublicationBundleRecord.assembly_run_id == assembly_run_id,
        )
    )
    path = _marketing_artifact_path(assembly_run_id)
    if not row or not path:
        raise HTTPException(404, "A publikációs export nem található.")
    return FileResponse(path)


@app.post("/marketing/assets/{asset_id}/release-review")
async def marketing_asset_release_review(
    asset_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in {"marketing", "managing-director", "platform-admin"}:
        raise HTTPException(403, "Release QA jogosultság szükséges.")
    form = await request.form()
    try:
        record_release_review(
            db,
            asset_id,
            ReleaseReviewSubmission(
                decision=Decision(str(form.get("decision") or "")),
                reviewer_run_id=f"REL-HUMAN-{uuid4().hex[:12].upper()}",
                reviewer_identity=user.email,
                strategy_match_score=int(str(form.get("strategy_match_score") or "0")),
                copy_visual_consistency_score=int(
                    str(form.get("copy_visual_consistency_score") or "0")
                ),
                channel_fit_score=int(str(form.get("channel_fit_score") or "0")),
                conversion_path_score=int(str(form.get("conversion_path_score") or "0")),
                four_gate_recheck_passed=form.get("four_gate_recheck_passed") is not None,
                brand_recheck_passed=form.get("brand_recheck_passed") is not None,
                technical_export_check_passed=form.get("technical_export_check_passed") is not None,
                findings=_form_values(form.get("findings")),
            ),
            actor=user.email,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#asset-{asset_id}", status_code=303)


@app.post("/marketing/assets/{asset_id}/publish")
def marketing_asset_publish(asset_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if user.role != "owner":
        raise HTTPException(403, "Publikációt csak tulajdonos indíthat.")
    try:
        publish_content_asset(db, asset_id, actor=user.email)
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#asset-{asset_id}", status_code=303)


@app.post("/marketing/assets/{asset_id}/live-review")
async def marketing_asset_live_review(
    asset_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    reviewer_roles = {
        "marketing": "ONLINE_MARKETING_MANAGER",
        "creative-director": "CREATIVE_DIRECTOR",
        "copywriter": "DIRECT_RESPONSE_COPYWRITER",
    }
    if user.role not in reviewer_roles:
        raise HTTPException(403, "Élő double checkhez kijelölt szakértői szerepkör szükséges.")
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == asset_id))
    if not asset:
        raise HTTPException(404, "A tartalomasset nem található.")
    form = await request.form()
    screenshot_id = f"LIVE-{uuid4().hex[:16].upper()}"
    path, screenshot_sha = await _save_marketing_upload(form.get("screenshot_file"), screenshot_id)
    try:
        record_live_publication_review(
            db,
            asset_id,
            LiveReviewSubmission(
                reviewer_role=reviewer_roles[user.role],
                reviewer_identity=user.email,
                decision=str(form.get("decision") or ""),
                live_url=str(form.get("live_url") or ""),
                screenshot_sha256=screenshot_sha,
                rendered_copy_sha256=asset.content_hash,
                findings=_form_values(form.get("findings")),
            ),
            actor=user.email,
        )
    except (KeyError, ValueError) as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/marketing#asset-{asset_id}", status_code=303)


@app.post("/marketing/assets/{asset_id}/rollback")
async def marketing_asset_rollback(asset_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if user.role != "owner":
        raise HTTPException(403, "Visszavonást csak tulajdonos indíthat.")
    form = await request.form()
    reason = str(form.get("reason") or "")
    if len(reason.strip()) < 10:
        raise HTTPException(400, "A visszavonás indoklása legalább 10 karakter legyen.")
    try:
        rollback_content_asset(db, asset_id, actor=user.email, reason=reason)
    except KeyError as exc:
        raise HTTPException(404, "A tartalomasset nem található.") from exc
    return RedirectResponse(f"/marketing#asset-{asset_id}", status_code=303)


@app.get("/health/live")
def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        publishing_ready, publishing = autonomous_publishing_readiness(db)
        growth_ready, growth = growth_ops_readiness(db)
        if not publishing_ready or not growth_ready:
            return JSONResponse(
                {
                    "status": "not_ready",
                    "database": "ok",
                    "autonomous_publishing": (
                        "disabled"
                        if not publishing["enabled"]
                        else "ready"
                        if publishing_ready
                        else "not_ready"
                    ),
                    "growth_ops": (
                        "disabled"
                        if not growth["enabled"]
                        else "ready"
                        if growth_ready
                        else "not_ready"
                    ),
                },
                status_code=503,
            )
        return {
            "status": "ready",
            "database": "ok",
            "autonomous_publishing": "disabled" if not publishing["enabled"] else "ready",
            "growth_ops": "disabled" if not growth["enabled"] else "ready",
        }
    except Exception as exc:
        return JSONResponse({"status": "not_ready", "error": str(exc)}, status_code=503)


@app.get("/api/auth/session")
def api_auth_session(user: User = Depends(require_session_user)):
    role = role_definition(user.role)
    if not role:
        raise HTTPException(403, "A felhasználó szerepköre nincs regisztrálva.")
    return {
        "authenticated": True,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
        },
        "role": public_role_payload(user.role),
    }


def require_demo_runtime() -> None:
    if not settings.demo_runtime_enabled:
        raise HTTPException(404, "Demo runtime is disabled in this environment.")


def _demo_state_for(user: User):
    require_demo_runtime()
    state = demo_runtime.state()
    role = role_definition(user.role)
    if not role:
        raise HTTPException(403, "A felhasználó szerepköre nincs regisztrálva.")
    allowed = role.module_access
    state["modules"] = [module for module in state["modules"] if module["id"] in allowed]
    state["events"] = [
        event
        for event in state.get("events", [])
        if event.get("producer") in allowed
        or any(consumer in allowed for consumer in event.get("consumers", []))
    ]
    if user.role not in {"owner", "managing-director", "platform-admin"}:
        state["journeys"] = []
    return state


@app.get("/api/demo/state")
def api_demo_state(user: User = Depends(require_session_user)):
    return _demo_state_for(user)


@app.get("/api/demo/modules")
def api_demo_modules(user: User = Depends(require_session_user)):
    state = _demo_state_for(user)
    return {"modules": state["modules"], "summary": state["summary"]}


@app.get("/api/demo/modules/{module_id}")
def api_demo_module(
    module_id: str,
    user: User = Depends(require_session_user),
):
    require_demo_runtime()
    if not can_access(user, module_id):
        raise HTTPException(403, "Ehhez a modulhoz nincs jogosultság.")
    try:
        return demo_runtime.module(module_id)
    except DemoRuntimeError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/demo/actions")
def api_demo_action(
    data: DemoActionIn,
    user: User = Depends(require_session_user),
):
    require_demo_runtime()
    if not can_access(user, data.module_id):
        raise HTTPException(403, "Ehhez a modulművelethez nincs jogosultság.")
    try:
        return demo_runtime.execute_action(
            module_id=data.module_id,
            action_id=data.action_id,
            project_id=data.project_id,
            actor=user.email,
            correlation_id=data.correlation_id,
            idempotency_key=data.idempotency_key,
            payload=data.payload,
        )
    except DemoRuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/demo/journeys/{journey_id}/run")
def api_demo_journey(
    journey_id: str,
    data: DemoJourneyIn,
    user: User = Depends(require_session_user),
):
    require_demo_runtime()
    if user.role not in {"owner", "managing-director", "platform-admin"}:
        raise HTTPException(403, "Teljes tesztutat csak vezetői szerepkör indíthat.")
    try:
        return demo_runtime.run_journey(journey_id, user.email)
    except DemoRuntimeError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/demo/failures")
def api_demo_failure(
    data: DemoFailureIn,
    user: User = Depends(require_session_user),
):
    require_demo_runtime()
    if user.role != "platform-admin":
        raise HTTPException(403, "Hibainjektálást csak platform admin indíthat.")
    try:
        return demo_runtime.inject_failure(data.consumer)
    except DemoRuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/demo/outbox/{outbox_id}/retry")
def api_demo_retry(
    outbox_id: str,
    user: User = Depends(require_session_user),
):
    require_demo_runtime()
    if user.role != "platform-admin":
        raise HTTPException(403, "Outbox újrapróbálást csak platform admin indíthat.")
    try:
        return demo_runtime.retry_outbox(outbox_id)
    except DemoRuntimeError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/demo/reset")
def api_demo_reset(user: User = Depends(require_session_user)):
    require_demo_runtime()
    if user.role != "platform-admin":
        raise HTTPException(403, "Demo-visszaállítást csak platform admin indíthat.")
    return demo_runtime.reset()


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, return_to: str = "/"):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None, "return_to": return_to},
    )


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    return_to: Annotated[str, Form()] = "/",
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == email, User.active.is_(True)))
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Hibás e-mail vagy jelszó.",
                "return_to": return_to,
            },
            status_code=401,
        )
    request.session["user_id"] = user.id
    audit(db, actor=user.email, action="login", entity_type="user", entity_id=str(user.id))
    claimed_session_id = None
    guest_session_token = str(request.cookies.get(GUEST_SESSION_COOKIE) or "")
    guest_claim_token = str(request.cookies.get(GUEST_CLAIM_COOKIE) or "")
    if guest_session_token and guest_claim_token:
        try:
            claimed = claim_guest_design(
                db,
                guest_session_token=guest_session_token,
                claim_token=guest_claim_token,
                authenticated_subject_id=str(user.itep_subject_id or user.email),
            )
            claimed_session_id = claimed["sessionId"]
        except HouseDesignerError as error:
            audit(
                db,
                actor=str(user.itep_subject_id or user.email),
                action="house_designer.guest.claim_rejected",
                entity_type="HouseDesignGuestClaim",
                after={"code": error.code},
            )
            db.commit()
    else:
        db.commit()
    safe_return_to = (
        return_to if return_to.startswith("/") and not return_to.startswith("//") else "/"
    )
    target = "/account/password" if user.must_change_password else safe_return_to
    if claimed_session_id and not user.must_change_password:
        target = f"/house-designer/sessions/{claimed_session_id}"
    response = RedirectResponse(target, status_code=303)
    response.delete_cookie(GUEST_SESSION_COOKIE, path="/")
    response.delete_cookie(GUEST_CLAIM_COOKIE, path="/")
    return response


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/account/password", response_class=HTMLResponse)
def account_password_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or not user.active:
        return RedirectResponse("/login?return_to=/account/password", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="account_password.html",
        context={"user": user, "active": "account", "error": None, "success": None},
    )


@app.post("/account/password", response_class=HTMLResponse)
async def account_password_change(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or not user.active:
        return RedirectResponse("/login?return_to=/account/password", status_code=303)
    form = await request.form()
    current_password = str(form.get("current_password") or "")
    new_password = str(form.get("new_password") or "")
    confirm_password = str(form.get("confirm_password") or "")
    error = None
    if not verify_password(current_password, user.password_hash):
        error = "A jelenlegi jelszó nem megfelelő."
    elif len(new_password) < 14:
        error = "Az új jelszó legalább 14 karakter legyen."
    elif new_password != confirm_password:
        error = "Az új jelszó és a megerősítés nem egyezik."
    elif verify_password(new_password, user.password_hash):
        error = "Az új jelszó nem lehet azonos a jelenlegivel."
    if error:
        return templates.TemplateResponse(
            request=request,
            name="account_password.html",
            context={"user": user, "active": "account", "error": error, "success": None},
            status_code=400,
        )
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    audit(
        db,
        actor=user.email,
        action="user.password_changed",
        entity_type="user",
        entity_id=str(user.id),
    )
    db.commit()
    return templates.TemplateResponse(
        request=request,
        name="account_password.html",
        context={
            "user": user,
            "active": "account",
            "error": None,
            "success": "A jelszó módosítása sikeres.",
        },
    )


def _require_user_admin(request: Request, db: Session) -> User:
    user = require_session_user(request, db)
    if user.role not in {"owner", "platform-admin"}:
        raise HTTPException(
            403, "Felhasználókezeléshez tulajdonosi vagy platform admin jogosultság szükséges."
        )
    return user


@app.get("/admin/users", response_class=HTMLResponse)
def user_admin_workspace(request: Request, db: Session = Depends(get_db)):
    user = _require_user_admin(request, db)
    users = list(db.scalars(select(User).order_by(User.active.desc(), User.name, User.email)))
    return templates.TemplateResponse(
        request=request,
        name="user_admin.html",
        context={"user": user, "active": "user-admin", "users": users, "roles": ROLE_DEFINITIONS},
    )


@app.post("/admin/users")
async def user_admin_create(request: Request, db: Session = Depends(get_db)):
    actor = _require_user_admin(request, db)
    form = await request.form()
    email = str(form.get("email") or "").strip().lower()
    name = str(form.get("name") or "").strip()
    role = str(form.get("role") or "")
    temporary_password = str(form.get("temporary_password") or "")
    if "@" not in email or len(name) < 2:
        raise HTTPException(400, "Érvényes név és e-mail-cím szükséges.")
    if role not in {item.id for item in ROLE_DEFINITIONS}:
        raise HTTPException(400, "Ismeretlen szerepkör.")
    if role == "owner" and actor.role != "owner":
        raise HTTPException(403, "Tulajdonosi fiókot csak tulajdonos hozhat létre.")
    if len(temporary_password) < 14:
        raise HTTPException(400, "Az ideiglenes jelszó legalább 14 karakter legyen.")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Ezzel az e-mail-címmel már létezik felhasználó.")
    row = User(
        email=email,
        name=name,
        role=role,
        password_hash=hash_password(temporary_password),
        active=True,
        must_change_password=True,
    )
    db.add(row)
    db.flush()
    audit(
        db,
        actor=actor.email,
        action="user.created",
        entity_type="user",
        entity_id=str(row.id),
        after={"email": email, "name": name, "role": role, "must_change_password": True},
    )
    db.commit()
    return RedirectResponse(f"/admin/users#user-{row.id}", status_code=303)


@app.post("/admin/users/{user_id}")
async def user_admin_update(user_id: int, request: Request, db: Session = Depends(get_db)):
    actor = _require_user_admin(request, db)
    row = db.get(User, user_id)
    if not row:
        raise HTTPException(404, "A felhasználó nem található.")
    form = await request.form()
    role = str(form.get("role") or row.role)
    active = form.get("active") is not None
    temporary_password = str(form.get("temporary_password") or "")
    if role not in {item.id for item in ROLE_DEFINITIONS}:
        raise HTTPException(400, "Ismeretlen szerepkör.")
    if (row.role == "owner" or role == "owner") and actor.role != "owner":
        raise HTTPException(403, "Tulajdonosi fiókot csak tulajdonos kezelhet.")
    if row.id == actor.id and not active:
        raise HTTPException(409, "A saját aktív fiók nem kapcsolható ki.")
    if row.role == "owner" and (not active or role != "owner"):
        other_owners = (
            db.scalar(
                select(text("count(*)"))
                .select_from(User)
                .where(User.role == "owner", User.active.is_(True), User.id != row.id)
            )
            or 0
        )
        if other_owners == 0:
            raise HTTPException(
                409, "Az utolsó aktív tulajdonosi fiók nem kapcsolható ki és nem sorolható át."
            )
    before = {
        "role": row.role,
        "active": row.active,
        "must_change_password": row.must_change_password,
    }
    row.role = role
    row.active = active
    if temporary_password:
        if len(temporary_password) < 14:
            raise HTTPException(400, "Az ideiglenes jelszó legalább 14 karakter legyen.")
        row.password_hash = hash_password(temporary_password)
        row.must_change_password = True
    audit(
        db,
        actor=actor.email,
        action="user.updated",
        entity_type="user",
        entity_id=str(row.id),
        before=before,
        after={
            "role": row.role,
            "active": row.active,
            "must_change_password": row.must_change_password,
        },
    )
    db.commit()
    return RedirectResponse(f"/admin/users#user-{row.id}", status_code=303)


@app.get("/executive", response_class=HTMLResponse)
def executive_dashboard(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    metrics = dashboard_metrics(db)
    projects = db.scalars(
        select(ProjectRegistry)
        .order_by(desc(ProjectRegistry.financial_impact_huf), desc(ProjectRegistry.updated_at))
        .limit(10)
    ).all()
    events = db.scalars(
        select(EventRecord)
        .where(EventRecord.status == "open", EventRecord.executive_relevance.is_(True))
        .order_by(desc(EventRecord.severity), desc(EventRecord.received_at))
        .limit(15)
    ).all()
    issues = db.scalars(
        select(ConsistencyIssue)
        .where(ConsistencyIssue.status == "open")
        .order_by(desc(ConsistencyIssue.severity), desc(ConsistencyIssue.financial_impact_huf))
        .limit(10)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "metrics": metrics,
            "projects": projects,
            "events": events,
            "issues": issues,
            "active": "executive",
        },
    )


@app.get("/", response_class=HTMLResponse)
def workspace_home(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    summary = workspace_summary(db, user)
    return templates.TemplateResponse(
        request=request,
        name="workspace.html",
        context={"user": user, "summary": summary, "active": "workspace"},
    )


def _dpm_redirect(
    *,
    message: str | None = None,
    error: str | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
) -> RedirectResponse:
    query = {
        key: value
        for key, value in {
            "message": message,
            "error": error,
            "agent_id": agent_id,
            "project_id": project_id,
        }.items()
        if value
    }
    suffix = f"?{urlencode(query)}" if query else ""
    return RedirectResponse(f"/digital-project-managers{suffix}", status_code=303)


def _dpm_context_for_user(user: User):
    if not can_access(user, "digital-project-managers", "pm-cockpit"):
        raise HTTPException(403, "A Digital Project Managers munkatér nem érhető el.")
    return dpm_gateway.user_context(email=user.email, role=user.role)


@app.get("/digital-project-managers", response_class=HTMLResponse)
def digital_project_managers_workspace(
    request: Request,
    agent_id: str | None = None,
    project_id: str | None = None,
    knowledge_q: str | None = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    error = request.query_params.get("error")
    message = request.query_params.get("message")
    agents: list[dict] = []
    assignments: list[dict] = []
    tasks: list[dict] = []
    approvals: list[dict] = []
    audit_events: list[dict] = []
    project_context: dict | None = None
    memory: dict | None = None
    knowledge_results: list[dict] = []
    dpm_context = None
    try:
        dpm_context = _dpm_context_for_user(user)
        agents = dpm_gateway.request("GET", "/api/v1/agents", dpm_context.identity)
        if not dpm_context.admin:
            agents = [item for item in agents if str(item["id"]) in dpm_context.agent_ids]
        assignments = dpm_gateway.request("GET", "/api/v1/assignments", dpm_context.identity)
        valid_agent_ids = {str(item["id"]) for item in agents}
        if agent_id not in valid_agent_ids:
            agent_id = next(iter(valid_agent_ids), None)
        visible_assignments = [
            item
            for item in assignments
            if not agent_id or str(item["digital_manager_id"]) == agent_id
        ]
        ordered_project_ids = [str(item["external_project_id"]) for item in visible_assignments]
        if project_id not in set(ordered_project_ids):
            project_id = ordered_project_ids[0] if ordered_project_ids else None
        if agent_id:
            tasks = dpm_gateway.request(
                "GET",
                f"/api/v1/agents/{agent_id}/workqueue",
                dpm_context.identity,
                query={"project_id": project_id},
            )
        approvals = dpm_gateway.request(
            "GET",
            "/api/v1/approvals",
            dpm_context.identity,
            query={"project_id": project_id, "status": "PENDING", "limit": 100},
        )
        if project_id:
            project_context = dpm_gateway.request(
                "GET",
                f"/api/v1/projects/{project_id}/context",
                dpm_context.identity,
            )
            audit_events = dpm_gateway.request(
                "GET",
                "/api/v1/audit/events",
                dpm_context.identity,
                query={"project_id": project_id, "limit": 30},
            )
            if agent_id:
                memory = dpm_gateway.request(
                    "GET",
                    f"/api/v1/agents/{agent_id}/projects/{project_id}/memory",
                    dpm_context.identity,
                )
            if knowledge_q and len(knowledge_q.strip()) >= 2:
                knowledge_results = dpm_gateway.request(
                    "POST",
                    "/api/v1/knowledge/search",
                    dpm_context.identity,
                    payload={
                        "external_project_id": project_id,
                        "query": knowledge_q.strip(),
                        "limit": 20,
                    },
                )
    except DpmGatewayError as exc:
        error = exc.detail

    all_projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
    if dpm_context and not dpm_context.admin:
        all_projects = [
            item for item in all_projects if item.project_id in dpm_context.identity.project_ids
        ]
    internal_users = db.scalars(
        select(User)
        .where(
            User.active.is_(True),
            User.role.in_({"project-manager", "owner", "managing-director", "platform-admin"}),
        )
        .order_by(User.name)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="digital_project_managers.html",
        context={
            "user": user,
            "active": "digital-project-managers",
            "message": message,
            "error": error,
            "configured": dpm_gateway.configured,
            "is_admin": bool(dpm_context and dpm_context.admin),
            "agents": agents,
            "assignments": assignments,
            "tasks": tasks,
            "approvals": approvals,
            "audit_events": audit_events,
            "project_context": project_context,
            "memory": memory,
            "knowledge_results": knowledge_results,
            "knowledge_q": knowledge_q or "",
            "projects": all_projects,
            "internal_users": internal_users,
            "agent_id": agent_id,
            "project_id": project_id,
            "agent_map": {str(item["id"]): item for item in agents},
        },
    )


@app.post("/digital-project-managers/agents/{agent_id}/link")
async def digital_project_manager_link(
    agent_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    try:
        context = _dpm_context_for_user(user)
        if not context.admin:
            raise DpmGatewayError(403, "Csak vezető vagy platformadmin kapcsolhat felelőst.")
        form = await request.form()
        dpm_gateway.request(
            "PATCH",
            f"/api/v1/agents/{agent_id}",
            context.identity,
            payload={"human_manager_ref": str(form.get("human_manager_ref") or "") or None},
        )
        return _dpm_redirect(
            message="A humán projektmenedzser kapcsolata frissült.", agent_id=agent_id
        )
    except DpmGatewayError as exc:
        return _dpm_redirect(error=exc.detail, agent_id=agent_id)


@app.post("/digital-project-managers/agents/{agent_id}/assignments")
async def digital_project_manager_assign(
    agent_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    form = await request.form()
    project_id = str(form.get("project_id") or "")
    try:
        context = _dpm_context_for_user(user)
        if not context.admin:
            raise DpmGatewayError(403, "Csak vezető vagy platformadmin oszthat ki projektet.")
        dpm_gateway.request(
            "POST",
            f"/api/v1/agents/{agent_id}/assignments",
            context.identity,
            payload={
                "external_project_id": project_id,
                "approval_owner_ref": str(form.get("approval_owner_ref") or "") or None,
                "restrictions": {"externalWrites": False},
            },
        )
        return _dpm_redirect(
            message="A projektkiosztás létrejött.",
            agent_id=agent_id,
            project_id=project_id,
        )
    except DpmGatewayError as exc:
        return _dpm_redirect(error=exc.detail, agent_id=agent_id, project_id=project_id)


@app.post("/digital-project-managers/agents/{agent_id}/tasks")
async def digital_project_manager_task_create(
    agent_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    form = await request.form()
    project_id = str(form.get("project_id") or "")
    try:
        context = _dpm_context_for_user(user)
        impact_text = str(form.get("impact_json") or "{}").strip() or "{}"
        impact = json.loads(impact_text)
        if not isinstance(impact, dict):
            raise ValueError("object required")
        result = dpm_gateway.request(
            "POST",
            f"/api/v1/agents/{agent_id}/tasks",
            context.identity,
            payload={
                "external_project_id": project_id,
                "task_type": str(form.get("task_type") or "internal_administration"),
                "objective": str(form.get("objective") or ""),
                "priority": int(str(form.get("priority") or "3")),
                "risk_level": int(str(form.get("risk_level") or "0")),
                "impact": impact,
                "recommendation": str(form.get("recommendation") or "") or None,
            },
        )
        policy = result["policy"]
        return _dpm_redirect(
            message=f"Feladat rögzítve: {policy['status']} / {policy['escalation_level']}.",
            agent_id=agent_id,
            project_id=project_id,
        )
    except (DpmGatewayError, ValueError, json.JSONDecodeError) as exc:
        detail = (
            exc.detail
            if isinstance(exc, DpmGatewayError)
            else "A hatásmező csak JSON objektum lehet."
        )
        return _dpm_redirect(error=detail, agent_id=agent_id, project_id=project_id)


@app.post("/digital-project-managers/tasks/{task_id}/retry")
async def digital_project_manager_task_retry(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    form = await request.form()
    agent_id = str(form.get("agent_id") or "")
    project_id = str(form.get("project_id") or "")
    try:
        context = _dpm_context_for_user(user)
        result = dpm_gateway.request("POST", f"/api/v1/tasks/{task_id}/retry", context.identity)
        message = (
            "A feladat újra sorba került." if result["queued"] else "A sorba állítás nem sikerült."
        )
        return _dpm_redirect(message=message, agent_id=agent_id, project_id=project_id)
    except DpmGatewayError as exc:
        return _dpm_redirect(error=exc.detail, agent_id=agent_id, project_id=project_id)


@app.post("/digital-project-managers/assignments/{assignment_id}/close")
async def digital_project_manager_assignment_close(
    assignment_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    form = await request.form()
    agent_id = str(form.get("agent_id") or "")
    project_id = str(form.get("project_id") or "")
    try:
        context = _dpm_context_for_user(user)
        if not context.admin:
            raise DpmGatewayError(403, "Csak vezető vagy platformadmin vonhat vissza kiosztást.")
        dpm_gateway.request("DELETE", f"/api/v1/assignments/{assignment_id}", context.identity)
        return _dpm_redirect(message="A projektkiosztás auditáltan lezárult.", agent_id=agent_id)
    except DpmGatewayError as exc:
        return _dpm_redirect(error=exc.detail, agent_id=agent_id, project_id=project_id)


@app.post("/digital-project-managers/approvals/{approval_id}/decision")
async def digital_project_manager_approval_decision(
    approval_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    form = await request.form()
    agent_id = str(form.get("agent_id") or "")
    project_id = str(form.get("project_id") or "")
    try:
        context = _dpm_context_for_user(user)
        dpm_gateway.request(
            "POST",
            f"/api/v1/approvals/{approval_id}/decision",
            context.identity,
            payload={
                "decision": str(form.get("decision") or "REJECTED"),
                "rationale": str(form.get("rationale") or ""),
            },
        )
        return _dpm_redirect(
            message="A jóváhagyási döntés auditáltan rögzült.",
            agent_id=agent_id,
            project_id=project_id,
        )
    except DpmGatewayError as exc:
        return _dpm_redirect(error=exc.detail, agent_id=agent_id, project_id=project_id)


@app.post("/digital-project-managers/agents/{agent_id}/projects/{project_id}/memory")
async def digital_project_manager_memory_update(
    agent_id: str,
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        content = json.loads(str(form.get("content_json") or "{}"))
        if not isinstance(content, dict):
            raise ValueError("object required")
        context = _dpm_context_for_user(user)
        dpm_gateway.request(
            "PATCH",
            f"/api/v1/agents/{agent_id}/projects/{project_id}/memory",
            context.identity,
            payload={
                "expected_version": int(str(form.get("expected_version") or "0")),
                "content": content,
            },
        )
        return _dpm_redirect(
            message="A projektmemória új verziója elkészült.",
            agent_id=agent_id,
            project_id=project_id,
        )
    except (DpmGatewayError, ValueError, json.JSONDecodeError) as exc:
        detail = (
            exc.detail
            if isinstance(exc, DpmGatewayError)
            else "A projektmemória csak JSON objektum lehet."
        )
        return _dpm_redirect(error=detail, agent_id=agent_id, project_id=project_id)


@app.post("/digital-project-managers/knowledge")
async def digital_project_manager_knowledge_create(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    form = await request.form()
    agent_id = str(form.get("agent_id") or "")
    project_id = str(form.get("project_id") or "")
    try:
        context = _dpm_context_for_user(user)
        dpm_gateway.request(
            "POST",
            "/api/v1/knowledge",
            context.identity,
            payload={
                "external_project_id": project_id,
                "title": str(form.get("title") or ""),
                "content": str(form.get("content") or ""),
                "source_type": "manual",
                "version": str(form.get("version") or "1.0"),
                "precedence": int(str(form.get("precedence") or "100")),
                "metadata_json": {"source": "platform-dpm-workspace"},
            },
        )
        return _dpm_redirect(
            message="A projektismeret indexelve és auditálva lett.",
            agent_id=agent_id,
            project_id=project_id,
        )
    except (DpmGatewayError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, DpmGatewayError) else "Érvénytelen precedenciaérték."
        return _dpm_redirect(error=detail, agent_id=agent_id, project_id=project_id)


@app.get("/tasks", response_class=HTMLResponse)
def action_center(
    request: Request,
    status: str | None = None,
    priority: str | None = None,
    project_id: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    rows = list_tasks(
        db,
        status=status,
        priority=priority,
        project_id=project_id,
        assignee=user.email,
        query_text=q,
    )
    metrics = task_metrics(db, assignee=user.email)
    projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
    return templates.TemplateResponse(
        request=request,
        name="action_center.html",
        context={
            "user": user,
            "tasks": rows,
            "metrics": metrics,
            "projects": projects,
            "filters": {"status": status, "priority": priority, "project_id": project_id, "q": q},
            "active": "tasks",
        },
    )


@app.get("/smart-calendar", response_class=HTMLResponse)
def smart_calendar(
    request: Request,
    project_id: str | None = None,
    status: str | None = None,
    entry_type: str | None = None,
    assignee: str | None = None,
    q: str | None = None,
    starts_from: str | None = None,
    starts_until: str | None = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "smart-calendar", "workflow-center", "workspace"):
        raise HTTPException(403, "Az okosnaptár ehhez a szerepkörhöz nem érhető el.")
    project_ids = calendar_project_ids_for_user(db, user)
    if project_id:
        try:
            assert_calendar_project_access(db, user, project_id)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
    project_query = select(ProjectRegistry).order_by(ProjectRegistry.name)
    if project_ids is not None:
        project_query = project_query.where(ProjectRegistry.project_id.in_(project_ids or {"-"}))
    projects = db.scalars(project_query).all()
    try:
        parsed_from = _calendar_local_datetime(f"{starts_from}T00:00") if starts_from else None
        parsed_until = (
            _calendar_local_datetime(f"{starts_until}T23:59:59") if starts_until else None
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    portfolio = calendar_portfolio(
        db,
        project_id=project_id,
        project_ids=project_ids,
        assignee=assignee,
        status=status,
        entry_type=entry_type,
        query_text=q,
        starts_from=parsed_from,
        starts_until=parsed_until,
    )
    internal_users = db.scalars(
        select(User)
        .where(User.active.is_(True), User.role.notin_({"customer", "subcontractor"}))
        .order_by(User.name)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="smart_calendar.html",
        context={
            "user": user,
            "active": "calendar",
            "today": datetime.now(timezone.utc).date(),
            "projects": projects,
            "internal_users": internal_users,
            "project_id": project_id,
            "filters": {
                "status": status or "",
                "entry_type": entry_type or "",
                "assignee": assignee or "",
                "q": q or "",
                "starts_from": starts_from or "",
                "starts_until": starts_until or "",
            },
            "csrf_token": _ui_csrf_token(request),
            "can_approve_change": user.role in _CALENDAR_APPROVER_ROLES,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
            **portfolio,
        },
    )


@app.post("/smart-calendar/entries")
async def smart_calendar_entry_create(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárkezelési jogosultság.")
    form = await request.form()
    _require_ui_csrf(request, form.get("csrf_token"))
    try:
        project_id = str(form.get("project_id") or "")
        assert_calendar_project_access(db, user, project_id)
        row = create_calendar_entry(
            db,
            CalendarEntryIn(
                project_id=project_id,
                entry_type=str(form.get("entry_type") or "task"),
                title=str(form.get("title") or ""),
                description=str(form.get("description") or "") or None,
                starts_at=_calendar_local_datetime(form.get("starts_at")),
                ends_at=_calendar_local_datetime(form.get("ends_at")),
                all_day=form.get("all_day") is not None,
                assignee=str(form.get("assignee") or "") or None,
                participants=[
                    item.strip()
                    for item in str(form.get("participants") or "").replace(";", ",").split(",")
                    if item.strip()
                ],
                location=str(form.get("location") or "") or None,
                priority=str(form.get("priority") or "normal"),
                source_module=str(form.get("source_module") or "smart-calendar"),
                source_object_id=str(form.get("source_object_id") or "") or None,
                contractual_deadline=form.get("contractual_deadline") is not None,
                capacity_hours=Decimal(str(form.get("capacity_hours") or "0")),
                create_task=form.get("create_task") is not None,
                conflict_override_reason=str(form.get("conflict_override_reason") or "") or None,
            ),
            actor=user.email,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(
        f"/smart-calendar?project_id={row.project_id}#{row.entry_id}", status_code=303
    )


@app.post("/smart-calendar/sync")
async def smart_calendar_sync(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárkezelési jogosultság.")
    form = await request.form()
    _require_ui_csrf(request, form.get("csrf_token"))
    synchronize_schedule_sources(
        db, actor=user.email, project_ids=calendar_project_ids_for_user(db, user)
    )
    return RedirectResponse("/smart-calendar", status_code=303)


@app.post("/smart-calendar/dependencies")
async def smart_calendar_dependency_create(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárkezelési jogosultság.")
    form = await request.form()
    _require_ui_csrf(request, form.get("csrf_token"))
    try:
        predecessor = _calendar_entry_for_user(
            db, user, str(form.get("predecessor_entry_id") or "")
        )
        successor = _calendar_entry_for_user(db, user, str(form.get("successor_entry_id") or ""))
        row = add_calendar_dependency(
            db,
            CalendarDependencyIn(
                predecessor_entry_id=predecessor.entry_id,
                successor_entry_id=successor.entry_id,
                dependency_type=str(form.get("dependency_type") or "finish_to_start"),
                lag_days=_form_int(form.get("lag_days")),
            ),
            actor=user.email,
        )
        project_id = get_calendar_entry(db, row.successor_entry_id).project_id
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/smart-calendar?project_id={project_id}", status_code=303)


@app.post("/smart-calendar/entries/{entry_id}/reschedule")
async def smart_calendar_entry_reschedule(
    entry_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárkezelési jogosultság.")
    form = await request.form()
    _require_ui_csrf(request, form.get("csrf_token"))
    try:
        _calendar_entry_for_user(db, user, entry_id)
        row = reschedule_entry(
            db,
            entry_id,
            CalendarRescheduleIn(
                starts_at=_calendar_local_datetime(form.get("starts_at")),
                ends_at=_calendar_local_datetime(form.get("ends_at")),
                reason=str(form.get("reason") or ""),
                conflict_override_reason=str(form.get("conflict_override_reason") or "") or None,
                expected_version=_form_int(form.get("expected_version")),
            ),
            actor=user.email,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A naptárelem nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(
        f"/smart-calendar?project_id={row.project_id}#{row.entry_id}", status_code=303
    )


@app.post("/smart-calendar/entries/{entry_id}/status")
async def smart_calendar_entry_status(
    entry_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárkezelési jogosultság.")
    form = await request.form()
    _require_ui_csrf(request, form.get("csrf_token"))
    try:
        _calendar_entry_for_user(db, user, entry_id)
        payload = CalendarStatusIn(
            status=str(form.get("status") or ""),
            note=str(form.get("note") or "") or None,
            expected_version=_form_int(form.get("expected_version")),
        )
        row = update_entry_status(
            db,
            entry_id,
            status=payload.status,
            note=payload.note,
            expected_version=payload.expected_version,
            actor=user.email,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A naptárelem nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(
        f"/smart-calendar?project_id={row.project_id}#{row.entry_id}", status_code=303
    )


@app.post("/smart-calendar/entries/{entry_id}/change-requests")
async def smart_calendar_change_request(
    entry_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárkezelési jogosultság.")
    form = await request.form()
    _require_ui_csrf(request, form.get("csrf_token"))
    try:
        row = _calendar_entry_for_user(db, user, entry_id)
        request_contractual_change(
            db,
            entry_id,
            CalendarChangeRequestIn(
                starts_at=_calendar_local_datetime(form.get("starts_at")),
                ends_at=_calendar_local_datetime(form.get("ends_at")),
                reason=str(form.get("reason") or ""),
                impact_summary=str(form.get("impact_summary") or ""),
                expected_version=_form_int(form.get("expected_version")),
            ),
            actor=user.email,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A naptárelem nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(
        f"/smart-calendar?project_id={row.project_id}#{row.entry_id}", status_code=303
    )


@app.post("/smart-calendar/change-requests/{request_id}/decision")
async def smart_calendar_change_decision(
    request_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in _CALENDAR_APPROVER_ROLES:
        raise HTTPException(403, "Szerződéses határidő módosítását csak vezető hagyhatja jóvá.")
    form = await request.form()
    _require_ui_csrf(request, form.get("csrf_token"))
    try:
        change_row = db.scalar(
            select(CalendarChangeRequest).where(CalendarChangeRequest.request_id == request_id)
        )
        if not change_row:
            raise KeyError(request_id)
        entry = _calendar_entry_for_user(db, user, change_row.entry_id)
        payload = CalendarChangeDecisionIn(
            decision=str(form.get("decision") or ""),
            note=str(form.get("note") or ""),
            conflict_override_reason=str(form.get("conflict_override_reason") or "") or None,
            expected_entry_version=_form_int(form.get("expected_entry_version")),
        )
        decide_contractual_change(
            db,
            request_id,
            decision=payload.decision,
            note=payload.note,
            conflict_override_reason=payload.conflict_override_reason,
            expected_entry_version=payload.expected_entry_version,
            actor=user.email,
        )
        project_id = entry.project_id
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A változáskérelem nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/smart-calendar?project_id={project_id}", status_code=303)


@app.get("/api/smart-calendar/entries")
def api_smart_calendar_entries(
    request: Request,
    project_id: str | None = None,
    status: str | None = None,
    entry_type: str | None = None,
    assignee: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárhozzáférés.")
    try:
        if project_id:
            assert_calendar_project_access(db, user, project_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    portfolio = calendar_portfolio(
        db,
        project_id=project_id,
        project_ids=calendar_project_ids_for_user(db, user),
        status=status,
        entry_type=entry_type,
        assignee=assignee,
        query_text=q,
    )
    return {
        "csrf_token": _ui_csrf_token(request),
        "metrics": portfolio["metrics"],
        "entries": [serialize_calendar_entry(row) for row in portfolio["entries"]],
        "conflicts": [
            {
                "left_entry_id": item["left"].entry_id,
                "right_entry_id": item["right"].entry_id,
                "people": item["people"],
            }
            for item in portfolio["conflicts"]
        ],
    }


@app.post("/api/smart-calendar/sync")
def api_smart_calendar_sync(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárkezelési jogosultság.")
    _require_calendar_api_csrf(request)
    return synchronize_schedule_sources(
        db, actor=user.email, project_ids=calendar_project_ids_for_user(db, user)
    )


@app.post("/api/smart-calendar/entries")
def api_smart_calendar_entry_create(
    payload: CalendarEntryIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárkezelési jogosultság.")
    _require_calendar_api_csrf(request)
    try:
        assert_calendar_project_access(db, user, payload.project_id)
        return serialize_calendar_entry(create_calendar_entry(db, payload, actor=user.email))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/smart-calendar/dependencies")
def api_smart_calendar_dependency_create(
    payload: CalendarDependencyIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárkezelési jogosultság.")
    _require_calendar_api_csrf(request)
    try:
        _calendar_entry_for_user(db, user, payload.predecessor_entry_id)
        _calendar_entry_for_user(db, user, payload.successor_entry_id)
        row = add_calendar_dependency(db, payload, actor=user.email)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "dependency_id": row.dependency_id,
        "predecessor_entry_id": row.predecessor_entry_id,
        "successor_entry_id": row.successor_entry_id,
        "dependency_type": row.dependency_type,
        "lag_days": row.lag_days,
    }


@app.post("/api/smart-calendar/entries/{entry_id}/reschedule")
def api_smart_calendar_entry_reschedule(
    entry_id: str,
    payload: CalendarRescheduleIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárkezelési jogosultság.")
    _require_calendar_api_csrf(request)
    try:
        _calendar_entry_for_user(db, user, entry_id)
        return serialize_calendar_entry(reschedule_entry(db, entry_id, payload, actor=user.email))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A naptárelem nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/smart-calendar/entries/{entry_id}/status")
def api_smart_calendar_entry_status(
    entry_id: str,
    payload: CalendarStatusIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárkezelési jogosultság.")
    _require_calendar_api_csrf(request)
    try:
        _calendar_entry_for_user(db, user, entry_id)
        return serialize_calendar_entry(
            update_entry_status(
                db,
                entry_id,
                status=payload.status,
                note=payload.note,
                expected_version=payload.expected_version,
                actor=user.email,
            )
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A naptárelem nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/smart-calendar/entries/{entry_id}/change-requests")
def api_smart_calendar_change_request(
    entry_id: str,
    payload: CalendarChangeRequestIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if not can_access(user, "smart-calendar"):
        raise HTTPException(403, "Nincs naptárkezelési jogosultság.")
    _require_calendar_api_csrf(request)
    try:
        _calendar_entry_for_user(db, user, entry_id)
        row = request_contractual_change(db, entry_id, payload, actor=user.email)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A naptárelem nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"request_id": row.request_id, "status": row.status, "entry_id": row.entry_id}


@app.post("/api/smart-calendar/change-requests/{request_id}/decision")
def api_smart_calendar_change_decision(
    request_id: str,
    payload: CalendarChangeDecisionIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if user.role not in _CALENDAR_APPROVER_ROLES:
        raise HTTPException(403, "Nincs döntési jogosultság.")
    _require_calendar_api_csrf(request)
    try:
        change_row = db.scalar(
            select(CalendarChangeRequest).where(CalendarChangeRequest.request_id == request_id)
        )
        if not change_row:
            raise KeyError(request_id)
        _calendar_entry_for_user(db, user, change_row.entry_id)
        row = decide_contractual_change(
            db,
            request_id,
            decision=payload.decision,
            note=payload.note,
            conflict_override_reason=payload.conflict_override_reason,
            expected_entry_version=payload.expected_entry_version,
            actor=user.email,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A változáskérelem nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"request_id": row.request_id, "status": row.status, "entry_id": row.entry_id}


@app.post("/tasks/{task_id}/update")
def action_center_update(
    request: Request,
    task_id: str,
    status: Annotated[str | None, Form()] = None,
    assignee: Annotated[str | None, Form()] = None,
    project_id: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        update_task(db, task_id, TaskUpdateIn(status=status, assignee=assignee), actor=user.email)
    except KeyError:
        raise HTTPException(404, "Feladat nem található.")
    target = f"/tasks?project_id={project_id}" if project_id else "/tasks"
    return RedirectResponse(target, status_code=303)


@app.get("/communications", response_class=HTMLResponse)
def communications_page(
    request: Request,
    thread_id: str | None = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in _INTERNAL_COMMUNICATION_ROLES:
        raise HTTPException(403, "A belső kommunikáció csak belső felhasználóknak érhető el.")
    active_thread = None
    if thread_id:
        try:
            active_thread = get_thread(db, thread_id=thread_id, user=user)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, "A beszélgetés nem található.") from exc
    users = list(
        db.scalars(
            select(User)
            .where(
                User.active.is_(True),
                User.id != user.id,
                User.role.in_(_INTERNAL_COMMUNICATION_ROLES),
            )
            .order_by(User.name, User.email)
        )
    )
    projects = list(db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)))
    tasks = list(
        db.scalars(
            select(TaskRecord)
            .where(TaskRecord.status.not_in(("done", "cancelled")))
            .order_by(TaskRecord.project_id, TaskRecord.due_at)
            .limit(250)
        )
    )
    return templates.TemplateResponse(
        request=request,
        name="communications.html",
        context={
            "user": user,
            "threads": list_threads(db, user),
            "active_thread": active_thread,
            "notifications": list_notifications(db, user),
            "unread_notifications": unread_notification_count(db, user),
            "users": users,
            "projects": projects,
            "tasks": tasks,
            "active": "communications",
        },
    )


@app.post("/communications/threads")
async def communications_thread_create(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in _INTERNAL_COMMUNICATION_ROLES:
        raise HTTPException(403, "A belső kommunikáció csak belső felhasználóknak érhető el.")
    form = await request.form()
    try:
        participant_ids = [_form_int(value) for value in form.getlist("participant_user_ids")]
        thread = create_thread(
            db,
            creator=user,
            subject=str(form.get("subject") or ""),
            thread_type=str(form.get("thread_type") or ""),
            participant_user_ids=participant_ids,
            project_id=str(form.get("project_id") or "") or None,
            task_id=str(form.get("task_id") or "") or None,
            initial_message=str(form.get("initial_message") or "") or None,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/communications?thread_id={thread.thread_id}", status_code=303)


@app.post("/communications/{thread_id}/messages")
async def communications_message_create(
    thread_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in _INTERNAL_COMMUNICATION_ROLES:
        raise HTTPException(403, "A belső kommunikáció csak belső felhasználóknak érhető el.")
    form = await request.form()
    try:
        post_message(db, thread_id=thread_id, sender=user, body=str(form.get("body") or ""))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A beszélgetés nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/communications?thread_id={thread_id}", status_code=303)


@app.post("/communications/notifications/read-all")
def communications_notifications_read_all(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in _INTERNAL_COMMUNICATION_ROLES:
        raise HTTPException(403, "A belső kommunikáció csak belső felhasználóknak érhető el.")
    mark_notifications_read(db, user)
    return RedirectResponse("/communications#notifications", status_code=303)


@app.get("/api/communications/unread")
def communications_unread_api(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if user.role not in _INTERNAL_COMMUNICATION_ROLES:
        raise HTTPException(403, "A belső kommunikáció csak belső felhasználóknak érhető el.")
    return {"unread": unread_notification_count(db, user)}


@app.get("/documents/templates", response_class=HTMLResponse)
def canonical_templates_page(
    request: Request,
    category: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    all_rows = list_canonical_templates(role=user.role)
    rows = list_canonical_templates(role=user.role, category=category, query=q)
    categories = sorted({row["category"]: row["category_label"] for row in all_rows}.items())
    return templates.TemplateResponse(
        request=request,
        name="canonical_templates.html",
        context={
            "user": user,
            "rows": rows,
            "categories": categories,
            "filters": {"category": category, "q": q},
            "status": canonical_template_status(),
            "active": "documents",
        },
    )


@app.get("/documents/templates/{template_id}", response_class=HTMLResponse)
def canonical_template_detail(
    request: Request,
    template_id: str,
    created: str | None = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        row = get_canonical_template(template_id, role=user.role)
    except KeyError:
        raise HTTPException(404, "Iratminta nem található.")
    except PermissionError:
        raise HTTPException(403, "Ehhez az iratmintához nincs jogosultsága.")
    projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
    created_document = (
        db.scalar(select(WorkspaceDocument).where(WorkspaceDocument.document_id == created))
        if created
        else None
    )
    return templates.TemplateResponse(
        request=request,
        name="canonical_template_detail.html",
        context={
            "user": user,
            "template": row,
            "projects": projects,
            "created_document": created_document,
            "error": None,
            "active": "documents",
        },
    )


@app.post("/documents/templates/{template_id}/instantiate", response_class=HTMLResponse)
def canonical_template_instantiate(
    request: Request,
    template_id: str,
    project_id: Annotated[str | None, Form()] = None,
    related_object_id: Annotated[str | None, Form()] = None,
    trigger_reason: Annotated[str | None, Form()] = None,
    occurred_at: Annotated[str | None, Form()] = None,
    owner: Annotated[str | None, Form()] = None,
    participants: Annotated[str | None, Form()] = None,
    facts: Annotated[str | None, Form()] = None,
    decision: Annotated[str | None, Form()] = None,
    actions: Annotated[str | None, Form()] = None,
    evidence_ids: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    due_at: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        result = instantiate_canonical_template(
            db,
            template_id=template_id,
            role=user.role,
            actor=user.email,
            owner=(owner or user.email).strip(),
            project_id=(project_id or "").strip() or None,
            related_object_id=(related_object_id or "").strip() or None,
            trigger_reason=(trigger_reason or "").strip() or None,
            occurred_at=(occurred_at or "").strip() or None,
            participants=participants,
            facts=facts,
            decision=decision,
            actions=actions,
            evidence_ids=evidence_ids,
            notes=notes,
            due_at=(due_at or "").strip() or None,
        )
        return RedirectResponse(
            f"/documents/templates/{template_id}?created={result['document'].document_id}",
            status_code=303,
        )
    except (KeyError, PermissionError):
        raise HTTPException(404, "Iratminta nem található vagy nem használható.")
    except ValueError as exc:
        try:
            row = get_canonical_template(template_id, role=user.role)
        except (KeyError, PermissionError):
            raise HTTPException(404, "Iratminta nem található vagy nem használható.")
        projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
        return templates.TemplateResponse(
            request=request,
            name="canonical_template_detail.html",
            context={
                "user": user,
                "template": row,
                "projects": projects,
                "created_document": None,
                "error": str(exc),
                "active": "documents",
            },
            status_code=400,
        )


@app.get("/documents/files/{document_id}")
def canonical_document_download(request: Request, document_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    row = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.document_id == document_id,
            WorkspaceDocument.source_system == "canonical_document_generator",
        )
    )
    if not row:
        raise HTTPException(404, "Dokumentum nem található.")
    metadata = json.loads(row.metadata_json or "{}")
    path = Path(metadata.get("local_path") or "")
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "A generált dokumentumpéldány nem található.")
    return FileResponse(path, filename=path.name, media_type=row.mime_type)


@app.get("/documents", response_class=HTMLResponse)
def documents_page(
    request: Request,
    project_id: str | None = None,
    category: str | None = None,
    approval_status: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    rows = list_documents(
        db, project_id=project_id, category=category, approval_status=approval_status, query_text=q
    )
    metrics = document_metrics(db)
    projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
    categories = sorted(
        {r.category for r in db.scalars(select(WorkspaceDocument)).all()}
        | {
            "contract",
            "plan",
            "invoice",
            "delivery_note",
            "photo",
            "certificate",
            "report",
            "other",
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="documents.html",
        context={
            "user": user,
            "documents": rows,
            "metrics": metrics,
            "projects": projects,
            "categories": categories,
            "filters": {
                "project_id": project_id,
                "category": category,
                "approval_status": approval_status,
                "q": q,
            },
            "active": "documents",
        },
    )


@app.post("/documents")
def documents_create(
    request: Request,
    title: Annotated[str, Form()],
    category: Annotated[str, Form()],
    project_id: Annotated[str | None, Form()] = None,
    source_url: Annotated[str | None, Form()] = None,
    source_system: Annotated[str, Form()] = "google_drive",
    owner: Annotated[str | None, Form()] = None,
    extracted_summary: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    create_document(
        db,
        WorkspaceDocumentIn(
            title=title,
            category=category,
            project_id=project_id or None,
            source_url=source_url or None,
            source_system=source_system,
            owner=owner or user.name,
            extracted_summary=extracted_summary or None,
        ),
        actor=user.email,
    )
    return RedirectResponse("/documents", status_code=303)


@app.post("/documents/{document_id}/status")
def documents_status(
    request: Request,
    document_id: str,
    approval_status: Annotated[str | None, Form()] = None,
    verification_status: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        update_document_status(
            db,
            document_id,
            approval_status=approval_status,
            verification_status=verification_status,
            actor=user.email,
        )
    except KeyError:
        raise HTTPException(404, "Dokumentum nem található.")
    return RedirectResponse("/documents", status_code=303)


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    results = global_search(db, q)
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={"user": user, "q": q, "results": results, "active": "search"},
    )


@app.get("/api/workspace/summary", dependencies=[Depends(require_api_token)])
def api_workspace_summary(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db) or db.scalar(select(User).order_by(User.id))
    if user is None:
        raise HTTPException(404, "Nincs aktív felhasználó.")
    return workspace_summary(db, user)


@app.get("/api/tasks", dependencies=[Depends(require_api_token)])
def api_tasks(
    status: str | None = None,
    priority: str | None = None,
    project_id: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    return list_tasks(db, status=status, priority=priority, project_id=project_id, query_text=q)


@app.post("/api/tasks/{task_id}", dependencies=[Depends(require_api_token)])
def api_task_update(task_id: str, payload: TaskUpdateIn, db: Session = Depends(get_db)):
    try:
        return update_task(db, task_id, payload, actor="api")
    except KeyError:
        raise HTTPException(404, "Feladat nem található.")


@app.get("/api/search", dependencies=[Depends(require_api_token)])
def api_search(q: str, limit: int = 12, db: Session = Depends(get_db)):
    return global_search(db, q, limit=max(1, min(limit, 50)))


@app.get("/api/projects/{project_id}/360", dependencies=[Depends(require_api_token)])
def api_project_360(project_id: str, db: Session = Depends(get_db)):
    try:
        return project_360(db, project_id)
    except KeyError:
        raise HTTPException(404, "Projekt nem található.")


@app.post("/api/documents", dependencies=[Depends(require_api_token)])
def api_document_create(payload: WorkspaceDocumentIn, db: Session = Depends(get_db)):
    return create_document(db, payload, actor="api")


@app.get("/booking/{experience_id}", response_class=HTMLResponse)
def public_booking_page(request: Request, experience_id: str, db: Session = Depends(get_db)):
    experience = db.scalar(
        select(BookingExperienceVersion).where(
            BookingExperienceVersion.experience_id == experience_id,
            BookingExperienceVersion.active.is_(True),
        )
    )
    if not experience:
        raise HTTPException(404, "A foglalási felület nem aktív.")
    slots = db.scalars(
        select(BookingSlot)
        .where(
            BookingSlot.experience_id == experience_id,
            BookingSlot.status == "available",
            BookingSlot.starts_at > datetime.now(timezone.utc),
        )
        .order_by(BookingSlot.starts_at)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="booking_public.html",
        context={
            "user": None,
            "experience": experience,
            "slots": slots,
            "booking": None,
            "error": None,
        },
    )


@app.post("/booking/{experience_id}", response_class=HTMLResponse)
async def public_booking_create(
    request: Request, experience_id: str, db: Session = Depends(get_db)
):
    experience = db.scalar(
        select(BookingExperienceVersion).where(
            BookingExperienceVersion.experience_id == experience_id,
            BookingExperienceVersion.active.is_(True),
        )
    )
    if not experience:
        raise HTTPException(404, "A foglalási felület nem aktív.")
    form = await request.form()
    booking = None
    error = None
    try:
        booking = create_booking(
            db,
            BookingCreateIn(
                slot_id=str(form.get("slot_id") or ""),
                customer_name=str(form.get("customer_name") or ""),
                customer_email=str(form.get("customer_email") or ""),
                customer_phone=str(form.get("customer_phone") or ""),
                project_description=str(form.get("project_description") or ""),
                plot_status=str(form.get("plot_status") or ""),
                planned_start=str(form.get("planned_start") or ""),
                postal_code=str(form.get("postal_code") or "") or None,
                city=str(form.get("city") or "") or None,
                street_address=str(form.get("street_address") or "") or None,
                access_notes=str(form.get("access_notes") or "") or None,
                document_url=str(form.get("document_url") or "") or None,
                consent_version_id=str(form.get("consent_version_id") or "CONSENT-BOOKING-V1"),
                consent=form.get("consent") is not None,
                attribution={
                    "page_id": str(form.get("page_id") or ""),
                    "campaign_id": str(form.get("campaign_id") or ""),
                    "utm_source": str(form.get("utm_source") or ""),
                },
            ),
            actor="public-web",
        )
    except ValueError as exc:
        error = str(exc)
    slots = db.scalars(
        select(BookingSlot)
        .where(
            BookingSlot.experience_id == experience_id,
            BookingSlot.status == "available",
            BookingSlot.starts_at > datetime.now(timezone.utc),
        )
        .order_by(BookingSlot.starts_at)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="booking_public.html",
        context={
            "user": None,
            "experience": experience,
            "slots": slots,
            "booking": booking,
            "error": error,
        },
        status_code=409 if error else 200,
    )


@app.get("/booking/manage/{token}", response_class=HTMLResponse)
def public_booking_manage(request: Request, token: str, db: Session = Depends(get_db)):
    booking = db.scalar(select(BookingRecord).where(BookingRecord.cancellation_token == token))
    if not booking:
        raise HTTPException(404, "Érvénytelen foglaláskezelési hivatkozás.")
    slots = db.scalars(
        select(BookingSlot)
        .where(
            BookingSlot.brand_id == booking.brand_id,
            BookingSlot.booking_type == booking.booking_type,
            BookingSlot.status == "available",
            BookingSlot.starts_at > datetime.now(timezone.utc),
        )
        .order_by(BookingSlot.starts_at)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="booking_manage.html",
        context={"user": None, "booking": booking, "slots": slots, "message": None},
    )


@app.post("/booking/manage/{token}/cancel", response_class=HTMLResponse)
async def public_booking_cancel(request: Request, token: str, db: Session = Depends(get_db)):
    booking = db.scalar(select(BookingRecord).where(BookingRecord.cancellation_token == token))
    if not booking:
        raise HTTPException(404)
    form = await request.form()
    try:
        cancel_booking(
            db,
            booking.booking_id,
            actor="public-web",
            reason=str(form.get("reason") or "Ügyfél által lemondva"),
        )
        message = "A foglalást lemondtuk."
    except ValueError as exc:
        message = str(exc)
    return templates.TemplateResponse(
        request=request,
        name="booking_manage.html",
        context={"user": None, "booking": booking, "slots": [], "message": message},
    )


@app.post("/booking/manage/{token}/reschedule", response_class=HTMLResponse)
async def public_booking_reschedule(request: Request, token: str, db: Session = Depends(get_db)):
    booking = db.scalar(select(BookingRecord).where(BookingRecord.cancellation_token == token))
    if not booking:
        raise HTTPException(404)
    form = await request.form()
    try:
        reschedule_booking(
            db,
            booking.booking_id,
            BookingRescheduleIn(
                new_slot_id=str(form.get("new_slot_id") or ""),
                reason=str(form.get("reason") or "Ügyfél által kért átfoglalás"),
            ),
            actor="public-web",
        )
        message = "Az új idősávot zároltuk; a foglalás új külső naptár-visszaigazolásra vár."
    except ValueError as exc:
        message = str(exc)
    slots = db.scalars(
        select(BookingSlot)
        .where(
            BookingSlot.brand_id == booking.brand_id,
            BookingSlot.booking_type == booking.booking_type,
            BookingSlot.status == "available",
            BookingSlot.starts_at > datetime.now(timezone.utc),
        )
        .order_by(BookingSlot.starts_at)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="booking_manage.html",
        context={"user": None, "booking": booking, "slots": slots, "message": message},
    )


@app.get("/reservation/{offer_version_id}", response_class=HTMLResponse)
def public_reservation_page(request: Request, offer_version_id: str, db: Session = Depends(get_db)):
    offer = db.scalar(
        select(ReservationOfferVersion).where(
            ReservationOfferVersion.offer_version_id == offer_version_id,
            ReservationOfferVersion.active.is_(True),
        )
    )
    if not offer:
        raise HTTPException(404, "Az ajánlat nem aktív.")
    return templates.TemplateResponse(
        request=request,
        name="reservation_public.html",
        context={"user": None, "offer": offer, "reservation": None, "error": None},
    )


@app.post("/reservation/{offer_version_id}", response_class=HTMLResponse)
async def public_reservation_create(
    request: Request, offer_version_id: str, db: Session = Depends(get_db)
):
    offer = db.scalar(
        select(ReservationOfferVersion).where(
            ReservationOfferVersion.offer_version_id == offer_version_id,
            ReservationOfferVersion.active.is_(True),
        )
    )
    if not offer:
        raise HTTPException(404, "Az ajánlat nem aktív.")
    form = await request.form()
    reservation = None
    error = None
    try:
        reservation = create_reservation(
            db,
            ReservationCreateIn(
                offer_version_id=offer_version_id,
                house_plan_id=str(form.get("house_plan_id") or ""),
                house_config_id=str(form.get("house_config_id") or ""),
                customer_name=str(form.get("customer_name") or ""),
                customer_email=str(form.get("customer_email") or ""),
                billing_name=str(form.get("billing_name") or ""),
                billing_address=str(form.get("billing_address") or ""),
                tax_number=str(form.get("tax_number") or "") or None,
                terms_accepted=form.get("terms_accepted") is not None,
                attribution={
                    "page_id": str(form.get("page_id") or ""),
                    "campaign_id": str(form.get("campaign_id") or ""),
                },
            ),
            actor="public-web",
        )
    except ValueError as exc:
        error = str(exc)
    return templates.TemplateResponse(
        request=request,
        name="reservation_public.html",
        context={"user": None, "offer": offer, "reservation": reservation, "error": error},
        status_code=409 if error else 200,
    )


@app.get("/intent/{offer_version_id}", response_class=HTMLResponse)
def public_intent_page(request: Request, offer_version_id: str, db: Session = Depends(get_db)):
    offer = db.scalar(
        select(ReservationOfferVersion).where(
            ReservationOfferVersion.offer_version_id == offer_version_id,
            ReservationOfferVersion.active.is_(True),
            ReservationOfferVersion.intent_declaration_enabled.is_(True),
        )
    )
    if not offer:
        raise HTTPException(404, "A szándéknyilatkozati út nem aktív.")
    return templates.TemplateResponse(
        request=request,
        name="intent_public.html",
        context={"user": None, "offer": offer, "intent": None, "error": None},
    )


@app.post("/intent/{offer_version_id}", response_class=HTMLResponse)
async def public_intent_create(
    request: Request, offer_version_id: str, db: Session = Depends(get_db)
):
    offer = db.scalar(
        select(ReservationOfferVersion).where(
            ReservationOfferVersion.offer_version_id == offer_version_id,
            ReservationOfferVersion.active.is_(True),
            ReservationOfferVersion.intent_declaration_enabled.is_(True),
        )
    )
    if not offer:
        raise HTTPException(404, "A szándéknyilatkozati út nem aktív.")
    form = await request.form()
    intent = None
    error = None
    try:
        intent = create_intent_declaration(
            db,
            IntentDeclarationCreateIn(
                offer_version_id=offer_version_id,
                house_plan_id=str(form.get("house_plan_id") or ""),
                house_config_id=str(form.get("house_config_id") or ""),
                customer_name=str(form.get("customer_name") or ""),
                customer_email=str(form.get("customer_email") or ""),
                customer_phone=str(form.get("customer_phone") or ""),
                target_start_window=str(form.get("target_start_window") or ""),
                project_scope=str(form.get("project_scope") or ""),
                plot_status=str(form.get("plot_status") or ""),
                consent_version_id=str(form.get("consent_version_id") or "CONSENT-INTENT-V1"),
                terms_accepted=form.get("terms_accepted") is not None,
                consent=form.get("consent") is not None,
                attribution={
                    "page_id": str(form.get("page_id") or ""),
                    "campaign_id": str(form.get("campaign_id") or ""),
                },
            ),
            actor="public-web",
        )
    except ValueError as exc:
        error = str(exc)
    return templates.TemplateResponse(
        request=request,
        name="intent_public.html",
        context={"user": None, "offer": offer, "intent": intent, "error": error},
        status_code=409 if error else 200,
    )


@app.get("/intent/manage/{token}", response_class=HTMLResponse)
def public_intent_manage(request: Request, token: str, db: Session = Depends(get_db)):
    intent = db.scalar(
        select(IntentDeclarationRecord).where(IntentDeclarationRecord.cancellation_token == token)
    )
    if not intent:
        raise HTTPException(404, "Érvénytelen szándéknyilatkozat-kezelési hivatkozás.")
    return templates.TemplateResponse(
        request=request,
        name="intent_manage.html",
        context={"user": None, "intent": intent, "message": None},
    )


@app.post("/intent/manage/{token}/withdraw", response_class=HTMLResponse)
async def public_intent_withdraw(request: Request, token: str, db: Session = Depends(get_db)):
    intent = db.scalar(
        select(IntentDeclarationRecord).where(IntentDeclarationRecord.cancellation_token == token)
    )
    if not intent:
        raise HTTPException(404)
    form = await request.form()
    try:
        withdraw_intent_declaration(
            db,
            intent.intent_declaration_id,
            actor="public-web",
            reason=str(form.get("reason") or "Ügyfél által visszavonva"),
        )
        message = "A szándéknyilatkozatot visszavontuk."
    except ValueError as exc:
        message = str(exc)
    return templates.TemplateResponse(
        request=request,
        name="intent_manage.html",
        context={"user": None, "intent": intent, "message": message},
    )


@app.post("/intent/manage/{token}/resubmit", response_class=HTMLResponse)
async def public_intent_resubmit(request: Request, token: str, db: Session = Depends(get_db)):
    intent = db.scalar(
        select(IntentDeclarationRecord).where(IntentDeclarationRecord.cancellation_token == token)
    )
    if not intent:
        raise HTTPException(404)
    form = await request.form()
    try:
        update_intent_declaration(
            db,
            intent.intent_declaration_id,
            IntentDeclarationUpdateIn(
                house_plan_id=str(form.get("house_plan_id") or ""),
                house_config_id=str(form.get("house_config_id") or ""),
                customer_phone=str(form.get("customer_phone") or ""),
                target_start_window=str(form.get("target_start_window") or ""),
                project_scope=str(form.get("project_scope") or ""),
                plot_status=str(form.get("plot_status") or ""),
                consent=form.get("consent") is not None,
            ),
            actor="public-web",
        )
        message = "A módosított szándéknyilatkozatot újra beküldtük."
    except ValueError as exc:
        message = str(exc)
    return templates.TemplateResponse(
        request=request,
        name="intent_manage.html",
        context={"user": None, "intent": intent, "message": message},
    )


@app.get("/my-imperial", response_class=HTMLResponse)
def my_imperial_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "my-imperial"):
        raise HTTPException(403)
    return templates.TemplateResponse(
        request=request,
        name="my_imperial.html",
        context={"user": user, "data": my_imperial_workspace(db, user), "active": "my-imperial"},
    )


@app.get("/my-imperial/{project_id}", response_class=HTMLResponse)
def my_imperial_project_page(request: Request, project_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        data = project_portal_detail(db, project_id, user)
    except KeyError as exc:
        raise HTTPException(404, "A projekt nem található.") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="my_imperial_project.html",
        context={"user": user, "data": data, "active": "my-imperial"},
    )


@app.get("/my-imperial/{project_id}/documents/{document_id}")
def my_imperial_document_download(
    request: Request,
    project_id: str,
    document_id: str,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        assert_project_access(db, project_id, user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    row = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.document_id == document_id,
            WorkspaceDocument.project_id == project_id,
            WorkspaceDocument.source_system == "change-control",
            WorkspaceDocument.confidentiality == "customer",
            WorkspaceDocument.approval_status == "approved",
            WorkspaceDocument.verification_status == "sha256_verified",
        )
    )
    if not row:
        raise HTTPException(404, "Az ügyféldokumentum nem található.")
    metadata = json.loads(row.metadata_json or "{}")
    path = Path(metadata.get("local_path") or "")
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Az ügyféldokumentum fájlja nem található.")
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha != metadata.get("artifact_sha256"):
        raise HTTPException(409, "Az ügyféldokumentum SHA-256 ellenőrzése sikertelen.")
    return FileResponse(path, filename=path.name, media_type="application/pdf")


@app.post("/my-imperial/{project_id}/updates")
async def my_imperial_update_publish(
    request: Request, project_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        publish_project_update(
            db,
            project_id,
            user,
            title=str(form.get("title") or ""),
            body=str(form.get("body") or ""),
            progress_percent=int(str(form.get("progress_percent") or "0")),
            requires_acknowledgement=form.get("requires_acknowledgement") is not None,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/my-imperial/{project_id}#updates", status_code=303)


@app.post("/my-imperial/{project_id}/updates/{update_id}/acknowledge")
def my_imperial_update_acknowledge(
    request: Request, project_id: str, update_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        acknowledge_project_update(db, project_id, update_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/my-imperial/{project_id}#updates", status_code=303)


@app.post("/my-imperial/{project_id}/decisions")
async def my_imperial_decision_create(
    request: Request, project_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    due_raw = str(form.get("due_at") or "").strip()
    try:
        due_at = None
        if due_raw:
            due_at = datetime.fromisoformat(due_raw)
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=ZoneInfo("Europe/Budapest")).astimezone(timezone.utc)
        create_decision_request(
            db,
            project_id,
            user,
            title=str(form.get("title") or ""),
            description=str(form.get("description") or ""),
            options=str(form.get("options") or "").splitlines(),
            due_at=due_at,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/my-imperial/{project_id}#decisions", status_code=303)


@app.post("/my-imperial/{project_id}/decisions/{decision_id}/respond")
async def my_imperial_decision_respond(
    request: Request, project_id: str, decision_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        respond_to_decision(
            db,
            project_id,
            decision_id,
            user,
            selected_option=str(form.get("selected_option") or ""),
            note=str(form.get("note") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/my-imperial/{project_id}#decisions", status_code=303)


@app.post("/my-imperial/{project_id}/tasks/{task_id}/complete")
def my_imperial_task_complete(
    request: Request, project_id: str, task_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        complete_customer_task(db, project_id, task_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/my-imperial/{project_id}#tasks", status_code=303)


@app.get("/imperial-care", response_class=HTMLResponse)
def imperial_care_page(
    request: Request,
    project_id: str = "",
    status: str = "",
    severity: str = "",
    assigned_to: str = "",
    query: str = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    data = care_workspace(
        db,
        user,
        project_id=project_id,
        status=status,
        severity=severity,
        assigned_to=assigned_to,
        query_text=query,
    )
    return templates.TemplateResponse(
        request=request,
        name="imperial_care.html",
        context={"user": user, "data": data, "active": "imperial-care"},
    )


@app.post("/imperial-care/cases")
async def imperial_care_case_create(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        row = create_care_case(
            db,
            user,
            project_id=str(form.get("project_id") or ""),
            category=str(form.get("category") or ""),
            severity=str(form.get("severity") or ""),
            title=str(form.get("title") or ""),
            description=str(form.get("description") or ""),
            location=str(form.get("location") or ""),
            preferred_contact=str(form.get("preferred_contact") or ""),
            customer_email=str(form.get("customer_email") or ""),
            reporter_name=str(form.get("reporter_name") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/imperial-care/{row.case_id}", status_code=303)


@app.get("/imperial-care/evidence/{evidence_id}")
def imperial_care_evidence_download(
    request: Request, evidence_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        evidence = care_evidence_for_user(db, evidence_id, user)
    except KeyError as exc:
        raise HTTPException(404, "A bizonyíték nem található.") from exc
    except PermissionError as exc:
        raise HTTPException(403) from exc
    try:
        path = verified_care_evidence_path(
            db,
            evidence,
            storage_root=CARE_EVIDENCE_DIR,
            actor=user.email,
        )
    except CareEvidenceUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(path, media_type=evidence.mime_type, filename=evidence.file_name)


@app.get("/imperial-care/{case_id}", response_class=HTMLResponse)
def imperial_care_case_page(request: Request, case_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        row = care_case_for_user(db, case_id, user)
    except KeyError as exc:
        raise HTTPException(404, "Az Imperial Care ügy nem található.") from exc
    except PermissionError as exc:
        raise HTTPException(403) from exc
    messages = row.messages
    if user.role not in {
        "owner",
        "managing-director",
        "platform-admin",
        "project-manager",
        "technical-prep",
    }:
        messages = [message for message in messages if message.customer_visible]
    return templates.TemplateResponse(
        request=request,
        name="imperial_care_case.html",
        context={
            "user": user,
            "case": row,
            "messages": sorted(messages, key=lambda item: item.created_at),
            "internal": user.role
            in {
                "owner",
                "managing-director",
                "platform-admin",
                "project-manager",
                "technical-prep",
            },
            "active": "imperial-care",
        },
    )


@app.post("/imperial-care/{case_id}/messages")
async def imperial_care_message_create(
    request: Request, case_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        add_care_message(
            db,
            case_id,
            user,
            body=str(form.get("body") or ""),
            customer_visible=form.get("customer_visible") is not None,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/imperial-care/{case_id}#messages", status_code=303)


@app.post("/imperial-care/{case_id}/status")
async def imperial_care_case_status(request: Request, case_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        expected_version = int(str(form.get("expected_version") or ""))
        transition_care_case(
            db,
            case_id,
            user,
            status=str(form.get("status") or ""),
            assigned_to=str(form.get("assigned_to") or ""),
            resolution_summary=str(form.get("resolution_summary") or ""),
            expected_version=expected_version,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/imperial-care/{case_id}", status_code=303)


@app.post("/imperial-care/{case_id}/evidence")
async def imperial_care_evidence_upload(
    request: Request,
    case_id: str,
    file: UploadFile = File(...),
    caption: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    raw = await file.read(10 * 1024 * 1024 + 1)
    try:
        save_care_evidence(
            db,
            case_id,
            user,
            file_name=file.filename or "care-evidence",
            mime_type=file.content_type or "application/octet-stream",
            raw=raw,
            caption=caption or "",
            storage_root=CARE_EVIDENCE_DIR,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403) from exc
    except TenderScannerUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except TenderMalwareDetected as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/imperial-care/{case_id}#evidence", status_code=303)


@app.get("/sales-commercial", response_class=HTMLResponse)
def sales_commercial_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in _SALES_COMMERCIAL_INTERNAL_ROLES:
        raise HTTPException(
            403, "Az ügyfél csak a saját, tokennel védett foglalási felületét használhatja."
        )
    return templates.TemplateResponse(
        request=request,
        name="sales_commercial.html",
        context={
            "user": user,
            "data": commercial_sales_workspace(db),
            "pipeline": sales_pipeline_workspace(db),
            "active": "sales-commercial",
            "can_activate": user.role in {"owner", "platform-admin"},
        },
    )


@app.post("/sales-commercial/opportunities")
async def sales_opportunity_create(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    expected_close = str(form.get("expected_close_date") or "")
    try:
        create_opportunity(
            db,
            SalesOpportunityIn(
                lead_id=str(form.get("lead_id") or "") or None,
                customer_id=str(form.get("customer_id") or "") or None,
                brand_id=str(form.get("brand_id") or ""),
                title=str(form.get("title") or ""),
                customer_name=str(form.get("customer_name") or ""),
                customer_email=str(form.get("customer_email") or "") or None,
                owner_email=str(form.get("owner_email") or ""),
                estimated_value_huf=Decimal(str(form.get("estimated_value_huf") or "0")),
                probability_percent=int(str(form.get("probability_percent") or "10")),
                expected_close_date=(
                    datetime.fromisoformat(expected_close).date() if expected_close else None
                ),
                needs_summary=str(form.get("needs_summary") or ""),
                budget_confirmed=form.get("budget_confirmed") is not None,
                decision_process=str(form.get("decision_process") or ""),
                next_action=str(form.get("next_action") or ""),
            ),
            user,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#pipeline", status_code=303)


@app.post("/sales-commercial/opportunities/{opportunity_id}/stage")
async def sales_opportunity_stage(
    opportunity_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        transition_opportunity(
            db,
            opportunity_id,
            SalesOpportunityStageIn(
                stage=str(form.get("stage") or ""),
                note=str(form.get("note") or ""),
                probability_percent=int(str(form.get("probability_percent") or "0")),
                next_action=str(form.get("next_action") or ""),
            ),
            user,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#pipeline", status_code=303)


@app.post("/sales-commercial/opportunities/{opportunity_id}/proposals")
async def sales_proposal_create(
    opportunity_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        create_proposal(
            db,
            opportunity_id,
            SalesProposalIn(
                currency=str(form.get("currency") or "HUF"),
                vat_rate=Decimal(str(form.get("vat_rate") or "27")),
                cost_net=Decimal(str(form.get("cost_net") or "0")),
                sale_net=Decimal(str(form.get("sale_net") or "0")),
                price_snapshot_id=str(form.get("price_snapshot_id") or ""),
                terms_version_id=str(form.get("terms_version_id") or ""),
                technical_scope_version_id=str(form.get("technical_scope_version_id") or ""),
                scope_summary=str(form.get("scope_summary") or ""),
                exclusions=str(form.get("exclusions") or ""),
                payment_terms=str(form.get("payment_terms") or ""),
                valid_until=datetime.fromisoformat(str(form.get("valid_until") or "")),
            ),
            user,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#pipeline", status_code=303)


@app.post("/sales-commercial/proposals/{proposal_version_id}/submit")
def sales_proposal_submit(
    proposal_version_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    try:
        submit_proposal(db, proposal_version_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#pipeline", status_code=303)


@app.post("/sales-commercial/proposals/{proposal_version_id}/review")
async def sales_proposal_review(
    proposal_version_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        review_proposal(
            db,
            proposal_version_id,
            SalesProposalReviewIn(
                gate=str(form.get("gate") or ""),
                decision=str(form.get("decision") or ""),
                note=str(form.get("note") or ""),
            ),
            user,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#pipeline", status_code=303)


@app.post("/sales-commercial/proposals/{proposal_version_id}/send")
async def sales_proposal_send(
    proposal_version_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        send_proposal(
            db,
            proposal_version_id,
            SalesProposalSendIn(delivery_evidence_url=str(form.get("delivery_evidence_url") or "")),
            user,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#pipeline", status_code=303)


@app.post("/sales-commercial/proposals/{proposal_version_id}/decision")
async def sales_proposal_decision(
    proposal_version_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        record_proposal_decision(
            db,
            proposal_version_id,
            SalesProposalDecisionIn(
                decision=str(form.get("decision") or ""),
                customer_decision_reference=str(form.get("customer_decision_reference") or ""),
                note=str(form.get("note") or ""),
            ),
            user,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#pipeline", status_code=303)


@app.post("/sales-commercial/opportunities/{opportunity_id}/close")
async def sales_opportunity_close(
    opportunity_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        close_opportunity(
            db,
            opportunity_id,
            SalesOpportunityCloseIn(
                outcome=str(form.get("outcome") or ""),
                reason=str(form.get("reason") or ""),
                contract_id=str(form.get("contract_id") or "") or None,
                delivery_project_id=str(form.get("delivery_project_id") or "") or None,
                competitor=str(form.get("competitor") or "") or None,
            ),
            user,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#pipeline", status_code=303)


@app.post("/sales-commercial/experiences")
async def sales_commercial_experience_create(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "platform-admin", "sales"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        create_booking_experience(
            db,
            BookingExperienceIn(
                experience_id=str(form.get("experience_id") or ""),
                brand_id=str(form.get("brand_id") or ""),
                version=str(form.get("version") or "v1"),
                display_name=str(form.get("display_name") or ""),
                cta_label=str(form.get("cta_label") or ""),
                trust_copy=str(form.get("trust_copy") or ""),
                confirmation_copy=str(form.get("confirmation_copy") or ""),
                theme_key=str(form.get("theme_key") or ""),
                active=form.get("active") is not None and user.role in {"owner", "platform-admin"},
                policy={},
            ),
            actor=user.email,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#booking", status_code=303)


@app.post("/sales-commercial/experiences/{experience_id}/activation")
async def sales_commercial_experience_activation(
    experience_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "platform-admin"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        set_booking_experience_active(
            db,
            experience_id,
            VersionActivationIn(
                active=str(form.get("active") or "false").lower() == "true",
                note=str(form.get("note") or "Tulajdonosi verzióváltás"),
            ),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#booking", status_code=303)


@app.post("/sales-commercial/slots")
async def sales_commercial_slot_create(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "managing-director", "platform-admin", "sales"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        create_booking_slot(
            db,
            BookingSlotIn(
                experience_id=str(form.get("experience_id") or ""),
                booking_type=str(form.get("booking_type") or ""),
                calendar_resource_id=str(form.get("calendar_resource_id") or ""),
                advisor_email=str(form.get("advisor_email") or ""),
                starts_at=datetime.fromisoformat(str(form.get("starts_at") or "")),
                ends_at=datetime.fromisoformat(str(form.get("ends_at") or "")),
                location=str(form.get("location") or "") or None,
            ),
            actor=user.email,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#booking", status_code=303)


@app.post("/sales-commercial/bookings")
async def sales_commercial_booking_create(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "managing-director", "platform-admin", "sales"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        create_booking(
            db,
            BookingCreateIn(
                slot_id=str(form.get("slot_id") or ""),
                project_id=str(form.get("project_id") or "") or None,
                lead_id=str(form.get("lead_id") or "") or None,
                opportunity_id=str(form.get("opportunity_id") or "") or None,
                customer_name=str(form.get("customer_name") or ""),
                customer_email=str(form.get("customer_email") or ""),
                customer_phone=str(form.get("customer_phone") or ""),
                project_description=str(form.get("project_description") or ""),
                plot_status=str(form.get("plot_status") or ""),
                planned_start=str(form.get("planned_start") or ""),
                postal_code=str(form.get("postal_code") or "") or None,
                city=str(form.get("city") or "") or None,
                street_address=str(form.get("street_address") or "") or None,
                access_notes=str(form.get("access_notes") or "") or None,
                document_url=str(form.get("document_url") or "") or None,
                consent_version_id=str(form.get("consent_version_id") or ""),
                consent=form.get("consent") is not None,
                attribution={},
            ),
            actor=user.email,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#bookings", status_code=303)


@app.post("/sales-commercial/bookings/{booking_id}/calendar-sync")
async def sales_commercial_booking_sync(
    booking_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "managing-director", "platform-admin", "sales"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        record_booking_calendar_sync(
            db,
            booking_id,
            BookingCalendarSyncIn(
                success=form.get("success") is not None,
                calendar_event_id=str(form.get("calendar_event_id") or "") or None,
                meeting_link=str(form.get("meeting_link") or "") or None,
                error=str(form.get("error") or "") or None,
            ),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#bookings", status_code=303)


@app.post("/sales-commercial/bookings/{booking_id}/cancel")
async def sales_commercial_booking_cancel(
    booking_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "managing-director", "platform-admin", "sales"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        cancel_booking(
            db,
            booking_id,
            actor=user.email,
            reason=str(form.get("reason") or "Felhasználói lemondás"),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#bookings", status_code=303)


@app.post("/sales-commercial/bookings/{booking_id}/outcome")
async def sales_commercial_booking_outcome(
    booking_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "managing-director", "platform-admin", "sales"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        update_booking_outcome(
            db,
            booking_id,
            BookingOutcomeIn(
                status=str(form.get("status") or ""), note=str(form.get("note") or "")
            ),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#bookings", status_code=303)


@app.post("/sales-commercial/offers")
async def sales_commercial_offer_create(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "platform-admin", "finance"}:
        raise HTTPException(403)
    form = await request.form()
    active = form.get("active") is not None
    if active and user.role not in {"owner", "platform-admin"}:
        raise HTTPException(
            403, "Aktív OfferVersiont csak tulajdonos vagy platform-admin adhat ki."
        )
    try:
        create_offer_version(
            db,
            ReservationOfferIn(
                offer_version_id=str(form.get("offer_version_id") or ""),
                brand_id=str(form.get("brand_id") or ""),
                public_name=str(form.get("public_name") or ""),
                cta_label=str(form.get("cta_label") or ""),
                reservation_amount_huf=Decimal(str(form.get("reservation_amount_huf") or "0")),
                target_start_months_min=int(str(form.get("target_start_months_min") or "6")),
                target_start_months_max=int(str(form.get("target_start_months_max") or "12")),
                price_lock_months=int(str(form.get("price_lock_months") or "12")),
                price_snapshot_id=str(form.get("price_snapshot_id") or ""),
                terms_version_id=str(form.get("terms_version_id") or ""),
                technical_scope_version_id=str(form.get("technical_scope_version_id") or ""),
                valid_from=datetime.fromisoformat(str(form.get("valid_from") or "")),
                valid_to=datetime.fromisoformat(str(form.get("valid_to") or "")),
                public_summary=str(form.get("public_summary") or ""),
                exclusions_summary=str(form.get("exclusions_summary") or ""),
                refund_rule=str(form.get("refund_rule") or ""),
                transfer_rule=str(form.get("transfer_rule") or ""),
                intent_declaration_enabled=form.get("intent_declaration_enabled") is not None,
                intent_valid_days=int(str(form.get("intent_valid_days") or "30")),
                intent_public_summary=str(form.get("intent_public_summary") or ""),
                legal_approved=form.get("legal_approved") is not None,
                finance_approved=form.get("finance_approved") is not None,
                pricing_approved=form.get("pricing_approved") is not None,
                active=active,
            ),
            actor=user.email,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#reservation", status_code=303)


@app.post("/sales-commercial/offers/{offer_version_id}/activation")
async def sales_commercial_offer_activation(
    offer_version_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "platform-admin"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        set_offer_active(
            db,
            offer_version_id,
            VersionActivationIn(
                active=str(form.get("active") or "false").lower() == "true",
                note=str(form.get("note") or "Tulajdonosi OfferVersion-váltás"),
            ),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#reservation", status_code=303)


@app.post("/sales-commercial/reservations")
async def sales_commercial_reservation_create(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "managing-director", "platform-admin", "sales", "finance"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        create_reservation(
            db,
            ReservationCreateIn(
                project_id=str(form.get("project_id") or "") or None,
                lead_id=str(form.get("lead_id") or "") or None,
                opportunity_id=str(form.get("opportunity_id") or "") or None,
                offer_version_id=str(form.get("offer_version_id") or ""),
                house_plan_id=str(form.get("house_plan_id") or ""),
                house_config_id=str(form.get("house_config_id") or ""),
                customer_name=str(form.get("customer_name") or ""),
                customer_email=str(form.get("customer_email") or ""),
                billing_name=str(form.get("billing_name") or ""),
                billing_address=str(form.get("billing_address") or ""),
                tax_number=str(form.get("tax_number") or "") or None,
                terms_accepted=form.get("terms_accepted") is not None,
                attribution={},
            ),
            actor=user.email,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#reservations", status_code=303)


@app.post("/sales-commercial/intents")
async def sales_commercial_intent_create(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "managing-director", "platform-admin", "sales"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        create_intent_declaration(
            db,
            IntentDeclarationCreateIn(
                project_id=str(form.get("project_id") or "") or None,
                lead_id=str(form.get("lead_id") or "") or None,
                opportunity_id=str(form.get("opportunity_id") or "") or None,
                offer_version_id=str(form.get("offer_version_id") or ""),
                house_plan_id=str(form.get("house_plan_id") or ""),
                house_config_id=str(form.get("house_config_id") or ""),
                customer_name=str(form.get("customer_name") or ""),
                customer_email=str(form.get("customer_email") or ""),
                customer_phone=str(form.get("customer_phone") or ""),
                target_start_window=str(form.get("target_start_window") or ""),
                project_scope=str(form.get("project_scope") or ""),
                plot_status=str(form.get("plot_status") or ""),
                consent_version_id=str(form.get("consent_version_id") or "CONSENT-INTENT-V1"),
                terms_accepted=form.get("terms_accepted") is not None,
                consent=form.get("consent") is not None,
                attribution={},
            ),
            actor=user.email,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#intents", status_code=303)


@app.post("/sales-commercial/intents/{intent_declaration_id}/review")
async def sales_commercial_intent_review(
    intent_declaration_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "managing-director", "platform-admin", "sales", "legal"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        review_intent_declaration(
            db,
            intent_declaration_id,
            IntentDeclarationReviewIn(
                action=str(form.get("action") or ""),
                note=str(form.get("note") or ""),
                delivery_evidence_url=str(form.get("delivery_evidence_url") or "") or None,
            ),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#intents", status_code=303)


@app.post("/sales-commercial/intents/{intent_declaration_id}/convert")
async def sales_commercial_intent_convert(
    intent_declaration_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "platform-admin", "sales", "legal"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        convert_intent_declaration(
            db, intent_declaration_id, str(form.get("contract_id") or ""), actor=user.email
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#intents", status_code=303)


@app.post("/sales-commercial/reservations/{reservation_id}/payment")
async def sales_commercial_payment_result(
    reservation_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "platform-admin", "finance"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        record_payment_result(
            db,
            reservation_id,
            ReservationPaymentResultIn(
                provider=str(form.get("provider") or ""),
                provider_reference=str(form.get("provider_reference") or ""),
                idempotency_key=str(form.get("idempotency_key") or ""),
                amount_huf=Decimal(str(form.get("amount_huf") or "0")),
                status=str(form.get("status") or "failed"),
                evidence_url=str(form.get("evidence_url") or "") or None,
                raw_result={"source": "internal_controlled_callback"},
            ),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#reservations", status_code=303)


@app.post("/sales-commercial/reservations/{reservation_id}/lifecycle")
async def sales_commercial_reservation_lifecycle(
    reservation_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "platform-admin", "finance", "sales"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        transition_reservation(
            db,
            reservation_id,
            ReservationLifecycleIn(
                action=str(form.get("action") or ""),
                reason=str(form.get("reason") or ""),
                evidence_url=str(form.get("evidence_url") or "") or None,
            ),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#reservations", status_code=303)


@app.post("/sales-commercial/reservations/{reservation_id}/convert")
async def sales_commercial_reservation_convert(
    reservation_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {"owner", "platform-admin", "sales", "legal"}:
        raise HTTPException(403)
    form = await request.form()
    try:
        convert_reservation(
            db, reservation_id, str(form.get("contract_id") or ""), actor=user.email
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/sales-commercial#reservations", status_code=303)


@app.get("/api/sales-commercial/summary")
def api_sales_commercial_summary(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if user.role not in _SALES_COMMERCIAL_INTERNAL_ROLES:
        raise HTTPException(403)
    data = commercial_sales_workspace(db)
    pipeline = sales_pipeline_workspace(db)
    return {
        "metrics": data["metrics"],
        "pipeline_metrics": pipeline["metrics"],
        "opportunities": [serialize_opportunity(row) for row in pipeline["opportunities"]],
        "proposals": [serialize_proposal(row) for row in pipeline["proposals"]],
        "bookings": [serialize_booking(row) for row in data["bookings"]],
        "reservations": [serialize_reservation(row) for row in data["reservations"]],
    }


@app.post("/api/sales-commercial/opportunities")
def api_sales_opportunity_create(
    payload: SalesOpportunityIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    try:
        return serialize_opportunity(create_opportunity(db, payload, user))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/opportunities/{opportunity_id}/stage")
def api_sales_opportunity_stage(
    opportunity_id: str,
    payload: SalesOpportunityStageIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    try:
        return serialize_opportunity(transition_opportunity(db, opportunity_id, payload, user))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/opportunities/{opportunity_id}/proposals")
def api_sales_proposal_create(
    opportunity_id: str,
    payload: SalesProposalIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    try:
        return serialize_proposal(create_proposal(db, opportunity_id, payload, user))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/proposals/{proposal_version_id}/submit")
def api_sales_proposal_submit(
    proposal_version_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    try:
        return serialize_proposal(submit_proposal(db, proposal_version_id, user))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/proposals/{proposal_version_id}/review")
def api_sales_proposal_review(
    proposal_version_id: str,
    payload: SalesProposalReviewIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    try:
        return serialize_proposal(review_proposal(db, proposal_version_id, payload, user))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/proposals/{proposal_version_id}/send")
def api_sales_proposal_send(
    proposal_version_id: str,
    payload: SalesProposalSendIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    try:
        return serialize_proposal(send_proposal(db, proposal_version_id, payload, user))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/proposals/{proposal_version_id}/decision")
def api_sales_proposal_decision(
    proposal_version_id: str,
    payload: SalesProposalDecisionIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    try:
        return serialize_proposal(record_proposal_decision(db, proposal_version_id, payload, user))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/opportunities/{opportunity_id}/close")
def api_sales_opportunity_close(
    opportunity_id: str,
    payload: SalesOpportunityCloseIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    try:
        return serialize_opportunity(close_opportunity(db, opportunity_id, payload, user))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/experiences")
def api_booking_experience_create(
    payload: BookingExperienceIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "platform-admin", "sales"}:
        raise HTTPException(403)
    if payload.active and user.role not in {"owner", "platform-admin"}:
        raise HTTPException(403)
    try:
        row = create_booking_experience(db, payload, actor=user.email)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"experience_id": row.experience_id, "active": row.active}


@app.post("/api/sales-commercial/experiences/{experience_id}/activation")
def api_booking_experience_activation(
    experience_id: str,
    payload: VersionActivationIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "platform-admin"}:
        raise HTTPException(403)
    try:
        row = set_booking_experience_active(db, experience_id, payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"experience_id": row.experience_id, "active": row.active}


@app.post("/api/sales-commercial/slots")
def api_booking_slot_create(
    payload: BookingSlotIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "managing-director", "platform-admin", "sales"}:
        raise HTTPException(403)
    try:
        row = create_booking_slot(db, payload, actor=user.email)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"slot_id": row.slot_id, "status": row.status}


@app.post("/api/sales-commercial/bookings")
def api_booking_create(payload: BookingCreateIn, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if user.role not in {"owner", "managing-director", "platform-admin", "sales"}:
        raise HTTPException(403)
    try:
        return serialize_booking(create_booking(db, payload, actor=user.email))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/bookings/{booking_id}/calendar-sync")
def api_booking_calendar_sync(
    booking_id: str, payload: BookingCalendarSyncIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "managing-director", "platform-admin", "sales"}:
        raise HTTPException(403)
    try:
        return serialize_booking(
            record_booking_calendar_sync(db, booking_id, payload, actor=user.email)
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/bookings/{booking_id}/reschedule")
def api_booking_reschedule(
    booking_id: str, payload: BookingRescheduleIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "managing-director", "platform-admin", "sales"}:
        raise HTTPException(403)
    try:
        return serialize_booking(reschedule_booking(db, booking_id, payload, actor=user.email))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/bookings/{booking_id}/outcome")
def api_booking_outcome(
    booking_id: str, payload: BookingOutcomeIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "managing-director", "platform-admin", "sales"}:
        raise HTTPException(403)
    try:
        return serialize_booking(update_booking_outcome(db, booking_id, payload, actor=user.email))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/offers")
def api_reservation_offer_create(
    payload: ReservationOfferIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "platform-admin", "finance"}:
        raise HTTPException(403)
    if payload.active and user.role not in {"owner", "platform-admin"}:
        raise HTTPException(403)
    try:
        row = create_offer_version(db, payload, actor=user.email)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"offer_version_id": row.offer_version_id, "active": row.active}


@app.post("/api/sales-commercial/offers/{offer_version_id}/activation")
def api_reservation_offer_activation(
    offer_version_id: str,
    payload: VersionActivationIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "platform-admin"}:
        raise HTTPException(403)
    try:
        row = set_offer_active(db, offer_version_id, payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"offer_version_id": row.offer_version_id, "active": row.active}


@app.post("/api/sales-commercial/reservations")
def api_reservation_create(
    payload: ReservationCreateIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "managing-director", "platform-admin", "sales", "finance"}:
        raise HTTPException(403)
    try:
        return serialize_reservation(create_reservation(db, payload, actor=user.email))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/reservations/{reservation_id}/payment")
def api_reservation_payment(
    reservation_id: str,
    payload: ReservationPaymentResultIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "platform-admin", "finance"}:
        raise HTTPException(403)
    try:
        row, payment = record_payment_result(db, reservation_id, payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "reservation": serialize_reservation(row),
        "payment_id": payment.payment_id,
        "payment_status": payment.status,
    }


@app.post("/api/sales-commercial/reservations/{reservation_id}/lifecycle")
def api_reservation_lifecycle(
    reservation_id: str,
    payload: ReservationLifecycleIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "platform-admin", "finance", "sales"}:
        raise HTTPException(403)
    try:
        return serialize_reservation(
            transition_reservation(db, reservation_id, payload, actor=user.email)
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/reservations/{reservation_id}/convert")
def api_reservation_convert(
    reservation_id: str,
    payload: ReservationConvertIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "platform-admin", "sales", "legal"}:
        raise HTTPException(403)
    try:
        return serialize_reservation(
            convert_reservation(db, reservation_id, payload.contract_id, actor=user.email)
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/intents")
def api_intent_create(
    payload: IntentDeclarationCreateIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "managing-director", "platform-admin", "sales"}:
        raise HTTPException(403)
    try:
        return serialize_intent_declaration(
            create_intent_declaration(db, payload, actor=user.email)
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/intents/{intent_declaration_id}/review")
def api_intent_review(
    intent_declaration_id: str,
    payload: IntentDeclarationReviewIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "managing-director", "platform-admin", "sales", "legal"}:
        raise HTTPException(403)
    try:
        return serialize_intent_declaration(
            review_intent_declaration(db, intent_declaration_id, payload, actor=user.email)
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sales-commercial/intents/{intent_declaration_id}/convert")
def api_intent_convert(
    intent_declaration_id: str,
    payload: IntentDeclarationConvertIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    if user.role not in {"owner", "platform-admin", "sales", "legal"}:
        raise HTTPException(403)
    try:
        return serialize_intent_declaration(
            convert_intent_declaration(
                db, intent_declaration_id, payload.contract_id, actor=user.email
            )
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/my-imperial/summary")
def api_my_imperial_summary(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not can_access(user, "my-imperial"):
        raise HTTPException(403)
    data = my_imperial_workspace(db, user)
    return {
        "metrics": data["metrics"],
        "projects": [
            {"project_id": row.project_id, "name": row.name, "status": row.status}
            for row in data["projects"]
        ],
        "reservations": [serialize_reservation(row) for row in data["reservations"]],
        "intents": [serialize_intent_declaration(row) for row in data["intents"]],
        "customer_tasks": [
            {
                "task_id": row.task_id,
                "project_id": row.project_id,
                "title": row.title,
                "status": row.status,
                "due_at": row.due_at,
            }
            for row in data["customer_tasks"]
        ],
    }


@app.get("/commercial", response_class=HTMLResponse)
def commercial_page(request: Request, project_id: str | None = None, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    data = commercial_workspace(db, project_id=project_id)
    return templates.TemplateResponse(
        request=request,
        name="commercial.html",
        context={"user": user, "data": data, "active": "commercial"},
    )


_CHANGE_INTERNAL_ROLES = {
    "owner",
    "managing-director",
    "platform-admin",
    "project-manager",
    "technical-prep",
    "finance",
    "legal",
}


def _change_user(request: Request, db: Session) -> User:
    user = require_session_user(request, db)
    if user.role not in _CHANGE_INTERNAL_ROLES:
        raise HTTPException(403, "A Change Control belső üzleti felület.")
    return user


@app.get("/change-control", response_class=HTMLResponse)
def change_control_page(
    request: Request, project_id: str | None = None, db: Session = Depends(get_db)
):
    user = _change_user(request, db)
    return templates.TemplateResponse(
        request=request,
        name="change_control.html",
        context={
            "user": user,
            "data": change_control_workspace(db, project_id=project_id),
            "active": "commercial",
        },
    )


@app.get("/change-control/{change_id}", response_class=HTMLResponse)
def change_control_detail_page(change_id: str, request: Request, db: Session = Depends(get_db)):
    user = _change_user(request, db)
    try:
        data = change_control_detail(db, change_id)
    except KeyError as exc:
        raise HTTPException(404, "A ChangeID nem található.") from exc
    return templates.TemplateResponse(
        request=request,
        name="change_control_detail.html",
        context={"user": user, "data": data, "active": "commercial"},
    )


@app.get("/change-control/files/{document_id}")
def change_control_document_download(
    document_id: str, request: Request, db: Session = Depends(get_db)
):
    _change_user(request, db)
    row = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.document_id == document_id,
            WorkspaceDocument.source_system == "change-control",
            WorkspaceDocument.verification_status == "sha256_verified",
        )
    )
    if not row:
        raise HTTPException(404, "A ChangeControl dokumentum nem található.")
    metadata = json.loads(row.metadata_json or "{}")
    path = Path(metadata.get("local_path") or "")
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "A ChangeControl dokumentumfájl nem található.")
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha != metadata.get("artifact_sha256"):
        raise HTTPException(409, "A ChangeControl dokumentum SHA-256 ellenőrzése sikertelen.")
    return FileResponse(path, filename=path.name, media_type="application/pdf")


@app.post("/change-control")
async def change_control_create(request: Request, db: Session = Depends(get_db)):
    user = _change_user(request, db)
    form = await request.form()
    try:
        row = create_change_case(
            db,
            user,
            project_id=str(form.get("project_id") or ""),
            title=str(form.get("title") or ""),
            change_type=str(form.get("change_type") or ""),
            reason=str(form.get("reason") or ""),
            technical_scope=str(form.get("technical_scope") or ""),
            exclusions=str(form.get("exclusions") or ""),
            assumptions=str(form.get("assumptions") or ""),
            deadline_impact_days=int(str(form.get("deadline_impact_days") or "0")),
            vat_rate=form.get("vat_rate") or "27",
            customer_advance_net=form.get("customer_advance_net") or "0",
            responsible=str(form.get("responsible") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/change-control/{row.change_id}", status_code=303)


@app.post("/change-control/{change_id}/draft")
async def change_control_draft_update(
    change_id: str, request: Request, db: Session = Depends(get_db)
):
    user = _change_user(request, db)
    form = await request.form()
    try:
        update_change_draft(
            db,
            change_id,
            user,
            reason=str(form.get("reason") or ""),
            technical_scope=str(form.get("technical_scope") or ""),
            exclusions=str(form.get("exclusions") or ""),
            assumptions=str(form.get("assumptions") or ""),
            deadline_impact_days=int(str(form.get("deadline_impact_days") or "0")),
            vat_rate=form.get("vat_rate") or "27",
            customer_advance_net=form.get("customer_advance_net") or "0",
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/change-control/{change_id}", status_code=303)


@app.post("/change-control/{change_id}/lines")
async def change_control_line_create(
    change_id: str, request: Request, db: Session = Depends(get_db)
):
    user = _change_user(request, db)
    form = await request.form()
    try:
        add_change_line(
            db,
            change_id,
            user,
            category=str(form.get("category") or ""),
            description=str(form.get("description") or ""),
            quantity=form.get("quantity") or "0",
            unit=str(form.get("unit") or ""),
            unit_cost_net=form.get("unit_cost_net") or "0",
            unit_sale_net=form.get("unit_sale_net") or "0",
            early_direct_cost=form.get("early_direct_cost") is not None,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/change-control/{change_id}", status_code=303)


@app.post("/change-control/{change_id}/lines/{line_id}/delete")
def change_control_line_delete(
    change_id: str, line_id: str, request: Request, db: Session = Depends(get_db)
):
    user = _change_user(request, db)
    try:
        delete_change_line(db, change_id, line_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/change-control/{change_id}", status_code=303)


@app.post("/change-control/{change_id}/submit")
def change_control_submit(change_id: str, request: Request, db: Session = Depends(get_db)):
    user = _change_user(request, db)
    try:
        submit_change(db, change_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/change-control/{change_id}", status_code=303)


@app.post("/change-control/{change_id}/review")
async def change_control_review(change_id: str, request: Request, db: Session = Depends(get_db)):
    user = _change_user(request, db)
    form = await request.form()
    try:
        review_change(
            db,
            change_id,
            user,
            gate=str(form.get("gate") or ""),
            decision=str(form.get("decision") or ""),
            note=str(form.get("note") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/change-control/{change_id}", status_code=303)


@app.post("/change-control/{change_id}/revisions")
async def change_control_revision_create(
    change_id: str, request: Request, db: Session = Depends(get_db)
):
    user = _change_user(request, db)
    form = await request.form()
    try:
        create_change_revision(db, change_id, user, reason=str(form.get("reason") or ""))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/change-control/{change_id}", status_code=303)


@app.post("/change-control/{change_id}/sync-customer")
def change_control_customer_sync(change_id: str, request: Request, db: Session = Depends(get_db)):
    user = _change_user(request, db)
    try:
        sync_customer_decision(db, change_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/change-control/{change_id}", status_code=303)


@app.post("/change-control/{change_id}/authorize")
async def change_control_authorize(change_id: str, request: Request, db: Session = Depends(get_db)):
    user = _change_user(request, db)
    form = await request.form()
    try:
        authorize_change_work(
            db,
            change_id,
            user,
            starts_at=datetime.fromisoformat(str(form.get("starts_at") or "")),
            ends_at=datetime.fromisoformat(str(form.get("ends_at") or "")),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/change-control/{change_id}", status_code=303)


@app.post("/change-control/{change_id}/complete")
async def change_control_complete(change_id: str, request: Request, db: Session = Depends(get_db)):
    user = _change_user(request, db)
    form = await request.form()
    try:
        complete_change(
            db,
            change_id,
            user,
            evidence_url=str(form.get("evidence_url") or ""),
            note=str(form.get("note") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/change-control/{change_id}", status_code=303)


@app.get("/commercial/contracts/new", response_class=HTMLResponse)
def commercial_contract_new(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "contract-generator"):
        raise HTTPException(403)
    contract_type = request.query_params.get("contract_type", "customer_construction")
    try:
        values = blank_contract_form_values(contract_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
    return templates.TemplateResponse(
        request=request,
        name="contract_generate.html",
        context={
            "user": user,
            "values": values,
            "contract_types": contract_intake_options(),
            "projects": projects,
            "error": None,
            "result": None,
            "source": contract_source_status(),
            "active": "commercial",
        },
    )


@app.post("/commercial/contracts/generate", response_class=HTMLResponse)
async def commercial_contract_generate(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "contract-generator"):
        raise HTTPException(403)
    form = await request.form()
    values = {key: str(value) for key, value in form.items()}
    result = None
    error = None
    try:
        payload = build_contract_intake_payload(values)
        result = generate_contract_package(db, payload, actor=user.email)
    except Exception as exc:
        error = str(exc)
    projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
    return templates.TemplateResponse(
        request=request,
        name="contract_generate.html",
        context={
            "user": user,
            "values": values,
            "contract_types": contract_intake_options(),
            "projects": projects,
            "error": error,
            "result": result,
            "source": contract_source_status(),
            "active": "commercial",
        },
        status_code=400 if error else 200,
    )


_CONTRACT_WORKFLOW_ROLES = {
    "owner",
    "managing-director",
    "platform-admin",
    "sales",
    "finance",
    "project-manager",
    "technical-prep",
    "legal",
}


def _contract_workflow_user(request: Request, db: Session) -> User:
    user = require_session_user(request, db)
    if user.role not in _CONTRACT_WORKFLOW_ROLES:
        raise HTTPException(403, "A szerződés-életciklus belső üzleti felület.")
    return user


def _contract_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value or ""))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Budapest"))
    return parsed.astimezone(timezone.utc)


@app.get("/commercial/contracts/{contract_id}", response_class=HTMLResponse)
def commercial_contract_workflow_page(
    contract_id: str, request: Request, db: Session = Depends(get_db)
):
    user = _contract_workflow_user(request, db)
    try:
        data = contract_workflow_detail(db, contract_id, user=user)
    except KeyError as exc:
        raise HTTPException(404, "A szerződés-életciklus nem található.") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="contract_workflow.html",
        context={"user": user, "data": data, "active": "commercial"},
    )


@app.post("/commercial/contracts/{contract_id}/submit")
def commercial_contract_workflow_submit(
    contract_id: str, request: Request, db: Session = Depends(get_db)
):
    user = _contract_workflow_user(request, db)
    try:
        submit_contract_review(db, contract_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/commercial/contracts/{contract_id}", status_code=303)


@app.post("/commercial/contracts/{contract_id}/review")
async def commercial_contract_workflow_review(
    contract_id: str, request: Request, db: Session = Depends(get_db)
):
    user = _contract_workflow_user(request, db)
    form = await request.form()
    try:
        review_contract(
            db,
            contract_id,
            user,
            gate=str(form.get("gate") or ""),
            decision=str(form.get("decision") or ""),
            note=str(form.get("note") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/commercial/contracts/{contract_id}", status_code=303)


@app.post("/commercial/contracts/{contract_id}/signed")
async def commercial_contract_workflow_signed(
    contract_id: str, request: Request, db: Session = Depends(get_db)
):
    user = _contract_workflow_user(request, db)
    form = await request.form()
    try:
        record_signed_contract(
            db,
            contract_id,
            user,
            file_id=str(form.get("file_id") or ""),
            document_sha256=str(form.get("document_sha256") or ""),
            signed_at=_contract_datetime(form.get("signed_at")),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/commercial/contracts/{contract_id}", status_code=303)


@app.post("/commercial/contracts/{contract_id}/dispatch")
async def commercial_contract_workflow_dispatch(
    contract_id: str, request: Request, db: Session = Depends(get_db)
):
    user = _contract_workflow_user(request, db)
    form = await request.form()
    try:
        record_contract_dispatch(
            db,
            contract_id,
            user,
            postal_sent_at=_contract_datetime(form.get("postal_sent_at")),
            postal_tracking_number=str(form.get("postal_tracking_number") or ""),
            postal_proof_file_id=str(form.get("postal_proof_file_id") or ""),
            electronic_sent_at=_contract_datetime(form.get("electronic_sent_at")),
            electronic_message_id=str(form.get("electronic_message_id") or ""),
            electronic_recipient=str(form.get("electronic_recipient") or ""),
            electronic_attachment_sha256=str(form.get("electronic_attachment_sha256") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/commercial/contracts/{contract_id}", status_code=303)


@app.post("/commercial/contracts/{contract_id}/activate")
def commercial_contract_workflow_activate(
    contract_id: str, request: Request, db: Session = Depends(get_db)
):
    user = _contract_workflow_user(request, db)
    try:
        activate_contract(db, contract_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/commercial/contracts/{contract_id}", status_code=303)


@app.get("/commercial/files/{document_id}")
def commercial_file_download(request: Request, document_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "contract-generator") and user.role not in _CONTRACT_WORKFLOW_ROLES:
        raise HTTPException(403)
    row = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.document_id == document_id,
            WorkspaceDocument.source_system == "contract_generator",
        )
    )
    if not row:
        raise HTTPException(404, "Dokumentum nem található.")
    try:
        path = resolve_contract_artifact(row)
    except FileNotFoundError:
        raise HTTPException(404, "A helyi artifact nem található.")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(
        path, filename=path.name, media_type=row.mime_type or "application/octet-stream"
    )


@app.get("/development-governance", response_class=HTMLResponse)
def development_governance_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="development_governance.html",
        context={"user": user, "rows": list_discoveries(db), "active": "governance"},
    )


@app.post("/development-governance")
def development_governance_create(
    request: Request,
    discovery_id: Annotated[str, Form()],
    requested_capability: Annotated[str, Form()],
    requested_module_key: Annotated[str | None, Form()] = None,
    canonical_module_key: Annotated[str | None, Form()] = None,
    decision: Annotated[str, Form()] = "integrate",
    source_version: Annotated[str | None, Form()] = None,
    searched_terms: Annotated[str, Form()] = "",
    implementation_gap: Annotated[str, Form()] = "",
    exception_reason: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        create_discovery(
            db,
            DevelopmentDiscoveryIn(
                discovery_id=discovery_id,
                requested_capability=requested_capability,
                requested_module_key=requested_module_key or None,
                searched_terms=[x.strip() for x in searched_terms.split(",") if x.strip()],
                candidate_artifacts=[],
                canonical_module_key=canonical_module_key or None,
                canonical_object_owner=None,
                source_version=source_version or None,
                decision=decision,
                implementation_gap=implementation_gap,
                exception_reason=exception_reason or None,
                requested_by=user.email,
            ),
            actor=user.email,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return RedirectResponse("/development-governance", status_code=303)


@app.post("/development-governance/{discovery_id}/review")
async def development_governance_review(
    discovery_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    exception_approved = form.get("exception_approved") is not None
    if exception_approved and user.role != "owner":
        raise HTTPException(403, "Új fejlesztési kivételt csak tulajdonos hagyhat jóvá.")
    try:
        review_discovery(
            db,
            discovery_id,
            DevelopmentDiscoveryReviewIn(
                status=str(form.get("status") or ""),
                reviewed_by=user.email,
                exception_approved=exception_approved,
                review_note=str(form.get("review_note") or ""),
            ),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, "A discovery rekord nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/development-governance#discovery-{discovery_id}", status_code=303)


@app.get("/api/development-discoveries", dependencies=[Depends(require_api_token)])
def api_development_discoveries(db: Session = Depends(get_db)):
    return list_discoveries(db)


@app.post("/api/development-discoveries", dependencies=[Depends(require_api_token)])
def api_development_discovery_create(
    payload: DevelopmentDiscoveryIn, db: Session = Depends(get_db)
):
    try:
        return create_discovery(db, payload, actor="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post(
    "/api/development-discoveries/{discovery_id}/review", dependencies=[Depends(require_api_token)]
)
def api_development_discovery_review(
    discovery_id: str, payload: DevelopmentDiscoveryReviewIn, db: Session = Depends(get_db)
):
    try:
        return review_discovery(db, discovery_id, payload, actor="api")
    except KeyError:
        raise HTTPException(404, "Discovery rekord nem található.")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/commercial/source-status", dependencies=[Depends(require_api_token)])
def api_commercial_source_status():
    return contract_source_status()


@app.post("/api/commercial/contracts/validate", dependencies=[Depends(require_api_token)])
def api_commercial_contract_validate(payload: ContractGenerateIn):
    return validate_contract_payload(payload.payload)


@app.post("/api/commercial/contracts/generate", dependencies=[Depends(require_api_token)])
def api_commercial_contract_generate(payload: ContractGenerateIn, db: Session = Depends(get_db)):
    try:
        return generate_contract_package(db, payload.payload, actor="api")
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post(
    "/api/commercial/contracts/{contract_number}/signed", dependencies=[Depends(require_api_token)]
)
def api_commercial_contract_signed(
    contract_number: str,
    project_id: str,
    evidence_url: str | None = None,
    db: Session = Depends(get_db),
):
    raise HTTPException(
        409,
        "A közvetlen aláírt státusz lezárult. Használja a szerződés-életciklus aláírási, kettős kézbesítési és aktiválási kapuit.",
    )


@app.post("/api/commercial/change-events", dependencies=[Depends(require_api_token)])
def api_commercial_change_event(payload: ChangeControlEventIn, db: Session = Depends(get_db)):
    return ingest_change_control_event(db, payload, actor="api")


@app.get("/modules", response_class=HTMLResponse)
def modules_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    modules = db.scalars(
        select(ModuleRegistry).order_by(ModuleRegistry.criticality.desc(), ModuleRegistry.name)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="modules.html",
        context={"user": user, "modules": modules, "active": "modules"},
    )


def _business_optional_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, "A határidő formátuma érvénytelen.") from exc


def _business_decimal(value: str | None) -> Decimal:
    try:
        return Decimal(value or "0")
    except Exception as exc:
        raise HTTPException(400, "Az összeg formátuma érvénytelen.") from exc


@app.get("/workbench/{module_key}", response_class=HTMLResponse)
def module_workbench_page(
    request: Request,
    module_key: str,
    include_archived: bool = False,
    db: Session = Depends(get_db),
):
    if module_key == "imperial-care":
        return RedirectResponse("/imperial-care", status_code=303)
    user, redirect = module_auth_or_redirect(request, db, module_key)
    if redirect:
        return redirect
    try:
        profile = module_profile(module_key)
        records = list_module_records(db, module_key, include_archived=include_archived)
        source_projection = module_source_projection(module_key)
        canonical_records = db.scalars(
            select(EnterpriseCanonicalRecord)
            .where(EnterpriseCanonicalRecord.target_module == module_key)
            .order_by(desc(EnterpriseCanonicalRecord.updated_at))
            .limit(100)
        ).all()
        canonical_total = (
            db.scalar(
                select(func.count(EnterpriseCanonicalRecord.id)).where(
                    EnterpriseCanonicalRecord.target_module == module_key
                )
            )
            or 0
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="module_workbench.html",
        context={
            "user": user,
            "profile": profile,
            "records": records,
            "source_projection": source_projection,
            "canonical_records": canonical_records,
            "canonical_total": canonical_total,
            "include_archived": include_archived,
            "active": "module-workbench",
        },
    )


@app.get("/workbench/{module_key}/canonical/{record_id}", response_class=HTMLResponse)
def module_canonical_record_page(
    request: Request,
    module_key: str,
    record_id: str,
    db: Session = Depends(get_db),
):
    user, redirect = module_auth_or_redirect(request, db, module_key)
    if redirect:
        return redirect
    row = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.record_id == record_id,
            EnterpriseCanonicalRecord.target_module == module_key,
        )
    )
    if row is None:
        raise HTTPException(404, "A migrált vállalati rekord nem található ebben a modulban.")
    return templates.TemplateResponse(
        request=request,
        name="canonical_record.html",
        context={
            "user": user,
            "row": row,
            "data": _json_value(row.data_json, {}),
            "provenance": _json_value(row.provenance_json, {}),
            "active": "module-workbench",
        },
    )


@app.post("/workbench/{module_key}/records")
async def module_record_create_ui(
    request: Request,
    module_key: str,
    db: Session = Depends(get_db),
):
    user, redirect = module_auth_or_redirect(request, db, module_key)
    if redirect:
        return redirect
    try:
        profile = module_profile(module_key)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    form = await request.form()
    domain_data = {
        field["key"]: str(form.get(f"data_{field['key']}") or "").strip()
        for field in profile["fields"]
        if str(form.get(f"data_{field['key']}") or "").strip()
    }
    payload = ModuleBusinessRecordIn(
        record_type=str(form.get("record_type") or profile["entity_label"]),
        title=str(form.get("title") or ""),
        description=str(form.get("description") or "") or None,
        status=str(form.get("status") or profile["initial_status"]),
        project_id=str(form.get("project_id") or "") or None,
        customer_reference=str(form.get("customer_reference") or "") or None,
        assignee=str(form.get("assignee") or "") or None,
        priority=str(form.get("priority") or "normal"),
        due_at=_business_optional_datetime(str(form.get("due_at") or "") or None),
        amount_huf=_business_decimal(str(form.get("amount_huf") or "0")),
        data=domain_data,
    )
    try:
        record = create_module_record(db, module_key, payload, actor=user.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/workbench/{module_key}/records/{record.record_id}", status_code=303)


@app.get("/workbench/{module_key}/records/{record_id}", response_class=HTMLResponse)
def module_record_page(
    request: Request,
    module_key: str,
    record_id: str,
    db: Session = Depends(get_db),
):
    user, redirect = module_auth_or_redirect(request, db, module_key)
    if redirect:
        return redirect
    try:
        profile = module_profile(module_key)
        record = get_module_record(db, module_key, record_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="module_record.html",
        context={
            "user": user,
            "profile": profile,
            "record": record,
            "record_data": json.loads(record.data_json or "{}"),
            "active": "module-workbench",
        },
    )


@app.post("/workbench/{module_key}/records/{record_id}")
async def module_record_update_ui(
    request: Request,
    module_key: str,
    record_id: str,
    db: Session = Depends(get_db),
):
    user, redirect = module_auth_or_redirect(request, db, module_key)
    if redirect:
        return redirect
    try:
        profile = module_profile(module_key)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    form = await request.form()
    domain_data = {
        field["key"]: str(form.get(f"data_{field['key']}") or "").strip()
        for field in profile["fields"]
        if str(form.get(f"data_{field['key']}") or "").strip()
    }
    payload = ModuleBusinessRecordUpdateIn(
        title=str(form.get("title") or ""),
        description=str(form.get("description") or "") or None,
        status=None,
        project_id=str(form.get("project_id") or "") or None,
        customer_reference=str(form.get("customer_reference") or "") or None,
        assignee=str(form.get("assignee") or "") or None,
        priority=str(form.get("priority") or "normal"),
        due_at=_business_optional_datetime(str(form.get("due_at") or "") or None),
        amount_huf=_business_decimal(str(form.get("amount_huf") or "0")),
        data=domain_data,
        archived=str(form.get("archived") or "") == "true",
    )
    try:
        update_module_record(db, module_key, record_id, payload, actor=user.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/workbench/{module_key}/records/{record_id}", status_code=303)


@app.post("/workbench/{module_key}/records/{record_id}/comments")
def module_record_comment_ui(
    request: Request,
    module_key: str,
    record_id: str,
    body: Annotated[str, Form(min_length=1, max_length=5000)],
    db: Session = Depends(get_db),
):
    user, redirect = module_auth_or_redirect(request, db, module_key)
    if redirect:
        return redirect
    try:
        add_module_comment(db, module_key, record_id, body, actor=user.email)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return RedirectResponse(
        f"/workbench/{module_key}/records/{record_id}#communication", status_code=303
    )


@app.post("/workbench/{module_key}/records/{record_id}/approvals")
def module_record_approval_ui(
    request: Request,
    module_key: str,
    record_id: str,
    stage: Annotated[str, Form(min_length=2, max_length=100)],
    decision: Annotated[str, Form(pattern="^(pending|approved|rejected)$")],
    note: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = module_auth_or_redirect(request, db, module_key)
    if redirect:
        return redirect
    try:
        add_module_approval(
            db, module_key, record_id, stage=stage, decision=decision, note=note, actor=user.email
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(
        f"/workbench/{module_key}/records/{record_id}#approvals", status_code=303
    )


@app.post("/workbench/{module_key}/records/{record_id}/actions/{action_id}")
def module_record_transition_ui(
    request: Request,
    module_key: str,
    record_id: str,
    action_id: str,
    note: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = module_auth_or_redirect(request, db, module_key)
    if redirect:
        return redirect
    try:
        transition_module_record(db, module_key, record_id, action_id, actor=user.email, note=note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/workbench/{module_key}/records/{record_id}", status_code=303)


@app.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    projects = db.scalars(select(ProjectRegistry).order_by(desc(ProjectRegistry.updated_at))).all()
    return templates.TemplateResponse(
        request=request,
        name="projects.html",
        context={"user": user, "projects": projects, "active": "projects"},
    )


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_page(request: Request, project_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if not project:
        raise HTTPException(404, "Projekt nem található.")
    data = project_360(db, project_id)
    return templates.TemplateResponse(
        request=request,
        name="project_360.html",
        context={"user": user, **data, "active": "projects"},
    )


@app.get("/exceptions", response_class=HTMLResponse)
def exceptions_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    events = db.scalars(
        select(EventRecord)
        .where(EventRecord.status == "open", EventRecord.executive_relevance.is_(True))
        .order_by(desc(EventRecord.received_at))
    ).all()
    issues = db.scalars(
        select(ConsistencyIssue)
        .where(ConsistencyIssue.status == "open")
        .order_by(desc(ConsistencyIssue.last_detected_at))
    ).all()
    tasks = db.scalars(
        select(TaskRecord)
        .where(TaskRecord.status == "open", TaskRecord.executive_relevance.is_(True))
        .order_by(TaskRecord.due_at)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="exceptions.html",
        context={
            "user": user,
            "events": events,
            "issues": issues,
            "tasks": tasks,
            "active": "exceptions",
        },
    )


@app.post("/exceptions/events/{event_id}/resolve")
async def exceptions_event_resolve(event_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        resolve_executive_event(
            db,
            event_id,
            resolution_note=str(form.get("resolution_note") or ""),
            close_related_tasks=form.get("close_related_tasks") is not None,
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, "A vezetői esemény nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/exceptions", status_code=303)


@app.post("/exceptions/issues/{fingerprint}/assign")
async def exceptions_issue_assign(
    fingerprint: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        assign_consistency_issue(
            db,
            fingerprint,
            responsible=str(form.get("responsible") or ""),
            assignment_note=str(form.get("assignment_note") or ""),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, "Az adateltérés nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/exceptions", status_code=303)


@app.post("/exceptions/issues/{fingerprint}/recheck")
def exceptions_issue_recheck(fingerprint: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    issue = db.scalar(select(ConsistencyIssue).where(ConsistencyIssue.fingerprint == fingerprint))
    if not issue:
        raise HTTPException(404, "Az adateltérés nem található.")
    scan_consistency(db, project_id=issue.project_id, actor=user.email)
    return RedirectResponse("/exceptions", status_code=303)


@app.post("/exceptions/tasks/{task_id}/update")
async def exceptions_task_update(task_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        update_task(
            db,
            task_id,
            TaskUpdateIn(
                status=str(form.get("status") or "") or None,
                assignee=str(form.get("assignee") or "") or None,
            ),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, "A vezetői feladat nem található.") from exc
    return RedirectResponse("/exceptions", status_code=303)


@app.get("/releases", response_class=HTMLResponse)
def releases_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    releases = db.scalars(
        select(ReleaseRecord)
        .options(selectinload(ReleaseRecord.artifacts))
        .order_by(desc(ReleaseRecord.created_at))
    ).all()
    environments = db.scalars(select(EnvironmentRecord).order_by(EnvironmentRecord.id)).all()
    deployments = db.scalars(select(DeploymentRecord).order_by(desc(DeploymentRecord.id))).all()
    return templates.TemplateResponse(
        request=request,
        name="releases.html",
        context={
            "user": user,
            "releases": releases,
            "environments": environments,
            "deployments": deployments,
            "active": "releases",
        },
    )


@app.get("/pilots", response_class=HTMLResponse)
def pilots_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    pilots = db.scalars(select(PilotRun).order_by(desc(PilotRun.started_at))).all()
    return templates.TemplateResponse(
        request=request,
        name="pilots.html",
        context={"user": user, "pilots": pilots, "active": "pilots"},
    )


@app.post("/pilots/run")
def run_pilots_ui(
    request: Request, scenario: Annotated[str, Form()], db: Session = Depends(get_db)
):
    user = current_user(request, db)
    if not user or user.role not in _LEADERSHIP_ROLES:
        raise HTTPException(403)
    if scenario == "all":
        run_all_pilots(db)
    else:
        run_pilot_scenario(db, scenario)
    return RedirectResponse("/pilots", status_code=303)


@app.post("/api/events", dependencies=[Depends(require_api_token)])
def api_ingest_event(data: EventIn, db: Session = Depends(get_db)):
    event, created = ingest_event(db, data)
    return {
        "created": created,
        "event_id": event.event_id,
        "status": event.status,
        "severity": event.severity,
    }


@app.post("/api/heartbeats", dependencies=[Depends(require_api_token)])
def api_heartbeat(data: HeartbeatIn, db: Session = Depends(get_db)):
    module = register_heartbeat(db, data)
    return {
        "module_key": module.module_key,
        "integration_status": module.integration_status,
        "last_heartbeat_at": module.last_heartbeat_at,
    }


@app.post("/api/facts", dependencies=[Depends(require_api_token)])
def api_fact(data: FactIn, db: Session = Depends(get_db)):
    fact = upsert_fact(db, data)
    return {"id": fact.id, "project_id": fact.project_id, "fact_key": fact.fact_key}


@app.post("/api/consistency/scan", dependencies=[Depends(require_internal_job_token)])
def api_consistency_scan(project_id: str | None = None, db: Session = Depends(get_db)):
    return scan_consistency(db, project_id=project_id)


@app.post("/api/outbox/process", dependencies=[Depends(require_internal_job_token)])
def api_outbox_process(db: Session = Depends(get_db)):
    return process_outbox(db)


@app.post("/api/releases", dependencies=[Depends(require_api_token)])
def api_release(data: ReleaseIn, db: Session = Depends(get_db)):
    row = create_release(db, data)
    return {"release_id": row.release_id, "status": row.status}


@app.post("/api/releases/{release_id}/artifacts", dependencies=[Depends(require_api_token)])
def api_artifact(release_id: str, data: ArtifactIn, db: Session = Depends(get_db)):
    try:
        row = add_artifact(db, release_id, data)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"artifact_id": row.artifact_id, "cloud_status": row.cloud_status}


@app.get("/api/releases/{release_id}/gate", dependencies=[Depends(require_api_token)])
def api_release_gate(release_id: str, db: Session = Depends(get_db)):
    try:
        return release_gate(db, release_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/dashboard", dependencies=[Depends(require_api_token)])
def api_dashboard(db: Session = Depends(get_db)):
    return dashboard_metrics(db)


@app.get("/api/modules", dependencies=[Depends(require_api_token)])
def api_modules(db: Session = Depends(get_db)):
    modules = db.scalars(select(ModuleRegistry).order_by(ModuleRegistry.name)).all()
    return [
        {
            "module_key": m.module_key,
            "name": m.name,
            "version": m.version,
            "lifecycle_status": m.lifecycle_status,
            "integration_status": m.integration_status,
            "last_heartbeat_at": m.last_heartbeat_at,
        }
        for m in modules
    ]


@app.get("/api/modules/{module_key}/business-profile", dependencies=[Depends(require_api_token)])
def api_module_business_profile(module_key: str):
    try:
        return module_profile(module_key)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/modules/{module_key}/records", dependencies=[Depends(require_api_token)])
def api_module_records(
    module_key: str,
    include_archived: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return [
            serialize_module_record(record)
            for record in list_module_records(db, module_key, include_archived=include_archived)
        ]
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/modules/{module_key}/records", dependencies=[Depends(require_api_token)])
def api_module_record_create(
    module_key: str,
    payload: ModuleBusinessRecordIn,
    db: Session = Depends(get_db),
):
    try:
        record = create_module_record(db, module_key, payload, actor="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return serialize_module_record(record, include_threads=True)


@app.get(
    "/api/modules/{module_key}/records/{record_id}",
    dependencies=[Depends(require_api_token)],
)
def api_module_record(module_key: str, record_id: str, db: Session = Depends(get_db)):
    try:
        record = get_module_record(db, module_key, record_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return serialize_module_record(record, include_threads=True)


@app.patch(
    "/api/modules/{module_key}/records/{record_id}",
    dependencies=[Depends(require_api_token)],
)
def api_module_record_update(
    module_key: str,
    record_id: str,
    payload: ModuleBusinessRecordUpdateIn,
    db: Session = Depends(get_db),
):
    try:
        record = update_module_record(db, module_key, record_id, payload, actor="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return serialize_module_record(record, include_threads=True)


@app.post(
    "/api/modules/{module_key}/records/{record_id}/comments",
    dependencies=[Depends(require_api_token)],
)
def api_module_record_comment(
    module_key: str,
    record_id: str,
    payload: ModuleBusinessCommentIn,
    db: Session = Depends(get_db),
):
    try:
        add_module_comment(db, module_key, record_id, payload.body, actor="api")
        record = get_module_record(db, module_key, record_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return serialize_module_record(record, include_threads=True)


@app.post(
    "/api/modules/{module_key}/records/{record_id}/approvals",
    dependencies=[Depends(require_api_token)],
)
def api_module_record_approval(
    module_key: str,
    record_id: str,
    payload: ModuleBusinessApprovalIn,
    db: Session = Depends(get_db),
):
    try:
        add_module_approval(
            db,
            module_key,
            record_id,
            stage=payload.stage,
            decision=payload.decision,
            note=payload.note,
            actor="api",
        )
        record = get_module_record(db, module_key, record_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return serialize_module_record(record, include_threads=True)


@app.post(
    "/api/modules/{module_key}/records/{record_id}/transitions",
    dependencies=[Depends(require_api_token)],
)
def api_module_record_transition(
    module_key: str,
    record_id: str,
    payload: ModuleBusinessTransitionIn,
    db: Session = Depends(get_db),
):
    try:
        record = transition_module_record(
            db,
            module_key,
            record_id,
            payload.action_id,
            actor="api",
            project_id=payload.project_id,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return serialize_module_record(record, include_threads=True)


@app.get("/api/projects/{project_id}", dependencies=[Depends(require_api_token)])
def api_project(project_id: str, db: Session = Depends(get_db)):
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if not project:
        raise HTTPException(404)
    events = db.scalars(
        select(EventRecord)
        .where(EventRecord.project_id == project_id)
        .order_by(desc(EventRecord.occurred_at))
    ).all()
    issues = db.scalars(
        select(ConsistencyIssue).where(
            ConsistencyIssue.project_id == project_id, ConsistencyIssue.status == "open"
        )
    ).all()
    return {
        "project": {
            "project_id": project.project_id,
            "name": project.name,
            "status": project.status,
            "risk_level": project.risk_level,
            "blocked": project.blocked,
            "financial_impact_huf": str(project.financial_impact_huf),
            "deadline_impact_days": project.deadline_impact_days,
            "next_action": project.next_action,
        },
        "events": [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "severity": e.severity,
                "status": e.status,
                "financial_impact_huf": str(e.financial_impact_huf),
            }
            for e in events
        ],
        "open_consistency_issues": [
            {"rule_code": i.rule_code, "title": i.title, "severity": i.severity} for i in issues
        ],
    }


@app.post("/api/pilots/run", dependencies=[Depends(require_internal_job_token)])
def api_pilots_run(scenario: str = "all", db: Session = Depends(get_db)):
    pilots = run_all_pilots(db) if scenario == "all" else [run_pilot_scenario(db, scenario)]
    return [
        {
            "pilot_id": p.pilot_id,
            "project_id": p.project_id,
            "scenario": p.scenario,
            "status": p.status,
            "steps_passed": p.steps_passed,
            "steps_total": p.steps_total,
        }
        for p in pilots
    ]


def _json_value(value: str | None, fallback):
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return fallback


@app.get("/imports", response_class=HTMLResponse)
def imports_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    metrics = import_metrics(db)
    sources = db.scalars(select(ImportDataSource).order_by(ImportDataSource.name)).all()
    jobs = db.scalars(select(ImportJob).order_by(desc(ImportJob.created_at)).limit(30)).all()
    batches = db.scalars(
        select(ImportCommitBatch).order_by(desc(ImportCommitBatch.created_at)).limit(15)
    ).all()
    canonical = db.scalars(
        select(EnterpriseCanonicalRecord)
        .order_by(desc(EnterpriseCanonicalRecord.updated_at))
        .limit(20)
    ).all()
    canonical_by_domain: dict[str, int] = {
        domain: count
        for domain, count in db.execute(
            select(
                EnterpriseCanonicalRecord.domain, func.count(EnterpriseCanonicalRecord.id)
            ).group_by(EnterpriseCanonicalRecord.domain)
        ).all()
    }
    delivery_by_target_status = [
        {"target": target, "status": status, "count": count}
        for target, status, count in db.execute(
            select(
                CanonicalDeliveryRecord.target_system,
                CanonicalDeliveryRecord.status,
                func.count(CanonicalDeliveryRecord.id),
            ).group_by(CanonicalDeliveryRecord.target_system, CanonicalDeliveryRecord.status)
        ).all()
    ]
    latest_reconciliation = db.scalar(
        select(CanonicalReconciliationRun)
        .order_by(desc(CanonicalReconciliationRun.started_at))
        .limit(1)
    )
    integrity = canonical_integrity_report(db)
    return templates.TemplateResponse(
        request=request,
        name="imports.html",
        context={
            "user": user,
            "active": "imports",
            "metrics": metrics,
            "sources": sources,
            "jobs": jobs,
            "batches": batches,
            "canonical": canonical,
            "canonical_by_domain": canonical_by_domain,
            "delivery_by_target_status": delivery_by_target_status,
            "latest_reconciliation": latest_reconciliation,
            "integrity": integrity,
        },
    )


@app.post("/imports/crm-sync")
def sync_crm_canonical_ui(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.role not in _LEADERSHIP_ROLES:
        raise HTTPException(403, "A kanonikus adatszinkron vezetői jogosultságot igényel.")
    try:
        result = sync_crm_canonical(db, actor=user.email)
    except CrmCanonicalSyncError as exc:
        raise HTTPException(502, str(exc)) from exc
    audit(
        db,
        actor=user.email,
        action="crm_canonical_sync",
        entity_type="import_job",
        entity_id=result["job_id"],
        after=result,
    )
    db.commit()
    return RedirectResponse(f"/imports/{result['job_id']}", status_code=303)


def _canonical_sync_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(401, "A kanonikus rendszerszinkronhoz bejelentkezés szükséges.")
    if user.role not in _LEADERSHIP_ROLES:
        raise HTTPException(403, "A kanonikus rendszerszinkron vezetői jogosultságot igényel.")
    return user


def _enforce_canonical_result(result: dict[str, Any]) -> None:
    if int(result.get("failed") or 0) > 0:
        raise HTTPException(
            502,
            "A kanonikus rendszerszinkron egy vagy több kézbesítése sikertelen.",
        )
    if int(result.get("conflicts") or 0) > 0 or int(result.get("rejected") or 0) > 0:
        raise HTTPException(
            409,
            "A kanonikus rendszerszinkron konfliktust vagy elutasított rekordot talált.",
        )
    status = result.get("status")
    if status is not None and status != "passed":
        raise HTTPException(
            409,
            "A kanonikus egyeztetés nem igazolta a két rendszer azonosságát.",
        )


@app.post("/imports/canonical/pull-itep")
def pull_itep_canonical_ui(request: Request, db: Session = Depends(get_db)):
    user = _canonical_sync_user(request, db)
    try:
        result = pull_itep_tasks_to_platform(db)
    except CanonicalBridgeError as exc:
        raise HTTPException(502, str(exc)) from exc
    audit(
        db,
        actor=user.email,
        action="canonical_pull_itep",
        entity_type="canonical_record",
        entity_id="itep-tasks",
        after=result,
    )
    db.commit()
    _enforce_canonical_result(result)
    return RedirectResponse("/imports", status_code=303)


@app.post("/imports/canonical/push-itep")
def push_itep_canonical_ui(request: Request, db: Session = Depends(get_db)):
    user = _canonical_sync_user(request, db)
    result = push_platform_events_to_itep(db)
    audit(
        db,
        actor=user.email,
        action="canonical_push_itep",
        entity_type="event_delivery",
        entity_id="itep",
        after=result,
    )
    db.commit()
    _enforce_canonical_result(result)
    return RedirectResponse("/imports", status_code=303)


@app.post("/imports/canonical/push-crm")
def push_crm_canonical_ui(request: Request, db: Session = Depends(get_db)):
    user = _canonical_sync_user(request, db)
    try:
        result = push_canonical_to_crm(db)
    except CanonicalBridgeError as exc:
        raise HTTPException(502, str(exc)) from exc
    audit(
        db,
        actor=user.email,
        action="canonical_push_crm",
        entity_type="canonical_delivery",
        entity_id="crm",
        after=result,
    )
    db.commit()
    _enforce_canonical_result(result)
    return RedirectResponse("/imports", status_code=303)


@app.post("/imports/canonical/reconcile-crm")
def reconcile_crm_canonical_ui(request: Request, db: Session = Depends(get_db)):
    user = _canonical_sync_user(request, db)
    try:
        result = reconcile_canonical_with_crm(db)
    except CanonicalBridgeError as exc:
        raise HTTPException(502, str(exc)) from exc
    audit(
        db,
        actor=user.email,
        action="canonical_reconcile_crm",
        entity_type="canonical_reconciliation",
        entity_id=result["run_id"],
        after=result,
    )
    db.commit()
    _enforce_canonical_result(result)
    return RedirectResponse("/imports", status_code=303)


@app.get("/imports/{job_id}", response_class=HTMLResponse)
def import_job_page(request: Request, job_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    job = db.scalar(select(ImportJob).where(ImportJob.job_id == job_id))
    if not job:
        raise HTTPException(404, "Importfutás nem található.")
    items = db.scalars(
        select(ImportItem).where(ImportItem.job_id == job_id).order_by(ImportItem.received_at)
    ).all()
    staged = db.scalars(
        select(StagedEnterpriseRecord)
        .where(StagedEnterpriseRecord.job_id == job_id)
        .order_by(StagedEnterpriseRecord.domain, StagedEnterpriseRecord.canonical_name)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="import_job.html",
        context={
            "user": user,
            "active": "imports",
            "job": job,
            "items": items,
            "staged": staged,
            "loads": _json_value,
            "job_summary": _json_value(job.summary_json, {}),
        },
    )


@app.post("/imports/jobs")
def create_import_job_ui(
    request: Request,
    source_key: Annotated[str, Form()],
    name: Annotated[str, Form()],
    domain_hint: Annotated[str, Form()] = "enterprise",
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        job = create_job(
            db,
            ImportJobIn(
                source_key=source_key, name=name, domain_hint=domain_hint, requested_by=user.email
            ),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(
        db,
        actor=user.email,
        action="import_job_created",
        entity_type="import_job",
        entity_id=job.job_id,
    )
    db.commit()
    return RedirectResponse(f"/imports/{job.job_id}", status_code=303)


@app.post("/imports/{job_id}/upload")
async def upload_import_file_ui(
    request: Request,
    job_id: str,
    file: UploadFile = File(...),
    domain_hint: Annotated[str, Form()] = "enterprise",
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    raw = await file.read()
    try:
        content = parse_upload(file.filename or "feltoltes", raw)
        item = add_item(
            db,
            job_id,
            ImportItemIn(
                file_name=file.filename,
                mime_type=file.content_type,
                domain_hint=domain_hint,
                sha256=(content.get("metadata") or {}).get("sha256"),
                content=content,
            ),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(
        db,
        actor=user.email,
        action="import_file_uploaded",
        entity_type="import_item",
        entity_id=item.item_id,
    )
    db.commit()
    return RedirectResponse(f"/imports/{job_id}", status_code=303)


@app.post("/imports/{job_id}/process")
def process_import_job_ui(request: Request, job_id: str, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        process_job(db, job_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(
        db,
        actor=user.email,
        action="import_job_processed",
        entity_type="import_job",
        entity_id=job_id,
    )
    db.commit()
    return RedirectResponse(f"/imports/{job_id}", status_code=303)


@app.post("/imports/{job_id}/review/{staged_id}")
def review_import_record_ui(
    request: Request,
    job_id: str,
    staged_id: str,
    review_status: Annotated[str, Form()],
    canonical_name: Annotated[str | None, Form()] = None,
    project_id: Annotated[str | None, Form()] = None,
    target_module: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        review_record(
            db,
            staged_id,
            ImportReviewIn(
                review_status=review_status,
                canonical_name=canonical_name or None,
                project_id=project_id or None,
                target_module=target_module or None,
            ),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(
        db,
        actor=user.email,
        action="import_record_reviewed",
        entity_type="staged_record",
        entity_id=staged_id,
    )
    db.commit()
    return RedirectResponse(f"/imports/{job_id}", status_code=303)


@app.post("/imports/{job_id}/commit")
def commit_import_job_ui(
    request: Request,
    job_id: str,
    auto_approve_high_confidence: Annotated[bool, Form()] = False,
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user or user.role not in _LEADERSHIP_ROLES:
        raise HTTPException(403)
    try:
        batch = commit_records(
            db, job_id, [], user.email, auto_approve_high_confidence=auto_approve_high_confidence
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(
        db,
        actor=user.email,
        action="import_committed",
        entity_type="import_batch",
        entity_id=batch.batch_id,
    )
    db.commit()
    return RedirectResponse(f"/imports/{job_id}", status_code=303)


@app.post("/imports/batches/{batch_id}/rollback")
def rollback_import_batch_ui(request: Request, batch_id: str, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role not in _LEADERSHIP_ROLES:
        raise HTTPException(403)
    try:
        batch = rollback_batch(db, batch_id, user.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(
        db,
        actor=user.email,
        action="import_rolled_back",
        entity_type="import_batch",
        entity_id=batch.batch_id,
    )
    db.commit()
    return RedirectResponse("/imports", status_code=303)


@app.get("/experience", response_class=HTMLResponse)
def experience_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    sources = db.scalars(
        select(CalculationSourceRegistry).order_by(CalculationSourceRegistry.priority)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="experience.html",
        context={
            "user": user,
            "active": "experience",
            "catalog": pricing_repository.brand_catalog(),
            "house_count": len(public_catalog(db)),
            "sources": sources,
        },
    )


@app.get("/api/imports/metrics", dependencies=[Depends(require_api_token)])
def api_import_metrics(db: Session = Depends(get_db)):
    return import_metrics(db)


@app.post("/api/imports/crm-sync", dependencies=[Depends(require_internal_job_token)])
def api_crm_canonical_sync(db: Session = Depends(get_db)):
    try:
        result = sync_crm_canonical(db, actor="internal-job")
    except CrmCanonicalSyncError as exc:
        raise HTTPException(502, str(exc)) from exc
    audit(
        db,
        actor="internal-job",
        action="crm_canonical_sync",
        entity_type="import_job",
        entity_id=result["job_id"],
        after=result,
    )
    db.commit()
    return result


@app.post(
    "/api/integrations/canonical/push-crm", dependencies=[Depends(require_internal_job_token)]
)
def api_push_canonical_to_crm(db: Session = Depends(get_db)):
    try:
        result = push_canonical_to_crm(db)
    except CanonicalBridgeError as exc:
        raise HTTPException(502, str(exc)) from exc
    audit(
        db,
        actor="internal-job",
        action="canonical_push_crm",
        entity_type="canonical_delivery",
        entity_id="crm",
        after=result,
    )
    db.commit()
    _enforce_canonical_result(result)
    return result


@app.post(
    "/api/integrations/canonical/pull-itep", dependencies=[Depends(require_internal_job_token)]
)
def api_pull_itep_tasks_to_platform(db: Session = Depends(get_db)):
    try:
        result = pull_itep_tasks_to_platform(db)
    except CanonicalBridgeError as exc:
        raise HTTPException(502, str(exc)) from exc
    audit(
        db,
        actor="internal-job",
        action="canonical_pull_itep",
        entity_type="canonical_record",
        entity_id="itep-tasks",
        after=result,
    )
    db.commit()
    _enforce_canonical_result(result)
    return result


@app.post(
    "/api/integrations/canonical/push-itep", dependencies=[Depends(require_internal_job_token)]
)
def api_push_platform_events_to_itep(db: Session = Depends(get_db)):
    result = push_platform_events_to_itep(db)
    audit(
        db,
        actor="internal-job",
        action="canonical_push_itep",
        entity_type="event_delivery",
        entity_id="itep",
        after=result,
    )
    db.commit()
    _enforce_canonical_result(result)
    return result


@app.post(
    "/api/integrations/canonical/reconcile-crm", dependencies=[Depends(require_internal_job_token)]
)
def api_reconcile_canonical_with_crm(db: Session = Depends(get_db)):
    try:
        result = reconcile_canonical_with_crm(db)
    except CanonicalBridgeError as exc:
        raise HTTPException(502, str(exc)) from exc
    audit(
        db,
        actor="internal-job",
        action="canonical_reconcile_crm",
        entity_type="canonical_reconciliation",
        entity_id=result["run_id"],
        after=result,
    )
    db.commit()
    _enforce_canonical_result(result)
    return result


@app.get(
    "/api/integrations/canonical/integrity",
    dependencies=[Depends(require_internal_job_token)],
)
def api_canonical_integrity(db: Session = Depends(get_db)):
    return canonical_integrity_report(db)


def _dpm_project_payload(project: ProjectRegistry) -> dict[str, object]:
    customer_ref = (project.customer_name or "").strip() or None
    return {
        "id": project.project_id,
        "name": project.name,
        "customerId": customer_ref,
        "customerName": customer_ref,
        "projectType": project.project_type,
        "status": project.status,
        "riskLevel": project.risk_level,
        "blocked": project.blocked,
        "responsible": project.responsible,
        "nextAction": project.next_action,
        "updatedAt": project.updated_at.isoformat() if project.updated_at else None,
    }


@app.get(
    "/api/integrations/dpm/projects",
    dependencies=[Depends(require_internal_job_token)],
)
def api_dpm_projects(limit: int = 500, db: Session = Depends(get_db)):
    safe_limit = max(1, min(limit, 1000))
    rows = db.scalars(
        select(ProjectRegistry).order_by(ProjectRegistry.updated_at.desc()).limit(safe_limit)
    ).all()
    return {"projects": [_dpm_project_payload(row) for row in rows]}


@app.get(
    "/api/integrations/dpm/projects/{project_id}",
    dependencies=[Depends(require_internal_job_token)],
)
def api_dpm_project(project_id: str, db: Session = Depends(get_db)):
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if project is None:
        raise HTTPException(404, "Kanonikus projekt nem talalhato.")
    customer_ref = (project.customer_name or "").strip() or None
    customer = (
        {"id": customer_ref, "name": customer_ref, "source": "project_registry"}
        if customer_ref
        else None
    )
    return {"project": _dpm_project_payload(project), "customer": customer}


@app.get(
    "/api/integrations/dpm/users/{user_ref}",
    dependencies=[Depends(require_internal_job_token)],
)
def api_dpm_user(user_ref: str, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == user_ref))
    if user is None or not user.active:
        raise HTTPException(404, "Aktiv kanonikus felhasznalo nem talalhato.")
    return {"id": user.email, "email": user.email, "name": user.name, "role": user.role}


@app.post("/api/imports/sources", dependencies=[Depends(require_api_token)])
def api_import_source(data: ImportSourceIn, db: Session = Depends(get_db)):
    return {"source_key": create_source(db, data).source_key}


@app.post("/api/imports/jobs", dependencies=[Depends(require_api_token)])
def api_import_job(data: ImportJobIn, db: Session = Depends(get_db)):
    try:
        row = create_job(db, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"job_id": row.job_id, "status": row.status}


@app.post("/api/imports/jobs/{job_id}/items", dependencies=[Depends(require_api_token)])
def api_import_item(job_id: str, data: ImportItemIn, db: Session = Depends(get_db)):
    try:
        row = add_item(db, job_id, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"item_id": row.item_id, "status": row.status}


@app.post("/api/imports/push", dependencies=[Depends(require_api_token)])
def api_import_push(data: ImportPushIn, db: Session = Depends(get_db)):
    try:
        job = create_job(
            db,
            ImportJobIn(
                source_key=data.source_key,
                name=f"Connector push – {data.file_name or data.external_id or 'adatcsomag'}",
                domain_hint=data.domain_hint or "enterprise",
                requested_by="connector",
            ),
        )
        item = add_item(
            db,
            job.job_id,
            ImportItemIn(
                external_id=data.external_id,
                file_name=data.file_name,
                mime_type=data.mime_type,
                source_url=data.source_url,
                domain_hint=data.domain_hint,
                content={"records": data.records, "text": data.text, "metadata": data.metadata},
            ),
        )
        process_job(db, job.job_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "job_id": job.job_id,
        "item_id": item.item_id,
        "status": job.status,
        "records_extracted": job.records_extracted,
    }


@app.post("/api/imports/jobs/{job_id}/process", dependencies=[Depends(require_api_token)])
def api_process_import(job_id: str, db: Session = Depends(get_db)):
    try:
        row = process_job(db, job_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"job_id": row.job_id, "status": row.status, "records_extracted": row.records_extracted}


@app.post("/api/imports/staged/{staged_id}/review", dependencies=[Depends(require_api_token)])
def api_review_import(staged_id: str, data: ImportReviewIn, db: Session = Depends(get_db)):
    try:
        row = review_record(db, staged_id, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"staged_id": row.staged_id, "review_status": row.review_status}


@app.post("/api/imports/jobs/{job_id}/commit", dependencies=[Depends(require_api_token)])
def api_commit_import(job_id: str, data: ImportCommitIn, db: Session = Depends(get_db)):
    try:
        batch = commit_records(
            db, job_id, data.staged_ids, data.actor, data.auto_approve_high_confidence
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "batch_id": batch.batch_id,
        "committed_count": batch.committed_count,
        "status": batch.status,
    }


@app.post("/api/imports/batches/{batch_id}/rollback", dependencies=[Depends(require_api_token)])
def api_rollback_import(batch_id: str, db: Session = Depends(get_db)):
    try:
        batch = rollback_batch(db, batch_id, "api")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "batch_id": batch.batch_id,
        "rollback_count": batch.rollback_count,
        "status": batch.status,
    }


@app.get("/api/calculators/catalog")
def api_calculator_catalog():
    return pricing_repository.brand_catalog()


@app.post("/api/calculators/new-build")
def api_new_build_calculation(data: CalculationRequest):
    try:
        return pricing_repository.calculate_new_build(
            brand=data.brand,
            technology=data.technology,
            completion_level=data.completion_level,
            package=data.package,
            gross_area_m2=data.gross_area_m2,
            vat_rate=data.vat_rate,
            include_internal=False,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/internal/calculators/new-build", dependencies=[Depends(require_api_token)])
def api_internal_new_build_calculation(data: CalculationRequest):
    try:
        return pricing_repository.calculate_new_build(
            brand=data.brand,
            technology=data.technology,
            completion_level=data.completion_level,
            package=data.package,
            gross_area_m2=data.gross_area_m2,
            vat_rate=data.vat_rate,
            include_internal=True,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/calculators/renovation/catalog")
def api_renovation_catalog(q: str = "", limit: int = 50):
    return pricing_repository.renovation_catalog(query=q, limit=limit)


@app.post("/api/calculators/renovation")
def api_renovation_calculation(data: RenovationCalculationIn):
    try:
        return pricing_repository.calculate_renovation(
            lines=[line.model_dump() for line in data.lines], vat_rate=data.vat_rate
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/housematch/catalog")
def api_housematch_catalog(brand: str | None = None, db: Session = Depends(get_db)):
    return public_catalog(db, brand=brand)


@app.post("/api/housematch/match")
def api_housematch(data: HouseMatchIn, db: Session = Depends(get_db)):
    try:
        return housematch_repository.match(
            HouseProfile(
                budget_huf=data.budget_huf,
                target_area_m2=data.target_area_m2,
                lifestyle=data.lifestyle,
                allowed_brands=tuple(data.allowed_brands),
                score_profile=data.score_profile,
            ),
            limit=data.limit,
            catalog=public_catalog(db),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _technical_payload_for_user(payload: dict, user: User) -> dict:
    if payload.get("module_key") != "buildconfig" or user.role in {
        "owner",
        "managing-director",
        "finance",
        "platform-admin",
    }:
        return payload
    result = dict(payload.get("result") or {})
    result.pop("internal_control", None)
    return {**payload, "result": result}


_TECHNICAL_ADMIN_ROLES = {"owner", "managing-director", "platform-admin"}
_TECHNICAL_CREATOR_ROLES = {
    "housebuild-agent": _TECHNICAL_ADMIN_ROLES | {"technical-prep"},
    "plotcheck": _TECHNICAL_ADMIN_ROLES
    | {"technical-prep", "sales", "project-manager", "designer"},
    "buildconfig": _TECHNICAL_ADMIN_ROLES | {"technical-prep", "sales", "designer"},
    "plancheck": _TECHNICAL_ADMIN_ROLES | {"technical-prep", "project-manager", "designer"},
}
_TECHNICAL_REVIEWER_ROLES = {
    "housebuild-agent": _TECHNICAL_ADMIN_ROLES | {"technical-prep"},
    "plotcheck": _TECHNICAL_ADMIN_ROLES | {"technical-prep", "project-manager", "designer"},
    "buildconfig": _TECHNICAL_ADMIN_ROLES | {"technical-prep", "designer"},
    "plancheck": _TECHNICAL_ADMIN_ROLES | {"technical-prep", "project-manager", "designer"},
}


def _can_view_technical_case(user: User, module_key: str) -> bool:
    """Keep internal technical records away from customer/partner workspaces."""
    return user.role not in {"customer", "subcontractor"} and can_access(user, module_key)


def _can_create_technical_case(user: User, module_key: str) -> bool:
    return _can_view_technical_case(user, module_key) and user.role in _TECHNICAL_CREATOR_ROLES.get(
        module_key, set()
    )


def _can_review_technical_gate(user: User, module_key: str, gate_key: str) -> bool:
    if not _can_view_technical_case(user, module_key) or gate_key == "margin":
        return False
    if module_key == "buildconfig" and gate_key in {"finance", "cashflow"}:
        return user.role in _TECHNICAL_ADMIN_ROLES | {"finance"}
    if user.role == "finance":
        return False
    return user.role in _TECHNICAL_REVIEWER_ROLES.get(module_key, set())


def _engineering_guard(action):
    try:
        return action()
    except KeyError as exc:
        raise HTTPException(404, "Az Engineering Workspace objektum nem található.") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/engineering-workspace", response_class=HTMLResponse)
def engineering_workspace_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "engineering-workspace"):
        raise HTTPException(403)
    return templates.TemplateResponse(
        request=request,
        name="engineering_workspace.html",
        context={
            "user": user,
            "active": "engineering-workspace",
            "data": _engineering_guard(lambda: engineering_workspace(db, user)),
        },
    )


@app.post("/engineering-workspace/cases")
async def engineering_case_create_page(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    payload = EngineeringCaseIn(
        project_id=str(form.get("project_id") or ""),
        title=str(form.get("title") or ""),
        lead_designer=str(form.get("lead_designer") or ""),
        project_manager=str(form.get("project_manager") or ""),
        contract_date=datetime.fromisoformat(str(form.get("contract_date"))).date(),
    )
    _engineering_guard(lambda: create_engineering_case(db, payload, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.post("/engineering-workspace/projects/{project_id}/consultation")
def engineering_consultation_page(project_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    _engineering_guard(lambda: complete_consultation(db, project_id, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.post("/engineering-workspace/projects/{project_id}/deliverables")
async def engineering_deliverable_create_page(
    project_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    due_at = datetime.fromisoformat(str(form.get("due_at")))
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    payload = EngineeringDeliverableIn(
        discipline=str(form.get("discipline") or ""),
        deliverable_code=str(form.get("deliverable_code") or ""),
        title=str(form.get("title") or ""),
        document_type=str(form.get("document_type") or ""),
        responsible=str(form.get("responsible") or ""),
        due_at=due_at,
        required=form.get("required") is not None,
    )
    _engineering_guard(lambda: create_engineering_deliverable(db, project_id, payload, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.post("/engineering-workspace/deliverables/{deliverable_id}/revisions")
async def engineering_revision_create_page(
    deliverable_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = EngineeringRevisionIn(
        source_document_id=str(form.get("source_document_id") or ""),
        source_version=str(form.get("source_version") or ""),
        source_url=str(form.get("source_url") or ""),
        file_name=str(form.get("file_name") or ""),
        mime_type=str(form.get("mime_type") or "application/pdf"),
        file_size=_form_int(form.get("file_size")),
        content_sha256=str(form.get("content_sha256") or ""),
        change_summary=str(form.get("change_summary") or ""),
        metadata={},
    )
    _engineering_guard(lambda: create_engineering_revision(db, deliverable_id, payload, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.post("/engineering-workspace/revisions/{revision_id}/submit")
def engineering_revision_submit_page(
    revision_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    _engineering_guard(lambda: submit_engineering_revision(db, revision_id, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.post("/engineering-workspace/revisions/{revision_id}/review")
async def engineering_revision_review_page(
    revision_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = EngineeringRevisionReviewIn(
        decision=str(form.get("decision") or ""), note=str(form.get("note") or "")
    )
    _engineering_guard(lambda: review_engineering_revision(db, revision_id, payload, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.post("/engineering-workspace/revisions/{revision_id}/release")
def engineering_revision_release_page(
    revision_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    _engineering_guard(lambda: release_engineering_revision(db, revision_id, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.post("/engineering-workspace/projects/{project_id}/findings")
async def engineering_finding_create_page(
    project_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    due_at = datetime.fromisoformat(str(form.get("due_at")))
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    payload = EngineeringFindingIn(
        revision_id=str(form.get("revision_id") or ""),
        category=str(form.get("category") or "coordination"),
        severity=str(form.get("severity") or "medium"),
        blocking=form.get("blocking") is not None,
        title=str(form.get("title") or ""),
        description=str(form.get("description") or ""),
        location=str(form.get("location") or "") or None,
        responsible=str(form.get("responsible") or ""),
        due_at=due_at,
        source_module="plancheck",
        source_fingerprint=str(form.get("source_fingerprint") or ""),
    )
    _engineering_guard(lambda: create_engineering_finding(db, project_id, payload, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.post("/engineering-workspace/findings/{finding_id}/propose")
async def engineering_finding_propose_page(
    finding_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = EngineeringFindingResolutionIn(
        resolution_revision_id=str(form.get("resolution_revision_id") or ""),
        note=str(form.get("note") or ""),
    )
    _engineering_guard(lambda: propose_finding_resolution(db, finding_id, payload, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.post("/engineering-workspace/findings/{finding_id}/resolve")
def engineering_finding_resolve_page(
    finding_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    _engineering_guard(lambda: approve_finding_resolution(db, finding_id, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.post("/engineering-workspace/projects/{project_id}/transmittals")
async def engineering_transmittal_issue_page(
    project_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = EngineeringTransmittalIn(
        purpose=str(form.get("purpose") or ""),
        subject=str(form.get("subject") or ""),
        recipient_name=str(form.get("recipient_name") or ""),
        recipient_email=str(form.get("recipient_email") or ""),
        message=str(form.get("message") or ""),
        revision_ids=[
            item.strip() for item in str(form.get("revision_ids") or "").split(",") if item.strip()
        ],
    )
    _engineering_guard(lambda: issue_transmittal(db, project_id, payload, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.post("/engineering-workspace/transmittals/{transmittal_id}/ack")
async def engineering_transmittal_ack_page(
    transmittal_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = EngineeringTransmittalAckIn(
        decision=str(form.get("decision") or ""), note=str(form.get("note") or "")
    )
    _engineering_guard(lambda: acknowledge_transmittal(db, transmittal_id, payload, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.post("/engineering-workspace/projects/{project_id}/construction-ready")
def engineering_construction_ready_page(
    project_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    _engineering_guard(lambda: mark_construction_ready(db, project_id, user))
    return RedirectResponse("/engineering-workspace", status_code=303)


@app.get("/api/engineering/summary")
def api_engineering_summary(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    data = _engineering_guard(lambda: engineering_workspace(db, user))
    return {
        "metrics": data["metrics"],
        "cases": [serialize_engineering(row) for row in data["cases"]],
    }


@app.get("/api/engineering/projects/{project_id}")
def api_engineering_project(project_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    data = _engineering_guard(lambda: engineering_workspace(db, user))
    case = next((row for row in data["cases"] if row.project_id == project_id), None)
    if not case:
        raise HTTPException(404)
    deliverables = data["deliverables_by_case"].get(case.engineering_case_id, [])
    revision_ids = {
        revision.revision_id
        for deliverable in deliverables
        for revision in data["revisions_by_deliverable"].get(deliverable.deliverable_id, [])
    }
    return {
        "case": serialize_engineering(case),
        "deliverables": [
            {
                **serialize_engineering(row),
                "revisions": [
                    serialize_engineering(revision)
                    for revision in data["revisions_by_deliverable"].get(row.deliverable_id, [])
                ],
            }
            for row in deliverables
        ],
        "findings": [
            serialize_engineering(row)
            for row in data["findings"]
            if row.revision_id in revision_ids
        ],
        "transmittals": [
            serialize_engineering(row)
            for row in data["transmittals"]
            if row.engineering_case_id == case.engineering_case_id
        ],
    }


@app.post("/api/engineering/cases")
def api_engineering_case_create(
    payload: EngineeringCaseIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: create_engineering_case(db, payload, user))
    )


@app.post("/api/engineering/projects/{project_id}/consultation")
def api_engineering_consultation(project_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: complete_consultation(db, project_id, user))
    )


@app.post("/api/engineering/projects/{project_id}/deliverables")
def api_engineering_deliverable_create(
    project_id: str,
    payload: EngineeringDeliverableIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: create_engineering_deliverable(db, project_id, payload, user))
    )


@app.post("/api/engineering/deliverables/{deliverable_id}/revisions")
def api_engineering_revision_create(
    deliverable_id: str,
    payload: EngineeringRevisionIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: create_engineering_revision(db, deliverable_id, payload, user))
    )


@app.post("/api/engineering/revisions/{revision_id}/submit")
def api_engineering_revision_submit(
    revision_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: submit_engineering_revision(db, revision_id, user))
    )


@app.post("/api/engineering/revisions/{revision_id}/review")
def api_engineering_revision_review(
    revision_id: str,
    payload: EngineeringRevisionReviewIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: review_engineering_revision(db, revision_id, payload, user))
    )


@app.post("/api/engineering/revisions/{revision_id}/release")
def api_engineering_revision_release(
    revision_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: release_engineering_revision(db, revision_id, user))
    )


@app.post("/api/engineering/projects/{project_id}/findings")
def api_engineering_finding_create(
    project_id: str,
    payload: EngineeringFindingIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: create_engineering_finding(db, project_id, payload, user))
    )


@app.post("/api/engineering/findings/{finding_id}/propose")
def api_engineering_finding_propose(
    finding_id: str,
    payload: EngineeringFindingResolutionIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: propose_finding_resolution(db, finding_id, payload, user))
    )


@app.post("/api/engineering/findings/{finding_id}/resolve")
def api_engineering_finding_resolve(
    finding_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: approve_finding_resolution(db, finding_id, user))
    )


@app.post("/api/engineering/projects/{project_id}/transmittals")
def api_engineering_transmittal_issue(
    project_id: str,
    payload: EngineeringTransmittalIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: issue_transmittal(db, project_id, payload, user))
    )


@app.post("/api/engineering/transmittals/{transmittal_id}/ack")
def api_engineering_transmittal_ack(
    transmittal_id: str,
    payload: EngineeringTransmittalAckIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: acknowledge_transmittal(db, transmittal_id, payload, user))
    )


@app.post("/api/engineering/projects/{project_id}/construction-ready")
def api_engineering_construction_ready(
    project_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    return serialize_engineering(
        _engineering_guard(lambda: mark_construction_ready(db, project_id, user))
    )


def _project_control_guard(action):
    try:
        return action()
    except KeyError as exc:
        raise HTTPException(404, "A Project Control objektum nem található.") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def _project_control_target(project_id: str | None) -> str:
    return f"/project-control?project_id={project_id}" if project_id else "/project-control"


@app.get("/project-control", response_class=HTMLResponse)
def project_control_page(
    request: Request, project_id: str | None = None, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not can_access(user, "project-control"):
        raise HTTPException(403)
    return templates.TemplateResponse(
        request=request,
        name="project_control.html",
        context={
            "user": user,
            "active": "project-control",
            "data": _project_control_guard(lambda: project_control_workspace(db, user, project_id)),
        },
    )


@app.post("/project-control/baselines")
async def project_control_baseline_create_page(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    project_id = str(form.get("project_id") or "")
    payload = ProjectControlBaselineIn(
        project_id=project_id,
        scope_document_id=str(form.get("scope_document_id") or ""),
        scope_version=str(form.get("scope_version") or ""),
        scope_sha256=str(form.get("scope_sha256") or ""),
        planned_start=date.fromisoformat(str(form.get("planned_start") or "")),
        planned_end=date.fromisoformat(str(form.get("planned_end") or "")),
        note=str(form.get("note") or ""),
    )
    _project_control_guard(lambda: create_project_control_baseline(db, payload, user))
    return RedirectResponse(_project_control_target(project_id), status_code=303)


@app.post("/project-control/baselines/{baseline_id}/submit")
async def project_control_baseline_submit_page(
    baseline_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    _project_control_guard(lambda: submit_project_control_baseline(db, baseline_id, user))
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.post("/project-control/baselines/{baseline_id}/review")
async def project_control_baseline_review_page(
    baseline_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = ProjectControlBaselineReviewIn(
        gate=cast(Literal["technical", "finance"], str(form.get("gate") or "")),
        decision=cast(Literal["approve", "reject"], str(form.get("decision") or "")),
        note=str(form.get("note") or ""),
    )
    _project_control_guard(lambda: review_project_control_baseline(db, baseline_id, payload, user))
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.post("/project-control/baselines/{baseline_id}/leadership")
async def project_control_baseline_leadership_page(
    baseline_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = ProjectControlLeadershipDecisionIn(
        decision=cast(Literal["approve", "reject"], str(form.get("decision") or "")),
        note=str(form.get("note") or ""),
    )
    _project_control_guard(lambda: decide_project_control_baseline(db, baseline_id, payload, user))
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.post("/project-control/baselines/{baseline_id}/forecasts")
async def project_control_forecast_create_page(
    baseline_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = ProjectControlForecastIn(
        as_of_date=date.fromisoformat(str(form.get("as_of_date") or "")),
        forecast_completion_date=date.fromisoformat(
            str(form.get("forecast_completion_date") or "")
        ),
        note=str(form.get("note") or ""),
    )
    _project_control_guard(lambda: create_project_control_forecast(db, baseline_id, payload, user))
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.post("/project-control/forecasts/{forecast_id}/submit")
async def project_control_forecast_submit_page(
    forecast_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    _project_control_guard(lambda: submit_project_control_forecast(db, forecast_id, user))
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.post("/project-control/forecasts/{forecast_id}/finance-review")
async def project_control_forecast_finance_page(
    forecast_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = ProjectControlFinanceReviewIn(
        decision=cast(Literal["approve", "reject"], str(form.get("decision") or "")),
        note=str(form.get("note") or ""),
    )
    _project_control_guard(lambda: review_project_control_forecast(db, forecast_id, payload, user))
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.post("/project-control/forecasts/{forecast_id}/leadership")
async def project_control_forecast_leadership_page(
    forecast_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = ProjectControlLeadershipDecisionIn(
        decision=cast(Literal["approve", "reject"], str(form.get("decision") or "")),
        note=str(form.get("note") or ""),
    )
    _project_control_guard(lambda: decide_project_control_forecast(db, forecast_id, payload, user))
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.post("/project-control/variances/{variance_id}/classify")
async def project_control_variance_classify_page(
    variance_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = ProjectControlVarianceClassifyIn(
        root_cause=cast(
            Literal[
                "price",
                "quantity",
                "productivity",
                "design",
                "change",
                "defect",
                "delay",
                "scope",
                "other",
            ],
            str(form.get("root_cause") or ""),
        ),
        note=str(form.get("note") or ""),
    )
    _project_control_guard(
        lambda: classify_project_control_variance(db, variance_id, payload, user)
    )
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.post("/project-control/variances/{variance_id}/actions")
async def project_control_recovery_create_page(
    variance_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    due_at = datetime.fromisoformat(str(form.get("due_at") or ""))
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    payload = ProjectControlRecoveryActionIn(
        title=str(form.get("title") or ""),
        owner=str(form.get("owner") or ""),
        due_at=due_at,
        target_amount_net=Decimal(str(form.get("target_amount_net") or "0")),
        target_days=_form_int(form.get("target_days")),
    )
    _project_control_guard(lambda: create_project_control_recovery(db, variance_id, payload, user))
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.post("/project-control/actions/{action_id}/complete")
async def project_control_recovery_complete_page(
    action_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = ProjectControlRecoveryCompleteIn(
        completion_note=str(form.get("completion_note") or ""),
        evidence_url=str(form.get("evidence_url") or ""),
    )
    _project_control_guard(lambda: complete_project_control_recovery(db, action_id, payload, user))
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.post("/project-control/actions/{action_id}/verify")
async def project_control_recovery_verify_page(
    action_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = ProjectControlRecoveryVerifyIn(
        decision=cast(Literal["verify", "reject"], str(form.get("decision") or "")),
        note=str(form.get("note") or ""),
    )
    _project_control_guard(lambda: verify_project_control_recovery(db, action_id, payload, user))
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.post("/project-control/projects/{project_id}/reports")
async def project_control_report_generate_page(
    project_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = ProjectControlWeeklyReportIn(
        week_ending=date.fromisoformat(str(form.get("week_ending") or "")),
        management_summary=str(form.get("management_summary") or ""),
    )
    _project_control_guard(lambda: generate_project_control_report(db, project_id, payload, user))
    return RedirectResponse(_project_control_target(project_id), status_code=303)


@app.post("/project-control/reports/{report_id}/submit")
async def project_control_report_submit_page(
    report_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    _project_control_guard(lambda: submit_project_control_report(db, report_id, user))
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.post("/project-control/reports/{report_id}/decision")
async def project_control_report_decision_page(
    report_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    payload = ProjectControlWeeklyReportDecisionIn(
        decision=cast(Literal["approve", "reject"], str(form.get("decision") or "")),
        note=str(form.get("note") or ""),
    )
    _project_control_guard(lambda: decide_project_control_report(db, report_id, payload, user))
    return RedirectResponse(
        _project_control_target(str(form.get("project_id") or "") or None), status_code=303
    )


@app.get("/api/project-control/summary")
def api_project_control_summary(
    request: Request, project_id: str | None = None, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    data = _project_control_guard(lambda: project_control_workspace(db, user, project_id))
    return {
        "metrics": data["metrics"],
        "baselines": [serialize_project_control(row) for row in data["baselines"]],
        "forecasts": [serialize_project_control(row) for row in data["forecasts"]],
        "variances": [serialize_project_control(row) for row in data["variances"]],
        "actions": [serialize_project_control(row) for row in data["actions"]],
        "reports": [serialize_project_control(row) for row in data["reports"]],
    }


@app.post("/api/project-control/baselines")
def api_project_control_baseline_create(
    payload: ProjectControlBaselineIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    return serialize_project_control(
        _project_control_guard(lambda: create_project_control_baseline(db, payload, user))
    )


@app.post("/api/project-control/baselines/{baseline_id}/forecasts")
def api_project_control_forecast_create(
    baseline_id: str,
    payload: ProjectControlForecastIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    return serialize_project_control(
        _project_control_guard(
            lambda: create_project_control_forecast(db, baseline_id, payload, user)
        )
    )


@app.get("/house-catalog", response_class=HTMLResponse)
def house_catalog_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role not in {
        "owner",
        "managing-director",
        "platform-admin",
        "technical-prep",
        "designer",
        "legal",
        "finance",
        "sales",
    }:
        raise HTTPException(403)
    return templates.TemplateResponse(
        request=request,
        name="house_catalog.html",
        context={
            "user": user,
            "active": "house-catalog",
            "data": catalog_workspace(db),
        },
    )


@app.post("/house-catalog/versions")
async def house_catalog_version_create(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        create_catalog_version(
            db,
            HouseCatalogVersionIn(
                house_id=str(form.get("house_id") or ""),
                brand=str(form.get("brand") or ""),
                canonical_name=str(form.get("canonical_name") or ""),
                catalog_price_huf=Decimal(str(form.get("catalog_price_huf") or "0")),
                gross_area_m2=Decimal(str(form.get("gross_area_m2") or "0")),
                rooms=str(form.get("rooms") or ""),
                price_status=str(form.get("price_status") or ""),
                data_quality=str(form.get("data_quality") or ""),
                lifestyles=[
                    value.strip()
                    for value in str(form.get("lifestyles") or "").split(",")
                    if value.strip()
                ],
                source_type=str(form.get("source_type") or ""),
                source_url=str(form.get("source_url") or ""),
                source_verified_at=str(form.get("source_verified_at") or ""),
                rights_evidence=str(form.get("rights_evidence") or ""),
                technical_summary=str(form.get("technical_summary") or ""),
                change_summary=str(form.get("change_summary") or ""),
            ),
            user,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/house-catalog", status_code=303)


@app.post("/house-catalog/versions/{catalog_version_id}/submit")
def house_catalog_version_submit(
    catalog_version_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    try:
        submit_catalog_version(db, catalog_version_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/house-catalog", status_code=303)


@app.post("/house-catalog/versions/{catalog_version_id}/review")
async def house_catalog_version_review(
    catalog_version_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        review_catalog_version(
            db,
            catalog_version_id,
            HouseCatalogReviewIn(
                gate=str(form.get("gate") or ""),
                decision=str(form.get("decision") or ""),
                note=str(form.get("note") or ""),
            ),
            user,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/house-catalog", status_code=303)


@app.post("/house-catalog/versions/{catalog_version_id}/release")
def house_catalog_version_release(
    catalog_version_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    try:
        release_catalog_version(db, catalog_version_id, user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/house-catalog", status_code=303)


@app.post("/house-catalog/plans/{house_id}/withdraw")
async def house_catalog_plan_withdraw(
    house_id: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        payload = HouseCatalogWithdrawIn(reason=str(form.get("reason") or ""))
        withdraw_catalog_plan(db, house_id, reason=payload.reason, user=user)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/house-catalog", status_code=303)


@app.get("/api/house-catalog")
def api_house_catalog_workspace(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if user.role not in {
        "owner",
        "managing-director",
        "platform-admin",
        "technical-prep",
        "designer",
        "legal",
        "finance",
        "sales",
    }:
        raise HTTPException(403)
    data = catalog_workspace(db)
    return {
        "metrics": data["metrics"],
        "plans": [serialize_catalog_plan(row) for row in data["plans"]],
        "versions": [serialize_catalog_version(row) for row in data["versions"]],
    }


@app.post("/api/house-catalog/versions")
def api_house_catalog_version_create(
    payload: HouseCatalogVersionIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    try:
        return serialize_catalog_version(create_catalog_version(db, payload, user))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/house-catalog/versions/{catalog_version_id}/submit")
def api_house_catalog_version_submit(
    catalog_version_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    try:
        return serialize_catalog_version(submit_catalog_version(db, catalog_version_id, user))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/house-catalog/versions/{catalog_version_id}/review")
def api_house_catalog_version_review(
    catalog_version_id: str,
    payload: HouseCatalogReviewIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    try:
        return serialize_catalog_version(
            review_catalog_version(db, catalog_version_id, payload, user)
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/house-catalog/versions/{catalog_version_id}/release")
def api_house_catalog_version_release(
    catalog_version_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    try:
        return serialize_catalog_version(release_catalog_version(db, catalog_version_id, user))
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/house-catalog/plans/{house_id}/withdraw")
def api_house_catalog_plan_withdraw(
    house_id: str, payload: HouseCatalogWithdrawIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    try:
        return serialize_catalog_version(
            withdraw_catalog_plan(db, house_id, reason=payload.reason, user=user)
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/technical", response_class=HTMLResponse)
def technical_workspace(
    request: Request, module: str = "", project_id: str = "", db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    visible_modules = {
        key for key in _TECHNICAL_CREATOR_ROLES if _can_view_technical_case(user, key)
    }
    if not visible_modules or (module and module not in visible_modules):
        raise HTTPException(403, "Ehhez a műszaki munkatérhez nincs jogosultság.")
    rows = [
        row
        for row in list_cases(db, module_key=module or None, project_id=project_id or None)
        if row["module_key"] in visible_modules
    ]
    return templates.TemplateResponse(
        request=request,
        name="technical.html",
        context={
            "user": user,
            "active": "technical",
            "cases": [_technical_payload_for_user(row, user) for row in rows],
            "selected_module": module,
            "project_id": project_id,
            "catalog": pricing_repository.brand_catalog(),
            "houses": public_catalog(db),
            "creatable_modules": {
                key
                for key in visible_modules
                if _can_create_technical_case(user, key)
                and key not in {"plotcheck", "housebuild-agent", "buildconfig"}
            },
            "can_review_technical_gate": lambda module_key, gate_key: _can_review_technical_gate(
                user, module_key, gate_key
            ),
        },
    )


@app.get("/plancheck", response_class=HTMLResponse)
def plancheck_workspace_page(
    request: Request,
    project_id: str = "",
    status: str = "",
    query: str = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not _can_view_technical_case(user, "plancheck"):
        raise HTTPException(403, "A PlanCheck munkatérhez nincs jogosultsága.")
    normalized_query = query.strip().lower()
    cases = [
        item
        for item in list_plancheck_cases(db)
        if (not project_id or item["case"].project_id == project_id.strip())
        and (not status or item["case"].status == status)
        and (
            not normalized_query
            or normalized_query in item["case"].case_id.lower()
            or normalized_query in item["case"].title.lower()
            or normalized_query in item["case"].contact_email.lower()
        )
    ]
    return templates.TemplateResponse(
        request=request,
        name="plancheck.html",
        context={
            "user": user,
            "active": "technical",
            "cases": cases,
            "project_id": project_id,
            "selected_status": status,
            "query": query,
            "can_edit": _can_create_technical_case(user, "plancheck"),
        },
    )


@app.get("/housebuild", response_class=HTMLResponse)
def housebuild_workspace_page(
    request: Request,
    project_id: str = "",
    status: str = "",
    query: str = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not _can_view_technical_case(user, "housebuild-agent"):
        raise HTTPException(403, "A HouseBuild munkatérhez nincs jogosultsága.")
    normalized_query = query.strip().lower()
    cases = [
        item
        for item in list_housebuild_cases(db)
        if (not project_id or item["project_id"] == project_id.strip())
        and (not status or item["status"] == status)
        and (
            not normalized_query
            or normalized_query in item["case_id"].lower()
            or normalized_query in item["title"].lower()
            or normalized_query in item["source_house_id"].lower()
        )
    ]
    return templates.TemplateResponse(
        request=request,
        name="housebuild.html",
        context={
            "user": user,
            "active": "technical",
            "cases": cases,
            "houses": public_catalog(db),
            "can_edit": _can_create_technical_case(user, "housebuild-agent"),
            "project_id": project_id,
            "selected_status": status,
            "query": query,
        },
    )


@app.get("/buildconfig", response_class=HTMLResponse)
def buildconfig_workspace_page(
    request: Request, project_id: str = "", db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not _can_view_technical_case(user, "buildconfig"):
        raise HTTPException(403, "A BuildConfig munkatérhez nincs jogosultsága.")
    return templates.TemplateResponse(
        request=request,
        name="buildconfig.html",
        context={
            "user": user,
            "active": "technical",
            "cases": list_buildconfig_cases(db, project_id or None),
            "project_id": project_id,
            "housebuild_variants": buildconfig_housebuild_variants(db),
            "options": buildconfig_option_catalog(),
            "catalog": pricing_repository.brand_catalog(),
            "can_edit": _can_create_technical_case(user, "buildconfig"),
        },
    )


def _buildconfig_form_payload(form, *, include_binding: bool) -> dict:
    payload = {
        "brand": form.get("brand"),
        "technology": form.get("technology"),
        "completion_level": form.get("completion_level"),
        "package": form.get("package"),
        "gross_area_m2": form.get("gross_area_m2"),
        "vat_rate": form.get("vat_rate"),
        "options": form.getlist("options"),
        "planned_start": form.get("planned_start"),
        "promised_delivery": form.get("promised_delivery"),
        "crew_count": form.get("crew_count"),
        "weekly_capacity_m2": form.get("weekly_capacity_m2"),
    }
    if include_binding:
        payload.update(
            {
                "project_id": form.get("project_id"),
                "title": form.get("title"),
                "housebuild_case_id": form.get("housebuild_case_id"),
                "housebuild_variant_id": form.get("housebuild_variant_id"),
            }
        )
    return payload


@app.post("/buildconfig/cases")
async def buildconfig_case_create_page(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "buildconfig"):
        raise HTTPException(403, "BuildConfig ügy indításához nincs jogosultsága.")
    form = await request.form()
    try:
        detail = create_buildconfig_case(
            db, _buildconfig_form_payload(form, include_binding=True), user
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse(f"/buildconfig/cases/{detail['case_id']}", status_code=303)


@app.get("/buildconfig/cases/{case_id}", response_class=HTMLResponse)
def buildconfig_case_detail_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not _can_view_technical_case(user, "buildconfig"):
        raise HTTPException(403, "A BuildConfig ügyhöz nincs jogosultsága.")
    try:
        detail = buildconfig_case_detail(db, case_id)
    except KeyError as exc:
        raise HTTPException(404, "A BuildConfig ügy nem található.") from exc
    return templates.TemplateResponse(
        request=request,
        name="buildconfig_detail.html",
        context={
            "user": user,
            "active": "technical",
            "detail": detail,
            "options": buildconfig_option_catalog(),
            "catalog": pricing_repository.brand_catalog(),
            "can_edit": _can_create_technical_case(user, "buildconfig"),
            "can_technical_review": user.role in BUILDCONFIG_TECHNICAL_REVIEW_ROLES,
            "can_finance_review": user.role in BUILDCONFIG_FINANCE_REVIEW_ROLES,
            "can_release": user.role in BUILDCONFIG_RELEASE_ROLES,
            "show_internal": user.role
            in {"owner", "managing-director", "finance", "platform-admin"},
        },
    )


@app.post("/buildconfig/cases/{case_id}/revisions")
async def buildconfig_revision_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        create_buildconfig_revision(
            db, case_id, _buildconfig_form_payload(form, include_binding=False), user
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/buildconfig/cases/{case_id}", status_code=303)


@app.post("/buildconfig/cases/{case_id}/submit")
def buildconfig_submit_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    try:
        submit_buildconfig_case(db, case_id, user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A BuildConfig ügy nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/buildconfig/cases/{case_id}", status_code=303)


@app.post("/buildconfig/cases/{case_id}/gates/{gate_key}")
async def buildconfig_gate_page(
    case_id: str, gate_key: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        review_buildconfig_gate(
            db,
            case_id,
            gate_key,
            {
                "decision": form.get("decision"),
                "note": form.get("note"),
                "evidence_ref": form.get("evidence_ref"),
                "evidence_sha256": form.get("evidence_sha256"),
            },
            user,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A BuildConfig ügy vagy kapu nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/buildconfig/cases/{case_id}", status_code=303)


@app.post("/buildconfig/cases/{case_id}/release")
async def buildconfig_release_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        release_buildconfig_case(db, case_id, str(form.get("note") or ""), user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A BuildConfig ügy nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/buildconfig/cases/{case_id}", status_code=303)


@app.post("/buildconfig/cases/{case_id}/reject")
async def buildconfig_reject_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        reject_buildconfig_case(db, case_id, str(form.get("reason") or ""), user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A BuildConfig ügy nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/buildconfig/cases/{case_id}", status_code=303)


@app.get("/buildconfig/reports/{document_id}")
def buildconfig_report_download(document_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not _can_view_technical_case(user, "buildconfig"):
        raise HTTPException(403)
    try:
        path = buildconfig_report_path(db, document_id)
    except KeyError as exc:
        raise HTTPException(404, "A BuildConfig jelentés nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/api/buildconfig/cases", dependencies=[Depends(require_api_token)])
def api_buildconfig_cases(project_id: str = "", db: Session = Depends(get_db)):
    return list_buildconfig_cases(db, project_id or None)


@app.get("/api/buildconfig/cases/{case_id}", dependencies=[Depends(require_api_token)])
def api_buildconfig_case(case_id: str, db: Session = Depends(get_db)):
    try:
        return buildconfig_case_detail(db, case_id)
    except KeyError as exc:
        raise HTTPException(404, "A BuildConfig ügy nem található.") from exc


@app.post("/housebuild/cases")
async def housebuild_case_create_page(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "housebuild-agent"):
        raise HTTPException(403, "HouseBuild ügy indításához nincs jogosultsága.")
    form = await request.form()
    try:
        detail = create_housebuild_case(
            db,
            {
                "project_id": form.get("project_id"),
                "title": form.get("title"),
                "source_house_id": form.get("source_house_id"),
                "rights_evidence_ref": form.get("rights_evidence_ref"),
                "rights_evidence_sha256": form.get("rights_evidence_sha256"),
                "desired_area_m2": form.get("desired_area_m2"),
                "technology": form.get("technology"),
                "bedrooms": form.get("bedrooms"),
                "bathrooms": form.get("bathrooms"),
                "floors": form.get("floors"),
                "garage_spaces": form.get("garage_spaces"),
                "roof_style": form.get("roof_style"),
                "facade_style": form.get("facade_style"),
                "orientation": form.get("orientation"),
                "accessibility": form.get("accessibility") == "on",
                "customization_notes": form.get("customization_notes"),
            },
            user,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse(f"/housebuild/cases/{detail['case_id']}", status_code=303)


@app.get("/housebuild/cases/{case_id}", response_class=HTMLResponse)
def housebuild_case_detail_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not _can_view_technical_case(user, "housebuild-agent"):
        raise HTTPException(403, "A HouseBuild ügyhöz nincs jogosultsága.")
    try:
        detail = housebuild_case_detail(db, case_id)
    except KeyError as exc:
        raise HTTPException(404, "A HouseBuild ügy nem található.") from exc
    return templates.TemplateResponse(
        request=request,
        name="housebuild_detail.html",
        context={
            "user": user,
            "active": "technical",
            "detail": detail,
            "can_edit": _can_create_technical_case(user, "housebuild-agent"),
            "can_review": user.role in _TECHNICAL_REVIEWER_ROLES["housebuild-agent"],
            "can_release": user.role in HOUSEBUILD_RELEASE_ROLES,
        },
    )


@app.post("/housebuild/cases/{case_id}/variant")
async def housebuild_variant_select_page(
    case_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        select_housebuild_canonical_variant(db, case_id, str(form.get("variant_id") or ""), user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A HouseBuild ügy vagy változat nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/housebuild/cases/{case_id}", status_code=303)


@app.post("/housebuild/cases/{case_id}/submit")
def housebuild_submit_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    try:
        submit_housebuild_case(db, case_id, user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A HouseBuild ügy nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/housebuild/cases/{case_id}", status_code=303)


@app.post("/housebuild/cases/{case_id}/gates/{gate_key}")
async def housebuild_gate_page(
    case_id: str, gate_key: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        review_housebuild_gate(
            db,
            case_id,
            gate_key,
            {
                "decision": form.get("decision"),
                "note": form.get("note"),
                "evidence_refs": [form.get("evidence_ref")],
                "evidence_sha256": form.get("evidence_sha256"),
            },
            user,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A HouseBuild ügy vagy kapu nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/housebuild/cases/{case_id}", status_code=303)


@app.post("/housebuild/cases/{case_id}/release")
async def housebuild_release_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        release_housebuild_case(db, case_id, str(form.get("note") or ""), user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A HouseBuild ügy nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/housebuild/cases/{case_id}", status_code=303)


@app.post("/housebuild/cases/{case_id}/reject")
async def housebuild_reject_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        reject_housebuild_case(db, case_id, str(form.get("reason") or ""), user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A HouseBuild ügy nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/housebuild/cases/{case_id}", status_code=303)


@app.get("/housebuild/reports/{document_id}")
def housebuild_report_download(document_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not _can_view_technical_case(user, "housebuild-agent"):
        raise HTTPException(403)
    try:
        path = housebuild_report_path(db, document_id)
    except KeyError as exc:
        raise HTTPException(404, "A HouseBuild jelentés nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/plotcheck", response_class=HTMLResponse)
def plotcheck_workspace_page(
    request: Request,
    project_id: str = "",
    status: str = "",
    query: str = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not _can_view_technical_case(user, "plotcheck"):
        raise HTTPException(403, "A PlotCheck munkatérhez nincs jogosultsága.")
    normalized_query = query.strip().lower()
    cases = [
        item
        for item in list_plotcheck_cases(db)
        if (not project_id or item["project_id"] == project_id.strip())
        and (not status or item["status"] == status)
        and (
            not normalized_query
            or normalized_query in item["case_id"].lower()
            or normalized_query in item["title"].lower()
            or normalized_query in item["address"].lower()
            or normalized_query in item["parcel_number"].lower()
        )
    ]
    return templates.TemplateResponse(
        request=request,
        name="plotcheck.html",
        context={
            "user": user,
            "active": "technical",
            "cases": cases,
            "rules": list_plotcheck_rule_sets(db),
            "verified_rules": list_plotcheck_rule_sets(db, include_non_verified=False),
            "can_edit": _can_create_technical_case(user, "plotcheck"),
            "can_admin_rules": user.role in PLOTCHECK_RULE_ADMIN_ROLES,
            "project_id": project_id,
            "selected_status": status,
            "query": query,
        },
    )


@app.post("/plotcheck/rules")
async def plotcheck_rule_create_page(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        create_plotcheck_rule_set(
            db,
            {
                "municipality": form.get("municipality"),
                "zoning_code": form.get("zoning_code"),
                "version": form.get("version"),
                "lifecycle_status": form.get("lifecycle_status"),
                "source_url": form.get("source_url"),
                "source_document_version": form.get("source_document_version"),
                "source_note": form.get("source_note"),
                "effective_from": form.get("effective_from"),
                "maximum_coverage_percent": form.get("maximum_coverage_percent"),
                "maximum_floor_area_ratio": form.get("maximum_floor_area_ratio"),
                "maximum_height_m": form.get("maximum_height_m"),
                "minimum_green_percent": form.get("minimum_green_percent"),
                "front_setback_m": form.get("front_setback_m"),
                "side_setback_m": form.get("side_setback_m"),
                "rear_setback_m": form.get("rear_setback_m"),
                "allowed_uses": [
                    item.strip() for item in str(form.get("allowed_uses") or "").split(",")
                ],
            },
            user,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse("/plotcheck", status_code=303)


@app.post("/plotcheck/rules/{rule_set_id}/verify")
def plotcheck_rule_verify_page(rule_set_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    try:
        verify_plotcheck_rule_set(db, rule_set_id, user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A szabályverzió nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/plotcheck", status_code=303)


@app.post("/plotcheck/cases")
async def plotcheck_case_create_page(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "plotcheck"):
        raise HTTPException(403, "PlotCheck ügy indításához nincs jogosultsága.")
    form = await request.form()
    try:
        detail = create_plotcheck_case(
            db,
            {
                "project_id": form.get("project_id"),
                "title": form.get("title"),
                "address": form.get("address"),
                "parcel_number": form.get("parcel_number"),
                "municipality": form.get("municipality"),
                "zoning_code": form.get("zoning_code"),
                "rule_set_id": form.get("rule_set_id"),
                "declared_plot_area_m2": form.get("declared_plot_area_m2"),
                "plot_width_m": form.get("plot_width_m"),
                "plot_depth_m": form.get("plot_depth_m"),
                "geometry": form.get("geometry") or None,
                "geometry_crs": form.get("geometry_crs"),
                "proposed_width_m": form.get("proposed_width_m"),
                "proposed_depth_m": form.get("proposed_depth_m"),
                "proposed_footprint_m2": form.get("proposed_footprint_m2") or None,
                "proposed_gross_floor_area_m2": form.get("proposed_gross_floor_area_m2"),
                "proposed_paved_area_m2": form.get("proposed_paved_area_m2"),
                "proposed_height_m": form.get("proposed_height_m"),
                "proposed_use": form.get("proposed_use"),
                "house_id": form.get("house_id"),
            },
            user.email,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse(f"/plotcheck/cases/{detail['case_id']}", status_code=303)


@app.get("/plotcheck/cases/{case_id}", response_class=HTMLResponse)
def plotcheck_detail_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not _can_view_technical_case(user, "plotcheck"):
        raise HTTPException(403, "A PlotCheck ügyhöz nincs jogosultsága.")
    try:
        detail = plotcheck_case_detail(db, case_id)
    except KeyError as exc:
        raise HTTPException(404, "A PlotCheck ügy nem található.") from exc
    return templates.TemplateResponse(
        request=request,
        name="plotcheck_detail.html",
        context={
            "user": user,
            "active": "technical",
            "detail": detail,
            "can_edit": _can_create_technical_case(user, "plotcheck"),
            "can_review_gate": user.role in _TECHNICAL_REVIEWER_ROLES["plotcheck"],
            "can_finalize": user.role in PLOTCHECK_FINAL_ROLES,
        },
    )


@app.post("/plotcheck/cases/{case_id}/evidence")
async def plotcheck_evidence_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "plotcheck"):
        raise HTTPException(403)
    form = await request.form()
    try:
        add_plotcheck_evidence(
            db,
            case_id,
            {
                "category": form.get("category"),
                "source_reference": form.get("source_reference"),
                "source_version": form.get("source_version"),
                "source_sha256": form.get("source_sha256"),
                "note": form.get("note"),
                "legal_blocker": form.get("legal_blocker") == "on",
            },
            user.email,
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse(f"/plotcheck/cases/{case_id}", status_code=303)


@app.post("/plotcheck/cases/{case_id}/evidence/{evidence_id}/verify")
def plotcheck_evidence_verify_page(
    case_id: str, evidence_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in _TECHNICAL_REVIEWER_ROLES["plotcheck"]:
        raise HTTPException(403, "PlotCheck bizonyíték-hitelesítéshez nincs jogosultsága.")
    try:
        verify_plotcheck_evidence(db, case_id, evidence_id, user.email)
    except KeyError as exc:
        raise HTTPException(404, "A bizonyíték nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/plotcheck/cases/{case_id}", status_code=303)


@app.post("/plotcheck/cases/{case_id}/actions")
async def plotcheck_action_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "plotcheck"):
        raise HTTPException(403)
    form = await request.form()
    try:
        add_plotcheck_action(
            db,
            case_id,
            {
                "condition": form.get("condition"),
                "owner": form.get("owner"),
                "estimated_cost_huf": form.get("estimated_cost_huf"),
                "deadline_impact_days": form.get("deadline_impact_days"),
                "design_impact": form.get("design_impact"),
            },
            user.email,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse(f"/plotcheck/cases/{case_id}", status_code=303)


@app.post("/plotcheck/cases/{case_id}/actions/{action_id}/complete")
async def plotcheck_action_complete_page(
    case_id: str, action_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "plotcheck"):
        raise HTTPException(403)
    form = await request.form()
    try:
        complete_plotcheck_action(
            db,
            case_id,
            action_id,
            {
                "completion_evidence_ref": form.get("completion_evidence_ref"),
                "completion_evidence_sha256": form.get("completion_evidence_sha256"),
            },
            user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, "Az ActionID nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/plotcheck/cases/{case_id}", status_code=303)


@app.post("/plotcheck/cases/{case_id}/gates/{gate_key}")
async def plotcheck_gate_page(
    case_id: str, gate_key: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if user.role not in _TECHNICAL_REVIEWER_ROLES["plotcheck"]:
        raise HTTPException(403, "PlotCheck kapudöntéshez nincs jogosultsága.")
    form = await request.form()
    try:
        review_plotcheck_gate(
            db,
            case_id,
            gate_key,
            {
                "decision": form.get("decision"),
                "note": form.get("note"),
                "evidence_ids": form.getlist("evidence_ids"),
            },
            user.email,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/plotcheck/cases/{case_id}", status_code=303)


@app.post("/plotcheck/cases/{case_id}/assess")
def plotcheck_assess_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "plotcheck"):
        raise HTTPException(403)
    try:
        assess_plotcheck_case(db, case_id, user.email)
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/plotcheck/cases/{case_id}", status_code=303)


@app.post("/plotcheck/cases/{case_id}/finalize")
async def plotcheck_finalize_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        finalize_plotcheck_case(
            db, case_id, str(form.get("outcome") or ""), str(form.get("note") or ""), user
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/plotcheck/cases/{case_id}", status_code=303)


@app.get("/plotcheck/reports/{document_id}")
def plotcheck_report_download(document_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not _can_view_technical_case(user, "plotcheck"):
        raise HTTPException(403)
    row = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.document_id == document_id,
            WorkspaceDocument.category == "plotcheck_report",
        )
    )
    if row is None:
        raise HTTPException(404, "A PlotCheck jelentés nem található.")
    metadata = json.loads(row.metadata_json or "{}")
    path = Path(str(metadata.get("local_path") or "")).resolve()
    allowed_root = (
        Path(os.getenv("PLATFORM_RUNTIME_ROOT", "/app/runtime")) / "plotcheck"
    ).resolve()
    try:
        path.relative_to(allowed_root)
    except ValueError as exc:
        raise HTTPException(409, "A jelentés tárolási útvonala érvénytelen.") from exc
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != metadata.get(
        "sha256"
    ):
        raise HTTPException(409, "A jelentés hiányzik vagy a SHA-256 ellenőrzése sikertelen.")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.post("/plancheck/cases", response_class=HTMLResponse)
async def plancheck_create_page(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "plancheck"):
        raise HTTPException(403, "PlanCheck ügy indításához nincs jogosultsága.")
    form = await request.form()
    intake = {
        "HouseMatchID": str(form.get("housematch_id") or "").strip(),
        "PlotCheckID": str(form.get("plotcheck_id") or "").strip(),
        "BuildConfigID": str(form.get("buildconfig_id") or "").strip(),
        "building_type": str(form.get("building_type") or "").strip(),
        "gross_area_m2": str(form.get("gross_area_m2") or "").strip(),
    }
    try:
        detail, token = create_plancheck_case(
            db,
            project_id=str(form.get("project_id") or ""),
            title=str(form.get("title") or ""),
            contact_name=str(form.get("contact_name") or ""),
            contact_email=str(form.get("contact_email") or ""),
            intake=intake,
            actor=user.email,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    upload_url = str(request.base_url).rstrip("/") + f"/plancheck/upload/{token}"
    return templates.TemplateResponse(
        request=request,
        name="plancheck_created.html",
        context={
            "user": user,
            "active": "technical",
            "detail": detail,
            "upload_url": upload_url,
        },
    )


@app.get("/plancheck/cases/{case_id}", response_class=HTMLResponse)
def plancheck_detail_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not _can_view_technical_case(user, "plancheck"):
        raise HTTPException(403, "A PlanCheck ügyhöz nincs jogosultsága.")
    try:
        detail = plancheck_case_detail(db, case_id)
    except KeyError as exc:
        raise HTTPException(404, "A PlanCheck ügy nem található.") from exc
    return templates.TemplateResponse(
        request=request,
        name="plancheck_detail.html",
        context={
            "user": user,
            "active": "technical",
            "detail": detail,
            "can_edit": _can_create_technical_case(user, "plancheck"),
            "can_decide_gate": lambda key: user.role in PLANCHECK_GATE_ROLES.get(key, set()),
            "can_finalize": user.role in PLANCHECK_FINAL_ROLES,
        },
    )


@app.post("/plancheck/cases/{case_id}/upload-link/rotate", response_class=HTMLResponse)
async def plancheck_upload_link_rotate_page(
    case_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "plancheck"):
        raise HTTPException(403, "Nincs jogosultsága feltöltési hivatkozást kiadni.")
    form = await request.form()
    try:
        valid_days = int(str(form.get("valid_days") or "30"))
        detail, token = rotate_plancheck_upload_link(db, case_id, user.email, valid_days=valid_days)
    except KeyError as exc:
        raise HTTPException(404, "A PlanCheck ügy nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    upload_url = str(request.base_url).rstrip("/") + f"/plancheck/upload/{token}"
    return templates.TemplateResponse(
        request=request,
        name="plancheck_created.html",
        context={
            "user": user,
            "active": "technical",
            "detail": detail,
            "upload_url": upload_url,
            "rotated": True,
        },
    )


@app.post("/plancheck/cases/{case_id}/upload-link/revoke")
def plancheck_upload_link_revoke_page(
    case_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "plancheck"):
        raise HTTPException(403, "Nincs jogosultsága feltöltési hivatkozást visszavonni.")
    try:
        revoke_plancheck_upload_link(db, case_id, user.email)
    except KeyError as exc:
        raise HTTPException(404, "A PlanCheck ügy nem található.") from exc
    return RedirectResponse(f"/plancheck/cases/{case_id}", status_code=303)


@app.get("/plancheck/upload/{token}", response_class=HTMLResponse)
def plancheck_public_upload_page(token: str, request: Request, db: Session = Depends(get_db)):
    try:
        case = plancheck_case_for_token(db, token)
    except (PermissionError, ValueError) as exc:
        raise HTTPException(410, str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="plancheck_upload.html",
        context={"case": case, "token": token, "uploaded": False},
    )


@app.post("/plancheck/upload/{token}", response_class=HTMLResponse)
async def plancheck_public_upload_submit(
    token: str, request: Request, db: Session = Depends(get_db)
):
    form = await request.form()
    uploaded = form.get("document")
    if not isinstance(uploaded, StarletteUploadFile):
        raise HTTPException(422, "A tervdokumentum kiválasztása kötelező.")
    if not getattr(uploaded, "filename", None):
        raise HTTPException(422, "A tervdokumentum kiválasztása kötelező.")
    content = await uploaded.read(20 * 1024 * 1024 + 1)
    try:
        detail = upload_plancheck_document(
            db,
            token=token,
            category=str(form.get("category") or ""),
            file_name=uploaded.filename or "plancheck-upload.bin",
            mime_type=uploaded.content_type or "application/octet-stream",
            content=content,
            uploader=plancheck_case_for_token(db, token).contact_email,
        )
    except (PermissionError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="plancheck_upload.html",
        context={"case": detail["case"], "token": token, "uploaded": True},
    )


@app.post("/plancheck/cases/{case_id}/assumptions")
async def plancheck_assumption_create(
    case_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "plancheck"):
        raise HTTPException(403, "Nincs PlanCheck szerkesztési jogosultsága.")
    form = await request.form()
    try:
        add_plancheck_assumption(
            db,
            case_id,
            description=str(form.get("description") or ""),
            impact=str(form.get("impact") or ""),
            owner=str(form.get("owner") or ""),
            actor=user.email,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse(f"/plancheck/cases/{case_id}", status_code=303)


@app.post("/plancheck/cases/{case_id}/assumptions/{assumption_id}/resolve")
async def plancheck_assumption_resolve(
    case_id: str, assumption_id: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "plancheck"):
        raise HTTPException(403, "Nincs PlanCheck szerkesztési jogosultsága.")
    form = await request.form()
    try:
        resolve_plancheck_assumption(
            db,
            case_id,
            assumption_id,
            resolution=str(form.get("resolution") or ""),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, "A nyitott feltételezés nem található.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse(f"/plancheck/cases/{case_id}", status_code=303)


@app.post("/plancheck/cases/{case_id}/submit")
def plancheck_submit_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, "plancheck"):
        raise HTTPException(403, "Nincs PlanCheck szerkesztési jogosultsága.")
    try:
        submit_plancheck_review(db, case_id, user.email)
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/plancheck/cases/{case_id}", status_code=303)


@app.post("/plancheck/cases/{case_id}/gates/{gate_key}")
async def plancheck_gate_page(
    case_id: str, gate_key: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        review_plancheck_gate(
            db,
            case_id,
            gate_key=gate_key,
            decision=str(form.get("decision") or ""),
            note=str(form.get("note") or ""),
            user=user,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/plancheck/cases/{case_id}", status_code=303)


@app.post("/plancheck/cases/{case_id}/finalize")
async def plancheck_finalize_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        finalize_plancheck_case(
            db,
            case_id,
            outcome=str(form.get("outcome") or ""),
            note=str(form.get("note") or ""),
            user=user,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/plancheck/cases/{case_id}", status_code=303)


@app.get("/plancheck/reports/{document_id}")
def plancheck_report_download(document_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    if not _can_view_technical_case(user, "plancheck"):
        raise HTTPException(403, "Nincs hozzáférése a PlanCheck jelentéshez.")
    row = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.document_id == document_id,
            WorkspaceDocument.category == "plancheck_report",
        )
    )
    if row is None:
        raise HTTPException(404, "A PlanCheck jelentés nem található.")
    metadata = json.loads(row.metadata_json or "{}")
    path = Path(str(metadata.get("local_path") or "")).resolve()
    allowed_root = (
        Path(os.getenv("PLATFORM_RUNTIME_ROOT", "/app/runtime")) / "plancheck"
    ).resolve()
    try:
        path.relative_to(allowed_root)
    except ValueError as exc:
        raise HTTPException(409, "A jelentés tárolási útvonala érvénytelen.") from exc
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != metadata.get(
        "sha256"
    ):
        raise HTTPException(409, "A jelentés hiányzik vagy a SHA-256 ellenőrzése sikertelen.")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.post("/technical/cases")
async def technical_case_create(request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    module_key = str(form.get("module_key") or "")
    if not _can_create_technical_case(user, module_key):
        raise HTTPException(403, "Ehhez a műszaki modulhoz nincs jogosultság.")
    if module_key in {"plotcheck", "housebuild-agent", "buildconfig"}:
        target = {
            "plotcheck": "/plotcheck",
            "housebuild-agent": "/housebuild",
            "buildconfig": "/buildconfig",
        }[module_key]
        raise HTTPException(
            409, f"Ez a modul kizárólag a kanonikus {target} munkatérben indítható."
        )
    data: dict = {}
    if module_key == "housebuild-agent":
        data = {
            "source_house_id": str(form.get("source_house_id") or ""),
            "rights_evidence": str(form.get("rights_evidence") or ""),
            "desired_area_m2": str(form.get("desired_area_m2") or ""),
            "bedrooms": str(form.get("bedrooms") or ""),
            "bathrooms": str(form.get("bathrooms") or ""),
            "floors": str(form.get("floors") or ""),
            "garage_spaces": str(form.get("garage_spaces") or "0"),
            "roof_style": str(form.get("roof_style") or ""),
            "facade_style": str(form.get("facade_style") or ""),
            "orientation": str(form.get("orientation") or ""),
            "accessibility": form.get("accessibility") is not None,
            "customization_notes": str(form.get("customization_notes") or ""),
        }
    elif module_key == "plotcheck":
        data = {
            "address": str(form.get("address") or ""),
            "parcel_number": str(form.get("parcel_number") or ""),
            "zoning_code": str(form.get("zoning_code") or ""),
            "plot_area_m2": str(form.get("plot_area_m2") or ""),
            "utilities": str(form.get("utilities") or ""),
            "evidence_references": [
                line.strip()
                for line in str(form.get("evidence_references") or "").splitlines()
                if line.strip()
            ],
        }
    elif module_key == "buildconfig":
        data = {
            "brand": str(form.get("brand") or ""),
            "technology": str(form.get("technology") or ""),
            "completion_level": str(form.get("completion_level") or ""),
            "package": str(form.get("package") or ""),
            "gross_area_m2": str(form.get("gross_area_m2") or ""),
        }
    elif module_key == "plancheck":
        data = {
            "document_refs": [
                line.strip()
                for line in str(form.get("document_refs") or "").splitlines()
                if line.strip()
            ]
        }
    try:
        row = create_case(
            db,
            module_key=module_key,
            project_id=str(form.get("project_id") or ""),
            title=str(form.get("title") or ""),
            data=data,
            actor=user.email,
            assigned_to=str(form.get("assigned_to") or "") or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/technical?module={module_key}#{row['case_id']}", status_code=303)


@app.post("/technical/cases/{case_id}/variant")
async def technical_housebuild_variant(
    case_id: str, request: Request, db: Session = Depends(get_db)
):
    require_session_user(request, db)
    raise HTTPException(
        409,
        "A korábbi általános HouseBuild ügy csak olvasható; használja a kanonikus /housebuild munkateret.",
    )


@app.post("/technical/cases/{case_id}/submit")
def technical_case_submit(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    try:
        row = get_case(db, case_id)
        if row["module_key"] in {"plotcheck", "housebuild-agent", "buildconfig"}:
            raise HTTPException(
                409,
                "A korábbi általános műszaki ügy csak olvasható; használja a kanonikus modulmunkateret.",
            )
        if not _can_create_technical_case(user, row["module_key"]):
            raise HTTPException(403, "Nincs jogosultság.")
        submit_case(db, case_id, user.email)
    except KeyError as exc:
        raise HTTPException(404, "A műszaki ügy nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/technical?module={row['module_key']}#{case_id}", status_code=303)


@app.post("/technical/cases/{case_id}/gates/{gate_key}")
async def technical_gate_review(
    case_id: str, gate_key: str, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        row = get_case(db, case_id)
        if row["module_key"] in {"plotcheck", "housebuild-agent", "buildconfig"}:
            raise HTTPException(409, "A korábbi általános műszaki ügy kapui már nem módosíthatók.")
        if not _can_review_technical_gate(user, row["module_key"], gate_key):
            raise HTTPException(403, "Ezt az ellenőrzési kaput nem értékelheted.")
        review_gate(
            db,
            case_id,
            gate_key,
            str(form.get("status") or ""),
            str(form.get("evidence") or ""),
            user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, "A műszaki ügy vagy kapu nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/technical?module={row['module_key']}#{case_id}", status_code=303)


@app.post("/technical/cases/{case_id}/decision")
async def technical_case_decision(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    form = await request.form()
    try:
        row = get_case(db, case_id)
        if row["module_key"] in {"plotcheck", "housebuild-agent", "buildconfig"}:
            raise HTTPException(
                409,
                "A korábbi általános műszaki ügy nem zárható le; használja a kanonikus modulmunkateret.",
            )
        decision_roles = {"owner", "managing-director", "platform-admin"}
        if row["module_key"] in {"plotcheck", "plancheck"}:
            decision_roles |= {"technical-prep", "designer"}
        if user.role not in decision_roles:
            raise HTTPException(403, "A végső műszaki döntéshez nincs jogosultság.")
        decide_case(
            db, case_id, str(form.get("decision") or ""), str(form.get("reason") or ""), user.email
        )
    except KeyError as exc:
        raise HTTPException(404, "A műszaki ügy nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/technical?module={row['module_key']}#{case_id}", status_code=303)


@app.get("/api/technical/cases")
def api_technical_cases(
    request: Request, module: str = "", project_id: str = "", db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if module and not _can_view_technical_case(user, module):
        raise HTTPException(403, "Nincs jogosultság.")
    rows = list_cases(db, module_key=module or None, project_id=project_id or None)
    return [
        _technical_payload_for_user(row, user)
        for row in rows
        if _can_view_technical_case(user, row["module_key"])
    ]


@app.post("/api/technical/cases")
def api_technical_case_create(
    payload: TechnicalCaseIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    if not _can_create_technical_case(user, payload.module_key):
        raise HTTPException(403, "Nincs jogosultság.")
    if payload.module_key in {"plotcheck", "housebuild-agent", "buildconfig"}:
        raise HTTPException(
            409,
            "A modul általános technikai API-ja kivezetésre került; használja a kanonikus munkafolyamatot.",
        )
    try:
        row = create_case(
            db,
            module_key=payload.module_key,
            project_id=payload.project_id,
            title=payload.title,
            data=payload.input,
            actor=user.email,
            assigned_to=payload.assigned_to,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _technical_payload_for_user(row, user)


@app.post("/api/technical/cases/{case_id}/submit")
def api_technical_case_submit(case_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_session_user(request, db)
    try:
        row = get_case(db, case_id)
        if row["module_key"] in {"plotcheck", "housebuild-agent", "buildconfig"}:
            raise HTTPException(409, "A korábbi általános műszaki ügy csak olvasható.")
        if not _can_create_technical_case(user, row["module_key"]):
            raise HTTPException(403, "Nincs jogosultság.")
        return _technical_payload_for_user(submit_case(db, case_id, user.email), user)
    except KeyError as exc:
        raise HTTPException(404, "A műszaki ügy nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/technical/cases/{case_id}/variant")
def api_technical_housebuild_variant(
    case_id: str,
    payload: TechnicalVariantSelectionIn,
    request: Request,
    db: Session = Depends(get_db),
):
    require_session_user(request, db)
    raise HTTPException(
        409,
        "A korábbi általános HouseBuild API csak olvasható; használja a kanonikus HouseBuild munkafolyamatot.",
    )


@app.post("/api/technical/cases/{case_id}/gates/{gate_key}")
def api_technical_gate_review(
    case_id: str,
    gate_key: str,
    payload: TechnicalGateReviewIn,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_session_user(request, db)
    try:
        row = get_case(db, case_id)
        if row["module_key"] in {"plotcheck", "housebuild-agent", "buildconfig"}:
            raise HTTPException(409, "A korábbi általános műszaki ügy kapui már nem módosíthatók.")
        if not _can_review_technical_gate(user, row["module_key"], gate_key):
            raise HTTPException(403, "Nincs jogosultság.")
        return _technical_payload_for_user(
            review_gate(db, case_id, gate_key, payload.status, payload.evidence, user.email), user
        )
    except KeyError as exc:
        raise HTTPException(404, "A műszaki ügy vagy kapu nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/technical/cases/{case_id}/decision")
def api_technical_case_decision(
    case_id: str, payload: TechnicalDecisionIn, request: Request, db: Session = Depends(get_db)
):
    user = require_session_user(request, db)
    try:
        row = get_case(db, case_id)
        if row["module_key"] in {"plotcheck", "housebuild-agent", "buildconfig"}:
            raise HTTPException(409, "A korábbi általános műszaki ügy nem zárható le.")
        decision_roles = {"owner", "managing-director", "platform-admin"}
        if row["module_key"] in {"plotcheck", "plancheck"}:
            decision_roles |= {"technical-prep", "designer"}
        if user.role not in decision_roles:
            raise HTTPException(403, "Nincs döntési jogosultság.")
        return _technical_payload_for_user(
            decide_case(db, case_id, payload.decision, payload.reason, user.email), user
        )
    except KeyError as exc:
        raise HTTPException(404, "A műszaki ügy nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def _form_datetime(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        if len(value) == 10:
            suffix = "T23:59:00" if end_of_day else "T12:00:00"
            return datetime.fromisoformat(value + suffix).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(422, f"Hibás dátum: {value}")


_OPERATIONS_INTERNAL_ROLES = {
    "owner",
    "managing-director",
    "platform-admin",
    "project-manager",
    "subcontractor",
}


def _require_operations_user(user: User) -> None:
    if user.role not in _OPERATIONS_INTERNAL_ROLES:
        raise HTTPException(403, "A belső projektoperáció ehhez a szerepkörhöz nem érhető el.")


def _require_operations_project(db: Session, user: User, project_id: str) -> None:
    _require_operations_user(user)
    try:
        assert_calendar_project_access(db, user, project_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


def _operations_csrf(request: Request, token: str) -> None:
    _require_ui_csrf(request, token)


@app.get("/operations", response_class=HTMLResponse)
def operations_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    _require_operations_user(user)
    project_ids = calendar_project_ids_for_user(db, user)
    return templates.TemplateResponse(
        request=request,
        name="operations.html",
        context={
            "user": user,
            "summary": operations_summary(db, project_ids=project_ids),
            "portfolio": operations_portfolio(db, project_ids=project_ids),
            "active": "operations",
            "csrf_token": _ui_csrf_token(request),
        },
    )


@app.get("/operations/projects/{project_id}", response_class=HTMLResponse)
def operations_project_page(request: Request, project_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    _require_operations_project(db, user, project_id)
    try:
        data = project_operations(db, project_id)
    except KeyError:
        raise HTTPException(404, "Projekt nem található.")
    return templates.TemplateResponse(
        request=request,
        name="operations_project.html",
        context={
            "user": user,
            **data,
            **internal_partner_projection(db, project_id),
            "active": "operations",
            "requested_tab": request.query_params.get("tab"),
            "csrf_token": _ui_csrf_token(request),
        },
    )


@app.post("/operations/work-packages/{work_package_id}")
def operations_work_package_update(
    request: Request,
    work_package_id: str,
    status: Annotated[str | None, Form()] = None,
    progress_pct: Annotated[int | None, Form()] = None,
    assignee: Annotated[str | None, Form()] = None,
    blocked: Annotated[str | None, Form()] = None,
    block_reason: Annotated[str | None, Form()] = None,
    next_action: Annotated[str | None, Form()] = None,
    project_id: Annotated[str | None, Form()] = None,
    expected_updated_at: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    _operations_csrf(request, csrf_token)
    row = db.scalar(select(PMWorkPackage).where(PMWorkPackage.work_package_id == work_package_id))
    if not row:
        raise HTTPException(404, "Munkacsomag nem található.")
    _require_operations_project(db, user, row.project_id)
    if project_id and project_id != row.project_id:
        raise HTTPException(409, "A munkacsomag nem a megadott projekthez tartozik.")
    try:
        update_work_package(
            db,
            work_package_id,
            WorkPackageUpdateIn(
                status=status,
                progress_pct=progress_pct,
                assignee=assignee or None,
                blocked=blocked == "true" if blocked is not None else None,
                block_reason=block_reason or None,
                next_action=next_action or None,
                expected_updated_at=_form_datetime(expected_updated_at),
            ),
            actor=user.email,
        )
    except KeyError:
        raise HTTPException(404, "Munkacsomag nem található.")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(
        f"/operations/projects/{project_id}" if project_id else "/operations", status_code=303
    )


@app.post("/operations/gates/{gate_id}")
def operations_gate_update(
    request: Request,
    gate_id: str,
    status: Annotated[str, Form()],
    evidence_url: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    project_id: Annotated[str | None, Form()] = None,
    expected_updated_at: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    _operations_csrf(request, csrf_token)
    row = db.scalar(select(PMGateCheck).where(PMGateCheck.gate_id == gate_id))
    if not row:
        raise HTTPException(404, "Kapu nem található.")
    _require_operations_project(db, user, row.project_id)
    if project_id and project_id != row.project_id:
        raise HTTPException(409, "A kapu nem a megadott projekthez tartozik.")
    try:
        update_gate(
            db,
            gate_id,
            GateCheckIn(
                status=status,
                evidence_url=evidence_url or None,
                notes=notes or None,
                checked_by=user.email,
                expected_updated_at=_form_datetime(expected_updated_at),
            ),
            actor=user.email,
        )
    except KeyError:
        raise HTTPException(404, "Kapu nem található.")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(
        f"/operations/projects/{project_id}" if project_id else "/operations", status_code=303
    )


@app.get("/field", response_class=HTMLResponse)
def field_home(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    _require_operations_user(user)
    project_ids = calendar_project_ids_for_user(db, user)
    return templates.TemplateResponse(
        request=request,
        name="field.html",
        context={
            "user": user,
            "projects": field_projects(db, project_ids=project_ids),
            "active": "field",
            "csrf_token": _ui_csrf_token(request),
        },
    )


@app.get("/field/{project_id}", response_class=HTMLResponse)
def field_project(request: Request, project_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    _require_operations_project(db, user, project_id)
    try:
        data = project_operations(db, project_id)
    except KeyError:
        raise HTTPException(404, "Projekt nem található.")
    return templates.TemplateResponse(
        request=request,
        name="field_project.html",
        context={
            "user": user,
            **data,
            "active": "field",
            "csrf_token": _ui_csrf_token(request),
        },
    )


@app.post("/field/{project_id}/daily-report")
def field_daily_report(
    request: Request,
    project_id: str,
    report_date: Annotated[str | None, Form()] = None,
    reporter: Annotated[str, Form()] = "",
    weather: Annotated[str | None, Form()] = None,
    workers_total: Annotated[int, Form()] = 0,
    summary: Annotated[str, Form()] = "",
    blockers: Annotated[str | None, Form()] = None,
    safety_status: Annotated[str, Form()] = "ok",
    quality_status: Annotated[str, Form()] = "ok",
    evidence_url: Annotated[str | None, Form()] = None,
    voice_note_text: Annotated[str | None, Form()] = None,
    source_device_id: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    _operations_csrf(request, csrf_token)
    _require_operations_project(db, user, project_id)
    create_daily_report(
        db,
        DailyReportIn(
            project_id=project_id,
            report_date=_form_datetime(report_date),
            reporter=reporter or user.name,
            weather=weather or None,
            workers_total=workers_total,
            summary=summary,
            blockers=blockers or None,
            safety_status=safety_status,
            quality_status=quality_status,
            evidence_url=evidence_url or None,
            voice_note_text=voice_note_text or None,
            source_device_id=source_device_id or None,
        ),
        actor=user.email,
    )
    return RedirectResponse(f"/field/{project_id}", status_code=303)


@app.post("/field/{project_id}/issues")
def field_issue_create(
    request: Request,
    project_id: str,
    issue_type: Annotated[str, Form()] = "other",
    severity: Annotated[str, Form()] = "medium",
    title: Annotated[str, Form()] = "",
    description: Annotated[str | None, Form()] = None,
    location: Annotated[str | None, Form()] = None,
    responsible: Annotated[str | None, Form()] = None,
    due_at: Annotated[str | None, Form()] = None,
    evidence_url: Annotated[str | None, Form()] = None,
    work_package_id: Annotated[str | None, Form()] = None,
    financial_impact_huf: Annotated[Decimal, Form()] = Decimal("0"),
    deadline_impact_days: Annotated[int, Form()] = 0,
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    _operations_csrf(request, csrf_token)
    _require_operations_project(db, user, project_id)
    create_issue(
        db,
        SiteIssueIn(
            project_id=project_id,
            work_package_id=work_package_id or None,
            issue_type=issue_type,
            severity=severity,
            title=title,
            description=description or None,
            location=location or None,
            responsible=responsible or "Projektvezetés",
            due_at=_form_datetime(due_at, end_of_day=True),
            evidence_url=evidence_url or None,
            financial_impact_huf=financial_impact_huf,
            deadline_impact_days=deadline_impact_days,
        ),
        actor=user.email,
    )
    return RedirectResponse(f"/field/{project_id}", status_code=303)


@app.get("/partner-field-sw.js")
def partner_field_service_worker():
    path = BASE_DIR / "static" / "partner-field-service-worker.js"
    return FileResponse(
        path,
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/partner-field"},
    )


@app.get("/partner-field/login", response_class=HTMLResponse)
def partner_field_login_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="partner_field_login.html", context={"error": None}
    )


@app.post("/partner-field/login", response_class=HTMLResponse)
def partner_field_login(
    request: Request, access_code: Annotated[str, Form()], db: Session = Depends(get_db)
):
    access = authenticate_access(db, access_code)
    if not access:
        return templates.TemplateResponse(
            request=request,
            name="partner_field_login.html",
            context={"error": "Érvénytelen vagy lejárt belépési kód."},
            status_code=401,
        )
    request.session["partner_access_id"] = access.access_id
    audit(
        db,
        actor=f"partner:{access.access_id}",
        action="partner_field.login",
        entity_type="partner_field_access",
        entity_id=access.access_id,
    )
    db.commit()
    return RedirectResponse("/partner-field", status_code=303)


@app.post("/partner-field/logout")
def partner_field_logout(request: Request):
    request.session.pop("partner_access_id", None)
    return RedirectResponse("/partner-field/login", status_code=303)


@app.get("/partner-field", response_class=HTMLResponse)
def partner_field_home(request: Request, db: Session = Depends(get_db)):
    access, redirect = partner_auth_or_redirect(request, db)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="partner_field.html",
        context={
            **partner_dashboard(db, access),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@app.post("/partner-field/attendance")
def partner_field_attendance(
    request: Request,
    action: Annotated[str, Form()],
    worker_ids: Annotated[list[str], Form()],
    declaration_accepted: Annotated[bool, Form()] = False,
    latitude: Annotated[Decimal | None, Form()] = None,
    longitude: Annotated[Decimal | None, Form()] = None,
    accuracy_m: Annotated[Decimal | None, Form()] = None,
    source_device_id: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    access, redirect = partner_auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        attendance_action(
            db,
            access,
            PartnerAttendanceActionIn(
                worker_ids=worker_ids,
                action=action,
                declaration_accepted=declaration_accepted,
                latitude=latitude,
                longitude=longitude,
                accuracy_m=accuracy_m,
                source_device_id=source_device_id,
                note=note or None,
            ),
        )
    except (ValueError, PermissionError) as exc:
        return RedirectResponse(f"/partner-field?error={str(exc)}", status_code=303)
    label = "Érkezés" if action == "check_in" else "Távozás"
    return RedirectResponse(f"/partner-field?message={label} rögzítve.", status_code=303)


@app.post("/partner-field/progress")
def partner_field_progress(
    request: Request,
    summary: Annotated[str, Form()],
    reported_progress_pct: Annotated[int | None, Form()] = None,
    quantity: Annotated[Decimal | None, Form()] = None,
    unit: Annotated[str | None, Form()] = None,
    problem_text: Annotated[str | None, Form()] = None,
    safety_note: Annotated[str | None, Form()] = None,
    quality_note: Annotated[str | None, Form()] = None,
    source_device_id: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    access, redirect = partner_auth_or_redirect(request, db)
    if redirect:
        return redirect
    create_progress(
        db,
        access,
        PartnerProgressIn(
            reported_progress_pct=reported_progress_pct,
            quantity=quantity,
            unit=unit or None,
            summary=summary,
            problem_text=problem_text or None,
            safety_note=safety_note or None,
            quality_note=quality_note or None,
            source_device_id=source_device_id,
        ),
    )
    return RedirectResponse(
        "/partner-field?message=Haladási jelentés beküldve ellenőrzésre.", status_code=303
    )


@app.post("/partner-field/issues")
def partner_field_issue(
    request: Request,
    issue_type: Annotated[str, Form()],
    severity: Annotated[str, Form()],
    title: Annotated[str, Form()],
    description: Annotated[str | None, Form()] = None,
    location: Annotated[str | None, Form()] = None,
    source_device_id: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    access, redirect = partner_auth_or_redirect(request, db)
    if redirect:
        return redirect
    create_partner_issue(
        db,
        access,
        issue_type=issue_type,
        severity=severity,
        title=title,
        description=description or None,
        location=location or None,
        source_device_id=source_device_id,
    )
    return RedirectResponse(
        "/partner-field?message=Probléma rögzítve és továbbítva a projektvezetésnek.",
        status_code=303,
    )


@app.post("/partner-field/changes")
def partner_field_change(
    request: Request,
    change_type: Annotated[str, Form()],
    title: Annotated[str, Form()],
    description: Annotated[str, Form()],
    requested_by: Annotated[str | None, Form()] = None,
    deadline_impact_days: Annotated[int, Form()] = 0,
    source_device_id: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    access, redirect = partner_auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        create_change(
            db,
            access,
            PartnerChangeIn(
                change_type=change_type,
                title=title,
                description=description,
                requested_by=requested_by or None,
                deadline_impact_days=deadline_impact_days,
                source_device_id=source_device_id,
            ),
        )
    except PermissionError as exc:
        return RedirectResponse(f"/partner-field?error={str(exc)}", status_code=303)
    return RedirectResponse(
        "/partner-field?message=Változásbejelentés rögzítve. Jóváhagyásig nem módosítja a scope-ot vagy az árat.",
        status_code=303,
    )


@app.post("/partner-field/photos")
async def partner_field_photos(
    request: Request,
    photos: list[UploadFile] = File(...),
    category: Annotated[str, Form()] = "progress",
    caption: Annotated[str | None, Form()] = None,
    progress_report_id: Annotated[str | None, Form()] = None,
    change_notice_id: Annotated[str | None, Form()] = None,
    latitude: Annotated[Decimal | None, Form()] = None,
    longitude: Annotated[Decimal | None, Form()] = None,
    source_device_id: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    access, redirect = partner_auth_or_redirect(request, db)
    if redirect:
        return redirect
    saved = 0
    try:
        for photo in photos[:10]:
            raw = await photo.read()
            save_evidence(
                db,
                access,
                file_name=photo.filename or "helyszini-foto",
                mime_type=photo.content_type or "",
                raw=raw,
                category=category,
                caption=caption or None,
                progress_report_id=progress_report_id or None,
                issue_id=None,
                change_notice_id=change_notice_id or None,
                latitude=latitude,
                longitude=longitude,
                source_device_id=source_device_id,
                storage_root=PARTNER_EVIDENCE_DIR,
            )
            saved += 1
    except (ValueError, PermissionError) as exc:
        return RedirectResponse(f"/partner-field?error={str(exc)}", status_code=303)
    return RedirectResponse(f"/partner-field?message={saved} fotó feltöltve.", status_code=303)


@app.get("/partner-field/evidence/{evidence_id}")
def partner_field_evidence(request: Request, evidence_id: str, db: Session = Depends(get_db)):
    row = db.scalar(select(PartnerEvidence).where(PartnerEvidence.evidence_id == evidence_id))
    if not row:
        raise HTTPException(404, "Kép nem található.")
    user = current_user(request, db)
    access = current_partner_access(request, db)
    if user is None and (
        access is None or not access_is_valid(access) or access.access_id != row.access_id
    ):
        raise HTTPException(403, "Nincs jogosultság a képhez.")
    path = Path(row.storage_path)
    if not path.exists():
        raise HTTPException(404, "A képfájl nem található.")
    return FileResponse(path, media_type=row.mime_type, filename=row.file_name)


@app.post("/operations/projects/{project_id}/partner-accesses")
def operations_partner_access_create(
    request: Request,
    project_id: str,
    company_name: Annotated[str, Form()],
    access_code: Annotated[str, Form()],
    work_package_id: Annotated[str | None, Form()] = None,
    contact_name: Annotated[str | None, Form()] = None,
    contact_phone: Annotated[str | None, Form()] = None,
    company_tax_number: Annotated[str | None, Form()] = None,
    worker_names: Annotated[str | None, Form()] = None,
    valid_until: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    _operations_csrf(request, csrf_token)
    _require_operations_project(db, user, project_id)
    try:
        create_access(
            db,
            PartnerAccessCreateIn(
                company_name=company_name,
                project_id=project_id,
                work_package_id=work_package_id or None,
                contact_name=contact_name or None,
                contact_phone=contact_phone or None,
                company_tax_number=company_tax_number or None,
                access_code=access_code,
                worker_names=[x.strip() for x in (worker_names or "").splitlines() if x.strip()],
                valid_until=_form_datetime(valid_until, end_of_day=True),
            ),
            actor=user.email,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/operations/projects/{project_id}?tab=partners", status_code=303)


@app.post("/operations/partner-accesses/{access_id}/deactivate")
def operations_partner_access_deactivate(
    request: Request,
    access_id: str,
    project_id: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    _operations_csrf(request, csrf_token)
    row = db.scalar(select(PartnerFieldAccess).where(PartnerFieldAccess.access_id == access_id))
    if not row:
        raise HTTPException(404, "Hozzáférés nem található.")
    _require_operations_project(db, user, row.project_id)
    if project_id != row.project_id:
        raise HTTPException(409, "A hozzáférés nem a megadott projekthez tartozik.")
    try:
        deactivate_access(db, access_id, actor=user.email)
    except KeyError:
        raise HTTPException(404, "Hozzáférés nem található.")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/operations/projects/{project_id}?tab=partners", status_code=303)


@app.post("/operations/partner-progress/{progress_report_id}/review")
def operations_partner_progress_review(
    request: Request,
    progress_report_id: str,
    project_id: Annotated[str, Form()],
    decision: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    _operations_csrf(request, csrf_token)
    row = db.scalar(
        select(PartnerProgressReport).where(
            PartnerProgressReport.progress_report_id == progress_report_id
        )
    )
    if not row:
        raise HTTPException(404, "Haladási jelentés nem található.")
    _require_operations_project(db, user, row.project_id)
    if project_id != row.project_id:
        raise HTTPException(409, "A jelentés nem a megadott projekthez tartozik.")
    try:
        review_progress(db, progress_report_id, decision, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/operations/projects/{project_id}?tab=partners", status_code=303)


@app.get("/procurement/workbench", response_class=HTMLResponse)
def procurement_workbench(
    request: Request, project_id: str | None = None, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
    return templates.TemplateResponse(
        request=request,
        name="procurement_workbench.html",
        context={
            "user": user,
            "projects": projects,
            "selected_project_id": project_id,
            **procurement_summary(db, project_id),
            **procurement_workspace(db, project_id),
            "active": "procurement",
        },
    )


@app.get("/procurement/projects/{project_id}", response_class=HTMLResponse)
def procurement_project(request: Request, project_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if not project:
        raise HTTPException(404, "Projekt nem található.")
    return templates.TemplateResponse(
        request=request,
        name="procurement_project.html",
        context={
            "user": user,
            "project": project,
            **procurement_summary(db, project_id),
            **procurement_workspace(db, project_id),
            "active": "procurement",
        },
    )


@app.post("/procurement/projects/{project_id}/requirements")
async def procurement_requirement_create_ui(
    request: Request, project_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        create_procurement_requirement(
            db,
            ProcurementRequirementIn(
                project_id=project_id,
                work_package_id=_optional_form_text(form.get("work_package_id")),
                category=str(form["category"]),
                scope_description=str(form["scope_description"]),
                specification=str(form["specification"]),
                net_quantity=Decimal(str(form["net_quantity"])),
                waste_pct=Decimal(str(form.get("waste_pct") or 0)),
                unit=str(form["unit"]),
                required_at=_required_form_datetime(form["required_at"]),
                budget_huf=Decimal(str(form["budget_huf"])),
                target_huf=Decimal(str(form["target_huf"])),
            ),
            actor=user.email,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/requirements/{requirement_id}/approve")
async def procurement_requirement_approve_ui(
    request: Request, requirement_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    project_id = str(form["project_id"])
    try:
        approve_procurement_requirement(
            db, requirement_id, str(form["stage"]), user.email, user.role
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/requirements/{requirement_id}/offers")
async def procurement_offer_create_ui(
    request: Request, requirement_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    project_id = str(form["project_id"])
    try:
        add_procurement_offer(
            db,
            ProcurementOfferIn(
                requirement_id=requirement_id,
                supplier_name=str(form["supplier_name"]),
                partner_id=_optional_form_text(form.get("partner_id")),
                net_total_huf=Decimal(str(form["net_total_huf"])),
                delivery_cost_huf=Decimal(str(form.get("delivery_cost_huf") or 0)),
                other_landed_cost_huf=Decimal(str(form.get("other_landed_cost_huf") or 0)),
                lead_time_days=_form_int(form.get("lead_time_days")),
                warranty_months=_form_int(form.get("warranty_months")),
                payment_terms=str(form["payment_terms"]),
                risk_score=_form_int(form.get("risk_score")),
                technical_compliant=str(form.get("technical_compliant") or "").lower()
                in {"1", "true", "on", "yes"},
                document_ref=str(form["document_ref"]),
                notes=_optional_form_text(form.get("notes")),
            ),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/requirements/{requirement_id}/revise")
async def procurement_requirement_revise_ui(
    request: Request, requirement_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    project_id = str(form["project_id"])
    try:
        revise_procurement_requirement(
            db,
            requirement_id,
            net_quantity=Decimal(str(form["net_quantity"])),
            waste_pct=Decimal(str(form.get("waste_pct") or 0)),
            budget_huf=Decimal(str(form["budget_huf"])),
            target_huf=Decimal(str(form["target_huf"])),
            reason=str(form["reason"]),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/requirements/{requirement_id}/substitutions")
async def procurement_substitution_create_ui(
    request: Request, requirement_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    project_id = str(form["project_id"])
    try:
        create_procurement_substitution_review(
            db,
            ProcurementSubstitutionIn(
                requirement_id=requirement_id,
                proposed_product=str(form["proposed_product"]),
                proposed_specification=str(form["proposed_specification"]),
                technical_equivalence=str(form["technical_equivalence"]),
                declaration_ref=str(form["declaration_ref"]),
                price_impact_huf=Decimal(str(form.get("price_impact_huf") or 0)),
                schedule_impact_days=_form_int(form.get("schedule_impact_days")),
                risk_assessment=str(form["risk_assessment"]),
                rationale=str(form["rationale"]),
            ),
            user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/substitutions/{review_id}/review")
async def procurement_substitution_review_ui(
    request: Request, review_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    project_id = str(form["project_id"])
    try:
        review_procurement_substitution(db, review_id, str(form["decision"]), user.email, user.role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/requirements/{requirement_id}/selections")
async def procurement_selection_create_ui(
    request: Request, requirement_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    project_id = str(form["project_id"])
    try:
        select_procurement_offer(
            db,
            ProcurementSelectionIn(
                requirement_id=requirement_id,
                offer_id=str(form["offer_id"]),
                market_evidence_ref=_optional_form_text(form.get("market_evidence_ref")),
                rationale=str(form["rationale"]),
                risk_rationale=str(form["risk_rationale"]),
            ),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/selections/{selection_id}/approve")
async def procurement_selection_approve_ui(
    request: Request, selection_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    project_id = str(form["project_id"])
    try:
        approve_procurement_selection(
            db,
            selection_id,
            str(form["stage"]),
            user.email,
            user.role,
            str(form.get("decision") or "approve") == "approve",
            _optional_form_text(form.get("note")),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/selections/{selection_id}/orders")
async def procurement_order_create_ui(
    request: Request, selection_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    project_id = str(form["project_id"])
    try:
        create_procurement_order(
            db,
            ProcurementOrderIn(
                selection_id=selection_id,
                ordered_quantity=Decimal(str(form["ordered_quantity"])),
                delivery_due=_required_form_datetime(form["delivery_due"]),
            ),
            actor=user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/orders/{order_id}/confirm")
async def procurement_order_confirm_ui(
    request: Request, order_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    project_id = str(form["project_id"])
    try:
        confirm_procurement_order(db, order_id, user.email)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/projects/{project_id}/invoice-matches")
async def procurement_invoice_match_ui(
    request: Request, project_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        create_procurement_invoice_match(
            db,
            ProcurementInvoiceMatchIn(
                order_id=str(form["order_id"]),
                delivery_note_id=str(form["delivery_note_id"]),
                invoice_reference=str(form["invoice_reference"]),
                invoice_total_huf=Decimal(str(form["invoice_total_huf"])),
            ),
            user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/deviations/{deviation_id}/resolve")
async def procurement_deviation_resolve_ui(
    request: Request, deviation_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    project_id = str(form["project_id"])
    try:
        resolve_procurement_deviation(db, deviation_id, str(form["resolution"]), user.email)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/projects/{project_id}/delivery-notes")
def procurement_delivery_create(
    request: Request,
    project_id: str,
    order_id: Annotated[str, Form()],
    receiver: Annotated[str, Form()],
    item_summary: Annotated[str, Form()],
    ordered_quantity: Annotated[Decimal, Form()],
    received_quantity: Annotated[Decimal, Form()],
    unit: Annotated[str, Form()] = "db",
    note_number: Annotated[str | None, Form()] = None,
    source_url: Annotated[str | None, Form()] = None,
    received_at: Annotated[str | None, Form()] = None,
    actual_specification: Annotated[str | None, Form()] = None,
    quality_status: Annotated[str, Form()] = "accepted",
    damage_or_shortage: Annotated[str | None, Form()] = None,
    plan_match: Annotated[str, Form()] = "matched",
    document_status: Annotated[str, Form()] = "complete",
    performance_declaration_status: Annotated[str, Form()] = "pending",
    elog_evidence_status: Annotated[str, Form()] = "pending",
    storage_location: Annotated[str | None, Form()] = None,
    custodian: Annotated[str | None, Form()] = None,
    weather_protection: Annotated[str, Form()] = "not_checked",
    evidence_url: Annotated[str | None, Form()] = None,
    supplier_signed: Annotated[bool, Form()] = False,
    receiver_signed: Annotated[bool, Form()] = False,
    signature_evidence_ref: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        create_delivery_note(
            db,
            DeliveryNoteIn(
                order_id=order_id,
                project_id=project_id,
                note_number=note_number or None,
                source_url=source_url or None,
                received_at=_form_datetime(received_at),
                receiver=receiver,
                item_summary=item_summary,
                ordered_quantity=ordered_quantity,
                received_quantity=received_quantity,
                unit=unit,
                actual_specification=actual_specification or None,
                quality_status=quality_status,
                damage_or_shortage=damage_or_shortage or None,
                plan_match=plan_match,
                document_status=document_status,
                performance_declaration_status=performance_declaration_status,
                elog_evidence_status=elog_evidence_status,
                storage_location=storage_location or None,
                custodian=custodian or None,
                weather_protection=weather_protection,
                evidence_url=evidence_url or None,
                supplier_signed=supplier_signed,
                receiver_signed=receiver_signed,
                signature_evidence_ref=signature_evidence_ref or None,
            ),
            actor=user.email,
        )
    except KeyError:
        raise HTTPException(404, "Rendelés nem található.")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/projects/{project_id}/movements")
def procurement_movement_create(
    request: Request,
    project_id: str,
    lot_id: Annotated[str, Form()],
    movement_type: Annotated[str, Form()],
    quantity: Annotated[Decimal, Form()],
    from_location: Annotated[str | None, Form()] = None,
    to_location: Annotated[str | None, Form()] = None,
    responsible: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    occurred_at: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        create_material_movement(
            db,
            MaterialMovementIn(
                lot_id=lot_id,
                movement_type=movement_type,
                quantity=quantity,
                from_location=from_location or None,
                to_location=to_location or None,
                responsible=responsible or user.name,
                note=note or None,
                occurred_at=_form_datetime(occurred_at),
            ),
            actor=user.email,
        )
    except KeyError:
        raise HTTPException(404, "Anyaglot nem található.")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/projects/{project_id}/usage-controls")
def procurement_usage_create(
    request: Request,
    project_id: str,
    planned_quantity: Annotated[Decimal, Form()],
    actual_quantity: Annotated[Decimal, Form()],
    waste_pct: Annotated[Decimal, Form()] = Decimal("0"),
    unit: Annotated[str, Form()] = "db",
    unit_cost_huf: Annotated[Decimal, Form()] = Decimal("0"),
    damage_huf: Annotated[Decimal, Form()] = Decimal("0"),
    work_package_id: Annotated[str | None, Form()] = None,
    lot_id: Annotated[str | None, Form()] = None,
    subcontractor: Annotated[str | None, Form()] = None,
    contractual_basis: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    create_usage_control(
        db,
        MaterialUsageIn(
            project_id=project_id,
            work_package_id=work_package_id or None,
            lot_id=lot_id or None,
            subcontractor=subcontractor or None,
            planned_quantity=planned_quantity,
            waste_pct=waste_pct,
            actual_quantity=actual_quantity,
            unit=unit,
            unit_cost_huf=unit_cost_huf,
            damage_huf=damage_huf,
            contractual_basis=contractual_basis or None,
        ),
        actor=user.email,
    )
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.get("/housevision", response_class=HTMLResponse)
def housevision_workbench(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="housevision.html",
        context={
            "user": user,
            "active": "housevision",
            "csrf_token": _ui_csrf_token(request),
            "permissions": housevision_action_permissions(user.role),
            **housevision_workspace(
                db,
                status=request.query_params.get("status"),
                brand_id=request.query_params.get("brand_id"),
                search=request.query_params.get("q"),
            ),
        },
    )


@app.get("/buildconfig/cases/{case_id}/compare", response_class=HTMLResponse)
def buildconfig_compare_page(case_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if not _can_view_technical_case(user, "buildconfig"):
        raise HTTPException(403, "A BuildConfig összehasonlításhoz nincs jogosultsága.")
    try:
        comparison = compare_buildconfig_versions(
            db,
            case_id,
            left_version_id=request.query_params.get("left"),
            right_version_id=request.query_params.get("right"),
        )
    except KeyError as exc:
        raise HTTPException(
            404, "A kiválasztott BuildConfig-verzió nem található ebben az ügyben."
        ) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="buildconfig_compare.html",
        context={
            "user": user,
            "active": "technical",
            "comparison": comparison,
            "show_internal": user.role
            in {"owner", "managing-director", "finance", "platform-admin"},
        },
    )


@app.get("/housevision/jobs/{job_id}", response_class=HTMLResponse)
def housevision_job_page(request: Request, job_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        context = housevision_job_detail(db, job_id)
    except KeyError as exc:
        raise HTTPException(404, "A HouseVision job nem található.") from exc
    return templates.TemplateResponse(
        request=request,
        name="housevision_detail.html",
        context={
            "user": user,
            "active": "housevision",
            "csrf_token": _ui_csrf_token(request),
            "permissions": housevision_action_permissions(user.role),
            **context,
        },
    )


@app.get("/housevision/jobs/{job_id}/upload", response_class=HTMLResponse)
def housevision_upload_page(request: Request, job_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        context = housevision_job_detail(db, job_id)
    except KeyError as exc:
        raise HTTPException(404, "A HouseVision job nem található.") from exc
    return templates.TemplateResponse(
        request=request,
        name="housevision_upload.html",
        context={
            "user": user,
            "active": "housevision",
            "csrf_token": _ui_csrf_token(request),
            "permissions": housevision_action_permissions(user.role),
            **context,
        },
    )


@app.get("/housevision/jobs/{job_id}/compare", response_class=HTMLResponse)
def housevision_compare_page(request: Request, job_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        context = housevision_job_detail(db, job_id)
    except KeyError as exc:
        raise HTTPException(404, "A HouseVision job nem található.") from exc
    return templates.TemplateResponse(
        request=request,
        name="housevision_compare.html",
        context={"user": user, "active": "housevision", **context},
    )


@app.post("/housevision/rights")
async def housevision_rights_create_ui(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "rights_manage")
        form = await request.form()
        _require_ui_csrf(request, form.get("csrf_token"))
        create_housevision_rights(
            db,
            HouseVisionRightsPolicyIn(
                domain=str(form["domain"]),
                path_prefix=str(form.get("path_prefix") or "/"),
                rights_status=str(form["rights_status"]),
                evidence_ref=str(form["evidence_ref"]),
                grant_id=_optional_form_text(form.get("grant_id")),
                owner_attestation_sha256=_optional_form_text(form.get("owner_attestation_sha256")),
                page_scope_sha256=_optional_form_text(form.get("page_scope_sha256")),
                attribution_required=bool(form.get("attribution_required")),
                attribution_text=_optional_form_text(form.get("attribution_text")),
                crawl_delay_seconds=_form_int(form.get("crawl_delay_seconds"), 2),
                max_assets_per_page=_form_int(form.get("max_assets_per_page"), 12),
            ),
            user.email,
            user.role,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/housevision", status_code=303)


@app.post("/housevision/rights/{policy_id}/approve")
def housevision_rights_approve_ui(
    request: Request,
    policy_id: str,
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "rights_approve")
        _require_ui_csrf(request, csrf_token)
        approve_housevision_rights(db, policy_id, user.email, user.role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/housevision", status_code=303)


@app.post("/housevision/jobs")
async def housevision_job_create_ui(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "job_create")
        form = await request.form()
        _require_ui_csrf(request, form.get("csrf_token"))
        row = create_housevision_job(
            db,
            str(form["brand_id"]),
            str(form["source_url"]),
            user.email,
            operation_mode=str(form.get("operation_mode") or "package_only"),
            render_provider=str(form.get("render_provider") or "mock"),
        )
        if row.status == "SOURCE_CRAWL":
            try:
                auto_ingest_housevision_sources(db, row.job_id, user.email)
            except ValueError:
                # The job and the fail-closed ingest finding stay visible for manual review/retry.
                pass
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return RedirectResponse(f"/housevision/jobs/{row.job_id}", status_code=303)


@app.post("/housevision/jobs/{job_id}/sources/auto-import")
def housevision_source_auto_import_ui(
    request: Request,
    job_id: str,
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "source_manage")
        _require_ui_csrf(request, csrf_token)
        auto_ingest_housevision_sources(db, job_id, user.email)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return RedirectResponse(f"/housevision/jobs/{job_id}", status_code=303)


@app.post("/housevision/jobs/{job_id}/rights-recheck")
def housevision_rights_recheck_ui(
    request: Request,
    job_id: str,
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "job_create")
        _require_ui_csrf(request, csrf_token)
        row = recheck_housevision_rights(db, job_id, user.email)
        if row.status == "SOURCE_CRAWL" and housevision_action_permissions(user.role)[
            "source_manage"
        ]:
            try:
                auto_ingest_housevision_sources(db, job_id, user.email)
            except ValueError:
                pass
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return RedirectResponse(f"/housevision/jobs/{job_id}", status_code=303)


@app.post("/housevision/jobs/{job_id}/sources")
async def housevision_source_create_ui(
    request: Request, job_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "source_manage")
        form = await request.form()
        _require_ui_csrf(request, form.get("csrf_token"))
        add_housevision_source(
            db,
            job_id,
            HouseVisionSourceAssetIn(
                source_url=str(form["source_url"]),
                asset_type=str(form["asset_type"]),
                sequence=_form_int(form["sequence"]),
                content_sha256=str(form["content_sha256"]),
                width_px=_form_int(form["width_px"]),
                height_px=_form_int(form["height_px"]),
                magic_mime_type=str(form["magic_mime_type"]),
            ),
            user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return RedirectResponse(f"/housevision/jobs/{job_id}", status_code=303)


@app.post("/housevision/jobs/{job_id}/geometry-lock")
async def housevision_geometry_ui(request: Request, job_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "geometry_lock")
        form = await request.form()
        _require_ui_csrf(request, form.get("csrf_token"))
        lock_housevision_geometry(
            db,
            job_id,
            HouseVisionGeometryLockIn(
                floorplan_topology_sha256=str(form["floorplan_topology_sha256"]),
                massing_signature=str(form["massing_signature"]),
                roof_form=str(form["roof_form"]),
                roof_pitch_deg=Decimal(str(form["roof_pitch_deg"]))
                if form.get("roof_pitch_deg")
                else None,
                storey_count=_form_int(form["storey_count"]),
                window_count=_form_int(form["window_count"]),
                door_count=_form_int(form["door_count"]),
                width_depth_height_ratio=str(form["width_depth_height_ratio"]),
                immutable_features=[
                    item.strip()
                    for item in str(form["immutable_features"]).split(",")
                    if item.strip()
                ],
            ),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/housevision/jobs/{job_id}", status_code=303)


@app.post("/housevision/jobs/{job_id}/geometry-lock/auto")
def housevision_geometry_auto_ui(
    request: Request,
    job_id: str,
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "source_manage")
        _require_ui_csrf(request, csrf_token)
        auto_lock_housevision_geometry(db, job_id, user.email)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/housevision/jobs/{job_id}", status_code=303)


@app.post("/housevision/jobs/{job_id}/renders/generate")
def housevision_render_generate_ui(
    request: Request,
    job_id: str,
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "source_manage")
        _require_ui_csrf(request, csrf_token)
        rendered = generate_typehouse_renders(db, job_id, user.email)
        if rendered.get("created"):
            create_housevision_source_baseline(db, job_id, user.email)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/housevision/jobs/{job_id}", status_code=303)


@app.post("/housevision/jobs/{job_id}/name")
async def housevision_name_ui(request: Request, job_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "name_assign")
        form = await request.form()
        _require_ui_csrf(request, form.get("csrf_token"))
        assign_housevision_name(db, job_id, str(form["public_name"]), user.email)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return RedirectResponse(f"/housevision/jobs/{job_id}", status_code=303)


@app.post("/housevision/jobs/{job_id}/outputs")
async def housevision_output_ui(request: Request, job_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "output_manage")
        form = await request.form()
        _require_ui_csrf(request, form.get("csrf_token"))
        add_housevision_output(
            db,
            job_id,
            HouseVisionOutputAssetIn(
                source_visual_id=str(form["source_visual_id"]),
                provider_job_id=str(form["provider_job_id"]),
                output_ref=str(form["output_ref"]),
                content_sha256=str(form["content_sha256"]),
                width_px=_form_int(form["width_px"]),
                height_px=_form_int(form["height_px"]),
                edge_overlap=Decimal(str(form["edge_overlap"])),
                roof_match=Decimal(str(form["roof_match"])),
                opening_match=Decimal(str(form["opening_match"])),
                floorplan_fidelity=Decimal(str(form["floorplan_fidelity"]))
                if form.get("floorplan_fidelity")
                else None,
                full_house_in_frame=bool(form.get("full_house_in_frame")),
                daylight_pass=bool(form.get("daylight_pass")),
                photorealism_pass=bool(form.get("photorealism_pass")),
                brand_identity_pass=bool(form.get("brand_identity_pass")),
                privacy_pass=bool(form.get("privacy_pass")),
            ),
            user.email,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return RedirectResponse(f"/housevision/jobs/{job_id}", status_code=303)


@app.post("/housevision/jobs/{job_id}/qa")
def housevision_qa_ui(
    request: Request,
    job_id: str,
    csrf_token: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "qa_run")
        _require_ui_csrf(request, csrf_token)
        run_housevision_qa(db, job_id, user.email)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return RedirectResponse(f"/housevision/jobs/{job_id}", status_code=303)


@app.post("/housevision/jobs/{job_id}/bind")
async def housevision_bind_ui(request: Request, job_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "houseplan_bind")
        form = await request.form()
        _require_ui_csrf(request, form.get("csrf_token"))
        bind_housevision_houseplan(db, job_id, str(form["house_id"]), user.email, user.role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return RedirectResponse(f"/housevision/jobs/{job_id}", status_code=303)


@app.post("/housevision/jobs/{job_id}/package")
async def housevision_package_ui(request: Request, job_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        ensure_housevision_action(user.role, "package_release")
        form = await request.form()
        _require_ui_csrf(request, form.get("csrf_token"))
        package_housevision_job(db, job_id, str(form["storage_ref"]), user.email)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return RedirectResponse(f"/housevision/jobs/{job_id}", status_code=303)


@app.post("/api/housevision/rights", dependencies=[Depends(require_api_token)])
def api_housevision_rights(payload: HouseVisionRightsPolicyIn, db: Session = Depends(get_db)):
    row = create_housevision_rights(db, payload, "api", "platform-admin")
    return {"policy_id": row.policy_id, "active": row.active}


@app.post("/api/housevision/rights/{policy_id}/approve", dependencies=[Depends(require_api_token)])
def api_housevision_rights_approve(policy_id: str, db: Session = Depends(get_db)):
    try:
        row = approve_housevision_rights(db, policy_id, "api-legal", "platform-admin")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"policy_id": row.policy_id, "active": row.active}


@app.post("/api/housevision/jobs", dependencies=[Depends(require_api_token)])
def api_housevision_job(payload: HouseVisionJobIn, db: Session = Depends(get_db)):
    try:
        row = create_housevision_job(
            db,
            payload.brand_id,
            payload.source_url,
            "api",
            operation_mode=payload.operation_mode,
            render_provider=payload.render_provider,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": row.job_id, "status": row.status, "rights_policy_id": row.rights_policy_id}


@app.post(
    "/api/housevision/jobs/{job_id}/rights-recheck", dependencies=[Depends(require_api_token)]
)
def api_housevision_rights_recheck(job_id: str, db: Session = Depends(get_db)):
    try:
        row = recheck_housevision_rights(db, job_id, "api")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": row.job_id, "status": row.status, "rights_policy_id": row.rights_policy_id}


@app.post("/api/housevision/jobs/{job_id}/sources", dependencies=[Depends(require_api_token)])
def api_housevision_source(
    job_id: str, payload: HouseVisionSourceAssetIn, db: Session = Depends(get_db)
):
    try:
        row = add_housevision_source(db, job_id, payload, "api")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"source_visual_id": row.source_visual_id, "status": row.status}


@app.post("/api/housevision/jobs/{job_id}/geometry-lock", dependencies=[Depends(require_api_token)])
def api_housevision_geometry(
    job_id: str, payload: HouseVisionGeometryLockIn, db: Session = Depends(get_db)
):
    try:
        row = lock_housevision_geometry(db, job_id, payload, "api", "platform-admin")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"geometry_lock_id": row.geometry_lock_id, "content_sha256": row.content_sha256}


@app.post("/api/housevision/jobs/{job_id}/outputs", dependencies=[Depends(require_api_token)])
def api_housevision_output(
    job_id: str, payload: HouseVisionOutputAssetIn, db: Session = Depends(get_db)
):
    try:
        row = add_housevision_output(db, job_id, payload, "api")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"output_visual_id": row.output_visual_id, "revision": row.revision}


@app.post("/api/housevision/jobs/{job_id}/name", dependencies=[Depends(require_api_token)])
def api_housevision_name(job_id: str, public_name: str, db: Session = Depends(get_db)):
    try:
        row = assign_housevision_name(db, job_id, public_name, "api")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"house_name_id": row.house_name_id, "public_name": row.public_name}


@app.post(
    "/api/housevision/jobs/{job_id}/bind/{house_id}", dependencies=[Depends(require_api_token)]
)
def api_housevision_bind(job_id: str, house_id: str, db: Session = Depends(get_db)):
    try:
        row = bind_housevision_houseplan(db, job_id, house_id, "api", "platform-admin")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "job_id": row.job_id,
        "house_id": row.house_id,
        "publication_eligibility": row.publication_eligibility,
    }


@app.post("/api/housevision/jobs/{job_id}/qa", dependencies=[Depends(require_api_token)])
def api_housevision_qa(job_id: str, db: Session = Depends(get_db)):
    try:
        row = run_housevision_qa(db, job_id, "api")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "qa_report_id": row.qa_report_id,
        "status": row.status,
        "automatic_retry": row.automatic_retry,
    }


@app.post("/api/housevision/jobs/{job_id}/package", dependencies=[Depends(require_api_token)])
def api_housevision_package(job_id: str, storage_ref: str, db: Session = Depends(get_db)):
    try:
        row = package_housevision_job(db, job_id, storage_ref, "api")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "package_id": row.package_id,
        "manifest_sha256": row.manifest_sha256,
        "publication_status": row.publication_status,
    }


@app.get("/website-content-control", response_class=HTMLResponse)
def website_content_control(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="website_content_control.html",
        context={
            "user": user,
            "active": "website-content-control",
            **website_content_workspace(db),
        },
    )


@app.post("/website-content-control/sites")
async def website_site_create_ui(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        register_website_site(
            db,
            WebsiteSiteIn(
                brand_id=str(form["brand_id"]),
                name=str(form["name"]),
                base_url=str(form["base_url"]),
                adapter_endpoint=str(form["adapter_endpoint"]),
                credential_ref=str(form["credential_ref"]),
            ),
            user.email,
            user.role,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/website-content-control", status_code=303)


@app.post("/website-content-control/sites/{site_id}/kill-switch")
async def website_kill_switch_ui(request: Request, site_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        set_website_kill_switch(
            db,
            site_id,
            str(form.get("enabled") or "false").lower() == "true",
            str(form["reason"]),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/website-content-control", status_code=303)


@app.post("/website-content-control/releases")
async def website_release_create_ui(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    site_ids = [value.strip() for value in str(form["site_ids"]).split(",") if value.strip()]
    try:
        create_website_release(
            db,
            WebsiteReleaseIn(
                asset_id=str(form["asset_id"]),
                targets=[
                    WebsiteTargetIn(
                        site_id=site_id,
                        route_path=str(form["route_path"]),
                        locale=str(form.get("locale") or "hu-HU"),
                    )
                    for site_id in site_ids
                ],
            ),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/website-content-control", status_code=303)


@app.post("/website-content-control/releases/{release_id}/dispatch")
def website_release_dispatch_ui(request: Request, release_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        dispatch_website_release(db, release_id, user.email, user.role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/website-content-control", status_code=303)


@app.post("/website-content-control/targets/{target_id}/receipt")
async def website_receipt_ui(request: Request, target_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        record_website_receipt(
            db,
            WebsiteDeliveryReceiptIn(
                target_id=target_id,
                idempotency_key=target_id,
                success=True,
                external_version_id=str(form["external_version_id"]),
                published_url=str(form["published_url"]),
                rendered_content_sha256=str(form["rendered_content_sha256"]),
            ),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/website-content-control", status_code=303)


@app.post("/website-content-control/targets/{target_id}/smoke")
async def website_smoke_ui(request: Request, target_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        record_website_smoke(
            db,
            target_id,
            WebsiteSmokeTestIn(
                http_status=_form_int(form["http_status"]),
                rendered_content_sha256=str(form["rendered_content_sha256"]),
                link_pass=bool(form.get("link_pass")),
                form_pass=bool(form.get("form_pass")),
                schema_pass=bool(form.get("schema_pass")),
                canonical_pass=bool(form.get("canonical_pass")),
                accessibility_pass=bool(form.get("accessibility_pass")),
                analytics_pass=bool(form.get("analytics_pass")),
                crm_pass=bool(form.get("crm_pass")),
                privacy_pass=bool(form.get("privacy_pass")),
                mobile_render_pass=bool(form.get("mobile_render_pass")),
            ),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/website-content-control", status_code=303)


@app.post("/website-content-control/releases/{release_id}/rollback")
async def website_rollback_ui(request: Request, release_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        rollback_website_release(db, release_id, str(form["reason"]), user.email, user.role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/website-content-control", status_code=303)


@app.post("/api/website-content/sites", dependencies=[Depends(require_api_token)])
def api_website_site(payload: WebsiteSiteIn, db: Session = Depends(get_db)):
    try:
        row = register_website_site(db, payload, "api", "platform-admin")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"site_id": row.site_id, "brand_id": row.brand_id, "active": row.active}


@app.post("/api/website-content/releases", dependencies=[Depends(require_api_token)])
def api_website_release(payload: WebsiteReleaseIn, db: Session = Depends(get_db)):
    try:
        row = create_website_release(db, payload, "api", "platform-admin")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "release_id": row.release_id,
        "version": row.version,
        "status": row.status,
        "manifest_sha256": row.release_manifest_sha256,
    }


@app.post(
    "/api/website-content/releases/{release_id}/dispatch", dependencies=[Depends(require_api_token)]
)
def api_website_dispatch(release_id: str, db: Session = Depends(get_db)):
    try:
        row = dispatch_website_release(db, release_id, "api", "platform-admin")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"release_id": row.release_id, "status": row.status}


@app.post("/api/website-content/receipts", dependencies=[Depends(require_api_token)])
def api_website_receipt(payload: WebsiteDeliveryReceiptIn, db: Session = Depends(get_db)):
    try:
        row = record_website_receipt(db, payload, "adapter", "adapter")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"target_id": row.target_id, "status": row.status}


@app.post(
    "/api/website-content/targets/{target_id}/smoke", dependencies=[Depends(require_api_token)]
)
def api_website_smoke(target_id: str, payload: WebsiteSmokeTestIn, db: Session = Depends(get_db)):
    try:
        row = record_website_smoke(db, target_id, payload, "smoke-runner", "smoke-runner")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"target_id": row.target_id, "status": row.status, "release_id": row.release_id}


@app.post(
    "/api/website-content/releases/{release_id}/rollback", dependencies=[Depends(require_api_token)]
)
def api_website_rollback(release_id: str, reason: str, db: Session = Depends(get_db)):
    try:
        row = rollback_website_release(db, release_id, reason, "api", "platform-admin")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "release_id": row.release_id,
        "status": row.status,
        "rollback_status": row.auto_rollback_status,
    }


@app.get("/answer-center", response_class=HTMLResponse)
def answer_center_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="answer_center.html",
        context={"user": user, "active": "answer-center", **answer_center_workspace(db)},
    )


@app.post("/answer-center/sources")
async def answer_source_create_ui(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        register_answer_source(
            db,
            AnswerKnowledgeSourceIn(
                title=str(form["title"]),
                source_type=str(form["source_type"]),
                canonical_ref=str(form["canonical_ref"]),
                version=str(form["version"]),
                domain=str(form["domain"]),
                visibility=str(form["visibility"]),
                allowed_roles=[
                    item.strip()
                    for item in str(form.get("allowed_roles") or "").split(",")
                    if item.strip()
                ],
                project_id=str(form.get("project_id") or "").strip() or None,
                content_sha256=str(form["content_sha256"]),
                owner_role=str(form["owner_role"]),
            ),
            user.email,
            user.role,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/answer-center", status_code=303)


@app.post("/answer-center/sources/{source_id}/excerpts")
async def answer_excerpt_create_ui(request: Request, source_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        add_answer_excerpt(
            db,
            source_id,
            AnswerKnowledgeExcerptIn(
                locator=str(form["locator"]), excerpt_text=str(form["excerpt_text"])
            ),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/answer-center", status_code=303)


@app.post("/answer-center/sources/{source_id}/approve")
def answer_source_approve_ui(request: Request, source_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        approve_answer_source(db, source_id, user.email, user.role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/answer-center", status_code=303)


@app.post("/answer-center/sources/{source_id}/revoke")
async def answer_source_revoke_ui(request: Request, source_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        revoke_answer_source(db, source_id, str(form["reason"]), user.email, user.role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/answer-center", status_code=303)


@app.post("/answer-center/questions")
async def answer_question_create_ui(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        create_answer_question(
            db,
            AnswerQuestionIn(
                question_text=str(form["question_text"]),
                domain=str(form["domain"]),
                channel=str(form["channel"]),
                project_id=str(form.get("project_id") or "").strip() or None,
                customer_reference=str(form.get("customer_reference") or "").strip() or None,
            ),
            user.email,
            user.role,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/answer-center", status_code=303)


@app.post("/answer-center/questions/{question_id}/drafts")
async def answer_draft_create_ui(request: Request, question_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        create_answer_draft(
            db,
            question_id,
            AnswerDraftIn(
                answer_text=str(form["answer_text"]),
                certainty=str(form["certainty"]),
                source_conflict=bool(form.get("source_conflict")),
            ),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/answer-center", status_code=303)


@app.post("/answer-center/versions/{answer_version_id}/citations")
async def answer_citation_create_ui(
    request: Request, answer_version_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        add_answer_citation(
            db,
            answer_version_id,
            AnswerCitationIn(
                claim_key=str(form["claim_key"]),
                claim_text=str(form["claim_text"]),
                source_id=str(form["source_id"]),
                excerpt_id=str(form["excerpt_id"]),
            ),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/answer-center", status_code=303)


@app.post("/answer-center/versions/{answer_version_id}/submit")
def answer_submit_ui(request: Request, answer_version_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        submit_answer_for_review(db, answer_version_id, user.email, user.role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/answer-center", status_code=303)


@app.post("/answer-center/versions/{answer_version_id}/reviews")
async def answer_review_ui(request: Request, answer_version_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        review_answer(
            db,
            answer_version_id,
            AnswerReviewIn(decision=str(form["decision"]), note=str(form["note"])),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/answer-center", status_code=303)


@app.post("/answer-center/versions/{answer_version_id}/publish")
async def answer_publish_ui(
    request: Request, answer_version_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        publish_answer(
            db,
            answer_version_id,
            AnswerPublicationIn(
                audience=str(form["audience"]),
                destination=str(form["destination"]),
                project_id=str(form.get("project_id") or "").strip() or None,
            ),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/answer-center", status_code=303)


@app.post("/answer-center/publications/{publication_id}/retract")
async def answer_retract_ui(request: Request, publication_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        retract_answer_publication(db, publication_id, str(form["reason"]), user.email, user.role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/answer-center", status_code=303)


@app.post("/api/answer-center/sources", dependencies=[Depends(require_api_token)])
def api_answer_source(
    payload: AnswerKnowledgeSourceIn,
    actor: str = "api",
    actor_role: str = "platform-admin",
    db: Session = Depends(get_db),
):
    try:
        row = register_answer_source(db, payload, actor, actor_role)
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"source_id": row.source_id, "status": row.status, "content_sha256": row.content_sha256}


@app.post(
    "/api/answer-center/sources/{source_id}/excerpts", dependencies=[Depends(require_api_token)]
)
def api_answer_excerpt(
    source_id: str,
    payload: AnswerKnowledgeExcerptIn,
    actor: str = "api",
    actor_role: str = "platform-admin",
    db: Session = Depends(get_db),
):
    try:
        row = add_answer_excerpt(db, source_id, payload, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"excerpt_id": row.excerpt_id, "excerpt_sha256": row.excerpt_sha256}


@app.post(
    "/api/answer-center/sources/{source_id}/approve", dependencies=[Depends(require_api_token)]
)
def api_answer_source_approve(
    source_id: str, actor: str, actor_role: str, db: Session = Depends(get_db)
):
    try:
        row = approve_answer_source(db, source_id, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"source_id": row.source_id, "status": row.status, "approved_by": row.approved_by}


@app.post("/api/answer-center/questions", dependencies=[Depends(require_api_token)])
def api_answer_question(
    payload: AnswerQuestionIn,
    actor: str = "api",
    actor_role: str = "platform-admin",
    db: Session = Depends(get_db),
):
    try:
        row = create_answer_question(db, payload, actor, actor_role)
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "question_id": row.question_id,
        "status": row.status,
        "assigned_role": row.assigned_role,
    }


@app.post(
    "/api/answer-center/questions/{question_id}/drafts", dependencies=[Depends(require_api_token)]
)
def api_answer_draft(
    question_id: str,
    payload: AnswerDraftIn,
    actor: str = "api",
    actor_role: str = "platform-admin",
    db: Session = Depends(get_db),
):
    try:
        row = create_answer_draft(db, question_id, payload, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "answer_version_id": row.answer_version_id,
        "version": row.version,
        "status": row.status,
        "answer_sha256": row.answer_sha256,
    }


@app.post(
    "/api/answer-center/versions/{answer_version_id}/citations",
    dependencies=[Depends(require_api_token)],
)
def api_answer_citation(
    answer_version_id: str,
    payload: AnswerCitationIn,
    actor: str = "api",
    actor_role: str = "platform-admin",
    db: Session = Depends(get_db),
):
    try:
        row = add_answer_citation(db, answer_version_id, payload, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "citation_id": row.citation_id,
        "source_id": row.source_id,
        "source_version": row.source_version,
    }


@app.post(
    "/api/answer-center/versions/{answer_version_id}/submit",
    dependencies=[Depends(require_api_token)],
)
def api_answer_submit(
    answer_version_id: str,
    actor: str = "api",
    actor_role: str = "platform-admin",
    db: Session = Depends(get_db),
):
    try:
        row = submit_answer_for_review(db, answer_version_id, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"answer_version_id": row.answer_version_id, "status": row.status}


@app.post(
    "/api/answer-center/versions/{answer_version_id}/reviews",
    dependencies=[Depends(require_api_token)],
)
def api_answer_review(
    answer_version_id: str,
    payload: AnswerReviewIn,
    actor: str,
    actor_role: str,
    db: Session = Depends(get_db),
):
    try:
        row = review_answer(db, answer_version_id, payload, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "review_id": row.review_id,
        "decision": row.decision,
        "reviewer_role": row.reviewer_role,
    }


@app.post(
    "/api/answer-center/versions/{answer_version_id}/publish",
    dependencies=[Depends(require_api_token)],
)
def api_answer_publish(
    answer_version_id: str,
    payload: AnswerPublicationIn,
    actor: str,
    actor_role: str,
    db: Session = Depends(get_db),
):
    try:
        row = publish_answer(db, answer_version_id, payload, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "publication_id": row.publication_id,
        "status": row.status,
        "publication_sha256": row.publication_sha256,
    }


@app.get("/b2b-project-intake", response_class=HTMLResponse)
def b2b_project_intake_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="b2b_project_intake.html",
        context={"user": user, "active": "b2b-project-intake", **b2b_intake_workspace(db)},
    )


@app.post("/b2b-project-intake/intakes")
async def b2b_intake_create_ui(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        row = B2BProjectIntakeIn(
            source_system=str(form["source_system"]),
            source_external_id=str(form["source_external_id"]),
            source_reference=str(form["source_reference"]),
            source_content_sha256=str(form["source_content_sha256"]),
            lawful_basis=str(form["lawful_basis"]),
            source_use_approved=bool(form.get("source_use_approved")),
            linked_marketing_lead_id=str(form.get("linked_marketing_lead_id") or "").strip()
            or None,
            organization_name=str(form["organization_name"]),
            tax_number=str(form.get("tax_number") or "").strip() or None,
            website_domain=str(form.get("website_domain") or "").strip() or None,
            contact_name=str(form["contact_name"]),
            contact_email=str(form.get("contact_email") or "").strip() or None,
            contact_phone=str(form.get("contact_phone") or "").strip() or None,
            project_type=str(form["project_type"]),
            country=str(form["country"]),
            city=str(form["city"]),
            site_address=str(form.get("site_address") or "").strip() or None,
            gross_floor_area_m2=Decimal(str(form["gross_floor_area_m2"])),
            planned_start=date.fromisoformat(str(form["planned_start"]))
            if form.get("planned_start")
            else None,
            requested_deadline=date.fromisoformat(str(form["requested_deadline"]))
            if form.get("requested_deadline")
            else None,
            estimated_budget_huf=Decimal(str(form["estimated_budget_huf"])),
            project_summary=str(form["project_summary"]),
            document_ids=[
                item.strip()
                for item in str(form.get("document_ids") or "").split(",")
                if item.strip()
            ],
        )
        capture_b2b_intake(db, row, user.email, user.role)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/b2b-project-intake", status_code=303)


@app.post("/b2b-project-intake/matches/{match_id}/resolve")
async def b2b_duplicate_ui(request: Request, match_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        resolve_b2b_duplicate(
            db,
            match_id,
            B2BDuplicateDecisionIn(decision=str(form["decision"]), note=str(form["note"])),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/b2b-project-intake", status_code=303)


@app.post("/b2b-project-intake/intakes/{intake_id}/technical-review")
async def b2b_technical_ui(request: Request, intake_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        review_b2b_technical(
            db,
            intake_id,
            B2BTechnicalReviewIn(
                decision=str(form["decision"]),
                delivery_model=str(form["delivery_model"]),
                capacity_fit=str(form["capacity_fit"]),
                site_feasibility=str(form["site_feasibility"]),
                complexity=str(form["complexity"]),
                assumptions=[
                    item.strip()
                    for item in str(form.get("assumptions") or "").split("|")
                    if item.strip()
                ],
                note=str(form["note"]),
            ),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/b2b-project-intake", status_code=303)


@app.post("/b2b-project-intake/intakes/{intake_id}/financial-review")
async def b2b_financial_ui(request: Request, intake_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        review_b2b_financial(
            db,
            intake_id,
            B2BFinancialReviewIn(
                decision=str(form["decision"]),
                budget_credibility=str(form["budget_credibility"]),
                funding_status=str(form["funding_status"]),
                preliminary_margin_band=str(form["preliminary_margin_band"]),
                assumptions=[
                    item.strip()
                    for item in str(form.get("assumptions") or "").split("|")
                    if item.strip()
                ],
                note=str(form["note"]),
            ),
            user.email,
            user.role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/b2b-project-intake", status_code=303)


def _b2b_decision_form(form) -> B2BQualificationDecisionIn:
    return B2BQualificationDecisionIn(
        decision=str(form["decision"]),
        route=str(form["route"]),
        assigned_sales_email=str(form["assigned_sales_email"]),
        next_action=str(form["next_action"]),
        note=str(form["note"]),
    )


@app.post("/b2b-project-intake/intakes/{intake_id}/qualification")
async def b2b_qualification_ui(request: Request, intake_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        qualify_b2b_intake(
            db, intake_id, _b2b_decision_form(await request.form()), user.email, user.role
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/b2b-project-intake", status_code=303)


@app.post("/b2b-project-intake/intakes/{intake_id}/leadership-decision")
async def b2b_leadership_ui(request: Request, intake_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        decide_b2b_leadership(
            db, intake_id, _b2b_decision_form(await request.form()), user.email, user.role
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/b2b-project-intake", status_code=303)


@app.post("/b2b-project-intake/intakes/{intake_id}/crm-handoff")
def b2b_handoff_ui(request: Request, intake_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        queue_b2b_crm_handoff(db, intake_id, user.email, user.role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/b2b-project-intake", status_code=303)


@app.post("/b2b-project-intake/deliveries/{delivery_id}/receipt")
async def b2b_receipt_ui(request: Request, delivery_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    if user.role != "platform-admin":
        raise HTTPException(
            403, "A kézi UAT receipt kizárólag platform-admin számára engedélyezett."
        )
    form = await request.form()
    try:
        record_b2b_crm_receipt(
            db,
            B2BCRMReceiptIn(
                delivery_id=delivery_id,
                idempotency_key=str(form["idempotency_key"]),
                payload_sha256=str(form["payload_sha256"]),
                accepted=str(form["accepted"]).lower() == "true",
                external_crm_id=str(form.get("external_crm_id") or "").strip() or None,
                error_message=str(form.get("error_message") or "").strip() or None,
            ),
            user.email,
            "platform-admin",
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/b2b-project-intake", status_code=303)


@app.post("/api/b2b-project-intake/intakes", dependencies=[Depends(require_api_token)])
def api_b2b_intake(
    payload: B2BProjectIntakeIn,
    actor: str = "api",
    actor_role: str = "platform-admin",
    db: Session = Depends(get_db),
):
    try:
        row = capture_b2b_intake(db, payload, actor, actor_role)
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "intake_id": row.intake_id,
        "status": row.status,
        "score": row.base_score,
        "missing_fields": json.loads(row.missing_fields_json),
    }


@app.post(
    "/api/b2b-project-intake/matches/{match_id}/resolve", dependencies=[Depends(require_api_token)]
)
def api_b2b_duplicate(
    match_id: str,
    payload: B2BDuplicateDecisionIn,
    actor: str,
    actor_role: str,
    db: Session = Depends(get_db),
):
    try:
        row = resolve_b2b_duplicate(db, match_id, payload, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"match_id": row.match_id, "status": row.status}


@app.post(
    "/api/b2b-project-intake/intakes/{intake_id}/technical-review",
    dependencies=[Depends(require_api_token)],
)
def api_b2b_technical(
    intake_id: str,
    payload: B2BTechnicalReviewIn,
    actor: str,
    actor_role: str,
    db: Session = Depends(get_db),
):
    try:
        row = review_b2b_technical(db, intake_id, payload, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"review_id": row.review_id, "decision": row.decision}


@app.post(
    "/api/b2b-project-intake/intakes/{intake_id}/financial-review",
    dependencies=[Depends(require_api_token)],
)
def api_b2b_financial(
    intake_id: str,
    payload: B2BFinancialReviewIn,
    actor: str,
    actor_role: str,
    db: Session = Depends(get_db),
):
    try:
        row = review_b2b_financial(db, intake_id, payload, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"review_id": row.review_id, "decision": row.decision}


@app.post(
    "/api/b2b-project-intake/intakes/{intake_id}/qualification",
    dependencies=[Depends(require_api_token)],
)
def api_b2b_qualification(
    intake_id: str,
    payload: B2BQualificationDecisionIn,
    actor: str,
    actor_role: str,
    db: Session = Depends(get_db),
):
    try:
        row = qualify_b2b_intake(db, intake_id, payload, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"decision_id": row.decision_id, "decision": row.decision, "route": row.route}


@app.post(
    "/api/b2b-project-intake/intakes/{intake_id}/leadership-decision",
    dependencies=[Depends(require_api_token)],
)
def api_b2b_leadership(
    intake_id: str,
    payload: B2BQualificationDecisionIn,
    actor: str,
    actor_role: str,
    db: Session = Depends(get_db),
):
    try:
        row = decide_b2b_leadership(db, intake_id, payload, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"decision_id": row.decision_id, "decision": row.decision}


@app.post(
    "/api/b2b-project-intake/intakes/{intake_id}/crm-handoff",
    dependencies=[Depends(require_api_token)],
)
def api_b2b_handoff(intake_id: str, actor: str, actor_role: str, db: Session = Depends(get_db)):
    try:
        row = queue_b2b_crm_handoff(db, intake_id, actor, actor_role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "delivery_id": row.delivery_id,
        "status": row.status,
        "payload_sha256": row.payload_sha256,
        "idempotency_key": row.idempotency_key,
    }


@app.post("/api/b2b-project-intake/crm-receipts", dependencies=[Depends(require_api_token)])
def api_b2b_receipt(payload: B2BCRMReceiptIn, db: Session = Depends(get_db)):
    try:
        row = record_b2b_crm_receipt(db, payload, "crm-adapter", "adapter")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "delivery_id": row.delivery_id,
        "status": row.status,
        "external_crm_id": row.external_crm_id,
    }


@app.get("/api/operations/summary", dependencies=[Depends(require_api_token)])
def api_operations_summary(db: Session = Depends(get_db)):
    return operations_summary(db)


@app.get("/api/operations/projects/{project_id}", dependencies=[Depends(require_api_token)])
def api_operations_project(project_id: str, db: Session = Depends(get_db)):
    try:
        data = project_operations(db, project_id)
    except KeyError:
        raise HTTPException(404, "Projekt nem található.")
    return {
        "project_id": project_id,
        "metrics": data["metrics"],
        "phases": [
            {
                "phase_id": p.phase_id,
                "name": p.name,
                "status": p.status,
                "progress_pct": p.progress_pct,
            }
            for p in data["phases"]
        ],
        "work_packages": [
            {
                "work_package_id": p.work_package_id,
                "name": p.name,
                "status": p.status,
                "progress_pct": p.progress_pct,
                "blocked": p.blocked,
            }
            for p in data["packages"]
        ],
        "open_issues": [
            {"issue_id": i.issue_id, "title": i.title, "severity": i.severity, "status": i.status}
            for i in data["issues"]
            if i.status == "open"
        ],
    }


@app.post("/api/operations/daily-reports", dependencies=[Depends(require_api_token)])
def api_daily_report(payload: DailyReportIn, db: Session = Depends(get_db)):
    try:
        row = create_daily_report(db, payload, actor="api")
    except KeyError:
        raise HTTPException(404, "Projekt nem található.")
    return {"report_id": row.report_id, "project_id": row.project_id, "status": row.status}


@app.post("/api/operations/issues", dependencies=[Depends(require_api_token)])
def api_site_issue(payload: SiteIssueIn, db: Session = Depends(get_db)):
    row = create_issue(db, payload, actor="api")
    return {"issue_id": row.issue_id, "project_id": row.project_id, "status": row.status}


@app.post("/api/operations/commands", dependencies=[Depends(require_api_token)])
def api_operations_command(payload: OperationsCommandIn, db: Session = Depends(get_db)):
    row = create_operations_command(db, payload, actor="api")
    return {
        "message_id": row.message_id,
        "status": row.status,
        "destination_module": row.destination_module,
    }


@app.post("/api/procurement/requirements", dependencies=[Depends(require_api_token)])
def api_procurement_requirement(payload: ProcurementRequirementIn, db: Session = Depends(get_db)):
    try:
        row = create_procurement_requirement(db, payload, actor="api")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "requirement_id": row.requirement_id,
        "status": row.status,
        "max_orderable_quantity": str(row.max_orderable_quantity),
    }


@app.post(
    "/api/procurement/requirements/{requirement_id}/approvals/{stage}",
    dependencies=[Depends(require_api_token)],
)
def api_procurement_requirement_approval(
    requirement_id: str, stage: str, db: Session = Depends(get_db)
):
    try:
        row = approve_procurement_requirement(db, requirement_id, stage, "api", "platform-admin")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"requirement_id": row.requirement_id, "status": row.status}


@app.post("/api/procurement/offers", dependencies=[Depends(require_api_token)])
def api_procurement_offer(payload: ProcurementOfferIn, db: Session = Depends(get_db)):
    try:
        row = add_procurement_offer(db, payload, actor="api")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"offer_id": row.offer_id, "total_landed_cost_huf": str(row.total_landed_cost_huf)}


@app.post("/api/procurement/selections", dependencies=[Depends(require_api_token)])
def api_procurement_selection(payload: ProcurementSelectionIn, db: Session = Depends(get_db)):
    try:
        row = select_procurement_offer(db, payload, actor="api")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "selection_id": row.selection_id,
        "status": row.status,
        "savings_pct": str(row.savings_pct),
        "dual_approval_required": row.dual_approval_required,
    }


@app.post(
    "/api/procurement/selections/{selection_id}/approvals/{stage}",
    dependencies=[Depends(require_api_token)],
)
def api_procurement_selection_approval(
    selection_id: str, stage: str, db: Session = Depends(get_db)
):
    try:
        row = approve_procurement_selection(
            db, selection_id, stage, f"api-{stage}", "platform-admin"
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"selection_id": row.selection_id, "status": row.status}


@app.post("/api/procurement/orders", dependencies=[Depends(require_api_token)])
def api_procurement_order(payload: ProcurementOrderIn, db: Session = Depends(get_db)):
    try:
        row = create_procurement_order(db, payload, actor="api")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"order_id": row.order_id, "status": row.status, "content_sha256": row.content_sha256}


@app.post("/api/procurement/orders/{order_id}/confirm", dependencies=[Depends(require_api_token)])
def api_procurement_order_confirm(order_id: str, db: Session = Depends(get_db)):
    try:
        row = confirm_procurement_order(db, order_id, actor="api")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"order_id": row.order_id, "confirmation_status": row.confirmation_status}


@app.post("/api/procurement/invoice-matches", dependencies=[Depends(require_api_token)])
def api_procurement_invoice_match(
    payload: ProcurementInvoiceMatchIn, db: Session = Depends(get_db)
):
    try:
        row = create_procurement_invoice_match(db, payload, actor="api")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "match_id": row.match_id,
        "status": row.status,
        "payment_ready": row.payment_ready,
        "blockers": json.loads(row.blockers_json),
    }


@app.post("/api/procurement/delivery-notes", dependencies=[Depends(require_api_token)])
def api_delivery_note(payload: DeliveryNoteIn, db: Session = Depends(get_db)):
    try:
        row, lot = create_delivery_note(db, payload, actor="api")
    except KeyError:
        raise HTTPException(404, "Rendelés nem található.")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "delivery_note_id": row.delivery_note_id,
        "lot_id": lot.lot_id if lot else None,
        "document_status": row.document_status,
    }


@app.post("/api/procurement/material-movements", dependencies=[Depends(require_api_token)])
def api_material_movement(payload: MaterialMovementIn, db: Session = Depends(get_db)):
    try:
        row = create_material_movement(db, payload, actor="api")
    except KeyError:
        raise HTTPException(404, "Anyaglot nem található.")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"movement_id": row.movement_id, "lot_id": row.lot_id, "quantity": str(row.quantity)}


@app.post("/api/procurement/usage-controls", dependencies=[Depends(require_api_token)])
def api_usage_control(payload: MaterialUsageIn, db: Session = Depends(get_db)):
    row = create_usage_control(db, payload, actor="api")
    return {
        "control_id": row.control_id,
        "allowed_quantity": str(row.allowed_quantity),
        "decision_status": row.decision_status,
    }


def _partner_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Érvénytelen dátum.") from exc


@app.get("/partners", response_class=HTMLResponse)
def partner_control_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="partner_control.html",
        context={
            "user": user,
            "data": partner_control_workspace(db),
            "projects": db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all(),
            "active": "partners",
        },
    )


@app.post("/partners")
async def partner_create_ui(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        row = create_partner(
            db,
            user,
            company_name=str(form.get("company_name") or ""),
            primary_email=str(form.get("primary_email") or ""),
            tax_number=str(form.get("tax_number") or ""),
            trade_categories=[
                value.strip()
                for value in str(form.get("trade_categories") or "").split(",")
                if value.strip()
            ],
            territories=[
                value.strip()
                for value in str(form.get("territories") or "").split(",")
                if value.strip()
            ],
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{row.partner_id}", status_code=303)


@app.post("/partners/{partner_id}/external-score")
async def partner_external_score_ui(
    request: Request, partner_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        set_partner_external_score(
            db,
            partner_id,
            user,
            score=str(form.get("score") or ""),
            evidence_ref=str(form.get("evidence_ref") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{partner_id}", status_code=303)


@app.post("/partners/{partner_id}/approve")
async def partner_approve_ui(request: Request, partner_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        approve_partner(db, partner_id, user, note=str(form.get("note") or ""))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{partner_id}", status_code=303)


@app.post("/partners/{partner_id}/certificates")
async def partner_certificate_create_ui(
    request: Request, partner_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        add_partner_certificate(
            db,
            partner_id,
            user,
            certificate_type=str(form.get("certificate_type") or ""),
            issuer=str(form.get("issuer") or ""),
            document_ref=str(form.get("document_ref") or ""),
            document_sha256=str(form.get("document_sha256") or ""),
            reference_number=str(form.get("reference_number") or ""),
            valid_from=_partner_date(str(form.get("valid_from")))
            if form.get("valid_from")
            else None,
            valid_until=_partner_date(str(form.get("valid_until")))
            if form.get("valid_until")
            else None,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{partner_id}", status_code=303)


@app.post("/partners/certificates/{certificate_id}/verify")
async def partner_certificate_verify_ui(
    request: Request, certificate_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        row = verify_partner_certificate(
            db,
            certificate_id,
            user,
            accepted=str(form.get("decision")) == "accepted",
            note=str(form.get("note") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{row.partner_id}", status_code=303)


@app.post("/partners/{partner_id}/capacity")
async def partner_capacity_create_ui(
    request: Request, partner_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        declare_partner_capacity(
            db,
            partner_id,
            user,
            trade_category=str(form.get("trade_category") or ""),
            territory=str(form.get("territory") or ""),
            available_from=_partner_date(str(form.get("available_from") or "")),
            available_until=_partner_date(str(form.get("available_until") or "")),
            crew_count=_form_int(form.get("crew_count")),
            monthly_capacity=str(form.get("monthly_capacity") or "0"),
            committed_capacity=str(form.get("committed_capacity") or "0"),
            evidence_ref=str(form.get("evidence_ref") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{partner_id}", status_code=303)


@app.post("/partners/capacity/{declaration_id}/review")
async def partner_capacity_review_ui(
    request: Request, declaration_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        row = review_partner_capacity(
            db,
            declaration_id,
            user,
            accepted=str(form.get("decision")) == "accepted",
            note=str(form.get("note") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{row.partner_id}", status_code=303)


@app.post("/partners/{partner_id}/evaluations")
async def partner_evaluation_create_ui(
    request: Request, partner_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        create_partner_project_evaluation(
            db,
            partner_id,
            str(form.get("project_id") or ""),
            user,
            quality=_form_int(form.get("quality")),
            deadline=_form_int(form.get("deadline")),
            documentation=_form_int(form.get("documentation")),
            hse=_form_int(form.get("hse")),
            cooperation=_form_int(form.get("cooperation")),
            commercial=_form_int(form.get("commercial")),
            warranty=_form_int(form.get("warranty")),
            notes=str(form.get("notes") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{partner_id}", status_code=303)


@app.post("/partners/{partner_id}/incidents")
async def partner_incident_create_ui(
    request: Request, partner_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        create_partner_incident(
            db,
            partner_id,
            user,
            incident_type=str(form.get("incident_type") or ""),
            severity=str(form.get("severity") or ""),
            facts=str(form.get("facts") or ""),
            requirement_breached=str(form.get("requirement_breached") or ""),
            immediate_risk=str(form.get("immediate_risk") or ""),
            project_id=str(form.get("project_id") or ""),
            contract_id=str(form.get("contract_id") or ""),
            evidence_refs=[
                value.strip()
                for value in str(form.get("evidence_refs") or "").splitlines()
                if value.strip()
            ],
            recurring=form.get("recurring") is not None,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{partner_id}", status_code=303)


@app.post("/partners/incidents/{incident_id}/response")
async def partner_incident_response_ui(
    request: Request, incident_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        row = record_incident_response(
            db,
            incident_id,
            user,
            partner_statement=str(form.get("partner_statement") or ""),
            corrective_action=str(form.get("corrective_action") or ""),
            corrective_owner=str(form.get("corrective_owner") or ""),
            corrective_due_at=_tender_datetime(str(form.get("corrective_due_at") or "")),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{row.partner_id}", status_code=303)


@app.post("/partners/incidents/{incident_id}/close")
async def partner_incident_close_ui(
    request: Request, incident_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        row = close_partner_incident(db, incident_id, user, outcome=str(form.get("outcome") or ""))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{row.partner_id}", status_code=303)


@app.post("/partners/{partner_id}/decisions")
async def partner_decision_create_ui(
    request: Request, partner_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        propose_partner_decision(
            db,
            partner_id,
            user,
            decision_type=str(form.get("decision_type") or ""),
            basis={
                "summary": str(form.get("basis") or ""),
                "incident_ids": [
                    value.strip()
                    for value in str(form.get("incident_ids") or "").split(",")
                    if value.strip()
                ],
            },
            conditions={
                "trade_categories": [
                    value.strip()
                    for value in str(form.get("allowed_trades") or "").split(",")
                    if value.strip()
                ],
                "territories": [
                    value.strip()
                    for value in str(form.get("allowed_territories") or "").split(",")
                    if value.strip()
                ],
                "max_contract_value": str(form.get("max_contract_value") or "0"),
            },
            review_at=_tender_datetime(str(form.get("review_at")))
            if form.get("review_at")
            else None,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{partner_id}", status_code=303)


@app.post("/partners/decisions/{decision_id}/review")
async def partner_decision_review_ui(
    request: Request, decision_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        row = review_partner_decision(
            db,
            decision_id,
            user,
            review_type=str(form.get("review_type") or ""),
            note=str(form.get("note") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{row.partner_id}", status_code=303)


@app.post("/partners/decisions/{decision_id}/approve")
async def partner_decision_approve_ui(
    request: Request, decision_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        row = approve_partner_decision(
            db,
            decision_id,
            user,
            notification_evidence_ref=str(form.get("notification_evidence_ref") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/partners#{row.partner_id}", status_code=303)


def _tender_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Budapest"))
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Érvénytelen tenderhatáridő.") from exc


@app.get("/tenders", response_class=HTMLResponse)
def tenders_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    data = tender_workspace(db)
    projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
    return templates.TemplateResponse(
        request=request,
        name="tenders.html",
        context={"user": user, "data": data, "projects": projects, "active": "tenders"},
    )


@app.post("/tenders")
async def tender_create_ui(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        row = create_tender(
            db,
            user,
            tender_id=str(form.get("tender_id") or ""),
            project_id=str(form.get("project_id") or ""),
            title=str(form.get("title") or ""),
            scope=str(form.get("scope") or ""),
            currency=str(form.get("currency") or "HUF"),
            question_deadline_at=_tender_datetime(str(form.get("question_deadline_at") or "")),
            submission_deadline_at=_tender_datetime(str(form.get("submission_deadline_at") or "")),
            criteria={
                "price": _form_int(form.get("price_weight"), 40),
                "technical": _form_int(form.get("technical_weight"), 30),
                "timeline": _form_int(form.get("timeline_weight"), 20),
                "references": _form_int(form.get("references_weight"), 10),
            },
            prequalification_required=form.get("prequalification_required") is not None,
            certificate_gate_enabled=form.get("certificate_gate_enabled") is not None,
            required_certificate_types=[
                _form_text(value) for value in form.getlist("required_certificate_types")
            ],
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tenders/{row.tender_id}", status_code=303)


@app.get("/tenders/evidence/{evidence_id}")
def tender_internal_evidence_download(
    request: Request, evidence_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        evidence = evidence_for_internal(db, evidence_id, user)
        path = verified_evidence_path(
            db,
            evidence,
            storage_root=TENDER_EVIDENCE_DIR,
            actor=str(user.email),
            channel="internal",
        )
    except KeyError as exc:
        raise HTTPException(404, "A tenderdokumentum nem található.") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except TenderEvidenceUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(path, media_type=evidence.mime_type, filename=evidence.file_name)


@app.get("/tenders/{tender_id}", response_class=HTMLResponse)
def tender_detail_page(request: Request, tender_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        tender = get_tender(db, tender_id)
    except KeyError as exc:
        raise HTTPException(404, "A tender nem található.") from exc
    criteria = json.loads(tender.evaluation_criteria_json or "{}")
    return templates.TemplateResponse(
        request=request,
        name="tender_detail.html",
        context={"user": user, "tender": tender, "criteria": criteria, "active": "tenders"},
    )


@app.get("/tenders/{tender_id}/compare", response_class=HTMLResponse)
def tender_compare_page(request: Request, tender_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        comparison = tender_bid_comparison(db, tender_id)
    except KeyError as exc:
        raise HTTPException(404, "A tender nem található.") from exc
    return templates.TemplateResponse(
        request=request,
        name="tender_compare.html",
        context={
            "user": user,
            "comparison": comparison,
            "active": "tenders",
        },
    )


@app.get("/tenders/{tender_id}/governance", response_class=HTMLResponse)
def tender_governance_page(request: Request, tender_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        tender = get_tender(db, tender_id)
    except KeyError as exc:
        raise HTTPException(404, "A tender nem található.") from exc
    bid_ids = [bid.id for bid in tender.bids]
    versions = (
        list(
            db.scalars(
                select(TenderBidVersion)
                .where(TenderBidVersion.bid_id_fk.in_(bid_ids))
                .order_by(TenderBidVersion.bid_id_fk, TenderBidVersion.version)
            )
        )
        if bid_ids
        else []
    )
    requests = list(
        db.scalars(
            select(TenderClarificationRequest)
            .where(TenderClarificationRequest.tender_id_fk == tender.id)
            .order_by(TenderClarificationRequest.created_at)
        )
    )
    preparation = db.scalar(
        select(TenderPurchaseOrderPreparation).where(
            TenderPurchaseOrderPreparation.tender_id == tender_id
        )
    )
    return templates.TemplateResponse(
        request=request,
        name="tender_governance.html",
        context={
            "user": user,
            "tender": tender,
            "versions": versions,
            "requests": requests,
            "preparation": preparation,
            "active": "tenders",
        },
    )


@app.post("/tenders/{tender_id}/invitations")
async def tender_invitation_create_ui(
    request: Request, tender_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        add_invitation(
            db,
            tender_id,
            user,
            partner_email=str(form.get("partner_email") or ""),
            company_name=str(form.get("company_name") or ""),
            contact_name=str(form.get("contact_name") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tenders/{tender_id}#partners", status_code=303)


@app.post("/tenders/{tender_id}/line-items")
async def tender_line_item_create_ui(
    request: Request, tender_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        add_tender_line_item(
            db,
            tender_id,
            user,
            line_code=str(form.get("line_code") or ""),
            category=str(form.get("category") or ""),
            name=str(form.get("name") or ""),
            unit=str(form.get("unit") or ""),
            quantity=str(form.get("quantity") or ""),
            required=form.get("required") is not None,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tenders/{tender_id}#line-items", status_code=303)


@app.post("/tenders/{tender_id}/invitations/{invitation_id}/{action}")
async def tender_invitation_access_ui(
    request: Request,
    tender_id: str,
    invitation_id: str,
    action: str,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        manage_invitation_access(
            db,
            tender_id,
            invitation_id,
            user,
            action=action,
            reason=str(form.get("reason") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "A meghívó nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tenders/{tender_id}#partners", status_code=303)


@app.post("/tenders/{tender_id}/sync-mail")
def tender_sync_mail_ui(request: Request, tender_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        sync_mail_recipients(db, tender_id, user)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return RedirectResponse(f"/tenders/{tender_id}#partners", status_code=303)


@app.post("/tenders/{tender_id}/publish")
def tender_publish_ui(request: Request, tender_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        publish_tender(db, tender_id, user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tenders/{tender_id}", status_code=303)


@app.post("/tenders/{tender_id}/close")
def tender_close_ui(request: Request, tender_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        close_tender(db, tender_id, user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tenders/{tender_id}", status_code=303)


@app.post("/tenders/{tender_id}/clarifications")
async def tender_internal_clarification_ui(
    request: Request, tender_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        add_clarification(
            db,
            tender_id,
            user=user,
            body=str(form.get("body") or ""),
            invitation_id=str(form.get("invitation_id") or ""),
            partner_visible=form.get("partner_visible") is not None,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tenders/{tender_id}#clarifications", status_code=303)


@app.post("/tenders/{tender_id}/bids/{bid_id}/evaluate")
async def tender_evaluate_ui(
    request: Request, tender_id: str, bid_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        evaluate_bid(
            db,
            tender_id,
            bid_id,
            user,
            price_score=_form_int(form.get("price_score")),
            technical_score=_form_int(form.get("technical_score")),
            timeline_score=_form_int(form.get("timeline_score")),
            references_score=_form_int(form.get("references_score")),
            recommendation=str(form.get("recommendation") or ""),
            notes=str(form.get("notes") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tenders/{tender_id}#bids", status_code=303)


@app.post("/tenders/{tender_id}/bids/{bid_id}/clarification-requests")
async def tender_clarification_request_create_ui(
    request: Request, tender_id: str, bid_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        create_clarification_request(
            db,
            tender_id,
            bid_id,
            user,
            question=str(form.get("question") or ""),
            due_at=_tender_datetime(str(form.get("due_at") or "")),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tenders/{tender_id}#bids", status_code=303)


@app.post("/tenders/{tender_id}/clarification-requests/{request_id}/accept")
async def tender_clarification_request_accept_ui(
    request: Request, tender_id: str, request_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        accept_clarification_request(db, request_id, user, note=str(form.get("note") or ""))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tenders/{tender_id}#bids", status_code=303)


@app.post("/tenders/{tender_id}/bids/{bid_id}/award")
async def tender_award_ui(
    request: Request, tender_id: str, bid_id: str, db: Session = Depends(get_db)
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    form = await request.form()
    try:
        award_bid(db, tender_id, bid_id, user, summary=str(form.get("summary") or ""))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tenders/{tender_id}#bids", status_code=303)


@app.get("/tender/{tender_id}", response_class=HTMLResponse)
def tender_partner_page(
    request: Request, tender_id: str, recipient: str = "", db: Session = Depends(get_db)
):
    try:
        data = tender_partner_workspace(db, tender_id, recipient)
    except KeyError as exc:
        raise HTTPException(404, "A tender nem található.") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="tender_partner.html",
        context={"user": None, "data": data, "asset_version": __version__},
    )


@app.post("/tender/{tender_id}/bid")
async def tender_partner_bid_save(request: Request, tender_id: str, db: Session = Depends(get_db)):
    form = await request.form()
    descriptions = form.getlist("item_description")
    units = form.getlist("item_unit")
    quantities = form.getlist("item_quantity")
    prices = form.getlist("item_unit_price")
    items = [
        {
            "description": descriptions[index],
            "unit": units[index] if index < len(units) else "db",
            "quantity": quantities[index] if index < len(quantities) else "0",
            "unit_price": prices[index] if index < len(prices) else "0",
        }
        for index in range(len(descriptions))
    ]
    token = str(form.get("recipient") or "")
    try:
        save_bid(
            db,
            tender_id,
            token,
            items=items,
            vat_percent=form.get("vat_percent") or "27",
            validity_days=_form_int(form.get("validity_days"), 30),
            lead_time_days=_form_int(form.get("lead_time_days")),
            warranty_months=_form_int(form.get("warranty_months")),
            summary=str(form.get("summary") or ""),
            exclusions=str(form.get("exclusions") or ""),
        )
    except (KeyError, PermissionError) as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tender/{tender_id}?recipient={token}#bid", status_code=303)


@app.post("/tender/{tender_id}/submit")
async def tender_partner_bid_submit(
    request: Request, tender_id: str, db: Session = Depends(get_db)
):
    form = await request.form()
    token = str(form.get("recipient") or "")
    try:
        submit_bid(db, tender_id, token)
    except (KeyError, PermissionError) as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tender/{tender_id}?recipient={token}#bid", status_code=303)


@app.post("/tender/{tender_id}/withdraw")
async def tender_partner_bid_withdraw(
    request: Request, tender_id: str, db: Session = Depends(get_db)
):
    form = await request.form()
    token = str(form.get("recipient") or "")
    try:
        withdraw_bid(db, tender_id, token)
    except (KeyError, PermissionError) as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tender/{tender_id}?recipient={token}#bid", status_code=303)


@app.post("/tender/{tender_id}/decline")
async def tender_partner_decline(request: Request, tender_id: str, db: Session = Depends(get_db)):
    form = await request.form()
    token = str(form.get("recipient") or "")
    try:
        decline_invitation(db, tender_id, token, str(form.get("reason") or ""))
    except (KeyError, PermissionError) as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tender/{tender_id}?recipient={token}", status_code=303)


@app.post("/tender/{tender_id}/clarifications")
async def tender_partner_clarification(
    request: Request, tender_id: str, db: Session = Depends(get_db)
):
    form = await request.form()
    token = str(form.get("recipient") or "")
    try:
        add_clarification(db, tender_id, token=token, body=str(form.get("body") or ""))
    except (KeyError, PermissionError) as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(
        f"/tender/{tender_id}?recipient={token}#clarifications", status_code=303
    )


@app.post("/tender/{tender_id}/clarification-requests/{request_id}/respond")
async def tender_partner_clarification_request_response(
    request: Request, tender_id: str, request_id: str, db: Session = Depends(get_db)
):
    form = await request.form()
    token = str(form.get("recipient") or "")
    try:
        respond_clarification_request(
            db, tender_id, token, request_id, response=str(form.get("response") or "")
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(
        f"/tender/{tender_id}?recipient={token}#clarifications", status_code=303
    )


@app.post("/tender/{tender_id}/evidence")
async def tender_partner_evidence_upload(
    request: Request,
    tender_id: str,
    file: UploadFile = File(...),
    recipient: Annotated[str, Form()] = "",
    caption: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    raw = await file.read(25 * 1024 * 1024 + 1)
    try:
        save_bid_evidence(
            db,
            tender_id,
            recipient,
            file_name=file.filename or "tender-document",
            mime_type=file.content_type or "application/octet-stream",
            raw=raw,
            caption=caption or "",
            storage_root=TENDER_EVIDENCE_DIR,
        )
    except (KeyError, PermissionError) as exc:
        raise HTTPException(403, str(exc)) from exc
    except TenderScannerUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except TenderMalwareDetected as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tender/{tender_id}?recipient={recipient}#evidence", status_code=303)


@app.get("/tender/{tender_id}/evidence/{evidence_id}")
def tender_partner_evidence_download(
    tender_id: str, evidence_id: str, recipient: str = "", db: Session = Depends(get_db)
):
    try:
        evidence = evidence_for_partner(db, evidence_id, tender_id, recipient)
    except KeyError as exc:
        raise HTTPException(404) from exc
    except PermissionError as exc:
        raise HTTPException(403) from exc
    try:
        path = verified_evidence_path(
            db,
            evidence,
            storage_root=TENDER_EVIDENCE_DIR,
            actor=evidence.bid.invitation.partner_email,
            channel="partner",
        )
    except TenderEvidenceUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(path, media_type=evidence.mime_type, filename=evidence.file_name)


@app.get("/tendermail", response_class=HTMLResponse)
def tendermail_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    metrics = tender_mail_metrics(db)
    domains = db.scalars(select(MailSendingDomain).order_by(MailSendingDomain.domain_name)).all()
    campaigns = db.scalars(
        select(TenderMailCampaign).order_by(desc(TenderMailCampaign.created_at)).limit(30)
    ).all()
    suppressions = db.scalars(
        select(MailSuppression)
        .where(MailSuppression.active.is_(True))
        .order_by(desc(MailSuppression.created_at))
        .limit(20)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="tendermail.html",
        context={
            "user": user,
            "active": "tendermail",
            "metrics": metrics,
            "domains": domains,
            "campaigns": campaigns,
            "suppressions": suppressions,
        },
    )


@app.get("/tendermail/{campaign_id}", response_class=HTMLResponse)
def tendermail_campaign_page(request: Request, campaign_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    campaign = db.scalar(
        select(TenderMailCampaign).where(TenderMailCampaign.campaign_id == campaign_id)
    )
    if not campaign:
        raise HTTPException(404, "Kampány nem található.")
    domain = db.scalar(
        select(MailSendingDomain).where(MailSendingDomain.domain_key == campaign.domain_key)
    )
    recipients = db.scalars(
        select(TenderMailRecipient)
        .where(TenderMailRecipient.campaign_id == campaign_id)
        .order_by(TenderMailRecipient.status, TenderMailRecipient.company_name)
    ).all()
    events = db.scalars(
        select(TenderMailEvent)
        .where(TenderMailEvent.campaign_id == campaign_id)
        .order_by(desc(TenderMailEvent.occurred_at))
        .limit(50)
    ).all()
    readiness = campaign_readiness(db, campaign_id)
    return templates.TemplateResponse(
        request=request,
        name="tendermail_campaign.html",
        context={
            "user": user,
            "active": "tendermail",
            "campaign": campaign,
            "domain": domain,
            "recipients": recipients,
            "events": events,
            "readiness": readiness,
        },
    )


@app.post("/tendermail/campaigns")
def create_tender_campaign_ui(
    request: Request,
    name: Annotated[str, Form()],
    domain_key: Annotated[str, Form()],
    subject_template: Annotated[str, Form()],
    text_template: Annotated[str, Form()],
    tender_id: Annotated[str | None, Form()] = None,
    project_id: Annotated[str | None, Form()] = None,
    hourly_rate: Annotated[int, Form()] = 100,
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        campaign = create_campaign(
            db,
            TenderCampaignIn(
                name=name,
                domain_key=domain_key,
                subject_template=subject_template,
                text_template=text_template,
                tender_id=tender_id or None,
                project_id=project_id or None,
                hourly_rate=hourly_rate,
                created_by=user.email,
            ),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(
        db,
        actor=user.email,
        action="tendermail_campaign_created",
        entity_type="mail_campaign",
        entity_id=campaign.campaign_id,
    )
    db.commit()
    return RedirectResponse(f"/tendermail/{campaign.campaign_id}", status_code=303)


@app.post("/tendermail/{campaign_id}/recipients")
def add_tender_recipient_ui(
    request: Request,
    campaign_id: str,
    email: Annotated[str, Form()],
    company_name: Annotated[str | None, Form()] = None,
    contact_name: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        add_recipient(
            db,
            campaign_id,
            TenderRecipientIn(email=email, company_name=company_name, contact_name=contact_name),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tendermail/{campaign_id}", status_code=303)


@app.post("/tendermail/{campaign_id}/recipients/import")
def import_tender_recipients_ui(request: Request, campaign_id: str, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    add_canonical_partner_recipients(db, campaign_id)
    return RedirectResponse(f"/tendermail/{campaign_id}", status_code=303)


@app.post("/tendermail/{campaign_id}/approve")
def approve_tender_campaign_ui(request: Request, campaign_id: str, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role not in _LEADERSHIP_ROLES:
        raise HTTPException(403)
    try:
        approve_campaign(db, campaign_id, user.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tendermail/{campaign_id}", status_code=303)


@app.post("/tendermail/{campaign_id}/simulate")
def simulate_tender_campaign_ui(request: Request, campaign_id: str, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role not in _LEADERSHIP_ROLES:
        raise HTTPException(403)
    try:
        queue_campaign(db, campaign_id, simulate=True)
        dispatch_batch(
            db, campaign_id, simulate=True, base_url=str(request.base_url).rstrip("/"), limit=100
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tendermail/{campaign_id}", status_code=303)


@app.get("/mail/preferences/{tracking_token}", response_class=HTMLResponse)
def mail_preferences_page(request: Request, tracking_token: str, db: Session = Depends(get_db)):
    recipient = db.scalar(
        select(TenderMailRecipient).where(TenderMailRecipient.tracking_token == tracking_token)
    )
    if not recipient:
        raise HTTPException(404, "Érvénytelen értesítési hivatkozás.")
    return templates.TemplateResponse(
        request=request,
        name="mail_preferences.html",
        context={"recipient": recipient, "done": False},
    )


@app.post("/mail/preferences/{tracking_token}", response_class=HTMLResponse)
def mail_unsubscribe(request: Request, tracking_token: str, db: Session = Depends(get_db)):
    try:
        recipient = unsubscribe_by_token(db, tracking_token)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="mail_preferences.html",
        context={"recipient": recipient, "done": True},
    )


@app.get("/api/tendermail/metrics", dependencies=[Depends(require_api_token)])
def api_tendermail_metrics(db: Session = Depends(get_db)):
    return tender_mail_metrics(db)


@app.post("/api/tendermail/domains", dependencies=[Depends(require_api_token)])
def api_tendermail_domain(data: SendingDomainIn, db: Session = Depends(get_db)):
    try:
        row = upsert_domain(db, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"domain_key": row.domain_key, "domain_name": row.domain_name}


@app.post(
    "/api/tendermail/domains/{domain_key}/verification", dependencies=[Depends(require_api_token)]
)
def api_tendermail_domain_verification(
    domain_key: str, data: DomainVerificationIn, db: Session = Depends(get_db)
):
    try:
        row = verify_domain(db, domain_key, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "domain_key": row.domain_key,
        "spf": row.spf_status,
        "dkim": row.dkim_status,
        "dmarc": row.dmarc_status,
    }


@app.post("/api/tendermail/campaigns", dependencies=[Depends(require_api_token)])
def api_tendermail_campaign(data: TenderCampaignIn, db: Session = Depends(get_db)):
    try:
        row = create_campaign(db, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"campaign_id": row.campaign_id, "status": row.status}


@app.post(
    "/api/tendermail/campaigns/{campaign_id}/recipients", dependencies=[Depends(require_api_token)]
)
def api_tendermail_recipients(
    campaign_id: str, data: TenderRecipientBatchIn, db: Session = Depends(get_db)
):
    added = suppressed = 0
    try:
        for recipient in data.recipients:
            row = add_recipient(db, campaign_id, recipient)
            if row.status == "suppressed":
                suppressed += 1
            else:
                added += 1
        canonical = (
            add_canonical_partner_recipients(db, campaign_id)
            if data.include_canonical_partner_records
            else {"added": 0, "suppressed": 0, "skipped": 0}
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "added": added + canonical["added"],
        "suppressed": suppressed + canonical["suppressed"],
        "skipped": canonical["skipped"],
    }


@app.get(
    "/api/tendermail/campaigns/{campaign_id}/readiness", dependencies=[Depends(require_api_token)]
)
def api_tendermail_readiness(campaign_id: str, db: Session = Depends(get_db)):
    try:
        return campaign_readiness(db, campaign_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post(
    "/api/tendermail/campaigns/{campaign_id}/approve", dependencies=[Depends(require_api_token)]
)
def api_tendermail_approve(campaign_id: str, actor: str = "api", db: Session = Depends(get_db)):
    try:
        row = approve_campaign(db, campaign_id, actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "campaign_id": row.campaign_id,
        "status": row.status,
        "approval_status": row.approval_status,
    }


@app.post(
    "/api/tendermail/campaigns/{campaign_id}/queue", dependencies=[Depends(require_api_token)]
)
def api_tendermail_queue(campaign_id: str, simulate: bool = False, db: Session = Depends(get_db)):
    try:
        row = queue_campaign(db, campaign_id, simulate=simulate)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"campaign_id": row.campaign_id, "status": row.status, "queued_count": row.queued_count}


@app.post(
    "/api/tendermail/campaigns/{campaign_id}/dispatch",
    dependencies=[Depends(require_internal_job_token)],
)
def api_tendermail_dispatch(
    campaign_id: str, simulate: bool = True, limit: int | None = None, db: Session = Depends(get_db)
):
    try:
        return dispatch_batch(
            db,
            campaign_id,
            simulate=simulate,
            base_url="https://tender.imperialholding.hu",
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/tendermail/events", dependencies=[Depends(require_api_token)])
def api_tendermail_event(data: MailEventIn, db: Session = Depends(get_db)):
    try:
        row = record_event(db, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"event_id": row.event_id, "event_type": row.event_type}
