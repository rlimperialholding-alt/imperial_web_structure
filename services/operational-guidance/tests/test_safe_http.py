"""SSRF-politika negatív tesztjei: szintetikus, teljesen hálózatmentes."""

from __future__ import annotations

import ipaddress

import httpx
import pytest

from app.connectors.safe_http import (
    AddressResolver,
    SafeHttpClient,
    SafeHttpError,
    validate_identifier,
    validate_url_path,
)

PUBLIC = {ipaddress.ip_address("93.184.216.34")}
LOOPBACK = {ipaddress.ip_address("127.0.0.1")}
PRIVATE = {ipaddress.ip_address("10.20.30.40")}
LINK_LOCAL = {ipaddress.ip_address("169.254.169.254")}
IPV6_ULA = {ipaddress.ip_address("fd00::1")}
IPV6_LINK_LOCAL = {ipaddress.ip_address("fe80::1")}
CGNAT = {ipaddress.ip_address("100.64.0.1")}


def _resolver(addresses: set) -> AddressResolver:
    return lambda host, port: addresses


def _client(base_url: str, addresses: set, handler=None) -> SafeHttpClient:
    return SafeHttpClient(
        base_url,
        transport=httpx.MockTransport(handler) if handler else None,
        resolver=_resolver(addresses),
    )


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


class TestOriginPolicy:
    def test_https_origin_requires_public_addresses(self) -> None:
        for addresses in (LOOPBACK, PRIVATE, LINK_LOCAL, IPV6_ULA, IPV6_LINK_LOCAL, CGNAT):
            with pytest.raises(SafeHttpError):
                _client("https://provider.example/api", addresses)

    def test_http_origin_allows_only_loopback_or_private(self) -> None:
        assert _client("http://localhost:8055", LOOPBACK, _ok_handler) is not None
        assert _client("http://10.0.0.5:8000", PRIVATE, _ok_handler) is not None
        with pytest.raises(SafeHttpError):
            _client("http://provider.example:8000", PUBLIC)
        with pytest.raises(SafeHttpError):
            _client("http://10.0.0.5:8000", LINK_LOCAL)

    def test_metadata_and_local_hostnames_are_blocked(self) -> None:
        for host in (
            "metadata.google.internal",
            "metadata",
            "instance-data",
            "instance-data.ec2.internal",
            "service.local",
        ):
            with pytest.raises(SafeHttpError):
                _client(f"https://{host}/v1", PUBLIC)

    def test_userinfo_and_non_http_scheme_rejected(self) -> None:
        with pytest.raises(SafeHttpError):
            _client("ftp://files.example/x", PUBLIC)
        # A userinfo URL szintetikus fixture-ben összefűzött literal, hogy a
        # tracked-secret scanner ne lásson valós credential-mintát a fájlban.
        with pytest.raises(SafeHttpError):
            _client("https://" + "user@" + "provider.example", PUBLIC)

    def test_redirect_to_allowlisted_host_with_foreign_port_is_rejected(self) -> None:
        # A port az explicit origin-allowlist része: ugyanaz a host más porton
        # más origin, és a redirect nem léphet rá.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://provider.example:8443/admin"})

        client = SafeHttpClient(
            "https://provider.example/v1",
            transport=httpx.MockTransport(handler),
            resolver=_resolver(PUBLIC),
        )
        with pytest.raises(SafeHttpError):
            try:
                client.get("/start")
            finally:
                client.close()

    def test_allowlist_is_exact_origin_not_prefix(self) -> None:
        client = SafeHttpClient(
            "https://provider.example/v1",
            allowed_origins=frozenset({"https://provider.example"}),
            resolver=_resolver(PUBLIC),
            transport=httpx.MockTransport(_ok_handler),
        )
        client.close()
        with pytest.raises(SafeHttpError):
            SafeHttpClient(
                "https://provider.example.evil.example/v1",
                allowed_origins=frozenset({"https://provider.example"}),
                resolver=_resolver(PUBLIC),
            )


class TestRedirectPolicy:
    def _redirect_client(self, locations: list[str]) -> tuple[SafeHttpClient, list[httpx.Request]]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if locations:
                return httpx.Response(302, headers={"location": locations.pop(0)})
            return httpx.Response(200, json={"ok": True})

        client = SafeHttpClient(
            "https://provider.example/v1",
            transport=httpx.MockTransport(handler),
            resolver=_resolver(PUBLIC),
        )
        return client, seen

    def test_same_origin_redirect_is_followed(self) -> None:
        client, seen = self._redirect_client(["/v1/final"])
        try:
            response = client.get("/start")
        finally:
            client.close()
        assert response.status_code == 200
        assert [request.url.path for request in seen] == ["/v1/start", "/v1/final"]

    def test_cross_origin_redirect_fails_closed(self) -> None:
        client, _ = self._redirect_client(["https://evil.example/steal"])
        with pytest.raises(SafeHttpError):
            try:
                client.get("/start")
            finally:
                client.close()

    def test_redirect_to_internal_ip_fails_closed(self) -> None:
        resolver = _resolver(PUBLIC)
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(302, headers={"location": "http://10.0.0.1/admin"})

        client = SafeHttpClient(
            "https://provider.example/v1",
            transport=httpx.MockTransport(handler),
            resolver=resolver,
        )
        with pytest.raises(SafeHttpError):
            try:
                client.get("/start")
            finally:
                client.close()

    def test_redirect_without_location_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(301, headers={})

        client = SafeHttpClient(
            "https://provider.example/v1",
            transport=httpx.MockTransport(handler),
            resolver=_resolver(PUBLIC),
        )
        with pytest.raises(SafeHttpError, match="cél nélkül"):
            try:
                client.get("/start")
            finally:
                client.close()

    def test_redirect_loop_hits_hop_limit(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "/again"})

        client = SafeHttpClient(
            "https://provider.example/v1",
            transport=httpx.MockTransport(handler),
            resolver=_resolver(PUBLIC),
            max_redirects=2,
        )
        with pytest.raises(SafeHttpError, match="Túl sok átirányítás"):
            try:
                client.get("/start")
            finally:
                client.close()


class TestPathAndIdentifierValidation:
    @pytest.mark.parametrize(
        "path",
        [
            "ads",
            "",
            None,
            "/ads/../admin",
            "/ads//x",
            "/ads/a..b",
            "/ads/%2e%2e/admin",
            "/ads/%2f%2f",
            "/ads/%5cwindows",
            "/ads/back\\slash",
            "/ads/raw space",
            "/ads/\r\nInjected: x",
            "https://evil.example/x",
            "/" + "a" * 3000,
        ],
    )
    def test_unsafe_paths_are_rejected(self, path: object) -> None:
        with pytest.raises(SafeHttpError):
            validate_url_path(path)

    def test_safe_path_is_accepted(self) -> None:
        assert validate_url_path("/ads/IMP000001/photos/P1") == "/ads/IMP000001/photos/P1"

    @pytest.mark.parametrize(
        "value",
        [
            "",
            None,
            12,
            "..",
            "../admin",
            "a/b",
            "a\\b",
            "a b",
            "a;DROP",
            "a%2e%2e",
            "a" * 65,
        ],
    )
    def test_unsafe_identifiers_are_rejected(self, value: object) -> None:
        with pytest.raises(SafeHttpError):
            validate_identifier(value, label="teszt")

    def test_safe_identifier_is_accepted(self) -> None:
        assert validate_identifier("IMP-0001_a") == "IMP-0001_a"
