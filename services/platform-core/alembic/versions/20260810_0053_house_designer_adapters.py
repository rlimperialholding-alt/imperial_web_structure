"""Add governed House Designer production adapter evidence.

Revision ID: 20260810_0053
Revises: 20260810_0052
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260810_0053"
down_revision = "20260810_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    names = {
        "house_designer_adapter_registrations",
        "house_designer_adapter_jobs",
        "house_designer_adapter_receipts",
    }
    present = tables & names
    if present == names:
        return
    if present:
        raise RuntimeError(f"Partial House Designer adapter schema: {sorted(present)}")
    required = {
        "house_design_sessions",
        "house_design_revisions",
        "house_design_estimate_snapshots",
        "house_design_schedule_snapshots",
        "house_design_render_revisions",
    }
    if not required <= tables:
        raise RuntimeError(f"House Designer schema is incomplete: {sorted(required - tables)}")

    op.create_table(
        "house_designer_adapter_registrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("adapter_id", sa.String(120), nullable=False),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("adapter_type", sa.String(30), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(120), nullable=False),
        sa.Column("endpoint", sa.String(1200), nullable=False),
        sa.Column("key_id", sa.String(160), nullable=False),
        sa.Column(
            "contract_version",
            sa.String(80),
            nullable=False,
            server_default="house-designer-adapter-v1",
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("health_status", sa.String(30), nullable=False, server_default="UNKNOWN"),
        sa.Column("last_health_at", sa.DateTime(timezone=True)),
        sa.Column("authored_by", sa.String(255), nullable=False),
        sa.Column("reviewed_by", sa.String(255)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("adapter_id", name="uq_hd_adapter_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "brand_id",
            "adapter_type",
            "revision_no",
            name="uq_hd_adapter_scope_revision",
        ),
        sa.CheckConstraint(
            "adapter_type IN ('pricing','capacity','render')", name="ck_hd_adapter_type"
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','IN_REVIEW','ACTIVE','SUSPENDED','REVOKED')",
            name="ck_hd_adapter_status",
        ),
    )
    for column in (
        "adapter_id",
        "tenant_id",
        "brand_id",
        "adapter_type",
        "status",
        "health_status",
        "authored_by",
        "reviewed_by",
    ):
        op.create_index(
            f"ix_house_designer_adapter_registrations_{column}",
            "house_designer_adapter_registrations",
            [column],
        )

    op.create_table(
        "house_designer_adapter_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(120), nullable=False),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("design_revision_id", sa.String(120), nullable=False),
        sa.Column("adapter_id", sa.String(120), nullable=False),
        sa.Column("adapter_type", sa.String(30), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="QUEUED"),
        sa.Column("provider_job_id", sa.String(255)),
        sa.Column("result_object_id", sa.String(120)),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", name="uq_hd_adapter_job_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_hd_adapter_job_idempotency"),
        sa.CheckConstraint(
            "adapter_type IN ('pricing','capacity','render')", name="ck_hd_adapter_job_type"
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','DISPATCHED','SUCCEEDED','FAILED','EXPIRED')",
            name="ck_hd_adapter_job_status",
        ),
    )
    for column in (
        "job_id",
        "tenant_id",
        "brand_id",
        "session_id",
        "design_revision_id",
        "adapter_id",
        "adapter_type",
        "request_sha256",
        "status",
        "provider_job_id",
        "result_object_id",
        "expires_at",
        "created_by",
    ):
        op.create_index(
            f"ix_house_designer_adapter_jobs_{column}", "house_designer_adapter_jobs", [column]
        )

    op.create_table(
        "house_designer_adapter_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("receipt_id", sa.String(120), nullable=False),
        sa.Column("job_id", sa.String(120), nullable=False),
        sa.Column("adapter_id", sa.String(120), nullable=False),
        sa.Column("provider_job_id", sa.String(255), nullable=False),
        sa.Column("key_id", sa.String(160), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("response_sha256", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("rejection_code", sa.String(120)),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("receipt_id", name="uq_hd_adapter_receipt_id"),
        sa.UniqueConstraint("job_id", "response_sha256", name="uq_hd_adapter_receipt_response"),
        sa.UniqueConstraint("adapter_id", "provider_job_id", name="uq_hd_adapter_provider_job"),
        sa.CheckConstraint(
            "status IN ('ACCEPTED','REJECTED')", name="ck_hd_adapter_receipt_status"
        ),
    )
    for column in (
        "receipt_id",
        "job_id",
        "adapter_id",
        "provider_job_id",
        "request_sha256",
        "response_sha256",
        "issued_at",
        "status",
    ):
        op.create_index(
            f"ix_house_designer_adapter_receipts_{column}",
            "house_designer_adapter_receipts",
            [column],
        )


def downgrade() -> None:
    raise RuntimeError(
        "0053 stores production adapter requests and signed evidence. Use a verified export "
        "and a forward migration; destructive automatic downgrade is forbidden."
    )
