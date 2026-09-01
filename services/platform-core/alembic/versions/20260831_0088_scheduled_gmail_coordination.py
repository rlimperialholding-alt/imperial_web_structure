"""Coordinate direct scheduled Gmail delivery with the central outreach ledger.

Revision ID: 20260831_0088
Revises: 20260830_0087
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260831_0088"
down_revision = "20260830_0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "growth_scheduled_gmail_leases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lease_id", sa.String(120), nullable=False),
        sa.Column("outreach_id", sa.String(120), nullable=False),
        sa.Column("client_id", sa.String(120), nullable=False),
        sa.Column("token_nonce", sa.String(64), nullable=False),
        sa.Column("lease_token_sha256", sa.String(64), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("quota_local_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="authorized"),
        sa.Column("global_guard_claim_token", sa.String(120)),
        sa.Column("provider_message_id", sa.String(500)),
        sa.Column("provider_internal_date", sa.DateTime(timezone=True)),
        sa.Column("readback_mime_sha256", sa.String(64)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("aborted_at", sa.DateTime(timezone=True)),
        sa.Column("abort_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('authorized','sent','accepted_unverified','aborted')",
            name="ck_growth_scheduled_gmail_lease_status",
        ),
        sa.ForeignKeyConstraint(
            ["outreach_id"],
            ["growth_outreach_messages.outreach_id"],
            name="fk_growth_scheduled_gmail_lease_outreach",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("lease_id", name="uq_growth_scheduled_gmail_lease_id"),
        sa.UniqueConstraint("outreach_id", name="uq_growth_scheduled_gmail_lease_outreach"),
        sa.UniqueConstraint(
            "provider_message_id",
            name="uq_growth_scheduled_gmail_lease_provider_message",
        ),
    )
    for column in (
        "lease_id",
        "outreach_id",
        "client_id",
        "lease_token_sha256",
        "payload_sha256",
        "quota_local_date",
        "status",
        "global_guard_claim_token",
        "provider_message_id",
        "provider_internal_date",
        "readback_mime_sha256",
        "expires_at",
        "accepted_at",
        "verified_at",
        "aborted_at",
    ):
        op.create_index(
            f"ix_growth_scheduled_gmail_leases_{column}",
            "growth_scheduled_gmail_leases",
            [column],
        )

    op.create_table(
        "growth_scheduled_gmail_lease_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(120), nullable=False),
        sa.Column("client_id", sa.String(120), nullable=False),
        sa.Column("lease_id", sa.String(120), nullable=False),
        sa.Column("outreach_id", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="authorized"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('authorized','sent','accepted_unverified','aborted')",
            name="ck_growth_scheduled_gmail_lease_request_status",
        ),
        sa.ForeignKeyConstraint(
            ["lease_id"],
            ["growth_scheduled_gmail_leases.lease_id"],
            name="fk_growth_scheduled_gmail_lease_request_lease",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["outreach_id"],
            ["growth_outreach_messages.outreach_id"],
            name="fk_growth_scheduled_gmail_lease_request_outreach",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "request_id",
            name="uq_growth_scheduled_gmail_lease_request_id",
        ),
    )
    for column in (
        "request_id",
        "client_id",
        "lease_id",
        "outreach_id",
        "status",
        "created_at",
        "updated_at",
    ):
        op.create_index(
            f"ix_growth_scheduled_gmail_lease_requests_{column}",
            "growth_scheduled_gmail_lease_requests",
            [column],
        )


def downgrade() -> None:
    op.drop_table("growth_scheduled_gmail_lease_requests")
    op.drop_table("growth_scheduled_gmail_leases")
