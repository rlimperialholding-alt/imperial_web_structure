from __future__ import annotations

import json

from sqlalchemy import inspect, text

from app.database import engine


def main() -> int:
    inspector = inspect(engine)
    table = "cq_publication_deliveries"
    errors: list[str] = []
    counts: dict[str, int] = {}
    if table not in inspector.get_table_names():
        errors.append(f"missing table: {table}")
    else:
        required_columns = {
            "delivery_id",
            "message_id",
            "asset_id",
            "publication_proof_id",
            "target",
            "action",
            "idempotency_key",
            "payload_json",
            "payload_sha256",
            "status",
            "attempt_count",
            "max_attempts",
            "available_at",
            "claimed_by",
            "lease_expires_at",
            "external_reference",
            "receipt_json",
            "receipt_sha256",
            "last_error",
            "delivered_at",
        }
        columns = {str(row["name"]) for row in inspector.get_columns(table)}
        for missing in sorted(required_columns - columns):
            errors.append(f"missing column: {table}.{missing}")
        indexes = {
            str(row["name"]): dict(row) for row in inspector.get_indexes(table)
        }
        for name in (
            "ix_cq_publication_deliveries_status",
            "ix_cq_publication_deliveries_target",
            "ix_cq_publication_deliveries_publication_proof_id",
        ):
            if name not in indexes:
                errors.append(f"missing index: {name}")

    if not errors:
        # Statikus, rögzített táblanévvel írt integritás-lekérdezések: nincs
        # f-string/interpoláció, a szöveg változatlanul kerül a motorhoz.
        integrity_queries = {
            "rows": "SELECT COUNT(*) FROM cq_publication_deliveries",
            "invalid_attempts": (
                "SELECT COUNT(*) FROM cq_publication_deliveries "
                "WHERE attempt_count < 0 OR max_attempts < 1 "
                "OR attempt_count > max_attempts"
            ),
            "invalid_hashes": (
                "SELECT COUNT(*) FROM cq_publication_deliveries "
                "WHERE length(payload_sha256) <> 64 "
                "OR length(idempotency_key) <> 64"
            ),
            "invalid_claims": (
                "SELECT COUNT(*) FROM cq_publication_deliveries WHERE "
                "(status = 'claimed' AND "
                "(claimed_by IS NULL OR claimed_at IS NULL OR lease_expires_at IS NULL)) "
                "OR (status <> 'claimed' AND "
                "(claimed_by IS NOT NULL OR claimed_at IS NOT NULL "
                "OR lease_expires_at IS NOT NULL))"
            ),
            "invalid_deliveries": (
                "SELECT COUNT(*) FROM cq_publication_deliveries "
                "WHERE status = 'delivered' AND "
                "(external_reference IS NULL OR receipt_json IS NULL "
                "OR receipt_sha256 IS NULL OR delivered_at IS NULL)"
            ),
            "unexplained_failures": (
                "SELECT COUNT(*) FROM cq_publication_deliveries "
                "WHERE status IN ('retry','dead_letter') AND last_error IS NULL"
            ),
        }
        with engine.connect() as connection:
            for key, query in integrity_queries.items():
                counts[key] = int(connection.execute(text(query)).scalar_one())
        for key in integrity_queries:
            if key != "rows" and counts[key]:
                errors.append(f"data integrity error: {key}={counts[key]}")

    print(json.dumps({"ok": not errors, "errors": errors, "counts": counts}))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
