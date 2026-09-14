from app.services.pricing import WEB_PRICES_FILE


def test_unicode_normalized_calculation_source_is_portably_resolved():
    assert WEB_PRICES_FILE.is_file()
    assert WEB_PRICES_FILE.name.endswith("weboldal_2026-07.xlsx")
