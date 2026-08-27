"""Pinned detect-secrets scan worker for ``check_secret_baseline.py``.

Single-purpose subprocess driver. It reads repo-relative candidate paths from
stdin, scans each with the pinned package's own ``scan.scan_file`` (the exact
code path the package CLI pool scan uses per file), and prints one
deterministic JSON document to stdout. The package's INFO log -- including one
``Checking file: <path>`` line for every file the scanner actually opens -- is
written to stderr; the caller parses those lines as the per-file coverage
accounting, so a file the scanner silently skips (any unmodeled filename
filter, a locked file, a decode surprise) can never disappear unnoticed.

Determinism contract:

* the ``default_settings()`` context configures exactly the built-in plugin
  and filter set of the pinned CLI defaults;
* files are scanned in the order given on stdin, and findings are deduplicated
  per file on ``(type, hashed_secret)`` keeping the lowest line number, so the
  emitted document is byte-identical on every host;
* the forced UTF-8 environment (set by the caller) makes file decoding and
  stdio encoding platform-independent.

This script contains no secret material and is itself a tracked candidate of
the very scan it drives; the caller's fail-closed coverage check applies to it
exactly like to every other file.
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
    """Scan one file and keep the lowest line number per (type, fingerprint)."""
    findings: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in scan.scan_file(filename):
        entry = candidate.json()
        key = (
            str(entry.get("type", "")),
            str(entry.get("hashed_secret", "")),
        )
        previous = findings.get(key)
        if previous is None or _line_number(entry) < _line_number(previous):
            findings[key] = entry
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
