from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts import verify_canonical_roundtrip as smoke


def healthy_payload(path: str) -> dict:
    if path.endswith("crm-sync"):
        return {"status": "committed", "total": 2500, "inserted": 0, "updated": 0, "unchanged": 2500}
    if path.endswith("push-crm"):
        return {"local": 154, "pending": 0, "applied": 0, "conflicts": 0, "rejected": 0, "failed": 0}
    if path.endswith("reconcile-crm"):
        return {"status": "passed", "local": 154, "remote": 154, "matching": 154, "missing_remote": 0, "hash_mismatch": 0}
    return {"status": "passed", "project_masters": 84, "project_references": 154, "missing_project_masters": 0, "modules_with_canonical_data": 47}


def test_roundtrip_smoke_requires_clean_push_reconciliation_and_integrity(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "settings", SimpleNamespace(internal_job_token="x" * 32))
    monkeypatch.setattr(
        smoke,
        "request_json",
        lambda path, **_kwargs: healthy_payload(path),
    )

    smoke.main()

    result = json.loads(capsys.readouterr().out)
    assert result["reconciliation"]["matching"] == 154
    assert result["integrity"]["modules_with_canonical_data"] == 47


def test_roundtrip_smoke_fails_closed_on_reconciliation_gap(monkeypatch):
    monkeypatch.setattr(smoke, "settings", SimpleNamespace(internal_job_token="x" * 32))

    def response(path: str, **_kwargs) -> dict:
        payload = healthy_payload(path)
        if path.endswith("reconcile-crm"):
            payload = payload | {"status": "attention_required", "missing_remote": 1}
        return payload

    monkeypatch.setattr(smoke, "request_json", response)

    with pytest.raises(RuntimeError, match="requires attention"):
        smoke.main()
