from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta

from app.models import MarketSourceSnapshot
from app.services.market_intelligence import (
    MarketActor,
    create_observation,
    create_pack,
    create_target,
    import_manual_snapshot,
    transition_pack,
    transition_target,
)


def _configure(monkeypatch, token: str, permissions: list[str]) -> None:
    registry = {
        "version": 1,
        "tokens": [
            {
                "tokenId": "mci-uat-reader",
                "tokenSha256": hashlib.sha256(token.encode()).hexdigest(),
                "subjectId": "service:mci-uat",
                "tenantId": "imperial-holding",
                "brandId": "imperial",
                "marketId": "HU",
                "permissions": permissions,
                "expiresAt": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        ],
    }
    monkeypatch.setenv("MARKET_SERVICE_API_ENABLED", "true")
    monkeypatch.setenv("MARKET_SERVICE_TOKENS", json.dumps(registry))


def test_market_service_api_is_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("MARKET_SERVICE_API_ENABLED", raising=False)
    response = client.get(
        "/api/v1/market-intelligence/source-targets",
        headers={"Authorization": "Bearer disabled-token"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "market_service_api_disabled"


def test_market_service_token_is_scope_bound_and_documented(client, db, monkeypatch):
    token = "mci-service-token-with-sufficient-entropy-for-uat"
    _configure(monkeypatch, token, ["read"])
    actor = MarketActor(
        subject_id="ITEP-MKT-TEST",
        tenant_id="imperial-holding",
        brand_id="imperial",
        market_id="HU",
        can_author=True,
    )
    target = create_target(
        db,
        actor=actor,
        name="Service API target",
        source_type="public_web",
        origin="https://service-api.example.test",
        allowed_path="/research",
        rights_status="PUBLIC_RESEARCH",
        capture_mode="manual",
    )
    foreign_actor = MarketActor(
        subject_id="ITEP-MKT-FOREIGN",
        tenant_id="imperial-holding",
        brand_id="other-brand",
        market_id="DE",
        can_author=True,
    )
    foreign_target = create_target(
        db,
        actor=foreign_actor,
        name="Foreign service API target",
        source_type="public_web",
        origin="https://foreign-service-api.example.test",
        allowed_path="/research",
        rights_status="PUBLIC_RESEARCH",
        capture_mode="manual",
    )

    assert client.get("/api/v1/market-intelligence/source-targets").status_code == 401
    assert (
        client.get(
            "/api/v1/market-intelligence/source-targets",
            headers={"Authorization": "Bearer wrong-token"},
        ).status_code
        == 401
    )
    response = client.get(
        "/api/v1/market-intelligence/source-targets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == {
        "tenantId": "imperial-holding",
        "brandId": "imperial",
        "marketId": "HU",
    }
    assert [item["targetId"] for item in payload["items"]] == [target["targetId"]]
    assert foreign_target["targetId"] not in {item["targetId"] for item in payload["items"]}

    denied = client.post(
        "/api/v1/market-intelligence/research-packs/MRP-NOT-USED/handoff",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "service-handoff-denied",
            "Content-Type": "application/json",
        },
        json={"downstreamPurpose": "copy_brief"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "service_token_scope_denied"

    openapi = client.get("/openapi.json").json()
    operation = openapi["paths"]["/api/v1/market-intelligence/source-targets"]["get"]
    assert operation["security"] == [{"MarketServiceBearer": []}]
    assert "Market Intelligence service API v1" in operation["tags"]


def test_market_service_handoff_is_hash_bound_and_idempotent(client, db, monkeypatch):
    token = "mci-service-handoff-token-with-sufficient-entropy"
    _configure(monkeypatch, token, ["read", "handoff"])
    author = MarketActor(
        "ITEP-MKT-SERVICE-AUTHOR",
        "imperial-holding",
        "imperial",
        "HU",
        can_author=True,
    )
    reviewer = MarketActor(
        "ITEP-MKT-SERVICE-REVIEWER",
        "imperial-holding",
        "imperial",
        "HU",
        can_review=True,
        can_freeze=True,
    )
    target = create_target(
        db,
        actor=author,
        name="Service handoff source",
        source_type="public_web",
        origin="https://handoff.example.test",
        allowed_path="/evidence",
        rights_status="PUBLIC_RESEARCH",
        capture_mode="manual",
    )
    target = transition_target(
        db,
        actor=author,
        target_id=target["targetId"],
        row_version=target["rowVersion"],
        action="submit_review",
    )
    target = transition_target(
        db,
        actor=reviewer,
        target_id=target["targetId"],
        row_version=target["rowVersion"],
        action="approve",
    )
    snapshot = import_manual_snapshot(
        db,
        actor=author,
        target_id=target["targetId"],
        resolved_url="https://handoff.example.test/evidence/1",
        mime_type="text/plain",
        content="Measured customer preference evidence for service handoff.",
        idempotency_key="service-handoff-snapshot",
    )
    observation = create_observation(
        db,
        actor=author,
        snapshot_id=snapshot["snapshotId"],
        statement="Customers prefer measurable evidence.",
        start_offset=0,
        end_offset=36,
        evidence_level="OBSERVED",
    )
    pack = create_pack(
        db,
        actor=author,
        title="Service handoff pack",
        summary="Hash-bound service API handoff proof.",
        intended_use="content_research_brief",
        channels=["website"],
        observation_ids=[observation["observationId"]],
    )
    pack = transition_pack(
        db,
        actor=author,
        pack_id=pack["packId"],
        row_version=pack["rowVersion"],
        action="submit_review",
    )
    pack = transition_pack(
        db,
        actor=reviewer,
        pack_id=pack["packId"],
        row_version=pack["rowVersion"],
        action="approve",
    )
    pack = transition_pack(
        db,
        actor=reviewer,
        pack_id=pack["packId"],
        row_version=pack["rowVersion"],
        action="freeze",
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "service-handoff-route-proof",
        "Content-Type": "application/json",
    }
    first = client.post(
        f"/api/v1/market-intelligence/research-packs/{pack['packId']}/handoff",
        headers=headers,
        json={"downstreamPurpose": "content_research_brief"},
    )
    replay = client.post(
        f"/api/v1/market-intelligence/research-packs/{pack['packId']}/handoff",
        headers=headers,
        json={"downstreamPurpose": "content_research_brief"},
    )
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["handoffId"] == first.json()["handoffId"]
    assert first.json()["status"] == "ACCEPTED"

    stored_snapshot = (
        db.query(MarketSourceSnapshot).filter_by(snapshot_id=snapshot["snapshotId"]).one()
    )
    stored_snapshot.encrypted_content = "invalid-ciphertext"
    db.commit()
    independent_list = client.get(
        "/api/v1/market-intelligence/source-targets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert independent_list.status_code == 200
    assert independent_list.json()["items"][0]["targetId"] == target["targetId"]


def test_market_service_registry_and_payload_limits_fail_closed(client, monkeypatch):
    token = "mci-duplicate-token-with-sufficient-entropy-value"
    _configure(monkeypatch, token, ["read", "handoff"])
    registry = json.loads(os.environ["MARKET_SERVICE_TOKENS"])
    registry["tokens"].append(dict(registry["tokens"][0]))
    monkeypatch.setenv("MARKET_SERVICE_TOKENS", json.dumps(registry))
    denied = client.get(
        "/api/v1/market-intelligence/source-targets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 401
    assert denied.json()["detail"]["code"] == "service_token_invalid"

    _configure(monkeypatch, token, ["handoff"])
    oversized = client.post(
        "/api/v1/market-intelligence/research-packs/MRP-NOT-USED/handoff",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "oversized-service-handoff",
            "Content-Type": "application/json",
            "Content-Length": "400001",
        },
        content=b"{}",
    )
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "request_too_large"
