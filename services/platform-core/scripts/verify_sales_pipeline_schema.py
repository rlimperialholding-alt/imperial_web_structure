from __future__ import annotations

from sqlalchemy import inspect

from app.database import engine


def main() -> None:
    expected = {
        "sales_opportunities": {
            "opportunity_id",
            "lead_id",
            "customer_id",
            "brand_id",
            "stage",
            "estimated_value_huf",
            "probability_percent",
            "accepted_proposal_version_id",
            "contract_id",
            "delivery_project_id",
            "version",
        },
        "sales_proposal_versions": {
            "proposal_version_id",
            "opportunity_id",
            "version",
            "status",
            "cost_net",
            "sale_net",
            "margin_percent",
            "price_snapshot_id",
            "terms_version_id",
            "technical_scope_version_id",
            "content_sha256",
            "technical_approved_by",
            "finance_approved_by",
            "legal_approved_by",
            "delivery_evidence_url",
            "customer_decision_reference",
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
