"""Add TENDER 35% direct-margin hard-gate schema: budget provenance/hash,
direct-cost classification, allocation snapshots, commitments, immutable
margin decisions and VAT config.

Revision ID: 20260907_0073
Revises: 20260816_0072
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260907_0073"
down_revision = "20260816_0072"
branch_labels = None
depends_on = None

# Az 0001 bootstrap a mindenkori app.models metaadatot hozza létre, ezért a
# tábla-/oszloplétrehozás introspekciós guarddal idempotens (0025/0059 minta).
_NEW_TABLES = ("finance_budget_imports",
    "finance_commitments",
    "finance_allocation_snapshots",
    "finance_allocation_snapshot_rows",
    "margin_gate_decisions",
    "margin_gate_vat_rules",)

# A downgrade DROP-sorrend child-before-parent (Review B MEDIUM): az
# FK-függő gyerektáblák a szülők ELŐTT törlődnek, különben a PostgreSQL
# RESTRICT a visszagörgetést elutasítaná.
_DOWNGRADE_DROP_ORDER = ("finance_budget_imports",
    "margin_gate_decisions",
    "finance_commitments",
    "finance_allocation_snapshot_rows",
    "finance_allocation_snapshots",
    "margin_gate_vat_rules",)

# Task79 (Review HIGH): a 0073 által MEGLÉVŐ táblákra felvett oszlopok
# (tábla, oszlop, nullable, üres/alapértelmezett érték) és indexeik — a
# downgrade csak adatmentes oszlopot dobhat el (pontos 0072-visszaállítás).
_ADDED_COLUMNS = (("finance_project_plans", "content_sha256", True, None),
    ("finance_project_plans", "provenance_json", False, "{}"),
    ("finance_project_budget_lines", "cost_class", True, None),
    ("finance_project_budget_lines", "direct_cost_component", True, None),
    ("finance_project_budget_lines", "amount_basis", True, None),
    ("finance_project_budget_lines", "is_summary_package", False, False),
    ("finance_project_budget_lines", "parent_summary_line_id", True, None),
    ("finance_project_budget_lines", "currency", False, "HUF"),
    ("tender_packages", "cost_code", True, None),
    ("procurement_requirements", "cost_code", True, None),)
# Az upgrade által az új oszlopokra felvett indexek (tábla -> nevek).
_ADDED_INDEXES = {"finance_project_plans": ("ix_finance_project_plans_content_sha256",),
    "finance_project_budget_lines": ("ix_finance_project_budget_lines_cost_class",
        "ix_finance_project_budget_lines_parent_summary_line_id",),
    "tender_packages": ("ix_tender_packages_cost_code",),
    "procurement_requirements": ("ix_procurement_requirements_cost_code",),}


def _indexes(table: str, prefix: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{prefix}_{column}", table, [column])


def _add_missing_column(inspector, table: str, column: sa.Column) -> None:
    columns = {item["name"] for item in inspector.get_columns(table)}
    if column.name not in columns:
        op.add_column(table, column)


def _add_missing_index(table: str, index_name: str, columns: tuple[str, ...]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing_indexes = {item["name"] for item in inspector.get_indexes(table)}
    if index_name not in existing_indexes:
        op.create_index(index_name, table, list(columns))


def _add_missing_unique_constraint(table: str, name: str, columns: tuple[str, ...]) -> None:
    # Task77 Gate7: egy döntéshez legfeljebb egy megrendelés; a 0001 bootstrap
    # már létrehozta (guard-skip), a migrált adatbázisban batch-rebuild adja.
    inspector = sa.inspect(op.get_bind())
    names = {item.get("name") for item in inspector.get_unique_constraints(table)}
    if name in names:
        return
    with op.batch_alter_table(table) as batch_op:
        batch_op.create_unique_constraint(name, list(columns))


def _drop_unique_constraint_if_exists(table: str, name: str) -> None:
    # Task78: a downgrade pontosan a 0072-es head sémát állítja vissza — a
    # selection-id egyedi kényszert is eldobja (guarddal, a re-upgrade
    # idempotens marad); batch-mód a hordozhatóságért (SQLite tábla-újraépítés).
    inspector = sa.inspect(op.get_bind())
    names = {item.get("name") for item in inspector.get_unique_constraints(table)}
    if name not in names:
        return
    with op.batch_alter_table(table) as batch_op:
        batch_op.drop_constraint(name, type_="unique")


def _drop_index_if_exists(table: str, name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    names = {item.get("name") for item in inspector.get_indexes(table)}
    if name in names:
        op.drop_index(name, table_name=table)


def _drop_column_if_exists(table: str, name: str) -> None:
    # Task80 (Review MEDIUM): az oszlopdobás batch-módban történik — a
    # PostgreSQL-ben ez ugyanúgy plain ``ALTER TABLE ... DROP COLUMN``-ra
    # fordul, az SQLite viszont kizárólag tábla-újraépítéssel (batch) tud
    # oszlopot dobni; a korábbi közvetlen op.drop_column SQLite alatt
    # hordozhatatlan volt.
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns(table)}
    if name in columns:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column(name)


def _added_column_has_data(table: str, column: str, nullable: bool, default) -> bool:
    # Task79: valós (nem alapértelmezett) oszlopadatnál a downgrade fail-closed.
    probe = sa.table(table, sa.column(column))
    expression = probe.c[column].isnot(None) if nullable else (probe.c[column] != default)
    count = op.get_bind().execute(sa.select(sa.func.count()).select_from(probe).where(expression)).scalar()
    return bool(count)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    required = set(_NEW_TABLES)
    present = existing & required
    if present == required:
        pass  # a 0001 bootstrap már létrehozta a teljes sémát
    elif present:
        raise RuntimeError("Partial tender margin gate schema: " + ", ".join(sorted(present)))
    else:
        op.create_table("finance_budget_imports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("import_id", sa.String(120), nullable=False, unique=True),
            sa.Column("project_id", sa.String(100), nullable=False),
            sa.Column("file_name", sa.String(500), nullable=False),
            sa.Column("source_format", sa.String(20), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("preview_sha256", sa.String(64), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("amount_basis", sa.String(40), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),
            sa.Column("status", sa.String(30), nullable=False, server_default="preview"),
            sa.Column("preview_json", sa.Text(), nullable=False),
            sa.Column("error_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("imported_by", sa.String(255), nullable=False),
            sa.Column("approved_by", sa.String(255)),
            sa.Column("approved_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("status IN ('preview','approved','rejected')",
                name="ck_budget_import_status",),
            sa.CheckConstraint("amount_basis IN ('NET_REVENUE_ENVELOPE','DIRECT_COST_BASELINE')",
                name="ck_budget_import_amount_basis",),)
        op.create_table("finance_commitments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("commitment_id", sa.String(120), nullable=False, unique=True),
            sa.Column("plan_id_fk",
                sa.Integer(),
                sa.ForeignKey("finance_project_plans.id", ondelete="CASCADE"),
                nullable=False,),
            sa.Column("cost_code", sa.String(100), nullable=False),
            sa.Column("subject_type", sa.String(40), nullable=False),
            sa.Column("subject_id", sa.String(120), nullable=False),
            sa.Column("net_huf", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),
            sa.Column("status", sa.String(30), nullable=False, server_default="committed"),
            sa.Column("created_by", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("subject_type", "subject_id", "cost_code",
                name="uq_finance_commitment_subject_cost",),
            sa.CheckConstraint("status IN ('committed','cancelled')", name="ck_finance_commitment_status"),)
        op.create_table("finance_allocation_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("allocation_id", sa.String(120), nullable=False, unique=True),
            sa.Column("plan_id_fk",
                sa.Integer(),
                sa.ForeignKey("finance_project_plans.id", ondelete="CASCADE"),
                nullable=False,),
            sa.Column("parent_summary_line_id", sa.String(120), nullable=False),
            sa.Column("summary_work_type", sa.String(160), nullable=False),
            sa.Column("package_net_revenue_huf", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("package_max_direct_cost_huf",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",),
            sa.Column("unallocated_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(40), nullable=False, server_default="approved"),
            sa.Column("source_type", sa.String(40), nullable=False),
            sa.Column("source_version", sa.String(80)),
            sa.Column("source_hash", sa.String(64)),
            sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
            sa.Column("effective_to", sa.DateTime(timezone=True)),
            sa.Column("confidence_percent", sa.Numeric(6, 2), nullable=False, server_default="100"),
            sa.Column("coverage_percent", sa.Numeric(6, 2), nullable=False, server_default="100"),
            sa.Column("approved_by", sa.String(255), nullable=False),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=False),
            sa.Column("snapshot_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("plan_id_fk", "parent_summary_line_id", "version",
                name="uq_finance_allocation_snapshot_version",),
            sa.CheckConstraint("source_type IN ('DETAILED_LINES','NORM_TABLE','HISTORICAL_ACTUAL','SUPPLIER_EVIDENCE','ALLOCATION_UNRESOLVED')",
                name="ck_finance_allocation_source_type",),)
        op.create_table("finance_allocation_snapshot_rows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("row_id", sa.String(120), nullable=False, unique=True),
            sa.Column("allocation_id_fk",
                sa.Integer(),
                sa.ForeignKey("finance_allocation_snapshots.id", ondelete="CASCADE"),
                nullable=False,),
            sa.Column("trade_code", sa.String(100), nullable=False),
            sa.Column("direct_cost_component", sa.String(20), nullable=False),
            sa.Column("normalized_ratio", sa.Numeric(8, 4), nullable=False, server_default="0"),
            sa.Column("allocated_net_huf", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("allocation_id_fk", "trade_code", name="uq_finance_allocation_row_trade"),
            sa.CheckConstraint("direct_cost_component IN ('material','labour','machinery','other')",
                name="ck_finance_allocation_row_component",),)
        op.create_table("margin_gate_decisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("decision_id", sa.String(120), nullable=False, unique=True),
            sa.Column("project_id", sa.String(100), nullable=False),
            sa.Column("plan_id_fk",
                sa.Integer(),
                sa.ForeignKey("finance_project_plans.id", ondelete="SET NULL"),),
            sa.Column("plan_id", sa.String(120)),
            sa.Column("plan_version", sa.Integer()),
            sa.Column("plan_status", sa.String(30)),
            sa.Column("plan_content_sha256", sa.String(64)),
            sa.Column("action_type", sa.String(60), nullable=False),
            sa.Column("subject_type", sa.String(40), nullable=False),
            sa.Column("subject_id", sa.String(120), nullable=False),
            sa.Column("cost_code", sa.String(100)),
            sa.Column("proposed_net_huf", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("revenue_net_huf", sa.Numeric(18, 2)),
            sa.Column("projected_direct_cost_huf", sa.Numeric(18, 2)),
            sa.Column("margin_percent", sa.Numeric(10, 4)),
            sa.Column("required_margin_percent", sa.Numeric(6, 2), nullable=False, server_default="35"),
            sa.Column("decision", sa.String(10), nullable=False),
            sa.Column("block_reason_code", sa.String(60)),
            sa.Column("block_reason_hu", sa.Text()),
            sa.Column("input_snapshot_json", sa.Text(), nullable=False),
            sa.Column("calculation_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("input_sha256", sa.String(64), nullable=False),
            sa.Column("created_by", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("decision IN ('PASS','BLOCK')", name="ck_margin_gate_decision"),)
        op.create_table("margin_gate_vat_rules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("rule_id", sa.String(120), nullable=False, unique=True),
            sa.Column("scope", sa.String(120), nullable=False),
            sa.Column("vat_rate_percent", sa.Numeric(8, 4), nullable=False, server_default="0"),
            sa.Column("input_vat_differential_percent",
                sa.Numeric(8, 4),
                nullable=False,
                server_default="0",),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending_approval"),
            sa.Column("rationale", sa.Text(), nullable=False),
            sa.Column("approved_by", sa.String(255)),
            sa.Column("approved_at", sa.DateTime(timezone=True)),
            sa.Column("created_by", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("status IN ('pending_approval','approved','rejected')",
                name="ck_margin_gate_vat_rule_status",),)
        # Az indexek csak az itteni (tényleges) létrehozás után; a 0001
        # bootstrap-ágban a modellek metadataja már létrehozta őket.
        _indexes("finance_budget_imports", "finance_budget_imports", ("import_id", "content_sha256"),)
        _indexes("finance_commitments", "finance_commitments", ("cost_code", "subject_type", "subject_id"),)
        _indexes("finance_allocation_snapshots", "finance_allocation_snapshots", ("parent_summary_line_id", "snapshot_sha256"),)
        _indexes("finance_allocation_snapshot_rows", "finance_allocation_snapshot_rows", ("trade_code",),)
        _indexes("margin_gate_decisions", "margin_gate_decisions", ("project_id", "action_type", "subject_id", "cost_code", "block_reason_code", "input_sha256",),)
        _indexes("margin_gate_vat_rules", "margin_gate_vat_rules", ("scope", "status"))

    # Oszlopbővítések meglévő táblákon (guarddal, a 0059-es minta szerint).
    _add_missing_column(inspector, "finance_project_plans", sa.Column("content_sha256", sa.String(64), nullable=True),)
    _add_missing_column(inspector, "finance_project_plans", sa.Column("provenance_json", sa.Text(), nullable=False, server_default="{}"),)
    _add_missing_column(inspector, "finance_project_budget_lines", sa.Column("cost_class", sa.String(20), nullable=True),)
    _add_missing_column(inspector, "finance_project_budget_lines", sa.Column("direct_cost_component", sa.String(20), nullable=True),)
    _add_missing_column(inspector, "finance_project_budget_lines", sa.Column("amount_basis", sa.String(40), nullable=True),)
    # Task80 (Review HIGH): a Boolean oszlop server_default-ja PG-érvényes
    # boolean-literál (``DEFAULT false``); a korábbi "0" egész-literál, amit
    # a PostgreSQL boolean oszlopra elutasít. A sa.text konstans, interpoláció
    # nélküli — a Semgrep avoid-sqlalchemy-text szerződése nem sérül.
    _add_missing_column(inspector, "finance_project_budget_lines", sa.Column("is_summary_package", sa.Boolean(), nullable=False, server_default=sa.text("false")),)
    _add_missing_column(inspector, "finance_project_budget_lines", sa.Column("parent_summary_line_id", sa.String(120), nullable=True),)
    _add_missing_column(inspector, "finance_project_budget_lines", sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),)
    _add_missing_column(inspector, "tender_packages", sa.Column("cost_code", sa.String(100), nullable=True),)
    _add_missing_column(inspector, "procurement_requirements", sa.Column("cost_code", sa.String(100), nullable=True),)

    # Indexek az új oszlopokon (guarddal).
    _add_missing_index("finance_project_plans", "ix_finance_project_plans_content_sha256", ("content_sha256",),)
    # Az indexnevek a modellek auto-neveivel egyeznek
    # (ix_finance_project_budget_lines_*), így a friss adatbázis (0001
    # bootstrap) és a migrált adatbázis sémája azonos (Review B LOW-1).
    _add_missing_index("finance_project_budget_lines", "ix_finance_project_budget_lines_cost_class", ("cost_class",),)
    _add_missing_index("finance_project_budget_lines", "ix_finance_project_budget_lines_parent_summary_line_id", ("parent_summary_line_id",),)
    _add_missing_index("tender_packages", "ix_tender_packages_cost_code", ("cost_code",))
    _add_missing_index("procurement_requirements", "ix_procurement_requirements_cost_code", ("cost_code",))

    # Task77 Gate7: egy döntéshez legfeljebb egy megrendelés — atomi kényszer
    # a create_order ellenőrzése mellé; konkurens kettősnél a kényszer dönt.
    _add_missing_unique_constraint("ops_procurement_orders", "uq_ops_procurement_orders_selection_id", ("selection_id",),)


def downgrade() -> None:
    # Az új táblák csak üres állapotban dobhatók el (0050-es minta); üzleti
    # adattal a visszagörgetés a HOUSEPLAN_0049_ROLLBACK_RUNBOOK szerint.
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table in _DOWNGRADE_DROP_ORDER:
        if table not in existing:
            continue
        # A táblanév kizárólag a forráskódban rögzített tuple-ból
        # származik; az SQLAlchemy table-clause idézi az azonosítót
        # (nincs text()-interpoláció, Semgrep avoid-sqlalchemy-text tiszta).
        count = op.get_bind().execute(sa.select(sa.func.count()).select_from(sa.table(table))).scalar()
        if count:
            raise RuntimeError(f"0073 downgrade refused: {table} contains business rows; " "use an approved forward migration instead.")
    # Task79 (Review HIGH): meglévő táblák 0073-oszlopai is eldobandók; valós
    # oszlopadatnál fail-closed elutasítás (nincs részleges visszaállítás).
    for table, column, nullable, default in _ADDED_COLUMNS:
        if table not in existing:
            continue
        if column not in {item["name"] for item in inspector.get_columns(table)}:
            continue
        if _added_column_has_data(table, column, nullable, default):
            raise RuntimeError(f"0073 downgrade refused: {table}.{column} contains business data; " "use an approved forward migration instead.")
    # Task78: az upgrade által hozzáadott egyedi kényszer eldobása a függő
    # táblák ELŐTT (FK-biztos sorrend) — a downgrade pontosan a 0072-es head
    # sémát állítja vissza, a re-upgrade a guard miatt idempotens. Üzleti
    # soroknál a downgrade fent fail-closed elutasításra került, így itt
    # részleges visszaállítás nem történhet.
    _drop_unique_constraint_if_exists("ops_procurement_orders", "uq_ops_procurement_orders_selection_id")
    # FK-biztos sorrend: kényszer → oszlopindexek → oszlopok → új táblák.
    for table, index_names in _ADDED_INDEXES.items():
        if table not in existing:
            continue
        for index_name in index_names:
            _drop_index_if_exists(table, index_name)
    for table, column, _nullable, _default in _ADDED_COLUMNS:
        if table not in existing:
            continue
        _drop_column_if_exists(table, column)
    for table in _DOWNGRADE_DROP_ORDER:
        if table not in existing:
            continue
        op.drop_table(table)
    return None
