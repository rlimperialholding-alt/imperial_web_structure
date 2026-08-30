from __future__ import annotations

import hashlib
import html
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from .registry import GrowthRegistry, GrowthRegistryError, _registrable_domain

OFFICIAL_SOURCE_TIMEOUT_SECONDS = 20.0
OFFICIAL_SOURCE_MAX_RESPONSE_BYTES = 2_000_000
OFFICIAL_SOURCE_MAX_REDIRECTS = 3


class OfficialSourceEvidenceError(GrowthRegistryError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def is_public_unicast_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return bool(
        address.is_global
        and not address.is_multicast
        and not address.is_unspecified
        and not address.is_reserved
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_private
    )


@dataclass(frozen=True)
class OfficialSourcePageEvidence:
    requested_url: str
    final_url: str
    http_status: int
    content_type: str
    content_bytes: int
    content_sha256: str
    source_ip: str


@dataclass(frozen=True)
class OfficialSourceLiveEvidence:
    source_id: str
    binding_sha256: str
    observed_at: datetime
    pages: tuple[OfficialSourcePageEvidence, ...]
    matched_email: str
    matched_organization_marker: str
    matched_recipient_marker: str

    def audit_payload(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "binding_sha256": self.binding_sha256,
            "observed_at": self.observed_at.isoformat(),
            "pages": [asdict(page) for page in self.pages],
            "matched_email": self.matched_email,
            "matched_organization_marker": self.matched_organization_marker,
            "matched_recipient_marker": self.matched_recipient_marker,
        }


class _VisibleText(HTMLParser):
    _ALWAYS_HIDDEN_TAGS = {"script", "style", "noscript", "svg", "template"}
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

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.mailto_addresses: set[str] = set()
        self.stack: list[tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        normalized_attrs = {
            key.casefold(): str(value or "") for key, value in attrs
        }
        style = re.sub(r"\s+", "", normalized_attrs.get("style", "").casefold())
        hidden = bool(
            (self.stack and self.stack[-1][1])
            or normalized_tag in self._ALWAYS_HIDDEN_TAGS
            or "hidden" in normalized_attrs
            or normalized_attrs.get("aria-hidden", "").strip().casefold() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
            or "content-visibility:hidden" in style
        )
        if normalized_tag == "a" and not hidden:
            href = next(
                (
                    str(value)
                    for key, value in attrs
                    if key.casefold() == "href" and value is not None
                ),
                "",
            )
            if href.casefold().startswith("mailto:"):
                address = unquote(href[7:].split("?", 1)[0]).strip().casefold()
                if address:
                    self.mailto_addresses.add(address)
        if normalized_tag not in self._VOID_TAGS:
            self.stack.append((normalized_tag, hidden))

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == normalized_tag:
                del self.stack[index:]
                break

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        # HTML5 ignores the self-closing flag on non-void HTML elements. Keep
        # such an element on the stack so `<div hidden/>...` cannot make its
        # following marker text appear visible to this parser.
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if not self.stack or not self.stack[-1][1]:
            self.parts.append(data)


def _normalized_marker(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", html.unescape(str(value))).casefold(),
    ).strip()


def normalize_official_source_marker(value: str) -> str:
    return _normalized_marker(value)


def _parsed_visible_html(value: str) -> tuple[str, set[str]]:
    parser = _VisibleText()
    try:
        parser.feed(value)
        parser.close()
    except (ValueError, RecursionError) as exc:
        raise OfficialSourceEvidenceError("official_source_html_unreadable") from exc
    return _normalized_marker(" ".join(parser.parts)), parser.mailto_addresses


def _visible_text(value: str) -> str:
    return _parsed_visible_html(value)[0]


_VISIBLE_EMAIL_RE = re.compile(
    r"(?<![a-z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?![a-z0-9-])",
    re.IGNORECASE,
)


def _visible_email_addresses(value: str) -> set[str]:
    text, mailto_addresses = _parsed_visible_html(value)
    return {
        *(address.casefold() for address in _VISIBLE_EMAIL_RE.findall(text)),
        *(address.casefold() for address in mailto_addresses),
    }


def _contains_marker(text: str, marker: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", text))


def _resolve_public_addresses(
    host: str,
    port: int,
    *,
    deadline_monotonic: float | None = None,
) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    if not host or host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise OfficialSourceEvidenceError("official_source_private_address")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        outcome: dict[str, Any] = {}

        def resolve() -> None:
            try:
                outcome["records"] = socket.getaddrinfo(
                    host,
                    port,
                    type=socket.SOCK_STREAM,
                )
            except (OSError, ValueError) as exc:
                outcome["error"] = exc

        resolver = threading.Thread(
            target=resolve,
            name="official-source-dns",
            daemon=True,
        )
        resolver.start()
        deadline = deadline_monotonic or (
            time.monotonic() + OFFICIAL_SOURCE_TIMEOUT_SECONDS
        )
        resolver.join(timeout=max(0.0, deadline - time.monotonic()))
        if resolver.is_alive():
            raise OfficialSourceEvidenceError("official_source_fetch_timeout") from None
        if "error" in outcome:
            raise OfficialSourceEvidenceError("official_source_dns_failed") from outcome[
                "error"
            ]
        try:
            addresses = {
                ipaddress.ip_address(item[4][0]) for item in outcome.get("records", [])
            }
        except (TypeError, ValueError) as exc:
            raise OfficialSourceEvidenceError("official_source_dns_failed") from exc
    if not addresses or any(
        not is_public_unicast_address(address) for address in addresses
    ):
        raise OfficialSourceEvidenceError("official_source_private_address")
    return addresses


def _connect_pinned(
    host: str,
    port: int,
    source_ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    deadline_monotonic: float,
) -> http.client.HTTPSConnection:
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise OfficialSourceEvidenceError("official_source_fetch_timeout")
    raw_socket = socket.create_connection((str(source_ip), port), timeout=remaining)
    context = ssl.create_default_context()
    try:
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise OfficialSourceEvidenceError("official_source_fetch_timeout")
        raw_socket.settimeout(remaining)
        tls_socket = context.wrap_socket(raw_socket, server_hostname=host)
    except Exception:
        raw_socket.close()
        raise
    connection = http.client.HTTPSConnection(
        host,
        port=port,
        timeout=max(0.001, deadline_monotonic - time.monotonic()),
        context=context,
    )
    connection.sock = tls_socket
    return connection


def _allowed_url(value: str, *, allowed_urls: set[str], root_domain: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise OfficialSourceEvidenceError("official_source_url_invalid") from exc
    try:
        port = parsed.port
    except ValueError as exc:
        raise OfficialSourceEvidenceError("official_source_url_invalid") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise OfficialSourceEvidenceError("official_source_url_invalid")
    try:
        if _registrable_domain(parsed.hostname) != root_domain:
            raise OfficialSourceEvidenceError("official_source_url_invalid")
    except GrowthRegistryError as exc:
        raise OfficialSourceEvidenceError("official_source_url_invalid") from exc
    canonical = urlunsplit(
        (
            "https",
            parsed.netloc.casefold(),
            parsed.path or "/",
            parsed.query,
            "",
        )
    )
    if canonical not in allowed_urls:
        raise OfficialSourceEvidenceError("official_source_redirect_not_allowlisted")
    return canonical


def _fetch_html(
    requested_url: str,
    *,
    allowed_urls: set[str],
    root_domain: str,
    max_bytes: int,
    max_redirects: int,
    expected_final_url: str,
    deadline_monotonic: float,
) -> tuple[OfficialSourcePageEvidence, str]:
    current_url = _allowed_url(
        requested_url,
        allowed_urls=allowed_urls,
        root_domain=root_domain,
    )
    for redirect_no in range(max_redirects + 1):
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise OfficialSourceEvidenceError("official_source_fetch_timeout")
        parsed = urlsplit(current_url)
        host = str(parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port or 443
        addresses = _resolve_public_addresses(
            host,
            port,
            deadline_monotonic=deadline_monotonic,
        )
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise OfficialSourceEvidenceError("official_source_fetch_timeout")
        source_ip = sorted(addresses, key=lambda item: (item.version, str(item)))[0]
        connection: http.client.HTTPSConnection | None = None
        try:
            connection = _connect_pinned(
                host,
                port,
                source_ip,
                deadline_monotonic,
            )
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise OfficialSourceEvidenceError("official_source_fetch_timeout")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            connection.request(
                "GET",
                path,
                headers={
                    "Host": host if parsed.port is None else f"{host}:{port}",
                    "User-Agent": "Imperial-Official-Source-Verifier/1.0",
                    "Accept": "text/html",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise OfficialSourceEvidenceError("official_source_fetch_timeout")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            response = connection.getresponse()
            headers = {key.casefold(): value.strip() for key, value in response.getheaders()}
            if response.status in {301, 302, 303, 307, 308}:
                location = headers.get("location")
                if not location or redirect_no >= max_redirects:
                    raise OfficialSourceEvidenceError("official_source_redirect_forbidden")
                current_url = _allowed_url(
                    urljoin(current_url, location),
                    allowed_urls=allowed_urls,
                    root_domain=root_domain,
                )
                continue
            if response.status != 200:
                raise OfficialSourceEvidenceError("official_source_http_not_200")
            if current_url != expected_final_url:
                raise OfficialSourceEvidenceError("official_source_final_url_mismatch")
            if headers.get("content-encoding", "identity").casefold() not in {"", "identity"}:
                raise OfficialSourceEvidenceError("official_source_compression_forbidden")
            content_type = headers.get("content-type", "")
            if content_type.split(";", 1)[0].strip().casefold() != "text/html":
                raise OfficialSourceEvidenceError("official_source_mime_not_html")
            declared_size = headers.get("content-length")
            if declared_size:
                try:
                    parsed_size = int(declared_size)
                except ValueError as exc:
                    raise OfficialSourceEvidenceError(
                        "official_source_content_length_invalid"
                    ) from exc
                if parsed_size < 0 or parsed_size > max_bytes:
                    raise OfficialSourceEvidenceError("official_source_response_too_large")
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise OfficialSourceEvidenceError("official_source_fetch_timeout")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunks: list[bytes] = []
            received = 0
            while received <= max_bytes:
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    raise OfficialSourceEvidenceError("official_source_fetch_timeout")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65_536, max_bytes + 1 - received))
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
            payload = b"".join(chunks)
            if not payload:
                raise OfficialSourceEvidenceError("official_source_response_empty")
            if len(payload) > max_bytes:
                raise OfficialSourceEvidenceError("official_source_response_too_large")
            decoded = payload.decode("utf-8", errors="replace")
            if deadline_monotonic - time.monotonic() <= 0:
                raise OfficialSourceEvidenceError("official_source_fetch_timeout")
            return (
                OfficialSourcePageEvidence(
                    requested_url=requested_url,
                    final_url=current_url,
                    http_status=response.status,
                    content_type=content_type[:240],
                    content_bytes=len(payload),
                    content_sha256=hashlib.sha256(payload).hexdigest(),
                    source_ip=str(source_ip),
                ),
                decoded,
            )
        except OfficialSourceEvidenceError:
            raise
        except TimeoutError as exc:
            raise OfficialSourceEvidenceError("official_source_fetch_timeout") from exc
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise OfficialSourceEvidenceError("official_source_fetch_failed") from exc
        finally:
            if connection is not None:
                connection.close()
    raise OfficialSourceEvidenceError("official_source_redirect_forbidden")


def fetch_official_source_evidence(
    source_id: str,
    source: dict[str, Any],
    *,
    expected_recipient_name: str,
    expected_organization_names: tuple[str, ...] | list[str],
    timeout_seconds: float = OFFICIAL_SOURCE_TIMEOUT_SECONDS,
    max_bytes: int = OFFICIAL_SOURCE_MAX_RESPONSE_BYTES,
    max_redirects: int = OFFICIAL_SOURCE_MAX_REDIRECTS,
    now: datetime | None = None,
) -> OfficialSourceLiveEvidence:
    if timeout_seconds <= 0 or max_bytes <= 0 or max_redirects < 0:
        raise OfficialSourceEvidenceError("official_source_fetch_limits_invalid")
    if (
        source.get("enabled") is not True
        or source.get("kind") != GrowthRegistry.OFFICIAL_COMPANY_SOURCE_KIND
        or source.get("fetch_mode") != GrowthRegistry.OFFICIAL_COMPANY_FETCH_MODE
    ):
        raise OfficialSourceEvidenceError("official_source_not_enabled")
    allowed_values = source.get("allowed_evidence_urls")
    if not isinstance(allowed_values, list) or not allowed_values:
        raise OfficialSourceEvidenceError("official_source_allowlist_missing")
    allowed_urls = {str(value) for value in allowed_values}
    try:
        root_domain = _registrable_domain(
            urlsplit(str(source.get("url") or "")).hostname or ""
        )
    except (GrowthRegistryError, ValueError) as exc:
        raise OfficialSourceEvidenceError("official_source_url_invalid") from exc
    bound_urls = list(
        dict.fromkeys(
            [
                str(source.get("context_evidence_url") or ""),
                str(source.get("public_contact_url") or ""),
            ]
        )
    )
    if any(not value for value in bound_urls):
        raise OfficialSourceEvidenceError("official_source_bound_url_missing")
    policy_evidence = source.get("policy_evidence")
    if not isinstance(policy_evidence, dict):
        raise OfficialSourceEvidenceError("official_source_policy_evidence_missing")
    policy_requested_url = str(policy_evidence.get("evidence_url") or "")
    policy_final_url = str(policy_evidence.get("final_url") or "")
    if not policy_requested_url or not policy_final_url:
        raise OfficialSourceEvidenceError("official_source_policy_evidence_missing")
    observation_started_at = now or datetime.now(UTC)
    if observation_started_at.tzinfo is None:
        observation_started_at = observation_started_at.replace(tzinfo=UTC)
    observation_started_at = observation_started_at.astimezone(UTC)
    deadline_monotonic = time.monotonic() + timeout_seconds
    pages: list[OfficialSourcePageEvidence] = []
    bodies: dict[str, str] = {}
    for url in bound_urls:
        expected_final_url = policy_final_url if url == policy_requested_url else url
        expected_final_url = _allowed_url(
            expected_final_url,
            allowed_urls=allowed_urls,
            root_domain=root_domain,
        )
        page, body = _fetch_html(
            url,
            allowed_urls=allowed_urls,
            root_domain=root_domain,
            max_bytes=max_bytes,
            max_redirects=max_redirects,
            expected_final_url=expected_final_url,
            deadline_monotonic=deadline_monotonic,
        )
        pages.append(page)
        bodies[url] = body
        if deadline_monotonic - time.monotonic() <= 0:
            raise OfficialSourceEvidenceError("official_source_fetch_timeout")

    binding = source.get("recipient_binding")
    if not isinstance(binding, dict):
        raise OfficialSourceEvidenceError("official_source_recipient_binding_missing")
    email = _normalized_marker(str(binding.get("recipient_email") or ""))
    contact_emails = _visible_email_addresses(
        bodies[str(source["public_contact_url"])]
    )
    if deadline_monotonic - time.monotonic() <= 0:
        raise OfficialSourceEvidenceError("official_source_fetch_timeout")
    if not email or email not in contact_emails:
        raise OfficialSourceEvidenceError("official_source_email_marker_missing")
    context_text = _visible_text(bodies[str(source["context_evidence_url"])])
    if deadline_monotonic - time.monotonic() <= 0:
        raise OfficialSourceEvidenceError("official_source_fetch_timeout")
    allowed_organization_markers = {
        _normalized_marker(str(value))
        for value in binding.get("organization_names") or []
        if _normalized_marker(str(value))
    }
    organization_markers = {
        _normalized_marker(str(value))
        for value in expected_organization_names
        if _normalized_marker(str(value))
    }
    recipient_marker = _normalized_marker(expected_recipient_name)
    if (
        not organization_markers
        or not organization_markers.issubset(allowed_organization_markers)
    ):
        raise OfficialSourceEvidenceError("official_source_organization_binding_mismatch")
    matched_organizations = sorted(
        (
            marker
            for marker in organization_markers
            if _contains_marker(context_text, marker)
        ),
        key=lambda marker: (-len(marker), marker),
    )
    if not matched_organizations:
        raise OfficialSourceEvidenceError("official_source_organization_marker_missing")
    if not recipient_marker or not _contains_marker(context_text, recipient_marker):
        raise OfficialSourceEvidenceError("official_source_recipient_marker_missing")
    if deadline_monotonic - time.monotonic() <= 0:
        raise OfficialSourceEvidenceError("official_source_fetch_timeout")

    return OfficialSourceLiveEvidence(
        source_id=source_id,
        binding_sha256=str(source["binding_sha256"]),
        observed_at=observation_started_at,
        pages=tuple(pages),
        matched_email=email,
        matched_organization_marker=matched_organizations[0],
        matched_recipient_marker=recipient_marker,
    )
