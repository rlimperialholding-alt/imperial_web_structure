from app.config import Settings
from app.process_cards.domain import RealRole


def _role_tokens() -> dict[str, str]:
    return {role.value: (role.name.lower() + "-") * 6 for role in RealRole}


def test_production_accepts_complete_five_role_security_model() -> None:
    roles = _role_tokens()
    n8n = "n8n-service-token-" * 3
    settings = Settings(
        app_env="production",
        app_version="0.8.1",
        api_admin_token="admin-token-" * 4,
        human_role_tokens_json=roles,
        service_tokens_json={"n8n": n8n, "directus": "directus-service-token-" * 2},
        n8n_service_token=n8n,
        require_role_tokens=True,
        require_idempotency_keys=True,
        metrics_token="metrics-token-" * 4,
        trusted_hosts_json=["api.imperial.example"],
        docs_enabled=False,
        auto_create_db_schema=False,
        database_url="postgresql+psycopg://prod:strong-password@postgres:5432/imperial",
        directus_static_token="directus-static-token-" * 2,
        directus_webhook_secret="webhook-secret-" * 4,
        operational_catalog_file="config/operational-process-catalog-v1.0.json",
    )

    assert settings.validation_errors() == []


def test_production_rejects_missing_role_and_n8n_token_mismatch() -> None:
    roles = _role_tokens()
    roles.pop("Pénzügyes")
    settings = Settings(
        app_env="production",
        api_admin_token="admin-token-" * 4,
        human_role_tokens_json=roles,
        service_tokens_json={"n8n": "n8n-service-token-" * 3},
        n8n_service_token="different-token-" * 3,
        require_role_tokens=True,
        require_idempotency_keys=True,
        metrics_token="metrics-token-" * 4,
        trusted_hosts_json=["api.imperial.example"],
        docs_enabled=False,
        auto_create_db_schema=False,
        database_url="postgresql+psycopg://prod:strong-password@postgres:5432/imperial",
        directus_static_token="directus-static-token-" * 2,
        directus_webhook_secret="webhook-secret-" * 4,
        operational_catalog_file="config/operational-process-catalog-v1.0.json",
    )

    errors = settings.validation_errors()
    assert any("Pénzügyes" in item for item in errors)
    assert any("N8N_SERVICE_TOKEN" in item for item in errors)
