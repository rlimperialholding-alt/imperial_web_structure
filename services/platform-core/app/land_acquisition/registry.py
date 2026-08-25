from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LandRegistryError(ValueError):
    pass


# These domains are denied to the generic HTML scanner even when the optional
# registry cannot be loaded. A licensed feed/API connector is the only accepted
# discovery path for named real-estate portals.
NAMED_PORTAL_DOMAINS = frozenset(
    {
        "dh.hu",
        "ingatlan.com",
        "ingatlannet.hu",
        "jofogas.hu",
        "koltozzbe.hu",
        "oc.hu",
        "zenga.hu",
    }
)


def _host_matches(host: str, domain: str) -> bool:
    normalized_host = host.casefold().rstrip(".")
    normalized_domain = domain.casefold().rstrip(".")
    return normalized_host == normalized_domain or normalized_host.endswith(f".{normalized_domain}")


def is_named_portal_host(host: str) -> bool:
    return any(_host_matches(host, domain) for domain in NAMED_PORTAL_DOMAINS)


def _default_path() -> Path:
    configured = os.getenv("LAND_ACQUISITION_PORTAL_REGISTRY_FILE", "").strip()
    if configured:
        return Path(configured)
    runtime_path = Path("/app/config/land-acquisition/portals.json")
    if runtime_path.is_file():
        return runtime_path
    return Path(__file__).resolve().parents[4] / "config/land-acquisition/portals.json"


@dataclass(frozen=True)
class Portal:
    key: str
    domains: tuple[str, ...]
    discovery_mode: str
    publish_mode: str
    discovery_enabled: bool
    publish_enabled: bool
    adapter_module: str | None

    def permits(self, action: str) -> bool:
        if action == "discover":
            return self.discovery_enabled and self.discovery_mode in {"licensed_api", "feed"}
        if action in {"publish", "withdraw"}:
            return (
                self.publish_enabled
                and self.publish_mode == "licensed_api"
                and bool(self.adapter_module)
            )
        return False


class PortalRegistry:
    def __init__(self, raw: dict[str, Any]) -> None:
        if raw.get("version") != 1 or not isinstance(raw.get("portals"), list):
            raise LandRegistryError("Invalid land-acquisition portal registry")
        self.portals: dict[str, Portal] = {}
        for item in raw["portals"]:
            if not isinstance(item, dict):
                raise LandRegistryError("Portal entry must be an object")
            key = str(item.get("key") or "").strip()
            domains = tuple(
                str(value).casefold().rstrip(".")
                for value in item.get("domains", [])
                if str(value).strip()
            )
            if not key or not domains or key in self.portals:
                raise LandRegistryError("Portal key and domains must be unique and non-empty")
            if any(
                not domain or ":" in domain or "/" in domain or domain.startswith(".")
                for domain in domains
            ):
                raise LandRegistryError(f"Invalid portal domain: {key}")
            portal = Portal(
                key=key,
                domains=domains,
                discovery_mode=str(item.get("discovery_mode") or "manual"),
                publish_mode=str(item.get("publish_mode") or "manual"),
                discovery_enabled=item.get("discovery_enabled") is True,
                publish_enabled=item.get("publish_enabled") is True,
                adapter_module=str(item.get("adapter_module") or "").strip() or None,
            )
            if portal.discovery_enabled and portal.discovery_mode not in {"licensed_api", "feed"}:
                raise LandRegistryError(f"Unsafe discovery mode enabled: {key}")
            if portal.publish_enabled and (
                portal.publish_mode != "licensed_api" or not portal.adapter_module
            ):
                raise LandRegistryError(f"Unsafe publishing mode enabled: {key}")
            self.portals[key] = portal

    @classmethod
    def load(cls, path: str | Path | None = None) -> PortalRegistry:
        target = Path(path) if path else _default_path()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LandRegistryError("Portal registry is unreadable") from exc
        if not isinstance(raw, dict):
            raise LandRegistryError("Portal registry must be an object")
        return cls(raw)

    def portal(self, key: str) -> Portal:
        try:
            return self.portals[key]
        except KeyError as exc:
            raise LandRegistryError(f"Unknown portal: {key}") from exc

    def for_host(self, host: str) -> Portal | None:
        for portal in self.portals.values():
            if any(_host_matches(host, domain) for domain in portal.domains):
                return portal
        return None

    def readiness(self) -> dict[str, Any]:
        return {
            "configured": len(self.portals),
            "discovery_enabled": sorted(
                portal.key for portal in self.portals.values() if portal.permits("discover")
            ),
            "publishing_enabled": sorted(
                portal.key for portal in self.portals.values() if portal.permits("publish")
            ),
            "manual_only": sorted(
                portal.key
                for portal in self.portals.values()
                if not portal.permits("discover") and not portal.permits("publish")
            ),
        }
