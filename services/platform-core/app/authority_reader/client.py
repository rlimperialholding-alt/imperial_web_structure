from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..services.safe_http import AddressResolver, SafeHttpClient, SafeHttpError
from .config import ReaderSettings

ETDR_FIELDS = frozenset(
    {
        "ConstructionActivity",
        "Street",
        "HouseNumber",
        "City",
        "StreetType",
        "TopographicalNumber",
        "Type",
        "ProcessNumber",
        "SubmissionDate",
        "FullAddress",
    }
)
CHALLENGE_MARKERS = ("captcha", "recaptcha", "access denied", "cloudflare", "bejelentkezés")


class ReaderBlocked(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ETDRRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    construction_activity: str = Field(alias="ConstructionActivity", min_length=1, max_length=5000)
    street: str | None = Field(alias="Street", default=None, max_length=500)
    house_number: str | None = Field(alias="HouseNumber", default=None, max_length=100)
    city: str = Field(alias="City", min_length=1, max_length=200)
    street_type: str | None = Field(alias="StreetType", default=None, max_length=100)
    topographical_number: str | None = Field(
        alias="TopographicalNumber", default=None, max_length=100
    )
    procedure_type: str = Field(alias="Type", min_length=1, max_length=500)
    process_number: str = Field(alias="ProcessNumber", pattern=r"^[0-9]{6,40}$")
    submission_date: datetime = Field(alias="SubmissionDate")
    full_address: str | None = Field(alias="FullAddress", default=None, max_length=1000)

    @field_validator(
        "street", "house_number", "street_type", "topographical_number", "full_address"
    )
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def normalized(self) -> dict[str, Any]:
        # Only the public, explicitly allowlisted procedure/property fields are retained.
        return self.model_dump(mode="json", exclude_none=True)


@dataclass(frozen=True)
class ETDRPage:
    total: int
    records: tuple[ETDRRecord, ...]
    payload_sha256: str


class ETDRClient:
    def __init__(
        self,
        settings: ReaderSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: AddressResolver | None = None,
    ) -> None:
        self.settings = settings
        try:
            self.http = SafeHttpClient(
                settings.etdr_base_url,
                allowed_origins=frozenset({settings.etdr_base_url}),
                timeout=settings.request_timeout_seconds,
                transport=transport,
                resolver=resolver,
                max_redirects=0,
                default_headers={
                    "Accept": "application/json",
                    "User-Agent": "Imperial-Authority-Reader/1.0 (+policy-gated)",
                },
            )
        except SafeHttpError as exc:
            raise ReaderBlocked("unsafe_source_origin") from exc

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> ETDRClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_page(self, *, skip: int, page_size: int, filter_expression: str) -> ETDRPage:
        if skip < 0 or page_size < 1 or page_size > 100:
            raise ReaderBlocked("invalid_paging")
        params: dict[str, str | int] = {"$top": page_size, "$skip": skip, "$count": "true"}
        if filter_expression:
            params["$filter"] = filter_expression
        try:
            response = self.http.get("/query/PublicProcessData", params=params)
        except (SafeHttpError, httpx.HTTPError) as exc:
            raise ReaderBlocked("upstream_transport_error") from exc
        try:
            if response.status_code in {401, 403}:
                raise ReaderBlocked("upstream_access_blocked")
            if response.status_code == 429:
                raise ReaderBlocked("upstream_rate_limited")
            if response.status_code >= 500:
                raise ReaderBlocked("upstream_unavailable")
            if response.status_code != 200:
                raise ReaderBlocked("unexpected_upstream_status")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type != "application/json":
                raise ReaderBlocked("unexpected_content_type")
            declared = response.headers.get("content-length")
            if declared and int(declared) > self.settings.max_response_bytes:
                raise ReaderBlocked("response_too_large")
            body = response.content
            if len(body) > self.settings.max_response_bytes:
                raise ReaderBlocked("response_too_large")
            lowered = body[:4096].decode("utf-8", errors="ignore").lower()
            if any(marker in lowered for marker in CHALLENGE_MARKERS):
                raise ReaderBlocked("challenge_detected")
            try:
                payload = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ReaderBlocked("invalid_json") from exc
            return self._parse(payload, body, page_size)
        finally:
            response.close()

    @staticmethod
    def _parse(payload: Any, raw_body: bytes, page_size: int) -> ETDRPage:
        if not isinstance(payload, dict) or set(payload) != {
            "@odata.context",
            "@odata.count",
            "value",
        }:
            raise ReaderBlocked("schema_drift_envelope")
        if not isinstance(payload["@odata.context"], str):
            raise ReaderBlocked("schema_drift_context")
        total = payload["@odata.count"]
        rows = payload["value"]
        if not isinstance(total, int) or total < 0 or not isinstance(rows, list):
            raise ReaderBlocked("schema_drift_envelope")
        if len(rows) > page_size:
            raise ReaderBlocked("page_limit_exceeded")
        records: list[ETDRRecord] = []
        try:
            for row in rows:
                if not isinstance(row, dict) or set(row) != ETDR_FIELDS:
                    raise ReaderBlocked("schema_drift_record")
                records.append(ETDRRecord.model_validate(row))
        except ValidationError as exc:
            raise ReaderBlocked("invalid_record") from exc
        return ETDRPage(
            total=total,
            records=tuple(records),
            payload_sha256=hashlib.sha256(raw_body).hexdigest(),
        )


class OENYClient:
    """Anonymous parcel enrichment client; execution remains behind the same policy gate."""

    def __init__(
        self,
        settings: ReaderSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: AddressResolver | None = None,
    ) -> None:
        self.settings = settings
        self.http = SafeHttpClient(
            settings.oeny_base_url,
            allowed_origins=frozenset({settings.oeny_base_url}),
            timeout=settings.request_timeout_seconds,
            transport=transport,
            resolver=resolver,
            max_redirects=0,
            default_headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> OENYClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def settlement_search(self, name: str) -> list[dict[str, str]]:
        payload = self._json_list(
            "/hk-api/settlements/search", params={"searchString": name}, code_prefix="oeny"
        )
        expected = {"kshCode", "name"}
        if any(
            set(item) != expected or not all(isinstance(item[key], str) for key in expected)
            for item in payload
        ):
            raise ReaderBlocked("oeny_schema_drift")
        return payload

    def parcel_search(self, *, ksh_code: str, lot_number: str) -> list[dict[str, Any]]:
        payload = self._json_list(
            "/hk-api/parcels/search",
            params={"kshCode": ksh_code, "lotNumber": lot_number},
            code_prefix="oeny",
        )
        if any(
            set(item) != {"id", "lotNumber"}
            or not isinstance(item["id"], int)
            or not isinstance(item["lotNumber"], str)
            for item in payload
        ):
            raise ReaderBlocked("oeny_schema_drift")
        return payload

    def _json_list(
        self, path: str, *, params: dict[str, str], code_prefix: str
    ) -> list[dict[str, Any]]:
        response = self.http.get(path, params=params)
        try:
            if response.status_code in {401, 403, 429}:
                raise ReaderBlocked(f"{code_prefix}_access_blocked")
            if response.status_code != 200:
                raise ReaderBlocked(f"{code_prefix}_unexpected_status")
            if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                raise ReaderBlocked(f"{code_prefix}_unexpected_content_type")
            if len(response.content) > self.settings.max_response_bytes:
                raise ReaderBlocked(f"{code_prefix}_response_too_large")
            payload = response.json()
            if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
                raise ReaderBlocked(f"{code_prefix}_schema_drift")
            return payload
        finally:
            response.close()
