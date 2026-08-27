import time

from app.security import sign_payload, verify_signature


def test_signature_roundtrip() -> None:
    payload = {"content_id": "abc", "paths": ["/", "/akciok"], "content": {"b": 2, "a": 1}}
    timestamp, signature = sign_payload(payload, "top-secret", timestamp=int(time.time()))
    assert verify_signature(payload, "top-secret", timestamp, signature)


def test_signature_rejects_tampering() -> None:
    payload = {"content_id": "abc", "price": 100}
    timestamp, signature = sign_payload(payload, "top-secret", timestamp=int(time.time()))
    payload["price"] = 101
    assert not verify_signature(payload, "top-secret", timestamp, signature)


def test_signature_rejects_stale_request() -> None:
    payload = {"content_id": "abc"}
    timestamp, signature = sign_payload(payload, "top-secret", timestamp=int(time.time()) - 1000)
    assert not verify_signature(payload, "top-secret", timestamp, signature)


def test_directus_webhook_accepts_scalar_key() -> None:
    from app.schemas import DirectusWebhookEvent

    event = DirectusWebhookEvent(
        event="items.update",
        collection="content_items",
        keys="content-123",
        payload={"status": "approved"},
    )

    assert event.keys == ["content-123"]


def test_raw_body_signature_handles_decimal_representation() -> None:
    from app.security import sign_body, verify_body_signature

    body = '{"price":1.0,"title":"Árgarancia"}'
    timestamp, signature = sign_body(body, "top-secret", timestamp=int(time.time()))

    assert verify_body_signature(body, "top-secret", timestamp, signature)
    assert not verify_body_signature(
        '{"price":1,"title":"Árgarancia"}',
        "top-secret",
        timestamp,
        signature,
    )
