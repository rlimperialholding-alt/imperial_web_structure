from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
registry = json.loads((ROOT / "data" / "completion-registry.json").read_text(encoding="utf-8"))
scoped = [page for page in registry["pages"] if page["state"] != "NIM_CONTENT_PLACEHOLDER"]
incomplete = [page for page in scoped if page["state"] != "AUTOMATED_QA_PASSED_COPY_REVIEW_REQUIRED"]

if incomplete:
    preview = ", ".join(f'{page["page_id"]}:{page["state"]}' for page in incomplete[:12])
    raise SystemExit(
        f"RELEASE BLOCKED: {len(incomplete)}/{len(scoped)} scoped pages are incomplete. {preview}"
    )

assert all(page["publication_allowed"] is False for page in scoped)
assert all(page["copy_gate_state"] == "BLOCKED_MISSING_HASH_BOUND_INDEPENDENT_REVIEWS" for page in scoped)
print(f"AUTOMATED BUILD QA PASSED, INDEPENDENT COPY REVIEW AND OWNER RELEASE STILL REQUIRED: {len(scoped)} pages")
