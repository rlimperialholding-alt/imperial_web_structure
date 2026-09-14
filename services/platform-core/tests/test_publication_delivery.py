from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import OutboxMessage, PublicationDelivery
from app.schemas import PublicationDeliveryClaimIn, PublicationDeliveryReceiptIn
from app.services.publication_delivery import (
    claim_publication_deliveries,
    record_publication_receipt,
    retry_publication_delivery,
    stage_publication_deliveries,
)


def _message(db, suffix: str, payload: dict) -> OutboxMessage:
    row = OutboxMessage(
        message_id=f"MSG-PUBDEL-{suffix}",
        destination_module="publication-adapter",
        payload_json="{}",
        status="pending",
        max_retries=2,
        next_attempt_at=datetime.now(UTC),
    )
    db.add(row)
    db.commit()
    return row


def _claim(target: str, adapter: str = "adapter-meta") -> PublicationDeliveryClaimIn:
    return PublicationDeliveryClaimIn(
        adapter_id=adapter, targets=[target], limit=10, lease_minutes=5
    )


def test_publication_delivery_claim_receipt_retry_and_idempotency(db):
    payload = {
        "action": "PUBLISH",
        "asset_id": "ASSET-DELIVERY-UAT",
        "publication_proof_id": "PROOF-DELIVERY-UAT",
        "publication_bundle_id": "BUNDLE-DELIVERY-UAT",
        "content_hash": "a" * 64,
    }
    validation = {
        "action": "PUBLISH",
        "adapter_contract": {
            "delivery_targets": ["META_ADS", "GOOGLE_ADS", "META_ADS"]
        },
        "validated": True,
    }
    message = _message(db, "PUBLISH", payload)
    rows = stage_publication_deliveries(db, message, payload, validation)
    db.commit()
    assert {row.target for row in rows} == {"META_ADS", "GOOGLE_ADS"}
    assert message.status == "staged"

    repeated = stage_publication_deliveries(db, message, payload, validation)
    db.commit()
    assert {row.delivery_id for row in repeated} == {row.delivery_id for row in rows}
    assert len(db.scalars(select(PublicationDelivery)).all()) == 2

    claimed = claim_publication_deliveries(db, _claim("META_ADS"))
    assert len(claimed) == 1
    delivery = claimed[0]
    assert delivery.status == "claimed" and delivery.attempt_count == 1
    with pytest.raises(ValueError, match="foglalást birtokló"):
        record_publication_receipt(
            db,
            delivery.delivery_id,
            PublicationDeliveryReceiptIn(
                adapter_id="adapter-google",
                idempotency_key=delivery.idempotency_key,
                payload_sha256=delivery.payload_sha256,
                status="delivered",
                external_reference="META-123",
                receipt={"provider_status": "ACTIVE"},
            ),
        )

    failed = record_publication_receipt(
        db,
        delivery.delivery_id,
        PublicationDeliveryReceiptIn(
            adapter_id="adapter-meta",
            idempotency_key=delivery.idempotency_key,
            payload_sha256=delivery.payload_sha256,
            status="failed",
            receipt={"provider_status": "RATE_LIMITED"},
            error_message="A szolgáltató átmeneti rate limit hibát adott.",
        ),
    )
    assert failed.status == "retry"
    failed.available_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    claimed_again = claim_publication_deliveries(db, _claim("META_ADS"))
    assert len(claimed_again) == 1 and claimed_again[0].attempt_count == 2
    delivered = record_publication_receipt(
        db,
        delivery.delivery_id,
        PublicationDeliveryReceiptIn(
            adapter_id="adapter-meta",
            idempotency_key=delivery.idempotency_key,
            payload_sha256=delivery.payload_sha256,
            status="delivered",
            external_reference="META-123",
            receipt={"provider_status": "ACTIVE"},
        ),
    )
    assert delivered.status == "delivered" and delivered.delivered_at is not None
    replay = record_publication_receipt(
        db,
        delivery.delivery_id,
        PublicationDeliveryReceiptIn(
            adapter_id="adapter-meta",
            idempotency_key=delivery.idempotency_key,
            payload_sha256=delivery.payload_sha256,
            status="delivered",
            external_reference="META-123",
            receipt={"provider_status": "ACTIVE"},
        ),
    )
    assert replay.delivery_id == delivered.delivery_id
    with pytest.raises(ValueError, match="nem módosítható"):
        record_publication_receipt(
            db,
            delivery.delivery_id,
            PublicationDeliveryReceiptIn(
                adapter_id="adapter-meta",
                idempotency_key=delivery.idempotency_key,
                payload_sha256=delivery.payload_sha256,
                status="delivered",
                external_reference="META-CONFLICT",
                receipt={"provider_status": "ACTIVE"},
            ),
        )


def test_pause_targets_prior_delivery_and_dead_letter_can_be_requeued(db):
    publish_payload = {
        "asset_id": "ASSET-PAUSE-UAT",
        "publication_proof_id": "PROOF-PAUSE-UAT",
    }
    publish_message = _message(db, "PAUSE-PUBLISH", publish_payload)
    stage_publication_deliveries(
        db,
        publish_message,
        publish_payload,
        {
            "action": "PUBLISH",
            "adapter_contract": {"delivery_targets": ["META_ADS"]},
        },
    )
    db.commit()
    pause_payload = {
        "action": "PAUSE_OR_UNPUBLISH",
        "asset_id": "ASSET-PAUSE-UAT",
        "publication_proof_id": "PROOF-PAUSE-UAT",
        "reason": ["Élő vizuális eltérés."],
        "automatic_republish_allowed": False,
    }
    pause_message = _message(db, "PAUSE", pause_payload)
    pause_rows = stage_publication_deliveries(
        db,
        pause_message,
        pause_payload,
        {"action": "PAUSE_OR_UNPUBLISH", "validated": True},
    )
    db.commit()
    assert len(pause_rows) == 1
    assert pause_rows[0].target == "META_ADS"
    assert pause_rows[0].action == "PAUSE_OR_UNPUBLISH"

    pause_rows[0].status = "dead_letter"
    pause_rows[0].last_error = "Tartós szolgáltatói hiba."
    db.commit()
    with pytest.raises(PermissionError):
        retry_publication_delivery(
            db,
            pause_rows[0].delivery_id,
            SimpleNamespace(role="sales", email="sales@imperial.local"),
            reason="Újraindítási kísérlet jogosultság nélkül.",
        )
    requeued = retry_publication_delivery(
        db,
        pause_rows[0].delivery_id,
        SimpleNamespace(role="marketing", email="marketing@imperial.local"),
        reason="A szolgáltatói incidens lezárult, az újraküldés engedélyezett.",
    )
    assert requeued.status == "ready" and requeued.attempt_count == 0


def test_delivery_operator_page_and_internal_adapter_api(logged_in_client, db):
    payload = {
        "action": "PUBLISH",
        "asset_id": "ASSET-ADAPTER-API",
        "publication_proof_id": "PROOF-ADAPTER-API",
    }
    message = _message(db, "ADAPTER-API", payload)
    rows = stage_publication_deliveries(
        db,
        message,
        payload,
        {
            "action": "PUBLISH",
            "adapter_contract": {"delivery_targets": ["GOOGLE_ADS"]},
        },
    )
    db.commit()

    page = logged_in_client.get("/marketing/deliveries")
    assert page.status_code == 200
    assert rows[0].delivery_id in page.text

    claim = logged_in_client.post(
        "/api/publication-adapter/deliveries/claim",
        json={
            "adapter_id": "adapter-google-api",
            "targets": ["GOOGLE_ADS"],
            "limit": 1,
            "lease_minutes": 5,
        },
    )
    assert claim.status_code == 200
    claimed = claim.json()["deliveries"][0]
    assert claimed["payload"] == payload

    receipt = logged_in_client.post(
        f"/api/publication-adapter/deliveries/{rows[0].delivery_id}/receipt",
        json={
            "adapter_id": "adapter-google-api",
            "idempotency_key": rows[0].idempotency_key,
            "payload_sha256": rows[0].payload_sha256,
            "status": "delivered",
            "external_reference": "GOOGLE-API-123",
            "receipt": {"provider_status": "ENABLED"},
        },
    )
    assert receipt.status_code == 200
    assert receipt.json()["status"] == "delivered"
