from __future__ import annotations

import signal
import time

from .database import SessionLocal
from .growth_ops.registry import settings
from .growth_ops.service import heartbeat, run_once

stopping = False


def request_stop(_signum, _frame) -> None:
    global stopping
    stopping = True


def main() -> None:
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stopping:
        try:
            with SessionLocal() as db:
                run_once(db)
        except Exception as exc:
            with SessionLocal() as db:
                heartbeat(db, status="degraded", detail={"error_type": type(exc).__name__})
        deadline = time.monotonic() + settings().poll_seconds
        while not stopping and time.monotonic() < deadline:
            time.sleep(0.2)
    with SessionLocal() as db:
        heartbeat(db, status="stopped")


if __name__ == "__main__":
    main()
