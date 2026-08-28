"""Pinned detect-secrets scan worker for ``check_secret_baseline.py``.

Single-purpose subprocess driver: reads repo-relative candidate paths from
stdin, scans each with the pinned package's own ``scan.scan_file`` (the exact
code path the package CLI pool scan uses), and prints one deterministic JSON
document to stdout. The package's INFO log -- one ``Checking file: <path>``
line for every file the scanner actually opens -- goes to stderr and is
parsed by the caller as per-file coverage accounting, so a silently skipped
file can never disappear unnoticed. Determinism: ``default_settings()``
configures the pinned CLI defaults; files are scanned in stdin order and
findings deduplicated per file on ``(type, hashed_secret, line_number)`` (one
entry per reported line, never collapsed); the forced UTF-8 environment makes
decoding and stdio platform-independent. This script contains no secret
material and is itself a tracked candidate of the very scan it drives.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from detect_secrets.core import scan
from detect_secrets.core.log import log
from detect_secrets.settings import default_settings, get_plugins

log.set_debug_level(1)


def _line_number(entry: dict[str, Any]) -> int:
    """The 1-based line number of a finding; 0 when absent or malformed."""
    value = entry.get("line_number", 0) or 0
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _scan_and_dedupe(filename: str) -> list[dict[str, Any]]:
    """Scan one file; keep one entry per (type, fingerprint, line).

    Findings are never collapsed across line contexts: two occurrences of the
    same value on different lines stay distinct entries, so the caller's
    per-line classifier sees every line and fails closed on any line it
    cannot prove harmless. Identical duplicate records on the same line are
    reduced to one deterministic entry.
    """
    findings: dict[tuple[str, str, int], dict[str, Any]] = {}
    for candidate in scan.scan_file(filename):
        entry = candidate.json()
        key = (
            str(entry.get("type", "")),
            str(entry.get("hashed_secret", "")),
            _line_number(entry),
        )
        findings.setdefault(key, entry)
    return sorted(
        findings.values(),
        key=lambda entry: (
            str(entry.get("type", "")),
            str(entry.get("hashed_secret", "")),
            _line_number(entry),
        ),
    )


def main() -> int:
    filenames = [line for line in sys.stdin.read().splitlines() if line]
    results: dict[str, list[dict[str, Any]]] = {}
    with default_settings():
        if not get_plugins():
            print("tracked-secret scan driver: no plugins configured.", file=sys.stderr)
            return 2
        for filename in filenames:
            findings = _scan_and_dedupe(filename)
            if findings:
                results[filename] = findings
    print(json.dumps({"results": results}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
