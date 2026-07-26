from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus


def _database_url() -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    host = os.getenv("DATABASE_HOST")
    if not host:
        return "sqlite:///./data/control_center.db"
    password_file = os.getenv("DATABASE_PASSWORD_FILE", "")
    if not password_file:
        return ""
    password = Path(password_file).read_text(encoding="utf-8").strip()
    user = quote_plus(os.getenv("DATABASE_USER", "imperial_platform"))
    database = quote_plus(os.getenv("DATABASE_NAME", "imperial_platform"))
    port = os.getenv("DATABASE_PORT", "5432")
    return (
        f"postgresql+psycopg://{user}:{quote_plus(password)}"
        f"@{host}:{port}/{database}"
    )


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("ENVIRONMENT", "development")
    database_url: str = _database_url()
    session_secret: str = os.getenv("SESSION_SECRET", "change-this-before-production")
    api_token: str = os.getenv("CONTROL_CENTER_API_TOKEN", "")
    internal_job_token: str = os.getenv("INTERNAL_JOB_TOKEN", "")
    content_external_publishing_enabled: bool = os.getenv(
        "CONTENT_EXTERNAL_PUBLISHING_ENABLED", "false"
    ).lower() == "true"
    require_https: bool = os.getenv("REQUIRE_HTTPS", "false").lower() == "true"
    allowed_hosts: tuple[str, ...] = tuple(
        h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if h.strip()
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.database_url:
            errors.append("DATABASE_URL vagy DATABASE_PASSWORD_FILE kötelező.")
        if self.is_production:
            if self.session_secret in {"", "change-this-before-production"} or len(self.session_secret) < 32:
                errors.append("Production környezetben legalább 32 karakteres SESSION_SECRET kötelező.")
            if self.database_url.startswith("sqlite"):
                errors.append("Production környezetben PostgreSQL adatbázis kötelező.")
            if not self.api_token:
                errors.append("Production környezetben CONTROL_CENTER_API_TOKEN kötelező.")
            if self.content_external_publishing_enabled and not self.internal_job_token:
                errors.append("Külső tartalompublikáláshoz INTERNAL_JOB_TOKEN kötelező.")
        return errors


settings = Settings()
