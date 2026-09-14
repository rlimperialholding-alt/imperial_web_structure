from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.checklists.service import ChecklistEngine
from app.config import Settings, get_settings
from app.operations.adapters import DirectusOperationalRecordSink, NullOperationalRecordSink
from app.process_cards.adapters import GmailApprovalNotifier, GoogleDrivePublisher
from app.process_cards.service import ProcessCardGenerator


@dataclass(slots=True)
class OperationalServices:
    process_cards: ProcessCardGenerator
    checklists: ChecklistEngine
    catalog_path: Path


def build_operational_services(settings: Settings) -> OperationalServices:
    publisher = None
    notifier = None
    service_account = settings.resolved_path(settings.google_service_account_file)
    if (
        settings.drive_publication_enabled
        and settings.process_card_drive_folder_id
        and service_account.exists()
    ):
        publisher = GoogleDrivePublisher(
            settings.google_service_account_file, settings.process_card_drive_folder_id
        )
    if (
        settings.gmail_approval_enabled
        and publisher is not None
        and settings.process_card_approver_email
        and settings.process_card_gmail_delegated_user
        and service_account.exists()
    ):
        notifier = GmailApprovalNotifier(
            settings.google_service_account_file,
            settings.process_card_gmail_delegated_user,
            settings.process_card_approver_email,
        )
    token = settings.directus_static_token.get_secret_value().strip()
    if token:
        record_sink = DirectusOperationalRecordSink(
            base_url=settings.directus_url,
            token=token,
            process_card_collection=settings.process_card_collection,
            checklist_template_collection=settings.checklist_template_collection,
            checklist_instance_collection=settings.checklist_instance_collection,
        )
    else:
        record_sink = NullOperationalRecordSink()

    checklists = ChecklistEngine(
        settings.resolved_path(settings.checklist_runtime_root),
        record_sink=record_sink,
    )
    process_cards = ProcessCardGenerator(
        settings.resolved_path(settings.process_card_runtime_root),
        settings.resolved_path(settings.process_card_publish_root),
        publisher,
        notifier,
        checklists,
        record_sink,
    )
    catalog_path = settings.resolved_path(settings.operational_catalog_file)
    if catalog_path.exists():
        process_cards.import_catalog(catalog_path, persist=False)
    return OperationalServices(process_cards, checklists, catalog_path)


@lru_cache(maxsize=1)
def get_operational_services() -> OperationalServices:
    return build_operational_services(get_settings())
