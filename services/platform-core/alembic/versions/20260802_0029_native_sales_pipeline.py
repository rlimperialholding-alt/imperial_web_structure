"""Add native customer-specific Sales opportunity and proposal lifecycle.

Revision ID: 20260802_0029
Revises: 20260802_0028
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0029"
down_revision = "20260802_0028"
branch_labels = None
depends_on = None


def _index(table: str, prefix: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{prefix}_{column}", table, [column])


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    required = {"sales_opportunities", "sales_proposal_versions"}
    present = existing & required
    if present and present != required:
        raise RuntimeError("Partial Sales schema: " + ", ".join(sorted(present)))
    if present:
        return

    op.create_table(
        "sales_opportunities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("opportunity_id", sa.String(120), nullable=False, unique=True),
        sa.Column("lead_id", sa.String(120)),
        sa.Column("customer_id", sa.String(120)),
        sa.Column("crm_record_id", sa.String(120)),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("customer_email", sa.String(255)),
        sa.Column("owner_email", sa.String(255), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False, server_default="new"),
        sa.Column("estimated_value_huf", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("probability_percent", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("expected_close_date", sa.Date()),
        sa.Column("needs_summary", sa.Text(), nullable=False),
        sa.Column("budget_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("decision_process", sa.Text(), nullable=False),
        sa.Column("next_action", sa.Text(), nullable=False),
        sa.Column("loss_reason", sa.Text()),
        sa.Column("competitor", sa.String(255)),
        sa.Column("accepted_proposal_version_id", sa.String(120)),
        sa.Column("contract_id", sa.String(120)),
        sa.Column("delivery_project_id", sa.String(100)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "stage IN ('new','qualified','discovery','proposal','negotiation',"
            "'contracting','won','lost')",
            name="ck_sales_opportunity_stage",
        ),
        sa.CheckConstraint(
            "probability_percent >= 0 AND probability_percent <= 100",
            name="ck_sales_opportunity_probability",
        ),
    )
    _index(
        "sales_opportunities",
        "sales_opp",
        (
            "opportunity_id",
            "lead_id",
            "customer_id",
            "crm_record_id",
            "brand_id",
            "title",
            "customer_name",
            "customer_email",
            "owner_email",
            "stage",
            "expected_close_date",
            "accepted_proposal_version_id",
            "contract_id",
            "delivery_project_id",
        ),
    )

    op.create_table(
        "sales_proposal_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proposal_version_id", sa.String(140), nullable=False, unique=True),
        sa.Column(
            "opportunity_id",
            sa.String(120),
            sa.ForeignKey("sales_opportunities.opportunity_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),
        sa.Column("vat_rate", sa.Numeric(6, 2), nullable=False, server_default="27"),
        sa.Column("cost_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("sale_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("vat_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("sale_gross", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("margin_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("margin_percent", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("price_snapshot_id", sa.String(120), nullable=False),
        sa.Column("terms_version_id", sa.String(120), nullable=False),
        sa.Column("technical_scope_version_id", sa.String(120), nullable=False),
        sa.Column("scope_summary", sa.Text(), nullable=False),
        sa.Column("exclusions", sa.Text(), nullable=False),
        sa.Column("payment_terms", sa.Text(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("technical_approved_by", sa.String(255)),
        sa.Column("technical_approval_note", sa.Text()),
        sa.Column("technical_approved_at", sa.DateTime(timezone=True)),
        sa.Column("finance_approved_by", sa.String(255)),
        sa.Column("finance_approval_note", sa.Text()),
        sa.Column("finance_approved_at", sa.DateTime(timezone=True)),
        sa.Column("legal_approved_by", sa.String(255)),
        sa.Column("legal_approval_note", sa.Text()),
        sa.Column("legal_approved_at", sa.DateTime(timezone=True)),
        sa.Column("content_sha256", sa.String(64)),
        sa.Column("sent_by", sa.String(255)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_evidence_url", sa.String(1000)),
        sa.Column("customer_decision_reference", sa.String(255)),
        sa.Column("customer_decision_note", sa.Text()),
        sa.Column("customer_decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("opportunity_id", "version", name="uq_sales_proposal_version"),
        sa.CheckConstraint(
            "status IN ('draft','internal_review','rejected','approved','sent','accepted',"
            "'customer_rejected','expired','superseded')",
            name="ck_sales_proposal_status",
        ),
        sa.CheckConstraint("vat_rate >= 0 AND vat_rate <= 100", name="ck_sales_proposal_vat"),
    )
    _index(
        "sales_proposal_versions",
        "sales_prop",
        (
            "proposal_version_id",
            "opportunity_id",
            "status",
            "price_snapshot_id",
            "terms_version_id",
            "technical_scope_version_id",
            "valid_until",
            "content_sha256",
        ),
    )


def downgrade() -> None:
    op.drop_table("sales_proposal_versions")
    op.drop_table("sales_opportunities")
