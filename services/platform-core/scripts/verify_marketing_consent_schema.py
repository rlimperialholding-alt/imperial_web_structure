from __future__ import annotations

import json

from sqlalchemy import inspect, text

from app.database import engine


def main() -> int:
    inspector = inspect(engine)
    errors: list[str] = []
    required_columns = {
        "marketing_consent_updated_at",
        "marketing_consent_source",
        "marketing_consent_evidence",
        "marketing_consent_withdrawn_at",
        "consent_management_token",
    }
    columns: dict[str, dict[str, object]] = {
        str(column["name"]): dict(column)
        for column in inspector.get_columns("mkt_leads")
    }
    for missing in sorted(required_columns - columns.keys()):
        errors.append(f"missing column: mkt_leads.{missing}")
    if columns.get("consent_management_token", {}).get("nullable") is not False:
        errors.append("nullable column: mkt_leads.consent_management_token")

    indexes: dict[str, dict[str, object]] = {
        str(index["name"]): dict(index)
        for index in inspector.get_indexes("mkt_leads")
    }
    token_index = indexes.get("ix_mkt_leads_consent_management_token")
    if not token_index:
        errors.append("missing index: ix_mkt_leads_consent_management_token")
    elif not token_index.get("unique"):
        errors.append("non-unique index: ix_mkt_leads_consent_management_token")

    counts: dict[str, int] = {}
    if not errors:
        with engine.connect() as connection:
            counts["leads"] = int(
                connection.execute(text("SELECT COUNT(*) FROM mkt_leads")).scalar_one()
            )
            counts["null_tokens"] = int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM mkt_leads "
                        "WHERE consent_management_token IS NULL"
                    )
                ).scalar_one()
            )
            counts["duplicate_tokens"] = int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM ("
                        "SELECT consent_management_token FROM mkt_leads "
                        "GROUP BY consent_management_token HAVING COUNT(*) > 1"
                        ") AS duplicate_consent_tokens"
                    )
                ).scalar_one()
            )
            counts["active_withdrawn_conflicts"] = int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM mkt_leads "
                        "WHERE marketing_consent = true "
                        "AND marketing_consent_withdrawn_at IS NOT NULL"
                    )
                ).scalar_one()
            )
        for key in ("null_tokens", "duplicate_tokens", "active_withdrawn_conflicts"):
            if counts[key]:
                errors.append(f"data integrity error: {key}={counts[key]}")

    print(json.dumps({"ok": not errors, "errors": errors, "counts": counts}))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
