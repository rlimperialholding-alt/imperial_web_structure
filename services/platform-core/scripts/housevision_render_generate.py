from __future__ import annotations

import json
import sys

from app.database import SessionLocal
from app.services.housevision_render_bridge import generate_typehouse_renders


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    with SessionLocal() as db:
        result = generate_typehouse_renders(db, sys.argv[1], sys.argv[2])
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
