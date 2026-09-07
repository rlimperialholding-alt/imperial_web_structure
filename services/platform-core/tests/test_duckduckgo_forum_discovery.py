from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest
from sqlalchemy import select

from app.growth_ops import catalog
from app.growth_ops.models import SourceCoverageRoute

SEARCH_URL = "https://lite.duckduckgo.com/lite/?q=felujitas+forum"
FORUM_URL = "https://www.hoxa.hu/felujitas-forum"


def _wrapper(url: str) -> str:
    return "//duckduckgo.com/l/?" + urlencode({"uddg": url, "rut": "opaque"})


def test_lite_query_is_discovery_and_existing_non_search_paths_stay_unchanged():
    assert catalog._is_search_route(SEARCH_URL)
    assert not catalog._is_search_route("https://lite.duckduckgo.com/lite/")
    assert not catalog._is_search_route("https://www.bing.com/lite/?q=forum")
    assert not catalog._is_search_route("https://www.hoxa.hu/lite/?q=forum")
    parent = SourceCoverageRoute(
        route_url=SEARCH_URL, category="fórum", route_key="QUESTION-RADAR:DISCOVERY-TEST",
    )
    assert catalog._is_forum_discovery_route(parent)


def test_ddg_relevance_decodes_and_deduplicates_original_forum_without_source_date():
    body = (
        f'<a href="{_wrapper(FORUM_URL + "?utm_source=duckduckgo")}">Felújítás - Hoxa</a>'
        '<td class="result-snippet">Újraindexelve 2026-09-07. Kivitelezőt keresek.</td>'
        f'<a href="{_wrapper(FORUM_URL)}">Felújítás</a>'
        f'<a href="{_wrapper("https://recipes.example/food/12345")}">Sütemény fórum</a>'
        '<a href="/lite/?q=next">Következő</a>'
    )
    text, links = catalog._page_evidence(body, base_url=SEARCH_URL, limit=6000)
    assert links == [{"url": FORUM_URL, "label": "Felújítás - Hoxa"}]
    assert "[SOURCE_PAGE_EVIDENCE]" not in text
    assert "2026-09-07" not in text
    assert "Újraindexelve" not in text


@pytest.mark.parametrize("target", [
    "http://epitkezes.forum.hu/garazs/",
    "https://127.0.0.1/felujitas-forum",
    "https://localhost/felujitas-forum",
    "https://user:password@forum.example/felujitas-forum",
    "https://forum.example:8443/felujitas-forum",
])
def test_ddg_wrapper_cannot_bypass_public_https_source_validation(target):
    assert not catalog._forum_search_result_candidate(_wrapper(target), base_url=SEARCH_URL)


def test_ddg_discovered_new_forum_route_is_persisted_once_with_source_identity(db):
    body = f'<a href="{_wrapper(FORUM_URL)}">Felújítás - Hoxa</a>'
    _text, links = catalog._page_evidence(body, base_url=SEARCH_URL, limit=6000)
    parent = SourceCoverageRoute(
        route_key="QUESTION-RADAR:FORUM-DISCOVERY-RENOVATION",
        route_url=SEARCH_URL, brand_fit="BauFreund,Bautica,Prefab",
        search_signal="felújítás; szakember",
    )
    for _ in range(2):
        catalog._upsert_discovered_forum_routes(
            db, catalog_sha256="a" * 64, parent_route=parent, links=links + links,
            now=datetime(2026, 9, 7, 8, tzinfo=UTC),
        )
        db.commit()
    rows = db.scalars(select(SourceCoverageRoute)).all()
    assert len(rows) == 1
    assert rows[0].route_url == FORUM_URL
    assert rows[0].route_mode == "direct_post"
    assert rows[0].brand_fit == parent.brand_fit
    assert "duckduckgo" not in rows[0].route_url


def test_verified_lite_queries_replace_two_existing_discovery_requests():
    routes = [
        row for row in catalog.QUESTION_RADAR_DIRECT_ROUTES
        if row["route_key"] in {
            "QUESTION-RADAR:FORUM-DISCOVERY-CONSTRUCTION",
            "QUESTION-RADAR:FORUM-DISCOVERY-RENOVATION",
        }
    ]
    assert len(routes) == 2
    assert {row["route_url"] for row in routes} == {
        "https://lite.duckduckgo.com/lite/?q=epitkezes+forum", SEARCH_URL,
    }
