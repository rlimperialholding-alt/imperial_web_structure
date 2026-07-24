from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("ENVIRONMENT", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/control_center.db")
    session_secret: str = os.getenv("SESSION_SECRET", "change-this-before-production")
    api_token: str = os.getenv("CONTROL_CENTER_API_TOKEN", "")
    internal_job_token: str = os.getenv("INTERNAL_JOB_TOKEN", "")
    require_https: bool = os.getenv("REQUIRE_HTTPS", "false").lower() == "true"
    allowed_hosts: tuple[str, ...] = tuple(
        h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if h.strip()
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.is_production:
            if self.session_secret in {"", "change-this-before-production"} or len(self.session_secret) < 32:
                errors.append("Production környezetben legalább 32 karakteres SESSION_SECRET kötelező.")
            if self.database_url.startswith("sqlite"):
                errors.append("Production környezetben PostgreSQL adatbázis kötelező.")
            if not self.api_token:
                errors.append("Production környezetben CONTROL_CENTER_API_TOKEN kötelező.")
        return errors


settings = Settings()
