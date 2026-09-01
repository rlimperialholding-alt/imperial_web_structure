from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from .models import PublishingJobRecord
from .schemas import PublicationJobIn, PublishingRetryIn
from .service import readiness, retry_job, submit_job

router = APIRouter()


def require_internal_token(
    x_internal_job_token: str | None = Header(default=None, alias="X-Internal-Job-Token"),
) -> None:
    expected = settings.internal_job_token
    if (
        not expected
        or not x_internal_job_token
        or not hmac.compare_digest(expected, x_internal_job_token)
    ):
        raise HTTPException(status_code=401, detail="invalid internal token")


@router.post(
    "/api/autonomous-publishing/jobs",
    dependencies=[Depends(require_internal_token)],
)
def submit_publication_job(
    payload: PublicationJobIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    try:
        return submit_job(db, payload).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/api/autonomous-publishing/jobs/{job_id}",
    dependencies=[Depends(require_internal_token)],
)
def publication_job_status(job_id: str, db: Session = Depends(get_db)):  # noqa: B008
    row = db.scalar(select(PublishingJobRecord).where(PublishingJobRecord.job_id == job_id))
    if not row:
        raise HTTPException(status_code=404, detail="PublicationJob not found")
    return {
        "job_id": row.job_id,
        "content_asset_id": row.content_asset_id,
        "content_version_id": row.content_version_id,
        "brand_id": row.brand_id,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "last_successful_step": row.last_successful_step,
        "last_error": row.last_error,
        "completed_at": row.completed_at,
    }


@router.post(
    "/api/autonomous-publishing/jobs/{job_id}/retry",
    dependencies=[Depends(require_internal_token)],
)
def retry_publication_job(
    job_id: str,
    payload: PublishingRetryIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    try:
        row = retry_job(db, job_id, reason=payload.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="PublicationJob not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": row.job_id, "status": row.status}


@router.get(
    "/api/autonomous-publishing/ready",
    dependencies=[Depends(require_internal_token)],
)
def publication_readiness(db: Session = Depends(get_db)):  # noqa: B008
    ready, payload = readiness(db)
    if not ready:
        return JSONResponse({"status": "not_ready", **payload}, status_code=503)
    return {"status": "ready", **payload}
