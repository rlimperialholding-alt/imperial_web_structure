from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.auth import Actor, require_manager_or_service
from app.db import get_db
from app.models import AuditEventRecord
from app.operations.factory import get_operational_services

router = APIRouter(prefix="/operations", tags=["operations"])


def _json_status_counts(paths: list[Path], field: str = "status") -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            counts[str(payload.get(field) or "unknown")] += 1
        except Exception:  # noqa: BLE001 - status endpoint must remain available
            counts["unreadable"] += 1
    return dict(sorted(counts.items()))


@router.get("/status")
def operational_status(_: Actor = Depends(require_manager_or_service)):
    services = get_operational_services()
    process_store = services.process_cards.store
    checklist_store = services.checklists.store
    source_files = list(process_store.sources_dir.glob("*.json"))
    card_files = list(process_store.cards_dir.glob("*.json"))
    template_files = list(checklist_store.templates_dir.glob("*.json"))
    instance_files = list(checklist_store.instances_dir.glob("*.json"))
    return {
        "catalog": {
            "processes": len(source_files),
            "checklist_templates": len(template_files),
        },
        "process_cards": {
            "versions": len(card_files),
            "status_counts": _json_status_counts(card_files),
            "pending_approvals": len(list(process_store.approval_dir.glob("*.json"))),
        },
        "checklists": {
            "instances": len(instance_files),
            "status_counts": _json_status_counts(instance_files),
            "pending_template_approvals": len(
                list(checklist_store.template_approval_dir.glob("*.json"))
            ),
            "pending_instance_approvals": len(
                list(checklist_store.instance_approval_dir.glob("*.json"))
            ),
        },
    }


@router.get("/audit/recent")
def recent_audit_events(
    limit: int = Query(default=50, ge=1, le=250),
    _: Actor = Depends(require_manager_or_service),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(AuditEventRecord).order_by(desc(AuditEventRecord.created_at)).limit(limit)
    ).all()
    return [
        {
            "request_id": row.request_id,
            "event_type": row.event_type,
            "actor_subject": row.actor_subject,
            "actor_kind": row.actor_kind,
            "actor_role": row.actor_role,
            "method": row.method,
            "path": row.path,
            "status_code": row.status_code,
            "duration_ms": row.duration_ms,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
