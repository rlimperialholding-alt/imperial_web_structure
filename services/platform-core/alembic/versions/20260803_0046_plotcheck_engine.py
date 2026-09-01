"""Add canonical PlotCheck engineering workflow.

Revision ID: 20260803_0046
Revises: 20260803_0045
"""

import sqlalchemy as sa

from alembic import op

revision = "20260803_0046"
down_revision = "20260803_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "plotcheck_rule_sets" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "plotcheck_rule_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_set_id", sa.String(140), nullable=False, unique=True),
        sa.Column("municipality", sa.String(255), nullable=False),
        sa.Column("zoning_code", sa.String(100), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("lifecycle_status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("source_url", sa.String(1200), nullable=False),
        sa.Column("source_document_version", sa.String(120), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date()),
        sa.Column("maximum_coverage_percent", sa.Numeric(8, 3), nullable=False),
        sa.Column("maximum_floor_area_ratio", sa.Numeric(8, 3), nullable=False),
        sa.Column("maximum_height_m", sa.Numeric(8, 3), nullable=False),
        sa.Column("minimum_green_percent", sa.Numeric(8, 3), nullable=False),
        sa.Column("front_setback_m", sa.Numeric(8, 3), nullable=False),
        sa.Column("side_setback_m", sa.Numeric(8, 3), nullable=False),
        sa.Column("rear_setback_m", sa.Numeric(8, 3), nullable=False),
        sa.Column("allowed_uses_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("verified_by", sa.String(255)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("municipality", "zoning_code", "version", name="uq_plotcheck_rule_version"),
        sa.CheckConstraint("lifecycle_status IN ('draft','verified','demo','uat','retired')", name="ck_plotcheck_rule_lifecycle"),
    )
    op.create_table(
        "plotcheck_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.String(140), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("address", sa.String(800), nullable=False),
        sa.Column("parcel_number", sa.String(120), nullable=False),
        sa.Column("municipality", sa.String(255), nullable=False),
        sa.Column("zoning_code", sa.String(100), nullable=False),
        sa.Column("rule_set_id", sa.String(140), sa.ForeignKey("plotcheck_rule_sets.rule_set_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="intake"),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("geometry_json", sa.Text(), nullable=False),
        sa.Column("geometry_crs", sa.String(80), nullable=False, server_default="LOCAL-METRIC"),
        sa.Column("geometry_sha256", sa.String(64), nullable=False),
        sa.Column("declared_plot_area_m2", sa.Numeric(14, 3), nullable=False),
        sa.Column("proposed_footprint_m2", sa.Numeric(14, 3), nullable=False),
        sa.Column("proposed_gross_floor_area_m2", sa.Numeric(14, 3), nullable=False),
        sa.Column("proposed_paved_area_m2", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("proposed_height_m", sa.Numeric(8, 3), nullable=False),
        sa.Column("proposed_use", sa.String(120), nullable=False, server_default="residential"),
        sa.Column("proposed_width_m", sa.Numeric(10, 3), nullable=False),
        sa.Column("proposed_depth_m", sa.Numeric(10, 3), nullable=False),
        sa.Column("house_id", sa.String(120)),
        sa.Column("final_assessment_id", sa.String(140)),
        sa.Column("final_report_document_id", sa.String(120)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("finalized_by", sa.String(255)),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('intake','review','fit','fit_with_conditions','redesign_required','not_suitable')", name="ck_plotcheck_case_status"),
    )
    op.create_table(
        "plotcheck_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evidence_id", sa.String(140), nullable=False, unique=True),
        sa.Column("case_id", sa.String(140), sa.ForeignKey("plotcheck_cases.case_id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("source_reference", sa.String(1200), nullable=False),
        sa.Column("source_version", sa.String(120), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("legal_blocker", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("verified_by", sa.String(255)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("category IN ('land_registry','cadastral_map','hesz','townscape','geodesy','soil','utilities','access','logistics','legal','other')", name="ck_plotcheck_evidence_category"),
    )
    op.create_table(
        "plotcheck_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_id", sa.String(140), nullable=False, unique=True),
        sa.Column("case_id", sa.String(140), sa.ForeignKey("plotcheck_cases.case_id", ondelete="CASCADE"), nullable=False),
        sa.Column("condition", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("estimated_cost_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("deadline_impact_days", sa.Integer(), nullable=False),
        sa.Column("design_impact", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("completion_evidence_ref", sa.String(1200)),
        sa.Column("completion_evidence_sha256", sa.String(64)),
        sa.Column("completed_by", sa.String(255)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('open','completed','cancelled')", name="ck_plotcheck_action_status"),
    )
    op.create_table(
        "plotcheck_gates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.String(140), sa.ForeignKey("plotcheck_cases.case_id", ondelete="CASCADE"), nullable=False),
        sa.Column("gate_key", sa.String(40), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("note", sa.Text()),
        sa.Column("decided_by", sa.String(255)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "gate_key", name="uq_plotcheck_gate_case_key"),
        sa.CheckConstraint("gate_key IN ('identity','zoning','geodesy','soil','utilities','access','logistics','engineering')", name="ck_plotcheck_gate_key"),
        sa.CheckConstraint("decision IN ('pending','approved','rejected')", name="ck_plotcheck_gate_decision"),
    )
    op.create_table(
        "plotcheck_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.String(140), nullable=False, unique=True),
        sa.Column("case_id", sa.String(140), sa.ForeignKey("plotcheck_cases.case_id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("confidence_class", sa.String(1), nullable=False, server_default="D"),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("stop_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("conditions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("preliminary", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assessed_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "revision", name="uq_plotcheck_assessment_revision"),
        sa.CheckConstraint("outcome IN ('FIT','FIT WITH CONDITIONS','RE-DESIGN REQUIRED','NOT SUITABLE')", name="ck_plotcheck_assessment_outcome"),
    )
    indexes = {
        "plotcheck_rule_sets": ("rule_set_id", "municipality", "zoning_code", "lifecycle_status"),
        "plotcheck_cases": ("case_id", "project_id", "parcel_number", "municipality", "zoning_code", "rule_set_id", "status", "geometry_sha256", "house_id", "final_assessment_id", "final_report_document_id"),
        "plotcheck_evidence": ("evidence_id", "case_id", "category", "source_sha256", "verified"),
        "plotcheck_actions": ("action_id", "case_id", "status", "completion_evidence_sha256"),
        "plotcheck_gates": ("case_id", "gate_key", "decision"),
        "plotcheck_assessments": ("assessment_id", "case_id", "outcome", "snapshot_sha256"),
    }
    for table, columns in indexes.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in ("plotcheck_assessments", "plotcheck_gates", "plotcheck_actions", "plotcheck_evidence", "plotcheck_cases", "plotcheck_rule_sets"):
        op.drop_table(table)
