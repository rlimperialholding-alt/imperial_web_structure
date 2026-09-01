from __future__ import annotations

from app.main import dpm_gateway
from app.services.dpm_gateway import ALL_SCOPES, DpmIdentity, DpmUserContext


def admin_context() -> DpmUserContext:
    return DpmUserContext(
        identity=DpmIdentity(
            subject="platform-admin@imperial.local",
            role="platform-admin",
            scopes=ALL_SCOPES,
            project_ids=frozenset(),
        ),
        agent_ids=frozenset(),
        admin=True,
    )


def test_dpm_workspace_renders_role_protected_operator_screen(
    logged_in_client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(dpm_gateway, "user_context", lambda **kwargs: admin_context())

    def fake_request(method, path, identity, **kwargs):
        if path.endswith("/agents"):
            return [
                {
                    "id": "11111111-1111-4111-8111-111111111101",
                    "name": "Digitális Kálmán",
                    "human_partner_name": "Kálmán",
                    "human_manager_ref": None,
                    "authority_profile": "standard-r0-r7",
                    "mode": "limited-autonomy",
                    "status": "active",
                }
            ]
        if (
            path.endswith("/assignments")
            or path.endswith("/approvals")
            or path.endswith("/workqueue")
        ):
            return []
        raise AssertionError(path)

    monkeypatch.setattr(dpm_gateway, "request", fake_request)
    response = logged_in_client.get("/digital-project-managers")
    assert response.status_code == 200
    assert "Digital Project Managers" in response.text
    assert "Digitális PM ↔ humán PM" in response.text
    assert "R0–R7" in response.text


def test_dpm_manager_link_is_forwarded_with_auditable_platform_identity(
    logged_in_client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(dpm_gateway, "user_context", lambda **kwargs: admin_context())
    calls = []

    def fake_request(method, path, identity, **kwargs):
        calls.append((method, path, identity, kwargs))
        return {"id": path.rsplit("/", 1)[-1]}

    monkeypatch.setattr(dpm_gateway, "request", fake_request)
    agent_id = "11111111-1111-4111-8111-111111111101"
    response = logged_in_client.post(
        f"/digital-project-managers/agents/{agent_id}/link",
        data={"human_manager_ref": "project-manager@imperial.local"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    method, path, identity, kwargs = calls[0]
    assert method == "PATCH"
    assert path == f"/api/v1/agents/{agent_id}"
    assert identity.subject == "platform-admin@imperial.local"
    assert kwargs["payload"] == {"human_manager_ref": "project-manager@imperial.local"}


def test_dpm_assignment_close_uses_audited_service_identity(
    logged_in_client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(dpm_gateway, "user_context", lambda **kwargs: admin_context())
    calls = []

    def fake_request(method, path, identity, **kwargs):
        calls.append((method, path, identity, kwargs))
        return {"id": path.rsplit("/", 1)[-1], "valid_to": "2026-08-02T18:00:00Z"}

    monkeypatch.setattr(dpm_gateway, "request", fake_request)
    assignment_id = "22222222-2222-4222-8222-222222222222"
    response = logged_in_client.post(
        f"/digital-project-managers/assignments/{assignment_id}/close",
        data={
            "agent_id": "11111111-1111-4111-8111-111111111101",
            "project_id": "P-5001",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    method, path, identity, kwargs = calls[0]
    assert method == "DELETE"
    assert path == f"/api/v1/assignments/{assignment_id}"
    assert identity.subject == "platform-admin@imperial.local"
    assert kwargs == {}
