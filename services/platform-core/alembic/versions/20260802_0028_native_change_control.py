"""Add native ChangeControl workflow and MyImperial source binding.

Revision ID: 20260802_0028
Revises: 20260802_0027
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0028"
down_revision = "20260802_0027"
branch_labels = None
depends_on = None


def _index(table: str, prefix: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{prefix}_{column}", table, [column])


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    required = {"change_cases", "change_versions", "change_lines"}
    present = existing & required
    if present and present != required:
        raise RuntimeError("Partial ChangeControl schema: " + ", ".join(sorted(present)))

    if not present:
        op.create_table(
            "change_cases",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.String(120), nullable=False, unique=True),
            sa.Column("project_id", sa.String(100), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("change_type", sa.String(50), nullable=False),
            sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
            sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("responsible", sa.String(255), nullable=False),
            sa.Column("created_by", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('draft','internal_review','internal_rejected',"
                "'customer_review','customer_rejected','approved',"
                "'work_authorized','completed','cancelled')",
                name="ck_change_case_status",
            ),
        )
        _index(
            "change_cases",
            "chg_case",
            ("change_id", "project_id", "title", "change_type", "status", "responsible"),
        )

        op.create_table(
            "change_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("version_id", sa.String(140), nullable=False, unique=True),
            sa.Column(
                "change_id_fk",
                sa.Integer(),
                sa.ForeignKey("change_cases.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("technical_scope", sa.Text(), nullable=False),
            sa.Column("exclusions", sa.Text(), nullable=False),
            sa.Column("assumptions", sa.Text(), nullable=False),
            sa.Column("deadline_impact_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("vat_rate", sa.Numeric(6, 2), nullable=False, server_default="27"),
            sa.Column(
                "customer_advance_net", sa.Numeric(18, 2), nullable=False, server_default="0"
            ),
            sa.Column("cost_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("sale_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("vat_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("sale_gross", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("margin_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("margin_percent", sa.Numeric(6, 2), nullable=False, server_default="0"),
            sa.Column(
                "early_direct_cost_net", sa.Numeric(18, 2), nullable=False, server_default="0"
            ),
            sa.Column(
                "leadership_required", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("technical_approved_by", sa.String(255)),
            sa.Column("technical_approval_note", sa.Text()),
            sa.Column("technical_approved_at", sa.DateTime(timezone=True)),
            sa.Column("finance_approved_by", sa.String(255)),
            sa.Column("finance_approval_note", sa.Text()),
            sa.Column("finance_approved_at", sa.DateTime(timezone=True)),
            sa.Column("leadership_approved_by", sa.String(255)),
            sa.Column("leadership_approval_note", sa.Text()),
            sa.Column("leadership_approved_at", sa.DateTime(timezone=True)),
            sa.Column("customer_decision_id", sa.String(120)),
            sa.Column("work_authorized_by", sa.String(255)),
            sa.Column("work_authorized_at", sa.DateTime(timezone=True)),
            sa.Column("calendar_entry_id", sa.String(120)),
            sa.Column("completion_evidence_url", sa.String(1000)),
            sa.Column("completed_by", sa.String(255)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("content_sha256", sa.String(64)),
            sa.Column("created_by", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("change_id_fk", "version", name="uq_change_case_version"),
            sa.CheckConstraint(
                "status IN ('draft','internal_review','internal_rejected',"
                "'customer_review','customer_accepted','customer_rejected',"
                "'work_authorized','completed','superseded')",
                name="ck_change_version_status",
            ),
            sa.CheckConstraint("vat_rate >= 0 AND vat_rate <= 100", name="ck_change_vat_rate"),
        )
        _index(
            "change_versions",
            "chg_ver",
            (
                "version_id",
                "change_id_fk",
                "status",
                "leadership_required",
                "customer_decision_id",
                "calendar_entry_id",
                "content_sha256",
            ),
        )

        op.create_table(
            "change_lines",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("line_id", sa.String(120), nullable=False, unique=True),
            sa.Column(
                "version_id_fk",
                sa.Integer(),
                sa.ForeignKey("change_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("category", sa.String(100), nullable=False),
            sa.Column("description", sa.String(500), nullable=False),
            sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
            sa.Column("unit", sa.String(40), nullable=False),
            sa.Column("unit_cost_net", sa.Numeric(18, 2), nullable=False),
            sa.Column("unit_sale_net", sa.Numeric(18, 2), nullable=False),
            sa.Column("total_cost_net", sa.Numeric(18, 2), nullable=False),
            sa.Column("total_sale_net", sa.Numeric(18, 2), nullable=False),
            sa.Column("early_direct_cost", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("quantity > 0", name="ck_change_line_quantity"),
            sa.CheckConstraint(
                "unit_cost_net >= 0 AND unit_sale_net >= 0",
                name="ck_change_line_nonnegative_prices",
            ),
        )
        _index(
            "change_lines",
            "chg_line",
            ("line_id", "version_id_fk", "category", "early_direct_cost"),
        )

    decision_columns = {
        row["name"] for row in inspector.get_columns("cc_customer_decision_requests")
    }
    for name, column in (
        ("source_module", sa.Column("source_module", sa.String(100))),
        ("source_object_id", sa.Column("source_object_id", sa.String(160))),
        ("source_version", sa.Column("source_version", sa.Integer())),
    ):
        if name not in decision_columns:
            op.add_column("cc_customer_decision_requests", column)
            op.create_index(f"ix_myi_dec_{name}", "cc_customer_decision_requests", [name])


def downgrade() -> None:
    for column in ("source_version", "source_object_id", "source_module"):
        op.drop_index(f"ix_myi_dec_{column}", table_name="cc_customer_decision_requests")
        op.drop_column("cc_customer_decision_requests", column)
    op.drop_table("change_lines")
    op.drop_table("change_versions")
    op.drop_table("change_cases")
