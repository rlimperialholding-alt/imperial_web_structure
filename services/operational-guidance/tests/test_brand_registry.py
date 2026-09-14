from __future__ import annotations

import pytest

from app.brand_registry import (
    load_brand_registry,
    registry_status,
    resolve_target_brand,
)
from app.config import Settings
from app.connectors.website_publisher import WebsitePublisher


def settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        brand_registry_file="config/brand-registry.json",
        website_targets_file="config/website-targets.json",
    )


def test_registry_contains_all_current_brands() -> None:
    brands = load_brand_registry(settings())
    keys = {brand["key"] for brand in brands}

    assert len(brands) == 11
    assert keys == {
        "imperial",
        "danishfabrik",
        "bautica",
        "prefab",
        "timberhaus",
        "casamoderna",
        "property360",
        "everydayhomes",
        "familyhomes",
        "budapestimagasepito",
        "redproperty",
    }


def test_each_brand_has_main_target_and_independent_blog() -> None:
    brands = load_brand_registry(settings())
    website_keys = [website["key"] for brand in brands for website in brand["websites"]]
    blog_keys = [
        website["key"]
        for brand in brands
        for website in brand["websites"]
        if website["kind"] == "wordpress_blog"
    ]

    assert all(len(brand["websites"]) >= 2 for brand in brands)
    assert len(website_keys) == len(set(website_keys))
    assert len(blog_keys) == 11
    assert all(key.endswith("-blog") for key in blog_keys)


def test_editorial_authors_are_unique_across_brands() -> None:
    brands = load_brand_registry(settings())
    editorial = [brand["editorial"] for brand in brands]

    for field in ("author_login", "author_display_name", "author_email"):
        values = [item[field].casefold() for item in editorial]
        assert len(values) == len(set(values)) == 11


def test_registry_status_does_not_expose_secrets_or_author_emails() -> None:
    statuses = registry_status(settings())
    assert statuses
    for brand in statuses:
        assert "author_email" not in brand["editorial"]
        assert "author_login" not in brand["editorial"]
        for website in brand["websites"]:
            assert "secret" not in website


def test_target_brand_resolution_prevents_cross_brand_routing() -> None:
    current = settings()
    assert resolve_target_brand(current, "imperial-blog") == "imperial"
    assert resolve_target_brand(current, "redproperty-blog") == "redproperty"
    with pytest.raises(KeyError, match="Unknown publication target"):
        resolve_target_brand(current, "unknown-blog")


def test_disabled_target_cannot_publish() -> None:
    publisher = WebsitePublisher(settings())
    with pytest.raises(RuntimeError, match="disabled"):
        publisher.publish(
            "imperial",
            {
                "event_id": "test",
                "action": "publish",
                "content_id": "content-test",
                "brand_key": "imperial",
                "website_key": "imperial",
                "content": {"brand_key": "imperial"},
            },
        )


def test_one_brand_can_have_multiple_websites_without_code_changes() -> None:
    custom = Settings(
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        brand_registry_json={
            "brands": [
                {
                    "key": "demo",
                    "name": "Demo Brand",
                    "editorial": {
                        "author_login": "demo-author",
                        "author_display_name": "Demo Author",
                        "author_email": "demo@author.invalid",
                    },
                    "websites": [
                        {"key": "demo-hu", "base_url": "https://example.hu"},
                        {
                            "key": "demo-blog",
                            "kind": "wordpress_blog",
                            "base_url": "https://blog.example.hu",
                        },
                    ],
                }
            ]
        },
        website_targets_file="",
    )

    brands = load_brand_registry(custom)
    assert [website["key"] for website in brands[0]["websites"]] == [
        "demo-hu",
        "demo-blog",
    ]
