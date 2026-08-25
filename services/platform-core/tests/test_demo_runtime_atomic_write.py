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
write.

These tests prove, deterministically:

1. a single transient denial is retried and the atomic write completes;
2. a persistent denial still fails closed: the original PermissionError
   propagates, the previous target content stays byte-identical, and no
   owned temporary file is left behind;
3. the real Windows share-mode mechanism (a held target without
   FILE_SHARE_DELETE) blocks replacement and recovers once released;
4. concurrent writers on one runtime instance stay serialized and the file
   is always complete JSON.

All fixtures use synthetic copies under the pytest temporary directory; the
repository runtime data is never touched.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from app.demo_runtime import DemoRuntime, SEED_PATH


def _runtime(tmp_path: Path) -> DemoRuntime:
    runtime = DemoRuntime(runtime_path=tmp_path / "platform_demo_runtime.json")
    runtime.reset()
    return runtime


def _state_bytes(runtime: DemoRuntime) -> bytes:
    return runtime.runtime_path.read_bytes()


def test_transient_replace_denial_is_retried_and_write_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path)
    real_replace = os.replace
    denials: list[bool] = []

    def flaky_replace(source, target):
        if Path(target) == runtime.runtime_path and not denials:
            denials.append(True)
            raise PermissionError(
                13, "Access is denied", str(source), str(target)
            )
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", flaky_replace)

    result = runtime.execute_action(
        module_id="crm",
        action_id="qualify_lead",
        project_id="PRJ-TRANSIENT",
        actor="transient@example.test",
        idempotency_key="IDEMP-TRANSIENT-1",
    )

    assert len(denials) == 1, "the injected transient denial was never raised"
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

    def always_denied(source, target):
        if Path(target) == runtime.runtime_path:
            raise PermissionError(
                13, "Access is denied", str(source), str(target)
            )
        raise AssertionError("replace was called for an unexpected target")

    monkeypatch.setattr(os, "replace", always_denied)

    with pytest.raises(PermissionError):
        runtime.execute_action(
            module_id="crm",
            action_id="qualify_lead",
            project_id="PRJ-PERSISTENT",
            idempotency_key="IDEMP-PERSISTENT-1",
        )

    # Fail closed: the previous complete content is untouched (no non-atomic
    # partial write) and every owned temporary file is removed.
    assert _state_bytes(runtime) == before
    assert list(tmp_path.glob(".*.tmp")) == []


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

    threads = [
        threading.Thread(target=worker, args=(index,)) for index in range(writers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    state = json.loads(_state_bytes(runtime))
    assert len(state["events"]) == writers * actions_per_writer
    assert list(tmp_path.glob(".*.tmp")) == []
