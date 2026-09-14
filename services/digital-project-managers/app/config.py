from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"

    database_url: str | None = None
    database_host: str = "dpm-postgres"
    database_port: int = 5432
    database_name: str = "imperial_dpm"
    database_user: str = "imperial_dpm"
    database_password_file: Path | None = Path("/run/secrets/dpm_db_password")

    redis_url: str = "redis://dpm-redis:6379/0"
    queue_enabled: bool = True

    platform_data_path: Path = Path("/data/platform.json")

    auth_mode: Literal["oidc", "test"] = "oidc"
    auth_issuer: str = "imperial-intelligence"
    auth_audience: str = "digital-project-managers"
    auth_jwks_url: str | None = None
    auth_hs256_secret: SecretStr | None = Field(default=None, repr=False)
    auth_hs256_secret_file: Path | None = Path("/run/secrets/dpm_auth_hs256_secret")

    external_writes_enabled: bool = False
    partner_control_base_url: str | None = None
    partner_control_token_file: Path | None = None
    tender_portal_base_url: str | None = None
    tender_portal_token_file: Path | None = None
    myimperial_base_url: str | None = None
    myimperial_token_file: Path | None = None
    email_service_base_url: str | None = None
    email_service_token_file: Path | None = None

    @model_validator(mode="after")
    def validate_test_auth(self) -> Settings:
        if self.auth_mode == "test" and self.app_env != "test":
            raise ValueError("AUTH_MODE=test is only allowed with APP_ENV=test")
        return self

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        password = self._read_required_secret(
            self.database_password_file,
            "DATABASE_PASSWORD_FILE",
        )
        return (
            "postgresql+psycopg://"
            f"{quote_plus(self.database_user)}:{quote_plus(password)}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )

    def resolved_auth_hs256_secret(self) -> str | None:
        if self.auth_hs256_secret is not None:
            return self.auth_hs256_secret.get_secret_value()
        if self.auth_hs256_secret_file and self.auth_hs256_secret_file.is_file():
            value = self.auth_hs256_secret_file.read_text(encoding="utf-8").strip()
            return value or None
        return None

    @staticmethod
    def _read_required_secret(path: Path | None, setting_name: str) -> str:
        if path is None or not path.is_file():
            raise RuntimeError(f"{setting_name} must reference a readable secret file")
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise RuntimeError(f"{setting_name} references an empty secret")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
