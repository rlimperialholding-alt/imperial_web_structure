from __future__ import annotations

import json

import pytest

from app.copy_gate.brand_assets import (
    BrandAssetError,
    load_brand_asset_manifest,
    resolve_brand_asset,
)

EXPECTED_VARIANTS = {
    "imperial": {"primary", "monochrome_mark"},
    "danish-fabrik": {"primary", "site_icon"},
    "bautica": {"primary", "inverse_orange", "monochrome_mark"},
    "prefab": {"primary", "site_icon"},
    "casa-moderna": {"primary"},
    "baufreund": {"primary", "mascot", "site_icon"},
    "timberhaus": {"primary", "site_icon"},
}


def test_registry_contains_every_requested_brand_and_variant():
    manifest = load_brand_asset_manifest()

    assert set(manifest["brands"]) == set(EXPECTED_VARIANTS)
    for brand_id, variants in EXPECTED_VARIANTS.items():
        assert set(manifest["brands"][brand_id]["assets"]) == variants


def test_every_observed_asset_is_hash_verified_and_available_for_test_creatives():
    for brand_id, variants in EXPECTED_VARIANTS.items():
        for variant in variants:
            asset = resolve_brand_asset(brand_id, variant)

            assert asset.path.is_file(), f"{brand_id}/{variant}"
            assert asset.public_url.startswith(f"/static/brand-assets/{brand_id}/")
            assert asset.source_url.startswith("https://")
            assert asset.approval_status == "observed_pending_owner_approval"


def test_every_observed_primary_logo_is_fail_closed_for_external_publication():
    for brand_id in EXPECTED_VARIANTS:
        with pytest.raises(BrandAssetError, match="publikációs jóváhagyással"):
            resolve_brand_asset(brand_id, "primary", for_publication=True)


def test_every_registry_asset_is_served_with_hash_identical_bytes(client):
    for brand_id, variants in EXPECTED_VARIANTS.items():
        for variant in variants:
            asset = resolve_brand_asset(brand_id, variant)
            response = client.get(asset.public_url)

            assert response.status_code == 200, asset.public_url
            assert response.content == asset.path.read_bytes()


def test_tampered_brand_asset_is_rejected(tmp_path):
    (tmp_path / "logo.svg").write_text("<svg/>", encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "brands": {
            "test": {
                "display_name": "Test",
                "source_page": "https://example.test/",
                "approval_status": "approved",
                "assets": {
                    "primary": {
                        "file": "logo.svg",
                        "media_type": "image/svg+xml",
                        "source_url": "https://example.test/logo.svg",
                        "sha256": "0" * 64,
                    }
                },
            }
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BrandAssetError, match="hash eltérés"):
        resolve_brand_asset("test", "primary", manifest_path=manifest_path)
