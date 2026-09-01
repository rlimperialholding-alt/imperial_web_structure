from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

import app.main as main_module
from app.database import SessionLocal
from app.models import (
    AuditLog,
    CanonicalDeliveryRecord,
    CanonicalSyncLease,
    EnterpriseCanonicalRecord,
)
from app.services.canonical_bridge import CanonicalBridgeError, push_canonical_to_crm
from app.services.canonical_sync_lease import (
    HEARTBEAT_INTERVAL,
    CanonicalSyncBusy,
    CanonicalSyncLeaseLost,
    acquire_canonical_sync_lease,
)


def test_lease_is_exclusive_releasable_and_generation_tracked(db):
    first = acquire_canonical_sync_lease("crm-push")

    with pytest.raises(CanonicalSyncBusy, match="párhuzamos indítás tiltott"):
        acquire_canonical_sync_lease("crm-push")

    db.expire_all()
    row = db.scalar(
        select(CanonicalSyncLease).where(CanonicalSyncLease.lease_key == "crm-push")
    )
    assert row.holder_token == first.holder_token
    assert row.generation == 1
    assert row.contention_count == 1
    assert row.last_contention_at is not None
    assert first.release() is True

    second = acquire_canonical_sync_lease("crm-push")
    db.expire_all()
    assert db.scalar(
        select(CanonicalSyncLease.generation).where(
            CanonicalSyncLease.lease_key == "crm-push"
        )
    ) == 2
    assert second.release() is True


def test_expired_lease_is_recoverable_and_old_owner_cannot_release_new_owner(db):
    expired_owner = acquire_canonical_sync_lease("crm-import")
    with SessionLocal() as lease_db:
        lease_db.execute(
            update(CanonicalSyncLease)
            .where(CanonicalSyncLease.lease_key == "crm-import")
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        lease_db.commit()

    recovered_owner = acquire_canonical_sync_lease("crm-import")

    assert recovered_owner.holder_token != expired_owner.holder_token
    assert expired_owner.release() is False
    db.expire_all()
    assert db.scalar(
        select(CanonicalSyncLease.holder_token).where(
            CanonicalSyncLease.lease_key == "crm-import"
        )
    ) == recovered_owner.holder_token
    assert recovered_owner.release() is True


def test_heartbeat_fails_closed_after_lease_ownership_is_lost():
    owner = acquire_canonical_sync_lease("itep-pull")
    owner.heartbeat_at = datetime.now(UTC) - HEARTBEAT_INTERVAL
    with SessionLocal() as lease_db:
        lease_db.execute(
            update(CanonicalSyncLease)
            .where(CanonicalSyncLease.lease_key == "itep-pull")
            .values(
                holder_token="replacement-owner",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        lease_db.commit()

    with pytest.raises(CanonicalSyncLeaseLost, match="lease elveszett"):
        owner.renew_if_due()


def test_heartbeat_renews_the_same_owner_without_generation_change(db):
    owner = acquire_canonical_sync_lease("crm-reconcile")
    owner.heartbeat_at = datetime.now(UTC) - HEARTBEAT_INTERVAL

    owner.renew_if_due()

    db.expire_all()
    row = db.scalar(
        select(CanonicalSyncLease).where(
            CanonicalSyncLease.lease_key == "crm-reconcile"
        )
    )
    assert row.holder_token == owner.holder_token
    assert row.generation == 1
    assert row.expires_at is not None
    assert owner.release() is True


def test_service_does_not_enter_business_logic_while_lease_is_held(db):
    owner = acquire_canonical_sync_lease("crm-push")
    called = False

    def forbidden_post(_envelopes):
        nonlocal called
        called = True
        raise AssertionError("Remote CRM call must not run while the lease is busy.")

    try:
        with pytest.raises(CanonicalSyncBusy):
            push_canonical_to_crm(db, post_batch=forbidden_post)
    finally:
        owner.release()

    assert called is False
    assert db.scalar(select(func.count(CanonicalDeliveryRecord.id))) == 0


def test_service_failure_releases_lease_for_a_safe_retry(db):
    db.add(
        EnterpriseCanonicalRecord(
            record_id="LEASE-FAILURE-RECORD",
            domain="project",
            entity_type="project",
            external_key="platform:lease-failure",
            canonical_name="Lease failure test",
            project_id="PROJECT-LEASE-1",
            target_module="project-control",
            status="active",
            data_json="{}",
            provenance_json="{}",
        )
    )
    db.commit()

    def remote_failure(_envelopes):
        raise RuntimeError("synthetic remote failure")

    with pytest.raises(CanonicalBridgeError, match="synthetic remote failure"):
        push_canonical_to_crm(db, post_batch=remote_failure)

    retry_owner = acquire_canonical_sync_lease("crm-push")
    assert retry_owner.release() is True
    delivery = db.scalar(
        select(CanonicalDeliveryRecord).where(
            CanonicalDeliveryRecord.external_key == "canonical:LEASE-FAILURE-RECORD"
        )
    )
    assert delivery.status == "failed"


def test_busy_lease_maps_to_an_audited_http_conflict(logged_in_client, db, monkeypatch):
    def busy(_db):
        raise CanonicalSyncBusy("crm-push")

    monkeypatch.setattr(main_module, "push_canonical_to_crm", busy)
    response = logged_in_client.post("/imports/canonical/push-crm", follow_redirects=False)

    assert response.status_code == 409
    assert "már fut" in response.json()["detail"]
    audit_row = db.scalar(
        select(AuditLog).where(AuditLog.action == "canonical_sync.lease_busy")
    )
    assert audit_row is not None
    assert audit_row.entity_id == "crm-push"


def test_lost_lease_maps_to_an_audited_service_failure(logged_in_client, db, monkeypatch):
    def lost(_db):
        raise CanonicalSyncLeaseLost("crm-push")

    monkeypatch.setattr(main_module, "push_canonical_to_crm", lost)
    response = logged_in_client.post("/imports/canonical/push-crm", follow_redirects=False)

    assert response.status_code == 503
    audit_row = db.scalar(
        select(AuditLog).where(AuditLog.action == "canonical_sync.lease_lost")
    )
    assert audit_row is not None
    assert audit_row.entity_id == "crm-push"
