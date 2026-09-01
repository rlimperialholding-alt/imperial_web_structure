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

The driver deliberately stays on the pinned package's own public
``scan.scan_file`` path: one serial scan per file, no private package API
(no ``_get_lines_from_file`` / ``_process_line_based_plugins``), no internal
process pool and no line renumbering, so findings keep the exact line
numbers of the serial CLI scan. Parallelism is bounded at the caller level
only (one driver subprocess per candidate chunk in ``check_secret_baseline``);
within one driver process nothing is forked, so no orphan child or nested
process-pool explosion can occur under pytest/Windows. The only package
logger mutation is the INFO level the per-file accounting requires: it is
applied inside ``main`` and restored to the exact previous level in a
``finally``, so the logger state is byte-identical after both the success
path and the exception path -- importing this module mutates nothing.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from detect_secrets.core import scan
from detect_secrets.core.log import log
from detect_secrets.settings import default_settings, get_plugins


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
    # The per-file ``Checking file:`` accounting travels on the package
    # logger's INFO channel, so the level is raised for the scan and
    # restored to the exact previous level in the ``finally`` -- on the
    # success path and on the exception path alike. Importing this module
    # mutates nothing, so an in-process caller always finds the pristine
    # logger state afterwards.
    previous_level = log.level
    log.set_debug_level(1)
    try:
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
    finally:
        log.setLevel(previous_level)


if __name__ == "__main__":
    raise SystemExit(main())
