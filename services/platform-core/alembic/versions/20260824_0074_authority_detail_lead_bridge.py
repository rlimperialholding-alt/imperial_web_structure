"""Add ÉTDR detail revisions and the fail-closed lead bridge ledger.

Revision ID: 20260824_0074
Revises: 20260824_0073
"""

import sqlalchemy as sa

from alembic import op

revision = "20260824_0074"
down_revision = "20260824_0073"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    with op.batch_alter_table("growth_signals") as batch:
        batch.drop_constraint("ck_growth_signal_subject_type", type_="check")
        batch.create_check_constraint(
            "ck_growth_signal_subject_type",
            "subject_type IN ('organization','natural_person','project')",
        )

    with op.batch_alter_table("authority_records") as batch:
        batch.add_column(
            sa.Column(
                "current_detail_revision_no", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch.add_column(sa.Column("current_detail_payload_sha256", sa.String(64)))
        batch.add_column(
            sa.Column("detail_status", sa.String(30), nullable=False, server_default="held")
        )
        batch.add_column(sa.Column("detail_checked_at", sa.DateTime(timezone=True)))
        batch.create_check_constraint(
            "ck_authority_record_detail_status",
            "detail_status IN ('held','pending','current','blocked','failed')",
        )
    _indexes(
        "authority_records",
        ("current_detail_payload_sha256", "detail_status", "detail_checked_at"),
    )

    op.create_table(
        "authority_detail_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "record_id",
            sa.String(120),
            sa.ForeignKey("authority_records.record_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_revision_id", sa.String(120), nullable=False),
        sa.Column("listing_payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="held"),
        sa.Column(
            "reason_code", sa.String(120), nullable=False, server_default="detail_policy_gate"
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(120)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "record_id", "listing_payload_sha256", name="uq_authority_detail_queue"
        ),
        sa.CheckConstraint(
            "status IN ('held','pending','claimed','completed','blocked','failed')",
            name="ck_authority_detail_queue_status",
        ),
    )
    _indexes(
        "authority_detail_queue",
        (
            "record_id",
            "source_revision_id",
            "listing_payload_sha256",
            "status",
            "lease_owner",
            "lease_expires_at",
        ),
    )

    op.create_table(
        "authority_detail_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("detail_revision_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "record_id",
            sa.String(120),
            sa.ForeignKey("authority_records.record_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_revision_id", sa.String(120), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_json", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False, server_default="etdr-detail-v1"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("record_id", "payload_sha256", name="uq_authority_detail_payload"),
        sa.UniqueConstraint("record_id", "revision_no", name="uq_authority_detail_number"),
    )
    _indexes(
        "authority_detail_revisions",
        ("detail_revision_id", "record_id", "source_revision_id", "payload_sha256"),
    )

    with op.batch_alter_table("authority_signal_outbox") as batch:
        batch.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("last_error", sa.String(120)))
        batch.add_column(sa.Column("delivery_ref", sa.String(120)))
        batch.add_column(sa.Column("lease_owner", sa.String(120)))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("delivered_at", sa.DateTime(timezone=True)))
    _indexes(
        "authority_signal_outbox",
        ("delivery_ref", "lease_owner", "lease_expires_at", "delivered_at"),
    )


def downgrade() -> None:
    for column in ("delivered_at", "lease_expires_at", "lease_owner", "delivery_ref"):
        op.drop_index(f"ix_authority_signal_outbox_{column}", table_name="authority_signal_outbox")
    with op.batch_alter_table("authority_signal_outbox") as batch:
        batch.drop_column("delivered_at")
        batch.drop_column("lease_expires_at")
        batch.drop_column("lease_owner")
        batch.drop_column("delivery_ref")
        batch.drop_column("last_error")
        batch.drop_column("attempt_count")

    op.drop_table("authority_detail_revisions")
    op.drop_table("authority_detail_queue")

    for column in ("detail_checked_at", "detail_status", "current_detail_payload_sha256"):
        op.drop_index(f"ix_authority_records_{column}", table_name="authority_records")
    with op.batch_alter_table("authority_records") as batch:
        batch.drop_constraint("ck_authority_record_detail_status", type_="check")
        batch.drop_column("detail_checked_at")
        batch.drop_column("detail_status")
        batch.drop_column("current_detail_payload_sha256")
        batch.drop_column("current_detail_revision_no")

    with op.batch_alter_table("growth_signals") as batch:
        batch.drop_constraint("ck_growth_signal_subject_type", type_="check")
        batch.create_check_constraint(
            "ck_growth_signal_subject_type",
            "subject_type IN ('organization','natural_person')",
        )
