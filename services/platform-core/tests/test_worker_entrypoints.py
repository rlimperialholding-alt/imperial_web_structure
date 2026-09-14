"""Worker/queue belépési pontok és fail-closed ciklusok determinisztikus tesztjei.

Minden teszt hálózatmentes és időzítő-független: a ``time.sleep`` és a
``SessionLocal`` szintetikus fake-kel van cserélve, így a végtelen worker-
ciklusok pontosan egy-két iteráció alatt, determinisztikusan leállnak.
A ciklusok hibakezelését (fail-closed: kivétel esetén a ciklus nem hal meg,
a szívverés degraded/stopped státuszt kap) szintén itt bizonyítjuk.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import app.typehouse_worker as typehouse_worker
import app.worker as control_worker
from app import growth_worker, publishing_worker


class _FakeSession:
    """Kontextuskezelőként használható fake DB-munkamenet."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _stop_sleep(module: object, counter: dict[str, int] | None = None) -> object:
    """Alvás-helyettesítő: az első hívás leállítja a modul hurkát."""

    def fake_sleep(seconds: float) -> None:
        if counter is not None:
            counter["n"] += 1
        module.stopping = True

    return fake_sleep


class TestControlCenterWorker:

    def test_run_once_merges_all_processor_results(self, monkeypatch) -> None:
        monkeypatch.setattr(control_worker, "SessionLocal", _FakeSession)
        monkeypatch.setattr(
            control_worker, "scan_consistency", lambda db, actor: db.calls.append(actor)
        )
        monkeypatch.setattr(control_worker, "process_outbox", lambda db: {"outbox_done": 1})
        monkeypatch.setattr(
            control_worker, "dispatch_adapter_jobs", lambda db: {"adapters": 2}
        )
        monkeypatch.setattr(
            control_worker,
            "process_public_capture_jobs",
            lambda db, connector_enabled: {"captured": 3},
        )
        monkeypatch.setattr(
            control_worker, "process_content_image_factory", lambda db: {"images": 4}
        )
        result = control_worker.run_once()
        assert result == {
            "outbox_done": 1,
            "house_designer_adapters": 2,
            "market_capture_captured": 3,
            "content_image_factory_images": 4,
        }


    def test_main_initializes_then_runs_cycle(self, monkeypatch) -> None:
        state = {"initialized": False, "cycles": 0}
        monkeypatch.setattr(control_worker, "initialize", lambda: state.update(initialized=True))

        def cycle_run_once(**kwargs: object) -> dict[str, int]:
            state["cycles"] += 1
            raise KeyboardInterrupt

        monkeypatch.setattr(control_worker, "run_once", cycle_run_once)
        with pytest.raises(KeyboardInterrupt):
            control_worker.main()
        assert state == {"initialized": True, "cycles": 1}



class TestTypehouseWorker:
    def _settings(self, processing_enabled: bool = True) -> SimpleNamespace:
        return SimpleNamespace(
            typehouse_factory_processing_enabled=processing_enabled,
            typehouse_factory_worker_poll_seconds=1,
        )

    def _signal(self) -> SimpleNamespace:
        return SimpleNamespace(SIGTERM=15, SIGINT=2, signal=lambda *args: None)

    def test_claims_job_processes_it_and_stops(self, monkeypatch) -> None:
        iterations = {"n": 0}
        claimed = {"done": False}
        processed: list[tuple[str, str, int]] = []

        def dispatch_and_claim(db, worker_id: str) -> tuple[str, int] | None:
            if not claimed["done"]:
                claimed["done"] = True
                return ("TYPEHOUSE-JOB-1", 7)
            return None

        monkeypatch.setattr(typehouse_worker, "settings", self._settings())
        monkeypatch.setattr(typehouse_worker, "SessionLocal", _FakeSession)
        monkeypatch.setattr(
            typehouse_worker,
            "dispatch_and_claim",
            dispatch_and_claim,
        )
        monkeypatch.setattr(
            typehouse_worker,
            "process_job",
            lambda db, job_id, worker_id, claimed: processed.append((job_id, worker_id, claimed)),
        )
        monkeypatch.setattr(typehouse_worker, "signal", self._signal())
        monkeypatch.setattr(typehouse_worker.time, "sleep", _stop_sleep(typehouse_worker, iterations))
        typehouse_worker.stopping = False
        typehouse_worker.run()
        assert processed == [("TYPEHOUSE-JOB-1", f"typehouse-{os.getpid()}", 7)]

    def test_processing_disabled_idles(self, monkeypatch) -> None:
        monkeypatch.setattr(typehouse_worker, "settings", self._settings(False))
        monkeypatch.setattr(typehouse_worker, "SessionLocal", _FakeSession)
        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            typehouse_worker.stopping = True

        monkeypatch.setattr(typehouse_worker.time, "sleep", fake_sleep)
        monkeypatch.setattr(typehouse_worker, "signal", self._signal())
        typehouse_worker.stopping = False
        typehouse_worker.run()
        assert sleeps == [1.0]  # min(30, poll_seconds) várakozás, kérés nélkül

    def test_failed_cycle_is_fail_closed_and_loop_survives(self, monkeypatch) -> None:
        iterations = {"n": 0}
        monkeypatch.setattr(typehouse_worker, "settings", self._settings())
        monkeypatch.setattr(typehouse_worker, "SessionLocal", _FakeSession)
        monkeypatch.setattr(
            typehouse_worker,
            "dispatch_and_claim",
            lambda db, worker_id: (_ for _ in ()).throw(RuntimeError("adatbázis hiba")),
        )
        logged: list[tuple[str, tuple]] = []
        monkeypatch.setattr(
            typehouse_worker,
            "logger",
            SimpleNamespace(
                info=lambda *a, **k: None,
                exception=lambda message, *a, **k: logged.append((message, a)),
            ),
        )

        monkeypatch.setattr(typehouse_worker.time, "sleep", _stop_sleep(typehouse_worker, iterations))
        monkeypatch.setattr(typehouse_worker, "signal", self._signal())
        typehouse_worker.stopping = False
        typehouse_worker.run()
        assert iterations["n"] == 1
        assert logged == [("Typehouse worker cycle failed claim=%s", (None,))]



class _HeartbeatLoopTestBase:
    """Publishing/growth worker közös hurok-ellenőrzése."""

    module = publishing_worker
    settings_factory: object = None

    def _run_loop(self, monkeypatch, *, run_once_exc: BaseException | None = None) -> dict:
        heartbeats: list[dict] = []
        ran = {"n": 0}
        monkeypatch.setattr(self.module, "SessionLocal", _FakeSession)

        def fake_run_once(db) -> None:
            ran["n"] += 1
            if run_once_exc is not None:
                raise run_once_exc

        monkeypatch.setattr(self.module, "run_once", fake_run_once)
        monkeypatch.setattr(
            self.module,
            "heartbeat",
            lambda db, **kwargs: heartbeats.append(kwargs),
        )
        monkeypatch.setattr(self.module, "signal", SimpleNamespace(SIGTERM=15, SIGINT=2, signal=lambda *a: None))
        monkeypatch.setattr(
            self.module,
            "time",
            SimpleNamespace(
                monotonic=lambda: float(ran["n"]),
                sleep=lambda seconds: setattr(self.module, "stopping", True),
            ),
        )
        monkeypatch.setattr(self.module, "settings", self.settings_factory)
        self.module.stopping = False
        self.module.main()
        return {"ran": ran["n"], "heartbeats": heartbeats}


class TestPublishingWorker(_HeartbeatLoopTestBase):
    module = publishing_worker
    settings_factory = SimpleNamespace(autonomous_publishing_poll_seconds=1)




    module = growth_worker

    @staticmethod
    def settings_factory() -> SimpleNamespace:
        return SimpleNamespace(poll_seconds=1)


    def test_failed_cycle_reports_degraded_heartbeat(self, monkeypatch) -> None:
        result = self._run_loop(monkeypatch, run_once_exc=ValueError("növekedési hiba"))
        assert result["ran"] == 1
        assert result["heartbeats"] == [
            {"status": "degraded", "detail": {"error_type": "ValueError"}},
            {"status": "stopped"},
        ]
