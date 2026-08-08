from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "assets" / "site.css").read_text(encoding="utf-8")
JS = (ROOT / "assets" / "site.js").read_text(encoding="utf-8")
PAGE_MAP = json.loads((ROOT / "data" / "page-map.json").read_text(encoding="utf-8"))

assert PAGE_MAP["canonical_page_count"] == 66
assert PAGE_MAP["publication_allowed"] is False
pages = [page for group in PAGE_MAP["groups"] for page in group["pages"]]
assert len(pages) == 66, len(pages)
assert len({page[0] for page in pages}) == 66
assert len({page[1] for page in pages}) == 66

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

for forbidden in ("Kattints és költözz", "Építőipar 2.0", "Az építés tudománya", "Nem érdemes másból építeni"):
    assert forbidden not in JS, f"Cross-brand phrase found: {forbidden}"

print(json.dumps({
    "canonical_pages": len(pages),
    "implemented_page_ids": len(implemented_ids),
    "local_assets_checked": True,
    "external_runtime_dependencies": 0,
    "publication_allowed": False,
}, ensure_ascii=False))
