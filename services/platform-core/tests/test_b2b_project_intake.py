from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    B2BCRMDelivery,
    B2BDuplicateMatch,
    B2BProjectIntake,
    EnterpriseCanonicalRecord,
    ModuleBusinessRecord,
    OutboxMessage,
    TaskRecord,
    WorkspaceDocument,
)
from app.schemas import (
    B2BCRMReceiptIn,
    B2BDuplicateDecisionIn,
    B2BFinancialReviewIn,
    B2BProjectIntakeIn,
    B2BQualificationDecisionIn,
    B2BTechnicalReviewIn,
)
from app.services.b2b_project_intake import (
    capture_intake,
    leadership_decision,
    qualify_intake,
    queue_crm_handoff,
    record_crm_receipt,
    record_financial_review,
    record_technical_review,
    resolve_duplicate,
)
from app.seed import DEMO_PASSWORD


def _document(db, suffix: str) -> WorkspaceDocument:
    row = WorkspaceDocument(document_id=f"DOC-B2B-{suffix}", title=f"B2B UAT projektbrief {suffix}", category="project_brief", source_system="google_drive", source_url=f"gdrive://b2b/{suffix}", approval_status="approved", verification_status="verified", confidentiality="internal", owner="sales@imperial.local")
    db.add(row); db.commit(); return row


def _payload(suffix: str, document_id: str, *, organization: str = "Imperial Projekt Kft.", source_external_id: str | None = None, budget: str = "1500000000", area: str = "5200", project_type: str = "industrial") -> B2BProjectIntakeIn:
    return B2BProjectIntakeIn(
        source_system="lead-intelligence", source_external_id=source_external_id or f"SIG-{suffix}", source_reference=f"gdrive://b2b/source/{suffix}", source_content_sha256=(suffix.lower().encode().hex() + "a" * 64)[:64], lawful_basis="contract_request", source_use_approved=True,
        organization_name=organization, tax_number="12345678-2-41", website_domain="imperial-projekt.example", contact_name="Teszt Elek", contact_email="teszt.elek@imperial-projekt.example", contact_phone="+36 30 123 4567", project_type=project_type, country="HU", city="Budapest", site_address="1111 Budapest, Teszt utca 1.", gross_floor_area_m2=Decimal(area), planned_start=date(2027, 1, 15), requested_deadline=date(2028, 6, 30), estimated_budget_huf=Decimal(budget), project_summary="Ellenőrzött szintetikus vállalati projektigény ipari épület teljes körű tervezésére és kivitelezésére, döntési és műszaki adatokkal.", document_ids=[document_id],
    )


def _reviews(db, intake_id: str, *, complexity: str = "high") -> None:
    record_technical_review(db, intake_id, B2BTechnicalReviewIn(decision="approved", delivery_model="design_and_build", capacity_fit="fit", site_feasibility="needs_plotcheck", complexity=complexity, assumptions=["A telek részletes PlotCheck ellenőrzése még szükséges."], note="A műszaki tartalom előzetesen illeszkedik a vállalati szolgáltatási körbe."), "pm-reviewer@imperial.local", "project-manager")
    record_financial_review(db, intake_id, B2BFinancialReviewIn(decision="conditional", budget_credibility="credible", funding_status="planned", preliminary_margin_band="előzetes 12–18%, nem ajánlat", assumptions=["Finanszírozási igazolás ajánlat előtt szükséges."], note="A becsült keret előzetesen reális, de kötelező árat vagy fedezetet nem jelent."), "finance-reviewer@imperial.local", "finance")


def test_capture_is_source_idempotent_scored_and_document_governed(db):
    document = _document(db, "CAPTURE")
    payload = _payload("CAPTURE", document.document_id)
    row = capture_intake(db, payload, "marketing@imperial.local", "marketing")
    assert row.status == "prescreen" and row.base_score >= 80
    assert row.missing_fields_json == "[]" and len(row.company_fingerprint) == 64 and len(row.project_fingerprint) == 64
    same = capture_intake(db, payload, "marketing@imperial.local", "marketing")
    assert same.intake_id == row.intake_id and same.signal_count == 2

    document.verification_status = "unverified"; db.commit()
    with pytest.raises(ValueError, match="ellenőrzött"):
        capture_intake(db, _payload("BAD-DOC", document.document_id, source_external_id="SIG-BAD-DOC"), "sales@imperial.local", "sales")
    bad_source = _payload("BAD-SOURCE", document.document_id, source_external_id="SIG-BAD-SOURCE").model_copy(update={"source_use_approved": False})
    with pytest.raises(ValueError, match="jogalappal"):
        capture_intake(db, bad_source, "sales@imperial.local", "sales")


def test_company_and_project_duplicate_requires_human_merge_or_distinct_decision(db):
    document = _document(db, "DEDUPE")
    first = capture_intake(db, _payload("DEDUPE-A", document.document_id), "sales@imperial.local", "sales")
    second = capture_intake(db, _payload("DEDUPE-B", document.document_id, source_external_id="SIG-DEDUPE-B"), "marketing@imperial.local", "marketing")
    assert first.status == "prescreen" and second.status == "dedupe_review"
    match = db.scalar(select(B2BDuplicateMatch).where(B2BDuplicateMatch.intake_id == second.intake_id))
    assert match and match.match_score == 100 and match.status == "pending"
    with pytest.raises(PermissionError):
        resolve_duplicate(db, match.match_id, B2BDuplicateDecisionIn(decision="distinct", note="Külön projektként igazolt igény."), "marketing@imperial.local", "marketing")
    resolve_duplicate(db, match.match_id, B2BDuplicateDecisionIn(decision="distinct", note="A forrásgazda igazolta, hogy külön ütem és külön beszerzési döntés."), "sales@imperial.local", "sales")
    db.refresh(second); assert second.status == "prescreen"

    third = capture_intake(db, _payload("DEDUPE-C", document.document_id, source_external_id="SIG-DEDUPE-C"), "sales@imperial.local", "sales")
    merge_match = db.scalar(select(B2BDuplicateMatch).where(B2BDuplicateMatch.intake_id == third.intake_id, B2BDuplicateMatch.status == "pending"))
    merge_candidate = db.scalar(select(B2BProjectIntake).where(B2BProjectIntake.intake_id == merge_match.candidate_intake_id))
    previous_signals = merge_candidate.signal_count
    resolve_duplicate(db, merge_match.match_id, B2BDuplicateDecisionIn(decision="merge", note="Azonos projektjel ismételt partneri beküldése, a meglévő igényhez olvasztva."), "sales@imperial.local", "sales")
    db.refresh(third); db.refresh(merge_candidate)
    assert third.status == "merged" and merge_candidate.signal_count == previous_signals + 1


def test_full_strategic_lifecycle_requires_pm_finance_sales_leadership_and_hash_receipt(db):
    document = _document(db, "FULL")
    intake = capture_intake(db, _payload("FULL", document.document_id), "marketing@imperial.local", "marketing")
    with pytest.raises(PermissionError):
        record_technical_review(db, intake.intake_id, B2BTechnicalReviewIn(decision="approved", delivery_model="design_and_build", capacity_fit="fit", site_feasibility="plausible", complexity="high", note="Tiltott értékesítői műszaki review."), "sales@imperial.local", "sales")
    _reviews(db, intake.intake_id)
    decision = qualify_intake(db, intake.intake_id, B2BQualificationDecisionIn(decision="qualified", route="b2b_offer", assigned_sales_email="sales@imperial.local", next_action="Vezetői kapu után döntéshozói workshop egyeztetése.", note="A műszaki és pénzügyi előszűrés alapján stratégiai minősített projektigény."), "sales@imperial.local", "sales")
    assert decision.decision == "qualified"
    db.refresh(intake); assert intake.status == "leadership_review" and intake.strategic_review_required is True
    with pytest.raises(PermissionError):
        leadership_decision(db, intake.intake_id, B2BQualificationDecisionIn(decision="approved", route="strategic_b2b", assigned_sales_email="sales@imperial.local", next_action="Workshop.", note="Tiltott értékesítői vezetői döntés."), "sales@imperial.local", "sales")
    leadership_decision(db, intake.intake_id, B2BQualificationDecisionIn(decision="approved", route="strategic_b2b", assigned_sales_email="sales@imperial.local", next_action="Döntéshozói workshop és műszaki discovery indítása.", note="A stratégiai volumen, kockázat és felelősségi szint vezetőileg jóváhagyott."), "managing-director@imperial.local", "managing-director")
    delivery = queue_crm_handoff(db, intake.intake_id, "sales@imperial.local", "sales")
    assert delivery.status == "pending" and len(delivery.payload_sha256) == 64
    assert db.scalar(select(EnterpriseCanonicalRecord).where(EnterpriseCanonicalRecord.external_key == intake.intake_id, EnterpriseCanonicalRecord.entity_type == "lead")) is not None
    assert db.scalar(select(ModuleBusinessRecord).where(ModuleBusinessRecord.record_id == f"CRM-{intake.intake_id}")) is not None
    message = db.scalar(select(OutboxMessage).where(OutboxMessage.destination_module == "crm", OutboxMessage.payload_json.contains(delivery.delivery_id)))
    assert message and delivery.payload_sha256 in message.payload_json
    with pytest.raises(ValueError, match="payload hash"):
        record_crm_receipt(db, B2BCRMReceiptIn(delivery_id=delivery.delivery_id, idempotency_key=delivery.idempotency_key, payload_sha256="f" * 64, accepted=True, external_crm_id="CRM-EXT-BAD"), "crm-adapter", "adapter")
    receipt = record_crm_receipt(db, B2BCRMReceiptIn(delivery_id=delivery.delivery_id, idempotency_key=delivery.idempotency_key, payload_sha256=delivery.payload_sha256, accepted=True, external_crm_id="CRM-EXT-B2B-001"), "crm-adapter", "adapter")
    assert receipt.status == "accepted" and receipt.external_crm_id == "CRM-EXT-B2B-001"
    db.refresh(intake); assert intake.status == "crm_handoff"


def test_incomplete_intake_and_failed_crm_delivery_fail_closed(db):
    document = _document(db, "FAIL")
    incomplete = _payload("INCOMPLETE", document.document_id, budget="0", area="0").model_copy(update={"planned_start": None, "document_ids": [], "contact_email": None, "contact_phone": None, "website_domain": None, "tax_number": None})
    row = capture_intake(db, incomplete, "sales@imperial.local", "sales")
    assert row.status == "incomplete" and row.base_score < 60
    with pytest.raises(ValueError, match="műszaki előszűrés"):
        record_technical_review(db, row.intake_id, B2BTechnicalReviewIn(decision="approved", delivery_model="unknown", capacity_fit="fit", site_feasibility="plausible", complexity="low", note="Hiányos adatokat nem szabad átugrani."), "pm@imperial.local", "project-manager")

    good_payload = _payload("FAIL-CRM", document.document_id, source_external_id="SIG-FAIL-CRM", budget="300000000", area="1200", project_type="corporate").model_copy(update={"organization_name": "Másik Projekt Zrt.", "tax_number": "87654321-2-41", "website_domain": "masik-projekt.example", "city": "Győr"})
    good = capture_intake(db, good_payload, "sales@imperial.local", "sales")
    _reviews(db, good.intake_id, complexity="medium")
    qualify_intake(db, good.intake_id, B2BQualificationDecisionIn(decision="qualified", route="b2b_offer", assigned_sales_email="sales@imperial.local", next_action="CRM-átadás és kapcsolatfelvétel.", note="Nem stratégiai, előszűrt vállalati igény értékesítésre átadható."), "sales@imperial.local", "sales")
    delivery = queue_crm_handoff(db, good.intake_id, "sales@imperial.local", "sales")
    record_crm_receipt(db, B2BCRMReceiptIn(delivery_id=delivery.delivery_id, idempotency_key=delivery.idempotency_key, payload_sha256=delivery.payload_sha256, accepted=False, error_message="Szintetikus CRM validációs hiba."), "crm-adapter", "adapter")
    db.refresh(good); db.refresh(delivery)
    assert good.status == "handoff_failed" and delivery.status == "rejected"
    assert db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == good.intake_id, TaskRecord.title.contains("CRM-átadás javítása"))) is not None


def test_b2b_role_page_access(client):
    for role in ("owner", "managing-director", "marketing", "sales", "finance", "project-manager", "platform-admin"):
        client.post("/logout")
        assert client.post("/login", data={"email": f"{role}@imperial.local", "password": DEMO_PASSWORD}, follow_redirects=False).status_code == 303
        assert client.get("/b2b-project-intake").status_code == 200
    client.post("/logout")
    assert client.post("/login", data={"email": "customer@imperial.local", "password": DEMO_PASSWORD}, follow_redirects=False).status_code == 303
    assert client.get("/b2b-project-intake").status_code == 403
