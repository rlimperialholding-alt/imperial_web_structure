from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

BASE_URL = os.getenv("DIRECTUS_URL", "http://localhost:8055").rstrip("/")
EMAIL = os.getenv("DIRECTUS_ADMIN_EMAIL", "admin@imperial.local")
PASSWORD = os.getenv("DIRECTUS_ADMIN_PASSWORD", "change-this-password")
REGISTRY_FILE = os.getenv("BRAND_REGISTRY_FILE", "config/brand-registry.json")
OPERATIONAL_CATALOG_FILE = os.getenv(
    "OPERATIONAL_CATALOG_FILE", "config/operational-process-catalog-v1.0.json"
)

ID_FIELD: dict[str, Any] = {
    "field": "id",
    "type": "uuid",
    "meta": {"hidden": True, "readonly": True, "required": True},
    "schema": {"is_primary_key": True, "is_nullable": False},
}

COLLECTIONS: dict[str, list[dict[str, Any]]] = {
    "brands": [
        ID_FIELD,
        {"field": "status", "type": "string", "schema": {"default_value": "active"}},
        {
            "field": "key",
            "type": "string",
            "meta": {"required": True},
            "schema": {"is_unique": True, "max_length": 64, "is_nullable": False},
        },
        {
            "field": "name",
            "type": "string",
            "meta": {"required": True},
            "schema": {"max_length": 255, "is_nullable": False},
        },
        {"field": "style_guide", "type": "json"},
        {"field": "editorial", "type": "json"},
    ],
    "websites": [
        ID_FIELD,
        {
            "field": "status",
            "type": "string",
            "schema": {"default_value": "pending_configuration"},
        },
        {
            "field": "key",
            "type": "string",
            "meta": {"required": True},
            "schema": {"is_unique": True, "max_length": 64, "is_nullable": False},
        },
        {"field": "brand_key", "type": "string", "meta": {"required": True}},
        {"field": "name", "type": "string", "meta": {"required": True}},
        {"field": "kind", "type": "string", "schema": {"default_value": "custom_website"}},
        {"field": "base_url", "type": "string"},
        {"field": "author_display_name", "type": "string"},
        {"field": "publish_endpoint", "type": "string"},
        {"field": "default_paths", "type": "json"},
        {"field": "default_tags", "type": "json"},
    ],
    "content_items": [
        ID_FIELD,
        {"field": "status", "type": "string", "schema": {"default_value": "draft"}},
        {"field": "content_type", "type": "string", "meta": {"required": True}},
        {"field": "brand_key", "type": "string", "meta": {"required": True}},
        {"field": "website_keys", "type": "json", "meta": {"required": True}},
        {"field": "slug", "type": "string", "meta": {"required": True}},
        {"field": "title", "type": "string", "meta": {"required": True}},
        {"field": "summary", "type": "text"},
        {"field": "excerpt", "type": "text"},
        {"field": "body_html", "type": "text"},
        {"field": "body", "type": "json"},
        {"field": "categories", "type": "json"},
        {"field": "pricing", "type": "json"},
        {"field": "seo", "type": "json"},
        {"field": "assets", "type": "json"},
        {"field": "paths", "type": "json"},
        {"field": "tags", "type": "json"},
        {"field": "valid_from", "type": "timestamp"},
        {"field": "valid_until", "type": "timestamp"},
        {"field": "approved_by", "type": "string"},
        {"field": "approved_at", "type": "timestamp"},
        {"field": "published_at", "type": "timestamp"},
        {"field": "legal_notes", "type": "text"},
        {"field": "version_note", "type": "string"},
    ],
    "process_catalog": [
        ID_FIELD,
        {"field": "status", "type": "string", "schema": {"default_value": "active"}},
        {"field": "process_key", "type": "string", "meta": {"required": True}, "schema": {"is_unique": True, "max_length": 64, "is_nullable": False}},
        {"field": "title", "type": "string", "meta": {"required": True}},
        {"field": "family", "type": "string"},
        {"field": "trigger", "type": "text"},
        {"field": "inputs", "type": "json"},
        {"field": "steps", "type": "json"},
        {"field": "outputs", "type": "json"},
        {"field": "stop_conditions", "type": "json"},
        {"field": "completion_conditions", "type": "json"},
        {"field": "source_role", "type": "string"},
        {"field": "participant_roles", "type": "json"},
        {"field": "external_participants", "type": "json"},
        {"field": "policy_refs", "type": "json"},
        {"field": "source_version", "type": "string"},
        {"field": "source_updated_at", "type": "timestamp"},
        {"field": "gate_id", "type": "string"},
        {"field": "object_type", "type": "string"},
        {"field": "checklist_template_id", "type": "string"},
        {"field": "approval_role", "type": "string"},
        {"field": "checklist_required", "type": "boolean", "schema": {"default_value": False}},
        {"field": "metadata", "type": "json"},
    ],
    "checklist_templates": [
        ID_FIELD,
        {"field": "status", "type": "string", "schema": {"default_value": "draft"}},
        {"field": "version_key", "type": "string", "meta": {"required": True}, "schema": {"is_unique": True, "max_length": 192, "is_nullable": False}},
        {"field": "template_id", "type": "string", "meta": {"required": True}, "schema": {"max_length": 128, "is_nullable": False}},
        {"field": "process_key", "type": "string", "meta": {"required": True}},
        {"field": "title", "type": "string"},
        {"field": "family", "type": "string"},
        {"field": "primary_role", "type": "string"},
        {"field": "participant_roles", "type": "json"},
        {"field": "external_participants", "type": "json"},
        {"field": "when_to_use", "type": "text"},
        {"field": "gate_id", "type": "string"},
        {"field": "object_type", "type": "string"},
        {"field": "items", "type": "json"},
        {"field": "stop_conditions", "type": "json"},
        {"field": "required_evidence", "type": "json"},
        {"field": "closer_approver", "type": "string"},
        {"field": "answer_mode", "type": "string"},
        {"field": "version", "type": "string"},
        {"field": "source_url", "type": "string"},
        {"field": "checksum", "type": "string"},
        {"field": "approved_by", "type": "string"},
        {"field": "approved_at", "type": "timestamp"},
        {"field": "metadata", "type": "json"},
    ],
    "checklist_instances": [
        ID_FIELD,
        {"field": "status", "type": "string", "schema": {"default_value": "open"}},
        {"field": "instance_id", "type": "string", "meta": {"required": True}, "schema": {"is_unique": True, "max_length": 128, "is_nullable": False}},
        {"field": "template_id", "type": "string"},
        {"field": "template_version", "type": "string"},
        {"field": "process_key", "type": "string"},
        {"field": "gate_id", "type": "string"},
        {"field": "role", "type": "string"},
        {"field": "object_id", "type": "string"},
        {"field": "object_type", "type": "string"},
        {"field": "created_by", "type": "string"},
        {"field": "items", "type": "json"},
        {"field": "evidence_ids", "type": "json"},
        {"field": "created_at", "type": "timestamp"},
        {"field": "updated_at", "type": "timestamp"},
        {"field": "submitted_at", "type": "timestamp"},
        {"field": "approved_by", "type": "string"},
        {"field": "approved_at", "type": "timestamp"},
        {"field": "closed_at", "type": "timestamp"},
        {"field": "metadata", "type": "json"},
    ],
    "process_card_versions": [
        ID_FIELD,
        {"field": "record_key", "type": "string", "meta": {"required": True}, "schema": {"is_unique": True, "max_length": 128, "is_nullable": False}},
        {"field": "status", "type": "string", "schema": {"default_value": "draft"}},
        {"field": "process_key", "type": "string"},
        {"field": "version", "type": "integer"},
        {"field": "role", "type": "string"},
        {"field": "checklist_template_id", "type": "string"},
        {"field": "source_checksum", "type": "string"},
        {"field": "payload", "type": "json"},
        {"field": "artifacts", "type": "json"},
        {"field": "approved_by", "type": "string"},
        {"field": "approved_at", "type": "timestamp"},
    ],
}


def load_registry() -> list[dict[str, Any]]:
    inline = os.getenv("BRAND_REGISTRY_JSON", "").strip()
    if inline:
        data = json.loads(inline)
    else:
        path = Path(REGISTRY_FILE)
        if not path.is_absolute():
            path = Path.cwd() / path
        data = json.loads(path.read_text(encoding="utf-8"))
    brands = data.get("brands", [])
    if not isinstance(brands, list):
        raise ValueError("Brand registry 'brands' must be a list")
    return brands


def load_operational_catalog() -> dict[str, Any]:
    path = Path(OPERATIONAL_CATALOG_FILE)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return {"processes": [], "checklist_templates": []}
    return json.loads(path.read_text(encoding="utf-8"))


def login(client: httpx.Client) -> str:
    response = client.post(
        f"{BASE_URL}/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
    )
    response.raise_for_status()
    return response.json()["data"]["access_token"]


def exists(client: httpx.Client, headers: dict[str, str], path: str) -> bool:
    response = client.get(f"{BASE_URL}{path}", headers=headers)
    return response.status_code == 200


def create_collection(
    client: httpx.Client,
    headers: dict[str, str],
    name: str,
    fields: list[dict[str, Any]],
) -> bool:
    if exists(client, headers, f"/collections/{name}"):
        return False
    meta: dict[str, Any] = {
        "icon": "database",
        "note": "Imperial Intelligence Content Hub",
    }
    if name == "content_items":
        meta.update(
            {
                "archive_field": "status",
                "archive_value": "archived",
                "unarchive_value": "draft",
                "archive_app_filter": True,
                "versioning": True,
            }
        )
    response = client.post(
        f"{BASE_URL}/collections",
        headers=headers,
        json={
            "collection": name,
            "meta": meta,
            "schema": {"name": name},
            "fields": fields,
        },
    )
    response.raise_for_status()
    return True


def create_field(
    client: httpx.Client,
    headers: dict[str, str],
    collection: str,
    field: dict[str, Any],
) -> None:
    if exists(client, headers, f"/fields/{collection}/{field['field']}"):
        return
    response = client.post(
        f"{BASE_URL}/fields/{collection}",
        headers=headers,
        json=field,
    )
    response.raise_for_status()


def upsert_item(
    client: httpx.Client,
    headers: dict[str, str],
    collection: str,
    key: str,
    payload: dict[str, Any],
) -> None:
    check = client.get(
        f"{BASE_URL}/items/{collection}",
        headers=headers,
        params={"filter[key][_eq]": key, "limit": 1},
    )
    check.raise_for_status()
    items = check.json().get("data", [])
    if items:
        item_id = items[0]["id"]
        response = client.patch(
            f"{BASE_URL}/items/{collection}/{item_id}",
            headers=headers,
            json=payload,
        )
    else:
        response = client.post(
            f"{BASE_URL}/items/{collection}",
            headers=headers,
            json=payload,
        )
    response.raise_for_status()


def upsert_item_by_field(
    client: httpx.Client,
    headers: dict[str, str],
    collection: str,
    field: str,
    key: str,
    payload: dict[str, Any],
) -> None:
    check = client.get(
        f"{BASE_URL}/items/{collection}",
        headers=headers,
        params={f"filter[{field}][_eq]": key, "limit": 1},
    )
    check.raise_for_status()
    items = check.json().get("data", [])
    if items:
        response = client.patch(
            f"{BASE_URL}/items/{collection}/{items[0]['id']}",
            headers=headers,
            json=payload,
        )
    else:
        response = client.post(
            f"{BASE_URL}/items/{collection}", headers=headers, json=payload
        )
    response.raise_for_status()


def seed_operational_catalog(
    client: httpx.Client, headers: dict[str, str]
) -> tuple[int, int]:
    catalog = load_operational_catalog()
    process_count = 0
    checklist_count = 0
    for process in catalog.get("processes") or []:
        payload = dict(process)
        payload["status"] = "active"
        upsert_item_by_field(
            client,
            headers,
            "process_catalog",
            "process_key",
            str(process["process_key"]),
            payload,
        )
        process_count += 1
    for template in catalog.get("checklist_templates") or []:
        payload = dict(template)
        version_key = f"{template['template_id']}:v{template['version']}"
        payload["version_key"] = version_key
        upsert_item_by_field(
            client,
            headers,
            "checklist_templates",
            "version_key",
            version_key,
            payload,
        )
        checklist_count += 1
    return process_count, checklist_count


def seed_registry(client: httpx.Client, headers: dict[str, str]) -> tuple[int, int]:
    brand_count = 0
    website_count = 0
    for brand in load_registry():
        brand_key = str(brand["key"])
        upsert_item(
            client,
            headers,
            "brands",
            brand_key,
            {
                "key": brand_key,
                "name": str(brand["name"]),
                "status": str(brand.get("status") or "active"),
                "style_guide": brand.get("style_guide") or {},
                "editorial": brand.get("editorial") or {},
            },
        )
        brand_count += 1
        for website in brand.get("websites") or []:
            website_key = str(website["key"])
            base_url = website.get("base_url")
            kind = str(website.get("kind") or "custom_website")
            endpoint_path = (
                "/wp-json/imperial/v1/articles"
                if kind == "wordpress_blog"
                else "/api/internal/content-publish"
            )
            publish_endpoint = (
                f"{str(base_url).rstrip('/')}{endpoint_path}" if base_url else None
            )
            upsert_item(
                client,
                headers,
                "websites",
                website_key,
                {
                    "key": website_key,
                    "brand_key": brand_key,
                    "name": str(website.get("name") or brand["name"]),
                    "kind": kind,
                    "author_display_name": (brand.get("editorial") or {}).get(
                        "author_display_name"
                    ),
                    "status": str(
                        website.get("status")
                        or ("active" if base_url else "pending_configuration")
                    ),
                    "base_url": base_url,
                    "publish_endpoint": publish_endpoint,
                    "default_paths": ["/"],
                    "default_tags": [brand_key, website_key, "content"],
                },
            )
            website_count += 1
    return brand_count, website_count


def main() -> None:
    with httpx.Client(timeout=30) as client:
        token = login(client)
        headers = {"Authorization": f"Bearer {token}"}
        for collection, fields in COLLECTIONS.items():
            created = create_collection(client, headers, collection, fields)
            if not created:
                for field in fields:
                    if field["field"] != "id":
                        create_field(client, headers, collection, field)
        brand_count, website_count = seed_registry(client, headers)
        process_count, checklist_count = seed_operational_catalog(client, headers)
    print(
        f"Directus collections ready: {brand_count} brands, "
        f"{website_count} website records, {process_count} processes, "
        f"{checklist_count} checklist templates."
    )


if __name__ == "__main__":
    main()
