from __future__ import annotations

import hashlib
import smtplib
import ssl
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

    def send(
        self,
        *,
        to_email: str,
        subject: str,
        body_text: str,
        idempotency_key: str,
        body_html: str | None = None,
        reply_to: str | None = None,
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
