"""Közös szintetikus fixture-ek a TENDER-kapu tesztekhez (Task75).

Kizárólag szintetikus adat; a tartalomlenyomat a kanonikus
plan_content_sha256 függvénnyel keletkezik, így a kapu
provenance-ellenőrzése a fixture-ön is éles.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProjectFinanceBudgetLine, ProjectFinancePlan
from app.services.tender_margin_gate import plan_content_sha256


def _line_id() -> str:
    return f"FIN-LINE-{uuid4().hex[:12].upper()}"


def _line(db: Session, plan: ProjectFinancePlan, **fields) -> ProjectFinanceBudgetLine:
    line = ProjectFinanceBudgetLine(line_id=_line_id(), plan_id_fk=plan.id, **fields)
    db.add(line)
    return line


def seed_gate_plan(
    db: Session,
    *,
    project_id: str,
    revenue: str,
    direct_lines: Iterable[tuple[str, str, str]] = (),
    indirect_lines: Iterable[tuple[str, str]] = (),
    contingency: str = "0",
    plan_id: str | None = None,
    version: int = 1,
    summary_lines: Iterable[dict] = (),
) -> ProjectFinancePlan:
    """Jóváhagyott, hash-elt terv; direct_lines: (kód, HUF, költségnem)
    hármasok, summary_lines: {cost_code, amount, amount_basis, component}."""
    plan = ProjectFinancePlan(
        plan_id=plan_id or f"FIN-PLAN-GATE-{project_id}-{version:02d}",
        project_id=project_id,
        version=version,
        status="approved",
        currency="HUF",
        contract_revenue_net=Decimal(revenue),
        approved_change_revenue_net=Decimal("0"),
        contingency_net=Decimal(contingency),
        target_margin_percent=Decimal("35"),
        submitted_by="fixture-submitter@imperial.local",
        finance_approved_by="fixture-finance@imperial.local",
        leadership_approved_by="fixture-leadership@imperial.local",
        created_by="fixture@imperial.local",
    )
    db.add(plan)
    db.flush()
    for code, amount, component in direct_lines:
        _line(db, plan, cost_code=code, category="direct",
              description=f"{code} szintetikus direct teszt-sor", budget_net=Decimal(amount),
              cost_class="direct", direct_cost_component=component, currency="HUF")
    for entry in summary_lines:
        _line(db, plan, cost_code=entry["cost_code"],
              category=entry.get("category", entry["cost_code"]),
              description=f"{entry['cost_code']} szintetikus összegző csomagsor",
              budget_net=Decimal(entry["amount"]), cost_class="direct",
              direct_cost_component=entry.get("component", "other"),
              amount_basis=entry["amount_basis"], is_summary_package=True, currency="HUF")
    for code, amount in indirect_lines:
        _line(db, plan, cost_code=code, category="indirect",
              description=f"{code} szintetikus indirect teszt-sor", budget_net=Decimal(amount),
              cost_class="indirect", currency="HUF")
    plan.content_sha256 = plan_content_sha256(plan)
    db.commit()
    db.refresh(plan)
    return plan


def ensure_gate_plan(
    db: Session,
    *,
    project_id: str,
    revenue: str,
    direct_lines: Iterable[tuple[str, str, str]],
    plan_id: str | None = None,
) -> ProjectFinancePlan:
    """Jóváhagyott, hash-elt kapu-terv, ha még nincs ilyen."""
    from app.models import ProjectFinancePlan
    existing = db.scalar(select(ProjectFinancePlan).where( ProjectFinancePlan.project_id == project_id, ProjectFinancePlan.status == "approved",)
    )
    if existing is not None:
        return existing
    return seed_gate_plan(db, project_id=project_id, revenue=revenue, direct_lines=direct_lines, plan_id=plan_id,)


def get_line(db: Session, plan: ProjectFinancePlan, cost_code: str) -> ProjectFinanceBudgetLine:
    """A terv sorának keresése költségkód alapján (friss lekérdezés)."""
    line = db.scalar(select(ProjectFinanceBudgetLine).where( ProjectFinanceBudgetLine.plan_id_fk == plan.id, ProjectFinanceBudgetLine.cost_code == cost_code,)
    )
    if line is None:
        raise AssertionError(f"Nincs {cost_code} költségkódú sor a {plan.plan_id} terven.")
    return line


def add_child_line(
    db: Session,
    plan: ProjectFinancePlan,
    *,
    cost_code: str,
    amount: str,
    component: str,
    parent_summary_line_id: str,
) -> ProjectFinanceBudgetLine:
    """Gyereksor hozzáadása összegző csomagsorhoz."""
    line = ProjectFinanceBudgetLine(
        line_id=_line_id(),
        plan_id_fk=plan.id,
        cost_code=cost_code,
        category="direct",
        description=f"{cost_code} szintetikus gyereksor",
        budget_net=Decimal(amount),
        cost_class="direct",
        direct_cost_component=component,
        parent_summary_line_id=parent_summary_line_id,
        currency="HUF",
    )
    db.add(line)
    db.flush()
    # A korábban betöltött budget_lines frissítése, hogy a lenyomat az új
    # gyereksort is tartalmazza.
    db.expire(plan, ["budget_lines"])
    plan.content_sha256 = plan_content_sha256(plan)
    db.commit()
    db.refresh(line)
    return line
