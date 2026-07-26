from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._json(200, {"status": "ok", "mode": "synthetic"})
            return
        if path == "/v3/documents":
            self._json(200, {
                "data": [{
                    "id": "mock-invoice-1",
                    "invoice_number": "MOCK-2026-001",
                    "payment_status": "OVERDUE",
                    "gross_total": 1250000,
                    "currency": "HUF",
                    "partner": {"name": "Teszt Ügyfél", "emails": ["test@example.invalid"]},
                    "due_date": "2026-07-20",
                    "invoice_date": "2026-07-24",
                }],
                "current_page": 1,
                "last_page": 1,
            })
            return
        if path.startswith("/accounts/") and path.endswith("/transactions"):
            self._json(200, {
                "transactions": {"booked": [{
                    "transactionId": "mock-tx-1",
                    "bookingDate": "2026-07-24",
                    "transactionAmount": {"amount": "250000", "currency": "HUF"},
                    "creditorName": "Teszt Partner",
                    "remittanceInformationUnstructured": "MOCK-2026-001",
                    "status": "BOOKED",
                }]}
            })
            return
        if path == "/v25.0/act_mock/insights":
            self._json(200, {
                "data": [{
                    "account_id": "mock",
                    "account_currency": "HUF",
                    "campaign_id": "meta-campaign-1",
                    "campaign_name": "Meta tesztkampány",
                    "date_start": "2026-07-26",
                    "date_stop": "2026-07-26",
                    "impressions": "1200",
                    "clicks": "48",
                    "spend": "15600",
                    "actions": [{"action_type": "lead", "value": "4"}],
                }],
            })
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        if path == "/oauth2/token":
            self._json(200, {
                "access_token": "synthetic-google-oauth-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            })
            return
        if path == "/v25/customers/1234567890/googleAds:searchStream":
            self._json(200, [{
                "results": [{
                    "campaign": {
                        "id": "google-campaign-1",
                        "name": "Google tesztkampány",
                        "status": "ENABLED",
                    },
                    "segments": {"date": "2026-07-26"},
                    "customer": {"currencyCode": "HUF"},
                    "metrics": {
                        "impressions": "2400",
                        "clicks": "96",
                        "costMicros": "28400000000",
                        "conversions": 7,
                    },
                }],
            }])
            return
        self._json(404, {"error": "not_found"})

    def log_message(self, *_: object) -> None:
        return


ThreadingHTTPServer(("0.0.0.0", 9010), Handler).serve_forever()
