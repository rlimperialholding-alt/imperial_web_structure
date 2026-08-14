"""Add deny-first ITEP permissions for Market Intelligence.

Revision ID: 20260811_0058
Revises: 20260810_0057
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260811_0058"
down_revision = "20260810_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "market_permission_grants"
    inspector = sa.inspect(op.get_bind())
    if table in inspector.get_table_names():
        return
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("grant_id", sa.String(160), nullable=False),
        sa.Column("subject_id", sa.String(140), nullable=False),
        sa.Column("permission", sa.String(100), nullable=False),
        sa.Column("effect", sa.String(10), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_key", sa.String(500), nullable=False),
        sa.Column("tenant_id", sa.String(120)),
        sa.Column("brand_id", sa.String(120)),
        sa.Column("market_id", sa.String(120)),
        sa.Column("revision", sa.String(100), nullable=False),
        sa.Column("claim_sequence", sa.Integer(), nullable=False),
        sa.Column("claim_issuer", sa.String(255), nullable=False),
        sa.Column("claim_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("grant_id", name="uq_mkt_permission_grant_id"),
        sa.UniqueConstraint(
            "subject_id",
            "permission",
            "scope_key",
            "effect",
            "revision",
            name="uq_mkt_permission_revision",
        ),
        sa.CheckConstraint("effect IN ('allow','deny')", name="ck_mkt_permission_effect"),
        sa.CheckConstraint(
            "scope_type IN ('global','brand_market')", name="ck_mkt_permission_scope"
        ),
        sa.CheckConstraint(
            "status IN ('active','revoked','expired')", name="ck_mkt_permission_status"
        ),
    )
    for column in (
        "grant_id",
        "subject_id",
        "permission",
        "effect",
        "scope_type",
        "scope_key",
        "tenant_id",
        "brand_id",
        "market_id",
        "claim_sequence",
        "claim_sha256",
        "status",
        "valid_from",
        "expires_at",
    ):
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    raise RuntimeError(
        "0058 stores authorization evidence. Use a forward migration; destructive automatic "
        "downgrade is forbidden."
    )
