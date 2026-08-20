"""Add canonical wide growth policy, daily gates, and exact outreach release.

Revision ID: 20260820_0073
Revises: 20260816_0072
"""

import sqlalchemy as sa

from alembic import op

revision = "20260820_0073"
down_revision = "20260816_0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("growth_outreach_messages", sa.Column("release_token_hash", sa.String(64)))
    op.add_column("growth_outreach_messages", sa.Column("release_approved_by", sa.String(255)))
    op.add_column(
        "growth_outreach_messages",
        sa.Column("release_approved_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_growth_outreach_messages_release_token_hash",
        "growth_outreach_messages",
        ["release_token_hash"],
    )

    op.create_table(
        "canonical_growth_daily_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(120), nullable=False, unique=True),
        sa.Column("local_date", sa.Date(), nullable=False, unique=True),
        sa.Column("spec_version", sa.String(120), nullable=False),
        sa.Column("source_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("source_route_catalog_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("route_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_leads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("question_topics", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_brands", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("iora_opportunities", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("etdr_new_or_changed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("etdr_start_not_verified", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("etdr_completion_not_verified", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "internal_handoff_status",
            sa.String(40),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "external_publication_status",
            sa.String(40),
            nullable=False,
            server_default="blocked",
        ),
        sa.Column(
            "external_outreach_status",
            sa.String(40),
            nullable=False,
            server_default="blocked",
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("gate_errors_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('running','full','partial','blocked','failed')",
            name="ck_canonical_growth_daily_status",
        ),
    )
    for column in ("run_id", "local_date", "spec_version", "source_manifest_sha256", "status"):
        op.create_index(
            f"ix_canonical_growth_daily_runs_{column}",
            "canonical_growth_daily_runs",
            [column],
        )

    op.create_table(
        "daily_content_obligations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("content_asset_id", sa.String(120)),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("release_token_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("local_date", "brand_id", name="uq_daily_content_brand"),
        sa.CheckConstraint(
            "status IN ('pending','drafted','quarantined','release_passed','published','failed')",
            name="ck_daily_content_status",
        ),
    )
    for column in ("local_date", "brand_id", "status", "content_asset_id"):
        op.create_index(
            f"ix_daily_content_obligations_{column}", "daily_content_obligations", [column]
        )

    op.create_table(
        "question_radar_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.String(120), nullable=False, unique=True),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("use_case", sa.String(120), nullable=False),
        sa.Column("source_url", sa.String(1500)),
        sa.Column("classification", sa.String(40), nullable=False, server_default="observed"),
        sa.Column("dedupe_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("local_date", "dedupe_hash", name="uq_question_radar_daily_hash"),
    )
    for column in ("topic_id", "local_date", "brand_id", "use_case", "dedupe_hash"):
        op.create_index(f"ix_question_radar_topics_{column}", "question_radar_topics", [column])

    op.create_table(
        "canonical_llm_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(120), nullable=False, unique=True),
        sa.Column("run_id", sa.String(120)),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("purpose", sa.String(80), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached_prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("response_sha256", sa.String(64)),
        sa.Column("status", sa.String(30), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("request_id", "run_id", "provider", "model", "purpose", "status"):
        op.create_index(f"ix_canonical_llm_usage_{column}", "canonical_llm_usage", [column])


def downgrade() -> None:
    op.drop_table("canonical_llm_usage")
    op.drop_table("question_radar_topics")
    op.drop_table("daily_content_obligations")
    op.drop_table("canonical_growth_daily_runs")
    op.drop_index(
        "ix_growth_outreach_messages_release_token_hash",
        table_name="growth_outreach_messages",
    )
    op.drop_column("growth_outreach_messages", "release_approved_at")
    op.drop_column("growth_outreach_messages", "release_approved_by")
    op.drop_column("growth_outreach_messages", "release_token_hash")
