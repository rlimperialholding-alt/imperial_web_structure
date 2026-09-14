from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.models import ProjectRegistry, TaskRecord, WorkspaceDocument
from app.services.canonical_documents import (
    canonical_template_catalog,
    canonical_template_status,
    instantiate_canonical_template,
    list_canonical_templates,
)


def test_drive_canonical_catalog_is_complete_and_verified():
    rows = canonical_template_catalog()
    status = canonical_template_status()
    assert len(rows) == 86
    assert status == {
        "healthy": True,
        "template_count": 86,
        "verified_count": 86,
        "category_count": 18,
        "folder_drive_id": "1WDIvn93b-3aBNtGllN2npdtpmL21ibNi",
        "registry_drive_file_id": "1-UE60l3OBUSt9qxlRgyIW9ShOUc2WqZtVYAQIU9TVrQ",
        "captured_at": "2026-08-01",
    }
    assert len({row["template_id"] for row in rows}) == 86
    assert all(row["source_verified"] and len(row["sha256"]) == 64 for row in rows)
    assert {row["tier"] for row in rows} == {"A", "B", "C"}


def test_catalog_is_filtered_by_operational_role():
    assert len(list_canonical_templates(role="platform-admin")) == 86
    finance = list_canonical_templates(role="finance")
    assert finance
    assert {row["category"] for row in finance} <= {"FIN", "CLOSE", "PROC"}
    pm = list_canonical_templates(role="project-manager")
    assert any(row["template_id"] == "TPL-OPS-019" for row in pm)
    assert any(row["template_id"] == "TPL-CARE-001" for row in pm)
    assert not any(row["category"] == "HRA" for row in pm)


def add_test_project(db):
    db.add(ProjectRegistry(project_id="IMP-GOD-014", name="Göd tesztprojekt", status="active"))
    db.commit()


def test_event_document_creates_docx_record_and_workflow_cards(db):
    add_test_project(db)
    result = instantiate_canonical_template(
        db,
        template_id="TPL-OPS-003",
        role="project-manager",
        actor="project-manager@imperial.local",
        owner="project-manager@imperial.local",
        project_id="IMP-GOD-014",
        related_object_id="CHANGE-TEST-001",
        trigger_reason="Ügyfél által kért műszaki változtatás",
        facts="A kérés a jóváhagyott műszaki tartalmat érinti.",
        decision="Árazás és határidőhatás vizsgálata szükséges.",
        actions="ChangeControl döntési kapu megnyitása.",
        evidence_ids="EVIDENCE-TEST-001",
        due_at="2026-08-15",
    )
    document = result["document"]
    assert document.source_system == "canonical_document_generator"
    assert document.drive_file_id == result["template"]["id"]
    metadata = json.loads(document.metadata_json)
    assert metadata["template_id"] == "TPL-OPS-003"
    assert metadata["canonical_source_immutable"] is True
    assert metadata["template_source_sha256"] == result["template"]["sha256"]
    artifact = Path(metadata["local_path"])
    assert artifact.exists() and artifact.suffix == ".docx"
    assert len(metadata["artifact_sha256"]) == 64
    tasks = db.scalars(select(TaskRecord).where(TaskRecord.source_event_id == document.document_id)).all()
    assert len(tasks) == 3
    assert {task.status for task in tasks} == {"open"}


def test_event_document_rejects_duplicate_primary_record(db):
    add_test_project(db)
    kwargs = dict(
        template_id="TPL-QA-001",
        role="project-manager",
        actor="project-manager@imperial.local",
        owner="project-manager@imperial.local",
        project_id="IMP-GOD-014",
        related_object_id="RFI-TEST-001",
        trigger_reason="Műszaki kérdés",
    )
    instantiate_canonical_template(db, **kwargs)
    try:
        instantiate_canonical_template(db, **kwargs)
    except ValueError as exc:
        assert "elsődleges irat" in str(exc)
    else:
        raise AssertionError("A duplikált elsődleges iratot a rendszer nem tiltotta le.")


def test_template_ui_and_download(logged_in_client, db):
    add_test_project(db)
    catalog = logged_in_client.get("/documents/templates")
    assert catalog.status_code == 200
    assert "86" in catalog.text
    assert "TPL-OPS-019" in catalog.text
    detail = logged_in_client.get("/documents/templates/TPL-OPS-019")
    assert detail.status_code == 200
    created = logged_in_client.post(
        "/documents/templates/TPL-OPS-019/instantiate",
        data={"project_id": "IMP-GOD-014", "owner": "project-manager@imperial.local", "facts": "Projektindítási teszt."},
        follow_redirects=False,
    )
    assert created.status_code == 303
    document = db.scalar(select(WorkspaceDocument).where(WorkspaceDocument.source_system == "canonical_document_generator"))
    assert document is not None
    download = logged_in_client.get(f"/documents/files/{document.document_id}")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument")
