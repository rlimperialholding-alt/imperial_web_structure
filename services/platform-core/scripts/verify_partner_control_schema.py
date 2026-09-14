from __future__ import annotations

from sqlalchemy import inspect

from app.database import engine

REQUIRED = {
    "partner_profiles",
    "partner_certificates",
    "partner_capacity_declarations",
    "partner_project_evaluations",
    "partner_incidents",
    "partner_decisions",
}


def main() -> int:
    tables = set(inspect(engine).get_table_names())
    missing = sorted(REQUIRED - tables)
    print({"required": len(REQUIRED), "present": len(REQUIRED & tables), "missing": missing})
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
