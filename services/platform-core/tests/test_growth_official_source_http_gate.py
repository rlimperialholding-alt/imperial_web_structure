from __future__ import annotations

import hashlib
import ipaddress
import socket
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

import pytest

from app.growth_ops import official_source
from app.growth_ops.official_source import (
    OfficialSourceEvidenceError,
    OfficialSourcePageEvidence,
)

SOURCE_ID = "DYNAMIC_HU_EXAMPLE_HU"
ROOT_URL = "https://example.hu/"
CONTACT_URL = "https://example.hu/contact"
PUBLIC_IP = ipaddress.ip_address("93.184.216.34")


def _source(**changes: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        "enabled": True,
        "motor": "construction",
        "bucket": "architect_office",
        "kind": "official_company_html",
        "fetch_mode": "ingest_only",
        "url": ROOT_URL,
        "allowed_evidence_urls": [ROOT_URL, CONTACT_URL],
        "context_evidence_url": ROOT_URL,
        "public_contact_url": CONTACT_URL,
        "binding_sha256": "b" * 64,
        "recipient_binding": {
            "recipient_type": "architect_office",
            "recipient_email": "office@example.hu",
            "recipient_email_type": "role",
            "contact_basis": "public_business_contact",
            "primary_language": "hu",
            "organization_names": ["Example Architects"],
            "recipient_names": ["Selected Studio", "Registry Alias"],
        },
        "policy_evidence": {
            "evidence_url": ROOT_URL,
            "final_url": ROOT_URL,
            "http_status": 200,
            "content_type": "text/html",
            "content_sha256": "a" * 64,
        },
    }
    source.update(changes)
    return source


def _page(requested_url: str, body: str, final_url: str | None = None):
    payload = body.encode()
    return (
        OfficialSourcePageEvidence(
            requested_url=requested_url,
            final_url=final_url or requested_url,
            http_status=200,
            content_type="text/html; charset=utf-8",
            content_bytes=len(payload),
            content_sha256=hashlib.sha256(payload).hexdigest(),
            source_ip=str(PUBLIC_IP),
        ),
        body,
    )


def _stub_bound_pages(monkeypatch, *, context_html: str, contact_html: str):
    bodies = {ROOT_URL: context_html, CONTACT_URL: contact_html}

    def fetch(url: str, **kwargs: Any):
        return _page(url, bodies[url], kwargs["expected_final_url"])

    monkeypatch.setattr(official_source, "_fetch_html", fetch)


@pytest.mark.parametrize(
    "hidden_contact",
    [
        "<script>office@example.hu</script>",
        "<style>.x{content:'office@example.hu'}</style>",
        "<template>office@example.hu</template>",
        "<div hidden>office@example.hu</div>",
        "<div aria-hidden='true'>office@example.hu</div>",
        "<div style='display: none'>office@example.hu</div>",
        "<div style='visibility:hidden'>office@example.hu</div>",
        "<div style='content-visibility: hidden'>office@example.hu</div>",
        "<div hidden><span>office@example.hu</span></div>",
        "<div hidden><a href='mailto:office@example.hu'>Email</a></div>",
        "<div hidden/>office@example.hu",
        "<div hidden/><a href='mailto:office@example.hu'>Email</a>",
    ],
)
def test_hidden_template_ancestor_and_hidden_mailto_do_not_prove_email(
    monkeypatch,
    hidden_contact,
):
    _stub_bound_pages(
        monkeypatch,
        context_html="<main>Example Architects — Selected Studio</main>",
        contact_html=hidden_contact,
    )

    with pytest.raises(
        OfficialSourceEvidenceError,
        match="official_source_email_marker_missing",
    ):
        official_source.fetch_official_source_evidence(
            SOURCE_ID,
            _source(),
            expected_recipient_name="Selected Studio",
            expected_organization_names=["Example Architects"],
        )


def test_visible_mailto_is_accepted_as_exact_public_contact(monkeypatch):
    _stub_bound_pages(
        monkeypatch,
        context_html="<main>Example Architects — Selected Studio</main>",
        contact_html="<a href='mailto:office%40example.hu?subject=Hello'>Email</a>",
    )

    evidence = official_source.fetch_official_source_evidence(
        SOURCE_ID,
        _source(),
        expected_recipient_name="Selected Studio",
        expected_organization_names=["Example Architects"],
    )

    assert evidence.source_id == SOURCE_ID
    assert evidence.binding_sha256 == "b" * 64
    assert [page.requested_url for page in evidence.pages] == [ROOT_URL, CONTACT_URL]


def test_registry_alias_does_not_replace_exact_selected_render_recipient(monkeypatch):
    _stub_bound_pages(
        monkeypatch,
        context_html="<main>Example Architects — Registry Alias</main>",
        contact_html="<p>office@example.hu</p>",
    )

    with pytest.raises(
        OfficialSourceEvidenceError,
        match="official_source_recipient_marker_missing",
    ):
        official_source.fetch_official_source_evidence(
            SOURCE_ID,
            _source(),
            expected_recipient_name="Selected Studio",
            expected_organization_names=["Example Architects"],
        )


@pytest.mark.parametrize(
    ("context_html", "expected_error"),
    [
        (
            "<div hidden/>Example Architects</div><p>Selected Studio</p>",
            "official_source_organization_marker_missing",
        ),
        (
            "<div hidden/>Selected Studio</div><p>Example Architects</p>",
            "official_source_recipient_marker_missing",
        ),
        (
            "<div hidden/>Example Architects — Selected Studio",
            "official_source_organization_marker_missing",
        ),
    ],
)
def test_html5_nonvoid_startend_hidden_context_markers_do_not_prove_identity(
    monkeypatch,
    context_html,
    expected_error,
):
    _stub_bound_pages(
        monkeypatch,
        context_html=context_html,
        contact_html="<p>office@example.hu</p>",
    )

    with pytest.raises(OfficialSourceEvidenceError, match=expected_error):
        official_source.fetch_official_source_evidence(
            SOURCE_ID,
            _source(),
            expected_recipient_name="Selected Studio",
            expected_organization_names=["Example Architects"],
        )


@pytest.mark.parametrize(
    ("context_html", "expected_error"),
    [
        ("<p>Selected Studio</p>", "official_source_organization_marker_missing"),
        (
            "<p>Example Architects and Selected Studios</p>",
            "official_source_recipient_marker_missing",
        ),
        (
            "<p>Example Architectural and Selected Studio</p>",
            "official_source_organization_marker_missing",
        ),
    ],
)
def test_identity_markers_are_exact_visible_boundaries(
    monkeypatch,
    context_html,
    expected_error,
):
    _stub_bound_pages(
        monkeypatch,
        context_html=context_html,
        contact_html="<p>office@example.hu</p>",
    )

    with pytest.raises(OfficialSourceEvidenceError, match=expected_error):
        official_source.fetch_official_source_evidence(
            SOURCE_ID,
            _source(),
            expected_recipient_name="Selected Studio",
            expected_organization_names=["Example Architects"],
        )


def test_content_hash_drift_passes_when_current_identity_markers_still_match(monkeypatch):
    current_context = "<main>Example Architects — Selected Studio — new content</main>"
    _stub_bound_pages(
        monkeypatch,
        context_html=current_context,
        contact_html="<p>office@example.hu</p>",
    )

    evidence = official_source.fetch_official_source_evidence(
        SOURCE_ID,
        _source(),
        expected_recipient_name="Selected Studio",
        expected_organization_names=["Example Architects"],
    )

    assert evidence.pages[0].content_sha256 == hashlib.sha256(
        current_context.encode()
    ).hexdigest()
    assert evidence.pages[0].content_sha256 != "a" * 64


def _addrinfo(*addresses: str) -> list[tuple[Any, ...]]:
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (address, 443),
        )
        for address in addresses
    ]


def test_dns_requires_all_resolved_addresses_to_be_public(monkeypatch):
    monkeypatch.setattr(
        official_source.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo("93.184.216.34", "2606:2800:220:1::1"),
    )

    assert official_source._resolve_public_addresses("example.hu", 443) == {
        ipaddress.ip_address("93.184.216.34"),
        ipaddress.ip_address("2606:2800:220:1::1"),
    }


@pytest.mark.parametrize(
    "addresses",
    [
        ("0.0.0.0",),
        ("::",),
        ("127.0.0.1",),
        ("10.0.0.7",),
        ("169.254.169.254",),
        ("224.0.0.1",),
        ("240.0.0.1",),
        ("::1",),
        ("fc00::1",),
        ("fe80::1",),
        ("ff02::1",),
        ("93.184.216.34", "192.168.1.2"),
        ("2606:2800:220:1::1", "::1"),
    ],
)
def test_private_or_mixed_dns_fails_closed(monkeypatch, addresses):
    monkeypatch.setattr(
        official_source.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo(*addresses),
    )

    with pytest.raises(
        OfficialSourceEvidenceError,
        match="official_source_private_address",
    ):
        official_source._resolve_public_addresses("example.hu", 443)


@pytest.mark.parametrize("address", ["224.0.0.1", "ff02::1"])
def test_multicast_dns_fails_closed_before_socket_connect(monkeypatch, address):
    monkeypatch.setattr(
        official_source.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo(address),
    )
    monkeypatch.setattr(
        official_source,
        "_connect_pinned",
        lambda *_args, **_kwargs: pytest.fail(
            "multicast DNS result must be rejected before socket connect"
        ),
    )

    with pytest.raises(
        OfficialSourceEvidenceError,
        match="official_source_private_address",
    ):
        official_source._fetch_html(
            ROOT_URL,
            allowed_urls={ROOT_URL},
            root_domain="example.hu",
            max_bytes=1024,
            max_redirects=0,
            expected_final_url=ROOT_URL,
            deadline_monotonic=official_source.time.monotonic() + 1.0,
        )


@pytest.mark.parametrize("host", ["localhost", "service.local", "127.0.0.1", "::1"])
def test_local_and_literal_private_hosts_are_rejected_without_dns(monkeypatch, host):
    monkeypatch.setattr(
        official_source.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail("DNS must not run for a private literal"),
    )

    with pytest.raises(OfficialSourceEvidenceError, match="official_source_private_address"):
        official_source._resolve_public_addresses(host, 443)


def test_tls_socket_is_pinned_to_resolved_ip_with_original_hostname(monkeypatch):
    calls: dict[str, Any] = {}

    class RawSocket:
        def settimeout(self, value: float):
            calls["raw_timeout"] = value

        def close(self):
            calls["raw_closed"] = True

    raw = RawSocket()
    tls = SimpleNamespace()

    class Context:
        def wrap_socket(self, current_raw, *, server_hostname):
            calls["wrapped"] = (current_raw, server_hostname)
            return tls

    monkeypatch.setattr(
        official_source.socket,
        "create_connection",
        lambda address, timeout: calls.update(
            connect_address=address,
            timeout=timeout,
        )
        or raw,
    )
    monkeypatch.setattr(official_source.ssl, "create_default_context", Context)
    monkeypatch.setattr(official_source.time, "monotonic", lambda: 0.0)

    connection = official_source._connect_pinned(
        "example.hu",
        443,
        PUBLIC_IP,
        3.5,
    )

    assert calls["connect_address"] == (str(PUBLIC_IP), 443)
    assert calls["timeout"] == 3.5
    assert calls["wrapped"] == (raw, "example.hu")
    assert connection.host == "example.hu"
    assert connection.sock is tls


class _Socket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)


class _Response:
    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        chunks: Iterable[bytes] = (b"<p>ok</p>", b""),
    ) -> None:
        self.status = status
        self._headers = headers or {"Content-Type": "text/html"}
        self._chunks = iter(chunks)

    def getheaders(self):
        return list(self._headers.items())

    def read1(self, _size: int) -> bytes:
        return next(self._chunks, b"")


class _Connection:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.sock = _Socket()
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.closed = False

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        self.requests.append((method, path, headers))

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        self.closed = True


def _install_http(
    monkeypatch,
    responses: Iterable[_Response],
) -> tuple[list[_Connection], list[tuple[str, int, str, float]]]:
    queue = iter(responses)
    connections: list[_Connection] = []
    pins: list[tuple[str, int, str, float]] = []
    monkeypatch.setattr(
        official_source,
        "_resolve_public_addresses",
        lambda *_args, **_kwargs: {PUBLIC_IP},
    )

    def connect(host: str, port: int, source_ip, deadline_monotonic: float):
        pins.append((host, port, str(source_ip), deadline_monotonic))
        connection = _Connection(next(queue))
        connections.append(connection)
        return connection

    monkeypatch.setattr(official_source, "_connect_pinned", connect)
    return connections, pins


def _fetch(
    *,
    allowed_urls: set[str] | None = None,
    expected_final_url: str = ROOT_URL,
    deadline: float = 100.0,
    max_bytes: int = 1024,
):
    return official_source._fetch_html(
        ROOT_URL,
        allowed_urls=allowed_urls or {ROOT_URL},
        root_domain="example.hu",
        max_bytes=max_bytes,
        max_redirects=3,
        expected_final_url=expected_final_url,
        deadline_monotonic=deadline,
    )


def test_fetch_uses_pinned_ip_tls_host_header_and_identity_encoding(monkeypatch):
    connections, pins = _install_http(monkeypatch, [_Response()])
    monkeypatch.setattr(official_source.time, "monotonic", lambda: 0.0)

    page, body = _fetch()

    assert pins == [("example.hu", 443, str(PUBLIC_IP), 100.0)]
    method, path, headers = connections[0].requests[0]
    assert (method, path) == ("GET", "/")
    assert headers["Host"] == "example.hu"
    assert headers["Accept"] == "text/html"
    assert headers["Accept-Encoding"] == "identity"
    assert page.source_ip == str(PUBLIC_IP)
    assert body == "<p>ok</p>"
    assert connections[0].closed


def test_exact_allowlisted_same_root_redirect_is_followed(monkeypatch):
    redirected = "https://example.hu/approved"
    connections, _ = _install_http(
        monkeypatch,
        [
            _Response(status=302, headers={"Location": "/approved"}),
            _Response(),
        ],
    )
    monkeypatch.setattr(official_source.time, "monotonic", lambda: 0.0)

    page, _ = _fetch(
        allowed_urls={ROOT_URL, redirected},
        expected_final_url=redirected,
    )

    assert page.final_url == redirected
    assert connections[0].requests[0][1] == "/"
    assert connections[1].requests[0][1] == "/approved"


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example.net/approved",
        "https://example.hu/not-allowlisted",
        "https://example.hu/approved?unexpected=1",
        "http://example.hu/approved",
    ],
)
def test_redirect_requires_exact_https_allowlist_and_same_root(monkeypatch, location):
    redirected = "https://example.hu/approved"
    _install_http(
        monkeypatch,
        [_Response(status=302, headers={"Location": location})],
    )
    monkeypatch.setattr(official_source.time, "monotonic", lambda: 0.0)

    with pytest.raises(OfficialSourceEvidenceError):
        _fetch(
            allowed_urls={ROOT_URL, redirected},
            expected_final_url=redirected,
        )


@pytest.mark.parametrize(
    ("response", "expected_error", "max_bytes"),
    [
        (_Response(status=404), "official_source_http_not_200", 1024),
        (
            _Response(headers={"Content-Type": "application/json"}),
            "official_source_mime_not_html",
            1024,
        ),
        (
            _Response(headers={"Content-Type": "application/rss+xml"}),
            "official_source_mime_not_html",
            1024,
        ),
        (
            _Response(
                headers={
                    "Content-Type": "text/html",
                    "Content-Encoding": "gzip",
                }
            ),
            "official_source_compression_forbidden",
            1024,
        ),
        (
            _Response(
                headers={"Content-Type": "text/html", "Content-Length": "2048"}
            ),
            "official_source_response_too_large",
            1024,
        ),
        (
            _Response(
                headers={"Content-Type": "text/html"},
                chunks=(b"x" * 1025, b""),
            ),
            "official_source_response_too_large",
            1024,
        ),
        (
            _Response(headers={"Content-Type": "text/html"}, chunks=(b"",)),
            "official_source_response_empty",
            1024,
        ),
    ],
)
def test_non_200_non_html_compression_oversize_and_empty_fail_closed(
    monkeypatch,
    response,
    expected_error,
    max_bytes,
):
    _install_http(monkeypatch, [response])
    monkeypatch.setattr(official_source.time, "monotonic", lambda: 0.0)

    with pytest.raises(OfficialSourceEvidenceError, match=expected_error):
        _fetch(max_bytes=max_bytes)


def test_total_deadline_is_checked_before_connect(monkeypatch):
    monkeypatch.setattr(official_source.time, "monotonic", lambda: 101.0)
    monkeypatch.setattr(
        official_source,
        "_connect_pinned",
        lambda *_args, **_kwargs: pytest.fail("connect must not run after deadline"),
    )

    with pytest.raises(OfficialSourceEvidenceError, match="official_source_fetch_timeout"):
        _fetch(deadline=100.0)


def test_chunk_read_rechecks_total_deadline(monkeypatch):
    _install_http(monkeypatch, [_Response(chunks=(b"first", b"second", b""))])
    calls = 0

    def monotonic():
        nonlocal calls
        calls += 1
        return 0.0 if calls <= 6 else 2.0

    monkeypatch.setattr(
        official_source.time,
        "monotonic",
        monotonic,
    )

    with pytest.raises(OfficialSourceEvidenceError, match="official_source_fetch_timeout"):
        _fetch(deadline=1.0)


def test_unexpected_policy_final_url_drift_fails_even_after_http_200(monkeypatch):
    redirected = "https://example.hu/approved"
    _install_http(monkeypatch, [_Response()])
    monkeypatch.setattr(official_source.time, "monotonic", lambda: 0.0)

    with pytest.raises(
        OfficialSourceEvidenceError,
        match="official_source_final_url_mismatch",
    ):
        _fetch(
            allowed_urls={ROOT_URL, redirected},
            expected_final_url=redirected,
        )
