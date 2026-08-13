#!/usr/bin/env python3
"""Run all Everyday Homes browser gates in bounded route batches."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa"
NODE = os.environ.get("EVERYDAY_NODE", "node")
BASE_ENV = {
    **os.environ,
    "EVERYDAY_PREVIEW_ROOT": str(ROOT),
}

RICH = [
    "/", "/otthonvalaszto", "/keretbol-otthon", "/igy-lesz-egyszeru", "/kozelrol",
    "/elso-lepesek", "/a-fontos-kerdesek", "/kezdjuk-egyutt",
    "/kell-egy-otthon-mindenkinek", "/garanciak-es-utogondozas",
    "/elso-lepesek-hirlevel", "/karrier", "/sajto", "/elso-sajat-otthon",
    "/most-leszunk-csalad", "/tobb-hely-a-csaladnak", "/otthon-es-munka",
    "/kisebb-haz-konnyebb-elet", "/ket-generacio-egy-otthon",
    "/kesobb-bovitheto-otthon", "/szamolok/hazkoltseg",
]

SERVICE = [
    "/mi-intezzuk/tervezes", "/mi-intezzuk/general-kivitelezes",
    "/mi-intezzuk/finanszirozas", "/mi-intezzuk/felujitas", "/mi-intezzuk/tetoter",
    "/mi-intezzuk/pincebol-lakas", "/mi-intezzuk/telek-ellenorzes",
    "/mi-intezzuk/szemelyes-hazajanlas", "/biztonsag/vallalasaink",
    "/biztonsag/atlathato-ar", "/biztonsag/szerzodes", "/biztonsag/projektkovetes",
    "/biztonsag/atadas-utan", "/elso-lepesek/mekkora-haz",
    "/elso-lepesek/jo-alaprajz", "/elso-lepesek/telekvasarlas",
    "/elso-lepesek/teljes-koltseg", "/elso-lepesek/technologia-valasztas",
    "/elso-lepesek/finanszirozas-menete", "/elso-lepesek/tarthato-utemterv",
    "/elso-lepesek/energia", "/kozelrol/elkeszult-otthonok",
    "/kozelrol/csaladok-tortenetei", "/adatkezeles", "/impresszum", "/sutik",
    "/akadalymentesseg",
]


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=ROOT.parents[1], env=env or BASE_ENV, check=True)


def merge(output: Path, expected: int, parts: list[Path]) -> None:
    run([sys.executable, str(QA / "merge_render_reports.py"), str(output), str(expected), *map(str, parts)])


def batched(script: str, routes: list[str], route_env: str, report_env: str, output: str) -> None:
    parts = []
    for index in range(0, len(routes), 3):
        part = Path(tempfile.gettempdir()) / f"everyday-{output}-{index // 3 + 1}.json"
        env = {**BASE_ENV, route_env: ",".join(routes[index:index + 3]), report_env: str(part)}
        run([NODE, str(QA / script)], env)
        parts.append(part)
    merge(QA / f"{output}-pages-report.json", len(routes), parts)


def main() -> int:
    batched("validate_rich_pages.cjs", RICH, "EVERYDAY_RICH_ROUTES", "EVERYDAY_RICH_REPORT_PATH", "rich")
    batched("validate_service_pages.cjs", SERVICE, "EVERYDAY_SERVICE_ROUTES", "EVERYDAY_SERVICE_REPORT_PATH", "service")
    run([NODE, str(QA / "validate_decision_pages.cjs")])
    run([NODE, str(QA / "validate_technology_pages.cjs")])
    print(json.dumps({"rich": 21, "service": 27, "decision": 7, "technology": 5, "viewports": 3, "checks": 180}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
