from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.process_cards.service import ProcessCardGenerator

root = Path("runtime/demo_process_cards")
service = ProcessCardGenerator(root, Path("runtime/demo_published"))
payload = json.loads(Path("examples/process_cards/project_start.json").read_text(encoding="utf-8"))
service.ingest(payload)
result = service.generate(payload["process_key"], force=True)
approved = service.approve(payload["process_key"], result["card"]["version"], "Ügyvezető - demo")
print(json.dumps({"generated": result, "approved": approved}, ensure_ascii=False, indent=2))
