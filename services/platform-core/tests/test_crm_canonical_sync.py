from __future__ import annotations

import json

from sqlalchemy import func, select

from app.models import EnterpriseCanonicalRecord, ImportJob, ProjectRegistry
from app.services.crm_canonical_sync import sync_crm_canonical
from app.services.financial_allocations import allocate_financial_record

SOURCE = {
    "leads": [
        {"id": 1, "name": "Első ügyfél", "email": "elso@example.invalid", "stage": "new"},
        {"id": 2, "name": "Második ügyfél", "email": "masodik@example.invalid", "stage": "offer"},
    ],
    "customers": [
        {
            "id": "CUS-1",
            "name": "Aktív ügyfél",
            "email": "aktiv@example.invalid",
            "status": "active",
        }
    ],
    "customer_imports": [],
    "business_partners": [{"id": 8, "name": "Próba Partner Kft.", "recordStatus": "verified"}],
    "business_projects": [
        {"id": 9, "externalKey": "PRJ-9", "title": "Próba projekt", "projectStatus": "planning"}
    ],
    "projects": [],
    "contracts": [],
    "invoices": [
        {
            "id": 10,
            "invoiceNumber": "INV-10",
            "buyerName": "Aktív ügyfél",
            "grossAmount": 127000,
            "customerMatchStatus": "matched",
        }
    ],
    "cashflow": [],
    "migration_documents": [],
    "review_items": [
        {"id": 12, "summary": "H" * 700, "reasonCode": "long_source_title", "status": "open"}
    ],
    "source_records": [
        {"id": 11, "recordType": "contract", "title": "Szerződésforrás", "reviewStatus": "review"}
    ],
}


def fetch_page(entity: str, cursor: int, limit: int):
    rows = SOURCE[entity][cursor : cursor + limit]
    return {"entity": entity, "rows": rows, "nextCursor": None}


def fetch_itep_invoice_page(page: int, page_size: int):
    rows = (
        [
            {
                "id": "SRC-BILLINGO-1",
                "invoiceNumber": "BILL-1",
                "partnerName": "Szállító Kft.",
                "grossAmount": 381000,
                "paymentStatus": "UNPAID",
            }
        ]
        if page == 1
        else []
    )
    return {"items": rows, "totalPages": 1, "total": len(rows)}


def test_crm_sync_is_idempotent_and_preserves_source_types(db):
    first = sync_crm_canonical(
        db,
        actor="test@example.invalid",
        fetch_page=fetch_page,
        fetch_itep_invoice_page=fetch_itep_invoice_page,
    )

    assert first["status"] == "committed"
    assert first["inserted"] == 9
    assert first["updated"] == 0
    assert db.scalar(select(func.count(EnterpriseCanonicalRecord.id))) == 9

    contract_source = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.entity_type == "contract_source_evidence"
        )
    )
    assert contract_source is not None
    assert contract_source.target_module == "contract-generator"
    assert json.loads(contract_source.data_json)["reviewStatus"] == "review"
    review = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.entity_type == "import_review"
        )
    )
    assert len(review.canonical_name) == 500
    assert len(json.loads(review.data_json)["summary"]) == 700

    second = sync_crm_canonical(
        db,
        actor="test@example.invalid",
        fetch_page=fetch_page,
        fetch_itep_invoice_page=fetch_itep_invoice_page,
    )
    assert second["inserted"] == 0
    assert second["updated"] == 0
    assert second["unchanged"] == 9
    assert db.scalar(select(func.count(EnterpriseCanonicalRecord.id))) == 9
    assert db.scalar(select(func.count(ImportJob.id))) == 2


def test_crm_sync_updates_changed_record_without_duplicate(db):
    sync_crm_canonical(
        db,
        actor="test@example.invalid",
        fetch_page=fetch_page,
        fetch_itep_invoice_page=fetch_itep_invoice_page,
    )
    SOURCE["invoices"][0]["grossAmount"] = 254000
    try:
        result = sync_crm_canonical(
            db,
            actor="test@example.invalid",
            fetch_page=fetch_page,
            fetch_itep_invoice_page=fetch_itep_invoice_page,
        )
    finally:
        SOURCE["invoices"][0]["grossAmount"] = 127000

    assert result["updated"] == 1
    assert result["inserted"] == 0
    assert db.scalar(select(func.count(EnterpriseCanonicalRecord.id))) == 9
    invoice = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.entity_type == "supplier_invoice"
        )
    )
    assert json.loads(invoice.data_json)["grossAmount"] == 254000


def test_crm_sync_preserves_manual_financial_allocation_when_source_changes(db):
    sync_crm_canonical(
        db,
        actor="test@example.invalid",
        fetch_page=fetch_page,
        fetch_itep_invoice_page=fetch_itep_invoice_page,
    )
    project = ProjectRegistry(project_id="PRJ-MANUAL-1", name="Kézi besorolási projekt")
    db.add(project)
    db.commit()
    invoice = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.entity_type == "supplier_invoice"
        )
    )
    allocate_financial_record(
        db,
        invoice.record_id,
        scope="project",
        project_id=project.project_id,
        note="Pénzügyi ellenőrzéssel igazolt projektkapcsolat.",
        actor="finance@example.invalid",
        actor_role="finance",
    )

    SOURCE["invoices"][0]["grossAmount"] = 508000
    try:
        result = sync_crm_canonical(
            db,
            actor="test@example.invalid",
            fetch_page=fetch_page,
            fetch_itep_invoice_page=fetch_itep_invoice_page,
        )
    finally:
        SOURCE["invoices"][0]["grossAmount"] = 127000

    db.refresh(invoice)
    assert result["updated"] == 1
    assert invoice.project_id == project.project_id
    allocation = json.loads(invoice.provenance_json)["manualAllocation"]
    assert allocation["scope"] == "project"
    assert allocation["projectId"] == project.project_id


def test_synced_records_are_visible_in_their_business_module(logged_in_client, db):
    sync_crm_canonical(
        db,
        actor="test@example.invalid",
        fetch_page=fetch_page,
        fetch_itep_invoice_page=fetch_itep_invoice_page,
    )

    crm_page = logged_in_client.get("/workbench/crm")
    assert crm_page.status_code == 200
    assert "KANONIKUS VÁLLALATI ADATOK" in crm_page.text
    assert "Aktív ügyfél" in crm_page.text

    finance_page = logged_in_client.get("/workbench/financial-control")
    assert finance_page.status_code == 200
    assert "BILL-1" in finance_page.text
