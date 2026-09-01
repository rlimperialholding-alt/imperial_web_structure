from __future__ import annotations

from sqlalchemy import inspect, select

from app.database import SessionLocal, engine
from app.models import CanonicalSyncLease
from app.services.canonical_sync_lease import LEASE_KEYS


def main() -> None:
    table_name = "ic_canonical_sync_leases"
    inspector = inspect(engine)
    if table_name not in set(inspector.get_table_names()):
        raise RuntimeError("Missing canonical sync lease table.")
    required_columns = {
        "lease_key",
        "holder_token",
        "acquired_at",
        "heartbeat_at",
        "expires_at",
        "generation",
        "contention_count",
        "last_contention_at",
        "last_released_at",
        "updated_at",
    }
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    missing_columns = sorted(required_columns - columns)
    if missing_columns:
        raise RuntimeError("Missing canonical sync lease columns: " + ", ".join(missing_columns))
    with SessionLocal() as db:
        keys = set(db.scalars(select(CanonicalSyncLease.lease_key)).all())
    missing_keys = sorted(LEASE_KEYS - keys)
    if missing_keys:
        raise RuntimeError("Missing canonical sync lease keys: " + ", ".join(missing_keys))
    print("Canonical sync lease schema and seeded keys: ok")


if __name__ == "__main__":
    main()
