"""Add shared-db land acquisition and publication-control workflow.

Revision ID: 20260825_0077
Revises: 20260821_0076
"""

import sqlalchemy as sa

from alembic import op

revision = "20260825_0077"
down_revision = "20260821_0076"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "land_opportunities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("opportunity_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "source_signal_id",
            sa.String(120),
            sa.ForeignKey("growth_signals.signal_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("source_code", sa.String(120), nullable=False),
        sa.Column("external_key", sa.String(255), nullable=False),
        sa.Column("source_content_sha256", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(1500), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("location", sa.String(500)),
        sa.Column("property_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("state", sa.String(40), nullable=False, server_default="DISCOVERED"),
        sa.Column("listing_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_status_evidence_ref", sa.String(1500)),
        sa.Column("source_status_changed_by", sa.String(255)),
        sa.Column("source_status_changed_at", sa.DateTime(timezone=True)),
        sa.Column("source_verified_by", sa.String(255)),
        sa.Column("source_verified_at", sa.DateTime(timezone=True)),
        sa.Column("source_verification_note", sa.Text()),
        sa.Column("deal_evidence_ref", sa.String(1500)),
        sa.Column("deal_evidence_sha256", sa.String(64)),
        sa.Column("deal_recorded_by", sa.String(255)),
        sa.Column("deal_recorded_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('DISCOVERED','SOURCE_VERIFIED','CONTACTED','REPLIED','DEAL_VALIDATED',"
            "'PACKAGE_READY','PUBLISH_APPROVED','PARTIAL_PUBLISH','PUBLISHED',"
            "'TAKEDOWN_REQUIRED','WITHDRAWN','CLOSED_NO_DEAL')",
            name="ck_land_opportunity_state",
        ),
    )
    _indexes(
        "land_opportunities",
        (
            "opportunity_id",
            "source_signal_id",
            "source_code",
            "external_key",
            "source_content_sha256",
            "location",
            "property_fingerprint",
            "state",
            "listing_active",
            "deal_evidence_sha256",
        ),
    )

    op.create_table(
        "land_authority_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("grant_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "opportunity_id",
            sa.String(120),
            sa.ForeignKey("land_opportunities.opportunity_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("grantor_reference", sa.String(500), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False),
        sa.Column("evidence_ref", sa.String(1500), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("approved_by", sa.String(255), nullable=False),
        sa.Column("revoked_by", sa.String(255)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revocation_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('ACTIVE','REVOKED','EXPIRED')", name="ck_land_authority_status"
        ),
        sa.CheckConstraint("valid_until > valid_from", name="ck_land_authority_time_order"),
    )
    _indexes(
        "land_authority_grants",
        ("grant_id", "opportunity_id", "evidence_sha256", "valid_from", "valid_until", "status"),
    )

    op.create_table(
        "land_listing_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("package_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "opportunity_id",
            sa.String(120),
            sa.ForeignKey("land_opportunities.opportunity_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "authority_grant_id",
            sa.String(120),
            sa.ForeignKey("land_authority_grants.grant_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "plotcheck_case_id",
            sa.String(140),
            sa.ForeignKey("plotcheck_cases.case_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "house_id",
            sa.String(120),
            sa.ForeignKey("house_catalog_plans.house_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "catalog_version_id",
            sa.String(150),
            sa.ForeignKey("house_catalog_versions.catalog_version_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "buildconfig_case_id",
            sa.String(140),
            sa.ForeignKey("buildconfig_cases.case_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "buildconfig_version_id",
            sa.String(140),
            sa.ForeignKey("buildconfig_versions.version_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="READY"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("reviewed_by", sa.String(255)),
        sa.Column("review_note", sa.Text()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "opportunity_id", "version", name="uq_land_listing_package_opportunity_version"
        ),
        sa.CheckConstraint(
            "status IN ('READY','APPROVED','SUPERSEDED','WITHDRAWN')",
            name="ck_land_listing_package_status",
        ),
    )
    _indexes(
        "land_listing_packages",
        (
            "package_id",
            "opportunity_id",
            "authority_grant_id",
            "plotcheck_case_id",
            "house_id",
            "catalog_version_id",
            "buildconfig_case_id",
            "buildconfig_version_id",
            "payload_sha256",
            "status",
        ),
    )

    op.create_table(
        "land_publication_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attempt_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "opportunity_id",
            sa.String(120),
            sa.ForeignKey("land_opportunities.opportunity_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "package_id",
            sa.String(120),
            sa.ForeignKey("land_listing_packages.package_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(100), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("outbox_message_id", sa.String(120)),
        sa.Column("external_id", sa.String(500)),
        sa.Column("public_url", sa.String(1500)),
        sa.Column("proof_json", sa.Text()),
        sa.Column("proof_sha256", sa.String(64)),
        sa.Column("blocked_reason", sa.Text()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("action IN ('PUBLISH','WITHDRAW')", name="ck_land_publication_action"),
        sa.CheckConstraint(
            "status IN ('BLOCKED','QUEUED','EXPORTED','UNKNOWN','SUCCEEDED','FAILED',"
            "'WITHDRAWAL_REQUIRED','WITHDRAWN')",
            name="ck_land_publication_status",
        ),
    )
    _indexes(
        "land_publication_attempts",
        (
            "attempt_id",
            "opportunity_id",
            "package_id",
            "channel",
            "action",
            "idempotency_key",
            "payload_sha256",
            "status",
            "outbox_message_id",
            "external_id",
            "proof_sha256",
        ),
    )


def downgrade() -> None:
    op.drop_table("land_publication_attempts")
    op.drop_table("land_listing_packages")
    op.drop_table("land_authority_grants")
    op.drop_table("land_opportunities")
