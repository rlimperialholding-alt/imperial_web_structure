from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import Settings


class DirectusConnector:
    def __init__(self, settings: Settings):
        self.base_url = settings.directus_url.rstrip("/")
        self.token = settings.directus_static_token.get_secret_value()
        self.content_collection = settings.directus_content_collection
        self.website_collection = settings.directus_website_collection

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def get_content(self, content_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{self.base_url}/items/{self.content_collection}/{content_id}",
                params={"fields": "*"},
                headers=self._headers(),
            )
            response.raise_for_status()
            return dict(response.json()["data"])

    def list_expired_content(self, now: datetime) -> list[dict[str, Any]]:
        params = {
            "filter[status][_eq]": "published",
            "filter[valid_until][_lte]": now.isoformat(),
            "fields": "*",
            "limit": -1,
        }
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{self.base_url}/items/{self.content_collection}",
                params=params,
                headers=self._headers(),
            )
            response.raise_for_status()
            return [dict(item) for item in response.json().get("data", [])]

    def get_website(self, website_key: str) -> dict[str, Any]:
        params = {"filter[key][_eq]": website_key, "limit": 1}
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{self.base_url}/items/{self.website_collection}",
                params=params,
                headers=self._headers(),
            )
            response.raise_for_status()
            items = response.json().get("data", [])
            if not items:
                raise KeyError(f"Unknown Directus website: {website_key}")
            return dict(items[0])

    def set_status(self, content_id: str, status: str) -> None:
        payload: dict[str, Any] = {"status": status}
        if status == "published":
            payload["published_at"] = datetime.now(UTC).isoformat()
        with httpx.Client(timeout=30) as client:
            response = client.patch(
                f"{self.base_url}/items/{self.content_collection}/{content_id}",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()

    def mark_published(self, content_id: str) -> None:
        self.set_status(content_id, "published")

    def mark_unpublished(self, content_id: str) -> None:
        self.set_status(content_id, "archived")
