"""Serialize canonical CRM and ITEP synchronization operations.

Revision ID: 20260816_0070
Revises: 20260815_0069
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260816_0070"
down_revision = "20260815_0069"
branch_labels = None
depends_on = None

LEASE_KEYS = (
    "crm-import",
    "crm-push",
    "crm-reconcile",
    "itep-pull",
    "itep-push",
)


def upgrade() -> None:
    table_name = "ic_canonical_sync_leases"
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        op.create_table(
            table_name,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("lease_key", sa.String(80), nullable=False),
            sa.Column("holder_token", sa.String(64), nullable=True),
            sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("contention_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_contention_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_released_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("lease_key", name="uq_ic_canonical_sync_lease_key"),
        )
        op.create_index(
            "ix_ic_canonical_sync_leases_lease_key",
            table_name,
            ["lease_key"],
            unique=True,
        )
        op.create_index(
            "ix_ic_canonical_sync_leases_holder_token",
            table_name,
            ["holder_token"],
            unique=False,
        )
        op.create_index(
            "ix_ic_canonical_sync_leases_expires_at",
            table_name,
            ["expires_at"],
            unique=False,
        )
    else:
        required_columns = {
            "lease_key",
            "holder_token",
            "acquired_at",
            "heartbeat_at",
            "expires_at",
            "generation",
            "contention_count",
            "last_contention_at",
            "last_released_at",
            "updated_at",
        }
        present_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        missing_columns = sorted(required_columns - present_columns)
        if missing_columns:
            raise RuntimeError(
                "Canonical sync lease schema is incomplete: "
                + ", ".join(missing_columns)
            )
    lease_table = sa.table(
        table_name,
        sa.column("lease_key", sa.String),
        sa.column("generation", sa.Integer),
        sa.column("contention_count", sa.Integer),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    existing = {
        row[0]
        for row in op.get_bind().execute(sa.select(lease_table.c.lease_key)).all()
    }
    now = sa.func.now()
    for lease_key in LEASE_KEYS:
        if lease_key not in existing:
            op.execute(
                lease_table.insert().values(
                    lease_key=lease_key,
                    generation=0,
                    contention_count=0,
                    updated_at=now,
                )
            )


def downgrade() -> None:
    # Lease history is operational evidence and intentionally survives code rollback.
    return None
