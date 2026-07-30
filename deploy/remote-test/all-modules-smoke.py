from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = os.environ.get("IMPERIAL_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
PLATFORM = json.loads(
    (ROOT / "sites" / "_portal" / "data" / "platform.json").read_text(
        encoding="utf-8"
    )
)
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def login() -> None:
    data = urllib.parse.urlencode(
        {
            "email": os.environ.get(
                "PLATFORM_SMOKE_EMAIL",
                "platform-admin@imperial.local",
            ),
            "password": os.environ.get(
                "PLATFORM_SMOKE_PASSWORD",
                "Imperial2026!",
            ),
            "return_to": "/",
        }
    ).encode()
    request = urllib.request.Request(
        f"{BASE_URL}/login",
        data=data,
        method="POST",
    )
    with OPENER.open(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"Platform login returned HTTP {response.status}")


def request_json(path: str, *, method: str = "GET", payload: dict | None = None):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with OPENER.open(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        return json.loads(response.read().decode())


login()
expected_ids = {module["id"] for module in PLATFORM["modules"]}
reset = request_json("/core/api/demo/reset", method="POST", payload={})
runtime_modules = reset["modules"]
runtime_ids = {module["id"] for module in runtime_modules}

if runtime_ids != expected_ids or len(runtime_modules) != 47:
    raise RuntimeError(
        f"Module set mismatch: missing={sorted(expected_ids - runtime_ids)}, "
        f"unexpected={sorted(runtime_ids - expected_ids)}"
    )

executed = []
for module in runtime_modules:
    if not module.get("records") or not module.get("actions"):
        raise RuntimeError(f"{module['id']} is not testable")
    action = module["actions"][0]
    idempotency_key = f"all-modules-smoke-{module['id']}"
    payload = {
        "module_id": module["id"],
        "action_id": action["id"],
        "project_id": "PRJ-ALL-MODULES-SMOKE",
        "actor": "remote.module.smoke@imperial.local",
        "correlation_id": "CORR-ALL-MODULES-SMOKE",
        "idempotency_key": idempotency_key,
        "payload": {"synthetic": True, "test": "all-modules-smoke"},
    }
    result = request_json("/core/api/demo/actions", method="POST", payload=payload)
    if result.get("duplicate") is not False:
        raise RuntimeError(f"{module['id']} did not execute a fresh test action")
    event = result.get("event", {})
    if event.get("producer") != module["id"] or event.get("status") != "delivered":
        raise RuntimeError(f"{module['id']} produced an invalid event")

    duplicate = request_json("/core/api/demo/actions", method="POST", payload=payload)
    if duplicate.get("duplicate") is not True:
        raise RuntimeError(f"{module['id']} idempotency check failed")
    executed.append(module["id"])

state = request_json("/core/api/demo/state")
summary = state["summary"]
if summary["registeredModules"] != 47 or summary["testableModules"] != 47:
    raise RuntimeError("The final runtime summary is incomplete")
if summary["events"] != 47 or summary["auditEntries"] != 47:
    raise RuntimeError("Not every module produced exactly one event and audit record")
if summary["outbox"]["retry"] or summary["outbox"]["deadLetter"]:
    raise RuntimeError("The module smoke test left retry or dead-letter messages")

print(
    json.dumps(
        {
            "ok": True,
            "registered_modules": summary["registeredModules"],
            "testable_modules": summary["testableModules"],
            "executed_modules": len(executed),
            "events": summary["events"],
            "audit_entries": summary["auditEntries"],
            "outbox": summary["outbox"],
            "synthetic_only": True,
        },
        ensure_ascii=False,
    )
)
