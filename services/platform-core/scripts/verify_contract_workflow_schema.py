from __future__ import annotations

import json

from sqlalchemy import inspect, text

from app.database import engine


def main() -> int:
    table = "contract_workflows"
    inspector = inspect(engine)
    errors: list[str] = []
    counts: dict[str, int] = {}
    if table not in inspector.get_table_names():
        errors.append(f"missing table: {table}")
    else:
        required = {
            "contract_id",
            "contract_number",
            "project_id",
            "payload_json",
            "payload_sha256",
            "package_document_id",
            "manifest_document_id",
            "status",
            "commercial_approved_by",
            "technical_approved_by",
            "legal_required",
            "legal_approved_by",
            "owner_approved_by",
            "signed_file_id",
            "signed_document_sha256",
            "postal_tracking_number",
            "postal_proof_file_id",
            "electronic_message_id",
            "electronic_recipient",
            "electronic_attachment_sha256",
            "work_start_allowed",
        }
        columns = {str(column["name"]) for column in inspector.get_columns(table)}
        for missing in sorted(required - columns):
            errors.append(f"missing column: {table}.{missing}")

    if not errors:
        queries = {
            "rows": f"SELECT COUNT(*) FROM {table}",
            "invalid_payload_hash": (
                f"SELECT COUNT(*) FROM {table} WHERE length(payload_sha256) <> 64"
            ),
            "premature_work_start": (
                f"SELECT COUNT(*) FROM {table} "
                "WHERE work_start_allowed = true AND status <> 'active'"
            ),
            "active_without_evidence": (
                f"SELECT COUNT(*) FROM {table} WHERE status = 'active' AND "
                "(signed_file_id IS NULL OR length(signed_document_sha256) <> 64 "
                "OR postal_tracking_number IS NULL OR postal_proof_file_id IS NULL "
                "OR electronic_message_id IS NULL OR electronic_recipient IS NULL "
                "OR electronic_attachment_sha256 <> signed_document_sha256)"
            ),
            "approved_without_gates": (
                f"SELECT COUNT(*) FROM {table} WHERE status IN "
                "('approved','signed','dispatched','active') AND "
                "(commercial_approved_by IS NULL OR technical_approved_by IS NULL "
                "OR owner_approved_by IS NULL "
                "OR (legal_required = true AND legal_approved_by IS NULL))"
            ),
        }
        with engine.connect() as connection:
            for key, query in queries.items():
                counts[key] = int(connection.execute(text(query)).scalar_one())
        for key, count in counts.items():
            if key != "rows" and count:
                errors.append(f"data integrity error: {key}={count}")

    print(json.dumps({"ok": not errors, "errors": errors, "counts": counts}))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
