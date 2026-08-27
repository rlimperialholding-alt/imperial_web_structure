from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db import get_session_factory, set_audit_actor
from app.models import AgentTask


def process_task(task_id: str) -> str:
    session: Session = get_session_factory()()
    try:
        task = session.get(AgentTask, uuid.UUID(task_id))
        if task is None:
            raise LookupError(f"Task not found: {task_id}")
        if task.risk_level > 3 or task.requires_approval:
            return task.status
        set_audit_actor(session, f"worker:dpm-task-{task_id}")
        task.status = "RUNNING"
        session.flush()
        task.status = "COMPLETED"
        session.commit()
        return task.status
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
