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
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.database import Base, SessionLocal
from app.models import (ContractWorkflowRecord, FinanceCommitment, MarginGateDecision, ProcurementOffer, ProcurementOrderProjection, ProcurementRequirement, ProcurementSelection, ProjectBudgetImport, ProjectFinanceBudgetLine, ProjectFinancePlan, ProjectRegistry,)
from app.schemas import ProcurementOrderIn
from app.services import procurement as procurement_service
from app.services.budget_allocation import create_allocation_snapshot
from app.services.budget_import import approve_budget_import, preview_budget_import
from app.services.commercial_integration import generate_contract_package
from app.services.contract_workflow import (record_contract_dispatch, record_signed_contract, review_contract, submit_contract_review,)
from app.services.project_finance import (clone_finance_plan, leadership_approve_plan, require_finance_plan_project_scope, require_project_finance_scope,)
from app.services.tender_margin_gate import (MarginGateBlocked, evaluate_commitment_gate, plan_content_sha256,)
from tests.test_budget_import import _csv_bytes, _draft_plan, _persist_user, _row

PROJECT = "REMED-001"


def _user(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _registry_row(db, project_id: str, responsible: str | None = None) -> None:
    if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id)):
        db.add(ProjectRegistry(project_id=project_id, name=f"{project_id} szintetikus projekt", responsible=responsible,))
        db.commit()


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
    import re
    migration, migration_path = _load_migration_module()
    order = list(migration._DOWNGRADE_DROP_ORDER)
    assert set(order) == set(migration._NEW_TABLES)
    # Az FK-függő gyerektáblák a szülők ELŐTT törlődnek (PG RESTRICT-biztos).
    assert order.index("finance_allocation_snapshot_rows") < order.index("finance_allocation_snapshots")
    source = Path(migration_path).read_text(encoding="utf-8")
    assert "_drop_unique_constraint_if_exists" in source
    assert 'batch_op.drop_constraint(name, type_="unique")' in source
    assert "uq_ops_procurement_orders_selection_id" in source
    assert source.index("_drop_unique_constraint_if_exists(") < source.index("op.drop_table")
    upgrade_columns = set(re.findall(r'_add_missing_column\(inspector, "([^"]+)", sa\.Column\("([^"]+)"', source))
    assert upgrade_columns == {(table, column) for table, column, _n, _d in migration._ADDED_COLUMNS}
    upgrade_indexes = set(re.findall(r'_add_missing_index\("([^"]+)", "([^"]+)"', source))
    assert upgrade_indexes == {(table, name) for table, names in migration._ADDED_INDEXES.items() for name in names}
    assert source.index("_drop_unique_constraint_if_exists(") < source.index("_drop_index_if_exists(") < source.index("_drop_column_if_exists(") < source.index("op.drop_table")
    assert "_added_column_has_data" in source


def test_migration_0073_postgresql_dialect_ddl_compiles():
    # Task80: PG-dialektus DDL: Boolean server_default ``DEFAULT false``, oszlopdobás plain ``DROP COLUMN``.
    from pathlib import Path
    import re
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_mock_engine
    captured: list[str] = []
    engine = create_mock_engine("postgresql://", lambda sql, *args, **kwargs: captured.append(str(sql)))
    context = MigrationContext.configure(connection=engine.connect())
    ops = Operations(context)
    ops.add_column("finance_project_budget_lines", sa.Column("is_summary_package", sa.Boolean(), nullable=False, server_default=sa.text("false")),)
    with ops.batch_alter_table("finance_project_budget_lines") as batch_op:
        batch_op.drop_column("parent_summary_line_id")
    add_sql = next(statement for statement in captured if "ADD COLUMN is_summary_package" in statement)
    assert "BOOLEAN" in add_sql.upper()
    assert "default false" in add_sql.lower()
    assert "default '0'" not in add_sql.lower()
    assert "default 0" not in add_sql.lower()
    drop_sql = next(statement for statement in captured if "DROP COLUMN parent_summary_line_id" in statement)
    assert "ALTER TABLE finance_project_budget_lines DROP COLUMN parent_summary_line_id" in drop_sql.replace("\n", " ")
    _migration, migration_path = _load_migration_module()
    source = Path(migration_path).read_text(encoding="utf-8")
    boolean_lines = re.findall(r'[^\n]*sa\.Column\("is_summary_package"[^\n]*', source)
    assert boolean_lines and all('server_default=sa.text("false")' in line for line in boolean_lines)
    assert all('server_default="0"' not in line for line in boolean_lines)
    assert "batch_op.drop_column(name)" in source


def test_migration_0073_upgrade_downgrade_reupgrade_and_row_refusal(tmp_path):
    # Futás idejű lánc (izolált alprocessz): upgrade → downgrade → re-upgrade.
    import os
    import subprocess
    import sys
    from datetime import UTC, datetime
    from pathlib import Path
    import sqlalchemy as sa
    from sqlalchemy import create_engine
    migration, _ = _load_migration_module()
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

    def schema_snapshot():
        inspector = sa.inspect(engine)
        snapshot = {}
        for name in sorted(inspector.get_table_names()):
            snapshot[name] = {
                "columns": tuple(sorted((c["name"], str(c["type"]), bool(c["nullable"])) for c in inspector.get_columns(name))),
                "indexes": tuple(sorted(((i.get("name"), tuple(i.get("column_names") or ())) for i in inspector.get_indexes(name)), key=str)),
                "uniques": tuple(sorted(((u.get("name"),) for u in inspector.get_unique_constraints(name)), key=str)),
                "fks": tuple(sorted(((tuple(f.get("constrained_columns") or ()), f.get("referred_table"), tuple(f.get("referred_columns") or ())) for f in inspector.get_foreign_keys(name)), key=str)),
                "checks": tuple(sorted(((c.get("name"),) for c in inspector.get_check_constraints(name)), key=str)),
            }
        return snapshot

    def assert_0073_columns_and_indexes_present(snap):
        for table, column, _n, _d in migration._ADDED_COLUMNS:
            assert column in {c[0] for c in snap[table]["columns"]}
        for table, index_names in migration._ADDED_INDEXES.items():
            assert set(index_names) <= {i[0] for i in snap[table]["indexes"]}

    def assert_only_0073_objects_removed(after):
        # A downgrade UTÁN a head sémából CSAK a 0073-objektumok hiányoznak.
        assert set(after) == set(head) - set(migration._NEW_TABLES)
        for table, objects in after.items():
            dropped_columns = {column for t, column, _n, _d in migration._ADDED_COLUMNS if t == table}
            dropped_indexes = set(migration._ADDED_INDEXES.get(table, ()))
            dropped_uniques = {"uq_ops_procurement_orders_selection_id"} if table == "ops_procurement_orders" else set()
            assert objects["columns"] == tuple(item for item in head[table]["columns"] if item[0] not in dropped_columns)
            assert objects["indexes"] == tuple(item for item in head[table]["indexes"] if item[0] not in dropped_indexes)
            assert objects["uniques"] == tuple(item for item in head[table]["uniques"] if item[0] not in dropped_uniques)
            assert objects["fks"] == head[table]["fks"]
            assert objects["checks"] == head[table]["checks"]

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
    head = schema_snapshot()
    for table in migration._NEW_TABLES:
        assert table in head
    assert_0073_columns_and_indexes_present(head)
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
    assert schema_snapshot() == head  # részleges visszaállítás nem történt
    with engine.connect() as connection:
        connection.execute(imports_table.delete())
        connection.commit()
    expect_ok("downgrade", "20260816_0072")
    assert "finance_budget_imports" not in table_names()
    assert "uq_ops_procurement_orders_selection_id" not in unique_constraint_names()
    assert_only_0073_objects_removed(schema_snapshot())
    # Re-upgrade: a 0073-objektumok determinisztikusan helyreállnak.
    expect_ok("upgrade", "20260907_0073")
    assert "finance_budget_imports" in table_names()
    assert "uq_ops_procurement_orders_selection_id" in unique_constraint_names()
    assert_0073_columns_and_indexes_present(schema_snapshot())
    # Oszlopadat-őr: valós adatú oszlopnál a downgrade fail-closed elutasít.
    from sqlalchemy.orm import Session as MigrationSession
    from app.models import TenderPackage
    with MigrationSession(engine) as session:
        session.add(TenderPackage(tender_id="TEN-MIG-ROW", project_id="MIG-1", title="Szintetikus tender", scope="Szintetikus kör", cost_code="DATA-CODE", question_deadline_at=datetime.now(UTC), submission_deadline_at=datetime.now(UTC), created_by="fixture@imperial.local",))
        session.commit()
    refused = run_alembic("downgrade", "20260816_0072")
    assert refused.returncode != 0
    assert "0073 downgrade refused" in refused.stdout + refused.stderr
    assert "tender_packages.cost_code" in refused.stdout + refused.stderr
    assert "uq_ops_procurement_orders_selection_id" in unique_constraint_names()
    engine.dispose()


def _evaluate(db, *, cost_code="MAT-A", amount="100", subject_id="S-1", project=PROJECT):
    return evaluate_commitment_gate(db, project_id=project, action_type="tender_award", subject_type="tender_bid", subject_id=subject_id, cost_code=cost_code, proposed_net_huf=Decimal(amount), actor="fixture@imperial.local",)


def test_block_and_pass_decision_evidence_plan_fk_contract(db):
    seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6501000", "material")])
    with pytest.raises(MarginGateBlocked):
        _evaluate(db, amount="100")
    rows = list(db.scalars(select(MarginGateDecision)).all())
    assert rows and rows[0].decision == "BLOCK"
    # A független bizonyíték-tranzakció nem hivatkozza az FK-n a tervsort.
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
    with pytest.raises(MarginGateBlocked) as excinfo:
        _evaluate(db, subject_id="NEW-COMMIT", amount="100")
    assert excinfo.value.reason_code == "margin_below_minimum"
    db.rollback()


def test_leadership_approval_blocks_orphan_commitment_codes(db):
    # Review A CRITICAL: a v2-ből hiányzó v1-es MAT-A kód — jóváhagyás az aktiválás ELŐTT blokkol.
    plan_v1 = seed_gate_plan(db, project_id=PROJECT, revenue="10000000", direct_lines=[("MAT-A", "6500000", "material")])
    _evaluate(db, subject_id="ORPHAN-COMMIT", amount="100000")
    db.commit()
    v2 = _v2_plan(db, "FIN-PLAN-REMED-03", ["MAT-B"])
    with pytest.raises(ValueError, match="MAT-A"):
        leadership_approve_plan(db, v2.plan_id, _user("managing-director", "md@imperial.local"), note="Vezetői jóváhagyás árva költségkóddal.", margin_exception_reason="",)
    db.rollback()
    # A blokkolt aktiválás után a régi terv jóváhagyott marad.
    assert db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == plan_v1.plan_id)).status == "approved"
    assert db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == v2.plan_id)).status == "finance_approved"
    commitment = db.scalar(select(FinanceCommitment))
    assert commitment.plan_id_fk == plan_v1.id


def test_gate_counts_orphan_commitment_conservatively(db):
    # Defense-in-depth: az árva lekötés teljes összege a vetületben számít.
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
        # post = max(6M, 6.5M) = 6.5M → 35.00; 100 új lekötéssel 6.5001M → 34.999 → BLOCK.
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
    # SQLite NUMERIC-affinitás: float64-pontosság (PG Numeric(18,2) egzakt); 35.00 alá visz.
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
    # A generálás → kézbesítés lánc ugyanazzal a subject-kulccsal fut.
    assert len(commitments) == 1


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


def _order_payload(selection_id):
    from app.schemas import ProcurementOrderIn
    return ProcurementOrderIn(selection_id=selection_id, ordered_quantity=Decimal("100"),
        delivery_due=datetime.now(UTC) + timedelta(days=5))


def _approved_selection(client, db, cost_code="MAT-ENF"):
    from tests.test_tender_margin_enforcement import _approved_requirement, _selected
    seed_gate_plan(db, project_id="ENF-001", revenue="10000000", direct_lines=[(cost_code, "6000000", "labour")])
    requirement_id = _approved_requirement(client, db, cost_code=cost_code)
    selection_id = _selected(client, requirement_id)
    assert client.post(f"/api/procurement/selections/{selection_id}/approvals/managing_director").status_code == 200
    return selection_id


def test_commit_time_selection_unique_conflict_maps_to_duplicate_without_artifacts(client, db, monkeypatch):
    # BIZONYÍTOTT selection-unique ütközés → duplicate hiba (409), artifact nélkül.
    from sqlalchemy.exc import IntegrityError
    from app.models import AuditLog, ProcurementOrderProjection as OrderRow
    from app.services.procurement import create_order
    selection_id = _approved_selection(client, db)
    passed_before = len(list(db.scalars(select(AuditLog.id).where(AuditLog.action == "margin_gate.passed")).all()))
    original_commit = db.commit
    calls: list[int] = []

    def fail_once_commit():
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed: ops_procurement_orders.selection_id"))
        original_commit()

    monkeypatch.setattr(db, "commit", fail_once_commit)
    with pytest.raises(ValueError, match="már készült megrendelés"):
        create_order(db, _order_payload(selection_id), actor="fixture@imperial.local")
    assert db.scalar(select(OrderRow.id).where(OrderRow.selection_id == selection_id)) is None
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "procurement.order.create")) is None
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "procurement.order.duplicate_blocked")) is None
    passed_after = len(list(db.scalars(select(AuditLog.id).where(AuditLog.action == "margin_gate.passed")).all()))
    assert passed_after == passed_before

def test_commit_time_unrelated_integrity_error_stays_visible_without_audit(client, db, monkeypatch):
    # Más integritás-hiba eredeti formában terjed (nincs téves mapping/audit).
    from sqlalchemy.exc import IntegrityError
    from app.models import AuditLog, ProcurementOrderProjection as OrderRow
    from app.services.procurement import create_order
    selection_id = _approved_selection(client, db)
    original_commit = db.commit

    def fail_once_commit():
        if getattr(fail_once_commit, "failed", False):
            original_commit()
            return
        fail_once_commit.failed = True
        raise IntegrityError("INSERT", {}, Exception("NOT NULL constraint failed: ops_procurement_orders.status"))

    monkeypatch.setattr(db, "commit", fail_once_commit)
    with pytest.raises(IntegrityError):
        create_order(db, _order_payload(selection_id), actor="fixture@imperial.local")
    assert db.scalar(select(OrderRow.id).where(OrderRow.selection_id == selection_id)) is None
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "procurement.order.duplicate_blocked")) is None
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "procurement.order.create")) is None


def test_award_then_po_preparation_approval_counts_once(client, db):
    # Review B HIGH-1 / Review A M3: odaítélés és PO-jóváhagyás AZONOS subject-kulccsal — nem dupláz.
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


# --- Task77 (Gate7): AC-01 scope, AC-04 egy-döntés-egy-megrendelés,
# --- AC-05/05b import sorzár + draft, AC-06 parent-remap, AC-07 kényszer.


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


def test_concurrent_order_creation_creates_at_most_one_order(tmp_path):
    # Két különálló session fut TELJES create_order-rel; a második a 0073-as selection_id kényszeren bukik, kanonikus domain hibára képezve.
    from sqlalchemy.orm import sessionmaker
    from app.database import engine
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as seed:
        seed_gate_plan(seed, project_id="T77-RACE", revenue="10000000", direct_lines=[("MAT-RACE", "6000000", "labour")],)
        seed.add(ProjectRegistry(project_id="T77-RACE", name="T77-RACE szintetikus projekt"))
        # Jóváhagyott döntés a versenyhez (a lánc bizonyítéka az enforcement fájlban).
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
            # A második kísérlet TELJESEN lefut, míg az első még nem commitolt; a
            # versenyt az uq_ops_procurement_orders_selection_id kényszer zárja atomi módon.
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


def test_import_approval_rechecks_draft_after_lock_acquisition(db):
    _persist_user(db, role="finance", email="fixture-finance@imperial.local")
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
                              user=_user("finance", "fixture-finance@imperial.local"))
    # A jóváhagyott terv immutable maradt: egyetlen import-sor sem került rá.
    db.expire_all()
    fresh_plan = db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.plan_id == plan.plan_id))
    assert fresh_plan.status == "approved"
    assert db.scalars(select(ProjectFinanceBudgetLine).where(ProjectFinanceBudgetLine.plan_id_fk == fresh_plan.id)).all() == []
    assert db.scalar(select(ProjectBudgetImport).where(ProjectBudgetImport.import_id == row.import_id)).status == "preview"


def test_concurrent_import_approval_applies_lines_at_most_once(db):
    import json as _json
    from app.models import AuditLog
    from app.services import budget_import as budget_import_service
    row = preview_budget_import(db, project_id="IMP-T78", file_name="budget.csv",
        data=_csv_bytes([_row("MAT-T78-CONC", amount="1000000")]),
        actor="fixture@imperial.local",)
    plan = _draft_plan(db, project_id="IMP-T78", plan_id="FIN-PLAN-T78-CONC")
    _persist_user(db, role="finance", email="other-finance@imperial.local")
    _persist_user(db, role="finance", email="first-finance@imperial.local")
    # Deterministikus verseny: az első jóváhagyás a tervzárnál átengedi a másodikat;
    # az első a zár UTÁNI sorállapot-ellenőrzésen bukik — a sorok egyszer kerülnek a tervre.
    original_select = budget_import_service.select
    fired = {"value": False}

    def select_hook(*args, **kwargs):
        # A select(Model) a modellosztályt kapja — a hook erről ismeri fel a célterv-zárat.
        if args and args[0] is ProjectFinancePlan and not fired["value"]:
            fired["value"] = True
            with SessionLocal() as other:
                approve_budget_import(other, import_id=row.import_id, plan_id=plan.plan_id, user=_user("finance", "other-finance@imperial.local"),)
        return original_select(*args, **kwargs)

    budget_import_service.select = select_hook
    try:
        with pytest.raises(MarginGateBlocked, match="preview"):
            approve_budget_import(db, import_id=row.import_id, plan_id=plan.plan_id, user=_user("finance", "first-finance@imperial.local"),)
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


def test_clone_remaps_parent_when_child_precedes_parent_in_collection(db):
    _registry_row(db, "T77-CLONE")
    plan = seed_gate_plan(db, project_id="T77-CLONE", revenue="10000000")
    # A gyerek előbb jön létre (a kollekcióban ELŐBB áll); a régi egymenetes remap itt None-t adott volna.
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


def test_migration_0073_adds_and_enforces_order_selection_unique_constraint(db):
    # Futás idejű séma: modell-metaadat és tesztadatbázis is hordozza a kényszert; a duplikált INSERT a kényszeren bukik.
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
