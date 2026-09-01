"""Add governance decision evidence.

Revision ID: 20260731_0014
Revises: 20260731_0013
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0014"
down_revision = "20260731_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("cc_development_discovery")
    }
    if "review_note" not in columns:
        with op.batch_alter_table("cc_development_discovery") as batch:
            batch.add_column(sa.Column("review_note", sa.Text(), nullable=True))


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("cc_development_discovery")
    }
    if "review_note" in columns:
        with op.batch_alter_table("cc_development_discovery") as batch:
            batch.drop_column("review_note")
