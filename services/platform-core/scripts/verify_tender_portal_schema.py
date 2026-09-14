from __future__ import annotations

from sqlalchemy import inspect

from app.database import engine

REQUIRED = {
    "tender_packages",
    "tender_invitations",
    "tender_bids",
    "tender_bid_items",
    "tender_clarifications",
    "tender_bid_evidence",
    "tender_evaluations",
    "tender_line_items",
    "tender_bid_versions",
    "tender_bid_version_items",
    "tender_clarification_requests",
    "tender_purchase_order_preparations",
}


def main() -> int:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing = sorted(REQUIRED - tables)
    package_columns = (
        {column["name"] for column in inspector.get_columns("tender_packages")}
        if "tender_packages" in tables
        else set()
    )
    invitation_columns = (
        {column["name"] for column in inspector.get_columns("tender_invitations")}
        if "tender_invitations" in tables
        else set()
    )
    evidence_columns = (
        {column["name"] for column in inspector.get_columns("tender_bid_evidence")}
        if "tender_bid_evidence" in tables
        else set()
    )
    missing_columns = sorted(
        {
            "prequalification_required",
            "certificate_gate_enabled",
            "required_certificate_types_json",
        }
        - package_columns
    ) + sorted({"partner_id"} - invitation_columns) + sorted(
        {"scan_status", "scan_engine", "scan_engine_version", "scan_signature", "scanned_at"}
        - evidence_columns
    )
    print(
        {
            "required": len(REQUIRED),
            "present": len(REQUIRED & tables),
            "missing": missing,
            "missing_columns": missing_columns,
        }
    )
    return 1 if missing or missing_columns else 0


if __name__ == "__main__":
    raise SystemExit(main())
