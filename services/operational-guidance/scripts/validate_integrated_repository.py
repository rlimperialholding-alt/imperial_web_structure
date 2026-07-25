from __future__ import annotations

import json
from pathlib import Path

hub_root = Path(__file__).resolve().parents[1]
repo_root = hub_root.parents[1]
required_repo = [
    ".github/workflows/quality.yml",
    ".github/workflows/live-crm-integration.yml",
    "docker-compose.github-test.yml",
    "services/itep-core/src/connectors/connector-adapter-factory.ts",
    "services/itep-core/src/api/server.ts",
    "services/itep-core/prisma/seed.mjs",
]
required_hub = [
    "app/connectors/itep.py",
    "app/api/routes/itep.py",
]
missing = [path for path in required_repo if not (repo_root / path).is_file()]
missing.extend(path for path in required_hub if not (hub_root / path).is_file())
if missing:
    raise SystemExit("Missing required files: " + ", ".join(missing))

compose = (repo_root / "docker-compose.github-test.yml").read_text(encoding="utf-8")
for token in [
    "CRM_API_BASE_URL",
    "CRM_ACCESS_TOKEN",
    "CRM_WORKSPACE_ID",
    "ITEP_IDENTITY_SHARED_SECRET",
]:
    if token not in compose:
        raise SystemExit(f"Missing required test environment token: {token}")

manifest = json.loads(
    (hub_root / "RELEASE-MANIFEST-v0.9.0-test.json").read_text(encoding="utf-8")
)
if manifest["dataPolicy"]["crm"] != "live-read-only":
    raise SystemExit("CRM must remain live-read-only")

print("Integrated repository validation passed.")
