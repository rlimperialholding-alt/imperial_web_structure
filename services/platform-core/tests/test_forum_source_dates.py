from datetime import UTC, datetime

import pytest

from app.growth_ops import catalog, processing

POST = "https://www.gyakorikerdesek.hu/otthon__epitkezes__13249178-tervezot-keresek"
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


def test_gyakori_original_date_keeps_year_and_ignores_sidebar():
    body = """<aside>2026. szept. 7. 10:00</aside><div class="kerdes">
    <h1>Tervezőt keresek</h1><div title="A kérdés kiírásának időpontja">
    2023. júl. 23. 09:43</div></div><div class="sajnosmeg">
    Sajnos még nem érkezett válasz a kérdésre.</div>"""
    metadata = catalog._reply_page_metadata(body, source_url=POST)
    assert metadata["published_at_raw"] == "2023. júl. 23. 09:43"
    assert metadata["existing_answer_count"] == "0"
    stamp = processing._parse_observed_date(metadata["published_at_raw"], observed_at=NOW)
    assert stamp == datetime(2023, 7, 23, 7, 43, tzinfo=UTC)


def test_unscoped_sidebar_date_is_not_question_date():
    body = '<div class="kerdes"><h1>Kivitelezőt keresek</h1></div><aside>júl. 23.</aside>'
    assert catalog._reply_page_metadata(body, source_url=POST) is None
    body = '<time datetime="2026-09-07T00:00:00Z"></time><h1>Kivitelezőt keresek</h1>'
    assert (
        catalog._reply_page_metadata(
            body, source_url="https://forum.example.hu/threads/building-123/"
        )
        is None
    )


def test_atom_updated_is_not_original_and_author_footer_is_removed():
    body = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <updated>2026-09-07T12:00:00Z</updated><published>2023-01-02T01:00:00Z</published>
    <title>Mennyibe kerül a felújítás?</title>
    <link href="https://www.reddit.com/r/lakokozosseg/comments/abc123/title/"/>
    <content type="html">Költségeket keresek. submitted by /u/person</content>
    </entry></feed>"""
    text, links = catalog._page_evidence(
        body, base_url="https://www.reddit.com/r/lakokozosseg/new/.rss", limit=5000
    )
    assert len(links) == 1
    assert "2023-01-02" in text
    assert "2026-09-07" not in text
    assert "/u/person" not in text
    assert "active_status=active" not in text


def test_updated_only_prefixed_feed_retains_text_without_inventing_date():
    body = """<a:feed xmlns:a="http://www.w3.org/2005/Atom"><a:entry>
    <a:updated>2026-09-07T12:00:00Z</a:updated><a:title>Mennyibe kerül a felújítás?</a:title>
    <a:link href="https://www.reddit.com/r/lakokozosseg/comments/abc123/title/"/>
    </a:entry></a:feed>"""
    _, links = catalog._page_evidence(
        body, base_url="https://www.reddit.com/r/lakokozosseg/new/.rss", limit=5000
    )
    assert len(links) == 1
    assert "published_at_raw" not in links[0]["label"]


def test_feed_cannot_attest_other_sites_publication_date():
    body = """<rss><channel><item><title>Házat építek?</title>
    <link>https://forum.other.hu/threads/building-123/</link>
    <pubDate>Sun, 06 Sep 2026 10:15:00 GMT</pubDate></item></channel></rss>"""
    assert catalog._page_evidence(
        body, base_url="https://www.reddit.com/r/lakokozosseg/new/.rss", limit=5000
    ) == ("", [])


def test_index_thread_is_not_post_and_exact_view_has_bound_date():
    thread = "https://forum.index.hu/Article/showArticle?t=9004917"
    post = "https://forum.index.hu/Article/viewArticle?a=172270043&t=9004917"
    assert not catalog._reply_page_candidate(thread, base_url=thread)
    assert not processing._specific_reply_permalink(thread)
    assert catalog._reply_page_candidate(post, base_url=thread)
    assert processing._specific_reply_permalink(post)
    body = """<table class="art"><tr><td><a name="172270043"></a>
    <a rel="bookmark" title="2026.09.06 11:18:01">tegnap</a></td></tr>
    <tr class="art_b"><td>10 vagy 15 cm hőszigetelést érdemes választani?</td></tr></table>"""
    assert catalog._reply_page_metadata(body, source_url=post)["published_at_raw"] == (
        "2026.09.06 11:18:01"
    )
    assert catalog._forum_post_links(body, base_url=post)[0]["url"] == post


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026.09.06 11:18:01", datetime(2026, 9, 6, 9, 18, 1, tzinfo=UTC)),
        ("tegnap 23:07:59", datetime(2026, 9, 6, 21, 7, 59, tzinfo=UTC)),
        ("2023. júl. 23. 09:43", datetime(2023, 7, 23, 7, 43, tzinfo=UTC)),
        ("febr. 31.", None),
        ("2026-09-06T09:45:34Z", datetime(2026, 9, 6, 9, 45, 34, tzinfo=UTC)),
        ("szept. 4., 15:56:47", datetime(2026, 9, 4, 13, 56, 47, tzinfo=UTC)),
    ],
)
def test_source_date_precision(raw, expected):
    assert processing._parse_observed_date(raw, observed_at=NOW) == expected


@pytest.mark.parametrize(
    ("published", "text", "queue"),
    [
        ("2026-09-07T08:00:00+02:00", "Kivitelezőt keresek, megvan a telkem.", "HOT"),
        ("2026-09-05T08:00:00+02:00", "Kivitelezőt keresek családi házamhoz.", "WARM"),
        ("2026-08-25T08:00:00+02:00", "Kivitelezőt keresek családi házamhoz.", "CONTENT_SIGNAL"),
        ("2023-08-25T08:00:00+02:00", "Kivitelezőt keresek családi házamhoz.", "RESEARCH_ONLY"),
    ],
)
def test_revenue_queues_keep_answered_posts_and_unknown_status(published, text, queue):
    item = {
        "source_url": "https://forum.example.hu/threads/building-123/",
        "published_at_raw": published,
        "published_at_source": "source_page",
        "question": text,
        "existing_answer_count": 4,
        "answer_count_raw": "4 válasz",
    }
    result = processing._question_freshness(
        item,
        evidence_text=published + " 4 válasz",
        observed_at=NOW,
        require_source_date_proof=True,
    )
    assert result["freshness_decision"] == queue
    assert result["existing_answer_count"] == 4
    assert result["active_status"] == "unknown"
    assert "already_answered" not in result["reasons"]
    assert result["revenue_decision"]["contact_allowed"] is False


def test_generic_related_jsonld_item_is_not_post_date():
    body = """<script type="application/ld+json">{"@type":"Question",
    "url":"https://forum.example.hu/threads/other/",
    "datePublished":"2026-09-07T00:00:00Z"}</script>"""
    assert (
        catalog._reply_page_metadata(
            body, source_url="https://forum.example.hu/threads/building-123/"
        )
        is None
    )


def test_native_identity_ignores_reddit_title_and_index_thread_query_order():
    assert processing._radar_identity_hash(
        "https://www.reddit.com/r/lakokozosseg/comments/abc123/original-title/"
    ) == processing._radar_identity_hash(
        "https://reddit.com/r/lakokozosseg/comments/abc123/edited-title/"
    )
    assert processing._radar_identity_hash(
        "https://forum.index.hu/Article/viewArticle?a=172270043&t=9004917"
    ) == processing._radar_identity_hash(
        "https://forum.index.hu/Article/showArticle?t=9004917&a=172270043"
    )
    assert processing._radar_identity_hash(
        "https://prohardver.hu/tema/first-topic/hsz_15-15.html"
    ) != processing._radar_identity_hash("https://prohardver.hu/tema/second-topic/hsz_15-15.html")


def test_reply_enrichment_has_total_deadline_and_retains_unread_links(monkeypatch):
    tick = [0.0]
    calls = []
    monkeypatch.setattr(catalog.monotonic_time, "monotonic", lambda: tick[0])

    def fetch(url, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        tick[0] += kwargs["timeout_seconds"]
        return {"status_code": 503}

    monkeypatch.setattr(catalog, "_forum_page_get", fetch)
    links = [
        {"url": f"https://forum.example.hu/threads/item-{i}/", "label": "Építkezés"}
        for i in range(20)
    ]
    result = catalog._enrich_reply_page_links(
        links, base_url="https://forum.example.hu", timeout_seconds=30, max_response_bytes=1000
    )
    assert result == links
    assert len(calls) == 6
    assert sum(calls) == 45
    assert max(calls) <= 8


def test_reddit_reply_cannot_replace_original_posts_publication_date():
    post = "https://www.reddit.com/r/lakokozosseg/comments/abc123/title/"
    reply = post + "reply456/"
    assert not catalog._same_forum_post(post, reply)
    assert not catalog._same_forum_post(reply, post)
    assert catalog._same_forum_post(post, post.replace("title", "edited-title"))
