from __future__ import annotations

from sqlalchemy import inspect

from app.database import engine


def main() -> None:
    expected = {
        "house_catalog_plans": {
            "house_id",
            "brand",
            "canonical_name",
            "lifecycle_status",
            "current_released_version",
        },
        "house_catalog_versions": {
            "catalog_version_id",
            "house_id",
            "version",
            "status",
            "catalog_price_huf",
            "gross_area_m2",
            "content_sha256",
            "source_approved_by",
            "technical_approved_by",
            "commercial_approved_by",
            "released_by",
            "withdrawn_by",
            "withdrawal_reason",
        },
    }
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    errors: list[str] = []
    for table, required in expected.items():
        if table not in tables:
            errors.append(f"missing table: {table}")
            continue
        columns = {row["name"] for row in inspector.get_columns(table)}
        errors.extend(f"missing column: {table}.{name}" for name in sorted(required - columns))
    print(
        {
            "tables_required": len(expected),
            "tables_present": len(set(expected) & tables),
            "errors": errors,
        }
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
