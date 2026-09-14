from __future__ import annotations

from sqlalchemy import inspect

from app.database import engine


def main() -> None:
    required = {
        "cc_customer_portal_updates",
        "cc_customer_portal_update_acknowledgements",
        "cc_customer_decision_requests",
        "cc_customer_decision_responses",
    }
    present = set(inspect(engine).get_table_names())
    missing = sorted(required - present)
    result = {"required": len(required), "present": len(required & present), "missing": missing}
    print(result)
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
