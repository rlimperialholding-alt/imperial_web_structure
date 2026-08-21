"""Fail-closed SSRF-védelemmel ellátott HTTP kliens (Platform Core).

Minden kérésre érvényesülő szabályok (nem prefix- vagy substring-egyezés):

1. A cél origin (scheme://host[:port]) csak az explicit allowlist pontos eleme lehet.
2. A host nem lehet metadata/blokkolt hostnév.
3. DNS/IP újraellenőrzés közvetlenül a kérés előtt:
   - https origin esetén minden feloldott cím csak publikus (``is_global``) lehet,
     így loopback, privát, link-local és metadata cél nem érhető el;
   - http origin kizárólag loopback vagy privát (RFC1918/ULA) címre oldódhat,
     ami a plaintext forgalom egyetlen, explicit fail-closed kivételhatára.
4. Redirect nem követhető vakon: minden ugrásra újra fut a teljes origin-, host-
   és IP-validáció; bármilyen szabálysértés leállítja a kérést (fail-closed).
5. Az URL útvonal csak biztonságos path-karaktereket tartalmazhat; ``..``,
   ``//``, backslash és kódolt traversal (``%2e``/``%2f``/``%5c``) tiltott.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx

REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
HTTP_SCHEMES = frozenset({"http", "https"})
MAX_PATH_LENGTH = 2048

BLOCKED_HOSTNAMES = frozenset(
    {
        "metadata",
        "metadata.google.internal",
        "instance-data",
        "instance-data.ec2.internal",
    }
)

_SAFE_PATH_RE = re.compile(r"[A-Za-z0-9._~!$&'()*+,;=:@%/-]+")
_ENCODED_TRAVERSAL_RE = re.compile(r"%2[ef]|%5c", re.IGNORECASE)

AddressResolver = Callable[[str, int], set[ipaddress.IPv4Address | ipaddress.IPv6Address]]


class SafeHttpError(ValueError):
    """Egy SSRF-politikai szabály megsértése miatt elutasított kérés."""


def resolve_addresses(host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        }
    except OSError as error:
        raise SafeHttpError(f"A host nem oldható fel biztonságosan: {host}") from error
    if not addresses:
        raise SafeHttpError(f"A host nem oldható fel biztonságosan: {host}")
    return addresses


def validate_url_path(path: object) -> str:
    """URL-útvonal validálása: csak biztonságos path-karakterek, traversal nélkül."""
    if not isinstance(path, str) or not path.startswith("/") or len(path) > MAX_PATH_LENGTH:
        raise SafeHttpError("Érvénytelen URL útvonal.")
    if _SAFE_PATH_RE.fullmatch(path) is None:
        raise SafeHttpError("Az URL útvonal tiltott karaktert tartalmaz.")
    if ".." in path or "//" in path or "\\" in path:
        raise SafeHttpError("Az URL útvonal traversal vagy abszolút hivatkozást tartalmaz.")
    if _ENCODED_TRAVERSAL_RE.search(path):
        raise SafeHttpError("Az URL útvonal kódolt traversalt tartalmaz.")
    return path


def _quoted_query(query: str) -> str:
    return quote(query, safe="=&%:@!$'()*+,;/?-._~")


def _check_url(
    url: str,
    *,
    allowed_origins: frozenset[str] | None,
    resolver: AddressResolver,
) -> str:
    """A teljes SSRF-politika érvényesítése egy URL-re; kanonikus URL-t ad vissza."""
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        raise SafeHttpError("Az URL vezérlőkaraktert tartalmaz.")
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme not in HTTP_SCHEMES or not parsed.hostname:
        raise SafeHttpError("Csak hiteles webes origin hívható.")
    if parsed.username is not None or parsed.password is not None:
        raise SafeHttpError("Az URL userinfo nem megengedett.")
    try:
        port = parsed.port
    except ValueError as error:
        raise SafeHttpError("Az URL portja érvénytelen.") from error
    host = parsed.hostname.lower().rstrip(".")
    if host in BLOCKED_HOSTNAMES or host.endswith(".local"):
        raise SafeHttpError("Metadata vagy belső host tiltott.")
    origin = urlunsplit((scheme, f"{host}{f':{port}' if port else ''}", "", "", ""))
    if allowed_origins is not None and origin not in allowed_origins:
        raise SafeHttpError("A cél origin nincs az engedélyezett listán.")
    addresses = resolver(host, port or (443 if scheme == "https" else 80))
    if scheme == "https":
        if any(not address.is_global for address in addresses):
            raise SafeHttpError(
                "A https cél nem kizárólag publikus címre oldódik "
                "(privát/loopback/link-local/metadata tiltott)."
            )
    elif any(
        not (address.is_private or address.is_loopback) or address.is_link_local
        for address in addresses
    ):
        # A Python 3.12 is_private definíciója magában foglalja a link-local
        # tartományt is, ezért a metadata-vektor (169.254.0.0/16, fe80::/10)
        # itt külön, explicit tiltásra kerül.
        raise SafeHttpError(
            "A http cél nem kizárólag belső címre oldódik "
            "(link-local/metadata tiltott); a plaintext hívás határa loopback/privát."
        )
    path = parsed.path or "/"
    if (
        _SAFE_PATH_RE.fullmatch(path) is None
        or ".." in path
        or "//" in path
        or "\\" in path
        or _ENCODED_TRAVERSAL_RE.search(path)
    ):
        raise SafeHttpError("Az URL útvonala nem biztonságos.")
    return urlunsplit((scheme, parsed.netloc.lower(), path, _quoted_query(parsed.query), ""))


class SafeHttpClient:
    """httpx kliens, amely minden kérést a SSRF-politika szerint validál.

    A ``transport`` és ``resolver`` paraméterek csak szintetikus, hálózatmentes
    tesztekben cserélhetők le; éles útvonalon a valódi DNS- és kapcsolatellenőrzés fut.
    """

    def __init__(
        self,
        base_url: str,
        *,
        allowed_origins: frozenset[str] | None = None,
        timeout: float = 45.0,
        transport: httpx.BaseTransport | None = None,
        resolver: AddressResolver | None = None,
        max_redirects: int = 3,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self._resolver: AddressResolver = resolver or resolve_addresses
        self._max_redirects = max(0, max_redirects)
        base = base_url.rstrip("/")
        parsed = urlsplit(base)
        self._scheme = parsed.scheme.lower()
        self._netloc = parsed.netloc.lower()
        self._base_path = parsed.path.rstrip("/")
        base_origin = urlunsplit((self._scheme, self._netloc, "", "", ""))
        self.allowed_origins = (
            frozenset(allowed_origins) if allowed_origins is not None else frozenset({base_origin})
        )
        if base_origin not in self.allowed_origins:
            raise SafeHttpError("A saját origin nem szerepel az engedélyezett listán.")
        _check_url(base, allowed_origins=self.allowed_origins, resolver=self._resolver)
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers=default_headers,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SafeHttpClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _send(
        self,
        method: str,
        url: str,
        *,
        redirects_left: int,
        kwargs: dict[str, Any],
    ) -> httpx.Response:
        canonical = _check_url(url, allowed_origins=self.allowed_origins, resolver=self._resolver)
        response = self._client.request(method, canonical, **kwargs)
        if response.status_code not in REDIRECT_STATUS:
            return response
        location = response.headers.get("location")
        if not location:
            raise SafeHttpError("Átirányítás cél nélkül; a kérés leállt.")
        if redirects_left <= 0:
            raise SafeHttpError("Túl sok átirányítás; a kérés leállt.")
        if response.status_code in {301, 302, 303}:
            next_method = "GET"
            next_kwargs = {key: value for key, value in kwargs.items() if key == "headers"}
        else:
            next_method = method
            next_kwargs = kwargs
        next_url = urljoin(canonical, location)
        return self._send(
            next_method, next_url, redirects_left=redirects_left - 1, kwargs=next_kwargs
        )

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        safe_path = validate_url_path(path)
        full_path = f"{self._base_path}{safe_path}"
        url = urlunsplit((self._scheme, self._netloc, full_path, "", ""))
        return self._send(method, url, redirects_left=self._max_redirects, kwargs=kwargs)

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)
