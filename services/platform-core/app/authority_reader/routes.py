from __future__ import annotations

import hmac
from datetime import UTC
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from .client import ReaderBlocked
from .config import ReaderSettings
from .models import AuthorityReaderRun, AuthorityRecord, AuthorityRecordRevision
from .service import process_enrichments, readiness, run_reader, run_summary

router = APIRouter()


def current_settings() -> ReaderSettings:
    return ReaderSettings.from_env()


def require_token(
    x_internal_job_token: Annotated[str | None, Header(alias="X-Internal-Job-Token")] = None,
    settings: ReaderSettings = Depends(current_settings),  # noqa: B008
) -> None:
    if (
        len(settings.internal_token) < 32
        or not x_internal_job_token
        or not hmac.compare_digest(settings.internal_token, x_internal_job_token)
    ):
        raise HTTPException(status_code=401, detail="invalid internal token")


class RunRequest(BaseModel):
    mode: Literal["baseline", "delta", "pilot"] = "delta"
    town: str | None = Field(default=None, min_length=2, max_length=200)
    max_pages: int | None = Field(default=None, ge=1, le=20_000)


@router.get("/api/internal/authority-reader/readiness", dependencies=[Depends(require_token)])
def reader_readiness(
    db: Session = Depends(get_db),  # noqa: B008
    settings: ReaderSettings = Depends(current_settings),  # noqa: B008
):
    ready, detail = readiness(db, settings)
    if not ready:
        raise HTTPException(status_code=503, detail=detail)
    return {"status": "ready", **detail}


@router.post("/api/internal/authority-reader/runs", dependencies=[Depends(require_token)])
def create_run(
    data: RunRequest,
    db: Session = Depends(get_db),  # noqa: B008
    settings: ReaderSettings = Depends(current_settings),  # noqa: B008
):
    try:
        row = run_reader(
            db,
            settings,
            mode=data.mode,
            town=data.town,
            max_pages=data.max_pages,
            trigger="api",
        )
    except ReaderBlocked as exc:
        status = 409 if exc.code == "active_lease" else 503
        raise HTTPException(status_code=status, detail={"code": exc.code}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
    return run_summary(row)


@router.post(
    "/api/internal/authority-reader/enrichments/run", dependencies=[Depends(require_token)]
)
def run_enrichments(
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    db: Session = Depends(get_db),  # noqa: B008
    settings: ReaderSettings = Depends(current_settings),  # noqa: B008
):
    try:
        return process_enrichments(db, settings, limit=limit)
    except ReaderBlocked as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code}) from exc


@router.get("/api/internal/authority-reader/runs", dependencies=[Depends(require_token)])
def list_runs(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    db: Session = Depends(get_db),  # noqa: B008
):
    rows = db.scalars(
        select(AuthorityReaderRun).order_by(desc(AuthorityReaderRun.started_at)).limit(limit)
    ).all()
    return {"items": [run_summary(row) for row in rows]}


@router.get("/api/internal/authority-reader/runs/{run_id}", dependencies=[Depends(require_token)])
def get_run(run_id: str, db: Session = Depends(get_db)):  # noqa: B008
    row = db.scalar(select(AuthorityReaderRun).where(AuthorityReaderRun.run_id == run_id))
    if not row:
        raise HTTPException(status_code=404, detail="run not found")
    return run_summary(row)


@router.get("/api/internal/authority-reader/records", dependencies=[Depends(require_token)])
def list_records(
    city: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    db: Session = Depends(get_db),  # noqa: B008
):
    statement = select(AuthorityRecord).order_by(desc(AuthorityRecord.submission_date))
    if city:
        statement = statement.where(AuthorityRecord.city == city)
    rows = db.scalars(statement.limit(limit)).all()
    return {
        "items": [
            {
                "record_id": row.record_id,
                "process_number": row.public_process_number,
                "city": row.city,
                "topographical_number": row.topographical_number,
                "procedure_type": row.procedure_type,
                "construction_activity": row.construction_activity,
                "submission_date": row.submission_date,
                "evidence_url": row.evidence_url,
                "revision_no": row.current_revision_no,
                "status": row.status,
            }
            for row in rows
        ]
    }


@router.get(
    "/api/internal/authority-reader/records/{record_id}/revisions",
    dependencies=[Depends(require_token)],
)
def list_revisions(record_id: str, db: Session = Depends(get_db)):  # noqa: B008
    if not db.scalar(select(AuthorityRecord.id).where(AuthorityRecord.record_id == record_id)):
        raise HTTPException(status_code=404, detail="record not found")
    rows = db.scalars(
        select(AuthorityRecordRevision)
        .where(AuthorityRecordRevision.record_id == record_id)
        .order_by(AuthorityRecordRevision.revision_no)
    ).all()
    return {
        "items": [
            {
                "revision_id": row.revision_id,
                "revision_no": row.revision_no,
                "payload_sha256": row.payload_sha256,
                "observed_at": row.observed_at,
            }
            for row in rows
        ]
    }


def dashboard_data(db: Session) -> dict[str, object]:
    latest = db.scalar(select(AuthorityReaderRun).order_by(desc(AuthorityReaderRun.started_at)))
    return {
        "records": db.scalar(select(func.count()).select_from(AuthorityRecord)) or 0,
        "latest": run_summary(latest) if latest else None,
        "generated_at": __import__("datetime").datetime.now(UTC),
    }
