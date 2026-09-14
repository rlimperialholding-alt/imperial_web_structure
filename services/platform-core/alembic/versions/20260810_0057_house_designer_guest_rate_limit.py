"""Add durable House Designer guest creation rate limiting.

Revision ID: 20260810_0057
Revises: 20260810_0056
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260810_0057"
down_revision = "20260810_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "house_designer_guest_rate_limits"
    inspector = sa.inspect(op.get_bind())
    if table in inspector.get_table_names():
        return
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rate_limit_id", sa.String(120), nullable=False),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("fingerprint_hash", sa.String(64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_until", sa.DateTime(timezone=True)),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("rate_limit_id", name="uq_hd_guest_rate_limit_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "brand_id",
            "fingerprint_hash",
            name="uq_hd_guest_rate_scope_fingerprint",
        ),
    )
    for column in (
        "rate_limit_id",
        "tenant_id",
        "brand_id",
        "fingerprint_hash",
        "window_started_at",
        "blocked_until",
    ):
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    raise RuntimeError(
        "0057 stores abuse-prevention evidence. Use a forward migration; destructive automatic "
        "downgrade is forbidden."
    )
