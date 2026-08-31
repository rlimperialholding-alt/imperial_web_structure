from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Literal, cast
from urllib.parse import unquote, urlparse, urlunparse

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..land_acquisition.registry import (
    is_named_portal_host,
    same_named_portal_binding,
)
from .canonical_policy import (
    LAND_AGENT_HARD_GATE_REASONS,
    contains_no_monitoring_entity,
    land_agent_hard_gate_reason,
)
from .models import (
    GrowthSignal,
    GrowthSignalSourceEvidence,
    SourceCoverageAttempt,
    SourceCoverageRoute,
)
from .registry import GrowthRegistry, GrowthRegistryError
from .schemas import GrowthSignalIn, GrowthSignalReceipt

MANAGED_LAND_SOURCE_MOTOR: Literal["construction"] = "construction"
MANAGED_LAND_SOURCE_BUCKET = "property_development"
MANAGED_LAND_SOURCE_ID = "construction_public_land_html"
MANAGED_LAND_SOURCE_KIND = "public_land_listing_html"
MANAGED_LAND_SOURCE_FETCH_MODE = "ingest_only"

_HIDDEN_TAGS = {"script", "style", "noscript", "svg", "template"}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}
_CONTACT_BLOCK_TAGS = {"address", "article", "div", "dl", "li", "section", "table"}
_FORBIDDEN_CONTACT_REGION_TAGS = {"aside", "footer", "header", "nav"}
_HIDDEN_CLASS_TOKENS = {"d-none", "hidden", "invisible", "sr-only", "visually-hidden"}
_STYLESHEET_MAX_CHARS = 200_000
_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "dd",
    "div",
    "dl",
    "dt",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "p",
    "section",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
}

_NAME_LABELS = {
    "ertekesito",
    "ertekesito neve",
    "hirdeto neve",
    "ingatlan kozvetito",
    "ingatlankozvetito",
    "ingatlanreferens",
    "ingatlanreferens neve",
    "kapcsolattarto",
    "kapcsolattarto neve",
    "tulajdonos",
    "tulajdonos neve",
}
_ROLE_LABELS = {
    "hirdeto minosege",
    "hirdeto szerepe",
    "hirdeto tipusa",
    "kapcsolattarto szerepe",
    "szerepkor",
}
_ORGANIZATION_LABELS = {
    "ceg",
    "halozat",
    "ingatlanhalozat",
    "irodahalozat",
    "szervezet",
}
_OFFICE_LABELS = {
    "ingatlan iroda",
    "ingatlaniroda",
    "iroda",
    "iroda neve",
    "irodai affiliacio",
    "irodai tagsag",
    "kirendeltseg",
}
_LOCATION_LABELS = {
    "helyseg",
    "ingatlan telepulese",
    "settlement",
    "telepules",
}
_PLOT_SIZE_LABELS = {
    "terulet",
    "telek merete",
    "telek terulete",
    "telekmeret",
    "telekterulet",
}
_PROPERTY_TYPE_LABELS = {
    "hirdetes tipusa",
    "ingatlan tipusa",
    "ingatlantipus",
    "property type",
}
_EMAIL_LABELS = {"e mail", "e mail cim", "email", "email cim"}

_AGENT_ROLE_VALUES = {
    "ertekesito",
    "ingatlan kozvetito",
    "ingatlankozvetito",
    "ingatlanos",
    "ingatlanreferens",
    "kozvetito",
    "listing agent",
}
_OWNER_ROLE_VALUES = {
    "ingatlan tulajdonosa",
    "maganhirdeto",
    "maganszemely",
    "property owner",
    "sajat tulajdonos",
    "tulajdonos",
}
_IMPLIED_AGENT_NAME_LABELS = {
    "ertekesito",
    "ertekesito neve",
    "ingatlan kozvetito",
    "ingatlankozvetito",
    "ingatlanreferens",
    "ingatlanreferens neve",
}
_IMPLIED_OWNER_NAME_LABELS = {"tulajdonos", "tulajdonos neve"}

_BUILDING_PLOT_MARKERS = (
    "beepitheto telek",
    "belteruleti epitesi telek",
    "epitesi celra alkalmas telek",
    "epitesi telek",
    "lakoovezeti telek",
    "lakoovezeti telek",
)
_INACTIVE_LISTING_MARKERS = (
    "a hirdetes mar nem aktiv",
    "a hirdetes nem aktiv",
    "a hirdetest archivaltak",
    "archivalt hirdetes",
    "elkelt",
    "hirdetes inaktiv",
    "ingatlan mar nem elerheto",
    "torolt hirdetes",
    "visszavont hirdetes",
    "withdrawn",
)

_AREA_RE = re.compile(
    r"(?<!\d)(\d[\d .\u00a0]*(?:[,.]\d+)?)\s*(?:m\s*(?:2|²)|nm|negyzetmeter)\b",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
    re.IGNORECASE,
)
_STRUCTURED_SCRIPT_MAX_CHARS = 2_000_000


def _fold(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).split())


def _clean(value: object, limit: int = 500) -> str | None:
    normalized = " ".join(str(value or "").split()).strip(" :-–—|\t\r\n")
    return normalized[:limit] or None


def _canonical_https_url(value: object) -> str | None:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or len(raw) > 1500
    ):
        return None
    try:
        if parsed.port not in {None, 443}:
            return None
    except ValueError:
        return None
    return urlunparse(parsed._replace(fragment=""))


def is_specific_listing_permalink(value: object) -> bool:
    canonical = _canonical_https_url(value)
    if not canonical:
        return False
    parsed = urlparse(canonical)
    host = (parsed.hostname or "").casefold()
    if not is_named_portal_host(host):
        return False
    path = parsed.path.casefold().rstrip("/")
    parts = [part for part in path.split("/") if part]
    if not parts:
        return False
    if re.fullmatch(r"/\d{6,}", path):
        return True
    if path.endswith(".htm") and any(character.isdigit() for character in parts[-1]):
        return True
    generic_parts = {
        "elado",
        "elado telek",
        "ingatlan",
        "ingatlanok",
        "lista",
        "telek",
    }
    return (
        (
            any(part in {"ingatlan", "ingatlanok"} for part in parts[:-1])
            or bool(re.search(r"\d{5,}", parts[-1]))
        )
        and _fold(parts[-1]) not in generic_parts
        and (len(parts[-1]) >= 8 or any(character.isdigit() for character in parts[-1]))
    )


def _stylesheet_hidden_selectors(html: str) -> tuple[set[str], set[str], bool]:
    hidden_classes: set[str] = set()
    hidden_ids: set[str] = set()
    stylesheet_chars = 0
    ambiguous = False
    for style_match in re.finditer(
        r"<style\b[^>]*>(.*?)</style\s*>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        stylesheet = style_match.group(1)
        stylesheet_chars += len(stylesheet)
        if stylesheet_chars > _STYLESHEET_MAX_CHARS:
            return set(), set(), True
        for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", stylesheet):
            declarations = re.sub(r"\s+", "", rule.group(2).casefold())
            if not any(
                marker in declarations
                for marker in (
                    "display:none",
                    "visibility:hidden",
                    "content-visibility:hidden",
                )
            ):
                continue
            selector = rule.group(1)
            classes = {
                value.casefold()
                for value in re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", selector)
            }
            ids = {
                value.casefold()
                for value in re.findall(r"#([A-Za-z_][A-Za-z0-9_-]*)", selector)
            }
            hidden_classes.update(classes)
            hidden_ids.update(ids)
            if not classes and not ids:
                ambiguous = True
    return hidden_classes, hidden_ids, ambiguous


class _ListingHTML(HTMLParser):
    def __init__(
        self,
        *,
        stylesheet_hidden_classes: set[str] | None = None,
        stylesheet_hidden_ids: set[str] | None = None,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_stack: list[str] = []
        self.forbidden_contact_stack: list[str] = []
        self.mailto_values: list[str] = []
        self.heading_depth = 0
        self.heading_parts: list[str] = []
        self.headings: list[str] = []
        self.contact_stack: list[tuple[str, int]] = []
        self.contact_parts: dict[int, list[str]] = {}
        self.structured_contact_parts: dict[int, list[str]] = {}
        self.contact_mailtos: dict[int, list[str]] = {}
        self.contact_meta_emails: dict[int, list[str]] = {}
        self.contact_has_child: dict[int, bool] = {}
        self.meta_values: list[tuple[str, str, str]] = []
        self.semantic_stack: list[tuple[str, str, list[str]]] = []
        self.semantic_events: list[tuple[str, str]] = []
        self.next_contact_id = 1
        self.stylesheet_hidden_classes = set(stylesheet_hidden_classes or ())
        self.stylesheet_hidden_ids = set(stylesheet_hidden_ids or ())

    def _separator(self) -> None:
        if self.parts and self.parts[-1] != "\n":
            self.parts.append("\n")
        if self.contact_stack and not self.forbidden_contact_stack:
            _, block_id = self.contact_stack[-1]
            parts = self.contact_parts[block_id]
            if parts and parts[-1] != "\n":
                parts.append("\n")
            for _, structured_block_id in self.contact_stack:
                structured_parts = self.structured_contact_parts[
                    structured_block_id
                ]
                if structured_parts and structured_parts[-1] != "\n":
                    structured_parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.casefold()
        if self.hidden_stack:
            if name not in _VOID_TAGS:
                self.hidden_stack.append(name)
            return
        attributes = {key.casefold(): str(value or "") for key, value in attrs}
        class_tokens = {
            token.casefold() for token in attributes.get("class", "").split()
        }
        style = re.sub(r"\s+", "", attributes.get("style", "").casefold())
        hidden_here = (
            name in _HIDDEN_TAGS
            or "hidden" in attributes
            or attributes.get("aria-hidden", "").casefold() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
            or bool(class_tokens & _HIDDEN_CLASS_TOKENS)
            or bool(class_tokens & self.stylesheet_hidden_classes)
            or attributes.get("id", "").casefold() in self.stylesheet_hidden_ids
        )
        if hidden_here:
            if name not in _VOID_TAGS:
                self.hidden_stack.append(name)
            return
        if self.forbidden_contact_stack:
            if name not in _VOID_TAGS:
                self.forbidden_contact_stack.append(name)
        elif name in _FORBIDDEN_CONTACT_REGION_TAGS:
            if name not in _VOID_TAGS:
                self.forbidden_contact_stack.append(name)
        elif name in _CONTACT_BLOCK_TAGS:
            if self.contact_stack:
                self.contact_has_child[self.contact_stack[-1][1]] = True
            block_id = self.next_contact_id
            self.next_contact_id += 1
            self.contact_stack.append((name, block_id))
            self.contact_parts[block_id] = []
            self.structured_contact_parts[block_id] = []
            self.contact_mailtos[block_id] = []
            self.contact_meta_emails[block_id] = []
            self.contact_has_child[block_id] = False
        if name in _BLOCK_TAGS or name == "br":
            self._separator()
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if self.heading_depth == 0:
                self.heading_parts = []
            self.heading_depth += 1
        if name == "a":
            href = next(
                (value for key, value in attrs if key.casefold() == "href"), None
            )
            if href and href.casefold().startswith("mailto:"):
                self.mailto_values.append(href)
                if self.contact_stack and not self.forbidden_contact_stack:
                    _, block_id = self.contact_stack[-1]
                    self.contact_mailtos[block_id].append(href)
        itemprop = _fold(attributes.get("itemprop"))
        if name == "meta":
            content = _clean(attributes.get("content"), 2_000)
            key = _fold(
                attributes.get("itemprop")
                or attributes.get("name")
                or attributes.get("property")
            )
            if key and content:
                self.meta_values.append((key, content, name))
                if (
                    key == "email"
                    and self.contact_stack
                    and not self.forbidden_contact_stack
                ):
                    _, block_id = self.contact_stack[-1]
                    self.contact_meta_emails[block_id].append(content)
        elif itemprop in {"name", "description"}:
            self.semantic_stack.append((name, itemprop, []))

    def handle_endtag(self, tag: str) -> None:
        name = tag.casefold()
        if self.hidden_stack:
            if self.hidden_stack[-1] == name:
                self.hidden_stack.pop()
            return
        if name in _BLOCK_TAGS:
            self._separator()
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.heading_depth:
            self.heading_depth -= 1
            if self.heading_depth == 0:
                heading = _clean("".join(self.heading_parts), 2_000)
                if heading:
                    self.headings.append(heading)
                self.heading_parts = []
        if (
            self.contact_stack
            and not self.forbidden_contact_stack
            and self.contact_stack[-1][0] == name
        ):
            self.contact_stack.pop()
        if self.semantic_stack and self.semantic_stack[-1][0] == name:
            _, itemprop, parts = self.semantic_stack.pop()
            value = _clean("".join(parts), 2_000)
            if value:
                self.semantic_events.append((itemprop, value))
        if self.forbidden_contact_stack and self.forbidden_contact_stack[-1] == name:
            self.forbidden_contact_stack.pop()

    def handle_data(self, data: str) -> None:
        if not self.hidden_stack and not self.forbidden_contact_stack:
            self.parts.append(data)
            if self.contact_stack:
                _, block_id = self.contact_stack[-1]
                self.contact_parts[block_id].append(data)
                for _, structured_block_id in self.contact_stack:
                    self.structured_contact_parts[structured_block_id].append(data)
            if self.heading_depth:
                self.heading_parts.append(data)
            for _, _, parts in self.semantic_stack:
                parts.append(data)

    def lines(self) -> list[str]:
        return [
            line
            for raw in "".join(self.parts).splitlines()
            if (line := _clean(raw, 2000))
        ]

    def contact_blocks(self) -> list[tuple[list[str], list[str]]]:
        blocks: list[tuple[list[str], list[str]]] = []
        for block_id, parts in self.contact_parts.items():
            if self.contact_has_child[block_id]:
                continue
            lines = [
                line
                for raw in "".join(parts).splitlines()
                if (line := _clean(raw, 2_000))
            ]
            blocks.append((lines, list(self.contact_mailtos[block_id])))
        return blocks

    def contact_blocks_with_meta(
        self,
    ) -> list[tuple[list[str], list[str], list[str]]]:
        blocks: list[tuple[list[str], list[str], list[str]]] = []
        for block_id, parts in self.structured_contact_parts.items():
            lines = [
                line
                for raw in "".join(parts).splitlines()
                if (line := _clean(raw, 2_000))
            ]
            blocks.append(
                (
                    lines,
                    list(self.contact_mailtos[block_id]),
                    list(self.contact_meta_emails[block_id]),
                )
            )
        return blocks


class _StructuredScripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.active_attrs: dict[str, str] | None = None
        self.active_parts: list[str] = []
        self.scripts: list[tuple[dict[str, str], str]] = []
        self.overflow = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "script" or self.active_attrs is not None:
            return
        self.active_attrs = {
            key.casefold(): str(value or "") for key, value in attrs
        }
        self.active_parts = []

    def handle_data(self, data: str) -> None:
        if self.active_attrs is None or self.overflow:
            return
        if sum(len(part) for part in self.active_parts) + len(data) > _STRUCTURED_SCRIPT_MAX_CHARS:
            self.overflow = True
            return
        self.active_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "script" or self.active_attrs is None:
            return
        self.scripts.append((self.active_attrs, "".join(self.active_parts)))
        self.active_attrs = None
        self.active_parts = []


@dataclass(frozen=True)
class ListingDecision:
    signal: GrowthSignalIn | None
    reasons: tuple[str, ...]
    evidence_fields: dict[str, str]
    evidence_records: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class _StructuredListingEvidence:
    values: dict[str, str]
    snippets: dict[str, str]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _BoundContactRecipient:
    email: str | None
    role: Literal["listing_agent", "property_owner"] | None
    name: str | None
    email_snippet: str | None
    role_snippet: str | None
    name_snippet: str | None
    fact_lines: tuple[str, ...]
    screening_blocks: tuple[tuple[str, ...], ...]
    reasons: tuple[str, ...]


def _json_evidence_snippet(locator: str, value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{locator}={encoded}"[:2_000]


def _nested_dict(value: object, *keys: str) -> dict[str, Any] | None:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, dict) else None


def _strict_positive_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        return None
    integer = int(parsed)
    return integer if 0 < integer <= 10_000_000 else None


def _rendered_value_present(lines: list[str], value: object) -> bool:
    target = _fold(value)
    return bool(
        target
        and any(
            _fold(line) == target
            or re.search(rf"(?:^| ){re.escape(target)}(?: |$)", _fold(line))
            for line in lines
        )
    )


def _rendered_area_present(lines: list[str], area: int) -> bool:
    compact = re.sub(r"\s+", " ", "\n".join(lines)).casefold()
    digits = r"[ .\u00a0]*".join(re.escape(character) for character in str(area))
    return bool(re.search(rf"(?<!\d){digits}\s*(?:m\s*(?:2|²)|nm)(?!\w)", compact))


def _dh_structured_evidence(
    *,
    listing_url: str,
    html: str,
) -> _StructuredListingEvidence:
    reasons: list[str] = []
    scripts = _StructuredScripts()
    try:
        scripts.feed(html)
    except Exception:
        return _StructuredListingEvidence({}, {}, ("dh_structured_payload_unreadable",))
    if scripts.overflow:
        return _StructuredListingEvidence({}, {}, ("dh_structured_payload_too_large",))
    assignment = re.compile(
        r"pageCache\s*\[\s*(['\"])([0-9a-fA-F]{32})\1\s*\]\s*=\s*"
        r"(\"(?:\\.|[^\"\\])*\")\s*;",
        re.DOTALL,
    )
    matches = [match for _, script in scripts.scripts for match in assignment.finditer(script)]
    if len(matches) != 1:
        return _StructuredListingEvidence({}, {}, ("dh_page_cache_not_unique",))

    def reject_duplicate_object_keys(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    try:
        decoded = json.loads(matches[0].group(3))
        if not isinstance(decoded, str) or len(decoded) > _STRUCTURED_SCRIPT_MAX_CHARS:
            raise ValueError
        payload = json.loads(decoded, object_pairs_hook=reject_duplicate_object_keys)
    except (json.JSONDecodeError, TypeError, ValueError):
        return _StructuredListingEvidence({}, {}, ("dh_page_cache_invalid",))
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return _StructuredListingEvidence({}, {}, ("dh_listing_status_invalid",))
    result = payload.get("result")
    agent = result.get("agent") if isinstance(result, dict) else None
    if not isinstance(result, dict) or not isinstance(agent, dict):
        return _StructuredListingEvidence({}, {}, ("dh_listing_schema_invalid",))
    reference = _clean(result.get("referenceNumber"), 120)
    alias = _clean(result.get("alias"), 500)
    parsed_url = urlparse(listing_url)
    if (
        not reference
        or not alias
        or not re.search(
            rf"(?:^|/)ingatlan/{re.escape(reference)}(?:/|$)",
            parsed_url.path,
            re.IGNORECASE,
        )
    ):
        reasons.append("dh_listing_identity_mismatch")
    address = _clean(result.get("address"), 500)
    location = None
    if address:
        without_postcode = re.sub(r"^\s*\d{4}\s+", "", address)
        location = _clean(without_postcode.split(",", 1)[0], 500)
    area = _strict_positive_integer(result.get("area"))
    property_candidates = [
        value
        for value in (
            _clean(result.get("subType"), 500),
            _clean(result.get("propertyTypeName"), 500),
        )
        if value and any(marker in _fold(value) for marker in _BUILDING_PLOT_MARKERS)
    ]
    property_type, _ = _unique(property_candidates)
    name = _clean(agent.get("name"), 500)
    raw_email = agent.get("email")
    email = (
        raw_email.strip()
        if isinstance(raw_email, str) and len(raw_email.strip()) <= 320
        else None
    )
    office = _clean(agent.get("office"), 500)
    if not email or not _EMAIL_RE.fullmatch(email.casefold()):
        reasons.append("recipient_email_missing")
    if reasons:
        return _StructuredListingEvidence({}, {}, tuple(sorted(set(reasons))))
    assert all((reference, email))
    values = {
        "recipient_email": str(email).casefold(),
        "recipient_role": "listing_agent",
        "recipient_organization_name": "Duna House",
    }
    snippets = {
        "recipient_email": _json_evidence_snippet("$.result.agent.email", email),
        "recipient_role": "$.result.agent=listing_agent",
        "recipient_organization_name": (
            "portal=dh.hu; organization=Duna House"
        ),
    }
    # `result.agent` is the listing's structured recipient object. Its exact
    # scalar `email` field plus the object identity proves listing_agent without
    # a second rendered meta-email/name copy. Footer/support mailboxes are never
    # consulted here. A name is optional and retained only when it is person-like.
    bound_name = name if _named_recipient(name) else None
    if bound_name:
        values["recipient_name"] = str(bound_name)
        snippets["recipient_name"] = _json_evidence_snippet(
            "$.result.agent.name", bound_name
        )
    for field_name, value, snippet in (
        ("property_type", property_type, _json_evidence_snippet("$.result.subType", property_type)),
        ("location", location, _json_evidence_snippet("$.result.address", address)),
        (
            "plot_size_sqm",
            area,
            _json_evidence_snippet("$.result.area", result.get("area")),
        ),
        (
            "recipient_office_name",
            office,
            _json_evidence_snippet("$.result.agent.office", office),
        ),
    ):
        if value is not None:
            values[field_name] = str(value)
            snippets[field_name] = snippet
    return _StructuredListingEvidence(values, snippets, ())


def _ingatlannet_structured_evidence(
    *,
    listing_url: str,
    html: str,
    rendered: _ListingHTML,
) -> _StructuredListingEvidence:
    scripts = _StructuredScripts()
    try:
        scripts.feed(html)
    except Exception:
        return _StructuredListingEvidence({}, {}, ("ingatlannet_next_data_unreadable",))
    matches = [
        text
        for attrs, text in scripts.scripts
        if attrs.get("id") == "__NEXT_DATA__"
        and attrs.get("type", "").casefold() == "application/json"
    ]
    if scripts.overflow:
        return _StructuredListingEvidence({}, {}, ("ingatlannet_next_data_too_large",))
    if len(matches) != 1:
        return _StructuredListingEvidence({}, {}, ("ingatlannet_next_data_not_unique",))
    try:
        payload = json.loads(matches[0])
    except (json.JSONDecodeError, TypeError):
        return _StructuredListingEvidence({}, {}, ("ingatlannet_next_data_invalid",))
    page_props = _nested_dict(payload, "props", "pageProps")
    envelope = _nested_dict(page_props, "data") if page_props else None
    data = envelope.get("data") if isinstance(envelope, dict) else None
    owner = envelope.get("ownerData") if isinstance(envelope, dict) else None
    office_data = envelope.get("officeData") if isinstance(envelope, dict) else None
    query = payload.get("query") if isinstance(payload, dict) else None
    if not all(isinstance(value, dict) for value in (data, owner, query)):
        return _StructuredListingEvidence({}, {}, ("ingatlannet_listing_schema_invalid",))
    assert isinstance(page_props, dict)
    assert isinstance(data, dict)
    assert isinstance(owner, dict)
    assert isinstance(query, dict)
    reasons: list[str] = []
    listing_id = _clean(data.get("id"), 120)
    canonical = _canonical_https_url(page_props.get("canonical"))
    final_url = _canonical_https_url(listing_url)
    relative_url = _clean(data.get("url"), 1_500)
    relative_path = urlparse(relative_url or "").path
    final_path = urlparse(final_url or "").path
    if (
        not listing_id
        or str(query.get("id")) != listing_id
        or not re.search(rf"/{re.escape(listing_id)}/?$", final_path)
        or relative_path.rstrip("/") != final_path.rstrip("/")
        or canonical != final_url
    ):
        reasons.append("ingatlannet_listing_identity_mismatch")
    if (
        type(data.get("status")) is not int
        or data.get("status") != 1
        or type(data.get("estateStatus")) is not int
        or data.get("estateStatus") != 1
        or data.get("deletedAt") is not None
        or not isinstance(payload, dict)
        or payload.get("isFallback") is not False
    ):
        reasons.append("listing_inactive_explicit")
    if str(data.get("advertiserId")) != str(owner.get("id")):
        reasons.append("ingatlannet_owner_binding_mismatch")
    plot_size = _strict_positive_integer(data.get("plotSize"))
    address = _clean(data.get("address"), 500)
    location = address
    if address and "," in address:
        street = _clean(data.get("street") or data.get("streetName"), 500)
        settlement, suffix = (_clean(part, 500) for part in address.split(",", 1))
        if street and suffix and _fold(street) in _fold(suffix):
            location = settlement
        else:
            location = None
    name = _clean(owner.get("name"), 500)
    email = _clean(owner.get("email"), 320)
    role_raw = _clean(owner.get("type"), 500)
    office = (
        _clean(office_data.get("name"), 500)
        if isinstance(office_data, dict)
        else None
    )
    property_candidates = [
        heading
        for heading in rendered.headings
        if any(marker in _fold(heading) for marker in _BUILDING_PLOT_MARKERS)
    ]
    property_type, _ = _unique(property_candidates)
    if not email or not _EMAIL_RE.fullmatch(email.casefold()):
        reasons.append("recipient_email_missing")
    folded_role = _fold(role_raw)
    if folded_role in _AGENT_ROLE_VALUES:
        recipient_role = "listing_agent"
    elif folded_role in _OWNER_ROLE_VALUES:
        recipient_role = "property_owner"
    else:
        recipient_role = None
        reasons.append("recipient_role_missing")
    lines = rendered.lines()
    rendered_bindings = [(role_raw, "ingatlannet_rendered_owner_role_mismatch")]
    for value, reason in rendered_bindings:
        if not _rendered_value_present(lines, value):
            reasons.append(reason)
    if reasons:
        return _StructuredListingEvidence({}, {}, tuple(sorted(set(reasons))))
    assert all((email, role_raw))
    values = {
        "recipient_email": str(email).casefold(),
        "recipient_role": str(recipient_role),
    }
    snippets = {
        "recipient_email": _json_evidence_snippet(
            "$.props.pageProps.data.ownerData.email", email
        ),
        "recipient_role": _json_evidence_snippet(
            "$.props.pageProps.data.ownerData.type", role_raw
        ),
    }
    bound_name = name if _named_recipient(name) and _rendered_value_present(lines, name) else None
    if bound_name:
        values["recipient_name"] = str(bound_name)
        snippets["recipient_name"] = _json_evidence_snippet(
            "$.props.pageProps.data.ownerData.name", bound_name
        )
    for field_name, value, snippet in (
        (
            "property_type",
            property_type,
            f"rendered_heading={json.dumps(property_type, ensure_ascii=False)}",
        ),
        (
            "location",
            location,
            _json_evidence_snippet("$.props.pageProps.data.data.address", address),
        ),
        (
            "plot_size_sqm",
            plot_size,
            _json_evidence_snippet(
                "$.props.pageProps.data.data.plotSize", data.get("plotSize")
            ),
        ),
        (
            "recipient_organization_name",
            office,
            _json_evidence_snippet("$.props.pageProps.data.officeData.name", office),
        ),
        (
            "recipient_office_name",
            office,
            _json_evidence_snippet("$.props.pageProps.data.officeData.name", office),
        ),
    ):
        if value is not None:
            values[field_name] = str(value)
            snippets[field_name] = snippet
    return _StructuredListingEvidence(values, snippets, ())


def _structured_portal_evidence(
    *,
    listing_url: str,
    html: str,
    rendered: _ListingHTML,
) -> _StructuredListingEvidence | None:
    host = (urlparse(listing_url).hostname or "").casefold().removeprefix("www.")
    if host == "dh.hu":
        return _dh_structured_evidence(
            listing_url=listing_url,
            html=html,
        )
    if host == "ingatlannet.hu":
        return _ingatlannet_structured_evidence(
            listing_url=listing_url,
            html=html,
            rendered=rendered,
        )
    return None


def _label_values(lines: list[str], labels: set[str]) -> list[tuple[str, str, str]]:
    values: list[tuple[str, str, str]] = []
    folded_labels = sorted(labels, key=len, reverse=True)
    for index, line in enumerate(lines):
        folded_line = _fold(line)
        for label in folded_labels:
            if folded_line == label:
                if index + 1 < len(lines) and (value := _clean(lines[index + 1])):
                    values.append((label, value, f"{line}\n{lines[index + 1]}"))
                break
            if not folded_line.startswith(f"{label} "):
                continue
            # Slice the original string on a source-native separator where possible;
            # otherwise consume exactly the same number of whitespace-separated label
            # words. The captured value always comes from the fetched HTML.
            separated = re.match(
                r"^\s*(.+?)\s*(?:[:|–—]|\s-\s)\s*(.+)$",
                line,
            )
            if separated and _fold(separated.group(1)) == label:
                candidate = _clean(separated.group(2))
            else:
                words = line.split()
                candidate = _clean(" ".join(words[len(label.split()) :]))
            if candidate:
                values.append((label, candidate, line))
            break
    return values


def _source_snippet(
    pairs: list[tuple[str, str, str]], value: str | None
) -> str | None:
    if not value:
        return None
    folded_value = _fold(value)
    return next(
        (snippet for _, candidate, snippet in pairs if _fold(candidate) == folded_value),
        None,
    )


def _unique(values: list[str]) -> tuple[str | None, bool]:
    unique: dict[str, str] = {}
    for value in values:
        cleaned = _clean(value)
        if cleaned:
            unique.setdefault(_fold(cleaned), cleaned)
    if len(unique) != 1:
        return None, len(unique) > 1
    return next(iter(unique.values())), False


def _mailto_emails(values: list[str]) -> tuple[list[str], bool]:
    emails: dict[str, str] = {}
    malformed = False
    for href in values:
        target = unquote(href[7:].split("?", 1)[0]).strip()
        if not target or any(separator in target for separator in (",", ";")):
            malformed = True
            continue
        normalized = target.casefold()
        if not _EMAIL_RE.fullmatch(normalized):
            malformed = True
            continue
        emails.setdefault(normalized, normalized)
    return list(emails.values()), malformed


def _unique_emails(values: list[str]) -> tuple[str | None, bool]:
    unique = {
        value.strip().casefold(): value.strip().casefold()
        for value in values
        if value.strip()
    }
    if len(unique) != 1:
        return None, len(unique) > 1
    return next(iter(unique.values())), False


def _bound_contact_recipient(parser: _ListingHTML) -> _BoundContactRecipient:
    bindings: list[
        tuple[
            str,
            Literal["listing_agent", "property_owner"],
            str | None,
            str,
            str,
            str | None,
            tuple[str, ...],
        ]
    ] = []
    malformed = False
    role_ambiguous = False
    role_seen = False
    for lines, mailtos in parser.contact_blocks():
        block_name_pairs = _label_values(lines, _NAME_LABELS)
        block_name, block_name_ambiguous = _unique(
            [value for _, value, _ in block_name_pairs]
        )
        block_role, block_role_ambiguous = _recipient_role(
            [label for label, _, _ in block_name_pairs],
            [value for _, value, _ in _label_values(lines, _ROLE_LABELS)],
        )
        email_pairs = _label_values(lines, _EMAIL_LABELS)
        visible_emails = [
            value.casefold()
            for _, value, _ in email_pairs
            if _EMAIL_RE.fullmatch(value.casefold())
        ]
        email_label_visible = bool(email_pairs) or any(
            _fold(line) in _EMAIL_LABELS for line in lines
        )
        mailto_emails, mailto_malformed = _mailto_emails(mailtos)
        block_emails = [
            *(mailto_emails if email_label_visible else []),
            *visible_emails,
        ]
        block_email, block_email_ambiguous = _unique_emails(block_emails)
        if block_role_ambiguous and block_email:
            role_ambiguous = True
            continue
        if not block_role:
            continue
        role_seen = True
        malformed = malformed or mailto_malformed
        if block_email_ambiguous or not block_email:
            if block_email_ambiguous:
                bindings.extend(
                    (
                        email,
                        cast(
                            Literal["listing_agent", "property_owner"],
                            block_role,
                        ),
                        None,
                        email,
                        block_role,
                        None,
                        tuple(lines),
                    )
                    for email in sorted(set(block_emails))
                )
            continue
        role_snippet = next(
            (
                snippet
                for _, value, snippet in _label_values(lines, _ROLE_LABELS)
                if (
                    block_role == "listing_agent"
                    and _fold(value) in _AGENT_ROLE_VALUES
                )
                or (
                    block_role == "property_owner"
                    and _fold(value) in _OWNER_ROLE_VALUES
                )
            ),
            None,
        )
        if role_snippet is None:
            implied_labels = (
                _IMPLIED_AGENT_NAME_LABELS
                if block_role == "listing_agent"
                else _IMPLIED_OWNER_NAME_LABELS
            )
            role_snippet = next(
                (
                    snippet
                    for label, _, snippet in block_name_pairs
                    if label in implied_labels
                ),
                block_role,
            )
        email_snippet = next(
            (
                href
                for href in mailtos
                if unquote(href[7:].split("?", 1)[0]).strip().casefold()
                == block_email
            ),
            None,
        ) or next(
            (
                snippet
                for _, value, snippet in email_pairs
                if value.casefold() == block_email
            ),
            block_email,
        )
        bound_name = (
            block_name
            if not block_name_ambiguous and _named_recipient(block_name)
            else None
        )
        bindings.append(
            (
                block_email,
                cast(Literal["listing_agent", "property_owner"], block_role),
                bound_name,
                email_snippet,
                role_snippet,
                _source_snippet(block_name_pairs, bound_name),
                tuple(lines),
            )
        )
    emails = {binding[0].casefold(): binding[0] for binding in bindings}
    roles = {binding[1] for binding in bindings}
    reasons: list[str] = []
    if len(roles) > 1:
        reasons.append("recipient_role_ambiguous")
    if len(emails) > 1:
        reasons.append("recipient_email_ambiguous")
    if not bindings:
        if malformed:
            reasons.append("recipient_email_malformed")
        if role_ambiguous:
            reasons.append("recipient_role_ambiguous")
        reasons.append(
            "recipient_email_missing" if role_seen else "recipient_role_missing"
        )
    if reasons:
        return _BoundContactRecipient(
            None,
            None,
            None,
            None,
            None,
            None,
            (),
            (),
            tuple(sorted(set(reasons))),
        )
    selected_email = next(iter(emails.values()))
    selected_role = next(iter(roles))
    selected = [
        binding
        for binding in bindings
        if binding[0] == selected_email and binding[1] == selected_role
    ]
    names = _unique([binding[2] for binding in selected if binding[2]])
    selected_name = names[0] if not names[1] else None
    named_binding = next(
        (binding for binding in selected if binding[2] == selected_name),
        selected[0],
    )
    return _BoundContactRecipient(
        selected_email,
        selected_role,
        selected_name,
        selected[0][3],
        selected[0][4],
        named_binding[5] if selected_name else None,
        selected[0][6] if len(selected) == 1 else (),
        tuple(binding[6] for binding in selected),
        (),
    )


def _plot_size(value: str) -> int | None:
    matches = _AREA_RE.findall(value)
    parsed: set[int] = set()
    for raw in matches:
        compact = raw.replace("\u00a0", "").replace(" ", "")
        if "," in compact:
            whole, fraction = compact.split(",", 1)
            if fraction.strip("0"):
                continue
            compact = whole
        elif compact.count(".") == 1 and len(compact.rsplit(".", 1)[-1]) <= 2:
            whole, fraction = compact.split(".", 1)
            if fraction.strip("0"):
                continue
            compact = whole
        else:
            compact = compact.replace(".", "")
        if compact.isdigit() and 0 < int(compact) <= 10_000_000:
            parsed.add(int(compact))
    return next(iter(parsed)) if len(parsed) == 1 else None


def _recipient_role(
    name_labels: list[str], role_values: list[str]
) -> tuple[str | None, bool]:
    candidates: set[str] = set()
    if any(label in _IMPLIED_AGENT_NAME_LABELS for label in name_labels):
        candidates.add("listing_agent")
    if any(label in _IMPLIED_OWNER_NAME_LABELS for label in name_labels):
        candidates.add("property_owner")
    for value in role_values:
        folded = _fold(value)
        if folded in _AGENT_ROLE_VALUES:
            candidates.add("listing_agent")
        if folded in _OWNER_ROLE_VALUES:
            candidates.add("property_owner")
    if len(candidates) != 1:
        return None, len(candidates) > 1
    return next(iter(candidates)), False


def _named_recipient(value: str | None) -> bool:
    if not value or len(value) < 3 or "@" in value:
        return False
    folded = _fold(value)
    if folded in _AGENT_ROLE_VALUES | _OWNER_ROLE_VALUES:
        return False
    name_parts = [
        part for part in value.split() if any(character.isalpha() for character in part)
    ]
    return len(name_parts) >= 2


def _managed_land_source_id() -> str:
    registry = GrowthRegistry.load()
    sources = getattr(registry, "sources", None)
    if not isinstance(sources, dict):
        raise GrowthRegistryError("managed_land_source_binding_missing")
    source = sources.get(MANAGED_LAND_SOURCE_ID)
    if not isinstance(source, dict) or source.get("enabled") is not True:
        raise GrowthRegistryError("managed_land_source_binding_missing")
    if (
        source.get("motor") != MANAGED_LAND_SOURCE_MOTOR
        or source.get("bucket") != MANAGED_LAND_SOURCE_BUCKET
        or source.get("kind") != MANAGED_LAND_SOURCE_KIND
        or source.get("fetch_mode") != MANAGED_LAND_SOURCE_FETCH_MODE
    ):
        raise GrowthRegistryError("managed_land_source_binding_invalid")
    from ..land_acquisition.service import managed_public_land_route_set_sha256

    if source.get("route_set_sha256") != managed_public_land_route_set_sha256():
        raise GrowthRegistryError("managed_land_source_route_set_binding_invalid")
    duplicates = [
        source_id
        for source_id, candidate in sources.items()
        if source_id != MANAGED_LAND_SOURCE_ID
        and isinstance(candidate, dict)
        and candidate.get("enabled") is True
        and candidate.get("fetch_mode") == MANAGED_LAND_SOURCE_FETCH_MODE
        and candidate.get("motor") == MANAGED_LAND_SOURCE_MOTOR
        and candidate.get("bucket") == MANAGED_LAND_SOURCE_BUCKET
    ]
    if duplicates:
        raise GrowthRegistryError("managed_land_source_binding_not_unique")
    return MANAGED_LAND_SOURCE_ID


def listing_signal_decision(
    *,
    route: SourceCoverageRoute,
    attempt: SourceCoverageAttempt,
    listing_url: str,
    html: str,
    response_sha256: str,
    source_id: str,
) -> ListingDecision:
    reasons: list[str] = []
    evidence_fields: dict[str, str] = {}
    evidence_records: list[dict[str, str]] = []

    def record(field_name: str, observed_value: object, source_snippet: object) -> None:
        value = str(observed_value)
        snippet = str(source_snippet)
        evidence_fields[field_name] = value
        evidence_records.append(
            {
                "field_name": field_name,
                "observed_value": value,
                "source_snippet": snippet,
            }
        )
    canonical_url = _canonical_https_url(listing_url)
    route_url = _canonical_https_url(route.route_url)
    if not canonical_url or not route_url or not is_specific_listing_permalink(canonical_url):
        reasons.append("concrete_listing_permalink_missing")
    elif not same_named_portal_binding(
        urlparse(canonical_url).hostname or "",
        urlparse(route_url).hostname or "",
    ):
        reasons.append("listing_permalink_not_same_portal")
    else:
        record("listing_permalink", canonical_url, canonical_url)

    hidden_classes, hidden_ids, stylesheet_ambiguous = (
        _stylesheet_hidden_selectors(html)
    )
    if stylesheet_ambiguous:
        reasons.append("listing_stylesheet_visibility_ambiguous")
    parser = _ListingHTML(
        stylesheet_hidden_classes=hidden_classes,
        stylesheet_hidden_ids=hidden_ids,
    )
    try:
        parser.feed(html)
    except Exception:
        reasons.append("listing_html_unreadable")
    structured = (
        _structured_portal_evidence(
            listing_url=canonical_url,
            html=html,
            rendered=parser,
        )
        if canonical_url
        else None
    )
    if structured is not None:
        reasons.extend(structured.reasons)
    lines = parser.lines()
    visible_text = "\n".join(lines)
    folded_text = _fold(visible_text)
    if any(marker in folded_text for marker in _INACTIVE_LISTING_MARKERS):
        reasons.append("listing_inactive_explicit")
    property_type: str | None
    if structured is not None:
        property_type = structured.values.get("property_type")
        if property_type:
            record(
                "property_type",
                property_type,
                structured.snippets.get("property_type") or property_type,
            )
    else:
        property_pairs = _label_values(lines, _PROPERTY_TYPE_LABELS)
        property_candidates = [
            (value, snippet)
            for _, value, snippet in property_pairs
            if any(marker in _fold(value) for marker in _BUILDING_PLOT_MARKERS)
        ]
        if not property_candidates:
            property_candidates = [
                (heading, heading)
                for heading in parser.headings
                if any(marker in _fold(heading) for marker in _BUILDING_PLOT_MARKERS)
            ]
        property_type, _ = _unique(
            [value for value, _ in property_candidates]
        )
        if property_type:
            property_snippet = next(
                snippet
                for value, snippet in property_candidates
                if _fold(value) == _fold(property_type)
            )
            record("property_type", property_type, property_snippet)

    bound_contact: _BoundContactRecipient | None = None
    if structured is not None:
        recipient_name = structured.values.get("recipient_name")
        if recipient_name:
            record(
                "recipient_name",
                recipient_name,
                structured.snippets.get("recipient_name") or recipient_name,
            )
    else:
        bound_contact = _bound_contact_recipient(parser)
        reasons.extend(bound_contact.reasons)
        recipient_name = bound_contact.name
        if recipient_name:
            record(
                "recipient_name",
                recipient_name,
                bound_contact.name_snippet or recipient_name,
            )

    if structured is not None:
        recipient_role = structured.values.get("recipient_role")
        if recipient_role:
            record(
                "recipient_role",
                recipient_role,
                structured.snippets.get("recipient_role") or recipient_role,
            )
    else:
        assert bound_contact is not None
        recipient_role = bound_contact.role
        if recipient_role:
            record(
                "recipient_role",
                recipient_role,
                bound_contact.role_snippet or recipient_role,
            )

    if structured is not None:
        recipient_email = structured.values.get("recipient_email")
        if recipient_email:
            record(
                "recipient_email",
                recipient_email,
                structured.snippets.get("recipient_email") or recipient_email,
            )
    else:
        assert bound_contact is not None
        recipient_email = bound_contact.email
        if recipient_email:
            record(
                "recipient_email",
                recipient_email,
                bound_contact.email_snippet or recipient_email,
            )

    if bound_contact is not None and recipient_email and recipient_role:
        aggregate_names: list[str] = []
        aggregate_organizations: list[str] = []
        aggregate_offices: list[str] = []
        for screening_block in bound_contact.screening_blocks:
            screening_text = "\n".join(screening_block)
            if contains_no_monitoring_entity(screening_text):
                reasons.append("no_monitoring_hard_gate_blocked")
            block_names = [
                value
                for _, value, _ in _label_values(
                    list(screening_block), _NAME_LABELS
                )
                if _named_recipient(value)
            ]
            block_organizations = [
                value
                for _, value, _ in _label_values(
                    list(screening_block), _ORGANIZATION_LABELS
                )
            ]
            block_offices = [
                value
                for _, value, _ in _label_values(
                    list(screening_block), _OFFICE_LABELS
                )
            ]
            aggregate_names.extend(block_names)
            aggregate_organizations.extend(block_organizations)
            aggregate_offices.extend(block_offices)
            exclusion_reason = land_agent_hard_gate_reason(
                recipient_role=recipient_role,
                contact_name=" ".join(block_names) or recipient_name,
                organization_name=" ".join(block_organizations) or None,
                office_name=" ".join(block_offices) or None,
                recipient_email=recipient_email,
                public_contact_url=canonical_url,
                evidence_url=canonical_url,
            )
            if exclusion_reason:
                reasons.append(exclusion_reason)
        aggregate_exclusion_reason = land_agent_hard_gate_reason(
            recipient_role=recipient_role,
            contact_name=" ".join(aggregate_names) or recipient_name,
            organization_name=" ".join(aggregate_organizations) or None,
            office_name=" ".join(aggregate_offices) or None,
            recipient_email=recipient_email,
            public_contact_url=canonical_url,
            evidence_url=canonical_url,
        )
        if aggregate_exclusion_reason:
            reasons.append(aggregate_exclusion_reason)

    if structured is not None:
        location = structured.values.get("location")
        if location:
            record(
                "location",
                location,
                structured.snippets.get("location") or location,
            )
    else:
        assert bound_contact is not None
        fact_lines = list(bound_contact.fact_lines)
        location_pairs = _label_values(fact_lines, _LOCATION_LABELS)
        location, _ = _unique(
            [value for _, value, _ in location_pairs]
        )
        if location:
            record(
                "location",
                location,
                _source_snippet(location_pairs, location) or location,
            )

    if structured is not None:
        structured_size = structured.values.get("plot_size_sqm")
        plot_size_sqm = (
            int(structured_size)
            if structured_size and structured_size.isdigit()
            else None
        )
        if plot_size_sqm is not None:
            record(
                "plot_size_sqm",
                plot_size_sqm,
                structured.snippets.get("plot_size_sqm") or structured_size or "",
            )
    else:
        assert bound_contact is not None
        fact_lines = list(bound_contact.fact_lines)
        size_pairs = _label_values(fact_lines, _PLOT_SIZE_LABELS)
        parsed_sizes = {
            size
            for _, value, _ in size_pairs
            if (size := _plot_size(value)) is not None
        }
        plot_size_sqm = next(iter(parsed_sizes)) if len(parsed_sizes) == 1 else None
        if plot_size_sqm is not None:
            size_snippet = next(
                (
                    snippet
                    for _, value, snippet in size_pairs
                    if _plot_size(value) == plot_size_sqm
                ),
                str(plot_size_sqm),
            )
            record("plot_size_sqm", plot_size_sqm, size_snippet)

    organization = None
    office = None
    if recipient_role == "listing_agent":
        if structured is not None:
            organization = structured.values.get("recipient_organization_name")
            office = structured.values.get("recipient_office_name")
            if organization:
                record(
                    "recipient_organization_name",
                    organization,
                    structured.snippets.get("recipient_organization_name")
                    or organization,
                )
            if office:
                record(
                    "recipient_office_name",
                    office,
                    structured.snippets.get("recipient_office_name") or office,
                )
        else:
            assert bound_contact is not None
            fact_lines = list(bound_contact.fact_lines)
            organization, organization_ambiguous = _unique(
                [
                    value
                    for _, value, _ in _label_values(
                        fact_lines, _ORGANIZATION_LABELS
                    )
                ]
            )
            office, office_ambiguous = _unique(
                [value for _, value, _ in _label_values(fact_lines, _OFFICE_LABELS)]
            )
            if organization and not organization_ambiguous:
                organization_pairs = _label_values(
                    fact_lines, _ORGANIZATION_LABELS
                )
                record(
                    "recipient_organization_name",
                    organization,
                    _source_snippet(organization_pairs, organization) or organization,
                )
            if office and not office_ambiguous:
                office_pairs = _label_values(fact_lines, _OFFICE_LABELS)
                record(
                    "recipient_office_name",
                    office,
                    _source_snippet(office_pairs, office) or office,
                )

    if not re.fullmatch(r"[0-9a-f]{64}", response_sha256 or ""):
        reasons.append("listing_payload_hash_missing")
    if reasons:
        return ListingDecision(
            None,
            tuple(sorted(set(reasons))),
            evidence_fields,
            tuple(evidence_records),
        )

    assert canonical_url is not None
    recipient_role = cast(Literal["listing_agent", "property_owner"], recipient_role)

    detected_at = attempt.started_at
    if detected_at.tzinfo is None:
        detected_at = detected_at.replace(tzinfo=UTC)
    external_key = hashlib.sha256(
        json.dumps(
            {"portal_listing_url": canonical_url},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    try:
        signal = GrowthSignalIn(
            source_id=source_id,
            external_key=external_key,
            motor_key=MANAGED_LAND_SOURCE_MOTOR,
            source_bucket=MANAGED_LAND_SOURCE_BUCKET,
            signal_type="residential_building_plot",
            detected_at=detected_at,
            company_name=recipient_name,
            company_registration_id=None,
            recipient_organization_name=organization,
            recipient_office_name=office,
            subject_type="natural_person",
            recipient_role=recipient_role,
            recipient_type=(
                "real_estate_agent" if recipient_role == "listing_agent" else "land_owner"
            ),
            recipient_name=recipient_name,
            sender_company_name=None,
            reference_names=[],
            reference_names_verified=False,
            recipient_classification_verified=True,
            exclusion_screening_verified=True,
            recipient_email=recipient_email,
            # A mailbox category is not inferred from its local part. The public
            # listing exception accepts this explicitly unknown classification.
            recipient_email_type="unknown",
            contact_basis="public_property_listing",
            consent_evidence_id=None,
            public_contact_url=canonical_url,
            location=location,
            plot_size_sqm=plot_size_sqm,
            summary=(
                f"Nyilvános építési telek hirdetés: {location}; "
                f"telekméret: {plot_size_sqm} m²."
            ),
            evidence_url=canonical_url,
            brand_id=None,
            # Confidence describes deterministic field completeness. The minimal
            # recency value only denotes a listing fetched in the current daily run;
            # it does not infer seller urgency from marketing language.
            confidence=100,
            urgency=10,
            source_payload_hash=response_sha256,
        )
    except ValidationError:
        return ListingDecision(
            None,
            ("growth_signal_schema_rejected",),
            evidence_fields,
            tuple(evidence_records),
        )
    return ListingDecision(signal, (), evidence_fields, tuple(evidence_records))


def process_public_land_listings(
    db: Session,
    *,
    route: SourceCoverageRoute,
    attempt: SourceCoverageAttempt,
    listing_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    if not listing_pages:
        return {"status": "completed", "examined": 0, "qualified": 0, "queued": 0}
    try:
        source_id = _managed_land_source_id()
    except GrowthRegistryError as exc:
        return {
            "status": "blocked",
            "examined": len(listing_pages),
            "qualified": 0,
            "queued": 0,
            "decisions": [{"reasons": [str(exc)]}],
        }

    from .service import ingest_signal

    decisions: list[dict[str, Any]] = []
    qualified = 0
    queued = 0
    idempotent = 0
    for page in listing_pages:
        decision = listing_signal_decision(
            route=route,
            attempt=attempt,
            listing_url=str(page.get("url") or ""),
            html=str(page.get("html") or ""),
            response_sha256=str(page.get("response_sha256") or ""),
            source_id=source_id,
        )
        public_url = _canonical_https_url(page.get("url"))
        item: dict[str, Any] = {
            "listing_url": public_url,
            "reasons": list(decision.reasons),
        }
        if decision.signal is None:
            decisions.append(item)
            continue
        qualified += 1
        try:
            receipt: GrowthSignalReceipt = ingest_signal(
                db,
                decision.signal,
                run_id=attempt.run_id,
                source_evidence=[
                    {
                        **record,
                        "source_url": decision.signal.evidence_url,
                        "snapshot_sha256": decision.signal.source_payload_hash,
                        "fetched_at": (
                            attempt.completed_at
                            if attempt.completed_at.tzinfo
                            else attempt.completed_at.replace(tzinfo=UTC)
                        ),
                    }
                    for record in decision.evidence_records
                ],
            )
        except (GrowthRegistryError, ValueError) as exc:
            item["reasons"] = [str(exc)]
            item["status"] = "blocked"
        else:
            item.update(
                {
                    "status": receipt.status,
                    "idempotent": receipt.idempotent,
                    "signal_id": receipt.signal_id,
                    "outreach_id": receipt.outreach_id,
                    "reasons": receipt.reasons,
                }
            )
            if receipt.idempotent:
                idempotent += 1
            if receipt.status == "queued" and receipt.outreach_id:
                queued += 1
        decisions.append(item)
    return {
        "status": "completed",
        "examined": len(listing_pages),
        "qualified": qualified,
        "queued": queued,
        "idempotent": idempotent,
        "decisions": decisions,
    }


@dataclass(frozen=True)
class LiveListingRevalidation:
    rejection_reason: str | None
    audit_evidence: dict[str, Any]


def _normalized_live_value(field_name: str, value: object) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", str(value or "")).split())
    if field_name == "listing_permalink":
        return _canonical_https_url(normalized) or ""
    if field_name in {"recipient_email", "recipient_role"}:
        return normalized.casefold()
    if field_name == "plot_size_sqm":
        return str(int(normalized)) if normalized.isdigit() else ""
    return normalized.casefold()


def live_listing_revalidation(db: Session, signal: GrowthSignal) -> LiveListingRevalidation:
    """Re-identify the live URL plus bound recipient email and role for dispatch."""

    checked_at = datetime.now(UTC)

    def result(
        reason: str | None,
        *,
        response_sha256: str | None = None,
        records: list[dict[str, str]] | None = None,
    ) -> LiveListingRevalidation:
        evidence_records = []
        for record in records or []:
            snippet = str(record.get("source_snippet") or "")[:2_000]
            evidence_records.append(
                {
                    "field_name": str(record.get("field_name") or ""),
                    "observed_value": str(record.get("observed_value") or ""),
                    "source_snippet": snippet,
                    "snippet_sha256": hashlib.sha256(snippet.encode("utf-8")).hexdigest(),
                }
            )
        return LiveListingRevalidation(
            rejection_reason=reason,
            audit_evidence={
                "status": "blocked" if reason else "passed",
                "rejection_reason": reason,
                "source_url": signal.evidence_url,
                "fetched_at": checked_at.isoformat(),
                "response_sha256": response_sha256,
                "critical_fields": evidence_records,
            },
        )

    required = {
        "listing_permalink": str(signal.public_contact_url or ""),
        "recipient_email": str(signal.recipient_email or ""),
        "recipient_role": signal.recipient_role,
    }
    live_expected = dict(required)
    if signal.company_name:
        live_expected["recipient_name"] = str(signal.company_name)
    if signal.recipient_role == "property_owner":
        live_expected.update(
            {
                "location": str(signal.location or ""),
                "plot_size_sqm": str(signal.plot_size_sqm or ""),
            }
        )
    rows = list(
        db.scalars(
            select(GrowthSignalSourceEvidence).where(
                GrowthSignalSourceEvidence.signal_id == signal.signal_id
            )
        )
    )
    by_field = {row.field_name: row for row in rows}
    if not set(live_expected).issubset(by_field):
        return result("public_land_live_source_evidence_missing")
    snapshot_hashes = {row.snapshot_sha256 for row in rows}
    if len(snapshot_hashes) != 1 or snapshot_hashes != {signal.source_payload_hash}:
        return result("public_land_live_snapshot_binding_mismatch")
    for field_name, expected in live_expected.items():
        row = by_field[field_name]
        if (
            row.observed_value != expected
            or row.source_url != signal.evidence_url
            or not row.source_snippet
            or hashlib.sha256(row.source_snippet.encode("utf-8")).hexdigest()
            != row.snippet_sha256
            or row.fetched_at is None
        ):
            return result(f"public_land_live_evidence_binding_mismatch:{field_name}")

    from .catalog import fetch_public_land_listing_url

    fetch_result = fetch_public_land_listing_url(signal.evidence_url)
    if fetch_result.get("status") != "succeeded":
        unavailable = str(
            fetch_result.get("error_type")
            or fetch_result.get("status")
            or "unavailable"
        )
        return LiveListingRevalidation(
            rejection_reason=f"public_land_live_listing_unavailable:{unavailable}",
            audit_evidence={
                "status": "blocked",
                "rejection_reason": (
                    f"public_land_live_listing_unavailable:{unavailable}"
                ),
                "source_url": signal.evidence_url,
                "fetched_at": checked_at.isoformat(),
                "response_sha256": fetch_result.get("response_sha256"),
                "critical_fields": [],
            },
        )
    current_hash = str(fetch_result.get("response_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", current_hash):
        return result("public_land_live_response_hash_missing")
    if _canonical_https_url(fetch_result.get("url")) != signal.evidence_url:
        return result(
            "public_land_live_listing_url_binding_mismatch",
            response_sha256=current_hash,
        )

    attempt = SourceCoverageAttempt(
        attempt_id="LIVE-REVALIDATION",
        route_key="LIVE-REVALIDATION",
        catalog_sha256="0" * 64,
        run_id=None,
        status="succeeded",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    route = SourceCoverageRoute(
        route_key="LIVE-REVALIDATION",
        route_id="LIVE-REVALIDATION",
        catalog_sha256="0" * 64,
        motor="construction",
        route_url=signal.evidence_url,
        source_row_sha256="0" * 64,
        source_record_json="{}",
    )
    decision = listing_signal_decision(
        route=route,
        attempt=attempt,
        listing_url=signal.evidence_url,
        html=str(fetch_result.get("html") or ""),
        response_sha256=current_hash,
        source_id=signal.source_id,
    )
    if decision.signal is None:
        positive_hard_gate = next(
            (
                reason
                for reason in decision.reasons
                if reason in LAND_AGENT_HARD_GATE_REASONS
                or reason == "no_monitoring_hard_gate_blocked"
                or reason.startswith("canonical_hard_gate_blocked:")
            ),
            None,
        )
        return result(
            positive_hard_gate
            or "public_land_live_evidence_missing:" + ",".join(decision.reasons),
            response_sha256=current_hash,
            records=list(decision.evidence_records),
        )
    # Optional affiliation fields are not eligibility prerequisites, but any
    # positively identified exclusion appearing on the fresh listing remains a
    # non-overridable NO_SEND gate. Re-run the complete canonical screening on
    # the newly fetched signal before comparing only the rendered fields.
    from .canonical_templates import CanonicalFirstContactRegistry
    from .service import _incoming_hard_gate_reason

    fresh_hard_gate = _incoming_hard_gate_reason(
        decision.signal,
        CanonicalFirstContactRegistry.load(),
    )
    if fresh_hard_gate:
        return result(
            fresh_hard_gate,
            response_sha256=current_hash,
            records=list(decision.evidence_records),
        )
    for field_name, expected in live_expected.items():
        if _normalized_live_value(
            field_name, decision.evidence_fields.get(field_name)
        ) != _normalized_live_value(field_name, expected):
            return result(
                f"public_land_live_evidence_changed:{field_name}",
                response_sha256=current_hash,
                records=list(decision.evidence_records),
            )
    return result(
        None,
        response_sha256=current_hash,
        records=list(decision.evidence_records),
    )


def live_listing_rejection_reason(db: Session, signal: GrowthSignal) -> str | None:
    """Compatibility wrapper for callers that only need the NO_SEND reason."""

    return live_listing_revalidation(db, signal).rejection_reason
