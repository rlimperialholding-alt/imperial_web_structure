"""Add durable Content Factory to Image Factory batch requests.

Revision ID: 20260813_0065
Revises: 20260813_0064
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260813_0065"
down_revision = "20260813_0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "cq_image_factory_requests"
    inspector = sa.inspect(op.get_bind())
    required_columns = {
        "request_id",
        "asset_id",
        "content_version",
        "content_sha256",
        "status",
        "idempotency_key",
        "image_factory_batch_id",
        "image_factory_job_id",
        "requested_role",
        "output_role",
        "request_payload_json",
        "response_json",
        "attempt_count",
        "next_attempt_at",
        "output_uri",
        "output_sha256",
        "qa_score",
        "release_state",
        "last_error",
        "submitted_at",
        "completed_at",
        "created_at",
        "updated_at",
    }
    required_index_columns = {
        ("asset_id",),
        ("content_sha256",),
        ("status",),
        ("idempotency_key",),
        ("image_factory_batch_id",),
        ("image_factory_job_id",),
        ("next_attempt_at",),
        ("output_sha256",),
        ("release_state",),
    }
    if table in set(inspector.get_table_names()):
        columns = {column["name"] for column in inspector.get_columns(table)}
        indexes = inspector.get_indexes(table)
        indexed_columns = {tuple(index["column_names"]) for index in indexes}
        missing_columns = sorted(required_columns - columns)
        missing_indexes = sorted(required_index_columns - indexed_columns)
        job_index = next(
            (
                index
                for index in indexes
                if tuple(index["column_names"]) == ("image_factory_job_id",)
            ),
            None,
        )
        if missing_columns or missing_indexes:
            raise RuntimeError(
                "Existing Content Image Factory schema is incomplete: "
                + ", ".join(
                    [*missing_columns, *("/".join(columns) for columns in missing_indexes)]
                )
            )
        if not job_index or not job_index.get("unique"):
            raise RuntimeError("Existing Content Image Factory job index is not unique.")
        return
    op.create_table(
        table,
        sa.Column("request_id", sa.String(length=120), nullable=False),
        sa.Column("asset_id", sa.String(length=120), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column("image_factory_batch_id", sa.String(length=80), nullable=True),
        sa.Column("image_factory_job_id", sa.String(length=80), nullable=True),
        sa.Column("requested_role", sa.String(length=40), nullable=False),
        sa.Column("output_role", sa.String(length=40), nullable=False),
        sa.Column("request_payload_json", sa.Text(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_uri", sa.String(length=2000), nullable=True),
        sa.Column("output_sha256", sa.String(length=64), nullable=True),
        sa.Column("qa_score", sa.Integer(), nullable=True),
        sa.Column("release_state", sa.String(length=40), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('QUEUED','BLOCKED','SUBMITTED','PROCESSING','IMPORTED',"
            "'NEEDS_REVIEW','FAILED','STALE')",
            name="ck_cq_image_factory_request_status",
        ),
        sa.PrimaryKeyConstraint("request_id"),
        sa.UniqueConstraint(
            "asset_id", "content_version", name="uq_cq_image_factory_asset_version"
        ),
        sa.UniqueConstraint("image_factory_job_id"),
    )
    for name, columns in {
        "ix_cq_image_factory_requests_asset_id": ["asset_id"],
        "ix_cq_image_factory_requests_content_sha256": ["content_sha256"],
        "ix_cq_image_factory_requests_status": ["status"],
        "ix_cq_image_factory_requests_idempotency_key": ["idempotency_key"],
        "ix_cq_image_factory_requests_batch_id": ["image_factory_batch_id"],
        "ix_cq_image_factory_requests_job_id": ["image_factory_job_id"],
        "ix_cq_image_factory_requests_next_attempt": ["next_attempt_at"],
        "ix_cq_image_factory_requests_output_sha256": ["output_sha256"],
        "ix_cq_image_factory_requests_release_state": ["release_state"],
    }.items():
        op.create_index(name, "cq_image_factory_requests", columns)


def downgrade() -> None:
    op.drop_table("cq_image_factory_requests")
