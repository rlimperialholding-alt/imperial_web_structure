from app.config import Settings


def test_production_validation_blocks_unsafe_defaults(monkeypatch):
    # The dataclass can be constructed explicitly for a deterministic validation test.
    unsafe = Settings(environment="production", database_url="sqlite:///x.db", session_secret="short", api_token="")
    errors = unsafe.validate()
    assert len(errors) == 4


def test_live_ai_routing_requires_provider_key_and_budget():
    unsafe = Settings(
        ai_external_calls_enabled=True,
        ai_monthly_budget_usd=0,
        ai_provider_api_key_file="",
    )
    errors = unsafe.validate()
    assert any("AI_MONTHLY_BUDGET_USD" in error for error in errors)
    assert any("AI_PROVIDER_API_KEY_FILE" in error for error in errors)


def test_anonymous_ui_redirects(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?return_to=/"
