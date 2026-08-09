from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
registry = json.loads((ROOT / "data" / "completion-registry.json").read_text(encoding="utf-8"))
scoped = [page for page in registry["pages"] if page["state"] != "NIM_CONTENT_PLACEHOLDER"]
incomplete = [page for page in scoped if page["state"] != "COMPLETE_REVIEW_REQUIRED"]

if incomplete:
    preview = ", ".join(f'{page["page_id"]}:{page["state"]}' for page in incomplete[:12])
    raise SystemExit(
        f"RELEASE BLOCKED: {len(incomplete)}/{len(scoped)} scoped pages are incomplete. {preview}"
    )

assert all(page["publication_allowed"] is False for page in scoped)
print(f"CONTENT BUILD COMPLETE, OWNER REVIEW STILL REQUIRED: {len(scoped)} pages")
