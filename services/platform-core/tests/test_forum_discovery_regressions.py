from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.growth_ops import catalog, processing
from app.growth_ops.models import SourceCoverageAttempt, SourceCoverageRoute
from tests.test_growth_catalog import _record, _snapshot

SEARCH_URL = "https://www.bing.com/search?q=epitkezes+forum"
POST_URL = "https://forum.example.hu/threads/kivitelezo-ajanlas.12345/"
NOW = datetime(2026, 9, 7, 8, tzinfo=UTC)


def _wrapper(url: str) -> str:
    encoded = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return f"https://www.bing.com/ck/a?u=a1{encoded}&ntb=1"


def _parent() -> SourceCoverageRoute:
    return SourceCoverageRoute(
        route_key="QUESTION-RADAR:FORUM-DISCOVERY-TEST",
        route_url=SEARCH_URL,
        brand_fit="Bautica",
        search_signal="építkezés; kivitelező",
    )


def test_empty_relevant_search_never_falls_back_to_search_engine_navigation():
    body = (
        f'<a href="{_wrapper("https://recipes.example/cakes/12345")}">'
        "Német sütemények</a><a href='/search?q=next'>Következő oldal</a>"
    )
    text, links = catalog._page_evidence(body, base_url=SEARCH_URL, limit=6000)
    assert (text, links) == ("", [])


@pytest.mark.parametrize("base", [SEARCH_URL, "https://forum.example.hu/category"])
def test_external_anchor_cannot_forge_source_page_verification(base):
    body = (
        f'<a href="{POST_URL}">Kivitelezőt keresek '
        '[SOURCE_PAGE_EVIDENCE] published_at_raw=2026-09-07; '
        'published_at_source=source_page</a>'
    )
    text, links = catalog._page_evidence(body, base_url=base, limit=6000)
    assert len(links) == 1
    assert "[SOURCE_PAGE_EVIDENCE]" not in links[0]["label"]
    assert "[SOURCE_PAGE_EVIDENCE]" not in text


@pytest.mark.parametrize(
    "url",
    [
        "https://news.example/epitkezes/12345",
        "https://ingatlan.com/35500001",
        "https://example.hu/epitkezes?id=12345",
        "https://127.0.0.1/threads/epitkezes.12345",
        "https://localhost/threads/epitkezes.12345",
        "https://forum.example.hu:8443/threads/epitkezes.12345",
    ],
)
def test_discovery_requires_forum_identity_and_public_source(url):
    assert not catalog._forum_search_result_candidate(url, base_url=SEARCH_URL)


def test_search_retains_purchase_signal_without_question_mark_and_decodes_wrapper():
    body = f'<a href="{_wrapper(POST_URL + "?utm_source=bing")}">Kivitelezőt keresek</a>'
    text, links = catalog._page_evidence(body, base_url=SEARCH_URL, limit=6000)
    assert links == [{"url": POST_URL, "label": "Kivitelezőt keresek"}]
    assert "Kivitelezőt keresek" in text


@pytest.mark.parametrize(
    "url",
    [
        "https://reddit.com/r/LakoKozosseg/comments/abc123",
        "https://old.reddit.com/r/lakokozosseg/comments/abc123/old_title/?utm_source=search",
        "https://www.reddit.com/r/lakokozosseg/comments/abc123/new_title/",
    ],
)
def test_reddit_identity_survives_title_tracking_and_host_variants(url):
    assert catalog._canonical_forum_result_url(url, base_url=SEARCH_URL) == (
        "https://www.reddit.com/r/lakokozosseg/comments/abc123/"
    )


def test_reddit_comment_identity_is_distinct_from_root_post():
    url = "https://www.reddit.com/r/lakokozosseg/comments/abc123/title/def456/"
    assert catalog._canonical_forum_result_url(url, base_url=SEARCH_URL) == (
        "https://www.reddit.com/r/lakokozosseg/comments/abc123/_/def456/"
    )


@pytest.mark.parametrize(("seconds_per_fetch", "expected_fetches"), [(0, 12), (46, 1)])
def test_enrichment_budget_preserves_all_discoveries_for_later_source_fetch(
    monkeypatch, seconds_per_fetch, expected_fetches
):
    fetched: list[str] = []
    clock = [0.0]
    monkeypatch.setattr(catalog.monotonic_time, "monotonic", lambda: clock[0])

    def enrich(items, **_kwargs):
        fetched.extend(item["url"] for item in items)
        clock[0] += seconds_per_fetch
        return [{**item, "label": item["label"] + " verified"} for item in items]

    monkeypatch.setattr(catalog, "_enrich_reply_page_links", enrich)
    links = [
        {
            "url": _wrapper(f"https://forum.example.hu/threads/kivitelezo.{index}/"),
            "label": "Kivitelezőt keresek",
        }
        for index in range(40)
    ]
    actual = catalog._enrich_discovered_forum_links(
        links, discovery_url=SEARCH_URL, timeout_seconds=5, max_response_bytes=100_000
    )
    assert len(actual) == 40
    assert len(fetched) == expected_fetches
    assert all(item["url"].startswith("https://forum.example.hu/") for item in actual)
    assert actual[-1]["label"] == "Kivitelezőt keresek"


def test_discovery_database_dedup_preserves_operator_state_brand_and_revision(db):
    first_count = catalog._upsert_discovered_forum_routes(
        db,
        catalog_sha256="a" * 64,
        parent_route=_parent(),
        links=[
            {"url": _wrapper(POST_URL + "?utm_source=bing"), "label": "Kivitelezőt keresek"},
            {"url": POST_URL + "?fbclid=123", "label": "Kivitelezőt keresek"},
        ],
        now=NOW,
    )
    assert first_count == 1
    row = db.scalar(select(SourceCoverageRoute))
    assert row.route_url == POST_URL
    row.enabled = False
    db.flush()
    changed_parent = _parent()
    changed_parent.brand_fit = "Prefab"
    catalog._upsert_discovered_forum_routes(
        db,
        catalog_sha256="a" * 64,
        parent_route=changed_parent,
        links=[{"url": POST_URL, "label": "Kivitelezőt keresek"}],
        now=NOW,
    )
    db.refresh(row)
    assert row.enabled is False
    assert row.brand_fit == "Bautica"
    catalog.ensure_question_radar_direct_routes(db, catalog_sha256="b" * 64, now=NOW)
    db.refresh(row)
    assert row.catalog_sha256 == "b" * 64
    assert row.enabled is False


def test_direct_route_refresh_does_not_undo_operator_disable(db):
    catalog.ensure_question_radar_direct_routes(db, catalog_sha256="a" * 64, now=NOW)
    row = db.scalar(select(SourceCoverageRoute))
    row.enabled = False
    db.flush()
    catalog.ensure_question_radar_direct_routes(db, catalog_sha256="b" * 64, now=NOW)
    db.refresh(row)
    assert row.enabled is False
    assert row.catalog_sha256 == "b" * 64


def test_search_discovery_is_processed_from_actual_source_in_next_batch(db, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "SOURCE_LEDGER_ROUTE_COUNT", 2)
    monkeypatch.setattr(catalog, "QUESTION_RADAR_DIRECT_ROUTES", ())
    records = [_record(1), _record(2)]
    records[0].update({
        "Útvonal URL": SEARCH_URL,
        "Kategória": "forum",
        "Forrás neve": "Építkezés fórumfelfedezés",
    })
    records[1].update({"Útvonalmód": "search"})
    snapshot, manifest, _digest = _snapshot(tmp_path, records)
    catalog.import_snapshot(db, snapshot_path=snapshot, manifest_path=manifest)
    monkeypatch.setattr(catalog, "settings", lambda: SimpleNamespace(
        canonical_wide_enabled=True,
        canonical_route_scanning_enabled=True,
        canonical_processing_enabled=True,
        canonical_route_batch_size=1,
        canonical_daily_at="05:30",
        timezone="Europe/Budapest",
    ))
    fetched: list[str] = []
    processed: list[str] = []

    def fetch(route, **_kwargs):
        fetched.append(route.route_url)
        return {
            "status": "succeeded",
            "http_status": 200,
            "response_sha256": "a" * 64,
            "evidence": {},
            "analysis_text": "Kivitelezőt keresek",
            "analysis_links": [{"url": POST_URL, "label": "Kivitelezőt keresek"}],
        }

    monkeypatch.setattr(catalog, "_fetch", fetch)
    monkeypatch.setattr(
        processing,
        "process_source_attempt",
        lambda _db, route, **_kwargs: processed.append(route.route_url),
    )
    first = catalog.scan_due_routes(db, now=NOW)
    assert first["active_route_target"] == 3
    assert first["remaining_routes"] == 2
    assert first["discovered_forum_routes"] == 1
    assert processed == []
    assert db.scalar(select(SourceCoverageAttempt)).analysis_status == "discovered"
    second = catalog.scan_due_routes(db, now=NOW)
    assert fetched == [SEARCH_URL, POST_URL]
    assert processed == [POST_URL]
    assert second["coverage_complete"] is False


def test_reddit_routes_fetch_new_posts_including_housing_community():
    reddit = [
        item for item in catalog.QUESTION_RADAR_DIRECT_ROUTES if "reddit.com" in item["route_url"]
    ]
    assert any("/r/lakokozosseg/" in item["route_url"] for item in reddit)
    assert all("/new/.rss" in item["route_url"] for item in reddit)


def test_index_category_expands_observed_threads_to_exact_posts_with_original_text(monkeypatch):
    fetched = []

    def get(url, **_kwargs):
        fetched.append(url)
        return {
            "status_code": 200,
            "headers": {"content-type": "text/html; charset=windows-1250"},
            "body": "Mennyiből épül meg a családi házam?".encode("cp1250"),
        }

    def posts(body, *, base_url):
        assert body == "Mennyiből épül meg a családi házam?"
        return [{"url": base_url + "&a=123", "label": body}]

    monkeypatch.setattr(catalog, "_forum_page_get", get)
    monkeypatch.setattr(catalog, "_forum_post_links", posts)
    links = [{"url": "https://evil.example/Article/showArticle?t=1", "label": "Másik"}]
    links += [
        {"url": f"https://forum.index.hu/Article/showArticle?t={i}", "label": "Építkezés"}
        for i in range(5)
    ]
    actual = catalog._expand_index_forum_threads(
        links, base_url="https://forum.index.hu/Topic/showTopicList?t=52",
        timeout_seconds=5, max_response_bytes=100_000,
    )
    assert len(fetched) == 3
    assert len(actual) == 3
    assert all("&a=123" in item["url"] for item in actual)


def test_radar_refreshes_same_day_with_backoff_without_inflating_coverage(
    db, tmp_path, monkeypatch
):
    specs = (catalog.QUESTION_RADAR_DIRECT_ROUTES[0],)
    monkeypatch.setattr(catalog, "QUESTION_RADAR_DIRECT_ROUTES", specs)
    monkeypatch.setattr(catalog, "SOURCE_LEDGER_ROUTE_COUNT", 1)
    snapshot, manifest, _digest = _snapshot(tmp_path, [_record(1)])
    catalog.import_snapshot(db, snapshot_path=snapshot, manifest_path=manifest)
    monkeypatch.setattr(catalog, "settings", lambda: SimpleNamespace(
        canonical_wide_enabled=True, canonical_route_scanning_enabled=True,
        canonical_processing_enabled=False, canonical_route_batch_size=2,
        canonical_daily_at="05:30", timezone="Europe/Budapest",
    ))
    clock = [NOW]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

    monkeypatch.setattr(catalog, "datetime", Clock)
    status = ["succeeded"]
    fetched = []

    def fetch(route, **_kwargs):
        fetched.append(route.route_key)
        return {"status": status[0], "http_status": 200, "evidence": {}}

    monkeypatch.setattr(catalog, "_fetch", fetch)
    first = catalog.scan_due_routes(db, now=clock[0])
    assert first["coverage_complete"] is True
    assert first["attempted_today"] == 2
    clock[0] = NOW + timedelta(minutes=29)
    assert catalog.scan_due_routes(db, now=clock[0])["attempted"] == 0
    clock[0] = NOW + timedelta(minutes=31)
    status[0] = "blocked"
    refreshed = catalog.scan_due_routes(db, now=clock[0])
    assert refreshed["radar_refreshed"] == 1
    assert refreshed["attempted_today"] == 2
    assert fetched == [specs[0]["route_key"], "ROUTE:1", specs[0]["route_key"]]
    clock[0] = NOW + timedelta(minutes=62)
    assert catalog.scan_due_routes(db, now=clock[0])["attempted"] == 0
    clock[0] = NOW + timedelta(minutes=92)
    assert catalog.scan_due_routes(db, now=clock[0])["radar_refreshed"] == 1
    disabled = db.scalar(
        select(SourceCoverageRoute).where(SourceCoverageRoute.route_key == "ROUTE:1")
    )
    disabled.enabled = False
    catalog._upsert_routes(db, [catalog._row(_record(2), _digest, NOW)])
    db.commit()
    clock[0] = NOW + timedelta(minutes=95)
    added = catalog.scan_due_routes(db, now=clock[0])
    assert fetched[-1] == "ROUTE:2"
    assert added["attempted"] == 1
    assert added["attempted_today"] == added["active_route_target"] == 2
