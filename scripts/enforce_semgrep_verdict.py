#!/usr/bin/env python3
"""A path-szűk Semgrep scan-lépések összesített, fail-closed enforcement kapuja.

Az ``.github/workflows/imperial-adas-semgrep.yml`` négy részscanje (platform-core
kód, platform-core Jinja-sablonok, npm projektek, minden más path) ``if:
always()`` mellett fut: mindegyik lefut akkor is, ha egy korábbi scan blokkoló
találattal vagy technikai hibával tért vissza, a saját exit kódját
``<rész>.exit`` fájlba rögzíti, és a lépés maga a scan kilépőkódjával ér véget
(az ``always()`` tehát a job-összegzést NEM zöldíti). Ez a szkript a végső,
összesített kapu:

- bármely rész JSON hiányzik, nem parse-olható, vagy nem tartalmaz
  ``results`` listát (hiányos bizonyíték) → FAIL;
- bármely rész ``errors`` mezője hiányzik, nem lista típusú, vagy nem üres
  (belső Semgrep hiba) → FAIL;
- bármely rögzített scan exit kód nem 0 (blokkoló találat vagy technikai
  hiba) → FAIL;
- bármely rész CRITICAL/HIGH/ERROR severity találatot tartalmaz → FAIL;
- az egyesített ``semgrep.json`` bizonyíték hiánya (merge-hiba) → FAIL;
- a WARNING/INFO szintű, dokumentált találatok nem blokkolnak.

Csak olvas; a kimenete egy emberi összegzés (secretmentes).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PARTS = (
    "semgrep-platform-core.json",
    "semgrep-platform-core-templates.json",
    "semgrep-npm.json",
    "semgrep-rest.json",
)
EXITS = (
    "semgrep-platform-core.exit",
    "semgrep-platform-core-templates.exit",
    "semgrep-npm.exit",
    "semgrep-rest.exit",
)
MERGED = "semgrep.json"
BLOCKING_SEVERITIES = {"CRITICAL", "HIGH", "ERROR"}


def _severity(finding: dict[str, Any]) -> str:
    severity = finding.get("severity")
    extra = finding.get("extra")
    if isinstance(extra, dict) and extra.get("severity"):
        severity = extra["severity"]
    return str(severity or "").upper()


def main() -> int:
    failures: list[str] = []
    blocking: list[str] = []
    for part, exit_file in zip(PARTS, EXITS):
        part_path = Path(part)
        if not part_path.is_file():
            failures.append(f"missing scan evidence: {part}")
        else:
            try:
                data = json.loads(part_path.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError as error:
                failures.append(f"unparsable scan evidence: {part} ({error})")
                data = None
            if isinstance(data, dict):
                results = data.get("results")
                if not isinstance(results, list):
                    failures.append(f"incomplete scan evidence: {part} (missing results list)")
                    results = []
                if "errors" not in data:
                    failures.append(f"incomplete scan evidence: {part} (missing errors list)")
                elif not isinstance(data["errors"], list):
                    failures.append(f"invalid scan evidence: {part} (errors is not a list)")
                elif data["errors"]:
                    failures.append(
                        f"scan evidence {part} contains internal errors "
                        f"({len(data['errors'])} error(s))"
                    )
                for index, finding in enumerate(results):
                    if isinstance(finding, dict) and _severity(finding) in BLOCKING_SEVERITIES:
                        blocking.append(
                            f"{part}: {_severity(finding)} finding "
                            f"{finding.get('check_id', '?')} (result #{index})"
                        )
            elif data is not None:
                failures.append(f"scan evidence {part} is not a JSON object")
        exit_path = Path(exit_file)
        if not exit_path.is_file():
            failures.append(f"missing scan exit evidence: {exit_file}")
            continue
        raw = exit_path.read_text(encoding="utf-8", errors="replace").strip()
        try:
            code = int(raw)
        except ValueError:
            failures.append(f"unparsable scan exit evidence: {exit_file} ({raw!r})")
            continue
        if code != 0:
            failures.append(f"scan exited nonzero: {part} (exit {code})")
    if not Path(MERGED).is_file():
        failures.append(f"missing merged evidence: {MERGED}")
    if failures or blocking:
        for line in failures:
            print(f"enforce_semgrep_verdict: FAIL - {line}", file=sys.stderr)
        for line in blocking:
            print(f"enforce_semgrep_verdict: FAIL - blocking {line}", file=sys.stderr)
        return 1
    print("enforce_semgrep_verdict: PASS - all scans complete, exit 0, no blocking findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
