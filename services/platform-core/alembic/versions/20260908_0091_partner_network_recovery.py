"""Add durable partner-network stop and legacy reconciliation ledgers.

Revision ID: 20260908_0091
Revises: 20260906_0090
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260908_0091"
down_revision = "20260906_0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "growth_account_stops",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stop_id", sa.String(120), nullable=False),
        sa.Column("account_key", sa.String(500), nullable=False),
        sa.Column("organization_key", sa.String(500), nullable=True),
        sa.Column("scope", sa.String(30), nullable=False),
        sa.Column("stop_kind", sa.String(40), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("source_event_id", sa.String(500), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stop_id", name="uq_growth_account_stops_stop_id"),
        sa.UniqueConstraint(
            "source",
            "source_event_id",
            "account_key",
            name="uq_growth_account_stop_source_event_account",
        ),
        sa.CheckConstraint(
            "scope IN ('email','domain','organization','group')",
            name="ck_growth_account_stop_scope",
        ),
        sa.CheckConstraint(
            "stop_kind IN ('response','rejection','dnc','bounce','complaint',"
            "'existing_relationship','hard_suppression','other_brand_active')",
            name="ck_growth_account_stop_kind",
        ),
    )
    for column in (
        "stop_id",
        "account_key",
        "organization_key",
        "scope",
        "stop_kind",
        "source",
        "source_event_id",
        "active",
        "occurred_at",
    ):
        op.create_index(f"ix_growth_account_stops_{column}", "growth_account_stops", [column])

    op.create_table(
        "growth_outreach_reconciliations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reconciliation_id", sa.String(120), nullable=False),
        sa.Column("source_record_id", sa.String(160), nullable=False),
        sa.Column("candidate_id", sa.String(160), nullable=True),
        sa.Column("recipient_email", sa.String(320), nullable=True),
        sa.Column("classification", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reconciliation_id", name="uq_growth_outreach_reconciliations_id"),
        sa.UniqueConstraint("source_record_id", name="uq_growth_reconciliation_source_record"),
        sa.CheckConstraint(
            "classification IN ('ALREADY_SENT','REPLIED_STOP','DNC_STOP','BOUNCE_BLOCK',"
            "'OWNER_MANUAL_ONLY','DUPLICATE_STOP','STALE_REQUALIFY','READY_TO_SEND',"
            "'SEND_UNVERIFIED_REVIEW','OTHER')",
            name="ck_growth_reconciliation_classification",
        ),
    )
    for column in (
        "reconciliation_id",
        "source_record_id",
        "candidate_id",
        "recipient_email",
        "classification",
        "reconciled_at",
    ):
        op.create_index(
            f"ix_growth_outreach_reconciliations_{column}",
            "growth_outreach_reconciliations",
            [column],
        )


def downgrade() -> None:
    op.drop_table("growth_outreach_reconciliations")
    op.drop_table("growth_account_stops")
