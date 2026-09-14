from __future__ import annotations

import os
import time

from .config import settings
from .database import Base, SessionLocal, engine
from .seed import seed_database
from .services.consistency import scan_consistency
from .services.content_image_factory import process_content_image_factory
from .services.house_designer_adapters import dispatch_adapter_jobs
from .services.integration import process_outbox
from .services.market_intelligence import process_public_capture_jobs


def initialize() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)


def run_once(*, run_consistency: bool = False) -> dict[str, int]:
    with SessionLocal() as db:
        if run_consistency:
            scan_consistency(db, actor="worker")
        outbox = process_outbox(db)
        adapters = dispatch_adapter_jobs(db)
        market_capture = process_public_capture_jobs(
            db, connector_enabled=settings.market_public_fetch_enabled
        )
        content_images = process_content_image_factory(db)
        return {
            **outbox,
            **{f"house_designer_{key}": value for key, value in adapters.items()},
            **{f"market_capture_{key}": value for key, value in market_capture.items()},
            **{f"content_image_factory_{key}": value for key, value in content_images.items()},
        }


def main() -> None:
    interval = max(5, int(os.getenv("CONTROL_CENTER_WORKER_INTERVAL_SECONDS", "15")))
    consistency_interval = max(
        60, int(os.getenv("CONTROL_CENTER_CONSISTENCY_INTERVAL_SECONDS", "3600"))
    )
    initialize()
    next_consistency = 0.0
    while True:
        now = time.monotonic()
        run_once(run_consistency=now >= next_consistency)
        if now >= next_consistency:
            next_consistency = now + consistency_interval
        time.sleep(interval)


if __name__ == "__main__":
    main()
