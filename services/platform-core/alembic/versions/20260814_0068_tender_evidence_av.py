"""Persist fail-closed Tender evidence malware scan verdicts.

Revision ID: 20260814_0068
Revises: 20260814_0067
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260814_0068"
down_revision = "20260814_0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "tender_bid_evidence"
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        raise RuntimeError("Tender evidence schema is missing.")
    columns = {column["name"] for column in inspector.get_columns(table)}
    additions = {
        "scan_status": sa.Column(
            "scan_status", sa.String(30), nullable=False, server_default="legacy_unverified"
        ),
        "scan_engine": sa.Column("scan_engine", sa.String(120), nullable=True),
        "scan_engine_version": sa.Column("scan_engine_version", sa.String(255), nullable=True),
        "scan_signature": sa.Column("scan_signature", sa.String(255), nullable=True),
        "scanned_at": sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column(table, column)
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if "ix_tender_bid_evidence_scan_status" not in indexes:
        op.create_index(
            "ix_tender_bid_evidence_scan_status", table, ["scan_status"], unique=False
        )


def downgrade() -> None:
    # Malware verdicts are security evidence and intentionally survive code rollback.
    return None
