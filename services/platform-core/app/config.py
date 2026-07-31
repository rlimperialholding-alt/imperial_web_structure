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
    return f"postgresql+psycopg://{user}:{quote_plus(password)}@{host}:{port}/{database}"


def _secret_value(name: str) -> str:
    value = os.getenv(name, "")
    if value:
        return value
    secret_file = os.getenv(f"{name}_FILE", "")
    if not secret_file:
        return ""
    return Path(secret_file).read_text(encoding="utf-8").strip()


def _optional_bool(name: str) -> bool | None:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return None
    return value == "true"


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("ENVIRONMENT", "development")
    database_url: str = _database_url()
    session_secret: str = os.getenv("SESSION_SECRET", "change-this-before-production")
    api_token: str = os.getenv("CONTROL_CENTER_API_TOKEN", "")
    internal_job_token: str = os.getenv("INTERNAL_JOB_TOKEN", "")
    itep_api_base_url: str = os.getenv("ITEP_API_BASE_URL", "")
    itep_identity_shared_secret: str = _secret_value(
        "ITEP_IDENTITY_SHARED_SECRET"
    )
    content_expert_review_secret: str = _secret_value("CONTENT_EXPERT_REVIEW_SECRET")
    content_expert_review_key_id: str = os.getenv(
        "CONTENT_EXPERT_REVIEW_KEY_ID",
        "content-expert-review-v1",
    )
    content_marketing_review_secret: str = _secret_value("CONTENT_MARKETING_REVIEW_SECRET")
    content_marketing_review_key_id: str = os.getenv(
        "CONTENT_MARKETING_REVIEW_KEY_ID",
        "content-marketing-review-v1",
    )
    content_copywriter_review_secret: str = _secret_value("CONTENT_COPYWRITER_REVIEW_SECRET")
    content_copywriter_review_key_id: str = os.getenv(
        "CONTENT_COPYWRITER_REVIEW_KEY_ID",
        "content-copywriter-review-v1",
    )
    content_visual_review_secret: str = _secret_value("CONTENT_VISUAL_REVIEW_SECRET")
    content_visual_review_key_id: str = os.getenv(
        "CONTENT_VISUAL_REVIEW_KEY_ID",
        "content-visual-review-v1",
    )
    content_campaign_package_secret: str = _secret_value("CONTENT_CAMPAIGN_PACKAGE_SECRET")
    content_campaign_package_key_id: str = os.getenv(
        "CONTENT_CAMPAIGN_PACKAGE_KEY_ID",
        "content-campaign-package-v1",
    )
    imperial_release_hmac_key: str = _secret_value("IMPERIAL_RELEASE_HMAC_KEY")
    content_external_publishing_enabled: bool = (
        os.getenv("CONTENT_EXTERNAL_PUBLISHING_ENABLED", "false").lower() == "true"
    )
    require_https: bool = os.getenv("REQUIRE_HTTPS", "false").lower() == "true"
    demo_features_enabled: bool | None = _optional_bool("DEMO_FEATURES_ENABLED")
    ai_external_calls_enabled: bool = os.getenv(
        "AI_EXTERNAL_CALLS_ENABLED", "false"
    ).lower() == "true"
    ai_routing_provider: str = os.getenv("AI_ROUTING_PROVIDER", "openrouter")
    ai_routine_model: str = os.getenv(
        "AI_ROUTINE_MODEL", "qwen/qwen3-30b-a3b-instruct-2507"
    )
    ai_reasoning_model: str = os.getenv(
        "AI_REASONING_MODEL", "openai/gpt-5-mini"
    )
    ai_monthly_budget_usd: float = float(os.getenv("AI_MONTHLY_BUDGET_USD", "0"))
    ai_provider_api_key_file: str = os.getenv("AI_PROVIDER_API_KEY_FILE", "")
    allowed_hosts: tuple[str, ...] = tuple(
        h.strip()
        for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
        if h.strip()
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def demo_runtime_enabled(self) -> bool:
        if self.demo_features_enabled is not None:
            return self.demo_features_enabled
        return not self.is_production

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.database_url:
            errors.append("DATABASE_URL vagy DATABASE_PASSWORD_FILE kötelező.")
        if self.is_production:
            if (
                self.session_secret in {"", "change-this-before-production"}
                or len(self.session_secret) < 32
            ):
                errors.append(
                    "Production környezetben legalább 32 karakteres SESSION_SECRET kötelező."
                )
            if self.database_url.startswith("sqlite"):
                errors.append("Production környezetben PostgreSQL adatbázis kötelező.")
            if not self.api_token:
                errors.append("Production környezetben CONTROL_CENTER_API_TOKEN kötelező.")
            if not self.require_https:
                errors.append("Production környezetben REQUIRE_HTTPS=true kötelező.")
            if self.demo_runtime_enabled:
                errors.append(
                    "Production environment must not enable DEMO_FEATURES_ENABLED."
                )
            if "*" in self.allowed_hosts:
                errors.append("Production környezetben az ALLOWED_HOSTS nem tartalmazhat helyettesítő karaktert.")
            if self.content_external_publishing_enabled and not self.internal_job_token:
                errors.append("Külső tartalompublikáláshoz INTERNAL_JOB_TOKEN kötelező.")
            if (
                self.content_external_publishing_enabled
                and len(self.content_expert_review_secret) < 32
            ):
                errors.append(
                    "Külső tartalompublikáláshoz legalább 32 karakteres "
                    "CONTENT_EXPERT_REVIEW_SECRET vagy CONTENT_EXPERT_REVIEW_SECRET_FILE kötelező."
                )
            mandatory_gate_secrets = {
                "CONTENT_MARKETING_REVIEW_SECRET": self.content_marketing_review_secret,
                "CONTENT_COPYWRITER_REVIEW_SECRET": self.content_copywriter_review_secret,
                "CONTENT_VISUAL_REVIEW_SECRET": self.content_visual_review_secret,
                "CONTENT_CAMPAIGN_PACKAGE_SECRET": self.content_campaign_package_secret,
                "IMPERIAL_RELEASE_HMAC_KEY": self.imperial_release_hmac_key,
            }
            if self.content_external_publishing_enabled:
                for name, secret in mandatory_gate_secrets.items():
                    if len(secret) < 32:
                        errors.append(
                            "Külső tartalompublikáláshoz legalább 32 karakteres "
                            f"{name} vagy {name}_FILE kötelező."
                        )
                configured = [
                    self.content_expert_review_secret,
                    *mandatory_gate_secrets.values(),
                ]
                if all(len(secret) >= 32 for secret in configured) and len(set(configured)) != 6:
                    errors.append(
                        "A nyelvi, marketing-, copywriter-, vizuális, kampánycsomag- és "
                        "release-kapuknak hat különálló secretet kell használniuk."
                    )
        if bool(self.itep_api_base_url) != bool(self.itep_identity_shared_secret):
            errors.append(
                "Az ITEP_API_BASE_URL és az ITEP_IDENTITY_SHARED_SECRET együtt kötelező."
            )
        if self.itep_identity_shared_secret and len(self.itep_identity_shared_secret) < 32:
            errors.append(
                "Az ITEP_IDENTITY_SHARED_SECRET legalább 32 karakteres legyen."
            )
        if self.ai_external_calls_enabled:
            if self.ai_routing_provider not in {"openrouter", "openai"}:
                errors.append("Az AI_ROUTING_PROVIDER csak openrouter vagy openai lehet.")
            if not self.ai_routine_model or not self.ai_reasoning_model:
                errors.append("Az AI-modellútvonalak nem lehetnek üresek.")
            if self.ai_monthly_budget_usd <= 0:
                errors.append("Élő AI-hívásokhoz pozitív AI_MONTHLY_BUDGET_USD kötelező.")
            key_path = Path(self.ai_provider_api_key_file)
            if not self.ai_provider_api_key_file or not key_path.is_file():
                errors.append("Élő AI-hívásokhoz olvasható AI_PROVIDER_API_KEY_FILE kötelező.")
        return errors


settings = Settings()
