from __future__ import annotations

import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx

SENSITIVE_KEYS = {
    "authorization",
    "access_token",
    "token",
    "password",
    "secret",
    "signature",
    "appsecret_proof",
}


class PublishingHttpError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


@dataclass
class CircuitState:
    failures: int = 0
    opened_until: float = 0.0


class ProductionHttpClient:
    metrics: Counter = Counter()
    latency_seconds: dict[str, list[float]] = defaultdict(list)
    circuits: dict[str, CircuitState] = defaultdict(CircuitState)

    def __init__(self, *, timeout_seconds: float, max_response_bytes: int = 4_000_000) -> None:
        self.timeout = httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds))
        self.max_response_bytes = max_response_bytes
        self.client = httpx.Client(
            timeout=self.timeout,
            verify=True,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": "ImperialAutonomousPublishing/1.0"},
        )

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return max(0.0, min(60.0, float(raw)))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(raw)
                return max(0.0, min(60.0, parsed.timestamp() - time.time()))
            except (TypeError, ValueError):
                return None

    def request(
        self,
        adapter: str,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        correlation_id: str,
        request_id: str,
        idempotency_key: str | None = None,
        allow_idempotent_post_retry: bool = False,
        max_attempts: int = 3,
    ) -> httpx.Response:
        method = method.upper()
        host = urlparse(url).hostname or "unknown"
        circuit = self.circuits[f"{adapter}:{host}"]
        now = time.monotonic()
        if circuit.opened_until > now:
            raise PublishingHttpError("adapter circuit is open", retryable=True)
        can_retry = method in {"GET", "HEAD", "PUT", "DELETE"} or (
            method == "POST" and bool(idempotency_key) and allow_idempotent_post_retry
        )
        attempts = max_attempts if can_retry else 1
        merged = {
            "X-Correlation-ID": correlation_id,
            "X-Request-ID": request_id,
            **(headers or {}),
        }
        if idempotency_key:
            merged["Idempotency-Key"] = idempotency_key
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                response = self.client.request(
                    method,
                    url,
                    headers=merged,
                    params=params,
                    json=json_body,
                    data=data,
                    files=files,
                )
                elapsed = time.monotonic() - started
                self.latency_seconds[adapter].append(elapsed)
                self.metrics[f"{adapter}.requests"] += 1
                length = int(response.headers.get("Content-Length") or len(response.content))
                if (
                    length > self.max_response_bytes
                    or len(response.content) > self.max_response_bytes
                ):
                    raise PublishingHttpError(
                        "response size limit exceeded", status=response.status_code
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    self.metrics[f"{adapter}.retryable"] += 1
                    if attempt < attempts:
                        delay = self._retry_after(response)
                        if delay is None:
                            delay = min(8.0, 0.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.25)
                        time.sleep(delay)
                        continue
                    raise PublishingHttpError(
                        f"upstream HTTP {response.status_code}",
                        status=response.status_code,
                        retryable=True,
                    )
                if response.status_code >= 400:
                    raise PublishingHttpError(
                        f"upstream HTTP {response.status_code}",
                        status=response.status_code,
                        retryable=False,
                    )
                circuit.failures = 0
                circuit.opened_until = 0.0
                return response
            except (httpx.TimeoutException, httpx.NetworkError, PublishingHttpError) as exc:
                last_error = exc
                retryable = not isinstance(exc, PublishingHttpError) or exc.retryable
                if retryable and attempt < attempts:
                    time.sleep(min(8.0, 0.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.25))
                    continue
                circuit.failures += 1
                if circuit.failures >= 5:
                    circuit.opened_until = time.monotonic() + 60
                self.metrics[f"{adapter}.failures"] += 1
                if isinstance(exc, PublishingHttpError):
                    raise
                raise PublishingHttpError(type(exc).__name__, retryable=retryable) from exc
        raise PublishingHttpError(type(last_error).__name__ if last_error else "request failed")

    @classmethod
    def metric_snapshot(cls) -> dict[str, Any]:
        latency = {
            adapter: {
                "count": len(values),
                "average_seconds": round(sum(values) / len(values), 6) if values else 0,
                "max_seconds": round(max(values), 6) if values else 0,
            }
            for adapter, values in cls.latency_seconds.items()
        }
        return {"counters": dict(cls.metrics), "latency": latency}
