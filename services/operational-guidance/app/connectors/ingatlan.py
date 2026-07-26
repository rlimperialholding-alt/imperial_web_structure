from __future__ import annotations

import base64
import re
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings


class IngatlanAPIError(RuntimeError):
    pass


class IngatlanConnector:
    """Official ingatlan.com Automata Betöltés API client.

    The product/account must be enabled by ingatlan.com before production use.
    """

    def __init__(self, settings: Settings):
        self.base_url = settings.ingatlan_base_url.rstrip("/")
        self.username = settings.ingatlan_username
        self.password = settings.ingatlan_password.get_secret_value()
        self._token: str | None = None
        self._token_expires_at = 0.0
        self.client = httpx.Client(timeout=60, headers={"Accept": "application/json"})

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> IngatlanConnector:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _raise_for_jsend(self, response: httpx.Response) -> dict[str, Any]:
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")
        if status not in {"success", "succes"}:
            message = payload.get("message") or payload.get("data") or payload
            raise IngatlanAPIError(f"ingatlan.com API failure: {message}")
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise IngatlanAPIError("Unexpected ingatlan.com response payload")
        return data

    def login(self, force: bool = False) -> str:
        if not force and self._token and time.time() < self._token_expires_at:
            return self._token
        if not self.username or not self.password:
            raise IngatlanAPIError("INGATLAN_USERNAME and INGATLAN_PASSWORD are required")
        response = self.client.post(
            f"{self.base_url}/auth/login",
            json={"username": self.username, "password": self.password},
        )
        data = self._raise_for_jsend(response)
        token = data.get("token")
        if not token:
            raise IngatlanAPIError("Login succeeded without a token")
        self._token = str(token)
        # Official documentation states a one-hour token. Refresh early.
        self._token_expires_at = time.time() + 50 * 60
        return self._token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.login()}", "Content-Type": "application/json"}

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.client.request(
            method,
            f"{self.base_url}/{path.lstrip('/')}",
            headers=self._headers(),
            **kwargs,
        )
        if response.status_code == 401:
            self.login(force=True)
            response = self.client.request(
                method,
                f"{self.base_url}/{path.lstrip('/')}",
                headers=self._headers(),
                **kwargs,
            )
        return self._raise_for_jsend(response)

    def list_ads(
        self,
        offset: int = 0,
        limit: int = 100,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"offset": offset, "limit": min(limit, 100)}
        if fields:
            params["fields"] = ",".join(fields)
        return self.request("GET", "/ads", params=params)

    def list_ad_ids(self) -> list[dict[str, Any]]:
        return list(self.request("GET", "/ads/ids").get("ids", []))

    def get_ad(self, own_id: str, fields: list[str] | None = None) -> dict[str, Any]:
        params = {"fields": ",".join(fields)} if fields else None
        return dict(self.request("GET", f"/ads/{own_id}", params=params).get("ad", {}))

    def upsert_ad(self, payload: dict[str, Any]) -> dict[str, Any]:
        own_id = str(payload.get("ownId", ""))
        if not re.fullmatch(r"[0-9A-Za-z_-]{1,15}", own_id):
            raise ValueError(
                "ownId is required, may contain letters, digits, _ or -, "
                "and must be at most 15 characters"
            )
        return dict(self.request("PUT", f"/ads/{own_id}", json=payload).get("ad", {}))

    def delete_ad(self, own_id: str) -> dict[str, Any]:
        return dict(self.request("DELETE", f"/ads/{own_id}").get("ad", {}))

    def list_photos(self, own_id: str) -> list[dict[str, Any]]:
        return list(self.request("GET", f"/ads/{own_id}/photos").get("photos", []))

    def upsert_photo(
        self,
        ad_own_id: str,
        photo_own_id: str,
        image: bytes | Path,
        order: int,
        title: str,
        label_id: int | None = None,
        subtype: str | None = None,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9A-Za-z_-]{1,32}", photo_own_id):
            raise ValueError("photo ownId must be 1-32 letters, digits, _ or -")
        if len(title) > 100:
            raise ValueError("photo title must be at most 100 characters")
        if isinstance(image, Path):
            image = image.read_bytes()
        payload: dict[str, Any] = {
            "order": order,
            "title": title,
            "imageData": base64.b64encode(image).decode("ascii"),
        }
        if label_id is not None:
            payload["labelId"] = label_id
        if subtype is not None:
            payload["subtype"] = subtype
        return dict(
            self.request(
                "PUT", f"/ads/{ad_own_id}/photos/{photo_own_id}", json=payload
            ).get("photo", {})
        )

    def delete_photo(self, ad_own_id: str, photo_own_id: str) -> None:
        self.request("DELETE", f"/ads/{ad_own_id}/photos/{photo_own_id}")

    def set_photo_order(self, ad_own_id: str, photo_own_ids: list[str]) -> list[dict[str, Any]]:
        return list(
            self.request(
                "PUT", f"/ads/{ad_own_id}/photoOrder", json={"order": photo_own_ids}
            ).get("photos", [])
        )
