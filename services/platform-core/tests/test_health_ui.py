from sqlalchemy import select

from app.models import ModuleRegistry, User


def test_health_and_readiness(client):
    assert client.get("/health").json()["version"] == "1.5.0"
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json()["status"] == "ready"


def test_login_and_main_pages(logged_in_client):
    for path in ["/", "/modules", "/projects", "/executive", "/exceptions", "/releases", "/pilots"]:
        response = logged_in_client.get(path)
        assert response.status_code == 200
        assert "Imperial" in response.text


def test_seeded_module_registry(db):
    modules = db.scalars(select(ModuleRegistry)).all()
    assert len(modules) == 47
    assert all(m.integration_status == "healthy" for m in modules)
    assert all(m.lifecycle_status == "test_ready" for m in modules)
    assert all(m.last_integration_test_status == "passed" for m in modules)
    assert any(m.module_key == "procurement" and m.version == "1.0.0" for m in modules)


def test_all_role_accounts_are_seeded_outside_production(db):
    users = db.scalars(select(User)).all()
    assert len(users) == 12
    assert {user.role for user in users} == {
        "owner", "managing-director", "marketing", "technical-prep", "sales",
        "finance", "project-manager", "designer", "subcontractor", "customer",
        "legal", "platform-admin",
    }
