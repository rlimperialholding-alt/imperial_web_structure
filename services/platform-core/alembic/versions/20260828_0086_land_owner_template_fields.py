"""Store the exact plot size required by the owner-approved land email.

Revision ID: 20260828_0086
Revises: 20260828_0085
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260828_0086"
down_revision = "20260828_0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("growth_signals") as batch:
        batch.add_column(sa.Column("plot_size_sqm", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "ck_growth_signal_plot_size_sqm",
            "plot_size_sqm IS NULL OR (plot_size_sqm > 0 AND plot_size_sqm <= 10000000)",
        )


def downgrade() -> None:
    with op.batch_alter_table("growth_signals") as batch:
        batch.drop_constraint("ck_growth_signal_plot_size_sqm", type_="check")
        batch.drop_column("plot_size_sqm")
