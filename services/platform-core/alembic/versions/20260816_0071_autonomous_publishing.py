"""Add durable autonomous publishing execution state.

Revision ID: 20260816_0071
Revises: 20260816_0070
"""

import sqlalchemy as sa

from alembic import op

revision = "20260816_0071"
down_revision = "20260816_0070"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    target_tables = {
        "pub_jobs",
        "pub_channel_states",
        "pub_proofs",
        "pub_exceptions",
        "pub_events",
        "pub_worker_heartbeats",
    }
    present = target_tables & set(sa.inspect(op.get_bind()).get_table_names())
    if present:
        if present == target_tables:
            # The legacy 0001 migration creates the current ORM metadata on a fresh database.
            return
        raise RuntimeError("Partial autonomous-publishing schema detected; refusing migration")
    op.create_table(
        "pub_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(120), nullable=False, unique=True),
        sa.Column("content_asset_id", sa.String(120), nullable=False),
        sa.Column("content_version_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("cms_route", sa.String(30), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("correlation_id", sa.String(120), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="QUEUED"),
        sa.Column("desired_publish_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("claimed_by", sa.String(160)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_successful_step", sa.String(100)),
        sa.Column("last_error", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('QUEUED','BLOCKED','RUNNING','VERIFIED','FAILED',"
            "'ROLLING_BACK','ROLLED_BACK','ROLLBACK_FAILED')",
            name="ck_pub_jobs_status",
        ),
    )
    _indexes(
        "pub_jobs",
        (
            "job_id",
            "content_asset_id",
            "content_version_id",
            "brand_id",
            "cms_route",
            "idempotency_key",
            "correlation_id",
            "payload_sha256",
            "status",
            "desired_publish_at",
            "available_at",
            "claimed_by",
            "lease_expires_at",
            "completed_at",
            "created_at",
        ),
    )

    op.create_table(
        "pub_channel_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_state_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "job_id",
            sa.String(120),
            sa.ForeignKey("pub_jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("content_asset_id", sa.String(120), nullable=False),
        sa.Column("content_version_id", sa.String(120), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="QUEUED"),
        sa.Column("external_id", sa.String(255)),
        sa.Column("public_url", sa.String(1000)),
        sa.Column("admin_url", sa.String(1000)),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("canonical_url", sa.String(1000)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("rollback_status", sa.String(30)),
        sa.Column("rollback_readback_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "channel", name="uq_pub_channel_job_channel"),
        sa.UniqueConstraint(
            "brand_id",
            "content_asset_id",
            "content_version_id",
            "channel",
            name="uq_pub_channel_content_idempotency",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','BLOCKED','DRAFT_CREATED','PUBLISHING','PUBLISHED',"
            "'READBACK_VERIFIED','FAILED','ROLLING_BACK','ROLLED_BACK',"
            "'ROLLBACK_FAILED','DRAFT_ONLY')",
            name="ck_pub_channel_status",
        ),
    )
    _indexes(
        "pub_channel_states",
        (
            "channel_state_id",
            "job_id",
            "brand_id",
            "content_asset_id",
            "content_version_id",
            "channel",
            "idempotency_key",
            "status",
            "external_id",
            "content_hash",
            "verified_at",
            "rollback_status",
            "created_at",
        ),
    )

    op.create_table(
        "pub_proofs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proof_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "job_id",
            sa.String(120),
            sa.ForeignKey("pub_jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_state_id",
            sa.String(120),
            sa.ForeignKey("pub_channel_states.channel_state_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("public_url", sa.String(1000), nullable=False),
        sa.Column("content_asset_id", sa.String(120), nullable=False),
        sa.Column("content_version_id", sa.String(120), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("canonical_url", sa.String(1000)),
        sa.Column("readback_json", sa.Text(), nullable=False),
        sa.Column("readback_sha256", sa.String(64), nullable=False),
        sa.Column("analytics_event_id", sa.String(160)),
        sa.Column("crm_event_id", sa.String(160)),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes(
        "pub_proofs",
        (
            "proof_id",
            "job_id",
            "channel_state_id",
            "brand_id",
            "channel",
            "external_id",
            "content_asset_id",
            "content_version_id",
            "content_hash",
            "readback_sha256",
            "analytics_event_id",
            "crm_event_id",
            "verified_at",
            "created_at",
        ),
    )

    op.create_table(
        "pub_exceptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exception_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "job_id",
            sa.String(120),
            sa.ForeignKey("pub_jobs.job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("content_asset_id", sa.String(120), nullable=False),
        sa.Column("content_version_id", sa.String(120), nullable=False),
        sa.Column("channel", sa.String(40)),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=False),
        sa.Column("last_successful_step", sa.String(100)),
        sa.Column("redacted_response_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("admin_url", sa.String(1000)),
        sa.Column("public_url", sa.String(1000)),
        sa.Column("publication_proof_id", sa.String(120)),
        sa.Column("rollback_status", sa.String(30)),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(255), nullable=False, server_default="Molnár Andrea"),
        sa.Column("status", sa.String(30), nullable=False, server_default="OPEN"),
        sa.Column("retry_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("regate_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "severity IN ('BLOCKER','CRITICAL','MAJOR','MINOR')", name="ck_pub_exception_severity"
        ),
    )
    _indexes(
        "pub_exceptions",
        (
            "exception_id",
            "job_id",
            "brand_id",
            "content_asset_id",
            "content_version_id",
            "channel",
            "severity",
            "error_type",
            "publication_proof_id",
            "rollback_status",
            "owner",
            "status",
            "due_at",
            "created_at",
            "resolved_at",
        ),
    )

    op.create_table(
        "pub_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(120), nullable=False, unique=True),
        sa.Column("dedupe_key", sa.String(255), nullable=False, unique=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("job_id", sa.String(120), nullable=False),
        sa.Column("content_asset_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(40)),
        sa.Column("external_id", sa.String(255)),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes(
        "pub_events",
        (
            "event_id",
            "dedupe_key",
            "event_type",
            "job_id",
            "content_asset_id",
            "brand_id",
            "channel",
            "external_id",
            "occurred_at",
        ),
    )

    op.create_table(
        "pub_worker_heartbeats",
        sa.Column("worker_id", sa.String(160), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="healthy"),
        sa.Column("current_job_id", sa.String(120)),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("pub_worker_heartbeats", ("status", "current_job_id", "heartbeat_at"))


def downgrade() -> None:
    for table in (
        "pub_worker_heartbeats",
        "pub_events",
        "pub_exceptions",
        "pub_proofs",
        "pub_channel_states",
        "pub_jobs",
    ):
        op.drop_table(table)
