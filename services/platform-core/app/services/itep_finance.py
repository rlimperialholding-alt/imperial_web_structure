from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import settings


class ItepFinanceError(RuntimeError):
    pass


def _identity_headers(user: object) -> dict[str, str]:
    now = int(time.time())
    payload = {
        "actorId": str(getattr(user, "email", "") or getattr(user, "user_id", "")),
        "organizationId": "imperial-holding",
        "roles": [str(getattr(user, "role", ""))],
        "permissions": ["financial:read"],
        "issuedAt": now,
        "expiresAt": now + 120,
        "nonce": str(uuid.uuid4()),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(
        settings.itep_identity_shared_secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Accept": "application/json",
        "X-Imperial-Identity": encoded,
        "X-Imperial-Identity-Signature": f"sha256={signature}",
    }


def incoming_invoices(
    user: object,
    *,
    page: int = 1,
    page_size: int = 50,
    search: str = "",
    payment_status: str = "",
    currency: str = "",
) -> dict[str, Any]:
    if not settings.itep_api_base_url or len(settings.itep_identity_shared_secret) < 32:
        raise ItepFinanceError("Az ITEP pénzügyi adatkapcsolat nincs konfigurálva.")
    query: dict[str, int | str] = {
        "page": max(1, page),
        "pageSize": min(100, max(10, page_size)),
    }
    if search.strip():
        query["search"] = search.strip()[:120]
    if payment_status in {"PAID", "UNPAID"}:
        query["paymentStatus"] = payment_status
    if len(currency.strip()) == 3:
        query["currency"] = currency.strip().upper()
    url = (
        f"{settings.itep_api_base_url.rstrip('/')}"
        f"/v1/financial/incoming-invoices?{urlencode(query)}"
    )
    request = Request(url, headers=_identity_headers(user), method="GET")
    try:
        with urlopen(request, timeout=15) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ItepFinanceError(
            f"Az ITEP pénzügyi lekérdezés {exc.code} hibával leállt."
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ItepFinanceError(
            "Az ITEP pénzügyi adatkapcsolat átmenetileg nem érhető el."
        ) from exc
