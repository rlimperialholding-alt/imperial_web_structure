"""Add provider-neutral publication delivery lifecycle.

Revision ID: 20260803_0042
Revises: 20260802_0041
"""

import sqlalchemy as sa

from alembic import op

revision = "20260803_0042"
down_revision = "20260802_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "cq_publication_deliveries" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "cq_publication_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "message_id",
            sa.String(120),
            sa.ForeignKey("cc_outbox.message_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.String(120), nullable=False),
        sa.Column("publication_proof_id", sa.String(120), nullable=False),
        sa.Column("publication_bundle_id", sa.String(120)),
        sa.Column("target", sa.String(120), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="ready"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.String(160)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("external_reference", sa.String(500)),
        sa.Column("receipt_json", sa.Text()),
        sa.Column("receipt_sha256", sa.String(64)),
        sa.Column("last_error", sa.Text()),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "publication_proof_id",
            "target",
            "action",
            name="uq_cq_publication_delivery_proof_target_action",
        ),
        sa.CheckConstraint(
            "action IN ('PUBLISH','PAUSE_OR_UNPUBLISH')",
            name="ck_cq_publication_delivery_action",
        ),
        sa.CheckConstraint(
            "status IN ('ready','claimed','retry','delivered','dead_letter')",
            name="ck_cq_publication_delivery_status",
        ),
    )
    for column in (
        "delivery_id", "message_id", "asset_id", "publication_proof_id",
        "publication_bundle_id", "target", "action", "idempotency_key",
        "payload_sha256", "status", "claimed_by", "external_reference",
        "receipt_sha256",
    ):
        op.create_index(
            f"ix_cq_publication_deliveries_{column}",
            "cq_publication_deliveries",
            [column],
        )


def downgrade() -> None:
    op.drop_table("cq_publication_deliveries")
