import json
from pathlib import Path

from app.process_cards.domain import RealRole, resolve_real_role

CATALOG = Path("config/operational-process-catalog-v1.0.json")


def test_catalog_has_99_linked_processes_and_checklists():
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    processes = payload["processes"]
    templates = payload["checklist_templates"]
    assert len(processes) == 99
    assert len(templates) == 99
    assert len({item["process_key"] for item in processes}) == 99
    assert len({item["template_id"] for item in templates}) == 99
    template_by_process = {item["process_key"]: item for item in templates}
    for process in processes:
        assert process["checklist_required"] is True
        assert process["process_key"] in template_by_process
        assert process["checklist_template_id"] == template_by_process[process["process_key"]]["template_id"]
        assert process["gate_id"] == template_by_process[process["process_key"]]["gate_id"]


def test_catalog_uses_only_five_internal_roles():
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    allowed = {role.value for role in RealRole}
    assert set(payload["real_roles"]) == allowed
    assert {item["source_role"] for item in payload["processes"]} <= allowed
    assert {item["primary_role"] for item in payload["checklist_templates"]} <= allowed


def test_external_only_role_is_mapped_to_real_internal_owner():
    assert resolve_real_role("Alvállalkozó (auditor)", family="AUD") == RealRole.UGYVEZETO
