"""Add compliance-first autonomous growth operations.

Revision ID: 20260816_0072
Revises: 20260816_0071
"""

import sqlalchemy as sa

from alembic import op

revision = "20260816_0072"
down_revision = "20260816_0071"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "growth_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(120), nullable=False, unique=True),
        sa.Column("motor_key", sa.String(80), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("attempted_sources", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_sources", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_signals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_signals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queued_outreach", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_outreach", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_results_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("error_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('running','completed','partial','failed','disabled')",
            name="ck_growth_run_status",
        ),
    )
    _indexes("growth_runs", ("run_id", "motor_key", "scheduled_for", "status"))

    op.create_table(
        "growth_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.String(120), nullable=False, unique=True),
        sa.Column("run_id", sa.String(120)),
        sa.Column("motor_key", sa.String(80), nullable=False),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("source_bucket", sa.String(100), nullable=False),
        sa.Column("external_key", sa.String(255), nullable=False),
        sa.Column("signal_type", sa.String(120), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_name", sa.String(500)),
        sa.Column("company_registration_id", sa.String(120)),
        sa.Column("subject_type", sa.String(30), nullable=False),
        sa.Column("recipient_email", sa.String(320)),
        sa.Column("recipient_email_type", sa.String(20), nullable=False, server_default="none"),
        sa.Column("contact_basis", sa.String(80), nullable=False),
        sa.Column("consent_evidence_id", sa.String(200)),
        sa.Column("public_contact_url", sa.String(1500)),
        sa.Column("location", sa.String(500)),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_url", sa.String(1500), nullable=False),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("urgency", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dedupe_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("source_payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="accepted"),
        sa.Column("rejection_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "external_key", name="uq_growth_signal_source_external"),
        sa.CheckConstraint(
            "subject_type IN ('organization','natural_person')",
            name="ck_growth_signal_subject_type",
        ),
        sa.CheckConstraint(
            "recipient_email_type IN ('role','named','unknown','none')",
            name="ck_growth_signal_email_type",
        ),
        sa.CheckConstraint(
            "status IN ('accepted','rejected','blocked','queued',"
            "'contacted','responded','suppressed')",
            name="ck_growth_signal_status",
        ),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_growth_signal_score"),
    )
    _indexes(
        "growth_signals",
        (
            "signal_id",
            "run_id",
            "motor_key",
            "source_id",
            "source_bucket",
            "external_key",
            "signal_type",
            "detected_at",
            "company_name",
            "company_registration_id",
            "recipient_email",
            "brand_id",
            "score",
            "dedupe_hash",
            "status",
            "created_at",
        ),
    )

    op.create_table(
        "growth_outreach_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("outreach_id", sa.String(120), nullable=False, unique=True),
        sa.Column("signal_id", sa.String(120), nullable=False),
        sa.Column("motor_key", sa.String(80), nullable=False),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("sender_email", sa.String(320), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("sequence_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("unsubscribe_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("claimed_by", sa.String(160)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("provider_message_id", sa.String(500)),
        sa.Column("receipt_json", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("response_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("signal_id", "sequence_step", name="uq_growth_outreach_signal_step"),
        sa.CheckConstraint(
            "sequence_step >= 0 AND sequence_step <= 2", name="ck_growth_outreach_step"
        ),
        sa.CheckConstraint(
            "status IN ('queued','claimed','sent','delivered','responded','bounced',"
            "'complained','unsubscribed','suppressed','blocked','failed','dead_letter')",
            name="ck_growth_outreach_status",
        ),
    )
    _indexes(
        "growth_outreach_messages",
        (
            "outreach_id",
            "signal_id",
            "motor_key",
            "brand_id",
            "sender_email",
            "recipient_email",
            "unsubscribe_token_hash",
            "idempotency_key",
            "status",
            "available_at",
            "claimed_by",
            "lease_expires_at",
            "provider_message_id",
        ),
    )

    op.create_table(
        "growth_worker_heartbeats",
        sa.Column("worker_id", sa.String(160), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="starting"),
        sa.Column("current_motor_key", sa.String(80)),
        sa.Column("current_outreach_id", sa.String(120)),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("growth_worker_heartbeats", ("status", "heartbeat_at"))

    op.create_table(
        "growth_control_state",
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.Text()),
        sa.Column("changed_by", sa.String(255)),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("growth_control_state", ("enabled",))


def downgrade() -> None:
    for table in (
        "growth_control_state",
        "growth_worker_heartbeats",
        "growth_outreach_messages",
        "growth_signals",
        "growth_runs",
    ):
        op.drop_table(table)
