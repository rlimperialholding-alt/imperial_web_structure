from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models import (
    ProcurementDeviation,
    ProcurementInvoiceMatch,
    ProcurementOrderProjection,
    ProcurementRequirement,
    ProcurementSelection,
    OutboxMessage,
    ProjectRegistry,
)
from app.services.procurement import approve_selection


def seed_project(db, project_id: str = "IMP-PROC-001") -> None:
    db.add(ProjectRegistry(
        project_id=project_id, name="Procurement tesztprojekt", customer_name="Teszt Ügyfél",
        project_type="Aktív kivitelezés", status="active", risk_level="green", blocked=False,
        responsible="Teszt PM", next_action="Beszerzési igény",
    ))
    db.commit()


def create_approved_requirement(client, db, *, target: str = "10000000", budget: str = "11000000") -> str:
    seed_project(db)
    response = client.post("/api/procurement/requirements", json={
        "project_id": "IMP-PROC-001", "category": "falazat",
        "scope_description": "Falazóanyag teljes mennyiség", "specification": "Tégla 30 N+F",
        "net_quantity": "100", "waste_pct": "5", "unit": "raklap",
        "required_at": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
        "budget_huf": budget, "target_huf": target,
    })
    assert response.status_code == 200, response.text
    requirement_id = response.json()["requirement_id"]
    assert client.post(f"/api/procurement/requirements/{requirement_id}/approvals/technical").status_code == 200
    response = client.post(f"/api/procurement/requirements/{requirement_id}/approvals/budget_cash")
    assert response.status_code == 200 and response.json()["status"] == "ready_for_tender"
    return requirement_id


def add_offer(client, requirement_id: str, supplier: str, total: str) -> str:
    response = client.post("/api/procurement/offers", json={
        "requirement_id": requirement_id, "supplier_name": supplier,
        "net_total_huf": total, "delivery_cost_huf": "0", "other_landed_cost_huf": "0",
        "lead_time_days": 7, "warranty_months": 24, "payment_terms": "30 nap",
        "risk_score": 15, "technical_compliant": True,
        "document_ref": f"https://drive.example/{supplier}",
    })
    assert response.status_code == 200, response.text
    return response.json()["offer_id"]


def create_approved_selection(client, requirement_id: str, offer_id: str) -> str:
    response = client.post("/api/procurement/selections", json={
        "requirement_id": requirement_id, "offer_id": offer_id,
        "rationale": "Legjobb teljes bekerülési költség és megfelelő műszaki tartalom.",
        "risk_rationale": "Alacsony szállítási és partnerkockázat.",
    })
    assert response.status_code == 200, response.text
    selection_id = response.json()["selection_id"]
    assert client.post(f"/api/procurement/selections/{selection_id}/approvals/finance").status_code == 200
    response = client.post(f"/api/procurement/selections/{selection_id}/approvals/managing_director")
    assert response.status_code == 200 and response.json()["status"] == "approved"
    return selection_id


def test_end_to_end_requirement_order_receipt_and_three_way_match(client, db):
    requirement_id = create_approved_requirement(client, db)
    add_offer(client, requirement_id, "A Beszállító Kft.", "9200000")
    selected_offer = add_offer(client, requirement_id, "B Beszállító Kft.", "8500000")
    selection_id = create_approved_selection(client, requirement_id, selected_offer)

    order = client.post("/api/procurement/orders", json={
        "selection_id": selection_id, "ordered_quantity": "105",
        "delivery_due": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
    })
    assert order.status_code == 200, order.text
    order_id = order.json()["order_id"]
    assert len(order.json()["content_sha256"]) == 64
    assert client.post(f"/api/procurement/orders/{order_id}/confirm").json()["confirmation_status"] == "confirmed"

    delivery = client.post("/api/procurement/delivery-notes", json={
        "order_id": order_id, "project_id": "IMP-PROC-001", "receiver": "Teszt PM",
        "item_summary": "Falazóanyag teljes mennyiség", "ordered_quantity": "105",
        "received_quantity": "105", "unit": "raklap", "actual_specification": "Tégla 30 N+F",
        "plan_match": "matched", "quality_status": "accepted", "document_status": "complete",
        "performance_declaration_status": "complete", "elog_evidence_status": "complete",
        "supplier_signed": True, "receiver_signed": True,
        "signature_evidence_ref": "https://drive.example/signed-delivery-note",
    })
    assert delivery.status_code == 200, delivery.text
    match = client.post("/api/procurement/invoice-matches", json={
        "order_id": order_id, "delivery_note_id": delivery.json()["delivery_note_id"],
        "invoice_reference": "INV-PROC-001", "invoice_total_huf": "8500000",
    })
    assert match.status_code == 200, match.text
    assert match.json()["payment_ready"] is True and match.json()["blockers"] == []
    stored = db.scalar(select(ProcurementInvoiceMatch).where(ProcurementInvoiceMatch.invoice_reference == "INV-PROC-001"))
    assert stored.status == "payment_ready"
    destinations = db.scalars(select(OutboxMessage.destination_module)).all()
    assert destinations.count("finance") >= 2 and "smart-calendar" in destinations


def test_order_quantity_and_approval_gates_fail_closed(client, db):
    requirement_id = create_approved_requirement(client, db)
    first = add_offer(client, requirement_id, "Első Kft.", "9500000")
    single = client.post("/api/procurement/selections", json={
        "requirement_id": requirement_id, "offer_id": first,
        "rationale": "Egy ajánlat", "risk_rationale": "Teszt",
    })
    assert single.status_code == 409
    second = add_offer(client, requirement_id, "Második Kft.", "8500000")
    selection = client.post("/api/procurement/selections", json={
        "requirement_id": requirement_id, "offer_id": second,
        "rationale": "Legjobb TLC", "risk_rationale": "Alacsony kockázat",
    }).json()["selection_id"]
    assert client.post("/api/procurement/orders", json={"selection_id": selection, "ordered_quantity": "100", "delivery_due": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()}).status_code == 409
    assert client.post(f"/api/procurement/selections/{selection}/approvals/finance").status_code == 200
    assert client.post(f"/api/procurement/selections/{selection}/approvals/managing_director").status_code == 200
    excessive = client.post("/api/procurement/orders", json={"selection_id": selection, "ordered_quantity": "105.0001", "delivery_due": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()})
    assert excessive.status_code == 409


def test_above_twenty_million_requires_distinct_owner_approval(client, db):
    requirement_id = create_approved_requirement(client, db, target="30000000", budget="30000000")
    add_offer(client, requirement_id, "A Nagy Kft.", "28000000")
    chosen = add_offer(client, requirement_id, "B Nagy Kft.", "26000000")
    response = client.post("/api/procurement/selections", json={
        "requirement_id": requirement_id, "offer_id": chosen,
        "rationale": "Legjobb TLC", "risk_rationale": "Ellenőrzött kockázat",
        "market_evidence_ref": "https://drive.example/market-evidence",
    })
    assert response.json()["dual_approval_required"] is True
    selection_id = response.json()["selection_id"]
    assert client.post(f"/api/procurement/selections/{selection_id}/approvals/finance").status_code == 200
    assert client.post(f"/api/procurement/selections/{selection_id}/approvals/managing_director").json()["status"] == "approval_pending"
    row = db.scalar(select(ProcurementSelection).where(ProcurementSelection.selection_id == selection_id))
    try:
        approve_selection(db, selection_id, "owner", row.md_approved_by, "owner")
        assert False, "same actor must not satisfy dual approval"
    except ValueError:
        db.rollback()
    assert client.post(f"/api/procurement/selections/{selection_id}/approvals/owner").json()["status"] == "approved"


def test_variance_creates_owned_deviation_and_blocks_invoice(client, db):
    requirement_id = create_approved_requirement(client, db)
    add_offer(client, requirement_id, "A Kft.", "9000000")
    selected = add_offer(client, requirement_id, "B Kft.", "8500000")
    selection_id = create_approved_selection(client, requirement_id, selected)
    order = client.post("/api/procurement/orders", json={"selection_id": selection_id, "ordered_quantity": "100", "delivery_due": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()}).json()
    client.post(f"/api/procurement/orders/{order['order_id']}/confirm")
    delivery = client.post("/api/procurement/delivery-notes", json={
        "order_id": order["order_id"], "project_id": "IMP-PROC-001", "receiver": "Teszt PM",
        "item_summary": "Falazóanyag", "ordered_quantity": "100", "received_quantity": "90", "unit": "raklap",
        "actual_specification": "Tégla 30 N+F", "plan_match": "variance", "quality_status": "accepted",
        "document_status": "complete", "performance_declaration_status": "complete", "elog_evidence_status": "complete",
        "supplier_signed": True, "receiver_signed": True, "signature_evidence_ref": "https://drive.example/signed",
    })
    assert delivery.status_code == 200, delivery.text
    deviation = db.scalar(select(ProcurementDeviation).where(ProcurementDeviation.order_id == order["order_id"]))
    assert deviation and deviation.owner == "Teszt PM" and deviation.status == "open"
    match = client.post("/api/procurement/invoice-matches", json={"order_id": order["order_id"], "delivery_note_id": delivery.json()["delivery_note_id"], "invoice_reference": "INV-BLOCKED", "invoice_total_huf": "8000000"})
    assert match.json()["payment_ready"] is False
    assert {"quantity_variance", "open_deviation"}.issubset(set(match.json()["blockers"]))


def test_procurement_ui_contains_every_operational_input(logged_in_client, db):
    seed_project(db)
    response = logged_in_client.get("/procurement/projects/IMP-PROC-001")
    assert response.status_code == 200
    for marker in (
        "Beszerzési követelmény", "Total landed cost összehasonlítás", "Beszerzési döntés előkészítése",
        "Jóváhagyott kiválasztásból", "Aláírt szállítólevél", "Háromoldalú egyeztetés",
        "Műszaki termékhelyettesítés", "Készlet és tételkövetés",
    ):
        assert marker in response.text
