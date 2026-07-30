from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .audit import audit
from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import (
    ArtifactRecord,
    ConsistencyIssue,
    DeploymentRecord,
    EnvironmentRecord,
    EventRecord,
    ModuleRegistry,
    OutboxMessage,
    PilotRun,
    ProjectObjectState,
    ProjectRegistry,
    ReleaseRecord,
    TaskRecord,
    User,
    CalculationSourceRegistry,
    EnterpriseCanonicalRecord,
    ImportCommitBatch,
    ImportDataSource,
    ImportItem,
    ImportJob,
    StagedEnterpriseRecord,
    MailSendingDomain,
    MailSuppression,
    TenderMailCampaign,
    TenderMailEvent,
    TenderMailRecipient,
    WorkspaceDocument,
    PartnerEvidence,
    PartnerFieldAccess,
)
from .copy_gate.models import ApprovalSubmission, AssemblySubmission, ContentAssetCreateRequest, CopyQualityRequest, CopySourceIn, CreativeDirectorReviewSubmission, FourGateSubmission, LiveReviewSubmission, PerformanceSubmission, MandatoryCopyGateReviewSubmission, ReleaseReviewSubmission, StrategyReviewSubmission, VisualProductionSubmission
from .schemas import (
    ArtifactIn,
    CalculationRequest,
    EnvironmentIn,
    EventIn,
    FactIn,
    HeartbeatIn,
    HouseMatchIn,
    DomainVerificationIn,
    ImportCommitIn,
    ImportItemIn,
    ImportJobIn,
    ImportPushIn,
    ImportReviewIn,
    ImportSourceIn,
    MailEventIn,
    ReleaseIn,
    RenovationCalculationIn,
    SendingDomainIn,
    TenderCampaignIn,
    TenderRecipientBatchIn,
    TenderRecipientIn,
    TaskUpdateIn,
    WorkspaceDocumentIn,
    WorkPackageUpdateIn,
    GateCheckIn,
    DailyReportIn,
    SiteIssueIn,
    DeliveryNoteIn,
    MaterialMovementIn,
    MaterialUsageIn,
    OperationsCommandIn,
    PartnerAccessCreateIn,
    PartnerAttendanceActionIn,
    PartnerChangeIn,
    PartnerProgressIn,
    DevelopmentDiscoveryIn,
    DevelopmentDiscoveryReviewIn,
    ContractGenerateIn,
    ChangeControlEventIn,
)
from .security import current_partner_access, current_user, require_api_token, require_internal_job_token, require_role, require_session_user, verify_password
from .roles import can_access, modules_for_path, public_role_payload, role_definition
from .seed import DEMO_PASSWORD, seed_database
from .services.consistency import scan_consistency, upsert_fact
from .services.commercial_integration import commercial_workspace, contract_source_status, generate_contract_package, ingest_change_control_event, ingest_contract_signed, validate_contract_payload
from .services.development_governance import create_discovery, list_discoveries, review_discovery
from .services.dashboard import dashboard_metrics
from .services.integration import ingest_event, process_outbox, register_heartbeat
from .services.file_ingestion import parse_upload
from .services.housematch import HouseProfile, housematch_repository
from .services.import_center import add_item, commit_records, create_job, create_source, import_metrics, process_job, review_record, rollback_batch
from .services.pricing import pricing_repository
from .services.workspace import create_document, document_metrics, global_search, list_documents, list_tasks, project_360, task_metrics, update_document_status, update_task, workspace_summary
from .services.operations import create_daily_report, create_delivery_note, create_issue, create_material_movement, create_operations_command, create_usage_control, field_projects, operations_portfolio, operations_summary, procurement_summary, project_operations, update_gate, update_work_package
from .services.partner_field import access_is_valid, attendance_action, authenticate_access, create_access, create_change, create_partner_issue, create_progress, deactivate_access, internal_partner_projection, partner_dashboard, review_progress, save_evidence
from .services.tender_mail import add_canonical_partner_recipients, add_recipient, approve_campaign, campaign_readiness, create_campaign, dispatch_batch, queue_campaign, record_event, suppress_email, tender_mail_metrics, unsubscribe_by_token, upsert_domain, verify_domain
from .services.pilots import run_all_pilots, run_pilot_scenario
from .services.releases import add_artifact, create_release, release_gate
from .services.content_quality import assemble_publication_bundle, create_content_asset, create_copy_brief, publish_content_asset, record_approval, record_creative_director_review, record_mandatory_copy_gate_review, record_live_publication_review, record_performance_metric, record_release_review, record_strategy_review, register_copy_source, rollback_content_asset, run_copy_quality, submit_four_gates, submit_visual_production, validate_copy_brief
from .demo_runtime import DemoRuntimeError, demo_runtime

BASE_DIR = Path(__file__).resolve().parent
PARTNER_EVIDENCE_DIR = BASE_DIR.parent / "data" / "partner_evidence"


@asynccontextmanager
async def lifespan(app: FastAPI):
    errors = settings.validate()
    if errors:
        raise RuntimeError(" | ".join(errors))
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
    yield


app = FastAPI(title="Imperial Intelligence Control Center", version=__version__, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax", https_only=settings.is_production)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["huf"] = lambda v: f"{Decimal(str(v or 0)):,.0f} Ft".replace(",", " ")
templates.env.filters["dt"] = lambda v: v.astimezone().strftime("%Y.%m.%d. %H:%M") if v else "—"
templates.env.globals["demo_password"] = (
    None if settings.is_production else DEMO_PASSWORD
)
templates.env.globals["can_access"] = can_access


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


def auth_or_redirect(request: Request, db: Session):
    user = current_user(request, db)
    if not user or not user.active:
        return None, RedirectResponse(
            f"/login?return_to={request.url.path}",
            status_code=303,
        )
    required_modules = modules_for_path(request.url.path)
    if required_modules and not can_access(user, *required_modules):
        raise HTTPException(
            status_code=403,
            detail="Ehhez a felülethez nincs szerepkör-jogosultság.",
        )
    return user, None


def partner_auth_or_redirect(request: Request, db: Session):
    access = current_partner_access(request, db)
    if not access_is_valid(access):
        request.session.pop("partner_access_id", None)
        return None, RedirectResponse("/partner-field/login", status_code=303)
    return access, None


@app.get("/health")
def health():
    return {"status": "ok", "service": "imperial-intelligence-control-center", "version": __version__, "platform_version": "5.0.0"}


@app.post("/api/content-quality/sources", dependencies=[Depends(require_api_token)])
def api_content_quality_source(payload: CopySourceIn, db: Session = Depends(get_db)):
    try:
        row = register_copy_source(db, payload, actor="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"source_key": row.source_key, "version": row.version, "content_hash": row.content_hash, "approved": row.approved}


@app.post("/api/content-quality/briefs/validate", dependencies=[Depends(require_api_token)])
def api_content_quality_brief_validate(payload: dict):
    return validate_copy_brief(payload)


@app.post("/api/content-quality/briefs", dependencies=[Depends(require_api_token)])
def api_content_quality_brief_create(payload: dict, db: Session = Depends(get_db)):
    try:
        row = create_copy_brief(db, payload, actor="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"copy_brief_id": row.copy_brief_id, "status": row.status, "source_snapshot_hash": row.source_snapshot_hash}


@app.post("/api/content-quality/briefs/{copy_brief_id}/strategy-review")
def api_content_quality_strategy_review(copy_brief_id: str, payload: StrategyReviewSubmission, user: User = Depends(require_role("owner", "admin", "marketing_editor")), db: Session = Depends(get_db)):
    try:
        row = record_strategy_review(db, copy_brief_id, payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "CopyBrief nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"copy_brief_id": row.copy_brief_id, "review_id": row.review_id, "decision": row.decision}


@app.post("/api/content-quality/assets", dependencies=[Depends(require_api_token)])
def api_content_quality_asset_create(payload: ContentAssetCreateRequest, db: Session = Depends(get_db)):
    try:
        row = create_content_asset(db, payload.asset, copy_brief_id=payload.copy_brief_id, project_id=payload.project_id, generation_trace=payload.generation_trace, actor="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "state": row.state, "content_hash": row.content_hash}


@app.post("/api/content-quality/assets/{asset_id}/copy-qa", dependencies=[Depends(require_internal_job_token)])
def api_content_quality_copy_qa(asset_id: str, payload: CopyQualityRequest, db: Session = Depends(get_db)):
    try:
        run = run_copy_quality(db, asset_id, payload.editorial_review, actor="quality-worker", evaluated_on=payload.evaluated_on)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return json.loads(run.scorecard_json) | {"run_id": run.run_id, "source_snapshot_hash": run.source_snapshot_hash}


def _record_mandatory_copy_gate(asset_id: str, payload: MandatoryCopyGateReviewSubmission, expected_gate_id: str, db: Session):
    if payload.gate_id != expected_gate_id:
        raise HTTPException(400, f"Ehhez az endpointhoz gate_id={expected_gate_id} kötelező.")
    try:
        row = record_mandatory_copy_gate_review(db, asset_id, payload, actor=f"{expected_gate_id.lower()}-gate-verifier")
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "review_id": row.review_id, "gate_id": expected_gate_id, "decision": row.decision}


@app.post("/api/content-quality/assets/{asset_id}/marketing-gate", dependencies=[Depends(require_internal_job_token)])
def api_content_quality_marketing_gate(asset_id: str, payload: MandatoryCopyGateReviewSubmission, db: Session = Depends(get_db)):
    return _record_mandatory_copy_gate(asset_id, payload, "MARKETING", db)


@app.post("/api/content-quality/assets/{asset_id}/copywriter-gate", dependencies=[Depends(require_internal_job_token)])
def api_content_quality_copywriter_gate(asset_id: str, payload: MandatoryCopyGateReviewSubmission, db: Session = Depends(get_db)):
    return _record_mandatory_copy_gate(asset_id, payload, "DIRECT_RESPONSE", db)


@app.post("/api/content-quality/assets/{asset_id}/four-gates", dependencies=[Depends(require_internal_job_token)])
def api_content_quality_four_gates(asset_id: str, payload: FourGateSubmission, db: Session = Depends(get_db)):
    try:
        return submit_four_gates(db, asset_id, payload, actor="gate-orchestrator")
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/content-quality/assets/{asset_id}/editorial-approval")
def api_content_quality_editorial_approval(asset_id: str, payload: ApprovalSubmission, user: User = Depends(require_role("owner", "admin", "marketing_editor")), db: Session = Depends(get_db)):
    try:
        row = record_approval(db, asset_id, "HUMAN_EDITORIAL", payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "state": row.state}


@app.post("/api/content-quality/assets/{asset_id}/owner-approval")
def api_content_quality_owner_approval(asset_id: str, payload: ApprovalSubmission, user: User = Depends(require_role("owner")), db: Session = Depends(get_db)):
    try:
        row = record_approval(db, asset_id, "OWNER", payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "state": row.state}


@app.post("/api/content-quality/assets/{asset_id}/visual-production", dependencies=[Depends(require_internal_job_token)])
def api_content_quality_visual_production(asset_id: str, payload: VisualProductionSubmission, db: Session = Depends(get_db)):
    try:
        row = submit_visual_production(db, asset_id, payload, actor="creative-producer")
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "generation_run_id": row.generation_run_id, "sequence_number": row.sequence_number, "status": row.status}


@app.post("/api/content-quality/assets/{asset_id}/creative-director-review", dependencies=[Depends(require_internal_job_token)])
def api_content_quality_creative_director_review(asset_id: str, payload: CreativeDirectorReviewSubmission, db: Session = Depends(get_db)):
    try:
        row = record_creative_director_review(db, asset_id, payload, actor=payload.reviewer_identity)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "review_id": row.review_id, "decision": row.decision}


@app.post("/api/content-quality/assets/{asset_id}/assembly", dependencies=[Depends(require_internal_job_token)])
def api_content_quality_assembly(asset_id: str, payload: AssemblySubmission, db: Session = Depends(get_db)):
    try:
        row = assemble_publication_bundle(db, asset_id, payload, actor="production-designer")
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "bundle_id": row.bundle_id, "bundle_hash": row.bundle_hash, "status": row.status}


@app.post("/api/content-quality/assets/{asset_id}/release-review")
def api_content_quality_release_review(asset_id: str, payload: ReleaseReviewSubmission, user: User = Depends(require_role("owner", "admin", "marketing_editor")), db: Session = Depends(get_db)):
    try:
        row = record_release_review(db, asset_id, payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"asset_id": row.asset_id, "review_id": row.review_id, "decision": row.decision}


@app.post("/api/content-quality/assets/{asset_id}/publish")
def api_content_quality_publish(asset_id: str, user: User = Depends(require_role("owner")), db: Session = Depends(get_db)):
    try:
        return publish_content_asset(db, asset_id, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/content-quality/assets/{asset_id}/live-review")
def api_content_quality_live_review(asset_id: str, payload: LiveReviewSubmission, user: User = Depends(require_role("owner", "admin", "marketing_editor")), db: Session = Depends(get_db)):
    try:
        return record_live_publication_review(db, asset_id, payload, actor=user.email)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/content-quality/assets/{asset_id}/rollback")
def api_content_quality_rollback(asset_id: str, reason: str, user: User = Depends(require_role("owner")), db: Session = Depends(get_db)):
    try:
        row = rollback_content_asset(db, asset_id, actor=user.email, reason=reason)
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    return {"asset_id": row.asset_id, "state": row.state, "content_version": row.content_version}


@app.post("/api/content-quality/assets/{asset_id}/performance", dependencies=[Depends(require_api_token)])
def api_content_quality_performance(asset_id: str, payload: PerformanceSubmission, db: Session = Depends(get_db)):
    try:
        row = record_performance_metric(db, asset_id, payload.metric, source_system=payload.source_system, actor="api")
    except KeyError as exc:
        raise HTTPException(404, "Asset nem található.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"metric_id": row.metric_id, "asset_id": row.asset_id}


@app.get("/health/live")
def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}
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


def _demo_state_for(user: User):
    state = demo_runtime.state()
    role = role_definition(user.role)
    if not role:
        raise HTTPException(403, "A felhasználó szerepköre nincs regisztrálva.")
    allowed = role.module_access
    state["modules"] = [
        module for module in state["modules"] if module["id"] in allowed
    ]
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
    if user.role != "platform-admin":
        raise HTTPException(403, "Outbox újrapróbálást csak platform admin indíthat.")
    try:
        return demo_runtime.retry_outbox(outbox_id)
    except DemoRuntimeError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/demo/reset")
def api_demo_reset(user: User = Depends(require_session_user)):
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
    db.commit()
    safe_return_to = (
        return_to
        if return_to.startswith("/") and not return_to.startswith("//")
        else "/"
    )
    return RedirectResponse(safe_return_to, status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/executive", response_class=HTMLResponse)
def executive_dashboard(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    metrics = dashboard_metrics(db)
    projects = db.scalars(select(ProjectRegistry).order_by(desc(ProjectRegistry.financial_impact_huf), desc(ProjectRegistry.updated_at)).limit(10)).all()
    events = db.scalars(select(EventRecord).where(EventRecord.status == "open", EventRecord.executive_relevance.is_(True)).order_by(desc(EventRecord.severity), desc(EventRecord.received_at)).limit(15)).all()
    issues = db.scalars(select(ConsistencyIssue).where(ConsistencyIssue.status == "open").order_by(desc(ConsistencyIssue.severity), desc(ConsistencyIssue.financial_impact_huf)).limit(10)).all()
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"user": user, "metrics": metrics, "projects": projects, "events": events, "issues": issues, "active": "executive"})


@app.get("/", response_class=HTMLResponse)
def workspace_home(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    summary = workspace_summary(db, user)
    return templates.TemplateResponse(request=request, name="workspace.html", context={"user": user, "summary": summary, "active": "workspace"})


@app.get("/tasks", response_class=HTMLResponse)
def action_center(request: Request, status: str | None = None, priority: str | None = None, project_id: str | None = None, q: str | None = None, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    rows = list_tasks(db, status=status, priority=priority, project_id=project_id, assignee=user.email, query_text=q)
    metrics = task_metrics(db, assignee=user.email)
    projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
    return templates.TemplateResponse(request=request, name="action_center.html", context={"user": user, "tasks": rows, "metrics": metrics, "projects": projects, "filters": {"status": status, "priority": priority, "project_id": project_id, "q": q}, "active": "tasks"})


@app.post("/tasks/{task_id}/update")
def action_center_update(request: Request, task_id: str, status: Annotated[str | None, Form()] = None, assignee: Annotated[str | None, Form()] = None, project_id: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        update_task(db, task_id, TaskUpdateIn(status=status, assignee=assignee), actor=user.email)
    except KeyError:
        raise HTTPException(404, "Feladat nem található.")
    target = f"/tasks?project_id={project_id}" if project_id else "/tasks"
    return RedirectResponse(target, status_code=303)


@app.get("/documents", response_class=HTMLResponse)
def documents_page(request: Request, project_id: str | None = None, category: str | None = None, approval_status: str | None = None, q: str | None = None, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    rows = list_documents(db, project_id=project_id, category=category, approval_status=approval_status, query_text=q)
    metrics = document_metrics(db)
    projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
    categories = sorted({r.category for r in db.scalars(select(WorkspaceDocument)).all()} | {"contract", "plan", "invoice", "delivery_note", "photo", "certificate", "report", "other"})
    return templates.TemplateResponse(request=request, name="documents.html", context={"user": user, "documents": rows, "metrics": metrics, "projects": projects, "categories": categories, "filters": {"project_id": project_id, "category": category, "approval_status": approval_status, "q": q}, "active": "documents"})


@app.post("/documents")
def documents_create(
    request: Request, title: Annotated[str, Form()], category: Annotated[str, Form()],
    project_id: Annotated[str | None, Form()] = None, source_url: Annotated[str | None, Form()] = None,
    source_system: Annotated[str, Form()] = "google_drive",
    owner: Annotated[str | None, Form()] = None, extracted_summary: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    create_document(db, WorkspaceDocumentIn(
        title=title, category=category, project_id=project_id or None, source_url=source_url or None,
        source_system=source_system,
        owner=owner or user.name, extracted_summary=extracted_summary or None,
    ), actor=user.email)
    return RedirectResponse("/documents", status_code=303)


@app.post("/documents/{document_id}/status")
def documents_status(request: Request, document_id: str, approval_status: Annotated[str | None, Form()] = None, verification_status: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        update_document_status(db, document_id, approval_status=approval_status, verification_status=verification_status, actor=user.email)
    except KeyError:
        raise HTTPException(404, "Dokumentum nem található.")
    return RedirectResponse("/documents", status_code=303)


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    results = global_search(db, q)
    return templates.TemplateResponse(request=request, name="search.html", context={"user": user, "q": q, "results": results, "active": "search"})


@app.get("/api/workspace/summary", dependencies=[Depends(require_api_token)])
def api_workspace_summary(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db) or db.scalar(select(User).order_by(User.id))
    return workspace_summary(db, user)


@app.get("/api/tasks", dependencies=[Depends(require_api_token)])
def api_tasks(status: str | None = None, priority: str | None = None, project_id: str | None = None, q: str | None = None, db: Session = Depends(get_db)):
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


@app.get("/commercial", response_class=HTMLResponse)
def commercial_page(request: Request, project_id: str | None = None, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    data = commercial_workspace(db, project_id=project_id)
    return templates.TemplateResponse(request=request, name="commercial.html", context={"user": user, "data": data, "active": "commercial"})


@app.get("/commercial/contracts/new", response_class=HTMLResponse)
def commercial_contract_new(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    example_path = BASE_DIR.parent / "integrations" / "contract_generator_v0_4" / "examples" / "customer_construction_valid.json"
    payload_json = example_path.read_text(encoding="utf-8") if example_path.exists() else "{}"
    return templates.TemplateResponse(request=request, name="contract_generate.html", context={"user": user, "payload_json": payload_json, "error": None, "result": None, "active": "commercial"})


@app.post("/commercial/contracts/generate", response_class=HTMLResponse)
def commercial_contract_generate(request: Request, payload_json: Annotated[str, Form()], db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    result = None
    error = None
    try:
        payload = json.loads(payload_json)
        result = generate_contract_package(db, payload, actor=user.email)
    except Exception as exc:
        error = str(exc)
    return templates.TemplateResponse(request=request, name="contract_generate.html", context={"user": user, "payload_json": payload_json, "error": error, "result": result, "active": "commercial"}, status_code=400 if error else 200)


@app.get("/commercial/files/{document_id}")
def commercial_file_download(request: Request, document_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    row = db.scalar(select(WorkspaceDocument).where(WorkspaceDocument.document_id == document_id, WorkspaceDocument.source_system == "contract_generator"))
    if not row:
        raise HTTPException(404, "Dokumentum nem található.")
    metadata = json.loads(row.metadata_json or "{}")
    path = Path(metadata.get("local_path") or "")
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "A helyi artifact nem található.")
    return FileResponse(path, filename=path.name, media_type=row.mime_type or "application/octet-stream")


@app.get("/development-governance", response_class=HTMLResponse)
def development_governance_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="development_governance.html", context={"user": user, "rows": list_discoveries(db), "active": "governance"})


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
                discovery_id=discovery_id, requested_capability=requested_capability, requested_module_key=requested_module_key or None, searched_terms=[x.strip() for x in searched_terms.split(",") if x.strip()], candidate_artifacts=[], canonical_module_key=canonical_module_key or None, canonical_object_owner=None, source_version=source_version or None, decision=decision, implementation_gap=implementation_gap, exception_reason=exception_reason or None, requested_by=user.email
            ),
            actor=user.email,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return RedirectResponse("/development-governance", status_code=303)


@app.get("/api/development-discoveries", dependencies=[Depends(require_api_token)])
def api_development_discoveries(db: Session = Depends(get_db)):
    return list_discoveries(db)


@app.post("/api/development-discoveries", dependencies=[Depends(require_api_token)])
def api_development_discovery_create(payload: DevelopmentDiscoveryIn, db: Session = Depends(get_db)):
    try:
        return create_discovery(db, payload, actor="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/development-discoveries/{discovery_id}/review", dependencies=[Depends(require_api_token)])
def api_development_discovery_review(discovery_id: str, payload: DevelopmentDiscoveryReviewIn, db: Session = Depends(get_db)):
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


@app.post("/api/commercial/contracts/{contract_number}/signed", dependencies=[Depends(require_api_token)])
def api_commercial_contract_signed(contract_number: str, project_id: str, evidence_url: str | None = None, db: Session = Depends(get_db)):
    return ingest_contract_signed(db, project_id=project_id, contract_number=contract_number, evidence_url=evidence_url, actor="api")


@app.post("/api/commercial/change-events", dependencies=[Depends(require_api_token)])
def api_commercial_change_event(payload: ChangeControlEventIn, db: Session = Depends(get_db)):
    return ingest_change_control_event(db, payload, actor="api")


@app.get("/modules", response_class=HTMLResponse)
def modules_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    modules = db.scalars(select(ModuleRegistry).order_by(ModuleRegistry.criticality.desc(), ModuleRegistry.name)).all()
    return templates.TemplateResponse(request=request, name="modules.html", context={"user": user, "modules": modules, "active": "modules"})


@app.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    projects = db.scalars(select(ProjectRegistry).order_by(desc(ProjectRegistry.updated_at))).all()
    return templates.TemplateResponse(request=request, name="projects.html", context={"user": user, "projects": projects, "active": "projects"})


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_page(request: Request, project_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if not project:
        raise HTTPException(404, "Projekt nem található.")
    data = project_360(db, project_id)
    return templates.TemplateResponse(request=request, name="project_360.html", context={"user": user, **data, "active": "projects"})


@app.get("/exceptions", response_class=HTMLResponse)
def exceptions_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    events = db.scalars(select(EventRecord).where(EventRecord.status == "open", EventRecord.executive_relevance.is_(True)).order_by(desc(EventRecord.received_at))).all()
    issues = db.scalars(select(ConsistencyIssue).where(ConsistencyIssue.status == "open").order_by(desc(ConsistencyIssue.last_detected_at))).all()
    tasks = db.scalars(select(TaskRecord).where(TaskRecord.status == "open", TaskRecord.executive_relevance.is_(True)).order_by(TaskRecord.due_at)).all()
    return templates.TemplateResponse(request=request, name="exceptions.html", context={"user": user, "events": events, "issues": issues, "tasks": tasks, "active": "exceptions"})


@app.get("/releases", response_class=HTMLResponse)
def releases_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    releases = db.scalars(select(ReleaseRecord).options(selectinload(ReleaseRecord.artifacts)).order_by(desc(ReleaseRecord.created_at))).all()
    environments = db.scalars(select(EnvironmentRecord).order_by(EnvironmentRecord.id)).all()
    deployments = db.scalars(select(DeploymentRecord).order_by(desc(DeploymentRecord.id))).all()
    return templates.TemplateResponse(request=request, name="releases.html", context={"user": user, "releases": releases, "environments": environments, "deployments": deployments, "active": "releases"})


@app.get("/pilots", response_class=HTMLResponse)
def pilots_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    pilots = db.scalars(select(PilotRun).order_by(desc(PilotRun.started_at))).all()
    return templates.TemplateResponse(request=request, name="pilots.html", context={"user": user, "pilots": pilots, "active": "pilots"})


@app.post("/pilots/run")
def run_pilots_ui(request: Request, scenario: Annotated[str, Form()], db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role not in {"owner", "admin", "managing_director"}:
        raise HTTPException(403)
    if scenario == "all":
        run_all_pilots(db)
    else:
        run_pilot_scenario(db, scenario)
    return RedirectResponse("/pilots", status_code=303)


@app.post("/api/events", dependencies=[Depends(require_api_token)])
def api_ingest_event(data: EventIn, db: Session = Depends(get_db)):
    event, created = ingest_event(db, data)
    return {"created": created, "event_id": event.event_id, "status": event.status, "severity": event.severity}


@app.post("/api/heartbeats", dependencies=[Depends(require_api_token)])
def api_heartbeat(data: HeartbeatIn, db: Session = Depends(get_db)):
    module = register_heartbeat(db, data)
    return {"module_key": module.module_key, "integration_status": module.integration_status, "last_heartbeat_at": module.last_heartbeat_at}


@app.post("/api/facts", dependencies=[Depends(require_api_token)])
def api_fact(data: FactIn, db: Session = Depends(get_db)):
    fact = upsert_fact(db, data)
    return {"id": fact.id, "project_id": fact.project_id, "fact_key": fact.fact_key}


@app.post("/api/consistency/scan", dependencies=[Depends(require_internal_job_token)])
def api_consistency_scan(project_id: str | None = None, db: Session = Depends(get_db)):
    return scan_consistency(db, project_id=project_id)


@app.post("/api/outbox/process", dependencies=[Depends(require_internal_job_token)])
def api_outbox_process(simulate_success: bool = True, db: Session = Depends(get_db)):
    return process_outbox(db, simulate_success=simulate_success)


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
    return [{"module_key": m.module_key, "name": m.name, "version": m.version, "lifecycle_status": m.lifecycle_status, "integration_status": m.integration_status, "last_heartbeat_at": m.last_heartbeat_at} for m in modules]


@app.get("/api/projects/{project_id}", dependencies=[Depends(require_api_token)])
def api_project(project_id: str, db: Session = Depends(get_db)):
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if not project:
        raise HTTPException(404)
    events = db.scalars(select(EventRecord).where(EventRecord.project_id == project_id).order_by(desc(EventRecord.occurred_at))).all()
    issues = db.scalars(select(ConsistencyIssue).where(ConsistencyIssue.project_id == project_id, ConsistencyIssue.status == "open")).all()
    return {
        "project": {"project_id": project.project_id, "name": project.name, "status": project.status, "risk_level": project.risk_level, "blocked": project.blocked, "financial_impact_huf": str(project.financial_impact_huf), "deadline_impact_days": project.deadline_impact_days, "next_action": project.next_action},
        "events": [{"event_id": e.event_id, "event_type": e.event_type, "severity": e.severity, "status": e.status, "financial_impact_huf": str(e.financial_impact_huf)} for e in events],
        "open_consistency_issues": [{"rule_code": i.rule_code, "title": i.title, "severity": i.severity} for i in issues],
    }


@app.post("/api/pilots/run", dependencies=[Depends(require_internal_job_token)])
def api_pilots_run(scenario: str = "all", db: Session = Depends(get_db)):
    pilots = run_all_pilots(db) if scenario == "all" else [run_pilot_scenario(db, scenario)]
    return [{"pilot_id": p.pilot_id, "project_id": p.project_id, "scenario": p.scenario, "status": p.status, "steps_passed": p.steps_passed, "steps_total": p.steps_total} for p in pilots]


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
    batches = db.scalars(select(ImportCommitBatch).order_by(desc(ImportCommitBatch.created_at)).limit(15)).all()
    canonical = db.scalars(select(EnterpriseCanonicalRecord).order_by(desc(EnterpriseCanonicalRecord.updated_at)).limit(20)).all()
    return templates.TemplateResponse(request=request, name="imports.html", context={"user": user, "active": "imports", "metrics": metrics, "sources": sources, "jobs": jobs, "batches": batches, "canonical": canonical})


@app.get("/imports/{job_id}", response_class=HTMLResponse)
def import_job_page(request: Request, job_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    job = db.scalar(select(ImportJob).where(ImportJob.job_id == job_id))
    if not job:
        raise HTTPException(404, "Importfutás nem található.")
    items = db.scalars(select(ImportItem).where(ImportItem.job_id == job_id).order_by(ImportItem.received_at)).all()
    staged = db.scalars(select(StagedEnterpriseRecord).where(StagedEnterpriseRecord.job_id == job_id).order_by(StagedEnterpriseRecord.domain, StagedEnterpriseRecord.canonical_name)).all()
    return templates.TemplateResponse(request=request, name="import_job.html", context={"user": user, "active": "imports", "job": job, "items": items, "staged": staged, "loads": _json_value})


@app.post("/imports/jobs")
def create_import_job_ui(request: Request, source_key: Annotated[str, Form()], name: Annotated[str, Form()], domain_hint: Annotated[str, Form()] = "enterprise", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        job = create_job(db, ImportJobIn(source_key=source_key, name=name, domain_hint=domain_hint, requested_by=user.email))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, actor=user.email, action="import_job_created", entity_type="import_job", entity_id=job.job_id)
    db.commit()
    return RedirectResponse(f"/imports/{job.job_id}", status_code=303)


@app.post("/imports/{job_id}/upload")
async def upload_import_file_ui(request: Request, job_id: str, file: UploadFile = File(...), domain_hint: Annotated[str, Form()] = "enterprise", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    raw = await file.read()
    try:
        content = parse_upload(file.filename or "feltoltes", raw)
        item = add_item(db, job_id, ImportItemIn(file_name=file.filename, mime_type=file.content_type, domain_hint=domain_hint, sha256=(content.get("metadata") or {}).get("sha256"), content=content))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, actor=user.email, action="import_file_uploaded", entity_type="import_item", entity_id=item.item_id)
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
    audit(db, actor=user.email, action="import_job_processed", entity_type="import_job", entity_id=job_id)
    db.commit()
    return RedirectResponse(f"/imports/{job_id}", status_code=303)


@app.post("/imports/{job_id}/review/{staged_id}")
def review_import_record_ui(request: Request, job_id: str, staged_id: str, review_status: Annotated[str, Form()], canonical_name: Annotated[str | None, Form()] = None, project_id: Annotated[str | None, Form()] = None, target_module: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        review_record(db, staged_id, ImportReviewIn(review_status=review_status, canonical_name=canonical_name or None, project_id=project_id or None, target_module=target_module or None))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, actor=user.email, action="import_record_reviewed", entity_type="staged_record", entity_id=staged_id)
    db.commit()
    return RedirectResponse(f"/imports/{job_id}", status_code=303)


@app.post("/imports/{job_id}/commit")
def commit_import_job_ui(request: Request, job_id: str, auto_approve_high_confidence: Annotated[bool, Form()] = False, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role not in {"owner", "admin", "managing_director"}:
        raise HTTPException(403)
    try:
        batch = commit_records(db, job_id, [], user.email, auto_approve_high_confidence=auto_approve_high_confidence)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, actor=user.email, action="import_committed", entity_type="import_batch", entity_id=batch.batch_id)
    db.commit()
    return RedirectResponse(f"/imports/{job_id}", status_code=303)


@app.post("/imports/batches/{batch_id}/rollback")
def rollback_import_batch_ui(request: Request, batch_id: str, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role not in {"owner", "admin", "managing_director"}:
        raise HTTPException(403)
    try:
        batch = rollback_batch(db, batch_id, user.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, actor=user.email, action="import_rolled_back", entity_type="import_batch", entity_id=batch.batch_id)
    db.commit()
    return RedirectResponse("/imports", status_code=303)


@app.get("/experience", response_class=HTMLResponse)
def experience_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    sources = db.scalars(select(CalculationSourceRegistry).order_by(CalculationSourceRegistry.priority)).all()
    return templates.TemplateResponse(request=request, name="experience.html", context={"user": user, "active": "experience", "catalog": pricing_repository.brand_catalog(), "house_count": len(housematch_repository.catalog()), "sources": sources})


@app.get("/api/imports/metrics", dependencies=[Depends(require_api_token)])
def api_import_metrics(db: Session = Depends(get_db)):
    return import_metrics(db)


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
        job = create_job(db, ImportJobIn(source_key=data.source_key, name=f"Connector push – {data.file_name or data.external_id or 'adatcsomag'}", domain_hint=data.domain_hint or "enterprise", requested_by="connector"))
        item = add_item(db, job.job_id, ImportItemIn(external_id=data.external_id, file_name=data.file_name, mime_type=data.mime_type, source_url=data.source_url, domain_hint=data.domain_hint, content={"records": data.records, "text": data.text, "metadata": data.metadata}))
        process_job(db, job.job_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"job_id": job.job_id, "item_id": item.item_id, "status": job.status, "records_extracted": job.records_extracted}


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
        batch = commit_records(db, job_id, data.staged_ids, data.actor, data.auto_approve_high_confidence)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"batch_id": batch.batch_id, "committed_count": batch.committed_count, "status": batch.status}


@app.post("/api/imports/batches/{batch_id}/rollback", dependencies=[Depends(require_api_token)])
def api_rollback_import(batch_id: str, db: Session = Depends(get_db)):
    try:
        batch = rollback_batch(db, batch_id, "api")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"batch_id": batch.batch_id, "rollback_count": batch.rollback_count, "status": batch.status}


@app.get("/api/calculators/catalog")
def api_calculator_catalog():
    return pricing_repository.brand_catalog()


@app.post("/api/calculators/new-build")
def api_new_build_calculation(data: CalculationRequest):
    try:
        return pricing_repository.calculate_new_build(brand=data.brand, technology=data.technology, completion_level=data.completion_level, package=data.package, gross_area_m2=data.gross_area_m2, vat_rate=data.vat_rate, include_internal=False)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/internal/calculators/new-build", dependencies=[Depends(require_api_token)])
def api_internal_new_build_calculation(data: CalculationRequest):
    try:
        return pricing_repository.calculate_new_build(brand=data.brand, technology=data.technology, completion_level=data.completion_level, package=data.package, gross_area_m2=data.gross_area_m2, vat_rate=data.vat_rate, include_internal=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/calculators/renovation/catalog")
def api_renovation_catalog(q: str = "", limit: int = 50):
    return pricing_repository.renovation_catalog(query=q, limit=limit)


@app.post("/api/calculators/renovation")
def api_renovation_calculation(data: RenovationCalculationIn):
    try:
        return pricing_repository.calculate_renovation(lines=[line.model_dump() for line in data.lines], vat_rate=data.vat_rate)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/housematch/catalog")
def api_housematch_catalog(brand: str | None = None):
    return housematch_repository.catalog(brand=brand)


@app.post("/api/housematch/match")
def api_housematch(data: HouseMatchIn):
    try:
        return housematch_repository.match(HouseProfile(budget_huf=data.budget_huf, target_area_m2=data.target_area_m2, lifestyle=data.lifestyle, allowed_brands=tuple(data.allowed_brands), score_profile=data.score_profile), limit=data.limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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


@app.get("/operations", response_class=HTMLResponse)
def operations_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="operations.html", context={"user": user, "summary": operations_summary(db), "portfolio": operations_portfolio(db), "active": "operations"})


@app.get("/operations/projects/{project_id}", response_class=HTMLResponse)
def operations_project_page(request: Request, project_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        data = project_operations(db, project_id)
    except KeyError:
        raise HTTPException(404, "Projekt nem található.")
    return templates.TemplateResponse(request=request, name="operations_project.html", context={"user": user, **data, **internal_partner_projection(db, project_id), "active": "operations", "requested_tab": request.query_params.get("tab")})


@app.post("/operations/work-packages/{work_package_id}")
def operations_work_package_update(request: Request, work_package_id: str, status: Annotated[str | None, Form()] = None, progress_pct: Annotated[int | None, Form()] = None, assignee: Annotated[str | None, Form()] = None, blocked: Annotated[str | None, Form()] = None, block_reason: Annotated[str | None, Form()] = None, next_action: Annotated[str | None, Form()] = None, project_id: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        update_work_package(db, work_package_id, WorkPackageUpdateIn(status=status, progress_pct=progress_pct, assignee=assignee or None, blocked=blocked == "true" if blocked is not None else None, block_reason=block_reason or None, next_action=next_action or None), actor=user.email)
    except KeyError:
        raise HTTPException(404, "Munkacsomag nem található.")
    return RedirectResponse(f"/operations/projects/{project_id}" if project_id else "/operations", status_code=303)


@app.post("/operations/gates/{gate_id}")
def operations_gate_update(request: Request, gate_id: str, status: Annotated[str, Form()], evidence_url: Annotated[str | None, Form()] = None, notes: Annotated[str | None, Form()] = None, project_id: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        update_gate(db, gate_id, GateCheckIn(status=status, evidence_url=evidence_url or None, notes=notes or None, checked_by=user.email), actor=user.email)
    except KeyError:
        raise HTTPException(404, "Kapu nem található.")
    return RedirectResponse(f"/operations/projects/{project_id}" if project_id else "/operations", status_code=303)


@app.get("/field", response_class=HTMLResponse)
def field_home(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="field.html", context={"user": user, "projects": field_projects(db), "active": "field"})


@app.get("/field/{project_id}", response_class=HTMLResponse)
def field_project(request: Request, project_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        data = project_operations(db, project_id)
    except KeyError:
        raise HTTPException(404, "Projekt nem található.")
    return templates.TemplateResponse(request=request, name="field_project.html", context={"user": user, **data, "active": "field"})


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
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    create_daily_report(db, DailyReportIn(project_id=project_id, report_date=_form_datetime(report_date), reporter=reporter or user.name, weather=weather or None, workers_total=workers_total, summary=summary, blockers=blockers or None, safety_status=safety_status, quality_status=quality_status, evidence_url=evidence_url or None, voice_note_text=voice_note_text or None, source_device_id=source_device_id or None), actor=user.email)
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
    db: Session = Depends(get_db),
):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    create_issue(db, SiteIssueIn(project_id=project_id, work_package_id=work_package_id or None, issue_type=issue_type, severity=severity, title=title, description=description or None, location=location or None, responsible=responsible or "Projektvezetés", due_at=_form_datetime(due_at, end_of_day=True), evidence_url=evidence_url or None, financial_impact_huf=financial_impact_huf, deadline_impact_days=deadline_impact_days), actor=user.email)
    return RedirectResponse(f"/field/{project_id}", status_code=303)


@app.get("/partner-field-sw.js")
def partner_field_service_worker():
    path = BASE_DIR / "static" / "partner-field-service-worker.js"
    return FileResponse(path, media_type="application/javascript", headers={"Service-Worker-Allowed": "/partner-field"})


@app.get("/partner-field/login", response_class=HTMLResponse)
def partner_field_login_page(request: Request):
    return templates.TemplateResponse(request=request, name="partner_field_login.html", context={"error": None})


@app.post("/partner-field/login", response_class=HTMLResponse)
def partner_field_login(request: Request, access_code: Annotated[str, Form()], db: Session = Depends(get_db)):
    access = authenticate_access(db, access_code)
    if not access:
        return templates.TemplateResponse(request=request, name="partner_field_login.html", context={"error": "Érvénytelen vagy lejárt belépési kód."}, status_code=401)
    request.session["partner_access_id"] = access.access_id
    audit(db, actor=f"partner:{access.access_id}", action="partner_field.login", entity_type="partner_field_access", entity_id=access.access_id)
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
    return templates.TemplateResponse(request=request, name="partner_field.html", context={**partner_dashboard(db, access), "message": request.query_params.get("message"), "error": request.query_params.get("error")})


@app.post("/partner-field/attendance")
def partner_field_attendance(request: Request, action: Annotated[str, Form()], worker_ids: Annotated[list[str], Form()], declaration_accepted: Annotated[bool, Form()] = False, latitude: Annotated[Decimal | None, Form()] = None, longitude: Annotated[Decimal | None, Form()] = None, accuracy_m: Annotated[Decimal | None, Form()] = None, source_device_id: Annotated[str | None, Form()] = None, note: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    access, redirect = partner_auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        attendance_action(db, access, PartnerAttendanceActionIn(worker_ids=worker_ids, action=action, declaration_accepted=declaration_accepted, latitude=latitude, longitude=longitude, accuracy_m=accuracy_m, source_device_id=source_device_id, note=note or None))
    except (ValueError, PermissionError) as exc:
        return RedirectResponse(f"/partner-field?error={str(exc)}", status_code=303)
    label = "Érkezés" if action == "check_in" else "Távozás"
    return RedirectResponse(f"/partner-field?message={label} rögzítve.", status_code=303)


@app.post("/partner-field/progress")
def partner_field_progress(request: Request, summary: Annotated[str, Form()], reported_progress_pct: Annotated[int | None, Form()] = None, quantity: Annotated[Decimal | None, Form()] = None, unit: Annotated[str | None, Form()] = None, problem_text: Annotated[str | None, Form()] = None, safety_note: Annotated[str | None, Form()] = None, quality_note: Annotated[str | None, Form()] = None, source_device_id: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    access, redirect = partner_auth_or_redirect(request, db)
    if redirect:
        return redirect
    create_progress(db, access, PartnerProgressIn(reported_progress_pct=reported_progress_pct, quantity=quantity, unit=unit or None, summary=summary, problem_text=problem_text or None, safety_note=safety_note or None, quality_note=quality_note or None, source_device_id=source_device_id))
    return RedirectResponse("/partner-field?message=Haladási jelentés beküldve ellenőrzésre.", status_code=303)


@app.post("/partner-field/issues")
def partner_field_issue(request: Request, issue_type: Annotated[str, Form()], severity: Annotated[str, Form()], title: Annotated[str, Form()], description: Annotated[str | None, Form()] = None, location: Annotated[str | None, Form()] = None, source_device_id: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    access, redirect = partner_auth_or_redirect(request, db)
    if redirect:
        return redirect
    create_partner_issue(db, access, issue_type=issue_type, severity=severity, title=title, description=description or None, location=location or None, source_device_id=source_device_id)
    return RedirectResponse("/partner-field?message=Probléma rögzítve és továbbítva a projektvezetésnek.", status_code=303)


@app.post("/partner-field/changes")
def partner_field_change(request: Request, change_type: Annotated[str, Form()], title: Annotated[str, Form()], description: Annotated[str, Form()], requested_by: Annotated[str | None, Form()] = None, deadline_impact_days: Annotated[int, Form()] = 0, source_device_id: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    access, redirect = partner_auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        create_change(db, access, PartnerChangeIn(change_type=change_type, title=title, description=description, requested_by=requested_by or None, deadline_impact_days=deadline_impact_days, source_device_id=source_device_id))
    except PermissionError as exc:
        return RedirectResponse(f"/partner-field?error={str(exc)}", status_code=303)
    return RedirectResponse("/partner-field?message=Változásbejelentés rögzítve. Jóváhagyásig nem módosítja a scope-ot vagy az árat.", status_code=303)


@app.post("/partner-field/photos")
async def partner_field_photos(request: Request, photos: list[UploadFile] = File(...), category: Annotated[str, Form()] = "progress", caption: Annotated[str | None, Form()] = None, progress_report_id: Annotated[str | None, Form()] = None, change_notice_id: Annotated[str | None, Form()] = None, latitude: Annotated[Decimal | None, Form()] = None, longitude: Annotated[Decimal | None, Form()] = None, source_device_id: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    access, redirect = partner_auth_or_redirect(request, db)
    if redirect:
        return redirect
    saved = 0
    try:
        for photo in photos[:10]:
            raw = await photo.read()
            save_evidence(db, access, file_name=photo.filename or "helyszini-foto", mime_type=photo.content_type or "", raw=raw, category=category, caption=caption or None, progress_report_id=progress_report_id or None, issue_id=None, change_notice_id=change_notice_id or None, latitude=latitude, longitude=longitude, source_device_id=source_device_id, storage_root=PARTNER_EVIDENCE_DIR)
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
    if not user and (not access_is_valid(access) or access.access_id != row.access_id):
        raise HTTPException(403, "Nincs jogosultság a képhez.")
    path = Path(row.storage_path)
    if not path.exists():
        raise HTTPException(404, "A képfájl nem található.")
    return FileResponse(path, media_type=row.mime_type, filename=row.file_name)


@app.post("/operations/projects/{project_id}/partner-accesses")
def operations_partner_access_create(request: Request, project_id: str, company_name: Annotated[str, Form()], access_code: Annotated[str, Form()], work_package_id: Annotated[str | None, Form()] = None, contact_name: Annotated[str | None, Form()] = None, contact_phone: Annotated[str | None, Form()] = None, company_tax_number: Annotated[str | None, Form()] = None, worker_names: Annotated[str | None, Form()] = None, valid_until: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        create_access(db, PartnerAccessCreateIn(company_name=company_name, project_id=project_id, work_package_id=work_package_id or None, contact_name=contact_name or None, contact_phone=contact_phone or None, company_tax_number=company_tax_number or None, access_code=access_code, worker_names=[x.strip() for x in (worker_names or "").splitlines() if x.strip()], valid_until=_form_datetime(valid_until, end_of_day=True)), actor=user.email)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/operations/projects/{project_id}?tab=partners", status_code=303)


@app.post("/operations/partner-accesses/{access_id}/deactivate")
def operations_partner_access_deactivate(request: Request, access_id: str, project_id: Annotated[str, Form()], db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        deactivate_access(db, access_id, actor=user.email)
    except KeyError:
        raise HTTPException(404, "Hozzáférés nem található.")
    return RedirectResponse(f"/operations/projects/{project_id}?tab=partners", status_code=303)


@app.post("/operations/partner-progress/{progress_report_id}/review")
def operations_partner_progress_review(request: Request, progress_report_id: str, project_id: Annotated[str, Form()], decision: Annotated[str, Form()], db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        review_progress(db, progress_report_id, decision, actor=user.email)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/operations/projects/{project_id}?tab=partners", status_code=303)


@app.get("/procurement/workbench", response_class=HTMLResponse)
def procurement_workbench(request: Request, project_id: str | None = None, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    projects = db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all()
    return templates.TemplateResponse(request=request, name="procurement_workbench.html", context={"user": user, "projects": projects, "selected_project_id": project_id, **procurement_summary(db, project_id), "active": "procurement"})


@app.get("/procurement/projects/{project_id}", response_class=HTMLResponse)
def procurement_project(request: Request, project_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if not project:
        raise HTTPException(404, "Projekt nem található.")
    return templates.TemplateResponse(request=request, name="procurement_project.html", context={"user": user, "project": project, **procurement_summary(db, project_id), "active": "procurement"})


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
            ),
            actor=user.email,
        )
    except KeyError:
        raise HTTPException(404, "Rendelés nem található.")
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


@app.post("/procurement/projects/{project_id}/movements")
def procurement_movement_create(request: Request, project_id: str, lot_id: Annotated[str, Form()], movement_type: Annotated[str, Form()], quantity: Annotated[Decimal, Form()], from_location: Annotated[str | None, Form()] = None, to_location: Annotated[str | None, Form()] = None, responsible: Annotated[str | None, Form()] = None, note: Annotated[str | None, Form()] = None, occurred_at: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    try:
        create_material_movement(db, MaterialMovementIn(lot_id=lot_id, movement_type=movement_type, quantity=quantity, from_location=from_location or None, to_location=to_location or None, responsible=responsible or user.name, note=note or None, occurred_at=_form_datetime(occurred_at)), actor=user.email)
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
    create_usage_control(db, MaterialUsageIn(project_id=project_id, work_package_id=work_package_id or None, lot_id=lot_id or None, subcontractor=subcontractor or None, planned_quantity=planned_quantity, waste_pct=waste_pct, actual_quantity=actual_quantity, unit=unit, unit_cost_huf=unit_cost_huf, damage_huf=damage_huf, contractual_basis=contractual_basis or None), actor=user.email)
    return RedirectResponse(f"/procurement/projects/{project_id}", status_code=303)


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
        "phases": [{"phase_id": p.phase_id, "name": p.name, "status": p.status, "progress_pct": p.progress_pct} for p in data["phases"]],
        "work_packages": [{"work_package_id": p.work_package_id, "name": p.name, "status": p.status, "progress_pct": p.progress_pct, "blocked": p.blocked} for p in data["packages"]],
        "open_issues": [{"issue_id": i.issue_id, "title": i.title, "severity": i.severity, "status": i.status} for i in data["issues"] if i.status == "open"],
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
    return {"message_id": row.message_id, "status": row.status, "destination_module": row.destination_module}


@app.post("/api/procurement/delivery-notes", dependencies=[Depends(require_api_token)])
def api_delivery_note(payload: DeliveryNoteIn, db: Session = Depends(get_db)):
    try:
        row, lot = create_delivery_note(db, payload, actor="api")
    except KeyError:
        raise HTTPException(404, "Rendelés nem található.")
    return {"delivery_note_id": row.delivery_note_id, "lot_id": lot.lot_id if lot else None, "document_status": row.document_status}


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
    return {"control_id": row.control_id, "allowed_quantity": str(row.allowed_quantity), "decision_status": row.decision_status}


@app.get("/tendermail", response_class=HTMLResponse)
def tendermail_page(request: Request, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    metrics = tender_mail_metrics(db)
    domains = db.scalars(select(MailSendingDomain).order_by(MailSendingDomain.domain_name)).all()
    campaigns = db.scalars(select(TenderMailCampaign).order_by(desc(TenderMailCampaign.created_at)).limit(30)).all()
    suppressions = db.scalars(select(MailSuppression).where(MailSuppression.active.is_(True)).order_by(desc(MailSuppression.created_at)).limit(20)).all()
    return templates.TemplateResponse(request=request, name="tendermail.html", context={"user": user, "active": "tendermail", "metrics": metrics, "domains": domains, "campaigns": campaigns, "suppressions": suppressions})


@app.get("/tendermail/{campaign_id}", response_class=HTMLResponse)
def tendermail_campaign_page(request: Request, campaign_id: str, db: Session = Depends(get_db)):
    user, redirect = auth_or_redirect(request, db)
    if redirect:
        return redirect
    campaign = db.scalar(select(TenderMailCampaign).where(TenderMailCampaign.campaign_id == campaign_id))
    if not campaign:
        raise HTTPException(404, "Kampány nem található.")
    domain = db.scalar(select(MailSendingDomain).where(MailSendingDomain.domain_key == campaign.domain_key))
    recipients = db.scalars(select(TenderMailRecipient).where(TenderMailRecipient.campaign_id == campaign_id).order_by(TenderMailRecipient.status, TenderMailRecipient.company_name)).all()
    events = db.scalars(select(TenderMailEvent).where(TenderMailEvent.campaign_id == campaign_id).order_by(desc(TenderMailEvent.occurred_at)).limit(50)).all()
    readiness = campaign_readiness(db, campaign_id)
    return templates.TemplateResponse(request=request, name="tendermail_campaign.html", context={"user": user, "active": "tendermail", "campaign": campaign, "domain": domain, "recipients": recipients, "events": events, "readiness": readiness})


@app.post("/tendermail/campaigns")
def create_tender_campaign_ui(request: Request, name: Annotated[str, Form()], domain_key: Annotated[str, Form()], subject_template: Annotated[str, Form()], text_template: Annotated[str, Form()], tender_id: Annotated[str | None, Form()] = None, project_id: Annotated[str | None, Form()] = None, hourly_rate: Annotated[int, Form()] = 100, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        campaign = create_campaign(db, TenderCampaignIn(name=name, domain_key=domain_key, subject_template=subject_template, text_template=text_template, tender_id=tender_id or None, project_id=project_id or None, hourly_rate=hourly_rate, created_by=user.email))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, actor=user.email, action="tendermail_campaign_created", entity_type="mail_campaign", entity_id=campaign.campaign_id)
    db.commit()
    return RedirectResponse(f"/tendermail/{campaign.campaign_id}", status_code=303)


@app.post("/tendermail/{campaign_id}/recipients")
def add_tender_recipient_ui(request: Request, campaign_id: str, email: Annotated[str, Form()], company_name: Annotated[str | None, Form()] = None, contact_name: Annotated[str | None, Form()] = None, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        add_recipient(db, campaign_id, TenderRecipientIn(email=email, company_name=company_name, contact_name=contact_name))
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
    if not user or user.role not in {"owner", "admin", "managing_director"}:
        raise HTTPException(403)
    try:
        approve_campaign(db, campaign_id, user.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tendermail/{campaign_id}", status_code=303)


@app.post("/tendermail/{campaign_id}/simulate")
def simulate_tender_campaign_ui(request: Request, campaign_id: str, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user or user.role not in {"owner", "admin", "managing_director"}:
        raise HTTPException(403)
    try:
        queue_campaign(db, campaign_id, simulate=True)
        dispatch_batch(db, campaign_id, simulate=True, base_url=str(request.base_url).rstrip("/"), limit=100)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/tendermail/{campaign_id}", status_code=303)


@app.get("/mail/preferences/{tracking_token}", response_class=HTMLResponse)
def mail_preferences_page(request: Request, tracking_token: str, db: Session = Depends(get_db)):
    recipient = db.scalar(select(TenderMailRecipient).where(TenderMailRecipient.tracking_token == tracking_token))
    if not recipient:
        raise HTTPException(404, "Érvénytelen értesítési hivatkozás.")
    return templates.TemplateResponse(request=request, name="mail_preferences.html", context={"recipient": recipient, "done": False})


@app.post("/mail/preferences/{tracking_token}", response_class=HTMLResponse)
def mail_unsubscribe(request: Request, tracking_token: str, db: Session = Depends(get_db)):
    try:
        recipient = unsubscribe_by_token(db, tracking_token)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return templates.TemplateResponse(request=request, name="mail_preferences.html", context={"recipient": recipient, "done": True})


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


@app.post("/api/tendermail/domains/{domain_key}/verification", dependencies=[Depends(require_api_token)])
def api_tendermail_domain_verification(domain_key: str, data: DomainVerificationIn, db: Session = Depends(get_db)):
    try:
        row = verify_domain(db, domain_key, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"domain_key": row.domain_key, "spf": row.spf_status, "dkim": row.dkim_status, "dmarc": row.dmarc_status}


@app.post("/api/tendermail/campaigns", dependencies=[Depends(require_api_token)])
def api_tendermail_campaign(data: TenderCampaignIn, db: Session = Depends(get_db)):
    try:
        row = create_campaign(db, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"campaign_id": row.campaign_id, "status": row.status}


@app.post("/api/tendermail/campaigns/{campaign_id}/recipients", dependencies=[Depends(require_api_token)])
def api_tendermail_recipients(campaign_id: str, data: TenderRecipientBatchIn, db: Session = Depends(get_db)):
    added = suppressed = 0
    try:
        for recipient in data.recipients:
            row = add_recipient(db, campaign_id, recipient)
            if row.status == "suppressed":
                suppressed += 1
            else:
                added += 1
        canonical = add_canonical_partner_recipients(db, campaign_id) if data.include_canonical_partner_records else {"added": 0, "suppressed": 0, "skipped": 0}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"added": added + canonical["added"], "suppressed": suppressed + canonical["suppressed"], "skipped": canonical["skipped"]}


@app.get("/api/tendermail/campaigns/{campaign_id}/readiness", dependencies=[Depends(require_api_token)])
def api_tendermail_readiness(campaign_id: str, db: Session = Depends(get_db)):
    try:
        return campaign_readiness(db, campaign_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/tendermail/campaigns/{campaign_id}/approve", dependencies=[Depends(require_api_token)])
def api_tendermail_approve(campaign_id: str, actor: str = "api", db: Session = Depends(get_db)):
    try:
        row = approve_campaign(db, campaign_id, actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"campaign_id": row.campaign_id, "status": row.status, "approval_status": row.approval_status}


@app.post("/api/tendermail/campaigns/{campaign_id}/queue", dependencies=[Depends(require_api_token)])
def api_tendermail_queue(campaign_id: str, simulate: bool = False, db: Session = Depends(get_db)):
    try:
        row = queue_campaign(db, campaign_id, simulate=simulate)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"campaign_id": row.campaign_id, "status": row.status, "queued_count": row.queued_count}


@app.post("/api/tendermail/campaigns/{campaign_id}/dispatch", dependencies=[Depends(require_internal_job_token)])
def api_tendermail_dispatch(campaign_id: str, simulate: bool = True, limit: int | None = None, db: Session = Depends(get_db)):
    try:
        return dispatch_batch(db, campaign_id, simulate=simulate, base_url="https://tender.imperialholding.hu", limit=limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/tendermail/events", dependencies=[Depends(require_api_token)])
def api_tendermail_event(data: MailEventIn, db: Session = Depends(get_db)):
    try:
        row = record_event(db, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"event_id": row.event_id, "event_type": row.event_type}
