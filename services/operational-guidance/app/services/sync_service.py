from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.connectors.base import MetricsConnector
from app.models import IntegrationRun, MetricSnapshot, RunStatus


def _dimension_hash(dimensions: dict) -> str:
    canonical = json.dumps(dimensions, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def sync_metrics(
    db: Session,
    connector: MetricsConnector,
    brand: str,
    entity_key: str,
    start_date: date,
    end_date: date,
) -> IntegrationRun:
    run = IntegrationRun(source=connector.source, entity_key=entity_key, status=RunStatus.started)
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        rows = connector.fetch(entity_key, start_date, end_date)
        for row in rows:
            values = {
                "source": connector.source,
                "brand": brand,
                "entity_key": entity_key,
                "metric_date": row.metric_date,
                "dimension_hash": _dimension_hash(row.dimensions),
                "dimensions": row.dimensions,
                "metrics": row.metrics,
                "raw_payload": row.raw_payload,
                "updated_at": datetime.now(UTC),
            }
            statement = insert(MetricSnapshot).values(**values)
            statement = statement.on_conflict_do_update(
                constraint="uq_metric_snapshot",
                set_={
                    "brand": statement.excluded.brand,
                    "metrics": statement.excluded.metrics,
                    "raw_payload": statement.excluded.raw_payload,
                    "updated_at": statement.excluded.updated_at,
                },
            )
            db.execute(statement)
        run.status = RunStatus.succeeded
        run.rows_written = len(rows)
        run.finished_at = datetime.now(UTC)
        run.metadata_json = {
            "brand": brand,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        db.rollback()
        run = db.get(IntegrationRun, run.id)
        if run is not None:
            run.status = RunStatus.failed
            run.error_message = str(exc)[:4000]
            run.finished_at = datetime.now(UTC)
            db.commit()
        raise
