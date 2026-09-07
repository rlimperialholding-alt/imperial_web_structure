"""Bounded public forum requests, including Index's anonymous session handshake."""

from __future__ import annotations

import time
from collections.abc import Callable
from http.cookies import CookieError, SimpleCookie
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse


def _public_origin(url: str) -> str:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid_forum_redirect") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in {None, 443}
    ):
        raise ValueError("invalid_forum_redirect")
    return parsed.hostname.casefold().rstrip(".")


def _allowed_redirect(current: str, target: str, original_host: str) -> bool:
    current_host = _public_origin(current)
    target_host = _public_origin(target)
    if target_host == current_host == original_host:
        return True
    if original_host == "prohardver.hu":
        if current_host == original_host and target_host == "auth.rios.hu":
            parsed = urlparse(target)
            query = dict(parse_qsl(parsed.query))
            return (
                parsed.path == "/hozzaferes/azonosit.php"
                and query.get("redir_host") == original_host
                and query.get("redir_uri", "").startswith("/tema/")
            )
        return current_host == "auth.rios.hu" and target_host == original_host
    if original_host != "forum.index.hu":
        return False
    if current_host == "forum.index.hu" and target_host == "daemon.indapass.hu":
        parsed = urlparse(target)
        query = dict(parse_qsl(parsed.query))
        try:
            return (
                parsed.path == "/http/session_request"
                and query.get("partner_id") == "forum"
                and _public_origin(query.get("redirect_to", "")) == original_host
            )
        except ValueError:
            return False
    return current_host == "daemon.indapass.hu" and target_host == original_host


def forum_public_get(
    url: str,
    *,
    max_response_bytes: int,
    deadline_monotonic: float,
    pinned_get: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Follow same-host redirects and exact public Index/Prohardver handshakes.

    The supplied transport validates public DNS and pins the connection on every
    hop. The fresh, host-only cookie jar contains only cookies this request chain
    receives; no browser login, persisted credentials, or user cookies are used.
    """

    original_host = _public_origin(url)
    current = url
    cookies: dict[str, dict[str, tuple[str, str]]] = {}
    received = 0
    for hop in range(5):
        if time.monotonic() >= deadline_monotonic:
            raise ValueError("forum_fetch_timeout")
        host = _public_origin(current)
        path = urlparse(current).path or "/"
        cookie_values = [
            f"{name}={value}"
            for name, (value, cookie_path) in cookies.get(host, {}).items()
            if path == cookie_path or path.startswith(cookie_path.rstrip("/") + "/")
        ]
        request_headers = {"Cookie": "; ".join(cookie_values)} if cookie_values else {}
        response = pinned_get(
            current,
            max_response_bytes=max_response_bytes - received,
            deadline_monotonic=deadline_monotonic,
            request_headers=request_headers,
        )
        received += len(bytes(response.get("body", b"")))
        if received > max_response_bytes:
            raise ValueError("forum_response_too_large")
        headers = {str(k).casefold(): str(v) for k, v in response.get("headers", {}).items()}
        cookie_headers = response.get("set_cookie_headers") or (
            [headers["set-cookie"]] if headers.get("set-cookie") else []
        )
        for raw in cookie_headers:
            jar: SimpleCookie[str] = SimpleCookie()
            try:
                jar.load(raw)
            except CookieError:
                continue
            for name, morsel in jar.items():
                domain = morsel["domain"].casefold().lstrip(".")
                if domain and host != domain and not host.endswith("." + domain):
                    continue
                host_jar = cookies.setdefault(host, {})
                if morsel["max-age"] == "0":
                    host_jar.pop(name, None)
                elif len(host_jar) < 32 and len(morsel.coded_value) <= 4096:
                    # Never expand Domain cookies to another redirect host.
                    host_jar[name] = (morsel.coded_value, morsel["path"] or "/")
        status = int(response["status_code"])
        if status not in {301, 302, 303, 307, 308}:
            return {**response, "final_url": current, "redirect_count": hop}
        location = headers.get("location", "")
        if not location or hop == 4:
            raise ValueError("forum_redirect_limit")
        target = urljoin(current, location)
        if not _allowed_redirect(current, target, original_host):
            raise ValueError("forum_redirect_outside_public_surface")
        current = target
    raise ValueError("forum_redirect_limit")
