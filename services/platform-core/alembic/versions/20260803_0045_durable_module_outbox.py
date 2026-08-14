"""Add durable module inbox receipts and outbox delivery evidence.

Revision ID: 20260803_0045
Revises: 20260803_0044
"""

import sqlalchemy as sa

from alembic import op

revision = "20260803_0045"
down_revision = "20260803_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    outbox_columns = {column["name"] for column in inspector.get_columns("cc_outbox")}
    for name, column in (
        ("payload_sha256", sa.Column("payload_sha256", sa.String(64))),
        ("delivery_mode", sa.Column("delivery_mode", sa.String(30))),
        ("delivery_receipt_json", sa.Column("delivery_receipt_json", sa.Text())),
        ("delivered_at", sa.Column("delivered_at", sa.DateTime(timezone=True))),
    ):
        if name not in outbox_columns:
            op.add_column("cc_outbox", column)

    inspector = sa.inspect(bind)
    outbox_indexes = {index["name"] for index in inspector.get_indexes("cc_outbox")}
    for name, column in (
        ("ix_cc_outbox_payload_sha256", "payload_sha256"),
        ("ix_cc_outbox_delivery_mode", "delivery_mode"),
        ("ix_cc_outbox_delivered_at", "delivered_at"),
    ):
        if name not in outbox_indexes:
            op.create_index(name, "cc_outbox", [column])

    if "cc_module_inbox" not in inspector.get_table_names():
        op.create_table(
            "cc_module_inbox",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("delivery_id", sa.String(120), nullable=False, unique=True),
            sa.Column(
                "message_id",
                sa.String(120),
                sa.ForeignKey("cc_outbox.message_id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("source_event_id", sa.String(120)),
            sa.Column("requested_destination", sa.String(100), nullable=False),
            sa.Column("destination_module", sa.String(100), nullable=False),
            sa.Column("endpoint", sa.String(500)),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("payload_sha256", sa.String(64), nullable=False),
            sa.Column("schema_version", sa.String(20), nullable=False, server_default="1.0"),
            sa.Column("status", sa.String(30), nullable=False, server_default="received"),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("message_id", name="uq_cc_module_inbox_message"),
            sa.CheckConstraint(
                "status IN ('received','consumed')", name="ck_cc_module_inbox_status"
            ),
        )
        for column in (
            "delivery_id",
            "message_id",
            "source_event_id",
            "requested_destination",
            "destination_module",
            "payload_sha256",
            "status",
        ):
            op.create_index(f"ix_cc_module_inbox_{column}", "cc_module_inbox", [column])

    # The pre-1.38 dispatcher could mark ordinary messages as sent without
    # contacting a consumer. Every such legacy row must be redelivered through
    # the durable inbox before it can regain the sent state.
    op.execute(
        sa.text(
            """
            UPDATE cc_outbox
            SET status = 'pending',
                retry_count = 0,
                next_attempt_at = CURRENT_TIMESTAMP,
                last_error = 'LEGACY_SYNTHETIC_STATUS_REQUIRES_REDELIVERY'
            WHERE status = 'sent' AND delivery_mode IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_table("cc_module_inbox")
    for name in (
        "ix_cc_outbox_delivered_at",
        "ix_cc_outbox_delivery_mode",
        "ix_cc_outbox_payload_sha256",
    ):
        op.drop_index(name, table_name="cc_outbox")
    for column in (
        "delivered_at",
        "delivery_receipt_json",
        "delivery_mode",
        "payload_sha256",
    ):
        op.drop_column("cc_outbox", column)
