from __future__ import annotations

import json
from sqlalchemy.orm import Session

from .models import AuditLog


def audit(db: Session, *, actor: str | None, action: str, entity_type: str, entity_id: str | None = None, before=None, after=None) -> None:
    db.add(AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_json=json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
        after_json=json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
    ))
