"""Add the idempotent internal ÉTDR sales digest ledger.

Revision ID: 20260824_0075
Revises: 20260824_0074
"""

import sqlalchemy as sa

from alembic import op

revision = "20260824_0075"
down_revision = "20260824_0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authority_sales_digests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("digest_id", sa.String(120), nullable=False, unique=True),
        sa.Column("digest_date", sa.Date(), nullable=False),
        sa.Column("window_start_at", sa.DateTime(timezone=True)),
        sa.Column("window_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified_contact_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recipients_sha256", sa.String(64), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("message_rfc822_id", sa.String(255), nullable=False, unique=True),
        sa.Column("gmail_message_id", sa.String(255), unique=True),
        sa.Column("gmail_thread_id", sa.String(255)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(120)),
        sa.Column("lease_owner", sa.String(120)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("digest_date", name="uq_authority_sales_digest_date"),
        sa.CheckConstraint(
            "status IN ('pending','claimed','sent','skipped','retry','dead_letter')",
            name="ck_authority_sales_digest_status",
        ),
    )
    for column in (
        "digest_id",
        "digest_date",
        "window_start_at",
        "window_end_at",
        "status",
        "message_rfc822_id",
        "gmail_message_id",
        "gmail_thread_id",
        "lease_owner",
        "lease_expires_at",
        "sent_at",
    ):
        op.create_index(f"ix_authority_sales_digests_{column}", "authority_sales_digests", [column])

    op.create_table(
        "authority_sales_digest_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "digest_id",
            sa.String(120),
            sa.ForeignKey("authority_sales_digests.digest_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "signal_outbox_id",
            sa.Integer(),
            sa.ForeignKey("authority_signal_outbox.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("item_payload_sha256", sa.String(64), nullable=False),
        sa.Column("item_snapshot_json", sa.Text(), nullable=False),
        sa.Column("contact_status", sa.String(40), nullable=False, server_default="not_available"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("digest_id", "signal_outbox_id", name="uq_authority_digest_item"),
    )
    for column in ("digest_id", "signal_outbox_id", "item_payload_sha256", "contact_status"):
        op.create_index(
            f"ix_authority_sales_digest_items_{column}",
            "authority_sales_digest_items",
            [column],
        )


def downgrade() -> None:
    op.drop_table("authority_sales_digest_items")
    op.drop_table("authority_sales_digests")
