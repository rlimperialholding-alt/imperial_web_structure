"""Classify land-listing recipients for role-specific outreach.

Revision ID: 20260825_0078
Revises: 20260825_0077
"""

import sqlalchemy as sa

from alembic import op

revision = "20260825_0078"
down_revision = "20260825_0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode keeps this migration portable: SQLite cannot add a check
    # constraint with ALTER TABLE, while PostgreSQL can execute the same
    # operations through Alembic's batch abstraction.
    with op.batch_alter_table("growth_signals") as batch_op:
        batch_op.add_column(
            sa.Column(
                "recipient_role",
                sa.String(30),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.create_check_constraint(
            "ck_growth_signal_recipient_role",
            "recipient_role IN ('listing_agent','property_owner','unknown')",
        )
        batch_op.create_index(
            "ix_growth_signals_recipient_role",
            ["recipient_role"],
        )


def downgrade() -> None:
    with op.batch_alter_table("growth_signals") as batch_op:
        batch_op.drop_index("ix_growth_signals_recipient_role")
        batch_op.drop_constraint(
            "ck_growth_signal_recipient_role",
            type_="check",
        )
        batch_op.drop_column("recipient_role")
