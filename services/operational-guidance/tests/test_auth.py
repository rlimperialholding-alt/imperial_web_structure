import pytest
from fastapi import HTTPException

from app.auth import authenticate_token, ensure_role_access
from app.config import Settings
from app.process_cards.domain import RealRole


def _settings() -> Settings:
    return Settings(
        api_admin_token="a" * 40,
        human_role_tokens_json={role.value: role.name.lower() * 8 for role in RealRole},
        service_tokens_json={"n8n": "s" * 40},
    )


def test_authenticates_all_five_real_roles() -> None:
    settings = _settings()
    for role, token in settings.human_role_tokens().items():
        actor = authenticate_token(token, settings)
        assert actor is not None
        assert actor.kind == "human"
        assert actor.role == role


def test_service_and_legacy_admin_are_not_human_roles() -> None:
    settings = _settings()
    service = authenticate_token("s" * 40, settings)
    admin = authenticate_token("", settings, legacy_admin_token="a" * 40)
    assert service is not None and service.is_service and service.role is None
    assert admin is not None and admin.is_service and admin.role is None


def test_role_access_allows_manager_and_assigned_role_only() -> None:
    settings = _settings()
    sales = authenticate_token(settings.human_role_tokens()[RealRole.ERTEKESITO], settings)
    manager = authenticate_token(settings.human_role_tokens()[RealRole.UGYVEZETO], settings)
    marketing = authenticate_token(settings.human_role_tokens()[RealRole.MARKETINGES], settings)
    assert sales and manager and marketing
    ensure_role_access(sales, RealRole.ERTEKESITO)
    ensure_role_access(manager, RealRole.ERTEKESITO)
    with pytest.raises(HTTPException) as exc:
        ensure_role_access(marketing, RealRole.ERTEKESITO)
    assert exc.value.status_code == 403


def test_bearer_dependency_and_manager_only(monkeypatch) -> None:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    import app.auth as auth_module

    settings = _settings()
    monkeypatch.setattr(auth_module, "get_settings", lambda: settings)
    app = FastAPI()

    @app.get("/who")
    def who(actor=Depends(auth_module.require_actor)):
        return {"subject": actor.subject, "role": actor.role.value if actor.role else None}

    @app.post("/approve")
    def approve(actor=Depends(auth_module.require_manager)):
        return {"approved_by": actor.subject}

    client = TestClient(app)
    assert client.get("/who").status_code == 401
    sales_token = settings.human_role_tokens()[RealRole.ERTEKESITO]
    manager_token = settings.human_role_tokens()[RealRole.UGYVEZETO]
    who_response = client.get("/who", headers={"Authorization": f"Bearer {sales_token}"})
    assert who_response.status_code == 200
    assert who_response.json()["role"] == "Értékesítő"
    assert client.post("/approve", headers={"Authorization": f"Bearer {sales_token}"}).status_code == 403
    assert client.post("/approve", headers={"Authorization": f"Bearer {manager_token}"}).status_code == 200
