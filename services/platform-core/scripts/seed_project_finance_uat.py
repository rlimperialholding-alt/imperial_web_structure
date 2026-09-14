from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import ProjectFinancePlan, ProjectRegistry
from app.services.project_finance import (
    add_budget_line,
    add_cashflow_line,
    create_finance_plan,
    finance_approve_plan,
    leadership_approve_plan,
    plan_summary,
    submit_finance_plan,
)

PROJECT_ID = "FIN-UAT-SERVER-001"


def _actor(role: str):
    return SimpleNamespace(role=role, email=f"{role}@imperial.local")


def _load_plan(db) -> ProjectFinancePlan | None:
    return db.scalar(
        select(ProjectFinancePlan)
        .options(
            selectinload(ProjectFinancePlan.budget_lines),
            selectinload(ProjectFinancePlan.cashflow_lines),
        )
        .execution_options(populate_existing=True)
        .where(ProjectFinancePlan.project_id == PROJECT_ID)
        .order_by(ProjectFinancePlan.version.desc())
    )


def main() -> None:
    with SessionLocal() as db:
        if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == PROJECT_ID)):
            db.add(
                ProjectRegistry(
                    project_id=PROJECT_ID,
                    name="Projektpénzügyi szerver UAT",
                    customer_name="Kontrollált pénzügyi UAT ügyfél",
                    project_type="uat_new_build",
                    status="active",
                    responsible="project-manager@imperial.local",
                    next_action="Jóváhagyott pénzügyi baseline UAT ellenőrzése",
                )
            )
            db.commit()
        plan = _load_plan(db)
        if not plan:
            plan = create_finance_plan(
                db,
                _actor("project-manager"),
                project_id=PROJECT_ID,
                currency="HUF",
                contract_revenue_net="125000000",
                approved_change_revenue_net="5000000",
                contingency_net="4000000",
                target_margin_percent="20",
                forecast_note="Kontrollált, szintetikus szerver-UAT pénzügyi baseline.",
            )
        if plan.status == "draft" and not plan.budget_lines:
            add_budget_line(
                db,
                plan.plan_id,
                _actor("project-manager"),
                cost_code="UAT-GEN-001",
                category="Generálkivitelezés",
                description="Kontrollált kivitelezési munkacsomag",
                budget_net="88000000",
                committed_net="50000000",
                actual_net="20000000",
                estimate_to_complete_net="68000000",
                source_type="uat_contract",
                source_id="FIN-UAT-CON-001",
            )
        plan = _load_plan(db)
        if plan and plan.status == "draft" and not plan.cashflow_lines:
            add_cashflow_line(
                db,
                plan.plan_id,
                _actor("project-manager"),
                period_date=date(2026, 9, 1),
                direction="inflow",
                category="Megrendelői mérföldkő",
                description="Kontrollált UAT bevétel",
                amount_net="100000000",
                status="committed",
                source_type="uat_contract",
                source_id="FIN-UAT-CON-001",
            )
            add_cashflow_line(
                db,
                plan.plan_id,
                _actor("project-manager"),
                period_date=date(2026, 9, 15),
                direction="outflow",
                category="Kivitelezés",
                description="Kontrollált UAT kiadás",
                amount_net="65000000",
                status="forecast",
                source_type="uat_purchase_order",
                source_id="FIN-UAT-PO-001",
            )
        plan = _load_plan(db)
        if plan and plan.status == "draft":
            submit_finance_plan(db, plan.plan_id, _actor("project-manager"))
        plan = _load_plan(db)
        if plan and plan.status == "review":
            finance_approve_plan(
                db,
                plan.plan_id,
                _actor("finance"),
                note="Kontrollált UAT: a pénzügyi források és számítások ellenőrizve.",
            )
        plan = _load_plan(db)
        if plan and plan.status == "finance_approved":
            leadership_approve_plan(
                db,
                plan.plan_id,
                _actor("managing-director"),
                note="Kontrollált UAT: a projektbaseline vezetőileg jóváhagyva.",
                margin_exception_reason="",
            )
        plan = _load_plan(db)
        if not plan:
            raise RuntimeError("A pénzügyi UAT terv nem jött létre.")
        print(
            {
                "project_id": PROJECT_ID,
                "plan_id": plan.plan_id,
                "version": plan.version,
                "status": plan.status,
                "budget_lines": len(plan.budget_lines),
                "cashflow_lines": len(plan.cashflow_lines),
                "summary": plan_summary(plan),
            }
        )


if __name__ == "__main__":
    main()
