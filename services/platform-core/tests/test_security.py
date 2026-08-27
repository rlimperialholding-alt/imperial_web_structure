from app.config import Settings
from app.seed import DEMO_PASSWORD


def test_production_validation_blocks_unsafe_defaults(monkeypatch):
    # The dataclass can be constructed explicitly for a deterministic validation test.
    unsafe = Settings(
        environment="production",
        database_url="sqlite:///x.db",
        session_secret="short",
        api_token="",
    )
    errors = unsafe.validate()
    assert len(errors) == 4


def test_production_disables_demo_runtime_by_default():
    production = Settings(environment="production")

    assert production.demo_runtime_enabled is False


def test_production_rejects_explicit_demo_runtime():
    production = Settings(
        environment="production",
        database_url="postgresql+psycopg://platform@postgres/platform",
        session_secret="s" * 32,
        api_token="api-token",
        require_https=True,
        demo_features_enabled=True,
    )

    assert any("DEMO_FEATURES_ENABLED" in error for error in production.validate())


def test_live_ai_routing_requires_provider_key_and_budget():
    unsafe = Settings(
        ai_external_calls_enabled=True,
        ai_monthly_budget_usd=0,
        ai_provider_api_key_file="",
    )
    errors = unsafe.validate()
    assert any("AI_MONTHLY_BUDGET_USD" in error for error in errors)
    assert any("AI_PROVIDER_API_KEY_FILE" in error for error in errors)


def test_external_publication_requires_separate_expert_review_secret():
    unsafe = Settings(
        environment="production",
        database_url="postgresql+psycopg://platform@postgres/platform",
        session_secret="s" * 32,
        api_token="api-token",
        internal_job_token="job-token",
        content_external_publishing_enabled=True,
        content_expert_review_secret="",
        content_marketing_review_secret="",
        content_copywriter_review_secret="",
        content_visual_review_secret="",
        content_campaign_package_secret="",
        imperial_release_hmac_key="",
    )

    errors = unsafe.validate()

    assert any("CONTENT_EXPERT_REVIEW_SECRET" in error for error in errors)
    assert any("CONTENT_MARKETING_REVIEW_SECRET" in error for error in errors)
    assert any("CONTENT_COPYWRITER_REVIEW_SECRET" in error for error in errors)
    assert any("CONTENT_VISUAL_REVIEW_SECRET" in error for error in errors)
    assert any("CONTENT_CAMPAIGN_PACKAGE_SECRET" in error for error in errors)
    assert any("IMPERIAL_RELEASE_HMAC_KEY" in error for error in errors)


def test_external_publication_rejects_shared_gate_secrets():
    shared = "x" * 32
    unsafe = Settings(
        environment="production",
        database_url="postgresql+psycopg://platform@postgres/platform",
        session_secret="s" * 32,
        api_token="api-token",
        internal_job_token="job-token",
        content_external_publishing_enabled=True,
        content_expert_review_secret=shared,
        content_marketing_review_secret=shared,
        content_copywriter_review_secret=shared,
        content_visual_review_secret=shared,
        content_campaign_package_secret=shared,
        imperial_release_hmac_key=shared,
    )

    assert any("különálló secretet" in error for error in unsafe.validate())


def test_house_design_order_intake_requires_adapter_kill_switch():
    unsafe = Settings(
        house_design_order_intake_enabled=True,
        house_designer_adapters_enabled=False,
    )

    assert any(
        "HOUSE_DESIGN_ORDER_INTAKE_ENABLED requires HOUSE_DESIGNER_ADAPTERS_ENABLED" in error
        for error in unsafe.validate()
    )


def test_house_designer_site_encryption_requires_a_distinct_key():
    shared = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    unsafe = Settings(
        market_evidence_kek=shared,
        house_designer_site_kek=shared,
    )

    assert any(
        "House Designer és Market titkosítási kulcsa nem lehet azonos" in error
        for error in unsafe.validate()
    )


def test_crm_read_connection_requires_a_paired_long_token():
    missing = Settings(crm_read_base_url="https://crm.example.invalid", crm_read_token="")
    short = Settings(
        crm_read_base_url="https://crm.example.invalid",
        crm_read_token="too-short",
    )

    assert any("CRM_READ_BASE_URL" in error for error in missing.validate())
    assert any("CRM_READ_TOKEN legalább 32" in error for error in short.validate())


def test_crm_read_write_and_sites_credentials_must_be_separate():
    shared = "x" * 32
    unsafe = Settings(
        crm_read_base_url="https://crm.example.invalid",
        crm_read_token=shared,
        crm_write_base_url="https://crm.example.invalid",
        crm_write_token=shared,
        crm_sites_bypass_token=shared,
    )

    errors = unsafe.validate()
    assert any("olvasási és írási tokenje nem lehet azonos" in error for error in errors)
    assert any("Sites hozzáférési tokenje" in error for error in errors)


def test_anonymous_ui_redirects(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?return_to=/"


def test_session_authenticated_writes_require_same_origin(client):
    login = client.post(
        "/login",
        data={"email": "platform-admin@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303

    foreign = client.post(
        "/logout",
        headers={"Origin": "https://attacker.example"},
        follow_redirects=False,
    )
    assert foreign.status_code == 403
    assert "azonos eredetű" in foreign.text

    missing = client.post("/logout", headers={"Origin": ""}, follow_redirects=False)
    assert missing.status_code == 403

    same_origin = client.post(
        "/logout",
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert same_origin.status_code == 303
