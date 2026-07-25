#!/usr/bin/env python3
"""Replace shared/CDN preview dependencies with brand-local assets."""

from __future__ import annotations

import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "sites"
SHARED = SITES / "_shared" / "assets"
ALL_BRANDS = [
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
BOOTSTRAP_BRANDS = {
    "imperial",
    "bautica",
    "prefab",
    "family-homes",
    "budapesti-magasepito-vallalat",
}


def add_before(content: str, marker: str, addition: str) -> str:
    return content if addition.strip() in content else content.replace(marker, addition + marker)


def localize_html(path: Path, brand: str) -> None:
    content = path.read_text(encoding="utf-8")
    base = f"/site-preview/{brand}/assets"
    content = content.replace(
        "/assets/preview-bootstrap.css",
        f"{base}/vendor/bootstrap/bootstrap.min.css",
    )
    content = content.replace(
        "/assets/review-bridge.css",
        f"{base}/platform/review-bridge.css",
    )
    content = content.replace(
        "/assets/review-bridge.js",
        f"{base}/platform/review-bridge.js",
    )
    if brand == "imperial" and path.name == "index.html" and path.parent == SITES / brand:
        content = content.replace('href="/assets/tokens.css"', f'href="{base}/tokens.css"')
        content = content.replace(
            'href="/assets/components.css"', f'href="{base}/components.css"'
        )
        content = content.replace(
            'href="/assets/imperial.css"', f'href="{base}/imperial.css"'
        )
        content = content.replace(
            'src="/assets/imperial.js"', f'src="{base}/imperial.js"'
        )
    if brand in BOOTSTRAP_BRANDS and "bootstrap.min.css" in content:
        content = add_before(
            content,
            "</head>",
            f'<link rel="stylesheet" href="{base}/vendor/bootstrap-icons/bootstrap-icons.min.css">',
        )
        content = add_before(
            content,
            "</body>",
            f'<script src="{base}/vendor/bootstrap/bootstrap.bundle.min.js"></script>',
        )
    content = add_before(
        content,
        "</head>",
        f'<link rel="stylesheet" href="{base}/platform/review-bridge.css">',
    )
    content = add_before(
        content,
        "</body>",
        f'<script src="{base}/platform/review-bridge.js" defer></script>',
    )
    path.write_text(content, encoding="utf-8")


def localize_family_page(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    base = "/site-preview/family-homes/assets"
    content = re.sub(
        r'<link rel="preconnect" href="https://cdn\.jsdelivr\.net">\s*',
        "",
        content,
    )
    content = content.replace(
        '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">',
        f'<link href="{base}/vendor/bootstrap/bootstrap.min.css" rel="stylesheet">',
    )
    content = content.replace(
        '<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css" rel="stylesheet">',
        f'<link href="{base}/vendor/bootstrap-icons/bootstrap-icons.min.css" rel="stylesheet">',
    )
    content = content.replace(
        '<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>',
        f'<script src="{base}/vendor/bootstrap/bootstrap.bundle.min.js"></script>',
    )
    content = re.sub(
        r'<meta name="robots" content="[^"]*">',
        '<meta name="robots" content="noindex,nofollow">',
        content,
        count=1,
    )
    path.write_text(content, encoding="utf-8")
    localize_html(path, "family-homes")


def copy_platform_assets() -> None:
    for brand in ALL_BRANDS:
        target = SITES / brand / "assets" / "platform"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SHARED / "review-bridge.css", target / "review-bridge.css")
        shutil.copy2(SHARED / "review-bridge.js", target / "review-bridge.js")


def copy_imperial_assets() -> None:
    target = SITES / "imperial" / "assets"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("tokens.css", "components.css", "imperial.css", "imperial.js"):
        shutil.copy2(SHARED / name, target / name)
    data_target = target / "data"
    data_target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SHARED / "data" / "imperial-home.json", data_target / "imperial-home.json")
    script = target / "imperial.js"
    script.write_text(
        script.read_text(encoding="utf-8").replace(
            'fetch("/assets/data/imperial-home.json"',
            'fetch("/site-preview/imperial/assets/data/imperial-home.json"',
        ),
        encoding="utf-8",
    )


def main() -> None:
    copy_platform_assets()
    copy_imperial_assets()
    for brand in ("imperial", "bautica", "prefab", "budapesti-magasepito-vallalat"):
        for path in (SITES / brand).rglob("*.html"):
            localize_html(path, brand)
    family_drive = SITES / "family-homes" / "drive"
    if family_drive.exists():
        for path in family_drive.glob("*.html"):
            localize_family_page(path)
    print("localized brand preview assets")


if __name__ == "__main__":
    main()
