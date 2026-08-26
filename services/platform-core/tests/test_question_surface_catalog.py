from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.growth_ops import catalog
from app.growth_ops.models import SourceCoverageRoute


def _route(url: str) -> SourceCoverageRoute:
    return SourceCoverageRoute(
        route_key="question-surface-test",
        route_id="TEST-QA",
        catalog_sha256="a" * 64,
        route_url=url,
        source_row_sha256="b" * 64,
        source_record_json="{}",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_public_page_with_login_navigation_is_not_an_auth_wall() -> None:
    body = """
    <html><head><title>Szakmai kérdések</title></head><body>
      <nav><a href="/bejelentkezes">Bejelentkezés</a></nav>
      <main><a href="/szakivalaszol/tetofelujitas">Hogyan újítsam fel a tetőt?</a></main>
    </body></html>
    """
    text, _ = catalog._page_evidence(body, base_url="https://joszaki.hu/szakivalaszol", limit=6000)
    assert not catalog._looks_like_blocked_response(
        status_code=200,
        route_url="https://joszaki.hu/szakivalaszol",
        title="Szakmai kérdések",
        body_text=body,
        visible_text=text,
    )


def test_real_login_page_is_still_blocked() -> None:
    body = "<html><title>Bejelentkezés</title><form><input type='password'></form></html>"
    assert catalog._looks_like_blocked_response(
        status_code=200,
        route_url="https://example.test/bejelentkezes",
        title="Bejelentkezés",
        body_text=body,
        visible_text="Bejelentkezés",
    )


def test_qjob_div_task_cards_become_specific_link_candidates() -> None:
    body = """
    <html><body>
      <a href="/kapcsolat">Kapcsolat</a>
      <div class="work card" id="210476" href="/tasks/210476">
        <a><h2>Beton kerítés építés</h2></a>
        <p>Húsz méter kerítés kivitelezéséhez keresek szakembert.</p>
      </div>
    </body></html>
    """
    _, links = catalog._page_evidence(
        body,
        base_url="https://qjob.hu/budapest/munka/epitesz-munka",
        limit=6000,
    )
    assert links[0] == {
        "url": "https://qjob.hu/tasks/210476",
        "label": "Beton kerítés építés Húsz méter kerítés kivitelezéséhez keresek szakembert.",
    }
    assert links[1:] == [
        {
            "url": "https://qjob.hu/kapcsolat",
            "label": "Kapcsolat",
        }
    ]


def test_fetch_analyzes_content_after_old_200k_cutoff(monkeypatch) -> None:
    tail = '<a href="/szakivalaszol/tetofelujitas">Hogyan újítsam fel a tetőt?</a>'
    body = ("<html><title>Kérdések</title><body>" + ("x" * 210_000) + tail + "</body></html>").encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/html"})

    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(catalog.httpx, "Client", client_factory)
    result = catalog._fetch(_route("https://joszaki.hu/szakivalaszol"))

    assert result["status"] == "succeeded"
    assert any(
        item["url"] == "https://joszaki.hu/szakivalaszol/tetofelujitas"
        for item in result["analysis_links"]
    )


def test_route_overlay_survives_catalog_reimport() -> None:
    row = catalog._row(
        {
            "RouteKey": "qjob",
            "RouteID": "SRC-0002",
            "Katalógusstátusz": "ENABLED",
            "Útvonal URL": "https://qjob.hu",
        },
        "c" * 64,
        datetime.now(UTC),
    )
    assert row["route_url"] == "https://qjob.hu/budapest/munka/epitesz-munka"
