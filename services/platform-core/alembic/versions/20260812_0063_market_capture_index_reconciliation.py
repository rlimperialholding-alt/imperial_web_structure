"""Reconcile market capture indexes after the deployed Typehouse Factory head.

Revision ID: 20260812_0063
Revises: 20260811_0062

The production database reached 0062 from a branch whose parent was 0060.
Fresh databases reach the same state through 0061 -> 0062.  This idempotent
revision makes both histories converge without altering business data.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260812_0063"
down_revision = "20260811_0062"
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
    # These indexes can predate this reconciliation revision (0061).  A
    # downgrade must therefore preserve them and all business data.
    return None
