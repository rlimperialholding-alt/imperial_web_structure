from __future__ import annotations

from sqlalchemy import inspect

from app.database import engine


def main() -> None:
    expected = {
        "mkt_campaigns": {
            "campaign_id",
            "status",
            "utm_campaign",
            "budget_net",
            "target_leads",
        },
        "mkt_leads": {
            "lead_id",
            "dedupe_key",
            "score",
            "status",
            "privacy_notice_accepted",
            "marketing_consent",
            "crm_record_id",
        },
        "mkt_lead_activities": {
            "activity_id",
            "lead_id",
            "activity_type",
            "actor",
        },
        "mkt_campaign_daily_metrics": {
            "metric_id",
            "campaign_id",
            "metric_date",
            "source_system",
            "external_key",
            "spend_net",
            "raw_payload_hash",
        },
        "mkt_optimization_decisions": {
            "decision_id",
            "campaign_id",
            "decision_type",
            "status",
            "evidence_json",
            "proposed_by",
            "decided_by",
            "executed_by",
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
