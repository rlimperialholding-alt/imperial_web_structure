#!/usr/bin/env python3
"""Audit preview copy uniqueness, brand ownership and source/guide alignment."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "sites" / "_portal" / "data" / "artifacts.json"
SOURCE_RULES = {
    "imperial": {
        "tagline": "Csodálatos otthonok megfizethető áron.",
        "primary": "#152A3A",
        "accent": "#D4A54B",
    },
    "danish-fabrik": {
        "tagline": "Nem érdemes másból építeni.",
        "primary": "#234B5C",
        "accent": "#F4C95D",
    },
    "bautica": {
        "tagline": "Értünk hozzá. Az építés tudománya.",
        "primary": "#173C57",
        "accent": "#F0B323",
    },
    "prefab": {
        "tagline": "Építőipar 2.0. Nincsenek kérdőjelek. Betonbiztos építkezés.",
        "primary": "#202A33",
        "accent": "#00A7C4",
    },
    "casa-moderna": {
        "tagline": "Nem csak megérkezik. Hazatér.",
        "primary": "#191816",
        "accent": "#B79A6B",
    },
    "everyday-homes": {
        "tagline": "Otthon – egyszerűen.",
        "primary": "#376C76",
        "accent": "#F3B563",
    },
    "property-360": {
        "tagline": "Kattints és költözz!",
        "primary": "#123B4A",
        "accent": "#29C3B2",
    },
    "baufreund": {
        "tagline": "BauFreund. Az építő barát.",
        "primary": "#245B49",
        "accent": "#F2A541",
    },
    "red-property": {
        "tagline": "Típusházak a leggyorsabban és a legjobb árakon!",
        "primary": "#C91F32",
        "accent": "#FFD400",
    },
    "timberhaus": {
        "tagline": "Fából mindent lehet.",
        "primary": "#244734",
        "accent": "#C98A4A",
    },
}
FORBIDDEN_BY_BRAND = {
    "prefab": (
        "imperial holding",
        "imperialholding.hu",
        "bautica",
        "csodálatos otthonok",
    ),
}
BLOCK_TAGS = {"h1", "h2", "h3", "p", "li", "summary"}
IGNORED_CONTAINERS = {"script", "style", "nav", "footer"}
BOILERPLATE_PATTERNS = (
    "preview nem küld adatot",
    "drive-forráshoz igazított",
    "forrás:",
    "publikálás nélkül",
)


def normalize(value: str) -> str:
    value = value.casefold().replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[^\wáéíóöőúüű%+–-]+", " ", value)
    return value.strip()


@dataclass
class Parsed:
    blocks: list[str] = field(default_factory=list)
    title: str = ""
    metas: dict[str, str] = field(default_factory=dict)
    body_classes: str = ""
    section_classes: list[str] = field(default_factory=list)


class Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.result = Parsed()
        self.ignored_depth = 0
        self.capture_tag: str | None = None
        self.capture: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in IGNORED_CONTAINERS:
            self.ignored_depth += 1
        if tag == "title":
            self.in_title = True
            self.capture = []
        if tag == "meta" and values.get("name") and values.get("content"):
            self.result.metas[values["name"]] = values["content"]
        if tag == "body":
            self.result.body_classes = values.get("class", "")
        if tag == "section":
            self.result.section_classes.append(values.get("class", ""))
        if self.ignored_depth == 0 and tag in BLOCK_TAGS:
            self.capture_tag = tag
            self.capture = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self.in_title:
            self.result.title = " ".join(self.capture).strip()
            self.capture = []
            self.in_title = False
        elif tag == self.capture_tag:
            value = " ".join(self.capture).strip()
            if value:
                self.result.blocks.append(value)
            self.capture_tag = None
            self.capture = []
        if tag in IGNORED_CONTAINERS and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_title or (self.capture_tag and self.ignored_depth == 0):
            self.capture.append(data)


def file_for(brand: str, page_path: str) -> Path:
    root = ROOT / "sites" / brand
    if page_path == "/":
        return root / "index.html"
    return root / page_path.lstrip("/")


def is_meaningful(block: str) -> bool:
    value = normalize(block)
    return (
        len(value) >= 90
        and not any(pattern in value for pattern in BOILERPLATE_PATTERNS)
    )


def main() -> None:
    cli = argparse.ArgumentParser()
    cli.add_argument("--json-output", type=Path)
    cli.add_argument("--markdown-output", type=Path)
    args = cli.parse_args()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    errors: list[dict] = []
    warnings: list[dict] = []
    occurrences: dict[str, list[dict]] = defaultdict(list)
    layout_occurrences: dict[str, list[dict]] = defaultdict(list)
    brand_summary: dict[str, dict] = {}

    for brand, entry in catalog["brands"].items():
        brand_summary[brand] = {
            "pages": len(entry["pages"]),
            "sourceAligned": 0,
            "foreignBrandErrors": 0,
            "duplicateErrors": 0,
        }
        for page in entry["pages"]:
            path = file_for(brand, page["path"])
            if not path.is_file():
                errors.append(
                    {"type": "missing-html", "brand": brand, "path": page["path"]}
                )
                continue
            source = path.read_text(encoding="utf-8")
            parser = Parser()
            parser.feed(source)
            parsed = parser.result
            page_ref = {"brand": brand, "path": page["path"], "title": page["title"]}
            if page.get("kind") == "drive-source-page":
                brand_summary[brand]["sourceAligned"] += 1
                for meta in ("source-id", "brand-guide-id", "content-status"):
                    if not parsed.metas.get(meta):
                        errors.append(
                            {
                                "type": "missing-source-meta",
                                **page_ref,
                                "meta": meta,
                            }
                        )
                rules = SOURCE_RULES[brand]
                folded = source.casefold()
                if folded.count(rules["tagline"].casefold()) < 2:
                    errors.append({"type": "missing-canonical-tagline", **page_ref})
                for token in (rules["primary"], rules["accent"]):
                    if token.casefold() not in folded:
                        errors.append(
                            {"type": "missing-brand-token", **page_ref, "token": token}
                        )

            folded_source = source.casefold()
            for marker in FORBIDDEN_BY_BRAND.get(brand, ()):
                if marker in folded_source:
                    brand_summary[brand]["foreignBrandErrors"] += 1
                    errors.append(
                        {
                            "type": "foreign-brand-marker",
                            **page_ref,
                            "marker": marker,
                        }
                    )

            local_seen: dict[str, int] = defaultdict(int)
            for block in parsed.blocks:
                if not is_meaningful(block):
                    continue
                key = normalize(block)
                local_seen[key] += 1
                occurrences[key].append({**page_ref, "text": block[:240]})
            for key, count in local_seen.items():
                if count > 1:
                    brand_summary[brand]["duplicateErrors"] += 1
                    errors.append(
                        {
                            "type": "duplicate-block-within-page",
                            **page_ref,
                            "count": count,
                            "text": key[:240],
                        }
                    )
            signature_source = "|".join(
                [parsed.body_classes, *parsed.section_classes]
            )
            if signature_source:
                signature = hashlib.sha256(signature_source.encode()).hexdigest()[:12]
                layout_occurrences[f"{brand}:{signature}"].append(page_ref)

    for block, refs in occurrences.items():
        unique_pages = {(ref["brand"], ref["path"]) for ref in refs}
        if len(unique_pages) > 1:
            brands = {ref["brand"] for ref in refs}
            level = errors if len(block) >= 150 and len(brands) > 1 else warnings
            record = {
                "type": "duplicate-block-across-pages",
                "pageCount": len(unique_pages),
                "brands": sorted(brands),
                "text": refs[0]["text"],
                "pages": [f"{ref['brand']}:{ref['path']}" for ref in refs[:12]],
            }
            level.append(record)

    for key, refs in layout_occurrences.items():
        if len(refs) > 2:
            warnings.append(
                {
                    "type": "shared-layout-signature",
                    "brand": key.split(":", 1)[0],
                    "pageCount": len(refs),
                    "pages": [ref["path"] for ref in refs],
                }
            )

    report = {
        "meta": {
            "catalogPages": sum(
                len(entry["pages"]) for entry in catalog["brands"].values()
            ),
            "errors": len(errors),
            "warnings": len(warnings),
            "policy": (
                "Exact visible blocks of 150+ normalized characters across brands "
                "are errors; shorter/same-brand repeats and shared structures are warnings."
            ),
        },
        "brands": brand_summary,
        "errors": errors,
        "warnings": warnings,
    }
    markdown = [
        "# Weboldal tartalmi, márka- és arculati audit",
        "",
        f"- Katalógusoldalak: **{report['meta']['catalogPages']}**",
        f"- Hibák: **{len(errors)}**",
        f"- Figyelmeztetések: **{len(warnings)}**",
        "",
        "## Márkánkénti állapot",
        "",
        "| Márka | Oldal | Drive-forráshoz igazított | Márkakeveredési hiba | Ismétlődési hiba |",
        "|---|---:|---:|---:|---:|",
    ]
    for brand, row in brand_summary.items():
        markdown.append(
            f"| {brand} | {row['pages']} | {row['sourceAligned']} | "
            f"{row['foreignBrandErrors']} | {row['duplicateErrors']} |"
        )
    markdown.extend(["", "## Hibák", ""])
    if errors:
        markdown.extend(
            f"- `{item['type']}` – {item.get('brand', ', '.join(item.get('brands', [])))} "
            f"{item.get('path', '')}: {item.get('marker', item.get('text', ''))}"
            for item in errors
        )
    else:
        markdown.append("- Nincs blokkoló tartalmi vagy márkakeveredési hiba.")
    markdown.extend(["", "## Figyelmeztetések", ""])
    if warnings:
        markdown.extend(
            f"- `{item['type']}` – {item.get('brand', ', '.join(item.get('brands', [])))}: "
            f"{item.get('text', item.get('pages', ''))}"
            for item in warnings
        )
    else:
        markdown.append("- Nincs figyelmeztetés.")

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(
        f"content audit: {report['meta']['catalogPages']} pages, "
        f"{len(errors)} errors, {len(warnings)} warnings"
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
