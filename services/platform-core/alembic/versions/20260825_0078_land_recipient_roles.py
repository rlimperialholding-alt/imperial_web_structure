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
    op.add_column(
        "growth_signals",
        sa.Column(
            "recipient_role",
            sa.String(30),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.create_check_constraint(
        "ck_growth_signal_recipient_role",
        "growth_signals",
        "recipient_role IN ('listing_agent','property_owner','unknown')",
    )
    op.create_index(
        "ix_growth_signals_recipient_role",
        "growth_signals",
        ["recipient_role"],
    )


def downgrade() -> None:
    op.drop_index("ix_growth_signals_recipient_role", table_name="growth_signals")
    op.drop_constraint(
        "ck_growth_signal_recipient_role",
        "growth_signals",
        type_="check",
    )
    op.drop_column("growth_signals", "recipient_role")
