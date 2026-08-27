from __future__ import annotations

import time
from typing import Any

import httpx

from app.config import Settings
from app.security import canonical_json, sign_body


class WebsitePublisher:
    def __init__(self, settings: Settings):
        self.targets = settings.resolved_website_targets()

    def publish(self, website_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        target = self.targets.get(website_key)
        if not target:
            raise KeyError(f"Unknown website target: {website_key}")
        if not bool(target.get("enabled", True)):
            raise RuntimeError(f"Website target is registered but disabled: {website_key}")
        url = str(target.get("url", "")).strip()
        secret = str(target.get("secret", "")).strip()
        brand_key = str(target.get("brand_key") or payload.get("brand_key") or "").strip()
        if not url or not secret:
            raise ValueError(f"Website target is missing url or secret: {website_key}")
        if not brand_key:
            raise ValueError(f"Website target is missing brand_key: {website_key}")
        if payload.get("brand_key") != brand_key:
            raise PermissionError(f"Publication payload brand mismatch for target: {website_key}")

        body = canonical_json(payload)
        timestamp, signature = sign_body(body, secret)
        headers = {
            "Content-Type": "application/json",
            "X-Imperial-Timestamp": timestamp,
            "X-Imperial-Signature": signature,
            "X-Imperial-Website-Key": website_key,
            "X-Imperial-Brand-Key": brand_key,
        }

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=45) as client:
                    response = client.post(url, content=body, headers=headers)
                    response.raise_for_status()
                    if not response.content:
                        return {"ok": True, "status_code": response.status_code}
                    return dict(response.json())
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2**attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError("Publication failed without an HTTP response")
