from __future__ import annotations

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
from datetime import UTC, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..land_acquisition.registry import (
    LandRegistryError,
    PortalRegistry,
    is_named_portal_host,
    same_named_portal_binding,
)
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
LAND_PUBLIC_HTML_LISTING_FETCH_MAXIMUM = 3
LAND_PUBLIC_HTML_LISTING_DAILY_ROUTE_BUDGET = 30
LAND_PUBLIC_HTML_ROUTE_PREFIX = "LAND-PUBLIC-HTML:"
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
            timeout=max(
                0.001, deadline_monotonic - monotonic_time.monotonic()
            ),
            context=context,
        )
        connection.sock = tls_socket
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        connection.request(
            "GET",
            path,
            headers={
                "Host": host if parsed.port is None else f"{host}:{port}",
                "User-Agent": PORTAL_PUBLIC_HTML_USER_AGENT,
                "Accept": "text/html,text/plain;q=0.9",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        headers = {
            key.casefold(): value.strip() for key, value in response.getheaders()
        }
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
            self.parts.append(data)
            if self._href:
                self._anchor_parts.append(data)


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


def _visible_text(body_text: str, limit: int) -> str:
    parser = _VisibleText()
    try:
        parser.feed(body_text)
        value = " ".join(parser.parts)
    except Exception:
        value = re.sub(r"<[^>]+>", " ", body_text)
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _page_evidence(
    body_text: str, *, base_url: str, limit: int
) -> tuple[str, list[dict[str, str]]]:
    parser = _VisibleText(base_url)
    try:
        parser.feed(body_text)
        value = " ".join(parser.parts)
    except Exception:
        return _visible_text(body_text, limit), []
    text = re.sub(r"\s+", " ", value).strip()[:limit]
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


def _upsert_routes(db: Session, rows: list[dict[str, Any]]) -> None:
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
                if key not in {"created_at"}:
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
            if column.name not in immutable_runtime
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
            SourceCoverageRoute.route_key.not_like(
                f"{LAND_PUBLIC_HTML_ROUTE_PREFIX}%"
            ),
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
    pending_listing_urls: list[str] | None = None,
    examined_listing_urls: set[str] | None = None,
) -> dict[str, Any]:
    cfg = settings()
    parsed = urlparse(route.route_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return {"status": "rejected", "error_type": "invalid_route_url"}
    named_portal = is_named_portal_host(parsed.hostname)
    if named_portal:
        portal_error = _public_html_portal_error(route.route_url)
        if portal_error:
            return {
                "status": "failed" if portal_error == "portal_registry_unavailable" else "rejected",
                "error_type": portal_error,
            }
    if not named_portal:
        try:
            assert_public_https_url(route.route_url)
        except UnsafeRouteError as exc:
            return {"status": "rejected", "error_type": str(exc)}
    if contains_no_monitoring_entity(route.source_record_json):
        return {"status": "rejected", "error_type": "no_monitoring_hard_gate"}
    content = bytearray()
    source_ip: str | None = None
    try:
        if named_portal:
            deadline = (
                monotonic_time.monotonic() + cfg.canonical_route_timeout_seconds
            )
            robots_error = _fresh_pinned_robots_error(
                route.route_url,
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
                route.route_url,
                max_response_bytes=cfg.canonical_route_max_response_bytes,
                deadline_monotonic=deadline,
            )
            status_code = int(response_data["status_code"])
            content_type = str(
                response_data["headers"].get("content-type", "")
            )[:240]
            content.extend(bytes(response_data["body"]))
            source_ip = str(response_data["source_ip"])
        else:
            with httpx.Client(
                timeout=cfg.canonical_route_timeout_seconds,
                follow_redirects=False,
                headers={"User-Agent": "Imperial-Source-Coverage/1.0"},
            ) as client:
                with client.stream("GET", route.route_url) as response:
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
    except httpx.HTTPError as exc:
        return {"status": "failed", "error_type": type(exc).__name__}
    body = bytes(content)
    body_text = body.decode("utf-8", errors="ignore")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", body_text, re.I | re.S)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip()[:500] if title_match else None
    analysis_text, analysis_links = _page_evidence(
        body_text,
        base_url=route.route_url,
        limit=getattr(cfg, "canonical_analysis_text_chars", 6000),
    )
    blocked = _looks_like_blocked_response(
        status_code=status_code,
        route_url=route.route_url,
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
    if managed_land and named_portal and result_status == "succeeded":
        route_host = (parsed.hostname or "").casefold()
        candidate_urls: list[str] = list(pending_listing_urls or [])
        if is_specific_listing_permalink(route.route_url):
            candidate_urls.append(route.route_url)
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
        candidate_urls = [
            url for url in all_candidate_urls if url not in (examined_listing_urls or set())
        ][
            :LAND_PUBLIC_HTML_LISTING_FETCH_MAXIMUM
        ]
        for listing_url in candidate_urls:
            if listing_url == route.route_url:
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
            "discovery_mode": "public_html" if named_portal else "generic_html",
            "robots_txt": "allowed" if named_portal else "not_applicable",
            "land_listing_fetches": land_listing_fetches,
            "land_listing_candidate_count": (
                len(all_candidate_urls) if managed_land and named_portal else 0
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
            <= LAND_PUBLIC_HTML_LISTING_FETCH_MAXIMUM
            if managed_land and named_portal
            else True
        ),
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
            select(func.count())
            .select_from(SourceCoverageAttempt)
            .where(
                SourceCoverageAttempt.started_at >= start_utc,
                SourceCoverageAttempt.catalog_sha256 == revision.catalog_sha256,
                SourceCoverageAttempt.run_id == run_id,
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
    allowance = max(0, min(
        cfg.canonical_route_batch_size,
        active_route_target - attempted_today,
    ))
    attempted_route_keys = select(SourceCoverageAttempt.route_key).where(
        SourceCoverageAttempt.started_at >= start_utc,
        SourceCoverageAttempt.catalog_sha256 == revision.catalog_sha256,
        SourceCoverageAttempt.run_id == run_id,
    )
    candidates = db.scalars(
        select(SourceCoverageRoute)
        .where(
            SourceCoverageRoute.enabled.is_(True),
            SourceCoverageRoute.catalog_sha256 == revision.catalog_sha256,
            SourceCoverageRoute.route_key.not_in(attempted_route_keys),
        )
        .order_by(
            case((SourceCoverageRoute.route_mode == "direct", 0), else_=1),
            SourceCoverageRoute.last_attempt_at.asc().nulls_first(),
            SourceCoverageRoute.priority.asc(),
            SourceCoverageRoute.id.asc(),
        )
        .limit(max(allowance * 5, allowance) if allowance else 0)
    ).all() if allowance else []
    selected: list[SourceCoverageRoute] = []
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
    managed_routes = list(
        db.scalars(
            select(SourceCoverageRoute)
            .where(
                SourceCoverageRoute.enabled.is_(True),
                SourceCoverageRoute.route_key.like(
                    f"{LAND_PUBLIC_HTML_ROUTE_PREFIX}%"
                ),
                SourceCoverageRoute.category == "residential_building_plot",
                SourceCoverageRoute.source_type == "public_html",
                SourceCoverageRoute.catalog_status == "active",
            )
            .order_by(SourceCoverageRoute.route_key)
            .limit(7)
        )
    )
    managed_selected: list[SourceCoverageRoute] = []
    pending_by_route: dict[str, list[str]] = {}
    examined_by_route: dict[str, set[str]] = {}
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
                    GrowthPublicLandListingCursor.next_retry_at.asc().nulls_first(),
                    GrowthPublicLandListingCursor.first_seen_at,
                )
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
        if examined_today >= LAND_PUBLIC_HTML_LISTING_DAILY_ROUTE_BUDGET:
            continue
        if not attempted_once or pending:
            managed_selected.append(route)
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
            pending_listing_urls=(pending_by_route.get(route.route_key) if _managed else None),
            examined_listing_urls=(examined_by_route.get(route.route_key) if _managed else None),
        )
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
            if managed_land:
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
    db.commit()
    return {
        "status": (
            "attempted"
            if selected_runs
            else "on_pace"
            if attempted_today >= active_route_target
            else "no_due_routes"
        ),
        "attempted": len(selected_runs),
        "attempted_today": attempted_today + len(selected),
        "unique_leads_today": unique_leads_today,
        "daily_lead_target_met": unique_leads_today >= DAILY_UNIQUE_LEAD_MINIMUM,
        "active_route_target": active_route_target,
        "coverage_complete": attempted_today + len(selected) >= active_route_target,
        "remaining_routes": max(0, active_route_target - attempted_today - len(selected)),
        "run_id": run_id,
        "outcomes": outcomes,
        "land_public_lane": {
            "run_id": land_run_id,
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
