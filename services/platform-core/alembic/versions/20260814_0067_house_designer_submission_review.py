"""Add durable House Designer submission review decisions.

Revision ID: 20260814_0067
Revises: 20260814_0066
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260814_0067"
down_revision = "20260814_0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "house_design_submission_decisions"
    inspector = sa.inspect(op.get_bind())
    if "house_design_submissions" not in set(inspector.get_table_names()):
        raise RuntimeError("House Designer submission schema is missing.")
    if table in set(inspector.get_table_names()):
        required_columns = {
            "id",
            "decision_id",
            "submission_id",
            "tenant_id",
            "brand_id",
            "project_id",
            "review_lane",
            "action",
            "from_status",
            "to_status",
            "note",
            "expected_row_version",
            "resulting_row_version",
            "actor_subject_id",
            "actor_role",
            "idempotency_key",
            "created_at",
        }
        actual_columns = {column["name"] for column in inspector.get_columns(table)}
        missing_columns = sorted(required_columns - actual_columns)
        if missing_columns:
            raise RuntimeError(
                "Existing House Designer submission decision schema is incomplete: "
                + ", ".join(missing_columns)
            )
        return
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(120), nullable=False),
        sa.Column("submission_id", sa.String(120), nullable=False),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("project_id", sa.String(120), nullable=False),
        sa.Column("review_lane", sa.String(30), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("from_status", sa.String(40), nullable=False),
        sa.Column("to_status", sa.String(40), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("expected_row_version", sa.Integer(), nullable=False),
        sa.Column("resulting_row_version", sa.Integer(), nullable=False),
        sa.Column("actor_subject_id", sa.String(160), nullable=False),
        sa.Column("actor_role", sa.String(60), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "review_lane IN ('sales','design','compliance','pricing','customer')",
            name="ck_hd_submission_decision_lane",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["house_design_submissions.submission_id"],
            name="fk_hd_submission_decision_submission",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("decision_id", name="uq_hd_submission_decision_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_hd_submission_decision_idempotency",
        ),
    )
    for column in (
        "submission_id",
        "tenant_id",
        "brand_id",
        "project_id",
        "review_lane",
        "action",
        "from_status",
        "to_status",
        "actor_subject_id",
        "actor_role",
        "created_at",
    ):
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    # Review decisions are legal/business audit evidence and are never removed
    # automatically. Roll back application code while retaining the table.
    return None
