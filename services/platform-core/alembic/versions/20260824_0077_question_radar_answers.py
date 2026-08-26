"""Add the fail-closed question-radar answer queue.

Revision ID: 20260824_0077
Revises: 20260821_0076
"""

import sqlalchemy as sa

from alembic import op

revision = "20260824_0077"
down_revision = "20260821_0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_radar_answers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("answer_id", sa.String(length=120), nullable=False),
        sa.Column("topic_id", sa.String(length=120), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("brand_id", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.String(length=1500), nullable=True),
        sa.Column("source_host", sa.String(length=500), nullable=True),
        sa.Column("disclosure_text", sa.Text(), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answer_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("eligibility_json", sa.Text(), nullable=False),
        sa.Column("review_manifest_json", sa.Text(), nullable=False),
        sa.Column("publication_job_id", sa.String(length=120), nullable=True),
        sa.Column("public_url", sa.String(length=1500), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('ineligible','quarantined','release_ready','channel_blocked',"
            "'published','failed')",
            name="ck_question_radar_answer_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("topic_id", name="uq_question_radar_answer_topic"),
    )
    for column in (
        "answer_id",
        "topic_id",
        "local_date",
        "brand_id",
        "source_host",
        "answer_sha256",
        "status",
        "publication_job_id",
    ):
        op.create_index(
            f"ix_question_radar_answers_{column}",
            "question_radar_answers",
            [column],
            unique=column == "answer_id",
        )


def downgrade() -> None:
    op.drop_table("question_radar_answers")
