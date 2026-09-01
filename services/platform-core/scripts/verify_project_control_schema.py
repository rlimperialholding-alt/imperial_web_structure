from sqlalchemy import inspect

from app.database import engine

REQUIRED = {
    "project_control_baselines",
    "project_control_forecasts",
    "project_control_variances",
    "project_control_recovery_actions",
    "project_control_weekly_reports",
}


def main() -> None:
    present = set(inspect(engine).get_table_names())
    missing = sorted(REQUIRED - present)
    print({"tables_required": len(REQUIRED), "tables_present": len(REQUIRED & present), "errors": missing})
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
