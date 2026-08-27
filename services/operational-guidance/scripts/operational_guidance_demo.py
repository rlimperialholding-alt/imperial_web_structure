from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.checklists.domain import ChecklistAnswer
from app.checklists.service import ChecklistEngine
from app.process_cards.service import ProcessCardGenerator

CATALOG = Path("config/operational-process-catalog-v1.0.json")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="imperial-operational-guidance-") as tmp:
        root = Path(tmp)
        checklists = ChecklistEngine(root / "checklists")
        cards = ProcessCardGenerator(
            root / "process_cards",
            root / "published",
            checklist_engine=checklists,
        )
        imported = cards.import_catalog(CATALOG)
        generated = cards.generate("SAL-001")
        approved = cards.approve("SAL-001", 1, "Ügyvezető")

        instance = checklists.start_instance(
            "SAL-001",
            object_id="LEAD-DEMO-001",
            created_by="Értékesítő",
            metadata={"demo": True},
        )
        for item in instance.items:
            checklists.answer_item(
                instance.instance_id,
                item.item_id,
                ChecklistAnswer.YES,
                answered_by="Értékesítő",
                evidence_ids=["EVID-DEMO-001"],
            )
        checklists.add_evidence(instance.instance_id, ["EVID-DEMO-001"])
        submitted = checklists.submit(instance.instance_id, "Értékesítő")
        closed = checklists.approve_instance(instance.instance_id, "Ügyvezető")
        gate = checklists.gate_status(instance.instance_id)

        print(
            json.dumps(
                {
                    "imported": imported,
                    "process_card": {
                        "process_key": generated["card"]["process_key"],
                        "version": generated["card"]["version"],
                        "approved_status": approved["card"]["status"],
                        "artifacts": generated["artifacts"],
                    },
                    "checklist": {
                        "instance_id": instance.instance_id,
                        "submitted_status": submitted["instance"]["status"],
                        "closed_status": closed["instance"]["status"],
                        "gate": gate,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
