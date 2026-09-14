from __future__ import annotations

from sqlalchemy import inspect

from app.database import engine


def main() -> None:
    expected = {
        "change_cases": {"change_id", "project_id", "status", "current_version"},
        "change_versions": {
            "version_id",
            "change_id_fk",
            "version",
            "status",
            "cost_net",
            "sale_net",
            "margin_percent",
            "content_sha256",
            "customer_decision_id",
            "calendar_entry_id",
        },
        "change_lines": {
            "line_id",
            "version_id_fk",
            "quantity",
            "unit_cost_net",
            "unit_sale_net",
            "early_direct_cost",
        },
    }
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    errors: list[str] = []
    for table, required in expected.items():
        if table not in tables:
            errors.append(f"missing table: {table}")
            continue
        columns = {row["name"] for row in inspector.get_columns(table)}
        errors.extend(f"missing column: {table}.{column}" for column in sorted(required - columns))
    decision_columns = {
        row["name"] for row in inspector.get_columns("cc_customer_decision_requests")
    }
    for column in {"source_module", "source_object_id", "source_version"} - decision_columns:
        errors.append(f"missing column: cc_customer_decision_requests.{column}")
    print(
        {
            "tables_required": len(expected),
            "tables_present": len(set(expected) & tables),
            "errors": errors,
        }
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
