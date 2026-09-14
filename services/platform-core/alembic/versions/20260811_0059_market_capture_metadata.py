"""Add governed public capture metadata.

Revision ID: 20260811_0059
Revises: 20260811_0058
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260811_0059"
down_revision = "20260811_0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    job_columns = {column["name"] for column in inspector.get_columns("market_capture_jobs")}
    snapshot_columns = {
        column["name"] for column in inspector.get_columns("market_source_snapshots")
    }
    if "requested_url" not in job_columns:
        op.add_column("market_capture_jobs", sa.Column("requested_url", sa.String(1600)))
    if "http_status" not in snapshot_columns:
        op.add_column("market_source_snapshots", sa.Column("http_status", sa.Integer()))
    if "response_headers_json" not in snapshot_columns:
        op.add_column(
            "market_source_snapshots",
            sa.Column("response_headers_json", sa.Text(), nullable=False, server_default="{}"),
        )
    if "source_ip" not in snapshot_columns:
        op.add_column("market_source_snapshots", sa.Column("source_ip", sa.String(80)))


def downgrade() -> None:
    raise RuntimeError(
        "0059 stores capture provenance. Use a forward migration; destructive automatic "
        "downgrade is forbidden."
    )
