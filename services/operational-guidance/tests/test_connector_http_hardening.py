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
from synthetic_fixtures import synthetic_auth_value

PUBLIC = ipaddress.ip_address("93.184.216.34")
LOOPBACK = ipaddress.ip_address("127.0.0.1")


def _settings() -> Settings:
    # Szintetikus, hitelesítés nélküli kapcsolat-URL; a statikus-fixture érték
    # futásidőben, a közös synthetic factoryból képződik, így credential-szerű
    # literál nem szerepel a diffben (a tracked-secret baseline ezért nem talál
    # újat).
    fixture = synthetic_auth_value("og", "directus", "static")
    return Settings(
        database_url="postgresql+psycopg://localhost/unused",
        directus_url="http://localhost:8055",
        directus_static_token=fixture,
    )


def _resolver() -> AddressResolver:
    return lambda host, port: {PUBLIC}


def _loopback_resolver() -> AddressResolver:
    # A local directus (http://localhost:8055) a loopback kivételhatárt teszteli.
    return lambda host, port: {LOOPBACK}


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"data": {"id": request.url.path}})


def _fake_auth() -> str:
    """Futásidőben képzett synthetic auth-fixture a közös factoryból."""
    return synthetic_auth_value("og", "google", "fake")


class _FakeCredentials:
    """Szintetikus credential-objektum: semmilyen valós providerhívás nem történik."""

    valid = True
    token = _fake_auth()

    def refresh(self, request: Any) -> None:
        pass


class _CloseTrackingTransport(httpx.BaseTransport):
    """Szintetikus transport, amely a ``close()`` hívásokat számlálja.

    A DirectusConnector lifecycle-tesztjei ezzel bizonyítják, hogy a kliens
    normál és kivételes úton is pontosan egyszer zárul, és a duplikált
    ``close()`` nem okoz újabb lezárási kísérletet.
    """

    def __init__(self, handler) -> None:
        self._handler = handler
        self.close_calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)

    def close(self) -> None:
        self.close_calls += 1


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
            connector.close()
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
            connector.close()
        assert result == {"id": 7}
        assert paths == ["/items/content_items/42"]


class TestDirectusLifecycle:
    """A DirectusConnector explicit close()/context-manager életciklusa.

    A kliens erőforrásai pontosan egyszer szabadulnak fel normál és
    kivételes úton egyaránt; a duplikált close() idempotens, ``__del__``-re
    a lifecycle nem támaszkodik.
    """

    def _connector(
        self, handler=None
    ) -> tuple[DirectusConnector, _CloseTrackingTransport]:
        transport = _CloseTrackingTransport(handler or _ok_handler)
        connector = DirectusConnector(
            _settings(), transport=transport, resolver=_loopback_resolver()
        )
        return connector, transport

    def test_close_is_idempotent_and_closes_exactly_once(self) -> None:
        connector, transport = self._connector()
        assert transport.close_calls == 0
        connector.close()
        assert transport.close_calls == 1
        # A második close() nem okoz újabb lezárási kísérletet.
        connector.close()
        connector.close()
        assert transport.close_calls == 1

    def test_context_manager_closes_on_normal_exit(self) -> None:
        connector, transport = self._connector()
        with connector:
            result = connector.get_content("42")
        assert result == {"id": "/items/content_items/42"}
        assert transport.close_calls == 1

    def test_context_manager_closes_on_exception(self) -> None:
        connector, transport = self._connector()
        with pytest.raises(RuntimeError):
            with connector:
                raise RuntimeError("szintetikus üzleti hiba")
        assert transport.close_calls == 1

    def test_context_manager_closes_when_the_request_itself_fails(self) -> None:
        def failing_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("szintetikus kapcsolódási hiba")

        transport = _CloseTrackingTransport(failing_handler)
        connector = DirectusConnector(
            _settings(), transport=transport, resolver=_loopback_resolver()
        )
        with pytest.raises(httpx.ConnectError):
            with connector:
                connector.get_content("42")
        assert transport.close_calls == 1

    def test_close_before_any_request_is_safe(self) -> None:
        connector, transport = self._connector()
        connector.close()
        connector.close()
        assert transport.close_calls == 1


class TestDirectusWebsiteKeyContract:
    """A website_key üzleti contractja 64 karakter (DB String(64)).

    A PublicationJob.website_key oszlop és a 431439b9fde5 migráció
    String(64)-et rögzít; a validátor határa ezzel konzisztens, ezért a
    65. karaktertől fail-closed elutasítás történik, kérés nélkül.
    """

    def _connector_with_seen(self) -> tuple[DirectusConnector, list[httpx.Request]]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"data": [{"id": 1}]})

        connector = DirectusConnector(
            _settings(), transport=httpx.MockTransport(handler), resolver=_loopback_resolver()
        )
        return connector, seen

    def test_64_char_website_key_is_accepted(self) -> None:
        connector, seen = self._connector_with_seen()
        try:
            result = connector.get_website("k" * 64)
        finally:
            connector.close()
        assert result == {"id": 1}
        assert len(seen) == 1

    def test_65_char_website_key_fails_closed_without_request(self) -> None:
        connector, seen = self._connector_with_seen()
        try:
            with pytest.raises(SafeHttpError):
                connector.get_website("k" * 65)
        finally:
            connector.close()
        assert seen == []


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


class TestGoogleResourceIdContract:
    """A ``_google_id`` decimális-only szerződés explicit rögzítése.

    A repo-szerződés (connector-tesztek, README discovery-leírás formátum-
    állítás nélkül) a numerikus alakot igazolja; alfanumerikus formátumot
    előíró hiteles helyi bizonyíték nincs, ezért a viselkedés nem változik,
    csak expliciten rögzített és dokumentált. Részletek és a szélesítési
    döntési kapu: ``app/connectors/google_business.py`` modul-docstring.
    """

    def test_numeric_account_location_and_review_ids_are_accepted(self) -> None:
        assert (
            GoogleBusinessProfileConnector._google_id("123456789", "accounts") == "123456789"
        )
        assert (
            GoogleBusinessProfileConnector._google_id("locations/987654321", "locations")
            == "987654321"
        )
        assert GoogleBusinessProfileConnector._google_id("reviews/42", "reviews") == "42"
        assert GoogleBusinessProfileConnector._google_id("0", "accounts") == "0"

    def test_max_30_digit_id_is_accepted(self) -> None:
        value = "9" * 30
        assert GoogleBusinessProfileConnector._google_id(value, "accounts") == value

    def test_alphanumeric_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="azonosító"):
            GoogleBusinessProfileConnector._google_id("accounts/ABC123", "accounts")

    def test_empty_ids_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="azonosító"):
            GoogleBusinessProfileConnector._google_id("", "locations")
        with pytest.raises(ValueError, match="azonosító"):
            GoogleBusinessProfileConnector._google_id("accounts/", "accounts")

    def test_oversized_and_traversal_ids_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="azonosító"):
            GoogleBusinessProfileConnector._google_id("1" * 31, "accounts")
        with pytest.raises(ValueError, match="azonosító"):
            GoogleBusinessProfileConnector._google_id("accounts/../evil", "accounts")
