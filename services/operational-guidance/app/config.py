from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.process_cards.domain import RealRole

_PLACEHOLDER_VALUES = {
    "change-me",
    "change-this-long-random-token",
    "change-directus-webhook-secret",
    "replace-this-directus-key",
    "replace-this-directus-secret",
    "replace-this-n8n-encryption-key",
    "change-this-password",
    "miniosecret",
}


def _is_placeholder(value: str) -> bool:
    normalized = value.strip()
    upper = normalized.upper()
    return (
        not normalized
        or normalized in _PLACEHOLDER_VALUES
        or upper.startswith(("REPLACE", "CHANGE_", "CHANGE-", "YOUR_", "YOUR-", "TODO"))
        or "REPLACE_" in upper
    )


def _secret_value(value: SecretStr | str) -> str:
    return value.get_secret_value().strip() if isinstance(value, SecretStr) else str(value).strip()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "Imperial Intelligence Integration Hub"
    app_version: str = "0.8.1"
    api_prefix: str = "/api/v1"
    api_admin_token: SecretStr = SecretStr("change-me")
    human_role_tokens_json: dict[str, SecretStr] = Field(default_factory=dict)
    service_tokens_json: dict[str, SecretStr] = Field(default_factory=dict)
    n8n_service_token: SecretStr = SecretStr("")
    require_role_tokens: bool = False
    require_idempotency_keys: bool = False
    metrics_enabled: bool = True
    metrics_token: SecretStr = SecretStr("")
    audit_log_enabled: bool = True
    trusted_hosts_json: list[str] = Field(default_factory=lambda: ["*"])
    cors_origins_json: list[str] = Field(default_factory=list)
    docs_enabled: bool = True
    max_request_body_bytes: int = 2_000_000

    database_url: str = "postgresql+psycopg://imperial:imperial@localhost:5432/imperial"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"
    auto_create_db_schema: bool = True
    startup_validate_config: bool = True
    readiness_check_redis: bool = True

    operational_guidance_enabled: bool = True
    drive_publication_enabled: bool = False
    gmail_approval_enabled: bool = False

    google_service_account_file: str = "/run/secrets/google-service-account.json"
    process_card_runtime_root: str = "runtime/process_cards"
    process_card_publish_root: str = "runtime/published_process_cards"
    checklist_runtime_root: str = "runtime/checklists"
    operational_catalog_file: str = "config/operational-process-catalog-v1.0.json"
    process_catalog_collection: str = "process_catalog"
    checklist_template_collection: str = "checklist_templates"
    checklist_instance_collection: str = "checklist_instances"
    process_card_collection: str = "process_card_versions"
    process_card_drive_folder_id: str = ""
    process_card_approver_email: str = ""
    process_card_gmail_delegated_user: str = ""
    ga4_properties_json: list[dict[str, str]] = Field(default_factory=list)
    search_console_sites_json: list[dict[str, str]] = Field(default_factory=list)

    google_oauth_client_id: str = ""
    google_oauth_client_secret: SecretStr = SecretStr("")
    google_oauth_refresh_token: SecretStr = SecretStr("")
    gbp_locations_json: list[dict[str, str]] = Field(default_factory=list)

    ingatlan_base_url: str = "https://apitest.ingatlan.com/v1"
    ingatlan_username: str = ""
    ingatlan_password: SecretStr = SecretStr("")

    directus_url: str = "http://localhost:8055"
    directus_static_token: SecretStr = SecretStr("")
    directus_webhook_secret: SecretStr = SecretStr("change-me")
    directus_content_collection: str = "content_items"
    directus_website_collection: str = "websites"

    brand_registry_file: str = "config/brand-registry.json"
    brand_registry_json: dict[str, Any] = Field(default_factory=dict)
    website_targets_file: str = "config/website-targets.json"
    website_targets_json: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @field_validator(
        "ga4_properties_json",
        "search_console_sites_json",
        "gbp_locations_json",
        "trusted_hosts_json",
        "cors_origins_json",
        "brand_registry_json",
        "website_targets_json",
        "human_role_tokens_json",
        "service_tokens_json",
        mode="before",
    )
    @classmethod
    def parse_json_env(cls, value: Any, info: ValidationInfo) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if value:
                return json.loads(value)
            if info.field_name in {
                "brand_registry_json",
                "website_targets_json",
                "human_role_tokens_json",
                "service_tokens_json",
            }:
                return {}
            return []
        return value

    @property
    def is_development_like(self) -> bool:
        return self.app_env in {"development", "test"}

    def resolved_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else Path.cwd() / path

    def runtime_directories(self) -> list[Path]:
        return [
            self.resolved_path(self.process_card_runtime_root),
            self.resolved_path(self.process_card_publish_root),
            self.resolved_path(self.checklist_runtime_root),
        ]

    def human_role_tokens(self) -> dict[RealRole, str]:
        resolved: dict[RealRole, str] = {}
        for raw_role, raw_token in self.human_role_tokens_json.items():
            try:
                role = RealRole(raw_role)
            except ValueError:
                continue
            resolved[role] = _secret_value(raw_token)
        return resolved

    def service_tokens(self) -> dict[str, str]:
        return {
            str(name).strip(): _secret_value(token)
            for name, token in self.service_tokens_json.items()
            if str(name).strip()
        }

    def validation_errors(self) -> list[str]:
        errors: list[str] = []

        if self.max_request_body_bytes < 16_384:
            errors.append("MAX_REQUEST_BODY_BYTES must be at least 16384")

        if self.app_env in {"staging", "production"}:
            admin_token = self.api_admin_token.get_secret_value().strip()
            webhook_secret = self.directus_webhook_secret.get_secret_value().strip()
            if len(admin_token) < 32 or _is_placeholder(admin_token):
                errors.append("API_ADMIN_TOKEN must be a non-placeholder secret of at least 32 characters")
            if len(webhook_secret) < 32 or _is_placeholder(webhook_secret):
                errors.append(
                    "DIRECTUS_WEBHOOK_SECRET must be a non-placeholder secret of at least 32 characters"
                )
            if self.auto_create_db_schema:
                errors.append("AUTO_CREATE_DB_SCHEMA must be false in staging and production")
            if "imperial:imperial@" in self.database_url or _is_placeholder(self.database_url):
                errors.append("DATABASE_URL must not use default or placeholder credentials")
            directus_token = self.directus_static_token.get_secret_value().strip()
            if self.operational_guidance_enabled and _is_placeholder(directus_token):
                errors.append(
                    "DIRECTUS_STATIC_TOKEN is required for Operational Guidance in staging and production"
                )
            if self.docs_enabled and self.app_env == "production":
                errors.append("DOCS_ENABLED must be false in production")
            if self.trusted_hosts_json == ["*"] or not self.trusted_hosts_json:
                errors.append("TRUSTED_HOSTS_JSON must explicitly list production/staging hostnames")
            if self.require_role_tokens:
                role_tokens = self.human_role_tokens()
                missing = [role.value for role in RealRole if role not in role_tokens]
                if missing:
                    errors.append("HUMAN_ROLE_TOKENS_JSON is missing roles: " + ", ".join(missing))
                for role, token in role_tokens.items():
                    if len(token) < 32 or _is_placeholder(token):
                        errors.append(
                            f"Token for role {role.value} must be a non-placeholder secret of at least 32 characters"
                        )
                services = self.service_tokens()
                if not services:
                    errors.append("SERVICE_TOKENS_JSON must contain at least one service token")
                for name, token in services.items():
                    if len(token) < 32 or _is_placeholder(token):
                        errors.append(
                            f"Service token {name} must be a non-placeholder secret of at least 32 characters"
                        )
                n8n_token = self.n8n_service_token.get_secret_value().strip()
                if services.get("n8n") and n8n_token != services.get("n8n"):
                    errors.append("N8N_SERVICE_TOKEN must equal SERVICE_TOKENS_JSON['n8n']")
                all_tokens = [admin_token, *role_tokens.values(), *services.values()]
                if len(all_tokens) != len(set(all_tokens)):
                    errors.append("API, human-role and service tokens must all be unique")
            if self.metrics_enabled:
                token = self.metrics_token.get_secret_value().strip()
                if len(token) < 32 or _is_placeholder(token):
                    errors.append("METRICS_TOKEN must be a non-placeholder secret of at least 32 characters")
            if not self.require_idempotency_keys:
                errors.append("REQUIRE_IDEMPOTENCY_KEYS must be true in staging and production")

        if self.operational_guidance_enabled:
            catalog_path = self.resolved_path(self.operational_catalog_file)
            if not catalog_path.is_file():
                errors.append(f"Operational catalog file does not exist: {catalog_path}")

        service_account = self.resolved_path(self.google_service_account_file)
        if self.drive_publication_enabled:
            if _is_placeholder(self.process_card_drive_folder_id):
                errors.append("PROCESS_CARD_DRIVE_FOLDER_ID is required when Drive publication is enabled")
            if not service_account.is_file():
                errors.append(
                    f"Google service-account file is required for Drive publication: {service_account}"
                )

        if self.gmail_approval_enabled:
            if not self.drive_publication_enabled:
                errors.append("DRIVE_PUBLICATION_ENABLED must be true when Gmail approval is enabled")
            if not self.process_card_approver_email.strip():
                errors.append("PROCESS_CARD_APPROVER_EMAIL is required when Gmail approval is enabled")
            if not self.process_card_gmail_delegated_user.strip():
                errors.append(
                    "PROCESS_CARD_GMAIL_DELEGATED_USER is required when Gmail approval is enabled"
                )
            for label, value in {
                "PROCESS_CARD_APPROVER_EMAIL": self.process_card_approver_email,
                "PROCESS_CARD_GMAIL_DELEGATED_USER": self.process_card_gmail_delegated_user,
            }.items():
                if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
                    errors.append(f"{label} must contain a valid email address")

        return errors

    def validate_runtime(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise RuntimeError("Invalid runtime configuration:\n- " + "\n- ".join(errors))

    def resolved_website_targets(self) -> dict[str, dict[str, Any]]:
        targets: dict[str, dict[str, Any]] = {}
        path = self.website_targets_file.strip()
        if path:
            target_path = self.resolved_path(path)
            if target_path.exists():
                loaded = json.loads(target_path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("Website targets file must contain a JSON object")
                targets.update(loaded)
        targets.update(self.website_targets_json)
        return targets


@lru_cache
def get_settings() -> Settings:
    return Settings()
