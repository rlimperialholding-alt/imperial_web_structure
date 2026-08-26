"""add land agent affiliation fields for hard-gate enforcement

Revision ID: 20260825_0080
Revises: 20260825_0079
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_0080"
down_revision: str | None = "20260825_0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "growth_signals",
        sa.Column("recipient_organization_name", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "growth_signals",
        sa.Column("recipient_office_name", sa.String(length=500), nullable=True),
    )
    op.create_index(
        op.f("ix_growth_signals_recipient_organization_name"),
        "growth_signals",
        ["recipient_organization_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_growth_signals_recipient_office_name"),
        "growth_signals",
        ["recipient_office_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_growth_signals_recipient_office_name"), table_name="growth_signals"
    )
    op.drop_index(
        op.f("ix_growth_signals_recipient_organization_name"),
        table_name="growth_signals",
    )
    op.drop_column("growth_signals", "recipient_office_name")
    op.drop_column("growth_signals", "recipient_organization_name")
