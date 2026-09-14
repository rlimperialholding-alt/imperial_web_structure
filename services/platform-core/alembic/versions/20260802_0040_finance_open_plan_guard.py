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
OPEN_STATUSES = ("draft", "review", "finance_approved")
# DDL-literal: a CREATE INDEX ... WHERE predikátum PostgreSQL-en nem fogad
# bind paramétert, ezért a rögzített státuszhalmaz tiszta literálként kerül a
# predikátumba (nincs f-string, concat vagy formázás a text() hívásnál).
_OPEN_STATUSES_WHERE = "status IN ('draft', 'review', 'finance_approved')"
if _OPEN_STATUSES_WHERE != "status IN (" + ", ".join(f"'{status}'" for status in OPEN_STATUSES) + ")":
    raise RuntimeError("0040: OPEN_STATUSES és _OPEN_STATUSES_WHERE eltér, a literál szinkronja sérült.")


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    indexes = {index["name"] for index in inspector.get_indexes("finance_project_plans")}
    if INDEX_NAME in indexes:
        return

    duplicates = connection.execute(
        sa.select(sa.column("project_id"), sa.func.count().label("open_count"))
        .select_from(sa.table("finance_project_plans"))
        .where(sa.column("status").in_(OPEN_STATUSES))
        .group_by(sa.column("project_id"))
        .having(sa.func.count() > 1)
    ).fetchall()
    if duplicates:
        project_ids = ", ".join(str(row.project_id) for row in duplicates)
        raise RuntimeError("Multiple open finance plans must be resolved first: " + project_ids)

    predicate = sa.text(_OPEN_STATUSES_WHERE)
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
