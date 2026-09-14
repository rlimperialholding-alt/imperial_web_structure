from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from ..audit import audit
from ..models import (
    ChangeControlCase,
    ChangeControlVersion,
    PMGateCheck,
    PMPhase,
    PMWorkPackage,
    ProjectControlBaseline,
    ProjectControlForecast,
    ProjectControlRecoveryAction,
    ProjectControlVariance,
    ProjectControlWeeklyReport,
    ProjectFinancePlan,
    ProjectRegistry,
    SiteIssue,
)
from ..schemas import (
    EventIn,
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
)
from .integration import ingest_event
from .project_finance import plan_summary

VIEW_ROLES = {
    "owner", "managing-director", "project-manager", "finance",
    "technical-prep", "designer", "platform-admin",
}
PM_ROLES = {"project-manager"}
TECHNICAL_ROLES = {"technical-prep", "designer"}
FINANCE_ROLES = {"finance"}
LEADERSHIP_ROLES = {"owner", "managing-director"}
MINIMUM_MARGIN_PERCENT = Decimal("35.00")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _identity(user: object, allowed: set[str]) -> tuple[str, str]:
    role = str(getattr(user, "role", ""))
    email = str(getattr(user, "email", "")).strip().lower()
    if role not in allowed or not email:
        raise PermissionError("Ehhez a Project Control művelethez nincs jogosultsága.")
    return role, email


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _baseline(db: Session, baseline_id: str, *, lock: bool = False) -> ProjectControlBaseline:
    stmt = select(ProjectControlBaseline).where(ProjectControlBaseline.baseline_id == baseline_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(baseline_id)
    return row


def _forecast(db: Session, forecast_id: str, *, lock: bool = False) -> ProjectControlForecast:
    stmt = select(ProjectControlForecast).where(ProjectControlForecast.forecast_id == forecast_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(forecast_id)
    return row


def _variance(db: Session, variance_id: str, *, lock: bool = False) -> ProjectControlVariance:
    stmt = select(ProjectControlVariance).where(ProjectControlVariance.variance_id == variance_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(variance_id)
    return row


def _action(db: Session, action_id: str, *, lock: bool = False) -> ProjectControlRecoveryAction:
    stmt = select(ProjectControlRecoveryAction).where(ProjectControlRecoveryAction.action_id == action_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(action_id)
    return row


def _report(db: Session, report_id: str, *, lock: bool = False) -> ProjectControlWeeklyReport:
    stmt = select(ProjectControlWeeklyReport).where(ProjectControlWeeklyReport.report_id == report_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(report_id)
    return row


def _finance_plan(db: Session, project_id: str) -> ProjectFinancePlan:
    row = db.scalar(
        select(ProjectFinancePlan)
        .options(selectinload(ProjectFinancePlan.budget_lines), selectinload(ProjectFinancePlan.cashflow_lines))
        .where(ProjectFinancePlan.project_id == project_id, ProjectFinancePlan.status == "approved")
        .order_by(desc(ProjectFinancePlan.version))
    )
    if not row:
        raise ValueError("A projektnek nincs jóváhagyott pénzügyi baseline-ja.")
    return row


def _emit(db: Session, project_id: str, event_type: str, object_id: str, status: str, actor: str, summary: str, *, executive: bool = False) -> None:
    ingest_event(
        db,
        EventIn(
            event_id=f"EVT-PC-{event_type}-{object_id}"[:120],
            dedupe_key=f"project-control:{event_type}:{object_id}:{status}"[:255],
            project_id=project_id,
            source_module="project-control",
            event_type=event_type,
            object_type="ProjectControl",
            object_id=object_id,
            status=status,
            executive_relevance=executive,
            payload={"summary": summary},
            route_to=["pm-cockpit", "financial-control", "smart-calendar", "my-imperial", "executive-dashboard"],
        ),
        actor=actor,
    )


def _schedule_snapshot(db: Session, project_id: str) -> dict:
    phases = db.scalars(select(PMPhase).where(PMPhase.project_id == project_id).order_by(PMPhase.sequence)).all()
    packages = db.scalars(select(PMWorkPackage).where(PMWorkPackage.project_id == project_id).order_by(PMWorkPackage.work_package_id)).all()
    if not packages:
        raise ValueError("A baseline-hoz legalább egy kanonikus munkacsomag szükséges.")
    return {
        "source": "operations-workspace",
        "phases": [
            {"phase_id": row.phase_id, "status": row.status, "planned_start": row.planned_start, "planned_end": row.planned_end, "progress_pct": row.progress_pct, "source_version": row.source_version}
            for row in phases
        ],
        "work_packages": [
            {"work_package_id": row.work_package_id, "phase_id": row.phase_id, "status": row.status, "planned_start": row.planned_start, "planned_end": row.planned_end, "budget_huf": row.budget_huf, "source_module": row.source_module, "source_object_id": row.source_object_id, "source_version": row.source_version}
            for row in packages
        ],
    }


def create_baseline(db: Session, data: ProjectControlBaselineIn, user: object) -> ProjectControlBaseline:
    _role, email = _identity(user, PM_ROLES)
    if data.planned_end < data.planned_start:
        raise ValueError("A baseline befejezése nem előzheti meg a kezdést.")
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == data.project_id))
    if not project:
        raise KeyError(data.project_id)
    design_gate = db.scalar(
        select(PMGateCheck).where(
            PMGateCheck.project_id == data.project_id,
            PMGateCheck.gate_code.in_(("design_freeze", "G5")),
            PMGateCheck.status == "passed",
        )
    )
    if not design_gate:
        raise ValueError("A Design Freeze/G5 kapu igazolt teljesülése nélkül baseline nem készíthető.")
    open_baseline = db.scalar(
        select(ProjectControlBaseline).where(
            ProjectControlBaseline.project_id == data.project_id,
            ProjectControlBaseline.status.in_(("draft", "review")),
        )
    )
    if open_baseline:
        return open_baseline
    finance_plan = _finance_plan(db, data.project_id)
    schedule = _schedule_snapshot(db, data.project_id)
    financial = plan_summary(finance_plan)
    latest = db.scalar(
        select(ProjectControlBaseline).where(ProjectControlBaseline.project_id == data.project_id).order_by(desc(ProjectControlBaseline.version))
    )
    version = (latest.version if latest else 0) + 1
    payload = {
        "project_id": data.project_id,
        "version": version,
        "finance_plan_id": finance_plan.plan_id,
        "scope_document_id": data.scope_document_id,
        "scope_version": data.scope_version,
        "scope_sha256": data.scope_sha256.lower(),
        "planned_start": data.planned_start,
        "planned_end": data.planned_end,
        "schedule": schedule,
        "financial": financial,
    }
    row = ProjectControlBaseline(
        baseline_id=f"PCB-{uuid4().hex[:12].upper()}",
        project_id=data.project_id,
        version=version,
        finance_plan_id=finance_plan.plan_id,
        scope_document_id=data.scope_document_id,
        scope_version=data.scope_version,
        scope_sha256=data.scope_sha256.lower(),
        planned_start=data.planned_start,
        planned_end=data.planned_end,
        schedule_snapshot_json=_json(schedule),
        financial_snapshot_json=_json(financial),
        content_sha256=_sha(payload),
        note=data.note.strip(),
        created_by=email,
    )
    db.add(row)
    audit(db, actor=email, action="project_control.baseline.create", entity_type="project_control_baseline", entity_id=row.baseline_id, after=payload)
    db.commit()
    db.refresh(row)
    return row


def submit_baseline(db: Session, baseline_id: str, user: object) -> ProjectControlBaseline:
    _role, email = _identity(user, PM_ROLES)
    row = _baseline(db, baseline_id, lock=True)
    if row.status != "draft":
        raise ValueError("Csak draft baseline küldhető review-ba.")
    if email != row.created_by:
        raise PermissionError("A baseline-t a létrehozó projektmenedzser küldheti review-ba.")
    row.status = "review"
    row.submitted_by = email
    row.submitted_at = utcnow()
    audit(db, actor=email, action="project_control.baseline.submit", entity_type="project_control_baseline", entity_id=row.baseline_id, after={"status": row.status})
    db.commit()
    db.refresh(row)
    return row


def review_baseline(db: Session, baseline_id: str, data: ProjectControlBaselineReviewIn, user: object) -> ProjectControlBaseline:
    allowed = TECHNICAL_ROLES if data.gate == "technical" else FINANCE_ROLES
    _role, email = _identity(user, allowed)
    row = _baseline(db, baseline_id, lock=True)
    if row.status != "review":
        raise ValueError("Csak review állapotú baseline bírálható.")
    if email in {row.created_by, row.submitted_by, row.technical_approved_by, row.finance_approved_by}:
        raise ValueError("A baseline készítője vagy másik kapujának jóváhagyója nem bírálhatja ezt a kaput.")
    if data.decision == "reject":
        row.status = "rejected"
    elif data.gate == "technical":
        row.technical_approved_by = email
        row.technical_note = data.note.strip()
        row.technical_approved_at = utcnow()
    else:
        row.finance_approved_by = email
        row.finance_note = data.note.strip()
        row.finance_approved_at = utcnow()
    audit(db, actor=email, action=f"project_control.baseline.{data.gate}_{data.decision}", entity_type="project_control_baseline", entity_id=row.baseline_id, after=data.model_dump())
    db.commit()
    db.refresh(row)
    return row


def decide_baseline(db: Session, baseline_id: str, data: ProjectControlLeadershipDecisionIn, user: object) -> ProjectControlBaseline:
    _role, email = _identity(user, LEADERSHIP_ROLES)
    row = _baseline(db, baseline_id, lock=True)
    if row.status != "review" or not row.technical_approved_by or not row.finance_approved_by:
        raise ValueError("A vezetői döntéshez külön műszaki és pénzügyi jóváhagyás szükséges.")
    if email in {row.created_by, row.submitted_by, row.technical_approved_by, row.finance_approved_by}:
        raise ValueError("A vezetői jóváhagyónak el kell különülnie az előkészítőktől.")
    if data.decision == "reject":
        row.status = "rejected"
    else:
        previous = db.scalars(
            select(ProjectControlBaseline).where(
                ProjectControlBaseline.project_id == row.project_id,
                ProjectControlBaseline.status == "approved",
                ProjectControlBaseline.baseline_id != row.baseline_id,
            )
        ).all()
        for old in previous:
            old.status = "superseded"
        row.status = "approved"
        row.leadership_approved_by = email
        row.leadership_note = data.note.strip()
        row.leadership_approved_at = utcnow()
    audit(db, actor=email, action=f"project_control.baseline.leadership_{data.decision}", entity_type="project_control_baseline", entity_id=row.baseline_id, after=data.model_dump())
    if row.status == "approved":
        _emit(db, row.project_id, "PROJECT_BASELINE_APPROVED", row.baseline_id, row.status, email, "A projekt scope-, ütem- és pénzügyi baseline-ja jóváhagyva.")
    else:
        db.commit()
    db.refresh(row)
    return row


def _progress(packages: list[PMWorkPackage]) -> Decimal:
    if not packages:
        return Decimal("0")
    weights = [max(Decimal(str(row.budget_huf or 0)), Decimal("1")) for row in packages]
    weighted_progress = sum(
        (Decimal(row.progress_pct) * weight for row, weight in zip(packages, weights)),
        Decimal("0"),
    )
    return (weighted_progress / sum(weights, Decimal("0"))).quantize(Decimal("0.01"))


def _planned_progress(baseline: ProjectControlBaseline, as_of_date: date) -> Decimal:
    total = max((baseline.planned_end - baseline.planned_start).days, 1)
    elapsed = (as_of_date - baseline.planned_start).days
    return (Decimal(max(0, min(elapsed, total))) / Decimal(total) * Decimal("100")).quantize(Decimal("0.01"))


def _change_snapshot(db: Session, project_id: str, packages: list[PMWorkPackage]) -> dict:
    cases = db.scalars(select(ChangeControlCase).where(ChangeControlCase.project_id == project_id)).all()
    approved_revenue = Decimal("0")
    approved_cost = Decimal("0")
    status_by_id = {row.change_id: row.status for row in cases}
    for case in cases:
        if case.status not in {"approved", "work_authorized", "completed"}:
            continue
        version = db.scalar(
            select(ChangeControlVersion).where(
                ChangeControlVersion.change_id_fk == case.id,
                ChangeControlVersion.version == case.current_version,
            )
        )
        if version:
            approved_revenue += Decimal(str(version.sale_net or 0))
            approved_cost += Decimal(str(version.cost_net or 0))
    unauthorized = [
        row.work_package_id for row in packages
        if row.source_module == "change-control"
        and row.status in {"in_progress", "done"}
        and status_by_id.get(row.source_object_id or "") not in {"work_authorized", "completed"}
    ]
    return {
        "approved_change_revenue_net": approved_revenue,
        "approved_change_cost_net": approved_cost,
        "unauthorized_work_packages": unauthorized,
        "cases": [{"change_id": row.change_id, "status": row.status, "version": row.current_version} for row in cases],
    }


def _add_variance(db: Session, forecast: ProjectControlForecast, *, category: str, severity: str, title: str, description: str, source_module: str, source_object_id: str, amount: Decimal = Decimal("0"), days: int = 0, percent: Decimal = Decimal("0")) -> None:
    db.add(ProjectControlVariance(
        variance_id=f"PCV-{uuid4().hex[:12].upper()}", forecast_id=forecast.forecast_id,
        category=category, severity=severity, title=title, description=description,
        amount_net=amount, impact_days=days, impact_percent=percent,
        source_module=source_module, source_object_id=source_object_id,
        recovery_required=severity in {"high", "critical"},
    ))


def create_forecast(db: Session, baseline_id: str, data: ProjectControlForecastIn, user: object) -> ProjectControlForecast:
    _role, email = _identity(user, PM_ROLES)
    baseline = _baseline(db, baseline_id)
    if baseline.status != "approved":
        raise ValueError("Forecast csak jóváhagyott baseline-ra készíthető.")
    existing = db.scalar(
        select(ProjectControlForecast).where(
            ProjectControlForecast.baseline_id == baseline_id,
            ProjectControlForecast.as_of_date == data.as_of_date,
        )
    )
    if existing:
        return existing
    plan = _finance_plan(db, baseline.project_id)
    if plan.plan_id != baseline.finance_plan_id:
        raise ValueError("A pénzügyi baseline megváltozott; új Project Control baseline szükséges.")
    packages = list(db.scalars(select(PMWorkPackage).where(PMWorkPackage.project_id == baseline.project_id)).all())
    if not packages:
        raise ValueError("A forecast forrás-munkacsomagjai hiányoznak.")
    finance = plan_summary(plan)
    changes = _change_snapshot(db, baseline.project_id, packages)
    planned = _planned_progress(baseline, data.as_of_date)
    actual = _progress(packages)
    schedule_variance = actual - planned
    deadline_variance = (data.forecast_completion_date - baseline.planned_end).days
    etc = sum((Decimal(str(row.estimate_to_complete_net or 0)) for row in plan.budget_lines), Decimal("0")) + Decimal(str(plan.contingency_net or 0))
    latest = db.scalar(select(ProjectControlForecast).where(ProjectControlForecast.baseline_id == baseline_id).order_by(desc(ProjectControlForecast.version)))
    version = (latest.version if latest else 0) + 1
    source = {
        "project_registry": baseline.project_id,
        "baseline_id": baseline.baseline_id,
        "finance_plan_id": plan.plan_id,
        "work_packages": [{"id": row.work_package_id, "status": row.status, "progress_pct": row.progress_pct, "budget": row.budget_huf, "committed": row.committed_huf, "actual": row.actual_huf, "updated_at": row.updated_at} for row in packages],
        "finance": finance,
        "change_control": changes,
        "open_site_issues": db.scalar(select(SiteIssue.id).where(SiteIssue.project_id == baseline.project_id, SiteIssue.status == "open").limit(1)) is not None,
    }
    row = ProjectControlForecast(
        forecast_id=f"PCF-{uuid4().hex[:12].upper()}", baseline_id=baseline_id, version=version,
        as_of_date=data.as_of_date, planned_progress_pct=planned, actual_progress_pct=actual,
        schedule_variance_pct=schedule_variance, forecast_completion_date=data.forecast_completion_date,
        deadline_variance_days=deadline_variance, revenue_net=finance["revenue"],
        budget_cost_net=finance["budget_cost"], committed_cost_net=finance["committed"],
        actual_cost_net=finance["actual"], estimate_to_complete_net=etc,
        eac_cost_net=finance["forecast_cost"], cost_variance_net=finance["variance_to_budget"],
        forecast_margin_net=finance["forecast_margin"], forecast_margin_percent=finance["forecast_margin_percent"],
        approved_change_revenue_net=changes["approved_change_revenue_net"],
        approved_change_cost_net=changes["approved_change_cost_net"],
        unauthorized_change_count=len(changes["unauthorized_work_packages"]),
        source_snapshot_json=_json(source), content_sha256=_sha(source), note=data.note.strip(), created_by=email,
    )
    db.add(row)
    db.flush()
    if schedule_variance <= Decimal("-5") or deadline_variance > 0:
        severity = "critical" if schedule_variance <= Decimal("-10") or deadline_variance >= 14 else "high"
        _add_variance(db, row, category="schedule", severity=severity, title="Ütemtervi eltérés", description="A tényleges készültség vagy a várható befejezés eltér a jóváhagyott baseline-tól.", source_module="operations-workspace", source_object_id=baseline.project_id, days=max(deadline_variance, 0), percent=schedule_variance)
    if row.cost_variance_net > 0:
        variance_pct = (row.cost_variance_net / row.budget_cost_net * Decimal("100")) if row.budget_cost_net else Decimal("100")
        severity = "critical" if variance_pct >= 10 else "high" if variance_pct >= 5 else "medium"
        _add_variance(db, row, category="cost", severity=severity, title="Várható költségtúllépés", description="A Finance által számított EAC meghaladja a jóváhagyott költségbaseline-t.", source_module="financial-control", source_object_id=plan.plan_id, amount=row.cost_variance_net, percent=variance_pct)
    if row.forecast_margin_percent < MINIMUM_MARGIN_PERCENT:
        _add_variance(db, row, category="margin", severity="critical", title="Projektfedezet a 35%-os vörös vonal alatt", description="A Finance kanonikus forecastja kötelező Margin Recovery Plan-t igényel.", source_module="financial-control", source_object_id=plan.plan_id, amount=max(Decimal("0"), row.revenue_net * MINIMUM_MARGIN_PERCENT / 100 - row.forecast_margin_net), percent=row.forecast_margin_percent)
    if row.unauthorized_change_count:
        _add_variance(db, row, category="change", severity="critical", title="Jóváhagyás nélkül végrehajtott változás", description="ChangeControl-engedély nélküli, elindított munkacsomag található.", source_module="change-control", source_object_id=baseline.project_id, percent=Decimal(row.unauthorized_change_count))
    blocked = sum(1 for item in packages if item.blocked and item.status != "done")
    if blocked:
        _add_variance(db, row, category="risk", severity="high", title="Blokkolt munkacsomag", description=f"{blocked} munkacsomag blokkolt a kanonikus Operations forrásban.", source_module="operations-workspace", source_object_id=baseline.project_id, percent=Decimal(blocked))
    audit(db, actor=email, action="project_control.forecast.create", entity_type="project_control_forecast", entity_id=row.forecast_id, after={"content_sha256": row.content_sha256, "source": source})
    db.commit()
    db.refresh(row)
    return row


def submit_forecast(db: Session, forecast_id: str, user: object) -> ProjectControlForecast:
    _role, email = _identity(user, PM_ROLES)
    row = _forecast(db, forecast_id, lock=True)
    if row.status != "draft" or row.created_by != email:
        raise ValueError("Csak a létrehozó PM draft forecastja küldhető pénzügyi review-ba.")
    row.status = "finance_review"
    row.submitted_by = email
    row.submitted_at = utcnow()
    audit(db, actor=email, action="project_control.forecast.submit", entity_type="project_control_forecast", entity_id=row.forecast_id, after={"status": row.status})
    db.commit()
    db.refresh(row)
    return row


def classify_variance(db: Session, variance_id: str, data: ProjectControlVarianceClassifyIn, user: object) -> ProjectControlVariance:
    _role, email = _identity(user, PM_ROLES | FINANCE_ROLES)
    row = _variance(db, variance_id, lock=True)
    if row.status in {"resolved", "accepted"}:
        raise ValueError("Lezárt eltérés nem osztályozható újra.")
    row.root_cause = data.root_cause
    row.status = "classified"
    row.classified_by = email
    row.classified_at = utcnow()
    row.resolution_note = data.note.strip()
    audit(db, actor=email, action="project_control.variance.classify", entity_type="project_control_variance", entity_id=row.variance_id, after=data.model_dump())
    db.commit()
    db.refresh(row)
    return row


def create_recovery_action(db: Session, variance_id: str, data: ProjectControlRecoveryActionIn, user: object) -> ProjectControlRecoveryAction:
    _role, email = _identity(user, PM_ROLES | FINANCE_ROLES)
    variance = _variance(db, variance_id, lock=True)
    if variance.status not in {"classified", "recovery"}:
        raise ValueError("Helyreállítási akció csak osztályozott eltéréshez készíthető.")
    if data.due_at <= utcnow():
        raise ValueError("A helyreállítási akció határideje jövőbeli legyen.")
    duplicate = db.scalar(select(ProjectControlRecoveryAction).where(ProjectControlRecoveryAction.variance_id == variance_id, ProjectControlRecoveryAction.title == data.title.strip()))
    if duplicate:
        return duplicate
    row = ProjectControlRecoveryAction(
        action_id=f"PCA-{uuid4().hex[:12].upper()}", variance_id=variance_id,
        title=data.title.strip(), owner=data.owner.strip().lower(), due_at=data.due_at,
        target_amount_net=data.target_amount_net, target_days=data.target_days, created_by=email,
    )
    db.add(row)
    variance.status = "recovery"
    audit(db, actor=email, action="project_control.recovery.create", entity_type="project_control_recovery_action", entity_id=row.action_id, after=data.model_dump(mode="json"))
    db.commit()
    db.refresh(row)
    return row


def complete_recovery_action(db: Session, action_id: str, data: ProjectControlRecoveryCompleteIn, user: object) -> ProjectControlRecoveryAction:
    _role, email = _identity(user, PM_ROLES | FINANCE_ROLES)
    row = _action(db, action_id, lock=True)
    if row.status not in {"open", "in_progress", "rejected"}:
        raise ValueError("Ez a helyreállítási akció nem teljesíthető ebben az állapotban.")
    if email not in {row.owner, row.created_by}:
        raise PermissionError("Az akciót a kijelölt owner vagy létrehozó teljesítheti.")
    row.status = "completed"
    row.completion_note = data.completion_note.strip()
    row.evidence_url = data.evidence_url.strip()
    row.completed_by = email
    row.completed_at = utcnow()
    audit(db, actor=email, action="project_control.recovery.complete", entity_type="project_control_recovery_action", entity_id=row.action_id, after=data.model_dump())
    db.commit()
    db.refresh(row)
    return row


def verify_recovery_action(db: Session, action_id: str, data: ProjectControlRecoveryVerifyIn, user: object) -> ProjectControlRecoveryAction:
    _role, email = _identity(user, FINANCE_ROLES | LEADERSHIP_ROLES)
    row = _action(db, action_id, lock=True)
    if row.status != "completed":
        raise ValueError("Csak bizonyítékkal teljesített akció verifikálható.")
    if email in {row.created_by, row.completed_by, row.owner}:
        raise ValueError("A végrehajtó nem verifikálhatja a saját helyreállítását.")
    row.status = "verified" if data.decision == "verify" else "rejected"
    row.verified_by = email
    row.verified_at = utcnow()
    row.verification_note = data.note.strip()
    variance = _variance(db, row.variance_id, lock=True)
    if data.decision == "verify":
        remaining = db.scalar(select(ProjectControlRecoveryAction.id).where(ProjectControlRecoveryAction.variance_id == variance.variance_id, ProjectControlRecoveryAction.action_id != row.action_id, ProjectControlRecoveryAction.status != "verified").limit(1))
        if remaining is None:
            variance.status = "resolved"
            variance.resolved_by = email
            variance.resolved_at = utcnow()
            variance.resolution_note = data.note.strip()
    audit(db, actor=email, action=f"project_control.recovery.{data.decision}", entity_type="project_control_recovery_action", entity_id=row.action_id, after=data.model_dump())
    db.commit()
    db.refresh(row)
    return row


def review_forecast(db: Session, forecast_id: str, data: ProjectControlFinanceReviewIn, user: object) -> ProjectControlForecast:
    _role, email = _identity(user, FINANCE_ROLES)
    row = _forecast(db, forecast_id, lock=True)
    if row.status != "finance_review":
        raise ValueError("Csak finance_review állapotú forecast bírálható.")
    if email in {row.created_by, row.submitted_by}:
        raise ValueError("A forecast készítője nem végezheti a pénzügyi review-t.")
    if data.decision == "reject":
        row.status = "rejected"
    else:
        critical = db.scalars(select(ProjectControlVariance).where(ProjectControlVariance.forecast_id == forecast_id, ProjectControlVariance.severity.in_(("high", "critical")), ProjectControlVariance.status != "resolved")).all()
        for variance in critical:
            if not variance.root_cause:
                raise ValueError("Minden jelentős eltéréshez kötelező gyökérok-besorolás.")
            if variance.recovery_required and not db.scalar(select(ProjectControlRecoveryAction.id).where(ProjectControlRecoveryAction.variance_id == variance.variance_id)):
                raise ValueError("Minden jelentős eltéréshez kötelező helyreállítási akció.")
        row.finance_approved_by = email
        row.finance_note = data.note.strip()
        row.finance_approved_at = utcnow()
        row.status = "leadership_review" if any(v.severity == "critical" for v in critical) else "approved"
    audit(db, actor=email, action=f"project_control.forecast.finance_{data.decision}", entity_type="project_control_forecast", entity_id=row.forecast_id, after=data.model_dump())
    if row.status == "approved":
        _finalize_forecast(db, row, email)
    else:
        db.commit()
    db.refresh(row)
    return row


def _finalize_forecast(db: Session, row: ProjectControlForecast, actor: str) -> None:
    previous = db.scalars(select(ProjectControlForecast).where(ProjectControlForecast.baseline_id == row.baseline_id, ProjectControlForecast.status == "approved", ProjectControlForecast.forecast_id != row.forecast_id)).all()
    for old in previous:
        old.status = "superseded"
    baseline = _baseline(db, row.baseline_id)
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == baseline.project_id))
    critical = db.scalar(select(ProjectControlVariance.id).where(ProjectControlVariance.forecast_id == row.forecast_id, ProjectControlVariance.severity == "critical", ProjectControlVariance.status != "resolved").limit(1)) is not None
    if project:
        project.risk_level = "red" if critical else "amber" if row.cost_variance_net > 0 or row.deadline_variance_days > 0 else "green"
        project.blocked = bool(row.unauthorized_change_count) or row.forecast_margin_percent < MINIMUM_MARGIN_PERCENT
        project.financial_impact_huf = max(Decimal("0"), row.cost_variance_net)
        project.deadline_impact_days = max(0, row.deadline_variance_days)
        project.next_action = "Margin/ütem helyreállítási terv végrehajtása." if critical else "Heti Project Control visszamérés."
    _emit(db, baseline.project_id, "PROJECT_FORECAST_APPROVED", row.forecast_id, row.status, actor, "A heti Project Control forecast és EAC jóváhagyva.", executive=critical)


def decide_forecast(db: Session, forecast_id: str, data: ProjectControlLeadershipDecisionIn, user: object) -> ProjectControlForecast:
    _role, email = _identity(user, LEADERSHIP_ROLES)
    row = _forecast(db, forecast_id, lock=True)
    if row.status != "leadership_review" or not row.finance_approved_by:
        raise ValueError("Vezetői döntéshez jóváhagyott pénzügyi review szükséges.")
    if email in {row.created_by, row.submitted_by, row.finance_approved_by}:
        raise ValueError("A vezetői jóváhagyónak el kell különülnie a forecast készítőitől.")
    if data.decision == "reject":
        row.status = "rejected"
    else:
        row.status = "approved"
        row.leadership_approved_by = email
        row.leadership_note = data.note.strip()
        row.leadership_approved_at = utcnow()
        _finalize_forecast(db, row, email)
    audit(db, actor=email, action=f"project_control.forecast.leadership_{data.decision}", entity_type="project_control_forecast", entity_id=row.forecast_id, after=data.model_dump())
    db.commit()
    db.refresh(row)
    return row


def generate_weekly_report(db: Session, project_id: str, data: ProjectControlWeeklyReportIn, user: object) -> ProjectControlWeeklyReport:
    _role, email = _identity(user, PM_ROLES)
    existing = db.scalar(select(ProjectControlWeeklyReport).where(ProjectControlWeeklyReport.project_id == project_id, ProjectControlWeeklyReport.week_ending == data.week_ending))
    if existing:
        return existing
    baseline = db.scalar(select(ProjectControlBaseline).where(ProjectControlBaseline.project_id == project_id, ProjectControlBaseline.status == "approved"))
    if not baseline:
        raise ValueError("Jóváhagyott Project Control baseline nélkül nincs heti riport.")
    forecast = db.scalar(select(ProjectControlForecast).where(ProjectControlForecast.baseline_id == baseline.baseline_id, ProjectControlForecast.status == "approved").order_by(desc(ProjectControlForecast.version)))
    if not forecast:
        raise ValueError("Jóváhagyott forecast nélkül nincs heti riport.")
    variances = db.scalars(select(ProjectControlVariance).where(ProjectControlVariance.forecast_id == forecast.forecast_id)).all()
    actions = db.scalars(select(ProjectControlRecoveryAction).where(ProjectControlRecoveryAction.variance_id.in_([v.variance_id for v in variances] or ["-"]))).all()
    payload = {
        "template_id": "TPL-OPS-012",
        "project_id": project_id,
        "week_ending": data.week_ending,
        "baseline_id": baseline.baseline_id,
        "forecast_id": forecast.forecast_id,
        "planned_progress_pct": forecast.planned_progress_pct,
        "actual_progress_pct": forecast.actual_progress_pct,
        "schedule_variance_pct": forecast.schedule_variance_pct,
        "forecast_completion_date": forecast.forecast_completion_date,
        "deadline_variance_days": forecast.deadline_variance_days,
        "budget_cost_net": forecast.budget_cost_net,
        "eac_cost_net": forecast.eac_cost_net,
        "cost_variance_net": forecast.cost_variance_net,
        "forecast_margin_percent": forecast.forecast_margin_percent,
        "approved_change_revenue_net": forecast.approved_change_revenue_net,
        "unauthorized_change_count": forecast.unauthorized_change_count,
        "variances": [{"id": v.variance_id, "category": v.category, "severity": v.severity, "status": v.status, "root_cause": v.root_cause} for v in variances],
        "recovery_actions": [{"id": a.action_id, "title": a.title, "owner": a.owner, "due_at": a.due_at, "status": a.status} for a in actions],
    }
    row = ProjectControlWeeklyReport(
        report_id=f"PCR-{uuid4().hex[:12].upper()}", project_id=project_id,
        forecast_id=forecast.forecast_id, week_ending=data.week_ending,
        report_json=_json(payload), content_sha256=_sha(payload),
        management_summary=data.management_summary.strip(), created_by=email,
    )
    db.add(row)
    audit(db, actor=email, action="project_control.report.generate", entity_type="project_control_weekly_report", entity_id=row.report_id, after=payload)
    db.commit()
    db.refresh(row)
    return row


def submit_weekly_report(db: Session, report_id: str, user: object) -> ProjectControlWeeklyReport:
    _role, email = _identity(user, PM_ROLES)
    row = _report(db, report_id, lock=True)
    if row.status != "draft" or row.created_by != email:
        raise ValueError("Csak a létrehozó PM draft riportja küldhető jóváhagyásra.")
    row.status = "submitted"
    row.submitted_by = email
    row.submitted_at = utcnow()
    db.commit()
    db.refresh(row)
    return row


def decide_weekly_report(db: Session, report_id: str, data: ProjectControlWeeklyReportDecisionIn, user: object) -> ProjectControlWeeklyReport:
    _role, email = _identity(user, LEADERSHIP_ROLES)
    row = _report(db, report_id, lock=True)
    if row.status != "submitted":
        raise ValueError("Csak benyújtott heti riport bírálható.")
    if email in {row.created_by, row.submitted_by}:
        raise ValueError("A heti riport készítője nem hagyhatja jóvá saját riportját.")
    row.status = "approved" if data.decision == "approve" else "rejected"
    row.approved_by = email
    row.approval_note = data.note.strip()
    row.approved_at = utcnow()
    audit(db, actor=email, action=f"project_control.report.{data.decision}", entity_type="project_control_weekly_report", entity_id=row.report_id, after=data.model_dump())
    if row.status == "approved":
        _emit(db, row.project_id, "PROJECT_WEEKLY_REPORT_APPROVED", row.report_id, row.status, email, "A TPL-OPS-012 heti projektkontroll riport jóváhagyva.", executive=True)
    else:
        db.commit()
    db.refresh(row)
    return row


def project_control_workspace(db: Session, user: object, project_id: str | None = None) -> dict:
    _identity(user, VIEW_ROLES)
    projects_stmt = select(ProjectRegistry).order_by(ProjectRegistry.name)
    projects = db.scalars(projects_stmt).all()
    baseline_stmt = select(ProjectControlBaseline).order_by(desc(ProjectControlBaseline.created_at))
    if project_id:
        baseline_stmt = baseline_stmt.where(ProjectControlBaseline.project_id == project_id)
    baselines = db.scalars(baseline_stmt).all()
    baseline_ids = [row.baseline_id for row in baselines]
    forecasts = db.scalars(select(ProjectControlForecast).where(ProjectControlForecast.baseline_id.in_(baseline_ids or ["-"])).order_by(desc(ProjectControlForecast.created_at))).all()
    forecast_ids = [row.forecast_id for row in forecasts]
    variances = db.scalars(select(ProjectControlVariance).where(ProjectControlVariance.forecast_id.in_(forecast_ids or ["-"])).order_by(desc(ProjectControlVariance.created_at))).all()
    variance_ids = [row.variance_id for row in variances]
    actions = db.scalars(select(ProjectControlRecoveryAction).where(ProjectControlRecoveryAction.variance_id.in_(variance_ids or ["-"])).order_by(ProjectControlRecoveryAction.due_at)).all()
    reports_stmt = select(ProjectControlWeeklyReport).order_by(desc(ProjectControlWeeklyReport.week_ending))
    if project_id:
        reports_stmt = reports_stmt.where(ProjectControlWeeklyReport.project_id == project_id)
    reports = db.scalars(reports_stmt).all()
    return {
        "projects": projects,
        "project_id": project_id,
        "baselines": baselines,
        "forecasts": forecasts,
        "variances": variances,
        "actions": actions,
        "reports": reports,
        "forecasts_by_baseline": {bid: [row for row in forecasts if row.baseline_id == bid] for bid in baseline_ids},
        "variances_by_forecast": {fid: [row for row in variances if row.forecast_id == fid] for fid in forecast_ids},
        "actions_by_variance": {vid: [row for row in actions if row.variance_id == vid] for vid in variance_ids},
        "metrics": {
            "approved_baselines": sum(1 for row in baselines if row.status == "approved"),
            "approved_forecasts": sum(1 for row in forecasts if row.status == "approved"),
            "open_variances": sum(1 for row in variances if row.status not in {"resolved", "accepted"}),
            "critical_variances": sum(1 for row in variances if row.severity == "critical" and row.status not in {"resolved", "accepted"}),
            "overdue_actions": sum(1 for row in actions if row.status != "verified" and row.due_at < utcnow()),
            "approved_reports": sum(1 for row in reports if row.status == "approved"),
        },
    }


def serialize(row: object) -> dict:
    table = getattr(row, "__table__", None)
    if table is None:
        raise TypeError("A rekord nem SQLAlchemy modell.")
    return {
        column.name: getattr(row, column.name)
        for column in table.columns
        if column.name != "id"
    }
