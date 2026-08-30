from __future__ import annotations

import argparse
import json

from app.database import SessionLocal
from app.land_acquisition.service import ensure_public_html_land_routes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan or idempotently upsert the seven public land category routes."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the plan. Without this flag the command is a read-only dry run.",
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        result = ensure_public_html_land_routes(db, dry_run=not args.apply)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if (result["dry_run"] or result["readback_pass"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
