from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from app import growth_worker


class _SessionContext:
    def __init__(self, session_id: int) -> None:
        self.session = SimpleNamespace(session_id=session_id)

    def __enter__(self):
        return self.session

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        return None


class _SessionFactory:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_id = 0

    def __call__(self) -> _SessionContext:
        with self._lock:
            self._next_id += 1
            session_id = self._next_id
        return _SessionContext(session_id)


def _worker_settings(*, enabled: bool = True):
    return SimpleNamespace(enabled=enabled, poll_seconds=5)


def test_periodic_working_heartbeat_uses_independent_sessions_and_cannot_win_terminal_race(
    monkeypatch,
):
    sessions = _SessionFactory()
    calls: list[tuple[int, str, dict | None]] = []
    calls_lock = threading.Lock()
    in_flight_pulse = threading.Event()
    release_pulse = threading.Event()
    working_count = 0
    run_session_id: int | None = None

    monkeypatch.setattr(growth_worker, "SessionLocal", sessions)
    monkeypatch.setattr(growth_worker, "settings", _worker_settings)
    monkeypatch.setattr(growth_worker, "_heartbeat_interval_seconds", lambda: 0.01)

    def fake_heartbeat(db, *, status, detail=None):
        nonlocal working_count
        if status == "working":
            working_count += 1
            if working_count == 2:
                in_flight_pulse.set()
                assert release_pulse.wait(timeout=1)
        with calls_lock:
            calls.append((db.session_id, status, detail))

    def fake_run_once(db, *, write_terminal_heartbeat=True):
        nonlocal run_session_id
        run_session_id = db.session_id
        assert write_terminal_heartbeat is False
        assert in_flight_pulse.wait(timeout=1)
        threading.Timer(0.02, release_pulse.set).start()
        return {"status": "healthy", "sent": 0}

    monkeypatch.setattr(growth_worker, "heartbeat", fake_heartbeat)
    monkeypatch.setattr(growth_worker, "run_once", fake_run_once)

    result = growth_worker._run_iteration_fail_closed()

    assert result == {"status": "healthy", "sent": 0}
    assert calls[-1][1:] == ("healthy", result)
    assert run_session_id is not None
    assert all(session_id != run_session_id for session_id, _status, _detail in calls)
    assert len({session_id for session_id, _status, _detail in calls}) == len(calls)
    call_count = len(calls)
    time.sleep(0.03)
    assert len(calls) == call_count


def test_periodic_heartbeat_failure_finishes_degraded_and_never_healthy(monkeypatch):
    sessions = _SessionFactory()
    calls: list[tuple[str, dict | None]] = []
    failed_pulse = threading.Event()
    working_count = 0

    monkeypatch.setattr(growth_worker, "SessionLocal", sessions)
    monkeypatch.setattr(growth_worker, "settings", _worker_settings)
    monkeypatch.setattr(growth_worker, "_heartbeat_interval_seconds", lambda: 0.01)

    def fake_heartbeat(_db, *, status, detail=None):
        nonlocal working_count
        if status == "working":
            working_count += 1
            if working_count == 2:
                failed_pulse.set()
                raise OSError("synthetic heartbeat database failure")
        calls.append((status, detail))

    def fake_run_once(_db, *, write_terminal_heartbeat=True):
        assert write_terminal_heartbeat is False
        assert failed_pulse.wait(timeout=1)
        return {"status": "healthy", "sent": 0}

    monkeypatch.setattr(growth_worker, "heartbeat", fake_heartbeat)
    monkeypatch.setattr(growth_worker, "run_once", fake_run_once)

    result = growth_worker._run_iteration_fail_closed()

    assert result is None
    assert all(status != "healthy" for status, _detail in calls)
    assert calls[-1] == (
        "degraded",
        {
            "error_type": "WorkingHeartbeatError",
            "heartbeat_error_type": "OSError",
        },
    )


def test_run_failure_stops_pulse_before_degraded_terminal_heartbeat(monkeypatch):
    sessions = _SessionFactory()
    statuses: list[str] = []

    monkeypatch.setattr(growth_worker, "SessionLocal", sessions)
    monkeypatch.setattr(growth_worker, "settings", _worker_settings)
    monkeypatch.setattr(growth_worker, "_heartbeat_interval_seconds", lambda: 0.01)

    def fake_heartbeat(_db, *, status, detail=None):
        del detail
        statuses.append(status)

    def fake_run_once(_db, *, write_terminal_heartbeat=True):
        assert write_terminal_heartbeat is False
        raise ValueError("synthetic run failure")

    monkeypatch.setattr(growth_worker, "heartbeat", fake_heartbeat)
    monkeypatch.setattr(growth_worker, "run_once", fake_run_once)

    result = growth_worker._run_iteration_fail_closed()

    assert result is None
    assert statuses[-1] == "degraded"
    status_count = len(statuses)
    time.sleep(0.03)
    assert len(statuses) == status_count


def test_main_preserves_graceful_stop_and_records_stopped_after_iteration(monkeypatch):
    sessions = _SessionFactory()
    statuses: list[str] = []

    def stop_after_iteration(_db, *, write_terminal_heartbeat=True):
        assert write_terminal_heartbeat is False
        growth_worker.stopping = True
        return {"status": "healthy"}

    monkeypatch.setattr(growth_worker.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(growth_worker, "SessionLocal", sessions)
    monkeypatch.setattr(growth_worker, "settings", _worker_settings)
    monkeypatch.setattr(growth_worker, "_heartbeat_interval_seconds", lambda: 0.01)
    monkeypatch.setattr(growth_worker, "run_once", stop_after_iteration)
    monkeypatch.setattr(
        growth_worker,
        "heartbeat",
        lambda _db, *, status, detail=None: statuses.append(status),
    )
    growth_worker.stopping = False
    try:
        growth_worker.main()
    finally:
        growth_worker.stopping = False

    assert statuses == ["working", "healthy", "stopped"]
    status_count = len(statuses)
    time.sleep(0.03)
    assert len(statuses) == status_count
