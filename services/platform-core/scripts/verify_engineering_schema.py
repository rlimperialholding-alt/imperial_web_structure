from sqlalchemy import inspect

from app.database import engine

REQUIRED = {
    "engineering_cases",
    "engineering_deliverables",
    "engineering_revisions",
    "engineering_findings",
    "engineering_transmittals",
    "engineering_transmittal_items",
}


def main() -> None:
    present = set(inspect(engine).get_table_names())
    missing = sorted(REQUIRED - present)
    print({"tables_required": len(REQUIRED), "tables_present": len(REQUIRED & present), "errors": missing})
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
