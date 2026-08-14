"""Enforce one open finance plan per project.

Revision ID: 20260802_0040
Revises: 20260802_0039
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0040"
down_revision = "20260802_0039"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_finance_project_single_open_plan"
OPEN_STATUSES = "'draft','review','finance_approved'"


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    indexes = {index["name"] for index in inspector.get_indexes("finance_project_plans")}
    if INDEX_NAME in indexes:
        return

    duplicates = connection.execute(
        sa.text(
            "SELECT project_id, COUNT(*) AS open_count "
            "FROM finance_project_plans "
            f"WHERE status IN ({OPEN_STATUSES}) "
            "GROUP BY project_id HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if duplicates:
        project_ids = ", ".join(str(row.project_id) for row in duplicates)
        raise RuntimeError("Multiple open finance plans must be resolved first: " + project_ids)

    predicate = sa.text(f"status IN ({OPEN_STATUSES})")
    op.create_index(
        INDEX_NAME,
        "finance_project_plans",
        ["project_id"],
        unique=True,
        postgresql_where=predicate,
        sqlite_where=predicate,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="finance_project_plans")
