from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "assets" / "site.css").read_text(encoding="utf-8")
JS = "\n".join(path.read_text(encoding="utf-8") for path in sorted((ROOT / "assets").glob("*.js")))
PAGE_MAP = json.loads((ROOT / "data" / "page-map.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((ROOT / "data" / "completion-registry.json").read_text(encoding="utf-8"))

assert PAGE_MAP["canonical_page_count"] == 67
assert PAGE_MAP["publication_allowed"] is False
pages = [page for group in PAGE_MAP["groups"] for page in group["pages"]]
assert len(pages) == PAGE_MAP["canonical_page_count"], len(pages)
assert len({page[0] for page in pages}) == PAGE_MAP["canonical_page_count"]
assert len({page[1] for page in pages}) == PAGE_MAP["canonical_page_count"]

assert 'name="robots" content="noindex,nofollow"' in INDEX
assert 'publication_allowed = true' not in (INDEX + CSS + JS)
assert not re.search(r'https?://', INDEX + CSS + JS), "External runtime dependency found"
assert '#ff0000' not in CSS.lower() and '#e41' not in CSS.lower(), "Forbidden red palette"

for asset in re.findall(r'(?:src|href)="([^"]+)"', INDEX):
    if asset.startswith("/site-preview/everyday-homes/"):
        if not Path(asset).suffix:
            continue
        target = ROOT / asset.removeprefix("/site-preview/everyday-homes/")
        assert target.exists(), f"Missing local asset: {asset}"

implemented_ids = set(re.findall(r'"(EH-HU-\d{3})"', JS))
canonical_ids = {page[0] for page in pages}
assert implemented_ids <= canonical_ids
assert implemented_ids == canonical_ids, sorted(canonical_ids - implemented_ids)

registry_pages = REGISTRY["pages"]
assert len(registry_pages) == PAGE_MAP["canonical_page_count"]
assert {page["page_id"] for page in registry_pages} == canonical_ids
assert REGISTRY["publication_allowed"] is False
assert REGISTRY["minimum_visible_body_characters"] == 12_000
assert REGISTRY["minimum_page_specific_visuals"] == 3
assert REGISTRY["required_qa_passes"] == 3

complete = [page for page in registry_pages if page["state"] == "COMPLETE_REVIEW_REQUIRED"]
layout_signatures = []
for page in complete:
    assert page["visible_body_characters"] >= page["minimum_visible_body_characters"], page
    assert page["faq_questions"] >= page["minimum_faq_questions"], page
    assert page["visual_assets"] >= 3, page
    assert page["triple_qa_passes"] == 3, page
    assert page["layout_signature"], page
    assert page["publication_allowed"] is False, page
    layout_signatures.append(page["layout_signature"])
assert len(layout_signatures) == len(set(layout_signatures)), "Repeated completed-page layout signature"

for forbidden in ("Kattints és költözz", "Építőipar 2.0", "Az építés tudománya", "Nem érdemes másból építeni"):
    assert forbidden not in JS, f"Cross-brand phrase found: {forbidden}"

print(json.dumps({
    "canonical_pages": len(pages),
    "materialized_route_shells": len(implemented_ids),
    "content_complete_pages": len(complete),
    "route_shell_only_pages": sum(page["state"] == "ROUTE_SHELL_ONLY" for page in registry_pages),
    "nim_managed_pages": sum(page["state"] == "NIM_CONTENT_PLACEHOLDER" for page in registry_pages),
    "local_assets_checked": True,
    "external_runtime_dependencies": 0,
    "publication_allowed": False,
}, ensure_ascii=False))
