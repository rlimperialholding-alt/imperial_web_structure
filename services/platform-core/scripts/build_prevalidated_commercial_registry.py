from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BRAND_ALIASES = {
    "imperial": "imperial",
    "bautica": "bautica",
    "prefab": "prefab",
    "danish-fabrik": "danish-fabrik",
    "baufreund": "baufreund",
    "casa-moderna": "casa-moderna",
    "timberhaus": "timberhaus",
}

DRIVE_PRICE_SOURCES = [
    {
        "registry_id": "drive-web-prices-2026-07",
        "drive_file_id": "1pFiXUVRIOqkDf40pgM5jUgNX2gUHpxZ4",
        "file_glob": "*oldalakhoz*weboldal_2026-07.xlsx",
        "source_version": "Kalkuláció_oldalakhoz_frissített_minden_weboldal_2026-07",
        "brands": ["imperial", "bautica", "prefab", "danish-fabrik", "baufreund"],
        "publication_scope": "calculator_output_only",
    },
    {
        "registry_id": "drive-imperial-100m2-price-model-2026-07",
        "drive_file_id": "1jlkCJLRbSr4cP0TbUEFCVnd1yh9adMB-",
        "file_glob": "Imperial_100m2_Technologia_Keszultseg_Armodell_2026_07.xlsx",
        "source_version": "Imperial_100m2_Technologia_Keszultseg_Armodell_2026_07",
        "brands": ["imperial"],
        "publication_scope": "calculator_output_only",
    },
]


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_unique(base: Path, pattern: str) -> Path:
    matches = sorted(base.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one file for {pattern!r}; found {len(matches)}.")
    return matches[0]


def build_registry(audit_path: Path, calculation_dir: Path) -> dict[str, Any]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    brands: dict[str, Any] = {}
    for brand_audit in audit:
        brand_id = BRAND_ALIASES[str(brand_audit["brand"])]
        fragments: dict[str, dict[str, Any]] = {}
        pages: dict[str, dict[str, Any]] = {}
        for page in brand_audit["pages"]:
            if page.get("status") != 200:
                continue
            url = str(page["url"])
            category_map: dict[str, list[str]] = page.get("matches", {})
            page_hash_material: list[str] = []
            for category, values in category_map.items():
                for value in values:
                    normalized = normalize(str(value))
                    if not normalized:
                        continue
                    fragment_sha256 = sha256_text(normalized)
                    entry = fragments.setdefault(
                        fragment_sha256,
                        {
                            "fragment_sha256": fragment_sha256,
                            "source_url": url,
                            "text": str(value),
                            "categories": [],
                        },
                    )
                    if category not in entry["categories"]:
                        entry["categories"].append(category)
                    page_hash_material.append(fragment_sha256)
            pages[url] = {
                "source_url": url,
                "status": 200,
                "claim_snapshot_sha256": sha256_text("|".join(sorted(page_hash_material))),
            }

        typehouse_assets = []
        for asset in brand_audit.get("typehouse_assets", []):
            source_page = str(asset["source_page"])
            asset_url = str(asset["url"])
            reference_sha256 = sha256_text(
                f"{brand_id}|{source_page}|{asset_url}|{normalize(str(asset.get('alt', '')))}"
            )
            typehouse_assets.append(
                {
                    "reference_sha256": reference_sha256,
                    "source_page": source_page,
                    "asset_url": asset_url,
                    "alt": str(asset.get("alt", "")),
                    "allowed_uses": [
                        "automated_marketing",
                        "social",
                        "web",
                        "email",
                        "advertising",
                    ],
                }
            )
        brands[brand_id] = {
            "root_url": brand_audit["root"],
            "pages_scanned": brand_audit["pages_scanned"],
            "pages": sorted(pages.values(), key=lambda item: item["source_url"]),
            "fragments": sorted(
                fragments.values(), key=lambda item: (item["source_url"], item["fragment_sha256"])
            ),
            "typehouse_assets": sorted(
                typehouse_assets, key=lambda item: (item["source_page"], item["asset_url"])
            ),
        }

    price_sources = []
    for source in DRIVE_PRICE_SOURCES:
        path = resolve_unique(calculation_dir, source["file_glob"])
        price_sources.append(
            source
            | {
                "local_file_name": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )

    captured_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "schema_version": 1,
        "registry_version": f"commercial-source-snapshot-{captured_at[:10]}",
        "captured_at": captured_at,
        "policy": {
            "website_snapshot_categories": [
                "commercial",
                "price",
                "technical",
                "legal",
                "typehouse",
            ],
            "website_match_mode": "normalized_source_fragment",
            "price_match_mode": "exact_calculator_output",
            "typehouse_match_mode": "observed_source_url",
            "legal_reuse_scope": "marketing_communication_only",
            "r6_r7_human_approval_required": True,
        },
        "brands": brands,
        "price_sources": price_sources,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("calculation_dir", type=Path)
    args = parser.parse_args()
    registry = build_registry(args.audit_json, args.calculation_dir)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output_json),
                "brands": len(registry["brands"]),
                "fragments": sum(len(brand["fragments"]) for brand in registry["brands"].values()),
                "typehouse_assets": sum(
                    len(brand["typehouse_assets"]) for brand in registry["brands"].values()
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
