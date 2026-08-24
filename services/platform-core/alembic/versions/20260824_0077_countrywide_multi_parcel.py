"""Allow bounded multi-parcel identifiers from the public ÉTDR feed.

Revision ID: 20260824_0077
Revises: 20260824_0076
"""

import sqlalchemy as sa

from alembic import op

revision = "20260824_0077"
down_revision = "20260824_0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("authority_records") as batch:
        batch.alter_column(
            "topographical_number",
            existing_type=sa.String(100),
            type_=sa.String(500),
            existing_nullable=True,
        )
        batch.alter_column(
            "parcel_key",
            existing_type=sa.String(100),
            type_=sa.String(500),
            existing_nullable=True,
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE authority_records SET topographical_number = NULL, parcel_key = NULL "
            "WHERE length(topographical_number) > 100 OR length(parcel_key) > 100"
        )
    )
    with op.batch_alter_table("authority_records") as batch:
        batch.alter_column(
            "topographical_number",
            existing_type=sa.String(500),
            type_=sa.String(100),
            existing_nullable=True,
        )
        batch.alter_column(
            "parcel_key",
            existing_type=sa.String(500),
            type_=sa.String(100),
            existing_nullable=True,
        )
