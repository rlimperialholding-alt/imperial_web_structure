from __future__ import annotations

import signal
import threading
import time
from typing import Any

from .database import SessionLocal
from .growth_ops.registry import settings
from .growth_ops.service import heartbeat, run_once

stopping = False
WORKING_HEARTBEAT_MAX_INTERVAL_SECONDS = 30.0


class WorkingHeartbeatError(RuntimeError):
    """Raised when the independent periodic worker heartbeat stops persisting."""


def _heartbeat_interval_seconds() -> float:
    return min(
        WORKING_HEARTBEAT_MAX_INTERVAL_SECONDS,
        max(5.0, float(settings().poll_seconds)),
    )


def _record_heartbeat(
    *,
    status: str,
    detail: dict[str, Any] | None = None,
) -> None:
    with SessionLocal() as db:
        heartbeat(db, status=status, detail=detail)


class _PeriodicWorkingHeartbeat:
    def __init__(self, interval_seconds: float) -> None:
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._failure: Exception | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="growth-working-heartbeat",
            daemon=True,
        )

    def start(self) -> None:
        # The first pulse is synchronous and fail-closed: no work starts unless
        # the worker can first prove that it is actively serving this cycle.
        self._write()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            # Joining before the terminal write makes it impossible for a late
            # in-flight `working` pulse to overwrite `healthy` or `degraded`.
            self._thread.join()

    def raise_if_failed(self) -> None:
        if self._failure is not None:
            raise WorkingHeartbeatError("periodic_working_heartbeat_failed") from self._failure

    def _write(self) -> None:
        _record_heartbeat(status="working", detail={"phase": "run_once"})

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                self._write()
            except Exception as exc:
                self._failure = exc
                self._stop.set()
                return


def request_stop(_signum, _frame) -> None:
    global stopping
    stopping = True


def _terminal_heartbeat(result: dict[str, Any]) -> None:
    if not settings().enabled:
        _record_heartbeat(status="disabled")
        return
    status = str(result.get("status") or "")
    if status not in {"healthy", "degraded"}:
        raise RuntimeError("invalid_growth_worker_terminal_status")
    _record_heartbeat(status=status, detail=result)


def _run_iteration() -> dict[str, Any]:
    pulse = _PeriodicWorkingHeartbeat(_heartbeat_interval_seconds())
    pulse.start()
    try:
        with SessionLocal() as db:
            result = run_once(db, write_terminal_heartbeat=False)
    finally:
        pulse.stop()
    pulse.raise_if_failed()
    _terminal_heartbeat(result)
    return result


def _run_iteration_fail_closed() -> dict[str, Any] | None:
    try:
        return _run_iteration()
    except Exception as exc:
        detail: dict[str, Any] = {"error_type": type(exc).__name__}
        if isinstance(exc, WorkingHeartbeatError) and exc.__cause__ is not None:
            detail["heartbeat_error_type"] = type(exc.__cause__).__name__
        _record_heartbeat(status="degraded", detail=detail)
        return None


def main() -> None:
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stopping:
        _run_iteration_fail_closed()
        deadline = time.monotonic() + settings().poll_seconds
        while not stopping and time.monotonic() < deadline:
            time.sleep(0.2)
    _record_heartbeat(status="stopped")


if __name__ == "__main__":
    main()
