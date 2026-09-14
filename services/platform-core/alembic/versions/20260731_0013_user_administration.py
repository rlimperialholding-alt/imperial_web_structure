"""Add production user onboarding state.

Revision ID: 20260731_0013
Revises: 20260731_0012
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0013"
down_revision = "20260731_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("cc_users")}
    if "must_change_password" not in columns:
        with op.batch_alter_table("cc_users") as batch:
            batch.add_column(
                sa.Column(
                    "must_change_password",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("cc_users")}
    if "must_change_password" in columns:
        with op.batch_alter_table("cc_users") as batch:
            batch.drop_column("must_change_password")
