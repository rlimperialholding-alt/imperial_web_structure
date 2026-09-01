from __future__ import annotations

from ..config import settings


def crm_service_headers(
    service_header: str,
    service_token: str,
    *,
    content_type: str | None = None,
    bypass_token: str | None = None,
) -> dict[str, str]:
    """Build fail-closed CRM service headers, including private Sites access."""

    headers = {
        "Accept": "application/json",
        service_header: service_token,
    }
    if content_type:
        headers["Content-Type"] = content_type
    resolved_bypass = (
        settings.crm_sites_bypass_token if bypass_token is None else bypass_token
    ).strip()
    if resolved_bypass:
        headers["OAI-Sites-Authorization"] = f"Bearer {resolved_bypass}"
    return headers
