from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

from demo_runtime_path_isolation import (
    isolate_demo_credentials_state_path,
    isolate_demo_runtime_path,
    restore_demo_credentials_state_path,
    restore_demo_runtime_path,
)

pytest_temp_root = Path(tempfile.gettempdir()) / f"iip_pytest_{os.getpid()}"
pytest_temp_root.mkdir(parents=True, exist_ok=True)
os.environ["PYTEST_DEBUG_TEMPROOT"] = str(pytest_temp_root)
os.environ.setdefault("PLATFORM_RUNTIME_ROOT", str(pytest_temp_root / "runtime"))
# The demo runtime writes its JSON state next to the seed data by default.
# Force it into the pytest temp root so the suite never rewrites the
# repository runtime data file, where a transient antivirus/indexer/sync
# hold on Windows caused the Gate 6 WinError 5 replacement failure. The
# assignment is unconditional (not setdefault), so an ambient
# DEMO_RUNTIME_PATH cannot redirect test writes outside the temp root; the
# previous value is saved and restored at session end, keeping the change
# reversible and test-scoped. Must be set before app.demo_runtime reads the
# variable at import time.
_previous_demo_runtime_path, _ = isolate_demo_runtime_path(pytest_temp_root)
# The demo-credential state gets the same unconditional, reversible isolation.
_previous_demo_credentials_state_path, _ = isolate_demo_credentials_state_path(pytest_temp_root)


def _cleanup_pytest_temp_root() -> None:
    shutil.rmtree(pytest_temp_root, ignore_errors=True)


atexit.register(_cleanup_pytest_temp_root)

os.environ.setdefault(
    "DATABASE_URL",
    "sqlite://",
)
os.environ.setdefault("SESSION_SECRET", "test-session-secret-which-is-long-enough")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("TENDER_AV_MODE", "test")
os.environ.setdefault("CARE_AV_MODE", "test")
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
os.environ.setdefault("HOUSE_DESIGNER_ADAPTERS_ENABLED", "true")
os.environ.setdefault("HOUSE_DESIGN_ORDER_INTAKE_ENABLED", "true")
os.environ.setdefault("MARKET_EVIDENCE_KEK", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")
os.environ.setdefault("MARKET_EVIDENCE_KEY_ID", "test-mci-evidence-kek-v1")
# A tordeles szandekos: a tracked-secret reconciliation ezt az auditalt
# elofordulast a sor BAJTAZONOS tartalmaval bizonyitja a baseline anchor
# commit ellen. Ujratordeles utan a sor addition lesz es a kapu fail-closed.
os.environ.setdefault(
    "HOUSE_DESIGNER_SITE_KEK", "YWJjZGVmMDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODk="
)  # fmt: skip
os.environ.setdefault("HOUSE_DESIGNER_SITE_KEY_ID", "test-hd-site-kek-v1")
os.environ.setdefault(
    "HOUSE_DESIGNER_PRICING_HMAC_SECRET",
    "test-only-house-designer-pricing-secret-which-is-distinct",
)
os.environ.setdefault(
    "HOUSE_DESIGNER_CAPACITY_HMAC_SECRET",
    "test-only-house-designer-capacity-secret-which-is-distinct",
)
os.environ.setdefault(
    "HOUSE_DESIGNER_RENDER_HMAC_SECRET",
    "test-only-house-designer-render-secret-which-is-distinct",
)
os.environ.setdefault("HOUSE_DESIGNER_CALLBACK_BASE_URL", "https://intelligence.test.example")

import pytest  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import DEMO_PASSWORD, seed_database  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


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
    with TestClient(app, headers={"Origin": "http://testserver"}) as c:
        yield c


@pytest.fixture
def logged_in_client(client):
    response = client.post(
        "/login",
        data={"email": "platform-admin@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client


def pytest_sessionfinish(session, exitstatus):
    del session, exitstatus
    engine.dispose()
    restore_demo_runtime_path(_previous_demo_runtime_path)
    restore_demo_credentials_state_path(_previous_demo_credentials_state_path)
    _cleanup_pytest_temp_root()
