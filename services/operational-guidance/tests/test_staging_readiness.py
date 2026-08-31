from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.process_cards.adapters import GmailApprovalNotifier
from app.readiness import build_readiness_report


def test_staging_rejects_placeholder_configuration(tmp_path: Path) -> None:
    settings = Settings(
        app_env="staging",
        operational_catalog_file=str(Path("config/operational-process-catalog-v1.0.json")),
    )

    errors = settings.validation_errors()

    assert any("API_ADMIN_TOKEN" in item for item in errors)
    assert any("DIRECTUS_WEBHOOK_SECRET" in item for item in errors)
    assert any("AUTO_CREATE_DB_SCHEMA" in item for item in errors)
    assert any("DATABASE_URL" in item for item in errors)


def test_staging_accepts_hardened_core_configuration() -> None:
    settings = Settings(
        app_env="staging",
        api_admin_token="a" * 48,
        directus_webhook_secret="b" * 48,
        auto_create_db_schema=False,
        database_url="postgresql+psycopg://iip:strong-password@postgres:5432/imperial",
        directus_static_token="d" * 48,
        drive_publication_enabled=False,
        gmail_approval_enabled=False,
        operational_catalog_file="config/operational-process-catalog-v1.0.json",
        trusted_hosts_json=["staging.example.com"],
        metrics_token="m" * 48,
        require_idempotency_keys=True,
    )

    assert settings.validation_errors() == []


def test_gmail_approval_requires_drive_and_addresses() -> None:
    settings = Settings(
        gmail_approval_enabled=True,
        drive_publication_enabled=False,
        process_card_approver_email="invalid",
        process_card_gmail_delegated_user="",
    )

    errors = settings.validation_errors()

    assert any("DRIVE_PUBLICATION_ENABLED" in item for item in errors)
    assert any("PROCESS_CARD_APPROVER_EMAIL" in item for item in errors)
    assert any("PROCESS_CARD_GMAIL_DELEGATED_USER" in item for item in errors)


def test_gmail_approval_cannot_bypass_the_central_info_account_gate() -> None:
    settings = Settings(
        gmail_approval_enabled=True,
        drive_publication_enabled=True,
        process_card_approver_email="approver@imperialholding.hu",
        process_card_gmail_delegated_user=" INFO@ImperialHolding.hu ",
    )

    errors = settings.validation_errors()

    assert any("centrally gated info@imperialholding.hu" in item for item in errors)


def test_notifier_runtime_also_rejects_the_centrally_gated_info_account() -> None:
    notifier = GmailApprovalNotifier(
        service_account_file="unused.json",
        delegated_user="info@imperialholding.hu",
        approver_email="approver@imperialholding.hu",
    )

    with pytest.raises(RuntimeError, match="central account quota gate"):
        notifier.notify(
            process_key="PC-TEST",
            title="Test",
            version=1,
            role="owner",
            artifact_links={},
        )


def test_readiness_checks_database_catalog_and_runtime(tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        readiness_check_redis=False,
        process_card_runtime_root=str(tmp_path / "cards"),
        process_card_publish_root=str(tmp_path / "published"),
        checklist_runtime_root=str(tmp_path / "checklists"),
        operational_catalog_file="config/operational-process-catalog-v1.0.json",
    )
    engine = create_engine(settings.database_url)

    with Session(engine) as session:
        report = build_readiness_report(session, settings)

    assert report.ready is True
    assert report.checks["database"]["ok"] is True
    assert report.checks["operational_catalog"]["process_count"] == 99
    assert report.checks["runtime_storage"]["ok"] is True


def test_generic_replace_placeholders_are_rejected() -> None:
    settings = Settings(
        app_env="staging",
        api_admin_token="REPLACE_WITH_32_PLUS_CHARACTER_RANDOM_SECRET",
        directus_webhook_secret="REPLACE_WITH_32_PLUS_CHARACTER_RANDOM_SECRET",
        directus_static_token="REPLACE_DIRECTUS_STATIC_TOKEN",
        auto_create_db_schema=False,
        database_url="postgresql+psycopg://iip:REPLACE_DB_PASSWORD@postgres:5432/imperial",
    )

    errors = settings.validation_errors()

    assert any("API_ADMIN_TOKEN" in item for item in errors)
    assert any("DIRECTUS_WEBHOOK_SECRET" in item for item in errors)
    assert any("DIRECTUS_STATIC_TOKEN" in item for item in errors)
    assert any("DATABASE_URL" in item for item in errors)
