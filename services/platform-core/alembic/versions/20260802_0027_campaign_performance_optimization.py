"""Add campaign performance ingestion and optimization decisions.

Revision ID: 20260802_0027
Revises: 20260802_0026
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0027"
down_revision = "20260802_0026"
branch_labels = None
depends_on = None


def _indexes(table: str, prefix: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{prefix}_{column}", table, [column])


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    required = {"mkt_campaign_daily_metrics", "mkt_optimization_decisions"}
    present = existing & required
    if present == required:
        return
    if present:
        raise RuntimeError("Partial campaign performance schema: " + ", ".join(sorted(present)))

    op.create_table(
        "mkt_campaign_daily_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("metric_id", sa.String(120), nullable=False, unique=True),
        sa.Column("campaign_id", sa.String(120), nullable=False),
        sa.Column("asset_id", sa.String(120)),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(80), nullable=False),
        sa.Column("source_system", sa.String(100), nullable=False),
        sa.Column("external_key", sa.String(255), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("landing_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("form_starts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("form_completes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("platform_conversions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("spend_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),
        sa.Column("raw_payload_hash", sa.String(64), nullable=False),
        sa.Column("imported_by", sa.String(255), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_system", "external_key", name="uq_mkt_metric_source_key"),
    )
    _indexes(
        "mkt_campaign_daily_metrics",
        "mkt_perf",
        (
            "metric_id",
            "campaign_id",
            "asset_id",
            "metric_date",
            "channel",
            "source_system",
            "external_key",
            "raw_payload_hash",
        ),
    )

    op.create_table(
        "mkt_optimization_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(120), nullable=False, unique=True),
        sa.Column("campaign_id", sa.String(120), nullable=False),
        sa.Column("decision_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="proposed"),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("proposed_budget_net", sa.Numeric(18, 2)),
        sa.Column("proposed_by", sa.String(255), nullable=False),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(255)),
        sa.Column("decision_note", sa.Text()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("executed_by", sa.String(255)),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('proposed','approved','rejected','executed')",
            name="ck_mkt_optimization_status",
        ),
    )
    _indexes(
        "mkt_optimization_decisions",
        "mkt_opt",
        ("decision_id", "campaign_id", "decision_type", "status"),
    )


def downgrade() -> None:
    op.drop_table("mkt_optimization_decisions")
    op.drop_table("mkt_campaign_daily_metrics")
