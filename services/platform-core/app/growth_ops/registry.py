from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class GrowthRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class GrowthSettings:
    enabled: bool
    registry_file: str
    secret_dir: str
    kill_switch_file: str
    worker_id: str
    poll_seconds: int
    lease_seconds: int
    base_url: str
    timezone: str
    outreach_send_start_local: str
    outreach_send_end_local: str
    canonical_wide_enabled: bool
    canonical_daily_at: str
    canonical_manifest_file: str
    canonical_route_scanning_enabled: bool
    canonical_route_batch_size: int
    canonical_route_timeout_seconds: float
    canonical_route_max_response_bytes: int
    canonical_processing_enabled: bool
    canonical_analysis_text_chars: int
    canonical_question_answer_enabled: bool
    canonical_question_answer_batch_size: int
    canonical_content_factory_enabled: bool
    canonical_internal_handoff_enabled: bool
    canonical_internal_handoff_at: str
    canonical_internal_handoff_secret_file: str
    canonical_publication_digest_enabled: bool
    canonical_publication_digest_at: str
    canonical_publication_digest_recipient: str
    canonical_publication_digest_kill_switch_file: str
    canonical_publication_digest_per_minute_limit: int
    canonical_publication_digest_rolling_24h_limit: int
    deepseek_api_key_file: str
    deepseek_base_url: str
    deepseek_routine_model: str
    deepseek_high_stakes_model: str
    deepseek_monthly_budget_usd: float
    deepseek_input_usd_per_million: float
    deepseek_output_usd_per_million: float


def settings() -> GrowthSettings:
    return GrowthSettings(
        enabled=os.getenv("GROWTH_OPS_ENABLED", "false").lower() == "true",
        registry_file=os.getenv("GROWTH_OPS_REGISTRY_FILE", "/app/config/growth/registry.json"),
        secret_dir=os.getenv("GROWTH_OPS_SECRET_DIR", "/run/secrets/growth"),
        kill_switch_file=os.getenv(
            "GROWTH_OPS_KILL_SWITCH_FILE", "/run/secrets/growth/kill-switch"
        ),
        worker_id=os.getenv("GROWTH_OPS_WORKER_ID", "imperial-growth-worker"),
        poll_seconds=max(5, int(os.getenv("GROWTH_OPS_POLL_SECONDS", "30"))),
        lease_seconds=max(30, int(os.getenv("GROWTH_OPS_LEASE_SECONDS", "300"))),
        base_url=os.getenv("GROWTH_OPS_BASE_URL", "").rstrip("/"),
        timezone=os.getenv("GROWTH_OPS_TIMEZONE", "Europe/Budapest"),
        outreach_send_start_local=os.getenv(
            "GROWTH_OPS_OUTREACH_SEND_START_LOCAL", "08:00"
        ),
        outreach_send_end_local=os.getenv(
            "GROWTH_OPS_OUTREACH_SEND_END_LOCAL", "18:00"
        ),
        canonical_wide_enabled=os.getenv("CANONICAL_GROWTH_ENABLED", "false").lower()
        == "true",
        canonical_daily_at=os.getenv("CANONICAL_GROWTH_DAILY_AT", "05:30"),
        canonical_manifest_file=os.getenv(
            "CANONICAL_SOURCE_MANIFEST_FILE", "/app/config/growth/source-ledger-manifest.json"
        ),
        canonical_route_scanning_enabled=os.getenv(
            "CANONICAL_ROUTE_SCANNING_ENABLED", "false"
        ).lower()
        == "true",
        canonical_route_batch_size=max(
            1, min(25, int(os.getenv("CANONICAL_ROUTE_BATCH_SIZE", "3")))
        ),
        canonical_route_timeout_seconds=max(
            2.0, min(30.0, float(os.getenv("CANONICAL_ROUTE_TIMEOUT_SECONDS", "12")))
        ),
        canonical_route_max_response_bytes=max(
            100_000,
            min(
                5_000_000,
                int(os.getenv("CANONICAL_ROUTE_MAX_RESPONSE_BYTES", "1000000")),
            ),
        ),
        canonical_processing_enabled=os.getenv(
            "CANONICAL_PROCESSING_ENABLED", "false"
        ).lower()
        == "true",
        canonical_analysis_text_chars=max(
            1_000, min(20_000, int(os.getenv("CANONICAL_ANALYSIS_TEXT_CHARS", "6000")))
        ),
        canonical_question_answer_enabled=os.getenv(
            "CANONICAL_QUESTION_ANSWER_ENABLED", "true"
        ).lower()
        == "true",
        canonical_question_answer_batch_size=max(
            1, min(100, int(os.getenv("CANONICAL_QUESTION_ANSWER_BATCH_SIZE", "50")))
        ),
        canonical_content_factory_enabled=os.getenv(
            "CANONICAL_CONTENT_FACTORY_ENABLED", "false"
        ).lower()
        == "true",
        canonical_internal_handoff_enabled=os.getenv(
            "CANONICAL_INTERNAL_HANDOFF_ENABLED", "false"
        ).lower()
        == "true",
        canonical_internal_handoff_at=os.getenv(
            "CANONICAL_INTERNAL_HANDOFF_AT", "18:30"
        ),
        canonical_internal_handoff_secret_file=os.getenv(
            "CANONICAL_INTERNAL_HANDOFF_SECRET_FILE",
            "/run/secrets/growth/internal-handoff-smtp.json",
        ),
        canonical_publication_digest_enabled=os.getenv(
            "CANONICAL_PUBLICATION_DIGEST_ENABLED", "false"
        ).lower()
        == "true",
        canonical_publication_digest_at=os.getenv(
            "CANONICAL_PUBLICATION_DIGEST_AT", "10:00"
        ),
        canonical_publication_digest_recipient=os.getenv(
            "CANONICAL_PUBLICATION_DIGEST_RECIPIENT", "molnar.andrea@imperialholding.hu"
        ),
        canonical_publication_digest_kill_switch_file=os.getenv(
            "CANONICAL_PUBLICATION_DIGEST_KILL_SWITCH_FILE",
            "/run/secrets/publishing/kill-switch",
        ),
        canonical_publication_digest_per_minute_limit=max(
            1,
            min(
                10,
                int(os.getenv("CANONICAL_PUBLICATION_DIGEST_PER_MINUTE_LIMIT", "1")),
            ),
        ),
        canonical_publication_digest_rolling_24h_limit=max(
            1,
            min(
                100,
                int(os.getenv("CANONICAL_PUBLICATION_DIGEST_ROLLING_24H_LIMIT", "20")),
            ),
        ),
        deepseek_api_key_file=os.getenv(
            "DEEPSEEK_API_KEY_FILE", "/run/secrets/growth/deepseek-api-key"
        ),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip(
            "/"
        ),
        deepseek_routine_model=os.getenv("DEEPSEEK_ROUTINE_MODEL", "deepseek-v4-flash"),
        deepseek_high_stakes_model=os.getenv(
            "DEEPSEEK_HIGH_STAKES_MODEL", "deepseek-v4-pro"
        ),
        deepseek_monthly_budget_usd=max(
            0.0, float(os.getenv("DEEPSEEK_MONTHLY_BUDGET_USD", "0"))
        ),
        deepseek_input_usd_per_million=max(
            0.0, float(os.getenv("DEEPSEEK_INPUT_USD_PER_MILLION", "0"))
        ),
        deepseek_output_usd_per_million=max(
            0.0, float(os.getenv("DEEPSEEK_OUTPUT_USD_PER_MILLION", "0"))
        ),
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GrowthRegistryError(f"Unreadable JSON reference: {path.name}") from exc
    if not isinstance(value, dict):
        raise GrowthRegistryError(f"JSON reference is not an object: {path.name}")
    return value


def _managed_secret(reference: str) -> Path:
    root = Path(settings().secret_dir).resolve()
    candidate = (root / reference).resolve()
    if candidate == root or root not in candidate.parents:
        raise GrowthRegistryError("Secret reference escapes the managed secret directory")
    if not candidate.is_file():
        raise GrowthRegistryError(f"Missing secret reference: {reference}")
    if stat.S_IMODE(candidate.stat().st_mode) & 0o077:
        raise GrowthRegistryError(f"Secret reference permissions are too broad: {reference}")
    return candidate


def writes_unlocked() -> bool:
    runtime_kill = Path("/app/runtime/growth-kill-switch")
    if runtime_kill.is_file():
        return False
    gate = Path(settings().kill_switch_file)
    if not gate.is_file():
        return False
    try:
        value = gate.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    environment = os.getenv("ENVIRONMENT", "development").lower()
    allowed = {"ALLOW_STAGING_WRITES"}
    if environment == "production":
        allowed = {"ALLOW_APPROVED_CANARY", "ALLOW_APPROVED_WRITES"}
    return value in allowed


@dataclass(frozen=True)
class BrandBinding:
    brand_id: str
    sender_email: str
    domain_key: str
    secret: dict[str, Any]
    config: dict[str, Any]


class GrowthRegistry:
    REQUIRED_MOTORS = {"construction", "distress", "ivs"}
    REQUIRED_CONSTRUCTION_BUCKETS = {
        "etdr",
        "public_request",
        "fitout_change",
        "property_development",
        "horeca",
        "contractor_capacity",
    }
    REQUIRED_DISTRESS_BUCKETS = {
        "liquidation",
        "bankruptcy",
        "enforcement",
        "officer_change",
        "registered_office_change",
        "construction_dispute",
    }

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.version = str(raw.get("version") or "")
        self.motors = raw.get("motors")
        self.brands = raw.get("brands")
        self.sources = raw.get("sources")
        self.routing = raw.get("routing")
        if str(raw.get("source")) in {"example", "sample", "demo"}:
            raise GrowthRegistryError("Example registry cannot be used at runtime")
        if not self.version or not all(
            isinstance(value, dict) and value
            for value in (self.motors, self.brands, self.sources, self.routing)
        ):
            raise GrowthRegistryError(
                "Registry version, motors, brands, sources and routing are required"
            )
        self._validate()

    @classmethod
    def load(cls) -> GrowthRegistry:
        return cls(_load_json(Path(settings().registry_file)))

    def _validate(self) -> None:
        if set(self.motors) != self.REQUIRED_MOTORS:
            raise GrowthRegistryError(
                "The construction, distress and ivs motors must be defined exactly"
            )
        for motor_key, motor in self.motors.items():
            interval = int(motor.get("interval_minutes") or 0)
            daily_at = str(motor.get("daily_at") or "")
            if bool(interval) == bool(daily_at):
                raise GrowthRegistryError(
                    f"Exactly one interval_minutes or daily_at schedule is required: {motor_key}"
                )
            if interval < 0 or (daily_at and not _valid_clock(daily_at)):
                raise GrowthRegistryError(f"Invalid motor schedule: {motor_key}")
            if int(motor.get("max_raw_signals_per_run") or 0) < 1:
                raise GrowthRegistryError(f"Invalid motor scan limit: {motor_key}")
        if int(self.motors["construction"].get("interval_minutes") or 0) != 60:
            raise GrowthRegistryError("Construction motor must run hourly")
        if int(self.motors["distress"].get("interval_minutes") or 0) != 60:
            raise GrowthRegistryError("Distress motor must run hourly")
        if str(self.motors["ivs"].get("daily_at") or "") != "08:00":
            raise GrowthRegistryError("IVS target motor must run daily at 08:00")
        if int(self.motors["construction"].get("daily_raw_review_target") or 0) < 300:
            raise GrowthRegistryError(
                "Construction motor daily raw review target must be at least 300"
            )
        buckets = {"construction": set(), "distress": set(), "ivs": set()}
        for source_id, source in self.sources.items():
            if not isinstance(source, dict):
                raise GrowthRegistryError(f"Invalid source binding: {source_id}")
            motor = str(source.get("motor") or "")
            bucket = str(source.get("bucket") or "")
            if motor not in self.motors or not bucket:
                raise GrowthRegistryError(f"Source motor/bucket is incomplete: {source_id}")
            buckets[motor].add(bucket)
            if not source.get("enabled"):
                continue
            parsed = urlparse(str(source.get("url") or ""))
            if parsed.scheme != "https" or not parsed.hostname:
                raise GrowthRegistryError(f"Enabled source must use HTTPS: {source_id}")
            evidence = source.get("policy_evidence") or {}
            checked = _parse_time(evidence.get("checked_at"))
            valid_until = _parse_time(evidence.get("valid_until"))
            if (
                not evidence.get("evidence_url")
                or not checked
                or not valid_until
                or valid_until <= datetime.now(UTC)
            ):
                raise GrowthRegistryError(
                    f"Current source-policy evidence is required: {source_id}"
                )
            if str(source.get("kind")) not in {"json", "rss"}:
                raise GrowthRegistryError(f"Unsupported enabled source kind: {source_id}")
        if not self.REQUIRED_CONSTRUCTION_BUCKETS.issubset(buckets["construction"]):
            raise GrowthRegistryError("All six construction source buckets must be represented")
        if not self.REQUIRED_DISTRESS_BUCKETS.issubset(buckets["distress"]):
            raise GrowthRegistryError("All six distress source buckets must be represented")
        for brand_id, brand in self.brands.items():
            if not isinstance(brand, dict):
                raise GrowthRegistryError(f"Invalid brand: {brand_id}")
            sender = str(brand.get("sender_email") or "").lower()
            if "@" not in sender or not brand.get("domain_key") or not brand.get("secret_ref"):
                raise GrowthRegistryError(f"Brand sender binding is incomplete: {brand_id}")
            if brand.get("templates"):
                raise GrowthRegistryError(
                    "Brand-local outreach templates are prohibited; use the canonical "
                    f"first-contact registry: {brand_id}"
                )
            _managed_secret(str(brand["secret_ref"]))
        for signal_type, brand_id in self.routing.items():
            if brand_id not in self.brands:
                raise GrowthRegistryError(f"Unknown routed brand for signal type: {signal_type}")

    def brand_for(self, signal_type: str, requested: str | None = None) -> str:
        routed = str(self.routing.get(signal_type) or "")
        if requested and requested != routed:
            raise GrowthRegistryError("Requested brand conflicts with canonical signal routing")
        if not routed:
            raise GrowthRegistryError(f"No canonical brand route for signal type: {signal_type}")
        return routed

    def brand_binding(self, brand_id: str) -> BrandBinding:
        brand = self.brands.get(brand_id)
        if not isinstance(brand, dict):
            raise GrowthRegistryError(f"Unknown brand: {brand_id}")
        secret = _load_json(_managed_secret(str(brand["secret_ref"])))
        return BrandBinding(
            brand_id=brand_id,
            sender_email=str(brand["sender_email"]).lower(),
            domain_key=str(brand["domain_key"]),
            secret=secret,
            config=dict(brand),
        )

    def sources_for(self, motor_key: str) -> list[tuple[str, dict[str, Any]]]:
        return [
            (source_id, dict(source))
            for source_id, source in sorted(self.sources.items())
            if source.get("motor") == motor_key and source.get("enabled")
        ]

    def validate_signal_source(self, *, source_id: str, motor_key: str, source_bucket: str) -> None:
        source = self.sources.get(source_id)
        if not isinstance(source, dict) or not source.get("enabled"):
            raise GrowthRegistryError("Signal source is not enabled in the managed registry")
        if source.get("motor") != motor_key or source.get("bucket") != source_bucket:
            raise GrowthRegistryError(
                "Signal source motor or bucket conflicts with the managed registry"
            )

    def readiness(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "writes_unlocked": writes_unlocked(),
            "motors": sorted(self.motors),
            "brands": sorted(self.brands),
            "enabled_sources": sum(bool(source.get("enabled")) for source in self.sources.values()),
            "ready": True,
        }


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo else result.replace(tzinfo=UTC)


def _valid_clock(value: str) -> bool:
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except (TypeError, ValueError):
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59
