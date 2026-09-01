from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import desc, func, select

from app.database import SessionLocal
from app.models import (
    EnterpriseCanonicalRecord,
    OutboxMessage,
    ProjectObjectState,
    ProjectRegistry,
    SalesOpportunity,
    SalesProposalVersion,
)
from app.schemas import (
    SalesOpportunityCloseIn,
    SalesOpportunityIn,
    SalesOpportunityStageIn,
    SalesProposalDecisionIn,
    SalesProposalIn,
    SalesProposalReviewIn,
    SalesProposalSendIn,
)
from app.services.sales_pipeline import (
    close_opportunity,
    create_opportunity,
    create_proposal,
    record_proposal_decision,
    review_proposal,
    send_proposal,
    submit_proposal,
    transition_opportunity,
)

LEAD_ID = "LEAD-SALES-SERVER-UAT"
DELIVERY_PROJECT_ID = "SALES-SERVER-UAT-DELIVERY"
CONTRACT_ID = "CONTRACT-SALES-SERVER-UAT"


def _actor(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _ensure_sources(db) -> None:
    canonical = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.domain == "customer",
            EnterpriseCanonicalRecord.entity_type == "lead",
            EnterpriseCanonicalRecord.external_key == LEAD_ID,
        )
    )
    if not canonical:
        db.add(
            EnterpriseCanonicalRecord(
                record_id=f"CAN-{LEAD_ID}",
                domain="customer",
                entity_type="lead",
                external_key=LEAD_ID,
                canonical_name="Sales szerver-UAT ügyfél",
                target_module="crm",
                data_json=json.dumps({"id": LEAD_ID, "stage": "sales_accepted"}),
                provenance_json=json.dumps({"source": "controlled_server_uat"}),
            )
        )
    project = db.scalar(
        select(ProjectRegistry).where(ProjectRegistry.project_id == DELIVERY_PROJECT_ID)
    )
    if not project:
        db.add(
            ProjectRegistry(
                project_id=DELIVERY_PROJECT_ID,
                name="Sales kontrollált szerver-UAT delivery projekt",
                customer_name="Sales szerver-UAT ügyfél",
                project_type="controlled_uat",
                status="active",
                responsible="project-manager@imperial.local",
            )
        )
    contract = db.scalar(
        select(ProjectObjectState).where(
            ProjectObjectState.project_id == DELIVERY_PROJECT_ID,
            ProjectObjectState.source_module == "contract_generator",
            ProjectObjectState.object_type == "Contract",
            ProjectObjectState.object_id == CONTRACT_ID,
        )
    )
    if not contract:
        db.add(
            ProjectObjectState(
                project_id=DELIVERY_PROJECT_ID,
                source_module="contract_generator",
                object_type="Contract",
                object_id=CONTRACT_ID,
                status="signed",
                summary="Kontrollált szerver-UAT aláírt szerződés.",
            )
        )
    db.commit()


def main() -> None:
    with SessionLocal() as db:
        _ensure_sources(db)
        opportunity = db.scalar(
            select(SalesOpportunity).where(
                SalesOpportunity.lead_id == LEAD_ID,
                SalesOpportunity.brand_id == "imperial-holding",
            )
        )
        if not opportunity:
            opportunity = create_opportunity(
                db,
                SalesOpportunityIn(
                    lead_id=LEAD_ID,
                    brand_id="imperial-holding",
                    title="Sales kontrollált szerver-UAT opportunity",
                    customer_name="Sales szerver-UAT ügyfél",
                    customer_email="sales-server-uat@example.com",
                    owner_email="sales@imperial.local",
                    estimated_value_huf="100000000",
                    probability_percent=25,
                    expected_close_date=(datetime.now(UTC) + timedelta(days=60)).date(),
                    needs_summary=(
                        "Kulcsrakész családi ház kontrollált értékesítési UAT-ja teljes scope-pal."
                    ),
                    budget_confirmed=True,
                    decision_process="Az UAT ügyfél és tanácsadója közös, bizonyított döntése.",
                    next_action="Ügyfélspecifikus ajánlatverzió előkészítése.",
                ),
                _actor("sales"),
            )
        if opportunity.stage == "new":
            opportunity = transition_opportunity(
                db,
                opportunity.opportunity_id,
                SalesOpportunityStageIn(
                    stage="qualified",
                    note="A kontrollált UAT lead értékesítési kvalifikációja megtörtént.",
                    probability_percent=30,
                    next_action="Kontrollált UAT discovery végrehajtása.",
                ),
                _actor("sales"),
            )
        if opportunity.stage == "qualified":
            opportunity = transition_opportunity(
                db,
                opportunity.opportunity_id,
                SalesOpportunityStageIn(
                    stage="discovery",
                    note="A kontrollált UAT ügyféligény és döntési út feltárása megtörtént.",
                    probability_percent=35,
                    next_action="Kontrollált ügyfélspecifikus ajánlatverzió összeállítása.",
                ),
                _actor("sales"),
            )
        proposal = db.scalar(
            select(SalesProposalVersion)
            .where(SalesProposalVersion.opportunity_id == opportunity.opportunity_id)
            .order_by(desc(SalesProposalVersion.version))
        )
        if not proposal:
            proposal = create_proposal(
                db,
                opportunity.opportunity_id,
                SalesProposalIn(
                    cost_net="60000000",
                    sale_net="100000000",
                    price_snapshot_id="PRICE-SALES-SERVER-UAT-V1",
                    terms_version_id="TERMS-SALES-SERVER-UAT-V1",
                    technical_scope_version_id="SCOPE-SALES-SERVER-UAT-V1",
                    scope_summary=(
                        "Kulcsrakész épület kontrollált UAT tervezési és kivitelezési tartalma."
                    ),
                    exclusions="Telekvásárlás és közműszolgáltatói díjak.",
                    payment_terms="Szakaszos, teljesítésigazolás-alapú kontrollált UAT ütemezés.",
                    valid_until=datetime.now(UTC) + timedelta(days=365),
                ),
                _actor("sales"),
            )
        if proposal.status == "draft":
            proposal = submit_proposal(db, proposal.proposal_version_id, _actor("sales"))
        if proposal.status == "internal_review" and not proposal.technical_approved_by:
            proposal = review_proposal(
                db,
                proposal.proposal_version_id,
                SalesProposalReviewIn(
                    gate="technical",
                    decision="approve",
                    note="A kontrollált UAT műszaki scope-ja és verziója megfelelő.",
                ),
                _actor("technical-prep"),
            )
        if proposal.status == "internal_review" and not proposal.finance_approved_by:
            proposal = review_proposal(
                db,
                proposal.proposal_version_id,
                SalesProposalReviewIn(
                    gate="finance",
                    decision="approve",
                    note="A kontrollált UAT költség-, ár-, fedezet- és fizetési kapuja megfelelő.",
                ),
                _actor("finance"),
            )
        if proposal.status == "internal_review" and not proposal.legal_approved_by:
            proposal = review_proposal(
                db,
                proposal.proposal_version_id,
                SalesProposalReviewIn(
                    gate="legal",
                    decision="approve",
                    note="A kontrollált UAT ajánlati feltételei és kizárásai kiadhatók.",
                ),
                _actor("legal"),
            )
        if proposal.status == "approved":
            proposal = send_proposal(
                db,
                proposal.proposal_version_id,
                SalesProposalSendIn(
                    delivery_evidence_url="https://drive.example/sales-server-uat-delivery"
                ),
                _actor("sales"),
            )
        if proposal.status == "sent":
            proposal = record_proposal_decision(
                db,
                proposal.proposal_version_id,
                SalesProposalDecisionIn(
                    decision="accept",
                    customer_decision_reference="CUSTOMER-SALES-SERVER-UAT-SIGNATURE",
                    note="A kontrollált UAT ügyfél az ajánlatot bizonyítottan elfogadta.",
                ),
                _actor("sales"),
            )
        if opportunity.stage == "contracting":
            opportunity = close_opportunity(
                db,
                opportunity.opportunity_id,
                SalesOpportunityCloseIn(
                    outcome="won",
                    reason="Az elfogadott UAT-ajánlatból igazoltan aláírt szerződés jött létre.",
                    contract_id=CONTRACT_ID,
                    delivery_project_id=DELIVERY_PROJECT_ID,
                ),
                _actor("sales"),
            )
        crm_outbox = db.scalar(
            select(func.count(OutboxMessage.id)).where(
                OutboxMessage.destination_module == "crm",
                OutboxMessage.payload_json.contains(opportunity.opportunity_id),
            )
        )
        print(
            {
                "opportunity_id": opportunity.opportunity_id,
                "stage": opportunity.stage,
                "proposal_version_id": proposal.proposal_version_id,
                "proposal_status": proposal.status,
                "margin_percent": str(proposal.margin_percent),
                "content_sha256": proposal.content_sha256,
                "contract_id": opportunity.contract_id,
                "delivery_project_id": opportunity.delivery_project_id,
                "crm_outbox_messages": crm_outbox,
            }
        )


if __name__ == "__main__":
    main()
