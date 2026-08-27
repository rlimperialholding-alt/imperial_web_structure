from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.connectors.directus import DirectusConnector
from app.db import SessionLocal, get_db
from app.models import PublicationJob
from app.schemas import DirectusWebhookEvent, PublicationCreate, PublicationRead
from app.security import require_admin_token
from app.services.publication_service import create_publication_job, execute_publication

router = APIRouter(prefix="/publications", tags=["publications"])


def _execute_in_new_session(job_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        execute_publication(db, settings, job_id)


def _dispatch_job(
    job: PublicationJob,
    publish_at: datetime | None,
    background_tasks: BackgroundTasks,
) -> None:
    if publish_at and publish_at > datetime.now(UTC):
        from app.tasks.jobs import execute_publication_job

        execute_publication_job.apply_async(args=[str(job.id)], eta=publish_at)
        return
    background_tasks.add_task(_execute_in_new_session, str(job.id))


def _read(job: PublicationJob) -> PublicationRead:
    return PublicationRead(
        id=job.id,
        batch_id=job.batch_id,
        content_id=job.content_id,
        website_key=job.website_key,
        status=job.status.value,
        attempt_count=job.attempt_count,
        error_message=job.error_message,
        response_payload=job.response_payload,
    )


@router.post(
    "",
    response_model=PublicationRead,
    dependencies=[Depends(require_admin_token)],
)
def publish(
    request: PublicationCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> PublicationRead:
    job = create_publication_job(db, request)
    _dispatch_job(job, request.publish_at, background_tasks)
    return _read(job)


@router.get(
    "/{job_id}",
    response_model=PublicationRead,
    dependencies=[Depends(require_admin_token)],
)
def get_publication(job_id: uuid.UUID, db: Session = Depends(get_db)) -> PublicationRead:
    job = db.get(PublicationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Publication job not found")
    return _read(job)


@router.post("/webhooks/directus", status_code=202)
def directus_webhook(
    event: DirectusWebhookEvent,
    background_tasks: BackgroundTasks,
    x_directus_secret: str = Header(default=""),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, int | bool]:
    expected = settings.directus_webhook_secret.get_secret_value()
    if not expected or not hmac.compare_digest(expected, x_directus_secret):
        raise HTTPException(status_code=401, detail="Invalid Directus webhook secret")
    if event.collection != settings.directus_content_collection:
        return {"accepted": True, "jobs_created": 0}
    if event.payload.get("status") != "approved":
        return {"accepted": True, "jobs_created": 0}

    directus = DirectusConnector(settings)
    batch_id = uuid.uuid4()
    count = 0
    for content_id in event.keys:
        content = directus.get_content(str(content_id))
        if content.get("status") != "approved":
            continue
        website_keys = content.get("website_keys", [])
        if isinstance(website_keys, str):
            website_keys = [website_keys]
        for website_key in website_keys:
            request = PublicationCreate(
                batch_id=batch_id,
                content_id=str(content_id),
                website_key=str(website_key),
                paths=content.get("paths") or [],
                tags=content.get("tags") or [],
                publish_at=content.get("valid_from"),
            )
            job = create_publication_job(db, request)
            _dispatch_job(job, request.publish_at, background_tasks)
            count += 1
    return {"accepted": True, "jobs_created": count}
