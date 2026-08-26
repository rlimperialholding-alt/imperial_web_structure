from app.growth_ops import images


def package() -> dict:
    return {
        "brand_id": "bautica",
        "title": "Felújítás előtt tisztázandó döntések",
        "body": "A jó előkészítés csökkenti a műszaki és szervezési bizonytalanságot.",
        "facebook_post": "Felújítás előtt érdemes rendszerezni a döntéseket.",
    }


def test_sync_submits_one_hash_bound_job(monkeypatch) -> None:
    monkeypatch.setenv("CANONICAL_IMAGE_FACTORY_ENABLED", "true")
    captured = {}

    def request(method, path, payload=None):
        captured.update({"method": method, "path": path, "payload": payload})
        return {
            "batch_id": "BATCH-1",
            "jobs": [{"job_id": "00000000-0000-0000-0000-000000000001", "content_id": "QCA-1", "status": "QUEUED"}],
        }

    monkeypatch.setattr(images, "_request", request)
    status, state = images.sync_canonical_image(
        package(), content_asset_id="QCA-1", article_slug="felujitas-elott"
    )

    assert status == "pending"
    assert state["batch_id"] == "BATCH-1"
    assert captured["payload"]["items"][0]["content_id"] == "QCA-1"
    assert captured["payload"]["items"][0]["target_aspect_ratio"] == "16:9"
    assert "logó-" in captured["payload"]["items"][0]["source_brief"]


def test_sync_releases_verified_unbranded_assets_after_canary_switch(monkeypatch) -> None:
    monkeypatch.setenv("CANONICAL_IMAGE_FACTORY_ENABLED", "true")
    monkeypatch.setenv("CANONICAL_IMAGE_AUTO_RELEASE_ENABLED", "true")
    initial_status, initial = "pending", {}

    def submit(method, path, payload=None):
        return {
            "batch_id": "BATCH-1",
            "jobs": [{"job_id": "00000000-0000-0000-0000-000000000001", "content_id": "QCA-1", "status": "QUEUED"}],
        }

    monkeypatch.setattr(images, "_request", submit)
    initial_status, initial = images.sync_canonical_image(
        package(), content_asset_id="QCA-1", article_slug="felujitas-elott"
    )
    assert initial_status == "pending"
    bound = package() | {"image_factory": initial}

    def poll(method, path, payload=None):
        return {
            "jobs": [
                {
                    "job_id": initial["job_id"],
                    "status": "COMPLETED",
                    "qa_score": 94,
                    "release_state": "TEST_ONLY_REVIEW_REQUIRED",
                    "derived_assets": {
                        "web_hero": {
                            "sha256": "a" * 64,
                            "dimensions": [1600, 900],
                        }
                    },
                }
            ]
        }

    monkeypatch.setattr(images, "_request", poll)
    status, state = images.sync_canonical_image(
        bound, content_asset_id="QCA-1", article_slug="felujitas-elott"
    )

    assert status == "ready"
    assert state["status"] == "AUTO_RELEASE_APPROVED"
    assert state["web_hero"]["role"] == "web_hero"
    assert state["facebook"] == state["web_hero"]
