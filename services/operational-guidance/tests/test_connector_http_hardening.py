"""Connector-szintű SSRF-negatív tesztek (szintetikus, hálózatmentes)."""

from __future__ import annotations

import ipaddress
from datetime import date
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.connectors.directus import DirectusConnector
from app.connectors.google_business import GoogleBusinessProfileConnector
from app.connectors.safe_http import AddressResolver, SafeHttpError

PUBLIC = ipaddress.ip_address("93.184.216.34")
LOOPBACK = ipaddress.ip_address("127.0.0.1")


def _settings() -> Settings:
    # Szintetikus, hitelesítés nélküli kapcsolat-URL; jelszószerű érték nem
    # szerepel a fájlban (a tracked-secret baseline ezért nem talál újat).
    return Settings(
        database_url="postgresql+psycopg://localhost/unused",
        directus_url="http://localhost:8055",
        directus_static_token="synthetic-directus-key",
    )


def _resolver() -> AddressResolver:
    return lambda host, port: {PUBLIC}


def _loopback_resolver() -> AddressResolver:
    # A local directus (http://localhost:8055) a loopback kivételhatárt teszteli.
    return lambda host, port: {LOOPBACK}


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"data": {"id": request.url.path}})


class _FakeCredentials:
    """Szintetikus credential-objektum: semmilyen valós providerhívás nem történik."""

    valid = True
    token = "synthetic-token"

    def refresh(self, request: Any) -> None:
        pass


class TestDirectusHardening:
    def test_content_id_traversal_is_rejected_before_any_request(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"data": {}})

        connector = DirectusConnector(
            _settings(), transport=httpx.MockTransport(handler), resolver=_loopback_resolver()
        )
        try:
            with pytest.raises(SafeHttpError):
                connector.get_content("../admin")
        finally:
            connector.client.close()
        assert seen == []

    def test_valid_content_id_is_sent(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(200, json={"data": {"id": 7}})

        connector = DirectusConnector(
            _settings(), transport=httpx.MockTransport(handler), resolver=_loopback_resolver()
        )
        try:
            result = connector.get_content("42")
        finally:
            connector.client.close()
        assert result == {"id": 7}
        assert paths == ["/items/content_items/42"]


class TestGoogleBusinessHardening:
    def _connector(
        self, handler=None, monkeypatch: pytest.MonkeyPatch | None = None
    ) -> GoogleBusinessProfileConnector:
        # A valódi OAuth-credential-gyárat szintetikusra cseréljük; valós
        # providerhívás vagy credential-felhasználás nem történik.
        if monkeypatch is not None:
            monkeypatch.setattr(
                "app.connectors.google_business.business_profile_user_credentials",
                lambda settings: _FakeCredentials(),
            )
        return GoogleBusinessProfileConnector(
            _settings(),
            transport=httpx.MockTransport(handler) if handler else None,
            resolver=_resolver(),
        )

    def test_non_numeric_account_id_is_rejected(self, monkeypatch) -> None:
        with pytest.raises(ValueError, match="azonosító"):
            self._connector(_ok_handler, monkeypatch).list_locations(
                "accounts/../../evil"
            )

    def test_location_id_with_traversal_is_rejected(self, monkeypatch) -> None:
        with pytest.raises(ValueError, match="azonosító"):
            self._connector(_ok_handler, monkeypatch).fetch(
                "locations/../evil", date(2026, 1, 1), date(2026, 1, 31)
            )

    def test_valid_numeric_ids_are_sent_to_google_origin(self, monkeypatch) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"multiDailyMetricTimeSeries": []})

        result = self._connector(handler, monkeypatch).fetch(
            "locations/123456", date(2026, 1, 1), date(2026, 1, 31)
        )
        assert result == []
        assert requests and requests[0].url.host == "businessprofileperformance.googleapis.com"
        assert "locations/123456" in requests[0].url.path
