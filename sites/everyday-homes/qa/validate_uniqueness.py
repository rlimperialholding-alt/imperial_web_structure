from __future__ import annotations

import html
import json
import re
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITES_ROOT = ROOT.parent
REGISTRY = ROOT / "data" / "completion-registry.json"
REPORT = ROOT / "qa" / "uniqueness-report.json"
WORD_RE = re.compile(r"[a-záéíóöőúüű0-9]+", re.I)
TAG_RE = re.compile(r"<[^>]+>")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
IGNORED_HEADINGS = {
    "hero",
    "gyakori kérdések",
    "gyakran ismételt kérdések",
    "kapcsolat",
    "everyday homes",
    "záró felhívás",
}


def normalize(value: str) -> str:
    value = html.unescape(TAG_RE.sub(" ", value)).lower()
    value = re.sub(r"[^a-záéíóöőúüű0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def public_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "NYILVÁNOS OLDALSZÖVEG" in text:
        text = text.split("NYILVÁNOS OLDALSZÖVEG", 1)[1]
    text = re.split(
        r"(?mi)^(?:\d+\.\s+)?(?:EGYEDI VIZUÁLIS ARCHETÍPUS|ÁLLÍTÁS- ÉS ADATKAPU|KAPUSTÁTUSZ|KIADÁSI STÁTUSZ|BELSŐ ELLENŐRZÉS|SZERKESZTŐI ÉS KOMPONENSÁTADÁS)\b",
        text,
        maxsplit=1,
    )[0]
    text = re.sub(r"\[[^\]]+\]", "", text)
    text = re.sub(
        r"(?mi)^(?:Mezők?|Űrlapmezők|Típusházkártya|Otthonkártya|Összehasonlítási mezők|Elsődleges gomb|Másodlagos gomb|Bizalmi sor):.*$",
        "",
        text,
    )
    return text


def registry_source_text(source: str) -> str:
    if source.startswith("assets/decision-pages.js#"):
        route = source.split("#", 1)[1]
        script = (ROOT / "assets" / "decision-pages.js").read_text(encoding="utf-8", errors="ignore")
        marker = f'  "{route}": {{'
        start = script.index(marker)
        next_page = re.search(r'\n  "/szamolok/[^\"]+": \{', script[start + len(marker):])
        end = start + len(marker) + next_page.start() if next_page else script.index("\n};", start)
        block = script[start:end]
        body = " ".join(re.findall(r"body:\s*`(.*?)`\s*,?", block, flags=re.S))
        metadata = " ".join(re.findall(r'(?:eyebrow|title|intro|closingTitle):\s*"([^"]+)"', block))
        faqs = " ".join(item for pair in re.findall(r'\["([^"]+\?)",\s*"([^"]+)"\]', block) for item in pair)
        return " ".join((body, metadata, faqs))
    return public_text(ROOT / "sources" / source)


def shingles(text: str, size: int = 5) -> set[tuple[str, ...]]:
    words = WORD_RE.findall(normalize(text))
    return {tuple(words[index:index + size]) for index in range(max(0, len(words) - size + 1))}


def jaccard(left: set[tuple[str, ...]], right: set[tuple[str, ...]]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def headings(text: str) -> set[str]:
    found = set()
    for raw in text.splitlines():
        line = raw.strip()
        if 8 <= len(line) <= 130 and line == line.upper() and any(ch.isalpha() for ch in line):
            key = normalize(line)
            if key not in IGNORED_HEADINGS and not re.fullmatch(r"\d+ gyakori kérdések", key):
                found.add(key)
    return found


def long_sentences(text: str) -> set[str]:
    return {
        sentence
        for sentence in (normalize(part) for part in SENTENCE_RE.split(text))
        if len(sentence) >= 70 and len(sentence.split()) >= 13
    }


def collect_other_brand_corpus() -> dict[str, str]:
    corpus: dict[str, str] = {}
    for site in SITES_ROOT.iterdir():
        if not site.is_dir() or site.name in {"everyday-homes", "_shared", "_portal"}:
            continue
        chunks = []
        for path in site.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".html", ".md", ".txt", ".json"}:
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
        corpus[site.name] = "\n".join(chunks)
    return corpus


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    source_rows = [row for row in registry["pages"] if row.get("source")]
    documents = {
        row["route"]: registry_source_text(row["source"])
        for row in source_rows
    }
    layouts = [row.get("layout_signature") for row in source_rows if row.get("layout_signature")]
    duplicate_layouts = sorted(name for name, count in Counter(layouts).items() if count > 1)

    pair_results = []
    repeated_headings = []
    repeated_sentences = []
    for left, right in combinations(documents, 2):
        score = jaccard(shingles(documents[left]), shingles(documents[right]))
        pair_results.append({"left": left, "right": right, "five_word_jaccard": round(score, 5)})
        shared_headings = sorted(headings(documents[left]) & headings(documents[right]))
        if shared_headings:
            repeated_headings.append({"left": left, "right": right, "headings": shared_headings})
        shared_sentences = sorted(long_sentences(documents[left]) & long_sentences(documents[right]))
        if shared_sentences:
            repeated_sentences.append({"left": left, "right": right, "sentences": shared_sentences})

    other_brands = collect_other_brand_corpus()
    cross_brand = []
    for route, text in documents.items():
        route_shingles = shingles(text)
        route_sentences = long_sentences(text)
        for brand, corpus in other_brands.items():
            score = jaccard(route_shingles, shingles(corpus))
            exact = sorted(route_sentences & long_sentences(corpus))
            if score >= 0.025 or exact:
                cross_brand.append({
                    "route": route,
                    "brand": brand,
                    "five_word_jaccard": round(score, 5),
                    "exact_long_sentences": exact,
                })

    failures = []
    high_similarity = [pair for pair in pair_results if pair["five_word_jaccard"] >= 0.08]
    if duplicate_layouts:
        failures.append(f"Ismétlődő layout-aláírás: {', '.join(duplicate_layouts)}")
    if high_similarity:
        failures.append(f"{len(high_similarity)} oldalpár öt-szavas hasonlósága eléri a 8%-ot")
    if repeated_headings:
        failures.append(f"{len(repeated_headings)} oldalpár azonos saját főcímet használ")
    if repeated_sentences:
        failures.append(f"{len(repeated_sentences)} oldalpár azonos hosszú mondatot használ")
    if cross_brand:
        failures.append(f"{len(cross_brand)} márkaközi tartalmi egyezés érte el a tiltási küszöböt")

    report = {
        "pages_checked": len(documents),
        "other_brands_checked": sorted(other_brands),
        "thresholds": {"within_brand_five_word_jaccard": 0.08, "cross_brand_five_word_jaccard": 0.025},
        "duplicate_layouts": duplicate_layouts,
        "highest_within_brand_pairs": sorted(pair_results, key=lambda item: item["five_word_jaccard"], reverse=True)[:15],
        "repeated_headings": repeated_headings,
        "repeated_long_sentences": repeated_sentences,
        "cross_brand_flags": cross_brand,
        "passed": not failures,
        "failures": failures,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "pages_checked": len(documents), "failures": failures}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
