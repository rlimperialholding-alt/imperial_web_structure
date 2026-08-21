"""Allow source-backed project signals without a named organization.

Revision ID: 20260821_0076
Revises: 20260821_0075
"""

from alembic import op

revision = "20260821_0076"
down_revision = "20260821_0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("growth_signals") as batch:
        batch.drop_constraint("ck_growth_signal_subject_type", type_="check")
        batch.create_check_constraint(
            "ck_growth_signal_subject_type",
            "subject_type IN ('organization','natural_person','project')",
        )


def downgrade() -> None:
    with op.batch_alter_table("growth_signals") as batch:
        batch.drop_constraint("ck_growth_signal_subject_type", type_="check")
        batch.create_check_constraint(
            "ck_growth_signal_subject_type",
            "subject_type IN ('organization','natural_person')",
        )
