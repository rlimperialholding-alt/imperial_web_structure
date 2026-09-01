"""Add Prefab intent declarations and explicit MyImperial access.

Revision ID: 20260801_0021
Revises: 20260801_0020
"""

import sqlalchemy as sa
from alembic import op

revision = "20260801_0021"
down_revision = "20260801_0020"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: list[str]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    offer_columns = {row["name"] for row in inspector.get_columns("cc_reservation_offer_versions")}
    if "intent_declaration_enabled" not in offer_columns:
        op.add_column("cc_reservation_offer_versions", sa.Column("intent_declaration_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.add_column("cc_reservation_offer_versions", sa.Column("intent_valid_days", sa.Integer(), nullable=False, server_default="30"))
        op.add_column("cc_reservation_offer_versions", sa.Column("intent_public_summary", sa.Text(), nullable=False, server_default=""))

    required = {"cc_intent_declarations", "cc_customer_portal_access"}
    present = existing & required
    if present == required:
        return
    if present:
        raise RuntimeError("Partial Intent/MyImperial schema detected; refusing unsafe migration: " + ", ".join(sorted(present)))

    op.create_table(
        "cc_intent_declarations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("intent_declaration_id", sa.String(120), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("lead_id", sa.String(120), nullable=True),
        sa.Column("opportunity_id", sa.String(120), nullable=True),
        sa.Column("offer_version_id", sa.String(120), sa.ForeignKey("cc_reservation_offer_versions.offer_version_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("house_plan_id", sa.String(120), nullable=False),
        sa.Column("house_config_id", sa.String(120), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("customer_phone", sa.String(80), nullable=False),
        sa.Column("target_start_window", sa.String(120), nullable=False),
        sa.Column("project_scope", sa.Text(), nullable=False),
        sa.Column("plot_status", sa.String(120), nullable=False),
        sa.Column("price_snapshot_id", sa.String(120), nullable=False),
        sa.Column("terms_version_id", sa.String(120), nullable=False),
        sa.Column("technical_scope_version_id", sa.String(120), nullable=False),
        sa.Column("consent_version_id", sa.String(120), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="submitted"),
        sa.Column("delivery_evidence_url", sa.String(1000), nullable=True),
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("contract_id", sa.String(120), nullable=True),
        sa.Column("cancellation_token", sa.String(160), nullable=False, unique=True),
        sa.Column("next_action", sa.Text(), nullable=False),
        sa.Column("attribution_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("cc_intent_declarations", ["intent_declaration_id", "project_id", "lead_id", "opportunity_id", "offer_version_id", "brand_id", "house_plan_id", "house_config_id", "customer_name", "customer_email", "price_snapshot_id", "terms_version_id", "technical_scope_version_id", "expires_at", "status", "contract_id", "cancellation_token"])

    op.create_table(
        "cc_customer_portal_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("access_id", sa.String(120), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "customer_email", name="uq_cc_customer_portal_project_email"),
    )
    _indexes("cc_customer_portal_access", ["access_id", "project_id", "customer_email", "source_type", "source_id", "active"])


def downgrade() -> None:
    op.drop_table("cc_customer_portal_access")
    op.drop_table("cc_intent_declarations")
    op.drop_column("cc_reservation_offer_versions", "intent_public_summary")
    op.drop_column("cc_reservation_offer_versions", "intent_valid_days")
    op.drop_column("cc_reservation_offer_versions", "intent_declaration_enabled")
