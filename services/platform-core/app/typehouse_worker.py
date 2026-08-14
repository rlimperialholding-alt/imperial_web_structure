from __future__ import annotations

import logging
import os
import signal
import time

from .config import settings
from .database import SessionLocal
from .services.typehouse_factory import dispatch_and_claim, process_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("typehouse-factory-worker")
stopping = False


def _stop(signum: int, frame: object) -> None:
    del signum, frame
    global stopping
    stopping = True


def run() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker_id = f"typehouse-{os.getpid()}"
    logger.info(
        "HouseVision Typehouse Factory worker started "
        "worker_id=%s concurrency=1 processing_enabled=%s",
        worker_id,
        settings.typehouse_factory_processing_enabled,
    )
    while not stopping:
        if not settings.typehouse_factory_processing_enabled:
            time.sleep(min(30, settings.typehouse_factory_worker_poll_seconds))
            continue
        claim: tuple[str, int] | None = None
        try:
            with SessionLocal() as db:
                claim = dispatch_and_claim(db, worker_id)
            if claim:
                job_id, fencing_token = claim
                with SessionLocal() as db:
                    process_job(db, job_id, worker_id, fencing_token)
            else:
                time.sleep(settings.typehouse_factory_worker_poll_seconds)
        except Exception:
            logger.exception("Typehouse worker cycle failed claim=%s", claim)
            time.sleep(settings.typehouse_factory_worker_poll_seconds)
    logger.info("HouseVision Typehouse Factory worker stopped")


if __name__ == "__main__":
    run()
