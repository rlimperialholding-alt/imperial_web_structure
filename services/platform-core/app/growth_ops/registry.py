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
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GrowthRegistryError(f"Unreadable JSON reference: {path.name}") from exc
    if not isinstance(value, dict):
        raise GrowthRegistryError(f"JSON reference is not an object: {path.name}")
    return value


def _required_section(value: Any) -> dict[str, Any] | None:
    """Return the registry section when it is a non-empty object, otherwise ``None``."""
    return value if isinstance(value, dict) and value else None


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
        motors = _required_section(raw.get("motors"))
        brands = _required_section(raw.get("brands"))
        sources = _required_section(raw.get("sources"))
        routing = _required_section(raw.get("routing"))
        if str(raw.get("source")) in {"example", "sample", "demo"}:
            raise GrowthRegistryError("Example registry cannot be used at runtime")
        if (
            not self.version
            or motors is None
            or brands is None
            or sources is None
            or routing is None
        ):
            raise GrowthRegistryError(
                "Registry version, motors, brands, sources and routing are required"
            )
        self.motors = motors
        self.brands = brands
        self.sources = sources
        self.routing = routing
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
        buckets: dict[str, set[str]] = {"construction": set(), "distress": set(), "ivs": set()}
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
            if not isinstance(brand.get("templates"), dict) or "default" not in brand["templates"]:
                raise GrowthRegistryError(f"Brand outreach template missing: {brand_id}")
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
