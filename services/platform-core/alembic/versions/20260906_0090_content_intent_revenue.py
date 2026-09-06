"""Persist source replenishment work created by the revenue content gate.

Revision ID: 20260906_0090
Revises: 20260901_0089
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op


revision = "20260906_0090"
down_revision = "20260901_0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_source_replenishment_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(120), nullable=False),
        sa.Column("dedupe_key", sa.String(180), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("radar_topic_id", sa.String(120), nullable=True),
        sa.Column("buyer_problem", sa.Text(), nullable=False),
        sa.Column("required_fact_types_json", sa.Text(), nullable=False, server_default='["brand_fact"]'),
        sa.Column("source_urls_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_content_source_replenishment_task_id"),
        sa.UniqueConstraint("dedupe_key", name="uq_content_source_replenishment_dedupe"),
        sa.CheckConstraint(
            "status IN ('open','resolved','cancelled')",
            name="ck_content_source_replenishment_status",
        ),
    )
    for column in ("task_id", "dedupe_key", "local_date", "brand_id", "radar_topic_id", "status"):
        op.create_index(f"ix_content_source_replenishment_{column}", "content_source_replenishment_tasks", [column])


def downgrade() -> None:
    for column in ("task_id", "dedupe_key", "local_date", "brand_id", "radar_topic_id", "status"):
        op.drop_index(f"ix_content_source_replenishment_{column}", table_name="content_source_replenishment_tasks")
    op.drop_table("content_source_replenishment_tasks")
