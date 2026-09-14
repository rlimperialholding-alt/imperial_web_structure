from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.database import SessionLocal
from app.models import ProjectRegistry
from app.schemas import (
    DeliveryNoteIn,
    ProcurementInvoiceMatchIn,
    ProcurementOfferIn,
    ProcurementOrderIn,
    ProcurementRequirementIn,
    ProcurementSelectionIn,
)
from app.services.operations import create_delivery_note
from app.services.procurement import (
    add_offer,
    approve_requirement,
    approve_selection,
    confirm_order,
    create_invoice_match,
    create_order,
    create_requirement,
    select_offer,
)


def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    project_id = f"PROC-UAT-{stamp}"
    with SessionLocal() as db:
        db.add(ProjectRegistry(
            project_id=project_id, name=f"Procurement UAT {stamp}",
            customer_name="Imperial belső UAT", project_type="Aktív kivitelezés",
            status="active", risk_level="green", blocked=False,
            responsible="UAT Projektmenedzser", next_action="Beszerzési folyamat lezárása",
        ))
        db.commit()
        requirement = create_requirement(db, ProcurementRequirementIn(
            project_id=project_id, category="falazat", scope_description="UAT falazóanyag",
            specification="Tégla 30 N+F", net_quantity=Decimal("100"), waste_pct=Decimal("5"),
            unit="raklap", required_at=datetime.now(timezone.utc) + timedelta(days=14),
            budget_huf=Decimal("11000000"), target_huf=Decimal("10000000"),
        ), "uat.pm@imperial.local")
        approve_requirement(db, requirement.requirement_id, "technical", "uat.technical@imperial.local", "technical-prep")
        approve_requirement(db, requirement.requirement_id, "budget_cash", "uat.finance@imperial.local", "finance")
        add_offer(db, ProcurementOfferIn(
            requirement_id=requirement.requirement_id, supplier_name="UAT A Beszállító Kft.",
            net_total_huf=Decimal("9200000"), payment_terms="30 nap", risk_score=20,
            technical_compliant=True, document_ref="https://drive.example/uat-offer-a",
        ), "uat.pm@imperial.local")
        chosen = add_offer(db, ProcurementOfferIn(
            requirement_id=requirement.requirement_id, supplier_name="UAT B Beszállító Kft.",
            net_total_huf=Decimal("8500000"), payment_terms="30 nap", risk_score=10,
            technical_compliant=True, document_ref="https://drive.example/uat-offer-b",
        ), "uat.pm@imperial.local")
        selection = select_offer(db, ProcurementSelectionIn(
            requirement_id=requirement.requirement_id, offer_id=chosen.offer_id,
            rationale="Legjobb teljes bekerülési költség.", risk_rationale="Alacsony ellenőrzött kockázat.",
        ), "uat.pm@imperial.local")
        approve_selection(db, selection.selection_id, "finance", "uat.finance@imperial.local", "finance")
        approve_selection(db, selection.selection_id, "managing_director", "uat.md@imperial.local", "managing-director")
        order = create_order(db, ProcurementOrderIn(
            selection_id=selection.selection_id, ordered_quantity=Decimal("105"),
            delivery_due=datetime.now(timezone.utc) + timedelta(days=10),
        ), "uat.pm@imperial.local")
        confirm_order(db, order.order_id, "uat.supplier@imperial.local")
        delivery, lot = create_delivery_note(db, DeliveryNoteIn(
            order_id=order.order_id, project_id=project_id, note_number=f"DN-{stamp}",
            receiver="UAT Projektmenedzser", item_summary="UAT falazóanyag",
            ordered_quantity=Decimal("105"), received_quantity=Decimal("105"), unit="raklap",
            actual_specification="Tégla 30 N+F", quality_status="accepted", plan_match="matched",
            document_status="complete", performance_declaration_status="complete",
            elog_evidence_status="complete", supplier_signed=True, receiver_signed=True,
            signature_evidence_ref="https://drive.example/uat-signed-delivery",
            storage_location="UAT depó", custodian="UAT Projektmenedzser", weather_protection="adequate",
        ), "uat.pm@imperial.local")
        match = create_invoice_match(db, ProcurementInvoiceMatchIn(
            order_id=order.order_id, delivery_note_id=delivery.delivery_note_id,
            invoice_reference=f"INV-{stamp}", invoice_total_huf=Decimal("8500000"),
        ), "uat.finance@imperial.local")
        print(f"project={project_id}")
        print(f"requirement={requirement.requirement_id} status={requirement.status}")
        print(f"selection={selection.selection_id} savings_pct={selection.savings_pct}")
        print(f"order={order.order_id} confirmation={order.confirmation_status} sha256={order.content_sha256}")
        print(f"delivery={delivery.delivery_note_id} lot={lot.lot_id if lot else None}")
        print(f"invoice_match={match.match_id} status={match.status} payment_ready={match.payment_ready}")


if __name__ == "__main__":
    main()
