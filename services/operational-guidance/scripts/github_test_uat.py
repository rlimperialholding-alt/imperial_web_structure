from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
import uuid

HUB = os.environ.get("HUB_URL", "http://127.0.0.1:8000")
ITEP = os.environ.get("ITEP_URL", "http://127.0.0.1:3000")
ADMIN_TOKEN = os.environ.get("API_ADMIN_TOKEN", "test-admin-token-not-for-production")
SECRET = os.environ["ITEP_IDENTITY_SHARED_SECRET"]


def get_json(url: str, headers: dict[str, str] | None = None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=20) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        return response.status, json.loads(response.read().decode())


def post_json(url: str, headers: dict[str, str] | None = None):
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(
        url,
        headers=request_headers,
        method="POST",
        data=b"{}",
    )
    # Belső szolgáltatás-közi hívás: a célhost operátori settingsből (crm_read/write_base_url, itep_api_base_url) vagy a CI-fixture-ből származik, sosem felhasználói kérésből; SSRF-felület nincs.
    with urllib.request.urlopen(request, timeout=30) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        return response.status, json.loads(response.read().decode())


def signed_headers() -> dict[str, str]:
    now = int(time.time())
    payload = {
        "actorId": "github-actions",
        "organizationId": "imperial-holding",
        "roles": ["SYSTEM"],
        "permissions": ["task.read.all", "task.create", "task.transition.all"],
        "issuedAt": now,
        "expiresAt": now + 300,
        "nonce": str(uuid.uuid4()),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    signature = hmac.new(SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Imperial-Identity": encoded,
        "X-Imperial-Identity-Signature": signature,
    }


checks: list[dict[str, object]] = []

status, hub_ready = get_json(f"{HUB}/ready")
checks.append({"name": "hub-ready", "status": status, "payload": hub_ready})

status, itep_ready = get_json(f"{ITEP}/health/ready")
checks.append({"name": "itep-ready", "status": status, "payload": itep_ready})

status, crm_result = post_json(
    f"{ITEP}/v1/connectors/crm-live/sync",
    signed_headers(),
)
checks.append({"name": "live-crm-sync", "status": status, "payload": crm_result})

status, control_room = get_json(
    f"{ITEP}/v1/integration-control-room/dashboard",
    signed_headers(),
)
checks.append({
    "name": "control-room",
    "status": status,
    "connectors": control_room.get("totals", {}).get("connectors"),
    "failed": control_room.get("totals", {}).get("failed"),
})

status, hub_proxy = get_json(
    f"{HUB}/api/v1/itep/integration-control-room",
    {"X-Admin-Token": ADMIN_TOKEN},
)
checks.append({
    "name": "hub-itep-proxy",
    "status": status,
    "connectors": hub_proxy.get("totals", {}).get("connectors"),
})

if any(int(check["status"]) >= 300 for check in checks):
    raise SystemExit(json.dumps(checks, ensure_ascii=False, indent=2))

print(json.dumps({"ok": True, "checks": checks}, ensure_ascii=False, indent=2))
