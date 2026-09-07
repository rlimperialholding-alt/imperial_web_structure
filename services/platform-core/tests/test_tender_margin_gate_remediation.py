"""A Task75 független review-k (A/B) találatainak remediációs tesztjei.

C1 (Postgres FK-holtpont), H1 (lekötés-átkötés tervverzióváltáskor),
M1 (részleges tartalék-allokáció), M3/HIGH-1 (award→PO-prep kettős
számolás), M3/MEDIUM-3 (második rendelés), MEDIUM-2 (csomagok közötti
szakágkód-ütközés), LOW-1/2/3/4 rések. Kizárólag szintetikus fixture-ek.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from margin_gate_fixtures import get_line, seed_gate_plan
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (ContractWorkflowRecord, FinanceCommitment, MarginGateDecision, ProjectFinanceBudgetLine, ProjectFinancePlan,)
from app.services.budget_allocation import create_allocation_snapshot
from app.services.commercial_integration import generate_contract_package
from app.services.contract_workflow import (record_contract_dispatch, record_signed_contract, review_contract, submit_contract_review,)
from app.services.project_finance import leadership_approve_plan
from app.services.tender_margin_gate import (MarginGateBlocked, evaluate_commitment_gate, plan_content_sha256,)

PROJECT = "REMED-001"


def _user(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


# --- AC-06 (Task78): a 0073 downgrade pontosan a 0072-es head sémát állítja vissza ---


def _load_migration_module():
    import importlib.util
    from pathlib import Path
    migration_path = (Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260907_0073_tender_margin_gate.py")
    spec = importlib.util.spec_from_file_location("migration_20260907_0073", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration, migration_path


def test_migration_0073_downgrade_restores_previous_schema_exactly():
    from pathlib import Path
    migration, migration_path = _load_migration_module()
    order = list(migration._DOWNGRADE_DROP_ORDER)
    assert set(order) == set(migration._NEW_TABLES)
    # Az FK-függő gyerektáblák a szülők ELŐTT törlődnek, különben a
    # PostgreSQL RESTRICT a downgrade-ot elutasítaná (Review B MEDIUM).
    assert order.index("finance_allocation_snapshot_rows") < order.index("finance_allocation_snapshots")
    # Task78: az upgrade által hozzáadott egyedi kényszert a downgrade
    # guarddal eldobja (re-upgrade idempotens), mégpedig a függő táblák
    # eldobása ELŐTT — a végső séma azonos a 0072-es headdel.
    source = Path(migration_path).read_text(encoding="utf-8")
    assert "_drop_unique_constraint_if_exists" in source
    assert 'batch_op.drop_constraint(name, type_="unique")' in source
    assert "uq_ops_procurement_orders_selection_id" in source
    assert source.index("_drop_unique_constraint_if_exists(") < source.index("op.drop_table")


def test_migration_0073_upgrade_downgrade_reupgrade_and_row_refusal(tmp_path):
    # Futás idejű lánc (a kanonikus alembic-futtatási kontextusban, izolált
    # alprocesszben — az env.py importkészletével): upgrade head → üzleti soros
    # downgrade fail-closed elutasítás (részleges visszaállítás nélkül) → üres
    # downgrade → re-upgrade.
    import os
    import subprocess
    import sys
    from datetime import UTC, datetime
    from pathlib import Path
    import sqlalchemy as sa
    from sqlalchemy import create_engine
    repo = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "migration-0073.db"
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{db_path.as_posix()}")

    def run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=repo, env=env, capture_output=True, text=True, timeout=300,)

    def expect_ok(*args: str) -> None:
        completed = run_alembic(*args)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def unique_constraint_names():
        return {c.get("name") for c in sa.inspect(engine).get_unique_constraints("ops_procurement_orders")}

    def table_names():
        return set(sa.inspect(engine).get_table_names())

    imports_table = sa.table("finance_budget_imports",
        sa.column("import_id"), sa.column("project_id"), sa.column("file_name"),
        sa.column("source_format"), sa.column("content_sha256"), sa.column("preview_sha256"),
        sa.column("row_count"), sa.column("amount_basis"), sa.column("currency"),
        sa.column("status"), sa.column("preview_json"), sa.column("error_json"),
        sa.column("imported_by"), sa.column("created_at"),)
    expect_ok("upgrade", "20260907_0073")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    assert "uq_ops_procurement_orders_selection_id" in unique_constraint_names()
    assert "finance_budget_imports" in table_names()
    # Üzleti sor: a downgrade elutasít, sem tábla, sem kényszer nem tűnik el.
    with engine.connect() as connection:
        connection.execute(imports_table.insert().values(import_id="BIMP-MIG-ROW", project_id="MIG-1", file_name="b.csv",
            source_format="csv", content_sha256="0" * 64, preview_sha256="0" * 64,
            row_count=1, amount_basis="NET_REVENUE_ENVELOPE", currency="HUF",
            status="preview", preview_json="{}", error_json="[]",
            imported_by="fixture@imperial.local", created_at=datetime.now(UTC),))
        connection.commit()
    refused = run_alembic("downgrade", "20260816_0072")
    assert refused.returncode != 0
    assert "0073 downgrade refused" in refused.stdout + refused.stderr
    assert "finance_budget_imports" in table_names()
    assert "uq_ops_procurement_orders_selection_id" in unique_constraint_names()
    # Üres állapot: a downgrade a kényszert és az új táblákat is eldobja.
    with engine.connect() as connection:
        connection.execute(imports_table.delete())
        connection.commit()
    expect_ok("downgrade", "20260816_0072")
    assert "finance_budget_imports" not in table_names()
    assert "uq_ops_procurement_orders_selection_id" not in unique_constraint_names()
    # A re-upgrade determinisztikusan helyreállítja a teljes sémát.
    expect_ok("upgrade", "20260907_0073")
    assert "finance_budget_imports" in table_names()
    assert "uq_ops_procurement_orders_selection_id" in unique_constraint_names()
    engine.dispose()


def _evaluate(db, *, cost_code="MAT-A", amount="100", subject_id="S-1", project=PROJECT):
    return evaluate_commitment_gate(db,
        project_id=project,
        action_type="tender_award",
        subject_type="tender_bid",
        subject_id=subject_id,
        cost_code=cost_code,
        proposed_net_huf=Decimal(amount),
        actor="fixture@imperial.local",)


# --- C1: a BLOCK-bizonyíték FK-mentes (nincs plan_id_fk) ---


def test_block_and_pass_decision_evidence_plan_fk_contract(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6501000", "material")])
    with pytest.raises(MarginGateBlocked):
        _evaluate(db, amount="100")
    rows = list(db.scalars(select(MarginGateDecision)).all())
    assert rows and rows[0].decision == "BLOCK"
    # A független bizonyíték-tranzakció nem hivatkozza az FK-n a tervsort
    # (a hívó FOR UPDATE zárja alatt a Postgres FK-ellenőrzés holtpontra
    # futna); a tervazonosítás a szöveges mezőkön át történik.
    assert rows[0].plan_id_fk is None
    assert rows[0].plan_id and rows[0].plan_version == 1
    assert rows[0].plan_content_sha256
    # A PASS-döntés a hívó tranzakciójában megtartja az FK-t.
    seed_gate_plan(db, project_id="REMED-002", revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")], plan_id="FIN-PLAN-REMED-PASS", version=1,)
    decision = _evaluate(db, project="REMED-002", amount="100")
    db.commit()
    assert decision.plan_id_fk is not None


def _v2_plan(db, plan_id: str, direct_codes: list[str]) -> ProjectFinancePlan:
    """finance_approved v2 terv a teljes jóváhagyási lánc-követelményekkel."""
    from app.models import ProjectFinanceCashflowLine
    v2 = ProjectFinancePlan(plan_id=plan_id, project_id=PROJECT, version=2, status="finance_approved",
        currency="HUF", contract_revenue_net=Decimal("10000000"),
        approved_change_revenue_net=Decimal("0"), contingency_net=Decimal("0"),
        target_margin_percent=Decimal("35"), submitted_by="submitter@imperial.local",
        finance_approved_by="finance@imperial.local", created_by="fixture@imperial.local",)
    db.add(v2)
    db.flush()
    for code in direct_codes:
        db.add(ProjectFinanceBudgetLine(line_id=f"FIN-LINE-{plan_id}-{code}", plan_id_fk=v2.id, cost_code=code,
            category="direct", description=f"v2 {code} sor", budget_net=Decimal("6500000"),
            estimate_to_complete_net=Decimal("6500000"), cost_class="direct",
            direct_cost_component="material", currency="HUF",))
    db.add(ProjectFinanceCashflowLine(flow_id=f"FIN-FLOW-{plan_id}-IN", plan_id_fk=v2.id,
        period_date=datetime.now(UTC).date(), direction="inflow",
        category="bevétel", description="v2 bevétel", amount_net=Decimal("10000000"),))
    db.add(ProjectFinanceCashflowLine(flow_id=f"FIN-FLOW-{plan_id}-OUT", plan_id_fk=v2.id,
        period_date=datetime.now(UTC).date(), direction="outflow",
        category="kiadás", description="v2 kiadás", amount_net=Decimal("6500000"),))
    v2.content_sha256 = plan_content_sha256(v2)
    db.commit()
    return v2


# --- H1: tervverzió-jóváhagyás átköti a lekötéseket ---


def test_leadership_approval_rebinds_commitments_to_new_plan(db):
    plan_v1 = seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    _evaluate(db, subject_id="OLD-COMMIT", amount="6500000")
    db.commit()
    v2 = _v2_plan(db, "FIN-PLAN-REMED-02", ["MAT-A"])
    leadership_approve_plan(db, v2.plan_id, _user("managing-director", "md@imperial.local"), note="Vezetői jóváhagyás a remediációs teszthez.", margin_exception_reason="",)
    db.expire_all()
    assert db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == plan_v1.plan_id)).status == "superseded"
    commitment = db.scalar(select(FinanceCommitment))
    assert commitment.plan_id_fk == v2.id
    # A v2-n értékelt ÚJ tárgy a régi lekötést is a vetületbe számítja:
    # 6.5M régi + 100 új → (10M − 6.5001M)/10M = 34.999% → BLOCK.
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, subject_id="NEW-COMMIT", amount="100")
    assert excinfo.value.reason_code == "margin_below_minimum"
    db.rollback()


def test_leadership_approval_blocks_orphan_commitment_codes(db):
    # Review A CRITICAL: a v2 tervből hiányzik a v1-en lekötött MAT-A
    # költségkód — a jóváhagyás az aktiválás ELŐTT fail-closed blokkol,
    # különben a lekötés kikerülne a fedezetszámításból (fail-open).
    plan_v1 = seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    _evaluate(db, subject_id="ORPHAN-COMMIT", amount="100000")
    db.commit()
    v2 = _v2_plan(db, "FIN-PLAN-REMED-03", ["MAT-B"])
    with pytest.raises(ValueError, match="MAT-A"):
        leadership_approve_plan(db, v2.plan_id, _user("managing-director", "md@imperial.local"), note="Vezetői jóváhagyás árva költségkóddal.", margin_exception_reason="",)
    db.rollback()
    # A blokkolt aktiválás után a régi terv jóváhagyott marad, a lekötés a
    # régi tervhez kötött, az új terv nem aktiválódott.
    assert db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == plan_v1.plan_id)).status == "approved"
    assert db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == v2.plan_id)).status == "finance_approved"
    commitment = db.scalar(select(FinanceCommitment))
    assert commitment.plan_id_fk == plan_v1.id


def test_gate_counts_orphan_commitment_conservatively(db):
    # Defense-in-depth: ha mégis árva lekötés kerülne a tervhez (pl. migrált
    # állapot), a kapu annak TELJES összegét a várható direct költségbe
    # számítja — soha nem tűnhet el a fedezetszámításból.
    plan = seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    db.add(FinanceCommitment(commitment_id="FCOMMIT-ORPHAN", plan_id_fk=plan.id, cost_code="GHOST-CODE",
        subject_type="tender_bid", subject_id="GHOST-1", net_huf=Decimal("100000"),
        currency="HUF", status="committed", created_by="fixture@imperial.local",))
    db.commit()
    # (10M − (6.5M + 0.1M)) / 10M = 34.00 → BLOCK: az árva 100k a vetületben.
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, subject_id="NEW-1", amount="100")
    assert excinfo.value.reason_code == "margin_below_minimum"
    assert excinfo.value.margin_percent == Decimal("34.00")
    import json as _json
    evidence = list(db.scalars(select(MarginGateDecision)).all())
    calc = _json.loads(evidence[-1].calculation_json)
    assert calc["orphan_codes"] == ["GHOST-CODE"]
    assert calc["orphan_committed_direct"] == "100000.00"
    db.rollback()


# --- M1: tartalék-allokáció (részleges eset a canonic gate-tesztben is) ---


def test_full_contingency_allocation_counts_line_amount(db):
    plan = seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")], contingency="1000000")
    db.add(ProjectFinanceBudgetLine(line_id="FIN-LINE-CONT-FULL",
        plan_id_fk=plan.id,
        cost_code="CONTINGENCY-FULL",
        category="contingency",
        description="Teljes tartalék-allokáció",
        budget_net=Decimal("1000000"),
        cost_class="direct",
        direct_cost_component="other",
        currency="HUF",))
    db.commit()
    # (10M − (6.5M + 1.0M)) / 10M = 25% → BLOCK: a teljes keret a vetületben.
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, cost_code="MAT-A", amount="100")
    assert excinfo.value.reason_code == "margin_below_minimum"
    assert excinfo.value.margin_percent == Decimal("25.00")
    db.rollback()


# --- max() második és harmadik ága ---


@pytest.mark.parametrize("mutator,expected_margin",
    [
        # post = max(6M, actual 5M + ETC 2M) = 7M → 30% → BLOCK.
        (lambda line: (setattr(line, "actual_net", Decimal("5000000")), setattr(line, "estimate_to_complete_net", Decimal("2000000"))), "30.00"),
        # post = max(6M, committed_baseline 6.5M) = 6.5M → 35.00; a 100 új
        # lekötéssel 6.5001M → 34.999 → BLOCK (megjelenítve 35.00).
        (lambda line: setattr(line, "committed_net", Decimal("6500000")), "35.00"),
    ],)
def test_max_branches_dominate_projection(db, mutator, expected_margin):
    plan = seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6000000", "material")])
    mutator(get_line(db, plan, "MAT-A"))
    plan.content_sha256 = plan_content_sha256(plan)
    db.commit()
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, amount="100")
    assert excinfo.value.reason_code == "margin_below_minimum"
    assert excinfo.value.margin_percent == Decimal(expected_margin)
    db.rollback()


# --- Üres költségvetés és nagyon nagy blokk-határ ---


def test_empty_budget_plan_blocks_with_explicit_reason(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[])
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db)
    assert excinfo.value.reason_code == "empty_budget"


def test_very_large_decimal_block_boundary(db):
    # SQLite NUMERIC-affinitás miatt az értékek float64-pontosak maradnak
    # (Postgres Numeric(18,2)-ben egzaktak); a határ 35.00 alá visz.
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000000000000", direct_lines=[("MAT-A", "6500000000000001", "material")])
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, amount="1")
    assert excinfo.value.reason_code == "margin_below_minimum"


# --- Két session egymás utáni kettős beküldés ---


def test_two_sessions_sequential_double_submit_single_row(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    with SessionLocal() as first:
        _evaluate(first, subject_id="TWOSESS", amount="500000")
        first.commit()
    with SessionLocal() as second:
        decision = _evaluate(second, subject_id="TWOSESS", amount="500000")
        second.commit()
    assert decision.decision == "PASS"
    rows = list(db.scalars(select(FinanceCommitment)).all())
    assert len(rows) == 1 and rows[0].net_huf == Decimal("500000")
    assert len(list(db.scalars(select(MarginGateDecision)).all())) == 2


# --- MEDIUM-2: csomagok közötti szakágkód-ütközés blokk ---


def test_cross_package_trade_code_conflict_blocks(db):
    plan = seed_gate_plan(db,
        project_id=PROJECT,
        revenue="20000000",
        summary_lines=[
            {"cost_code": "PACK-A", "amount": "10000000", "amount_basis": "NET_REVENUE_ENVELOPE", "component": "other"},
            {"cost_code": "PACK-B", "amount": "10000000", "amount_basis": "NET_REVENUE_ENVELOPE", "component": "other"},
        ],)
    create_allocation_snapshot(db,
        plan_id=plan.plan_id,
        summary_line_id=get_line(db, plan, "PACK-A").line_id,
        source_type="NORM_TABLE",
        source_version="NORM-1",
        source_hash="b" * 64,
        approver="fixture-finance@imperial.local",
        rationale="Szintetikus normatábla-allokáció.",
        rows=[
            {"trade_code": "SHARED-TRADE", "direct_cost_component": "material", "normalized_ratio": Decimal("100")},
        ],)
    with pytest.raises(MarginGateBlocked) as excinfo:
        create_allocation_snapshot(db,
            plan_id=plan.plan_id,
            summary_line_id=get_line(db, plan, "PACK-B").line_id,
            source_type="NORM_TABLE",
            source_version="NORM-1",
            source_hash="b" * 64,
            approver="fixture-finance@imperial.local",
            rationale="Szintetikus normatábla-allokáció ütköző szakágkóddal.",
            rows=[
                {"trade_code": "SHARED-TRADE", "direct_cost_component": "material", "normalized_ratio": Decimal("100")},
            ],)
    assert excinfo.value.reason_code == "trade_code_cross_package_conflict"


# --- LOW-2: indirect gyerek blokk importnál és allokációnál ---


def test_allocation_rejects_indirect_children(db):
    plan = seed_gate_plan(db, project_id=PROJECT, revenue="20000000", summary_lines=[{"cost_code": "PACK-X", "amount": "6000000", "amount_basis": "NET_REVENUE_ENVELOPE", "component": "other"}],)
    db.add(ProjectFinanceBudgetLine(line_id="FIN-LINE-IND-CHILD",
        plan_id_fk=plan.id,
        cost_code="IND-CHILD",
        category="indirect",
        description="Indirect gyereksor",
        budget_net=Decimal("100"),
        cost_class="indirect",
        parent_summary_line_id=get_line(db, plan, "PACK-X").line_id,
        currency="HUF",))
    db.commit()
    from app.services.budget_allocation import build_allocation_from_detailed_lines
    with pytest.raises(MarginGateBlocked) as excinfo:
        build_allocation_from_detailed_lines(db,
            plan_id=plan.plan_id,
            summary_line_id=get_line(db, plan, "PACK-X").line_id,
            approver="fixture-finance@imperial.local",
            rationale="Részletes sorokból épülő allokáció.",)
    assert excinfo.value.reason_code == "indirect_child_forbidden"


# --- LOW-1: szerződéstípus zárt szótár ---


def test_unknown_contract_type_blocks_fail_closed(db):
    from app.services.contract_workflow import create_contract_workflow
    payload = {
        "contract_number": "UAT-UNKNOWN-001",
        "contract_type": "subcontractor-agreement",
        "ids": {"ContractID": "CTR-UNKNOWN-001", "ProjectID": PROJECT},
        "counterparty": {"name": "Ismeretlen típusú partner", "email": "x@example.com"},
    }
    with pytest.raises(MarginGateBlocked) as excinfo:
        create_contract_workflow(db, payload=payload, package_document_id="DOC-X", manifest_document_id="DOC-M", actor="api",)
    assert excinfo.value.reason_code == "unclassified_contract_type"


# --- LOW-3: wrapper-blokkok bizonyítékkal ---


def test_missing_descriptor_block_leaves_evidence(db):
    from tests.test_tender_margin_enforcement import _subcontract_payload
    payload = _subcontract_payload(None)
    with pytest.raises(MarginGateBlocked):
        generate_contract_package(db, payload, actor="api")
    rows = list(db.scalars(select(MarginGateDecision)).all())
    assert rows and rows[0].block_reason_code == "missing_commitment_descriptor"
    assert rows[0].plan_id_fk is None


# --- LOW-4b: alvállalkozói kézbesítési kapu ---


def test_subcontract_dispatch_transition_is_gated(db):
    from app.models import ProjectRegistry
    from tests.test_tender_margin_enforcement import _project as enf_project
    from tests.test_tender_margin_enforcement import _subcontract_payload
    enf_project(db)
    seed_gate_plan(db, project_id="ENF-001", revenue="10000000", direct_lines=[("SUB-EXEC", "5000000", "labour")])
    result = generate_contract_package(db, _subcontract_payload({"cost_code": "SUB-EXEC", "net_huf": "5000000"}), actor="api",)
    row = db.scalar(select(ContractWorkflowRecord).where(ContractWorkflowRecord.contract_id == result["contract_id"]))
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == row.project_id))
    project.responsible = "project-manager@imperial.local"
    db.commit()
    submit_contract_review(db, row.contract_id, _user("sales"))
    review_contract(db, row.contract_id, _user("finance"), gate="commercial", decision="approve", note="A vállalkozói díj és fizetési ütem megfelelő.")
    review_contract(db, row.contract_id, _user("technical-prep"), gate="technical", decision="approve", note="A vállalkozói műszaki tartalom hiánytalan.")
    approved = review_contract(db, row.contract_id, _user("owner"), gate="owner", decision="approve", note="A partneri szerződés vezetői jóváhagyása megtörtént.")
    assert approved.status == "approved"
    digest = "a" * 64
    signed = record_signed_contract(db, row.contract_id, _user("legal"), file_id="DRIVE-SIGNED-REMED-001", document_sha256=digest, signed_at=datetime.now(UTC) - timedelta(minutes=1),)
    assert signed.status == "signed"
    sent_at = datetime.now(UTC)
    dispatched = record_contract_dispatch(db, row.contract_id, _user("legal"),
        postal_sent_at=sent_at, postal_tracking_number="TRACK-REMED-001",
        postal_proof_file_id="POSTAL-PROOF-001",
        electronic_sent_at=sent_at, electronic_message_id="MSG-REMED-001",
        electronic_recipient=str(json.loads(row.payload_json).get("counterparty", {}).get("email", "")).lower(),
        electronic_attachment_sha256=digest,)
    assert dispatched.status == "dispatched"
    commitments = list(db.scalars(select(FinanceCommitment)).all())
    # A generálás → előkészítés → jóváhagyás → kézbesítés lánc ugyanazzal a
    # subject-kulccsal fut: pontosan egy lekötés.
    assert len(commitments) == 1


# --- M3/MEDIUM-3: második megrendelés blokk (service szint) ---


def test_second_order_for_same_selection_is_rejected(client, db):
    from app.models import ProcurementOrderProjection as OrderRow
    from tests.test_tender_margin_enforcement import _approved_requirement, _selected
    seed_gate_plan(db, project_id="ENF-001", revenue="10000000", direct_lines=[("MAT-ENF", "6000000", "labour")])
    requirement_id = _approved_requirement(client, db, cost_code="MAT-ENF")
    selection_id = _selected(client, requirement_id)
    assert client.post(f"/api/procurement/selections/{selection_id}/approvals/managing_director").status_code == 200
    first = client.post("/api/procurement/orders", json={
        "selection_id": selection_id, "ordered_quantity": "100",
        "delivery_due": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
    })
    assert first.status_code == 200
    second = client.post("/api/procurement/orders", json={
        "selection_id": selection_id, "ordered_quantity": "100",
        "delivery_due": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
    })
    assert second.status_code == 409
    orders = list(db.scalars(select(OrderRow).where(OrderRow.selection_id == selection_id)).all())
    assert len(orders) == 1
    # A lekötés a döntés-jóváhagyáskori egyetlen sor marad.
    assert len(list(db.scalars(select(FinanceCommitment)).all())) == 1


def test_award_then_po_preparation_approval_counts_once(client, db):
    # Review B HIGH-1 / Review A M3: az odaítélés és a PO-előkészítés
    # jóváhagyása ugyanazt az ajánlati összeget köti le — AZONOS
    # subject-kulccsal, így a lánc nem dupláz.
    from app.models import TenderPurchaseOrderPreparation
    from tests.test_tender_margin_enforcement import (TENDER_ID, _bid, _login, _project, _tender,)
    _project(db)
    seed_gate_plan(db, project_id="ENF-001", revenue="10000000", direct_lines=[("MAT-ENF", "6500000", "labour")])
    tender = _tender(db, cost_code="MAT-ENF")
    bid = _bid(db, tender, net_total="5000000")
    _login(client)
    awarded = client.post(f"/tenders/{TENDER_ID}/bids/{bid.bid_id}/award", data={"summary": "A dokumentált értékelés alapján kiválasztott ajánlat."}, follow_redirects=False,)
    assert awarded.status_code == 303
    preparation = db.scalar(select(TenderPurchaseOrderPreparation).where(TenderPurchaseOrderPreparation.tender_id == TENDER_ID))
    assert preparation is not None
    approved = client.post(f"/tenders/purchase-order-preparations/{preparation.preparation_id}/approve", follow_redirects=False,)
    assert approved.status_code == 303
    db.refresh(preparation)
    assert preparation.status == "approved"
    commitments = list(db.scalars(select(FinanceCommitment)).all())
    # A lánc (odaítélés + PO-jóváhagyás) pontosan EGY lekötéssorral fut.
    assert len(commitments) == 1
    assert commitments[0].net_huf == Decimal("5000000")
    assert commitments[0].subject_type == "tender_bid"
    assert commitments[0].subject_id == bid.bid_id
