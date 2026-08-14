from __future__ import annotations

import base64
import binascii
import hmac
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
    itep_identity_shared_secret: str = _secret_value("ITEP_IDENTITY_SHARED_SECRET")
    crm_read_base_url: str = os.getenv("CRM_READ_BASE_URL", "").rstrip("/")
    crm_read_token: str = _secret_value("CRM_READ_TOKEN")
    crm_write_base_url: str = os.getenv("CRM_WRITE_BASE_URL", "").rstrip("/")
    crm_write_token: str = _secret_value("CRM_WRITE_TOKEN")
    crm_sites_bypass_token: str = _secret_value("CRM_SITES_BYPASS_TOKEN")
    crm_workspace_id: str = os.getenv("CRM_WORKSPACE_ID", "imperial-live")
    dpm_api_base_url: str = os.getenv("DPM_API_BASE_URL", "").rstrip("/")
    dpm_auth_issuer: str = os.getenv("DPM_AUTH_ISSUER", "imperial-intelligence")
    dpm_auth_audience: str = os.getenv("DPM_AUTH_AUDIENCE", "digital-project-managers")
    dpm_auth_hs256_secret: str = _secret_value("DPM_AUTH_HS256_SECRET")
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
    house_designer_adapters_enabled: bool = (
        os.getenv("HOUSE_DESIGNER_ADAPTERS_ENABLED", "false").lower() == "true"
    )
    house_design_order_intake_enabled: bool = (
        os.getenv("HOUSE_DESIGN_ORDER_INTAKE_ENABLED", "false").lower() == "true"
    )
    house_designer_pricing_hmac_secret: str = _secret_value("HOUSE_DESIGNER_PRICING_HMAC_SECRET")
    house_designer_capacity_hmac_secret: str = _secret_value("HOUSE_DESIGNER_CAPACITY_HMAC_SECRET")
    house_designer_render_hmac_secret: str = _secret_value("HOUSE_DESIGNER_RENDER_HMAC_SECRET")
    house_designer_callback_base_url: str = os.getenv(
        "HOUSE_DESIGNER_CALLBACK_BASE_URL", ""
    ).rstrip("/")
    house_designer_adapter_timeout_seconds: int = max(
        3, min(60, int(os.getenv("HOUSE_DESIGNER_ADAPTER_TIMEOUT_SECONDS", "15")))
    )
    house_designer_guest_ttl_hours: int = max(
        1, min(720, int(os.getenv("HOUSE_DESIGNER_GUEST_TTL_HOURS", "168")))
    )
    house_designer_guest_create_limit: int = max(
        1, min(100, int(os.getenv("HOUSE_DESIGNER_GUEST_CREATE_LIMIT", "5")))
    )
    house_designer_guest_rate_window_seconds: int = max(
        60,
        min(86_400, int(os.getenv("HOUSE_DESIGNER_GUEST_RATE_WINDOW_SECONDS", "3600"))),
    )
    house_designer_guest_block_seconds: int = max(
        60, min(86_400, int(os.getenv("HOUSE_DESIGNER_GUEST_BLOCK_SECONDS", "3600")))
    )
    content_external_publishing_enabled: bool = (
        os.getenv("CONTENT_EXTERNAL_PUBLISHING_ENABLED", "false").lower() == "true"
    )
    content_image_factory_enabled: bool = (
        os.getenv("CONTENT_IMAGE_FACTORY_ENABLED", "false").lower() == "true"
    )
    content_image_factory_host: str = os.getenv(
        "CONTENT_IMAGE_FACTORY_HOST", "image-factory"
    ).strip()
    content_image_factory_port: int = max(
        1, min(65535, int(os.getenv("CONTENT_IMAGE_FACTORY_PORT", "8000")))
    )
    content_image_factory_timeout_seconds: int = max(
        3, min(120, int(os.getenv("CONTENT_IMAGE_FACTORY_TIMEOUT_SECONDS", "30")))
    )
    content_image_factory_batch_size: int = max(
        1, min(100, int(os.getenv("CONTENT_IMAGE_FACTORY_BATCH_SIZE", "100")))
    )
    content_image_factory_asset_root: str = os.getenv(
        "CONTENT_IMAGE_FACTORY_ASSET_ROOT", "/app/runtime/marketing_creatives"
    )
    image_factory_api_token: str = _secret_value("IMAGE_FACTORY_API_TOKEN")
    market_public_fetch_enabled: bool = (
        os.getenv("MARKET_PUBLIC_FETCH_ENABLED", "false").lower() == "true"
    )
    market_evidence_kek: str = _secret_value("MARKET_EVIDENCE_KEK")
    market_evidence_key_id: str = os.getenv("MARKET_EVIDENCE_KEY_ID", "mci-evidence-kek-v1")
    house_designer_site_kek: str = _secret_value("HOUSE_DESIGNER_SITE_KEK")
    house_designer_site_key_id: str = os.getenv("HOUSE_DESIGNER_SITE_KEY_ID", "hd-site-kek-v1")
    typehouse_factory_processing_enabled: bool = (
        os.getenv("TYPEHOUSE_FACTORY_PROCESSING_ENABLED", "false").lower() == "true"
    )
    typehouse_factory_concurrency: int = int(os.getenv("TYPEHOUSE_FACTORY_CONCURRENCY", "1"))
    typehouse_factory_worker_poll_seconds: int = max(
        1, min(60, int(os.getenv("TYPEHOUSE_FACTORY_WORKER_POLL_SECONDS", "3")))
    )
    typehouse_factory_lease_seconds: int = max(
        60, min(3600, int(os.getenv("TYPEHOUSE_FACTORY_LEASE_SECONDS", "900")))
    )
    typehouse_factory_max_render_attempts: int = max(
        1, min(10, int(os.getenv("TYPEHOUSE_FACTORY_MAX_RENDER_ATTEMPTS", "3")))
    )
    typehouse_factory_max_repair_cycles: int = max(
        1, min(20, int(os.getenv("TYPEHOUSE_FACTORY_MAX_REPAIR_CYCLES", "5")))
    )
    typehouse_factory_qa_min_score: int = max(
        90, min(100, int(os.getenv("TYPEHOUSE_FACTORY_QA_MIN_SCORE", "90")))
    )
    typehouse_factory_required_consecutive_passes: int = int(
        os.getenv("TYPEHOUSE_FACTORY_REQUIRED_CONSECUTIVE_PASSES", "2")
    )
    typehouse_factory_asset_root: str = os.getenv(
        "TYPEHOUSE_FACTORY_ASSET_ROOT", "/app/runtime/typehouse-factory"
    )
    typehouse_factory_render_provider: str = os.getenv("RENDER_PROVIDER", "disabled")
    typehouse_factory_image_model: str = os.getenv("OPENAI_IMAGE_MODEL", "")
    typehouse_factory_vision_model: str = os.getenv("OPENAI_VISION_MODEL", "")
    require_https: bool = os.getenv("REQUIRE_HTTPS", "false").lower() == "true"
    demo_features_enabled: bool | None = _optional_bool("DEMO_FEATURES_ENABLED")
    ai_external_calls_enabled: bool = (
        os.getenv("AI_EXTERNAL_CALLS_ENABLED", "false").lower() == "true"
    )
    ai_routing_provider: str = os.getenv("AI_ROUTING_PROVIDER", "openrouter")
    ai_routine_model: str = os.getenv("AI_ROUTINE_MODEL", "qwen/qwen3-30b-a3b-instruct-2507")
    ai_reasoning_model: str = os.getenv("AI_REASONING_MODEL", "openai/gpt-5-mini")
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
        if self.content_image_factory_enabled:
            if not self.content_image_factory_host:
                errors.append("Aktív Content Factory képgeneráláshoz host kötelező.")
            if len(self.image_factory_api_token) < 32:
                errors.append(
                    "Aktív Content Factory képgeneráláshoz legalább 32 karakteres "
                    "IMAGE_FACTORY_API_TOKEN vagy IMAGE_FACTORY_API_TOKEN_FILE kötelező."
                )
        if self.typehouse_factory_concurrency != 1:
            errors.append("TYPEHOUSE_FACTORY_CONCURRENCY v1-ben kizárólag 1 lehet.")
        if self.typehouse_factory_required_consecutive_passes != 2:
            errors.append("TYPEHOUSE_FACTORY_REQUIRED_CONSECUTIVE_PASSES v1-ben kizárólag 2 lehet.")
        if self.typehouse_factory_processing_enabled:
            if self.typehouse_factory_render_provider == "disabled":
                errors.append("Aktív Typehouse Factory feldolgozáshoz RENDER_PROVIDER szükséges.")
            if not self.typehouse_factory_image_model or not self.typehouse_factory_vision_model:
                errors.append(
                    "Aktív Typehouse Factory feldolgozáshoz OPENAI_IMAGE_MODEL és "
                    "OPENAI_VISION_MODEL szükséges."
                )
        if not self.database_url:
            errors.append("DATABASE_URL vagy DATABASE_PASSWORD_FILE kötelező.")
        try:
            evidence_key = base64.b64decode(self.market_evidence_kek, validate=True)
        except (binascii.Error, ValueError):
            evidence_key = b""
        if len(evidence_key) != 32:
            errors.append("A MARKET_EVIDENCE_KEK pontosan 32 bájtos base64 AES-kulcs legyen.")
        try:
            house_designer_site_key = base64.b64decode(self.house_designer_site_kek, validate=True)
        except (binascii.Error, ValueError):
            house_designer_site_key = b""
        if len(house_designer_site_key) != 32:
            errors.append("A HOUSE_DESIGNER_SITE_KEK pontosan 32 bájtos base64 AES-kulcs legyen.")
        if (
            len(house_designer_site_key) == 32
            and len(evidence_key) == 32
            and hmac.compare_digest(house_designer_site_key, evidence_key)
        ):
            errors.append("A House Designer és Market titkosítási kulcsa nem lehet azonos.")
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
                errors.append("Production environment must not enable DEMO_FEATURES_ENABLED.")
            if "*" in self.allowed_hosts:
                errors.append(
                    "Production környezetben az ALLOWED_HOSTS nem tartalmazhat "
                    "helyettesítő karaktert."
                )
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
            errors.append("Az ITEP_API_BASE_URL és az ITEP_IDENTITY_SHARED_SECRET együtt kötelező.")
        if self.itep_identity_shared_secret and len(self.itep_identity_shared_secret) < 32:
            errors.append("Az ITEP_IDENTITY_SHARED_SECRET legalább 32 karakteres legyen.")
        if bool(self.crm_write_base_url) != bool(self.crm_write_token):
            errors.append("A CRM_WRITE_BASE_URL és a CRM_WRITE_TOKEN együtt kötelező.")
        if self.crm_write_token and len(self.crm_write_token) < 32:
            errors.append("A CRM_WRITE_TOKEN legalább 32 karakteres legyen.")
        dpm_token_source = bool(self.dpm_auth_hs256_secret) or bool(
            self.itep_api_base_url and self.itep_identity_shared_secret
        )
        if self.dpm_api_base_url and not dpm_token_source:
            errors.append(
                "A DPM_API_BASE_URL mellé ITEP tokenváltás vagy fejlesztői HS256 secret kötelező."
            )
        if self.dpm_auth_hs256_secret and not self.dpm_api_base_url:
            errors.append("A DPM_AUTH_HS256_SECRET csak DPM_API_BASE_URL mellett adható meg.")
        if self.dpm_auth_hs256_secret and len(self.dpm_auth_hs256_secret) < 32:
            errors.append("A DPM_AUTH_HS256_SECRET legalább 32 karakteres legyen.")
        if self.environment in {"staging", "production"} and self.dpm_api_base_url:
            if not self.itep_api_base_url or not self.itep_identity_shared_secret:
                errors.append(
                    "Staging/production DPM-kapcsolathoz a kanonikus ITEP tokenváltás kötelező."
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
        adapter_secrets = {
            "HOUSE_DESIGNER_PRICING_HMAC_SECRET": self.house_designer_pricing_hmac_secret,
            "HOUSE_DESIGNER_CAPACITY_HMAC_SECRET": self.house_designer_capacity_hmac_secret,
            "HOUSE_DESIGNER_RENDER_HMAC_SECRET": self.house_designer_render_hmac_secret,
        }
        if self.house_design_order_intake_enabled and not self.house_designer_adapters_enabled:
            errors.append(
                "HOUSE_DESIGN_ORDER_INTAKE_ENABLED requires HOUSE_DESIGNER_ADAPTERS_ENABLED."
            )
        if self.house_designer_adapters_enabled:
            if not self.house_designer_callback_base_url.startswith("https://"):
                errors.append(
                    "HOUSE_DESIGNER_CALLBACK_BASE_URL must be an externally reachable HTTPS URL."
                )
            for name, secret in adapter_secrets.items():
                if len(secret) < 32:
                    errors.append(
                        "Production House Designer adapters require a secret of at least "
                        f"32 characters in {name} or {name}_FILE."
                    )
            configured = [secret for secret in adapter_secrets.values() if len(secret) >= 32]
            if len(configured) == 3 and len(set(configured)) != 3:
                errors.append("Each House Designer adapter requires a distinct HMAC secret.")
        return errors


settings = Settings()
