from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("AUTH_MODE", "test")
os.environ.setdefault("QUEUE_ENABLED", "false")

from app.config import get_settings  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.main import app  # noqa: E402

ADMIN_HEADERS = {
    "X-Test-Subject": "test:platform-admin",
    "X-Test-Scopes": "digital-pm:read digital-pm:write digital-pm:approve digital-pm:audit",
    "X-Test-Role": "platform-admin",
}


@pytest.fixture(scope="session", autouse=True)
def database_is_migrated() -> None:
    with get_engine().connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == "20260724_0002"


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session", autouse=True)
def clear_settings_after_tests() -> Generator[None, None, None]:
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()
