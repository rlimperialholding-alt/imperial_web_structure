from __future__ import annotations

import base64
import hashlib
import html
import http.client
import json
import re
import smtplib
import ssl
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .canonical_policy import ACTIVE_CONTENT_BRANDS
from .registry import BrandBinding, GrowthRegistryError
from .registry import settings as growth_settings

HARD_BLOCKED_RECIPIENT_DOMAINS = {
    "leier.hu",
    "leier.eu",
    "leier.at",
    "leier.com",
}

SENDER_DOMAIN_BRANDS = {
    "imperialholding.hu": "imperial",
    "prefab.hu": "prefab",
    "bautica.hu": "bautica",
    "baufreund.hu": "baufreund",
    "danishfabrik.hu": "danish-fabrik",
    "timberhaus.hu": "timberhaus",
}

BRAND_IDENTITY_TERMS = {
    "imperial": ("Imperial Holding", "Imperial"),
    "prefab": ("Prefab.hu", "Prefab"),
    "bautica": ("Bautica",),
    "casa-moderna": ("Casa Moderna", "CasaModerna", "casamoderna.hu"),
    "baufreund": ("BauFreund", "Bau Freund"),
    "danish-fabrik": ("Danish Fabrik", "DanishFabrik", "danishfabrik.hu"),
    "timberhaus": ("TimberHaus", "Timber Haus"),
    "red-property": ("RED Property", "REDProperty", "redproperty.hu"),
    "property-360": ("Property360", "Property 360"),
    "everyday-homes": ("Everyday Homes", "EverydayHomes"),
    "venture-studio": ("Venture Studio", "VentureStudio"),
    "family-homes": ("Family Homes", "FamilyHomes"),
    "imperial-construction": (
        "Imperial Construction",
        "ImperialConstruction",
        "Budapesti Magasépítő Vállalat",
        "Budapesti Magasepito Vallalat",
        "budapesti-magasepito-vallalat",
        "budapestimagasepito",
    ),
    "imperial-intelligence": ("Imperial Intelligence", "ImperialIntelligence"),
    "imperial-technologies": ("Imperial Technologies", "ImperialTechnologies"),
    "imperial-knowledge": ("Imperial Knowledge", "ImperialKnowledge"),
    "exit-flow": ("ExitFlow", "Exit Flow"),
    "veritas-construct": ("Veritas Construct", "VeritasConstruct", "Veritas"),
    "bau-shield": ("BauShield", "Bau Shield"),
}

ACTIVE_CONTENT_BRAND_TERM_KEYS = {
    "Imperial": "imperial",
    "Prefab": "prefab",
    "Bautica": "bautica",
    "Casa Moderna": "casa-moderna",
    "BauFreund": "baufreund",
    "Danish Fabrik": "danish-fabrik",
    "TimberHaus": "timberhaus",
    "RED Property": "red-property",
    "Property360": "property-360",
    "Everyday Homes": "everyday-homes",
    "Venture Studio": "venture-studio",
    "Family Homes": "family-homes",
    "Imperial Construction": "imperial-construction",
    "Imperial Intelligence": "imperial-intelligence",
    "Imperial Technologies": "imperial-technologies",
    "Imperial Knowledge": "imperial-knowledge",
    "ExitFlow": "exit-flow",
    "Veritas Construct": "veritas-construct",
    "BauShield": "bau-shield",
}

if set(ACTIVE_CONTENT_BRAND_TERM_KEYS) != set(ACTIVE_CONTENT_BRANDS) or set(
    ACTIVE_CONTENT_BRAND_TERM_KEYS.values()
) != set(BRAND_IDENTITY_TERMS):
    raise RuntimeError("customer-facing brand identity inventory is incomplete")

DELIVERY_SCOPE_EXTERNAL_CUSTOMER = "external_customer"
DELIVERY_SCOPE_INTERNAL = "internal"
INTERNAL_EMAIL_DOMAIN = "imperialholding.hu"
ADDR_SPEC_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$"
)
GMAIL_OAUTH_FIELDS = {"client_id", "client_secret", "refresh_token", "scope"}
GMAIL_READ_SCOPE_SUFFIXES = (
    "/gmail.readonly",
    "/gmail.modify",
    "/mail.google.com/",
)


class _VisibleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []

    def handle_data(self, data: str) -> None:
        self.fragments.append(data)


class _GmailReadbackError(ValueError):
    pass


def _html_visible_text(value: str | None) -> str:
    if not value:
        return ""
    parser = _VisibleHTMLParser()
    try:
        parser.feed(html.unescape(value))
        parser.close()
    except (ValueError, AssertionError):
        return html.unescape(value)
    return "".join(parser.fragments)


def _canonical_addr_spec(value: str, *, field: str) -> str:
    address = str(value or "")
    if (
        not address
        or address != address.strip()
        or "\r" in address
        or "\n" in address
        or not ADDR_SPEC_RE.fullmatch(address)
        or ".." in address
    ):
        raise GrowthRegistryError(f"{field}_must_be_one_canonical_addr_spec_no_send")
    local, domain = address.rsplit("@", 1)
    if (
        local.startswith(".")
        or local.endswith(".")
        or domain.startswith(".")
        or domain.endswith(".")
        or any(
            not label or label.startswith("-") or label.endswith("-") for label in domain.split(".")
        )
    ):
        raise GrowthRegistryError(f"{field}_must_be_one_canonical_addr_spec_no_send")
    return address


def _normalize_customer_facing(value: object) -> str:
    without_format_chars = "".join(
        char for char in str(value or "") if unicodedata.category(char) != "Cf"
    )
    decomposed = unicodedata.normalize("NFKD", without_format_chars)
    ascii_like = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", ascii_like.casefold()).split())


def _email_domain(value: str) -> str:
    address = str(value or "").strip().lower()
    return address.rsplit("@", 1)[1].rstrip(".") if "@" in address else ""


def _assert_recipient_not_hard_blocked(to_email: str) -> None:
    recipient_domain = _email_domain(to_email)
    normalized_contact = _normalize_customer_facing(to_email)
    if (
        "leier" in normalized_contact.split()
        or "leier" in to_email.casefold()
        or recipient_domain in HARD_BLOCKED_RECIPIENT_DOMAINS
        or any(
            recipient_domain.endswith(f".{blocked}") for blocked in HARD_BLOCKED_RECIPIENT_DOMAINS
        )
    ):
        raise GrowthRegistryError(
            "outbound_recipient_hard_gate_no_send:BLOCK_LEIER_INCIDENT_CONTAINMENT"
        )


def _assert_customer_facing_outbound_allowed(
    *,
    binding: BrandBinding,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None,
    attachments: list[tuple[str, bytes, str]] | None,
    reply_to: str | None = None,
) -> None:
    sender_email = _canonical_addr_spec(binding.sender_email, field="sender_email")
    to_email = _canonical_addr_spec(to_email, field="recipient_email")
    if reply_to:
        reply_to = _canonical_addr_spec(reply_to, field="reply_to")
    _assert_recipient_not_hard_blocked(to_email)
    if attachments:
        raise GrowthRegistryError("external_customer_attachments_no_send")
    sender_domain = _email_domain(sender_email)
    sender_brand = SENDER_DOMAIN_BRANDS.get(sender_domain)
    if sender_brand is None or sender_brand not in BRAND_IDENTITY_TERMS:
        raise GrowthRegistryError("outbound_sender_brand_unknown_no_send")
    if sender_brand != binding.brand_id:
        raise GrowthRegistryError("outbound_sender_brand_binding_mismatch_no_send")
    if reply_to:
        reply_to_brand = SENDER_DOMAIN_BRANDS.get(_email_domain(reply_to))
        if reply_to_brand is None or reply_to_brand != sender_brand:
            raise GrowthRegistryError("outbound_reply_to_brand_mismatch_no_send")
    content_visible = "\n".join(
        [
            subject,
            body_text,
            html.unescape(body_html or ""),
            _html_visible_text(body_html),
        ]
    )
    screening_visible = "\n".join(
        [
            content_visible,
            to_email,
            _email_domain(to_email),
            reply_to or "",
            "\n".join(filename for filename, _, _ in attachments or []),
        ]
    )
    normalized = f" {_normalize_customer_facing(screening_visible)} "
    forbidden: list[str] = []
    for brand_key, terms in BRAND_IDENTITY_TERMS.items():
        if brand_key == sender_brand:
            continue
        for term in terms:
            normalized_term = _normalize_customer_facing(term)
            if normalized_term and f" {normalized_term} " in normalized:
                forbidden.append(term)
                break
    if forbidden:
        raise GrowthRegistryError(
            "cross_brand_customer_facing_content_no_send:" + ",".join(forbidden)
        )
    content_normalized = f" {_normalize_customer_facing(content_visible)} "
    own_identity_terms = BRAND_IDENTITY_TERMS[sender_brand]
    if not any(
        f" {_normalize_customer_facing(term)} " in content_normalized for term in own_identity_terms
    ):
        raise GrowthRegistryError("outbound_required_brand_identity_missing_no_send")


def _assert_internal_outbound_allowed(
    *,
    binding: BrandBinding,
    to_email: str,
    reply_to: str | None = None,
) -> None:
    _canonical_addr_spec(binding.sender_email, field="sender_email")
    to_email = _canonical_addr_spec(to_email, field="recipient_email")
    if reply_to:
        reply_to = _canonical_addr_spec(reply_to, field="reply_to")
    _assert_recipient_not_hard_blocked(to_email)
    if (
        binding.brand_id != "imperial"
        or _email_domain(binding.sender_email) != INTERNAL_EMAIL_DOMAIN
    ):
        raise GrowthRegistryError("internal_sender_brand_binding_mismatch_no_send")
    if _email_domain(to_email) != INTERNAL_EMAIL_DOMAIN:
        raise GrowthRegistryError("internal_recipient_domain_no_send")
    if reply_to and _email_domain(reply_to) != INTERNAL_EMAIL_DOMAIN:
        raise GrowthRegistryError("internal_reply_to_domain_no_send")


def _assert_external_transport_window_open() -> None:
    config = growth_settings()
    try:
        zone = ZoneInfo(config.timezone)
        start = time.fromisoformat(config.outreach_send_start_local)
        end = time.fromisoformat(config.outreach_send_end_local)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise GrowthRegistryError("Configured outreach sending window is invalid") from exc
    if start >= end:
        raise GrowthRegistryError("Outreach sending window must start before it ends")
    local_time = datetime.now(zone).time().replace(tzinfo=None)
    if not start <= local_time < end:
        raise GrowthRegistryError("outreach_sending_window_closed_no_send")


def _single_header(message: EmailMessage, name: str) -> str:
    values = message.get_all(name, [])
    if len(values) != 1:
        raise _GmailReadbackError(f"gmail_readback_{name.lower()}_header_count")
    return str(values[0])


def _text_bodies(message: EmailMessage) -> tuple[str, str | None]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type()
        disposition = part.get_content_disposition()
        if disposition in {"attachment", "inline"} or part.get_filename() is not None:
            continue
        if content_type not in {"text/plain", "text/html"}:
            raise _GmailReadbackError("gmail_readback_unexpected_mime_part")
        try:
            content = part.get_content()
        except (LookupError, UnicodeError, ValueError) as exc:
            raise _GmailReadbackError("gmail_readback_mime_decode_failed") from exc
        if not isinstance(content, str):
            raise _GmailReadbackError("gmail_readback_non_text_body")
        if content_type == "text/plain":
            plain_parts.append(content)
        else:
            html_parts.append(content)
    if len(plain_parts) != 1 or len(html_parts) > 1:
        raise _GmailReadbackError("gmail_readback_body_part_count")
    return plain_parts[0], html_parts[0] if html_parts else None


def _attachment_fingerprints(message: EmailMessage) -> list[tuple[str, str, str, str, str]]:
    fingerprints: list[tuple[str, str, str, str, str]] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        if disposition not in {"attachment", "inline"} and filename is None:
            continue
        if disposition not in {"attachment", "inline"} or not filename:
            raise _GmailReadbackError("gmail_readback_attachment_metadata_invalid")
        try:
            payload = part.get_payload(decode=True)
        except (LookupError, UnicodeError, ValueError) as exc:
            raise _GmailReadbackError("gmail_readback_attachment_decode_failed") from exc
        if not isinstance(payload, bytes):
            raise _GmailReadbackError("gmail_readback_attachment_decode_failed")
        fingerprints.append(
            (
                str(filename),
                part.get_content_type(),
                disposition,
                str(part.get("Content-ID") or ""),
                hashlib.sha256(payload).hexdigest(),
            )
        )
    return sorted(fingerprints)


def _verify_gmail_readback(
    *,
    expected: EmailMessage,
    raw_mime: bytes,
) -> tuple[str, str]:
    try:
        returned = BytesParser(policy=policy.default).parsebytes(raw_mime)
    except (TypeError, ValueError) as exc:
        raise _GmailReadbackError("gmail_readback_mime_parse_failed") from exc

    expected_from = _single_header(expected, "From")
    expected_to = _single_header(expected, "To")
    returned_from = _single_header(returned, "From")
    returned_to = _single_header(returned, "To")
    try:
        if _canonical_addr_spec(returned_from, field="readback_from") != expected_from:
            raise _GmailReadbackError("gmail_readback_from_mismatch")
        if _canonical_addr_spec(returned_to, field="readback_to") != expected_to:
            raise _GmailReadbackError("gmail_readback_to_mismatch")
    except GrowthRegistryError as exc:
        raise _GmailReadbackError(str(exc)) from exc

    # Gmail may replace the client supplied RFC Message-ID. It is evidence to
    # record, not a safe equality key. The delivery identity and content hash
    # remain deterministic and must survive the provider round trip.
    for header in ("Subject", "X-Imperial-Idempotency-Key", "X-Imperial-Content-SHA256"):
        if _single_header(returned, header) != _single_header(expected, header):
            raise _GmailReadbackError(f"gmail_readback_{header.lower()}_mismatch")
    for header in ("List-Unsubscribe", "List-Unsubscribe-Post"):
        if returned.get_all(header, []) != expected.get_all(header, []):
            raise _GmailReadbackError(f"gmail_readback_{header.lower()}_mismatch")
    expected_reply_to = expected.get_all("Reply-To", [])
    returned_reply_to = returned.get_all("Reply-To", [])
    if len(expected_reply_to) != len(returned_reply_to):
        raise _GmailReadbackError("gmail_readback_reply-to_header_count")
    if expected_reply_to:
        try:
            if _canonical_addr_spec(
                str(returned_reply_to[0]), field="readback_reply_to"
            ) != _canonical_addr_spec(str(expected_reply_to[0]), field="expected_reply_to"):
                raise _GmailReadbackError("gmail_readback_reply-to_mismatch")
        except GrowthRegistryError as exc:
            raise _GmailReadbackError(str(exc)) from exc
    if returned.get_all("Cc", []) or returned.get_all("Bcc", []):
        raise _GmailReadbackError("gmail_readback_unexpected_cc_or_bcc")

    expected_plain, expected_html = _text_bodies(expected)
    returned_plain, returned_html = _text_bodies(returned)
    if returned_plain != expected_plain:
        raise _GmailReadbackError("gmail_readback_plain_body_mismatch")
    if returned_html != expected_html:
        raise _GmailReadbackError("gmail_readback_html_body_mismatch")
    if _attachment_fingerprints(returned) != _attachment_fingerprints(expected):
        raise _GmailReadbackError("gmail_readback_attachment_mismatch")
    return (
        hashlib.sha256(raw_mime).hexdigest(),
        _single_header(returned, "Message-ID"),
    )


def _verified_gmail_resource(
    *,
    resource: dict[str, Any],
    expected: EmailMessage,
) -> dict[str, Any]:
    labels = resource.get("labelIds")
    if not isinstance(labels, list) or "SENT" not in labels:
        raise _GmailReadbackError("gmail_readback_sent_label_missing")
    internal_date_raw = resource.get("internalDate")
    try:
        internal_date_ms = int(str(internal_date_raw))
        if internal_date_ms <= 0:
            raise ValueError
        provider_internal_date = datetime.fromtimestamp(
            internal_date_ms / 1000,
            tz=UTC,
        )
    except (TypeError, ValueError, OSError, OverflowError) as exc:
        raise _GmailReadbackError("gmail_readback_internal_date_invalid") from exc
    readback_raw = resource.get("raw")
    if not isinstance(readback_raw, str) or not readback_raw:
        raise _GmailReadbackError("gmail_readback_raw_missing")
    try:
        raw_mime = base64.urlsafe_b64decode(readback_raw + "=" * (-len(readback_raw) % 4))
    except (ValueError, TypeError) as exc:
        raise _GmailReadbackError("gmail_readback_raw_invalid") from exc
    readback_mime_sha256, rfc_message_id = _verify_gmail_readback(
        expected=expected,
        raw_mime=raw_mime,
    )
    return {
        "rfc_message_id": rfc_message_id,
        "readback_mime_sha256": readback_mime_sha256,
        "label_ids": labels,
        "provider_internal_date": provider_internal_date.isoformat(),
    }


def _deterministic_message_id(*, idempotency_key: str, sender_domain: str) -> str:
    digest = hashlib.sha256(f"{idempotency_key}\0{sender_domain.lower()}".encode()).hexdigest()
    return f"<imperial-{digest}@{sender_domain.lower()}>"


class EmailDeliveryError(RuntimeError):
    def __init__(
        self,
        error_type: str,
        *,
        retry_safe: bool,
        authentication_failure: bool = False,
        accepted_but_unverified: bool = False,
        transport_attempted: bool = False,
        rate_limited: bool = False,
        retry_after_seconds: float | None = None,
        provider_reason: str | None = None,
        http_status: int | None = None,
        provider_message_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(error_type)
        self.error_type = error_type
        self.retry_safe = retry_safe
        self.authentication_failure = authentication_failure
        self.accepted_but_unverified = accepted_but_unverified
        self.transport_attempted = transport_attempted
        self.rate_limited = rate_limited
        self.retry_after_seconds = retry_after_seconds
        self.provider_reason = provider_reason
        self.http_status = http_status
        self.provider_message_id = provider_message_id
        self.detail = dict(detail or {})


def _http_retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    raw = str(exc.headers.get("Retry-After") or "").strip() if exc.headers else ""
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0.0, (when.astimezone(UTC) - datetime.now(UTC)).total_seconds())


def _gmail_http_error_metadata(exc: urllib.error.HTTPError) -> dict[str, Any]:
    provider_reason = ""
    provider_message = ""
    try:
        payload = json.loads(exc.read(1_000_000))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError):
        payload = {}
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, str):
            provider_reason = error
        elif isinstance(error, dict):
            provider_message = str(error.get("message") or "")
            candidates = error.get("errors")
            if isinstance(candidates, list):
                for candidate in candidates:
                    if isinstance(candidate, dict) and candidate.get("reason"):
                        provider_reason = str(candidate["reason"])
                        break
            provider_reason = provider_reason or str(error.get("status") or "")
    normalized_reason = provider_reason.casefold()
    rate_limited = exc.code == 429 or normalized_reason in {
        "dailylimitexceeded",
        "mailratelimitexceeded",
        "ratelimitexceeded",
        "userratelimitexceeded",
    }
    authentication_failure = exc.code == 401 or normalized_reason in {
        "access_denied",
        "autherror",
        "domainpolicy",
        "forbidden",
        "insufficientpermissions",
        "invalid_client",
        "invalidcredentials",
        "invalid_grant",
        "unauthenticated",
        "unauthorized_client",
    }
    retry_after_seconds = _http_retry_after_seconds(exc)
    return {
        "http_status": int(exc.code),
        "provider_reason": provider_reason or None,
        "provider_message": provider_message or None,
        "rate_limited": rate_limited,
        "authentication_failure": authentication_failure,
        "retry_after_seconds": retry_after_seconds,
    }


@dataclass(frozen=True)
class EmailReceipt:
    provider_message_id: str
    accepted_recipient: str
    provider: str
    response_sha256: str
    detail: dict[str, Any]


@dataclass(frozen=True)
class GmailRolling24hUsage:
    provider_ids: frozenset[str]
    limit: int
    cutoff: datetime
    observed_at: datetime
    pages: int

    @property
    def sent_messages(self) -> int:
        return len(self.provider_ids)

    @property
    def headroom(self) -> int:
        return max(0, self.limit - self.sent_messages)

    @property
    def snapshot_sha256(self) -> str:
        return hashlib.sha256("\n".join(sorted(self.provider_ids)).encode()).hexdigest()


def _gmail_sent_rolling_24h_usage(
    *,
    access_token: str,
    now: datetime | None = None,
) -> GmailRolling24hUsage:
    """Count all mailbox SENT messages in the preceding rolling 24 hours."""

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    cutoff = current - timedelta(hours=24)
    config = growth_settings()
    limit = int(getattr(config, "outreach_account_rolling_24h_max", 2000))
    if not 1 <= limit <= 2000:
        raise GrowthRegistryError("outreach_account_rolling_24h_max_invalid_no_send")

    authorization = {"Authorization": f"Bearer {access_token}"}
    seen_ids: set[str] = set()
    seen_page_tokens: set[str] = set()
    page_token: str | None = None
    pages = 0
    while True:
        params = {
            "labelIds": "SENT",
            # Whole-second epoch boundaries make the scan stable across pages.
            # Including the snapshot second is conservative for concurrent UI
            # sends while excluding all later seconds.
            "q": (
                # Gmail's second-granularity search boundary is widened by
                # one second so a message exactly on the rolling cutoff can
                # never be missed.  The slight overcount is fail-safe.
                f"after:{int(cutoff.timestamp()) - 1} "
                f"before:{int(current.timestamp()) + 1}"
            ),
            "maxResults": "500",
        }
        if page_token:
            params["pageToken"] = page_token
        url = (
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?"
            + urllib.parse.urlencode(params)
        )
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=authorization),
            timeout=30,
        ) as response:
            payload = json.loads(response.read(2_000_000))
        if not isinstance(payload, dict):
            raise _GmailReadbackError("gmail_rolling_24h_list_result_invalid")
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            raise _GmailReadbackError("gmail_rolling_24h_list_result_invalid")
        for candidate in messages:
            if not isinstance(candidate, dict) or not str(candidate.get("id") or ""):
                raise _GmailReadbackError("gmail_rolling_24h_message_id_missing")
            seen_ids.add(str(candidate["id"]))
        pages += 1
        if pages > 100:
            raise _GmailReadbackError("gmail_rolling_24h_pagination_limit_exceeded")
        next_page_token = str(payload.get("nextPageToken") or "")
        if not next_page_token:
            break
        if next_page_token in seen_page_tokens:
            raise _GmailReadbackError("gmail_rolling_24h_pagination_cycle")
        seen_page_tokens.add(next_page_token)
        page_token = next_page_token
    return GmailRolling24hUsage(
        provider_ids=frozenset(seen_ids),
        limit=limit,
        cutoff=cutoff,
        observed_at=current,
        pages=pages,
    )


def _validated_one_click_unsubscribe_url(value: str | None) -> str:
    candidate = str(value or "")
    parsed = urllib.parse.urlsplit(candidate)
    if (
        candidate != candidate.strip()
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise GrowthRegistryError("outbound_https_unsubscribe_url_required_no_send")
    return candidate


class SMTPEmailAdapter:
    def __init__(self, binding: BrandBinding) -> None:
        self.binding = binding
        self.secret = binding.secret

    def preflight(self, *, delivery_scope: str | None = None) -> None:
        account_scoped_delivery = (
            delivery_scope == DELIVERY_SCOPE_EXTERNAL_CUSTOMER
            or (
                delivery_scope == DELIVERY_SCOPE_INTERNAL
                and self.binding.sender_email == "info@imperialholding.hu"
            )
        )
        if account_scoped_delivery and not GMAIL_OAUTH_FIELDS.issubset(self.secret):
            raise GrowthRegistryError("account_scoped_gmail_oauth_required_no_send")
        if GMAIL_OAUTH_FIELDS.issubset(self.secret):
            scopes = str(self.secret.get("scope") or "").split()
            if not any(
                scope.endswith("/gmail.compose") or scope.endswith("/gmail.send")
                for scope in scopes
            ):
                raise GrowthRegistryError("Gmail compose/send OAuth scope is required")
            if account_scoped_delivery and not any(
                scope.endswith(GMAIL_READ_SCOPE_SUFFIXES) for scope in scopes
            ):
                raise GrowthRegistryError("Gmail read OAuth scope is required")
            return
        required = {"host", "port", "username", "password"}
        if required - set(self.secret):
            raise GrowthRegistryError("SMTP secret is incomplete")
        if (
            str(self.secret.get("envelope_from") or self.binding.sender_email).lower()
            != self.binding.sender_email
        ):
            raise GrowthRegistryError("SMTP envelope sender conflicts with the brand sender")
        if not self.secret.get("use_ssl") and not self.secret.get("starttls"):
            raise GrowthRegistryError("Encrypted SMTP transport is required")

    def live_preflight(self, *, delivery_scope: str) -> dict[str, str]:
        """Verify the external Gmail identity without creating a message."""
        self.preflight(delivery_scope=delivery_scope)
        if delivery_scope != DELIVERY_SCOPE_EXTERNAL_CUSTOMER:
            return {"provider": "smtp"}
        token_body = urllib.parse.urlencode(
            {
                "client_id": self.secret["client_id"],
                "client_secret": self.secret["client_secret"],
                "refresh_token": self.secret["refresh_token"],
                "grant_type": "refresh_token",
            }
        ).encode()
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    "https://oauth2.googleapis.com/token",
                    data=token_body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ),
                timeout=30,
            ) as response:
                token_payload = json.loads(response.read(1_000_000))
            if not isinstance(token_payload, dict):
                raise ValueError("token response is not an object")
            access_token = str(token_payload.get("access_token") or "")
            if not access_token:
                raise ValueError("access token is missing")
            if str(token_payload.get("token_type") or "").casefold() != "bearer":
                raise GrowthRegistryError(
                    "gmail_live_preflight_token_type_invalid_no_send"
                )
            granted_scopes = str(token_payload.get("scope") or "").split()
            if not any(
                scope.endswith("/gmail.compose") or scope.endswith("/gmail.send")
                for scope in granted_scopes
            ):
                raise GrowthRegistryError(
                    "gmail_live_preflight_granted_send_scope_missing_no_send"
                )
            if not any(
                scope.endswith(GMAIL_READ_SCOPE_SUFFIXES) for scope in granted_scopes
            ):
                raise GrowthRegistryError(
                    "gmail_live_preflight_granted_read_scope_missing_no_send"
                )
            with urllib.request.urlopen(
                urllib.request.Request(
                    "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                    headers={"Authorization": f"Bearer {access_token}"},
                ),
                timeout=30,
            ) as response:
                profile = json.loads(response.read(1_000_000))
            if not isinstance(profile, dict):
                raise ValueError("profile response is not an object")
        except GrowthRegistryError:
            raise
        except urllib.error.HTTPError as exc:
            raise GrowthRegistryError(
                f"gmail_live_preflight_http_{exc.code}_no_send"
            ) from exc
        except (
            OSError,
            urllib.error.URLError,
            http.client.HTTPException,
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            raise GrowthRegistryError(
                f"gmail_live_preflight_{type(exc).__name__}_no_send"
            ) from exc
        profile_email = str(profile.get("emailAddress") or "").strip().lower()
        if profile_email != self.binding.sender_email:
            raise GrowthRegistryError("gmail_live_preflight_sender_mismatch_no_send")
        return {
            "provider": "gmail_api",
            "profile_email": profile_email,
            "granted_scope_verified": "gmail_send_or_compose+gmail_read",
        }

    def _send_gmail_api(
        self,
        *,
        to_email: str,
        message: EmailMessage,
        message_id: str,
        delivery_scope: str,
        reconcile_only: bool = False,
        pre_send_guard: Callable[[], None] | None = None,
        account_quota_guard: Callable[[GmailRolling24hUsage], None] | None = None,
    ) -> EmailReceipt:
        token_body = urllib.parse.urlencode(
            {
                "client_id": self.secret["client_id"],
                "client_secret": self.secret["client_secret"],
                "refresh_token": self.secret["refresh_token"],
                "grant_type": "refresh_token",
            }
        ).encode()
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    "https://oauth2.googleapis.com/token",
                    data=token_body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ),
                timeout=30,
            ) as response:
                token_payload = json.loads(response.read(1_000_000))
            if not isinstance(token_payload, dict):
                raise json.JSONDecodeError("token response is not an object", "", 0)
            access_token = str(token_payload.get("access_token") or "")
            if not access_token:
                raise EmailDeliveryError(
                    "gmail_oauth_access_token_missing",
                    retry_safe=False,
                    authentication_failure=True,
                )
        except urllib.error.HTTPError as exc:
            metadata = _gmail_http_error_metadata(exc)
            raise EmailDeliveryError(
                f"gmail_oauth_http_{exc.code}",
                retry_safe=exc.code >= 500 or bool(metadata["rate_limited"]),
                authentication_failure=bool(metadata["authentication_failure"]),
                rate_limited=bool(metadata["rate_limited"]),
                retry_after_seconds=metadata["retry_after_seconds"],
                provider_reason=metadata["provider_reason"],
                http_status=exc.code,
                detail=metadata,
            ) from exc
        except (
            OSError,
            urllib.error.URLError,
            http.client.HTTPException,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
            raise EmailDeliveryError(
                f"gmail_oauth_pre_send:{type(exc).__name__}", retry_safe=True
            ) from exc

        authorization = {"Authorization": f"Bearer {access_token}"}
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                    headers=authorization,
                ),
                timeout=30,
            ) as response:
                profile = json.loads(response.read(1_000_000))
            if not isinstance(profile, dict):
                raise json.JSONDecodeError("profile response is not an object", "", 0)
            profile_email = str(profile.get("emailAddress") or "").strip().lower()
            if profile_email != self.binding.sender_email:
                raise EmailDeliveryError(
                    "gmail_oauth_profile_sender_mismatch_no_send",
                    retry_safe=False,
                    authentication_failure=True,
                    detail={"profile_email": profile_email},
                )
        except EmailDeliveryError:
            raise
        except urllib.error.HTTPError as exc:
            metadata = _gmail_http_error_metadata(exc)
            raise EmailDeliveryError(
                f"gmail_oauth_profile_http_{exc.code}",
                retry_safe=exc.code >= 500 or bool(metadata["rate_limited"]),
                authentication_failure=bool(metadata["authentication_failure"]),
                rate_limited=bool(metadata["rate_limited"]),
                retry_after_seconds=metadata["retry_after_seconds"],
                provider_reason=metadata["provider_reason"],
                http_status=exc.code,
                detail=metadata,
            ) from exc
        except (
            OSError,
            urllib.error.URLError,
            http.client.HTTPException,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
            raise EmailDeliveryError(
                f"gmail_oauth_profile_pre_send:{type(exc).__name__}",
                retry_safe=True,
            ) from exc

        idempotency_key = _single_header(message, "X-Imperial-Idempotency-Key")
        existing_provider_id: str | None = None
        existing_provider_id_is_strong = False
        try:
            candidate_ids: list[str] = []
            strong_candidate_ids: list[str] = []
            escaped_subject = str(message["Subject"]).replace('"', "")
            for query_index, query in enumerate(
                (
                    f"in:sent rfc822msgid:{message_id}",
                    f'in:sent "{idempotency_key}"',
                    f'in:sent to:{to_email} subject:"{escaped_subject}"',
                )
            ):
                search_url = (
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages?"
                    + urllib.parse.urlencode({"q": query, "maxResults": 10})
                )
                with urllib.request.urlopen(
                    urllib.request.Request(search_url, headers=authorization),
                    timeout=30,
                ) as response:
                    search_result = json.loads(response.read(1_000_000))
                if not isinstance(search_result, dict):
                    raise _GmailReadbackError("gmail_pre_send_search_result_invalid")
                candidates = search_result.get("messages", [])
                if not isinstance(candidates, list):
                    raise _GmailReadbackError("gmail_pre_send_search_result_invalid")
                query_candidate_ids = [
                    str(candidate.get("id") or "")
                    for candidate in candidates
                    if isinstance(candidate, dict)
                ]
                if any(not candidate_id for candidate_id in query_candidate_ids):
                    raise _GmailReadbackError("gmail_pre_send_candidate_id_missing")
                candidate_ids = list(dict.fromkeys([*candidate_ids, *query_candidate_ids]))
                if query_index < 2:
                    strong_candidate_ids = list(
                        dict.fromkeys([*strong_candidate_ids, *query_candidate_ids])
                    )
            verified_candidates: list[tuple[str, dict[str, Any]]] = []
            for candidate_id in candidate_ids:
                existing_provider_id = candidate_id
                existing_provider_id_is_strong = candidate_id in strong_candidate_ids
                existing_url = (
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
                    f"{urllib.parse.quote(candidate_id, safe='')}?format=raw"
                )
                with urllib.request.urlopen(
                    urllib.request.Request(existing_url, headers=authorization),
                    timeout=30,
                ) as response:
                    existing_resource = json.loads(response.read(10_000_000))
                if not isinstance(existing_resource, dict):
                    raise _GmailReadbackError("gmail_readback_resource_invalid")
                try:
                    existing_detail = _verified_gmail_resource(
                        resource=existing_resource,
                        expected=message,
                    )
                except _GmailReadbackError:
                    continue
                verified_candidates.append((candidate_id, existing_detail))
            if len(verified_candidates) > 1:
                existing_provider_id = verified_candidates[0][0]
                existing_provider_id_is_strong = True
                raise _GmailReadbackError("gmail_pre_send_multiple_exact_candidates")
            if verified_candidates:
                existing_provider_id, existing_detail = verified_candidates[0]
                existing_detail.update(
                    {
                        "accepted": True,
                        "readback_verified": True,
                        "provider_message_id": existing_provider_id,
                        "outbound_rfc_message_id": message_id,
                        "oauth_profile_email": profile_email,
                        "recovered_existing_sent": True,
                    }
                )
                return EmailReceipt(
                    provider_message_id=existing_provider_id,
                    accepted_recipient=to_email,
                    provider="gmail_api",
                    response_sha256=str(existing_detail["readback_mime_sha256"]),
                    detail=existing_detail,
                )
            if strong_candidate_ids:
                existing_provider_id = strong_candidate_ids[0]
                existing_provider_id_is_strong = True
                raise _GmailReadbackError("gmail_existing_delivery_identity_payload_mismatch")
            existing_provider_id = None
            if reconcile_only:
                raise EmailDeliveryError(
                    "accepted_but_unverified",
                    retry_safe=False,
                    accepted_but_unverified=True,
                    detail={"reason": "gmail_reconcile_no_exact_message_no_send"},
                )
        except urllib.error.HTTPError as exc:
            metadata = _gmail_http_error_metadata(exc)
            if existing_provider_id is None or not existing_provider_id_is_strong:
                raise EmailDeliveryError(
                    "pre_send_verification_failed_no_send",
                    retry_safe=exc.code >= 500 or bool(metadata["rate_limited"]),
                    authentication_failure=bool(metadata["authentication_failure"]),
                    rate_limited=bool(metadata["rate_limited"]),
                    retry_after_seconds=metadata["retry_after_seconds"],
                    provider_reason=metadata["provider_reason"],
                    http_status=exc.code,
                    detail={
                        **metadata,
                        "reason": f"gmail_pre_send_search_http_{exc.code}",
                    },
                ) from exc
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                authentication_failure=bool(metadata["authentication_failure"]),
                accepted_but_unverified=True,
                rate_limited=bool(metadata["rate_limited"]),
                retry_after_seconds=metadata["retry_after_seconds"],
                provider_reason=metadata["provider_reason"],
                http_status=exc.code,
                provider_message_id=existing_provider_id,
                detail={
                    **metadata,
                    "reason": f"gmail_pre_send_search_http_{exc.code}",
                    "provider_message_id": existing_provider_id,
                },
            ) from exc
        except (
            OSError,
            urllib.error.URLError,
            http.client.HTTPException,
            json.JSONDecodeError,
            UnicodeDecodeError,
            _GmailReadbackError,
        ) as exc:
            if existing_provider_id is None or not existing_provider_id_is_strong:
                raise EmailDeliveryError(
                    "pre_send_verification_failed_no_send",
                    retry_safe=True,
                    detail={"reason": str(exc)},
                ) from exc
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
                provider_message_id=existing_provider_id,
                detail={
                    "reason": str(exc),
                    "provider_message_id": existing_provider_id,
                },
            ) from exc

        raw = base64.urlsafe_b64encode(message.as_bytes()).rstrip(b"=").decode("ascii")
        send_body = json.dumps({"raw": raw}, separators=(",", ":")).encode()
        if delivery_scope == DELIVERY_SCOPE_EXTERNAL_CUSTOMER:
            _assert_external_transport_window_open()
        if pre_send_guard is None:
            raise GrowthRegistryError("external_customer_pre_send_guard_required_no_send")
        pre_send_guard()
        # Capacity verification may perform database work. Re-read the
        # authoritative clock after it so the window check is the final local
        # operation before the Gmail transport POST.
        if delivery_scope == DELIVERY_SCOPE_EXTERNAL_CUSTOMER:
            _assert_external_transport_window_open()
        try:
            quota_usage = _gmail_sent_rolling_24h_usage(access_token=access_token)
        except urllib.error.HTTPError as exc:
            metadata = _gmail_http_error_metadata(exc)
            raise EmailDeliveryError(
                "gmail_account_quota_verification_failed_no_send",
                retry_safe=exc.code >= 500 or bool(metadata["rate_limited"]),
                authentication_failure=bool(metadata["authentication_failure"]),
                rate_limited=bool(metadata["rate_limited"]),
                retry_after_seconds=metadata["retry_after_seconds"],
                provider_reason=metadata["provider_reason"],
                http_status=exc.code,
                detail={
                    **metadata,
                    "reason": f"gmail_rolling_24h_list_http_{exc.code}",
                },
            ) from exc
        except (
            OSError,
            urllib.error.URLError,
            http.client.HTTPException,
            json.JSONDecodeError,
            UnicodeDecodeError,
            _GmailReadbackError,
        ) as exc:
            raise EmailDeliveryError(
                "gmail_account_quota_verification_failed_no_send",
                retry_safe=True,
                detail={"reason": str(exc)},
            ) from exc
        if quota_usage.headroom <= 0:
            raise EmailDeliveryError(
                "gmail_account_rolling_24h_limit_reached_no_send",
                retry_safe=True,
                rate_limited=True,
                retry_after_seconds=900,
                detail={
                    "sent_messages": quota_usage.sent_messages,
                    "limit": quota_usage.limit,
                    "cutoff": quota_usage.cutoff.isoformat(),
                    "pages": quota_usage.pages,
                    "retry_after_seconds": 900,
                },
            )
        if account_quota_guard is None:
            raise GrowthRegistryError("external_customer_account_quota_guard_required_no_send")
        account_quota_guard(quota_usage)
        if delivery_scope == DELIVERY_SCOPE_EXTERNAL_CUSTOMER:
            _assert_external_transport_window_open()
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                    data=send_body,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                ),
                timeout=30,
            ) as response:
                sent_response = response.read(1_000_000)
        except urllib.error.HTTPError as exc:
            metadata = _gmail_http_error_metadata(exc)
            ambiguous_server_failure = (
                exc.code == 408 or exc.code >= 500
            ) and not metadata["rate_limited"]
            raise EmailDeliveryError(
                (
                    "accepted_but_unverified"
                    if ambiguous_server_failure
                    else "gmail_api_rate_limited"
                    if metadata["rate_limited"]
                    else f"gmail_api_http_{exc.code}"
                ),
                retry_safe=bool(metadata["rate_limited"]),
                authentication_failure=bool(metadata["authentication_failure"]),
                accepted_but_unverified=ambiguous_server_failure,
                transport_attempted=True,
                rate_limited=bool(metadata["rate_limited"]),
                retry_after_seconds=metadata["retry_after_seconds"],
                provider_reason=metadata["provider_reason"],
                http_status=exc.code,
                detail=metadata,
            ) from exc
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
                transport_attempted=True,
                detail={"reason": f"gmail_send_transport_ambiguous:{type(exc).__name__}"},
            ) from exc
        try:
            sent = json.loads(sent_response)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
                transport_attempted=True,
                detail={"reason": "gmail_send_response_invalid"},
            ) from exc
        if not isinstance(sent, dict):
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
                transport_attempted=True,
                detail={"reason": "gmail_send_response_not_an_object"},
            )
        provider_id = str(sent.get("id") or "")
        if not provider_id:
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
                transport_attempted=True,
                detail={"reason": "gmail_api_message_id_missing"},
            )

        readback_url = (
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
            f"{urllib.parse.quote(provider_id, safe='')}?format=raw"
        )
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    readback_url,
                    headers=authorization,
                ),
                timeout=30,
            ) as response:
                readback = json.loads(response.read(10_000_000))
            if not isinstance(readback, dict):
                raise _GmailReadbackError("gmail_readback_resource_invalid")
            readback_detail = _verified_gmail_resource(
                resource=readback,
                expected=message,
            )
        except urllib.error.HTTPError as exc:
            metadata = _gmail_http_error_metadata(exc)
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                authentication_failure=bool(metadata["authentication_failure"]),
                accepted_but_unverified=True,
                transport_attempted=True,
                rate_limited=bool(metadata["rate_limited"]),
                retry_after_seconds=metadata["retry_after_seconds"],
                provider_reason=metadata["provider_reason"],
                http_status=exc.code,
                provider_message_id=provider_id,
                detail={
                    **metadata,
                    "reason": f"gmail_readback_http_{exc.code}",
                    "provider_message_id": provider_id,
                },
            ) from exc
        except (
            OSError,
            urllib.error.URLError,
            http.client.HTTPException,
            json.JSONDecodeError,
            UnicodeDecodeError,
            _GmailReadbackError,
        ) as exc:
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
                transport_attempted=True,
                provider_message_id=provider_id,
                detail={"reason": str(exc), "provider_message_id": provider_id},
            ) from exc

        return EmailReceipt(
            provider_message_id=provider_id,
            accepted_recipient=to_email,
            provider="gmail_api",
            response_sha256=str(readback_detail["readback_mime_sha256"]),
            detail={
                **readback_detail,
                "accepted": True,
                "readback_verified": True,
                "provider_message_id": provider_id,
                "outbound_rfc_message_id": message_id,
                "oauth_profile_email": profile_email,
                "recovered_existing_sent": False,
                "account_rolling_24h": {
                    "sent_messages_before_send": quota_usage.sent_messages,
                    "limit": quota_usage.limit,
                    "headroom_before_send": quota_usage.headroom,
                    "cutoff": quota_usage.cutoff.isoformat(),
                    "pages": quota_usage.pages,
                },
            },
        )

    def send(
        self,
        *,
        to_email: str,
        subject: str,
        body_text: str,
        idempotency_key: str,
        delivery_scope: str,
        reconcile_only: bool = False,
        body_html: str | None = None,
        reply_to: str | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
        pre_send_guard: Callable[[], None] | None = None,
        account_quota_guard: Callable[[GmailRolling24hUsage], None] | None = None,
        unsubscribe_url: str | None = None,
    ) -> EmailReceipt:
        if delivery_scope == DELIVERY_SCOPE_EXTERNAL_CUSTOMER:
            _assert_customer_facing_outbound_allowed(
                binding=self.binding,
                to_email=to_email,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                attachments=attachments,
                reply_to=reply_to,
            )
            unsubscribe_url = _validated_one_click_unsubscribe_url(unsubscribe_url)
        elif delivery_scope == DELIVERY_SCOPE_INTERNAL:
            _assert_internal_outbound_allowed(
                binding=self.binding,
                to_email=to_email,
                reply_to=reply_to,
            )
        else:
            raise GrowthRegistryError("outbound_delivery_scope_unknown_no_send")
        if not re.fullmatch(r"[0-9a-f]{64}", idempotency_key):
            raise GrowthRegistryError("outbound_idempotency_key_invalid_no_send")
        self.preflight(delivery_scope=delivery_scope)
        domain = self.binding.sender_email.split("@", 1)[1]
        message_id = _deterministic_message_id(
            idempotency_key=idempotency_key,
            sender_domain=domain,
        )
        message = EmailMessage()
        message["From"] = self.binding.sender_email
        message["To"] = to_email
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = message_id
        message["X-Imperial-Idempotency-Key"] = idempotency_key
        message["X-Imperial-Content-SHA256"] = hashlib.sha256(
            (subject + "\0" + body_text + "\0" + (body_html or "")).encode("utf-8")
        ).hexdigest()
        if delivery_scope == DELIVERY_SCOPE_EXTERNAL_CUSTOMER:
            message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(body_text)
        if body_html:
            message.add_alternative(body_html, subtype="html")
        for filename, content, mime_type in attachments or []:
            maintype, subtype = mime_type.split("/", 1)
            message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
        if GMAIL_OAUTH_FIELDS.issubset(self.secret):
            return self._send_gmail_api(
                to_email=to_email,
                message=message,
                message_id=message_id,
                delivery_scope=delivery_scope,
                reconcile_only=reconcile_only,
                pre_send_guard=pre_send_guard,
                account_quota_guard=account_quota_guard,
            )
        if reconcile_only:
            raise EmailDeliveryError(
                "smtp_reconcile_not_supported_no_send",
                retry_safe=False,
                accepted_but_unverified=True,
            )
        host = str(self.secret["host"])
        port = int(self.secret["port"])
        timeout = float(self.secret.get("timeout_seconds", 30))
        context = ssl.create_default_context()
        try:
            if self.secret.get("use_ssl"):
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    host, port, timeout=timeout, context=context
                )
            else:
                client = smtplib.SMTP(host, port, timeout=timeout)
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            client.login(str(self.secret["username"]), str(self.secret["password"]))
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailDeliveryError(
                type(exc).__name__, retry_safe=False, authentication_failure=True
            ) from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError(type(exc).__name__, retry_safe=True) from exc
        try:
            with client:
                if delivery_scope == DELIVERY_SCOPE_EXTERNAL_CUSTOMER:
                    _assert_external_transport_window_open()
                    if pre_send_guard is None:
                        raise GrowthRegistryError(
                            "external_customer_pre_send_guard_required_no_send"
                        )
                    pre_send_guard()
                    _assert_external_transport_window_open()
                refused = client.send_message(
                    message,
                    from_addr=self.binding.sender_email,
                    to_addrs=[to_email],
                )
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError(
                f"ambiguous_delivery:{type(exc).__name__}",
                retry_safe=False,
                transport_attempted=True,
            ) from exc
        if refused:
            raise EmailDeliveryError(
                "recipient_refused", retry_safe=False, transport_attempted=True
            )
        response_hash = hashlib.sha256(f"accepted:{to_email}:{message_id}".encode()).hexdigest()
        return EmailReceipt(
            provider_message_id=message_id,
            accepted_recipient=to_email,
            provider="smtp",
            response_sha256=response_hash,
            detail={"accepted": True, "message_id": message_id},
        )
