"""A TENDER-kapu enforcement-tesztjei a tiltott mutációk határain — Task75.

Tender-odaítélés, PO-előkészítés-jóváhagyás, beszerzési döntés
véglegesítés, megrendelés létrehozás/visszaigazolás, finance-commitment
outbox, alvállalkozói szerződés-átmenetek: minden út a kanonikus kapun
keresztül fut, blokk esetén mutáció, outbox és lekötés nélkül.
Kizárólag szintetikus fixture-ek.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import (ContractWorkflowRecord,
    FinanceCommitment,
    MarginGateDecision,
    OutboxMessage,
    ProcurementOrderProjection,
    ProcurementSelection,
    ProjectFinancePlan,
    ProjectRegistry,
    TenderBid,
    TenderInvitation,
    TenderPackage,
    TenderPurchaseOrderPreparation,)
from app.seed import DEMO_PASSWORD
from app.services import procurement as procurement_service
from app.services.commercial_integration import generate_contract_package
from app.services.tender_portal import (create_tender,)
from app.services.tender_margin_gate import MarginGateBlocked
from margin_gate_fixtures import seed_gate_plan

PROJECT = "ENF-001"
TENDER_ID = "TND-ENF-2026-001"


def _user(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _login(client, email: str = "platform-admin@imperial.local") -> None:
    client.cookies.clear()
    response = client.post("/login", data={"email": email, "password": DEMO_PASSWORD}, follow_redirects=False)
    assert response.status_code == 303


def _project(db):
    if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == PROJECT)):
        db.add(ProjectRegistry(project_id=PROJECT, name="Enforcement tesztprojekt", status="active", responsible="project-manager@imperial.local",))
        db.commit()


def _tender(db, *, cost_code: str | None = None) -> TenderPackage:
    _project(db)
    now = datetime.now(UTC)
    tender = create_tender(db,
        _user("project-manager"),
        tender_id=TENDER_ID,
        project_id=PROJECT,
        title="Enforcement szerkezet tender",
        scope="Teljes szerkezetépítési munkatartalom anyaggal, dokumentált átadással.",
        currency="HUF",
        question_deadline_at=now + timedelta(days=2),
        submission_deadline_at=now + timedelta(days=5),
        cost_code=cost_code,
        prequalification_required=False,)
    tender.status = "evaluation"
    db.commit()
    db.refresh(tender)
    return tender


def _bid(db, tender: TenderPackage, *, net_total: str = "5000000") -> TenderBid:
    from app.services.partner_control import create_partner
    token = uuid.uuid4().hex
    partner_email = f"partner-{token[:8]}@example.com"
    partner = create_partner(db, _user("project-manager"), company_name="Szintetikus Partner Kft.", primary_email=partner_email, partner_id=f"PAR-{token[:8]}",)
    invitation = TenderInvitation(invitation_id=f"INV-{token[:10]}",
        tender_id_fk=tender.id, partner_id=partner.partner_id,
        partner_email=partner_email, company_name="Szintetikus Partner Kft.",
        contact_name="Partner Péter", access_token=token * 2,
        expires_at=datetime.now(UTC) + timedelta(days=30), status="sent",)
    db.add(invitation)
    db.flush()
    bid = TenderBid(bid_id=f"BID-{uuid.uuid4().hex[:10]}", tender_id_fk=tender.id, invitation_id_fk=invitation.id, status="submitted", currency="HUF", net_total=Decimal(net_total),)
    db.add(bid)
    db.flush()
    from app.models import TenderBidVersion, TenderEvaluation
    db.add(TenderBidVersion(bid_version_id=f"BV-{uuid.uuid4().hex[:10]}", bid_id_fk=bid.id, version=1,
        lifecycle_status="submitted", currency="HUF", net_total=Decimal(net_total),
        vat_total=Decimal("0"), gross_total=Decimal(net_total),
        normalization_status="clean", normalization_issues_json="[]",
        content_sha256="a" * 64,))
    db.add(TenderEvaluation(evaluation_id=f"EVAL-{uuid.uuid4().hex[:10]}", tender_id_fk=tender.id,
        bid_id_fk=bid.id, evaluator_email="project-manager@imperial.local",
        price_score=80, technical_score=80, timeline_score=80, references_score=80,
        weighted_total=Decimal("80.00"), recommendation="recommended",
        notes="Szintetikus értékelés a kapu teszthez.",))
    db.commit()
    return bid


# --- Tender-odaítélés ---


def _tender_with_bid(db, *, cost_code="MAT-ENF", net_total="5000000"):
    tender = _tender(db, cost_code=cost_code)
    return tender, _bid(db, tender, net_total=net_total)


def _award(client, bid):
    return client.post(f"/tenders/{TENDER_ID}/bids/{bid.bid_id}/award", data={"summary": "A dokumentált értékelés alapján kiválasztott ajánlat."}, follow_redirects=False,)


def test_award_blocks_without_budget_or_over_envelope(client, db):
    _project(db)
    _login(client)
    tender = _tender(db, cost_code="MAT-ENF")
    bid = _bid(db, tender)
    response = _award(client, bid)
    assert response.status_code == 400
    fresh = db.scalar(select(TenderPackage).where(TenderPackage.tender_id == TENDER_ID))
    assert fresh.status != "awarded" and fresh.awarded_bid_id is None
    decisions = list(db.scalars(select(MarginGateDecision)).all())
    assert decisions and decisions[0].decision == "BLOCK"
    # Pontosan 35.00% fedezetű tervvel a boríték fölé növő ajánlat → BLOCK,
    # odaítélés, PO-előkészítés és lekötés nélkül.
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-ENF", "6500000", "labour")])
    response = _award(client, _bid(db, tender, net_total="6500000.01"))
    assert response.status_code == 400
    fresh = db.scalar(select(TenderPackage).where(TenderPackage.tender_id == TENDER_ID))
    assert fresh.status != "awarded"
    assert db.scalars(select(TenderPurchaseOrderPreparation)).all() == []
    assert db.scalars(select(FinanceCommitment)).all() == []


def test_award_with_approved_budget_passes(client, db):
    _project(db)
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-ENF", "5000000", "labour")])
    _login(client)
    response = _award(client, _tender_with_bid(db)[1])
    assert response.status_code == 303, response.text
    db.expire_all()
    fresh = db.scalar(select(TenderPackage).where(TenderPackage.tender_id == TENDER_ID))
    assert fresh.status == "awarded"
    commitments = list(db.scalars(select(FinanceCommitment)).all())
    assert len(commitments) == 1 and commitments[0].cost_code == "MAT-ENF"


# --- PO-előkészítés jóváhagyás ---


def _preparation(db, preparation_id: str, *, bid=None, status="draft") -> TenderPurchaseOrderPreparation:
    preparation = TenderPurchaseOrderPreparation(preparation_id=preparation_id, tender_id=TENDER_ID, project_id=PROJECT,
        partner_id="PAR-X", bid_id=bid.bid_id if bid else "BID-X", bid_version_id="BV-X",
        line_snapshot_json="[]", status=status, eligibility_snapshot_json="{}",
        content_sha256="a" * 64, prepared_by="fixture@imperial.local",)
    db.add(preparation)
    db.commit()
    return preparation


# --- PO-előkészítés jóváhagyás ---


def test_po_preparation_approval_requires_gate(client, db):
    _project(db)
    _login(client)
    bid = _tender_with_bid(db)[1]
    response = _award(client, bid)
    assert response.status_code == 400  # terv nélkül az odaítélés sem mehet
    _preparation(db, "POPREP-ENF-1", bid=bid)
    response = client.post("/tenders/purchase-order-preparations/POPREP-ENF-1/approve")
    assert response.status_code == 400
    db.refresh(db.scalar(select(TenderPurchaseOrderPreparation)))
    assert db.scalar(select(TenderPurchaseOrderPreparation)).status == "draft"


def test_po_preparation_approval_passes_with_gate(client, db):
    _project(db)
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-ENF", "5000000", "labour")])
    bid = _tender_with_bid(db)[1]
    _preparation(db, "POPREP-ENF-2", bid=bid)
    _login(client)
    response = client.post("/tenders/purchase-order-preparations/POPREP-ENF-2/approve", follow_redirects=False,)
    assert response.status_code == 303
    preparation = db.scalar(select(TenderPurchaseOrderPreparation))
    db.refresh(preparation)
    assert preparation.status == "approved"


def test_po_preparation_approval_requires_decision_role(client, db):
    _project(db)
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-ENF", "5000000", "labour")])
    _preparation(db, "POPREP-ENF-3")
    _login(client, "project-manager@imperial.local")
    response = client.post("/tenders/purchase-order-preparations/POPREP-ENF-3/approve")
    assert response.status_code == 403


# --- Beszerzés: döntés, megrendelés, outbox ---


def _approved_requirement(client, db, *, cost_code: str | None = None) -> str:
    _project(db)
    response = client.post("/api/procurement/requirements", json={
        "project_id": PROJECT, "category": "falazat",
        "scope_description": "Falazóanyag teljes mennyiség", "specification": "Tégla 30 N+F",
        "net_quantity": "100", "waste_pct": "5", "unit": "raklap",
        "required_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        "budget_huf": "7000000", "target_huf": "6000000", "cost_code": cost_code,
    })
    assert response.status_code == 200, response.text
    requirement_id = response.json()["requirement_id"]
    assert client.post(f"/api/procurement/requirements/{requirement_id}/approvals/technical").status_code == 200
    assert client.post(f"/api/procurement/requirements/{requirement_id}/approvals/budget_cash").status_code == 200
    return requirement_id


def _selected(client, requirement_id: str) -> str:
    client.post("/api/procurement/offers", json={
        "requirement_id": requirement_id, "supplier_name": "A Kft.",
        "net_total_huf": "5200000", "delivery_cost_huf": "0", "other_landed_cost_huf": "0",
        "lead_time_days": 7, "warranty_months": 24, "payment_terms": "30 nap",
        "risk_score": 10, "technical_compliant": True, "document_ref": "https://drive.example/a",
    }).json()["offer_id"]
    chosen = client.post("/api/procurement/offers", json={
        "requirement_id": requirement_id, "supplier_name": "B Kft.",
        "net_total_huf": "5000000", "delivery_cost_huf": "0", "other_landed_cost_huf": "0",
        "lead_time_days": 7, "warranty_months": 24, "payment_terms": "30 nap",
        "risk_score": 10, "technical_compliant": True, "document_ref": "https://drive.example/b",
    }).json()["offer_id"]
    selection = client.post("/api/procurement/selections", json={
        "requirement_id": requirement_id, "offer_id": chosen,
        "rationale": "Legjobb TLC", "risk_rationale": "Alacsony kockázat",
    }).json()["selection_id"]
    assert client.post(f"/api/procurement/selections/{selection}/approvals/finance").status_code == 200
    return selection


def test_selection_final_approval_blocks_without_budget_or_cost_code(client, db):
    # Terv nélkül a döntés-véglegesítés blokkol, BLOCK-bizonyítékkal.
    requirement_id = _approved_requirement(client, db, cost_code="MAT-ENF")
    selection_id = _selected(client, requirement_id)
    response = client.post(f"/api/procurement/selections/{selection_id}/approvals/managing_director")
    assert response.status_code == 409
    row = db.scalar(select(ProcurementSelection).where(ProcurementSelection.selection_id == selection_id))
    assert row.status == "approval_pending"
    decisions = list(db.scalars(select(MarginGateDecision)).all())
    assert decisions and decisions[0].decision == "BLOCK"
    assert decisions[0].block_reason_code == "missing_approved_budget"
    # Tervvel, de költségkód nélkül: a kötelező kód-hozzárendelés hiánya blokkol.
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-ENF", "5000000", "labour")])
    requirement_id = _approved_requirement(client, db, cost_code=None)
    selection_id = _selected(client, requirement_id)
    response = client.post(f"/api/procurement/selections/{selection_id}/approvals/managing_director")
    assert response.status_code == 409
    decisions = list(db.scalars(select(MarginGateDecision)).all())
    assert decisions and decisions[-1].block_reason_code == "missing_cost_code_mapping"


def test_order_creation_blocks_without_budget_and_emits_no_outbox(client, db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-ENF", "5000000", "labour")])
    requirement_id = _approved_requirement(client, db, cost_code="MAT-ENF")
    selection_id = _selected(client, requirement_id)
    assert client.post(f"/api/procurement/selections/{selection_id}/approvals/managing_director").status_code == 200
    # A terv visszavonása után a megrendelés már nem mehet át.
    plan = db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.project_id == PROJECT))
    plan.status = "superseded"
    db.commit()
    outbox_before = len(list(db.scalars(select(OutboxMessage)).all()))
    commitments_before = len(list(db.scalars(select(FinanceCommitment)).all()))
    response = client.post("/api/procurement/orders", json={
        "selection_id": selection_id, "ordered_quantity": "100",
        "delivery_due": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
    })
    assert response.status_code == 409
    orders = list(db.scalars(select(ProcurementOrderProjection)).all())
    assert orders == []
    outbox_after = len(list(db.scalars(select(OutboxMessage)).all()))
    assert outbox_after == outbox_before
    # A döntés-jóváhagyáskor rögzült lekötés változatlan; a blokkolt
    # megrendeléshez új lekötés nem keletkezett.
    assert len(list(db.scalars(select(FinanceCommitment)).all())) == commitments_before


def test_order_confirm_rechecks_gate_and_blocks_on_tighter_plan(client, db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-ENF", "5000000", "labour")])
    requirement_id = _approved_requirement(client, db, cost_code="MAT-ENF")
    selection_id = _selected(client, requirement_id)
    assert client.post(f"/api/procurement/selections/{selection_id}/approvals/managing_director").status_code == 200
    order = client.post("/api/procurement/orders", json={
        "selection_id": selection_id, "ordered_quantity": "100",
        "delivery_due": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
    }).json()
    # Új, szűkebb jóváhagyott tervverzió: a visszaigazolás újraellenőrzése blokkol.
    old = db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.project_id == PROJECT))
    old.status = "superseded"
    db.commit()
    seed_gate_plan(db, project_id=PROJECT, revenue="7000000", direct_lines=[("MAT-ENF", "5000000", "labour")], plan_id="FIN-PLAN-ENF-02", version=2,)
    response = client.post(f"/api/procurement/orders/{order['order_id']}/confirm")
    assert response.status_code == 409
    row = db.scalar(select(ProcurementOrderProjection).where(ProcurementOrderProjection.order_id == order["order_id"]))
    assert row.confirmation_status == "pending"


def test_order_create_partial_failure_rolls_back_everything(client, db, monkeypatch):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-ENF", "5000000", "labour")])
    requirement_id = _approved_requirement(client, db, cost_code="MAT-ENF")
    selection_id = _selected(client, requirement_id)
    assert client.post(f"/api/procurement/selections/{selection_id}/approvals/managing_director").status_code == 200

    def _boom(db, destination, endpoint, payload):
        raise RuntimeError("outbox failure")

    monkeypatch.setattr(procurement_service, "_outbox", _boom)
    with pytest.raises(RuntimeError, match="outbox failure"):
        client.post("/api/procurement/orders", json={
            "selection_id": selection_id, "ordered_quantity": "100",
            "delivery_due": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
        })
    commitments_before = len(list(db.scalars(select(FinanceCommitment)).all()))
    decisions_before = len(list(db.scalars(select(MarginGateDecision)).all()))
    assert db.scalars(select(ProcurementOrderProjection)).all() == []
    assert db.scalars(select(OutboxMessage)).all() == []
    # A kapu-PASS döntése és az új lekötés a mutációval együtt visszagördült;
    # csak a döntés-jóváhagyáskori állapot maradt.
    assert len(list(db.scalars(select(FinanceCommitment)).all())) == commitments_before
    assert len(list(db.scalars(select(MarginGateDecision)).all())) == decisions_before


# --- Alvállalkozói szerződés-átmenetek ---


def _subcontract_payload(commitment: dict | None):
    import json as _json
    from pathlib import Path
    examples = Path(__file__).resolve().parents[1] / "integrations" / "contract_generator_v0_4" / "examples"
    payload = _json.loads((examples / "subcontractor_execution_valid.json").read_text(encoding="utf-8"))
    payload["contract_number"] = f"UAT-SUB-{uuid.uuid4().hex[:8].upper()}"
    payload["ids"].update({"ProjectID": PROJECT, "PartnerID": f"PAR-{uuid.uuid4().hex[:8]}"})
    for attachment in payload["attachments"]:
        attachment["file_id"] = f"EVIDENCE-{uuid.uuid4().hex[:8]}-{attachment['type']}"
    if commitment:
        payload["construction_commitment"] = commitment
    return payload


def test_subcontract_contract_generation_requires_gate_and_descriptor(db):
    _project(db)
    # Commitment-leíró nélkül a generálás blokkol, rekord nélkül.
    with pytest.raises(MarginGateBlocked) as excinfo:
        generate_contract_package(db, _subcontract_payload(None), actor="api")
    assert excinfo.value.reason_code == "missing_commitment_descriptor"
    assert db.scalars(select(ContractWorkflowRecord)).all() == []
    # Jóváhagyott terv nélkül a leíróval rendelkező szerződés is blokkol.
    with pytest.raises(MarginGateBlocked) as excinfo:
        generate_contract_package(db, _subcontract_payload({"cost_code": "SUB-EXEC", "net_huf": "5000000"}), actor="api",)
    assert excinfo.value.reason_code == "missing_approved_budget"
    assert db.scalars(select(ContractWorkflowRecord)).all() == []


def test_subcontract_contract_full_flow_with_gate_passes(db):
    _project(db)
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("SUB-EXEC", "5000000", "labour")])
    result = generate_contract_package(db, _subcontract_payload({"cost_code": "SUB-EXEC", "net_huf": "5000000"}), actor="api",)
    row = db.scalar(select(ContractWorkflowRecord).where(ContractWorkflowRecord.contract_id == result["contract_id"]))
    assert row is not None and row.status == "generated"
    commitments = list(db.scalars(select(FinanceCommitment)).all())
    assert len(commitments) == 1 and commitments[0].subject_id == row.contract_id


def test_customer_contracts_are_not_gated(db):
    import json as _json
    from pathlib import Path
    examples = Path(__file__).resolve().parents[1] / "integrations" / "contract_generator_v0_4" / "examples"
    payload = _json.loads((examples / "customer_construction_valid.json").read_text(encoding="utf-8"))
    payload["contract_number"] = f"UAT-CUST-{uuid.uuid4().hex[:8].upper()}"
    payload["ids"].update({"ProjectID": f"PRJ-CUST-{uuid.uuid4().hex[:8].upper()}"})
    for attachment in payload["attachments"]:
        attachment["file_id"] = f"EVIDENCE-{uuid.uuid4().hex[:8]}-{attachment['type']}"
    # Terv nélkül is átmegy: az ügyféloldali szerződés nem commitment-hordozó.
    result = generate_contract_package(db, payload, actor="api")
    assert result["contract_id"]


# --- Dashboard és API felületek ---


# --- AC-05: API-identitás-kötés (Review A HIGH) ---


def _previewed_import(client, project_id: str = PROJECT) -> str:
    import csv
    import io
    headers = [
        "cost_code", "category", "description", "amount", "currency", "cost_class",
        "direct_cost_component", "amount_basis", "is_summary_package", "parent_summary_line_id",
    ]
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(headers)
    writer.writerow(["MAT-X", "szerkezet", "Teszt sor", "1000", "", "direct", "material", "", "false", ""])
    # Task77 AC-03: a preview a bejelentkezett pénzügyi actorhoz kötött.
    _login(client, "finance@imperial.local")
    response = client.post("/api/budget-imports/preview", files={"file": ("budget.csv", buffer.getvalue().encode("utf-8-sig"), "text/csv")}, data={"project_id": project_id},)
    assert response.status_code == 200
    return response.json()["import_id"]


def _draft_plan_row(db, *, project_id: str, plan_id: str) -> None:
    db.add(ProjectFinancePlan(plan_id=plan_id, project_id=project_id, version=1, status="draft",
        currency="HUF", contract_revenue_net=Decimal("10000000"),
        created_by="fixture@imperial.local",))
    db.commit()


def test_budget_import_approve_api_requires_finance_actor(client, db):
    from app.models import AuditLog, ProjectBudgetImport
    import_id = _previewed_import(client)
    _draft_plan_row(db, project_id=PROJECT, plan_id="FIN-PLAN-API-01")
    # Generikus API token bejelentkezés nélkül nem ad platform-admin-t.
    client.cookies.clear()
    assert client.post(f"/api/budget-imports/{import_id}/approve", json={"plan_id": "FIN-PLAN-API-01"}).status_code == 401
    _login(client, "project-manager@imperial.local")
    assert client.post(f"/api/budget-imports/{import_id}/approve", json={"plan_id": "FIN-PLAN-API-01"}).status_code == 403
    _login(client, "finance@imperial.local")
    response = client.post(f"/api/budget-imports/{import_id}/approve", json={"plan_id": "FIN-PLAN-API-01"})
    assert response.status_code == 200, response.text
    row = db.scalar(select(ProjectBudgetImport).where(ProjectBudgetImport.import_id == import_id))
    assert row.approved_by == "finance@imperial.local"
    audit_row = db.scalar(select(AuditLog).where(AuditLog.action == "budget.import.approved"))
    assert audit_row is not None and audit_row.actor == "finance@imperial.local"
    # Task77 AC-03: a preview ugyanahhoz a pénzügyi actorhoz kötött; a valós
    # actor kerül az import-rekordba és az auditba (nem az "api").
    preview_files = {"file": ("budget.csv", b"cost_code;category;description;amount;currency;cost_class;direct_cost_component;amount_basis;is_summary_package;parent_summary_line_id\r\nMAT-X;szerkezet;Teszt sor;1000;;direct;material;;false;\r\n", "text/csv")}
    client.cookies.clear()
    assert client.post("/api/budget-imports/preview", files=preview_files, data={"project_id": PROJECT}).status_code == 401
    _login(client, "project-manager@imperial.local")
    assert client.post("/api/budget-imports/preview", files=preview_files, data={"project_id": PROJECT}).status_code == 403
    _login(client, "finance@imperial.local")
    preview_response = client.post("/api/budget-imports/preview", files=preview_files, data={"project_id": PROJECT})
    assert preview_response.status_code == 200, preview_response.text
    preview_row = db.scalar(select(ProjectBudgetImport).where(ProjectBudgetImport.import_id == preview_response.json()["import_id"]))
    assert preview_row.imported_by == "finance@imperial.local"
    preview_audit = db.scalar(select(AuditLog).where(AuditLog.action == "budget.import.previewed"))
    assert preview_audit is not None and preview_audit.actor == "finance@imperial.local"


def test_margin_gate_decisions_api_role_and_scope(client, db, monkeypatch):
    # Task77 AC-02 + Task78: a generikus token soha nem fedhet fel
    # keresztprojekt döntést; a lista az actor projektscope-jára szűrt —
    # a kötelező /api elérési úton is, azonos jogosultsági/szűrési lánccal.
    from app.models import MarginGateDecision
    for project_id, decision_id in ((PROJECT, "MGD-API-1"), ("TASK77-002", "MGD-API-2")):
        db.add(MarginGateDecision(decision_id=decision_id, project_id=project_id,
            plan_id=f"FIN-PLAN-{project_id}", plan_version=1,
            action_type="procurement_order_create",
            subject_type="procurement_selection", subject_id=f"SEL-{project_id}",
            proposed_net_huf=Decimal("1000"), decision="PASS",
            required_margin_percent=Decimal("35.00"),
            input_snapshot_json="{}", input_sha256="0" * 64,
            created_by="fixture@imperial.local", created_at=datetime.now(UTC),))
    db.commit()
    for path in ("/margin-gate/decisions", "/api/margin-gate/decisions"):
        client.cookies.clear()
        assert client.get(path).status_code == 401
        _login(client, "project-manager@imperial.local")
        assert client.get(path).status_code == 403
    _login(client, "finance@imperial.local")
    response = client.get("/margin-gate/decisions", params={"project_id": PROJECT})
    assert response.status_code == 200
    assert [d["decision_id"] for d in response.json()["decisions"]] == ["MGD-API-1"]
    api_response = client.get("/api/margin-gate/decisions", params={"project_id": PROJECT})
    assert api_response.status_code == 200
    assert [d["decision_id"] for d in api_response.json()["decisions"]] == ["MGD-API-1"]
    # Task78: szűkített projektkörű actor — a körön kívüli projekt kérése 403,
    # a lista csak a kör döntéseit adja vissza (keresztprojekt szivárgás tilos).
    monkeypatch.setattr("app.services.project_finance.finance_project_ids_for_user", lambda db, user: {PROJECT})
    monkeypatch.setattr("app.main.finance_project_ids_for_user", lambda db, user: {PROJECT})
    restricted = client.get("/api/margin-gate/decisions")
    assert restricted.status_code == 200
    assert [d["project_id"] for d in restricted.json()["decisions"]] == [PROJECT]
    assert client.get("/api/margin-gate/decisions", params={"project_id": "TASK77-002"}).status_code == 403


def test_budget_import_approve_api_rejects_cross_project_plan(client, db):
    import_id = _previewed_import(client, project_id=PROJECT)
    _draft_plan_row(db, project_id="MÁS-PROJEKT-001", plan_id="FIN-PLAN-API-02")
    _login(client, "finance@imperial.local")
    response = client.post(f"/api/budget-imports/{import_id}/approve", json={"plan_id": "FIN-PLAN-API-02"})
    assert response.status_code == 409


def test_budget_import_approve_requires_actor_project_access(client, db, monkeypatch):
    # Task78: a jóváhagyás az import projektjét ELŐSZÖR feloldja, és a
    # bejelentkezett actor hozzáférése az import PONTOS projektjéhez kötelező —
    # a szolgáltatás import-terv egyezése nem helyettesíti az actor-jogosultságot.
    from app.models import AuditLog, ProjectBudgetImport, ProjectFinanceBudgetLine
    import_id = _previewed_import(client, project_id="TASK77-002")
    _draft_plan_row(db, project_id="TASK77-002", plan_id="FIN-PLAN-API-03")
    monkeypatch.setattr("app.services.project_finance.finance_project_ids_for_user", lambda db, user: {PROJECT})
    monkeypatch.setattr("app.main.finance_project_ids_for_user", lambda db, user: {PROJECT})
    _login(client, "finance@imperial.local")
    response = client.post(f"/api/budget-imports/{import_id}/approve", json={"plan_id": "FIN-PLAN-API-03"})
    assert response.status_code == 403
    row = db.scalar(select(ProjectBudgetImport).where(ProjectBudgetImport.import_id == import_id))
    assert row.status == "preview" and row.approved_by is None
    plan = db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == "FIN-PLAN-API-03"))
    assert db.scalars(select(ProjectFinanceBudgetLine).where(ProjectFinanceBudgetLine.plan_id_fk == plan.id)).all() == []
    assert db.scalars(select(AuditLog).where(AuditLog.action == "budget.import.approved")).all() == []
    # A körön belüli projekt jóváhagyása változatlanul átmegy.
    in_scope = _previewed_import(client, project_id=PROJECT)
    _draft_plan_row(db, project_id=PROJECT, plan_id="FIN-PLAN-API-04")
    _login(client, "finance@imperial.local")
    assert client.post(f"/api/budget-imports/{in_scope}/approve", json={"plan_id": "FIN-PLAN-API-04"}).status_code == 200


def test_margin_gate_dashboard_scopes_to_authorized_projects(client, db, monkeypatch):
    # Task78: a HTML dashboard az actor engedélyezett projektkörét használja;
    # körön kívüli projekt kérése 403, keresztprojekt-döntés nem renderelődik.
    from app.models import MarginGateDecision
    for project_id, decision_id in ((PROJECT, "MGD-DASH-1"), ("TASK77-002", "MGD-DASH-2")):
        db.add(MarginGateDecision(decision_id=decision_id, project_id=project_id,
            plan_id=f"FIN-PLAN-{project_id}", plan_version=1,
            action_type="procurement_order_create",
            subject_type="procurement_selection", subject_id=f"SEL-{project_id}",
            proposed_net_huf=Decimal("1000"), decision="PASS",
            required_margin_percent=Decimal("35.00"),
            input_snapshot_json="{}", input_sha256="0" * 64,
            created_by="fixture@imperial.local", created_at=datetime.now(UTC),))
    db.commit()
    monkeypatch.setattr("app.services.project_finance.finance_project_ids_for_user", lambda db, user: {PROJECT})
    monkeypatch.setattr("app.main.finance_project_ids_for_user", lambda db, user: {PROJECT})
    _login(client, "finance@imperial.local")
    response = client.get("/margin-gate")
    assert response.status_code == 200
    assert PROJECT in response.text and "TASK77-002" not in response.text
    assert client.get("/margin-gate", params={"project_id": "TASK77-002"}).status_code == 403
    scoped = client.get("/margin-gate", params={"project_id": PROJECT})
    assert scoped.status_code == 200
    assert PROJECT in scoped.text and "TASK77-002" not in scoped.text
    # Teljes portfólió (pénzügyi/vezetői szerepkör): a szűrés feloldódik.
    monkeypatch.undo()
    full = client.get("/margin-gate")
    assert full.status_code == 200
    assert PROJECT in full.text and "TASK77-002" in full.text


def test_allocation_snapshot_api_binds_real_actor(client, db):
    from app.models import AuditLog, FinanceAllocationSnapshot
    from margin_gate_fixtures import get_line
    plan = seed_gate_plan(db, project_id=PROJECT, revenue="6000000", summary_lines=[{"cost_code": "PACK-API", "amount": "6000000", "amount_basis": "NET_REVENUE_ENVELOPE", "component": "other"}],)
    payload = {
        "plan_id": plan.plan_id,
        "summary_line_id": get_line(db, plan, "PACK-API").line_id,
        "source_type": "NORM_TABLE",
        "source_version": "NORM-API-1",
        "source_hash": "b" * 64,
        "rows": [{"trade_code": "TRADE-API", "direct_cost_component": "material", "normalized_ratio": "100"}],
        "rationale": "Szintetikus API allokáció a kapu teszthez.",
    }
    assert client.post("/api/allocation-snapshots", json=payload).status_code == 401
    _login(client, "project-manager@imperial.local")
    assert client.post("/api/allocation-snapshots", json=payload).status_code == 403
    _login(client, "finance@imperial.local")
    response = client.post("/api/allocation-snapshots", json=payload)
    assert response.status_code == 200, response.text
    snapshot = db.scalar(select(FinanceAllocationSnapshot))
    assert snapshot.approved_by == "finance@imperial.local"
    audit_row = db.scalar(select(AuditLog).where(AuditLog.action == "budget.allocation.snapshot_created"))
    assert audit_row is not None and audit_row.actor == "finance@imperial.local"
    # Task77 AC-01: a részletes-soros allokációs API ugyanazt a fail-closed
    # szerepköri + projekt-scope kötést követeli meg.
    from margin_gate_fixtures import add_child_line
    add_child_line(db, plan, cost_code="CHILD-API", amount="3000000",
                   component="labour", parent_summary_line_id=get_line(db, plan, "PACK-API").line_id)
    detailed_payload = {"plan_id": plan.plan_id, "summary_line_id": get_line(db, plan, "PACK-API").line_id,
                        "rationale": "Részletes sorokból épülő allokáció (Task77)."}
    client.cookies.clear()
    assert client.post("/api/allocation-snapshots/from-detailed-lines", json=detailed_payload).status_code == 401
    _login(client, "project-manager@imperial.local")
    assert client.post("/api/allocation-snapshots/from-detailed-lines", json=detailed_payload).status_code == 403
    _login(client, "finance@imperial.local")
    assert client.post("/api/allocation-snapshots/from-detailed-lines", json=detailed_payload).status_code == 200
