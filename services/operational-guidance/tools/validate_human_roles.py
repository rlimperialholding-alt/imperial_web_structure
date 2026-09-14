#!/usr/bin/env python3
"""Validate the canonical five internal human roles in runtime-owned fields."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ALLOWED = {
    "Ügyvezető",
    "Marketinges",
    "Értékesítő",
    "Pénzügyes",
    "Projektmenedzser",
}


def strings(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    return set()


def main() -> int:
    catalog_path = Path(__file__).resolve().parents[1] / "config" / "operational-process-catalog-v1.0.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    declared = set(catalog.get("real_roles", []))
    if declared != ALLOWED:
        print(f"Declared real_roles mismatch: expected={sorted(ALLOWED)!r}, got={sorted(declared)!r}")
        return 1

    runtime_roles: set[str] = set()
    for process in catalog.get("processes", []):
        runtime_roles |= strings(process.get("source_role"))
        runtime_roles |= strings(process.get("approval_role"))
        runtime_roles |= strings(process.get("participant_roles"))
    for checklist in catalog.get("checklist_templates", []):
        runtime_roles |= strings(checklist.get("primary_role"))
        runtime_roles |= strings(checklist.get("participant_roles"))

    unknown = runtime_roles - ALLOWED
    if unknown:
        print(f"Unknown internal runtime roles found: {sorted(unknown)!r}")
        return 1

    missing = ALLOWED - runtime_roles
    if missing:
        print(f"Canonical roles are declared but unused: {sorted(missing)!r}")
        return 1

    processes = catalog.get("processes", [])
    checklists = catalog.get("checklist_templates", [])
    if len(processes) != 99 or len(checklists) != 99:
        print(f"Catalog cardinality mismatch: processes={len(processes)}, checklists={len(checklists)}")
        return 1

    print(
        "Internal human-role boundary OK: exactly five roles; "
        f"processes={len(processes)}; checklists={len(checklists)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
