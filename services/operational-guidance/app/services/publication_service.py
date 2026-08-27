from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brand_registry import resolve_target_brand
from app.config import Settings
from app.connectors.directus import DirectusConnector
from app.connectors.website_publisher import WebsitePublisher
from app.models import PublicationJob, PublicationStatus
from app.schemas import PublicationCreate


def create_publication_job(db: Session, request: PublicationCreate) -> PublicationJob:
    job = PublicationJob(
        batch_id=request.batch_id,
        content_id=request.content_id,
        website_key=request.website_key,
        status=PublicationStatus.queued,
        request_payload=request.model_dump(mode="json"),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _finish_directus_batch(
    db: Session,
    directus: DirectusConnector,
    job: PublicationJob,
    action: str,
) -> None:
    batch_jobs = list(
        db.scalars(select(PublicationJob).where(PublicationJob.batch_id == job.batch_id)).all()
    )
    if batch_jobs and all(item.status == PublicationStatus.published for item in batch_jobs):
        if action == "unpublish":
            directus.mark_unpublished(job.content_id)
        else:
            directus.mark_published(job.content_id)


def execute_publication(db: Session, settings: Settings, job_id: str) -> PublicationJob:
    primary_key = uuid.UUID(job_id)
    job = db.get(PublicationJob, primary_key)
    if job is None:
        raise KeyError(f"Unknown publication job: {job_id}")

    job.status = PublicationStatus.publishing
    job.attempt_count += 1
    db.commit()

    try:
        directus = DirectusConnector(settings)
        content = directus.get_content(job.content_id)
        action = str(job.request_payload.get("action", "publish"))
        allowed_statuses = {"approved", "published"}
        if action == "unpublish":
            allowed_statuses.add("archived")
        if content.get("status") not in allowed_statuses:
            raise PermissionError("Only approved or published Directus content may be distributed")

        request = job.request_payload
        target_brand = resolve_target_brand(settings, job.website_key)
        content_brand = str(content.get("brand_key") or "").strip()
        if not content_brand:
            raise PermissionError("Directus content requires brand_key before publication")
        if content_brand != target_brand:
            raise PermissionError(
                f"Cross-brand publication blocked: content={content_brand}, target={target_brand}"
            )

        payload: dict[str, Any] = {
            "event_id": str(job.id),
            "action": action,
            "content_id": job.content_id,
            "brand_key": target_brand,
            "website_key": job.website_key,
            "paths": request.get("paths", []),
            "tags": request.get("tags", []),
            "content": content,
        }
        response = WebsitePublisher(settings).publish(job.website_key, payload)
        job.status = PublicationStatus.published
        job.response_payload = response
        job.published_at = datetime.now(UTC)
        job.error_message = None
        db.commit()
        db.refresh(job)
        _finish_directus_batch(db, directus, job, action)
        return job
    except Exception as exc:
        db.rollback()
        job = db.get(PublicationJob, primary_key)
        if job is not None:
            job.status = PublicationStatus.failed
            job.error_message = str(exc)[:4000]
            db.commit()
        raise
