#!/usr/bin/env python3
"""Merge route-batched Playwright reports without weakening any check."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 4:
        raise SystemExit("Usage: merge_render_reports.py <output> <expected-route-count> <report> [...]")

    output = Path(sys.argv[1])
    expected = int(sys.argv[2])
    inputs = [Path(value) for value in sys.argv[3:]]
    checks = {}
    layouts = set()
    for path in inputs:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not report.get("passed"):
            raise SystemExit(f"Sikertelen részjelentés nem egyesíthető: {path}")
        layouts.update(report.get("layout_signatures", []))
        for check in report.get("checks", []):
            key = (check["route"], check["viewport"])
            if not check.get("passed"):
                raise SystemExit(f"Sikertelen ellenőrzés: {path}: {key}")
            checks[key] = check

    routes = {route for route, _viewport in checks}
    expected_checks = expected * 3
    if len(routes) != expected or len(checks) != expected_checks:
        raise SystemExit(
            f"Hiányos egyesített jelentés: {len(routes)}/{expected} útvonal, "
            f"{len(checks)}/{expected_checks} nézet"
        )
    if len(layouts) != expected:
        raise SystemExit(f"Nem egyedi minden oldalelrendezés: {len(layouts)}/{expected}")

    merged = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": list(checks.values()),
        "layout_signatures": sorted(layouts),
        "summary": {
            "routes": expected,
            "checks": expected_checks,
            "failures": 0,
            "unique_layouts": len(layouts),
        },
        "passed": True,
    }
    output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(merged["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
