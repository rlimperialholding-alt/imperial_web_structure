from __future__ import annotations

import os
import tempfile

test_temp_root = tempfile.gettempdir().replace("\\", "/")
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{test_temp_root}/iip_control_center_tests_{os.getpid()}.db",
)
os.environ.setdefault("SESSION_SECRET", "test-session-secret-which-is-long-enough")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "CONTENT_EXPERT_REVIEW_SECRET",
    "test-only-expert-review-attestation-secret-which-is-long-enough",
)
os.environ.setdefault("CONTENT_EXPERT_REVIEW_KEY_ID", "test-expert-review-key-v1")
os.environ.setdefault(
    "CONTENT_MARKETING_REVIEW_SECRET",
    "test-only-marketing-review-attestation-secret-which-is-long-enough",
)
os.environ.setdefault("CONTENT_MARKETING_REVIEW_KEY_ID", "test-marketing-review-key-v1")
os.environ.setdefault(
    "CONTENT_COPYWRITER_REVIEW_SECRET",
    "test-only-copywriter-review-attestation-secret-which-is-long-enough",
)
os.environ.setdefault("CONTENT_COPYWRITER_REVIEW_KEY_ID", "test-copywriter-review-key-v1")
os.environ.setdefault(
    "CONTENT_VISUAL_REVIEW_SECRET",
    "test-only-visual-review-attestation-secret-which-is-long-enough",
)
os.environ.setdefault("CONTENT_VISUAL_REVIEW_KEY_ID", "test-visual-review-key-v1")
os.environ.setdefault(
    "CONTENT_CAMPAIGN_PACKAGE_SECRET",
    "test-only-campaign-package-attestation-secret-which-is-long-enough",
)
os.environ.setdefault("CONTENT_CAMPAIGN_PACKAGE_KEY_ID", "test-campaign-package-key-v1")
os.environ.setdefault(
    "IMPERIAL_RELEASE_HMAC_KEY",
    "test-only-release-hmac-key-which-is-long-enough-and-distinct",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_database  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def logged_in_client(client):
    response = client.post("/login", data={"email": "platform-admin@imperial.local", "password": "Imperial2026!"}, follow_redirects=False)
    assert response.status_code == 303
    return client
