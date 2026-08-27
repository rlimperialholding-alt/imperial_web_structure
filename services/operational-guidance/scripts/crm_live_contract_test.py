from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


def require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


base_url = require("CRM_API_BASE_URL").rstrip("/")
token = os.environ.get("CRM_ACCESS_TOKEN", "").strip() or require("ITEP_CRM_READ_TOKEN")
workspace = require("CRM_WORKSPACE_ID")
path = os.environ.get("CRM_ACTIVITIES_PATH", "/api/v1/activities")
header = os.environ.get("CRM_AUTH_HEADER", "Authorization")
scheme = os.environ.get("CRM_AUTH_SCHEME", "Bearer").strip()
if scheme.lower() in {"none", "raw"}:
    scheme = ""
workspace_param = os.environ.get("CRM_WORKSPACE_QUERY_PARAMETER", "workspace")

query = urllib.parse.urlencode({workspace_param: workspace, "limit": "1"})
url = f"{base_url}{path}?{query}"
auth_value = f"{scheme} {token}".strip() if scheme else token
request = urllib.request.Request(
    url,
    headers={header: auth_value, "Accept": "application/json"},
    method="GET",
)

with urllib.request.urlopen(request, timeout=20) as response:
    if not 200 <= response.status < 300:
        raise RuntimeError(f"CRM returned HTTP {response.status}")
    payload = json.loads(response.read().decode("utf-8"))

items = next(
    (payload[key] for key in ("activities", "items", "data") if key in payload),
    None,
)
if items is None:
    raise RuntimeError(
        "CRM response does not contain activities/items/data; field mapping must be updated"
    )

print(json.dumps({
    "ok": True,
    "status": response.status,
    "records_visible": len(items),
    "write_operation_performed": False,
}))
