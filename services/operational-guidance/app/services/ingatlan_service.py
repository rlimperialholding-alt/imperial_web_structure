from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.ingatlan import IngatlanConnector
from app.models import ListingSyncRecord


def _checksum(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def upsert_listing(db: Session, settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    with IngatlanConnector(settings) as connector:
        remote = connector.upsert_ad(payload)
    own_id = str(payload["ownId"])
    values = {
        "own_id": own_id,
        "remote_id": str(remote.get("id")) if remote.get("id") is not None else None,
        "status_id": remote.get("statusId"),
        "checksum": _checksum(payload),
        "last_payload": payload,
        "last_synced_at": datetime.now(UTC),
    }
    statement = insert(ListingSyncRecord).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[ListingSyncRecord.own_id],
        set_={
            "remote_id": statement.excluded.remote_id,
            "status_id": statement.excluded.status_id,
            "checksum": statement.excluded.checksum,
            "last_payload": statement.excluded.last_payload,
            "last_synced_at": statement.excluded.last_synced_at,
        },
    )
    db.execute(statement)
    db.commit()
    return remote


def sync_listing_ids(db: Session, settings: Settings) -> list[dict[str, Any]]:
    with IngatlanConnector(settings) as connector:
        remote_ids = connector.list_ad_ids()

    now = datetime.now(UTC)
    for item in remote_ids:
        own_id = item.get("ownId")
        if not own_id:
            continue
        values = {
            "own_id": str(own_id),
            "remote_id": str(item.get("id")) if item.get("id") is not None else None,
            "status_id": item.get("statusId"),
            "last_payload": {},
            "last_synced_at": now,
        }
        statement = insert(ListingSyncRecord).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[ListingSyncRecord.own_id],
            set_={
                "remote_id": statement.excluded.remote_id,
                "status_id": statement.excluded.status_id,
                "last_synced_at": statement.excluded.last_synced_at,
            },
        )
        db.execute(statement)
    db.commit()
    return remote_ids
