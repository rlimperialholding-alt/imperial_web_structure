from __future__ import annotations

from app.models import ModuleBusinessRecord, ProjectRegistry
from app.services.canonical_bridge import canonical_integrity_report


def _record(record_id: str, project_id: str) -> ModuleBusinessRecord:
    return ModuleBusinessRecord(
        record_id=record_id,
        module_key="financial-control",
        record_type="Invoice",
        title=record_id,
        status="draft",
        project_id=project_id,
        amount_huf=1000,
        data_json="{}",
        created_by="finance@imperial.local",
        updated_by="finance@imperial.local",
    )


def test_integrity_report_passes_for_known_project_reference(db):
    db.add(ProjectRegistry(project_id="PRJ-INTEGRITY-1", name="Live project"))
    db.add(_record("FIN-INTEGRITY-1", "PRJ-INTEGRITY-1"))
    db.commit()

    report = canonical_integrity_report(db)

    assert report["status"] == "passed"
    assert report["missing_project_masters"] == 0
    assert report["finance"]["linked_to_project"] >= 1


def test_integrity_report_fails_closed_for_orphan_project_reference(db):
    db.add(_record("FIN-INTEGRITY-ORPHAN", "PRJ-NOT-FOUND"))
    db.commit()

    report = canonical_integrity_report(db)

    assert report["status"] == "attention_required"
    assert report["missing_project_masters"] == 1
    assert report["missing"][0]["record_id"] == "FIN-INTEGRITY-ORPHAN"
