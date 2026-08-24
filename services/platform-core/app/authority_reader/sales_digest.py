from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import html
import json
import re
import signal
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..services.safe_http import AddressResolver, SafeHttpClient, SafeHttpError
from .config import ReaderSettings
from .models import (
    AuthorityDetailRevision,
    AuthorityRecord,
    AuthoritySalesDigest,
    AuthoritySalesDigestItem,
    AuthoritySignalOutbox,
)
from .service import canonical_json, utcnow

GOOGLE_OAUTH_ORIGIN = "https://oauth2.googleapis.com"
GMAIL_API_ORIGIN = "https://gmail.googleapis.com"
EMAIL_RE = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,63}$", re.I)
ALLOWED_RECIPIENT_ROLES = frozenset({"sales", "owner", "managing-director"})
GMAIL_SEND_SCOPES = (
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
)
GMAIL_READ_SCOPES = (
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly",
)


class DigestBlocked(RuntimeError):
    def __init__(self, code: str, *, retry_safe: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retry_safe = retry_safe


class DigestRecipient(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(min_length=6, max_length=320)
    role: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        lowered = value.lower()
        if not EMAIL_RE.fullmatch(lowered) or lowered.endswith(".local"):
            raise ValueError("invalid digest recipient")
        return lowered

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        if value not in ALLOWED_RECIPIENT_ROLES:
            raise ValueError("invalid digest recipient role")
        return value


class DigestRecipients(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str = Field(pattern=r"^internal-sales-digest-v1$")
    purpose: str = Field(pattern=r"^internal_sales_digest$")
    approved_by: str = Field(min_length=2, max_length=200)
    valid_until: datetime
    recipients: tuple[DigestRecipient, ...] = Field(min_length=1, max_length=20)

    @field_validator("valid_until")
    @classmethod
    def future_expiry(cls, value: datetime) -> datetime:
        aware = value if value.tzinfo else value.replace(tzinfo=UTC)
        if aware <= datetime.now(UTC):
            raise ValueError("digest recipient approval expired")
        return aware

    @field_validator("recipients")
    @classmethod
    def unique_recipients(
        cls, value: tuple[DigestRecipient, ...]
    ) -> tuple[DigestRecipient, ...]:
        if len({item.email for item in value}) != len(value):
            raise ValueError("duplicate digest recipient")
        return tuple(sorted(value, key=lambda item: item.email))


class OAuthSecret(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_id: str = Field(min_length=10, max_length=500)
    client_secret: str = Field(min_length=8, max_length=500)
    refresh_token: str = Field(min_length=20, max_length=2000)
    scope: str = Field(min_length=10, max_length=2000)
    token_type: str = Field(pattern=r"^[Bb]earer$")

    @field_validator("scope")
    @classmethod
    def required_scopes(cls, value: str) -> str:
        scopes = frozenset(value.split())
        if not scopes.intersection(GMAIL_SEND_SCOPES):
            raise ValueError("gmail send scope missing")
        if not scopes.intersection(GMAIL_READ_SCOPES):
            raise ValueError("gmail read scope missing")
        return value


@dataclass(frozen=True)
class GmailReceipt:
    message_id: str
    thread_id: str
    reconciled: bool = False


def _json_file(path_text: str, code: str) -> dict[str, Any]:
    try:
        raw = Path(path_text).read_bytes()
        if len(raw) > 64_000:
            raise DigestBlocked(f"{code}_too_large")
        payload = json.loads(raw)
    except DigestBlocked:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DigestBlocked(f"{code}_invalid") from exc
    if not isinstance(payload, dict):
        raise DigestBlocked(f"{code}_invalid")
    return payload


def load_recipients(settings: ReaderSettings) -> DigestRecipients:
    try:
        return DigestRecipients.model_validate(
            _json_file(settings.sales_digest_recipients_file, "digest_recipients")
        )
    except ValidationError as exc:
        raise DigestBlocked("digest_recipients_invalid") from exc


def load_oauth(settings: ReaderSettings) -> OAuthSecret:
    try:
        return OAuthSecret.model_validate(
            _json_file(settings.sales_digest_oauth_file, "digest_oauth")
        )
    except ValidationError as exc:
        raise DigestBlocked("digest_oauth_invalid") from exc


def recipients_sha256(config: DigestRecipients) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "schema_version": config.schema_version,
                "purpose": config.purpose,
                "approved_by": config.approved_by,
                "valid_until": _aware(config.valid_until).isoformat(),
                "recipients": [item.model_dump() for item in config.recipients],
            }
        ).encode()
    ).hexdigest()


class GmailDigestAdapter:
    def __init__(
        self,
        secret: OAuthSecret,
        *,
        oauth_transport: httpx.BaseTransport | None = None,
        gmail_transport: httpx.BaseTransport | None = None,
        resolver: AddressResolver | None = None,
    ) -> None:
        self.secret = secret
        self.oauth = SafeHttpClient(
            GOOGLE_OAUTH_ORIGIN,
            allowed_origins=frozenset({GOOGLE_OAUTH_ORIGIN}),
            timeout=20,
            transport=oauth_transport,
            resolver=resolver,
            max_redirects=0,
        )
        self.gmail = SafeHttpClient(
            GMAIL_API_ORIGIN,
            allowed_origins=frozenset({GMAIL_API_ORIGIN}),
            timeout=30,
            transport=gmail_transport,
            resolver=resolver,
            max_redirects=0,
        )
        self._access_token: str | None = None

    def close(self) -> None:
        self.oauth.close()
        self.gmail.close()

    def __enter__(self) -> GmailDigestAdapter:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @staticmethod
    def _response_json(response: httpx.Response, code: str) -> dict[str, Any]:
        try:
            if len(response.content) > 256_000:
                raise DigestBlocked(f"{code}_response_too_large")
            payload = response.json()
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DigestBlocked(f"{code}_invalid_response") from exc
        if not isinstance(payload, dict):
            raise DigestBlocked(f"{code}_invalid_response")
        return payload

    def access_token(self) -> str:
        if self._access_token:
            return self._access_token
        try:
            response = self.oauth.post(
                "/token",
                data={
                    "client_id": self.secret.client_id,
                    "client_secret": self.secret.client_secret,
                    "refresh_token": self.secret.refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Accept": "application/json"},
            )
        except (SafeHttpError, httpx.HTTPError) as exc:
            raise DigestBlocked("gmail_oauth_transport_error", retry_safe=True) from exc
        try:
            if response.status_code != 200:
                raise DigestBlocked(
                    "gmail_oauth_rejected", retry_safe=response.status_code >= 500
                )
            payload = self._response_json(response, "gmail_oauth")
            token = payload.get("access_token")
            if not isinstance(token, str) or len(token) < 20:
                raise DigestBlocked("gmail_oauth_invalid_response")
            self._access_token = token
            return token
        finally:
            response.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token()}",
            "Accept": "application/json",
        }

    def preflight(self) -> str:
        try:
            response = self.gmail.get("/gmail/v1/users/me/profile", headers=self._headers())
        except (SafeHttpError, httpx.HTTPError) as exc:
            raise DigestBlocked("gmail_profile_transport_error", retry_safe=True) from exc
        try:
            if response.status_code != 200:
                raise DigestBlocked("gmail_profile_rejected")
            payload = self._response_json(response, "gmail_profile")
            address = payload.get("emailAddress")
            if not isinstance(address, str) or not EMAIL_RE.fullmatch(address):
                raise DigestBlocked("gmail_profile_invalid_response")
            return address.lower()
        finally:
            response.close()

    def find_sent(self, digest_id: str) -> GmailReceipt | None:
        try:
            response = self.gmail.get(
                "/gmail/v1/users/me/messages",
                headers=self._headers(),
                params={"q": f'in:sent "{digest_id}"', "maxResults": 2},
            )
        except (SafeHttpError, httpx.HTTPError) as exc:
            raise DigestBlocked("gmail_reconcile_transport_error", retry_safe=True) from exc
        try:
            if response.status_code != 200:
                raise DigestBlocked("gmail_reconcile_rejected")
            payload = self._response_json(response, "gmail_reconcile")
            messages = payload.get("messages", [])
            if not isinstance(messages, list) or len(messages) > 1:
                raise DigestBlocked("gmail_reconcile_ambiguous")
            if not messages:
                return None
            item = messages[0]
            if not isinstance(item, dict):
                raise DigestBlocked("gmail_reconcile_invalid_response")
            message_id = item.get("id")
            thread_id = item.get("threadId")
            if not isinstance(message_id, str) or not isinstance(thread_id, str):
                raise DigestBlocked("gmail_reconcile_invalid_response")
            return GmailReceipt(message_id, thread_id, reconciled=True)
        finally:
            response.close()

    def get_sent(self, gmail_message_id: str, digest_id: str) -> GmailReceipt:
        try:
            response = self.gmail.get(
                f"/gmail/v1/users/me/messages/{gmail_message_id}",
                headers=self._headers(),
                params={
                    "format": "metadata",
                    "metadataHeaders": "X-Imperial-Digest-ID",
                },
            )
        except (SafeHttpError, httpx.HTTPError) as exc:
            raise DigestBlocked("gmail_verify_transport_error", retry_safe=True) from exc
        try:
            if response.status_code != 200:
                raise DigestBlocked("gmail_verify_rejected")
            payload = self._response_json(response, "gmail_verify")
            response_id = payload.get("id")
            thread_id = payload.get("threadId")
            label_ids = payload.get("labelIds", [])
            message_payload = payload.get("payload", {})
            headers = (
                message_payload.get("headers", [])
                if isinstance(message_payload, dict)
                else []
            )
            digest_header_values = [
                item.get("value")
                for item in headers
                if isinstance(item, dict)
                and str(item.get("name", "")).lower() == "x-imperial-digest-id"
            ]
            if (
                response_id != gmail_message_id
                or not isinstance(thread_id, str)
                or not isinstance(label_ids, list)
                or "SENT" not in label_ids
                or digest_header_values != [digest_id]
            ):
                raise DigestBlocked("gmail_verify_invalid_response")
            return GmailReceipt(response_id, thread_id, reconciled=True)
        finally:
            response.close()

    def send(self, raw_message: bytes) -> GmailReceipt:
        raw = base64.urlsafe_b64encode(raw_message).decode().rstrip("=")
        try:
            response = self.gmail.post(
                "/gmail/v1/users/me/messages/send",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"raw": raw},
            )
        except (SafeHttpError, httpx.HTTPError) as exc:
            raise DigestBlocked("gmail_send_ambiguous", retry_safe=True) from exc
        try:
            if response.status_code not in {200, 201}:
                raise DigestBlocked("gmail_send_rejected", retry_safe=response.status_code >= 500)
            payload = self._response_json(response, "gmail_send")
            message_id = payload.get("id")
            thread_id = payload.get("threadId")
            if not isinstance(message_id, str) or not isinstance(thread_id, str):
                raise DigestBlocked("gmail_send_invalid_response")
            return GmailReceipt(message_id, thread_id)
        finally:
            response.close()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _digest_local_date(settings: ReaderSettings, now: datetime) -> date:
    try:
        zone = ZoneInfo(settings.sales_digest_timezone)
    except ZoneInfoNotFoundError as exc:
        raise DigestBlocked("sales_digest_timezone_invalid") from exc
    return _aware(now).astimezone(zone).date()


def digest_due(settings: ReaderSettings, now: datetime) -> bool:
    try:
        zone = ZoneInfo(settings.sales_digest_timezone)
    except ZoneInfoNotFoundError as exc:
        raise DigestBlocked("sales_digest_timezone_invalid") from exc
    local = _aware(now).astimezone(zone)
    return (local.hour, local.minute) >= (settings.sales_digest_hour, settings.sales_digest_minute)


def _assert_digest_gate(settings: ReaderSettings) -> None:
    if not settings.enabled or not settings.policy_authorized or not settings.policy_evidence_valid:
        raise DigestBlocked("reader_policy_gate")
    if not settings.detail_enabled or not settings.lead_export_enabled:
        raise DigestBlocked("lead_export_policy_gate")
    if not settings.sales_digest_enabled or not settings.sales_digest_authorized:
        raise DigestBlocked("sales_digest_policy_gate")
    errors = settings.errors()
    if errors:
        raise DigestBlocked(errors[0])


def _item_snapshot(
    outbox: AuthoritySignalOutbox,
    record: AuthorityRecord,
    detail: AuthorityDetailRevision,
) -> dict[str, Any]:
    lead = json.loads(outbox.payload_json)
    detail_payload = json.loads(detail.normalized_json)
    return {
        "process_number": record.public_process_number,
        "submission_date": record.submission_date.date().isoformat(),
        "city": record.city,
        "topographical_number": record.topographical_number or "",
        "property_address": str(detail_payload.get("property_address") or ""),
        "construction_activity": record.construction_activity,
        "procedure_type": record.procedure_type,
        "lead_reason": lead["lead_reason"],
        "confidence": int(lead["confidence"]),
        "urgency": int(lead["urgency"]),
        "evidence_url": record.evidence_url,
        "business_contact": None,
        "contact_status": "not_available_from_etdr",
    }


def _last_closed_window(db: Session) -> datetime | None:
    row = db.scalar(
        select(AuthoritySalesDigest)
        .where(AuthoritySalesDigest.status.in_(("sent", "skipped")))
        .order_by(AuthoritySalesDigest.window_end_at.desc())
        .limit(1)
    )
    return _aware(row.window_end_at) if row else None


def _digest_payload_hash(
    *,
    digest_date: date,
    window_start_at: datetime | None,
    window_end_at: datetime,
    recipient_hash: str,
    items: list[dict[str, Any]],
) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "digest_date": digest_date.isoformat(),
                "window_start_at": (
                    _aware(window_start_at).isoformat() if window_start_at else None
                ),
                "window_end_at": _aware(window_end_at).isoformat(),
                "recipients_sha256": recipient_hash,
                "items": items,
            }
        ).encode()
    ).hexdigest()


def create_digest(
    db: Session,
    settings: ReaderSettings,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> AuthoritySalesDigest | None:
    _assert_digest_gate(settings)
    evaluated_at = _aware(now or utcnow())
    if not force and not digest_due(settings, evaluated_at):
        return None
    digest_date = _digest_local_date(settings, evaluated_at)
    existing = db.scalar(
        select(AuthoritySalesDigest).where(AuthoritySalesDigest.digest_date == digest_date)
    )
    if existing:
        return existing
    recipients = load_recipients(settings)
    recipient_hash = recipients_sha256(recipients)
    window_start = _last_closed_window(db)
    statement = (
        select(AuthoritySignalOutbox, AuthorityRecord, AuthorityDetailRevision)
        .join(AuthorityRecord, AuthorityRecord.record_id == AuthoritySignalOutbox.record_id)
        .join(
            AuthorityDetailRevision,
            AuthorityDetailRevision.detail_revision_id == AuthoritySignalOutbox.revision_id,
        )
        .where(
            AuthoritySignalOutbox.status == "delivered",
            AuthoritySignalOutbox.reason_code == "daily_lead_generator_imported",
            AuthoritySignalOutbox.created_at <= evaluated_at,
            AuthoritySignalOutbox.payload_json.contains('"schema_version":"etdr-lead-v2"'),
            ~exists(
                select(AuthoritySalesDigestItem.id).where(
                    AuthoritySalesDigestItem.signal_outbox_id == AuthoritySignalOutbox.id
                )
            ),
        )
        .order_by(AuthorityRecord.submission_date.desc(), AuthorityRecord.public_process_number)
        .limit(settings.sales_digest_max_items)
    )
    rows = db.execute(statement).all()
    snapshots = [_item_snapshot(outbox, record, detail) for outbox, record, detail in rows]
    payload_hash = _digest_payload_hash(
        digest_date=digest_date,
        window_start_at=window_start,
        window_end_at=evaluated_at,
        recipient_hash=recipient_hash,
        items=snapshots,
    )
    digest_id = f"ETDR-DIGEST-{digest_date:%Y%m%d}-{payload_hash[:16].upper()}"
    row = AuthoritySalesDigest(
        digest_id=digest_id,
        digest_date=digest_date,
        window_start_at=window_start,
        window_end_at=evaluated_at,
        status="pending" if snapshots else "skipped",
        item_count=len(snapshots),
        verified_contact_count=0,
        recipients_sha256=recipient_hash,
        payload_sha256=payload_hash,
        message_rfc822_id=f"<{digest_id.lower()}@digest.imperialholding.hu>",
    )
    db.add(row)
    db.flush()
    for (outbox, _record, _detail), snapshot in zip(rows, snapshots, strict=True):
        db.add(
            AuthoritySalesDigestItem(
                digest_id=digest_id,
                signal_outbox_id=outbox.id,
                item_payload_sha256=hashlib.sha256(canonical_json(snapshot).encode()).hexdigest(),
                item_snapshot_json=canonical_json(snapshot),
                contact_status="not_available_from_etdr",
            )
        )
    db.commit()
    return row


def _claim_digest(db: Session, settings: ReaderSettings) -> AuthoritySalesDigest | None:
    now = utcnow()
    db.execute(
        update(AuthoritySalesDigest)
        .where(
            AuthoritySalesDigest.status == "claimed",
            AuthoritySalesDigest.lease_expires_at.is_not(None),
            AuthoritySalesDigest.lease_expires_at < now,
        )
        .values(status="retry", lease_owner=None, lease_expires_at=None)
    )
    row = db.scalar(
        select(AuthoritySalesDigest)
        .where(AuthoritySalesDigest.status.in_(("pending", "retry")))
        .order_by(AuthoritySalesDigest.digest_date)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if not row:
        db.commit()
        return None
    row.status = "claimed"
    row.lease_owner = settings.worker_id
    row.lease_expires_at = now + timedelta(seconds=settings.lease_seconds)
    row.attempt_count += 1
    if row.last_error not in {"gmail_send_ambiguous", "gmail_reconcile_pending"}:
        row.last_error = None
    db.commit()
    return row


def _render_digest(
    digest: AuthoritySalesDigest,
    items: list[dict[str, Any]],
) -> tuple[str, str, str]:
    subject = f"ÉTDR napi leadlista – {digest.digest_date.isoformat()} – {len(items)} találat"
    intro = (
        "Az ÉTDR-olvasó által minősített új és befejezési jel nélküli építési találatok. "
        "Az ÉTDR nem közöl ellenőrzött ügyfél-e-mailt vagy telefonszámot; ilyen adatot a "
        "rendszer nem talál ki. A cím és a hivatalos ügyoldal minden sornál elérhető."
    )
    plain_parts = [subject, "", intro, ""]
    html_rows: list[str] = []
    labels = {
        "new_submission": "új feltöltés",
        "recently_authorized": "frissen engedélyezett",
        "likely_interrupted": "valószínűleg félbeszakadt vagy szünetel",
        "likely_not_started": "valószínűleg el sem indult",
        "no_completion_signal": "nincs későbbi befejezési jel",
    }
    for index, item in enumerate(items, 1):
        label = labels.get(str(item["lead_reason"]), str(item["lead_reason"]))
        address = str(item["property_address"] or item["city"])
        contact = "nincs ellenőrzött üzleti e-mail/telefon az ÉTDR-ben"
        plain_parts.extend(
            [
                f"{index}. {item['process_number']} – {label}",
                f"Projekt: {item['construction_activity']}",
                f"Helyszín: {address}; HRSZ: {item['topographical_number'] or '–'}",
                f"Elérhetőség: {contact}",
                f"Hivatalos adatlap: {item['evidence_url']}",
                "",
            ]
        )
        hrsz = html.escape(str(item["topographical_number"] or "–"))
        evidence_url = html.escape(str(item["evidence_url"]), quote=True)
        html_rows.append(
            "<tr>"
            f"<td>{html.escape(str(item['process_number']))}</td>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{html.escape(str(item['construction_activity']))}</td>"
            f"<td>{html.escape(address)}<br>HRSZ: {hrsz}</td>"
            f"<td>{html.escape(contact)}</td>"
            f"<td><a href=\"{evidence_url}\">ÉTDR-adatlap</a></td>"
            "</tr>"
        )
    plain_parts.append(
        "A 'nincs későbbi befejezési jel' nyilvántartási indikátor, nem helyszíni bizonyíték."
    )
    plain_parts.extend(["", f"Kézbesítési azonosító: {digest.digest_id}"])
    body_text = "\n".join(plain_parts)
    body_html = (
        "<!doctype html><html lang='hu'><body>"
        f"<h1>{html.escape(subject)}</h1><p>{html.escape(intro)}</p>"
        "<table border='1' cellpadding='7' cellspacing='0'><thead><tr>"
        "<th>ÉTDR ügy</th><th>Minősítés</th><th>Projekt</th><th>Helyszín</th>"
        "<th>Kapcsolat</th><th>Forrás</th></tr></thead><tbody>"
        + "".join(html_rows)
        + "</tbody></table><p><strong>Figyelem:</strong> a befejezési jel hiánya "
        "nyilvántartási indikátor, nem helyszíni bizonyíték.</p>"
        f"<p>Kézbesítési azonosító: {html.escape(digest.digest_id)}</p></body></html>"
    )
    return subject, body_text, body_html


def _mime_message(
    digest: AuthoritySalesDigest,
    recipients: DigestRecipients,
    *,
    sender: str,
    subject: str,
    body_text: str,
    body_html: str,
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(item.email for item in recipients.recipients)
    message["Subject"] = subject
    message["Message-ID"] = digest.message_rfc822_id
    message["X-Imperial-Source"] = "authority:etdr_public"
    message["X-Imperial-Digest-ID"] = digest.digest_id
    message.set_content(body_text)
    message.add_alternative(body_html, subtype="html")
    return message.as_bytes()


def dispatch_digest(
    db: Session,
    settings: ReaderSettings,
    digest: AuthoritySalesDigest,
    *,
    adapter_factory: Any = GmailDigestAdapter,
) -> AuthoritySalesDigest:
    recipients = load_recipients(settings)
    if not hmac.compare_digest(digest.recipients_sha256, recipients_sha256(recipients)):
        digest.status = "dead_letter"
        digest.last_error = "digest_recipients_changed"
        digest.lease_owner = None
        digest.lease_expires_at = None
        db.commit()
        return digest
    item_rows = db.scalars(
        select(AuthoritySalesDigestItem)
        .where(AuthoritySalesDigestItem.digest_id == digest.digest_id)
        .order_by(AuthoritySalesDigestItem.id)
    ).all()
    items = [json.loads(item.item_snapshot_json) for item in item_rows]
    if len(items) != digest.item_count:
        digest.status = "dead_letter"
        digest.last_error = "digest_item_count_mismatch"
        digest.lease_owner = None
        digest.lease_expires_at = None
        db.commit()
        return digest
    expected_hash = _digest_payload_hash(
        digest_date=digest.digest_date,
        window_start_at=digest.window_start_at,
        window_end_at=digest.window_end_at,
        recipient_hash=digest.recipients_sha256,
        items=items,
    )
    if not hmac.compare_digest(digest.payload_sha256, expected_hash):
        digest.status = "dead_letter"
        digest.last_error = "digest_payload_hash_mismatch"
        digest.lease_owner = None
        digest.lease_expires_at = None
        db.commit()
        return digest
    subject, body_text, body_html = _render_digest(digest, items)
    try:
        with adapter_factory(load_oauth(settings)) as adapter:
            sender = adapter.preflight()
            receipt = adapter.find_sent(digest.digest_id)
            if receipt is None:
                if digest.last_error in {
                    "gmail_send_ambiguous",
                    "gmail_reconcile_pending",
                }:
                    raise DigestBlocked("gmail_reconcile_pending", retry_safe=True)
                receipt = adapter.send(
                    _mime_message(
                        digest,
                        recipients,
                        sender=sender,
                        subject=subject,
                        body_text=body_text,
                        body_html=body_html,
                    )
                )
        digest.status = "sent"
        digest.gmail_message_id = receipt.message_id
        digest.gmail_thread_id = receipt.thread_id
        digest.sent_at = utcnow()
        digest.last_error = "reconciled_after_ambiguous_send" if receipt.reconciled else None
    except DigestBlocked as exc:
        digest.last_error = exc.code
        digest.status = (
            "retry" if exc.retry_safe and digest.attempt_count < 5 else "dead_letter"
        )
    digest.lease_owner = None
    digest.lease_expires_at = None
    db.commit()
    return digest


def run_once(
    db: Session,
    settings: ReaderSettings,
    *,
    force: bool = False,
    now: datetime | None = None,
    adapter_factory: Any = GmailDigestAdapter,
) -> AuthoritySalesDigest | None:
    created = create_digest(db, settings, now=now, force=force)
    if created is not None and created.status in {"sent", "skipped"}:
        return created
    claimed = _claim_digest(db, settings)
    if not claimed:
        return None
    return dispatch_digest(db, settings, claimed, adapter_factory=adapter_factory)


def check(settings: ReaderSettings, *, network: bool = False) -> dict[str, Any]:
    _assert_digest_gate(settings)
    recipients = load_recipients(settings)
    secret = load_oauth(settings)
    sender_domain = None
    if network:
        with GmailDigestAdapter(secret) as adapter:
            sender_domain = adapter.preflight().rsplit("@", 1)[-1]
            adapter.find_sent("ETDR-DIGEST-PREFLIGHT-NEVER-SENT")
    with SessionLocal() as db:
        db.scalar(select(AuthoritySalesDigest.id).limit(1))
    return {
        "status": "ready",
        "recipient_count": len(recipients.recipients),
        "recipients_sha256": recipients_sha256(recipients),
        "gmail_preflight": "pass" if network else "not_requested",
        "sender_domain": sender_domain,
    }


def verify_latest(settings: ReaderSettings) -> dict[str, Any]:
    _assert_digest_gate(settings)
    with SessionLocal() as db:
        digest = db.scalar(
            select(AuthoritySalesDigest)
            .where(AuthoritySalesDigest.status == "sent")
            .order_by(AuthoritySalesDigest.sent_at.desc(), AuthoritySalesDigest.id.desc())
            .limit(1)
        )
        if digest is None or not digest.gmail_message_id:
            raise DigestBlocked("sales_digest_sent_message_missing")
        expected_gmail_message_id = digest.gmail_message_id
        digest_id = digest.digest_id
        item_count = digest.item_count
    with GmailDigestAdapter(load_oauth(settings)) as adapter:
        sender_domain = adapter.preflight().rsplit("@", 1)[-1]
        receipt = adapter.get_sent(expected_gmail_message_id, digest_id)
    if not hmac.compare_digest(receipt.message_id, expected_gmail_message_id):
        raise DigestBlocked("sales_digest_gmail_message_mismatch")
    return {
        "status": "verified",
        "digest_id": digest_id,
        "item_count": item_count,
        "gmail_message_id_sha256": hashlib.sha256(receipt.message_id.encode()).hexdigest(),
        "sender_domain": sender_domain,
    }


stopping = False


def request_stop(_signum: int, _frame: Any) -> None:
    global stopping
    stopping = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--run-now", action="store_true")
    parser.add_argument("--verify-latest", action="store_true")
    args = parser.parse_args()
    settings = ReaderSettings.from_env()
    if args.check or args.preflight:
        print(canonical_json(check(settings, network=args.preflight)))
        return
    if args.verify_latest:
        print(canonical_json(verify_latest(settings)))
        return
    if args.run_now:
        with SessionLocal() as db:
            result = run_once(db, settings, force=True)
        print(
            canonical_json(
                {
                    "digest_id": result.digest_id if result else None,
                    "status": result.status if result else "not_due",
                    "item_count": result.item_count if result else 0,
                }
            )
        )
        if result and result.status not in {"sent", "skipped"}:
            raise SystemExit(1)
        return
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stopping:
        settings = ReaderSettings.from_env()
        try:
            with SessionLocal() as db:
                run_once(db, settings)
        except DigestBlocked:
            pass
        deadline = time.monotonic() + settings.poll_seconds
        while not stopping and time.monotonic() < deadline:
            time.sleep(0.2)


if __name__ == "__main__":
    main()
