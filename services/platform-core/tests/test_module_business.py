from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.models import AuditLog, EventRecord, ModuleBusinessRecord, OutboxMessage
from app.services.module_business import (
    BUSINESS_PROFILES,
    MODULE_WORKFLOW_FAMILY,
    module_profile,
)


def test_business_profiles_cover_all_49_registered_modules():
    seed_path = Path(__file__).resolve().parents[1] / "data" / "platform_demo_seed.json"
    modules = json.loads(seed_path.read_text(encoding="utf-8"))["modules"]
    module_keys = {module["id"] for module in modules}

    assert len(module_keys) == 49
    assert set(BUSINESS_PROFILES) == module_keys
    assert set(MODULE_WORKFLOW_FAMILY) == module_keys
    for module_key in module_keys:
        profile = module_profile(module_key)
        assert profile["entity_label"]
        assert len(profile["fields"]) == 3
        assert profile["actions"]
        assert "completed" in profile["statuses"]


def test_demo_action_consumers_are_registered_modules():
    seed_path = Path(__file__).resolve().parents[1] / "data" / "platform_demo_seed.json"
    modules = json.loads(seed_path.read_text(encoding="utf-8"))["modules"]
    module_keys = {module["id"] for module in modules}

    for module in modules:
        for action in module["actions"]:
            unknown = set(action["consumers"]) - module_keys
            assert not unknown, f"{module['id']}.{action['id']}: {sorted(unknown)}"


def test_every_module_has_role_accessible_business_workbench(logged_in_client):
    for module_key in BUSINESS_PROFILES:
        response = logged_in_client.get(f"/workbench/{module_key}")
        assert response.status_code == 200, module_key
        if module_key == "imperial-care":
            assert "KIZÁRÓLAGOS ÜGYFÉL-HIBABEJELENTÉSI CSATORNA" in response.text
            continue
        assert "Adatfelvitel" in response.text


def test_record_crud_comment_approval_and_transition(logged_in_client, db):
    create_response = logged_in_client.post(
        "/workbench/crm/records",
        data={
            "title": "Teszt ügyfélfolyamat",
            "record_type": "Ügyfél",
            "description": "Teljes belső üzleti folyamat ellenőrzése.",
            "status": "new",
            "project_id": "PRJ-MODULE-001",
            "customer_reference": "CUSTOMER-001",
            "assignee": "sales@example.invalid",
            "priority": "high",
            "amount_huf": "1250000",
            "data_contact": "Teszt kapcsolattartó",
            "data_source": "Teszt forrás",
            "data_next_step": "Minősítés",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 303
    record_id = create_response.headers["location"].rsplit("/", maxsplit=1)[-1]

    detail_response = logged_in_client.get(create_response.headers["location"])
    assert detail_response.status_code == 200
    assert "Teszt ügyfélfolyamat" in detail_response.text

    comment_response = logged_in_client.post(
        f"/workbench/crm/records/{record_id}/comments",
        data={"body": "Projektmenedzseri egyeztetés szükséges."},
        follow_redirects=False,
    )
    assert comment_response.status_code == 303

    approval_response = logged_in_client.post(
        f"/workbench/crm/records/{record_id}/approvals",
        data={
            "stage": "sales_approval",
            "decision": "approved",
            "note": "Minősített lehetőség.",
        },
        follow_redirects=False,
    )
    assert approval_response.status_code == 303

    transition_response = logged_in_client.post(
        f"/workbench/crm/records/{record_id}/actions/qualify_lead",
        data={"note": "Lead minősítve."},
        follow_redirects=False,
    )
    assert transition_response.status_code == 303

    db.expire_all()
    record = db.scalar(
        select(ModuleBusinessRecord).where(ModuleBusinessRecord.record_id == record_id)
    )
    assert record is not None
    assert record.status == "qualified"
    assert record.version == 2
    assert len(record.comments) == 1
    assert len(record.approvals) == 1
    assert db.scalar(select(EventRecord).where(EventRecord.object_id == record_id)) is not None
    assert db.scalar(select(OutboxMessage).where(OutboxMessage.source_event_id.is_not(None)))
    assert (
        db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == record_id,
                AuditLog.action == "module_business_transition:qualify_lead",
            )
        )
        is not None
    )


def test_module_business_api_round_trip(client):
    created = client.post(
        "/api/modules/finance-intelligence/records",
        json={
            "title": "Likviditási előrejelzés",
            "record_type": "Cash-flow",
            "project_id": "PRJ-FIN-001",
            "amount_huf": "5000000",
            "data": {"period": "2026 Q3", "scenario": "base"},
        },
    )
    assert created.status_code == 200
    record_id = created.json()["record_id"]

    blocked_status_edit = client.patch(
        f"/api/modules/finance-intelligence/records/{record_id}",
        json={"priority": "critical", "status": "in_review"},
    )
    assert blocked_status_edit.status_code == 400

    updated = client.patch(
        f"/api/modules/finance-intelligence/records/{record_id}",
        json={"priority": "critical"},
    )
    assert updated.status_code == 200
    assert updated.json()["priority"] == "critical"

    submitted = client.post(
        f"/api/modules/finance-intelligence/records/{record_id}/transitions",
        json={"action_id": "submit", "note": "Ellenőrzésre kész."},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "validated"

    blocked_without_approval = client.post(
        f"/api/modules/finance-intelligence/records/{record_id}/transitions",
        json={"action_id": "approve_budget", "note": "Keret elfogadva."},
    )
    assert blocked_without_approval.status_code == 400

    approval = client.post(
        f"/api/modules/finance-intelligence/records/{record_id}/approvals",
        json={"stage": "finance_approval", "decision": "approved", "note": "Pénzügyi kontroll."},
    )
    assert approval.status_code == 200

    transitioned = client.post(
        f"/api/modules/finance-intelligence/records/{record_id}/transitions",
        json={"action_id": "approve_budget", "note": "Keret elfogadva."},
    )
    assert transitioned.status_code == 200
    assert transitioned.json()["status"] == "approved"

    listed = client.get("/api/modules/finance-intelligence/records")
    assert listed.status_code == 200
    assert [item["record_id"] for item in listed.json()] == [record_id]


def test_sales_role_cannot_open_finance_workbench(client):
    login = client.post(
        "/login",
        data={"email": "sales@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert client.get("/workbench/crm").status_code == 200
    assert client.get("/workbench/finance-intelligence").status_code == 403
