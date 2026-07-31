from __future__ import annotations

import base64
import hashlib
import hmac
import json
from types import SimpleNamespace

from app.services import itep_finance
from app import main


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(
            {"total": 1, "items": [{"invoiceNumber": "INV-1"}]}
        ).encode("utf-8")


def test_incoming_invoice_request_is_signed_and_read_only(monkeypatch):
    secret = "test-itep-identity-shared-secret-which-is-long-enough"
    monkeypatch.setattr(
        itep_finance,
        "settings",
        SimpleNamespace(
            itep_api_base_url="http://itep-api:3000",
            itep_identity_shared_secret=secret,
        ),
    )
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(itep_finance, "urlopen", fake_urlopen)
    result = itep_finance.incoming_invoices(
        SimpleNamespace(email="finance@imperial.local", role="finance"),
        page=2,
        search="Minta Partner",
        payment_status="UNPAID",
        currency="huf",
    )

    request = captured["request"]
    encoded = request.headers["X-imperial-identity"]
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    payload = json.loads(
        base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    )
    assert request.get_method() == "GET"
    assert "page=2" in request.full_url
    assert "paymentStatus=UNPAID" in request.full_url
    assert "currency=HUF" in request.full_url
    assert request.headers["X-imperial-identity-signature"] == (
        f"sha256={expected_signature}"
    )
    assert payload["permissions"] == ["financial:read"]
    assert result["items"][0]["invoiceNumber"] == "INV-1"


def test_incoming_invoice_screen_renders_live_projection(
    logged_in_client,
    monkeypatch,
):
    monkeypatch.setattr(
        main,
        "incoming_invoices",
        lambda *_args, **_kwargs: {
            "page": 1,
            "pageSize": 50,
            "total": 1,
            "totalPages": 1,
            "filters": {
                "search": "",
                "paymentStatus": "",
                "currency": "",
            },
            "summary": {
                "paid": 0,
                "unpaid": 1,
                "currencyTotals": {
                    "HUF": {"count": 1, "grossAmount": 1270}
                },
            },
            "items": [
                {
                    "invoiceNumber": "INV-1",
                    "partnerName": "Minta Partner Kft.",
                    "taxNumber": "12345678",
                    "category": "Egyéb",
                    "issueDate": "2026-07-30",
                    "dueDate": "2026-08-15",
                    "grossAmount": 1270,
                    "netAmount": 1000,
                    "currency": "HUF",
                    "paymentStatus": "UNPAID",
                    "paymentDate": None,
                    "paymentMethod": "Átutalás",
                }
            ],
        },
    )
    response = logged_in_client.get("/financial/incoming-invoices")
    assert response.status_code == 200
    assert "Bejövő számlák" in response.text
    assert "Minta Partner Kft." in response.text
    assert "1 270.00 HUF" in response.text
