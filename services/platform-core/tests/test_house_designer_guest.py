import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import (
    AuditLog,
    HouseDesignerEntitlement,
    HouseDesignerGuestRateLimit,
    HouseDesignGuestClaim,
    HouseDesignRevision,
    HouseDesignSession,
)
from app.services.house_designer import HouseDesignerError
from app.services.house_designer_guest import (
    GUEST_CLAIM_COOKIE,
    GUEST_SESSION_COOKIE,
    claim_guest_design,
    consume_guest_creation_quota,
    create_guest_design,
    resolve_guest_actor,
)


def _enable_sandbox(db) -> None:
    db.add(
        HouseDesignerEntitlement(
            entitlement_id="HDENT-GUEST-TEST",
            tenant_id="imperial-holding",
            brand_id="imperial",
            status="sandbox",
            standalone_enabled=True,
            created_by="test",
        )
    )
    db.commit()


def test_guest_issue_claim_rotation_and_replay_protection(db):
    with pytest.raises(HouseDesignerError) as disabled:
        create_guest_design(
            db,
            brand_id="imperial",
            title="Tiltott vendégterv",
            command_id=str(uuid4()),
        )
    assert disabled.value.code == "standalone_not_enabled"

    _enable_sandbox(db)
    issued = create_guest_design(
        db,
        brand_id="imperial",
        title="Vendégként indított terv",
        command_id=str(uuid4()),
    )
    assert issued.guest_session_token not in repr(issued)
    assert issued.claim_token not in repr(issued)
    actor = resolve_guest_actor(
        db,
        guest_session_token=issued.guest_session_token,
        expected_session_id=issued.design["sessionId"],
    )
    assert actor.subject_id.startswith("guest:HDGC-")

    with pytest.raises(HouseDesignerError) as mismatch:
        claim_guest_design(
            db,
            guest_session_token="different-browser-session",
            claim_token=issued.claim_token,
            authenticated_subject_id="customer-subject",
        )
    assert mismatch.value.code == "guest_claim_scope_mismatch"
    assert mismatch.value.status_code == 404

    claimed = claim_guest_design(
        db,
        guest_session_token=issued.guest_session_token,
        claim_token=issued.claim_token,
        authenticated_subject_id="customer-subject",
    )
    assert claimed["sessionId"] == issued.design["sessionId"]
    session = db.scalar(
        select(HouseDesignSession).where(
            HouseDesignSession.session_id == issued.design["sessionId"]
        )
    )
    claim = db.scalar(
        select(HouseDesignGuestClaim).where(
            HouseDesignGuestClaim.session_id == issued.design["sessionId"]
        )
    )
    assert session.owner_subject_id == "customer-subject"
    assert claim.status == "claimed"
    assert claim.claimed_by_subject_id == "customer-subject"

    with pytest.raises(HouseDesignerError) as rotated:
        resolve_guest_actor(
            db,
            guest_session_token=issued.guest_session_token,
            expected_session_id=issued.design["sessionId"],
        )
    assert rotated.value.code == "guest_session_not_found"
    with pytest.raises(HouseDesignerError) as replay:
        claim_guest_design(
            db,
            guest_session_token=issued.guest_session_token,
            claim_token=issued.claim_token,
            authenticated_subject_id="customer-subject",
        )
    assert replay.value.code == "guest_claim_replayed"
    assert replay.value.status_code == 409

    audit_rows = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_type.in_(("HouseDesignGuestClaim", "HouseDesignSession"))
        )
    ).all()
    serialized = "\n".join(str(row.after_json or "") for row in audit_rows)
    assert issued.guest_session_token not in serialized
    assert issued.claim_token not in serialized


def test_expired_guest_access_is_fail_closed(db):
    _enable_sandbox(db)
    issued = create_guest_design(
        db,
        brand_id="imperial",
        title="Lejárt vendégterv",
        command_id=str(uuid4()),
    )
    claim = db.scalar(
        select(HouseDesignGuestClaim).where(
            HouseDesignGuestClaim.session_id == issued.design["sessionId"]
        )
    )
    claim.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    with pytest.raises(HouseDesignerError) as expired_session:
        resolve_guest_actor(db, guest_session_token=issued.guest_session_token)
    assert expired_session.value.code == "guest_session_not_found"
    with pytest.raises(HouseDesignerError) as expired_claim:
        claim_guest_design(
            db,
            guest_session_token=issued.guest_session_token,
            claim_token=issued.claim_token,
            authenticated_subject_id="customer-subject",
        )
    assert expired_claim.value.code == "guest_claim_expired"
    db.refresh(claim)
    assert claim.status == "expired"
    assert claim.revoked_at is not None


def test_public_standalone_design_is_claimed_on_login(client, db):
    _enable_sandbox(db)
    landing = client.get("/house-designer/standalone")
    assert landing.status_code == 200
    csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', landing.text)
    assert csrf_match
    created = client.post(
        "/house-designer/standalone/sessions",
        data={
            "csrf_token": csrf_match.group(1),
            "command_id": str(uuid4()),
            "title": "Publikus vendégterv",
            "origin": "blank",
            "width_mm": "10000",
            "depth_mm": "8000",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    detail_url = created.headers["location"]
    assert detail_url.startswith("/house-designer/sessions/HDS-")
    guest_token = client.cookies.get(GUEST_SESSION_COOKIE)
    claim_token = client.cookies.get(GUEST_CLAIM_COOKIE)
    assert guest_token and claim_token
    assert "HttpOnly" in created.headers.get("set-cookie", "")

    detail = client.get(detail_url)
    assert detail.status_code == 200
    assert "Publikus vendégterv" in detail.text
    session_id = detail_url.rsplit("/", 1)[-1]
    standalone_detail = client.get(
        f"/house-designer/standalone/sessions/{session_id}"
    )
    assert standalone_detail.status_code == 200
    assert detail.headers["etag"] == standalone_detail.headers["etag"]
    design_hash = re.search(r'data-canonical-sha256="([^"]+)"', detail.text)
    assert design_hash
    assert detail.headers["etag"] == f'"{design_hash.group(1)}"'
    assert detail.headers["cache-control"] == "private, no-cache"
    assert f'action="/house-designer/sessions/{session_id}/approve"' not in standalone_detail.text
    session = db.scalar(
        select(HouseDesignSession).where(HouseDesignSession.session_id == session_id)
    )
    revision = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == session.current_revision_id
        )
    )
    changed = client.post(
        f"{detail_url}/commands",
        data={
            "csrf_token": csrf_match.group(1),
            "command_id": str(uuid4()),
            "command_type": "set_north",
            "base_revision_id": revision.revision_id,
            "base_canonical_sha256": revision.canonical_sha256,
            "northAngleDeg": "22",
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303
    changed_detail = client.get(detail_url)
    changed_standalone = client.get(
        f"/house-designer/standalone/sessions/{session_id}"
    )
    assert changed_detail.headers["etag"] == changed_standalone.headers["etag"]
    assert changed_detail.headers["etag"] != detail.headers["etag"]
    db.expire_all()
    session = db.scalar(
        select(HouseDesignSession).where(HouseDesignSession.session_id == session_id)
    )
    revision = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == session.current_revision_id
        )
    )
    guest_api_change = client.post(
        f"/api/v1/house-designer/sessions/{session_id}/commands",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf_match.group(1),
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid4()),
            "If-Match": revision.canonical_sha256,
        },
        json={
            "baseRevisionId": revision.revision_id,
            "commandType": "set_north",
            "payload": {"northAngleDeg": 23},
        },
    )
    assert guest_api_change.status_code == 200
    assert guest_api_change.json()["revision"]["geometry"]["northAngleDeg"] == 23

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as outsider:
        assert outsider.get(detail_url).status_code == 404
        outsider_api = outsider.post(
            f"/api/v1/house-designer/sessions/{session_id}/commands",
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": csrf_match.group(1),
                "Content-Type": "application/json",
                "Idempotency-Key": str(uuid4()),
                "If-Match": guest_api_change.json()["revision"]["canonicalSha256"],
            },
            json={
                "baseRevisionId": guest_api_change.json()["revision"]["revisionId"],
                "commandType": "set_north",
                "payload": {"northAngleDeg": 24},
            },
        )
        assert outsider_api.status_code == 403
        outsider_landing = outsider.get("/house-designer/standalone")
        outsider_csrf = re.search(
            r'name="csrf_token" value="([^"]+)"', outsider_landing.text
        )
        assert outsider_csrf
        outsider_scoped_api = outsider.post(
            f"/api/v1/house-designer/sessions/{session_id}/commands",
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": outsider_csrf.group(1),
                "Content-Type": "application/json",
                "Idempotency-Key": str(uuid4()),
                "If-Match": guest_api_change.json()["revision"]["canonicalSha256"],
            },
            json={
                "baseRevisionId": guest_api_change.json()["revision"]["revisionId"],
                "commandType": "set_north",
                "payload": {"northAngleDeg": 24},
            },
        )
        assert outsider_scoped_api.status_code == 404

    login = client.post(
        "/login",
        data={
            "email": "customer@imperial.local",
            "password": "Imperial2026!",
            "return_to": "/house-designer",
        },
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == detail_url
    assert client.cookies.get(GUEST_SESSION_COOKIE) is None
    assert client.cookies.get(GUEST_CLAIM_COOKIE) is None
    db.expire_all()
    session = db.scalar(
        select(HouseDesignSession).where(HouseDesignSession.session_id == session_id)
    )
    assert session.owner_subject_id == "ITEP-DEMO-CUSTOMER"
    assert client.get(detail_url).status_code == 200

    with TestClient(app) as replay:
        replay.cookies.set(GUEST_SESSION_COOKIE, guest_token, path="/")
        replay.cookies.set(GUEST_CLAIM_COOKIE, claim_token, path="/")
        assert replay.get(detail_url).status_code == 404


def test_guest_creation_rate_limit_is_durable_and_privacy_preserving(db):
    fingerprint = "198.51.100.42|test-browser/1.0"
    first = consume_guest_creation_quota(
        db,
        brand_id="imperial",
        fingerprint_source=fingerprint,
        limit=2,
        window_seconds=60,
        block_seconds=120,
    )
    second = consume_guest_creation_quota(
        db,
        brand_id="imperial",
        fingerprint_source=fingerprint,
        limit=2,
        window_seconds=60,
        block_seconds=120,
    )
    assert first["remaining"] == 1
    assert second["remaining"] == 0
    with pytest.raises(HouseDesignerError) as blocked:
        consume_guest_creation_quota(
            db,
            brand_id="imperial",
            fingerprint_source=fingerprint,
            limit=2,
            window_seconds=60,
            block_seconds=120,
        )
    assert blocked.value.code == "guest_rate_limited"
    assert blocked.value.status_code == 429
    row = db.scalar(select(HouseDesignerGuestRateLimit))
    assert row.attempt_count == 2
    assert row.blocked_until is not None
    assert fingerprint not in row.fingerprint_hash
    assert len(row.fingerprint_hash) == 64

    row.window_started_at = datetime.now(UTC) - timedelta(seconds=61)
    row.blocked_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    reset = consume_guest_creation_quota(
        db,
        brand_id="imperial",
        fingerprint_source=fingerprint,
        limit=2,
        window_seconds=60,
        block_seconds=120,
    )
    assert reset["attemptCount"] == 1
    assert reset["remaining"] == 1


def test_public_guest_creation_returns_retry_after_when_limited(client, db):
    _enable_sandbox(db)
    landing = client.get("/house-designer/standalone")
    csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', landing.text)
    assert csrf_match
    payload = {
        "csrf_token": csrf_match.group(1),
        "title": "Rate limit teszt",
        "origin": "blank",
        "width_mm": "10000",
        "depth_mm": "8000",
    }
    for _ in range(5):
        response = client.post(
            "/house-designer/standalone/sessions",
            data={**payload, "command_id": str(uuid4())},
            follow_redirects=False,
        )
        assert response.status_code == 303
    blocked = client.post(
        "/house-designer/standalone/sessions",
        data={**payload, "command_id": str(uuid4())},
        follow_redirects=False,
    )
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "3600"
