from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

import app.main as main_module
from app.models import AuditLog


def _login(client, role: str) -> None:
    response = client.post(
        "/login",
        data={"email": f"{role}@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_canonical_leadership_roles_use_registered_role_ids(client, monkeypatch):
    assert main_module._LEADERSHIP_ROLES == {
        "owner",
        "managing-director",
        "platform-admin",
    }
    _login(client, "platform-admin")

    monkeypatch.setattr(main_module, "run_all_pilots", lambda _db: None)
    monkeypatch.setattr(
        main_module,
        "sync_crm_canonical",
        lambda _db, *, actor: {
            "job_id": "CRM-SYNC-ROLE-1",
            "status": "committed",
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
        },
    )
    monkeypatch.setattr(
        main_module,
        "commit_records",
        lambda *_args, **_kwargs: SimpleNamespace(batch_id="BATCH-ROLE-1"),
    )
    monkeypatch.setattr(
        main_module,
        "rollback_batch",
        lambda *_args, **_kwargs: SimpleNamespace(batch_id="BATCH-ROLE-1"),
    )
    monkeypatch.setattr(main_module, "approve_campaign", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "queue_campaign", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "dispatch_batch", lambda *_args, **_kwargs: None)

    requests = (
        ("/pilots/run", {"scenario": "all"}),
        ("/imports/crm-sync", {}),
        ("/imports/JOB-ROLE-1/commit", {}),
        ("/imports/batches/BATCH-ROLE-1/rollback", {}),
        ("/tendermail/CAMPAIGN-ROLE-1/approve", {}),
        ("/tendermail/CAMPAIGN-ROLE-1/simulate", {}),
    )
    for path, data in requests:
        response = client.post(path, data=data, follow_redirects=False)
        assert response.status_code == 303, path


def test_non_leadership_role_cannot_start_canonical_sync(client, monkeypatch):
    _login(client, "finance")
    called = False

    def forbidden_call(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("A service must not run before role authorization.")

    monkeypatch.setattr(main_module, "sync_crm_canonical", forbidden_call)
    response = client.post("/imports/crm-sync", follow_redirects=False)

    assert response.status_code == 403
    assert called is False


def test_canonical_ui_actions_fail_closed_and_keep_audit(logged_in_client, db, monkeypatch):
    monkeypatch.setattr(
        main_module,
        "push_canonical_to_crm",
        lambda _db: {
            "local": 1,
            "pending": 1,
            "applied": 0,
            "conflicts": 1,
            "rejected": 0,
            "failed": 0,
        },
    )
    monkeypatch.setattr(
        main_module,
        "pull_itep_tasks_to_platform",
        lambda _db: {
            "source": 1,
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "conflicts": 1,
        },
    )
    monkeypatch.setattr(
        main_module,
        "reconcile_canonical_with_crm",
        lambda _db: {
            "run_id": "RECON-FAIL-CLOSED-1",
            "status": "attention_required",
            "conflicts": 0,
        },
    )
    monkeypatch.setattr(
        main_module,
        "push_platform_events_to_itep",
        lambda _db: {"source": 1, "applied": 0, "idempotent": 0, "failed": 1},
    )

    expected = (
        ("/imports/canonical/push-crm", 409, "canonical_push_crm"),
        ("/imports/canonical/pull-itep", 409, "canonical_pull_itep"),
        ("/imports/canonical/reconcile-crm", 409, "canonical_reconcile_crm"),
        ("/imports/canonical/push-itep", 502, "canonical_push_itep"),
    )
    for path, status_code, audit_action in expected:
        response = logged_in_client.post(path, follow_redirects=False)
        assert response.status_code == status_code, path
        assert db.scalar(select(AuditLog).where(AuditLog.action == audit_action)) is not None
