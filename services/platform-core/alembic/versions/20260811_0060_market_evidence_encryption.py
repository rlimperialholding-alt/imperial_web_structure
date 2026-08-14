"""Add envelope encryption metadata for market evidence.

Revision ID: 20260811_0060
Revises: 20260811_0059
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260811_0060"
down_revision = "20260811_0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "market_source_snapshots"
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
    additions = (
        ("encrypted_content", sa.Text()),
        ("content_nonce", sa.String(32)),
        ("encrypted_dek", sa.Text()),
        ("dek_nonce", sa.String(32)),
        ("encryption_key_id", sa.String(120)),
        ("erased_at", sa.DateTime(timezone=True)),
    )
    for name, column_type in additions:
        if name not in columns:
            op.add_column(table, sa.Column(name, column_type))
    inspector = sa.inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes(table)}
    for column in ("encryption_key_id", "erased_at"):
        index = f"ix_{table}_{column}"
        if index not in indexes:
            op.create_index(index, table, [column])


def downgrade() -> None:
    raise RuntimeError(
        "0060 stores encryption and erasure evidence. Destructive automatic downgrade is forbidden."
    )
