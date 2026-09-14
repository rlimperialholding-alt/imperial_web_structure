from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ProjectRegistry, TenderPurchaseOrderPreparation
from app.services.partner_control import (
    add_certificate,
    approve_decision,
    approve_partner,
    close_incident,
    create_incident,
    create_partner,
    create_project_evaluation,
    declare_capacity,
    eligibility_report,
    propose_decision,
    record_incident_response,
    review_capacity,
    review_decision,
    set_external_score,
    verify_certificate,
)
from app.services.tender_portal import (
    accept_clarification_request,
    add_invitation,
    add_tender_line_item,
    award_bid,
    close_tender,
    create_clarification_request,
    create_tender,
    evaluate_bid,
    publish_tender,
    respond_clarification_request,
    save_bid,
    submit_bid,
)


def user(role: str, email: str) -> SimpleNamespace:
    return SimpleNamespace(role=role, email=email)


PM = user("project-manager", "partner-uat-pm@imperial.local")
TECH = user("technical-prep", "partner-uat-tech@imperial.local")
FINANCE = user("finance", "partner-uat-finance@imperial.local")
LEADERSHIP = user("managing-director", "partner-uat-md@imperial.local")


def main() -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    project_id = f"PARTNER-UAT-{stamp}"
    tender_id = f"TND-PARTNER-UAT-{stamp}"
    partner_email = f"partner-uat-{stamp.lower()}@example.com"
    with SessionLocal() as db:
        db.add(
            ProjectRegistry(
                project_id=project_id,
                name="Partner Control teljes UAT",
                status="active",
                responsible=PM.email,
            )
        )
        db.commit()
        partner = create_partner(
            db,
            PM,
            company_name=f"Partner UAT {stamp} Kft.",
            primary_email=partner_email,
            tax_number=f"UAT-{stamp}",
            trade_categories=["szerkezet"],
            territories=["Budapest"],
        )
        set_external_score(
            db,
            partner.partner_id,
            TECH,
            score=90,
            evidence_ref=f"drive://partner-uat/{stamp}/registry",
        )
        approve_partner(
            db,
            partner.partner_id,
            FINANCE,
            note="UAT külső cég-, pénzügyi és referenciaellenőrzés elfogadva.",
        )
        for index, cert_type in enumerate(("liability_insurance", "tax_clearance"), start=1):
            digest = hashlib.sha256(f"{stamp}:{cert_type}".encode()).hexdigest()
            certificate = add_certificate(
                db,
                partner.partner_id,
                PM,
                certificate_type=cert_type,
                issuer="UAT Kibocsátó",
                document_ref=f"drive://partner-uat/{stamp}/{cert_type}",
                document_sha256=digest,
                valid_from=date.today() - timedelta(days=1),
                valid_until=date.today() + timedelta(days=365),
                reference_number=f"UAT-{index}",
            )
            verify_certificate(db, certificate.certificate_id, FINANCE, accepted=True)
        capacity = declare_capacity(
            db,
            partner.partner_id,
            PM,
            trade_category="szerkezet",
            territory="Budapest",
            available_from=date.today(),
            available_until=date.today() + timedelta(days=120),
            crew_count=12,
            monthly_capacity=100,
            committed_capacity=20,
            evidence_ref=f"drive://partner-uat/{stamp}/capacity",
        )
        review_capacity(
            db,
            capacity.declaration_id,
            TECH,
            accepted=True,
            note="UAT kapacitás és brigádlétszám ellenőrizve.",
        )

        tender = create_tender(
            db,
            PM,
            tender_id=tender_id,
            project_id=project_id,
            title="Partner Control UAT szerkezetépítési tender",
            scope=(
                "Teljes szerkezetépítési tartalom tételes kiírással, "
                "igazoláskapuval és auditált odaítéléssel."
            ),
            currency="HUF",
            question_deadline_at=datetime.now(UTC) + timedelta(days=2),
            submission_deadline_at=datetime.now(UTC) + timedelta(days=5),
            prequalification_required=True,
            certificate_gate_enabled=True,
            required_certificate_types=["liability_insurance", "tax_clearance"],
        )
        add_tender_line_item(
            db,
            tender_id,
            PM,
            line_code="STR-001",
            category="Szerkezet",
            name="Vasbeton szerkezet",
            unit="m3",
            quantity="10",
        )
        add_tender_line_item(
            db,
            tender_id,
            PM,
            line_code="STR-002",
            category="Szerkezet",
            name="Falazási munkák",
            unit="m2",
            quantity="100",
        )
        invitation = add_invitation(
            db,
            tender_id,
            PM,
            partner_email=partner.primary_email,
            company_name=partner.company_name,
            partner_id=partner.partner_id,
        )
        publish_tender(db, tender_id, PM)
        bid = save_bid(
            db,
            tender_id,
            invitation.access_token,
            items=[
                {
                    "description": "Vasbeton szerkezet",
                    "unit": "m3",
                    "quantity": "10",
                    "unit_price": "50000",
                },
                {
                    "description": "Falazási munkák",
                    "unit": "m2",
                    "quantity": "100",
                    "unit_price": "12000",
                },
            ],
            vat_percent="27",
            validity_days=30,
            lead_time_days=45,
            warranty_months=36,
            summary="Teljes körű UAT ajánlat dokumentált kapacitással.",
            exclusions="Daruzás külön megrendelés szerint.",
        )
        submit_bid(db, tender_id, invitation.access_token)
        close_tender(db, tender_id, PM)
        evaluate_bid(
            db,
            tender_id,
            bid.bid_id,
            PM,
            price_score=88,
            technical_score=92,
            timeline_score=85,
            references_score=90,
            recommendation="recommended",
            notes="Az ajánlat tételesen teljes, normalizált, piaci és kapacitással igazolt.",
        )
        clarification = create_clarification_request(
            db,
            tender_id,
            bid.bid_id,
            PM,
            question="Kérjük a mobilizációs létszám végleges, dokumentált megerősítését.",
            due_at=datetime.now(UTC) + timedelta(days=1),
        )
        respond_clarification_request(
            db,
            tender_id,
            invitation.access_token,
            clarification.request_id,
            response="Tizenkét fős brigáddal öt munkanapon belül mobilizálunk.",
        )
        accept_clarification_request(
            db, clarification.request_id, PM, note="A létszám és a mobilizáció elfogadva."
        )
        awarded = award_bid(
            db,
            tender_id,
            bid.bid_id,
            LEADERSHIP,
            summary="A kapuk, a súlyozott értékelés és a hiánypótlás alapján a legjobb ajánlat.",
        )
        preparation = db.scalar(
            select(TenderPurchaseOrderPreparation).where(
                TenderPurchaseOrderPreparation.tender_id == tender_id
            )
        )
        performance = create_project_evaluation(
            db,
            partner.partner_id,
            project_id,
            PM,
            quality=5,
            deadline=4,
            documentation=5,
            hse=5,
            cooperation=5,
            commercial=4,
            warranty=4,
            notes=(
                "UAT projektvégi teljesítményértékelés bizonyított, magas színvonalú teljesítéssel."
            ),
        )
        incident = create_incident(
            db,
            partner.partner_id,
            PM,
            incident_type="hse",
            severity="critical",
            facts="UAT kritikus HSE esemény: dokumentált leesésvédelmi mulasztás történt.",
            requirement_breached="A kötelező leesésvédelmi előírást az UAT eseményben megszegték.",
            immediate_risk="A mulasztás közvetlen élet- és súlyos balesetveszélyt okozott.",
            project_id=project_id,
            evidence_refs=[f"drive://partner-uat/{stamp}/incident"],
        )
        reinstatement = propose_decision(
            db,
            partner.partner_id,
            PM,
            decision_type="reinstatement_review",
            basis={
                "incident_id": incident.incident_id,
                "review_scope": "HSE korrekció és helyszíni audit",
            },
            review_at=datetime.now(UTC) + timedelta(days=30),
        )
        review_decision(
            db,
            reinstatement.decision_id,
            PM,
            review_type="pm",
            note="Az újraengedélyezési vizsgálat szakmai köre megfelelő.",
        )
        review_decision(
            db,
            reinstatement.decision_id,
            FINANCE,
            review_type="finance_legal",
            note="A pénzügyi, biztosítási és jogi kontroll megfelelő.",
        )
        approve_decision(
            db,
            reinstatement.decision_id,
            LEADERSHIP,
            notification_evidence_ref=f"drive://partner-uat/{stamp}/reinstatement-review",
        )
        record_incident_response(
            db,
            incident.incident_id,
            PM,
            partner_statement="A partner az UAT eseményt elismerte és azonnal kivizsgálta.",
            corrective_action="Új oktatás, eszközellenőrzés és helyszíni audit végrehajtása.",
            corrective_owner="UAT HSE vezető",
            corrective_due_at=datetime.now(UTC) + timedelta(days=7),
        )
        close_incident(
            db,
            incident.incident_id,
            TECH,
            outcome="A korrekciókat dokumentumokkal és helyszíni visszaellenőrzéssel igazolták.",
        )
        decision = propose_decision(
            db,
            partner.partner_id,
            PM,
            decision_type="approved",
            basis={
                "incident_id": incident.incident_id,
                "closure": f"drive://partner-uat/{stamp}/closure",
            },
            review_at=datetime.now(UTC) + timedelta(days=180),
        )
        review_decision(
            db,
            decision.decision_id,
            PM,
            review_type="pm",
            note="A korrekció és visszaellenőrzés UAT szerint elfogadható.",
        )
        approve_decision(
            db,
            decision.decision_id,
            LEADERSHIP,
            notification_evidence_ref=f"drive://partner-uat/{stamp}/decision",
        )
        final_eligibility = eligibility_report(db, partner.partner_id, tender=tender)
        print(
            json.dumps(
                {
                    "project_id": project_id,
                    "tender_id": tender_id,
                    "partner_id": partner.partner_id,
                    "partner_status": partner.status,
                    "combined_score": str(partner.combined_score),
                    "capacity_status": capacity.status,
                    "tender_status": awarded.status,
                    "bid_id": bid.bid_id,
                    "bid_version": bid.version,
                    "clarification_status": clarification.status,
                    "purchase_order_preparation_id": preparation.preparation_id
                    if preparation
                    else None,
                    "purchase_order_status": preparation.status if preparation else None,
                    "performance_score": str(performance.score_100),
                    "incident_status": incident.status,
                    "immediate_suspension": incident.immediate_suspension,
                    "reinstatement_review_status": reinstatement.status,
                    "decision_status": decision.status,
                    "final_eligibility": final_eligibility,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
