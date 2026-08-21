"""Add the DB-native canonical source catalog and attempt ledger.

Revision ID: 20260820_0074
Revises: 20260820_0073
"""

import sqlalchemy as sa

from alembic import op

revision = "20260820_0074"
down_revision = "20260820_0073"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "source_catalog_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_id", sa.String(120), nullable=False, unique=True),
        sa.Column("spreadsheet_id", sa.String(120), nullable=False),
        sa.Column("sheet_id", sa.Integer(), nullable=False),
        sa.Column("source_modified_time", sa.String(80), nullable=False),
        sa.Column("catalog_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("route_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="importing"),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('importing','active','retired','failed')",
            name="ck_source_catalog_revision_status",
        ),
    )
    _indexes(
        "source_catalog_revisions",
        ("revision_id", "spreadsheet_id", "sheet_id", "catalog_sha256", "status"),
    )
    op.create_table(
        "source_coverage_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("route_key", sa.String(500), nullable=False, unique=True),
        sa.Column("route_id", sa.String(180), nullable=False),
        sa.Column("catalog_sha256", sa.String(64), nullable=False),
        sa.Column("motor", sa.String(160), nullable=False),
        sa.Column("catalog_part", sa.String(160)),
        sa.Column("country", sa.String(120)),
        sa.Column("brand_fit", sa.String(240)),
        sa.Column("category", sa.String(240)),
        sa.Column("source_name", sa.String(500)),
        sa.Column("source_type", sa.String(120)),
        sa.Column("search_signal", sa.Text()),
        sa.Column("route_url", sa.String(3000), nullable=False),
        sa.Column("base_url", sa.String(3000)),
        sa.Column("route_mode", sa.String(80)),
        sa.Column("priority", sa.String(80)),
        sa.Column("validation", sa.String(120)),
        sa.Column("catalog_status", sa.String(120)),
        sa.Column("source_updated_value", sa.String(120)),
        sa.Column("notes", sa.Text()),
        sa.Column("source_row_sha256", sa.String(64), nullable=False),
        sa.Column("source_record_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_result", sa.String(80)),
        sa.Column("next_due_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("route_id", name="uq_source_coverage_route_id"),
    )
    _indexes(
        "source_coverage_routes",
        (
            "route_key",
            "route_id",
            "catalog_sha256",
            "motor",
            "catalog_part",
            "country",
            "brand_fit",
            "category",
            "source_type",
            "route_mode",
            "priority",
            "validation",
            "catalog_status",
            "source_row_sha256",
            "enabled",
            "last_attempt_at",
            "last_result",
            "next_due_at",
        ),
    )
    op.create_table(
        "source_coverage_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attempt_id", sa.String(120), nullable=False, unique=True),
        sa.Column("route_key", sa.String(500), nullable=False),
        sa.Column("catalog_sha256", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(120)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("response_sha256", sa.String(64)),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_type", sa.String(120)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded','blocked','failed','rejected')",
            name="ck_source_coverage_attempt_status",
        ),
    )
    _indexes(
        "source_coverage_attempts",
        (
            "attempt_id",
            "route_key",
            "catalog_sha256",
            "run_id",
            "status",
            "http_status",
            "error_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("source_coverage_attempts")
    op.drop_table("source_coverage_routes")
    op.drop_table("source_catalog_revisions")
