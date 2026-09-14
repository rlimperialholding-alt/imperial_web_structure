"""Add composite indexes for governed market capture operations.

Revision ID: 20260811_0061
Revises: 20260811_0060
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260811_0061"
down_revision = "20260811_0060"
branch_labels = None
depends_on = None


INDEXES = {
    "ix_mkt_capture_scope_created": (
        "tenant_id",
        "brand_id",
        "market_id",
        "created_at",
    ),
    "ix_mkt_capture_scope_status_finished": (
        "tenant_id",
        "brand_id",
        "market_id",
        "status",
        "finished_at",
    ),
    "ix_mkt_capture_target_created": ("tenant_id", "target_id", "created_at"),
}


def upgrade() -> None:
    table = "market_capture_jobs"
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    for name, columns in INDEXES.items():
        if name not in existing:
            op.create_index(name, table, list(columns))


def downgrade() -> None:
    table = "market_capture_jobs"
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    for name in reversed(INDEXES):
        if name in existing:
            op.drop_index(name, table_name=table)
