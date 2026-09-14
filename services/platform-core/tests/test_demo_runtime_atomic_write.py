"""Focused regression for the Windows demo-runtime atomic-replacement race.

Gate 6 (BUSINESS_ASSURANCE) failed once on Windows with
``PermissionError: [WinError 5]`` while ``demo_runtime._write`` replaced a
unique temporary JSON file over ``data/platform_demo_runtime.json``. On
Windows, ``os.replace`` requires DELETE sharing on the target: a transient
external holder (antivirus real-time scan, search indexer, or file-sync
agent) opens the target without ``FILE_SHARE_DELETE`` for a few
milliseconds, and the rename fails with WinError 5 even though the process
owns the file and nothing is permanently wrong.

In-process concurrency cannot produce the denial alone because
``DemoRuntime`` serializes every read and write on a reentrant lock; the
holder has to be another process or a short-lived external scanner. The
remediation is therefore a bounded retry of the *same* atomic rename while
the transient holder releases, never a fallback to a non-atomic partial
write. Only the explicit allowlist of transient Windows replacement errors
(``winerror`` 5/32/33) is retried, only on Windows; every other
PermissionError/OSError is raised on the first attempt without sleeping.

Because the retry gate is platform-specific, the platform-dependent cases
below simulate the platform through the narrow module-local seam
``demo_runtime._is_windows`` (see :func:`_simulate_platform`). The global
``os.name`` attribute is never mutated, so ``pathlib``, pytest and every
other importer of ``os`` keep observing the real host, and the tests are
deterministic on Windows and non-Windows hosts alike.

These tests prove, deterministically and on every host:

1. an allowlisted transient denial is retried and the atomic write
   completes (Windows simulated);
2. a permanent permission error (no winerror, or a non-allowlisted
   winerror) is raised on the first attempt with no retry delay, and a
   persistent denial still fails closed: the original PermissionError
   propagates, the previous target content stays byte-identical, and no
   owned temporary file is left behind;
3. exhausted transient retries re-raise the original error after exactly
   the bounded delays and still clean up every owned temporary file
   (Windows simulated);
4. the allowlisted winerror is never retried outside Windows (non-Windows
   simulated);
5. the platform seam is production-neutral: unpatched it is exactly
   ``os.name == "nt"``, and simulating it never mutates global ``os.name``;
6. the real Windows share-mode mechanism (a held target without
   FILE_SHARE_DELETE) blocks replacement and recovers once released;
7. concurrent writers on one runtime instance stay serialized and the file
   is always complete JSON;
8. an ambient ``DEMO_RUNTIME_PATH`` cannot redirect test isolation, and the
   suite-level runtime path stays inside the pytest temporary root.

All fixtures use synthetic copies under the pytest temporary directory; the
repository runtime data is never touched.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import app.demo_runtime as demo_runtime
import pytest
from app.demo_runtime import DemoRuntime
from demo_runtime_path_isolation import (
    isolate_demo_runtime_path,
    restore_demo_runtime_path,
)


def _runtime(tmp_path: Path) -> DemoRuntime:
    runtime = DemoRuntime(runtime_path=tmp_path / "platform_demo_runtime.json")
    runtime.reset()
    return runtime


def _state_bytes(runtime: DemoRuntime) -> bytes:
    return runtime.runtime_path.read_bytes()


def _transient_windows_permission_error() -> PermissionError:
    """The observed Gate 6 race: PermissionError with winerror 5."""
    error = PermissionError(13, "Access is denied", "source", "target")
    error.winerror = 5
    return error


def _permission_error_with_winerror(winerror: int) -> PermissionError:
    error = PermissionError(13, "Permission denied", "source", "target")
    error.winerror = winerror
    return error


def _simulate_platform(monkeypatch: pytest.MonkeyPatch, *, windows: bool) -> None:
    """Deterministically simulate the platform for the retry gate.

    Only the module-local seam ``demo_runtime._is_windows`` is replaced, so
    the simulation is confined to the module under test and reverted by
    ``monkeypatch`` at teardown. Global ``os.name`` is deliberately left
    untouched: mutating it would also change ``pathlib``, pytest, and every
    other module that reads ``os.name``.
    """
    monkeypatch.setattr(demo_runtime, "_is_windows", lambda: windows)


def test_transient_replace_denial_is_retried_and_write_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path)
    real_replace = os.replace
    denials = 0

    def flaky_replace(source, target):
        nonlocal denials
        if Path(target) == runtime.runtime_path and denials < 2:
            denials += 1
            raise _transient_windows_permission_error()
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", flaky_replace)
    monkeypatch.setattr(time, "sleep", lambda _: None)  # keep the test instant
    # The injected winerror 5 is only retryable on Windows, so the platform
    # is simulated explicitly instead of depending on the host.
    _simulate_platform(monkeypatch, windows=True)

    result = runtime.execute_action(
        module_id="crm",
        action_id="qualify_lead",
        project_id="PRJ-TRANSIENT",
        actor="transient@example.test",
        idempotency_key="IDEMP-TRANSIENT-1",
    )

    assert denials == 2, "both injected transient denials were retried"
    assert result["duplicate"] is False
    state = json.loads(_state_bytes(runtime))
    assert state["events"][0]["id"] == result["event"]["id"]
    assert state["events"][0]["projectId"] == "PRJ-TRANSIENT"
    assert state["idempotency"][0]["key"] == "IDEMP-TRANSIENT-1"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_persistent_replace_denial_fails_closed_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path)
    before = _state_bytes(runtime)
    replace_calls = 0
    sleep_delays: list[float] = []

    def always_denied(source, target):
        nonlocal replace_calls
        replace_calls += 1
        if Path(target) == runtime.runtime_path:
            raise PermissionError(13, "Access is denied", str(source), str(target))
        raise AssertionError("replace was called for an unexpected target")

    monkeypatch.setattr(os, "replace", always_denied)
    monkeypatch.setattr(time, "sleep", sleep_delays.append)

    with pytest.raises(PermissionError):
        runtime.execute_action(
            module_id="crm",
            action_id="qualify_lead",
            project_id="PRJ-PERSISTENT",
            idempotency_key="IDEMP-PERSISTENT-1",
        )

    # A non-allowlisted permission error (no winerror) is raised on the first
    # attempt without any retry delay.
    assert replace_calls == 1
    assert sleep_delays == []
    # Fail closed: the previous complete content is untouched (no non-atomic
    # partial write) and every owned temporary file is removed.
    assert _state_bytes(runtime) == before
    assert list(tmp_path.glob(".*.tmp")) == []


@pytest.mark.parametrize(
    "error_factory",
    [
        pytest.param(
            lambda: _permission_error_with_winerror(1314),
            id="windows-permanent-privilege-not-held",
        ),
        pytest.param(
            lambda: _permission_error_with_winerror(2),
            id="windows-non-allowlisted-code",
        ),
    ],
)
def test_non_allowlisted_windows_permission_error_raises_on_first_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_factory
) -> None:
    runtime = _runtime(tmp_path)
    replace_calls = 0
    sleep_delays: list[float] = []

    def denied_replace(source, target):
        nonlocal replace_calls
        replace_calls += 1
        if Path(target) != runtime.runtime_path:
            raise AssertionError("replace was called for an unexpected target")
        raise error_factory()

    monkeypatch.setattr(os, "replace", denied_replace)
    monkeypatch.setattr(time, "sleep", sleep_delays.append)

    with pytest.raises(PermissionError):
        runtime.execute_action(
            module_id="crm",
            action_id="qualify_lead",
            project_id="PRJ-PERMANENT",
            idempotency_key="IDEMP-PERMANENT-1",
        )

    assert replace_calls == 1, "a permanent error must not be retried"
    assert sleep_delays == [], "a permanent error must not incur a retry delay"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_exhausted_transient_retries_reraise_original_error_and_clean_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path)
    before = _state_bytes(runtime)
    replace_calls = 0
    sleep_delays: list[float] = []

    def always_transient(source, target):
        nonlocal replace_calls
        replace_calls += 1
        if Path(target) != runtime.runtime_path:
            raise AssertionError("replace was called for an unexpected target")
        raise _transient_windows_permission_error()

    monkeypatch.setattr(os, "replace", always_transient)
    monkeypatch.setattr(time, "sleep", sleep_delays.append)
    # The injected winerror 5 is only retryable on Windows, so the platform
    # is simulated explicitly instead of depending on the host.
    _simulate_platform(monkeypatch, windows=True)

    with pytest.raises(PermissionError) as excinfo:
        runtime.execute_action(
            module_id="crm",
            action_id="qualify_lead",
            project_id="PRJ-EXHAUSTED",
            idempotency_key="IDEMP-EXHAUSTED-1",
        )

    # The original transient error is re-raised unchanged after exactly the
    # bounded attempts and delays; no error is swallowed.
    assert getattr(excinfo.value, "winerror", None) == 5
    assert replace_calls == demo_runtime._REPLACE_MAX_ATTEMPTS
    assert sleep_delays == list(demo_runtime._REPLACE_RETRY_DELAYS)
    assert sum(sleep_delays) <= 0.75
    # Fail closed after exhaustion: previous content untouched (no non-atomic
    # partial write) and every owned temporary file is removed.
    assert _state_bytes(runtime) == before
    assert list(tmp_path.glob(".*.tmp")) == []


def test_allowlisted_winerror_is_not_retried_outside_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temporary = tmp_path / "state.tmp"
    temporary.write_text("new", encoding="utf-8")
    target = tmp_path / "runtime.json"
    target.write_text("old", encoding="utf-8")
    replace_calls = 0

    def denied_replace(source, destination):
        nonlocal replace_calls
        replace_calls += 1
        raise _transient_windows_permission_error()

    monkeypatch.setattr(os, "replace", denied_replace)
    monkeypatch.setattr(time, "sleep", lambda _: pytest.fail("must not sleep outside Windows"))
    # Simulate a non-Windows host through the module-local seam. Patching
    # ``demo_runtime.os.name`` instead would mutate the single global ``os``
    # module object and leak into pathlib, pytest and unrelated modules.
    _simulate_platform(monkeypatch, windows=False)

    with pytest.raises(PermissionError):
        demo_runtime._replace_with_transient_retry(temporary, target)

    assert replace_calls == 1, "non-Windows failures are never retried"
    assert target.read_text(encoding="utf-8") == "old"
    assert temporary.read_text(encoding="utf-8") == "new"


def test_platform_seam_is_production_neutral_and_leak_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam must equal ``os.name == "nt"`` and never touch global ``os``."""
    real_os_name = os.name

    # Unpatched production behavior is exactly the documented predicate.
    assert demo_runtime._is_windows() is (real_os_name == "nt")

    # An allowlisted error is classified purely by the simulated platform.
    transient = _transient_windows_permission_error()
    _simulate_platform(monkeypatch, windows=True)
    assert demo_runtime._is_windows() is True
    assert demo_runtime._is_transient_windows_replace_error(transient) is True

    _simulate_platform(monkeypatch, windows=False)
    assert demo_runtime._is_windows() is False
    assert demo_runtime._is_transient_windows_replace_error(transient) is False

    # Simulating either platform leaves the real host attribute untouched, so
    # pathlib, pytest and unrelated modules are unaffected.
    assert os.name == real_os_name
    assert demo_runtime.os is os

    monkeypatch.undo()
    assert demo_runtime._is_windows() is (real_os_name == "nt")


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows-only share-mode mechanism; covered cross-platform by the monkeypatched tests",
)
def test_windows_held_target_blocks_replace_and_recovers_after_release(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)

    # Python's open() on Windows requests FILE_SHARE_READ | FILE_SHARE_WRITE
    # but not FILE_SHARE_DELETE, exactly like a transient scanner or sync
    # agent hold. While it lasts, replacement is denied; once it releases,
    # the same atomic write succeeds.
    with open(runtime.runtime_path, "rb"):
        with pytest.raises(PermissionError):
            runtime.execute_action(
                module_id="crm",
                action_id="qualify_lead",
                project_id="PRJ-HELD",
                idempotency_key="IDEMP-HELD-1",
            )

    result = runtime.execute_action(
        module_id="crm",
        action_id="qualify_lead",
        project_id="PRJ-RELEASED",
        idempotency_key="IDEMP-HELD-2",
    )
    assert result["duplicate"] is False
    state = json.loads(_state_bytes(runtime))
    assert state["events"][0]["projectId"] == "PRJ-RELEASED"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_concurrent_writers_serialize_and_keep_file_complete(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    writers = 4
    actions_per_writer = 10
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        for action in range(actions_per_writer):
            try:
                runtime.execute_action(
                    module_id="crm",
                    action_id="qualify_lead",
                    project_id=f"PRJ-T{index}",
                    idempotency_key=f"IDEMP-T{index}-{action}",
                )
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)
                return

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    state = json.loads(_state_bytes(runtime))
    assert len(state["events"]) == writers * actions_per_writer
    assert list(tmp_path.glob(".*.tmp")) == []


def test_ambient_demo_runtime_path_cannot_redirect_test_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ambient = tmp_path / "ambient" / "platform_demo_runtime.json"
    monkeypatch.setenv("DEMO_RUNTIME_PATH", str(ambient))

    previous, isolated = isolate_demo_runtime_path(tmp_path / "suite-root")

    # The isolation assignment is unconditional: the ambient value is
    # recorded but never used as the write target.
    assert previous == str(ambient)
    assert isolated == str(tmp_path / "suite-root" / "demo" / "platform_demo_runtime.json")
    assert os.environ["DEMO_RUNTIME_PATH"] == isolated
    assert os.environ["DEMO_RUNTIME_PATH"] != str(ambient)

    # Reversible: the previous value is restored for the next scope.
    restore_demo_runtime_path(previous)
    assert os.environ["DEMO_RUNTIME_PATH"] == str(ambient)


def test_isolated_demo_runtime_path_restores_to_unset_without_ambient_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEMO_RUNTIME_PATH", raising=False)

    previous, isolated = isolate_demo_runtime_path(tmp_path / "suite-root")

    assert previous is None
    assert os.environ["DEMO_RUNTIME_PATH"] == isolated

    restore_demo_runtime_path(previous)
    assert "DEMO_RUNTIME_PATH" not in os.environ


def test_suite_runtime_path_stays_inside_the_pytest_temp_root() -> None:
    temp_root = Path(os.environ["PYTEST_DEBUG_TEMPROOT"])
    assert demo_runtime.RUNTIME_PATH.is_relative_to(temp_root)
