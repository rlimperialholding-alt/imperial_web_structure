from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    PMGateCheck,
    PMPhase,
    PMWorkPackage,
    ProjectControlBaseline,
    ProjectControlForecast,
    ProjectControlRecoveryAction,
    ProjectControlVariance,
    ProjectControlWeeklyReport,
    ProjectFinanceBudgetLine,
    ProjectFinancePlan,
    ProjectRegistry,
)
from app.schemas import (
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
from app.services.project_control import (
    classify_variance,
    complete_recovery_action,
    create_baseline,
    create_forecast,
    create_recovery_action,
    decide_baseline,
    decide_forecast,
    decide_weekly_report,
    generate_weekly_report,
    review_baseline,
    review_forecast,
    submit_baseline,
    submit_forecast,
    submit_weekly_report,
    verify_recovery_action,
)

PROJECT_ID = "PROJECT-CONTROL-SERVER-UAT"
WEEK_ENDING = date(2026, 9, 4)


def _actor(role: str):
    return SimpleNamespace(role=role, email=f"{role}@imperial.local")


def _seed_sources(db) -> None:
    if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == PROJECT_ID)):
        db.add(ProjectRegistry(project_id=PROJECT_ID, name="Project Control szerver-UAT", status="active", responsible="project-manager@imperial.local"))
    if not db.scalar(select(PMPhase).where(PMPhase.phase_id == "PH-PC-SERVER-UAT")):
        db.add(PMPhase(phase_id="PH-PC-SERVER-UAT", project_id=PROJECT_ID, phase_key="construction", name="Kivitelezés", sequence=1, status="in_progress", planned_start=datetime(2026, 8, 1, tzinfo=UTC), planned_end=datetime(2026, 9, 30, tzinfo=UTC), progress_pct=20, owner="project-manager@imperial.local"))
    if not db.scalar(select(PMWorkPackage).where(PMWorkPackage.work_package_id == "WP-PC-SERVER-UAT")):
        db.add(PMWorkPackage(work_package_id="WP-PC-SERVER-UAT", project_id=PROJECT_ID, phase_id="PH-PC-SERVER-UAT", name="Szerkezetépítés", status="in_progress", progress_pct=20, planned_start=datetime(2026, 8, 1, tzinfo=UTC), planned_end=datetime(2026, 9, 30, tzinfo=UTC), budget_huf=Decimal("80000000"), committed_huf=Decimal("60000000"), actual_huf=Decimal("20000000"), source_module="operations-workspace", source_version="B01"))
    if not db.scalar(select(PMGateCheck).where(PMGateCheck.gate_id == "GATE-PC-SERVER-UAT")):
        db.add(PMGateCheck(gate_id="GATE-PC-SERVER-UAT", project_id=PROJECT_ID, gate_code="design_freeze", label="Design Freeze", required=True, status="passed", checked_by="technical-prep@imperial.local", evidence_url="https://drive.example/project-control/design-freeze", checked_at=datetime.now(UTC)))
    plan = db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == "FIN-PC-SERVER-UAT"))
    if not plan:
        plan = ProjectFinancePlan(plan_id="FIN-PC-SERVER-UAT", project_id=PROJECT_ID, version=1, status="approved", currency="HUF", contract_revenue_net=Decimal("100000000"), target_margin_percent=Decimal("35"), created_by="finance@imperial.local")
        db.add(plan)
        db.flush()
    if not db.scalar(select(ProjectFinanceBudgetLine).where(ProjectFinanceBudgetLine.line_id == "LINE-PC-SERVER-UAT")):
        db.add(ProjectFinanceBudgetLine(line_id="LINE-PC-SERVER-UAT", plan_id_fk=plan.id, cost_code="STR-001", category="Szerkezet", description="Szerkezetépítés", budget_net=Decimal("80000000"), committed_net=Decimal("60000000"), actual_net=Decimal("20000000"), estimate_to_complete_net=Decimal("60000000"), source_type="operations-workspace", source_id="WP-PC-SERVER-UAT"))
    db.commit()


def _print_result(db) -> None:
    baseline = db.scalar(select(ProjectControlBaseline).where(ProjectControlBaseline.project_id == PROJECT_ID).order_by(ProjectControlBaseline.version.desc()))
    forecast = db.scalar(select(ProjectControlForecast).where(ProjectControlForecast.baseline_id == baseline.baseline_id).order_by(ProjectControlForecast.version.desc())) if baseline else None
    variances = db.scalars(select(ProjectControlVariance).where(ProjectControlVariance.forecast_id == forecast.forecast_id)).all() if forecast else []
    variance_ids = [row.variance_id for row in variances]
    actions = db.scalars(select(ProjectControlRecoveryAction).where(ProjectControlRecoveryAction.variance_id.in_(variance_ids or ["-"]))).all()
    report = db.scalar(select(ProjectControlWeeklyReport).where(ProjectControlWeeklyReport.project_id == PROJECT_ID, ProjectControlWeeklyReport.week_ending == WEEK_ENDING))
    print({
        "project_id": PROJECT_ID,
        "baseline_version": baseline.version if baseline else None,
        "baseline_status": baseline.status if baseline else None,
        "baseline_sha256": baseline.content_sha256 if baseline else None,
        "forecast_version": forecast.version if forecast else None,
        "forecast_status": forecast.status if forecast else None,
        "forecast_sha256": forecast.content_sha256 if forecast else None,
        "eac_cost_net": str(forecast.eac_cost_net) if forecast else None,
        "forecast_margin_percent": str(forecast.forecast_margin_percent) if forecast else None,
        "variances": len(variances),
        "resolved_variances": sum(row.status == "resolved" for row in variances),
        "verified_actions": sum(row.status == "verified" for row in actions),
        "report_status": report.status if report else None,
        "report_sha256": report.content_sha256 if report else None,
    })


def main() -> None:
    with SessionLocal() as db:
        _seed_sources(db)
        approved_report = db.scalar(select(ProjectControlWeeklyReport).where(ProjectControlWeeklyReport.project_id == PROJECT_ID, ProjectControlWeeklyReport.week_ending == WEEK_ENDING, ProjectControlWeeklyReport.status == "approved"))
        if approved_report:
            _print_result(db)
            return

        baseline = create_baseline(db, ProjectControlBaselineIn(project_id=PROJECT_ID, scope_document_id="DOC-PC-SERVER-UAT-SCOPE", scope_version="V01", scope_sha256="a" * 64, planned_start=date(2026, 8, 1), planned_end=date(2026, 9, 30), note="Kontrollált szerver-UAT projektbaseline kanonikus forrásokból."), _actor("project-manager"))
        if baseline.status == "draft":
            baseline = submit_baseline(db, baseline.baseline_id, _actor("project-manager"))
        if baseline.status == "review" and not baseline.technical_approved_by:
            baseline = review_baseline(db, baseline.baseline_id, ProjectControlBaselineReviewIn(gate="technical", decision="approve", note="A scope és az Operations ütem műszakilag ellenőrzött."), _actor("technical-prep"))
        if baseline.status == "review" and not baseline.finance_approved_by:
            baseline = review_baseline(db, baseline.baseline_id, ProjectControlBaselineReviewIn(gate="finance", decision="approve", note="A Finance baseline és cashflow-forrás ellenőrzött."), _actor("finance"))
        if baseline.status == "review":
            baseline = decide_baseline(db, baseline.baseline_id, ProjectControlLeadershipDecisionIn(decision="approve", note="A kontrollbaseline vezetőileg jóváhagyva."), _actor("owner"))

        forecast = create_forecast(db, baseline.baseline_id, ProjectControlForecastIn(as_of_date=date(2026, 8, 31), forecast_completion_date=date(2026, 10, 14), note="Heti terv–tény–EAC forecast a kanonikus forrásokból."), _actor("project-manager"))
        if forecast.status == "draft":
            forecast = submit_forecast(db, forecast.forecast_id, _actor("project-manager"))
        variances = db.scalars(select(ProjectControlVariance).where(ProjectControlVariance.forecast_id == forecast.forecast_id, ProjectControlVariance.severity.in_(("high", "critical")))).all()
        for variance in variances:
            if not variance.root_cause:
                variance = classify_variance(db, variance.variance_id, ProjectControlVarianceClassifyIn(root_cause="delay" if variance.category == "schedule" else "price", note="A szerver-UAT eltérés gyökéroka a kanonikus forrásokból igazolt."), _actor("project-manager"))
            title = f"Helyreállítás: {variance.category}"
            action = db.scalar(select(ProjectControlRecoveryAction).where(ProjectControlRecoveryAction.variance_id == variance.variance_id, ProjectControlRecoveryAction.title == title))
            if not action:
                create_recovery_action(db, variance.variance_id, ProjectControlRecoveryActionIn(title=title, owner="project-manager@imperial.local", due_at=datetime.now(UTC) + timedelta(days=7), target_amount_net=variance.amount_net, target_days=max(variance.impact_days, 0)), _actor("finance"))
        if forecast.status == "finance_review":
            forecast = review_forecast(db, forecast.forecast_id, ProjectControlFinanceReviewIn(decision="approve", note="Az EAC és minden kötelező recovery-akció ellenőrzött."), _actor("finance"))
        if forecast.status == "leadership_review":
            forecast = decide_forecast(db, forecast.forecast_id, ProjectControlLeadershipDecisionIn(decision="approve", note="A vörös forecast vezetőileg elfogadva kötelező recovery-kontrollal."), _actor("managing-director"))

        variances = db.scalars(select(ProjectControlVariance).where(ProjectControlVariance.forecast_id == forecast.forecast_id)).all()
        actions = db.scalars(select(ProjectControlRecoveryAction).where(ProjectControlRecoveryAction.variance_id.in_([row.variance_id for row in variances] or ["-"]))).all()
        for action in actions:
            if action.status in {"open", "in_progress", "rejected"}:
                action = complete_recovery_action(db, action.action_id, ProjectControlRecoveryCompleteIn(completion_note="A recovery-akció végrehajtása és hatása a szerver-UAT során visszamért.", evidence_url=f"https://drive.example/project-control/recovery/{action.action_id}"), _actor("project-manager"))
            if action.status == "completed":
                verify_recovery_action(db, action.action_id, ProjectControlRecoveryVerifyIn(decision="verify", note="A recovery bizonyítéka és hatása függetlenül ellenőrzött."), _actor("owner"))

        report = generate_weekly_report(db, PROJECT_ID, ProjectControlWeeklyReportIn(week_ending=WEEK_ENDING, management_summary="A szerver-UAT projekt jóváhagyott forecast és verifikált recovery-kontroll mellett halad."), _actor("project-manager"))
        if report.status == "draft":
            report = submit_weekly_report(db, report.report_id, _actor("project-manager"))
        if report.status == "submitted":
            decide_weekly_report(db, report.report_id, ProjectControlWeeklyReportDecisionIn(decision="approve", note="A TPL-OPS-012 heti szerver-UAT riport vezetőileg jóváhagyva."), _actor("owner"))
        _print_result(db)


if __name__ == "__main__":
    main()
