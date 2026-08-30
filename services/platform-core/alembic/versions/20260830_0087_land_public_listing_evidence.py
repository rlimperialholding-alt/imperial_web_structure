"""Persist public land evidence and enforce the first production canary cap.

Revision ID: 20260830_0087
Revises: 20260828_0086
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import sqlalchemy as sa

from alembic import op

revision = "20260830_0087"
down_revision = "20260828_0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "growth_signal_source_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evidence_id", sa.String(120), nullable=False),
        sa.Column("signal_id", sa.String(120), nullable=False),
        sa.Column("field_name", sa.String(80), nullable=False),
        sa.Column("observed_value", sa.Text(), nullable=False),
        sa.Column("source_snippet", sa.Text(), nullable=False),
        sa.Column("snippet_sha256", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(1500), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "field_name IN ('listing_permalink','recipient_name','recipient_email',"
            "'recipient_role','property_type','location','plot_size_sqm',"
            "'recipient_organization_name',"
            "'recipient_office_name')",
            name="ck_growth_signal_source_evidence_field",
        ),
        sa.UniqueConstraint("evidence_id", name="uq_growth_signal_source_evidence_id"),
        sa.UniqueConstraint(
            "signal_id", "field_name", name="uq_growth_signal_source_evidence_field"
        ),
    )
    for column in (
        "evidence_id",
        "signal_id",
        "field_name",
        "snippet_sha256",
        "snapshot_sha256",
        "fetched_at",
    ):
        op.create_index(
            f"ix_growth_signal_source_evidence_{column}",
            "growth_signal_source_evidence",
            [column],
        )

    op.create_table(
        "growth_land_canary_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope_local_date", sa.Date(), nullable=False),
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="available"),
        sa.Column("outreach_id", sa.String(120)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("provider_message_id", sa.String(500)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "slot_number BETWEEN 1 AND 3", name="ck_growth_land_canary_slot"
        ),
        sa.CheckConstraint(
            "status IN ('available','claimed','sent','consumed')",
            name="ck_growth_land_canary_slot_status",
        ),
        sa.CheckConstraint(
            "(status = 'available' AND outreach_id IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NULL) OR "
            "(status = 'claimed' AND outreach_id IS NOT NULL AND claimed_at IS NOT NULL "
            "AND sent_at IS NULL) OR "
            "(status IN ('sent','consumed') AND outreach_id IS NOT NULL "
            "AND claimed_at IS NOT NULL AND sent_at IS NOT NULL)",
            name="ck_growth_land_canary_state_fields",
        ),
        sa.UniqueConstraint(
            "scope_local_date",
            "slot_number",
            name="uq_growth_land_canary_scope_slot",
        ),
        sa.UniqueConstraint("outreach_id", name="uq_growth_land_canary_outreach"),
    )
    for column in (
        "scope_local_date",
        "status",
        "outreach_id",
        "claimed_at",
        "sent_at",
        "provider_message_id",
    ):
        op.create_index(
            f"ix_growth_land_canary_slots_{column}",
            "growth_land_canary_slots",
            [column],
        )
    now = datetime.now(UTC)
    op.bulk_insert(
        sa.table(
            "growth_land_canary_slots",
            sa.column("scope_local_date", sa.Date()),
            sa.column("slot_number", sa.Integer()),
            sa.column("status", sa.String()),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "scope_local_date": date(2026, 8, 31),
                "slot_number": slot_number,
                "status": "available",
                "updated_at": now,
            }
            for slot_number in (1, 2, 3)
        ],
    )

    op.create_table(
        "growth_land_canary_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope_local_date", sa.Date(), nullable=False),
        sa.Column("max_total", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("released_by", sa.String(255)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_growth_land_canary_state_singleton"),
        sa.CheckConstraint(
            "status IN ('pending','completed','released')",
            name="ck_growth_land_canary_state_status",
        ),
        sa.CheckConstraint(
            "(status != 'released' AND released_by IS NULL AND released_at IS NULL) OR "
            "(status = 'released' AND released_by IS NOT NULL AND released_at IS NOT NULL)",
            name="ck_growth_land_canary_release_fields",
        ),
    )
    op.create_index(
        "ix_growth_land_canary_state_scope_local_date",
        "growth_land_canary_state",
        ["scope_local_date"],
    )
    op.create_index(
        "ix_growth_land_canary_state_status",
        "growth_land_canary_state",
        ["status"],
    )
    op.create_index(
        "ix_growth_land_canary_state_released_at",
        "growth_land_canary_state",
        ["released_at"],
    )
    op.bulk_insert(
        sa.table(
            "growth_land_canary_state",
            sa.column("id", sa.Integer()),
            sa.column("scope_local_date", sa.Date()),
            sa.column("max_total", sa.Integer()),
            sa.column("status", sa.String()),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": 1,
                "scope_local_date": date(2026, 8, 31),
                "max_total": 3,
                "status": "pending",
                "updated_at": now,
            }
        ],
    )

    op.create_table(
        "growth_public_land_listing_cursors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("route_key", sa.String(500), nullable=False),
        sa.Column("listing_url", sa.String(1500), nullable=False),
        sa.Column("listing_url_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("last_result", sa.String(120)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("examined_at", sa.DateTime(timezone=True)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','retryable','examined')",
            name="ck_growth_public_land_cursor_status",
        ),
        sa.UniqueConstraint(
            "route_key",
            "listing_url_sha256",
            name="uq_growth_public_land_cursor_route_url",
        ),
    )
    for column in (
        "route_key",
        "listing_url_sha256",
        "status",
        "last_result",
        "examined_at",
        "next_retry_at",
    ):
        op.create_index(
            f"ix_growth_public_land_listing_cursors_{column}",
            "growth_public_land_listing_cursors",
            [column],
        )


def downgrade() -> None:
    op.drop_table("growth_public_land_listing_cursors")
    op.drop_table("growth_land_canary_state")
    op.drop_table("growth_land_canary_slots")
    op.drop_table("growth_signal_source_evidence")
