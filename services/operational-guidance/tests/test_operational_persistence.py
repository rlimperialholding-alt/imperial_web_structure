from __future__ import annotations

from pathlib import Path
from typing import Any

from app.checklists.domain import ChecklistAnswer
from app.checklists.service import ChecklistEngine
from app.config import Settings
from app.operations.factory import build_operational_services
from app.process_cards.service import ProcessCardGenerator

CATALOG = Path("config/operational-process-catalog-v1.0.json")


class RecordingSink:
    def __init__(self) -> None:
        self.cards: list[tuple[dict[str, Any], dict[str, str]]] = []
        self.templates: list[dict[str, Any]] = []
        self.instances: list[dict[str, Any]] = []

    def upsert_process_card(self, payload: dict[str, Any], artifacts: dict[str, str]) -> None:
        self.cards.append((payload, artifacts))

    def upsert_checklist_template(self, payload: dict[str, Any]) -> None:
        self.templates.append(payload)

    def upsert_checklist_instance(self, payload: dict[str, Any]) -> None:
        self.instances.append(payload)


def test_process_cards_and_checklists_share_one_record_sink(tmp_path: Path) -> None:
    sink = RecordingSink()
    checklists = ChecklistEngine(tmp_path / "checklists", record_sink=sink)
    generator = ProcessCardGenerator(
        tmp_path / "process_cards",
        tmp_path / "published",
        checklist_engine=checklists,
        record_sink=sink,
    )

    imported = generator.import_catalog(CATALOG)
    assert imported["total_processes"] == 99
    assert imported["total_checklists"] == 99
    assert len(sink.templates) == 99

    generated = generator.generate("SAL-001")
    assert generated["card"]["checklist_template_id"] == "CHK-SAL-001"
    assert sink.cards[-1][0]["process_key"] == "SAL-001"
    generator.approve("SAL-001", 1, "Ügyvezető")

    instance = checklists.start_instance("SAL-001", "LEAD-77", "Teszt értékesítő")
    first = instance.items[0]
    checklists.answer_item(
        instance.instance_id,
        first.item_id,
        ChecklistAnswer.NO,
        answered_by="Teszt értékesítő",
        note="Hiányzó kötelező adat.",
        action_owner_role="Értékesítő",
        action_due_date="2026-08-01",
    )
    assert sink.instances[-1]["status"] == "hold"
    assert sink.instances[-1]["gate_id"] == generated["card"]["gate_id"]


def test_factory_wires_one_shared_sink_for_both_engines(tmp_path: Path) -> None:
    settings = Settings(
        directus_static_token="",
        google_service_account_file=str(tmp_path / "missing-service-account.json"),
        process_card_runtime_root=str(tmp_path / "process_cards"),
        process_card_publish_root=str(tmp_path / "published"),
        checklist_runtime_root=str(tmp_path / "checklists"),
        operational_catalog_file=str(CATALOG.resolve()),
    )
    services = build_operational_services(settings)
    assert services.process_cards.checklist_engine is services.checklists
    assert services.process_cards.record_sink is services.checklists.record_sink
    assert len(services.checklists.store.list_templates()) == 99


def test_directus_sink_uses_versioned_record_keys(monkeypatch) -> None:
    from app.operations.adapters import DirectusOperationalRecordSink

    calls: list[tuple[str, dict[str, str | int], dict[str, Any]]] = []

    def capture(self, collection, filters, payload):
        calls.append((collection, filters, payload))

    monkeypatch.setattr(DirectusOperationalRecordSink, "_upsert", capture)
    sink = DirectusOperationalRecordSink("https://directus.test", "token")

    sink.upsert_process_card(
        {
            "process_key": "PRJ-003",
            "version": 2,
            "role": "Projektmenedzser",
            "source_checksum": "abc",
            "status": "draft",
        },
        {"process_card_pdf": "card.pdf"},
    )
    sink.upsert_checklist_template(
        {
            "template_id": "CHK-PRJ-003",
            "version": "1.1",
            "process_key": "PRJ-003",
        }
    )

    assert calls[0][1] == {"record_key": "PRJ-003:v002"}
    assert calls[0][2]["record_key"] == "PRJ-003:v002"
    assert calls[1][1] == {"version_key": "CHK-PRJ-003:v1.1"}
    assert calls[1][2]["version_key"] == "CHK-PRJ-003:v1.1"


def test_factory_startup_does_not_write_catalog_back_to_directus(tmp_path: Path, monkeypatch) -> None:
    from app.operations.adapters import DirectusOperationalRecordSink

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Startup catalog hydration must not write back to Directus")

    monkeypatch.setattr(DirectusOperationalRecordSink, "_upsert", fail_if_called)
    settings = Settings(
        directus_url="https://directus.test",
        directus_static_token="token",
        google_service_account_file=str(tmp_path / "missing-service-account.json"),
        process_card_runtime_root=str(tmp_path / "process_cards"),
        process_card_publish_root=str(tmp_path / "published"),
        checklist_runtime_root=str(tmp_path / "checklists"),
        operational_catalog_file=str(CATALOG.resolve()),
    )
    services = build_operational_services(settings)
    assert isinstance(services.process_cards.record_sink, DirectusOperationalRecordSink)
    assert len(services.checklists.store.list_templates()) == 99
