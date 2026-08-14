from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from app.config import settings


BASE_URL = os.getenv("PLATFORM_SELF_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def request_json(path: str, *, token_header: str, token: str, method: str) -> dict:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=b"" if method == "POST" else None,
        headers={token_header: token},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Canonical roundtrip HTTP {exc.code}: {detail}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Canonical roundtrip returned invalid JSON: {path}")
    return payload


def main() -> None:
    if len(settings.internal_job_token) < 32:
        raise RuntimeError("Platform internal verification tokens are not configured.")
    crm_import = request_json(
        "/api/imports/crm-sync",
        token_header="X-Internal-Job-Token",
        token=settings.internal_job_token,
        method="POST",
    )
    if crm_import.get("status") != "committed":
        raise RuntimeError(
            f"CRM canonical import failed closed: {json.dumps(crm_import, sort_keys=True)}"
        )
    push = request_json(
        "/api/integrations/canonical/push-crm",
        token_header="X-Internal-Job-Token",
        token=settings.internal_job_token,
        method="POST",
    )
    if any(int(push.get(key) or 0) for key in ("conflicts", "rejected", "failed")):
        raise RuntimeError(f"Canonical push failed closed: {json.dumps(push, sort_keys=True)}")
    reconciliation = request_json(
        "/api/integrations/canonical/reconcile-crm",
        token_header="X-Internal-Job-Token",
        token=settings.internal_job_token,
        method="POST",
    )
    if reconciliation.get("status") != "passed":
        raise RuntimeError(
            f"Canonical reconciliation requires attention: {json.dumps(reconciliation, sort_keys=True)}"
        )
    integrity = request_json(
        "/api/integrations/canonical/integrity",
        token_header="X-Internal-Job-Token",
        token=settings.internal_job_token,
        method="GET",
    )
    if integrity.get("status") != "passed":
        raise RuntimeError(
            f"Canonical integrity requires attention: {json.dumps(integrity, sort_keys=True)}"
        )
    print(
        json.dumps(
            {
                "crm_import": {
                    key: crm_import.get(key)
                    for key in ("total", "inserted", "updated", "unchanged")
                },
                "push": {key: push.get(key) for key in ("local", "pending", "applied")},
                "reconciliation": {
                    key: reconciliation.get(key)
                    for key in ("local", "remote", "matching", "missing_remote", "hash_mismatch")
                },
                "integrity": {
                    key: integrity.get(key)
                    for key in (
                        "project_masters",
                        "project_references",
                        "missing_project_masters",
                        "modules_with_canonical_data",
                    )
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
