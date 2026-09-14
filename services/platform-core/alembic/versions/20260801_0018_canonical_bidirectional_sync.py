"""Add durable canonical delivery and reconciliation state.

Revision ID: 20260801_0018
Revises: 20260731_0017
"""

import sqlalchemy as sa

from alembic import op

revision = "20260801_0018"
down_revision = "20260731_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    required = {"ic_canonical_deliveries", "ic_canonical_reconciliation_runs"}
    present = existing & required
    if present == required:
        # The consolidated bootstrap migration creates the current metadata on a
        # brand-new database. Treat that valid state as already provisioned.
        return
    if present:
        raise RuntimeError(
            "Partial canonical sync schema detected; refusing an unsafe migration: "
            + ", ".join(sorted(present))
        )
    op.create_table(
        "ic_canonical_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("target_system", sa.String(length=80), nullable=False),
        sa.Column("domain", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("external_key", sa.String(length=255), nullable=False),
        sa.Column("source_version", sa.String(length=80), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("project_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("remote_id", sa.String(length=160), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_ic_canonical_delivery_event"),
    )
    for name, columns in (
        ("ix_ic_canonical_deliveries_event_id", ["event_id"]),
        ("ix_ic_canonical_deliveries_target_system", ["target_system"]),
        ("ix_ic_canonical_deliveries_domain", ["domain"]),
        ("ix_ic_canonical_deliveries_entity_type", ["entity_type"]),
        ("ix_ic_canonical_deliveries_external_key", ["external_key"]),
        ("ix_ic_canonical_deliveries_payload_sha256", ["payload_sha256"]),
        ("ix_ic_canonical_deliveries_project_id", ["project_id"]),
        ("ix_ic_canonical_deliveries_status", ["status"]),
    ):
        op.create_index(name, "ic_canonical_deliveries", columns)

    op.create_table(
        "ic_canonical_reconciliation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=120), nullable=False),
        sa.Column("target_system", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="processing"),
        sa.Column("local_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remote_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matching_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_remote_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hash_mismatch_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(
        "ix_ic_canonical_reconciliation_runs_run_id", "ic_canonical_reconciliation_runs", ["run_id"]
    )
    op.create_index(
        "ix_ic_canonical_reconciliation_runs_target_system",
        "ic_canonical_reconciliation_runs",
        ["target_system"],
    )
    op.create_index(
        "ix_ic_canonical_reconciliation_runs_status", "ic_canonical_reconciliation_runs", ["status"]
    )


def downgrade() -> None:
    op.drop_table("ic_canonical_reconciliation_runs")
    op.drop_table("ic_canonical_deliveries")
