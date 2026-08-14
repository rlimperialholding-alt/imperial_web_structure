"""Add canonical BuildConfig version, BOM and release workflow.

Revision ID: 20260803_0048
Revises: 20260803_0047
"""

import sqlalchemy as sa

from alembic import op

revision = "20260803_0048"
down_revision = "20260803_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "buildconfig_cases" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "buildconfig_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.String(140), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("housebuild_case_id", sa.String(140), nullable=False),
        sa.Column("housebuild_variant_id", sa.String(140), nullable=False),
        sa.Column("current_version_id", sa.String(140), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("final_report_document_id", sa.String(120)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','calculated','review','approved','rejected','superseded')",
            name="ck_buildconfig_case_status",
        ),
    )
    op.create_table(
        "buildconfig_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.String(140), nullable=False, unique=True),
        sa.Column(
            "case_id",
            sa.String(140),
            sa.ForeignKey("buildconfig_cases.case_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("brand", sa.String(100), nullable=False),
        sa.Column("technology", sa.String(120), nullable=False),
        sa.Column("completion_level", sa.String(100), nullable=False),
        sa.Column("package_name", sa.String(100), nullable=False),
        sa.Column("gross_area_m2", sa.Numeric(14, 3), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),
        sa.Column("vat_rate", sa.Numeric(8, 5), nullable=False),
        sa.Column("option_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("bom_json", sa.Text(), nullable=False),
        sa.Column("payment_schedule_json", sa.Text(), nullable=False),
        sa.Column("capacity_json", sa.Text(), nullable=False),
        sa.Column("pricing_snapshot_json", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("config_sha256", sa.String(64), nullable=False),
        sa.Column("bom_sha256", sa.String(64), nullable=False),
        sa.Column("net_cost_huf", sa.Numeric(20, 2), nullable=False),
        sa.Column("net_price_huf", sa.Numeric(20, 2), nullable=False),
        sa.Column("vat_huf", sa.Numeric(20, 2), nullable=False),
        sa.Column("gross_price_huf", sa.Numeric(20, 2), nullable=False),
        sa.Column("margin_percent", sa.Numeric(8, 4), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "version_no", name="uq_buildconfig_case_version"),
        sa.CheckConstraint(
            "status IN ('draft','submitted','approved','rejected','superseded')",
            name="ck_buildconfig_version_status",
        ),
    )
    op.create_table(
        "buildconfig_validations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("validation_id", sa.String(140), nullable=False, unique=True),
        sa.Column(
            "version_id",
            sa.String(140),
            sa.ForeignKey("buildconfig_versions.version_id", ondelete="CASCADE"),
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
            "version_id", "validation_key", name="uq_buildconfig_version_validation"
        ),
        sa.CheckConstraint(
            "decision IN ('pass','fail','warning')",
            name="ck_buildconfig_validation_decision",
        ),
    )
    op.create_table(
        "buildconfig_gates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "version_id",
            sa.String(140),
            sa.ForeignKey("buildconfig_versions.version_id", ondelete="CASCADE"),
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
        sa.UniqueConstraint("version_id", "gate_key", name="uq_buildconfig_version_gate"),
        sa.CheckConstraint(
            "gate_key IN ('source','houseplan','compatibility','bom','pricing','margin',"
            "'cashflow','capacity','technical','finance')",
            name="ck_buildconfig_gate_key",
        ),
        sa.CheckConstraint(
            "decision IN ('pending','approved','rejected')",
            name="ck_buildconfig_gate_decision",
        ),
    )
    indexes = {
        "buildconfig_cases": (
            "case_id",
            "project_id",
            "housebuild_case_id",
            "housebuild_variant_id",
            "current_version_id",
            "status",
            "final_report_document_id",
        ),
        "buildconfig_versions": (
            "version_id",
            "case_id",
            "status",
            "source_sha256",
            "config_sha256",
            "bom_sha256",
        ),
        "buildconfig_validations": (
            "validation_id",
            "version_id",
            "validation_key",
            "decision",
            "evidence_sha256",
        ),
        "buildconfig_gates": ("version_id", "gate_key", "decision", "evidence_sha256"),
    }
    for table, columns in indexes.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in (
        "buildconfig_gates",
        "buildconfig_validations",
        "buildconfig_versions",
        "buildconfig_cases",
    ):
        op.drop_table(table)
