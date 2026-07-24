from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "app", ROOT / "scripts", ROOT / "tests"]


def main() -> int:
    failures: list[str] = []
    checked = 0
    for root in TARGETS:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            checked += 1
            try:
                source = path.read_text(encoding="utf-8")
                ast.parse(source, filename=str(path))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{path.relative_to(ROOT)}: {exc}")
    for path in sorted((ROOT / "n8n").glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{path.relative_to(ROOT)}: {exc}")
    payload = {"status": "PASS" if not failures else "FAIL", "checked_python_files": checked, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
