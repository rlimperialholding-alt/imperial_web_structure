from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..config import settings

SUPPORTED_CHANNELS = {"nim_cms", "wordpress", "facebook", "instagram", "analytics", "crm", "forum"}


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class Binding:
    brand_id: str
    domain: str
    cms_route: str
    channel: str
    config: dict[str, Any]
    secret: dict[str, Any]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Unreadable JSON reference: {path.name}") from exc
    if not isinstance(value, dict):
        raise RegistryError(f"JSON reference is not an object: {path.name}")
    return value


def _secret_path(reference: str) -> Path:
    root = Path(settings.autonomous_publishing_secret_dir).resolve()
    candidate = (root / reference).resolve()
    if candidate == root or root not in candidate.parents:
        raise RegistryError("Secret reference escapes the managed secret directory")
    if not candidate.is_file():
        raise RegistryError(f"Missing secret reference: {reference}")
    mode = stat.S_IMODE(candidate.stat().st_mode)
    if mode & 0o077:
        raise RegistryError(f"Secret reference permissions are too broad: {reference}")
    return candidate


def writes_unlocked() -> bool:
    runtime_kill = Path("/app/runtime/publishing-kill-switch")
    if runtime_kill.is_file():
        return False
    path = Path(settings.autonomous_publishing_kill_switch_file)
    if not path.is_file():
        return False
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    allowed = {"ALLOW_STAGING_WRITES"}
    if settings.environment.lower() == "production":
        allowed = {"ALLOW_APPROVED_CANARY", "ALLOW_APPROVED_WRITES"}
    return value in allowed


class PublishingRegistry:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.version = str(raw.get("version") or "")
        self.brands = raw.get("brands")
        if not self.version or not isinstance(self.brands, dict) or not self.brands:
            raise RegistryError("Registry version and non-empty brands are required")
        if str(raw.get("source")) in {"example", "sample", "demo"}:
            raise RegistryError("Example registry cannot be used for runtime composition")
        self._validate()

    @classmethod
    def load(cls) -> PublishingRegistry:
        return cls(_load_json(Path(settings.autonomous_publishing_registry_file)))

    def _validate(self) -> None:
        for brand_id, brand in self.brands.items():
            if not isinstance(brand, dict):
                raise RegistryError(f"Invalid brand binding: {brand_id}")
            domain = str(brand.get("domain") or "")
            cms_route = str(brand.get("cms_route") or "").upper()
            channels = brand.get("channels")
            if (
                not domain
                or cms_route not in {"NIM", "WORDPRESS"}
                or not isinstance(channels, dict)
            ):
                raise RegistryError(f"Incomplete brand binding: {brand_id}")
            expected = "nim_cms" if cms_route == "NIM" else "wordpress"
            if not channels.get(expected, {}).get("enabled"):
                raise RegistryError(f"CMS route is not enabled for brand: {brand_id}")
            other = "wordpress" if expected == "nim_cms" else "nim_cms"
            if channels.get(other, {}).get("enabled"):
                raise RegistryError(f"Parallel CMS routing is blocked for brand: {brand_id}")
            for channel, config in channels.items():
                if channel not in SUPPORTED_CHANNELS or not isinstance(config, dict):
                    raise RegistryError(f"Invalid channel binding: {brand_id}/{channel}")
                if not config.get("enabled"):
                    continue
                base_url = str(config.get("base_url") or "")
                if channel not in {"analytics", "crm", "forum"}:
                    parsed = urlparse(base_url)
                    if parsed.scheme != "https" or not parsed.hostname:
                        raise RegistryError(f"HTTPS base_url required: {brand_id}/{channel}")
                    if parsed.hostname != domain and parsed.hostname not in config.get(
                        "allowed_hosts", []
                    ):
                        raise RegistryError(
                            f"Endpoint host is not allowlisted: {brand_id}/{channel}"
                        )
                secret_ref = config.get("secret_ref")
                if channel not in {"forum"} and not secret_ref:
                    raise RegistryError(f"Missing secret_ref: {brand_id}/{channel}")
                if secret_ref:
                    _secret_path(str(secret_ref))
                if channel == "forum" and str(config.get("mode") or "draft_only") != "draft_only":
                    policy = config.get("policy_evidence") or {}
                    if (
                        not policy.get("evidence_id")
                        or not policy.get("valid_until")
                        or not config.get("official_api")
                    ):
                        raise RegistryError(f"Forum auto-post policy evidence missing: {brand_id}")

    def binding(self, brand_id: str, channel: str) -> Binding:
        brand = self.brands.get(brand_id)
        if not isinstance(brand, dict):
            raise RegistryError(f"Unknown BrandID: {brand_id}")
        config = (brand.get("channels") or {}).get(channel)
        if not isinstance(config, dict) or not config.get("enabled"):
            raise RegistryError(f"Channel is not allowlisted: {brand_id}/{channel}")
        secret: dict[str, Any] = {}
        if config.get("secret_ref"):
            secret = _load_json(_secret_path(str(config["secret_ref"])))
        return Binding(
            brand_id=brand_id,
            domain=str(brand["domain"]),
            cms_route=str(brand["cms_route"]).upper(),
            channel=channel,
            config=dict(config),
            secret=secret,
        )

    def readiness(self) -> dict[str, Any]:
        routes: list[dict[str, Any]] = []
        for brand_id, brand in sorted(self.brands.items()):
            for channel, config in sorted((brand.get("channels") or {}).items()):
                if not config.get("enabled"):
                    continue
                try:
                    self.binding(brand_id, channel)
                    ready = True
                    reason = None
                except RegistryError as exc:
                    ready = False
                    reason = str(exc)
                routes.append(
                    {
                        "brand_id": brand_id,
                        "domain": brand.get("domain"),
                        "cms_route": brand.get("cms_route"),
                        "channel": channel,
                        "ready": ready,
                        "reason": reason,
                    }
                )
        return {
            "version": self.version,
            "writes_unlocked": writes_unlocked(),
            "routes": routes,
            "ready": bool(routes) and all(route["ready"] for route in routes),
        }
