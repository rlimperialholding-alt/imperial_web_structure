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


def test_source_page_publication_metadata_is_preserved_but_modified_time_is_not() -> None:
    body = """
    <html><head><script type="application/ld+json">
      {"@type":"Article","datePublished":"2025-01-17T18:48:41.385Z",
       "dateModified":"2026-09-06T09:00:00Z"}
    </script></head><body><main>Építési napló kérdés.</main></body></html>
    """
    text, _ = catalog._page_evidence(
        body, base_url="https://joszaki.hu/szakivalaszol/kerdes-1", limit=6000
    )
    assert "published_at_source=source_page" in text
    assert "2025-01-17T18:48:41.385Z" in text
    assert "2026-09-06T09:00:00Z" not in text


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


def test_concrete_reply_page_metadata_uses_original_post_date_and_state() -> None:
    body = """
    <script type="application/ld+json">
      {"datePublished":"2026-09-02T09:24:48.109+02:00"}
    </script>
    <script>
      {"status":"published","taskResponsesCount":0,
       "publishedAt":"2026-09-02T09:24:48.109+02:00"}
    </script>
    """
    metadata = catalog._reply_page_metadata(
        body, source_url="https://qjob.hu/tasks/215605"
    )
    assert metadata == {
        "published_at_raw": "2026-09-02T09:24:48.109+02:00",
        "active_status_raw": "published",
        "active_status": "active",
        "answer_count_raw": "0 válasz",
        "existing_answer_count": "0",
        "published_at_source": "source_page",
        "source_url": "https://qjob.hu/tasks/215605",
    }


def test_reply_page_candidate_rejects_category_and_cross_host_links() -> None:
    base = "https://joszaki.hu/szakivalaszol"
    assert catalog._reply_page_candidate(
        "https://joszaki.hu/szakivalaszol/lapostetos-haz-hoszigetelese",
        base_url=base,
    )
    assert not catalog._reply_page_candidate(
        "https://joszaki.hu/szakivalaszol/szakma/konyveles",
        base_url=base,
    )
    assert not catalog._reply_page_candidate(
        "https://example.test/szakivalaszol/lapostetos-haz-hoszigetelese",
        base_url=base,
    )
    assert catalog._reply_page_candidate(
        "https://forum.index.hu/Article/showArticle?t=9250012",
        base_url="https://forum.index.hu/Topic/showTopicList",
    )
    assert catalog._reply_page_candidate(
        "https://www.reddit.com/r/hungary/comments/abc123/epitkezes/",
        base_url="https://www.reddit.com/r/hungary/.rss",
    )


def test_public_atom_feed_preserves_entry_date_and_permalink() -> None:
    body = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>r/hungary</title>
      <entry>
        <title>Mennyiből lehet felújítani ezt a házat?</title>
        <published>2026-09-05T10:15:00+00:00</published>
        <link rel="alternate" href="https://www.reddit.com/r/hungary/comments/abc123/felujitas/" />
        <content type="html">Kivitelezőt és költségbecslést keresek.</content>
      </entry>
    </feed>
    """
    text, links = catalog._page_evidence(
        body,
        base_url="https://www.reddit.com/r/hungary/.rss",
        limit=6000,
    )
    assert "published_at_raw=2026-09-05T10:15:00+00:00" in text or any(
        "published_at_raw=2026-09-05T10:15:00+00:00" in item["label"] for item in links
    )
    assert links == [
        {
            "url": "https://www.reddit.com/r/hungary/comments/abc123/felujitas/",
            "label": (
                "Mennyiből lehet felújítani ezt a házat? Kivitelezőt és költségbecslést keresek.\n"
                "[SOURCE_PAGE_EVIDENCE] published_at_raw=2026-09-05T10:15:00+00:00; "
                "published_at_source=source_page; active_status_raw=active; active_status=active"
            ),
        }
    ]


def test_rss_feed_items_are_discovered_and_search_results_cross_host() -> None:
    rss = """<?xml version="1.0" encoding="UTF-8"?><rss><channel>
      <item><title>Tudtok megbízható kivitelezőt?</title>
      <pubDate>Sun, 06 Sep 2026 10:15:00 GMT</pubDate>
      <link>https://forum.example.hu/threads/kivitelezo-ajanlas.12345/</link>
      <description>Ajánlást és árajánlatot keresek.</description></item>
    </channel></rss>"""
    _text, rss_links = catalog._page_evidence(
        rss,
        base_url="https://www.reddit.com/r/askhungary/.rss",
        limit=6000,
    )
    assert rss_links[0]["url"].endswith("kivitelezo-ajanlas.12345/")
    assert "published_at_source=source_page" in rss_links[0]["label"]

    search = """<html><body><li class="b_algo">
      <h2><a href="https://forum.example.hu/threads/kivitelezo-ajanlas.12345/">
      Tudtok megbízható kivitelezőt? Építkezés fórum</a></h2>
    </li><a href="https://irrelevant.example/threads/other.123">Másik</a></body></html>"""
    _text, search_links = catalog._page_evidence(
        search,
        base_url="https://www.bing.com/search?q=epitkezes+kivitelezo+forum",
        limit=6000,
    )
    assert search_links == [
        {
            "url": "https://forum.example.hu/threads/kivitelezo-ajanlas.12345/",
            "label": "Tudtok megbízható kivitelezőt? Építkezés fórum",
        }
    ]


def test_fetch_search_discovery_rechecks_each_forum_post(monkeypatch) -> None:
    route = _route("https://www.bing.com/search?q=epitkezes+kivitelezo+forum")
    route.category = "forum"
    route.source_type = "public_html"
    route.source_name = "Automatikus fórumfelfedezés"
    route.route_mode = "direct"
    route.search_signal = "építkezés; kivitelező; fórum"
    route.source_record_json = '{"category":"forum"}'
    search_body = (
        "<html><body><h2><a href=\"https://forum.example.hu/threads/"
        "kivitelezo-ajanlas.12345/\">Tudtok megbízható kivitelezőt? "
        "Építkezés fórum</a></h2></body></html>"
    ).encode()
    post_body = (
        '<html><time datetime="2026-09-05T10:15:00+00:00"></time>'
        '<script>{"status":"published","taskResponsesCount":0}</script>'
        "<body>Tudtok megbízható kivitelezőt?</body></html>"
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        body = post_body if request.url.host == "forum.example.hu" else search_body
        return httpx.Response(200, content=body, headers={"content-type": "text/html"})

    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(catalog.httpx, "Client", client_factory)
    monkeypatch.setattr(
        catalog.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (catalog.socket.AF_INET, catalog.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    result = catalog._fetch(route)
    assert result["status"] == "succeeded"
    assert result["evidence"]["discovery_mode"] == "search_engine_forum_discovery"
    assert len(result["analysis_links"]) == 1
    assert "published_at_source=source_page" in result["analysis_links"][0]["label"]
    assert "answer_count_raw=0 válasz" in result["analysis_links"][0]["label"]


def test_fetch_analyzes_content_after_old_200k_cutoff(monkeypatch) -> None:
    tail = '<a href="/szakivalaszol/tetofelujitas">Hogyan újítsam fel a tetőt?</a>'
    body = (
        "<html><title>Kérdések</title><body>"
        + ("x" * 210_000)
        + tail
        + "</body></html>"
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/html"})

    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(
        catalog.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (catalog.socket.AF_INET, catalog.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
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
