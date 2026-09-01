"""Add campaign orchestration and lead intelligence.

Revision ID: 20260802_0026
Revises: 20260802_0025
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0026"
down_revision = "20260802_0025"
branch_labels = None
depends_on = None


def _indexes(table: str, prefix: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{prefix}_{column}", table, [column])


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    required = {"mkt_campaigns", "mkt_leads", "mkt_lead_activities"}
    present = existing & required
    if present == required:
        return
    if present:
        raise RuntimeError("Partial marketing automation schema: " + ", ".join(sorted(present)))

    op.create_table(
        "mkt_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.String(120), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("channels_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("budget_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),
        sa.Column("target_leads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_cpl_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("utm_source", sa.String(120), nullable=False),
        sa.Column("utm_medium", sa.String(120), nullable=False),
        sa.Column("utm_campaign", sa.String(160), nullable=False, unique=True),
        sa.Column("landing_page_url", sa.String(1200)),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("owner_email", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("submitted_by", sa.String(255)),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','review','approved','active','paused','completed','cancelled')",
            name="ck_mkt_campaign_status",
        ),
    )
    _indexes(
        "mkt_campaigns",
        "mkt_cmp",
        (
            "campaign_id",
            "name",
            "brand_id",
            "start_date",
            "end_date",
            "utm_campaign",
            "status",
            "owner_email",
        ),
    )

    op.create_table(
        "mkt_leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.String(120), nullable=False, unique=True),
        sa.Column("dedupe_key", sa.String(64), nullable=False, unique=True),
        sa.Column("campaign_id", sa.String(120)),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("channel", sa.String(80), nullable=False),
        sa.Column("landing_page_url", sa.String(1200)),
        sa.Column("utm_source", sa.String(120)),
        sa.Column("utm_medium", sa.String(120)),
        sa.Column("utm_campaign", sa.String(160)),
        sa.Column("utm_content", sa.String(160)),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(80)),
        sa.Column("company", sa.String(255)),
        sa.Column("lead_type", sa.String(20), nullable=False, server_default="b2c"),
        sa.Column("project_location", sa.String(255)),
        sa.Column("estimated_budget_huf", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("timeframe_months", sa.Integer()),
        sa.Column("intent_summary", sa.Text()),
        sa.Column(
            "privacy_notice_accepted", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("privacy_notice_version", sa.String(80), nullable=False),
        sa.Column("marketing_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(30), nullable=False, server_default="new"),
        sa.Column("signal_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("assigned_sales_email", sa.String(255)),
        sa.Column("qualification_note", sa.Text()),
        sa.Column("crm_record_id", sa.String(120)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("qualified_at", sa.DateTime(timezone=True)),
        sa.Column("handed_off_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('new','scored','marketing_qualified','crm_handoff',"
            "'sales_accepted','sales_rejected','disqualified','converted')",
            name="ck_mkt_lead_status",
        ),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_mkt_lead_score"),
    )
    _indexes(
        "mkt_leads",
        "mkt_lead",
        (
            "lead_id",
            "dedupe_key",
            "campaign_id",
            "source",
            "channel",
            "utm_source",
            "utm_campaign",
            "full_name",
            "email",
            "phone",
            "company",
            "lead_type",
            "marketing_consent",
            "score",
            "status",
            "assigned_sales_email",
            "crm_record_id",
        ),
    )

    op.create_table(
        "mkt_lead_activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("activity_id", sa.String(120), nullable=False, unique=True),
        sa.Column("lead_id", sa.String(120), nullable=False),
        sa.Column("activity_type", sa.String(80), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("actor", sa.String(255)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes(
        "mkt_lead_activities",
        "mkt_act",
        ("activity_id", "lead_id", "activity_type", "actor"),
    )


def downgrade() -> None:
    op.drop_table("mkt_lead_activities")
    op.drop_table("mkt_leads")
    op.drop_table("mkt_campaigns")
