from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from app.config import settings
from app.services.crm_transport import crm_service_headers


ENTITIES = ("users", "customers", "projects", "contracts", "invoices", "cashflow")
CRM_BASE_URL = (
    settings.crm_read_base_url or os.getenv("PLATFORM_CRM_READ_BASE_URL", "")
).rstrip("/")
CRM_READ_TOKEN = settings.crm_read_token or os.getenv("ITEP_CRM_READ_TOKEN", "")


def fetch_entity(entity: str, *, limit: int = 5) -> dict:
    query = urllib.parse.urlencode(
        {
            "entity": entity,
            "workspaceId": settings.crm_workspace_id,
            "cursor": 0,
            "limit": limit,
        }
    )
    request = urllib.request.Request(
        f"{CRM_BASE_URL}/api/integrations/crm-canonical-export?{query}",
        headers=crm_service_headers("X-ITEP-CRM-Token", CRM_READ_TOKEN),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"CRM canonical export HTTP {exc.code}: {detail}") from exc
    if payload.get("workspaceId") != settings.crm_workspace_id:
        raise RuntimeError(f"Workspace mismatch: {entity}")
    if payload.get("sourceSystem") != "imperial-sales-crm" or payload.get("entity") != entity:
        raise RuntimeError(f"Canonical export identity mismatch: {entity}")
    total = payload.get("total")
    envelopes = payload.get("envelopes")
    if not isinstance(total, int) or total < 0 or not isinstance(envelopes, list):
        raise RuntimeError(f"Invalid canonical export page: {entity}")
    for envelope in envelopes:
        payload_json = envelope.get("payloadJson")
        expected_hash = envelope.get("payloadSha256")
        if not isinstance(payload_json, str) or not isinstance(expected_hash, str):
            raise RuntimeError(f"Missing canonical payload evidence: {entity}")
        actual_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            raise RuntimeError(f"Canonical payload checksum mismatch: {entity}")
        if envelope.get("workspaceId") != settings.crm_workspace_id:
            raise RuntimeError(f"Envelope workspace mismatch: {entity}")
    return {
        "total": total,
        "verified": len(envelopes),
        "nextCursor": payload.get("nextCursor"),
    }


def main() -> None:
    if not CRM_BASE_URL or len(CRM_READ_TOKEN) < 32:
        raise RuntimeError("CRM canonical read connection is not configured.")
    print(json.dumps({entity: fetch_entity(entity) for entity in ENTITIES}, sort_keys=True))


if __name__ == "__main__":
    main()
