from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models import B2BDuplicateMatch, OutboxMessage, WorkspaceDocument
from app.schemas import B2BCRMReceiptIn, B2BDuplicateDecisionIn, B2BFinancialReviewIn, B2BProjectIntakeIn, B2BQualificationDecisionIn, B2BTechnicalReviewIn
from app.services.b2b_project_intake import capture_intake, leadership_decision, qualify_intake, queue_crm_handoff, record_crm_receipt, record_financial_review, record_technical_review, resolve_duplicate


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _payload(suffix: str, document_id: str, source_external_id: str) -> B2BProjectIntakeIn:
    return B2BProjectIntakeIn(source_system="uat-controlled-source", source_external_id=source_external_id, source_reference=f"uat://b2b/{suffix}/{source_external_id}", source_content_sha256=_sha(f"b2b-source:{suffix}:{source_external_id}"), lawful_basis="contract_request", source_use_approved=True, organization_name=f"Szintetikus Stratégiai Beruházó {suffix} Kft.", tax_number=f"{abs(hash(suffix)) % 90000000 + 10000000}-2-41", website_domain=f"b2b-{_sha(suffix)[:12]}.example", contact_name="B2B UAT Kapcsolattartó", contact_email=f"b2b-uat-{_sha(suffix)[:8]}@example.test", contact_phone="+36 30 555 0101", project_type="industrial", country="HU", city="Budapest", site_address="1111 Budapest, Szintetikus UAT út 1.", gross_floor_area_m2=Decimal("6200"), planned_start=date(2027, 2, 1), requested_deadline=date(2028, 12, 15), estimated_budget_huf=Decimal("1750000000"), project_summary="Kizárólag szintetikus szerver-UAT vállalati projektigény, amely a teljes deduplikációs, műszaki, pénzügyi, értékesítői, vezetői és CRM-átadási kapuláncot bizonyítja.", document_ids=[document_id])


def run(suffix: str) -> dict:
    with SessionLocal() as db:
        before_messages = set(db.scalars(select(OutboxMessage.message_id)).all())
        document = WorkspaceDocument(document_id=f"DOC-B2B-UAT-{suffix}", title=f"Szintetikus B2B UAT projektbrief {suffix}", category="project_brief", source_system="uat", source_url=f"uat://b2b/{suffix}/brief", approval_status="approved", verification_status="verified", confidentiality="internal", owner="sales@imperial.local")
        db.add(document); db.commit()
        intake = capture_intake(db, _payload(suffix, document.document_id, f"SIG-B2B-UAT-{suffix}"), "marketing@imperial.local", "marketing")
        record_technical_review(db, intake.intake_id, B2BTechnicalReviewIn(decision="approved", delivery_model="design_and_build", capacity_fit="fit", site_feasibility="needs_plotcheck", complexity="high", assumptions=["A PlotCheck és a részletes mérnöki discovery későbbi kötelező kapu."], note="Szintetikus UAT projektmenedzseri műszaki előszűrés, kötelező alkalmassági ígéret nélkül."), "project-manager@imperial.local", "project-manager")
        record_financial_review(db, intake.intake_id, B2BFinancialReviewIn(decision="conditional", budget_credibility="credible", funding_status="planned", preliminary_margin_band="előzetes 12–18%, nem ajánlat", assumptions=["Finanszírozási igazolás ajánlat előtt szükséges."], note="Szintetikus UAT pénzügyi előszűrés; nem végleges ár-, fedezet- vagy finanszírozási ígéret."), "finance@imperial.local", "finance")
        qualify_intake(db, intake.intake_id, B2BQualificationDecisionIn(decision="qualified", route="strategic_b2b", assigned_sales_email="sales@imperial.local", next_action="Ügyvezetői kapu után döntéshozói workshop.", note="Szintetikus UAT értékesítői minősítés a két szakmai review alapján."), "sales@imperial.local", "sales")
        leadership_decision(db, intake.intake_id, B2BQualificationDecisionIn(decision="approved", route="strategic_b2b", assigned_sales_email="sales@imperial.local", next_action="CRM receipt után műszaki discovery workshop.", note="Szintetikus UAT ügyvezetői stratégiai döntés, név szerinti felelősséggel."), "managing-director@imperial.local", "managing-director")
        delivery = queue_crm_handoff(db, intake.intake_id, "sales@imperial.local", "sales")
        messages = list(db.scalars(select(OutboxMessage).where(~OutboxMessage.message_id.in_(before_messages))).all())
        for message in messages:
            message.status = "sent"; message.last_error = "UAT_INTERCEPTED_NO_EXTERNAL_DELIVERY"
        db.commit()
        record_crm_receipt(db, B2BCRMReceiptIn(delivery_id=delivery.delivery_id, idempotency_key=delivery.idempotency_key, payload_sha256=delivery.payload_sha256, accepted=True, external_crm_id=f"CRM-UAT-{suffix}"), "b2b-uat-adapter", "adapter")

        duplicate = capture_intake(db, _payload(suffix, document.document_id, f"SIG-B2B-UAT-DUP-{suffix}"), "marketing@imperial.local", "marketing")
        match = db.scalar(select(B2BDuplicateMatch).where(B2BDuplicateMatch.intake_id == duplicate.intake_id, B2BDuplicateMatch.status == "pending"))
        if not match: raise RuntimeError("A szintetikus duplikátum nem került deduplikációs review-ba.")
        resolve_duplicate(db, match.match_id, B2BDuplicateDecisionIn(decision="merge", note="Szintetikus UAT ismételt projektjel, a már minősített projektigénybe olvasztva."), "sales@imperial.local", "sales")

        incomplete_payload = B2BProjectIntakeIn(source_system="uat-controlled-source", source_external_id=f"SIG-B2B-UAT-INCOMPLETE-{suffix}", source_reference=f"uat://b2b/{suffix}/incomplete", source_content_sha256=_sha(f"b2b-incomplete:{suffix}"), lawful_basis="partner_referral", source_use_approved=True, organization_name=f"Szintetikus Hiányos Igény {suffix} Kft.", contact_name="Hiányos UAT Kapcsolat", project_type="corporate", country="HU", city="Győr", gross_floor_area_m2=Decimal("0"), estimated_budget_huf=Decimal("0"), project_summary="Szintetikus hiányos B2B projektjel, amelyet a rendszernek meg kell állítania.")
        incomplete = capture_intake(db, incomplete_payload, "sales@imperial.local", "sales")
        db.refresh(intake); db.refresh(delivery); db.refresh(duplicate)
        if intake.status != "crm_handoff" or delivery.status != "accepted" or duplicate.status != "merged" or incomplete.status != "incomplete": raise RuntimeError("A B2B UAT visszaolvasott végállapota hibás.")
        return {"suffix": suffix, "document_id": document.document_id, "intake_id": intake.intake_id, "score": intake.base_score, "delivery_id": delivery.delivery_id, "payload_sha256": delivery.payload_sha256, "external_crm_id": delivery.external_crm_id, "duplicate_intake_id": duplicate.intake_id, "duplicate_match_id": match.match_id, "incomplete_intake_id": incomplete.intake_id, "intercepted_outbox": len(messages)}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--suffix", required=True); args = parser.parse_args()
    print(json.dumps(run(args.suffix), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__": main()
