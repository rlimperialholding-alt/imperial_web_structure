"""Operations Workspace additive schema.

Revision ID: 20260719_0004
Revises: 20260719_0003
"""
from alembic import op
from app.database import Base
from app import models  # noqa: F401

revision = "20260719_0004"
down_revision = "20260719_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # Additive production migration; destructive downgrade is deliberately disabled.
    pass
