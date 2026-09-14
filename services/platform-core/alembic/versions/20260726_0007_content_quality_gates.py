"""Content quality gates and fail-closed publication state.

Revision ID: 20260726_0007
Revises: 20260719_0006
"""

from alembic import op

from app import models  # noqa: F401
from app.database import Base


revision = "20260726_0007"
down_revision = "20260719_0006"
branch_labels = None
depends_on = None

TABLES = [
    "cq_source_records",
    "cq_copy_briefs",
    "cq_content_assets",
    "cq_review_runs",
    "cq_gate_decisions",
    "cq_approvals",
    "cq_golden_copy_samples",
    "cq_performance_metrics",
]


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
