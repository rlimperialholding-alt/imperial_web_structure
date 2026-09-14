"""Add auditable marketing-consent lifecycle and self-service token.

Revision ID: 20260802_0041
Revises: 20260802_0040
"""

from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20260802_0041"
down_revision = "20260802_0040"
branch_labels = None
depends_on = None

TOKEN_INDEX = "ix_mkt_leads_consent_management_token"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("mkt_leads")}
    with op.batch_alter_table("mkt_leads") as batch:
        if "marketing_consent_updated_at" not in columns:
            batch.add_column(sa.Column("marketing_consent_updated_at", sa.DateTime(timezone=True)))
        if "marketing_consent_source" not in columns:
            batch.add_column(sa.Column("marketing_consent_source", sa.String(120)))
        if "marketing_consent_evidence" not in columns:
            batch.add_column(sa.Column("marketing_consent_evidence", sa.Text()))
        if "marketing_consent_withdrawn_at" not in columns:
            batch.add_column(
                sa.Column("marketing_consent_withdrawn_at", sa.DateTime(timezone=True))
            )
        if "consent_management_token" not in columns:
            batch.add_column(sa.Column("consent_management_token", sa.String(120)))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id FROM mkt_leads WHERE consent_management_token IS NULL")
    ).fetchall()
    for row in rows:
        connection.execute(
            sa.text(
                "UPDATE mkt_leads SET consent_management_token = :token WHERE id = :row_id"
            ),
            {"token": uuid4().hex + uuid4().hex, "row_id": row.id},
        )

    with op.batch_alter_table("mkt_leads") as batch:
        batch.alter_column(
            "consent_management_token",
            existing_type=sa.String(120),
            nullable=False,
        )

    indexes = {index["name"] for index in sa.inspect(connection).get_indexes("mkt_leads")}
    if TOKEN_INDEX not in indexes:
        op.create_index(
            TOKEN_INDEX,
            "mkt_leads",
            ["consent_management_token"],
            unique=True,
        )


def downgrade() -> None:
    indexes = {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("mkt_leads")
    }
    if TOKEN_INDEX in indexes:
        op.drop_index(TOKEN_INDEX, table_name="mkt_leads")
    with op.batch_alter_table("mkt_leads") as batch:
        batch.drop_column("consent_management_token")
        batch.drop_column("marketing_consent_withdrawn_at")
        batch.drop_column("marketing_consent_evidence")
        batch.drop_column("marketing_consent_source")
        batch.drop_column("marketing_consent_updated_at")
