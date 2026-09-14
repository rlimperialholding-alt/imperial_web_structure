from __future__ import annotations

import json
import sys

from app.database import SessionLocal
from app.services.housevision import auto_lock_geometry


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: housevision_geometry_auto.py JOB_ID ACTOR", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        row = auto_lock_geometry(db, sys.argv[1], sys.argv[2])
        result = {
            "geometry_lock_id": row.geometry_lock_id,
            "job_id": row.job_id,
            "version": row.version,
            "content_sha256": row.content_sha256,
            "mode": "SOURCE_SET_LOCK_V1",
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
