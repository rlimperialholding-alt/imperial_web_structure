from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    EnterpriseCanonicalRecord,
    ModuleBusinessRecord,
    ProjectFinancePlan,
    ProjectRegistry,
)
from .financial_allocations import allocation_scope
from .project_finance import finance_project_ids_for_user, plan_summary


class InvoiceCurrencyTotals(TypedDict):
    open: Decimal
    paid: Decimal
    count: int


def _json(value: str | None) -> dict[str, Any]:
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def finance_intelligence_dashboard(
    db: Session,
    *,
    project_id: str | None = None,
    user: object | None = None,
) -> dict[str, Any]:
    allowed_project_ids = (
        None if user is None else finance_project_ids_for_user(db, user)
    )
    if (
        allowed_project_ids is not None
        and project_id
        and project_id not in allowed_project_ids
    ):
        raise PermissionError(
            "A projekt nincs a felhasználó pénzügyi felelősségi körében."
        )
    query = select(EnterpriseCanonicalRecord).where(EnterpriseCanonicalRecord.domain == "finance")
    records = list(db.scalars(query.order_by(EnterpriseCanonicalRecord.updated_at.desc())))
    today = date.today()
    cashflow: list[dict[str, Any]] = []
    incoming: list[dict[str, Any]] = []
    supplier: list[dict[str, Any]] = []
    unallocated = 0
    corporate = 0

    for row in records:
        data = _json(row.data_json)
        row_project_id = str(row.project_id or data.get("projectId") or "").strip() or None
        if allowed_project_ids is not None and row_project_id not in allowed_project_ids:
            continue
        if project_id and row_project_id != project_id:
            continue
        item: dict[str, Any] = {"record": row, "data": data, "project_id": row_project_id}
        if row.entity_type == "cashflow_entry":
            item.update(
                {
                    "amount": _money(data.get("amount")),
                    "currency": str(data.get("currency") or "HUF").upper(),
                    "direction": str(data.get("direction") or "outflow").lower(),
                    "due_date": _date(data.get("dueDate")),
                    "status": str(data.get("status") or "due").lower(),
                }
            )
            cashflow.append(item)
        elif row.entity_type == "incoming_invoice":
            item.update(
                {
                    "gross": _money(data.get("grossAmount")),
                    "currency": str(data.get("currency") or "HUF").upper(),
                    "due_date": _date(data.get("dueDate")),
                    "paid": str(data.get("paymentStatus") or "UNPAID").upper() == "PAID",
                }
            )
            incoming.append(item)
        elif row.entity_type == "supplier_invoice":
            item.update(
                {
                    "gross": _money(data.get("grossAmount")),
                    "currency": str(data.get("currency") or "HUF").upper(),
                    "due_date": _date(data.get("dueDate")),
                    "paid": bool(data.get("paymentDate")),
                }
            )
            supplier.append(item)
        if row.entity_type in {"cashflow_entry", "supplier_invoice"} and not row_project_id:
            if allocation_scope(row) == "corporate":
                corporate += 1
            else:
                unallocated += 1

    months: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(
        lambda: {"inflow": Decimal("0"), "outflow": Decimal("0")}
    )
    for item in cashflow:
        due = item["due_date"] or today
        key = (due.strftime("%Y-%m"), item["currency"])
        direction = "inflow" if item["direction"] in {"inflow", "income", "revenue"} else "outflow"
        months[key][direction] += item["amount"]
    cumulative_by_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    month_rows: list[dict[str, Any]] = []
    for period, currency in sorted(months):
        values = months[(period, currency)]
        balance = values["inflow"] - values["outflow"]
        cumulative_by_currency[currency] += balance
        month_rows.append(
            {
                "period": period,
                "currency": currency,
                **values,
                "balance": balance,
                "cumulative": cumulative_by_currency[currency],
            }
        )

    open_invoices = [item for item in incoming if not item["paid"]]
    overdue = [item for item in open_invoices if item["due_date"] and item["due_date"] < today]
    due_30 = [
        item
        for item in open_invoices
        if item["due_date"] and today <= item["due_date"] <= today + timedelta(days=30)
    ]
    currency_totals: dict[str, InvoiceCurrencyTotals] = defaultdict(
        lambda: {"open": Decimal("0"), "paid": Decimal("0"), "count": 0}
    )
    for item in incoming:
        bucket = currency_totals[item["currency"]]
        bucket["count"] += 1
        if item["paid"]:
            bucket["paid"] += item["gross"]
        else:
            bucket["open"] += item["gross"]

    budget_query = select(ModuleBusinessRecord).where(
        ModuleBusinessRecord.module_key == "finance-intelligence",
        ModuleBusinessRecord.archived.is_(False),
    )
    if project_id:
        budget_query = budget_query.where(ModuleBusinessRecord.project_id == project_id)
    if allowed_project_ids is not None:
        budget_query = budget_query.where(
            ModuleBusinessRecord.project_id.in_(allowed_project_ids)
        )
    budget_records = list(
        db.scalars(budget_query.order_by(ModuleBusinessRecord.updated_at.desc()).limit(100))
    )
    plan_query = (
        select(ProjectFinancePlan)
        .options(
            selectinload(ProjectFinancePlan.budget_lines),
            selectinload(ProjectFinancePlan.cashflow_lines),
        )
        .where(ProjectFinancePlan.status == "approved")
    )
    if project_id:
        plan_query = plan_query.where(ProjectFinancePlan.project_id == project_id)
    if allowed_project_ids is not None:
        plan_query = plan_query.where(
            ProjectFinancePlan.project_id.in_(allowed_project_ids)
        )
    approved_plans = [
        {"row": row, "summary": plan_summary(row)}
        for row in db.scalars(plan_query.order_by(ProjectFinancePlan.updated_at.desc())).unique()
    ]
    project_query = select(ProjectRegistry)
    if allowed_project_ids is not None:
        project_query = project_query.where(
            ProjectRegistry.project_id.in_(allowed_project_ids)
        )
    projects = list(db.scalars(project_query.order_by(ProjectRegistry.name)))
    warnings = []
    if cashflow and not any(
        item["direction"] in {"inflow", "income", "revenue"} for item in cashflow
    ):
        warnings.append(
            "A cash-flow állományban jelenleg nincs bevételi irányú tétel; "
            "a nettó előrejelzés ezért csak kiadási oldalt mutat."
        )
    if unallocated:
        warnings.append(
            f"{unallocated} pénzügyi tételhez nincs kanonikus ProjectID; "
            "ezek projektfedezetbe nem számíthatók be."
        )
    if not cashflow:
        warnings.append("Nincs a szűrésnek megfelelő cash-flow tétel; a havi előrejelzés üres.")
    if project_id and not approved_plans:
        warnings.append(
            "A kiválasztott projekthez nincs jóváhagyott pénzügyi baseline; "
            "a projektfedezet még nem tekinthető vezetőileg elfogadottnak."
        )

    return {
        "project_id": project_id,
        "projects": projects,
        "cashflow": cashflow,
        "incoming": incoming,
        "supplier": supplier,
        "month_rows": month_rows,
        "open_invoices": open_invoices,
        "overdue": overdue,
        "due_30": due_30,
        "currency_totals": dict(currency_totals),
        "budget_records": budget_records,
        "approved_plans": approved_plans,
        "unallocated": unallocated,
        "corporate": corporate,
        "warnings": warnings,
        "source_counts": {
            "cashflow": len(cashflow),
            "incoming": len(incoming),
            "supplier": len(supplier),
        },
    }
