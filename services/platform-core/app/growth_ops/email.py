from __future__ import annotations

import base64
import hashlib
import json
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from .registry import BrandBinding, GrowthRegistryError


class EmailDeliveryError(RuntimeError):
    def __init__(
        self, error_type: str, *, retry_safe: bool, authentication_failure: bool = False
    ) -> None:
        super().__init__(error_type)
        self.retry_safe = retry_safe
        self.authentication_failure = authentication_failure


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

    def preflight(self) -> None:
        oauth_required = {"client_id", "client_secret", "refresh_token", "scope"}
        if oauth_required.issubset(self.secret):
            scopes = str(self.secret.get("scope") or "").split()
            if not any(
                scope.endswith("/gmail.compose") or scope.endswith("/gmail.send")
                for scope in scopes
            ):
                raise GrowthRegistryError("Gmail compose/send OAuth scope is required")
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
            access_token = str(token_payload.get("access_token") or "")
            if not access_token:
                raise EmailDeliveryError(
                    "gmail_oauth_access_token_missing",
                    retry_safe=False,
                    authentication_failure=True,
                )
            raw = base64.urlsafe_b64encode(message.as_bytes()).rstrip(b"=").decode("ascii")
            send_body = json.dumps({"raw": raw}, separators=(",", ":")).encode()
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
                sent = json.loads(response.read(1_000_000))
        except urllib.error.HTTPError as exc:
            authentication_failure = exc.code in {400, 401, 403}
            raise EmailDeliveryError(
                f"gmail_api_http_{exc.code}",
                retry_safe=exc.code >= 500 or exc.code == 429,
                authentication_failure=authentication_failure,
            ) from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise EmailDeliveryError(
                f"ambiguous_delivery:{type(exc).__name__}", retry_safe=False
            ) from exc
        provider_id = str(sent.get("id") or "")
        if not provider_id:
            raise EmailDeliveryError("gmail_api_message_id_missing", retry_safe=False)
        response_hash = hashlib.sha256(
            f"accepted:{to_email}:{provider_id}:{message_id}".encode()
        ).hexdigest()
        return EmailReceipt(
            provider_message_id=provider_id,
            accepted_recipient=to_email,
            provider="gmail_api",
            response_sha256=response_hash,
            detail={"accepted": True, "message_id": provider_id},
        )

    def send(
        self,
        *,
        to_email: str,
        subject: str,
        body_text: str,
        idempotency_key: str,
        body_html: str | None = None,
        reply_to: str | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
    ) -> EmailReceipt:
        self.preflight()
        domain = self.binding.sender_email.split("@", 1)[1]
        message_id = make_msgid(idstring=idempotency_key[:24], domain=domain)
        message = EmailMessage()
        message["From"] = self.binding.sender_email
        message["To"] = to_email
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = message_id
        message["X-Imperial-Idempotency-Key"] = idempotency_key
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(body_text)
        if body_html:
            message.add_alternative(body_html, subtype="html")
        for filename, content, mime_type in attachments or []:
            maintype, subtype = mime_type.split("/", 1)
            message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
        if {"client_id", "client_secret", "refresh_token", "scope"}.issubset(self.secret):
            return self._send_gmail_api(
                to_email=to_email,
                message=message,
                message_id=message_id,
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
