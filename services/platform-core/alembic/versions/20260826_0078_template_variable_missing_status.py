"""Record fail-closed canonical-template variable gaps.

Revision ID: 20260826_0078
Revises: 20260824_0077
"""

from alembic import op

revision = "20260826_0078"
down_revision = "20260824_0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("growth_signals") as batch:
        batch.drop_constraint("ck_growth_signal_status", type_="check")
        batch.create_check_constraint(
            "ck_growth_signal_status",
            "status IN ('accepted','rejected','blocked','queued',"
            "'contacted','responded','suppressed','template-variable-missing')",
        )


def downgrade() -> None:
    op.execute(
        "UPDATE growth_signals SET status = 'blocked' WHERE status = 'template-variable-missing'"
    )
    with op.batch_alter_table("growth_signals") as batch:
        batch.drop_constraint("ck_growth_signal_status", type_="check")
        batch.create_check_constraint(
            "ck_growth_signal_status",
            "status IN ('accepted','rejected','blocked','queued',"
            "'contacted','responded','suppressed')",
        )
