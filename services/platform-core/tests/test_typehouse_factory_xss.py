"""Reflective XSS negatív tesztek a Typehouse Factory UI-útvonalára."""

from __future__ import annotations


class TestLoginRedirectHeader:
    def test_unauthenticated_factory_page_never_echoes_request_data(self, client) -> None:
        # A korábbi /login?next={request.url.path} minta a felhasználói útvonalat
        # beépítette a Location fejlécbe; a fail-closed javítás után a fejléc
        # konstans, felhasználói adat nem kerülhet bele.
        response = client.get(
            "/housevision/typehouse-factory?notice=<script>alert(1)</script>",
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers["location"]
        assert location == "/login"
        assert "<" not in location and ">" not in location and '"' not in location
        assert "\r" not in location and "\n" not in location
        assert "script" not in location.lower()

    def test_notice_is_escaped_when_authenticated(self, logged_in_client) -> None:
        payload = "<script>window.pwned=true</script>"
        response = logged_in_client.get(
            f"/housevision/typehouse-factory?notice={payload}",
            follow_redirects=False,
        )
        assert response.status_code == 200
        body = response.text
        # A raw script-tag soha nem jelenhet meg; a tartalom HTML-escape-elve
        # (szerveroldali html.escape + Jinja autoescape) látható csak.
        assert "<script>window.pwned=true</script>" not in body
        assert "&amp;lt;script" in body

    def test_unauthenticated_post_redirect_contains_no_raw_markup(self, client) -> None:
        response = client.post(
            "/housevision/typehouse-factory/jobs",
            data={"source_url": "https://example.test/house"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers["location"]
        assert "<" not in location and ">" not in location and '"' not in location
