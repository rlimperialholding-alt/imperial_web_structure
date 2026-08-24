from __future__ import annotations

import signal
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from .authority_reader.client import ReaderBlocked
from .authority_reader.config import ReaderSettings
from .authority_reader.models import AuthorityCheckpoint
from .authority_reader.service import (
    process_details,
    process_enrichments,
    requalify_waiting_leads,
    run_reader,
)
from .database import SessionLocal

stopping = False


def request_stop(_signum, _frame) -> None:
    global stopping
    stopping = True


def due(db, settings: ReaderSettings) -> bool:
    checkpoint = db.get(AuthorityCheckpoint, "etdr_public")
    if not checkpoint or not checkpoint.last_success_at:
        return True
    last = checkpoint.last_success_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return datetime.now(UTC) >= last + timedelta(hours=settings.interval_hours)


def main() -> None:
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stopping:
        settings = ReaderSettings.from_env()
        if settings.enabled and settings.policy_authorized and settings.schedule_enabled:
            with SessionLocal() as db:
                if due(db, settings):
                    checkpoint = db.scalar(
                        select(AuthorityCheckpoint).where(
                            AuthorityCheckpoint.source_key == "etdr_public"
                        )
                    )
                    mode = "delta" if checkpoint and checkpoint.last_success_at else "baseline"
                    try:
                        run_reader(db, settings, mode=mode, trigger="schedule")
                    except ReaderBlocked:
                        pass
                if settings.detail_enabled:
                    try:
                        process_details(db, settings)
                        requalify_waiting_leads(db, settings)
                    except ReaderBlocked:
                        pass
                if settings.oeny_enabled:
                    try:
                        process_enrichments(db, settings)
                    except ReaderBlocked:
                        pass
        deadline = time.monotonic() + settings.poll_seconds
        while not stopping and time.monotonic() < deadline:
            time.sleep(0.2)


if __name__ == "__main__":
    main()
