"""Partner field portal additive schema.

Revision ID: 20260719_0005
Revises: 20260719_0004
"""
from alembic import op
from app.database import Base
from app import models  # noqa: F401

revision = "20260719_0005"
down_revision = "20260719_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    pass
