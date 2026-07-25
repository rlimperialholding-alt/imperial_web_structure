#!/usr/bin/env python3
"""Remove cross-brand payloads from imported B2B preview HTML files.

The source archive embedded all Imperial, Bautica and Prefab page records in
every generated HTML file.  That made a Prefab package physically contain
Imperial Holding copy even when only the Prefab record was rendered.  Keep
exactly the active record and active brand palette in each standalone package.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PALETTES = {
    "imperial": ["#152A3A", "#D4A54B", "#F4F1EA", "Imperial Holding"],
    "bautica": ["#173C57", "#F0B323", "#EEF4F5", "Bautica"],
    "prefab": ["#202A33", "#00A7C4", "#F1F4F5", "Prefab"],
}
PATTERN = re.compile(
    r"const P=(\{.*?\});const C=(\{.*?\});"
    r"const slug=.*?;const p=.*?;const c=C\[p\.brand\];",
    re.DOTALL,
)
GENERIC_CARD = (
    "${dark?'':'<p>Konkrét felelősséggel, mérhető kimenettel és az üzleti "
    "célhoz igazított műszaki döntésekkel.</p>'}"
)
PAGE_SPECIFIC_REPLACEMENTS = {
    "Megvizsgáljuk a műszaki realitást, a döntési pontokat és az ajánlatkészítéshez hiányzó adatokat.": (
        "${p.title} esetén először a műszaki realitást, a döntési pontokat és "
        "az ajánlatkészítéshez hiányzó adatokat tárjuk fel."
    ),
    "A helyszínt, az alapterületet, a rendelkezésre álló terveket, a kívánt műszaki tartalmat és a célhatáridőt.": (
        "A ${p.title.toLowerCase()} elővizsgálatához a helyszín, a méret, a "
        "rendelkezésre álló terv, a kívánt tartalom és a célidő szükséges."
    ),
    "A jóváhagyott műszaki tartalom, mennyiségek, helyszíni adottságok és szerződéses feltételek ismeretében.": (
        "A ${p.title.toLowerCase()} ára csak jóváhagyott műszaki tartalom, "
        "mennyiségek, helyszíni adottságok és feltételek alapján megbízható."
    ),
    "Rövid előminősítés készül, majd kijelöljük a szükséges műszaki vizsgálatot és a következő döntési pontot.": (
        "A ${p.title.toLowerCase()} rövid előminősítése után kijelöljük a "
        "szükséges vizsgálatot és a következő, felelőshöz kötött döntést."
    ),
    "Küldje el a helyszínt, a terveket és a fő üzleti célt.": (
        "A ${p.title.toLowerCase()} következő lépéséhez küldje el a helyszínt, "
        "a rendelkezésre álló terveket és a fő üzleti célt."
    ),
}


def unique_card_copy() -> str:
    return (
        "${dark?`<p>${p.title}: a(z) ${x.toLowerCase()} kockázatát már az "
        "előminősítésben láthatóvá tesszük.</p>`:`<p>${x} a ${p.title.toLowerCase()} "
        "oldalon külön döntési pontot, felelőst és ellenőrizhető kimenetet kap.</p>`}"
    )


def sanitize(path: Path, brand: str, variant: int) -> None:
    source = path.read_text(encoding="utf-8")
    match = PATTERN.search(source)
    if not match:
        return
    records = json.loads(match.group(1))
    slug = path.stem
    if slug not in records:
        raise RuntimeError(f"{path}: no record for {slug}")
    record = records[slug]
    if record["brand"] != brand:
        raise RuntimeError(f"{path}: expected {brand}, got {record['brand']}")
    replacement = (
        "const p="
        + json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        + f';const slug="{slug}";const c='
        + json.dumps(PALETTES[brand], ensure_ascii=False, separators=(",", ":"))
        + f";const variant={variant};document.body.classList.add(`variant-${{variant}}`);"
    )
    output = PATTERN.sub(replacement, source, count=1)
    output = output.replace(GENERIC_CARD, unique_card_copy())
    variant_css = (
        "<style>"
        ".variant-1 .hero .row,.variant-1 .section:nth-of-type(even) .row{flex-direction:row-reverse}"
        ".variant-2 .hero{background:var(--d);color:#fff}.variant-2 .hero .leadx{color:#dce3e8}"
        ".variant-2 .cardx{border-radius:4px;box-shadow:none}"
        ".variant-3 .steps{grid-template-columns:repeat(3,minmax(0,1fr))}.variant-3 .cardx{border-top:5px solid var(--a)}"
        ".variant-4 .section.dark{background:var(--s);color:var(--d)}.variant-4 .darkcard{background:#fff;color:var(--d)}"
        ".variant-4 .cta{border-radius:4px}.variant-5 .hero{text-align:center}.variant-5 .hero .col-lg-8{margin:auto}"
        ".variant-5 .cardx{border-radius:32px 4px 32px 4px}"
        "@media(max-width:767px){.variant-3 .steps{grid-template-columns:1fr 1fr}"
        ".step{min-width:0;overflow-wrap:anywhere}}"
        "</style>"
    )
    output = output.replace("</head>", f"{variant_css}</head>", 1)
    path.write_text(output, encoding="utf-8")


def personalize(path: Path) -> None:
    output = path.read_text(encoding="utf-8")
    if "const p=" not in output:
        return
    output = output.replace(
        ".variant-3 .steps{grid-template-columns:repeat(3,1fr)}"
        ".variant-3 .cardx{border-top:5px solid var(--a)}",
        ".variant-3 .steps{grid-template-columns:repeat(3,minmax(0,1fr))}"
        ".variant-3 .cardx{border-top:5px solid var(--a)}",
    )
    responsive_fix = (
        "@media(max-width:767px){.variant-3 .steps{grid-template-columns:1fr 1fr}"
        ".step{min-width:0;overflow-wrap:anywhere}}"
    )
    if responsive_fix not in output:
        output = output.replace("</style><style data-imported-layout-variants>", responsive_fix + "</style><style data-imported-layout-variants>", 1)
    for original, replacement in PAGE_SPECIFIC_REPLACEMENTS.items():
        output = output.replace(original, replacement)
    path.write_text(output, encoding="utf-8")


def main() -> None:
    total = 0
    for brand in PALETTES:
        files = sorted((ROOT / "sites" / brand).rglob("*.html"))
        active = [
            path
            for path in files
            if "const P=" in path.read_text(encoding="utf-8")
        ]
        for index, path in enumerate(active):
            sanitize(path, brand, index % 6)
            total += 1
        personalized = [
            path
            for path in files
            if "const p=" in path.read_text(encoding="utf-8")
        ]
        for path in personalized:
            personalize(path)
        print(
            f"{brand}: {len(active)} newly isolated, "
            f"{len(personalized)} page-specific B2B pages"
        )
    print(f"sanitized {total} multibrand previews")


if __name__ == "__main__":
    main()
