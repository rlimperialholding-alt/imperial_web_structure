from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ConsistencyIssue,
    EventRecord,
    ModuleInboxDelivery,
    ModuleRegistry,
    OutboxMessage,
    ProjectRegistry,
    ReleaseRecord,
    TaskRecord,
)


def dashboard_metrics(db: Session) -> dict:
    now = datetime.now(UTC)

    def is_overdue(value):
        if not value:
            return False
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value < now

    modules = db.scalars(select(ModuleRegistry)).all()
    projects = db.scalars(select(ProjectRegistry)).all()
    events = db.scalars(select(EventRecord).where(EventRecord.status == "open")).all()
    issues = db.scalars(select(ConsistencyIssue).where(ConsistencyIssue.status == "open")).all()
    tasks = db.scalars(select(TaskRecord).where(TaskRecord.status == "open")).all()
    releases = db.scalars(select(ReleaseRecord)).all()
    outbox = db.scalars(select(OutboxMessage)).all()
    inbox_received = db.scalar(select(func.count(ModuleInboxDelivery.id))) or 0
    return {
        "module_count": len(modules),
        "module_healthy": sum(1 for m in modules if m.integration_status == "healthy"),
        "project_count": len(projects),
        "blocked_projects": sum(1 for p in projects if p.blocked),
        "open_events": len(events),
        "critical_events": sum(1 for e in events if e.severity == "critical"),
        "executive_events": sum(1 for e in events if e.executive_relevance),
        "financial_impact_huf": sum(
            (Decimal(str(e.financial_impact_huf or 0)) for e in events), Decimal("0")
        ),
        "open_consistency_issues": len(issues),
        "critical_consistency_issues": sum(1 for i in issues if i.severity == "critical"),
        "open_tasks": len(tasks),
        "overdue_tasks": sum(1 for t in tasks if is_overdue(t.due_at)),
        "outbox_pending": sum(1 for o in outbox if o.status in {"pending", "retry"}),
        "outbox_delivered": sum(1 for o in outbox if o.status == "sent"),
        "inbox_received": inbox_received,
        "dead_letters": sum(1 for o in outbox if o.status == "dead_letter"),
        "production_ready_releases": sum(1 for r in releases if r.status == "production_ready"),
    }
