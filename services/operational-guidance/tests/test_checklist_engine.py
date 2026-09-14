import json
from pathlib import Path

import pytest

from app.checklists.domain import ChecklistAnswer
from app.checklists.service import ChecklistEngine, ChecklistValidationError
from app.process_cards.service import ProcessCardGenerator

CATALOG = Path("config/operational-process-catalog-v1.0.json")


def test_checklist_hold_evidence_submit_and_approval(tmp_path: Path):
    engine = ChecklistEngine(tmp_path / "checklists")
    imported = engine.import_catalog(CATALOG)
    assert imported["total"] == 99
    engine.approve_template("CHK-SAL-001", "1.0", "Ügyvezető")
    instance = engine.start_instance("SAL-001", "LEAD-42", "Teszt értékesítő")
    first = instance.items[0]

    with pytest.raises(ChecklistValidationError):
        engine.answer_item(
            instance.instance_id,
            first.item_id,
            ChecklistAnswer.NO,
            answered_by="Teszt értékesítő",
        )

    held = engine.answer_item(
        instance.instance_id,
        first.item_id,
        ChecklistAnswer.NO,
        answered_by="Teszt értékesítő",
        note="Hiányzik egy kötelező adat.",
        action_owner_role="Értékesítő",
        action_due_date="2026-08-01",
    )
    assert held.status.value == "hold"
    assert engine.gate_status(instance.instance_id)["can_proceed"] is False

    engine.answer_item(
        instance.instance_id,
        first.item_id,
        ChecklistAnswer.YES,
        answered_by="Teszt értékesítő",
        evidence_ids=["EVID-1"],
    )
    current = engine.store.load_instance(instance.instance_id)
    for item in current.items[1:]:
        engine.answer_item(
            instance.instance_id,
            item.item_id,
            ChecklistAnswer.YES,
            answered_by="Teszt értékesítő",
            evidence_ids=["EVID-1"],
        )
    engine.add_evidence(instance.instance_id, ["EVID-1"])
    submitted = engine.submit(instance.instance_id, "Teszt értékesítő")
    assert submitted["instance"]["status"] == "ready_for_approval"
    assert Path(submitted["artifacts"]["pdf"]).exists()
    approved = engine.approve_instance(instance.instance_id, "Ügyvezető")
    assert approved["instance"]["status"] == "closed"
    assert engine.gate_status(instance.instance_id)["can_proceed"] is True


def test_process_card_bundle_contains_linked_checklist_and_reacts_to_rule_change(tmp_path: Path):
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    engine = ChecklistEngine(tmp_path / "checklists")
    generator = ProcessCardGenerator(
        tmp_path / "process_cards",
        tmp_path / "published",
        checklist_engine=engine,
    )
    imported = generator.import_catalog(catalog)
    assert imported["total_processes"] == 99
    assert imported["total_checklists"] == 99

    first = generator.generate("PRJ-003")
    assert first["card"]["checklist_template_id"] == "CHK-PRJ-003"
    assert Path(first["artifacts"]["process_card_pdf"]).exists()
    assert Path(first["artifacts"]["checklist_pdf"]).exists()
    assert Path(first["artifacts"]["bundle_json"]).exists()

    unchanged = generator.generate("PRJ-003")
    assert unchanged["changed"] is False

    template = engine.template_for_process("PRJ-003")
    assert template is not None
    template.items[0].text += " Kiegészített szabály."
    engine.store.save_template(template)
    changed = generator.generate("PRJ-003")
    assert changed["changed"] is True
    assert changed["card"]["version"] == 2


def test_runtime_uses_last_approved_template_until_new_version_is_approved(tmp_path: Path):
    engine = ChecklistEngine(tmp_path / "checklists")
    engine.import_catalog(CATALOG)

    with pytest.raises(ChecklistValidationError, match="Nincs jóváhagyott"):
        engine.start_instance("SAL-001", "LEAD-UNAPPROVED", "Értékesítő")

    engine.approve_template("CHK-SAL-001", "1.0", "Ügyvezető")
    new_template = engine.store.load_template("CHK-SAL-001", "1.0")
    new_template.version = "1.10"
    new_template.status = "uat"
    new_template.items[0].text += " Új, még nem jóváhagyott szabály."
    new_template.checksum = new_template.content_checksum()
    engine.store.save_template(new_template)

    instance = engine.start_instance("SAL-001", "LEAD-ACTIVE", "Értékesítő")
    assert instance.template_version == "1.0"

    engine.approve_template("CHK-SAL-001", "1.10", "Ügyvezető")
    next_instance = engine.start_instance("SAL-001", "LEAD-NEW", "Értékesítő")
    assert next_instance.template_version == "1.10"


def test_checklist_start_is_idempotent(tmp_path: Path):
    engine = ChecklistEngine(tmp_path / "checklists")
    engine.import_catalog(CATALOG)
    engine.approve_template("CHK-SAL-001", "1.0", "Ügyvezető")

    first = engine.start_instance(
        "SAL-001",
        "LEAD-IDEMPOTENT",
        "Értékesítő",
        idempotency_key="lead-idempotency-key-1",
    )
    second = engine.start_instance(
        "SAL-001",
        "LEAD-IDEMPOTENT",
        "Értékesítő",
        idempotency_key="lead-idempotency-key-1",
    )

    assert first.instance_id == second.instance_id
    assert len(list(engine.store.instances_dir.glob("*.json"))) == 1


def test_idempotency_key_cannot_be_reused_for_different_request(tmp_path: Path):
    engine = ChecklistEngine(tmp_path / "checklists")
    engine.import_catalog(CATALOG)
    engine.approve_template("CHK-SAL-001", "1.0", "Ügyvezető")
    engine.start_instance(
        "SAL-001",
        "LEAD-A",
        "Értékesítő",
        idempotency_key="same-key",
    )

    with pytest.raises(ChecklistValidationError, match="más kéréshez"):
        engine.start_instance(
            "SAL-001",
            "LEAD-B",
            "Értékesítő",
            idempotency_key="same-key",
        )
