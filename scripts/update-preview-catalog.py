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
        "defaultPath": "/",
        "sourceId": "1VAs7ftaGrf8JcoUGnmLv8J0FslQFfDSW",
        "title": "Danish Fabrik – favázas otthonok",
    },
    "casa-moderna": {
        "defaultPath": "/",
        "sourceId": "11We-v4bq7dw_LSktJPxGNsd0oyf3yGD1",
        "title": "Casa Moderna – prémium otthonok",
    },
    "everyday-homes": {
        "defaultPath": "/",
        "sourceId": "1VZmftOSSK1ZZs1jePp7ZJKxErvELKKCF",
        "title": "Everyday Homes – praktikus otthonok",
    },
    "property-360": {
        "defaultPath": "/",
        "sourceId": "1bVAjyyycFcUl1qyGwU_XWWiti3rI1Hur",
        "title": "Property 360 – teljes projekt",
    },
    "baufreund": {
        "defaultPath": "/",
        "sourceId": "11jIKIOsmT6HAfWwm40OnSNoZW1Rztv7_",
        "title": "BauFreund – családbarát otthonok",
    },
    "red-property": {
        "defaultPath": "/",
        "sourceId": "1o0sW9QmuVu6Hwl-B4StjRwOZyQkQtl28",
        "title": "RED Property – gyors, elérhető otthonok",
    },
    "timberhaus": {
        "defaultPath": "/",
        "sourceId": "1ue19H61K7gNKdynpKovTN7ucsyK2qBBz",
        "title": "TimberHaus – Smart & Efficient",
    },
}
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
            "catalogPageCount": 70,
            "runtimeExternalApis": False,
            "notes": (
                "All standalone preview screens are registered. Runtime assets are "
                "brand-local; editorial fragments and WordPress-only templates are excluded."
            ),
        }
    )

    for brand, entry in DRIVE_PAGES.items():
        artifacts["brands"][brand] = {
            "defaultPath": entry["defaultPath"],
            "pages": [
                {
                    "title": entry["title"],
                    "path": "/",
                    "kind": "drive-source-preview",
                    "sourceId": entry["sourceId"],
                }
            ],
        }

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
    if page_count != 70:
        raise RuntimeError(f"Expected 70 catalog pages, found {page_count}")
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
