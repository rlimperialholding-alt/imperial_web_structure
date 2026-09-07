from __future__ import annotations

import time

import pytest

from app.growth_ops.forum_http import forum_public_get


def test_index_anonymous_handshake_preserves_host_only_cookies():
    url = "https://forum.index.hu/Article/viewArticle?a=123&t=456"
    handshake = (
        "https://daemon.indapass.hu/http/session_request?partner_id=forum"
        "&redirect_to=https%3A%2F%2Fforum.index.hu%2FArticle%2FviewArticle%3Fa%3D123%26t%3D456"
    )
    visited = []

    def get(current, **kwargs):
        visited.append((current, kwargs))
        hop = len(visited)
        if hop == 1:
            return {
                "status_code": 302, "headers": {"location": handshake}, "body": b"",
                "set_cookie_headers": ["anonymous=abc; Path=/; Secure; Domain=.index.hu"],
            }
        if hop == 2:
            assert kwargs["request_headers"] == {}
            return {
                "status_code": 302, "headers": {"location": url + "&token=temporary"},
                "body": b"", "set_cookie_headers": ["provider=xyz; Path=/; Secure"],
            }
        assert kwargs["request_headers"] == {"Cookie": "anonymous=abc"}
        return {"status_code": 200, "headers": {}, "body": b"original post"}

    result = forum_public_get(
        url, max_response_bytes=1000,
        deadline_monotonic=time.monotonic() + 10, pinned_get=get,
    )
    assert result["status_code"] == 200
    assert result["body"] == b"original post"
    assert result["redirect_count"] == 2
    assert len(visited) == 3
    assert len({call[1]["deadline_monotonic"] for call in visited}) == 1


@pytest.mark.parametrize("target", [
    "http://forum.index.hu/Article/viewArticle?a=123",
    "https://127.0.0.1/private",
    "https://example.com/login",
    "https://daemon.indapass.hu/login",
    "https://daemon.indapass.hu/http/session_request?partner_id=other&redirect_to=https://forum.index.hu/",
    "https://daemon.indapass.hu/http/session_request?partner_id=forum&redirect_to=https://example.com/",
])
def test_redirects_cannot_leave_exact_anonymous_handshake(target):
    def get(current, **kwargs):
        return {"status_code": 302, "headers": {"location": target}, "body": b""}

    with pytest.raises(ValueError):
        forum_public_get(
            "https://forum.index.hu/Article/viewArticle?a=123", max_response_bytes=1000,
            deadline_monotonic=time.monotonic() + 10, pinned_get=get,
        )


def test_redirect_body_budget_and_total_hops_are_bounded():
    calls = []

    def get(current, **kwargs):
        calls.append(kwargs)
        return {
            "status_code": 302, "headers": {"location": "/next"}, "body": b"12345",
        }

    with pytest.raises(ValueError, match="forum_response_too_large"):
        forum_public_get(
            "https://forum.index.hu/start", max_response_bytes=9,
            deadline_monotonic=time.monotonic() + 10, pinned_get=get,
        )
    assert [call["max_response_bytes"] for call in calls] == [9, 4]
    calls.clear()
    with pytest.raises(ValueError, match="forum_redirect_limit"):
        forum_public_get(
            "https://forum.index.hu/start", max_response_bytes=1000,
            deadline_monotonic=time.monotonic() + 10, pinned_get=get,
        )
    assert len(calls) == 5


def test_expired_deadline_never_fetches():
    def get(current, **kwargs):
        pytest.fail("expired request must not fetch")

    with pytest.raises(ValueError, match="forum_fetch_timeout"):
        forum_public_get(
            "https://forum.index.hu/start", max_response_bytes=1000,
            deadline_monotonic=time.monotonic() - 1, pinned_get=get,
        )


def test_prohardver_anonymous_handshake_returns_to_original_public_forum():
    url = "https://prohardver.hu/tema/felujitas/hsz_12345-12345.html"
    redirects = [
        url + "?_tc=1",
        "https://auth.rios.hu/hozzaferes/azonosit.php?redir_host=prohardver.hu"
        "&redir_uri=%2Ftema%2Ffelujitas%2Fhsz_12345-12345.html",
        "https://prohardver.hu/muvelet/hozzaferes/azonosit.php?anonymous=yes",
        url,
    ]
    visited = []

    def get(current, **kwargs):
        visited.append(current)
        index = len(visited) - 1
        if index < len(redirects):
            return {
                "status_code": 302, "headers": {"location": redirects[index]},
                "body": b"", "set_cookie_headers": ["anonymous_cookie=example; Path=/"],
            }
        return {"status_code": 200, "headers": {}, "body": b"post"}

    result = forum_public_get(
        url, max_response_bytes=1000,
        deadline_monotonic=time.monotonic() + 10, pinned_get=get,
    )
    assert result["status_code"] == 200
    assert result["final_url"] == url
    assert result["redirect_count"] == 4


@pytest.mark.parametrize("target", [
    "https://auth.rios.hu/login",
    "https://auth.rios.hu/hozzaferes/azonosit.php?redir_host=other.hu&redir_uri=/tema/example",
])
def test_prohardver_handshake_does_not_allow_other_login_or_return_hosts(target):
    def get(current, **kwargs):
        return {"status_code": 302, "headers": {"location": target}, "body": b""}

    with pytest.raises(ValueError, match="forum_redirect_outside_public_surface"):
        forum_public_get(
            "https://prohardver.hu/tema/test/hsz_123-123.html", max_response_bytes=1000,
            deadline_monotonic=time.monotonic() + 10, pinned_get=get,
        )
