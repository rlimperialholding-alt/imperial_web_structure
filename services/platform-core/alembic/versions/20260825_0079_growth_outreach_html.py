"""Store optional reviewed HTML for multipart outreach email.

Revision ID: 20260825_0079
Revises: 20260825_0078
"""

import sqlalchemy as sa

from alembic import op

revision = "20260825_0079"
down_revision = "20260825_0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "growth_outreach_messages",
        sa.Column("body_html", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("growth_outreach_messages", "body_html")
