"""Add durable multi-day offline escrow contracts for scheduled Gmail clients.

Revision ID: 20260901_0089
Revises: 20260831_0088
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260901_0089"
down_revision = "20260831_0088"
branch_labels = None
depends_on = None


def _indexes(table: str, prefix: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{prefix}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "growth_scheduled_gmail_escrow_bundles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bundle_id", sa.String(120), nullable=False),
        sa.Column("request_id", sa.String(120), nullable=False),
        sa.Column("client_id", sa.String(120), nullable=False),
        sa.Column("client_key_id", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="building"),
        sa.Column("permit_count", sa.Integer(), nullable=False),
        sa.Column("first_quota_local_date", sa.Date(), nullable=False),
        sa.Column("last_quota_local_date", sa.Date(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_sha256", sa.String(64), nullable=False),
        sa.Column("client_registry_sha256", sa.String(64), nullable=False),
        # Public verification material only.  It is deliberately persisted so
        # registry key rotation cannot invalidate already-issued bundles.
        sa.Column("client_public_key_sha256", sa.String(64)),
        sa.Column("client_public_key_pem", sa.Text()),
        sa.Column("manifest_sha256", sa.String(64)),
        sa.Column("signing_key_id", sa.String(120), nullable=False),
        sa.Column("manifest_signature", sa.Text()),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column("reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('building','active','pending_sync','reconciled','revoked')",
            name="ck_growth_sg_escrow_bundle_status",
        ),
        sa.CheckConstraint(
            "permit_count > 0 AND permit_count <= 2000",
            name="ck_growth_sg_escrow_bundle_permit_count",
        ),
        sa.CheckConstraint(
            "first_quota_local_date <= last_quota_local_date",
            name="ck_growth_sg_escrow_bundle_date_order",
        ),
        sa.CheckConstraint(
            "valid_from < expires_at",
            name="ck_growth_sg_escrow_bundle_time_order",
        ),
        sa.UniqueConstraint("bundle_id", name="uq_growth_sg_escrow_bundle_id"),
        sa.UniqueConstraint("request_id", name="uq_growth_sg_escrow_bundle_request"),
        sa.UniqueConstraint(
            "manifest_sha256",
            name="uq_growth_sg_escrow_bundle_manifest",
        ),
    )
    _indexes(
        "growth_scheduled_gmail_escrow_bundles",
        "growth_sg_escrow_bundle",
        (
            "bundle_id",
            "request_id",
            "client_id",
            "client_key_id",
            "status",
            "first_quota_local_date",
            "last_quota_local_date",
            "valid_from",
            "expires_at",
            "policy_sha256",
            "client_registry_sha256",
            "client_public_key_sha256",
            "manifest_sha256",
            "signing_key_id",
            "issued_at",
            "reconciled_at",
            "revoked_at",
        ),
    )

    op.create_table(
        "growth_scheduled_gmail_escrow_permits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("permit_id", sa.String(120), nullable=False),
        sa.Column("bundle_id", sa.String(120), nullable=False),
        sa.Column("lease_id", sa.String(120), nullable=False),
        sa.Column("outreach_id", sa.String(120), nullable=False),
        sa.Column("client_id", sa.String(120), nullable=False),
        sa.Column("client_key_id", sa.String(120), nullable=False),
        sa.Column("permit_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="reserved"),
        sa.Column("sender_email", sa.String(320), nullable=False),
        sa.Column("motor_key", sa.String(80), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("exact_payload_sha256", sa.String(64), nullable=False),
        sa.Column("outreach_idempotency_key", sa.String(64), nullable=False),
        sa.Column("quota_local_date", sa.Date(), nullable=False),
        sa.Column("day_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("day_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_not_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_not_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("permit_token_nonce", sa.String(64), nullable=False),
        sa.Column("permit_token_sha256", sa.String(64), nullable=False),
        sa.Column("global_guard_claim_token", sa.String(120), nullable=False),
        sa.Column("global_guard_claim_token_sha256", sa.String(64), nullable=False),
        sa.Column("permit_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("signing_key_id", sa.String(120), nullable=False),
        sa.Column("permit_signature", sa.Text(), nullable=False),
        sa.Column("quota_reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("provider_message_id", sa.String(500)),
        sa.Column("provider_accepted_at", sa.DateTime(timezone=True)),
        sa.Column("provider_internal_date", sa.DateTime(timezone=True)),
        sa.Column("readback_mime_sha256", sa.String(64)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("aborted_at", sa.DateTime(timezone=True)),
        sa.Column("abort_reason", sa.Text()),
        sa.Column("last_client_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_event_sha256", sa.String(64)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('reserved','consuming','accepted_unverified','sent',"
            "'aborted','expired_unreconciled')",
            name="ck_growth_sg_escrow_permit_status",
        ),
        sa.CheckConstraint(
            "permit_index >= 0",
            name="ck_growth_sg_escrow_permit_index",
        ),
        sa.CheckConstraint(
            "day_start_utc < day_end_utc",
            name="ck_growth_sg_escrow_permit_day_order",
        ),
        sa.CheckConstraint(
            "slot_not_before >= day_start_utc AND slot_not_after <= day_end_utc "
            "AND slot_not_before < slot_not_after",
            name="ck_growth_sg_escrow_permit_slot_bounds",
        ),
        sa.CheckConstraint(
            "last_client_sequence >= 0",
            name="ck_growth_sg_escrow_permit_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["bundle_id"],
            ["growth_scheduled_gmail_escrow_bundles.bundle_id"],
            name="fk_growth_sg_escrow_permit_bundle",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lease_id"],
            ["growth_scheduled_gmail_leases.lease_id"],
            name="fk_growth_sg_escrow_permit_lease",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["outreach_id"],
            ["growth_outreach_messages.outreach_id"],
            name="fk_growth_sg_escrow_permit_outreach",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("permit_id", name="uq_growth_sg_escrow_permit_id"),
        sa.UniqueConstraint("lease_id", name="uq_growth_sg_escrow_permit_lease"),
        sa.UniqueConstraint("outreach_id", name="uq_growth_sg_escrow_permit_outreach"),
        sa.UniqueConstraint(
            "permit_token_sha256",
            name="uq_growth_sg_escrow_permit_token",
        ),
        sa.UniqueConstraint(
            "provider_message_id",
            name="uq_growth_sg_escrow_permit_provider",
        ),
        sa.UniqueConstraint(
            "bundle_id",
            "permit_index",
            name="uq_growth_sg_escrow_permit_bundle_index",
        ),
        sa.UniqueConstraint(
            "permit_manifest_sha256",
            name="uq_growth_sg_escrow_permit_manifest",
        ),
    )
    _indexes(
        "growth_scheduled_gmail_escrow_permits",
        "growth_sg_escrow_permit",
        (
            "permit_id",
            "bundle_id",
            "lease_id",
            "outreach_id",
            "client_id",
            "client_key_id",
            "status",
            "sender_email",
            "motor_key",
            "payload_sha256",
            "exact_payload_sha256",
            "outreach_idempotency_key",
            "quota_local_date",
            "day_start_utc",
            "day_end_utc",
            "slot_not_before",
            "slot_not_after",
            "permit_token_sha256",
            "global_guard_claim_token",
            "global_guard_claim_token_sha256",
            "permit_manifest_sha256",
            "signing_key_id",
            "quota_reserved_at",
            "consumed_at",
            "provider_message_id",
            "provider_accepted_at",
            "provider_internal_date",
            "readback_mime_sha256",
            "verified_at",
            "aborted_at",
            "last_event_sha256",
            "last_synced_at",
        ),
    )

    op.create_table(
        "growth_scheduled_gmail_escrow_sync_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(120), nullable=False),
        sa.Column("permit_id", sa.String(120), nullable=False),
        sa.Column("bundle_id", sa.String(120), nullable=False),
        sa.Column("client_id", sa.String(120), nullable=False),
        sa.Column("client_sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column(
            "processing_status",
            sa.String(32),
            nullable=False,
            server_default="received",
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("exact_payload_sha256", sa.String(64), nullable=False),
        sa.Column("permit_token_sha256", sa.String(64), nullable=False),
        sa.Column("previous_event_sha256", sa.String(64)),
        sa.Column("event_sha256", sa.String(64), nullable=False),
        sa.Column("client_key_id", sa.String(120), nullable=False),
        sa.Column("client_public_key_sha256", sa.String(64), nullable=False),
        sa.Column("client_signature", sa.Text(), nullable=False),
        sa.Column("provider_transport_called", sa.Boolean(), nullable=False),
        sa.Column("provider_message_id", sa.String(500)),
        sa.Column("reason", sa.Text()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('permit_consumed','provider_accepted','transport_ambiguous',"
            "'pretransport_aborted','expired_unused')",
            name="ck_growth_sg_escrow_event_type",
        ),
        sa.CheckConstraint(
            "processing_status IN ('received','applied','pending_verification','rejected')",
            name="ck_growth_sg_escrow_event_status",
        ),
        sa.CheckConstraint(
            "client_sequence > 0",
            name="ck_growth_sg_escrow_event_sequence",
        ),
        sa.CheckConstraint(
            "(client_sequence = 1 AND previous_event_sha256 IS NULL) OR "
            "(client_sequence > 1 AND previous_event_sha256 IS NOT NULL)",
            name="ck_growth_sg_escrow_event_chain",
        ),
        sa.CheckConstraint(
            "(event_type = 'permit_consumed' AND provider_transport_called = false "
            "AND provider_message_id IS NULL) OR "
            "(event_type = 'provider_accepted' AND provider_transport_called = true "
            "AND provider_message_id IS NOT NULL) OR "
            "(event_type = 'transport_ambiguous' AND provider_transport_called = true) OR "
            "(event_type IN ('pretransport_aborted','expired_unused') "
            "AND provider_transport_called = false AND provider_message_id IS NULL)",
            name="ck_growth_sg_escrow_event_transport",
        ),
        sa.ForeignKeyConstraint(
            ["permit_id"],
            ["growth_scheduled_gmail_escrow_permits.permit_id"],
            name="fk_growth_sg_escrow_event_permit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["bundle_id"],
            ["growth_scheduled_gmail_escrow_bundles.bundle_id"],
            name="fk_growth_sg_escrow_event_bundle",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("event_id", name="uq_growth_sg_escrow_event_id"),
        sa.UniqueConstraint("event_sha256", name="uq_growth_sg_escrow_event_hash"),
        sa.UniqueConstraint(
            "permit_id",
            "client_sequence",
            name="uq_growth_sg_escrow_event_sequence",
        ),
    )
    _indexes(
        "growth_scheduled_gmail_escrow_sync_events",
        "growth_sg_escrow_event",
        (
            "event_id",
            "permit_id",
            "bundle_id",
            "client_id",
            "event_type",
            "processing_status",
            "occurred_at",
            "payload_sha256",
            "exact_payload_sha256",
            "permit_token_sha256",
            "previous_event_sha256",
            "event_sha256",
            "client_key_id",
            "client_public_key_sha256",
            "provider_message_id",
            "processed_at",
        ),
    )


def downgrade() -> None:
    op.drop_table("growth_scheduled_gmail_escrow_sync_events")
    op.drop_table("growth_scheduled_gmail_escrow_permits")
    op.drop_table("growth_scheduled_gmail_escrow_bundles")
