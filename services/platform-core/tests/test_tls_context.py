"""TLS-verzióellenőrzés: publikus provider-fetch csak igazolt TLS 1.2+-t használhat."""

from __future__ import annotations

import ssl

from app.services.market_intelligence import _verified_tls_context


def test_provider_tls_context_pins_minimum_tls_1_2() -> None:
    context = _verified_tls_context()
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    # A hitelesítés alapértelmezetten kötelező (CERT_REQUIRED + hostname-ellenőrzés).
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
