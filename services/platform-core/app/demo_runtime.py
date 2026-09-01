from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "data" / "platform_demo_seed.json"
RUNTIME_PATH = Path(os.getenv("DEMO_RUNTIME_PATH", str(ROOT / "data" / "platform_demo_runtime.json")))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class DemoRuntimeError(ValueError):
    pass


# On Windows, os.replace requires DELETE sharing on the target. A transient
# external holder (antivirus real-time scan, search indexer, or file-sync
# agent) can open the freshly written target without FILE_SHARE_DELETE for a
# few milliseconds, which makes the rename fail with PermissionError
# (WinError 5, access denied) even though the process owns the file and the
# directory is writable. This is the failure observed once in the Gate 6
# regression suite. A failed rename leaves the temporary file intact, so the
# same atomic replacement can simply be retried. The retry never falls back
# to a non-atomic partial write, the total wait is bounded, and a persistent
# permission problem still surfaces as the original PermissionError.
_REPLACE_MAX_ATTEMPTS = 5
_REPLACE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4)

# Explicit, documented allowlist of transient Windows replacement failures.
# Only these PermissionError.winerror codes are retried, only on Windows,
# and only for the same atomic rename; every other PermissionError/OSError
# is raised immediately on the first attempt without sleeping or retrying.
#   - 5  (ERROR_ACCESS_DENIED): the observed WinError 5 race, where a
#        transient external holder opens the fresh target without
#        FILE_SHARE_DELETE for a few milliseconds;
#   - 32 (ERROR_SHARING_VIOLATION): another process holds the target file
#        without the sharing mode the rename requires;
#   - 33 (ERROR_LOCK_VIOLATION): another process holds a lock region on the
#        target file.
_TRANSIENT_WINDOWS_REPLACE_ERRORS = frozenset({5, 32, 33})


def _is_windows() -> bool:
    """Narrow, module-local platform predicate for the retry gate.

    At runtime this is exactly ``os.name == "nt"`` and nothing else. It is a
    dedicated helper only so the focused retry tests can simulate either
    platform deterministically on any host by monkeypatching this single
    module-local seam. Patching the seam keeps the simulation local to this
    module; patching the global ``os.name`` attribute instead would also
    change ``pathlib``, pytest and every other importer of ``os``.
    """
    return os.name == "nt"


def _is_transient_windows_replace_error(error: OSError) -> bool:
    """True only for a documented transient Windows replacement failure."""
    return (
        _is_windows()
        and isinstance(error, PermissionError)
        and getattr(error, "winerror", None) in _TRANSIENT_WINDOWS_REPLACE_ERRORS
    )


def _replace_with_transient_retry(temporary_path: Path, target: Path) -> None:
    attempts = 1
    while True:
        try:
            temporary_path.replace(target)
            return
        except OSError as error:
            if not _is_transient_windows_replace_error(error):
                raise
            if attempts >= _REPLACE_MAX_ATTEMPTS:
                raise
            logger.debug(
                "demo_runtime atomic replace attempt %d/%d hit transient "
                "Windows replacement error %s; retrying in %.2fs",
                attempts,
                _REPLACE_MAX_ATTEMPTS,
                getattr(error, "winerror", None),
                _REPLACE_RETRY_DELAYS[attempts - 1],
            )
            time.sleep(_REPLACE_RETRY_DELAYS[attempts - 1])
            attempts += 1


class DemoRuntime:
    """Thread-safe, JSON-backed sandbox for cross-module UAT.

    The runtime deliberately contains synthetic records only. It models the
    platform contracts (stable IDs, ProjectID, CorrelationID, idempotency,
    outbox delivery and audit) without calling an external system.
    """

    def __init__(self, seed_path: Path = SEED_PATH, runtime_path: Path = RUNTIME_PATH):
        self.seed_path = seed_path
        self.runtime_path = runtime_path
        self._lock = threading.RLock()

    def _seed(self) -> dict[str, Any]:
        return json.loads(self.seed_path.read_text(encoding="utf-8"))

    def _ensure(self) -> None:
        if not self.runtime_path.exists():
            self.reset()

    def _read(self) -> dict[str, Any]:
        self._ensure()
        return json.loads(self.runtime_path.read_text(encoding="utf-8"))

    def _write(self, state: dict[str, Any]) -> None:
        self.runtime_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            dir=self.runtime_path.parent,
            prefix=f".{self.runtime_path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            _replace_with_transient_retry(temporary_path, self.runtime_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _summary(state: dict[str, Any]) -> dict[str, Any]:
        outbox = state["outbox"]
        return {
            "registeredModules": len(state["modules"]),
            "testableModules": sum(bool(module["actions"]) for module in state["modules"]),
            "events": len(state["events"]),
            "auditEntries": len(state["audit"]),
            "outbox": {
                "delivered": sum(item["status"] == "delivered" for item in outbox),
                "retry": sum(item["status"] == "retry" for item in outbox),
                "deadLetter": sum(item["status"] == "dead_letter" for item in outbox),
            },
            "journeys": {
                journey["id"]: {
                    "status": journey["status"],
                    "completedSteps": sum(step["status"] == "completed" for step in journey["steps"]),
                    "totalSteps": len(journey["steps"]),
                }
                for journey in state["journeys"]
            },
        }

    def state(self) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            state["summary"] = self._summary(state)
            return state

    def module(self, module_id: str) -> dict[str, Any]:
        state = self.state()
        module = next((item for item in state["modules"] if item["id"] == module_id), None)
        if not module:
            raise DemoRuntimeError(f"Ismeretlen modul: {module_id}")
        module = deepcopy(module)
        module["events"] = [
            event
            for event in state["events"]
            if event["producer"] == module_id or module_id in event["consumers"]
        ][:20]
        module["outbox"] = [
            item
            for item in state["outbox"]
            if item["producer"] == module_id or item["consumer"] == module_id
        ][:20]
        return module

    def reset(self) -> dict[str, Any]:
        with self._lock:
            state = self._seed()
            state["meta"]["resetAt"] = utcnow()
            self._write(state)
            state["summary"] = self._summary(state)
            return state

    @staticmethod
    def _module(state: dict[str, Any], module_id: str) -> dict[str, Any]:
        module = next((item for item in state["modules"] if item["id"] == module_id), None)
        if not module:
            raise DemoRuntimeError(f"Ismeretlen modul: {module_id}")
        return module

    @staticmethod
    def _action(module: dict[str, Any], action_id: str) -> dict[str, Any]:
        action = next((item for item in module["actions"] if item["id"] == action_id), None)
        if not action:
            raise DemoRuntimeError(f"A(z) {module['id']} modulban nincs ilyen tesztművelet: {action_id}")
        return action

    def _execute(
        self,
        state: dict[str, Any],
        *,
        module_id: str,
        action_id: str,
        project_id: str,
        actor: str,
        correlation_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        existing = next(
            (entry for entry in state["idempotency"] if entry["key"] == idempotency_key),
            None,
        )
        if existing:
            event = next(item for item in state["events"] if item["id"] == existing["eventId"])
            return {"duplicate": True, "event": event, "deliveries": []}

        module = self._module(state, module_id)
        action = self._action(module, action_id)
        sequence = len(state["events"]) + 1
        event_id = f"EVT-DEMO-{sequence:05d}"
        occurred_at = utcnow()
        event = {
            "id": event_id,
            "eventKey": action["eventKey"],
            "producer": module_id,
            "consumers": action["consumers"],
            "projectId": project_id,
            "correlationId": correlation_id,
            "idempotencyKey": idempotency_key,
            "actor": actor,
            "payload": payload,
            "status": "delivered",
            "occurredAt": occurred_at,
        }
        deliveries = []
        for consumer in action["consumers"]:
            delivery = {
                "id": f"OUT-DEMO-{len(state['outbox']) + 1:05d}",
                "eventId": event_id,
                "eventKey": action["eventKey"],
                "producer": module_id,
                "consumer": consumer,
                "projectId": project_id,
                "correlationId": correlation_id,
                "status": "delivered",
                "attempts": 1,
                "lastAttemptAt": occurred_at,
            }
            state["outbox"].insert(0, delivery)
            deliveries.append(delivery)

        module["status"] = action["nextStatus"]
        module["lastEventId"] = event_id
        module["lastUpdatedAt"] = occurred_at
        if module["records"]:
            module["records"][0]["status"] = action["nextStatus"]
            module["records"][0]["projectId"] = project_id
            module["records"][0]["correlationId"] = correlation_id
            module["records"][0]["lastEventId"] = event_id
        state["events"].insert(0, event)
        state["idempotency"].append({"key": idempotency_key, "eventId": event_id})
        state["audit"].insert(
            0,
            {
                "id": f"AUD-DEMO-{len(state['audit']) + 1:05d}",
                "action": f"{module_id}.{action_id}",
                "actor": actor,
                "projectId": project_id,
                "correlationId": correlation_id,
                "eventId": event_id,
                "at": occurred_at,
            },
        )
        return {"duplicate": False, "event": event, "deliveries": deliveries}

    def execute_action(
        self,
        *,
        module_id: str,
        action_id: str,
        project_id: str,
        actor: str = "demo.user@imperial.local",
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            correlation_id = correlation_id or f"CORR-DEMO-{uuid.uuid4().hex[:12].upper()}"
            idempotency_key = idempotency_key or (
                f"{module_id}:{action_id}:{project_id}:{uuid.uuid4().hex[:12]}"
            )
            result = self._execute(
                state,
                module_id=module_id,
                action_id=action_id,
                project_id=project_id,
                actor=actor,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                payload=payload or {},
            )
            self._write(state)
            result["summary"] = self._summary(state)
            return result

    def run_journey(self, journey_id: str, actor: str = "demo.user@imperial.local") -> dict[str, Any]:
        with self._lock:
            state = self._read()
            journey = next((item for item in state["journeys"] if item["id"] == journey_id), None)
            if not journey:
                raise DemoRuntimeError(f"Ismeretlen tesztút: {journey_id}")
            correlation_id = f"CORR-{journey_id.upper()}-{uuid.uuid4().hex[:8].upper()}"
            results = []
            for index, step in enumerate(journey["steps"], start=1):
                result = self._execute(
                    state,
                    module_id=step["moduleId"],
                    action_id=step["actionId"],
                    project_id=journey["projectId"],
                    actor=actor,
                    correlation_id=correlation_id,
                    idempotency_key=f"{journey_id}:{correlation_id}:{index}",
                    payload={
                        "journeyId": journey_id,
                        "step": index,
                        "sourceRecordId": journey.get("sourceRecordId"),
                    },
                )
                step["status"] = "completed"
                step["eventId"] = result["event"]["id"]
                results.append(result["event"])
            journey["status"] = "completed"
            journey["lastRunAt"] = utcnow()
            journey["correlationId"] = correlation_id
            self._write(state)
            return {
                "journey": journey,
                "events": results,
                "summary": self._summary(state),
            }

    def inject_failure(self, consumer: str) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            item = next((row for row in state["outbox"] if row["consumer"] == consumer), None)
            if not item:
                raise DemoRuntimeError(f"Nincs kézbesítés ehhez a fogyasztóhoz: {consumer}")
            item["status"] = "retry"
            item["attempts"] += 1
            item["lastError"] = "Szándékosan előidézett sandbox adapterhiba."
            item["lastAttemptAt"] = utcnow()
            self._write(state)
            return item

    def retry_outbox(self, outbox_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            item = next((row for row in state["outbox"] if row["id"] == outbox_id), None)
            if not item:
                raise DemoRuntimeError(f"Ismeretlen outbox tétel: {outbox_id}")
            item["attempts"] += 1
            item["status"] = "delivered" if item["attempts"] <= 3 else "dead_letter"
            item["lastAttemptAt"] = utcnow()
            item.pop("lastError", None)
            self._write(state)
            return item


demo_runtime = DemoRuntime()
