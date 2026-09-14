"""Add House Designer entitlement review evidence.

Revision ID: 20260810_0055
Revises: 20260810_0054
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260810_0055"
down_revision = "20260810_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table = "house_designer_entitlements"
    if table not in inspector.get_table_names():
        raise RuntimeError("House Designer entitlement schema is missing.")
    columns = {column["name"] for column in inspector.get_columns(table)}
    additions = (
        sa.Column("activation_requested_at", sa.DateTime(timezone=True)),
        sa.Column("readiness_sha256", sa.String(64)),
        sa.Column("reviewed_by", sa.String(255)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column(table, column)
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    for column in ("readiness_sha256", "reviewed_by"):
        name = f"ix_house_designer_entitlements_{column}"
        if name not in indexes:
            op.create_index(name, table, [column])


def downgrade() -> None:
    raise RuntimeError(
        "0055 stores release approval evidence. Use a forward migration; destructive automatic "
        "downgrade is forbidden."
    )
