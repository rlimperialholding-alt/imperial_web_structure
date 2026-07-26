from __future__ import annotations

import os
import time

from .database import Base, SessionLocal, engine
from .seed import seed_database
from .services.consistency import scan_consistency
from .services.integration import process_outbox


def run_once() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
        scan_consistency(db, actor="worker")
        process_outbox(db, simulate_success=False)


def main() -> None:
    interval = max(3600, int(os.getenv("CONTROL_CENTER_WORKER_INTERVAL_SECONDS", "3600")))
    while True:
        run_once()
        time.sleep(interval)


if __name__ == "__main__":
    main()
