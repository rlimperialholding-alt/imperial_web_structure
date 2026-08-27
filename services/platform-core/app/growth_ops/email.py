from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import smtplib
import ssl
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate
from html.parser import HTMLParser
from typing import Any

from .canonical_policy import ACTIVE_CONTENT_BRANDS
from .registry import BrandBinding, GrowthRegistryError

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

if (
    set(ACTIVE_CONTENT_BRAND_TERM_KEYS) != set(ACTIVE_CONTENT_BRANDS)
    or set(ACTIVE_CONTENT_BRAND_TERM_KEYS.values()) != set(BRAND_IDENTITY_TERMS)
):
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
            not label or label.startswith("-") or label.endswith("-")
            for label in domain.split(".")
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
            recipient_domain.endswith(f".{blocked}")
            for blocked in HARD_BLOCKED_RECIPIENT_DOMAINS
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
        f" {_normalize_customer_facing(term)} " in content_normalized
        for term in own_identity_terms
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
        if disposition == "attachment":
            raise _GmailReadbackError("gmail_readback_unexpected_attachment")
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
    }


def _deterministic_message_id(*, idempotency_key: str, sender_domain: str) -> str:
    digest = hashlib.sha256(
        f"{idempotency_key}\0{sender_domain.lower()}".encode()
    ).hexdigest()
    return f"<imperial-{digest}@{sender_domain.lower()}>"


class EmailDeliveryError(RuntimeError):
    def __init__(
        self,
        error_type: str,
        *,
        retry_safe: bool,
        authentication_failure: bool = False,
        accepted_but_unverified: bool = False,
        provider_message_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(error_type)
        self.error_type = error_type
        self.retry_safe = retry_safe
        self.authentication_failure = authentication_failure
        self.accepted_but_unverified = accepted_but_unverified
        self.provider_message_id = provider_message_id
        self.detail = dict(detail or {})


@dataclass(frozen=True)
class EmailReceipt:
    provider_message_id: str
    accepted_recipient: str
    provider: str
    response_sha256: str
    detail: dict[str, Any]


class SMTPEmailAdapter:
    def __init__(self, binding: BrandBinding) -> None:
        self.binding = binding
        self.secret = binding.secret

    def preflight(self, *, delivery_scope: str | None = None) -> None:
        if (
            delivery_scope == DELIVERY_SCOPE_EXTERNAL_CUSTOMER
            and not GMAIL_OAUTH_FIELDS.issubset(self.secret)
        ):
            raise GrowthRegistryError("external_customer_gmail_oauth_required_no_send")
        if GMAIL_OAUTH_FIELDS.issubset(self.secret):
            scopes = str(self.secret.get("scope") or "").split()
            if not any(
                scope.endswith("/gmail.compose") or scope.endswith("/gmail.send")
                for scope in scopes
            ):
                raise GrowthRegistryError("Gmail compose/send OAuth scope is required")
            if delivery_scope == DELIVERY_SCOPE_EXTERNAL_CUSTOMER and not any(
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

    def _send_gmail_api(
        self,
        *,
        to_email: str,
        message: EmailMessage,
        message_id: str,
        reconcile_only: bool = False,
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
            authentication_failure = exc.code in {400, 401, 403}
            raise EmailDeliveryError(
                f"gmail_oauth_http_{exc.code}",
                retry_safe=exc.code >= 500 or exc.code == 429,
                authentication_failure=authentication_failure,
            ) from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise EmailDeliveryError(
                f"gmail_oauth_pre_send:{type(exc).__name__}", retry_safe=True
            ) from exc

        idempotency_key = _single_header(message, "X-Imperial-Idempotency-Key")
        authorization = {"Authorization": f"Bearer {access_token}"}
        existing_provider_id: str | None = None
        try:
            candidate_ids: list[str] = []
            strong_candidate_ids: list[str] = []
            escaped_subject = str(message["Subject"]).replace('"', "")
            for query_index, query in enumerate((
                f"in:sent rfc822msgid:{message_id}",
                f'in:sent "{idempotency_key}"',
                f'in:sent to:{to_email} subject:"{escaped_subject}"',
            )):
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
                raise _GmailReadbackError("gmail_pre_send_multiple_exact_candidates")
            if verified_candidates:
                existing_provider_id, existing_detail = verified_candidates[0]
                existing_detail.update(
                    {
                        "accepted": True,
                        "readback_verified": True,
                        "provider_message_id": existing_provider_id,
                        "outbound_rfc_message_id": message_id,
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
                raise _GmailReadbackError(
                    "gmail_existing_delivery_identity_payload_mismatch"
                )
            existing_provider_id = None
            if reconcile_only:
                raise EmailDeliveryError(
                    "accepted_but_unverified",
                    retry_safe=False,
                    accepted_but_unverified=True,
                    detail={"reason": "gmail_reconcile_no_exact_message_no_send"},
                )
        except urllib.error.HTTPError as exc:
            if existing_provider_id is None:
                raise EmailDeliveryError(
                    "pre_send_verification_failed_no_send",
                    retry_safe=False,
                    authentication_failure=exc.code in {400, 401, 403},
                    detail={"reason": f"gmail_pre_send_search_http_{exc.code}"},
                ) from exc
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                authentication_failure=exc.code in {400, 401, 403},
                accepted_but_unverified=True,
                provider_message_id=existing_provider_id,
                detail={
                    "reason": f"gmail_pre_send_search_http_{exc.code}",
                    "provider_message_id": existing_provider_id,
                },
            ) from exc
        except (
            OSError,
            urllib.error.URLError,
            json.JSONDecodeError,
            _GmailReadbackError,
        ) as exc:
            if existing_provider_id is None:
                raise EmailDeliveryError(
                    "pre_send_verification_failed_no_send",
                    retry_safe=False,
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
            authentication_failure = exc.code in {400, 401, 403}
            raise EmailDeliveryError(
                f"gmail_api_http_{exc.code}",
                retry_safe=False,
                authentication_failure=authentication_failure,
            ) from exc
        except (OSError, urllib.error.URLError) as exc:
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
                detail={
                    "reason": f"gmail_send_transport_ambiguous:{type(exc).__name__}"
                },
            ) from exc
        try:
            sent = json.loads(sent_response)
        except json.JSONDecodeError as exc:
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
                detail={"reason": "gmail_send_response_invalid"},
            ) from exc
        if not isinstance(sent, dict):
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
                detail={"reason": "gmail_send_response_not_an_object"},
            )
        provider_id = str(sent.get("id") or "")
        if not provider_id:
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
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
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                authentication_failure=exc.code in {400, 401, 403},
                accepted_but_unverified=True,
                provider_message_id=provider_id,
                detail={
                    "reason": f"gmail_readback_http_{exc.code}",
                    "provider_message_id": provider_id,
                },
            ) from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError, _GmailReadbackError) as exc:
            raise EmailDeliveryError(
                "accepted_but_unverified",
                retry_safe=False,
                accepted_but_unverified=True,
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
                "recovered_existing_sent": False,
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
                reconcile_only=reconcile_only,
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
                refused = client.send_message(
                    message,
                    from_addr=self.binding.sender_email,
                    to_addrs=[to_email],
                )
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError(
                f"ambiguous_delivery:{type(exc).__name__}", retry_safe=False
            ) from exc
        if refused:
            raise EmailDeliveryError("recipient_refused", retry_safe=False)
        response_hash = hashlib.sha256(f"accepted:{to_email}:{message_id}".encode()).hexdigest()
        return EmailReceipt(
            provider_message_id=message_id,
            accepted_recipient=to_email,
            provider="smtp",
            response_sha256=response_hash,
            detail={"accepted": True, "message_id": message_id},
        )
