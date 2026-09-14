from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.roles import ROLE_DEFINITIONS, can_access_role
from app.seed import DEMO_PASSWORD

SEED_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "platform_demo_seed.json"
)
MODULES = {
    module["id"]: module
    for module in json.loads(SEED_PATH.read_text(encoding="utf-8"))["modules"]
}


def role_email(role_id: str) -> str:
    return (
        "owner@imperial.local"
        if role_id == "owner"
        else f"{role_id}@imperial.local"
    )


def login(client, role_id: str):
    response = client.post(
        "/login",
        data={
            "email": role_email(role_id),
            "password": DEMO_PASSWORD,
            "return_to": "/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


@pytest.mark.parametrize("role", ROLE_DEFINITIONS, ids=lambda role: role.id)
def test_every_role_can_only_execute_an_allowed_module_action(client, role):
    login(client, role.id)
    identity = client.get("/api/auth/session")
    assert identity.status_code == 200
    assert identity.json()["role"]["id"] == role.id

    allowed_module = next(
        MODULES[module_id]
        for module_id in role.module_access
        if module_id in MODULES and MODULES[module_id].get("actions")
    )
    allowed_action = allowed_module["actions"][0]
    response = client.post(
        "/api/demo/actions",
        json={
            "module_id": allowed_module["id"],
            "action_id": allowed_action["id"],
            "project_id": f"ROLE-{role.id}",
            "actor": "forged-client-actor@example.test",
            "idempotency_key": f"role-test-{role.id}",
            "payload": {"notes": "Automatikus szerepkörteszt"},
        },
    )
    assert response.status_code == 200
    assert response.json()["event"]["actor"] == role_email(role.id)

    denied_module = next((
        module
        for module_id, module in MODULES.items()
        if not can_access_role(role.id, module_id) and module.get("actions")
    ), None)
    if denied_module is None:
        assert role.id == "platform-admin"
        client.post("/logout")
        return
    assert client.get(f"/api/demo/modules/{denied_module['id']}").status_code == 403
    denied_action = denied_module["actions"][0]
    denied = client.post(
        "/api/demo/actions",
        json={
            "module_id": denied_module["id"],
            "action_id": denied_action["id"],
            "project_id": f"DENIED-{role.id}",
        },
    )
    assert denied.status_code == 403
    client.post("/logout")


@pytest.mark.parametrize(
    ("role_id", "allowed_path", "denied_path"),
    [
        ("owner", "/executive", "/imports"),
        # The managing director is a tender award decision-maker; Import Center
        # remains outside this role's operational data access.
        ("managing-director", "/tenders", "/imports"),
        ("marketing", "/experience", "/procurement/workbench"),
        ("technical-prep", "/projects", "/executive"),
        ("sales", "/commercial", "/imports"),
        ("finance", "/imports", "/operations"),
        ("project-manager", "/operations", "/executive"),
        ("designer", "/documents", "/executive"),
        ("subcontractor", "/field", "/procurement/workbench"),
        ("customer", "/experience", "/modules"),
        ("legal", "/commercial", "/procurement/workbench"),
        ("platform-admin", "/development-governance", None),
    ],
)
def test_native_screens_follow_role_permissions(
    client,
    role_id,
    allowed_path,
    denied_path,
):
    login(client, role_id)
    assert client.get(allowed_path).status_code == 200
    if denied_path:
        assert client.get(denied_path).status_code == 403
    client.post("/logout")


def test_anonymous_demo_api_is_rejected(client):
    assert client.get("/api/auth/session").status_code == 401
    assert client.get("/api/demo/state").status_code == 401
