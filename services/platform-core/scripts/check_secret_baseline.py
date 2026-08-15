"""Fail when tracked files contain secret candidates absent from the audited baseline."""

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


def main() -> int:
    if not BASELINE_PATH.is_file():
        print("Secret baseline FAIL: repository baseline is missing.")
        return 2

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    completed = subprocess.run(
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
    if completed.returncode != 0:
        print(f"Secret baseline FAIL: scanner exit code {completed.returncode}.")
        return 2

    current = json.loads(completed.stdout)
    audited = _fingerprints(baseline)
    observed = _fingerprints(current)
    additions = observed - audited
    if additions:
        locations = sorted({filename for filename, _, _ in additions})
        print(
            "Secret baseline FAIL: "
            f"{len(additions)} new candidate(s) in {len(locations)} tracked file(s)."
        )
        for filename in locations:
            print(f"- {filename}")
        return 1

    stale = audited - observed
    suffix = f"; {len(stale)} stale baseline entry/entries" if stale else ""
    print(
        "Secret baseline PASS: "
        f"{len(observed)} tracked candidate(s) match the audited baseline{suffix}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
