from __future__ import annotations

from sqlalchemy import inspect

from app.database import engine


def main() -> None:
    expected = {
        "finance_project_plans": {
            "plan_id",
            "project_id",
            "version",
            "status",
            "currency",
            "contract_revenue_net",
            "target_margin_percent",
        },
        "finance_project_budget_lines": {
            "line_id",
            "plan_id_fk",
            "cost_code",
            "budget_net",
            "actual_net",
            "estimate_to_complete_net",
        },
        "finance_project_cashflow_lines": {
            "flow_id",
            "plan_id_fk",
            "period_date",
            "direction",
            "amount_net",
            "status",
        },
    }
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    errors: list[str] = []
    for table, required_columns in expected.items():
        if table not in tables:
            errors.append(f"missing table: {table}")
            continue
        columns = {row["name"] for row in inspector.get_columns(table)}
        for column in sorted(required_columns - columns):
            errors.append(f"missing column: {table}.{column}")
    plan_indexes = {
        row["name"]: row for row in inspector.get_indexes("finance_project_plans")
    }
    open_plan_index = plan_indexes.get("uq_finance_project_single_open_plan")
    if open_plan_index is None:
        errors.append("missing index: uq_finance_project_single_open_plan")
    elif not open_plan_index.get("unique"):
        errors.append("non-unique index: uq_finance_project_single_open_plan")
    result = {
        "tables_required": len(expected),
        "tables_present": len(set(expected) & tables),
        "errors": errors,
    }
    print(result)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
