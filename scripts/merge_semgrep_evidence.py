#!/usr/bin/env python3
"""A path-szűk Semgrep scan-lépések JSON-bizonyítékainak determinisztikus egyesítése.

Az ``.github/workflows/imperial-adas-semgrep.yml`` négy, egymást kizáró
útvonalszeletet vizsgál (platform-core kód; platform-core Jinja-sablonok; a
két npm projekt; minden más), hogy a rule-kivételek csak a bizonyítottan
egyenértékű védelemmel bíró exact pathokra szűküljenek. Ez a szkript a négy
``--json`` kimenetet egy ``semgrep.json`` bizonyítékba egyesíti
(results/errors összefűzve, az első rész metaadatai megtartva) az upload
step számára.

Csak olvas és a munkakönyvtárban ír ``semgrep.json``-t; bármely rész
hiánya fail-closed (kilépés 1).
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
OUTPUT = "semgrep.json"


def main() -> int:
    merged: dict[str, Any] | None = None
    for name in PARTS:
        part_path = Path(name)
        if not part_path.is_file():
            print(f"merge_semgrep_evidence: missing scan part: {name}", file=sys.stderr)
            return 1
        # A semgrep JSON bizonyíték a talált forrássorok nyers bájtjait is
        # hordozhatja (pl. latin-1-es drive-oldal); a beolvasás ezért
        # determinisztikus U+FFFD helyettesítéssel tűri a hibás bájtokat.
        data = json.loads(part_path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, dict):
            print(f"merge_semgrep_evidence: {name} is not a JSON object", file=sys.stderr)
            return 1
        if merged is None:
            merged = data
            merged["results"] = list(data.get("results") or [])
            merged["errors"] = list(data.get("errors") or [])
        else:
            merged["results"].extend(data.get("results") or [])
            merged["errors"].extend(data.get("errors") or [])
    if merged is None:
        return 1
    Path(OUTPUT).write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    print(
        "merge_semgrep_evidence: "
        f"{len(merged['results'])} result(s), {len(merged['errors'])} error(s) merged."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
