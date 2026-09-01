from __future__ import annotations

from http import HTTPStatus
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1").strip()
    return ""


def _normalized_authority(value: str) -> str:
    return value.lower().rstrip(".")


def _same_origin(scope: Scope) -> bool:
    host = _normalized_authority(_header(scope, b"host"))
    if not host:
        return False
    origin = _header(scope, b"origin")
    if origin:
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and _normalized_authority(parsed.netloc) == host
    referer = _header(scope, b"referer")
    if referer:
        parsed = urlsplit(referer)
        return parsed.scheme in {"http", "https"} and _normalized_authority(parsed.netloc) == host
    return False


class SessionWriteOriginMiddleware:
    """Fail closed for browser writes authenticated by an Imperial session cookie.

    API-token and signed public-token flows do not create an authenticated session and
    remain governed by their own token checks. Session-authenticated browser requests
    must prove a same-origin browser context even when a legacy form has not yet been
    migrated to the synchronizer-token helper.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        method_is_safe = scope.get("method", "GET").upper() not in UNSAFE_METHODS
        if scope["type"] != "http" or method_is_safe:
            await self.app(scope, receive, send)
            return
        session = scope.get("session") or {}
        authenticated = bool(session.get("user_id") or session.get("partner_access_id"))
        if not authenticated or _same_origin(scope):
            await self.app(scope, receive, send)
            return
        body = (
            "A munkamenettel hitelesített írás csak azonos eredetű felületről indítható.".encode()
        )
        headers = [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
        ]
        await send(
            {
                "type": "http.response.start",
                "status": HTTPStatus.FORBIDDEN,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": body})
