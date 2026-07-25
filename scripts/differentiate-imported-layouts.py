#!/usr/bin/env python3
"""Add stable page-specific layout variants to completed imported screens."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "sites" / "_portal" / "data" / "artifacts.json"
STYLE_MARKER = "data-imported-layout-variants"
FAMILY_SHARED_NOTICE = (
    "A hiánytalan megkeresésekre 2 munkanapon belül reagálunk. "
    "Az előzetes becslés nem minősül végleges ajánlatnak."
)
VARIANT_CSS = """<style data-imported-layout-variants>
body.preview-layout-0 main>section:nth-child(3n+2){border-inline-start:7px solid currentColor}
body.preview-layout-1 main>section:nth-child(even){background-image:linear-gradient(135deg,rgba(0,0,0,.045),transparent 62%)}
body.preview-layout-1 .hero-grid,body.preview-layout-1 header.hero{direction:rtl}body.preview-layout-1 .hero-grid>*,body.preview-layout-1 header.hero>*{direction:ltr}
body.preview-layout-2 .card,body.preview-layout-2 .cardx,body.preview-layout-2 article{border-radius:3px!important;box-shadow:none!important}
body.preview-layout-2 main>section:nth-child(odd){border-block:1px solid rgba(0,0,0,.12)}
body.preview-layout-3 h1{max-width:18ch!important}body.preview-layout-3 main>section:nth-child(3n){clip-path:polygon(0 3%,100% 0,100% 97%,0 100%);padding-block:clamp(5rem,9vw,9rem)}
body.preview-layout-4 .card,body.preview-layout-4 .cardx,body.preview-layout-4 article{border-radius:34px 6px 34px 6px!important}
body.preview-layout-4 main>section:nth-child(even) .row{flex-direction:row-reverse}
body.preview-layout-5 main>section:nth-child(odd){background-image:repeating-linear-gradient(90deg,transparent 0,transparent calc(8.333% - 1px),rgba(0,0,0,.035) calc(8.333% - 1px),rgba(0,0,0,.035) 8.333%)}
body.preview-layout-5 .steps{grid-template-columns:repeat(3,minmax(0,1fr))!important}
body.preview-layout-6 h1,body.preview-layout-6 h2{letter-spacing:-.055em!important}body.preview-layout-6 main>section:nth-child(even) .container{max-width:1040px}
body.preview-layout-7 main>section:nth-child(3n+1){border-bottom:12px solid rgba(0,0,0,.1)}body.preview-layout-7 .card,body.preview-layout-7 .cardx,body.preview-layout-7 article{transform:translateY(var(--card-shift,0))}
@media(min-width:768px) and (max-width:991.98px){.row.g-5{--bs-gutter-x:1.5rem}}
@media(max-width:800px){body.preview-layout-1 .hero-grid,body.preview-layout-1 header.hero{direction:ltr}body.preview-layout-3 main>section:nth-child(3n){clip-path:none}body.preview-layout-5 .steps{grid-template-columns:1fr 1fr!important}}
</style>"""


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "home"


def page_file(brand: str, page_path: str) -> Path:
    root = ROOT / "sites" / brand
    return root / "index.html" if page_path == "/" else root / page_path.lstrip("/")


def differentiate(path: Path, slug: str, variant: int) -> None:
    source = path.read_text(encoding="utf-8")
    if STYLE_MARKER in source:
        source = re.sub(
            rf"<style {STYLE_MARKER}>.*?</style>",
            VARIANT_CSS,
            source,
            count=1,
            flags=re.DOTALL,
        )
    else:
        source = source.replace("</head>", f"{VARIANT_CSS}</head>", 1)
    body_match = re.search(r"<body(?P<attrs>[^>]*)>", source, re.IGNORECASE)
    if not body_match:
        raise RuntimeError(f"{path}: no body element")
    attrs = body_match.group("attrs")
    class_match = re.search(r'\bclass=(["\'])(.*?)\1', attrs, re.IGNORECASE)
    generated = f"preview-layout-{variant} preview-page-{slug}"
    if class_match:
        existing = re.sub(
            r"\b(?:preview-layout-\d+|preview-page-[\w-]+)\b",
            "",
            class_match.group(2),
        )
        classes = re.sub(r"\s+", " ", f"{existing} {generated}").strip()
        attrs = (
            attrs[: class_match.start()]
            + f'class="{classes}"'
            + attrs[class_match.end() :]
        )
    else:
        attrs = f'{attrs} class="{generated}"'
    attrs = re.sub(r'\sdata-preview-layout="[^"]*"', "", attrs)
    attrs += f' data-preview-layout="{variant}"'
    source = (
        source[: body_match.start()]
        + f"<body{attrs}>"
        + source[body_match.end() :]
    )
    path.write_text(source, encoding="utf-8")


def personalize_family_notice(path: Path, page_title: str) -> None:
    source = path.read_text(encoding="utf-8")
    replacement = (
        f"A {page_title.lower()} témájában érkező hiánytalan megkeresésre "
        "2 munkanapon belül reagálunk. Az előzetes tájékoztatás nem minősül "
        "végleges ajánlatnak."
    )
    source = source.replace(FAMILY_SHARED_NOTICE, replacement)
    path.write_text(source, encoding="utf-8")


def main() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    count = 0
    for brand, entry in catalog["brands"].items():
        imported = [
            page for page in entry["pages"] if page.get("kind") != "drive-source-page"
        ]
        for index, page in enumerate(imported):
            slug = slugify(Path(page["path"]).stem if page["path"] != "/" else "home")
            path = page_file(brand, page["path"])
            differentiate(path, slug, index % 8)
            if brand == "family-homes":
                personalize_family_notice(path, page["title"])
            count += 1
    print(f"differentiated {count} imported preview layouts")


if __name__ == "__main__":
    main()
