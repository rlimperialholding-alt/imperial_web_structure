"""Pinned transport query-string regressziók: bájtpontos target-átadás.

A tesztek a pinelt hálózati backend által rögzített nyers HTTP/1.1
kérésbájtokat (a tényleges kapcsolati határt, nem MockTransportot)
ellenőrzik, és bizonyítják, hogy:

- query nélküli URL esetén a request-targetben nincs ``?``;
- egy params kulcs, ismétlődő kulcsok, percent-encoded és Unicode értékek
  bájtpontosan, a httpx által felépített kódolással kerülnek a kérésbe;
- a transport nem dekódol és nem kódol újra: a backendnek küldött target
  pontosan az httpx raw path + opcionális ``?`` + raw query bájt sor,
  dupla ``?``, sorrend- vagy kódolásváltozás nélkül;
- a Directus ``fields`` és a Google Business ``fetch`` params query-ja
  eljut a pinelt transportig.

Valódi hálózat sehol nincs; a resolverek determinisztikus szintetikus
címkészleteket adnak.
"""

from __future__ import annotations

import ipaddress
import json
from datetime import date

import httpx
import pytest
from test_connector_http_hardening import (
    _FakeCredentials,
    _loopback_resolver,
    _resolver,
    _settings,
)
from test_safe_http_pinning import _ScriptedBackend, _ScriptedSession

from app.connectors.directus import DirectusConnector
from app.connectors.google_business import GoogleBusinessProfileConnector
from app.connectors.safe_http import PinnedTransport, SafeHttpClient

PUBLIC = ipaddress.ip_address("93.184.216.34")
PUBLIC_SECOND = ipaddress.ip_address("1.1.1.1")

RESPONSE_OK = b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\n\r\n"


def _json_response(payload: object) -> bytes:
    """HTTP/1.1 200 válasz JSON törzzsel, pontos content-length-szel."""
    body = json.dumps(payload).encode("utf-8")
    return (
        b"HTTP/1.1 200 OK\r\n"
        b"content-type: application/json\r\n"
        + f"content-length: {len(body)}\r\n".encode("ascii")
        + b"\r\n"
        + body
    )


def _request_lines(session: _ScriptedSession) -> list[bytes]:
    """A rögzített nyers kérésbájtokból a HTTP request line-ok kinyerése."""
    raw = b"".join(session.request_bytes)
    return [line for line in raw.split(b"\r\n") if line.endswith(b" HTTP/1.1")]


def _request_line_target(session: _ScriptedSession) -> bytes:
    return _request_lines(session)[0].split(b" ", 2)[1]


class _RecordingPinnedTransport(PinnedTransport):
    """PinnedTransport, amely rögzíti a kapott httpx.Request példányokat.

    A rögzített URL-ből a teszt a transportnak átadott raw targetet
    ellenőrzi: a backendhez eljutó bájtoknak pontosan a
    ``raw_path`` (path + opcionális ``?`` + query) bájt sorral kell
    egyezniük — dekódolás/újrakódolás vagy dupla ``?`` nélkül.
    """

    def __init__(self, pins: dict, *, backend: object) -> None:
        super().__init__(pins, backend=backend)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return super().handle_request(request)


def _pinned_client(
    session: _ScriptedSession,
) -> tuple[SafeHttpClient, _RecordingPinnedTransport]:
    pins: dict[tuple[str, int], tuple[str, ...]] = {}
    transport = _RecordingPinnedTransport(pins, backend=_ScriptedBackend(session))
    client = SafeHttpClient(
        "https://provider.example/v1",
        resolver=lambda host, port: {PUBLIC},
        transport=transport,
    )
    return client, transport


@pytest.mark.parametrize(
    ("path", "params", "expected_target"),
    [
        pytest.param("/search", None, b"/v1/search", id="no-query"),
        pytest.param("/items", {}, b"/v1/items", id="empty-params"),
        pytest.param(
            "/items",
            {"fields": "*"},
            # A ``*`` a httpx params-kódolásában %2A alakú; a transport ezt
            # bájtpontosan adja tovább.
            b"/v1/items?fields=%2A",
            id="single-key",
        ),
        pytest.param(
            "/items",
            [("tag", "a"), ("tag", "b")],
            b"/v1/items?tag=a&tag=b",
            id="duplicate-keys",
        ),
        pytest.param(
            "/items",
            {"q": "árvíz"},
            b"/v1/items?q=%C3%A1rv%C3%ADz",
            id="unicode-value",
        ),
        pytest.param(
            "/items",
            {"filter": "a%2Fb"},
            # A literal ``%`` a httpx params-kódolásában egyszeres %25-re
            # kódolódik; a transport ezt bájtpontosan adja tovább (a target
            # rétegben nincs további dekódolás/újrakódolás).
            b"/v1/items?filter=a%252Fb",
            id="percent-literal-encoded-once",
        ),
    ],
)
class TestPinnedTransportQueryTarget:
    def test_query_is_forwarded_byte_exactly(
        self, path: str, params: object, expected_target: bytes
    ) -> None:
        session = _ScriptedSession([RESPONSE_OK])
        client, transport = _pinned_client(session)
        try:
            response = client.get(path, params=params)
            response.close()
        finally:
            client.close()
        assert _request_lines(session) == [b"GET " + expected_target + b" HTTP/1.1"]
        # A transport-szintű invariáns: a backendnek küldött target pontosan a
        # httpx által felépített raw path + opcionális ?query; nincs dupla ?
        # és nincs dekódolás/újrakódolás a target rétegben.
        recorded = transport.requests[0].url
        assert _request_line_target(session) == recorded.raw_path
        assert b"??" not in recorded.raw_path


class TestDirectusFieldsQueryReachesPinnedTransport:
    def test_get_content_fields_query_reaches_pinned_backend(self) -> None:
        session = _ScriptedSession([_json_response({"data": {"id": "42"}})])
        pins: dict[tuple[str, int], tuple[str, ...]] = {}
        transport = _RecordingPinnedTransport(pins, backend=_ScriptedBackend(session))
        connector = DirectusConnector(
            _settings(), transport=transport, resolver=_loopback_resolver()
        )
        with connector:
            result = connector.get_content("42")
        assert result == {"id": "42"}
        assert _request_lines(session) == [
            b"GET /items/content_items/42?fields=%2A HTTP/1.1"
        ]


class TestGoogleBusinessParamsReachPinnedTransport:
    def test_fetch_daily_metrics_query_reaches_pinned_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A valódi OAuth-credential-gyárat szintetikusra cseréljük; valós
        # providerhívás vagy credential-felhasználás nem történik.
        monkeypatch.setattr(
            "app.connectors.google_business.business_profile_user_credentials",
            lambda settings: _FakeCredentials(),
        )
        session = _ScriptedSession([_json_response({"multiDailyMetricTimeSeries": []})])
        pins: dict[tuple[str, int], tuple[str, ...]] = {}
        transport = _RecordingPinnedTransport(pins, backend=_ScriptedBackend(session))
        connector = GoogleBusinessProfileConnector(
            _settings(), transport=transport, resolver=_resolver()
        )
        rows = connector.fetch("locations/123456", date(2026, 1, 1), date(2026, 1, 31))
        assert rows == []
        expected = (
            b"GET /v1/locations/123456:fetchMultiDailyMetricsTimeSeries?"
            b"dailyMetrics=BUSINESS_IMPRESSIONS_DESKTOP_MAPS&"
            b"dailyMetrics=BUSINESS_IMPRESSIONS_DESKTOP_SEARCH&"
            b"dailyMetrics=BUSINESS_IMPRESSIONS_MOBILE_MAPS&"
            b"dailyMetrics=BUSINESS_IMPRESSIONS_MOBILE_SEARCH&"
            b"dailyMetrics=WEBSITE_CLICKS&"
            b"dailyMetrics=CALL_CLICKS&"
            b"dailyMetrics=BUSINESS_DIRECTION_REQUESTS&"
            b"dailyRange.start_date.year=2026&"
            b"dailyRange.start_date.month=1&"
            b"dailyRange.start_date.day=1&"
            b"dailyRange.end_date.year=2026&"
            b"dailyRange.end_date.month=1&"
            b"dailyRange.end_date.day=31"
            b" HTTP/1.1"
        )
        assert _request_lines(session) == [expected]
        # Az ismétlődő dailyMetrics kulcsok és a paramétersorrend bájtpontosan
        # megmaradt; a target réteg nem alakít át semmit.
        assert (
            _request_line_target(session)
            == transport.requests[0].url.raw_path
        )


class TestQueryAcrossPinnedRedirectHop:
    def test_first_hop_query_is_byte_exact_before_redirect(self) -> None:
        # A pinelt kapcsolaton átmenő, query-t hordozó kérés az átirányítás
        # ELŐTTI ugrásban bájtpontosan eléri a backendet. A 302 utáni GET
        # a SafeHttpClient redirect-szerződése szerint nem viszi tovább a
        # params-ot (kwargs->headers), ezért a második ugrás query nélküli.
        redirect = (
            b"HTTP/1.1 302 Found\r\n"
            b"location: https://cdn.example/x\r\n"
            b"content-length: 0\r\n\r\n"
        )
        session = _ScriptedSession([redirect, RESPONSE_OK])

        def resolver(host: str, port: int) -> set:
            return {PUBLIC_SECOND} if host == "cdn.example" else {PUBLIC}

        pins: dict[tuple[str, int], tuple[str, ...]] = {}
        transport = _RecordingPinnedTransport(pins, backend=_ScriptedBackend(session))
        client = SafeHttpClient(
            "https://provider.example/v1",
            resolver=resolver,
            transport=transport,
            allowed_origins=frozenset(
                {"https://provider.example", "https://cdn.example"}
            ),
        )
        try:
            response = client.get("/start", params=[("tag", "a"), ("tag", "b")])
            response.close()
        finally:
            client.close()
        assert _request_lines(session) == [
            b"GET /v1/start?tag=a&tag=b HTTP/1.1",
            b"GET /x HTTP/1.1",
        ]
