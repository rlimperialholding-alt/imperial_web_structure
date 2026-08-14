"""Add native Procurement execution lifecycle.

Revision ID: 20260802_0034
Revises: 20260802_0033
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0034"
down_revision = "20260802_0033"
branch_labels = None
depends_on = None

TABLES = {
    "procurement_requirements", "procurement_offers", "procurement_selections",
    "procurement_substitution_reviews", "procurement_deviations", "procurement_invoice_matches",
}


def _ix(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    present = existing & TABLES
    if present and present != TABLES:
        raise RuntimeError("Partial Procurement schema: " + ", ".join(sorted(present)))
    if present == TABLES:
        return

    order_columns = {c["name"] for c in inspector.get_columns("ops_procurement_orders")}
    order_additions = [
        sa.Column("requirement_id", sa.String(120)), sa.Column("selection_id", sa.String(120)),
        sa.Column("ordered_quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(40), nullable=False, server_default="db"),
        sa.Column("approval_status", sa.String(40), nullable=False, server_default="approved"),
        sa.Column("confirmation_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)), sa.Column("confirmed_by", sa.String(255)),
        sa.Column("content_sha256", sa.String(64)), sa.Column("created_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]
    for column in order_additions:
        if column.name not in order_columns: op.add_column("ops_procurement_orders", column)
    for column in ("requirement_id", "selection_id", "approval_status", "confirmation_status", "content_sha256"):
        if column not in order_columns: op.create_index(f"ix_ops_procurement_orders_{column}", "ops_procurement_orders", [column])

    delivery_columns = {c["name"] for c in inspector.get_columns("ops_delivery_notes")}
    for column in (
        sa.Column("supplier_signed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("receiver_signed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("signature_evidence_ref", sa.String(1200)),
    ):
        if column.name not in delivery_columns: op.add_column("ops_delivery_notes", column)

    op.create_table(
        "procurement_requirements",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("requirement_id", sa.String(120), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False), sa.Column("work_package_id", sa.String(120)),
        sa.Column("category", sa.String(120), nullable=False), sa.Column("scope_description", sa.Text(), nullable=False),
        sa.Column("specification", sa.Text(), nullable=False), sa.Column("net_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("waste_pct", sa.Numeric(8, 4), nullable=False, server_default="0"),
        sa.Column("max_orderable_quantity", sa.Numeric(18, 4), nullable=False), sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("required_at", sa.DateTime(timezone=True), nullable=False), sa.Column("budget_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("target_huf", sa.Numeric(18, 2), nullable=False), sa.Column("status", sa.String(40), nullable=False, server_default="spec_pending"),
        sa.Column("revision_no", sa.Integer(), nullable=False, server_default="1"), sa.Column("revision_reason", sa.Text()),
        sa.Column("technical_approved_by", sa.String(255)), sa.Column("technical_approved_at", sa.DateTime(timezone=True)),
        sa.Column("budget_approved_by", sa.String(255)), sa.Column("budget_approved_at", sa.DateTime(timezone=True)),
        sa.Column("cash_approved_by", sa.String(255)), sa.Column("cash_approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("procurement_requirements", "requirement_id", "project_id", "work_package_id", "category", "required_at", "status")

    op.create_table(
        "procurement_offers",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("offer_id", sa.String(120), nullable=False, unique=True),
        sa.Column("requirement_id", sa.String(120), nullable=False), sa.Column("supplier_name", sa.String(500), nullable=False),
        sa.Column("partner_id", sa.String(120)), sa.Column("net_total_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("delivery_cost_huf", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("other_landed_cost_huf", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_landed_cost_huf", sa.Numeric(18, 2), nullable=False), sa.Column("lead_time_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warranty_months", sa.Integer(), nullable=False, server_default="0"), sa.Column("payment_terms", sa.String(500), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"), sa.Column("technical_compliant", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("valid_until", sa.DateTime(timezone=True)), sa.Column("document_ref", sa.String(1200), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="received"), sa.Column("notes", sa.Text()),
        sa.Column("created_by", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("procurement_offers", "offer_id", "requirement_id", "supplier_name", "partner_id", "status")

    op.create_table(
        "procurement_selections",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("selection_id", sa.String(120), nullable=False, unique=True),
        sa.Column("requirement_id", sa.String(120), nullable=False), sa.Column("offer_id", sa.String(120), nullable=False),
        sa.Column("total_landed_cost_huf", sa.Numeric(18, 2), nullable=False), sa.Column("savings_pct", sa.Numeric(8, 4), nullable=False),
        sa.Column("market_evidence_ref", sa.String(1200)), sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("risk_rationale", sa.Text(), nullable=False), sa.Column("status", sa.String(40), nullable=False, server_default="approval_pending"),
        sa.Column("dual_approval_required", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("prepared_by", sa.String(255), nullable=False),
        sa.Column("finance_approved_by", sa.String(255)), sa.Column("finance_approved_at", sa.DateTime(timezone=True)),
        sa.Column("md_approved_by", sa.String(255)), sa.Column("md_approved_at", sa.DateTime(timezone=True)),
        sa.Column("owner_approved_by", sa.String(255)), sa.Column("owner_approved_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text()), sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("procurement_selections", "selection_id", "requirement_id", "offer_id", "status")

    op.create_table(
        "procurement_substitution_reviews",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("review_id", sa.String(120), nullable=False, unique=True),
        sa.Column("requirement_id", sa.String(120), nullable=False), sa.Column("proposed_product", sa.String(1000), nullable=False),
        sa.Column("proposed_specification", sa.Text(), nullable=False), sa.Column("technical_equivalence", sa.Text(), nullable=False),
        sa.Column("declaration_ref", sa.String(1200), nullable=False), sa.Column("price_impact_huf", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("schedule_impact_days", sa.Integer(), nullable=False, server_default="0"), sa.Column("risk_assessment", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False), sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.String(255), nullable=False), sa.Column("reviewed_by", sa.String(255)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("procurement_substitution_reviews", "review_id", "requirement_id", "status")

    op.create_table(
        "procurement_deviations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("deviation_id", sa.String(120), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False), sa.Column("order_id", sa.String(120), nullable=False),
        sa.Column("delivery_note_id", sa.String(120)), sa.Column("deviation_type", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False), sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False), sa.Column("corrective_action", sa.Text(), nullable=False),
        sa.Column("financial_impact_huf", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(40), nullable=False, server_default="open"), sa.Column("resolution", sa.Text()),
        sa.Column("resolved_by", sa.String(255)), sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("procurement_deviations", "deviation_id", "project_id", "order_id", "delivery_note_id", "deviation_type", "status")

    op.create_table(
        "procurement_invoice_matches",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("match_id", sa.String(120), nullable=False, unique=True),
        sa.Column("order_id", sa.String(120), nullable=False), sa.Column("delivery_note_id", sa.String(120), nullable=False),
        sa.Column("invoice_reference", sa.String(255), nullable=False, unique=True), sa.Column("invoice_total_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("ordered_total_huf", sa.Numeric(18, 2), nullable=False), sa.Column("accepted_value_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("blockers_json", sa.Text(), nullable=False, server_default="[]"), sa.Column("status", sa.String(40), nullable=False, server_default="blocked"),
        sa.Column("payment_ready", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("matched_by", sa.String(255), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("procurement_invoice_matches", "match_id", "order_id", "delivery_note_id", "invoice_reference", "status", "payment_ready")


def downgrade() -> None:
    for table in ("procurement_invoice_matches", "procurement_deviations", "procurement_substitution_reviews", "procurement_selections", "procurement_offers", "procurement_requirements"):
        op.drop_table(table)
