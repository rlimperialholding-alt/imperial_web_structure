"""TENDER-margin-gate migráció bizonyítékszkript (upgrade/downgrade/upgrade).

Ideiglenes SQLite adatbázison: upgrade head → hat új kapu-tábla és az új
oszlopok; üzleti sorokkal a downgrade adatőrző RuntimeError; üres tábláknál
downgrade töröl, az újra-upgrade determinisztikusan helyreállít. Sikeres
futás kimenete: tender-margin-gate-migration-ok
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

_NEW_TABLES = (
    "finance_budget_imports",
    "finance_commitments",
    "finance_allocation_snapshots",
    "finance_allocation_snapshot_rows",
    "margin_gate_decisions",
    "margin_gate_vat_rules",
)
_REQUIRED_COLUMNS = {
    "finance_project_plans": ("content_sha256", "provenance_json"),
    "finance_project_budget_lines": (
        "cost_class",
        "direct_cost_component",
        "amount_basis",
        "is_summary_package",
        "parent_summary_line_id",
        "currency",
    ),
    "tender_packages": ("cost_code",),
    "procurement_requirements": ("cost_code",),
}


def _alembic(database_url: str, command: str, revision: str, workspace: Path) -> int:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", command, revision],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
    ).returncode


def _assert_schema(engine, *, tables_present: bool) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table in _NEW_TABLES:
        if (table in tables) != tables_present:
            state = "missing" if tables_present else "lingered"
            raise RuntimeError(f"Gate table {table} {state}.")
    for table, columns in _REQUIRED_COLUMNS.items():
        if table not in tables:
            continue  # downgrade után a tábla sem létezhet
        present = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column not in present:
                raise RuntimeError(f"{table}.{column} missing after upgrade.")


def main() -> int:
    workspace = Path(__file__).parents[1]
    with tempfile.TemporaryDirectory(prefix="imperial-margin-gate-migration-") as temp_dir:
        database_path = Path(temp_dir) / "migration.db"
        database_url = f"sqlite:///{database_path.as_posix()}"
        if _alembic(database_url, "upgrade", "head", workspace) != 0:
            raise RuntimeError("upgrade head failed")
        engine = create_engine(database_url)
        try:
            _assert_schema(engine, tables_present=True)
            # Üzleti sorral a downgrade köteles megtagadni (fail-closed, adatőrző).
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO margin_gate_decisions (decision_id, project_id, "
                        "action_type, subject_type, subject_id, proposed_net_huf, decision, "
                        "required_margin_percent, input_snapshot_json, calculation_json, "
                        "input_sha256, created_by, created_at) VALUES (:decision_id, "
                        ":project_id, :action_type, :subject_type, :subject_id, 0, 'BLOCK', "
                        "35, '{}', '{}', :sha, 'probe', CURRENT_TIMESTAMP)"
                    ),
                    {
                        "decision_id": "DEC-PROBE-001",
                        "project_id": "PRJ-PROBE",
                        "action_type": "migration_probe",
                        "subject_type": "probe",
                        "subject_id": "probe-1",
                        "sha": "a" * 64,
                    },
                )
        finally:
            engine.dispose()
        if _alembic(database_url, "downgrade", "20260816_0072", workspace) == 0:
            raise RuntimeError("Downgrade with business rows must be refused.")
        engine = create_engine(database_url)
        try:
            if "margin_gate_decisions" not in _table_names(engine):
                raise RuntimeError("Refused downgrade must not drop data-bearing tables.")
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM margin_gate_decisions"))
        finally:
            engine.dispose()
        if _alembic(database_url, "downgrade", "20260816_0072", workspace) != 0:
            raise RuntimeError("Downgrade on empty gate tables failed")
        for present in (False, True):
            engine = create_engine(database_url)
            try:
                _assert_schema(engine, tables_present=present)
            finally:
                engine.dispose()
            if not present and _alembic(database_url, "upgrade", "head", workspace) != 0:
                raise RuntimeError("re-upgrade head failed")
    print("tender-margin-gate-migration-ok")
    return 0


def _table_names(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


if __name__ == "__main__":
    raise SystemExit(main())
