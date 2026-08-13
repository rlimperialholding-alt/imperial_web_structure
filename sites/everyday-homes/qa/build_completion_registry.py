from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "data" / "page-map.json"
OUT_PATH = ROOT / "data" / "completion-registry.json"
RENDER_REPORT_PATH = ROOT / "qa" / "decision-pages-report.json"
TECHNOLOGY_RENDER_REPORT_PATH = ROOT / "qa" / "technology-pages-report.json"
SERVICE_RENDER_REPORT_PATH = ROOT / "qa" / "service-pages-report.json"
RICH_RENDER_REPORT_PATH = ROOT / "qa" / "rich-pages-report.json"

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
    "/ket-generacio-egy-otthon": "pages/106-ket-generacio-egy-otthon.md",
    "/kesobb-bovitheto-otthon": "pages/107-kesobb-bovitheto-otthon.md",
    "/szamolok/hazkoltseg": "pages/301-hazkoltseg.md",
}

DECISION_PAGE_ROUTES = {
    "/szamolok/havi-teher",
    "/szamolok/teljes-projektkeret",
    "/szamolok/utemterv",
    "/szamolok/felujitas-vagy-uj",
    "/szamolok/energia-es-koltseg",
    "/szamolok/gyors-hazellenorzes",
    "/muszaki-adatok",
}

TECHNOLOGY_PAGE_ROUTES = {
    "/mibol-epuljon",
    "/technologiak/favazas",
    "/technologiak/tegla",
    "/technologiak/liapor",
    "/technologiak/acelszerkezet",
}

SERVICE_PAGE_ROUTES = {
    "/mi-intezzuk/tervezes",
    "/mi-intezzuk/general-kivitelezes",
    "/mi-intezzuk/finanszirozas",
    "/mi-intezzuk/felujitas",
    "/mi-intezzuk/tetoter",
    "/mi-intezzuk/pincebol-lakas",
    "/mi-intezzuk/telek-ellenorzes",
    "/mi-intezzuk/szemelyes-hazajanlas",
    "/biztonsag/vallalasaink",
    "/biztonsag/atlathato-ar",
    "/biztonsag/szerzodes",
    "/biztonsag/projektkovetes",
    "/biztonsag/atadas-utan",
    "/elso-lepesek/mekkora-haz",
    "/elso-lepesek/jo-alaprajz",
    "/elso-lepesek/telekvasarlas",
    "/elso-lepesek/teljes-koltseg",
    "/elso-lepesek/technologia-valasztas",
    "/elso-lepesek/finanszirozas-menete",
    "/elso-lepesek/tarthato-utemterv",
    "/elso-lepesek/energia",
    "/kozelrol/elkeszult-otthonok",
    "/kozelrol/csaladok-tortenetei",
    "/adatkezeles",
    "/impresszum",
    "/sutik",
    "/akadalymentesseg",
}

PAGE_RULES = {
    "editorial": {"minimum_characters": 12_000, "minimum_faq": 25, "visual_assets": 3},
    "decision_tool": {"minimum_characters": 12_000, "minimum_faq": 25, "visual_assets": 3},
    "detailed_decision_tool": {"minimum_characters": 12_000, "minimum_faq": 25, "visual_assets": 3},
    "technology_page": {"minimum_characters": 12_000, "minimum_faq": 25, "visual_assets": 3},
    "service_page": {"minimum_characters": 12_000, "minimum_faq": 25, "visual_assets": 3},
}

DETAILED_DECISION_ROUTES = {
    "/szamolok/teljes-projektkeret",
    "/szamolok/utemterv",
    "/szamolok/energia-es-koltseg",
    "/muszaki-adatok",
}

DETAILED_FAQ_NAMES = {
    "/szamolok/teljes-projektkeret": "costFaq",
    "/szamolok/utemterv": "scheduleFaq",
    "/szamolok/energia-es-koltseg": "energyFaq",
    "/muszaki-adatok": "technicalFaq",
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
    "/ket-generacio-egy-otthon": "two-household-bridge",
    "/kesobb-bovitheto-otthon": "phased-home-blueprint",
    "/szamolok/hazkoltseg": "project-cost-ledger",
    "/szamolok/havi-teher": "monthly-room",
    "/szamolok/teljes-projektkeret": "cost-map",
    "/szamolok/utemterv": "schedule-line",
    "/szamolok/felujitas-vagy-uj": "three-choices",
    "/szamolok/energia-es-koltseg": "warm-cold",
    "/szamolok/gyors-hazellenorzes": "family-compass",
    "/muszaki-adatok": "technical-specification-detailed",
    "/mibol-epuljon": "technology-atlas",
    "/technologiak/favazas": "timber-layers",
    "/technologiak/tegla": "brick-calendar",
    "/technologiak/liapor": "liapor-logistics",
    "/technologiak/acelszerkezet": "steel-precision",
    "/mi-intezzuk/tervezes": "daily-rhythm",
    "/mi-intezzuk/general-kivitelezes": "responsibility-grid",
    "/mi-intezzuk/finanszirozas": "funding-roadmap",
    "/mi-intezzuk/felujitas": "condition-map",
    "/mi-intezzuk/tetoter": "roof-section",
    "/mi-intezzuk/pincebol-lakas": "space-reborn",
    "/mi-intezzuk/telek-ellenorzes": "plot-fieldbook",
    "/mi-intezzuk/szemelyes-hazajanlas": "home-conversation",
    "/biztonsag/vallalasaink": "promise-ledger",
    "/biztonsag/atlathato-ar": "open-cost-map",
    "/biztonsag/szerzodes": "contract-margin",
    "/biztonsag/projektkovetes": "site-diary",
    "/biztonsag/atadas-utan": "care-calendar",
    "/elso-lepesek/mekkora-haz": "room-measure",
    "/elso-lepesek/jo-alaprajz": "plan-economy",
    "/elso-lepesek/telekvasarlas": "plot-expedition",
    "/elso-lepesek/teljes-koltseg": "cost-cutaway",
    "/elso-lepesek/technologia-valasztas": "material-library",
    "/elso-lepesek/finanszirozas-menete": "funding-conveyor",
    "/elso-lepesek/tarthato-utemterv": "schedule-weave",
    "/elso-lepesek/energia": "comfort-climate",
    "/kozelrol/elkeszult-otthonok": "open-house-album",
    "/kozelrol/csaladok-tortenetei": "story-portraits",
    "/adatkezeles": "privacy-ledger",
    "/impresszum": "identity-blueprint",
    "/sutik": "cookie-control-room",
    "/akadalymentesseg": "accessibility-path",
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


def decision_page_source(route: str) -> str:
    detailed = (ROOT / "assets" / "detailed-project-pages.js").read_text(encoding="utf-8")
    marker = f'DECISION_PAGE_MAP["{route}"] = {{'
    if marker in detailed:
        start = detailed.index(marker)
        next_page = detailed.find("\n  DECISION_PAGE_MAP[", start + len(marker))
        end = next_page if next_page != -1 else detailed.index("\n  upgradeDecisionPage", start)
        block = detailed[start:end]
        faq_name = DETAILED_FAQ_NAMES[route]
        faq_start = detailed.index(f"const {faq_name} = faq([")
        faq_end = detailed.index("\n  ]);", faq_start) + len("\n  ]);")
        return block + "\n" + detailed[faq_start:faq_end]
    source = (ROOT / "assets" / "decision-pages.js").read_text(encoding="utf-8")
    marker = f'  "{route}": {{'
    start = source.index(marker)
    next_page = re.search(r'\n  "/szamolok/[^\"]+": \{', source[start + len(marker):])
    end = start + len(marker) + next_page.start() if next_page else source.index("\n};", start)
    return source[start:end]


def decision_visible_copy(source: str) -> str:
    body_blocks = re.findall(r"body:\s*`(.*?)`\s*,?", source, flags=re.S)
    quoted_copy = re.findall(r'(?:eyebrow|title|intro|closingTitle):\s*"([^"]+)"', source)
    faq_copy = [item for pair in re.findall(r'\["([^"]+\?)",\s*"([^"]+)"\]', source) for item in pair]
    text = " ".join(body_blocks + quoted_copy + faq_copy)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def main() -> None:
    page_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    render_report = json.loads(RENDER_REPORT_PATH.read_text(encoding="utf-8")) if RENDER_REPORT_PATH.exists() else {"checks": []}
    technology_render_report = json.loads(TECHNOLOGY_RENDER_REPORT_PATH.read_text(encoding="utf-8")) if TECHNOLOGY_RENDER_REPORT_PATH.exists() else {"checks": []}
    service_render_report = json.loads(SERVICE_RENDER_REPORT_PATH.read_text(encoding="utf-8")) if SERVICE_RENDER_REPORT_PATH.exists() else {"checks": []}
    rich_render_report = json.loads(RICH_RENDER_REPORT_PATH.read_text(encoding="utf-8")) if RICH_RENDER_REPORT_PATH.exists() else {"checks": []}
    rendered_by_route: dict[str, list[dict]] = {}
    for check in render_report.get("checks", []) + technology_render_report.get("checks", []) + service_render_report.get("checks", []) + rich_render_report.get("checks", []):
        rendered_by_route.setdefault(check.get("route", ""), []).append(check)
    rows = []
    for group in page_map["groups"]:
        for page_id, route, title in group["pages"]:
            source_name = SOURCE_BY_ROUTE.get(route)
            page_type = "service_page" if route in SERVICE_PAGE_ROUTES else ("technology_page" if route in TECHNOLOGY_PAGE_ROUTES else ("detailed_decision_tool" if route in DETAILED_DECISION_ROUTES else ("decision_tool" if route in DECISION_PAGE_ROUTES else "editorial")))
            rules = PAGE_RULES[page_type]
            excluded_from_scope = route.startswith(HOUSE_PREFIXES) or page_id == "EH-HU-003"
            raw = ""
            if page_type == "service_page":
                legal_routes = {"/adatkezeles", "/impresszum", "/sutik", "/akadalymentesseg"}
                source_file = "legal-pages.js" if route in legal_routes else "service-pages.js"
                source_name = f"assets/{source_file}#{route}"
                raw = (ROOT / "assets" / source_file).read_text(encoding="utf-8")
                visible = ""
                questions = 0
            elif page_type == "technology_page":
                source_name = f"assets/technology-pages.js#{route}"
                raw = (ROOT / "assets" / "technology-pages.js").read_text(encoding="utf-8")
                visible = ""
                questions = 0
            elif page_type in {"decision_tool", "detailed_decision_tool"}:
                source_name = f"assets/{'detailed-project-pages.js' if route in DETAILED_DECISION_ROUTES else 'decision-pages.js'}#{route}"
                raw = decision_page_source(route)
                visible = decision_visible_copy(raw)
                questions = len(re.findall(r'\["[^"]+\?",\s*"[^"]+"\]', raw))
            elif source_name:
                raw = (ROOT / "sources" / source_name).read_text(encoding="utf-8")
                visible = public_copy(raw)
                questions = faq_count(raw)
            else:
                visible = ""
                questions = 0
            chars = len(visible)
            qa_passes = 0
            rendered_checks = rendered_by_route.get(route, [])
            if page_type == "editorial" and rendered_checks:
                chars = max(int(check.get("contentCharacters", 0)) for check in rendered_checks)
                questions = max(int(check.get("faqItems", 0)) for check in rendered_checks)
                qa_passes = min(3, len({check.get("viewport") for check in rendered_checks if check.get("passed")}))
            if page_type in {"decision_tool", "detailed_decision_tool", "technology_page", "service_page"} and rendered_checks:
                chars = max(int(check.get("contentCharacters", 0)) for check in rendered_checks)
                questions = max(int(check.get("faqItems", 0)) for check in rendered_checks)
                rendered_passes = len({check.get("viewport") for check in rendered_checks if check.get("passed")})
                qa_passes = min(3, rendered_passes)
            if excluded_from_scope:
                state = "NIM_CONTENT_PLACEHOLDER"
            elif not source_name:
                state = "ROUTE_SHELL_ONLY"
            elif chars < rules["minimum_characters"]:
                state = "SOURCE_IMPORTED_NEEDS_EXPANSION"
            elif questions < rules["minimum_faq"]:
                state = "SOURCE_IMPORTED_NEEDS_FAQ"
            elif qa_passes == 3:
                state = "AUTOMATED_QA_PASSED_COPY_REVIEW_REQUIRED"
            else:
                state = "SOURCE_IMPORTED_NEEDS_VISUAL_QA"
            rows.append({
                "page_id": page_id,
                "route": route,
                "title": title,
                "group": group["name"],
                "page_type": page_type,
                "state": state,
                "source": source_name,
                "visible_body_characters": chars,
                "faq_questions": questions,
                "minimum_visible_body_characters": rules["minimum_characters"],
                "minimum_faq_questions": rules["minimum_faq"],
                "visual_assets": rules["visual_assets"] if source_name else 0,
                "layout_signature": LAYOUT_BY_ROUTE.get(route),
                "automated_render_passes": qa_passes,
                "independent_copy_reviews": 0,
                "copy_gate_state": "BLOCKED_MISSING_HASH_BOUND_INDEPENDENT_REVIEWS",
                "publication_allowed": False,
            })

    payload = {
        "brand": "Everyday Homes",
        "generated_from": "Drive canonical sources + page-map.json",
        "minimum_visible_body_characters": 12_000,
        "preferred_visible_body_characters": 20_000,
        "minimum_faq_questions": 25,
        "minimum_page_specific_visuals": 3,
        "required_qa_passes": 3,
        "publication_allowed": False,
        "summary": {
            "canonical_routes": len(rows),
            "nim_managed_routes": sum(r["state"] == "NIM_CONTENT_PLACEHOLDER" for r in rows),
            "source_imported_routes": sum(bool(r["source"]) for r in rows),
            "route_shells": sum(r["state"] == "ROUTE_SHELL_ONLY" for r in rows),
            "automated_qa_passed_routes": sum(r["state"] == "AUTOMATED_QA_PASSED_COPY_REVIEW_REQUIRED" for r in rows),
            "publication_ready_routes": 0,
        },
        "pages": rows,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
