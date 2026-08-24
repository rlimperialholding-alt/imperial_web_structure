"""Scale the ÉTDR lead reader for countrywide parcel matching.

Revision ID: 20260824_0076
Revises: 20260824_0075
"""

import sqlalchemy as sa

from alembic import op

revision = "20260824_0076"
down_revision = "20260824_0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("authority_records", sa.Column("parcel_key", sa.String(100)))
    op.execute(
        sa.text(
            "UPDATE authority_records SET parcel_key = "
            "lower(replace(replace(replace(topographical_number, ' ', ''), "
            "char(9), ''), char(10), '')) WHERE topographical_number IS NOT NULL"
        )
    )
    op.create_index("ix_authority_records_parcel_key", "authority_records", ["parcel_key"])
    op.create_index(
        "ix_authority_records_source_city_parcel_status_submission",
        "authority_records",
        ["source_key", "city", "parcel_key", "status", "submission_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_authority_records_source_city_parcel_status_submission",
        table_name="authority_records",
    )
    op.drop_index("ix_authority_records_parcel_key", table_name="authority_records")
    op.drop_column("authority_records", "parcel_key")
