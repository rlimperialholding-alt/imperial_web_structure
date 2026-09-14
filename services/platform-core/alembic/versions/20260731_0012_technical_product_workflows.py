"""Add persistent technical product workflows.

Revision ID: 20260731_0012
Revises: 20260730_0011
"""

from alembic import op

from app import models  # noqa: F401
from app.database import Base

revision = "20260731_0012"
down_revision = "20260730_0011"
branch_labels = None
depends_on = None

TABLES = ("cc_technical_cases", "cc_technical_gates")


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
