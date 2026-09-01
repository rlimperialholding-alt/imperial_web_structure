import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import (
    EnterpriseCanonicalRecord,
    OutboxMessage,
    ProjectObjectState,
    ProjectRegistry,
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
    sales_pipeline_workspace,
    send_proposal,
    submit_proposal,
    transition_opportunity,
)
from app.seed import DEMO_PASSWORD

LEAD_ID = "LEAD-SALES-UAT-001"


def _user(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _canonical_lead(db):
    db.add(
        EnterpriseCanonicalRecord(
            record_id="CAN-LEAD-SALES-UAT-001",
            domain="customer",
            entity_type="lead",
            external_key=LEAD_ID,
            canonical_name="Sales UAT Ügyfél",
            target_module="crm",
            data_json=json.dumps({"id": LEAD_ID, "stage": "sales_accepted"}),
            provenance_json=json.dumps({"source": "test"}),
        )
    )
    db.commit()


def _opportunity_data():
    return SalesOpportunityIn(
        lead_id=LEAD_ID,
        brand_id="imperial-holding",
        title="Sales UAT családi ház opportunity",
        customer_name="Sales UAT Ügyfél",
        customer_email="sales-uat-customer@example.com",
        owner_email="sales@imperial.local",
        estimated_value_huf="100000000",
        probability_percent=25,
        expected_close_date=(datetime.now(UTC) + timedelta(days=60)).date(),
        needs_summary=(
            "Kulcsrakész családi ház tervezése és kivitelezése teljes műszaki tartalommal."
        ),
        budget_confirmed=True,
        decision_process="Az ügyfél és pénzügyi tanácsadója közösen dönt az ajánlatról.",
        next_action="Helyszíni igényfelmérés és műszaki koncepció egyeztetése.",
    )


def _proposal_data(*, sale_net: str = "100000000"):
    return SalesProposalIn(
        cost_net="60000000",
        sale_net=sale_net,
        price_snapshot_id="PRICE-SALES-UAT-V1",
        terms_version_id="TERMS-SALES-UAT-V1",
        technical_scope_version_id="SCOPE-SALES-UAT-V1",
        scope_summary="Kulcsrakész épület teljes tervezési és kivitelezési műszaki tartalma.",
        exclusions="Telekvásárlás és közműszolgáltatói díjak.",
        payment_terms="Szakaszos előleg- és teljesítésigazolás-alapú fizetési ütemezés.",
        valid_until=datetime.now(UTC) + timedelta(days=30),
    )


def _advance_to_discovery(db, opportunity_id: str, sales):
    transition_opportunity(
        db,
        opportunity_id,
        SalesOpportunityStageIn(
            stage="qualified",
            note="A kanonikus lead értékesítési kvalifikációja megtörtént.",
            probability_percent=30,
            next_action="Részletes discovery és döntéshozói igényfelmérés.",
        ),
        sales,
    )
    return transition_opportunity(
        db,
        opportunity_id,
        SalesOpportunityStageIn(
            stage="discovery",
            note="Az ügyféligény, döntési folyamat és költségkeret feltárása megtörtént.",
            probability_percent=35,
            next_action="Ügyfélspecifikus ajánlatverzió összeállítása.",
        ),
        sales,
    )


def test_full_sales_pipeline_is_canonical_gated_and_won_only_with_signed_contract(db):
    _canonical_lead(db)
    sales = _user("sales")
    opportunity = create_opportunity(db, _opportunity_data(), sales)
    assert opportunity.stage == "new"
    assert db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.entity_type == "opportunity",
            EnterpriseCanonicalRecord.external_key == opportunity.opportunity_id,
        )
    )

    with pytest.raises(ValueError, match="nyitott opportunity"):
        create_opportunity(db, _opportunity_data(), sales)

    _advance_to_discovery(db, opportunity.opportunity_id, sales)
    proposal = create_proposal(db, opportunity.opportunity_id, _proposal_data(), sales)
    assert proposal.version == 1
    assert proposal.margin_percent == 40
    proposal = submit_proposal(db, proposal.proposal_version_id, sales)
    assert proposal.status == "internal_review"
    assert proposal.content_sha256 and len(proposal.content_sha256) == 64

    with pytest.raises(ValueError, match="sorrendben"):
        review_proposal(
            db,
            proposal.proposal_version_id,
            SalesProposalReviewIn(
                gate="finance",
                decision="approve",
                note="A fedezet és pénzügyi feltételek elfogadhatók.",
            ),
            _user("finance"),
        )
    with pytest.raises(ValueError, match="készítője"):
        review_proposal(
            db,
            proposal.proposal_version_id,
            SalesProposalReviewIn(
                gate="technical",
                decision="approve",
                note="A műszaki tartalom az igényekkel összhangban van.",
            ),
            _user("platform-admin", "sales@imperial.local"),
        )

    review_proposal(
        db,
        proposal.proposal_version_id,
        SalesProposalReviewIn(
            gate="technical",
            decision="approve",
            note="A műszaki tartalom az igényekkel és a scope-verzióval összhangban van.",
        ),
        _user("technical-prep"),
    )
    review_proposal(
        db,
        proposal.proposal_version_id,
        SalesProposalReviewIn(
            gate="finance",
            decision="approve",
            note="A költség, ár, fedezet és fizetési ütemezés pénzügyileg elfogadható.",
        ),
        _user("finance"),
    )
    proposal = review_proposal(
        db,
        proposal.proposal_version_id,
        SalesProposalReviewIn(
            gate="legal",
            decision="approve",
            note="A feltételek, kizárások és érvényesség jogilag kiadható ajánlatot alkotnak.",
        ),
        _user("legal"),
    )
    assert proposal.status == "approved"

    proposal = send_proposal(
        db,
        proposal.proposal_version_id,
        SalesProposalSendIn(delivery_evidence_url="https://drive.example/sales-uat-delivery"),
        sales,
    )
    assert proposal.status == "sent"
    proposal = record_proposal_decision(
        db,
        proposal.proposal_version_id,
        SalesProposalDecisionIn(
            decision="accept",
            customer_decision_reference="CUSTOMER-SIGNATURE-SALES-UAT",
            note="Az ügyfél az ajánlatot igazolt elektronikus nyilatkozattal elfogadta.",
        ),
        sales,
    )
    assert proposal.status == "accepted"

    with pytest.raises(ValueError, match="aláírt ContractID"):
        close_opportunity(
            db,
            opportunity.opportunity_id,
            SalesOpportunityCloseIn(
                outcome="won",
                reason="Az ügyfél az ajánlatot elfogadta, szerződéskötés folyamatban van.",
            ),
            sales,
        )

    db.add(
        ProjectRegistry(
            project_id="SALES-UAT-DELIVERY",
            name="Sales UAT delivery projekt",
            customer_name="Sales UAT Ügyfél",
            project_type="construction",
            status="active",
            responsible="project-manager@imperial.local",
        )
    )
    db.add(
        ProjectObjectState(
            project_id="SALES-UAT-DELIVERY",
            source_module="contract_generator",
            object_type="Contract",
            object_id="CONTRACT-SALES-UAT-001",
            status="signed",
            summary="Kontrollált Sales UAT aláírt szerződés.",
        )
    )
    db.commit()
    won = close_opportunity(
        db,
        opportunity.opportunity_id,
        SalesOpportunityCloseIn(
            outcome="won",
            reason="Az elfogadott ajánlatból igazoltan aláírt kivitelezési szerződés jött létre.",
            contract_id="CONTRACT-SALES-UAT-001",
            delivery_project_id="SALES-UAT-DELIVERY",
        ),
        sales,
    )
    assert won.stage == "won"
    assert won.probability_percent == 100
    assert db.scalars(select(OutboxMessage).where(OutboxMessage.destination_module == "crm")).all()
    canonical = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.entity_type == "opportunity",
            EnterpriseCanonicalRecord.external_key == won.opportunity_id,
        )
    )
    assert json.loads(canonical.data_json)["stage"] == "won"
    assert sales_pipeline_workspace(db)["metrics"]["won_count"] == 1


def test_sales_proposal_margin_hash_and_roles_fail_closed(db):
    _canonical_lead(db)
    sales = _user("sales")
    opportunity = create_opportunity(db, _opportunity_data(), sales)
    _advance_to_discovery(db, opportunity.opportunity_id, sales)
    low_margin = create_proposal(
        db, opportunity.opportunity_id, _proposal_data(sale_net="80000000"), sales
    )
    assert low_margin.margin_percent == 25
    with pytest.raises(ValueError, match="35.00%"):
        submit_proposal(db, low_margin.proposal_version_id, sales)

    low_margin.status = "superseded"
    db.commit()
    proposal = create_proposal(db, opportunity.opportunity_id, _proposal_data(), sales)
    submit_proposal(db, proposal.proposal_version_id, sales)
    with pytest.raises(PermissionError, match="nem jogosult"):
        review_proposal(
            db,
            proposal.proposal_version_id,
            SalesProposalReviewIn(
                gate="technical",
                decision="approve",
                note="Jogosulatlan értékesítő nem végezhet műszaki ajánlati review-t.",
            ),
            sales,
        )
    review_proposal(
        db,
        proposal.proposal_version_id,
        SalesProposalReviewIn(
            gate="technical",
            decision="approve",
            note="A műszaki tartalom és a verziózott scope megfelelő.",
        ),
        _user("technical-prep"),
    )
    review_proposal(
        db,
        proposal.proposal_version_id,
        SalesProposalReviewIn(
            gate="finance",
            decision="approve",
            note="Az ár, költség és fedezet pénzügyileg megfelelő.",
        ),
        _user("finance"),
    )
    proposal = review_proposal(
        db,
        proposal.proposal_version_id,
        SalesProposalReviewIn(
            gate="legal",
            decision="approve",
            note="Az ajánlati feltételek és kizárások jogilag megfelelőek.",
        ),
        _user("legal"),
    )
    proposal.sale_net += 1
    db.commit()
    with pytest.raises(ValueError, match="tartalma"):
        send_proposal(
            db,
            proposal.proposal_version_id,
            SalesProposalSendIn(delivery_evidence_url="https://drive.example/tamper-test"),
            sales,
        )


def test_sales_pipeline_page_is_role_protected_and_renders_native_controls(client):
    response = client.post(
        "/login",
        data={"email": "sales@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/sales-commercial")
    assert page.status_code == 200
    assert "Natív Sales pipeline" in page.text
    assert "/sales-commercial/opportunities" in page.text

    for reviewer in ("technical-prep", "finance", "legal"):
        client.post("/logout")
        response = client.post(
            "/login",
            data={
                "email": f"{reviewer}@imperial.local",
                "password": DEMO_PASSWORD,
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert client.get("/sales-commercial").status_code == 200

    client.post("/logout")
    client.post(
        "/login",
        data={"email": "customer@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert client.get("/sales-commercial").status_code == 403
