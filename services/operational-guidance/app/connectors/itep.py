from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import httpx

from app.config import Settings


class ItepConnector:
    """Internal signed connector from Integration Hub to ITEP."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client

    def _signed_headers(self) -> dict[str, str]:
        now = int(time.time())
        payload = {
            "actorId": self.settings.itep_service_actor_id,
            "organizationId": self.settings.itep_organization_id,
            "roles": ["SYSTEM", "INTEGRATION_HUB"],
            "permissions": [
                "task.create",
                "task.read.all",
                "task.transition.all",
                "task.sensitive.legal",
                "task.sensitive.financial",
                "task.sensitive.authority",
                "task.sensitive.hr",
                "task.sensitive.confidential",
            ],
            "issuedAt": now,
            "expiresAt": now + 300,
            "nonce": str(uuid.uuid4()),
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        signature = hmac.new(
            self.settings.itep_identity_shared_secret.get_secret_value().encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-Imperial-Identity": encoded,
            "X-Imperial-Identity-Signature": signature,
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        client = self._client or httpx.AsyncClient(
            base_url=self.settings.itep_base_url,
            timeout=self.settings.itep_timeout_seconds,
        )
        close = self._client is None
        try:
            response = await client.request(
                method,
                path,
                headers={**self._signed_headers(), **kwargs.pop("headers", {})},
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        finally:
            if close:
                await client.aclose()

    async def readiness(self) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(
            base_url=self.settings.itep_base_url,
            timeout=self.settings.itep_timeout_seconds,
        )
        close = self._client is None
        try:
            response = await client.get("/health/ready")
            response.raise_for_status()
            return response.json()
        finally:
            if close:
                await client.aclose()

    async def dashboard(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/integration-control-room/dashboard")

    async def sync_live_crm(self) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/connectors/{self.settings.itep_crm_connector_id}/sync",
        )
