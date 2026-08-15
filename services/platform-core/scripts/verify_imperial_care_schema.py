from __future__ import annotations

from sqlalchemy import inspect

from app.database import engine


def main() -> None:
    required = {"care_cases", "care_messages", "care_evidence"}
    tables = set(inspect(engine).get_table_names())
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError("Missing Imperial Care tables: " + ", ".join(missing))
    evidence_columns = {
        column["name"] for column in inspect(engine).get_columns("care_evidence")
    }
    required_evidence_columns = {
        "scan_status",
        "scan_engine",
        "scan_engine_version",
        "scan_signature",
        "scanned_at",
    }
    missing_columns = sorted(required_evidence_columns - evidence_columns)
    if missing_columns:
        raise RuntimeError(
            "Missing Imperial Care evidence columns: " + ", ".join(missing_columns)
        )
    print("Imperial Care migration tables and AV evidence columns: ok")


if __name__ == "__main__":
    main()
