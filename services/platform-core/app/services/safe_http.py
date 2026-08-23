"""Fail-closed SSRF-védelemmel ellátott HTTP kliens (Platform Core).

Minden kérésre érvényesülő szabályok (nem prefix- vagy substring-egyezés):

1. A cél origin (scheme://host[:port]) csak az explicit allowlist pontos eleme lehet.
2. A host nem lehet metadata/blokkolt hostnév.
3. DNS/IP újraellenőrzés közvetlenül a kérés előtt:
   - https origin esetén minden feloldott cím csak publikus (``is_global``) lehet,
     így loopback, privát, link-local és metadata cél nem érhető el;
   - http origin kizárólag loopback vagy privát (RFC1918/ULA) címre oldódhat,
     ami a plaintext forgalom egyetlen, explicit fail-closed kivételhatára.
4. **A kapcsolat a validált IP-re kötődik (DNS-rebinding/TOCTOU ellen lezárva):**
   az ellenőrzés során feloldott címkészletet ugyanaz a kérés pineli a
   ``PinnedTransport`` hálózati backendjébe; a tényleges TCP-kapcsolat csak a
   validált címre mehet, új DNS-feloldás nélkül. A TLS SNI és a tanúsítvány-
   ellenőrzés az eredeti hostnévvel fut (a httpcore a pool-origin hostnevét
   adja a ``start_tls``-nek, függetlenül a TCP-céltól), a Host fejléc pedig az
   eredeti hostnevet tartalmazza.
5. Redirect nem követhető vakon: minden ugrásra újra fut a teljes origin-,
   host- és IP-validáció, és az új célra új pinelés érvényes; bármilyen
   szabálysértés leállítja a kérést (fail-closed).
6. Az URL útvonal csak biztonságos path-karaktereket tartalmazhat; ``..``,
   ``//``, backslash és kódolt traversal (``%2e``/``%2f``/``%5c``) tiltott.
7. A klienst környezeti proxy nem befolyásolja: a pinelt transport proxy
   nélkül csatlakozik, mert egy proxy saját, validálatlan DNS-feloldást
   végezne, ami a pinelést megkerülné.

A ``transport`` és ``resolver`` paraméterek csak szintetikus, hálózatmentes
tesztekben cserélhetők le; éles útvonalon a valódi DNS- és kapcsolatellenőrzés fut.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any, cast
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpcore
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
PinsMap = dict[tuple[str, int], tuple[str, ...]]

# httpcore -> httpx kivételtérkép, az httpx beépített transportjával azonos
# szemantikával, hogy a hívó réteg ``httpx.HTTPError``-ként lássa a hibákat.
_HTTPCORE_EXCEPTION_MAP: dict[type[BaseException], type[httpx.HTTPError]] = {
    httpcore.TimeoutException: httpx.TimeoutException,
    httpcore.ConnectTimeout: httpx.ConnectTimeout,
    httpcore.ReadTimeout: httpx.ReadTimeout,
    httpcore.WriteTimeout: httpx.WriteTimeout,
    httpcore.PoolTimeout: httpx.PoolTimeout,
    httpcore.NetworkError: httpx.NetworkError,
    httpcore.ConnectError: httpx.ConnectError,
    httpcore.ReadError: httpx.ReadError,
    httpcore.WriteError: httpx.WriteError,
    httpcore.ProxyError: httpx.ProxyError,
    httpcore.ProtocolError: httpx.ProtocolError,
    httpcore.LocalProtocolError: httpx.LocalProtocolError,
    httpcore.RemoteProtocolError: httpx.RemoteProtocolError,
    httpcore.UnsupportedProtocol: httpx.UnsupportedProtocol,
}


@contextmanager
def _map_httpcore_exceptions() -> Iterator[None]:
    try:
        yield
    except Exception as error:  # noqa: BLE001 - a térkép nem érinti az ismeretlen hibákat
        mapped_type = _HTTPCORE_EXCEPTION_MAP.get(type(error))
        if mapped_type is None:
            raise
        raise mapped_type(str(error)) from error


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


def _ordered_candidates(
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address],
) -> tuple[str, ...]:
    """Determinisztikus kapcsolati sorrend: IPv4 előbb, majd numerikus sorrend.

    A készlet minden eleme ugyanabban a validációs lépésben ment át az
    SSRF-politikán, így a sorrend csak a kapcsolódás hatékonyságát érinti.
    """
    ordered = sorted(addresses, key=lambda item: (item.version, int(item)))
    return tuple(str(item) for item in ordered)


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
) -> tuple[str, set[ipaddress.IPv4Address | ipaddress.IPv6Address]]:
    """A teljes SSRF-politika érvényesítése egy URL-re.

    Kanonikus URL-t és a kapcsolat szintjén pinelendő, validált címkészletet
    ad vissza; a hívó ugyanezt a készletet adja át a kapcsolati rétegnek,
    így az ellenőrzés és a tényleges kapcsolat között nincs második DNS-feloldás.
    """
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
    effective_port = port or (443 if scheme == "https" else 80)
    addresses = resolver(host, effective_port)
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
    canonical = urlunsplit((scheme, parsed.netloc.lower(), path, _quoted_query(parsed.query), ""))
    return canonical, addresses


class _PinnedNetworkBackend(httpcore.NetworkBackend):
    """Hálózati backend, amely csak előre validált IP-címekre köt TCP-t.

    A ``connect_tcp`` (host, port) kulcsához az ellenőrzés során rögzített,
    ugyanazon validált címkészlet tartozik; a kapcsolat nem végez új
    DNS-feloldást. Validálatlan célra irányuló kapcsolódási kísérlet
    fail-closed hibát ad (így környezeti proxy vagy más megkerülés sem tud
    a pinelt réteg mellett kapcsolódni). A validált címkészleten belül egy
    connect- vagy timeout-hibás cím után a következő validált cím
    próbálkozik; a záró hiba oka az utolsó hiba marad.
    """

    def __init__(
        self,
        delegate: httpcore.NetworkBackend,
        pins: PinsMap,
    ) -> None:
        self._delegate = delegate
        self._pins = pins

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.NetworkStream:
        pinned = self._pins.get((host, port))
        if not pinned:
            raise SafeHttpError(
                f"A kapcsolati cél IP-validáció nélkül maradt: {host}:{port}"
            )
        last_error: Exception | None = None
        for target in pinned:
            try:
                return self._delegate.connect_tcp(
                    target,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (
                OSError,
                httpcore.ConnectError,
                httpcore.ConnectTimeout,
                httpcore.TimeoutException,
            ) as error:
                # Az httpcore connect- és timeout-hibái (a ConnectTimeout a
                # TimeoutException leszármazottja) nem OSError típusúak, ezért
                # itt explicit módon kezeljük őket: egy validált cím
                # időtúllépése után a következő validált cím próbálkozik;
                # a ciklus a validált listán kívülre nem léphet.
                last_error = error
        assert last_error is not None
        raise httpcore.ConnectError(
            f"A validált cél egyik címére sem sikerült csatlakozni: {host}:{port}"
        ) from last_error

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.NetworkStream:
        raise SafeHttpError("Unix socket kapcsolat nem engedélyezett a SSRF-politikában.")

    def sleep(self, seconds: float) -> None:
        self._delegate.sleep(seconds)


class PinnedTransport(httpx.BaseTransport):
    """httpx-transport, amely a validált IP-re köt, hostnév-SNI/Host megőrzéssel.

    A belső httpcore pool ``network_backend``-je a pinelt backend; a TLS-réteg
    a pool origin-hostnevét kapja ``server_hostname``-ként (SNI és tanúsítvány-
    ellenőrzés az eredeti hostnévvel), miközben a TCP-cél a validált IP.
    A transport szándékosan proxy-mentes: környezeti proxyval a kapcsolat a
    proxyn keresztül, validálatlan DNS-feloldással menne.
    """

    def __init__(
        self,
        pins: PinsMap,
        *,
        backend: httpcore.NetworkBackend | None = None,
    ) -> None:
        self.pins = pins
        ssl_context = httpx.create_ssl_context(verify=True, cert=None, trust_env=True)
        network_backend: httpcore.NetworkBackend = (
            backend if backend is not None else httpcore.SyncBackend()
        )
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl_context,
            max_connections=10,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_PinnedNetworkBackend(network_backend, pins),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        httpcore_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        with _map_httpcore_exceptions():
            response = self._pool.handle_request(httpcore_request)
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_SafeResponseStream(cast(Iterable[bytes], response.stream)),
            extensions=response.extensions,
        )

    def close(self) -> None:
        self._pool.close()


class _SafeResponseStream(httpx.SyncByteStream):
    """httpcore-válaszstream az httpx által elvárt SyncByteStream-protokollal."""

    def __init__(self, stream: Iterable[bytes]) -> None:
        self._stream = stream

    def __iter__(self) -> Iterator[bytes]:
        with _map_httpcore_exceptions():
            yield from self._stream

    def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if close is not None:
            with _map_httpcore_exceptions():
                close()

    def __enter__(self) -> _SafeResponseStream:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class SafeHttpClient:
    """httpx kliens, amely minden kérést a SSRF-politika szerint validál.

    A ``transport`` és ``resolver`` paraméterek csak szintetikus, hálózatmentes
    tesztekben cserélhetők le; éles útvonalon a pinelt transport és a valódi
    DNS-ellenőrzés fut.
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
        self._pins: PinsMap = {}
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
        self._pinned_transport: PinnedTransport | None
        if transport is not None:
            # Szintetikus teszt-transport: MockTransport esetén nincs pinelés
            # (a hálózati réteg soha nem érhető el); PinnedTransport esetén a
            # szintetikus backendkel futó pinelés tesztelhető.
            if isinstance(transport, PinnedTransport):
                self._pinned_transport = transport
            else:
                self._pinned_transport = None
            self._transport = transport
        else:
            self._pinned_transport = PinnedTransport(self._pins)
            self._transport = self._pinned_transport
        self._client = httpx.Client(
            timeout=timeout,
            transport=self._transport,
            follow_redirects=False,
            headers=default_headers,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SafeHttpClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _pin(
        self,
        host: str,
        port: int,
        addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address],
    ) -> None:
        # Csak a pinelt transport esetén van értelme a pinelésnek; a szintetikus
        # teszt-transport sosem végez hálózati kapcsolatot. A pin a transport
        # saját térképébe kerül, amelyre a kapcsolati backend mutat.
        if self._pinned_transport is not None:
            self._pinned_transport.pins[(host, port)] = _ordered_candidates(addresses)

    def _send(
        self,
        method: str,
        url: str,
        *,
        redirects_left: int,
        kwargs: dict[str, Any],
    ) -> httpx.Response:
        canonical, addresses = _check_url(
            url, allowed_origins=self.allowed_origins, resolver=self._resolver
        )
        parsed = urlsplit(canonical)
        assert parsed.hostname is not None  # A _check_url garantálja.
        effective_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        # Ugyanaz a validált címkészlet kerül a kapcsolati rétegbe, amelyet a
        # _check_url ellenőrzött: az ellenőrzés és a kapcsolat között nincs
        # második DNS-feloldás (DNS-rebinding TOCTOU lezárva).
        self._pin(parsed.hostname, effective_port, addresses)
        response = self._client.request(method, canonical, **kwargs)
        if response.status_code not in REDIRECT_STATUS:
            return response
        location = response.headers.get("location")
        if not location:
            response.close()
            raise SafeHttpError("Átirányítás cél nélkül; a kérés leállt.")
        if redirects_left <= 0:
            response.close()
            raise SafeHttpError("Túl sok átirányítás; a kérés leállt.")
        if response.status_code in {301, 302, 303}:
            next_method = "GET"
            next_kwargs = {key: value for key, value in kwargs.items() if key == "headers"}
        else:
            next_method = method
            next_kwargs = kwargs
        next_url = urljoin(canonical, location)
        response.close()
        # Minden ugrásra új, teljes fail-closed URL- és IP-ellenőrzés fut,
        # és az új célra új pinelés érvényes.
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
