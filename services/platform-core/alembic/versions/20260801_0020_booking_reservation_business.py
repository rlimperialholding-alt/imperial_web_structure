"""Add production Booking and Reservation business engines.

Revision ID: 20260801_0020
Revises: 20260801_0019
"""

import sqlalchemy as sa
from alembic import op

revision = "20260801_0020"
down_revision = "20260801_0019"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: list[str]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    required = {
        "cc_booking_experiences",
        "cc_booking_slots",
        "cc_booking_records",
        "cc_reservation_offer_versions",
        "cc_reservation_records",
        "cc_reservation_payments",
    }
    present = existing & required
    if present == required:
        return
    if present:
        raise RuntimeError("Partial Booking/Reservation schema detected; refusing unsafe migration: " + ", ".join(sorted(present)))

    op.create_table(
        "cc_booking_experiences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("experience_id", sa.String(120), nullable=False, unique=True),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("cta_label", sa.String(255), nullable=False),
        sa.Column("trust_copy", sa.Text(), nullable=False),
        sa.Column("confirmation_copy", sa.Text(), nullable=False),
        sa.Column("theme_key", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("policy_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("brand_id", "version", name="uq_cc_booking_experience_brand_version"),
    )
    _indexes("cc_booking_experiences", ["experience_id", "brand_id", "active"])

    op.create_table(
        "cc_booking_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slot_id", sa.String(120), nullable=False, unique=True),
        sa.Column("experience_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("booking_type", sa.String(40), nullable=False),
        sa.Column("calendar_resource_id", sa.String(160), nullable=False),
        sa.Column("advisor_email", sa.String(255), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="available"),
        sa.Column("held_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name="ck_cc_booking_slot_time_order"),
        sa.UniqueConstraint("calendar_resource_id", "starts_at", "ends_at", name="uq_cc_booking_slot_resource_window"),
    )
    _indexes("cc_booking_slots", ["slot_id", "experience_id", "brand_id", "booking_type", "calendar_resource_id", "advisor_email", "starts_at", "ends_at", "status", "held_until"])

    op.create_table(
        "cc_booking_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.String(120), nullable=False, unique=True),
        sa.Column("slot_id", sa.String(120), sa.ForeignKey("cc_booking_slots.slot_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("lead_id", sa.String(120), nullable=True),
        sa.Column("opportunity_id", sa.String(120), nullable=True),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("booking_type", sa.String(40), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("customer_phone", sa.String(80), nullable=False),
        sa.Column("project_description", sa.Text(), nullable=False),
        sa.Column("plot_status", sa.String(80), nullable=False),
        sa.Column("planned_start", sa.String(120), nullable=False),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("city", sa.String(120), nullable=True),
        sa.Column("street_address", sa.String(500), nullable=True),
        sa.Column("access_notes", sa.Text(), nullable=True),
        sa.Column("document_url", sa.String(1000), nullable=True),
        sa.Column("consent_version_id", sa.String(120), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="calendar_locked"),
        sa.Column("external_sync_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("calendar_entry_id", sa.String(120), nullable=True),
        sa.Column("calendar_event_id", sa.String(255), nullable=True),
        sa.Column("meeting_link", sa.String(1000), nullable=True),
        sa.Column("cancellation_token", sa.String(160), nullable=False, unique=True),
        sa.Column("attribution_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("cc_booking_records", ["booking_id", "slot_id", "project_id", "lead_id", "opportunity_id", "brand_id", "booking_type", "customer_name", "customer_email", "status", "external_sync_status", "calendar_entry_id", "calendar_event_id", "cancellation_token"])

    op.create_table(
        "cc_reservation_offer_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("offer_version_id", sa.String(120), nullable=False, unique=True),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("public_name", sa.String(255), nullable=False),
        sa.Column("cta_label", sa.String(255), nullable=False),
        sa.Column("reservation_amount_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("target_start_months_min", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("target_start_months_max", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("price_lock_months", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("price_snapshot_id", sa.String(120), nullable=False),
        sa.Column("terms_version_id", sa.String(120), nullable=False),
        sa.Column("technical_scope_version_id", sa.String(120), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("public_summary", sa.Text(), nullable=False),
        sa.Column("exclusions_summary", sa.Text(), nullable=False),
        sa.Column("refund_rule", sa.Text(), nullable=False),
        sa.Column("transfer_rule", sa.Text(), nullable=False),
        sa.Column("legal_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("finance_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pricing_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("cc_reservation_offer_versions", ["offer_version_id", "brand_id", "price_snapshot_id", "terms_version_id", "technical_scope_version_id", "valid_to", "active"])

    op.create_table(
        "cc_reservation_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reservation_id", sa.String(120), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("lead_id", sa.String(120), nullable=True),
        sa.Column("opportunity_id", sa.String(120), nullable=True),
        sa.Column("offer_version_id", sa.String(120), sa.ForeignKey("cc_reservation_offer_versions.offer_version_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("brand_id", sa.String(100), nullable=False),
        sa.Column("house_plan_id", sa.String(120), nullable=False),
        sa.Column("house_config_id", sa.String(120), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("billing_name", sa.String(255), nullable=False),
        sa.Column("billing_address", sa.String(500), nullable=False),
        sa.Column("tax_number", sa.String(80), nullable=True),
        sa.Column("amount_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("price_snapshot_id", sa.String(120), nullable=False),
        sa.Column("terms_version_id", sa.String(120), nullable=False),
        sa.Column("technical_scope_version_id", sa.String(120), nullable=False),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="payment_pending"),
        sa.Column("price_lock_status", sa.String(40), nullable=False, server_default="inactive"),
        sa.Column("price_lock_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_id", sa.String(120), nullable=True),
        sa.Column("invoice_id", sa.String(120), nullable=True),
        sa.Column("contract_id", sa.String(120), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=False),
        sa.Column("attribution_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("cc_reservation_records", ["reservation_id", "project_id", "lead_id", "opportunity_id", "offer_version_id", "brand_id", "house_plan_id", "house_config_id", "customer_name", "customer_email", "price_snapshot_id", "terms_version_id", "technical_scope_version_id", "status", "price_lock_status", "price_lock_expires_at", "payment_id", "invoice_id", "contract_id"])

    op.create_table(
        "cc_reservation_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_id", sa.String(120), nullable=False, unique=True),
        sa.Column("reservation_id", sa.String(120), sa.ForeignKey("cc_reservation_records.reservation_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("provider_reference", sa.String(255), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("amount_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("evidence_url", sa.String(1000), nullable=True),
        sa.Column("raw_result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("cc_reservation_payments", ["payment_id", "reservation_id", "provider_reference", "idempotency_key", "status"])


def downgrade() -> None:
    for table in ["cc_reservation_payments", "cc_reservation_records", "cc_reservation_offer_versions", "cc_booking_records", "cc_booking_slots", "cc_booking_experiences"]:
        op.drop_table(table)
