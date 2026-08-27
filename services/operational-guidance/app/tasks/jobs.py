from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.connectors.directus import DirectusConnector
from app.connectors.ga4 import GA4Connector
from app.connectors.google_business import GoogleBusinessProfileConnector
from app.connectors.search_console import SearchConsoleConnector
from app.db import SessionLocal
from app.models import PublicationJob, PublicationStatus
from app.schemas import PublicationCreate
from app.services.business_profile_service import sync_business_profile_directory
from app.services.ingatlan_service import sync_listing_ids
from app.services.publication_service import create_publication_job, execute_publication
from app.services.sync_service import sync_metrics
from app.tasks.celery_app import celery


def _sync_configured(
    config: list[dict[str, str]],
    key: str,
    connector: Any,
    days: int,
) -> list[str]:
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=days - 1)
    run_ids: list[str] = []
    with SessionLocal() as db:
        for item in config:
            entity_key = item.get(key)
            if not entity_key:
                continue
            run = sync_metrics(
                db,
                connector=connector,
                brand=item.get("brand", "unknown"),
                entity_key=entity_key,
                start_date=start_date,
                end_date=end_date,
            )
            run_ids.append(str(run.id))
    return run_ids


@celery.task(
    name="app.tasks.jobs.execute_publication_job",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def execute_publication_job(job_id: str) -> str:
    settings = get_settings()
    with SessionLocal() as db:
        job = execute_publication(db, settings, job_id)
        return str(job.id)


@celery.task(name="app.tasks.jobs.sync_all_ga4")
def sync_all_ga4() -> list[str]:
    settings = get_settings()
    return _sync_configured(
        settings.ga4_properties_json, "property_id", GA4Connector(settings), days=3
    )


@celery.task(name="app.tasks.jobs.sync_all_search_console")
def sync_all_search_console() -> list[str]:
    settings = get_settings()
    return _sync_configured(
        settings.search_console_sites_json,
        "site_url",
        SearchConsoleConnector(settings),
        days=7,
    )


@celery.task(name="app.tasks.jobs.sync_all_google_business")
def sync_all_google_business() -> list[str]:
    settings = get_settings()
    return _sync_configured(
        settings.gbp_locations_json,
        "location_id",
        GoogleBusinessProfileConnector(settings),
        days=7,
    )


@celery.task(name="app.tasks.jobs.sync_google_business_directory")
def sync_google_business_directory() -> dict[str, int]:
    settings = get_settings()
    with SessionLocal() as db:
        return sync_business_profile_directory(db, settings)


@celery.task(name="app.tasks.jobs.snapshot_ingatlan_ids")
def snapshot_ingatlan_ids() -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.ingatlan_username:
        return []
    with SessionLocal() as db:
        return sync_listing_ids(db, settings)


@celery.task(name="app.tasks.jobs.unpublish_expired_content")
def unpublish_expired_content() -> list[str]:
    settings = get_settings()
    directus = DirectusConnector(settings)
    now = datetime.now(UTC)
    content_items = directus.list_expired_content(now)
    created_jobs: list[str] = []

    with SessionLocal() as db:
        for content in content_items:
            content_id = str(content["id"])
            existing = db.scalar(
                select(PublicationJob.id).where(
                    PublicationJob.content_id == content_id,
                    PublicationJob.status.in_(
                        [PublicationStatus.queued, PublicationStatus.publishing]
                    ),
                    PublicationJob.request_payload["action"].as_string() == "unpublish",
                )
            )
            if existing:
                continue

            batch_id = uuid.uuid4()
            website_keys = content.get("website_keys") or []
            if isinstance(website_keys, str):
                website_keys = [website_keys]
            jobs: list[PublicationJob] = []
            for website_key in website_keys:
                job = create_publication_job(
                    db,
                    PublicationCreate(
                        batch_id=batch_id,
                        content_id=content_id,
                        website_key=str(website_key),
                        action="unpublish",
                        paths=content.get("paths") or [],
                        tags=content.get("tags") or [],
                    ),
                )
                jobs.append(job)
                created_jobs.append(str(job.id))

            for job in jobs:
                execute_publication(db, settings, str(job.id))

    return created_jobs

@celery.task(name="app.tasks.jobs.sync_operational_guidance")
def sync_operational_guidance() -> dict[str, Any]:
    """Safety-net sync: import Directus rules and regenerate only affected bundles."""
    from app.operations.factory import build_operational_services
    from app.process_cards.adapters import DirectusOperationalCatalogAdapter

    settings = get_settings()
    token = settings.directus_static_token.get_secret_value()
    if not token:
        return {"skipped": True, "reason": "DIRECTUS_STATIC_TOKEN is empty"}
    operations = build_operational_services(settings)
    adapter = DirectusOperationalCatalogAdapter(
        settings.directus_url,
        token,
        settings.process_catalog_collection,
        settings.checklist_template_collection,
    )
    imported = operations.process_cards.import_catalog(
        adapter.fetch_catalog(), persist=False
    )
    changed = operations.process_cards.regenerate_changed()
    return {
        "skipped": False,
        "imported": imported,
        "regenerated": len(changed),
        "process_keys": [item["card"]["process_key"] for item in changed],
    }


@celery.task(name="app.tasks.jobs.retry_operational_approvals")
def retry_operational_approvals() -> dict[str, Any]:
    """Retry failed or still-pending approval notifications from the shared queue."""
    from app.operations.factory import build_operational_services

    operations = build_operational_services(get_settings())
    retried = operations.process_cards.resend_pending_approvals()
    return {"retried": len(retried), "items": retried}
