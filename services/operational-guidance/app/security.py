from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import Header, HTTPException, status

from app.config import get_settings


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def sign_body(
    body: bytes | str,
    secret: str,
    timestamp: int | None = None,
) -> tuple[str, str]:
    ts = str(timestamp or int(time.time()))
    body_bytes = body.encode() if isinstance(body, str) else body
    message = ts.encode() + b"." + body_bytes
    digest = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return ts, f"sha256={digest}"


def verify_body_signature(
    body: bytes | str,
    secret: str,
    timestamp: str,
    signature: str,
    tolerance_seconds: int = 300,
) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - ts) > tolerance_seconds:
        return False
    expected_ts, expected = sign_body(body, secret, timestamp=ts)
    return expected_ts == timestamp and hmac.compare_digest(expected, signature)


def sign_payload(
    payload: dict[str, Any],
    secret: str,
    timestamp: int | None = None,
) -> tuple[str, str]:
    return sign_body(canonical_json(payload), secret, timestamp)


def verify_signature(
    payload: dict[str, Any],
    secret: str,
    timestamp: str,
    signature: str,
    tolerance_seconds: int = 300,
) -> bool:
    return verify_body_signature(
        canonical_json(payload),
        secret,
        timestamp,
        signature,
        tolerance_seconds,
    )


def require_admin_token(
    authorization: str | None = Header(default=None),
    x_imperial_token: str = Header(default=""),
    x_admin_token: str = Header(default=""),
) -> None:
    from app.auth import _extract_bearer, authenticate_token

    settings = get_settings()
    actor = authenticate_token(
        _extract_bearer(authorization),
        settings,
        legacy_admin_token=x_imperial_token or x_admin_token,
    )
    if actor is None or (not actor.is_service and not actor.is_manager):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin or service token",
        )
