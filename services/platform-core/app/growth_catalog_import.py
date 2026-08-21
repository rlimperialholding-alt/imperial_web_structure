from __future__ import annotations

import argparse
import json

from .database import SessionLocal
from .growth_ops.catalog import import_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the canonical source route catalog.")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument(
        "--manifest",
        default="/app/config/growth/source-ledger-manifest.json",
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        revision = import_snapshot(
            db,
            snapshot_path=args.snapshot,
            manifest_path=args.manifest,
        )
        print(
            json.dumps(
                {
                    "revision_id": revision.revision_id,
                    "catalog_sha256": revision.catalog_sha256,
                    "route_count": revision.route_count,
                    "status": revision.status,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
