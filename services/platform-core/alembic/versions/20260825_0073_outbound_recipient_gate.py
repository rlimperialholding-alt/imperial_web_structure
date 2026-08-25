"""Persist recipient policy context for final-dispatch enforcement.

Revision ID: 20260825_0073
Revises: 20260816_0072
"""

import sqlalchemy as sa

from alembic import op

revision = "20260825_0073"
down_revision = "20260816_0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "growth_signals",
        sa.Column(
            "recipient_policy_context_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("growth_signals", "recipient_policy_context_json")
