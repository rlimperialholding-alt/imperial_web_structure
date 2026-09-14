from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()
celery = Celery(
    "imperial_intelligence",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.jobs"],
)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Budapest",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "sync-ga4-daily": {
            "task": "app.tasks.jobs.sync_all_ga4",
            "schedule": crontab(hour=3, minute=10),
        },
        "sync-search-console-daily": {
            "task": "app.tasks.jobs.sync_all_search_console",
            "schedule": crontab(hour=3, minute=35),
        },
        "sync-google-business-daily": {
            "task": "app.tasks.jobs.sync_all_google_business",
            "schedule": crontab(hour=4, minute=5),
        },
        "sync-google-business-directory": {
            "task": "app.tasks.jobs.sync_google_business_directory",
            "schedule": crontab(hour=4, minute=25),
        },
        "snapshot-ingatlan-ids": {
            "task": "app.tasks.jobs.snapshot_ingatlan_ids",
            "schedule": crontab(minute="*/30"),
        },
        "unpublish-expired-content": {
            "task": "app.tasks.jobs.unpublish_expired_content",
            "schedule": crontab(minute="*/15"),
        },
        "sync-operational-guidance": {
            "task": "app.tasks.jobs.sync_operational_guidance",
            "schedule": crontab(minute="*/15"),
        },
        "retry-operational-approvals": {
            "task": "app.tasks.jobs.retry_operational_approvals",
            "schedule": crontab(minute="*/5"),
        },
    },
)
