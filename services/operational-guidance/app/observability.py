from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable

try:
    import structlog
except ModuleNotFoundError:  # dependency is installed in the release image
    structlog = None
from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import Actor
from app.config import get_settings


class _FallbackLogger:
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def info(self, event: str, **metadata) -> None:
        self.logger.info("%s %s", event, json.dumps(metadata, ensure_ascii=False, default=str))

    def warning(self, event: str, **metadata) -> None:
        self.logger.warning("%s %s", event, json.dumps(metadata, ensure_ascii=False, default=str))


log = structlog.get_logger(__name__) if structlog is not None else _FallbackLogger()

HTTP_REQUESTS = Counter(
    "imperial_http_requests_total",
    "HTTP requests handled by the Integration Hub",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "imperial_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "route"],
)
AUTH_FAILURES = Counter(
    "imperial_auth_failures_total",
    "Authentication or authorization failures",
    ["status", "route"],
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        supplied = request.headers.get("x-request-id", "").strip()
        request_id = supplied[:64] if supplied and len(supplied) <= 64 else uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        response: Response | None = None
        error_name: str | None = None
        try:
            response = await call_next(request)
            return response
        except Exception as exc:  # noqa: BLE001 - middleware must audit unexpected failures
            error_name = type(exc).__name__
            raise
        finally:
            duration = max(0.0, time.perf_counter() - started)
            status_code = response.status_code if response is not None else 500
            route_obj = request.scope.get("route")
            route = getattr(route_obj, "path", request.url.path)
            HTTP_REQUESTS.labels(request.method, route, str(status_code)).inc()
            HTTP_DURATION.labels(request.method, route).observe(duration)
            if status_code in {401, 403}:
                AUTH_FAILURES.labels(str(status_code), route).inc()
            if response is not None:
                response.headers["X-Request-ID"] = request_id
            actor = getattr(request.state, "actor", None)
            actor_fields = _actor_fields(actor)
            log.info(
                "http_request",
                request_id=request_id,
                method=request.method,
                path=route,
                status_code=status_code,
                duration_ms=round(duration * 1000),
                error=error_name,
                **actor_fields,
            )
            if settings.audit_log_enabled and route not in {"/live", "/health", "/ready", "/metrics"}:
                _persist_audit(
                    request_id=request_id,
                    actor=actor,
                    method=request.method,
                    path=route,
                    status_code=status_code,
                    duration_ms=round(duration * 1000),
                    metadata={"error": error_name} if error_name else {},
                )


def _actor_fields(actor: Actor | None) -> dict[str, str | None]:
    if actor is None:
        return {"actor_subject": None, "actor_kind": None, "actor_role": None}
    return {
        "actor_subject": actor.subject,
        "actor_kind": actor.kind,
        "actor_role": actor.role.value if actor.role else None,
    }


def _persist_audit(
    *,
    request_id: str,
    actor: Actor | None,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    metadata: dict,
) -> None:
    fields = _actor_fields(actor)
    try:
        from app.db import SessionLocal
        from app.models import AuditEventRecord

        with SessionLocal() as db:
            db.add(
                AuditEventRecord(
                    request_id=request_id,
                    actor_subject=fields["actor_subject"],
                    actor_kind=fields["actor_kind"],
                    actor_role=fields["actor_role"],
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    metadata_json=metadata,
                )
            )
            db.commit()
    except Exception as exc:  # noqa: BLE001 - audit failure must not break business traffic
        log.warning("audit_persist_failed", request_id=request_id, error=f"{type(exc).__name__}: {exc}")


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


class RequestSizeLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        raw_length = headers.get(b"content-length", b"0")
        try:
            declared = int(raw_length)
        except ValueError:
            declared = 0
        if declared > self.max_bytes:
            response = Response(
                content='{"detail":"Request body too large"}',
                status_code=413,
                media_type="application/json",
            )
            await response(scope, receive, send)
            return

        messages = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message.get("type") == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    response = Response(
                        content='{"detail":"Request body too large"}',
                        status_code=413,
                        media_type="application/json",
                    )
                    await response(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            else:
                break

        iterator = iter(messages)

        async def replay_receive():
            try:
                return next(iterator)
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)
