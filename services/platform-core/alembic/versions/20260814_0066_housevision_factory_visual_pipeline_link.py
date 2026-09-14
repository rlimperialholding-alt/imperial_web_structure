"""Link Typehouse Factory queue items to visual HouseVision jobs.

Revision ID: 20260814_0066
Revises: 20260813_0065
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260814_0066"
down_revision = "20260813_0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "housevision_factory_jobs"
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        raise RuntimeError("HouseVision Factory job schema is missing.")
    columns = {column["name"] for column in inspector.get_columns(table)}
    if "housevision_job_id" not in columns:
        op.add_column(
            table,
            sa.Column("housevision_job_id", sa.String(length=120), nullable=True),
        )
    indexes = {index["name"]: index for index in sa.inspect(op.get_bind()).get_indexes(table)}
    index_name = "ix_housevision_factory_jobs_housevision_job_id"
    if index_name in indexes and not indexes[index_name].get("unique"):
        raise RuntimeError("Existing HouseVision visual job index is not unique.")
    if index_name not in indexes:
        op.create_index(index_name, table, ["housevision_job_id"], unique=True)


def downgrade() -> None:
    op.drop_index(
        "ix_housevision_factory_jobs_housevision_job_id",
        table_name="housevision_factory_jobs",
    )
    op.drop_column("housevision_factory_jobs", "housevision_job_id")
