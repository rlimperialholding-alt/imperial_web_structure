"""Commercial integration and duplicate-development gate.

Revision ID: 20260719_0006
Revises: 20260719_0005
"""
from alembic import op
import sqlalchemy as sa
from app.database import Base
from app import models  # noqa: F401

revision = "20260719_0006"
down_revision = "20260719_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "cc_releases" in tables:
        cols = {c["name"] for c in inspector.get_columns("cc_releases")}
        if "discovery_request_id" not in cols:
            op.add_column("cc_releases", sa.Column("discovery_request_id", sa.String(length=120), nullable=True))
            op.create_index("ix_cc_releases_discovery_request_id", "cc_releases", ["discovery_request_id"], unique=False)
        if "reuse_gate_passed" not in cols:
            op.add_column("cc_releases", sa.Column("reuse_gate_passed", sa.Boolean(), nullable=False, server_default=sa.false()))
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    pass
