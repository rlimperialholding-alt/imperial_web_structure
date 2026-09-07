"""Task77 — a Task76 TENDERKAPU Gate7 (authorization/concurrency) találatok
determinisztikus remediációs tesztjei.

AC-01 allokációs projekt-scope segédek, AC-04 egy-döntés-egy-megrendelés
adatbázis-invariáns konkurens regresszióval, AC-05 import-jóváhagyás sorzár
+ draft-újraellenőrzés, AC-06 klónozás kétmenetes parent-remap, AC-07 0073
kényszer-proof. Az API-szintű jogosultság-tesztek (AC-01..AC-03) az
enforcement és gate tesztfájlokban élnek. Kizárólag szintetikus fixture-ek.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from margin_gate_fixtures import seed_gate_plan
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base, SessionLocal
from app.models import (ProcurementOffer,
    ProcurementOrderProjection,
    ProcurementRequirement,
    ProcurementSelection,
    ProjectBudgetImport,
    ProjectFinanceBudgetLine,
    ProjectFinancePlan,
    ProjectRegistry,)
from app.schemas import ProcurementOrderIn
from app.services import procurement as procurement_service
from app.services.budget_import import approve_budget_import, preview_budget_import
from app.services.project_finance import (clone_finance_plan, require_finance_plan_project_scope, require_project_finance_scope,)
from app.services.tender_margin_gate import MarginGateBlocked
from tests.test_budget_import import _csv_bytes, _draft_plan, _row


def _user(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _registry_row(db, project_id: str, responsible: str | None = None) -> None:
    if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id)):
        db.add(ProjectRegistry(project_id=project_id, name=f"{project_id} szintetikus projekt", responsible=responsible,))
        db.commit()


# --- AC-01: allokációs projekt-scope segédek (fail-closed) ---


def test_allocation_project_scope_helpers_fail_closed(db):
    _registry_row(db, "T77-SCOPE", responsible="pm-other@imperial.local")
    plan = seed_gate_plan(db, project_id="T77-SCOPE", revenue="6000000",
                          summary_lines=[{"cost_code": "PACK-S", "amount": "6000000",
                                          "amount_basis": "NET_REVENUE_ENVELOPE",
                                          "component": "other"}])
    with pytest.raises(PermissionError):
        require_finance_plan_project_scope(db, _user("project-manager", "pm-a@imperial.local"), plan.plan_id)
    with pytest.raises(PermissionError):
        require_project_finance_scope(db, _user("project-manager", "pm-a@imperial.local"), "T77-SCOPE")
    assert require_finance_plan_project_scope(db, _user("project-manager", "pm-other@imperial.local"), plan.plan_id).plan_id == plan.plan_id
    require_project_finance_scope(db, _user("finance"), "T77-SCOPE")
    with pytest.raises(KeyError):
        require_finance_plan_project_scope(db, _user("finance"), "NINCS-PLAN")


# --- AC-04: egy döntéshez legfeljebb egy megrendelés (konkurens regresszió) ---


def test_concurrent_order_creation_creates_at_most_one_order(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'task77-orders.db').as_posix()}", future=True, connect_args={"timeout": 30},)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as seed:
        seed_gate_plan(seed, project_id="T77-RACE", revenue="10000000", direct_lines=[("MAT-RACE", "6000000", "labour")],)
        seed.add(ProjectRegistry(project_id="T77-RACE", name="T77-RACE szintetikus projekt"))
        # Jóváhagyott döntés a versenyhelyzethez (a jóváhagyási lánc
        # bizonyítéka az enforcement tesztfájlban él).
        seed.add(ProcurementRequirement(requirement_id="REQ-RACE", project_id="T77-RACE", category="falazat",
            scope_description="Falazóanyag teljes mennyiség", specification="Tégla 30 N+F",
            net_quantity=Decimal("100"), waste_pct=Decimal("0"),
            max_orderable_quantity=Decimal("100"), unit="raklap",
            required_at=datetime.now(UTC) + timedelta(days=14),
            budget_huf=Decimal("7000000"), target_huf=Decimal("6000000"),
            cost_code="MAT-RACE", status="selected", created_by="owner@imperial.local"))
        seed.add(ProcurementOffer(offer_id="POFF-RACE", requirement_id="REQ-RACE", supplier_name="B Kft.",
            net_total_huf=Decimal("5000000"), delivery_cost_huf=Decimal("0"),
            other_landed_cost_huf=Decimal("0"), total_landed_cost_huf=Decimal("5000000"),
            lead_time_days=7, warranty_months=24, payment_terms="30 nap", risk_score=10,
            technical_compliant=True, document_ref="https://drive.example/b",
            status="selected", created_by="owner@imperial.local"))
        seed.add(ProcurementSelection(selection_id="PSEL-RACE", requirement_id="REQ-RACE", offer_id="POFF-RACE",
            total_landed_cost_huf=Decimal("5000000"), savings_pct=Decimal("16.6667"),
            rationale="Legjobb teljes leszállított költség", risk_rationale="Alacsony kockázat",
            status="approved", prepared_by="owner@imperial.local",
            finance_approved_by="finance@imperial.local",
            md_approved_by="managing-director@imperial.local"))
        seed.commit()
    data = ProcurementOrderIn(selection_id="PSEL-RACE", ordered_quantity=Decimal("100"),
                              delivery_due=datetime.now(UTC) + timedelta(days=5))
    s1 = factory()
    s2 = factory()
    original_gate = procurement_service.evaluate_commitment_gate
    calls: list[str] = []
    second_result: dict[str, ProcurementOrderProjection] = {}

    def gate_hook(db, **kwargs):
        calls.append("gate")
        if len(calls) == 1:
            # A második kísérlet TELJESEN lefut, míg az első tranzakció még
            # nem commitolt: mindkét existence-check üres rendelés-táblát lát —
            # ezt a versenyhelyzetet az uq_ops_procurement_orders_selection_id
            # kényszer zárja le atomi módon (kanonikus domain hibára képezve).
            second_result["order"] = procurement_service.create_order(s2, data, actor="owner@imperial.local")
        return original_gate(db, **kwargs)

    procurement_service.evaluate_commitment_gate = gate_hook
    try:
        with pytest.raises(ValueError, match="már készült megrendelés"):
            procurement_service.create_order(s1, data, actor="owner@imperial.local")
    finally:
        procurement_service.evaluate_commitment_gate = original_gate
    s1.close()
    s2.close()
    assert second_result["order"].order_id
    with factory() as check:
        orders = list(check.scalars(select(ProcurementOrderProjection).where(ProcurementOrderProjection.selection_id == "PSEL-RACE")).all())
        assert len(orders) == 1
        assert orders[0].order_id == second_result["order"].order_id


# --- AC-05: import-jóváhagyás sorzár + draft-újraellenőrzés ---


def test_import_approval_rechecks_draft_after_lock_acquisition(db):
    row = preview_budget_import(db, project_id="IMP-T77", file_name="budget.csv", data=_csv_bytes([_row("MAT-LOCK")]), actor="fixture@imperial.local",)
    plan = _draft_plan(db, project_id="IMP-T77", plan_id="FIN-PLAN-T77-LOCK")
    # Az actor sessionje már látta a draft tervet (elavult identitástérkép)…
    assert db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == plan.plan_id)).status == "draft"
    # …majd egy konkurens vezetői jóváhagyás jóváhagyottra állítja.
    with SessionLocal() as other:
        other_plan = other.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == plan.plan_id))
        other_plan.status = "approved"
        other.commit()
    with pytest.raises(MarginGateBlocked, match="draft"):
        approve_budget_import(db, import_id=row.import_id, plan_id=plan.plan_id,
                              actor="fixture-finance@imperial.local", actor_role="finance",
                              user=_user("finance", "fixture-finance@imperial.local"))
    # A jóváhagyott terv immutable maradt: egyetlen import-sor sem került rá.
    db.expire_all()
    fresh_plan = db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == plan.plan_id))
    assert fresh_plan.status == "approved"
    assert db.scalars(select(ProjectFinanceBudgetLine).where(ProjectFinanceBudgetLine.plan_id_fk == fresh_plan.id)).all() == []
    assert db.scalar(select(ProjectBudgetImport).where(ProjectBudgetImport.import_id == row.import_id)).status == "preview"


# --- AC-05b (Task78): konkurens jóváhagyás — sorok legfeljebb egyszer ---


def test_concurrent_import_approval_applies_lines_at_most_once(db):
    import json as _json
    from app.models import AuditLog
    from app.services import budget_import as budget_import_service
    row = preview_budget_import(db, project_id="IMP-T78", file_name="budget.csv",
        data=_csv_bytes([_row("MAT-T78-CONC", amount="1000000")]),
        actor="fixture@imperial.local",)
    plan = _draft_plan(db, project_id="IMP-T78", plan_id="FIN-PLAN-T78-CONC")
    # Deterministikus versenyhelyzet: az első jóváhagyás a tervzár megszerzése
    # után (a ProjectFinancePlan-selectnél) átengedi a második, teljes
    # jóváhagyást, amely commitol és approved-ra állítja az importot. Az első
    # tranzakció a zár UTÁNI újrazárolt sorállapot-ellenőrzésen bukik — az
    # import sorai legfeljebb egyszer kerülnek a tervre.
    original_select = budget_import_service.select
    fired = {"value": False}

    def select_hook(*args, **kwargs):
        # A select(Model) hívás a modellosztályt kapja argumentumként (a
        # .where() csak az eredményen fut) — a hook a célterv-zár kiválasztását
        # ismeri fel róla.
        if args and args[0] is ProjectFinancePlan and not fired["value"]:
            fired["value"] = True
            with SessionLocal() as other:
                approve_budget_import(other, import_id=row.import_id, plan_id=plan.plan_id, actor="other-finance@imperial.local", actor_role="finance", user=_user("finance", "other-finance@imperial.local"),)
        return original_select(*args, **kwargs)

    budget_import_service.select = select_hook
    try:
        with pytest.raises(MarginGateBlocked, match="preview"):
            approve_budget_import(db, import_id=row.import_id, plan_id=plan.plan_id, actor="first-finance@imperial.local", actor_role="finance", user=_user("finance", "first-finance@imperial.local"),)
    finally:
        budget_import_service.select = original_select
    db.expire_all()
    fresh_row = db.scalar(select(ProjectBudgetImport).where(ProjectBudgetImport.import_id == row.import_id))
    assert fresh_row.status == "approved"
    assert fresh_row.approved_by == "other-finance@imperial.local"
    lines = list(db.scalars(select(ProjectFinanceBudgetLine).where(ProjectFinanceBudgetLine.plan_id_fk == plan.id)).all())
    assert [line.cost_code for line in lines] == ["MAT-T78-CONC"]
    provenance = _json.loads(db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == plan.plan_id)).provenance_json)
    assert len(provenance["budget_imports"]) == 1
    audit_rows = list(db.scalars(select(AuditLog).where(AuditLog.action == "budget.import.approved")).all())
    assert len(audit_rows) == 1
    assert audit_rows[0].actor == "other-finance@imperial.local"


# --- AC-06: klónozás kétmenetes parent-remap (gyerek a szülő ELŐTT) ---


def test_clone_remaps_parent_when_child_precedes_parent_in_collection(db):
    _registry_row(db, "T77-CLONE")
    plan = seed_gate_plan(db, project_id="T77-CLONE", revenue="10000000")
    # A gyerek előbb jön létre (kisebb id → a kollekcióban ELŐBB áll); a régi
    # egymenetes remap itt None-t adott volna.
    db.add(ProjectFinanceBudgetLine(line_id="FIN-LINE-T77-CHILD", plan_id_fk=plan.id, cost_code="CHILD-CODE",
        category="direct", description="Szintetikus gyereksor",
        budget_net=Decimal("1000000"), cost_class="direct",
        direct_cost_component="labour",
        parent_summary_line_id="FIN-LINE-T77-PARENT", currency="HUF",))
    db.add(ProjectFinanceBudgetLine(line_id="FIN-LINE-T77-PARENT", plan_id_fk=plan.id, cost_code="PARENT-CODE",
        category="direct", description="Szintetikus összegző szülősor",
        budget_net=Decimal("6000000"), cost_class="direct",
        direct_cost_component="other", amount_basis="NET_REVENUE_ENVELOPE",
        is_summary_package=True, currency="HUF",))
    db.commit()
    clone = clone_finance_plan(db, plan.plan_id, _user("owner"))
    cloned = list(db.scalars(select(ProjectFinanceBudgetLine).where(ProjectFinanceBudgetLine.plan_id_fk == clone.id)).all())
    by_code = {line.cost_code: line for line in cloned}
    assert by_code["CHILD-CODE"].parent_summary_line_id == by_code["PARENT-CODE"].line_id
    assert by_code["CHILD-CODE"].parent_summary_line_id != "FIN-LINE-T77-PARENT"


# --- AC-07: 0073 migráció kényszer-proof (futás idejű séma; a statikus
# --- forráskód-állítások a Task78 remediációs migrációtesztjében élnek) ---


def test_migration_0073_adds_and_enforces_order_selection_unique_constraint(db):
    # Futás idejű séma: modell-metaadat és tesztadatbázis is hordozza a
    # kényszert; a nyers duplikált INSERT a kényszeren bukik.
    names = {
        constraint.get("name")
        for constraint in inspect(db.get_bind()).get_unique_constraints("ops_procurement_orders")
    }
    assert "uq_ops_procurement_orders_selection_id" in names
    model_names = {c.name for c in ProcurementOrderProjection.__table__.constraints}
    assert "uq_ops_procurement_orders_selection_id" in model_names
    with pytest.raises(IntegrityError):
        with SessionLocal() as other:
            other.add(ProcurementOrderProjection(order_id="PO-T77-DUP-1", project_id="P-DUP",
                supplier_name="S-DUP", item_summary="X", status="ordered",
                selection_id="SEL-DUP",))
            other.add(ProcurementOrderProjection(order_id="PO-T77-DUP-2", project_id="P-DUP",
                supplier_name="S-DUP", item_summary="X", status="ordered",
                selection_id="SEL-DUP",))
            other.commit()
