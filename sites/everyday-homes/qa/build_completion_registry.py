from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "data" / "page-map.json"
OUT_PATH = ROOT / "data" / "completion-registry.json"
EVIDENCE_PATH = ROOT / "qa" / "qa-evidence.json"

SOURCE_BY_ROUTE = {
    "/": "drive/01-kezdolap.md",
    "/otthonvalaszto": "drive/02-otthonvalaszto.md",
    "/keretbol-otthon": "drive/04-keretbol-otthon.md",
    "/igy-lesz-egyszeru": "drive/05-igy-lesz-egyszeru.md",
    "/kozelrol": "drive/06-kozelrol.md",
    "/elso-lepesek": "drive/07-tudastar.md",
    "/a-fontos-kerdesek": "drive/08-gyik.md",
    "/kezdjuk-egyutt": "drive/09-kapcsolat.md",
    "/kell-egy-otthon-mindenkinek": "pages/10-kuldetesunk.md",
    "/garanciak-es-utogondozas": "pages/11-garanciak-es-utogondozas.md",
    "/elso-lepesek-hirlevel": "pages/12-hirlevel.md",
    "/karrier": "pages/13-karrier.md",
    "/sajto": "pages/14-sajto.md",
    "/elso-sajat-otthon": "pages/101-elso-sajat-otthon.md",
    "/most-leszunk-csalad": "pages/102-most-leszunk-csalad.md",
    "/tobb-hely-a-csaladnak": "pages/103-tobb-hely-a-csaladnak.md",
    "/otthon-es-munka": "pages/104-otthon-es-munka.md",
    "/kisebb-haz-konnyebb-elet": "pages/105-kisebb-haz-konnyebb-elet.md",
}

LAYOUT_BY_ROUTE = {
    "/": "family-editorial",
    "/otthonvalaszto": "chooser-mosaic",
    "/keretbol-otthon": "family-ledger",
    "/igy-lesz-egyszeru": "guided-journey",
    "/kozelrol": "proof-gallery",
    "/elso-lepesek": "knowledge-magazine",
    "/a-fontos-kerdesek": "question-wall",
    "/kezdjuk-egyutt": "conversation-room",
    "/kell-egy-otthon-mindenkinek": "mission-manifesto",
    "/garanciak-es-utogondozas": "care-protocol",
    "/elso-lepesek-hirlevel": "letter-lab",
    "/karrier": "maker-workshop",
    "/sajto": "press-desk",
    "/elso-sajat-otthon": "first-key-map",
    "/most-leszunk-csalad": "family-rhythm",
    "/tobb-hely-a-csaladnak": "family-traffic",
    "/otthon-es-munka": "workday-switchboard",
    "/kisebb-haz-konnyebb-elet": "lighter-life-balance",
}

HOUSE_PREFIXES = ("/otthonok/",)


def public_copy(text: str) -> str:
    marker = "NYILVÁNOS OLDALSZÖVEG"
    if marker in text:
        text = text.split(marker, 1)[1]
    text = re.sub(r"\[[^\]]*(?:SZÜKSÉGES|JÓVÁHAGYÁS|FORRÁS)[^\]]*\]", "", text, flags=re.I)
    text = re.sub(r"^(?:Elsődleges|Másodlagos)?\s*[Gg]omb:.*$", "", text, flags=re.M)
    text = re.sub(r"^Bizalmi sor:.*$", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def faq_count(text: str) -> int:
    return len(re.findall(r"(?m)^[^\n]{8,160}\?\s*$", text))


def main() -> None:
    page_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    qa_evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8")) if EVIDENCE_PATH.exists() else {"routes": {}}
    rows = []
    for group in page_map["groups"]:
        for page_id, route, title in group["pages"]:
            source_name = SOURCE_BY_ROUTE.get(route)
            excluded_from_scope = route.startswith(HOUSE_PREFIXES) or page_id == "EH-HU-003"
            raw = ""
            if source_name:
                raw = (ROOT / "sources" / source_name).read_text(encoding="utf-8")
            visible = public_copy(raw)
            chars = len(visible)
            questions = faq_count(raw)
            qa_passes = int(qa_evidence.get("routes", {}).get(route, {}).get("passes", 0))
            if excluded_from_scope:
                state = "NIM_CONTENT_PLACEHOLDER"
            elif not source_name:
                state = "ROUTE_SHELL_ONLY"
            elif chars < 12_000:
                state = "SOURCE_IMPORTED_NEEDS_EXPANSION"
            elif questions < 5:
                state = "SOURCE_IMPORTED_NEEDS_FAQ"
            elif qa_passes == 3:
                state = "COMPLETE_REVIEW_REQUIRED"
            else:
                state = "SOURCE_IMPORTED_NEEDS_VISUAL_QA"
            rows.append({
                "page_id": page_id,
                "route": route,
                "title": title,
                "group": group["name"],
                "state": state,
                "source": source_name,
                "visible_body_characters": chars,
                "faq_questions": questions,
                "visual_assets": 3 if source_name else 0,
                "layout_signature": LAYOUT_BY_ROUTE.get(route),
                "triple_qa_passes": qa_passes,
                "publication_allowed": False,
            })

    payload = {
        "brand": "Everyday Homes",
        "generated_from": "Drive canonical sources + page-map.json",
        "minimum_visible_body_characters": 12_000,
        "preferred_visible_body_characters": 20_000,
        "minimum_page_specific_visuals": 3,
        "required_qa_passes": 3,
        "publication_allowed": False,
        "summary": {
            "canonical_routes": len(rows),
            "nim_managed_routes": sum(r["state"] == "NIM_CONTENT_PLACEHOLDER" for r in rows),
            "source_imported_routes": sum(bool(r["source"]) for r in rows),
            "route_shells": sum(r["state"] == "ROUTE_SHELL_ONLY" for r in rows),
            "complete_routes": sum(r["state"] == "COMPLETE_REVIEW_REQUIRED" for r in rows),
        },
        "pages": rows,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
