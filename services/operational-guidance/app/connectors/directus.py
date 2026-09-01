from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import Settings
from app.connectors.safe_http import AddressResolver, SafeHttpClient, validate_identifier


class DirectusConnector:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: AddressResolver | None = None,
    ):
        self.base_url = settings.directus_url.rstrip("/")
        self.token = settings.directus_static_token.get_secret_value()
        self.content_collection = validate_identifier(
            settings.directus_content_collection, label="Directus content collection"
        )
        self.website_collection = validate_identifier(
            settings.directus_website_collection, label="Directus website collection"
        )
        # A transport/resolver csak szintetikus, hálózatmentes tesztekben cserélhető.
        self.client = SafeHttpClient(self.base_url, transport=transport, resolver=resolver)
        self._closed = False

    def close(self) -> None:
        """A HTTP-kliens erőforrásainak idempotens, pontosan egyszeri lezárása.

        A hívó réteg (taskok, service-ek, route-ok) minden normál és kivételes
        úton context managerrel zár; a duplikált ``close()`` hívás nem okoz
        hibát, és a lezárás kísérlete nem ismétlődik. ``__del__``-re a
        lifecycle nem támaszkodik.
        """
        if self._closed:
            return
        self._closed = True
        self.client.close()

    def __enter__(self) -> DirectusConnector:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def get_content(self, content_id: str) -> dict[str, Any]:
        content_id = validate_identifier(content_id, label="Directus content azonosító")
        response = self.client.get(
            f"/items/{self.content_collection}/{content_id}",
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
        response = self.client.get(
            f"/items/{self.content_collection}",
            params=params,
            headers=self._headers(),
        )
        response.raise_for_status()
        return [dict(item) for item in response.json().get("data", [])]

    def get_website(self, website_key: str) -> dict[str, Any]:
        # A website_key üzleti contractja 64 karakter (a PublicationJob.website_key
        # oszlop String(64) a modelben és a 431439b9fde5 migrációban); a validátor
        # alapértelmezett MAX_IDENTIFIER_LENGTH=64 határa ezzel konzisztens.
        # Ennél hosszabb kulcs nem létezhet a tárolt adatban, ezért fail-closed
        # elutasul; a korábbi max_length=128 félrevezető túlengedés volt.
        website_key = validate_identifier(website_key, label="Directus website kulcs")
        params = {"filter[key][_eq]": website_key, "limit": 1}
        response = self.client.get(
            f"/items/{self.website_collection}",
            params=params,
            headers=self._headers(),
        )
        response.raise_for_status()
        items = response.json().get("data", [])
        if not items:
            raise KeyError(f"Unknown Directus website: {website_key}")
        return dict(items[0])

    def set_status(self, content_id: str, status: str) -> None:
        content_id = validate_identifier(content_id, label="Directus content azonosító")
        payload: dict[str, Any] = {"status": status}
        if status == "published":
            payload["published_at"] = datetime.now(UTC).isoformat()
        response = self.client.patch(
            f"/items/{self.content_collection}/{content_id}",
            json=payload,
            headers=self._headers(),
        )
        response.raise_for_status()

    def mark_published(self, content_id: str) -> None:
        self.set_status(content_id, "published")

    def mark_unpublished(self, content_id: str) -> None:
        self.set_status(content_id, "archived")
