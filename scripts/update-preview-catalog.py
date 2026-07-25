#!/usr/bin/env python3
"""Register every standalone preview imported from the repository and Drive."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "sites" / "_portal" / "data"
DRIVE_PAGES = {
    "danish-fabrik": {
        "sourceId": "1VAs7ftaGrf8JcoUGnmLv8J0FslQFfDSW",
        "guideId": "1_mXGnbwMH3jFl0LL6r_ADDSIXV1OomjH4kMDQp4eKK0",
    },
    "casa-moderna": {
        "sourceId": "11We-v4bq7dw_LSktJPxGNsd0oyf3yGD1",
        "guideId": "10JPg2WoVMajzErERN8It-QNm3GDHJ36g6d2DHi_IKBc",
    },
    "everyday-homes": {
        "sourceId": "1VZmftOSSK1ZZs1jePp7ZJKxErvELKKCF",
        "guideId": "19DL0k4Cl-HHHylak9xfc9C0QYDXDJd60_zRu06fCdS4",
    },
    "property-360": {
        "sourceId": "1bVAjyyycFcUl1qyGwU_XWWiti3rI1Hur",
        "guideId": "14B2BEJNvNjUpgMpkBhuRVoEbQ3hn9oTsV5D6Ptc6WGU",
    },
    "baufreund": {
        "sourceId": "11jIKIOsmT6HAfWwm40OnSNoZW1Rztv7_",
        "guideId": "120-i4EHv_OrWXwSMUZad-gUFzXGby84UGfjXus8EyVo",
    },
    "red-property": {
        "sourceId": "1o0sW9QmuVu6Hwl-B4StjRwOZyQkQtl28",
        "guideId": "192fP7Y6r_WT8za8cxv-DR81-pPuasuP2HrNdowNurQk",
    },
    "timberhaus": {
        "sourceId": "1ue19H61K7gNKdynpKovTN7ucsyK2qBBz",
        "guideId": "1Lkf65qqksfbMSeIBszXpYNhKCVe36Qu5cGzEoFcJPus",
    },
}
CONSUMER_DRIVE_PAGES = {
    "imperial": {
        "sourceId": "1FS_rHRKBarfzOWCzMT56e0QSwnoIRbuk",
        "guideId": "1VkZsQzZ2wSXiAAwCNZi71EdVBfkkfRM2MCpuUCAFuio",
    },
    "bautica": {
        "sourceId": "11p3lBYwZvoiWK2kAHNnrJex_aKwQYImE",
        "guideId": "1vnsM34aDMY7EDKlktzVPKEA3YdemgLqUYpEsHnH4y4I",
    },
    "prefab": {
        "sourceId": "1I4B8E3LfK2POc5yGmh9XD_ZO6GFaJZLW",
        "guideId": "19YvNQlOHO0L0Aoy-cWtAEImo2cHST6kaEfxv_Yv6amc",
    },
}
EXPECTED_CATALOG_COUNT = 131
FAMILY_ARCHIVE_ID = "1CPW8qi49qmn9YJfJVXlhuL_w2VFRg-Z8"
FAMILY_ORDER = [
    "tipushazak.html",
    "egyedi-haztervek-megepitese.html",
    "tervezes.html",
    "felujitas-bovites.html",
    "technologiak.html",
    "arak-koltsegek.html",
    "keszultsegi-szintek.html",
    "muszaki-tartalmaink.html",
    "muszaki-garanciak.html",
    "finanszirozas.html",
    "telek-beepithetoseg.html",
    "okosotthon.html",
    "folyamatunk.html",
]


def title_for(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    if not match:
        return path.stem.replace("-", " ").title()
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    return title.split("|", 1)[0].strip()


def source_page_paths(brand: str, output_subdir: str = "") -> list[Path]:
    site_root = ROOT / "sites" / brand
    root = site_root / output_subdir if output_subdir else site_root
    source = site_root / "source" / "website-spec.md"
    expected_titles = [
        line[3:].strip()
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    candidates = [root / "index.html", *sorted((root / "pages").glob("*.html"))]
    by_title = {title_for(path): path for path in candidates}
    missing = [title for title in expected_titles if title not in by_title]
    if missing:
        raise RuntimeError(f"{brand}: missing generated source pages: {missing}")
    return [by_title[title] for title in expected_titles]


def source_page_records(
    brand: str, entry: dict, output_subdir: str = ""
) -> list[dict]:
    site_root = ROOT / "sites" / brand
    records = []
    for path in source_page_paths(brand, output_subdir):
        relative = path.relative_to(site_root).as_posix()
        records.append(
            {
                "title": title_for(path),
                "path": f"/{relative}",
                "kind": "drive-source-page",
                "sourceId": entry["sourceId"],
                "brandGuideId": entry["guideId"],
                "contentStatus": "source-aligned-preview",
            }
        )
    return records


def write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    artifacts_path = DATA / "artifacts.json"
    artifacts = json.loads(artifacts_path.read_text(encoding="utf-8"))
    artifacts["meta"].update(
        {
            "source": "Repository and approved Google Drive web artifacts",
            "importedAt": "2026-07-25",
            "catalogPageCount": EXPECTED_CATALOG_COUNT,
            "runtimeExternalApis": False,
            "notes": (
                "Every completed standalone screen and every H2-defined Drive source page "
                "is registered. Runtime assets are brand-local; non-standalone WordPress "
                "templates remain source evidence rather than misleading previews."
            ),
        }
    )

    for brand, entry in DRIVE_PAGES.items():
        pages = source_page_records(brand, entry)
        pages[0]["path"] = "/"
        artifacts["brands"][brand] = {
            "defaultPath": "/",
            "pages": pages,
        }

    # Six Imperial-branded knowledge screens were incorrectly catalogued and
    # physically packaged under Prefab.  The files are moved to Imperial and
    # their catalog ownership follows the visible brand.
    imperial_knowledge_paths = {
        "/drive/knowledge/muszaki-keszultsegi-szintek.html",
        "/drive/knowledge/talajcsavaros-alapozas.html",
        "/drive/knowledge/szigeteles-vastagsag.html",
        "/drive/knowledge/fodemtukor.html",
        "/drive/knowledge/mernoki-valaszok-konnyuszerkezet.html",
        "/drive/knowledge/hoszivattyu-osszehasonlito.html",
        "/drive/knowledge/szeglemezes-tetoszerkezet.html",
        "/drive/knowledge/felujitas-vagy-uj-epites.html",
        "/drive/knowledge/egyszerusitett-bejelentesi-eljaras.html",
        "/drive/knowledge/isola-muanyag-nyilaszarok.html",
    }
    prefab_pages = []
    for page in artifacts["brands"]["prefab"]["pages"]:
        if page["path"] == "/drive/knowledge/osszes-tudasoldal.html":
            continue
        if page["path"] in imperial_knowledge_paths:
            page["brandCorrection"] = "prefab-package-to-imperial"
            artifacts["brands"]["imperial"]["pages"].append(page)
            continue
        prefab_pages.append(page)
    artifacts["brands"]["prefab"]["pages"] = prefab_pages

    for brand, entry in CONSUMER_DRIVE_PAGES.items():
        artifacts["brands"][brand]["pages"] = [
            page
            for page in artifacts["brands"][brand]["pages"]
            if not (
                page.get("kind") == "drive-source-page"
                and page["path"].startswith("/consumer/")
            )
        ]
        artifacts["brands"][brand]["pages"].extend(
            source_page_records(brand, entry, "consumer")
        )

    family_root = ROOT / "sites" / "family-homes" / "drive"
    family_pages = []
    for filename in FAMILY_ORDER:
        path = family_root / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        family_pages.append(
            {
                "title": title_for(path),
                "path": f"/drive/{filename}",
                "kind": "drive-full-site",
                "sourceId": FAMILY_ARCHIVE_ID,
            }
        )
    artifacts["brands"]["family-homes"] = {
        "defaultPath": "/drive/tipushazak.html",
        "pages": family_pages,
    }

    brand_order = [
        "imperial",
        "danish-fabrik",
        "bautica",
        "prefab",
        "casa-moderna",
        "family-homes",
        "everyday-homes",
        "property-360",
        "budapesti-magasepito-vallalat",
        "baufreund",
        "red-property",
        "timberhaus",
    ]
    artifacts["brands"] = {
        brand: artifacts["brands"][brand] for brand in brand_order
    }
    page_count = sum(
        len(entry["pages"]) for entry in artifacts["brands"].values()
    )
    if page_count != EXPECTED_CATALOG_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_CATALOG_COUNT} catalog pages, found {page_count}"
        )
    write_json(artifacts_path, artifacts)

    brands_path = DATA / "brands.json"
    brands = json.loads(brands_path.read_text(encoding="utf-8"))
    counts = {
        brand: len(entry["pages"]) for brand, entry in artifacts["brands"].items()
    }
    for brand in brands["brands"]:
        count = counts[brand["id"]]
        brand["status"] = "active"
        brand["statusLabel"] = f"{count} tesztelhető oldal"
        brand["pageCount"] = count
    write_json(brands_path, brands)
    print(f"registered {page_count} preview pages")


if __name__ == "__main__":
    main()
