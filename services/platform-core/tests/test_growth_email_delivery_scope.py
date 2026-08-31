from __future__ import annotations

import base64
import http.client
import io
import json
import re
import stat
import urllib.error
import urllib.parse
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.growth_ops import email as growth_email
from app.growth_ops import processing
from app.growth_ops.email import EmailDeliveryError, SMTPEmailAdapter
from app.growth_ops.registry import BrandBinding, GrowthRegistryError

_REAL_EXTERNAL_TRANSPORT_WINDOW_OPEN = growth_email._assert_external_transport_window_open


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
        self.value = (
            value if isinstance(value, (bytes, BaseException)) else json.dumps(value).encode()
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _limit):
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


class _FakeGmail:
    def __init__(
        self,
        *,
        readback_mode: str = "exact",
        quota_pages: dict[str, object] | None = None,
    ) -> None:
        self.readback_mode = readback_mode
        self.quota_pages = quota_pages
        self.provider_id = "gmail-provider-id"
        self.sent_raw: str | None = None
        self.post_count = 0
        self.quota_queries: list[dict[str, list[str]]] = []

    def urlopen(self, request, timeout):
        assert timeout == 30
        url = request.full_url
        if url == "https://oauth2.googleapis.com/token":
            return _HTTPResponse(
                {
                    "access_token": "access-token",
                    "token_type": "Bearer",
                    "scope": (
                        "https://www.googleapis.com/auth/gmail.compose "
                        "https://www.googleapis.com/auth/gmail.readonly"
                    ),
                }
            )
        if url == "https://gmail.googleapis.com/gmail/v1/users/me/profile":
            return _HTTPResponse({"emailAddress": "info@imperialholding.hu"})
        if "/users/me/messages?" in url:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            if query.get("labelIds") == ["SENT"] and query.get("maxResults") == ["500"]:
                self.quota_queries.append(query)
                if self.quota_pages is not None:
                    token = query.get("pageToken", [""])[0]
                    return _HTTPResponse(self.quota_pages[token])
                messages = [] if self.sent_raw is None else [{"id": self.provider_id}]
                return _HTTPResponse({"messages": messages})
            if self.sent_raw is None:
                return _HTTPResponse({"messages": []})
            return _HTTPResponse({"messages": [{"id": self.provider_id}]})
        if url.endswith("/messages/send"):
            self.post_count += 1
            if self.readback_mode == "post_transport_error":
                raise OSError("connection reset after request write")
            if self.readback_mode.startswith("post_http_"):
                status = int(self.readback_mode.rsplit("_", 1)[1])
                raise urllib.error.HTTPError(
                    url,
                    status,
                    "provider timeout",
                    {},
                    io.BytesIO(b'{"error":{"message":"provider timeout"}}'),
                )
            payload = json.loads(request.data)
            self.sent_raw = payload["raw"]
            if self.readback_mode == "incomplete_read":
                return _HTTPResponse(http.client.IncompleteRead(b"partial"))
            if self.readback_mode == "invalid_utf8":
                return _HTTPResponse(b"\xff")
            return _HTTPResponse({"id": self.provider_id})
        if url.endswith(f"/messages/{self.provider_id}?format=raw"):
            assert self.sent_raw is not None
            if self.readback_mode == "readback_incomplete":
                return _HTTPResponse(http.client.IncompleteRead(b"partial"))
            if self.readback_mode == "readback_invalid_utf8":
                return _HTTPResponse(b"\xff")
            labels = [] if self.readback_mode == "missing_sent" else ["SENT"]
            readback_raw = self.sent_raw
            if self.readback_mode == "mismatched_body":
                raw = base64.urlsafe_b64decode(readback_raw + "=" * (-len(readback_raw) % 4))
                raw = raw.replace(b"Imperial Holding offer.", b"Imperial Holding other.")
                readback_raw = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
            elif self.readback_mode == "unexpected_cc":
                raw = base64.urlsafe_b64decode(readback_raw + "=" * (-len(readback_raw) % 4))
                separator = b"\r\n\r\n" if b"\r\n\r\n" in raw else b"\n\n"
                raw = raw.replace(
                    separator,
                    separator[: len(separator) // 2] + b"Cc: attacker@example.test" + separator,
                    1,
                )
                readback_raw = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
            elif self.readback_mode == "mismatched_list_unsubscribe":
                raw = base64.urlsafe_b64decode(readback_raw + "=" * (-len(readback_raw) % 4))
                original = (
                    b"List-Unsubscribe: "
                    b"<https://imperialholding.hu/growth/unsubscribe/token>"
                )
                assert original in raw
                raw = raw.replace(
                    original,
                    b"List-Unsubscribe: <https://example.test/unsubscribe/other>",
                    1,
                )
                readback_raw = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
            elif self.readback_mode == "mismatched_list_unsubscribe_post":
                raw = base64.urlsafe_b64decode(readback_raw + "=" * (-len(readback_raw) % 4))
                original = b"List-Unsubscribe-Post: List-Unsubscribe=One-Click"
                assert original in raw
                raw = raw.replace(
                    original,
                    b"List-Unsubscribe-Post: List-Unsubscribe=No",
                    1,
                )
                readback_raw = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
            elif self.readback_mode == "attachment_mismatch":
                raw = base64.urlsafe_b64decode(readback_raw + "=" * (-len(readback_raw) % 4))
                original = base64.b64encode(b"Prefab.hu")
                assert original in raw
                raw = raw.replace(original, base64.b64encode(b"Other.txt"), 1)
                readback_raw = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
            return _HTTPResponse(
                {
                    "id": self.provider_id,
                    "labelIds": labels,
                    "internalDate": "1788160000000",
                    "raw": readback_raw,
                }
            )
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture(autouse=True)
def external_transport_window_open(monkeypatch):
    monkeypatch.setattr(
        "app.growth_ops.email._assert_external_transport_window_open",
        lambda: None,
    )


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
        "pre_send_guard": lambda: None,
        "account_quota_guard": lambda: None,
        "unsubscribe_url": "https://imperialholding.hu/growth/unsubscribe/token",
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
        SMTPEmailAdapter(_binding()).send(**_payload(delivery_scope="unspecified"))


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
        match="account_scoped_gmail_oauth_required_no_send",
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
        SMTPEmailAdapter(_binding()).send(**_payload(delivery_scope="external_customer", **changes))

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
        SMTPEmailAdapter(_binding()).send(**_payload(delivery_scope="external_customer", **changes))
    assert smtp_transport == []


def test_external_sender_requires_one_exact_addr_spec(smtp_transport):
    with pytest.raises(
        GrowthRegistryError,
        match="sender_email_must_be_one_canonical_addr_spec_no_send",
    ):
        SMTPEmailAdapter(_binding(sender_email="Imperial <info@imperialholding.hu>")).send(
            **_payload(delivery_scope="external_customer")
        )
    assert smtp_transport == []


def test_external_gmail_requires_read_scope_before_network(monkeypatch):
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be reached")

    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", fail_if_called)
    with pytest.raises(GrowthRegistryError, match="Gmail read OAuth scope is required"):
        SMTPEmailAdapter(_oauth_binding(scope="https://www.googleapis.com/auth/gmail.send")).send(
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


def test_external_gmail_uses_no_rolling_sent_scan_and_calls_no_arg_quota_guard(
    monkeypatch,
):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)
    calls = []

    def daily_quota_guard():
        assert gmail.post_count == 0
        calls.append("daily-quota")

    receipt = SMTPEmailAdapter(_oauth_binding()).send(
        **_payload(
            delivery_scope="external_customer",
            body_text="Imperial Holding offer.",
            account_quota_guard=daily_quota_guard,
        )
    )

    assert calls == ["daily-quota"]
    assert gmail.quota_queries == []
    assert gmail.post_count == 1
    assert receipt.provider_message_id == gmail.provider_id


def test_external_gmail_daily_quota_guard_failure_is_before_post(monkeypatch):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)

    def daily_quota_full():
        raise EmailDeliveryError(
            "outreach_budapest_day_limit_reached_no_send",
            retry_safe=True,
        )

    with pytest.raises(
        EmailDeliveryError,
        match="outreach_budapest_day_limit_reached_no_send",
    ):
        SMTPEmailAdapter(_oauth_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Imperial Holding offer.",
                account_quota_guard=daily_quota_full,
            )
        )

    assert gmail.quota_queries == []
    assert gmail.post_count == 0
    assert gmail.sent_raw is None


def test_external_gmail_requires_account_quota_guard_before_post(monkeypatch):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)

    with pytest.raises(
        GrowthRegistryError,
        match="external_customer_account_quota_guard_required_no_send",
    ):
        SMTPEmailAdapter(_oauth_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Imperial Holding offer.",
                account_quota_guard=None,
            )
        )

    assert gmail.post_count == 0
    assert gmail.sent_raw is None


def test_external_gmail_requires_https_unsubscribe_before_network(monkeypatch):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)

    with pytest.raises(
        GrowthRegistryError,
        match="outbound_https_unsubscribe_url_required_no_send",
    ):
        SMTPEmailAdapter(_oauth_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Imperial Holding offer.",
                unsubscribe_url=None,
            )
        )

    assert gmail.quota_queries == []
    assert gmail.post_count == 0
    assert gmail.sent_raw is None


@pytest.mark.parametrize(
    "readback_mode",
    ["mismatched_list_unsubscribe", "mismatched_list_unsubscribe_post"],
)
def test_external_gmail_rfc8058_readback_tamper_is_held(
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
            )
        )

    assert gmail.post_count == 1
    assert raised.value.accepted_but_unverified is True
    assert raised.value.retry_safe is False
    assert raised.value.provider_message_id == gmail.provider_id


def test_external_gmail_rechecks_guard_immediately_before_send_post(monkeypatch):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)
    guard_calls = 0

    def window_closed_at_post_boundary():
        nonlocal guard_calls
        guard_calls += 1
        raise GrowthRegistryError("outreach_sending_window_closed_no_send")

    with pytest.raises(
        GrowthRegistryError,
        match="outreach_sending_window_closed_no_send",
    ):
        SMTPEmailAdapter(_oauth_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Imperial Holding offer.",
                pre_send_guard=window_closed_at_post_boundary,
            )
        )

    assert guard_calls == 1
    assert gmail.post_count == 0
    assert gmail.sent_raw is None


def test_external_gmail_authoritative_window_guard_runs_before_send_post(monkeypatch):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)
    window_calls = 0

    def closed_window():
        nonlocal window_calls
        window_calls += 1
        raise GrowthRegistryError("outreach_sending_window_closed_no_send")

    monkeypatch.setattr(
        "app.growth_ops.email._assert_external_transport_window_open",
        closed_window,
    )
    with pytest.raises(
        GrowthRegistryError,
        match="outreach_sending_window_closed_no_send",
    ):
        SMTPEmailAdapter(_oauth_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Imperial Holding offer.",
            )
        )

    assert window_calls == 1
    assert gmail.post_count == 0
    assert gmail.sent_raw is None


def test_external_gmail_all_day_window_allows_1930_pre_post(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = cls(2026, 8, 31, 17, 30, tzinfo=UTC)
            return current.astimezone(tz) if tz else current.replace(tzinfo=None)

    gmail = _FakeGmail()
    monkeypatch.setattr(growth_email.urllib.request, "urlopen", gmail.urlopen)
    monkeypatch.setattr(growth_email, "datetime", FixedDateTime)
    monkeypatch.setattr(
        growth_email,
        "growth_settings",
        lambda: SimpleNamespace(
            timezone="Europe/Budapest",
            outreach_send_start_local="00:00",
            outreach_send_end_local="00:00",
            outreach_budapest_day_max=2000,
        ),
    )
    monkeypatch.setattr(
        growth_email,
        "_assert_external_transport_window_open",
        _REAL_EXTERNAL_TRANSPORT_WINDOW_OPEN,
    )

    receipt = SMTPEmailAdapter(_oauth_binding()).send(
        **_payload(
            delivery_scope="external_customer",
            body_text="Imperial Holding offer.",
        )
    )

    assert receipt.provider == "gmail_api"
    assert gmail.post_count == 1


def test_external_gmail_inverted_partial_window_fails_closed(monkeypatch):
    monkeypatch.setattr(
        growth_email,
        "growth_settings",
        lambda: SimpleNamespace(
            timezone="Europe/Budapest",
            outreach_send_start_local="18:00",
            outreach_send_end_local="08:00",
        ),
    )
    monkeypatch.setattr(
        growth_email,
        "_assert_external_transport_window_open",
        _REAL_EXTERNAL_TRANSPORT_WINDOW_OPEN,
    )

    with pytest.raises(
        GrowthRegistryError,
        match="Outreach sending window must start before it ends",
    ):
        growth_email._assert_external_transport_window_open()


def test_external_gmail_rechecks_authoritative_clock_after_capacity_guard(monkeypatch):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)
    events = []

    def boundary_window():
        events.append("window")
        if events == ["window", "capacity", "window"]:
            raise GrowthRegistryError("outreach_sending_window_closed_no_send")

    def capacity_guard():
        events.append("capacity")

    monkeypatch.setattr(
        "app.growth_ops.email._assert_external_transport_window_open",
        boundary_window,
    )
    with pytest.raises(
        GrowthRegistryError,
        match="outreach_sending_window_closed_no_send",
    ):
        SMTPEmailAdapter(_oauth_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Imperial Holding offer.",
                pre_send_guard=capacity_guard,
            )
        )

    assert events == ["window", "capacity", "window"]
    assert gmail.post_count == 0
    assert gmail.sent_raw is None


def test_external_gmail_requires_immediate_pre_send_guard(monkeypatch):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)

    with pytest.raises(
        GrowthRegistryError,
        match="external_customer_pre_send_guard_required_no_send",
    ):
        SMTPEmailAdapter(_oauth_binding()).send(
            **_payload(
                delivery_scope="external_customer",
                body_text="Imperial Holding offer.",
                pre_send_guard=None,
            )
        )

    assert gmail.post_count == 0
    assert gmail.sent_raw is None


def test_external_gmail_profile_sender_mismatch_stops_before_send(monkeypatch):
    gmail = _FakeGmail()

    def mismatched_profile(request, timeout):
        if request.full_url == "https://oauth2.googleapis.com/token":
            return _HTTPResponse({"access_token": "access-token"})
        if request.full_url == "https://gmail.googleapis.com/gmail/v1/users/me/profile":
            return _HTTPResponse({"emailAddress": "other@imperialholding.hu"})
        return gmail.urlopen(request, timeout)

    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", mismatched_profile)

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


def test_external_gmail_live_preflight_refreshes_and_matches_profile(monkeypatch):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)

    detail = SMTPEmailAdapter(_oauth_binding()).live_preflight(
        delivery_scope="external_customer"
    )

    assert detail == {
        "provider": "gmail_api",
        "profile_email": "info@imperialholding.hu",
        "granted_scope_verified": "gmail_send_or_compose+gmail_read",
    }
    assert gmail.post_count == 0
    assert gmail.sent_raw is None


def test_external_gmail_live_preflight_rejects_profile_mismatch(monkeypatch):
    gmail = _FakeGmail()

    def mismatched_profile(request, timeout):
        if request.full_url == "https://oauth2.googleapis.com/token":
            return _FakeGmail().urlopen(request, timeout)
        if request.full_url == "https://gmail.googleapis.com/gmail/v1/users/me/profile":
            return _HTTPResponse({"emailAddress": "other@imperialholding.hu"})
        return gmail.urlopen(request, timeout)

    monkeypatch.setattr(
        "app.growth_ops.email.urllib.request.urlopen", mismatched_profile
    )

    with pytest.raises(
        GrowthRegistryError,
        match="gmail_live_preflight_sender_mismatch_no_send",
    ):
        SMTPEmailAdapter(_oauth_binding()).live_preflight(
            delivery_scope="external_customer"
        )

    assert gmail.post_count == 0


def test_external_gmail_live_preflight_rejects_missing_actual_read_scope(monkeypatch):
    profile_calls = 0

    def insufficient_grant(request, timeout):
        nonlocal profile_calls
        assert timeout == 30
        if request.full_url == "https://oauth2.googleapis.com/token":
            return _HTTPResponse(
                {
                    "access_token": "access-token",
                    "token_type": "Bearer",
                    "scope": "https://www.googleapis.com/auth/gmail.compose",
                }
            )
        profile_calls += 1
        return _HTTPResponse({"emailAddress": "info@imperialholding.hu"})

    monkeypatch.setattr(
        "app.growth_ops.email.urllib.request.urlopen", insufficient_grant
    )

    with pytest.raises(
        GrowthRegistryError,
        match="gmail_live_preflight_granted_read_scope_missing_no_send",
    ):
        SMTPEmailAdapter(_oauth_binding()).live_preflight(
            delivery_scope="external_customer"
        )

    assert profile_calls == 0


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


@pytest.mark.parametrize("status", [408, 500])
def test_external_gmail_post_timeout_or_server_error_is_held_without_resend(
    status,
    monkeypatch,
):
    gmail = _FakeGmail(readback_mode=f"post_http_{status}")
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
    assert raised.value.transport_attempted is True
    assert raised.value.retry_safe is False
    assert raised.value.http_status == status


@pytest.mark.parametrize("readback_mode", ["incomplete_read", "invalid_utf8"])
def test_external_gmail_post_response_protocol_errors_are_ambiguous(
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
    assert raised.value.transport_attempted is True
    assert raised.value.retry_safe is False


@pytest.mark.parametrize(
    "readback_mode", ["readback_incomplete", "readback_invalid_utf8"]
)
def test_external_gmail_post_readback_protocol_errors_are_ambiguous(
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
    assert raised.value.transport_attempted is True
    assert raised.value.provider_message_id == gmail.provider_id
    assert raised.value.retry_safe is False


@pytest.mark.parametrize(
    "readback_mode", ["readback_incomplete", "readback_invalid_utf8"]
)
def test_external_gmail_existing_readback_protocol_errors_do_not_second_post(
    readback_mode,
    monkeypatch,
):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)
    adapter = SMTPEmailAdapter(_oauth_binding())
    payload = _payload(
        delivery_scope="external_customer",
        body_text="Imperial Holding offer.",
        reply_to="info@imperialholding.hu",
    )
    adapter.send(**payload)
    gmail.readback_mode = readback_mode

    with pytest.raises(EmailDeliveryError) as raised:
        adapter.send(**payload)

    assert gmail.post_count == 1
    assert raised.value.retry_safe is False
    assert raised.value.transport_attempted is False


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
    assert raised.value.retry_safe is True


def test_internal_info_account_requires_gmail_oauth(smtp_transport):
    with pytest.raises(
        GrowthRegistryError,
        match="account_scoped_gmail_oauth_required_no_send",
    ):
        SMTPEmailAdapter(_binding()).send(
            to_email="vezetes@imperialholding.hu",
            subject="Belső márkaösszefoglaló",
            body_text="Imperial Holding, Prefab.hu, Bautica és BauFreund belső összefoglalója.",
            idempotency_key="b" * 64,
            delivery_scope="internal",
            attachments=[("belso.txt", b"Prefab.hu", "text/plain")],
        )
    assert smtp_transport == []


def test_internal_gmail_uses_account_guard_without_external_window(monkeypatch):
    gmail = _FakeGmail()
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)
    window_calls = 0

    def external_window_must_not_run():
        nonlocal window_calls
        window_calls += 1
        raise AssertionError("internal Gmail delivery must not use external outreach window")

    monkeypatch.setattr(
        "app.growth_ops.email._assert_external_transport_window_open",
        external_window_must_not_run,
    )
    receipt = SMTPEmailAdapter(_oauth_binding()).send(
        to_email="vezetes@imperialholding.hu",
        subject="Belső márkaösszefoglaló",
        body_text="Imperial Holding, Prefab.hu, Bautica és BauFreund belső összefoglalója.",
        idempotency_key="b" * 64,
        delivery_scope="internal",
        attachments=[("belso.txt", b"Prefab.hu", "text/plain")],
        pre_send_guard=lambda: None,
        account_quota_guard=lambda: None,
    )

    assert receipt.provider == "gmail_api"
    assert gmail.post_count == 1
    assert window_calls == 0


def test_internal_gmail_attachment_readback_mismatch_is_held(monkeypatch):
    gmail = _FakeGmail(readback_mode="attachment_mismatch")
    monkeypatch.setattr("app.growth_ops.email.urllib.request.urlopen", gmail.urlopen)

    with pytest.raises(EmailDeliveryError, match="accepted_but_unverified") as raised:
        SMTPEmailAdapter(_oauth_binding()).send(
            to_email="vezetes@imperialholding.hu",
            subject="Belső márkaösszefoglaló",
            body_text=(
                "Imperial Holding, Prefab.hu, Bautica és BauFreund belső összefoglalója."
            ),
            idempotency_key="b" * 64,
            delivery_scope="internal",
            attachments=[("belso.txt", b"Prefab.hu", "text/plain")],
            pre_send_guard=lambda: None,
            account_quota_guard=lambda: None,
        )

    assert gmail.post_count == 1
    assert raised.value.accepted_but_unverified is True
    assert raised.value.retry_safe is False
    assert raised.value.provider_message_id == gmail.provider_id


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
