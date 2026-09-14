"""Add full tender partner portal workflow.

Revision ID: 20260802_0023
Revises: 20260802_0022
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0023"
down_revision = "20260802_0022"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: list[str]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    required = {
        "tender_packages",
        "tender_invitations",
        "tender_bids",
        "tender_bid_items",
        "tender_clarifications",
        "tender_bid_evidence",
        "tender_evaluations",
    }
    present = existing & required
    if present == required:
        return
    if present:
        raise RuntimeError("Partial tender portal schema detected: " + ", ".join(sorted(present)))

    op.create_table(
        "tender_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tender_id", sa.String(120), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),
        sa.Column("question_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submission_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("evaluation_criteria_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("awarded_bid_id", sa.String(120)),
        sa.Column("award_summary", sa.Text()),
        sa.Column("awarded_by", sa.String(255)),
        sa.Column("awarded_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','published','closed','evaluation','awarded','cancelled')",
            name="ck_tender_package_status",
        ),
    )
    _indexes(
        "tender_packages",
        [
            "tender_id",
            "project_id",
            "question_deadline_at",
            "submission_deadline_at",
            "status",
            "awarded_bid_id",
        ],
    )

    op.create_table(
        "tender_invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invitation_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "tender_id_fk",
            sa.Integer(),
            sa.ForeignKey("tender_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mail_recipient_id", sa.String(120), unique=True),
        sa.Column("partner_email", sa.String(320), nullable=False),
        sa.Column("company_name", sa.String(500), nullable=False),
        sa.Column("contact_name", sa.String(255)),
        sa.Column("access_token", sa.String(160), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="invited"),
        sa.Column("viewed_at", sa.DateTime(timezone=True)),
        sa.Column("declined_at", sa.DateTime(timezone=True)),
        sa.Column("decline_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tender_id_fk", "partner_email", name="uq_tender_invitation_email"),
    )
    _indexes(
        "tender_invitations",
        [
            "invitation_id",
            "tender_id_fk",
            "mail_recipient_id",
            "partner_email",
            "access_token",
            "status",
        ],
    )

    op.create_table(
        "tender_bids",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bid_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "tender_id_fk",
            sa.Integer(),
            sa.ForeignKey("tender_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invitation_id_fk",
            sa.Integer(),
            sa.ForeignKey("tender_invitations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),
        sa.Column("net_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("vat_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("gross_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("validity_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("lead_time_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warranty_months", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text()),
        sa.Column("exclusions", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("tender_bids", ["bid_id", "tender_id_fk", "invitation_id_fk", "status"])

    op.create_table(
        "tender_bid_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "bid_id_fk",
            sa.Integer(),
            sa.ForeignKey("tender_bids.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("bid_id_fk", "line_no", name="uq_tender_bid_line"),
    )
    _indexes("tender_bid_items", ["item_id", "bid_id_fk"])

    op.create_table(
        "tender_clarifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clarification_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "tender_id_fk",
            sa.Integer(),
            sa.ForeignKey("tender_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invitation_id_fk",
            sa.Integer(),
            sa.ForeignKey("tender_invitations.id", ondelete="CASCADE"),
        ),
        sa.Column("author_email", sa.String(320), nullable=False),
        sa.Column("author_type", sa.String(30), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("partner_visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("tender_clarifications", ["clarification_id", "tender_id_fk", "invitation_id_fk"])

    op.create_table(
        "tender_bid_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evidence_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "bid_id_fk",
            sa.Integer(),
            sa.ForeignKey("tender_bids.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("caption", sa.Text()),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("tender_bid_evidence", ["evidence_id", "bid_id_fk", "sha256"])

    op.create_table(
        "tender_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evaluation_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "tender_id_fk",
            sa.Integer(),
            sa.ForeignKey("tender_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bid_id_fk",
            sa.Integer(),
            sa.ForeignKey("tender_bids.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evaluator_email", sa.String(320), nullable=False),
        sa.Column("price_score", sa.Integer(), nullable=False),
        sa.Column("technical_score", sa.Integer(), nullable=False),
        sa.Column("timeline_score", sa.Integer(), nullable=False),
        sa.Column("references_score", sa.Integer(), nullable=False),
        sa.Column("weighted_total", sa.Numeric(6, 2), nullable=False),
        sa.Column("recommendation", sa.String(30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("bid_id_fk", "evaluator_email", name="uq_tender_bid_evaluator"),
    )
    _indexes(
        "tender_evaluations", ["evaluation_id", "tender_id_fk", "bid_id_fk", "evaluator_email"]
    )


def downgrade() -> None:
    op.drop_table("tender_evaluations")
    op.drop_table("tender_bid_evidence")
    op.drop_table("tender_clarifications")
    op.drop_table("tender_bid_items")
    op.drop_table("tender_bids")
    op.drop_table("tender_invitations")
    op.drop_table("tender_packages")
