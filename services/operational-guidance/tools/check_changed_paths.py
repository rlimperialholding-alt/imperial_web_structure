#!/usr/bin/env python3
"""Fail a PR when this integration branch edits paths owned by other workstreams."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ALLOWED_EXACT = {
    ".github/workflows/live-crm-integration.yml",
    ".github/workflows/operational-guidance-ci.yml",
    ".github/workflows/quality.yml",
    "docker-compose.github-test.yml",
    "docs/integrations/operational-guidance-v0.8.1.md",
}
ALLOWED_PREFIXES = (
    "services/imperial-sales-crm/",
    "services/itep-core/",
    "services/operational-guidance/",
)


def changed_paths(base: str, head: str) -> list[str]:
    command = ["git", "diff", "--name-only", f"{base}...{head}"]
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def is_allowed(path: str) -> bool:
    normalized = Path(path).as_posix()
    return normalized in ALLOWED_EXACT or normalized.startswith(ALLOWED_PREFIXES)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()

    paths = changed_paths(args.base, args.head)
    blocked = [path for path in paths if not is_allowed(path)]
    if blocked:
        print("Integrated Hub/ITEP/CRM branch crossed ownership boundaries:")
        for path in blocked:
            print(f" - {path}")
        print("Move unrelated changes to their owning branch before merging.")
        return 1

    print(f"Boundary check passed for {len(paths)} changed path(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
