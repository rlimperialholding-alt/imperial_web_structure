from __future__ import annotations

import base64
import json
import re
import stat
from types import SimpleNamespace

import pytest

from app.growth_ops import processing
from app.growth_ops.email import EmailDeliveryError, SMTPEmailAdapter
from app.growth_ops.registry import BrandBinding, GrowthRegistryError


def _binding(
    *,
    brand_id: str = "imperial",
    sender_email: str = "info@imperialholding.hu",
) -> BrandBinding:
    return BrandBinding(
        brand_id=brand_id,
        sender_email=sender_email,
        domain_key=sender_email.rsplit("@", 1)[1],
        secret={
            "host": "smtp.test",
            "port": 465,
            "username": "test",
            "password": "test",
            "use_ssl": True,
        },
        config={},
    )


def _oauth_binding(*, scope: str | None = None) -> BrandBinding:
    return BrandBinding(
        brand_id="imperial",
        sender_email="info@imperialholding.hu",
        domain_key="imperialholding-hu",
        secret={
            "client_id": "client",
            "client_secret": "secret",
            "refresh_token": "refresh",
            "scope": scope
            or (
                "https://www.googleapis.com/auth/gmail.send "
                "https://www.googleapis.com/auth/gmail.readonly"
            ),
        },
        config={},
    )


class _HTTPResponse:
    def __init__(self, value):
        self.value = value if isinstance(value, bytes) else json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _limit):
        return self.value


class _FakeGmail:
    def __init__(self, *, readback_mode: str = "exact") -> None:
        self.readback_mode = readback_mode
        self.provider_id = "gmail-provider-id"
        self.sent_raw: str | None = None
        self.post_count = 0

    def urlopen(self, request, timeout):
        assert timeout == 30
        url = request.full_url
        if url == "https://oauth2.googleapis.com/token":
            return _HTTPResponse({"access_token": "access-token"})
        if url == "https://gmail.googleapis.com/gmail/v1/users/me/profile":
            return _HTTPResponse({"emailAddress": "info@imperialholding.hu"})
        if "/users/me/messages?" in url:
            if self.sent_raw is None:
                return _HTTPResponse({"messages": []})
            return _HTTPResponse({"messages": [{"id": self.provider_id}]})
        if url.endswith("/messages/send"):
            self.post_count += 1
            if self.readback_mode == "post_transport_error":
                raise OSError("connection reset after request write")
            payload = json.loads(request.data)
            self.sent_raw = payload["raw"]
            return _HTTPResponse({"id": self.provider_id})
        if url.endswith(f"/messages/{self.provider_id}?format=raw"):
            assert self.sent_raw is not None
            labels = [] if self.readback_mode == "missing_sent" else ["SENT"]
            readback_raw = self.sent_raw
            if self.readback_mode == "mismatched_body":
                raw = base64.urlsafe_b64decode(
                    readback_raw + "=" * (-len(readback_raw) % 4)
                )
                raw = raw.replace(b"Imperial Holding offer.", b"Imperial Holding other.")
                readback_raw = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
            elif self.readback_mode == "unexpected_cc":
                raw = base64.urlsafe_b64decode(
                    readback_raw + "=" * (-len(readback_raw) % 4)
                )
                separator = b"\r\n\r\n" if b"\r\n\r\n" in raw else b"\n\n"
                raw = raw.replace(
                    separator,
                    separator[: len(separator) // 2]
                    + b"Cc: attacker@example.test"
                    + separator,
                    1,
                )
                readback_raw = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
            return _HTTPResponse(
                {"id": self.provider_id, "labelIds": labels, "raw": readback_raw}
            )
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture
def smtp_transport(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, username, password):
            assert (username, password) == ("test", "test")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def send_message(self, message, **kwargs):
            sent.append(message)
            return {}

    monkeypatch.setattr("app.growth_ops.email.smtplib.SMTP_SSL", FakeSMTP)
    return sent


def _payload(**changes):
    payload = {
        "to_email": "partner@example.test",
        "subject": "együttműködés",
        "body_text": "Az Imperial Holding ajánlata.",
        "idempotency_key": "a" * 64,
    }
    payload.update(changes)
    return payload


def test_missing_delivery_scope_fails_closed():
    with pytest.raises(TypeError, match="delivery_scope"):
        SMTPEmailAdapter(_binding()).send(**_payload())


def test_unknown_delivery_scope_fails_closed():
    with pytest.raises(
        GrowthRegistryError,
        match="outbound_delivery_scope_unknown_no_send",
    ):
        SMTPEmailAdapter(_binding()).send(
            **_payload(delivery_scope="unspecified")
        )


def test_external_customer_rejects_attachments_before_transport(smtp_transport):
    with pytest.raises(
        GrowthRegistryError,
        match="external_customer_attachments_no_send",
    ):
        SMTPEmailAdapter(_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                attachments=[("ajanlat.pdf", b"binary", "application/pdf")],
            )
        )

    assert smtp_transport == []


def test_external_customer_smtp_is_rejected_before_transport(smtp_transport):
    with pytest.raises(
        GrowthRegistryError,
        match="external_customer_gmail_oauth_required_no_send",
    ):
        SMTPEmailAdapter(_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_html="<p>Az Imperial Holding ajánlata.</p>",
                reply_to="info@imperialholding.hu",
            )
        )

    assert smtp_transport == []


@pytest.mark.parametrize(
    "foreign_brand",
    [
        "RED Property",
        "Imperial Intelligence",
        "CasaModerna",
        "danishfabrik.hu",
        "REDProperty",
        "EverydayHomes",
        "VentureStudio",
        "FamilyHomes",
        "ImperialConstruction",
        "ImperialIntelligence",
        "ImperialTechnologies",
        "ImperialKnowledge",
        "VeritasConstruct",
    ],
)
def test_external_customer_rejects_complete_foreign_brand_inventory(
    foreign_brand,
    smtp_transport,
):
    with pytest.raises(
        GrowthRegistryError,
        match="cross_brand_customer_facing_content_no_send",
    ):
        SMTPEmailAdapter(_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text=f"Az Imperial Holding és a {foreign_brand} ajánlata.",
            )
        )

    assert smtp_transport == []


def test_external_customer_requires_own_brand_identity(smtp_transport):
    with pytest.raises(
        GrowthRegistryError,
        match="outbound_required_brand_identity_missing_no_send",
    ):
        SMTPEmailAdapter(_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Szeretnénk együttműködni Önnel.",
            )
        )

    assert smtp_transport == []


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        (
            {"to_email": "safe@example.test,info@leier.hu"},
            "recipient_email_must_be_one_canonical_addr_spec_no_send",
        ),
        (
            {"to_email": "info@prefab.hu"},
            "cross_brand_customer_facing_content_no_send",
        ),
        (
            {"to_email": "info@leier.sk"},
            "outbound_recipient_hard_gate_no_send:BLOCK_LEIER_INCIDENT_CONTAINMENT",
        ),
        (
            {"to_email": "leier.contact@example.test"},
            "outbound_recipient_hard_gate_no_send:BLOCK_LEIER_INCIDENT_CONTAINMENT",
        ),
        (
            {"body_html": "<p>Imperial Holding és Pre&#102;ab</p>"},
            "cross_brand_customer_facing_content_no_send",
        ),
        (
            {"body_html": "<p>Imperial Holding és <span>Pre</span><span>fab</span></p>"},
            "cross_brand_customer_facing_content_no_send",
        ),
        (
            {"body_text": "Imperial Holding és Pre\u200bfab"},
            "cross_brand_customer_facing_content_no_send",
        ),
        (
            {"body_text": "Imperial Holding és Budapesti Magasépítő Vállalat"},
            "cross_brand_customer_facing_content_no_send",
        ),
    ],
)
def test_external_header_and_obfuscated_brand_gates_run_before_transport(
    changes,
    error,
    smtp_transport,
):
    with pytest.raises(GrowthRegistryError, match=re.escape(error)):
        SMTPEmailAdapter(_binding()).send(
            **_payload(delivery_scope="external_customer", **changes)
        )

    assert smtp_transport == []


@pytest.mark.parametrize(
    "changes",
    [
        {"to_email": "Partner <partner@example.test>"},
        {"reply_to": "Imperial <info@imperialholding.hu>"},
    ],
)
def test_external_address_headers_require_one_exact_addr_spec(changes, smtp_transport):
    with pytest.raises(GrowthRegistryError, match="canonical_addr_spec_no_send"):
        SMTPEmailAdapter(_binding()).send(
            **_payload(delivery_scope="external_customer", **changes)
        )
    assert smtp_transport == []


def test_external_sender_requires_one_exact_addr_spec(smtp_transport):
    with pytest.raises(
        GrowthRegistryError,
        match="sender_email_must_be_one_canonical_addr_spec_no_send",
    ):
        SMTPEmailAdapter(
            _binding(sender_email="Imperial <info@imperialholding.hu>")
        ).send(**_payload(delivery_scope="external_customer"))
    assert smtp_transport == []


def test_external_gmail_requires_read_scope_before_network(monkeypatch):
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be reached")

    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", fail_if_called)
    with pytest.raises(GrowthRegistryError, match="Gmail read OAuth scope is required"):
        SMTPEmailAdapter(
            _oauth_binding(scope="https://www.googleapis.com/auth/gmail.send")
        ).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Imperial Holding offer.",
            )
        )
    assert not called


def test_external_gmail_exact_sent_readback_roundtrip(monkeypatch):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)

    receipt = SMTPEmailAdapter(_oauth_binding()).send(
        **_payload(
            delivery_scope="external_customer",
            body_text="Imperial Holding offer.",
            body_html="<p>Imperial Holding offer.</p>",
            reply_to="info@imperialholding.hu",
        )
    )

    assert gmail.post_count == 1
    assert receipt.provider == "gmail_api"
    assert receipt.provider_message_id == gmail.provider_id
    assert receipt.detail["readback_verified"] is True
    assert receipt.detail["readback_mime_sha256"] == receipt.response_sha256
    assert receipt.detail["rfc_message_id"].startswith("<imperial-")
    assert receipt.detail["oauth_profile_email"] == "info@imperialholding.hu"


def test_external_gmail_profile_sender_mismatch_stops_before_send(monkeypatch):
    gmail = _FakeGmail()

    def mismatched_profile(request, timeout):
        if request.full_url == "https://oauth2.googleapis.com/token":
            return _HTTPResponse({"access_token": "access-token"})
        if request.full_url == "https://gmail.googleapis.com/gmail/v1/users/me/profile":
            return _HTTPResponse({"emailAddress": "other@imperialholding.hu"})
        return gmail.urlopen(request, timeout)

    monkeypatch.setattr(
        "app.growth_ops.email.urllib.request.urlopen", mismatched_profile
    )

    with pytest.raises(
        EmailDeliveryError,
        match="gmail_oauth_profile_sender_mismatch_no_send",
    ):
        SMTPEmailAdapter(_oauth_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Imperial Holding offer.",
            )
        )

    assert gmail.post_count == 0


def test_external_gmail_existing_exact_sent_is_reused_without_second_post(monkeypatch):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)
    adapter = SMTPEmailAdapter(_oauth_binding())
    payload = _payload(
        delivery_scope="external_customer",
        body_text="Imperial Holding offer.",
        reply_to="info@imperialholding.hu",
    )

    first = adapter.send(**payload)
    second = adapter.send(**payload)

    assert gmail.post_count == 1
    assert second.provider_message_id == first.provider_message_id
    assert second.detail["recovered_existing_sent"] is True


@pytest.mark.parametrize(
    "readback_mode",
    ["missing_sent", "mismatched_body", "unexpected_cc"],
)
def test_external_gmail_unverifiable_post_is_never_retry_safe(
    readback_mode,
    monkeypatch,
):
    gmail = _FakeGmail(readback_mode=readback_mode)
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)

    with pytest.raises(EmailDeliveryError, match="accepted_but_unverified") as raised:
        SMTPEmailAdapter(_oauth_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Imperial Holding offer.",
                reply_to="info@imperialholding.hu",
            )
        )

    assert gmail.post_count == 1
    assert raised.value.accepted_but_unverified is True
    assert raised.value.provider_message_id == gmail.provider_id
    assert raised.value.retry_safe is False


def test_external_gmail_existing_mismatch_blocks_without_second_post(monkeypatch):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)
    adapter = SMTPEmailAdapter(_oauth_binding())
    payload = _payload(
        delivery_scope="external_customer",
        body_text="Imperial Holding offer.",
        reply_to="info@imperialholding.hu",
    )
    adapter.send(**payload)
    gmail.readback_mode = "mismatched_body"

    with pytest.raises(EmailDeliveryError, match="accepted_but_unverified") as raised:
        adapter.send(**payload)

    assert gmail.post_count == 1
    assert raised.value.accepted_but_unverified is True
    assert raised.value.provider_message_id == gmail.provider_id


def test_external_gmail_post_transport_ambiguity_is_held_and_never_retry_safe(
    monkeypatch,
):
    gmail = _FakeGmail(readback_mode="post_transport_error")
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)

    with pytest.raises(EmailDeliveryError, match="accepted_but_unverified") as raised:
        SMTPEmailAdapter(_oauth_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Imperial Holding offer.",
                reply_to="info@imperialholding.hu",
            )
        )

    assert gmail.post_count == 1
    assert raised.value.accepted_but_unverified is True
    assert raised.value.provider_message_id is None
    assert raised.value.retry_safe is False


def test_external_gmail_pre_send_search_failure_does_not_claim_acceptance(monkeypatch):
    gmail = _FakeGmail()

    def fail_search(request, timeout):
        if request.full_url == "https://oauth2.googleapis.com/token":
            return _HTTPResponse({"access_token": "access-token"})
        if request.full_url == "https://gmail.googleapis.com/gmail/v1/users/me/profile":
            return _HTTPResponse({"emailAddress": "info@imperialholding.hu"})
        raise OSError("search unavailable")

    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", fail_search)

    with pytest.raises(
        EmailDeliveryError,
        match="pre_send_verification_failed_no_send",
    ) as raised:
        SMTPEmailAdapter(_oauth_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Imperial Holding offer.",
                reply_to="info@imperialholding.hu",
            )
        )

    assert gmail.post_count == 0
    assert raised.value.accepted_but_unverified is False
    assert raised.value.retry_safe is False


def test_internal_corporate_multi_brand_message_passes(smtp_transport):
    receipt = SMTPEmailAdapter(_binding()).send(
        to_email="vezetes@imperialholding.hu",
        subject="Belső márkaösszefoglaló",
        body_text="Imperial Holding, Prefab.hu, Bautica és BauFreund belső összefoglalója.",
        idempotency_key="b" * 64,
        delivery_scope="internal",
        attachments=[("belso.txt", b"Prefab.hu", "text/plain")],
    )

    assert receipt.provider == "smtp"
    assert len(smtp_transport) == 1


@pytest.mark.parametrize(
    ("binding", "to_email", "error"),
    [
        (
            _binding(brand_id="prefab", sender_email="info@prefab.hu"),
            "vezetes@imperialholding.hu",
            "internal_sender_brand_binding_mismatch_no_send",
        ),
        (
            _binding(),
            "partner@example.test",
            "internal_recipient_domain_no_send",
        ),
        (
            _binding(),
            "info@leier.hu",
            "outbound_recipient_hard_gate_no_send:BLOCK_LEIER_INCIDENT_CONTAINMENT",
        ),
    ],
)
def test_internal_scope_rejects_noncorporate_delivery(binding, to_email, error):
    with pytest.raises(GrowthRegistryError, match=re.escape(error)):
        SMTPEmailAdapter(binding).send(
            to_email=to_email,
            subject="Belső összefoglaló",
            body_text="Prefab.hu és Imperial Holding belső összefoglalója.",
            idempotency_key="c" * 64,
            delivery_scope="internal",
        )


def test_internal_smtp_binding_uses_normalized_imperial_brand_id(monkeypatch):
    class FakeSecretPath:
        def is_file(self):
            return True

        def stat(self):
            return SimpleNamespace(st_mode=stat.S_IFREG | 0o600)

        def read_text(self, *, encoding):
            assert encoding == "utf-8"
            return '{"host":"smtp.test"}'

    monkeypatch.setattr(
        processing,
        "settings",
        lambda: SimpleNamespace(canonical_internal_handoff_secret_file="secret.json"),
    )
    monkeypatch.setattr(processing, "Path", lambda _value: FakeSecretPath())

    binding = processing._smtp_binding()

    assert binding.brand_id == "imperial"
    assert binding.sender_email == "info@imperialholding.hu"
