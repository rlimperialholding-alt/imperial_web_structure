from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.operations.factory import build_operational_services


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import the canonical Process Card and checklist catalog into the runtime stores."
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Optional catalog JSON. Defaults to OPERATIONAL_CATALOG_FILE.",
    )
    parser.add_argument(
        "--generate-all",
        action="store_true",
        help="Generate all 99 Process Card + checklist bundles after import.",
    )
    args = parser.parse_args()

    settings = get_settings()
    services = build_operational_services(settings)
    catalog = args.catalog or services.catalog_path
    result = services.process_cards.import_catalog(catalog, persist=False)
    output: dict[str, object] = {"catalog": str(catalog), "import": result}

    if args.generate_all:
        generated = []
        payload = json.loads(catalog.read_text(encoding="utf-8"))
        for process in payload.get("processes", []):
            generated.append(
                services.process_cards.generate(str(process["process_key"]), force=True)
            )
        output["generated"] = len(generated)

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
