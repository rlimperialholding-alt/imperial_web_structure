"""Add canonical evidence processing and internal handoff ledger.

Revision ID: 20260821_0075
Revises: 20260820_0074
"""

import sqlalchemy as sa

from alembic import op

revision = "20260821_0075"
down_revision = "20260820_0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_coverage_attempts",
        sa.Column("analysis_status", sa.String(30), nullable=False, server_default="pending"),
    )
    op.add_column(
        "source_coverage_attempts",
        sa.Column("analysis_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column("source_coverage_attempts", sa.Column("analysis_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_source_coverage_attempts_analysis_status",
        "source_coverage_attempts",
        ["analysis_status"],
    )
    op.create_index(
        "ix_source_coverage_attempts_analysis_at",
        "source_coverage_attempts",
        ["analysis_at"],
    )
    op.create_table(
        "canonical_internal_handoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("handoff_id", sa.String(120), nullable=False, unique=True),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("handoff_type", sa.String(80), nullable=False, server_default="daily_executive"),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("counts_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_message_id", sa.String(500)),
        sa.Column("last_error", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','sent','failed','blocked')",
            name="ck_canonical_handoff_status",
        ),
        sa.UniqueConstraint("local_date", "handoff_type", name="uq_canonical_handoff_day_type"),
    )
    for column in (
        "handoff_id",
        "local_date",
        "handoff_type",
        "payload_sha256",
        "status",
        "provider_message_id",
    ):
        op.create_index(
            f"ix_canonical_internal_handoffs_{column}",
            "canonical_internal_handoffs",
            [column],
        )


def downgrade() -> None:
    op.drop_table("canonical_internal_handoffs")
    op.drop_index("ix_source_coverage_attempts_analysis_at", table_name="source_coverage_attempts")
    op.drop_index(
        "ix_source_coverage_attempts_analysis_status", table_name="source_coverage_attempts"
    )
    op.drop_column("source_coverage_attempts", "analysis_at")
    op.drop_column("source_coverage_attempts", "analysis_json")
    op.drop_column("source_coverage_attempts", "analysis_status")
