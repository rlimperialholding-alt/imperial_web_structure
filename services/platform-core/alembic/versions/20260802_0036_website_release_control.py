"""Add multi-site Website Content Control releases and rollback.

Revision ID: 20260802_0036
Revises: 20260802_0035
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0036"
down_revision = "20260802_0035"
branch_labels = None
depends_on = None

TABLES = {"website_sites", "website_releases", "website_release_targets", "website_route_states", "website_publication_incidents"}


def _ix(table: str, *columns: str) -> None:
    for column in columns: op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names()); present = existing & TABLES
    if present and present != TABLES: raise RuntimeError("Partial Website Content schema: " + ", ".join(sorted(present)))
    if present == TABLES: return
    op.create_table("website_sites",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("site_id", sa.String(120), nullable=False, unique=True), sa.Column("brand_id", sa.String(120), nullable=False), sa.Column("name", sa.String(255), nullable=False), sa.Column("base_url", sa.String(1200), nullable=False, unique=True), sa.Column("adapter_endpoint", sa.String(1200), nullable=False), sa.Column("credential_ref", sa.String(1200), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("kill_switch", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("kill_switch_reason", sa.Text()), sa.Column("created_by", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    _ix("website_sites", "site_id", "brand_id", "active", "kill_switch")
    op.create_table("website_releases",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("release_id", sa.String(120), nullable=False, unique=True), sa.Column("asset_id", sa.String(120), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("content_version", sa.Integer(), nullable=False), sa.Column("content_sha256", sa.String(64), nullable=False), sa.Column("publication_bundle_id", sa.String(120), nullable=False), sa.Column("publication_proof_id", sa.String(120), nullable=False), sa.Column("release_manifest_sha256", sa.String(64), nullable=False), sa.Column("target_count", sa.Integer(), nullable=False), sa.Column("status", sa.String(40), nullable=False, server_default="ready"), sa.Column("auto_rollback_status", sa.String(40), nullable=False, server_default="not_required"), sa.Column("failure_reason", sa.Text()), sa.Column("created_by", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("dispatched_at", sa.DateTime(timezone=True)), sa.Column("activated_at", sa.DateTime(timezone=True)), sa.Column("rolled_back_at", sa.DateTime(timezone=True)), sa.Column("rolled_back_by", sa.String(255)), sa.UniqueConstraint("asset_id", "version", name="uq_website_asset_release_version"))
    _ix("website_releases", "release_id", "asset_id", "content_sha256", "publication_bundle_id", "publication_proof_id", "release_manifest_sha256", "status", "auto_rollback_status")
    op.create_table("website_release_targets",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("target_id", sa.String(120), nullable=False, unique=True), sa.Column("release_id", sa.String(120), nullable=False), sa.Column("site_id", sa.String(120), nullable=False), sa.Column("route_path", sa.String(1000), nullable=False), sa.Column("locale", sa.String(20), nullable=False, server_default="hu-HU"), sa.Column("canonical_url", sa.String(1200), nullable=False), sa.Column("payload_sha256", sa.String(64), nullable=False), sa.Column("status", sa.String(40), nullable=False, server_default="pending"), sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("external_version_id", sa.String(255)), sa.Column("published_url", sa.String(1200)), sa.Column("rendered_content_sha256", sa.String(64)), sa.Column("previous_target_id", sa.String(120)), sa.Column("receipt_at", sa.DateTime(timezone=True)), sa.Column("smoke_http_status", sa.Integer()), sa.Column("smoke_json", sa.Text(), nullable=False, server_default="{}"), sa.Column("smoke_at", sa.DateTime(timezone=True)), sa.Column("failure_reason", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("release_id", "site_id", "route_path", "locale", name="uq_website_release_target"))
    _ix("website_release_targets", "target_id", "release_id", "site_id", "route_path", "payload_sha256", "status", "previous_target_id")
    op.create_table("website_route_states",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("route_state_id", sa.String(120), nullable=False, unique=True), sa.Column("site_id", sa.String(120), nullable=False), sa.Column("route_path", sa.String(1000), nullable=False), sa.Column("locale", sa.String(20), nullable=False, server_default="hu-HU"), sa.Column("current_release_id", sa.String(120), nullable=False), sa.Column("current_target_id", sa.String(120), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("site_id", "route_path", "locale", name="uq_website_route_state"))
    _ix("website_route_states", "route_state_id", "site_id", "route_path", "current_release_id", "current_target_id")
    op.create_table("website_publication_incidents",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("incident_id", sa.String(120), nullable=False, unique=True), sa.Column("release_id", sa.String(120), nullable=False), sa.Column("target_id", sa.String(120)), sa.Column("severity", sa.String(30), nullable=False, server_default="critical"), sa.Column("incident_type", sa.String(80), nullable=False), sa.Column("description", sa.Text(), nullable=False), sa.Column("rollback_action", sa.String(80), nullable=False), sa.Column("status", sa.String(30), nullable=False, server_default="open"), sa.Column("created_by", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("resolved_at", sa.DateTime(timezone=True)))
    _ix("website_publication_incidents", "incident_id", "release_id", "target_id", "severity", "incident_type", "status")


def downgrade() -> None:
    for table in ("website_publication_incidents", "website_route_states", "website_release_targets", "website_releases", "website_sites"): op.drop_table(table)
