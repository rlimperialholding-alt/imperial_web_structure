"""Add versioned project finance planning and forecast baselines.

Revision ID: 20260802_0025
Revises: 20260802_0024
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0025"
down_revision = "20260802_0024"
branch_labels = None
depends_on = None


def _indexes(table: str, prefix: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{prefix}_{column}", table, [column])


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    required = {
        "finance_project_plans",
        "finance_project_budget_lines",
        "finance_project_cashflow_lines",
    }
    present = existing & required
    if present == required:
        return
    if present:
        raise RuntimeError("Partial project finance schema: " + ", ".join(sorted(present)))

    op.create_table(
        "finance_project_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.String(120), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),
        sa.Column("contract_revenue_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column(
            "approved_change_revenue_net", sa.Numeric(18, 2), nullable=False, server_default="0"
        ),
        sa.Column("contingency_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("target_margin_percent", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("forecast_note", sa.Text()),
        sa.Column("submitted_by", sa.String(255)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("finance_approved_by", sa.String(255)),
        sa.Column("finance_approved_at", sa.DateTime(timezone=True)),
        sa.Column("leadership_approved_by", sa.String(255)),
        sa.Column("leadership_approved_at", sa.DateTime(timezone=True)),
        sa.Column("margin_exception_reason", sa.Text()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "version", name="uq_finance_project_plan_version"),
        sa.CheckConstraint(
            "status IN ('draft','review','finance_approved','approved','superseded','rejected')",
            name="ck_finance_project_plan_status",
        ),
        sa.CheckConstraint(
            "target_margin_percent >= 0 AND target_margin_percent <= 100",
            name="ck_finance_plan_target_margin",
        ),
    )
    _indexes("finance_project_plans", "fin_plan", ("plan_id", "project_id", "status"))

    op.create_table(
        "finance_project_budget_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("line_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "plan_id_fk",
            sa.Integer(),
            sa.ForeignKey("finance_project_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cost_code", sa.String(100), nullable=False),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("budget_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("committed_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("actual_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column(
            "estimate_to_complete_net", sa.Numeric(18, 2), nullable=False, server_default="0"
        ),
        sa.Column("source_type", sa.String(80)),
        sa.Column("source_id", sa.String(160)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("plan_id_fk", "cost_code", name="uq_finance_plan_cost_code"),
    )
    _indexes(
        "finance_project_budget_lines",
        "fin_budget",
        ("line_id", "plan_id_fk", "cost_code", "category", "source_id"),
    )

    op.create_table(
        "finance_project_cashflow_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flow_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "plan_id_fk",
            sa.Integer(),
            sa.ForeignKey("finance_project_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("amount_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="forecast"),
        sa.Column("source_type", sa.String(80)),
        sa.Column("source_id", sa.String(160)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "direction IN ('inflow','outflow')", name="ck_finance_cashflow_direction"
        ),
        sa.CheckConstraint(
            "status IN ('forecast','committed','actual')", name="ck_finance_cashflow_status"
        ),
    )
    _indexes(
        "finance_project_cashflow_lines",
        "fin_flow",
        ("flow_id", "plan_id_fk", "period_date", "direction", "category", "status", "source_id"),
    )


def downgrade() -> None:
    op.drop_table("finance_project_cashflow_lines")
    op.drop_table("finance_project_budget_lines")
    op.drop_table("finance_project_plans")
