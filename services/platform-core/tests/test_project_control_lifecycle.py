from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from app.models import (
    PMGateCheck,
    PMPhase,
    PMWorkPackage,
    ProjectControlVariance,
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
from app.seed import DEMO_PASSWORD


def _user(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _seed_sources(db):
    project_id = "PC-UAT-001"
    db.add(ProjectRegistry(project_id=project_id, name="Project Control UAT", status="active", responsible="project-manager@imperial.local"))
    db.add(PMPhase(phase_id="PH-PC-UAT", project_id=project_id, phase_key="construction", name="Kivitelezés", sequence=1, status="in_progress", planned_start=datetime(2026, 8, 1, tzinfo=UTC), planned_end=datetime(2026, 9, 30, tzinfo=UTC), progress_pct=20, owner="project-manager@imperial.local"))
    db.add(PMWorkPackage(work_package_id="WP-PC-UAT", project_id=project_id, phase_id="PH-PC-UAT", name="Szerkezetépítés", status="in_progress", progress_pct=20, planned_start=datetime(2026, 8, 1, tzinfo=UTC), planned_end=datetime(2026, 9, 30, tzinfo=UTC), budget_huf=Decimal("80000000"), committed_huf=Decimal("60000000"), actual_huf=Decimal("20000000"), source_module="project-control", source_version="B01"))
    db.add(PMGateCheck(gate_id="GATE-PC-UAT", project_id=project_id, gate_code="design_freeze", label="Design Freeze", required=True, status="passed", checked_by="technical-prep@imperial.local", evidence_url="https://drive.example/design-freeze", checked_at=datetime.now(UTC)))
    plan = ProjectFinancePlan(plan_id="FIN-PC-UAT", project_id=project_id, version=1, status="approved", currency="HUF", contract_revenue_net=Decimal("100000000"), target_margin_percent=Decimal("35"), created_by="finance@imperial.local")
    db.add(plan)
    db.flush()
    db.add(ProjectFinanceBudgetLine(line_id="LINE-PC-UAT", plan_id_fk=plan.id, cost_code="STR-001", category="Szerkezet", description="Szerkezetépítés", budget_net=Decimal("80000000"), committed_net=Decimal("60000000"), actual_net=Decimal("20000000"), estimate_to_complete_net=Decimal("60000000"), source_type="project-control", source_id="WP-PC-UAT"))
    db.commit()
    return project_id


def test_project_control_baseline_forecast_recovery_and_weekly_report(db):
    project_id = _seed_sources(db)
    baseline_data = ProjectControlBaselineIn(project_id=project_id, scope_document_id="DOC-PC-SCOPE", scope_version="V01", scope_sha256="a" * 64, planned_start=date(2026, 8, 1), planned_end=date(2026, 9, 30), note="Kontrollált, jóváhagyásra előkészített projektbaseline.")
    baseline = create_baseline(db, baseline_data, _user("project-manager"))
    assert create_baseline(db, baseline_data, _user("project-manager")).baseline_id == baseline.baseline_id
    submit_baseline(db, baseline.baseline_id, _user("project-manager"))
    review_baseline(db, baseline.baseline_id, ProjectControlBaselineReviewIn(gate="technical", decision="approve", note="A scope és az ütem műszakilag egyezik."), _user("technical-prep"))
    review_baseline(db, baseline.baseline_id, ProjectControlBaselineReviewIn(gate="finance", decision="approve", note="A költség- és cashflow-baseline egyezik."), _user("finance"))
    baseline = decide_baseline(db, baseline.baseline_id, ProjectControlLeadershipDecisionIn(decision="approve", note="A projektbaseline vezetőileg jóváhagyva."), _user("owner"))
    assert baseline.status == "approved"

    forecast = create_forecast(db, baseline.baseline_id, ProjectControlForecastIn(as_of_date=date(2026, 8, 31), forecast_completion_date=date(2026, 10, 14), note="Heti kontrollált forecast a kanonikus tényadatokból."), _user("project-manager"))
    assert create_forecast(db, baseline.baseline_id, ProjectControlForecastIn(as_of_date=date(2026, 8, 31), forecast_completion_date=date(2026, 10, 14), note="Heti kontrollált forecast a kanonikus tényadatokból."), _user("project-manager")).forecast_id == forecast.forecast_id
    assert forecast.eac_cost_net == Decimal("80000000.00")
    assert forecast.forecast_margin_percent == Decimal("20.00")
    submit_forecast(db, forecast.forecast_id, _user("project-manager"))

    variances = db.scalars(select(ProjectControlVariance).where(ProjectControlVariance.forecast_id == forecast.forecast_id, ProjectControlVariance.severity.in_(("high", "critical")))).all()
    assert {row.category for row in variances} >= {"schedule", "margin"}
    actions = []
    for variance in variances:
        classify_variance(db, variance.variance_id, ProjectControlVarianceClassifyIn(root_cause="delay" if variance.category == "schedule" else "price", note="A gyökérok forrásadatokkal igazolt."), _user("project-manager"))
        actions.append(create_recovery_action(db, variance.variance_id, ProjectControlRecoveryActionIn(title=f"Helyreállítás: {variance.category}", owner="project-manager@imperial.local", due_at=datetime.now(UTC) + timedelta(days=7), target_amount_net=variance.amount_net, target_days=max(variance.impact_days, 0)), _user("finance")))

    forecast = review_forecast(db, forecast.forecast_id, ProjectControlFinanceReviewIn(decision="approve", note="Az EAC számítása és a helyreállítási tervek ellenőrzöttek."), _user("finance"))
    assert forecast.status == "leadership_review"
    forecast = decide_forecast(db, forecast.forecast_id, ProjectControlLeadershipDecisionIn(decision="approve", note="A vörös forecast a kötelező recovery kontrollal elfogadva."), _user("managing-director"))
    assert forecast.status == "approved"

    for action in actions:
        complete_recovery_action(db, action.action_id, ProjectControlRecoveryCompleteIn(completion_note="A helyreállítási intézkedést végrehajtottuk és visszamértük.", evidence_url=f"https://drive.example/recovery/{action.action_id}"), _user("project-manager"))
        verify_recovery_action(db, action.action_id, ProjectControlRecoveryVerifyIn(decision="verify", note="A végrehajtás bizonyítéka és hatása függetlenül ellenőrzött."), _user("owner"))

    report = generate_weekly_report(db, project_id, ProjectControlWeeklyReportIn(week_ending=date(2026, 9, 4), management_summary="A projekt a jóváhagyott vörös forecast mellett aktív helyreállítási kontroll alatt áll."), _user("project-manager"))
    assert generate_weekly_report(db, project_id, ProjectControlWeeklyReportIn(week_ending=date(2026, 9, 4), management_summary="A projekt a jóváhagyott vörös forecast mellett aktív helyreállítási kontroll alatt áll."), _user("project-manager")).report_id == report.report_id
    submit_weekly_report(db, report.report_id, _user("project-manager"))
    report = decide_weekly_report(db, report.report_id, ProjectControlWeeklyReportDecisionIn(decision="approve", note="A heti vezetői projektkontroll riport elfogadva."), _user("owner"))
    assert report.status == "approved"
    assert len(report.content_sha256) == 64


def test_project_control_http_role_scope(client):
    for role in (
        "owner",
        "managing-director",
        "project-manager",
        "finance",
        "technical-prep",
        "designer",
        "platform-admin",
    ):
        client.post("/logout")
        response = client.post(
            "/login",
            data={"email": f"{role}@imperial.local", "password": DEMO_PASSWORD},
            follow_redirects=False,
        )
        assert response.status_code == 303
        page = client.get("/project-control")
        assert page.status_code == 200
        assert "Project Control" in page.text
        assert client.get("/api/project-control/summary").status_code == 200

    client.post("/logout")
    client.post(
        "/login",
        data={"email": "customer@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert client.get("/project-control").status_code == 403
    assert client.get("/api/project-control/summary").status_code == 403
