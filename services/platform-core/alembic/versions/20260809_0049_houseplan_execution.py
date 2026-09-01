"""Add HousePlan source governance and executable batch lifecycle.

Revision ID: 20260809_0049
Revises: 20260803_0048
"""

import sqlalchemy as sa

from alembic import op

revision = "20260809_0049"
down_revision = "20260803_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    user_columns = {column["name"] for column in inspector.get_columns("cc_users")}
    if "itep_subject_id" not in user_columns:
        op.add_column("cc_users", sa.Column("itep_subject_id", sa.String(140)))
        op.create_index("ix_cc_users_itep_subject_id", "cc_users", ["itep_subject_id"], unique=True)
    if "houseplan_sources" not in tables:
        op.create_table(
            "houseplan_sources",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_id", sa.String(140), nullable=False, unique=True),
            sa.Column(
                "catalog_version_id",
                sa.String(150),
                sa.ForeignKey("house_catalog_versions.catalog_version_id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("source_revision", sa.Integer(), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("legal_basis", sa.String(40), nullable=False),
            sa.Column("licence_scope", sa.Text(), nullable=False),
            sa.Column("evidence_ref", sa.String(1200), nullable=False),
            sa.Column("evidence_sha256", sa.String(64), nullable=False),
            sa.Column("rights_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(30), nullable=False, server_default="rights_review"),
            sa.Column("approved_by_subject", sa.String(140)),
            sa.Column("approved_at", sa.DateTime(timezone=True)),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column("revoked_by_subject", sa.String(140)),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
            sa.Column("revocation_reason", sa.Text()),
            sa.Column("created_by_subject", sa.String(140), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "catalog_version_id", "source_revision", name="uq_houseplan_source_revision"
            ),
            sa.CheckConstraint(
                "legal_basis IN ('owned','licensed','public_domain',"
                "'customer_authorized','unknown')",
                name="ck_houseplan_source_legal_basis",
            ),
            sa.CheckConstraint(
                "status IN ('draft','rights_review','approved','blocked','expired','revoked')",
                name="ck_houseplan_source_status",
            ),
        )
        for column in (
            "source_id",
            "catalog_version_id",
            "content_sha256",
            "legal_basis",
            "status",
            "approved_by_subject",
            "expires_at",
            "evidence_sha256",
        ):
            op.create_index(f"ix_houseplan_sources_{column}", "houseplan_sources", [column])
    if "houseplan_batches" not in tables:
        op.create_table(
            "houseplan_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("batch_id", sa.String(140), nullable=False, unique=True),
            sa.Column(
                "source_id",
                sa.String(140),
                sa.ForeignKey("houseplan_sources.source_id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("source_revision", sa.Integer(), nullable=False),
            sa.Column("source_sha256", sa.String(64), nullable=False),
            sa.Column("actor_subject", sa.String(140), nullable=False),
            sa.Column("permission_revision", sa.String(160), nullable=False),
            sa.Column("pricing_revision", sa.String(160), nullable=False),
            sa.Column("ruleset_version", sa.String(100), nullable=False),
            sa.Column("batch_hash", sa.String(64), nullable=False),
            sa.Column("request_sha256", sa.String(64), nullable=False),
            sa.Column("request_json", sa.Text(), nullable=False),
            sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
            sa.Column("dry_run_token_sha256", sa.String(64), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="running"),
            sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("invalid_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.CheckConstraint(
                "status IN ('running','completed','partial','failed')",
                name="ck_houseplan_batch_status",
            ),
        )
        for column in (
            "batch_id",
            "source_id",
            "source_sha256",
            "actor_subject",
            "batch_hash",
            "idempotency_key",
            "status",
        ):
            op.create_index(f"ix_houseplan_batches_{column}", "houseplan_batches", [column])
    if "houseplan_records" not in tables:
        op.create_table(
            "houseplan_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("plan_id", sa.String(140), nullable=False, unique=True),
            sa.Column(
                "batch_id",
                sa.String(140),
                sa.ForeignKey("houseplan_batches.batch_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("row_number", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.String(100), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("family_id", sa.String(140), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "predecessor_plan_id",
                sa.String(140),
                sa.ForeignKey("houseplan_records.plan_id", ondelete="RESTRICT"),
            ),
            sa.Column(
                "source_id",
                sa.String(140),
                sa.ForeignKey("houseplan_sources.source_id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("input_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("geometry_signature", sa.String(64), nullable=False),
            sa.Column("normalized_input_json", sa.Text(), nullable=False),
            sa.Column("geometry_json", sa.Text(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("near_duplicate_score", sa.Numeric(6, 5)),
            sa.Column(
                "near_duplicate_plan_id",
                sa.String(140),
                sa.ForeignKey("houseplan_records.plan_id", ondelete="RESTRICT"),
            ),
            sa.Column(
                "housebuild_case_id",
                sa.String(140),
                sa.ForeignKey("housebuild_cases.case_id", ondelete="RESTRICT"),
            ),
            sa.Column(
                "housebuild_variant_id",
                sa.String(140),
                sa.ForeignKey("housebuild_variants.variant_id", ondelete="RESTRICT"),
            ),
            sa.Column(
                "plancheck_task_id",
                sa.String(120),
                sa.ForeignKey("cc_tasks.task_id", ondelete="RESTRICT"),
            ),
            sa.Column("created_by_subject", sa.String(140), nullable=False),
            sa.Column("reviewed_by_subject", sa.String(140)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("batch_id", "row_number", name="uq_houseplan_batch_row"),
            sa.UniqueConstraint("family_id", "version_number", name="uq_houseplan_family_version"),
            sa.UniqueConstraint("geometry_signature", name="uq_houseplan_geometry_signature"),
            sa.CheckConstraint(
                "status IN ('draft','qa_failed','rights_recheck','plancheck_review',"
                "'approved','rejected','catalog_ready','published','archived')",
                name="ck_houseplan_record_status",
            ),
        )
        for column in (
            "plan_id",
            "batch_id",
            "project_id",
            "title",
            "family_id",
            "predecessor_plan_id",
            "source_id",
            "input_hash",
            "geometry_signature",
            "status",
            "near_duplicate_plan_id",
            "housebuild_case_id",
            "housebuild_variant_id",
            "plancheck_task_id",
            "created_by_subject",
        ):
            op.create_index(f"ix_houseplan_records_{column}", "houseplan_records", [column])
    if "houseplan_batch_items" not in tables:
        op.create_table(
            "houseplan_batch_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("item_id", sa.String(160), nullable=False, unique=True),
            sa.Column(
                "batch_id",
                sa.String(140),
                sa.ForeignKey("houseplan_batches.batch_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("row_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("input_hash", sa.String(64)),
            sa.Column("geometry_signature", sa.String(64)),
            sa.Column(
                "plan_id",
                sa.String(140),
                sa.ForeignKey("houseplan_records.plan_id", ondelete="RESTRICT"),
            ),
            sa.Column(
                "duplicate_plan_id",
                sa.String(140),
                sa.ForeignKey("houseplan_records.plan_id", ondelete="RESTRICT"),
            ),
            sa.Column("similarity_score", sa.Numeric(6, 5)),
            sa.Column("error_code", sa.String(100)),
            sa.Column("message", sa.Text()),
            sa.Column("input_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("batch_id", "row_number", name="uq_houseplan_batch_item_row"),
            sa.CheckConstraint(
                "status IN ('created','invalid','duplicate','near_duplicate_blocked')",
                name="ck_houseplan_batch_item_status",
            ),
        )
        for column in (
            "item_id",
            "batch_id",
            "status",
            "input_hash",
            "geometry_signature",
            "plan_id",
            "duplicate_plan_id",
            "error_code",
        ):
            op.create_index(f"ix_houseplan_batch_items_{column}", "houseplan_batch_items", [column])
    if "house_studio_permission_grants" not in tables:
        op.create_table(
            "house_studio_permission_grants",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("grant_id", sa.String(160), nullable=False, unique=True),
            sa.Column("subject_id", sa.String(140), nullable=False),
            sa.Column("permission", sa.String(100), nullable=False),
            sa.Column("effect", sa.String(10), nullable=False),
            sa.Column("scope_type", sa.String(20), nullable=False),
            sa.Column("project_id", sa.String(100)),
            sa.Column("revision", sa.String(100), nullable=False),
            sa.Column("claim_sequence", sa.Integer(), nullable=False),
            sa.Column("claim_issuer", sa.String(255), nullable=False),
            sa.Column("claim_sha256", sa.String(64), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "subject_id",
                "permission",
                "project_id",
                "effect",
                "revision",
                name="uq_house_studio_permission_revision",
            ),
            sa.CheckConstraint(
                "scope_type IN ('global','project')",
                name="ck_house_studio_permission_scope",
            ),
            sa.CheckConstraint(
                "effect IN ('allow','deny')",
                name="ck_house_studio_permission_effect",
            ),
            sa.CheckConstraint(
                "status IN ('active','revoked','expired')",
                name="ck_house_studio_permission_status",
            ),
        )
        for column in (
            "grant_id",
            "subject_id",
            "permission",
            "effect",
            "scope_type",
            "project_id",
            "claim_sha256",
            "claim_sequence",
            "status",
            "valid_from",
            "expires_at",
        ):
            op.create_index(
                f"ix_house_studio_permission_grants_{column}",
                "house_studio_permission_grants",
                [column],
            )


def downgrade() -> None:
    raise RuntimeError(
        "0049 contains canonical business data and has no destructive automatic downgrade. "
        "Use the verified export/restore runbook and a forward migration."
    )
