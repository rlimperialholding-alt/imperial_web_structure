from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.config import Settings


class DisabledExternalAdapter:
    def __init__(self, name: str):
        self.name = name

    def invoke(
        self,
        *,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        del action, payload, idempotency_key
        raise RuntimeError(f"{self.name} adapter is not configured for external writes")


class HttpExternalAdapter:
    def __init__(
        self,
        name: str,
        base_url: str,
        token_file: Path,
        timeout_seconds: float = 15.0,
    ):
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._token_file = token_file
        self._timeout_seconds = timeout_seconds

    def invoke(
        self,
        *,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        token = self._token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError(f"{self.name} credential secret is empty")
        response = httpx.post(
            f"{self._base_url}/actions/{action}",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": idempotency_key,
                "User-Agent": "imperial-digital-pm/0.2.0",
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError(f"{self.name} returned a non-object response")
        return body


class ExternalAdapterRegistry:
    NAMES = ("partner-control", "tender-portal", "myimperial", "email")

    def __init__(self, settings: Settings):
        self._adapters = {
            "partner-control": self._build(
                settings,
                "partner-control",
                settings.partner_control_base_url,
                settings.partner_control_token_file,
            ),
            "tender-portal": self._build(
                settings,
                "tender-portal",
                settings.tender_portal_base_url,
                settings.tender_portal_token_file,
            ),
            "myimperial": self._build(
                settings,
                "myimperial",
                settings.myimperial_base_url,
                settings.myimperial_token_file,
            ),
            "email": self._build(
                settings,
                "email",
                settings.email_service_base_url,
                settings.email_service_token_file,
            ),
        }

    @staticmethod
    def _build(
        settings: Settings,
        name: str,
        base_url: str | None,
        token_file: Path | None,
    ) -> DisabledExternalAdapter | HttpExternalAdapter:
        if (
            not settings.external_writes_enabled
            or not base_url
            or token_file is None
            or not token_file.is_file()
        ):
            return DisabledExternalAdapter(name)
        return HttpExternalAdapter(name, base_url, token_file)

    def get(self, name: str) -> DisabledExternalAdapter | HttpExternalAdapter:
        try:
            return self._adapters[name]
        except KeyError as error:
            raise KeyError(f"Unknown external adapter: {name}") from error
