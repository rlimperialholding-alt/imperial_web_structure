from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import jwt
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.adapters.external import (
    DisabledExternalAdapter,
    ExternalAdapterRegistry,
    HttpExternalAdapter,
)
from app.auth import _decode_token
from app.config import Settings
from app.queue import enqueue_task


def test_hs256_token_is_strictly_validated() -> None:
    now = datetime.now(UTC)
    secret = "unit-test-only-secret-at-least-32-bytes"
    settings = Settings(
        app_env="development",
        auth_mode="oidc",
        database_url="postgresql+psycopg://unused",
        auth_issuer="issuer",
        auth_audience="audience",
        auth_hs256_secret=SecretStr(secret),
        auth_hs256_secret_file=None,
    )
    token = jwt.encode(
        {
            "sub": "USR-05",
            "iss": "issuer",
            "aud": "audience",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "scope": "digital-pm:read",
        },
        secret,
        algorithm="HS256",
    )
    assert _decode_token(token, settings)["sub"] == "USR-05"


def test_missing_auth_secret_fails_closed() -> None:
    settings = Settings(
        app_env="development",
        auth_mode="oidc",
        database_url="postgresql+psycopg://unused",
        auth_hs256_secret_file=Path("/missing/auth-secret"),
    )
    with pytest.raises(HTTPException) as error:
        _decode_token("not-a-token", settings)
    assert error.value.status_code == 503


def test_test_auth_cannot_be_enabled_outside_tests() -> None:
    with pytest.raises(ValueError):
        Settings(
            app_env="production",
            auth_mode="test",
            database_url="postgresql+psycopg://unused",
        )


def test_secret_file_resolution(tmp_path: Path) -> None:
    password_file = tmp_path / "database-password"
    password_file.write_text("encoded password", encoding="utf-8")
    settings = Settings(
        database_password_file=password_file,
        auth_mode="oidc",
        auth_hs256_secret_file=None,
    )
    assert "encoded+password" in settings.resolved_database_url()


def test_external_adapters_are_disabled_by_default(tmp_path: Path) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://unused",
        auth_mode="oidc",
        auth_hs256_secret_file=None,
        external_writes_enabled=False,
    )
    registry = ExternalAdapterRegistry(settings)
    for name in registry.NAMES:
        adapter = registry.get(name)
        assert isinstance(adapter, DisabledExternalAdapter)
        with pytest.raises(RuntimeError):
            adapter.invoke(action="write", payload={}, idempotency_key="test")
    with pytest.raises(KeyError):
        registry.get("unknown")

    empty_token = tmp_path / "empty-token"
    empty_token.write_text("", encoding="utf-8")
    http_adapter = HttpExternalAdapter("test", "https://example.invalid", empty_token)
    with pytest.raises(RuntimeError):
        http_adapter.invoke(action="write", payload={}, idempotency_key="test")


def test_queue_can_be_disabled_without_redis() -> None:
    assert enqueue_task(UUID("00000000-0000-4000-8000-000000000000")) is False
