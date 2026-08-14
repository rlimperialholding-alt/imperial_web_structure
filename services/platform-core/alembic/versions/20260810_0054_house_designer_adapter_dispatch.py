"""Add durable House Designer adapter dispatch retry state.

Revision ID: 20260810_0054
Revises: 20260810_0053
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260810_0054"
down_revision = "20260810_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "house_designer_adapter_jobs" not in inspector.get_table_names():
        raise RuntimeError("House Designer adapter job schema is missing.")
    columns = {column["name"] for column in inspector.get_columns("house_designer_adapter_jobs")}
    additions = (
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("house_designer_adapter_jobs", column)
    indexes = {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("house_designer_adapter_jobs")
    }
    for column in ("next_attempt_at", "dispatched_at"):
        name = f"ix_house_designer_adapter_jobs_{column}"
        if name not in indexes:
            op.create_index(name, "house_designer_adapter_jobs", [column])


def downgrade() -> None:
    raise RuntimeError(
        "0054 stores dispatch/retry evidence. Use a forward migration; destructive automatic "
        "downgrade is forbidden."
    )
