from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
from PIL import Image

from app.checklists.service import ChecklistEngine
from app.process_cards.service import ProcessCardGenerator

CATALOG = Path("config/operational-process-catalog-v1.0.json")


def inspect_pdf(path: Path) -> dict[str, object]:
    document = fitz.open(path)
    text = "\n".join(page.get_text() for page in document)
    return {"pages": document.page_count, "text_length": len(text.strip())}


def inspect_png(path: Path) -> dict[str, int]:
    with Image.open(path) as image:
        return {"width": image.width, "height": image.height}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and inspect all operational guidance artifacts.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)

    checklists = ChecklistEngine(args.output / "checklists")
    cards = ProcessCardGenerator(
        args.output / "process_cards",
        args.output / "published",
        checklist_engine=checklists,
    )
    imported = cards.import_catalog(CATALOG)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    issues: list[dict[str, str]] = []
    inspected = 0

    for process in catalog["processes"]:
        process_key = str(process["process_key"])
        result = cards.generate(process_key, force=True)
        for artifact_key in (
            "process_card_pdf",
            "checklist_pdf",
            "process_card_png",
            "checklist_png",
        ):
            path = Path(result["artifacts"][artifact_key])
            if not path.exists() or path.stat().st_size == 0:
                issues.append({"process_key": process_key, "artifact": artifact_key, "issue": "missing_or_empty"})
                continue
            if path.suffix == ".pdf":
                metadata = inspect_pdf(path)
                if metadata["pages"] != 1 or metadata["text_length"] < 120:
                    issues.append({"process_key": process_key, "artifact": artifact_key, "issue": str(metadata)})
            else:
                metadata = inspect_png(path)
                if metadata["width"] < 1000 or metadata["height"] < 1000:
                    issues.append({"process_key": process_key, "artifact": artifact_key, "issue": str(metadata)})
            inspected += 1

    report = {
        "catalog": imported,
        "processes": len(catalog["processes"]),
        "checklist_templates": len(catalog["checklist_templates"]),
        "artifacts_inspected": inspected,
        "issues": issues,
        "passed": not issues,
    }
    report_path = args.output / "operational-guidance-qa-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not issues else 1)


if __name__ == "__main__":
    main()
