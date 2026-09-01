"""Add the durable HouseVision Typehouse Factory v1.0 queue.

Revision ID: 20260811_0062
Revises: 20260811_0061
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260811_0062"
down_revision = "20260811_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    rights_table = "housevision_rights_policies"
    columns = {item["name"] for item in inspector.get_columns(rights_table)}
    for column in (
        sa.Column("grant_id", sa.String(255)),
        sa.Column("owner_attestation_sha256", sa.String(64)),
        sa.Column("page_scope_sha256", sa.String(64)),
    ):
        if column.name not in columns:
            op.add_column(rights_table, column)

    inspector = sa.inspect(bind)
    unique_names = {
        item["name"] for item in inspector.get_unique_constraints(rights_table) if item["name"]
    }
    if "uq_housevision_rights_grant_id" not in unique_names:
        with op.batch_alter_table(rights_table) as batch:
            batch.create_unique_constraint("uq_housevision_rights_grant_id", ["grant_id"])
    inspector = sa.inspect(bind)
    index_names = {item["name"] for item in inspector.get_indexes(rights_table)}
    if "ix_housevision_rights_grant_id" not in index_names:
        op.create_index("ix_housevision_rights_grant_id", rights_table, ["grant_id"])

    factory_tables = {
        "housevision_factory_streams",
        "housevision_factory_imports",
        "housevision_factory_import_items",
        "housevision_factory_jobs",
        "housevision_factory_artifacts",
        "housevision_factory_qa_runs",
        "housevision_factory_repairs",
    }
    existing_factory_tables = factory_tables.intersection(inspector.get_table_names())
    if existing_factory_tables == factory_tables:
        return
    if existing_factory_tables:
        raise RuntimeError(
            "A Typehouse Factory séma részleges; automatikus migráció helyett helyreállítás kell: "
            + ", ".join(sorted(existing_factory_tables))
        )
    op.create_table(
        "housevision_factory_streams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream_id", sa.String(120), nullable=False, unique=True),
        sa.Column("catalog_id", sa.String(160), nullable=False, unique=True),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pause_reason", sa.Text()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hvf_stream_catalog", "housevision_factory_streams", ["catalog_id"])
    op.create_index("ix_hvf_stream_paused", "housevision_factory_streams", ["paused"])

    op.create_table(
        "housevision_factory_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.String(120), nullable=False, unique=True),
        sa.Column("stream_id", sa.String(120), nullable=False),
        sa.Column("catalog_id", sa.String(160), nullable=False),
        sa.Column("source_file_name", sa.String(500)),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("registered_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(40), nullable=False, server_default="REGISTERED"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_hvf_import_stream_status", "housevision_factory_imports", ["stream_id", "status"]
    )
    op.create_index("ix_hvf_import_source_hash", "housevision_factory_imports", ["source_sha256"])

    op.create_table(
        "housevision_factory_import_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_item_id", sa.String(120), nullable=False, unique=True),
        sa.Column("import_id", sa.String(120), nullable=False),
        sa.Column("stream_id", sa.String(120), nullable=False),
        sa.Column("catalog_id", sa.String(160), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("requested_url", sa.String(1600), nullable=False),
        sa.Column("requested_url_sha256", sa.String(64), nullable=False),
        sa.Column("rights_grant_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="PENDING"),
        sa.Column("job_id", sa.String(120)),
        sa.Column("terminal_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("import_id", "sequence", name="uq_hvf_import_sequence"),
        sa.UniqueConstraint(
            "catalog_id", "requested_url_sha256", name="uq_hvf_catalog_requested_url"
        ),
    )
    op.create_index(
        "ix_hvf_item_claim", "housevision_factory_import_items", ["stream_id", "status", "sequence"]
    )
    op.create_index("ix_hvf_item_job", "housevision_factory_import_items", ["job_id"])

    op.create_table(
        "housevision_factory_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(120), nullable=False, unique=True),
        sa.Column("job_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("stream_id", sa.String(120), nullable=False),
        sa.Column("catalog_id", sa.String(160), nullable=False),
        sa.Column("import_item_id", sa.String(120)),
        sa.Column("idempotency_key", sa.String(500), nullable=False),
        sa.Column("requested_url", sa.String(1600), nullable=False),
        sa.Column("canonical_url", sa.String(1600), nullable=False),
        sa.Column("final_url", sa.String(1600)),
        sa.Column("requested_url_sha256", sa.String(64), nullable=False),
        sa.Column("source_revision_hash", sa.String(64), nullable=False),
        sa.Column("source_page_id", sa.String(120), nullable=False),
        sa.Column("project_code", sa.String(160)),
        sa.Column("house_plan_id", sa.String(120), unique=True),
        sa.Column("geographic_name", sa.String(255), unique=True),
        sa.Column("rights_grant_id", sa.String(255), nullable=False),
        sa.Column("rights_policy_id", sa.String(120)),
        sa.Column(
            "visual_profile_id",
            sa.String(120),
            nullable=False,
            server_default="california_ultra_v1",
        ),
        sa.Column(
            "output_profile_id", sa.String(120), nullable=False, server_default="web_8k_master_v1"
        ),
        sa.Column("render_provider", sa.String(120), nullable=False, server_default="disabled"),
        sa.Column("status", sa.String(50), nullable=False, server_default="PENDING"),
        sa.Column("stage", sa.String(80), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("render_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repair_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_passes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("package_manifest_sha256", sa.String(64)),
        sa.Column("package_url", sa.String(1600)),
        sa.Column("lease_owner", sa.String(255)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_title", sa.String(1000)),
        sa.Column("gross_floor_area_m2", sa.Numeric(12, 2)),
        sa.Column("net_floor_area_m2", sa.Numeric(12, 2)),
        sa.Column("levels", sa.Integer()),
        sa.Column("rooms_total", sa.Integer()),
        sa.Column("finding_summary_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("last_error_code", sa.String(120)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_hvf_job_idempotency_key"),
        sa.UniqueConstraint(
            "catalog_id",
            "canonical_url",
            "source_revision_hash",
            "job_revision",
            name="uq_hvf_job_source_revision",
        ),
    )
    op.create_index(
        "ix_hvf_job_claim",
        "housevision_factory_jobs",
        ["stream_id", "status", "lease_until", "created_at"],
    )
    op.create_index(
        "ix_hvf_job_source",
        "housevision_factory_jobs",
        ["catalog_id", "canonical_url", "source_revision_hash"],
    )
    op.create_index("ix_hvf_job_manifest", "housevision_factory_jobs", ["package_manifest_sha256"])

    op.create_table(
        "housevision_factory_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("artifact_id", sa.String(120), nullable=False, unique=True),
        sa.Column("job_id", sa.String(120), nullable=False),
        sa.Column("role", sa.String(80), nullable=False),
        sa.Column("relative_path", sa.String(1200), nullable=False),
        sa.Column("storage_ref", sa.String(1600), nullable=False),
        sa.Column("mime_type", sa.String(160), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width_px", sa.Integer()),
        sa.Column("height_px", sa.Integer()),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("source_page_url", sa.String(1600), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "relative_path", name="uq_hvf_artifact_path"),
    )
    op.create_index("ix_hvf_artifact_job_role", "housevision_factory_artifacts", ["job_id", "role"])
    op.create_index("ix_hvf_artifact_sha", "housevision_factory_artifacts", ["sha256"])

    op.create_table(
        "housevision_factory_qa_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("qa_run_id", sa.String(120), nullable=False, unique=True),
        sa.Column("job_id", sa.String(120), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("package_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("deterministic_pass", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("semantic_pass", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("semantic_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("verifier_id", sa.String(255), nullable=False),
        sa.Column("verifier_model", sa.String(255), nullable=False),
        sa.Column("findings_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "run_number", name="uq_hvf_qa_run_number"),
    )
    op.create_index(
        "ix_hvf_qa_manifest",
        "housevision_factory_qa_runs",
        ["job_id", "package_manifest_sha256", "decision"],
    )

    op.create_table(
        "housevision_factory_repairs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repair_id", sa.String(120), nullable=False, unique=True),
        sa.Column("job_id", sa.String(120), nullable=False),
        sa.Column("finding_code", sa.String(120), nullable=False),
        sa.Column("action_type", sa.String(120), nullable=False),
        sa.Column("before_sha256", sa.String(64)),
        sa.Column("after_sha256", sa.String(64)),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("provider_ref", sa.String(500)),
        sa.Column("result", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hvf_repair_job", "housevision_factory_repairs", ["job_id", "created_at"])


def downgrade() -> None:
    for table in (
        "housevision_factory_repairs",
        "housevision_factory_qa_runs",
        "housevision_factory_artifacts",
        "housevision_factory_jobs",
        "housevision_factory_import_items",
        "housevision_factory_imports",
        "housevision_factory_streams",
    ):
        op.drop_table(table)
    op.drop_index("ix_housevision_rights_grant_id", table_name="housevision_rights_policies")
    op.drop_constraint(
        "uq_housevision_rights_grant_id", "housevision_rights_policies", type_="unique"
    )
    op.drop_column("housevision_rights_policies", "page_scope_sha256")
    op.drop_column("housevision_rights_policies", "owner_attestation_sha256")
    op.drop_column("housevision_rights_policies", "grant_id")
