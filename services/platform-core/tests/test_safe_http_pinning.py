"""DNS-rebinding/TOCTOU pinning tesztek: szintetikus, teljesen hálózatmentes.

A tesztek egy szkriptelt fake backenddel bizonyítják, hogy:

- a tényleges TCP-kapcsolat mindig a validációs lépésben feloldott IP-re megy,
  a kapcsolódás soha nem végez új DNS-feloldást (eltérő első/második DNS-válasz
  esetén a rosszindulatú második feloldás nem befolyásolhatja a kapcsolatot);
- a TLS SNI/tanúsítvány-ellenőrzés és a Host fejléc az eredeti hostnevet
  használja akkor is, ha a TCP-cél a feloldott IP;
- metadata-, loopback-, privát-, link-local címre (IPv4 és IPv6) a kérés
  fail-closed leáll, kapcsolódás nélkül;
- minden redirect ugrás új URL- és IP-validációt és új pinelést kap;
- több A/AAAA rekord esetén a sorrend determinisztikus (IPv4 előbb), és egy
  cím sikertelensége esetén a következő validált cím próbálkozik.
"""

from __future__ import annotations

import ipaddress

import pytest

from app.services.safe_http import (
    AddressResolver,
    PinnedTransport,
    SafeHttpClient,
    SafeHttpError,
    _PinnedNetworkBackend,
)

PUBLIC_V4 = ipaddress.ip_address("93.184.216.34")
PUBLIC_V6 = ipaddress.ip_address("2606:2800:220:1:248:1893:25c8:1946")
INTERNAL = ipaddress.ip_address("10.0.0.1")
METADATA = ipaddress.ip_address("169.254.169.254")
LOOPBACK = ipaddress.ip_address("127.0.0.1")
ULA = ipaddress.ip_address("fd00::1")
LINK_LOCAL_V6 = ipaddress.ip_address("fe80::1")

RESPONSE_OK = b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\n\r\n"
RESPONSE_JSON_OK = b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\n{}"


class _ScriptedSession:
    """Determinisztikus, hálózatmentes HTTP/1.1 munkamenet-váz.

    Minden ``connect`` egy új szkriptelt választ kap; a felvétel rögzíti a
    TCP-célt, a TLS ``server_hostname`` értéket és a nyers kérésbájtokat.
    """

    def __init__(self, responses: list[bytes]) -> None:
        self._responses = list(responses)
        self.connected: list[tuple[str, int]] = []
        self.sni_hostnames: list[str | None] = []
        self.request_bytes: list[bytes] = []

    def pop_response(self) -> bytes:
        return self._responses.pop(0) if self._responses else RESPONSE_OK

    def connect(self, host: str, port: int) -> _ScriptedStream:
        self.connected.append((host, port))
        return _ScriptedStream(self)


class _ScriptedStream:
    def __init__(self, session: _ScriptedSession) -> None:
        self._session = session
        self._response = session.pop_response()
        self._sent = False

    def write(self, data: bytes, timeout: float | None = None) -> None:
        self._session.request_bytes.append(data)

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if not self._sent:
            self._sent = True
            return self._response
        return b""

    def start_tls(
        self, ssl_context: object, server_hostname: str | None, timeout: float | None = None
    ) -> _ScriptedStream:
        self._session.sni_hostnames.append(server_hostname)
        return self

    def get_extra_info(self, info: str, default: object = None) -> object:
        if info == "is_readable":
            return True
        return default

    def close(self) -> None:
        pass


class _ScriptedBackend:
    """Fake hálózati backend: csak a szkriptelt munkamenetbe köt, DNS nélkül."""

    def __init__(self, session: _ScriptedSession) -> None:
        self._session = session

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> _ScriptedStream:
        return self._session.connect(host, port)

    def connect_unix_socket(self, *args: object) -> _ScriptedStream:
        raise AssertionError("A SSRF-politika sosem használ unix socketet.")

    def sleep(self, seconds: float) -> None:
        pass


class _FailingIpv4Backend(_ScriptedBackend):
    """Az IPv4 címre szimulált hibát ad, az IPv6 célra viszont csatlakozik."""

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> _ScriptedStream:
        self._session.connected.append((host, port))
        if host == str(PUBLIC_V4):
            raise OSError(f"szimulált kapcsolódási hiba: {host}")
        return _ScriptedStream(self._session)


def _pinned_client(
    session: _ScriptedSession,
    resolver: AddressResolver,
    base_url: str = "https://provider.example/v1",
    allowed_origins: frozenset[str] | None = None,
    backend: object | None = None,
) -> SafeHttpClient:
    pins: dict[tuple[str, int], tuple[str, ...]] = {}
    transport = PinnedTransport(pins, backend=backend or _ScriptedBackend(session))
    return SafeHttpClient(
        base_url,
        resolver=resolver,
        transport=transport,
        allowed_origins=allowed_origins,
    )


class TestConnectionIpBinding:
    def test_connection_uses_validated_ip_without_second_dns_lookup(self) -> None:
        # Eltérő DNS-válaszok: az 1. (constructor) és 2. (kérés) feloldás
        # publikus; egy hipotetikus 3. feloldás már belső címre mutatna.
        # A pinelés miatt a 3. feloldás soha nem következhet be, és a TCP
        # a validált publikus IP-re megy, az eredeti hostnévvel a TLS-ben.
        calls: list[tuple[str, int]] = []

        def flip_resolver(host: str, port: int) -> set:
            calls.append((host, port))
            if len(calls) <= 2:
                return {PUBLIC_V4}
            return {INTERNAL}

        session = _ScriptedSession([RESPONSE_OK])
        client = _pinned_client(session, flip_resolver)
        try:
            response = client.get("/start")
        finally:
            client.close()
        assert response.status_code == 200
        response.close()
        assert calls == [("provider.example", 443), ("provider.example", 443)]
        assert session.connected == [(str(PUBLIC_V4), 443)]
        assert session.sni_hostnames == ["provider.example"]
        raw_request = b"".join(session.request_bytes)
        assert b"host: provider.example" in raw_request.lower()

    def test_second_dns_response_pointing_internal_fails_closed(self) -> None:
        # Az 1. feloldás publikus (constructor), a 2. (kérés előtti validáció)
        # már belső címre mutat: a kérés elutasul, kapcsolat nem jön létre.
        calls: list[tuple[str, int]] = []

        def resolver(host: str, port: int) -> set:
            calls.append((host, port))
            return {PUBLIC_V4} if len(calls) == 1 else {INTERNAL}

        session = _ScriptedSession([RESPONSE_OK])
        client = _pinned_client(session, resolver)
        with pytest.raises(SafeHttpError):
            client.get("/start")
        assert session.connected == []
        assert len(calls) == 2

    def test_second_dns_response_pointing_public_but_different_is_safe(self) -> None:
        # A második feloldás más publikus címre mutat: a kapcsolat mindenképp
        # a saját validációs lépésben kapott címre kötődik (determinisztikus).
        second_public = ipaddress.ip_address("1.1.1.1")
        calls: list[tuple[str, int]] = []

        def resolver(host: str, port: int) -> set:
            calls.append((host, port))
            return {PUBLIC_V4} if len(calls) == 1 else {second_public}

        session = _ScriptedSession([RESPONSE_OK])
        client = _pinned_client(session, resolver)
        try:
            response = client.get("/start")
            response.close()
        finally:
            client.close()
        assert session.connected == [(str(second_public), 443)]
        assert len(calls) == 2


class TestAddressPolicyBeforeConnection:
    @pytest.mark.parametrize(
        "address",
        [METADATA, LOOPBACK, INTERNAL, ULA, LINK_LOCAL_V6],
        ids=["metadata", "loopback", "private", "ipv6-ula", "ipv6-link-local"],
    )
    def test_https_origin_to_non_global_address_fails_closed(self, address) -> None:
        # A nem-publikus célra a kliens már a létrehozáskor fail-closed hibát ad,
        # így semmilyen kapcsolat nem jöhet létre.
        session = _ScriptedSession([RESPONSE_OK])
        with pytest.raises(SafeHttpError):
            _pinned_client(session, lambda host, port: {address})
        assert session.connected == []

    def test_mixed_public_and_ula_resolution_is_rejected(self) -> None:
        # Vegyes publikus + ULA feloldás esetén a teljes készlet elutasul.
        session = _ScriptedSession([RESPONSE_OK])
        with pytest.raises(SafeHttpError):
            _pinned_client(session, lambda host, port: {PUBLIC_V4, ULA})
        assert session.connected == []

    def test_unpinned_connect_attempt_fails_closed(self) -> None:
        # Validáció nélküli (host, port) célra a pinelt backend nem csatlakozhat:
        # ez zárja ki a pinelés bármilyen megkerülését a kapcsolati rétegben.
        backend = _PinnedNetworkBackend(_ScriptedBackend(_ScriptedSession([])), {})
        with pytest.raises(SafeHttpError):
            backend.connect_tcp("evil.example", 443)


class TestMultiRecordAndFamilies:
    def test_multiple_a_and_aaaa_records_connect_in_deterministic_order(self) -> None:
        session = _ScriptedSession([RESPONSE_OK])
        client = _pinned_client(session, lambda host, port: {PUBLIC_V6, PUBLIC_V4})
        try:
            response = client.get("/start")
            response.close()
        finally:
            client.close()
        assert session.connected == [(str(PUBLIC_V4), 443)]

    def test_failed_ipv4_candidate_falls_back_to_validated_ipv6(self) -> None:
        # Több A/AAAA rekord: ha az első validált cím elérhetetlen, a második
        # validált cím próbálkozik; a sorrend determinisztikus (IPv4 -> IPv6).
        session = _ScriptedSession([RESPONSE_OK])
        pins: dict[tuple[str, int], tuple[str, ...]] = {}
        transport = PinnedTransport(
            pins, backend=_FailingIpv4Backend(session)
        )
        client = SafeHttpClient(
            "https://provider.example/v1",
            resolver=lambda host, port: {PUBLIC_V4, PUBLIC_V6},
            transport=transport,
        )
        try:
            response = client.get("/start")
            response.close()
        finally:
            client.close()
        assert session.connected == [(str(PUBLIC_V4), 443), (str(PUBLIC_V6), 443)]


class TestRedirectPinning:
    REDIRECT = (
        b"HTTP/1.1 302 Found\r\n"
        b"location: https://cdn.example/x\r\n"
        b"content-length: 0\r\n\r\n"
    )

    def _redirect_client(
        self, session: _ScriptedSession
    ) -> tuple[SafeHttpClient, list[tuple[str, int]]]:
        cdn_public = ipaddress.ip_address("1.1.1.1")
        calls: list[tuple[str, int]] = []

        def resolver(host: str, port: int) -> set:
            calls.append((host, port))
            if host == "cdn.example":
                # A rosszindulatú második feloldás a cdn hostra belső címet adna;
                # pineléssel ez a feloldás nem következik be.
                return {cdn_public} if calls.count(("cdn.example", port)) <= 1 else {INTERNAL}
            return {PUBLIC_V4}

        client = _pinned_client(
            session,
            resolver,
            allowed_origins=frozenset(
                {"https://provider.example", "https://cdn.example"}
            ),
        )
        return client, calls

    def test_every_redirect_hop_gets_new_validation_and_pinning(self) -> None:
        session = _ScriptedSession([self.REDIRECT, RESPONSE_JSON_OK])
        client, calls = self._redirect_client(session)
        try:
            response = client.get("/start")
            assert response.status_code == 200
            assert response.json() == {}
            response.close()
        finally:
            client.close()
        assert session.connected == [(str(PUBLIC_V4), 443), ("1.1.1.1", 443)]
        assert session.sni_hostnames == ["provider.example", "cdn.example"]
        assert len(calls) == 3  # constructor + 1. ugrás + 2. ugrás

    def test_redirect_hop_whose_target_resolves_internal_fails_closed(self) -> None:
        def resolver(host: str, port: int) -> set:
            if host == "cdn.example":
                return {INTERNAL}
            return {PUBLIC_V4}

        session = _ScriptedSession([self.REDIRECT, RESPONSE_OK])
        pins: dict[tuple[str, int], tuple[str, ...]] = {}
        transport = PinnedTransport(pins, backend=_ScriptedBackend(session))
        client = SafeHttpClient(
            "https://provider.example/v1",
            resolver=resolver,
            transport=transport,
            allowed_origins=frozenset(
                {"https://provider.example", "https://cdn.example"}
            ),
        )
        with pytest.raises(SafeHttpError):
            client.get("/start")
        assert session.connected == [(str(PUBLIC_V4), 443)]
