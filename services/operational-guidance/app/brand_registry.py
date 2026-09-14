from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import Settings


def _read_json(path: str) -> dict[str, Any]:
    registry_path = Path(path)
    if not registry_path.is_absolute():
        registry_path = Path.cwd() / registry_path
    if not registry_path.exists():
        raise FileNotFoundError(f"Brand registry file does not exist: {registry_path}")
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Brand registry root must be a JSON object")
    return data


def load_brand_registry(settings: Settings) -> list[dict[str, Any]]:
    raw = settings.brand_registry_json or _read_json(settings.brand_registry_file)
    brands = raw.get("brands", [])
    if not isinstance(brands, list):
        raise ValueError("Brand registry 'brands' must be a list")

    seen_brands: set[str] = set()
    seen_websites: set[str] = set()
    seen_author_logins: set[str] = set()
    seen_author_names: set[str] = set()
    seen_author_emails: set[str] = set()
    normalized: list[dict[str, Any]] = []

    for brand in brands:
        if not isinstance(brand, dict):
            raise ValueError("Every brand registry item must be an object")
        key = str(brand.get("key", "")).strip()
        name = str(brand.get("name", "")).strip()
        if not key or not name:
            raise ValueError("Every brand requires a non-empty key and name")
        if key in seen_brands:
            raise ValueError(f"Duplicate brand key: {key}")
        seen_brands.add(key)

        editorial = brand.get("editorial") or {}
        if not isinstance(editorial, dict):
            raise ValueError(f"Brand editorial configuration must be an object: {key}")
        normalized_editorial = {
            "author_login": str(editorial.get("author_login", "")).strip(),
            "author_display_name": str(editorial.get("author_display_name", "")).strip(),
            "author_email": str(editorial.get("author_email", "")).strip(),
            "site_title": str(editorial.get("site_title", "")).strip(),
            "site_description": str(editorial.get("site_description", "")).strip(),
        }
        if any(normalized_editorial.values()):
            required = ("author_login", "author_display_name", "author_email")
            missing = [field for field in required if not normalized_editorial[field]]
            if missing:
                raise ValueError(f"Missing editorial fields for {key}: {', '.join(missing)}")
            uniqueness = (
                (
                    "author login",
                    normalized_editorial["author_login"].casefold(),
                    seen_author_logins,
                ),
                (
                    "author display name",
                    normalized_editorial["author_display_name"].casefold(),
                    seen_author_names,
                ),
                (
                    "author email",
                    normalized_editorial["author_email"].casefold(),
                    seen_author_emails,
                ),
            )
            for label, value, seen in uniqueness:
                if value in seen:
                    raise ValueError(f"Duplicate {label}: {value}")
                seen.add(value)

        websites = brand.get("websites") or []
        if not isinstance(websites, list):
            raise ValueError(f"Brand websites must be a list: {key}")
        normalized_websites: list[dict[str, Any]] = []
        for website in websites:
            if not isinstance(website, dict):
                raise ValueError(f"Website entry must be an object: {key}")
            website_key = str(website.get("key", "")).strip()
            if not website_key:
                raise ValueError(f"Website requires a key: {key}")
            if website_key in seen_websites:
                raise ValueError(f"Duplicate website key: {website_key}")
            seen_websites.add(website_key)
            normalized_websites.append(
                {
                    "key": website_key,
                    "name": str(website.get("name") or name),
                    "kind": str(website.get("kind") or "custom_website"),
                    "status": str(website.get("status") or "pending_configuration"),
                    "base_url": website.get("base_url"),
                }
            )

        normalized.append(
            {
                "key": key,
                "name": name,
                "status": str(brand.get("status") or "active"),
                "style_guide": brand.get("style_guide") or {},
                "editorial": normalized_editorial,
                "websites": normalized_websites,
            }
        )
    return normalized


def target_brand_map(settings: Settings) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for brand in load_brand_registry(settings):
        for website in brand["websites"]:
            mapping[website["key"]] = brand["key"]
    return mapping


def resolve_target_brand(settings: Settings, website_key: str) -> str:
    try:
        return target_brand_map(settings)[website_key]
    except KeyError as exc:
        raise KeyError(f"Unknown publication target: {website_key}") from exc


def registry_status(settings: Settings) -> list[dict[str, Any]]:
    targets = settings.resolved_website_targets()
    output: list[dict[str, Any]] = []
    for brand in load_brand_registry(settings):
        websites: list[dict[str, Any]] = []
        for website in brand["websites"]:
            target = targets.get(website["key"], {})
            websites.append(
                {
                    **website,
                    "publisher_kind": target.get("kind") or website["kind"],
                    "publisher_registered": website["key"] in targets,
                    "publisher_enabled": bool(target.get("enabled", True)),
                    "publisher_ready": bool(
                        target.get("enabled", True)
                        and target.get("url")
                        and target.get("secret")
                    ),
                }
            )
        editorial = brand["editorial"]
        safe_editorial = {
            "author_display_name": editorial.get("author_display_name"),
            "site_title": editorial.get("site_title"),
            "site_description": editorial.get("site_description"),
        }
        output.append({**brand, "editorial": safe_editorial, "websites": websites})
    return output
