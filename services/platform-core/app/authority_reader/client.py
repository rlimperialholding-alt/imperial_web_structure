from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag
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
DETAIL_REQUIRED_SECTIONS = frozenset({"Eljárás adatai", "Ingatlan adatai", "Hatóság neve"})
DETAIL_OPTIONAL_SECTIONS = frozenset({"Hatósági irat típusa, dátuma és döntés rövid tartalma"})
DOWNLOAD_PATH_RE = re.compile(r"^/PublicProcessData/DownloadDocument/[0-9]{1,20}$")
GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
PROCESS_NUMBER_RE = re.compile(r"^[0-9]{6,40}$")


class ReaderBlocked(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ETDRRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    # The official OData feed keeps this key in the exact schema but legitimately returns
    # null for some public procedures. The detail page remains the authoritative project subject.
    construction_activity: str | None = Field(
        alias="ConstructionActivity", default=None, min_length=1, max_length=5000
    )
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
        "construction_activity",
        "street",
        "house_number",
        "street_type",
        "topographical_number",
        "full_address",
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


class ETDRDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision_type: str = Field(min_length=1, max_length=500)
    decision_date: date
    summary: str = Field(min_length=1, max_length=5000)


class ETDRDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=500)
    download_url: str = Field(min_length=8, max_length=1500)


class ETDRDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    process_number: str = Field(pattern=r"^[0-9]{6,40}$")
    subject: str = Field(min_length=1, max_length=5000)
    procedure_type: str = Field(min_length=1, max_length=500)
    status: str = Field(min_length=1, max_length=500)
    submission_date: date
    property_address: str = Field(min_length=1, max_length=1000)
    topographical_number: str | None = Field(default=None, max_length=100)
    authority_name: str = Field(min_length=1, max_length=1000)
    decisions: tuple[ETDRDecision, ...] = Field(max_length=100)
    documents: tuple[ETDRDocument, ...] = Field(max_length=100)

    def normalized(self) -> dict[str, Any]:
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


def _clean_text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _section(soup: BeautifulSoup | Tag, title: str) -> Tag | None:
    heading = next(
        (node for node in soup.select("span.label-big") if _clean_text(node) == title),
        None,
    )
    return heading.find_parent("dap-ds-stack") if heading else None


def _label_values(section: Tag) -> dict[str, str]:
    result: dict[str, str] = {}
    for label in section.select("div.label-small"):
        stack = label.find_parent("dap-ds-stack")
        item = stack.select_one("div.item") if stack else None
        key = _clean_text(label)
        if not key or item is None or key in result:
            raise ReaderBlocked("detail_schema_drift")
        result[key] = _clean_text(item)
    return result


class ETDRDetailClient:
    """Strict parser for the public process detail page; documents remain links only."""

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
                settings.etdr_public_url,
                allowed_origins=frozenset({settings.etdr_public_url}),
                timeout=settings.request_timeout_seconds,
                transport=transport,
                resolver=resolver,
                max_redirects=0,
                default_headers={
                    "Accept": "text/html",
                    "User-Agent": "Imperial-Authority-Reader/1.1 (+policy-gated)",
                },
            )
        except SafeHttpError as exc:
            raise ReaderBlocked("unsafe_detail_origin") from exc

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> ETDRDetailClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_detail(self, process_number: str) -> ETDRDetail:
        if not PROCESS_NUMBER_RE.fullmatch(process_number):
            raise ReaderBlocked("invalid_process_number")
        try:
            response = self.http.get(f"/nyilvanos-adatok/{process_number}")
        except (SafeHttpError, httpx.HTTPError) as exc:
            raise ReaderBlocked("detail_transport_error") from exc
        try:
            if response.status_code in {401, 403}:
                raise ReaderBlocked("detail_access_blocked")
            if response.status_code == 429:
                raise ReaderBlocked("detail_rate_limited")
            if response.status_code >= 500:
                raise ReaderBlocked("detail_unavailable")
            if response.status_code != 200:
                raise ReaderBlocked("detail_unexpected_status")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type != "text/html":
                raise ReaderBlocked("detail_unexpected_content_type")
            declared = response.headers.get("content-length")
            if declared:
                try:
                    declared_bytes = int(declared)
                except ValueError as exc:
                    raise ReaderBlocked("detail_invalid_content_length") from exc
                if declared_bytes < 0 or declared_bytes > self.settings.max_response_bytes:
                    raise ReaderBlocked("detail_response_too_large")
            body = response.content
            if len(body) > self.settings.max_response_bytes:
                raise ReaderBlocked("detail_response_too_large")
            lowered = body[:8192].decode("utf-8", errors="ignore").lower()
            if any(marker in lowered for marker in CHALLENGE_MARKERS):
                raise ReaderBlocked("detail_challenge_detected")
            return self._parse(body, process_number, self.settings.etdr_public_url)
        finally:
            response.close()

    @staticmethod
    def _parse(body: bytes, expected_process_number: str, base_url: str) -> ETDRDetail:
        try:
            soup = BeautifulSoup(body.decode("utf-8"), "html.parser")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ReaderBlocked("detail_invalid_html") from exc
        cards = soup.select("dap-ds-card.details-card")
        if len(cards) != 1:
            raise ReaderBlocked("detail_schema_drift")
        card = cards[0]
        subject = _clean_text(card.select_one("dap-ds-card-title dap-ds-typography[variant='h3']"))
        identity = card.select_one("dap-ds-card-title dap-ds-label[description]")
        description = str(identity.get("description") or "") if identity else ""
        process_match = re.fullmatch(r"Azonosító:\s*([0-9]{6,40})", description)
        if not process_match or process_match.group(1) != expected_process_number:
            raise ReaderBlocked("detail_identity_mismatch")
        heading_items = [_clean_text(node) for node in card.select("span.label-big")]
        headings = set(heading_items)
        if not DETAIL_REQUIRED_SECTIONS.issubset(headings) or not headings.issubset(
            DETAIL_REQUIRED_SECTIONS | DETAIL_OPTIONAL_SECTIONS
        ):
            raise ReaderBlocked("detail_schema_drift")
        if any(heading_items.count(title) != 1 for title in DETAIL_REQUIRED_SECTIONS) or any(
            heading_items.count(title) > 1 for title in DETAIL_OPTIONAL_SECTIONS
        ):
            raise ReaderBlocked("detail_schema_drift")
        procedure_section = _section(card, "Eljárás adatai")
        property_section = _section(card, "Ingatlan adatai")
        authority_section = _section(card, "Hatóság neve")
        if not procedure_section or not property_section or not authority_section:
            raise ReaderBlocked("detail_schema_drift")
        procedure = _label_values(procedure_section)
        property_data = _label_values(property_section)
        if set(procedure) != {"Eljárás típusa", "Státusz", "Benyújtás dátuma"}:
            raise ReaderBlocked("detail_schema_drift")
        if set(property_data) != {"Cím", "Helyrajzi szám"}:
            raise ReaderBlocked("detail_schema_drift")
        try:
            submission_date = datetime.strptime(procedure["Benyújtás dátuma"], "%Y. %m. %d.").date()
        except ValueError as exc:
            raise ReaderBlocked("detail_invalid_date") from exc
        authority_items = authority_section.select("div.item")
        if len(authority_items) != 1:
            raise ReaderBlocked("detail_schema_drift")
        decisions: list[ETDRDecision] = []
        decision_section = _section(card, "Hatósági irat típusa, dátuma és döntés rövid tartalma")
        if decision_section:
            for accordion in decision_section.select("dap-ds-accordion"):
                decision_type = _clean_text(
                    accordion.select_one("span.label-small[slot='heading']")
                )
                date_text = _clean_text(accordion.select_one("span.accordion-date[slot='heading']"))
                summary = _clean_text(accordion.select_one("dap-ds-typography[variant='body']"))
                try:
                    decision_date = datetime.strptime(date_text, "%Y-%m-%d").date()
                    decisions.append(
                        ETDRDecision(
                            decision_type=decision_type,
                            decision_date=decision_date,
                            summary=summary,
                        )
                    )
                except (ValueError, ValidationError) as exc:
                    raise ReaderBlocked("detail_invalid_decision") from exc
        documents: list[ETDRDocument] = []
        origin = urlsplit(base_url)
        for link in card.select("div.document-row dap-ds-link[href]"):
            absolute = urljoin(base_url + "/", str(link.get("href") or ""))
            parsed = urlsplit(absolute)
            query = parse_qs(parsed.query, strict_parsing=True)
            if (
                parsed.scheme != origin.scheme
                or parsed.netloc != origin.netloc
                or not DOWNLOAD_PATH_RE.fullmatch(parsed.path)
                or set(query) != {"guid"}
                or len(query["guid"]) != 1
                or not GUID_RE.fullmatch(query["guid"][0])
                or parsed.fragment
            ):
                raise ReaderBlocked("detail_unsafe_document_link")
            try:
                documents.append(ETDRDocument(name=_clean_text(link), download_url=absolute))
            except ValidationError as exc:
                raise ReaderBlocked("detail_invalid_document") from exc
        try:
            return ETDRDetail(
                process_number=expected_process_number,
                subject=subject,
                procedure_type=procedure["Eljárás típusa"],
                status=procedure["Státusz"],
                submission_date=submission_date,
                property_address=property_data["Cím"],
                topographical_number=property_data["Helyrajzi szám"] or None,
                authority_name=_clean_text(authority_items[0]),
                decisions=tuple(decisions),
                documents=tuple(documents),
            )
        except ValidationError as exc:
            raise ReaderBlocked("detail_schema_drift") from exc


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
