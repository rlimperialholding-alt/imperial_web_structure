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
- a DpmGateway ``query`` params-ja eljut a pinelt transportig.

Valódi hálózat sehol nincs; a resolverek determinisztikus szintetikus
címkészleteket adnak.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import replace

import httpx
import pytest

from app.config import settings
from app.services.dpm_gateway import DpmGateway
from app.services.safe_http import PinnedTransport, SafeHttpClient
from test_dpm_gateway import _HS256_FIXTURE, _resolver
from test_safe_http_pinning import _ScriptedBackend, _ScriptedSession

PUBLIC = ipaddress.ip_address("93.184.216.34")

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


class TestDpmParamsReachPinnedTransport:
    def _gateway(self, transport: httpx.BaseTransport) -> DpmGateway:
        return DpmGateway(
            replace(
                settings,
                dpm_api_base_url="http://digital-project-managers:8000",
                dpm_auth_issuer="imperial-intelligence",
                dpm_auth_audience="digital-project-managers",
                dpm_auth_hs256_secret=_HS256_FIXTURE,
            ),
            transport=transport,
            resolver=_resolver(),
        )

    def test_request_query_reaches_pinned_backend(self) -> None:
        session = _ScriptedSession([_json_response([])])
        pins: dict[tuple[str, int], tuple[str, ...]] = {}
        transport = _RecordingPinnedTransport(pins, backend=_ScriptedBackend(session))
        gateway = self._gateway(transport)
        result = gateway.request(
            "GET",
            "/api/v1/tasks",
            gateway.admin_identity("owner@example.test"),
            query={"project_id": "P-5001", "status": "open"},
        )
        assert result == []
        assert _request_lines(session) == [
            b"GET /api/v1/tasks?project_id=P-5001&status=open HTTP/1.1"
        ]
        # A target réteg bájtpontosan a httpx raw path + ?query sorát küldte.
        assert (
            _request_line_target(session)
            == transport.requests[0].url.raw_path
        )

    def test_request_without_query_has_no_question_mark(self) -> None:
        session = _ScriptedSession([_json_response([])])
        pins: dict[tuple[str, int], tuple[str, ...]] = {}
        transport = _RecordingPinnedTransport(pins, backend=_ScriptedBackend(session))
        gateway = self._gateway(transport)
        result = gateway.request(
            "GET",
            "/api/v1/agents",
            gateway.admin_identity("owner@example.test"),
        )
        assert result == []
        assert _request_lines(session) == [b"GET /api/v1/agents HTTP/1.1"]
