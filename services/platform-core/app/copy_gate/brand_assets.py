from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BRAND_ASSET_ROOT = Path(__file__).resolve().parents[1] / "static" / "brand-assets"
BRAND_ASSET_MANIFEST = BRAND_ASSET_ROOT / "manifest.json"


class BrandAssetError(ValueError):
    """Raised when a brand asset is unknown, altered, or not approved for its use."""


@dataclass(frozen=True)
class ResolvedBrandAsset:
    brand_id: str
    variant: str
    path: Path
    public_url: str
    media_type: str
    source_url: str
    sha256: str
    approval_status: str


def load_brand_asset_manifest(path: Path = BRAND_ASSET_MANIFEST) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        raise BrandAssetError("Ismeretlen brand-asset manifest verzió.")
    brands = payload.get("brands")
    if not isinstance(brands, dict):
        raise BrandAssetError("A brand-asset manifest brands mezője hiányzik.")
    for brand_id, brand in brands.items():
        if not isinstance(brand, dict) or not brand.get("display_name"):
            raise BrandAssetError(f"Hiányos márkarekord: {brand_id}")
        if not str(brand.get("source_page") or "").startswith("https://"):
            raise BrandAssetError(f"Nem HTTPS márkaforrás: {brand_id}")
        if brand.get("approval_status") not in {
            "observed_pending_owner_approval",
            "approved",
            "rejected",
        }:
            raise BrandAssetError(f"Ismeretlen jóváhagyási állapot: {brand_id}")
        assets = brand.get("assets")
        if not isinstance(assets, dict) or "primary" not in assets:
            raise BrandAssetError(f"Hiányzó primary logó: {brand_id}")
        for variant, asset in assets.items():
            required = {"file", "media_type", "source_url", "sha256"}
            if not isinstance(asset, dict) or required - set(asset):
                raise BrandAssetError(f"Hiányos brand asset: {brand_id}/{variant}")
            if not str(asset["source_url"]).startswith("https://"):
                raise BrandAssetError(f"Nem HTTPS assetforrás: {brand_id}/{variant}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(asset["sha256"])):
                raise BrandAssetError(f"Hibás SHA-256: {brand_id}/{variant}")
    return payload


def resolve_brand_asset(
    brand_id: str,
    variant: str,
    *,
    for_publication: bool = False,
    manifest_path: Path = BRAND_ASSET_MANIFEST,
) -> ResolvedBrandAsset:
    manifest = load_brand_asset_manifest(manifest_path)
    brand = manifest["brands"].get(brand_id)
    if not brand:
        raise BrandAssetError(f"Ismeretlen márka: {brand_id}")
    asset = brand.get("assets", {}).get(variant)
    if not asset:
        raise BrandAssetError(f"Ismeretlen logóváltozat: {brand_id}/{variant}")

    approval_status = str(brand.get("approval_status") or "")
    if for_publication and approval_status != "approved":
        raise BrandAssetError(
            "A webhelyről beolvasott logó nincs márkatulajdonosi publikációs jóváhagyással ellátva."
        )

    asset_root = manifest_path.parent.resolve()
    asset_path = (asset_root / str(asset["file"])).resolve()
    try:
        asset_path.relative_to(asset_root)
    except ValueError as exc:
        raise BrandAssetError("A brand-asset útvonala kilép a registry könyvtárából.") from exc
    if not asset_path.is_file():
        raise BrandAssetError(f"Hiányzó brand asset: {asset_path}")

    actual_hash = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    expected_hash = str(asset.get("sha256") or "").lower()
    if actual_hash != expected_hash:
        raise BrandAssetError(f"Brand-asset hash eltérés: {brand_id}/{variant}")

    relative_path = asset_path.relative_to(BRAND_ASSET_ROOT).as_posix()
    return ResolvedBrandAsset(
        brand_id=brand_id,
        variant=variant,
        path=asset_path,
        public_url=f"/static/brand-assets/{relative_path}",
        media_type=str(asset["media_type"]),
        source_url=str(asset["source_url"]),
        sha256=actual_hash,
        approval_status=approval_status,
    )
