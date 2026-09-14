from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.connectors.itep import ItepConnector


@pytest.mark.asyncio
async def test_itep_connector_signs_and_calls_dashboard():
    observed: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["payload"] = request.headers["X-Imperial-Identity"]
        observed["signature"] = request.headers["X-Imperial-Identity-Signature"]
        return httpx.Response(200, json={"totals": {"connectors": 1}})

    settings = Settings(
        app_env="test",
        itep_base_url="https://itep.test",
        itep_identity_shared_secret=SecretStr("x" * 40),
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://itep.test",
    ) as client:
        result = await ItepConnector(settings, client).dashboard()

    expected = hmac.new(
        b"x" * 40,
        observed["payload"].encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    assert hmac.compare_digest(expected, observed["signature"])
    decoded = json.loads(
        base64.urlsafe_b64decode(
            observed["payload"] + "=" * (-len(observed["payload"]) % 4)
        ).decode("utf-8")
    )
    assert decoded["actorId"] == "integration-hub"
    assert result["totals"]["connectors"] == 1
