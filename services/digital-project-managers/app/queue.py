from __future__ import annotations

import uuid

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue

from app.config import get_settings


def enqueue_task(task_id: uuid.UUID) -> bool:
    settings = get_settings()
    if not settings.queue_enabled:
        return False
    try:
        connection = Redis.from_url(settings.redis_url)
        queue = Queue("digital-project-managers", connection=connection)
        queue.enqueue(
            "app.worker.process_task",
            str(task_id),
            job_id=f"dpm-task-{task_id}",
            result_ttl=86400,
            failure_ttl=604800,
        )
        return True
    except RedisError:
        return False
