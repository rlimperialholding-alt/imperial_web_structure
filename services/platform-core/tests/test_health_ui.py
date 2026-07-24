from app.models import ModuleRegistry
from sqlalchemy import select


def test_health_and_readiness(client):
    assert client.get("/health").json()["version"] == "1.5.0"
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json()["status"] == "ready"


def test_login_and_main_pages(logged_in_client):
    for path in ["/", "/modules", "/projects", "/imports", "/experience", "/tendermail", "/commercial", "/development-governance", "/exceptions", "/releases", "/pilots"]:
        response = logged_in_client.get(path)
        assert response.status_code == 200
        assert "Imperial" in response.text


def test_seeded_module_registry(db):
    modules = db.scalars(select(ModuleRegistry)).all()
    assert len(modules) >= 15
    assert any(m.module_key == "procurement" and m.version == "1.0.0" for m in modules)
