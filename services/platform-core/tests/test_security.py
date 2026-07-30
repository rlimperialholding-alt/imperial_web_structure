from app.config import Settings


def test_production_validation_blocks_unsafe_defaults(monkeypatch):
    # The dataclass can be constructed explicitly for a deterministic validation test.
    unsafe = Settings(
        environment="production",
        database_url="sqlite:///x.db",
        session_secret="short",
        api_token="",
    )
    errors = unsafe.validate()
    assert len(errors) == 3


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
    )

    errors = unsafe.validate()

    assert any("CONTENT_EXPERT_REVIEW_SECRET" in error for error in errors)
    assert any("CONTENT_MARKETING_REVIEW_SECRET" in error for error in errors)
    assert any("CONTENT_COPYWRITER_REVIEW_SECRET" in error for error in errors)
    assert any("CONTENT_VISUAL_REVIEW_SECRET" in error for error in errors)


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
    )

    assert any("különálló secretet" in error for error in unsafe.validate())


def test_anonymous_ui_redirects(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
