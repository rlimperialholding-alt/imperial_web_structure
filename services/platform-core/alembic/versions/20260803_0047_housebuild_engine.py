"""Add canonical HouseBuild plan generation and release workflow.

Revision ID: 20260803_0047
Revises: 20260803_0046
"""

import sqlalchemy as sa

from alembic import op

revision = "20260803_0047"
down_revision = "20260803_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "housebuild_cases" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "housebuild_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.String(140), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("source_house_id", sa.String(120), nullable=False),
        sa.Column("source_catalog_version_id", sa.String(140), nullable=False),
        sa.Column("source_snapshot_json", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("rights_evidence_ref", sa.String(1200), nullable=False),
        sa.Column("rights_evidence_sha256", sa.String(64), nullable=False),
        sa.Column("requirement_json", sa.Text(), nullable=False),
        sa.Column("requirement_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="intake"),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("selected_variant_id", sa.String(140)),
        sa.Column("plotcheck_case_id", sa.String(140)),
        sa.Column("buildconfig_case_id", sa.String(140)),
        sa.Column("plancheck_case_id", sa.String(140)),
        sa.Column("final_report_document_id", sa.String(120)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("released_by", sa.String(255)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('intake','variant_selected','review','released','rejected')",
            name="ck_housebuild_case_status",
        ),
    )
    op.create_table(
        "housebuild_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("variant_id", sa.String(140), nullable=False, unique=True),
        sa.Column(
            "case_id",
            sa.String(140),
            sa.ForeignKey("housebuild_cases.case_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variant_no", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("gross_area_m2", sa.Numeric(14, 3), nullable=False),
        sa.Column("net_area_m2", sa.Numeric(14, 3), nullable=False),
        sa.Column("footprint_m2", sa.Numeric(14, 3), nullable=False),
        sa.Column("width_m", sa.Numeric(10, 3), nullable=False),
        sa.Column("depth_m", sa.Numeric(10, 3), nullable=False),
        sa.Column("floors", sa.Integer(), nullable=False),
        sa.Column("bedrooms", sa.Integer(), nullable=False),
        sa.Column("bathrooms", sa.Integer(), nullable=False),
        sa.Column("garage_spaces", sa.Integer(), nullable=False),
        sa.Column("roof_style", sa.String(100), nullable=False),
        sa.Column("facade_style", sa.String(100), nullable=False),
        sa.Column("orientation", sa.String(100), nullable=False),
        sa.Column("accessibility", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("estimated_catalog_price_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("rooms_json", sa.Text(), nullable=False),
        sa.Column("adjacency_json", sa.Text(), nullable=False),
        sa.Column("geometry_json", sa.Text(), nullable=False),
        sa.Column("geometry_signature", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="generated"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "variant_no", name="uq_housebuild_variant_no"),
        sa.CheckConstraint(
            "status IN ('generated','selected','superseded','released','rejected')",
            name="ck_housebuild_variant_status",
        ),
    )
    op.create_table(
        "housebuild_validations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("validation_id", sa.String(140), nullable=False, unique=True),
        sa.Column(
            "variant_id",
            sa.String(140),
            sa.ForeignKey("housebuild_variants.variant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("validation_key", sa.String(80), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("measured_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("checked_by", sa.String(255), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "variant_id", "validation_key", name="uq_housebuild_variant_validation"
        ),
        sa.CheckConstraint(
            "decision IN ('pass','fail','warning')", name="ck_housebuild_validation_decision"
        ),
    )
    op.create_table(
        "housebuild_gates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(140),
            sa.ForeignKey("housebuild_cases.case_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gate_key", sa.String(40), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("evidence_refs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("evidence_sha256", sa.String(64)),
        sa.Column("note", sa.Text()),
        sa.Column("decided_by", sa.String(255)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "gate_key", name="uq_housebuild_gate_case_key"),
        sa.CheckConstraint(
            "gate_key IN ('source_rights','program','deduplication','topology',"
            "'plotcheck','buildconfig','plancheck','technical')",
            name="ck_housebuild_gate_key",
        ),
        sa.CheckConstraint(
            "decision IN ('pending','approved','rejected')", name="ck_housebuild_gate_decision"
        ),
    )
    indexes = {
        "housebuild_cases": (
            "case_id",
            "project_id",
            "source_house_id",
            "source_catalog_version_id",
            "source_sha256",
            "rights_evidence_sha256",
            "requirement_sha256",
            "status",
            "selected_variant_id",
            "plotcheck_case_id",
            "buildconfig_case_id",
            "plancheck_case_id",
            "final_report_document_id",
        ),
        "housebuild_variants": (
            "variant_id",
            "case_id",
            "geometry_signature",
            "content_sha256",
            "status",
        ),
        "housebuild_validations": (
            "validation_id",
            "variant_id",
            "validation_key",
            "decision",
            "evidence_sha256",
        ),
        "housebuild_gates": ("case_id", "gate_key", "decision", "evidence_sha256"),
    }
    for table, columns in indexes.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in (
        "housebuild_gates",
        "housebuild_validations",
        "housebuild_variants",
        "housebuild_cases",
    ):
        op.drop_table(table)
