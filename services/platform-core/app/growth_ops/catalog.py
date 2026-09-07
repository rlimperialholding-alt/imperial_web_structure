from __future__ import annotations

import base64
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import time as monotonic_time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from uuid import uuid4
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..audit import audit
from ..land_acquisition.registry import (
    LandRegistryError,
    PortalRegistry,
    is_named_portal_host,
    same_named_portal_binding,
)
from ..models import AuditLog
from .canonical_policy import (
    DAILY_UNIQUE_LEAD_MINIMUM,
    SOURCE_LEDGER_ROUTE_COUNT,
    SOURCE_LEDGER_SHEET_ID,
    SOURCE_LEDGER_SPREADSHEET_ID,
    contains_no_monitoring_entity,
)
from .models import (
    GrowthPublicLandListingCursor,
    GrowthSignal,
    SourceCatalogRevision,
    SourceCoverageAttempt,
    SourceCoverageRoute,
)
from .public_land import is_specific_listing_permalink, process_public_land_listings
from .registry import GrowthRegistryError, settings

BLOCKED_MARKERS = (
    "captcha",
    "access denied",
    "too many requests",
    "paywall",
)

LOGIN_PATH_MARKERS = (
    "/bejelentkezes",
    "/bejelentkezés",
    "/belepes",
    "/belépés",
    "/login",
    "/sign-in",
    "/signin",
)

QUESTION_SURFACE_ROUTE_OVERRIDES = {
    # The canonical ledger keeps the marketplace homepages. These deterministic
    # overlays point one route per surface at the public question/task listing,
    # without removing the separate homepage coverage routes.
    "SRC-0001": "https://joszaki.hu/szakivalaszol",
    "SRC-0002": "https://qjob.hu/budapest/munka/epitesz-munka",
    "EVB-06834": "https://qjob.hu/budapest/munka/epitomernok-allas",
}

# The canonical route ledger contains several search-engine URLs for forum
# discovery.  Those URLs are not reliable source pages: Google commonly
# redirects the worker to a consent page and the resulting page has no
# question evidence.  Keep the ledger immutable, but add a small, explicit
# overlay for the public Hungarian question surface that can be fetched and
# revalidated directly.  The concrete question permalinks are extracted from
# these category pages and fetched separately before they reach the extractor.
QUESTION_RADAR_DIRECT_ROUTES = (
    {
        "route_key": "QUESTION-RADAR:GYAKORI-EPITKEZES-NELKUL",
        "route_id": "QR-GYAKORI-EPITKEZES-NELKUL",
        "source_name": "Gyakori Kérdések – Építkezés – válasz nélkül",
        "route_url": "https://www.gyakorikerdesek.hu/otthon__epitkezes__valasz-nelkul",
        "search_signal": "építkezés; kivitelező; házépítés; tetőtér; költség",
        "brand_fit": "BauFreund,Bautica,Prefab",
    },
    {
        "route_key": "QUESTION-RADAR:GYAKORI-FELUJITAS-NELKUL",
        "route_id": "QR-GYAKORI-FELUJITAS-NELKUL",
        "source_name": "Gyakori Kérdések – Felújítás – válasz nélkül",
        "route_url": "https://www.gyakorikerdesek.hu/otthon__felujitas__valasz-nelkul",
        "search_signal": "felújítás; szakember; ár; kivitelező",
        "brand_fit": "BauFreund,Bautica",
    },
    {
        "route_key": "QUESTION-RADAR:INDEX-FORUM-TOPICLIST",
        "route_id": "QR-INDEX-FORUM-TOPICLIST",
        "source_name": "Index Fórum – témalisták",
        "route_url": "https://forum.index.hu/Topic/showTopicList?t=52",
        "search_signal": "építkezés; felújítás; kivitelező; tetőtér; költség",
        "brand_fit": "BauFreund,Bautica,Prefab",
    },
    {
        "route_key": "QUESTION-RADAR:PROHARDVER-FELUJITAS",
        "route_id": "QR-PROHARDVER-FELUJITAS",
        "source_name": "Prohardver – Lakásfelújító és szakemberkereső fórum",
        "route_url": (
            "https://prohardver.hu/tema/lakasfelujito_szerelo_szakemberkereso_nagy_topic_"
            "viz_gaz_villany_futes_festes_burkolas_stb/friss.html"
        ),
        "search_signal": "felújítás; szakember; víz; gáz; villany; festés; burkolás",
        "brand_fit": "BauFreund,Bautica",
    },
    {
        "route_key": "QUESTION-RADAR:REDDIT-HUNGARY-RSS",
        "route_id": "QR-REDDIT-HUNGARY-RSS",
        "source_name": "Reddit r/hungary – új bejegyzések",
        "route_url": "https://www.reddit.com/r/hungary/new/.rss?limit=25",
        "search_signal": "építkezés; felújítás; ingatlan; kivitelező",
        "brand_fit": "BauFreund,Bautica,Prefab",
    },
    {
        "route_key": "QUESTION-RADAR:REDDIT-ASKHUNGARY-RSS",
        "route_id": "QR-REDDIT-ASKHUNGARY-RSS",
        "source_name": "Reddit r/askhungary – új bejegyzések",
        "route_url": "https://www.reddit.com/r/askhungary/new/.rss?limit=25",
        "search_signal": "építkezés; felújítás; szakember; ár; ingatlan",
        "brand_fit": "BauFreund,Bautica,Prefab",
    },
    {
        "route_key": "QUESTION-RADAR:REDDIT-KISZAMOLO-RSS",
        "route_id": "QR-REDDIT-KISZAMOLO-RSS",
        "source_name": "Reddit r/kiszamolo – új bejegyzések",
        "route_url": "https://www.reddit.com/r/kiszamolo/new/.rss?limit=25",
        "search_signal": "felújítás; építkezés; költség; hitel; ingatlan",
        "brand_fit": "BauFreund,Bautica",
    },
    {
        "route_key": "QUESTION-RADAR:REDDIT-LAKOKOZOSSEG-RSS",
        "route_id": "QR-REDDIT-LAKOKOZOSSEG-RSS",
        "source_name": "Reddit r/lakokozosseg – új bejegyzések",
        "route_url": "https://www.reddit.com/r/lakokozosseg/new/.rss?limit=25",
        "search_signal": "építkezés; felújítás; munkadíj; kivitelező; garázs",
        "brand_fit": "BauFreund,Bautica,Prefab",
    },
    {
        "route_key": "QUESTION-RADAR:FORUM-DISCOVERY-CONSTRUCTION",
        "route_id": "QR-FORUM-DISCOVERY-CONSTRUCTION",
        "source_name": "Automatikus fórumfelfedezés – építkezés",
        "route_url": (
            "https://lite.duckduckgo.com/lite/?q=epitkezes+forum"
        ),
        "search_signal": "építkezés; kivitelező; házépítés; tetőtér; fórum",
        "brand_fit": "BauFreund,Bautica,Prefab",
    },
    {
        "route_key": "QUESTION-RADAR:FORUM-DISCOVERY-RENOVATION",
        "route_id": "QR-FORUM-DISCOVERY-RENOVATION",
        "source_name": "Automatikus fórumfelfedezés – felújítás",
        "route_url": (
            "https://lite.duckduckgo.com/lite/?q=felujitas+forum"
        ),
        "search_signal": "felújítás; szakember; kivitelező; költség; fórum",
        "brand_fit": "BauFreund,Bautica,Prefab",
    },
    {
        "route_key": "QUESTION-RADAR:FORUM-DISCOVERY-PURCHASE",
        "route_id": "QR-FORUM-DISCOVERY-PURCHASE",
        "source_name": "Automatikus fórumfelfedezés – vásárlási jelzések",
        "route_url": (
            "https://www.bing.com/search?"
            "q=megbizhato+kivitelezo+ajanlas+arajanlat+epitkezes"
        ),
        "search_signal": "megbízható kivitelező; ajánlás; árajánlat; építkezés",
        "brand_fit": "BauFreund,Bautica,Prefab",
    },
)

QUESTION_RADAR_DISCOVERY_ROUTE_PREFIX = "QUESTION-RADAR:FORUM-DISCOVERY-"
QUESTION_RADAR_DISCOVERED_ROUTE_PREFIX = "QUESTION-RADAR:DISCOVERED:"
_SEARCH_ENGINE_HOSTS = {
    "bing.com",
    "www.bing.com",
    "google.com",
    "www.google.com",
    "search.yahoo.com",
    "duckduckgo.com",
    "html.duckduckgo.com",
    "lite.duckduckgo.com",
}
_FORUM_RELEVANCE_MARKERS = (
    "épít",
    "epit",
    "felúj",
    "feluj",
    "kivitelez",
    "szakember",
    "tetőtér",
    "tetoter",
    "ház",
    "haz",
    "ingatlan",
    "lakás",
    "lakas",
    "költ",
    "kolt",
    "ár",
    "ajanl",
    "ajánl",
    "forum",
    "fórum",
    "reddit",
    "gyakorikerdesek",
    "index.hu",
)
_FORUM_CONTENT_MARKERS = tuple(
    marker
    for marker in _FORUM_RELEVANCE_MARKERS
    if marker not in {"forum", "fórum", "reddit", "gyakorikerdesek", "index.hu"}
)
_FORUM_PATH_MARKERS = (
    "comment",
    "discussion",
    "forum",
    "kerdes",
    "kérdés",
    "question",
    "post",
    "thread",
    "topic",
    "tema",
    "téma",
    "showarticle",
    "showthread",
)

# A Gyakori Kérdések kategóriaoldalán rendszerint több tucat konkrét kérdés
# szerepel. Ezek mindegyikének a saját oldaláról kell a dátumot és a válasz-
# állapotot visszaolvasni; a többi fórumnál megmarad a kisebb, óvatosabb keret.
QUESTION_RADAR_GYAKORI_REPLY_PAGE_MAXIMUM = 50

# The canonical ledger still contains the legacy `/lista` address, which the
# portal's current robots policy disallows. Keep the immutable source row for
# audit, but fetch the equivalent public route that robots.txt permits.
LAND_PUBLIC_HTML_ROUTE_OVERRIDES = {
    "SRC-0012": "https://ingatlan.com/elado+telek",
}
ROUTE_URL_OVERRIDES = {
    **QUESTION_SURFACE_ROUTE_OVERRIDES,
    **LAND_PUBLIC_HTML_ROUTE_OVERRIDES,
}

DAILY_ROUTE_ATTEMPT_MAXIMUM = 2_000
LAND_PUBLIC_HTML_LISTING_FETCH_MAXIMUM = 10
LAND_PUBLIC_HTML_LISTING_DAILY_ROUTE_BUDGET = 300
LAND_PUBLIC_HTML_PAGINATION_PAGE_MAXIMUM = 1_000
LAND_PUBLIC_HTML_ROUTE_PREFIX = "LAND-PUBLIC-HTML:"
LAND_RECIPIENT_POLICY_VERSION = "LAND-RECIPIENT-ROLE-EMAIL-V1"
PORTAL_PUBLIC_HTML_USER_AGENT = (
    "Imperial-Land-PublicHTML/1.0 (+https://imperialholding.hu; info@imperialholding.hu)"
)
ROBOTS_CACHE_SECONDS = 21_600
ROBOTS_MAX_BYTES = 256_000
_ROBOTS_CACHE: dict[str, tuple[float, list[str] | None, str | None]] = {}
_ROBOTS_CACHE_LOCK = Lock()

BUILDING_ACQUISITION_SCOPE_VERSION = "2026-08-28-building-v2.16"

_PROCUREMENT_MARKERS = (
    "ausschreibung",
    "award notice",
    "beszerzes",
    "framework award",
    "kozbeszerzes",
    "obstaravanie",
    "procurement",
    "tender",
    "verebes obstaranie",
    "verejne obstaravanie",
    "vergabe",
    "vergebener auftrag",
    "vysledok verejneho obstaravania",
    "zuschlag",
)

_FOREIGN_FAMILY_HOUSE_BUILD_OR_EXTENSION_PHRASES = (
    "building a house",
    "csaladi haz bovites",
    "csaladi haz epites",
    "einfamilienhausbau",
    "hausbau",
    "house construction",
    "house extension",
    "pristavba domu",
    "rozsirenie rodinneho domu",
    "stavba domu",
    "vystavba rodinneho domu",
)


class UnsafeRouteError(ValueError):
    pass


def _public_html_portal_error(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    try:
        portal = PortalRegistry.load().for_host(host)
    except LandRegistryError:
        return "portal_registry_unavailable"
    if not portal or not portal.permits("discover") or portal.discovery_mode != "public_html":
        return "portal_public_html_not_enabled"
    return None


def _robots_error(client: httpx.Client, url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    now = monotonic_time.monotonic()
    with _ROBOTS_CACHE_LOCK:
        cached = _ROBOTS_CACHE.get(host)
    if cached and now - cached[0] < ROBOTS_CACHE_SECONDS:
        lines, cached_error = cached[1], cached[2]
    else:
        robots_url = urlunparse(("https", parsed.netloc, "/robots.txt", "", "", ""))
        try:
            assert_public_https_url(robots_url)
            response = client.get(robots_url)
            if response.status_code in {404, 410}:
                lines, cached_error = None, None
            elif not 200 <= response.status_code < 300:
                lines, cached_error = None, "portal_robots_unavailable"
            elif len(response.content) > ROBOTS_MAX_BYTES:
                lines, cached_error = None, "portal_robots_too_large"
            else:
                lines = response.text.splitlines()
                cached_error = None
        except (httpx.HTTPError, UnsafeRouteError, UnicodeError):
            lines, cached_error = None, "portal_robots_unavailable"
        with _ROBOTS_CACHE_LOCK:
            _ROBOTS_CACHE[host] = (now, lines, cached_error)
    if cached_error:
        return cached_error
    if lines is None:
        return None
    parser = RobotFileParser()
    parser.set_url(urlunparse(("https", parsed.netloc, "/robots.txt", "", "", "")))
    parser.parse(lines)
    if not parser.can_fetch(PORTAL_PUBLIC_HTML_USER_AGENT, url):
        return "portal_robots_disallowed"
    return None


def assert_public_https_url(url: str) -> str:
    """Reject non-public HTTPS targets before a pinned connection is attempted."""

    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeRouteError("invalid_route_url")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeRouteError("invalid_route_url") from exc
    if port not in {None, 443}:
        raise UnsafeRouteError("non_standard_https_port")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname,
                port or 443,
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, socket.gaierror) as exc:
        raise UnsafeRouteError("dns_resolution_failed") from exc
    if not addresses:
        raise UnsafeRouteError("dns_resolution_empty")
    try:
        resolved = [ipaddress.ip_address(address) for address in addresses]
    except ValueError as exc:
        raise UnsafeRouteError("invalid_resolved_address") from exc
    if any(not address.is_global for address in resolved):
        raise UnsafeRouteError("non_public_target")
    return parsed.hostname.casefold().rstrip(".")


def _pinned_https_get(
    url: str,
    *,
    max_response_bytes: int,
    deadline_monotonic: float,
    request_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeRouteError("invalid_route_url")
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise UnsafeRouteError("invalid_route_url") from exc
    if parsed_port not in {None, 443}:
        raise UnsafeRouteError("non_standard_https_port")
    try:
        # ``http.client`` requires an ASCII request target. Public listing URLs
        # occasionally expose unescaped Unicode characters (for example ``²``
        # in a size slug). HTTPX applies RFC 3986 UTF-8 percent encoding while
        # the separately validated host, pinned IP and TLS SNI remain unchanged.
        request_target = httpx.URL(url).raw_path.decode("ascii")
    except (httpx.InvalidURL, UnicodeError) as exc:
        raise UnsafeRouteError("invalid_route_url") from exc
    if not request_target.startswith("/"):
        raise UnsafeRouteError("invalid_route_url")
    host = parsed.hostname.casefold().rstrip(".")
    port = parsed.port or 443
    outcome: dict[str, Any] = {}

    def resolve() -> None:
        try:
            outcome["records"] = socket.getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
        except (OSError, ValueError) as exc:
            outcome["error"] = exc

    resolver = threading.Thread(target=resolve, name="land-public-dns", daemon=True)
    resolver.start()
    resolver.join(timeout=max(0.0, deadline_monotonic - monotonic_time.monotonic()))
    if resolver.is_alive():
        raise UnsafeRouteError("fetch_timeout")
    if "error" in outcome:
        raise UnsafeRouteError("dns_resolution_failed") from outcome["error"]
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in outcome.get("records", [])
        }
    except (TypeError, ValueError) as exc:
        raise UnsafeRouteError("invalid_resolved_address") from exc
    if not addresses or any(
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        for address in addresses
    ):
        raise UnsafeRouteError("non_public_target")
    source_ip = sorted(addresses, key=lambda item: (item.version, str(item)))[0]
    remaining = deadline_monotonic - monotonic_time.monotonic()
    if remaining <= 0:
        raise UnsafeRouteError("fetch_timeout")
    raw_socket = socket.create_connection((str(source_ip), port), timeout=remaining)
    connection: http.client.HTTPSConnection | None = None
    try:
        context = ssl.create_default_context()
        raw_socket.settimeout(remaining)
        tls_socket = context.wrap_socket(raw_socket, server_hostname=host)
        connection = http.client.HTTPSConnection(
            host,
            port=port,
            timeout=max(0.001, deadline_monotonic - monotonic_time.monotonic()),
            context=context,
        )
        connection.sock = tls_socket
        connection.request(
            "GET",
            request_target,
            headers={
                "Host": host if parsed.port is None else f"{host}:{port}",
                "User-Agent": PORTAL_PUBLIC_HTML_USER_AGENT,
                "Accept": "text/html,text/plain;q=0.9",
                "Accept-Encoding": "identity",
                "Connection": "close",
                **(
                    {"Cookie": request_headers["Cookie"]}
                    if request_headers and "Cookie" in request_headers
                    else {}
                ),
            },
        )
        response = connection.getresponse()
        headers = {key.casefold(): value.strip() for key, value in response.getheaders()}
        if headers.get("content-encoding", "identity").casefold() not in {
            "",
            "identity",
        }:
            raise UnsafeRouteError("response_compression_forbidden")
        declared = headers.get("content-length")
        if declared:
            try:
                declared_size = int(declared)
            except ValueError as exc:
                raise UnsafeRouteError("content_length_invalid") from exc
            if declared_size < 0 or declared_size > max_response_bytes:
                raise UnsafeRouteError("response_too_large")
        chunks: list[bytes] = []
        received = 0
        while received <= max_response_bytes:
            if deadline_monotonic - monotonic_time.monotonic() <= 0:
                raise UnsafeRouteError("fetch_timeout")
            chunk = response.read(min(65_536, max_response_bytes + 1 - received))
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
        body = b"".join(chunks)
        if len(body) > max_response_bytes:
            raise UnsafeRouteError("response_too_large")
        return {
            "status_code": response.status,
            "headers": headers,
            "body": body,
            "source_ip": str(source_ip),
            "set_cookie_headers": [
                value for key, value in response.getheaders() if key.casefold() == "set-cookie"
            ],
        }
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise UnsafeRouteError("pinned_fetch_failed") from exc
    finally:
        if connection is not None:
            connection.close()
        else:
            raw_socket.close()


def _fresh_pinned_robots_error(
    url: str,
    *,
    deadline_monotonic: float,
) -> str | None:
    parsed = urlparse(url)
    robots_url = urlunparse(("https", parsed.netloc, "/robots.txt", "", "", ""))
    try:
        response = _pinned_https_get(
            robots_url,
            max_response_bytes=ROBOTS_MAX_BYTES,
            deadline_monotonic=deadline_monotonic,
        )
    except UnsafeRouteError:
        return "portal_robots_unavailable"
    status = int(response["status_code"])
    if status in {404, 410}:
        return None
    if not 200 <= status < 300:
        return "portal_robots_unavailable"
    try:
        lines = bytes(response["body"]).decode("utf-8").splitlines()
    except UnicodeError:
        return "portal_robots_unavailable"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(lines)
    return (
        None
        if parser.can_fetch(PORTAL_PUBLIC_HTML_USER_AGENT, url)
        else "portal_robots_disallowed"
    )


class _VisibleText(HTMLParser):
    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._anchor_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self.hidden += 1
        elif tag.casefold() == "a" and not self.hidden:
            self._href = next((value for key, value in attrs if key.casefold() == "href"), None)
            self._anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1
        elif tag.casefold() == "a" and self._href and self.base_url:
            absolute = urljoin(self.base_url, self._href.strip())
            parsed = urlparse(absolute)
            base_host = (urlparse(self.base_url).hostname or "").casefold()
            if (
                parsed.scheme == "https"
                and (parsed.hostname or "").casefold() == base_host
                and len(absolute) <= 1500
            ):
                canonical = urlunparse(parsed._replace(fragment=""))
                label = re.sub(r"\s+", " ", " ".join(self._anchor_parts)).strip()[:500]
                if label and not any(item["url"] == canonical for item in self.links):
                    self.links.append({"url": canonical, "label": label})
            self._href = None
            self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            data = data.replace("[SOURCE_PAGE_EVIDENCE]", "[idézett jelölés]")
            self.parts.append(data)
            if self._href:
                self._anchor_parts.append(data)


class _PublicLandPaginationLinks(HTMLParser):
    """Collect hrefs for exact category pagination, including icon-only anchors."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.casefold()
        if name in {"script", "style", "noscript", "template"}:
            self.hidden += 1
            return
        if name != "a" or self.hidden:
            return
        href = next((value for key, value in attrs if key.casefold() == "href"), None)
        if href:
            self.hrefs.append(href.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template"} and self.hidden:
            self.hidden -= 1


class _QjobTaskCards(HTMLParser):
    """Extract Qjob task cards whose permalink is stored on a div, not an anchor."""

    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.stack: list[str] = []
        self.active_depth: int | None = None
        self.active_href: str | None = None
        self.active_parts: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.casefold()
        if name not in self._VOID_TAGS:
            self.stack.append(name)
        if self.active_depth is not None or name != "div":
            return
        values = {key.casefold(): value or "" for key, value in attrs}
        href = values.get("href", "").strip()
        classes = values.get("class", "").casefold().split()
        if "work" not in classes or not re.fullmatch(r"/tasks/\d+/?", href):
            return
        self.active_depth = len(self.stack)
        self.active_href = href
        self.active_parts = []

    def handle_endtag(self, tag: str) -> None:
        name = tag.casefold()
        if (
            self.active_depth is not None
            and name == "div"
            and len(self.stack) == self.active_depth
            and self.active_href
        ):
            absolute = urljoin(self.base_url, self.active_href)
            parsed = urlparse(absolute)
            base_host = (urlparse(self.base_url).hostname or "").casefold()
            label = re.sub(r"\s+", " ", " ".join(self.active_parts)).strip()[:500]
            label = label.replace("[SOURCE_PAGE_EVIDENCE]", "[idézett jelölés]")
            if (
                label
                and parsed.scheme == "https"
                and (parsed.hostname or "").casefold() == base_host
            ):
                canonical = urlunparse(parsed._replace(fragment=""))
                if not any(item["url"] == canonical for item in self.links):
                    self.links.append({"url": canonical, "label": label})
            self.active_depth = None
            self.active_href = None
            self.active_parts = []
        if self.stack:
            if self.stack[-1] == name:
                self.stack.pop()
            elif name in self.stack:
                reverse_index = self.stack[::-1].index(name)
                del self.stack[len(self.stack) - reverse_index - 1 :]

    def handle_data(self, data: str) -> None:
        if self.active_depth is not None:
            self.active_parts.append(data)


class _SearchResultLinks(HTMLParser):
    """Collect result anchors from public search HTML, including nested titles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._parts: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a" or self._href is not None:
            return
        values = {key.casefold(): value or "" for key, value in attrs}
        href = values.get("href", "").strip()
        if href:
            self._href = href
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        label = re.sub(r"\s+", " ", " ".join(self._parts)).strip()[:900]
        self.links.append({"url": self._href, "label": label})
        self._href = None
        self._parts = []


def _decode_search_result_url(value: str, *, base_url: str) -> str:
    """Resolve search wrappers to source URLs, never their publication dates."""

    absolute = urljoin(base_url, value.strip())
    parsed = urlparse(absolute)
    if (parsed.hostname or "").casefold() not in _SEARCH_ENGINE_HOSTS:
        return absolute
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    # Google and DuckDuckGo also return links through their own redirect URLs.
    for key in ("uddg", "url", "q"):
        target = query.get(key, "")
        if target.startswith("https://"):
            return target
    opaque = query.get("u", "")
    if opaque.startswith("a1") and len(opaque) > 2:
        try:
            decoded = base64.urlsafe_b64decode(
                opaque[2:] + "=" * ((-len(opaque[2:])) % 4)
            ).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            decoded = ""
        if decoded.startswith("https://"):
            return decoded
    return absolute


def _canonical_forum_result_url(value: str, *, base_url: str) -> str:
    """Use the source URL, with tracking removed but post identity retained."""

    parsed = urlparse(_decode_search_result_url(value, base_url=base_url))
    host = (parsed.hostname or "").casefold()
    if host in {"reddit.com", "old.reddit.com", "m.reddit.com"}:
        host = "www.reddit.com"
    if host == "gyakorikerdesek.hu":
        host = "www.gyakorikerdesek.hu"
    try:
        port = parsed.port
    except ValueError:
        return ""
    # Credentials, internal addresses and nonstandard ports are not public
    # forum identities. The actual fetch additionally validates DNS addresses.
    if parsed.username or parsed.password or port not in {None, 443}:
        return ""
    if host in {"localhost", "localhost.localdomain"} or "." not in host:
        return ""
    try:
        if not ipaddress.ip_address(host).is_global:
            return ""
    except ValueError:
        pass
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in {"fbclid", "gclid", "msclkid", "ref", "ref_src"}
    )
    path = parsed.path
    if host == "www.reddit.com":
        match = re.fullmatch(
            r"/r/([^/]+)/comments/([a-z0-9]+)(?:/[^/]*)?(?:/([a-z0-9]+))?/?", path, re.I
        )
        if match:
            # Titles can be edited without changing the post's identity.
            path = f"/r/{match.group(1).casefold()}/comments/{match.group(2).casefold()}/"
            if match.group(3):
                path += f"_/{match.group(3).casefold()}/"
    return urlunparse(parsed._replace(netloc=host, path=path, query=urlencode(query), fragment=""))


def _is_search_route(route_url: str) -> bool:
    parsed = urlparse(route_url)
    host = (parsed.hostname or "").casefold()
    if host not in _SEARCH_ENGINE_HOSTS:
        return False
    path = parsed.path.casefold().rstrip("/")
    allowed_paths = {"", "/search", "/web"}
    if host in {"duckduckgo.com", "html.duckduckgo.com", "lite.duckduckgo.com"}:
        allowed_paths.update({"/lite", "/html"})
    return path in allowed_paths and bool(
        dict(parse_qsl(parsed.query, keep_blank_values=True)).get("q")
    )


def _is_forum_discovery_route(route: SourceCoverageRoute) -> bool:
    context = " ".join(
        str(value or "")
        for value in (
            getattr(route, "route_key", ""),
            getattr(route, "category", ""),
            getattr(route, "source_type", ""),
            getattr(route, "source_name", ""),
            getattr(route, "search_signal", ""),
        )
    ).casefold()
    return _is_search_route(route.route_url) and any(
        marker in context
        for marker in ("forum", "fórum", "question", "kérdés", "radar", "reddit", "gyakori")
    )


def _forum_search_result_candidate(url: str, *, base_url: str) -> bool:
    """Accept only concrete, relevant HTTPS result pages from a search surface."""

    canonical = _canonical_forum_result_url(url, base_url=base_url)
    parsed = urlparse(canonical)
    base_host = (urlparse(base_url).hostname or "").casefold()
    host = (parsed.hostname or "").casefold()
    if (
        parsed.scheme != "https"
        or not host
        or host in _SEARCH_ENGINE_HOSTS
        or host == base_host
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        return False
    path = parsed.path.casefold().rstrip("/")
    if not path or path in {"/", "/search", "/login", "/bejelentkezes"}:
        return False
    parts = [part for part in path.split("/") if part]
    query_keys = {
        key.casefold()
        for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
    }
    has_identity_query = bool(
        query_keys & {"id", "post", "question", "thread", "topic", "tid", "t"}
    )
    path_text = " ".join(parts)
    has_forum_path = any(marker in path_text for marker in _FORUM_PATH_MARKERS)
    has_forum_host = any(part in {"forum", "forums", "community"} for part in host.split("."))
    has_known_question_path = (
        host == "www.gyakorikerdesek.hu" and bool(re.search(r"__\d+-", path))
    ) or (
        host == "joszaki.hu" and path.startswith("/szakivalaszol/")
    ) or (host == "qjob.hu" and bool(re.fullmatch(r"/tasks/\d+", path)))
    # An article/product's numeric ID is not evidence that it is a forum post.
    return has_known_question_path or has_forum_path or (has_forum_host and has_identity_query)


def _forum_search_page_evidence(
    body_text: str, *, base_url: str, limit: int
) -> tuple[str, list[dict[str, str]]]:
    parser = _SearchResultLinks()
    try:
        parser.feed(body_text)
    except Exception:
        return _visible_text(body_text, limit), []
    links: list[dict[str, str]] = []
    visible_parts: list[str] = []
    for item in parser.links:
        url = _canonical_forum_result_url(str(item.get("url") or ""), base_url=base_url)
        label = re.sub(r"\s+", " ", str(item.get("label") or "")).strip()
        label = label.replace("[SOURCE_PAGE_EVIDENCE]", "[idézett jelölés]")
        relevance_text = f"{label} {url}".casefold()
        if not _forum_search_result_candidate(url, base_url=base_url):
            continue
        if not any(marker.casefold() in relevance_text for marker in _FORUM_CONTENT_MARKERS):
            continue
        canonical = url
        if any(existing["url"] == canonical for existing in links):
            continue
        links.append({"url": canonical, "label": label[:1200]})
        visible_parts.extend(part for part in (label, canonical) if part)
        if len(links) >= 40:
            break
    text = re.sub(r"\s+", " ", " ".join(visible_parts)).strip()[:limit]
    return text, links


def _reply_page_candidate(url: str, *, base_url: str) -> bool:
    """Return true only for public, concrete question/task pages we can verify.

    The category page is only a discovery surface.  Freshness must come from
    the concrete item page, so this deliberately supports the two current
    Hungarian reply surfaces with stable, same-host permalinks.
    """

    base = urlparse(base_url)
    candidate = urlparse(urljoin(base_url, url))
    if (
        candidate.scheme != "https"
        or not base.hostname
        or not candidate.hostname
        or candidate.hostname.casefold() != base.hostname.casefold()
        or candidate.username
        or candidate.password
        or candidate.fragment
    ):
        return False
    host = candidate.hostname.casefold()
    path = candidate.path.rstrip("/")
    if is_named_portal_host(host):
        # Property listing fetches have their own bounded adapter and robots policy.
        return False
    if host == "qjob.hu" and re.fullmatch(r"/tasks/\d+", path, flags=re.IGNORECASE):
        return True
    if host == "joszaki.hu" and path.casefold().startswith("/szakivalaszol/"):
        parts = [part.casefold() for part in path.split("/") if part]
        return len(parts) == 2 and parts[1] not in {
            "uj-kerdes",
            "szakma",
            "tevekenyseg",
        }
    if host == "gyakorikerdesek.hu" or host.endswith(".gyakorikerdesek.hu"):
        # Concrete Gyakori Kérdések pages carry a numeric question id in the
        # category slug (for example ``otthon__epitkezes__13249178-...``).
        return bool(re.search(r"__\d{6,}(?:-|$)", path, flags=re.IGNORECASE))
    if host == "forum.index.hu" or host.endswith(".forum.index.hu"):
        query = parse_qsl(candidate.query, keep_blank_values=True)
        return path.casefold().endswith(("/article/showarticle", "/article/viewarticle")) and any(
            key.casefold() == "a" and value.isdigit() for key, value in query
        )
    if host == "prohardver.hu":
        match = re.search(r"/hsz_(\d+)-(\d+)\.html$", path)
        return bool(match and match[1] == match[2])
    if host == "reddit.com" or host.endswith(".reddit.com"):
        return bool(re.search(r"/comments/[a-z0-9]+(?:/|$)", path, flags=re.IGNORECASE))
    query_keys = {
        key.casefold() for key, _value in parse_qsl(candidate.query, keep_blank_values=True)
    }
    if query_keys & {"post", "question", "thread", "topic", "tid"}:
        return True
    parts = [part for part in path.split("/") if part]
    if not parts or path in {
        "/",
        "/forum",
        "/forums",
        "/topic",
        "/topics",
        "/thread",
        "/threads",
        "/questions",
    }:
        return False
    path_text = " ".join(parts).casefold()
    if not any(marker in path_text for marker in _FORUM_PATH_MARKERS):
        return False
    return any(part.isdigit() or len(part) >= 6 for part in parts[1:])


class _PostEvidenceHTML(HTMLParser):
    """Minimal tree for binding evidence to one post, excluding adjacent posts."""

    def __init__(self, body: str):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "root", "attrs": {}, "parts": [], "children": []}
        self.stack = [self.root]
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "parts": [], "children": []}
        self.stack[-1]["children"].append(node)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "source",
            "wbr",
        }:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1]["parts"].append(data)

    @staticmethod
    def walk(node):
        yield node
        for child in node["children"]:
            yield from _PostEvidenceHTML.walk(child)

    @staticmethod
    def text(node):
        return " ".join(" ".join(part["parts"]) for part in _PostEvidenceHTML.walk(node)).strip()


def _reply_page_metadata(body_text: str, *, source_url: str) -> dict[str, str] | None:
    """Extract publication evidence only from the identified question or post."""
    if not _reply_page_candidate(source_url, base_url=source_url):
        return None
    document = _PostEvidenceHTML(body_text)
    nodes = list(document.walk(document.root))
    host = (urlparse(source_url).hostname or "").casefold()
    metadata: dict[str, str] = {}
    if host == "gyakorikerdesek.hu" or host.endswith(".gyakorikerdesek.hu"):
        questions = [n for n in nodes if "kerdes" in (n["attrs"].get("class") or "").split()]
        if len(questions) != 1:
            return None
        dates = [
            document.text(n)
            for n in document.walk(questions[0])
            if n["attrs"].get("title") == "A kérdés kiírásának időpontja"
        ]
        if len(dates) != 1 or not dates[0]:
            return None
        metadata["published_at_raw"] = dates[0][:255]
        empty = [n for n in nodes if "sajnosmeg" in (n["attrs"].get("class") or "").split()]
        if any("még nem érkezett válasz a kérdésre" in document.text(n).casefold() for n in empty):
            metadata.update(
                active_status="active",
                active_status_raw="active",
                answer_count_raw="0 válasz",
                existing_answer_count="0",
            )
        else:
            headers = [
                n for n in nodes if "valasz_fejlec" in (n["attrs"].get("class") or "").split()
            ]
            totals = {
                m.group(1)
                for n in headers
                if (m := re.search(r"\d+\s*/\s*(\d+)", document.text(n)))
            }
            if len(totals) == 1:
                count = totals.pop()
                metadata.update(existing_answer_count=count, answer_count_raw=count + " válasz")
            # An actual reply form proves the post remains open, regardless of answer count.
            if any(n["tag"] == "textarea" for n in nodes):
                metadata.update(active_status="active", active_status_raw="active")
    elif host == "forum.index.hu":
        post_id = dict(parse_qsl(urlparse(source_url).query)).get("a")
        exact_groups = [
            n
            for n in nodes
            if n["tag"] == "table"
            and "art" in (n["attrs"].get("class") or "").split()
            and any(child["attrs"].get("name") == post_id for child in document.walk(n))
        ]
        allowed_nodes = list(document.walk(exact_groups[0])) if len(exact_groups) == 1 else nodes
        bookmarks = [
            n
            for n in allowed_nodes
            if n["tag"] == "a"
            and "bookmark" in (n["attrs"].get("rel") or "").split()
            and (
                dict(parse_qsl(urlparse(n["attrs"].get("href") or "").query)).get("a") == post_id
                or (len(exact_groups) == 1 and not n["attrs"].get("href"))
            )
        ]
        dates = {n["attrs"].get("title") for n in bookmarks if n["attrs"].get("title")}
        if len(dates) != 1:
            return None
        stamp = dates.pop()
        if not re.fullmatch(r"\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}", stamp):
            return None
        metadata["published_at_raw"] = stamp
    elif host == "prohardver.hu":
        links = _forum_post_links(body_text, base_url=source_url)
        exact = next((item for item in links if _same_forum_post(item["url"], source_url)), None)
        if exact and "[SOURCE_PAGE_EVIDENCE]" in exact["label"]:
            marker = exact["label"].split("[SOURCE_PAGE_EVIDENCE]", 1)[1]
            metadata.update(
                dict(part.strip().split("=", 1) for part in marker.split(";") if "=" in part)
            )
    else:
        # JSON-LD must identify this item, not an unrelated sidebar/article/comment.
        records = []

        def visit(value):
            if isinstance(value, dict):
                records.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        for node in nodes:
            if node["tag"] != "script" or node["attrs"].get("type") != "application/ld+json":
                continue
            try:
                visit(json.loads(document.text(node)))
            except (ValueError, TypeError):
                continue
        target = source_url.rstrip("/")
        matched = []
        for record in records:
            kind = record.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            url = record.get("url") or record.get("@id")
            if not isinstance(url, str):
                continue
            if target == urljoin(source_url, url).rstrip("/") and any(
                value in {"Question", "DiscussionForumPosting", "SocialMediaPosting"}
                for value in kinds
            ):
                matched.append(record)
        if len(matched) == 1 and matched[0].get("datePublished"):
            record = matched[0]
            metadata["published_at_raw"] = str(record["datePublished"])[:255]
            count = record.get("answerCount", record.get("commentCount"))
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                metadata.update(
                    existing_answer_count=str(count), answer_count_raw=str(count) + " válasz"
                )
        elif host in {"qjob.hu", "joszaki.hu", "www.joszaki.hu"}:
            # The existing task adapter has a single task-state object on concrete pages.
            dates = set(re.findall(r'"(?:publishedAt|datePublished)"\s*:\s*"([^"\n]+)"', body_text))
            if len(dates) == 1:
                metadata["published_at_raw"] = dates.pop()[:255]
            statuses = set(re.findall(r'"status"\s*:\s*"([^"\n]+)"', body_text))
            if len(statuses) == 1:
                value = statuses.pop()
                if value.casefold() in {
                    "published",
                    "active",
                    "open",
                    "closed",
                    "deleted",
                    "expired",
                }:
                    metadata.update(
                        active_status_raw=value,
                        active_status="active"
                        if value.casefold() in {"published", "active", "open"}
                        else "inactive",
                    )
            counts = set(re.findall(r'"taskResponsesCount"\s*:\s*(\d+)', body_text))
            if len(counts) == 1:
                count = counts.pop()
                metadata.update(existing_answer_count=count, answer_count_raw=count + " válasz")
    if not metadata.get("published_at_raw"):
        return None
    metadata.update(published_at_source="source_page", source_url=source_url)
    return metadata


def _forum_post_links(body_text: str, *, base_url: str) -> list[dict[str, str]]:
    """Extract original message bodies and dates from public Index/Prohardver threads."""
    host = (urlparse(base_url).hostname or "").casefold()
    if host not in {"forum.index.hu", "prohardver.hu"}:
        return []
    doc = _PostEvidenceHTML(body_text)
    nodes = list(doc.walk(doc.root))
    groups = [
        n
        for n in nodes
        if (
            host == "forum.index.hu"
            and n["tag"] == "table"
            and "art" in (n["attrs"].get("class") or "").split()
        )
        or (host == "prohardver.hu" and n["tag"] == "li" and n["attrs"].get("data-id"))
    ]
    links = []
    for group in groups:
        children = list(doc.walk(group))
        if host == "forum.index.hu":
            anchors = [
                n
                for n in children
                if n["tag"] == "a" and "bookmark" in (n["attrs"].get("rel") or "").split()
            ]
            bodies = [n for n in children if "art_b" in (n["attrs"].get("class") or "").split()]
            raw_date = anchors[0]["attrs"].get("title", "") if anchors else ""
        else:
            identifier = group["attrs"]["data-id"]
            anchors = [
                n
                for n in children
                if n["tag"] == "a"
                and (n["attrs"].get("href") or "").endswith(f"/hsz_{identifier}-{identifier}.html")
            ]
            bodies = [
                child
                for node in children
                if "message-body-main" in (node["attrs"].get("class") or "").split()
                for child in node["children"]
                if "message-content" in (child["attrs"].get("class") or "").split()
            ]
            dates = [
                n
                for n in children
                if n["tag"] == "time" and "message-time" in (n["attrs"].get("class") or "").split()
            ]
            raw_date = doc.text(dates[0]) if len(dates) == 1 else ""
        if not anchors or not bodies:
            continue
        href = anchors[0]["attrs"].get("href") or ""
        if not href and host == "forum.index.hu":
            identifiers = [
                n["attrs"]["name"] for n in children if str(n["attrs"].get("name") or "").isdigit()
            ]
            if len(identifiers) != 1:
                continue
            thread = dict(parse_qsl(urlparse(base_url).query)).get("t", "")
            href = "/Article/viewArticle?a=" + identifiers[0] + ("&t=" + thread if thread else "")
        url = urljoin(base_url, href)
        if not _reply_page_candidate(url, base_url=base_url):
            continue
        label = re.sub(r"\s+", " ", doc.text(bodies[0])).strip()[:850]
        label = label.replace("[SOURCE_PAGE_EVIDENCE]", "[idézett jelölés]")
        if raw_date and ";" not in raw_date:
            label += (
                "\n[SOURCE_PAGE_EVIDENCE] published_at_raw="
                + raw_date[:255]
                + "; published_at_source=source_page"
            )
        if "[SOURCE_PAGE_EVIDENCE]" not in label:
            label += "\n[SOURCE_PAGE_EVIDENCE] published_at_source=unknown"
        if label:
            links.append({"url": url, "label": label})
    return links[:100]


def refresh_question_source(source_url: str) -> dict[str, Any]:
    """Read one original post immediately before use; perform no external writes."""
    observed_at = datetime.now(UTC)
    if not _reply_page_candidate(source_url, base_url=source_url):
        return {"source_url": source_url, "error": "exact_post_permalink_missing"}
    host = (urlparse(source_url).hostname or "").casefold()
    fetch_url = source_url
    if host == "reddit.com" or host.endswith(".reddit.com"):
        match = re.search(
            r"(/r/[^/]+/comments/[a-z0-9]+)", urlparse(source_url).path, flags=re.IGNORECASE
        )
        if match:
            fetch_url = "https://www.reddit.com" + match.group(1) + "/.rss"
    try:
        response = _forum_page_get(fetch_url, timeout_seconds=20, max_response_bytes=2_000_000)
        if not 200 <= response["status_code"] < 300:
            raise ValueError("source_http_" + str(response["status_code"]))
        body = _forum_decode_body(response)
        metadata = _reply_page_metadata(body, source_url=source_url)
        links = _forum_post_links(body, base_url=source_url)
        atom = _atom_feed_evidence(body, base_url=source_url, limit=60_000)
        if atom is not None:
            links = atom[1]
        exact = next((item for item in links if _same_forum_post(item["url"], source_url)), None)
        if exact:
            source_text, _, marker = exact["label"].partition("[SOURCE_PAGE_EVIDENCE]")
            if marker:
                metadata = dict(
                    part.strip().split("=", 1) for part in marker.split(";") if "=" in part
                )
        else:
            source_text = _original_question_text(body, source_url=source_url)
        if not metadata or not source_text.strip():
            raise ValueError("source_post_evidence_unavailable")
        return {
            **metadata,
            "source_url": source_url,
            "source_text": source_text.strip(),
            "observed_at": observed_at.isoformat(),
            "active_status": metadata.get("active_status", "unknown"),
            "existing_answer_count": metadata.get("existing_answer_count"),
        }
    except (ValueError, OSError, UnsafeRouteError, httpx.HTTPError) as exc:
        return {
            "source_url": source_url,
            "observed_at": observed_at.isoformat(),
            "error": str(exc)[:120],
        }


def _same_forum_post(left: str, right: str) -> bool:
    a, b = urlparse(left), urlparse(right)
    if (a.hostname or "").removeprefix("www.") != (b.hostname or "").removeprefix("www."):
        return False
    if (a.hostname or "").endswith("reddit.com"):
        def reddit_identity(path):
            parts = [part for part in path.split("/") if part]
            if "comments" not in parts:
                return None
            index = parts.index("comments")
            if len(parts) <= index + 1:
                return None
            return parts[index + 1], parts[index + 3] if len(parts) > index + 3 else None
        first, second = reddit_identity(a.path), reddit_identity(b.path)
        return bool(first and first == second)
    if a.hostname == "forum.index.hu":
        return dict(parse_qsl(a.query)).get("a") == dict(parse_qsl(b.query)).get("a")
    return left.rstrip("/") == right.rstrip("/")


def _original_question_text(body: str, *, source_url: str) -> str:
    doc = _PostEvidenceHTML(body)
    nodes = list(doc.walk(doc.root))
    host = (urlparse(source_url).hostname or "").casefold()
    if host.endswith("gyakorikerdesek.hu"):
        parts = [
            doc.text(n)
            for n in nodes
            if n["tag"] == "h1" or "kerdes_kerdes" in (n["attrs"].get("class") or "").split()
        ]
        return " ".join(parts)[:3000]
    # A bound JSON-LD question can provide its own original text. Do not use whole-page sidebars.
    for node in nodes:
        if node["tag"] == "script" and node["attrs"].get("type") == "application/ld+json":
            try:
                value = json.loads(doc.text(node))
            except ValueError:
                continue
            if isinstance(value, dict) and _same_forum_post(
                str(value.get("url") or ""), source_url
            ):
                return " ".join(
                    str(value.get(key) or "") for key in ("headline", "name", "text", "articleBody")
                )[:3000]
    return ""


def _forum_page_get(url: str, *, timeout_seconds: float, max_response_bytes: int) -> dict[str, Any]:
    from .forum_http import forum_public_get

    return forum_public_get(
        url,
        max_response_bytes=max_response_bytes,
        deadline_monotonic=monotonic_time.monotonic() + min(float(timeout_seconds), 20.0),
        pinned_get=_pinned_https_get,
    )


def _forum_decode_body(response: dict[str, Any]) -> str:
    header = str(response.get("headers", {}).get("content-type", ""))
    charset = re.search(r"charset=([^; ]+)", header, flags=re.IGNORECASE)
    encoding = charset.group(1).strip("\"'") if charset else "utf-8"
    try:
        return response["body"].decode(encoding, errors="replace")
    except LookupError:
        return response["body"].decode("utf-8", errors="replace")


def _expand_index_forum_threads(
    links: list[dict[str, str]],
    *,
    base_url: str,
    timeout_seconds: float,
    max_response_bytes: int,
) -> list[dict[str, str]]:
    """Read recent Index category threads to get individual post evidence."""
    if (urlparse(base_url).hostname or "").casefold() != "forum.index.hu" or urlparse(
        base_url
    ).path.casefold() != "/topic/showtopiclist":
        return links
    posts: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in links:
        parsed = urlparse(urljoin(base_url, str(item.get("url") or "")))
        query = dict(parse_qsl(parsed.query))
        if (
            parsed.scheme != "https"
            or parsed.hostname != "forum.index.hu"
            or parsed.path.casefold() != "/article/showarticle"
            or not str(query.get("t") or "").isdigit()
            or "a" in query
        ):
            continue
        url = f"https://forum.index.hu/Article/showArticle?t={query['t']}"
        if url in seen:
            continue
        seen.add(url)
        try:
            response = _forum_page_get(
                url, timeout_seconds=timeout_seconds, max_response_bytes=max_response_bytes
            )
            if 200 <= int(response["status_code"]) < 300:
                posts.extend(_forum_post_links(_forum_decode_body(response), base_url=url))
        except (ValueError, OSError, UnsafeRouteError, httpx.HTTPError):
            pass
        if len(seen) >= 3:
            break
    return list({item["url"]: item for item in posts}.values())


def _enrich_reply_page_links(
    links: list[dict[str, str]],
    *,
    base_url: str,
    timeout_seconds: float,
    max_response_bytes: int,
) -> list[dict[str, str]]:
    """Read exact post evidence with public-IP pinning and bounded response size."""
    host = (urlparse(base_url).hostname or "").casefold()
    maximum = (
        QUESTION_RADAR_GYAKORI_REPLY_PAGE_MAXIMUM if host.endswith("gyakorikerdesek.hu") else 12
    )
    deadline = monotonic_time.monotonic() + min(max(float(timeout_seconds) * 3, 1), 45.0)
    enriched = {}
    count = 0
    for item in links:
        url = str(item.get("url") or "")
        if count >= maximum or not _reply_page_candidate(url, base_url=base_url):
            continue
        remaining = deadline - monotonic_time.monotonic()
        if remaining <= 0:
            break
        count += 1
        try:
            response = _forum_page_get(
                url, timeout_seconds=min(8.0, remaining), max_response_bytes=max_response_bytes
            )
            if not 200 <= response["status_code"] < 300:
                continue
            metadata = _reply_page_metadata(_forum_decode_body(response), source_url=url)
        except (ValueError, UnsafeRouteError, OSError, httpx.HTTPError):
            continue
        if not metadata:
            continue
        # Replace prior feed/discovery markers; never concatenate conflicting timestamps.
        label = str(item.get("label") or "").split("[SOURCE_PAGE_EVIDENCE]", 1)[0].strip()[:850]
        evidence = "; ".join(
            f"{key}={value}" for key, value in metadata.items() if key != "source_url"
        )
        enriched[url] = {
            "url": url,
            "label": (label + "\n[SOURCE_PAGE_EVIDENCE] " + evidence)[:1200],
        }
    return [enriched.get(str(item.get("url") or ""), item) for item in links]


def _enrich_discovered_forum_links(
    links: list[dict[str, str]],
    *,
    discovery_url: str,
    timeout_seconds: float,
    max_response_bytes: int,
) -> list[dict[str, str]]:
    """Re-read each search result on its own host for source-page evidence."""

    enriched: list[dict[str, str]] = []
    seen: set[str] = set()
    deadline = monotonic_time.monotonic() + 45.0
    for item in links[:40]:
        url = _canonical_forum_result_url(str(item.get("url") or ""), base_url=discovery_url)
        if not _forum_search_result_candidate(url, base_url=discovery_url):
            continue
        if url in seen:
            continue
        seen.add(url)
        canonical_item = {**item, "url": url}
        remaining = deadline - monotonic_time.monotonic()
        if len(enriched) < 12 and remaining > 0:
            enriched.extend(
                _enrich_reply_page_links(
                    [canonical_item],
                    base_url=url,
                    timeout_seconds=min(float(timeout_seconds), 8.0, remaining),
                    max_response_bytes=max_response_bytes,
                )
            )
        else:
            # Preserve unverified candidates for their own scheduled source
            # fetch; a per-request network budget must not discard discoveries.
            enriched.append(canonical_item)
    return enriched


def _visible_text(body_text: str, limit: int) -> str:
    parser = _VisibleText()
    try:
        parser.feed(body_text)
        value = " ".join(parser.parts)
    except Exception:
        value = re.sub(r"<[^>]+>", " ", body_text)
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _source_page_date_evidence(body_text: str) -> str:
    """Extract only post-page publication metadata for the evidence prompt.

    Search-result dates and page-modified timestamps are deliberately excluded.
    The value remains raw source evidence; ``processing._question_freshness``
    still requires the extractor to bind it to the exact post permalink.
    """
    patterns = (
        r'"datePublished"\s*:\s*"([^"]+)"',
        r"<meta[^>]+(?:property|name)\s*=\s*[\"'](?:article:published_time|datepublished)[\"'][^>]+content\s*=\s*[\"']([^\"']+)",
        r"<meta[^>]+content\s*=\s*[\"']([^\"']+)[\"'][^>]+(?:property|name)\s*=\s*[\"'](?:article:published_time|datepublished)[\"']",
    )
    values: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, body_text, flags=re.IGNORECASE):
            value = re.sub(r"\s+", " ", match.group(1)).strip()[:255]
            if value and value not in values:
                values.append(value)
    if not values:
        return ""
    return "[SOURCE_PAGE_DATE_EVIDENCE] published_at_source=source_page; " + "; ".join(
        f"published_at_raw={value}" for value in values[:5]
    )


def _page_evidence(
    body_text: str, *, base_url: str, limit: int, forum_discovery: bool | None = None
) -> tuple[str, list[dict[str, str]]]:
    if forum_discovery is None:
        forum_discovery = _is_search_route(base_url)
    if forum_discovery and _is_search_route(base_url):
        search_text, search_links = _forum_search_page_evidence(
            body_text,
            base_url=base_url,
            limit=limit,
        )
        return search_text, search_links
    atom_evidence = _atom_feed_evidence(body_text, base_url=base_url, limit=limit)
    if atom_evidence is not None:
        return atom_evidence
    forum_links = _forum_post_links(body_text, base_url=base_url)
    if forum_links:
        return "\n".join(item["label"] for item in forum_links)[:limit], forum_links
    parser = _VisibleText(base_url)
    try:
        parser.feed(body_text)
        value = " ".join(parser.parts)
    except Exception:
        return _visible_text(body_text, limit), []
    visible = re.sub(r"\s+", " ", value).strip()
    metadata = _source_page_date_evidence(body_text)
    text = " ".join(part for part in (metadata, visible) if part)[:limit]
    links = list(parser.links)
    if (urlparse(base_url).hostname or "").casefold().endswith("qjob.hu"):
        task_parser = _QjobTaskCards(base_url)
        try:
            task_parser.feed(body_text)
        except Exception:
            task_parser.links = []
        task_urls = {item["url"] for item in task_parser.links}
        # Task cards are the actionable evidence; navigation links only fill the
        # remaining capacity after all concrete task permalinks.
        links = task_parser.links + [item for item in links if item["url"] not in task_urls]
    return text, links[:100]


def _atom_feed_evidence(
    body_text: str, *, base_url: str, limit: int
) -> tuple[str, list[dict[str, str]]] | None:
    """Bind each feed publication date to its post; a feed update proves no date."""
    if not re.search(r"<(?:[a-zA-Z0-9_]+:)?(?:feed|rss)\b", body_text[:1200], re.IGNORECASE):
        return None
    try:
        root = ElementTree.fromstring(body_text)
    except ElementTree.ParseError:
        return None

    def local(tag):
        return tag.rsplit("}", 1)[-1]

    links = []
    for entry in [node for node in root.iter() if local(node.tag) in {"entry", "item"}][:100]:
        values = {local(child.tag): str(child.text or "").strip() for child in entry}
        # Never fall back to updated, even when it occurs before published in the XML.
        raw_date = values.get("published") or values.get("pubDate") or ""
        title = values.get("title") or ""
        raw_content = (
            values.get("content") or values.get("description") or values.get("summary") or ""
        )
        permalink = ""
        for child in entry:
            if local(child.tag) == "link" and child.attrib.get("rel", "alternate") == "alternate":
                permalink = str(child.attrib.get("href") or child.text or "").strip()
                if permalink:
                    break
        canonical = urlunparse(urlparse(urljoin(base_url, permalink))._replace(fragment=""))
        if not permalink or not _reply_page_candidate(canonical, base_url=base_url):
            continue
        # Reddit appends submitter/profile links outside the original post body.
        raw_content = re.split(r"submitted\s+by", raw_content, maxsplit=1, flags=re.IGNORECASE)[0]
        excerpt = _visible_text(raw_content, 900)
        excerpt = re.sub(r"(?<!\w)/?u/[A-Za-z0-9_-]+", "[felhasználó]", excerpt)
        label = " ".join(part for part in (title, excerpt) if part).strip()[:850]
        label = label.replace("[SOURCE_PAGE_EVIDENCE]", "[idézett jelölés]")
        if raw_date and ";" not in raw_date and "\n" not in raw_date:
            label += (
                "\n[SOURCE_PAGE_EVIDENCE] published_at_raw="
                + raw_date[:255]
                + "; published_at_source=source_page"
            )
        if "[SOURCE_PAGE_EVIDENCE]" not in label:
            label += "\n[SOURCE_PAGE_EVIDENCE] published_at_source=unknown"
        if label and not any(item["url"] == canonical for item in links):
            links.append({"url": canonical, "label": label[:1200]})
    # An empty feed remains an empty feed, never a navigation-link fallback.
    return "\n".join(item["label"] for item in links)[:limit], links


def _public_land_pagination_entry(
    base_url: str,
    candidate_url: str,
) -> tuple[int, str] | None:
    """Return one exact same-category ``?page=N`` discovery URL.

    Pagination is deliberately narrower than ordinary same-portal binding: the
    scheme, hostname, port and path must remain byte-for-byte equivalent to the
    managed category route, and ``page`` must be the sole query parameter. This
    prevents a category page from expanding discovery onto search, login or
    unrelated portal surfaces.
    """

    base = urlparse(base_url)
    candidate = urlparse(urljoin(base_url, candidate_url))
    try:
        candidate_port = candidate.port
    except ValueError:
        return None
    if (
        base.scheme != "https"
        or candidate.scheme != "https"
        or not base.hostname
        or not candidate.hostname
        or candidate.username
        or candidate.password
        or (candidate_port not in {None, 443})
        or candidate.hostname.casefold() != base.hostname.casefold()
        or candidate.path.rstrip("/") != base.path.rstrip("/")
        or candidate.fragment
    ):
        return None
    query = parse_qsl(candidate.query, keep_blank_values=True)
    if len(query) != 1 or query[0][0].casefold() != "page":
        return None
    raw_page = query[0][1]
    if not raw_page.isascii() or not raw_page.isdigit():
        return None
    page = int(raw_page)
    if not 2 <= page <= LAND_PUBLIC_HTML_PAGINATION_PAGE_MAXIMUM:
        return None
    canonical = urlunparse(
        (
            "https",
            base.netloc,
            base.path,
            "",
            f"page={page}",
            "",
        )
    )
    return page, canonical


def _public_land_pagination_candidates(
    base_url: str,
    links: list[dict[str, str]],
) -> list[str]:
    by_page: dict[int, str] = {}
    for item in links:
        entry = _public_land_pagination_entry(base_url, str(item.get("url") or ""))
        if entry is not None:
            page, url = entry
            by_page.setdefault(page, url)
    return [by_page[page] for page in sorted(by_page)]


def _public_land_pagination_candidates_from_html(
    base_url: str,
    body_text: str,
) -> list[str]:
    # `_page_evidence` deliberately caps ordinary analysis links at 100. Portal
    # pagination is often rendered after those links, so scan the same bounded
    # HTML response independently while applying the much narrower URL policy
    # above.
    parser = _PublicLandPaginationLinks()
    try:
        parser.feed(body_text)
    except Exception:
        return []
    return _public_land_pagination_candidates(
        base_url,
        [{"url": href, "label": "pagination"} for href in parser.hrefs],
    )


def _managed_land_next_discovery_url(
    db: Session,
    *,
    route: SourceCoverageRoute,
    run_id: str,
) -> str | None:
    """Return only the next contiguous, observed category page for this run."""

    evidence_rows = list(
        db.scalars(
            select(SourceCoverageAttempt.evidence_json)
            .where(
                SourceCoverageAttempt.route_key == route.route_key,
                SourceCoverageAttempt.run_id == run_id,
            )
            .order_by(SourceCoverageAttempt.started_at, SourceCoverageAttempt.id)
        )
    )
    if not evidence_rows:
        return route.route_url

    attempted_pages: set[int] = set()
    candidate_by_page: dict[int, str] = {}
    pagination_metadata_seen = False
    for raw in evidence_rows:
        try:
            evidence = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(evidence, dict):
            continue
        if "land_discovery_url" not in evidence:
            continue
        pagination_metadata_seen = True
        discovery_url = str(evidence.get("land_discovery_url") or route.route_url)
        if discovery_url.rstrip("/") == route.route_url.rstrip("/"):
            attempted_pages.add(1)
        else:
            entry = _public_land_pagination_entry(route.route_url, discovery_url)
            if entry is not None:
                attempted_pages.add(entry[0])
        candidates = evidence.get("land_pagination_candidates")
        if isinstance(candidates, list):
            for value in candidates:
                entry = _public_land_pagination_entry(route.route_url, str(value or ""))
                if entry is not None:
                    candidate_by_page.setdefault(entry[0], entry[1])

    # A release deployed into an already-running daily ledger must refetch page
    # one exactly once to bind pagination metadata before it can advance.
    if not pagination_metadata_seen or 1 not in attempted_pages:
        return route.route_url

    next_page = 2
    while next_page in attempted_pages:
        next_page += 1
    return candidate_by_page.get(next_page)


def _looks_like_blocked_response(
    *, status_code: int, route_url: str, title: str | None, body_text: str, visible_text: str
) -> bool:
    if status_code in {401, 403, 407, 429, 451}:
        return True
    lowered_body = body_text.casefold()
    if any(marker in lowered_body for marker in BLOCKED_MARKERS):
        return True
    path = urlparse(route_url).path.casefold().rstrip("/")
    title_text = (title or "").casefold()
    login_page = any(marker in path for marker in LOGIN_PATH_MARKERS)
    login_language = any(
        marker in f"{title_text} {visible_text.casefold()}"
        for marker in ("bejelentkezés", "jelentkezzen be", "belépés", "log in", "sign in")
    )
    password_form = bool(
        re.search(r"<input[^>]+type\s*=\s*[\"']?password\b", body_text, re.I)
    )
    # A login link in ordinary navigation is not an authentication wall. Treat
    # it as blocking only when the requested URL is itself a login route, or a
    # short page is dominated by a password form and login language.
    return bool(
        (login_page and (login_language or password_form))
        or (password_form and login_language and len(visible_text) < 3_000)
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value: Any, limit: int | None = None) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    if not result:
        return None
    return result[:limit] if limit else result


def _scope_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).split())


def _building_route_enabled(record: dict[str, Any]) -> bool:
    status = _scope_text(record.get("Katalógusstátusz"))
    if status in {"disabled", "retired"}:
        return False
    if _scope_text(record.get("Motor")) != "imperial bautica prefab":
        return False
    canonical = _scope_text(_canonical_json(record))
    if contains_no_monitoring_entity(_canonical_json(record)):
        return False
    if any(marker in canonical for marker in _PROCUREMENT_MARKERS):
        return False
    country = _scope_text(record.get("Ország"))
    if country == "hu":
        return True
    if country not in {"at", "sk"}:
        return False
    explicit_route_text = _scope_text(
        " ".join(
            str(record.get(key) or "")
            for key in (
                "Kategória",
                "Forrás neve",
                "Keresési jel/kifejezés",
                "Márkailleszkedés",
            )
        )
    )
    return any(
        phrase in explicit_route_text
        for phrase in _FOREIGN_FAMILY_HOUSE_BUILD_OR_EXTENSION_PHRASES
    )


def _load_manifest(path: str | Path) -> tuple[dict[str, Any], str]:
    manifest_path = Path(path)
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise GrowthRegistryError("Canonical source-ledger manifest is unreadable") from exc
    expected = {
        "spreadsheet_id": SOURCE_LEDGER_SPREADSHEET_ID,
        "sheet_id": SOURCE_LEDGER_SHEET_ID,
        "route_count": SOURCE_LEDGER_ROUTE_COUNT,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise GrowthRegistryError("Canonical source-ledger manifest does not match policy")
    return manifest, hashlib.sha256(raw).hexdigest()


def _records(snapshot_path: str | Path) -> tuple[list[dict[str, Any]], str]:
    path = Path(snapshot_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GrowthRegistryError("Canonical source-ledger snapshot is unreadable") from exc
    snapshot_sha = hashlib.sha256(raw).hexdigest()
    records: list[dict[str, Any]] = []
    route_keys: set[str] = set()
    route_ids: set[str] = set()
    try:
        lines = raw.decode("utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"record {line_number} is not an object")
            route_key = _text(record.get("RouteKey"), 500)
            route_id = _text(record.get("RouteID"), 180)
            route_url = _text(record.get("Útvonal URL"), 3000)
            motor = _text(record.get("Motor"), 160)
            if not route_key or not route_id or not route_url or not motor:
                raise ValueError(f"record {line_number} lacks a required route field")
            if route_key in route_keys or route_id in route_ids:
                raise ValueError(f"record {line_number} duplicates a route identity")
            parsed = urlparse(route_url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError(f"record {line_number} contains a non-HTTPS route")
            canonical = _canonical_json(record)
            if contains_no_monitoring_entity(canonical):
                raise GrowthRegistryError("no_monitoring_hard_gate")
            route_keys.add(route_key)
            route_ids.add(route_id)
            records.append(record)
    except GrowthRegistryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GrowthRegistryError("Canonical source-ledger snapshot is invalid") from exc
    if len(records) != SOURCE_LEDGER_ROUTE_COUNT:
        raise GrowthRegistryError("Canonical source-ledger route count mismatch")
    return records, snapshot_sha


def _row(record: dict[str, Any], catalog_sha256: str, now: datetime) -> dict[str, Any]:
    canonical = _canonical_json(record)
    catalog_status = _text(record.get("Katalógusstátusz"), 120)
    route_id = _text(record.get("RouteID"), 180)
    return {
        "route_key": _text(record.get("RouteKey"), 500),
        "route_id": route_id,
        "catalog_sha256": catalog_sha256,
        "motor": _text(record.get("Motor"), 160),
        "catalog_part": _text(record.get("Katalógusrész"), 160),
        "country": _text(record.get("Ország"), 120),
        "brand_fit": _text(record.get("Márkailleszkedés"), 240),
        "category": _text(record.get("Kategória"), 240),
        "source_name": _text(record.get("Forrás neve"), 500),
        "source_type": _text(record.get("Forrástípus"), 120),
        "search_signal": _text(record.get("Keresési jel/kifejezés")),
        "route_url": ROUTE_URL_OVERRIDES.get(
            route_id or "", _text(record.get("Útvonal URL"), 3000)
        ),
        "base_url": _text(record.get("Alap URL"), 3000),
        "route_mode": _text(record.get("Útvonalmód"), 80),
        "priority": _text(record.get("Prioritás"), 80),
        "validation": _text(record.get("Validáció"), 120),
        "catalog_status": catalog_status,
        "source_updated_value": _text(record.get("Katalógus frissítése"), 120),
        "notes": _text(record.get("Megjegyzés")),
        "source_row_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "source_record_json": canonical,
        "enabled": _building_route_enabled(record),
        "created_at": now,
        "updated_at": now,
    }


def _upsert_routes(
    db: Session,
    rows: list[dict[str, Any]],
    *,
    preserve_existing: frozenset[str] = frozenset(),
) -> None:
    dialect = db.get_bind().dialect.name
    insert_factory = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect)
    if not insert_factory:
        for values in rows:
            existing = db.scalar(
                select(SourceCoverageRoute).where(
                    SourceCoverageRoute.route_key == values["route_key"]
                )
            )
            if not existing:
                db.add(SourceCoverageRoute(**values))
                continue
            for key, value in values.items():
                if key not in {"created_at"} | preserve_existing:
                    setattr(existing, key, value)
        return
    immutable_runtime = {
        "id",
        "created_at",
        "attempt_count",
        "success_count",
        "last_attempt_at",
        "last_success_at",
        "last_result",
        "next_due_at",
    }
    for start in range(0, len(rows), 500):
        statement = insert_factory(SourceCoverageRoute).values(rows[start : start + 500])
        updates = {
            column.name: getattr(statement.excluded, column.name)
            for column in SourceCoverageRoute.__table__.columns
            if column.name not in immutable_runtime | preserve_existing
        }
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[SourceCoverageRoute.route_key],
                set_=updates,
            )
        )


def import_snapshot(
    db: Session,
    *,
    snapshot_path: str | Path,
    manifest_path: str | Path,
) -> SourceCatalogRevision:
    manifest, _manifest_sha = _load_manifest(manifest_path)
    records, snapshot_sha = _records(snapshot_path)
    if manifest.get("catalog_sha256") != snapshot_sha:
        raise GrowthRegistryError("Canonical source-ledger snapshot hash mismatch")
    now = datetime.now(UTC)
    rows = [_row(record, snapshot_sha, now) for record in records]
    revision = db.scalar(
        select(SourceCatalogRevision).where(
            SourceCatalogRevision.catalog_sha256 == snapshot_sha
        )
    )
    if not revision:
        revision = SourceCatalogRevision(
            revision_id=f"SCR-{uuid4().hex[:20].upper()}",
            spreadsheet_id=SOURCE_LEDGER_SPREADSHEET_ID,
            sheet_id=SOURCE_LEDGER_SHEET_ID,
            source_modified_time=str(manifest["modified_time"]),
            catalog_sha256=snapshot_sha,
            route_count=len(rows),
            status="importing",
            imported_at=now,
        )
        db.add(revision)
        db.flush()
    _upsert_routes(db, rows)
    db.execute(
        update(SourceCoverageRoute)
        .where(
            SourceCoverageRoute.catalog_sha256 != snapshot_sha,
            SourceCoverageRoute.route_key.not_like(f"{LAND_PUBLIC_HTML_ROUTE_PREFIX}%"),
            SourceCoverageRoute.route_key.not_like("QUESTION-RADAR:%"),
        )
        .values(enabled=False, updated_at=now)
    )
    db.execute(
        update(SourceCatalogRevision)
        .where(SourceCatalogRevision.catalog_sha256 != snapshot_sha)
        .values(status="retired")
    )
    active_count = int(
        db.scalar(
            select(func.count())
            .select_from(SourceCoverageRoute)
            .where(
                SourceCoverageRoute.catalog_sha256 == snapshot_sha,
                SourceCoverageRoute.enabled.is_(True),
            )
        )
        or 0
    )
    if active_count <= 0:
        db.rollback()
        raise GrowthRegistryError("Imported building source scope is empty")
    revision.status = "active"
    revision.route_count = len(rows)
    revision.imported_at = now
    db.commit()
    return revision


def ensure_question_radar_direct_routes(
    db: Session,
    *,
    catalog_sha256: str,
    now: datetime | None = None,
) -> None:
    """Keep the approved direct public question surfaces beside the ledger.

    These rows deliberately use the current canonical revision hash so a later
    source-ledger import cannot silently disable the direct question feed.  The
    rows are still ordinary ``SourceCoverageRoute`` records, so all existing
    URL, robots, evidence, dedupe and freshness checks remain in force.
    """

    timestamp = now or datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for spec in QUESTION_RADAR_DIRECT_ROUTES:
        route_parsed = urlparse(spec["route_url"])
        route_base_url = f"{route_parsed.scheme}://{route_parsed.netloc}"
        record = {
            "RouteKey": spec["route_key"],
            "RouteID": spec["route_id"],
            "Motor": "Imperial–Bautica–Prefab",
            "Katalógusrész": "question_radar_direct_v1",
            "Ország": "HU",
            "Márkailleszkedés": spec["brand_fit"],
            "Kategória": "forum",
            "Forrás neve": spec["source_name"],
            "Forrástípus": "public_html",
            "Keresési jel/kifejezés": spec["search_signal"],
            "Útvonal URL": spec["route_url"],
            "Alap URL": route_base_url,
            "Útvonalmód": "direct",
            "Prioritás": "0",
            "Validáció": "runtime_direct_source",
            "Katalógusstátusz": "active",
            "Katalógus frissítése": "runtime",
            "Megjegyzés": (
                "Közvetlen nyilvános kérdéslista; a konkrét kérdésoldal dátuma, "
                "aktív állapota és válaszszáma külön visszaolvasandó."
            ),
        }
        canonical = _canonical_json(record)
        rows.append(
            {
                "route_key": spec["route_key"],
                "route_id": spec["route_id"],
                "catalog_sha256": catalog_sha256,
                "motor": record["Motor"],
                "catalog_part": record["Katalógusrész"],
                "country": record["Ország"],
                "brand_fit": record["Márkailleszkedés"],
                "category": record["Kategória"],
                "source_name": record["Forrás neve"],
                "source_type": record["Forrástípus"],
                "search_signal": record["Keresési jel/kifejezés"],
                "route_url": record["Útvonal URL"],
                "base_url": record["Alap URL"],
                "route_mode": record["Útvonalmód"],
                "priority": record["Prioritás"],
                "validation": record["Validáció"],
                "catalog_status": record["Katalógusstátusz"],
                "source_updated_value": record["Katalógus frissítése"],
                "notes": record["Megjegyzés"],
                "source_row_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
                "source_record_json": canonical,
                "enabled": True,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
    _upsert_routes(db, rows, preserve_existing=frozenset({"enabled"}))
    for route in db.scalars(
        select(SourceCoverageRoute).where(
            SourceCoverageRoute.route_key.in_(
                [spec["route_key"] for spec in QUESTION_RADAR_DIRECT_ROUTES]
            ),
            SourceCoverageRoute.last_attempt_at.is_not(None),
            SourceCoverageRoute.next_due_at.is_not(None),
        )
    ).all():
        # Only migrate the exact previous automatic one-day interval. Custom
        # retry times and operator-disabled sources keep their existing state.
        if route.next_due_at - route.last_attempt_at == timedelta(days=1):
            minutes = 30 if route.last_result == "succeeded" else 60
            route.next_due_at = route.last_attempt_at + timedelta(minutes=minutes)
    # Discovered posts are runtime additions beside the immutable ledger.
    # Carry them into its current revision without resetting operator choices.
    db.execute(
        update(SourceCoverageRoute)
        .where(
            SourceCoverageRoute.route_key.like(f"{QUESTION_RADAR_DISCOVERED_ROUTE_PREFIX}%"),
            SourceCoverageRoute.catalog_sha256 != catalog_sha256,
        )
        .values(catalog_sha256=catalog_sha256, updated_at=timestamp)
    )
    db.flush()


def _upsert_discovered_forum_routes(
    db: Session,
    *,
    catalog_sha256: str,
    parent_route: SourceCoverageRoute,
    links: list[dict[str, str]],
    now: datetime,
) -> int:
    """Persist exact forum permalinks found by a search route, idempotently."""

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in links[:40]:
        raw_url = str(item.get("url") or "").strip()
        canonical = _canonical_forum_result_url(raw_url, base_url=parent_route.route_url)
        if not _forum_search_result_candidate(canonical, base_url=parent_route.route_url):
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        parsed = urlparse(canonical)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        route_key = f"{QUESTION_RADAR_DISCOVERED_ROUTE_PREFIX}{digest[:40].upper()}"
        route_id = f"QR-DISC-{digest[:32].upper()}"
        source_name = f"Felfedezett fórum – {(parsed.hostname or 'ismeretlen').casefold()}"
        record = {
            "RouteKey": route_key,
            "RouteID": route_id,
            "Motor": "Imperial–Bautica–Prefab",
            "Katalógusrész": "question_radar_discovered_forum_v1",
            "Ország": "HU",
            "Márkailleszkedés": parent_route.brand_fit or "BauFreund,Bautica,Prefab",
            "Kategória": "forum",
            "Forrás neve": source_name,
            "Forrástípus": "public_html",
            "Keresési jel/kifejezés": (
                parent_route.search_signal
                or "építkezés; felújítás; kivitelező"
            ),
            "Útvonal URL": canonical,
            "Alap URL": f"{parsed.scheme}://{parsed.netloc}",
            "Útvonalmód": "direct_post",
            "Prioritás": "1",
            "Validáció": "runtime_forum_discovery",
            "Katalógusstátusz": "active",
            "Katalógus frissítése": "runtime",
            "Megjegyzés": (
                f"Automatikusan felfedezett konkrét fórum-bejegyzés; parent_route="
                f"{parent_route.route_key}; discovery_url={parent_route.route_url}. "
                "A publikálás és a küldés külön policy-kapuk alatt marad."
            ),
        }
        canonical_record = _canonical_json(record)
        if contains_no_monitoring_entity(canonical_record):
            continue
        rows.append(
            {
                "route_key": route_key,
                "route_id": route_id,
                "catalog_sha256": catalog_sha256,
                "motor": record["Motor"],
                "catalog_part": record["Katalógusrész"],
                "country": record["Ország"],
                "brand_fit": record["Márkailleszkedés"],
                "category": record["Kategória"],
                "source_name": record["Forrás neve"],
                "source_type": record["Forrástípus"],
                "search_signal": record["Keresési jel/kifejezés"],
                "route_url": canonical,
                "base_url": record["Alap URL"],
                "route_mode": record["Útvonalmód"],
                "priority": record["Prioritás"],
                "validation": record["Validáció"],
                "catalog_status": record["Katalógusstátusz"],
                "source_updated_value": record["Katalógus frissítése"],
                "notes": record["Megjegyzés"],
                "source_row_sha256": hashlib.sha256(canonical_record.encode()).hexdigest(),
                "source_record_json": canonical_record,
                "enabled": True,
                "created_at": now,
                "updated_at": now,
            }
        )
    if not rows:
        return 0
    _upsert_routes(db, rows, preserve_existing=frozenset({"enabled", "brand_fit"}))
    db.flush()
    return len(rows)


def active_revision(db: Session) -> SourceCatalogRevision:
    revision = db.scalar(
        select(SourceCatalogRevision)
        .where(SourceCatalogRevision.status == "active")
        .order_by(SourceCatalogRevision.imported_at.desc())
        .limit(1)
    )
    if not revision or revision.route_count != SOURCE_LEDGER_ROUTE_COUNT:
        raise GrowthRegistryError("DB-native source catalog is not active")
    return revision


def _local_start(now: datetime) -> tuple[datetime, datetime]:
    zone = ZoneInfo(settings().timezone)
    local_now = now.astimezone(zone)
    hour, minute = (int(part) for part in settings().canonical_daily_at.split(":"))
    start_local = datetime.combine(local_now.date(), time(hour, minute), zone)
    return local_now, start_local


def _fetch_public_land_listing(url: str, *, max_response_bytes: int) -> dict[str, Any]:
    portal_error = _public_html_portal_error(url)
    if portal_error:
        return {
            "status": "failed" if portal_error == "portal_registry_unavailable" else "rejected",
            "error_type": portal_error,
        }
    deadline = monotonic_time.monotonic() + settings().canonical_route_timeout_seconds
    robots_error = _fresh_pinned_robots_error(url, deadline_monotonic=deadline)
    if robots_error:
        return {
            "status": "failed" if robots_error == "portal_robots_unavailable" else "rejected",
            "error_type": robots_error,
        }
    try:
        response = _pinned_https_get(
            url,
            max_response_bytes=max_response_bytes,
            deadline_monotonic=deadline,
        )
    except UnsafeRouteError as exc:
        error_type = str(exc)
        return {
            "status": (
                "blocked"
                if error_type
                in {
                    "response_compression_forbidden",
                    "response_too_large",
                }
                else "rejected"
                if error_type
                in {
                    "invalid_route_url",
                    "non_public_target",
                    "non_standard_https_port",
                }
                else "failed"
            ),
            "error_type": error_type,
        }
    status_code = int(response["status_code"])
    content_type = str(response["headers"].get("content-type", ""))[:240]
    body = bytes(response["body"])
    body_text = body.decode("utf-8", errors="ignore")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", body_text, re.I | re.S)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip()[:500] if title_match else None
    visible_text = _visible_text(body_text, 6_000)
    if (
        _looks_like_blocked_response(
            status_code=status_code,
            route_url=url,
            title=title,
            body_text=body_text,
            visible_text=visible_text,
        )
        or 300 <= status_code < 400
    ):
        return {"status": "blocked", "http_status": status_code, "error_type": "blocked_page"}
    if not 200 <= status_code < 300 or not body:
        return {"status": "failed", "http_status": status_code, "error_type": "listing_unavailable"}
    if "html" not in content_type.casefold():
        return {
            "status": "rejected",
            "http_status": status_code,
            "error_type": "listing_not_html",
        }
    return {
        "status": "succeeded",
        "http_status": status_code,
        "url": url,
        "html": body_text,
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "source_ip": str(response["source_ip"]),
    }


def fetch_public_land_listing_url(url: str) -> dict[str, Any]:
    """Refetch one exact public listing with the scanner's unchanged safety policy."""

    cfg = settings()
    if not is_specific_listing_permalink(url):
        return {"status": "rejected", "error_type": "concrete_listing_permalink_missing"}
    return _fetch_public_land_listing(
        url,
        max_response_bytes=cfg.canonical_route_max_response_bytes,
    )


def _fetch(
    route: SourceCoverageRoute,
    *,
    managed_land: bool = False,
    discovery_url: str | None = None,
    pending_listing_urls: list[str] | None = None,
    examined_listing_urls: set[str] | None = None,
    replay_only_listing_urls: set[str] | None = None,
    listing_fetch_limit: int | None = None,
) -> dict[str, Any]:
    cfg = settings()
    fetch_url = route.route_url
    if discovery_url is not None:
        if not managed_land:
            return {"status": "rejected", "error_type": "managed_land_pagination_forbidden"}
        if discovery_url.rstrip("/") != route.route_url.rstrip("/"):
            pagination_entry = _public_land_pagination_entry(
                route.route_url,
                discovery_url,
            )
            if pagination_entry is None:
                return {
                    "status": "rejected",
                    "error_type": "managed_land_pagination_url_invalid",
                }
            fetch_url = pagination_entry[1]
    parsed = urlparse(fetch_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return {"status": "rejected", "error_type": "invalid_route_url"}
    named_portal = is_named_portal_host(parsed.hostname)
    if named_portal:
        portal_error = _public_html_portal_error(fetch_url)
        if portal_error:
            return {
                "status": "failed" if portal_error == "portal_registry_unavailable" else "rejected",
                "error_type": portal_error,
            }
    if not named_portal:
        try:
            assert_public_https_url(fetch_url)
        except UnsafeRouteError as exc:
            return {"status": "rejected", "error_type": str(exc)}
    if contains_no_monitoring_entity(route.source_record_json):
        return {"status": "rejected", "error_type": "no_monitoring_hard_gate"}
    content = bytearray()
    source_ip: str | None = None
    forum_response: dict[str, Any] | None = None
    try:
        if named_portal:
            deadline = (
                monotonic_time.monotonic() + cfg.canonical_route_timeout_seconds
            )
            robots_error = _fresh_pinned_robots_error(
                fetch_url,
                deadline_monotonic=deadline,
            )
            if robots_error:
                return {
                    "status": (
                        "failed"
                        if robots_error == "portal_robots_unavailable"
                        else "rejected"
                    ),
                    "error_type": robots_error,
                }
            response_data = _pinned_https_get(
                fetch_url,
                max_response_bytes=cfg.canonical_route_max_response_bytes,
                deadline_monotonic=deadline,
            )
            status_code = int(response_data["status_code"])
            content_type = str(
                response_data["headers"].get("content-type", "")
            )[:240]
            content.extend(bytes(response_data["body"]))
            source_ip = str(response_data["source_ip"])
        elif (
            (parsed.hostname or "").casefold() in {"forum.index.hu", "prohardver.hu"}
            or getattr(route, "route_mode", None) == "direct_post"
        ):
            forum_response = _forum_page_get(
                fetch_url,
                timeout_seconds=cfg.canonical_route_timeout_seconds,
                max_response_bytes=cfg.canonical_route_max_response_bytes,
            )
            status_code = int(forum_response["status_code"])
            content_type = str(forum_response.get("headers", {}).get("content-type", ""))[:240]
            content.extend(bytes(forum_response["body"]))
            source_ip = str(forum_response.get("source_ip") or "") or None
        else:
            with httpx.Client(
                timeout=cfg.canonical_route_timeout_seconds,
                follow_redirects=False,
                headers={"User-Agent": "Imperial-Source-Coverage/1.0"},
            ) as client:
                with client.stream("GET", fetch_url) as response:
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > cfg.canonical_route_max_response_bytes:
                            return {
                                "status": "blocked",
                                "http_status": response.status_code,
                                "error_type": "response_too_large",
                            }
                    status_code = response.status_code
                    content_type = response.headers.get("content-type", "")[:240]
    except UnsafeRouteError as exc:
        error_type = str(exc)
        return {
            "status": (
                "blocked"
                if error_type
                in {
                    "response_compression_forbidden",
                    "response_too_large",
                }
                else "rejected"
                if error_type
                in {
                    "invalid_route_url",
                    "non_public_target",
                    "non_standard_https_port",
                }
                else "failed"
            ),
            "error_type": error_type,
        }
    except (httpx.HTTPError, OSError, ValueError) as exc:
        return {"status": "failed", "error_type": type(exc).__name__}
    body = bytes(content)
    body_text = (
        _forum_decode_body(forum_response)
        if forum_response else body.decode("utf-8", errors="ignore")
    )
    title_match = re.search(r"<title[^>]*>(.*?)</title>", body_text, re.I | re.S)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip()[:500] if title_match else None
    forum_discovery = _is_forum_discovery_route(route)
    analysis_text, analysis_links = _page_evidence(
        body_text,
        base_url=fetch_url,
        limit=getattr(cfg, "canonical_analysis_text_chars", 6000),
        forum_discovery=forum_discovery,
    )
    if 200 <= status_code < 300 and body:
        # The list page is discovery only.  For supported question/task
        # surfaces, verify each bounded concrete permalink on its own page so
        # the extractor receives the original publication date and lifecycle
        # evidence rather than a search/list refresh time.
        if parsed.hostname == "forum.index.hu" and parsed.path.casefold() == "/topic/showtopiclist":
            analysis_links = _expand_index_forum_threads(
                analysis_links, base_url=fetch_url,
                timeout_seconds=cfg.canonical_route_timeout_seconds,
                max_response_bytes=cfg.canonical_route_max_response_bytes,
            )
            analysis_text = "\n".join(item["label"] for item in analysis_links)[
                :getattr(cfg, "canonical_analysis_text_chars", 6000)
            ]
        if forum_discovery:
            analysis_links = _enrich_discovered_forum_links(
                analysis_links,
                discovery_url=fetch_url,
                timeout_seconds=cfg.canonical_route_timeout_seconds,
                max_response_bytes=cfg.canonical_route_max_response_bytes,
            )
        else:
            if getattr(route, "route_mode", None) == "direct_post" and _reply_page_candidate(
                fetch_url,
                base_url=fetch_url,
            ):
                analysis_links = [
                    {
                        "url": fetch_url,
                        "label": analysis_text[:900].replace(
                            "[SOURCE_PAGE_EVIDENCE]", "[idézett jelölés]"
                        ),
                    },
                    *analysis_links,
                ]
            analysis_links = _enrich_reply_page_links(
                analysis_links,
                base_url=fetch_url,
                timeout_seconds=cfg.canonical_route_timeout_seconds,
                max_response_bytes=cfg.canonical_route_max_response_bytes,
            )
    blocked = _looks_like_blocked_response(
        status_code=status_code,
        route_url=fetch_url,
        title=title,
        body_text=body_text,
        visible_text=analysis_text,
    )
    if blocked or 300 <= status_code < 400:
        result_status = "blocked"
    elif 200 <= status_code < 300 and body:
        result_status = "succeeded"
    else:
        result_status = "failed"
    land_listing_pages: list[dict[str, Any]] = []
    land_listing_fetches: list[dict[str, Any]] = []
    all_candidate_urls: list[str] = []
    if managed_land and named_portal and result_status == "succeeded":
        route_host = (parsed.hostname or "").casefold()
        if replay_only_listing_urls is not None:
            # A same-day policy replay may re-fetch only the cursor rows named by
            # its audit-bound marker. The category response remains observable,
            # but must not expand the replay into newly discovered URLs.
            candidate_urls = [
                url
                for url in pending_listing_urls or []
                if url in replay_only_listing_urls
            ]
        else:
            candidate_urls = list(pending_listing_urls or [])
            if is_specific_listing_permalink(fetch_url):
                candidate_urls.append(fetch_url)
            candidate_urls.extend(
                str(item["url"])
                for item in analysis_links
                if is_specific_listing_permalink(item.get("url"))
                and same_named_portal_binding(
                    urlparse(str(item.get("url") or "")).hostname or "",
                    route_host,
                )
            )
        all_candidate_urls = list(dict.fromkeys(candidate_urls))
        effective_fetch_limit = min(
            LAND_PUBLIC_HTML_LISTING_FETCH_MAXIMUM,
            max(
                0,
                LAND_PUBLIC_HTML_LISTING_FETCH_MAXIMUM
                if listing_fetch_limit is None
                else listing_fetch_limit,
            ),
        )
        candidate_urls = [
            url for url in all_candidate_urls if url not in (examined_listing_urls or set())
        ][:effective_fetch_limit]
        for listing_url in candidate_urls:
            if listing_url == fetch_url:
                listing_result = {
                    "status": "succeeded",
                    "http_status": status_code,
                    "url": listing_url,
                    "html": body_text,
                    "response_sha256": hashlib.sha256(body).hexdigest(),
                }
            else:
                listing_result = _fetch_public_land_listing(
                    listing_url,
                    max_response_bytes=cfg.canonical_route_max_response_bytes,
                )
            land_listing_fetches.append(
                {
                    "url": listing_url,
                    "status": listing_result["status"],
                    "http_status": listing_result.get("http_status"),
                    "error_type": listing_result.get("error_type"),
                }
            )
            if listing_result["status"] == "succeeded":
                land_listing_pages.append(listing_result)
    return {
        "status": result_status,
        "http_status": status_code,
        "response_sha256": hashlib.sha256(body).hexdigest() if body else None,
        "evidence": {
            "content_bytes": len(body),
            "content_type": content_type,
            "title": title,
            "host": parsed.hostname,
            "source_ip": source_ip,
            "discovery_mode": (
                "search_engine_forum_discovery"
                if forum_discovery
                else "public_html"
                if named_portal
                else "generic_html"
            ),
            "robots_txt": "allowed" if named_portal else "not_applicable",
            "land_listing_fetches": land_listing_fetches,
            "land_listing_candidate_count": (
                len(all_candidate_urls) if managed_land and named_portal else 0
            ),
            "land_discovery_url": fetch_url if managed_land and named_portal else None,
            "land_pagination_candidates": (
                _public_land_pagination_candidates_from_html(
                    route.route_url,
                    body_text,
                )
                if managed_land and named_portal and result_status == "succeeded"
                else []
            ),
        },
        # Transient only: the worker gives this bounded visible-text sample to the
        # evidence extractor, but never persists the full fetched page body.
        "analysis_text": analysis_text if result_status == "succeeded" else "",
        "analysis_links": analysis_links if result_status == "succeeded" else [],
        "land_listing_pages": land_listing_pages,
        "land_listing_candidates": (
            all_candidate_urls if managed_land and named_portal else []
        ),
        "land_listing_exhausted": (
            len(
                [
                    url
                    for url in all_candidate_urls
                    if url not in (examined_listing_urls or set())
                ]
            )
            <= (
                LAND_PUBLIC_HTML_LISTING_FETCH_MAXIMUM
                if listing_fetch_limit is None
                else min(
                    LAND_PUBLIC_HTML_LISTING_FETCH_MAXIMUM,
                    max(0, listing_fetch_limit),
                )
            )
            if managed_land and named_portal
            else True
        ),
    }


def _budapest_today() -> date:
    return datetime.now(UTC).astimezone(ZoneInfo("Europe/Budapest")).date()


def replay_public_land_policy_cursors(
    db: Session,
    *,
    policy_version: str,
    scope_local_date: date,
    max_rows: int,
    apply: bool,
    expected_plan_sha256: str | None,
    reason: str,
    actor: str,
) -> dict[str, Any]:
    """Preview or reset examined cursors for one bounded, audited policy replay.

    This operation never fetches a listing and never dispatches outreach. Applied
    rows become pending so the normal managed route scanner performs the next live
    fetch, evidence extraction, ingest, suppression and queueing flow.
    """

    if policy_version != LAND_RECIPIENT_POLICY_VERSION:
        raise GrowthRegistryError("public_land_policy_replay_version_invalid")
    if max_rows < 1 or max_rows > 210:
        raise GrowthRegistryError("public_land_policy_replay_limit_invalid")
    if len(reason.strip()) < 10:
        raise GrowthRegistryError("public_land_policy_replay_reason_required")

    audit_entity_id = policy_version
    existing_audit = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "growth_public_land_policy_replay_applied",
            AuditLog.entity_type == "growth_public_land_policy_replay",
            AuditLog.entity_id == audit_entity_id,
        )
        .order_by(AuditLog.id.desc())
    )
    if existing_audit is not None:
        try:
            recorded = json.loads(existing_audit.after_json or "{}")
        except json.JSONDecodeError as exc:
            raise GrowthRegistryError(
                "public_land_policy_replay_audit_unreadable"
            ) from exc
        return {
            **recorded,
            "status": "already_applied",
            "apply": apply,
            "idempotent": True,
            "audit_log_id": existing_audit.id,
        }
    if scope_local_date != _budapest_today():
        raise GrowthRegistryError("public_land_policy_replay_scope_not_current")

    from ..land_acquisition.service import public_land_route_readiness

    route_state = public_land_route_readiness(db)
    if route_state.get("ready") is not True:
        raise GrowthRegistryError("public_land_policy_replay_routes_not_ready")
    route_keys = sorted(str(item["route_key"]) for item in route_state.get("routes", []))
    timezone = ZoneInfo("Europe/Budapest")
    start_local = datetime.combine(scope_local_date, time.min, tzinfo=timezone)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)
    filters = (
        GrowthPublicLandListingCursor.route_key.in_(route_keys),
        GrowthPublicLandListingCursor.status == "examined",
        GrowthPublicLandListingCursor.examined_at >= start_utc,
        GrowthPublicLandListingCursor.examined_at < end_utc,
    )
    total = int(
        db.scalar(
            select(func.count())
            .select_from(GrowthPublicLandListingCursor)
            .where(*filters)
        )
        or 0
    )
    row_query = (
        select(GrowthPublicLandListingCursor)
        .where(*filters)
        .order_by(
            GrowthPublicLandListingCursor.route_key,
            GrowthPublicLandListingCursor.id,
        )
        .limit(max_rows)
    )
    if apply:
        row_query = row_query.with_for_update()
    rows = list(db.scalars(row_query))
    items = [
        {
            "cursor_id": row.id,
            "route_key": row.route_key,
            "listing_url_sha256": row.listing_url_sha256,
            "original_examined_at": (
                row.examined_at.isoformat() if row.examined_at else None
            ),
        }
        for row in rows
    ]
    plan = {
        "policy_version": policy_version,
        "scope_local_date": scope_local_date.isoformat(),
        "route_set_sha256": route_state.get("route_set_sha256"),
        "selected_count": len(items),
        "total_matching": total,
        "truncated": total > max_rows,
        "items": items,
    }
    plan_sha256 = hashlib.sha256(_canonical_json(plan).encode("utf-8")).hexdigest()
    result = {
        "status": "preview" if not apply else "applied",
        "apply": apply,
        "idempotent": False,
        "plan_sha256": plan_sha256,
        **plan,
    }
    if not apply:
        return result
    if plan["truncated"]:
        raise GrowthRegistryError("public_land_policy_replay_limit_too_small")
    if expected_plan_sha256 != plan_sha256:
        raise GrowthRegistryError("public_land_policy_replay_plan_changed")
    marker = Path(settings().runtime_kill_switch_file)
    try:
        marker_value = marker.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise GrowthRegistryError(
            "public_land_policy_replay_runtime_kill_switch_required"
        ) from exc
    if marker_value != "KILLED":
        raise GrowthRegistryError(
            "public_land_policy_replay_runtime_kill_switch_required"
        )
    changed_at = datetime.now(UTC)
    for row in rows:
        row.status = "pending"
        row.last_result = f"policy_replay:{policy_version}"
        row.next_retry_at = None
        row.updated_at = changed_at
    audit_payload = {
        **result,
        "items": [
            {
                "cursor_id": item["cursor_id"],
                "route_key": item["route_key"],
                "listing_url_sha256": item["listing_url_sha256"],
                "original_examined_at": item["original_examined_at"],
            }
            for item in items
        ],
        "reason": reason.strip(),
        "changed_at": changed_at.isoformat(),
    }
    audit(
        db,
        actor=actor,
        action="growth_public_land_policy_replay_applied",
        entity_type="growth_public_land_policy_replay",
        entity_id=audit_entity_id,
        before={"examined": len(rows), "pending": 0},
        after=audit_payload,
    )
    db.commit()
    recorded_audit = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "growth_public_land_policy_replay_applied",
            AuditLog.entity_type == "growth_public_land_policy_replay",
            AuditLog.entity_id == audit_entity_id,
        )
        .order_by(AuditLog.id.desc())
    )
    return {
        **result,
        "audit_log_id": recorded_audit.id if recorded_audit else None,
    }


def scan_due_routes(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    cfg = settings()
    if not cfg.canonical_wide_enabled or not cfg.canonical_route_scanning_enabled:
        return {"status": "disabled", "attempted": 0}
    current = now or datetime.now(UTC)
    local_now, start_local = _local_start(current)
    if local_now < start_local:
        return {"status": "not_due", "attempted": 0}
    revision = active_revision(db)
    ensure_question_radar_direct_routes(db, catalog_sha256=revision.catalog_sha256, now=current)
    start_utc = start_local.astimezone(UTC)
    from .models import CanonicalGrowthDailyRun

    daily_run = db.scalar(
        select(CanonicalGrowthDailyRun).where(
            CanonicalGrowthDailyRun.local_date == local_now.date()
        )
    )
    run_id = (
        daily_run.run_id
        if daily_run
        else f"BUILDING-{local_now.strftime('%Y%m%d')}-V216"
    )
    active_route_keys = select(SourceCoverageRoute.route_key).where(
        SourceCoverageRoute.enabled.is_(True),
        SourceCoverageRoute.catalog_sha256 == revision.catalog_sha256,
    )
    active_route_target = int(
        db.scalar(
            select(func.count())
            .select_from(SourceCoverageRoute)
            .where(
                SourceCoverageRoute.enabled.is_(True),
                SourceCoverageRoute.catalog_sha256 == revision.catalog_sha256,
            )
        )
        or 0
    )
    attempted_today = int(
        db.scalar(
            select(func.count(func.distinct(SourceCoverageAttempt.route_key)))
            .where(
                SourceCoverageAttempt.started_at >= start_utc,
                SourceCoverageAttempt.catalog_sha256 == revision.catalog_sha256,
                SourceCoverageAttempt.run_id == run_id,
                SourceCoverageAttempt.route_key.in_(active_route_keys),
            )
        )
        or 0
    )
    unique_leads_today = int(
        db.scalar(
            select(func.count())
            .select_from(GrowthSignal)
            .where(GrowthSignal.created_at >= start_utc)
        )
        or 0
    )
    attempted_route_keys = select(SourceCoverageAttempt.route_key).where(
        SourceCoverageAttempt.started_at >= start_utc,
        SourceCoverageAttempt.catalog_sha256 == revision.catalog_sha256,
        SourceCoverageAttempt.run_id == run_id,
        SourceCoverageAttempt.route_key.in_(active_route_keys),
    )
    radar_keys = [spec["route_key"] for spec in QUESTION_RADAR_DIRECT_ROUTES]
    radar_due = (
        SourceCoverageRoute.route_key.in_(radar_keys)
        & (SourceCoverageRoute.route_mode == "direct")
        & (SourceCoverageRoute.next_due_at <= current)
        & SourceCoverageRoute.route_key.in_(attempted_route_keys)
    )
    refresh_due_count = int(db.scalar(
        select(func.count()).select_from(SourceCoverageRoute).where(
            SourceCoverageRoute.enabled.is_(True),
            SourceCoverageRoute.catalog_sha256 == revision.catalog_sha256,
            radar_due,
        )
    ) or 0)
    allowance = max(0, min(
        cfg.canonical_route_batch_size,
        active_route_target - attempted_today + refresh_due_count,
    ))
    candidates = db.scalars(
        select(SourceCoverageRoute)
        .where(
            SourceCoverageRoute.enabled.is_(True),
            SourceCoverageRoute.catalog_sha256 == revision.catalog_sha256,
            or_(SourceCoverageRoute.route_key.not_in(attempted_route_keys), radar_due),
        )
        .order_by(
            case(
                (
                    SourceCoverageRoute.route_key.in_(radar_keys)
                    & SourceCoverageRoute.route_key.not_in(attempted_route_keys), 0,
                ),
                (radar_due, 1),
                (SourceCoverageRoute.route_mode == "direct_post", 2),
                (SourceCoverageRoute.route_mode == "direct", 3),
                else_=4,
            ),
            SourceCoverageRoute.last_attempt_at.asc().nulls_first(),
            SourceCoverageRoute.priority.asc(),
            SourceCoverageRoute.id.asc(),
        )
        .limit(max(allowance * 5, allowance) if allowance else 0)
    ).all() if allowance else []
    selected: list[SourceCoverageRoute] = []
    already_attempted = set(db.scalars(attempted_route_keys).all())
    hosts: set[str] = set()
    for route in candidates:
        host = (urlparse(route.route_url).hostname or "").casefold()
        if host in hosts:
            continue
        hosts.add(host)
        selected.append(route)
        if len(selected) >= allowance:
            break
    land_run_id = f"LAND-PUBLIC-{local_now.strftime('%Y%m%d')}-V1"
    from ..land_acquisition.service import public_land_route_readiness

    managed_route_state = public_land_route_readiness(db)
    expected_managed_route_keys = [
        str(item["route_key"]) for item in managed_route_state.get("routes", [])
    ]
    managed_routes = (
        list(
            db.scalars(
                select(SourceCoverageRoute)
                .where(
                    SourceCoverageRoute.enabled.is_(True),
                    SourceCoverageRoute.route_key.in_(expected_managed_route_keys),
                    SourceCoverageRoute.catalog_sha256
                    == managed_route_state.get("route_set_sha256"),
                    SourceCoverageRoute.category == "residential_building_plot",
                    SourceCoverageRoute.source_type == "public_html",
                    SourceCoverageRoute.catalog_status == "active",
                )
                .order_by(SourceCoverageRoute.route_key)
                .limit(7)
            )
        )
        if managed_route_state.get("ready") is True
        else []
    )
    managed_selected: list[SourceCoverageRoute] = []
    pending_by_route: dict[str, list[str]] = {}
    examined_by_route: dict[str, set[str]] = {}
    replay_only_by_route: dict[str, set[str]] = {}
    listing_fetch_limit_by_route: dict[str, int] = {}
    discovery_url_by_route: dict[str, str] = {}
    replay_marker = f"policy_replay:{LAND_RECIPIENT_POLICY_VERSION}"
    for route in managed_routes:
        pending = list(
            db.scalars(
                select(GrowthPublicLandListingCursor.listing_url)
                .where(
                    GrowthPublicLandListingCursor.route_key == route.route_key,
                    or_(
                        GrowthPublicLandListingCursor.status == "pending",
                        (
                            GrowthPublicLandListingCursor.status == "retryable"
                        )
                        & (
                            GrowthPublicLandListingCursor.next_retry_at.is_(None)
                            | (GrowthPublicLandListingCursor.next_retry_at <= current)
                        ),
                    ),
                )
                .order_by(
                    case(
                        (GrowthPublicLandListingCursor.last_result == replay_marker, 0),
                        else_=1,
                    ),
                    GrowthPublicLandListingCursor.next_retry_at.asc().nulls_first(),
                    GrowthPublicLandListingCursor.first_seen_at,
                )
            )
        )
        policy_replay_pending = list(
            db.scalars(
                select(GrowthPublicLandListingCursor.listing_url)
                .where(
                    GrowthPublicLandListingCursor.route_key == route.route_key,
                    GrowthPublicLandListingCursor.status == "pending",
                    GrowthPublicLandListingCursor.last_result == replay_marker,
                )
                .order_by(GrowthPublicLandListingCursor.id)
            )
        )
        examined = set(
            db.scalars(
                select(GrowthPublicLandListingCursor.listing_url).where(
                    GrowthPublicLandListingCursor.route_key == route.route_key,
                    or_(
                        GrowthPublicLandListingCursor.status == "examined",
                        (
                            GrowthPublicLandListingCursor.status == "retryable"
                        )
                        & GrowthPublicLandListingCursor.next_retry_at.is_not(None)
                        & (GrowthPublicLandListingCursor.next_retry_at > current),
                    ),
                )
            )
        )
        examined_today = int(
            db.scalar(
                select(func.count())
                .select_from(GrowthPublicLandListingCursor)
                .where(
                    GrowthPublicLandListingCursor.route_key == route.route_key,
                    GrowthPublicLandListingCursor.examined_at >= start_utc,
                )
            )
            or 0
        )
        attempted_once = bool(
            db.scalar(
                select(SourceCoverageAttempt.id)
                .where(
                    SourceCoverageAttempt.route_key == route.route_key,
                    SourceCoverageAttempt.run_id == land_run_id,
                )
                .limit(1)
            )
        )
        if policy_replay_pending:
            # Replay work is isolated for the whole route poll, even while the
            # ordinary daily budget still has room. Normal pending and newly
            # discovered URLs wait for a later ordinary-budget poll.
            pending = policy_replay_pending
            replay_only_by_route[route.route_key] = set(policy_replay_pending)
            listing_fetch_limit_by_route[route.route_key] = (
                LAND_PUBLIC_HTML_LISTING_FETCH_MAXIMUM
            )
        elif examined_today >= LAND_PUBLIC_HTML_LISTING_DAILY_ROUTE_BUDGET:
            # A bounded policy replay is a re-evaluation of already-budgeted URLs,
            # not new discovery. Only explicitly marked replay rows may cross the
            # ordinary same-day discovery ceiling, and the marker is consumed by
            # the normal fetch result below.
            continue
        else:
            listing_fetch_limit_by_route[route.route_key] = min(
                LAND_PUBLIC_HTML_LISTING_FETCH_MAXIMUM,
                LAND_PUBLIC_HTML_LISTING_DAILY_ROUTE_BUDGET - examined_today,
            )
        if policy_replay_pending or pending or not attempted_once:
            discovery_url = route.route_url
        else:
            discovery_url = _managed_land_next_discovery_url(
                db,
                route=route,
                run_id=land_run_id,
            )
            if discovery_url is None:
                continue
        managed_selected.append(route)
        discovery_url_by_route[route.route_key] = discovery_url
        pending_by_route[route.route_key] = pending
        examined_by_route[route.route_key] = examined
    selected_runs = [
        *((route, run_id, False) for route in selected),
        *((route, land_run_id, True) for route in managed_selected),
    ]

    def fetch_timed(route_run: tuple[SourceCoverageRoute, str, bool]):
        route, _route_run_id, _managed = route_run
        started = datetime.now(UTC)
        result = _fetch(
            route,
            managed_land=_managed,
            discovery_url=(
                discovery_url_by_route.get(route.route_key) if _managed else None
            ),
            pending_listing_urls=(pending_by_route.get(route.route_key) if _managed else None),
            examined_listing_urls=(examined_by_route.get(route.route_key) if _managed else None),
            replay_only_listing_urls=(
                replay_only_by_route.get(route.route_key) if _managed else None
            ),
            listing_fetch_limit=(
                listing_fetch_limit_by_route.get(route.route_key) if _managed else None
            ),
        )
        if _managed:
            evidence = result.setdefault("evidence", {})
            if isinstance(evidence, dict):
                evidence.setdefault(
                    "land_discovery_url",
                    discovery_url_by_route.get(route.route_key, route.route_url),
                )
                evidence.setdefault("land_pagination_candidates", [])
        completed = datetime.now(UTC)
        return started, result, completed

    if selected_runs:
        with ThreadPoolExecutor(max_workers=min(8, len(selected_runs))) as executor:
            fetched = list(executor.map(fetch_timed, selected_runs))
    else:
        fetched = []

    outcomes: dict[str, int] = {}
    land_examined = 0
    land_qualified = 0
    land_queued = 0
    discovered_forum_routes = 0
    # Persist and extract evidence on the owning SQLAlchemy thread only.
    for (route, route_run_id, managed_land), (started, result, completed) in zip(
        selected_runs, fetched, strict=True
    ):
        status = str(result["status"])
        attempt = SourceCoverageAttempt(
            attempt_id=f"SCA-{uuid4().hex[:20].upper()}",
            route_key=route.route_key,
            catalog_sha256=route.catalog_sha256,
            run_id=route_run_id,
            status=status,
            http_status=result.get("http_status"),
            response_sha256=result.get("response_sha256"),
            evidence_json=_canonical_json(result.get("evidence") or {}),
            error_type=result.get("error_type"),
            started_at=started,
            completed_at=completed,
        )
        db.add(attempt)
        db.flush()
        if status == "succeeded" and _is_forum_discovery_route(route):
            discovered_forum_routes += _upsert_discovered_forum_routes(
                db,
                catalog_sha256=revision.catalog_sha256,
                parent_route=route,
                links=result.get("analysis_links") or [],
                now=completed,
            )
        cursor_rows: dict[str, GrowthPublicLandListingCursor] = {}
        if managed_land:
            land_examined += len(
                result.get("evidence", {}).get("land_listing_fetches", [])
            )
            for listing_url in result.get("land_listing_candidates") or []:
                listing_hash = hashlib.sha256(listing_url.encode("utf-8")).hexdigest()
                cursor = db.scalar(
                    select(GrowthPublicLandListingCursor).where(
                        GrowthPublicLandListingCursor.route_key == route.route_key,
                        GrowthPublicLandListingCursor.listing_url_sha256 == listing_hash,
                    )
                )
                if cursor is None:
                    cursor = GrowthPublicLandListingCursor(
                        route_key=route.route_key,
                        listing_url=listing_url,
                        listing_url_sha256=listing_hash,
                        status="pending",
                        first_seen_at=completed,
                        updated_at=completed,
                    )
                    db.add(cursor)
                    db.flush()
                cursor_rows[listing_url] = cursor
            for listing_fetch in result.get("evidence", {}).get(
                "land_listing_fetches", []
            ):
                listing_url = str(listing_fetch.get("url") or "")
                cursor = cursor_rows.get(listing_url) or db.scalar(
                    select(GrowthPublicLandListingCursor).where(
                        GrowthPublicLandListingCursor.route_key == route.route_key,
                        GrowthPublicLandListingCursor.listing_url_sha256
                        == hashlib.sha256(listing_url.encode("utf-8")).hexdigest(),
                    )
                )
                if cursor is not None:
                    fetch_status = str(listing_fetch.get("status") or "unknown")
                    error_type = str(listing_fetch.get("error_type") or fetch_status)
                    retryable = fetch_status in {"failed", "blocked"} and error_type in {
                        "blocked_page",
                        "fetch_timeout",
                        "listing_unavailable",
                        "pinned_fetch_failed",
                        "portal_robots_unavailable",
                    }
                    cursor.status = "retryable" if retryable else "examined"
                    cursor.last_result = error_type
                    cursor.attempt_count += 1
                    cursor.examined_at = completed
                    cursor.next_retry_at = (
                        completed + timedelta(days=1) if retryable else None
                    )
                    cursor.updated_at = completed
        if status == "succeeded" and getattr(cfg, "canonical_processing_enabled", False):
            if _is_forum_discovery_route(route):
                # A search page can discover a source, but is never the source
                # of a buyer's post. Its persisted direct route is fetched and
                # processed on the next batch with the actual source binding.
                attempt.analysis_status = "discovered"
                attempt.analysis_json = _canonical_json({"status": "source_fetch_scheduled"})
                attempt.analysis_at = datetime.now(UTC)
            elif managed_land:
                land_result = process_public_land_listings(
                    db,
                    route=route,
                    attempt=attempt,
                    listing_pages=result.get("land_listing_pages") or [],
                )
                attempt.analysis_status = str(land_result["status"])
                attempt.analysis_json = _canonical_json(land_result)
                attempt.analysis_at = datetime.now(UTC)
                land_qualified += int(land_result.get("qualified") or 0)
                land_queued += int(land_result.get("queued") or 0)
            else:
                from .processing import process_source_attempt

                process_source_attempt(
                    db,
                    route=route,
                    attempt=attempt,
                    text=result["analysis_text"],
                    link_candidates=result.get("analysis_links") or [],
                )
        elif status != "succeeded":
            attempt.analysis_status = "skipped"
        route.attempt_count += 1
        route.last_attempt_at = completed
        route.last_result = status
        if route.route_key in radar_keys and route.route_mode == "direct":
            route.next_due_at = completed + timedelta(minutes=30 if status == "succeeded" else 60)
        else:
            route.next_due_at = (
                completed + timedelta(days=1)
                if not managed_land or result.get("land_listing_exhausted") is True
                else completed
            )
        route.updated_at = completed
        if status == "succeeded":
            route.success_count += 1
            route.last_success_at = completed
        outcomes[status] = outcomes.get(status, 0) + 1
    if discovered_forum_routes:
        active_route_target = int(
            db.scalar(
                select(func.count())
                .select_from(SourceCoverageRoute)
                .where(
                    SourceCoverageRoute.enabled.is_(True),
                    SourceCoverageRoute.catalog_sha256 == revision.catalog_sha256,
                )
            )
            or 0
        )
    db.commit()
    newly_attempted = sum(route.route_key not in already_attempted for route in selected)
    return {
        "status": (
            "attempted"
            if selected_runs
            else "on_pace"
            if attempted_today >= active_route_target
            else "no_due_routes"
        ),
        "attempted": len(selected_runs),
        "attempted_today": attempted_today + newly_attempted,
        "radar_refreshed": len(selected) - newly_attempted,
        "unique_leads_today": unique_leads_today,
        "daily_lead_target_met": unique_leads_today >= DAILY_UNIQUE_LEAD_MINIMUM,
        "active_route_target": active_route_target,
        "coverage_complete": attempted_today + newly_attempted >= active_route_target,
        "remaining_routes": max(0, active_route_target - attempted_today - newly_attempted),
        "run_id": run_id,
        "outcomes": outcomes,
        "discovered_forum_routes": discovered_forum_routes,
        "land_public_lane": {
            "run_id": land_run_id,
            "route_readiness": managed_route_state,
            "started_at": (
                min(item[0] for item in fetched).isoformat() if managed_selected else None
            ),
            "completed_at": (
                max(item[2] for item in fetched).isoformat() if managed_selected else None
            ),
            "attempted": len(managed_selected),
            "blocked": sum(
                1
                for (_route, _run, managed), (_started, item, _completed) in zip(
                    selected_runs, fetched, strict=True
                )
                if managed and item.get("status") in {"blocked", "rejected"}
            ),
            "failed": sum(
                1
                for (_route, _run, managed), (_started, item, _completed) in zip(
                    selected_runs, fetched, strict=True
                )
                if managed and item.get("status") == "failed"
            ),
            "examined": land_examined,
            "eligible": land_qualified,
            "qualified": land_qualified,
            "queued": land_queued,
            "cursor": {
                "pending": int(
                    db.scalar(
                        select(func.count())
                        .select_from(GrowthPublicLandListingCursor)
                        .where(
                            GrowthPublicLandListingCursor.status.in_(
                                ("pending", "retryable")
                            )
                        )
                    )
                    or 0
                ),
                "retryable": int(
                    db.scalar(
                        select(func.count())
                        .select_from(GrowthPublicLandListingCursor)
                        .where(GrowthPublicLandListingCursor.status == "retryable")
                    )
                    or 0
                ),
                "examined": int(
                    db.scalar(
                        select(func.count())
                        .select_from(GrowthPublicLandListingCursor)
                        .where(GrowthPublicLandListingCursor.status == "examined")
                    )
                    or 0
                ),
                "exhausted": int(
                    db.scalar(
                        select(func.count())
                        .select_from(GrowthPublicLandListingCursor)
                        .where(
                            GrowthPublicLandListingCursor.status.in_(
                                ("pending", "retryable")
                            )
                        )
                    )
                    or 0
                )
                == 0,
            },
        },
    }
