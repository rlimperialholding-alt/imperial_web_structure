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


def request_json(path: str, *, method: str = "GET", payload: dict | None = None) -> dict:
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


if PLATFORM["meta"].get("synthetic") is not True:
    raise RuntimeError("The remote smoke dataset must be synthetic")
if PLATFORM["meta"].get("containsCustomerData") is not False:
    raise RuntimeError("The remote smoke dataset must not contain customer data")

login()
routes = [module["route"] for module in PLATFORM["modules"]]
for route in routes:
    with OPENER.open(f"{BASE_URL}{route}", timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"{route} returned HTTP {response.status}")

request_json("/core/api/demo/reset", method="POST", payload={})
journeys: dict[str, int] = {}
for journey_id in ("customer-to-care", "campaign-to-profit"):
    result = request_json(
        f"/core/api/demo/journeys/{journey_id}/run",
        method="POST",
        payload={"actor": "remote.test@imperial.local"},
    )
    if result.get("journey", {}).get("status") != "completed":
        raise RuntimeError(f"Journey did not complete: {journey_id}")
    journeys[journey_id] = len(result.get("events", []))

state = request_json("/core/api/demo/state")
print(
    json.dumps(
        {
            "ok": True,
            "synthetic_only": True,
            "customer_data": False,
            "module_routes": len(routes),
            "registered_modules": len(state["modules"]),
            "journeys": journeys,
        },
        ensure_ascii=False,
    )
)
