"""Add a fail-closed lifecycle to tender invitation links.

Revision ID: 20260813_0064
Revises: 20260812_0063
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260813_0064"
down_revision = "20260812_0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "tender_invitations"
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
    additions = (
        sa.Column("token_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", sa.String(255)),
        sa.Column("revoke_reason", sa.Text()),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column(table, column)
    op.execute(
        sa.text(
            """
            UPDATE tender_invitations AS invitation
               SET expires_at = package.submission_deadline_at
              FROM tender_packages AS package
             WHERE package.id = invitation.tender_id_fk
               AND invitation.expires_at IS NULL
            """
        )
    )
    with op.batch_alter_table(table) as batch:
        batch.alter_column("expires_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if "ix_tender_invitations_expires_at" not in indexes:
        op.create_index("ix_tender_invitations_expires_at", table, ["expires_at"])


def downgrade() -> None:
    # The lifecycle fields contain security and audit evidence. Automated rollback
    # intentionally preserves them and all existing business data.
    return None
