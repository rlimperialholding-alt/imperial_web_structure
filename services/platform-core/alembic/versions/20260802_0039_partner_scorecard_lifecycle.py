"""Complete the Partner Control scorecard lifecycle.

Revision ID: 20260802_0039
Revises: 20260802_0038
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0039"
down_revision = "20260802_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("partner_project_evaluations")}
    expected = {"cooperation_score", "warranty_score", "weighting_version"}
    present = columns & expected
    if present and present != expected:
        raise RuntimeError("Partial Partner scorecard schema: " + ", ".join(sorted(present)))
    if present == expected:
        return
    op.add_column(
        "partner_project_evaluations",
        sa.Column("cooperation_score", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "partner_project_evaluations",
        sa.Column("warranty_score", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "partner_project_evaluations",
        sa.Column(
            "weighting_version",
            sa.String(60),
            nullable=False,
            server_default="partner-score-v1",
        ),
    )


def downgrade() -> None:
    op.drop_column("partner_project_evaluations", "weighting_version")
    op.drop_column("partner_project_evaluations", "warranty_score")
    op.drop_column("partner_project_evaluations", "cooperation_score")
