"""Bind House Designer guest claims to a separate browser session token.

Revision ID: 20260810_0056
Revises: 20260810_0055
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260810_0056"
down_revision = "20260810_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "house_design_guest_claims"
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        raise RuntimeError("House Designer guest claim schema is missing.")
    columns = {column["name"] for column in inspector.get_columns(table)}
    if "guest_session_hash" not in columns:
        op.add_column(table, sa.Column("guest_session_hash", sa.String(64)))
    claims = sa.table(
        table,
        sa.column("token_hash", sa.String(64)),
        sa.column("guest_session_hash", sa.String(64)),
        sa.column("status", sa.String(30)),
        sa.column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        claims.update()
        .where(claims.c.guest_session_hash.is_(None))
        .values(
            guest_session_hash=claims.c.token_hash,
            status="revoked",
            revoked_at=sa.func.now(),
        )
    )
    with op.batch_alter_table(table) as batch:
        batch.alter_column(
            "guest_session_hash",
            existing_type=sa.String(64),
            nullable=False,
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    index_name = "ix_house_design_guest_claims_guest_session_hash"
    if index_name not in indexes:
        op.create_index(index_name, table, ["guest_session_hash"], unique=True)


def downgrade() -> None:
    raise RuntimeError(
        "0056 stores guest session security evidence. Use a forward migration; destructive "
        "automatic downgrade is forbidden."
    )
