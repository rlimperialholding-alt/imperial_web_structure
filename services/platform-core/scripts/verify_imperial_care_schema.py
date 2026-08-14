from __future__ import annotations

from sqlalchemy import inspect

from app.database import engine


def main() -> None:
    required = {"care_cases", "care_messages", "care_evidence"}
    tables = set(inspect(engine).get_table_names())
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError("Missing Imperial Care tables: " + ", ".join(missing))
    print("Imperial Care migration tables: ok")


if __name__ == "__main__":
    main()
