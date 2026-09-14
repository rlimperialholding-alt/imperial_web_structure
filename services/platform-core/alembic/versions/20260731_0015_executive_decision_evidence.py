"""Add executive decision evidence.

Revision ID: 20260731_0015
Revises: 20260731_0014
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0015"
down_revision = "20260731_0014"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    event_columns = _columns("cc_events")
    with op.batch_alter_table("cc_events") as batch:
        if "resolution_note" not in event_columns:
            batch.add_column(sa.Column("resolution_note", sa.Text(), nullable=True))
        if "resolved_by" not in event_columns:
            batch.add_column(sa.Column("resolved_by", sa.String(length=255), nullable=True))
        if "resolved_at" not in event_columns:
            batch.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    issue_columns = _columns("cc_consistency_issues")
    if "assignment_note" not in issue_columns:
        with op.batch_alter_table("cc_consistency_issues") as batch:
            batch.add_column(sa.Column("assignment_note", sa.Text(), nullable=True))


def downgrade() -> None:
    issue_columns = _columns("cc_consistency_issues")
    if "assignment_note" in issue_columns:
        with op.batch_alter_table("cc_consistency_issues") as batch:
            batch.drop_column("assignment_note")
    event_columns = _columns("cc_events")
    with op.batch_alter_table("cc_events") as batch:
        for name in ("resolved_at", "resolved_by", "resolution_note"):
            if name in event_columns:
                batch.drop_column(name)
