"""Add fail-closed ÉTDR/OÉNY authority reader.

Revision ID: 20260824_0073
Revises: 20260816_0072
"""

import sqlalchemy as sa

from alembic import op

revision = "20260824_0073"
down_revision = "20260816_0072"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "authority_reader_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(120), nullable=False, unique=True),
        sa.Column("source_key", sa.String(160), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("trigger", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("filter_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_reported", sa.Integer()),
        sa.Column("pages_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_unchanged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('running','completed','partial','failed','blocked','disabled')",
            name="ck_authority_reader_run_status",
        ),
        sa.CheckConstraint(
            "mode IN ('baseline','delta','pilot')", name="ck_authority_reader_run_mode"
        ),
    )
    _indexes(
        "authority_reader_runs", ("run_id", "source_key", "mode", "trigger", "status", "error_code")
    )

    op.create_table(
        "authority_reader_checkpoints",
        sa.Column("source_key", sa.String(160), primary_key=True),
        sa.Column("cursor_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("cursor_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(160)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes(
        "authority_reader_checkpoints",
        ("lease_owner", "lease_expires_at", "last_success_at"),
    )

    op.create_table(
        "authority_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("record_id", sa.String(120), nullable=False, unique=True),
        sa.Column("source_key", sa.String(160), nullable=False),
        sa.Column("external_key_hmac", sa.String(64), nullable=False),
        sa.Column("public_process_number", sa.String(40), nullable=False),
        sa.Column("city", sa.String(200), nullable=False),
        sa.Column("topographical_number", sa.String(100)),
        sa.Column("procedure_type", sa.String(500), nullable=False),
        sa.Column("construction_activity", sa.Text(), nullable=False),
        sa.Column("submission_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_url", sa.String(1500), nullable=False),
        sa.Column("current_revision_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_key", "external_key_hmac", name="uq_authority_record_external"),
        sa.CheckConstraint(
            "status IN ('active','excluded','quarantined')",
            name="ck_authority_record_status",
        ),
    )
    _indexes(
        "authority_records",
        (
            "record_id",
            "source_key",
            "external_key_hmac",
            "public_process_number",
            "city",
            "topographical_number",
            "procedure_type",
            "submission_date",
            "current_payload_sha256",
            "status",
        ),
    )

    op.create_table(
        "authority_record_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "record_id",
            sa.String(120),
            sa.ForeignKey("authority_records.record_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_id", sa.String(120), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_json", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False, server_default="etdr-v1"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("record_id", "payload_sha256", name="uq_authority_revision_payload"),
        sa.UniqueConstraint("record_id", "revision_no", name="uq_authority_revision_number"),
    )
    _indexes(
        "authority_record_revisions",
        ("revision_id", "record_id", "run_id", "payload_sha256"),
    )

    op.create_table(
        "authority_enrichment_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "record_id",
            sa.String(120),
            sa.ForeignKey("authority_records.record_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="held"),
        sa.Column("reason_code", sa.String(120), nullable=False, server_default="policy_gate"),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("record_id", "payload_sha256", name="uq_authority_enrichment_payload"),
        sa.CheckConstraint(
            "status IN ('held','pending','completed','ambiguous','blocked','failed')",
            name="ck_authority_enrichment_status",
        ),
    )
    _indexes("authority_enrichment_queue", ("record_id", "payload_sha256", "status"))

    op.create_table(
        "authority_signal_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "record_id",
            sa.String(120),
            sa.ForeignKey("authority_records.record_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_id", sa.String(120), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="held"),
        sa.Column(
            "reason_code",
            sa.String(120),
            nullable=False,
            server_default="manual_promotion_required",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('held','pending','claimed','delivered','blocked','dead_letter')",
            name="ck_authority_signal_outbox_status",
        ),
    )
    _indexes(
        "authority_signal_outbox",
        ("idempotency_key", "record_id", "revision_id", "payload_sha256", "status"),
    )


def downgrade() -> None:
    op.drop_table("authority_signal_outbox")
    op.drop_table("authority_enrichment_queue")
    op.drop_table("authority_record_revisions")
    op.drop_table("authority_records")
    op.drop_table("authority_reader_checkpoints")
    op.drop_table("authority_reader_runs")
