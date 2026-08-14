from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import TypedDict
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from ..audit import audit
from ..models import (
    ProjectFinanceBudgetLine,
    ProjectFinanceCashflowLine,
    ProjectFinancePlan,
    ProjectObjectState,
    ProjectRegistry,
    TaskRecord,
)

EDIT_ROLES = {"owner", "platform-admin", "finance", "project-manager"}
FINANCE_APPROVAL_ROLES = {"owner", "platform-admin", "finance"}
LEADERSHIP_ROLES = {"owner", "managing-director", "platform-admin"}


class CashflowSummaryRow(TypedDict):
    period: str
    inflow: Decimal
    outflow: Decimal
    net: Decimal
    cumulative: Decimal


class FinancePlanSummary(TypedDict):
    revenue: Decimal
    budget_lines: Decimal
    budget_cost: Decimal
    budget_margin: Decimal
    committed: Decimal
    actual: Decimal
    forecast_cost: Decimal
    forecast_margin: Decimal
    forecast_margin_percent: Decimal
    variance_to_budget: Decimal
    target_margin_percent: Decimal
    target_margin_met: bool
    cashflow: list[CashflowSummaryRow]
    minimum_cash_position: Decimal


def _identity(user: object) -> tuple[str, str]:
    return str(getattr(user, "role", "")), str(getattr(user, "email", "")).lower()


def _money(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Érvénytelen pénzügyi összeg.") from exc
    if result < 0:
        raise ValueError("Pénzügyi tervben negatív összeg nem rögzíthető.")
    return result.quantize(Decimal("0.01"))


def _plan(db: Session, plan_id: str) -> ProjectFinancePlan:
    row = db.scalar(
        select(ProjectFinancePlan)
        .options(
            selectinload(ProjectFinancePlan.budget_lines),
            selectinload(ProjectFinancePlan.cashflow_lines),
        )
        .execution_options(populate_existing=True)
        .where(ProjectFinancePlan.plan_id == plan_id)
    )
    if not row:
        raise KeyError(plan_id)
    return row


def _require_role(user: object, allowed: set[str]) -> tuple[str, str]:
    role, email = _identity(user)
    if role not in allowed:
        raise PermissionError("Ehhez a pénzügyi művelethez nincs jogosultsága.")
    return role, email


def _require_draft(plan: ProjectFinancePlan) -> None:
    if plan.status != "draft":
        raise ValueError("A benyújtott pénzügyi terv nem módosítható; készítsen új verziót.")


def plan_summary(plan: ProjectFinancePlan) -> FinancePlanSummary:
    revenue = plan.contract_revenue_net + plan.approved_change_revenue_net
    budget_lines = sum((row.budget_net for row in plan.budget_lines), Decimal("0"))
    budget_cost = budget_lines + plan.contingency_net
    committed = sum((row.committed_net for row in plan.budget_lines), Decimal("0"))
    actual = sum((row.actual_net for row in plan.budget_lines), Decimal("0"))
    forecast_cost = (
        sum(
            (row.actual_net + row.estimate_to_complete_net for row in plan.budget_lines),
            Decimal("0"),
        )
        + plan.contingency_net
    )
    forecast_margin = revenue - forecast_cost
    forecast_margin_percent = (
        (forecast_margin / revenue * Decimal("100")) if revenue else Decimal("0")
    ).quantize(Decimal("0.01"))
    budget_margin = revenue - budget_cost
    variance = forecast_cost - budget_cost
    month_buckets: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"inflow": Decimal("0"), "outflow": Decimal("0")}
    )
    for row in plan.cashflow_lines:
        month_buckets[row.period_date.strftime("%Y-%m")][row.direction] += row.amount_net
    cumulative = Decimal("0")
    cashflow: list[CashflowSummaryRow] = []
    for period in sorted(month_buckets):
        bucket = month_buckets[period]
        net = bucket["inflow"] - bucket["outflow"]
        cumulative += net
        cashflow.append(
            {
                "period": period,
                "inflow": bucket["inflow"],
                "outflow": bucket["outflow"],
                "net": net,
                "cumulative": cumulative,
            }
        )
    return {
        "revenue": revenue,
        "budget_lines": budget_lines,
        "budget_cost": budget_cost,
        "budget_margin": budget_margin,
        "committed": committed,
        "actual": actual,
        "forecast_cost": forecast_cost,
        "forecast_margin": forecast_margin,
        "forecast_margin_percent": forecast_margin_percent,
        "variance_to_budget": variance,
        "target_margin_percent": plan.target_margin_percent,
        "target_margin_met": forecast_margin_percent >= plan.target_margin_percent,
        "cashflow": cashflow,
        "minimum_cash_position": min((row["cumulative"] for row in cashflow), default=Decimal("0")),
    }


def finance_plan_workspace(db: Session, *, project_id: str | None = None) -> dict[str, object]:
    stmt = select(ProjectFinancePlan).options(
        selectinload(ProjectFinancePlan.budget_lines),
        selectinload(ProjectFinancePlan.cashflow_lines),
    )
    if project_id:
        stmt = stmt.where(ProjectFinancePlan.project_id == project_id)
    plans = db.scalars(stmt.order_by(desc(ProjectFinancePlan.updated_at))).unique().all()
    return {
        "plans": [{"row": row, "summary": plan_summary(row)} for row in plans],
        "projects": db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)).all(),
        "project_id": project_id,
        "metrics": {
            "plans": len(plans),
            "draft": sum(1 for row in plans if row.status == "draft"),
            "review": sum(1 for row in plans if row.status in {"review", "finance_approved"}),
            "approved": sum(1 for row in plans if row.status == "approved"),
        },
    }


def create_finance_plan(
    db: Session,
    user: object,
    *,
    project_id: str,
    currency: str,
    contract_revenue_net: object,
    approved_change_revenue_net: object,
    contingency_net: object,
    target_margin_percent: object,
    forecast_note: str,
) -> ProjectFinancePlan:
    _role, email = _require_role(user, EDIT_ROLES)
    project_id = project_id.strip()
    if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id)):
        raise ValueError("A ProjectID nem található a projekttörzsben.")
    open_plan = db.scalar(
        select(ProjectFinancePlan).where(
            ProjectFinancePlan.project_id == project_id,
            ProjectFinancePlan.status.in_(["draft", "review", "finance_approved"]),
        )
    )
    if open_plan:
        raise ValueError("A projekthez már van nyitott pénzügyi tervverzió.")
    version = (
        db.scalar(
            select(func.max(ProjectFinancePlan.version)).where(
                ProjectFinancePlan.project_id == project_id
            )
        )
        or 0
    ) + 1
    target = _money(target_margin_percent)
    if target > 100:
        raise ValueError("A célfedezet legfeljebb 100% lehet.")
    normalized_currency = currency.strip().upper()
    if normalized_currency not in {"HUF", "EUR"}:
        raise ValueError("A pénzügyi terv pénzneme HUF vagy EUR lehet.")
    row = ProjectFinancePlan(
        plan_id=f"FIN-PLAN-{project_id}-{version:02d}",
        project_id=project_id,
        version=version,
        currency=normalized_currency,
        contract_revenue_net=_money(contract_revenue_net),
        approved_change_revenue_net=_money(approved_change_revenue_net),
        contingency_net=_money(contingency_net),
        target_margin_percent=target,
        forecast_note=forecast_note.strip() or None,
        created_by=email,
    )
    db.add(row)
    audit(
        db,
        actor=email,
        action="finance_plan_created",
        entity_type="project_finance_plan",
        entity_id=row.plan_id,
        after={"project_id": project_id, "version": version},
    )
    db.commit()
    db.refresh(row)
    return row


def add_budget_line(
    db: Session,
    plan_id: str,
    user: object,
    *,
    cost_code: str,
    category: str,
    description: str,
    budget_net: object,
    committed_net: object,
    actual_net: object,
    estimate_to_complete_net: object,
    source_type: str,
    source_id: str,
) -> ProjectFinanceBudgetLine:
    _role, email = _require_role(user, EDIT_ROLES)
    plan = _plan(db, plan_id)
    _require_draft(plan)
    cost_code, category, description = (
        cost_code.strip(),
        category.strip(),
        description.strip(),
    )
    if not cost_code or not category or not description:
        raise ValueError("A költségkód, kategória és leírás kötelező.")
    if any(row.cost_code == cost_code for row in plan.budget_lines):
        raise ValueError("A költségkód ebben a tervverzióban már szerepel.")
    row = ProjectFinanceBudgetLine(
        line_id=f"FIN-LINE-{uuid4().hex[:12].upper()}",
        plan_id_fk=plan.id,
        cost_code=cost_code,
        category=category,
        description=description,
        budget_net=_money(budget_net),
        committed_net=_money(committed_net),
        actual_net=_money(actual_net),
        estimate_to_complete_net=_money(estimate_to_complete_net),
        source_type=source_type.strip() or None,
        source_id=source_id.strip() or None,
    )
    db.add(row)
    audit(
        db,
        actor=email,
        action="finance_budget_line_added",
        entity_type="project_finance_plan",
        entity_id=plan_id,
        after={"cost_code": cost_code, "budget_net": str(row.budget_net)},
    )
    db.commit()
    db.refresh(row)
    return row


def add_cashflow_line(
    db: Session,
    plan_id: str,
    user: object,
    *,
    period_date: date,
    direction: str,
    category: str,
    description: str,
    amount_net: object,
    status: str,
    source_type: str,
    source_id: str,
) -> ProjectFinanceCashflowLine:
    _role, email = _require_role(user, EDIT_ROLES)
    plan = _plan(db, plan_id)
    _require_draft(plan)
    if direction not in {"inflow", "outflow"}:
        raise ValueError("A cashflow iránya inflow vagy outflow lehet.")
    if status not in {"forecast", "committed", "actual"}:
        raise ValueError("Érvénytelen cashflow-státusz.")
    if not category.strip() or not description.strip():
        raise ValueError("A cashflow kategóriája és leírása kötelező.")
    row = ProjectFinanceCashflowLine(
        flow_id=f"FIN-FLOW-{uuid4().hex[:12].upper()}",
        plan_id_fk=plan.id,
        period_date=period_date,
        direction=direction,
        category=category.strip(),
        description=description.strip(),
        amount_net=_money(amount_net),
        status=status,
        source_type=source_type.strip() or None,
        source_id=source_id.strip() or None,
    )
    if row.amount_net == 0:
        raise ValueError("A cashflow összege nem lehet nulla.")
    db.add(row)
    audit(
        db,
        actor=email,
        action="finance_cashflow_line_added",
        entity_type="project_finance_plan",
        entity_id=plan_id,
        after={"direction": direction, "amount_net": str(row.amount_net)},
    )
    db.commit()
    db.refresh(row)
    return row


def _validate_submission(plan: ProjectFinancePlan) -> FinancePlanSummary:
    summary = plan_summary(plan)
    if summary["revenue"] <= 0:
        raise ValueError("A pénzügyi terv bevétele nem lehet nulla.")
    if not plan.budget_lines:
        raise ValueError("Legalább egy tételes költségsor kötelező.")
    directions = {row.direction for row in plan.cashflow_lines}
    if directions != {"inflow", "outflow"}:
        raise ValueError("A tervhez bevételi és kiadási cashflow-sor is kötelező.")
    if summary["forecast_cost"] <= 0:
        raise ValueError("A forecast költség nem lehet nulla.")
    return summary


def submit_finance_plan(db: Session, plan_id: str, user: object) -> ProjectFinancePlan:
    _role, email = _require_role(user, EDIT_ROLES)
    plan = _plan(db, plan_id)
    _require_draft(plan)
    _validate_submission(plan)
    plan.status = "review"
    plan.submitted_by = email
    plan.submitted_at = datetime.now(UTC)
    db.add(
        TaskRecord(
            task_id=f"TASK-FIN-REV-{uuid4().hex[:10].upper()}",
            project_id=plan.project_id,
            source_event_id=plan.plan_id,
            title=f"Pénzügyi terv ellenőrzése: {plan.plan_id}",
            assignee="finance@imperial.local",
            priority="high",
            status="open",
        )
    )
    audit(
        db,
        actor=email,
        action="finance_plan_submitted",
        entity_type="project_finance_plan",
        entity_id=plan.plan_id,
        after=plan_summary(plan),
    )
    db.commit()
    db.refresh(plan)
    return plan


def finance_approve_plan(
    db: Session, plan_id: str, user: object, *, note: str
) -> ProjectFinancePlan:
    _role, email = _require_role(user, FINANCE_APPROVAL_ROLES)
    plan = _plan(db, plan_id)
    if plan.status != "review":
        raise ValueError("Pénzügyi jóváhagyás csak review állapotban adható.")
    if plan.submitted_by == email:
        raise PermissionError("A pénzügyi terv benyújtója nem hagyhatja jóvá a saját tervét.")
    summary = _validate_submission(plan)
    if len(note.strip()) < 10:
        raise ValueError("A pénzügyi ellenőrzés indoklása kötelező.")
    plan.status = "finance_approved"
    plan.finance_approved_by = email
    plan.finance_approved_at = datetime.now(UTC)
    for task in db.scalars(
        select(TaskRecord).where(
            TaskRecord.source_event_id == plan.plan_id,
            TaskRecord.assignee == "finance@imperial.local",
            TaskRecord.status != "done",
        )
    ).all():
        task.status = "done"
    db.add(
        TaskRecord(
            task_id=f"TASK-FIN-APP-{uuid4().hex[:10].upper()}",
            project_id=plan.project_id,
            source_event_id=plan.plan_id,
            title=f"Projektfedezet végső jóváhagyása: {plan.plan_id}",
            assignee="managing-director@imperial.local",
            priority="high",
            status="open",
            executive_relevance=True,
        )
    )
    audit(
        db,
        actor=email,
        action="finance_plan_finance_approved",
        entity_type="project_finance_plan",
        entity_id=plan.plan_id,
        after={"note": note.strip(), **summary},
    )
    db.commit()
    db.refresh(plan)
    return plan


def leadership_approve_plan(
    db: Session,
    plan_id: str,
    user: object,
    *,
    note: str,
    margin_exception_reason: str,
) -> ProjectFinancePlan:
    _role, email = _require_role(user, LEADERSHIP_ROLES)
    plan = _plan(db, plan_id)
    if plan.status != "finance_approved":
        raise ValueError("Végső jóváhagyás csak pénzügyileg jóváhagyott tervre adható.")
    if email in {plan.submitted_by, plan.finance_approved_by}:
        raise PermissionError(
            "A vezetői jóváhagyó nem lehet a terv benyújtója vagy pénzügyi ellenőre."
        )
    summary = _validate_submission(plan)
    exception = margin_exception_reason.strip()
    if not summary["target_margin_met"] and len(exception) < 20:
        raise ValueError(
            "Célfedezet alatti tervhez legalább 20 karakteres vezetői kivételindoklás kell."
        )
    if len(note.strip()) < 10:
        raise ValueError("A vezetői döntés indoklása kötelező.")
    for previous in db.scalars(
        select(ProjectFinancePlan).where(
            ProjectFinancePlan.project_id == plan.project_id,
            ProjectFinancePlan.status == "approved",
            ProjectFinancePlan.id != plan.id,
        )
    ).all():
        previous.status = "superseded"
    plan.status = "approved"
    plan.leadership_approved_by = email
    plan.leadership_approved_at = datetime.now(UTC)
    plan.margin_exception_reason = exception or None
    for task in db.scalars(
        select(TaskRecord).where(
            TaskRecord.source_event_id == plan.plan_id,
            TaskRecord.assignee == "managing-director@imperial.local",
            TaskRecord.status != "done",
        )
    ).all():
        task.status = "done"
    state = db.scalar(
        select(ProjectObjectState).where(
            ProjectObjectState.project_id == plan.project_id,
            ProjectObjectState.source_module == "finance-intelligence",
            ProjectObjectState.object_type == "FinancePlan",
            ProjectObjectState.object_id == plan.plan_id,
        )
    )
    if not state:
        state = ProjectObjectState(
            project_id=plan.project_id,
            source_module="finance-intelligence",
            object_type="FinancePlan",
            object_id=plan.plan_id,
            status="approved",
        )
        db.add(state)
    state.status = "approved"
    state.summary = (
        f"Jóváhagyott forecast fedezet: {summary['forecast_margin']} {plan.currency} "
        f"({summary['forecast_margin_percent']}%)"
    )
    audit(
        db,
        actor=email,
        action="finance_plan_leadership_approved",
        entity_type="project_finance_plan",
        entity_id=plan.plan_id,
        after={"note": note.strip(), "margin_exception_reason": exception, **summary},
    )
    db.commit()
    db.refresh(plan)
    return plan


def reject_finance_plan(
    db: Session, plan_id: str, user: object, *, reason: str
) -> ProjectFinancePlan:
    role, email = _identity(user)
    plan = _plan(db, plan_id)
    allowed = (plan.status == "review" and role in FINANCE_APPROVAL_ROLES) or (
        plan.status == "finance_approved" and role in LEADERSHIP_ROLES
    )
    if not allowed:
        if role not in FINANCE_APPROVAL_ROLES | LEADERSHIP_ROLES:
            raise PermissionError("Ehhez a pénzügyi elutasításhoz nincs jogosultsága.")
        raise ValueError("A pénzügyi terv ebben az állapotban nem utasítható el.")
    reason = reason.strip()
    if len(reason) < 15:
        raise ValueError("Az elutasítás legalább 15 karakteres indoklása kötelező.")
    previous_status = plan.status
    plan.status = "rejected"
    for task in db.scalars(
        select(TaskRecord).where(
            TaskRecord.source_event_id == plan.plan_id,
            TaskRecord.status != "done",
        )
    ).all():
        task.status = "done"
    audit(
        db,
        actor=email,
        action="finance_plan_rejected",
        entity_type="project_finance_plan",
        entity_id=plan.plan_id,
        before={"status": previous_status},
        after={"status": plan.status, "reason": reason},
    )
    db.commit()
    db.refresh(plan)
    return plan


def clone_finance_plan(db: Session, plan_id: str, user: object) -> ProjectFinancePlan:
    _role, email = _require_role(user, EDIT_ROLES)
    source = _plan(db, plan_id)
    if source.status in {"draft", "review", "finance_approved"}:
        raise ValueError("Nyitott tervet nem lehet új verzióra klónozni.")
    if db.scalar(
        select(ProjectFinancePlan).where(
            ProjectFinancePlan.project_id == source.project_id,
            ProjectFinancePlan.status.in_(["draft", "review", "finance_approved"]),
        )
    ):
        raise ValueError("A projekthez már van nyitott pénzügyi tervverzió.")
    version = (
        db.scalar(
            select(func.max(ProjectFinancePlan.version)).where(
                ProjectFinancePlan.project_id == source.project_id
            )
        )
        or source.version
    ) + 1
    clone = ProjectFinancePlan(
        plan_id=f"FIN-PLAN-{source.project_id}-{version:02d}",
        project_id=source.project_id,
        version=version,
        currency=source.currency,
        contract_revenue_net=source.contract_revenue_net,
        approved_change_revenue_net=source.approved_change_revenue_net,
        contingency_net=source.contingency_net,
        target_margin_percent=source.target_margin_percent,
        forecast_note=source.forecast_note,
        created_by=email,
    )
    db.add(clone)
    db.flush()
    for budget_row in source.budget_lines:
        db.add(
            ProjectFinanceBudgetLine(
                line_id=f"FIN-LINE-{uuid4().hex[:12].upper()}",
                plan_id_fk=clone.id,
                cost_code=budget_row.cost_code,
                category=budget_row.category,
                description=budget_row.description,
                budget_net=budget_row.budget_net,
                committed_net=budget_row.committed_net,
                actual_net=budget_row.actual_net,
                estimate_to_complete_net=budget_row.estimate_to_complete_net,
                source_type=budget_row.source_type,
                source_id=budget_row.source_id,
            )
        )
    for cashflow_row in source.cashflow_lines:
        db.add(
            ProjectFinanceCashflowLine(
                flow_id=f"FIN-FLOW-{uuid4().hex[:12].upper()}",
                plan_id_fk=clone.id,
                period_date=cashflow_row.period_date,
                direction=cashflow_row.direction,
                category=cashflow_row.category,
                description=cashflow_row.description,
                amount_net=cashflow_row.amount_net,
                status=cashflow_row.status,
                source_type=cashflow_row.source_type,
                source_id=cashflow_row.source_id,
            )
        )
    audit(
        db,
        actor=email,
        action="finance_plan_version_cloned",
        entity_type="project_finance_plan",
        entity_id=clone.plan_id,
        before={"source_plan_id": source.plan_id},
        after={"project_id": clone.project_id, "version": version},
    )
    db.commit()
    db.refresh(clone)
    return clone
