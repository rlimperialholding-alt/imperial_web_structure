"""Fail when tracked files contain secret candidates absent from the audited baseline.

The comparison logic lives in ``reconcile_tracked_secrets`` so the platform-core
local reconciliation command reuses exactly this canonical implementation
instead of duplicating a weaker parser. Messages never contain secret material;
only tracked file paths and counts are reported.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = REPO_ROOT / ".secrets.baseline"


def _fingerprints(document: dict[str, Any]) -> set[tuple[str, str, str]]:
    fingerprints: set[tuple[str, str, str]] = set()
    for filename, findings in document.get("results", {}).items():
        for finding in findings:
            fingerprints.add(
                (
                    filename.replace("\\", "/"),
                    str(finding.get("type", "")),
                    str(finding.get("hashed_secret", "")),
                )
            )
    return fingerprints


def _live_scan() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "detect_secrets",
            "scan",
            "--no-verify",
            "--exclude-files",
            r"(^|[\\/])\.secrets\.baseline$",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )


def reconcile_tracked_secrets(baseline_path: Path) -> tuple[int, str]:
    """Reconcile an audited baseline against the live tracked-secret scan.

    Returns ``(status, message)``. Status 0: every live candidate matches the
    audited baseline (stale-only entries are reported as a documented warning,
    preserving the established gate contract). Status 1: live candidates are
    absent from the baseline (new, changed, or removed/changed baseline
    entries). Status 2: missing baseline, unparseable baseline, or scanner
    failure. Messages never contain secret material, only file paths/counts.
    """
    if not baseline_path.is_file():
        return 2, "repository baseline is missing."
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return 2, f"repository baseline is not valid JSON: {exc}"
    completed = _live_scan()
    if completed.returncode != 0:
        return 2, f"scanner exit code {completed.returncode}."
    try:
        current = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return 2, f"scanner output is not valid JSON: {exc}"
    audited = _fingerprints(baseline)
    observed = _fingerprints(current)
    additions = observed - audited
    if additions:
        locations = sorted({filename for filename, _, _ in additions})
        message = (
            f"{len(additions)} new candidate(s) in {len(locations)} tracked file(s).\n"
            + "\n".join(f"- {filename}" for filename in locations)
        )
        return 1, message
    stale = audited - observed
    suffix = f"; {len(stale)} stale baseline entry/entries" if stale else ""
    return (
        0,
        f"{len(observed)} tracked candidate(s) match the audited baseline{suffix}.",
    )


def main() -> int:
    status, message = reconcile_tracked_secrets(BASELINE_PATH)
    if status == 0:
        print(f"Secret baseline PASS: {message}")
    else:
        print(f"Secret baseline FAIL: {message}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
