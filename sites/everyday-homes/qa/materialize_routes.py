from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
PAGE_MAP = json.loads((ROOT / "data" / "page-map.json").read_text(encoding="utf-8"))

for group in PAGE_MAP["groups"]:
    for _, route, _ in group["pages"]:
        if route == "/":
            continue
        target = ROOT / route.removeprefix("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(INDEX, target)

print(f"Materialized {PAGE_MAP['canonical_page_count'] - 1} route entry points")
