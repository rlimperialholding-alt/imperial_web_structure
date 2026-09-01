from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import verify_crm_canonical_export as smoke


class Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def export_payload(*, checksum: str | None = None) -> dict:
    payload_json = '{"id":"CRM-1"}'
    return {
        "workspaceId": "imperial-live",
        "sourceSystem": "imperial-sales-crm",
        "entity": "customers",
        "total": 1,
        "nextCursor": None,
        "envelopes": [
            {
                "workspaceId": "imperial-live",
                "payloadJson": payload_json,
                "payloadSha256": checksum
                or hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
            }
        ],
    }


def test_smoke_verifies_operational_export_checksum(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "settings",
        SimpleNamespace(
            crm_read_base_url="https://crm.example",
            crm_read_token="x" * 32,
            crm_workspace_id="imperial-live",
        ),
    )
    monkeypatch.setattr(smoke, "CRM_BASE_URL", "https://crm.example")
    monkeypatch.setattr(smoke, "CRM_READ_TOKEN", "x" * 32)
    monkeypatch.setattr(smoke.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(export_payload()))

    assert smoke.fetch_entity("customers") == {
        "total": 1,
        "verified": 1,
        "nextCursor": None,
    }


def test_smoke_fails_closed_on_checksum_mismatch(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "settings",
        SimpleNamespace(
            crm_read_base_url="https://crm.example",
            crm_read_token="x" * 32,
            crm_workspace_id="imperial-live",
        ),
    )
    monkeypatch.setattr(smoke, "CRM_BASE_URL", "https://crm.example")
    monkeypatch.setattr(smoke, "CRM_READ_TOKEN", "x" * 32)
    monkeypatch.setattr(
        smoke.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(export_payload(checksum="0" * 64)),
    )

    with pytest.raises(RuntimeError, match="checksum"):
        smoke.fetch_entity("customers")
