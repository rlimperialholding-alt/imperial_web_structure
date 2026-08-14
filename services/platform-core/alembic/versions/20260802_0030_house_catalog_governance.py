"""Add governed House Catalog plan and release versions.

Revision ID: 20260802_0030
Revises: 20260802_0029
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0030"
down_revision = "20260802_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    required = {"house_catalog_plans", "house_catalog_versions"}
    present = existing & required
    if present and present != required:
        raise RuntimeError("Partial House Catalog schema: " + ", ".join(sorted(present)))
    if present:
        return
    op.create_table(
        "house_catalog_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("house_id", sa.String(120), nullable=False, unique=True),
        sa.Column("brand", sa.String(120), nullable=False),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("lifecycle_status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("current_released_version", sa.Integer()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "lifecycle_status IN ('active','withdrawn')",
            name="ck_house_catalog_plan_lifecycle",
        ),
    )
    for column in ("house_id", "brand", "canonical_name", "lifecycle_status"):
        op.create_index(f"ix_house_catalog_plan_{column}", "house_catalog_plans", [column])

    op.create_table(
        "house_catalog_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("catalog_version_id", sa.String(150), nullable=False, unique=True),
        sa.Column(
            "house_id",
            sa.String(120),
            sa.ForeignKey("house_catalog_plans.house_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("catalog_price_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("gross_area_m2", sa.Numeric(10, 2), nullable=False),
        sa.Column("rooms", sa.String(120), nullable=False),
        sa.Column("price_status", sa.String(80), nullable=False),
        sa.Column("data_quality", sa.String(80), nullable=False),
        sa.Column("lifestyles_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("source_type", sa.String(100), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("source_verified_at", sa.String(120), nullable=False),
        sa.Column("rights_evidence", sa.Text(), nullable=False),
        sa.Column("technical_summary", sa.Text(), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64)),
        sa.Column("source_approved_by", sa.String(255)),
        sa.Column("source_approval_note", sa.Text()),
        sa.Column("source_approved_at", sa.DateTime(timezone=True)),
        sa.Column("technical_approved_by", sa.String(255)),
        sa.Column("technical_approval_note", sa.Text()),
        sa.Column("technical_approved_at", sa.DateTime(timezone=True)),
        sa.Column("commercial_approved_by", sa.String(255)),
        sa.Column("commercial_approval_note", sa.Text()),
        sa.Column("commercial_approved_at", sa.DateTime(timezone=True)),
        sa.Column("released_by", sa.String(255)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawn_by", sa.String(255)),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawal_reason", sa.Text()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("house_id", "version", name="uq_house_catalog_plan_version"),
        sa.CheckConstraint(
            "status IN ('draft','review','rejected','approved','released',"
            "'superseded','withdrawn')",
            name="ck_house_catalog_version_status",
        ),
    )
    for column in (
        "catalog_version_id",
        "house_id",
        "status",
        "content_sha256",
    ):
        op.create_index(f"ix_house_catalog_version_{column}", "house_catalog_versions", [column])


def downgrade() -> None:
    op.drop_table("house_catalog_versions")
    op.drop_table("house_catalog_plans")
