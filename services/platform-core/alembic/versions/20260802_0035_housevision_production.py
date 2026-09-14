"""Add native HouseVision production lifecycle.

Revision ID: 20260802_0035
Revises: 20260802_0034
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0035"
down_revision = "20260802_0034"
branch_labels = None
depends_on = None

TABLES = {
    "housevision_rights_policies", "housevision_jobs", "housevision_source_assets",
    "housevision_geometry_locks", "housevision_output_assets", "housevision_qa_reports",
    "housevision_packages", "housevision_names",
}


def _ix(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    present = existing & TABLES
    if present and present != TABLES:
        raise RuntimeError("Partial HouseVision schema: " + ", ".join(sorted(present)))
    if present == TABLES:
        return

    op.create_table(
        "housevision_rights_policies",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("policy_id", sa.String(120), nullable=False, unique=True),
        sa.Column("domain", sa.String(255), nullable=False), sa.Column("path_prefix", sa.String(1000), nullable=False, server_default="/"),
        sa.Column("rights_status", sa.String(40), nullable=False), sa.Column("evidence_ref", sa.String(1200), nullable=False),
        sa.Column("attribution_required", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("attribution_text", sa.Text()),
        sa.Column("crawl_delay_seconds", sa.Integer(), nullable=False, server_default="2"), sa.Column("max_assets_per_page", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)), sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("housevision_rights_policies", "policy_id", "domain", "rights_status", "active")

    op.create_table(
        "housevision_jobs",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("job_id", sa.String(120), nullable=False, unique=True),
        sa.Column("brand_id", sa.String(120), nullable=False), sa.Column("source_url", sa.String(1200), nullable=False),
        sa.Column("source_page_id", sa.String(120), nullable=False), sa.Column("rights_policy_id", sa.String(120)),
        sa.Column("house_id", sa.String(120)), sa.Column("house_name_id", sa.String(120)),
        sa.Column("status", sa.String(50), nullable=False, server_default="RECEIVED"), sa.Column("operation_mode", sa.String(30), nullable=False, server_default="package_only"),
        sa.Column("render_provider", sa.String(50), nullable=False, server_default="mock"), sa.Column("render_prompt_version", sa.String(120), nullable=False, server_default="housevision-v1"),
        sa.Column("brand_policy_version", sa.String(120), nullable=False, server_default="brand-visual-v1"),
        sa.Column("accepted_source_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("output_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("publication_eligibility", sa.String(40), nullable=False, server_default="blocked"),
        sa.Column("provider_cost_huf", sa.Numeric(18, 2), nullable=False, server_default="0"), sa.Column("failure_reason", sa.Text()),
        sa.Column("created_by", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("housevision_jobs", "job_id", "brand_id", "source_page_id", "rights_policy_id", "house_id", "house_name_id", "status", "publication_eligibility")

    op.create_table(
        "housevision_source_assets",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("source_visual_id", sa.String(120), nullable=False, unique=True),
        sa.Column("job_id", sa.String(120), nullable=False), sa.Column("source_url", sa.String(1200), nullable=False),
        sa.Column("asset_type", sa.String(30), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False), sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False), sa.Column("magic_mime_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="accepted"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "content_sha256", name="uq_housevision_source_hash"),
    )
    _ix("housevision_source_assets", "source_visual_id", "job_id", "asset_type", "content_sha256", "status")

    op.create_table(
        "housevision_geometry_locks",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("geometry_lock_id", sa.String(120), nullable=False, unique=True),
        sa.Column("job_id", sa.String(120), nullable=False), sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("floorplan_topology_sha256", sa.String(64), nullable=False), sa.Column("massing_signature", sa.String(500), nullable=False),
        sa.Column("roof_form", sa.String(255), nullable=False), sa.Column("roof_pitch_deg", sa.Numeric(8, 2)),
        sa.Column("storey_count", sa.Integer(), nullable=False), sa.Column("window_count", sa.Integer(), nullable=False),
        sa.Column("door_count", sa.Integer(), nullable=False), sa.Column("width_depth_height_ratio", sa.String(120), nullable=False),
        sa.Column("immutable_features_json", sa.Text(), nullable=False, server_default="[]"), sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("housevision_geometry_locks", "geometry_lock_id", "job_id", "content_sha256")

    op.create_table(
        "housevision_output_assets",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("output_visual_id", sa.String(120), nullable=False, unique=True),
        sa.Column("job_id", sa.String(120), nullable=False), sa.Column("source_visual_id", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"), sa.Column("provider_job_id", sa.String(255), nullable=False),
        sa.Column("output_ref", sa.String(1200), nullable=False), sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=False), sa.Column("height_px", sa.Integer(), nullable=False),
        sa.Column("edge_overlap", sa.Numeric(8, 6), nullable=False), sa.Column("roof_match", sa.Numeric(8, 6), nullable=False),
        sa.Column("opening_match", sa.Numeric(8, 6), nullable=False), sa.Column("floorplan_fidelity", sa.Numeric(8, 6)),
        sa.Column("full_house_in_frame", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("daylight_pass", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("photorealism_pass", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("brand_identity_pass", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("privacy_pass", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("status", sa.String(40), nullable=False, server_default="qa_pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("housevision_output_assets", "output_visual_id", "job_id", "source_visual_id", "content_sha256", "status")

    op.create_table(
        "housevision_qa_reports",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("qa_report_id", sa.String(120), nullable=False, unique=True),
        sa.Column("job_id", sa.String(120), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("gates_json", sa.Text(), nullable=False), sa.Column("critical_failures_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("automatic_retry", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("housevision_qa_reports", "qa_report_id", "job_id", "status")

    op.create_table(
        "housevision_packages",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("package_id", sa.String(120), nullable=False, unique=True),
        sa.Column("job_id", sa.String(120), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("house_id", sa.String(120)),
        sa.Column("storage_ref", sa.String(1200), nullable=False), sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False), sa.Column("output_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="ready"), sa.Column("dam_handoff_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("buildconfig_handoff_status", sa.String(40), nullable=False, server_default="pending"), sa.Column("publication_status", sa.String(40), nullable=False, server_default="blocked"),
        sa.Column("supersedes_package_id", sa.String(120)), sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("job_id", "version", name="uq_housevision_package_version"),
    )
    _ix("housevision_packages", "package_id", "job_id", "house_id", "manifest_sha256", "status")

    op.create_table(
        "housevision_names",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("house_name_id", sa.String(120), nullable=False, unique=True),
        sa.Column("brand_id", sa.String(120), nullable=False), sa.Column("public_name", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="reserved"), sa.Column("job_id", sa.String(120), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("housevision_names", "house_name_id", "brand_id", "public_name", "status", "job_id")


def downgrade() -> None:
    for table in ("housevision_names", "housevision_packages", "housevision_qa_reports", "housevision_output_assets", "housevision_geometry_locks", "housevision_source_assets", "housevision_jobs", "housevision_rights_policies"):
        op.drop_table(table)
