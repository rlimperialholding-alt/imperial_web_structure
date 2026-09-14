"""Add native Project Control baseline, EAC and recovery governance.

Revision ID: 20260802_0032
Revises: 20260802_0031
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0032"
down_revision = "20260802_0031"
branch_labels = None
depends_on = None


def _indexes(table: str, prefix: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{prefix}_{column}", table, [column])


def upgrade() -> None:
    required = {
        "project_control_baselines",
        "project_control_forecasts",
        "project_control_variances",
        "project_control_recovery_actions",
        "project_control_weekly_reports",
    }
    present = set(sa.inspect(op.get_bind()).get_table_names()) & required
    if present and present != required:
        raise RuntimeError("Partial Project Control schema: " + ", ".join(sorted(present)))
    if present:
        return

    op.create_table(
        "project_control_baselines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("baseline_id", sa.String(140), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("finance_plan_id", sa.String(120), nullable=False),
        sa.Column("scope_document_id", sa.String(160), nullable=False),
        sa.Column("scope_version", sa.String(80), nullable=False),
        sa.Column("scope_sha256", sa.String(64), nullable=False),
        sa.Column("planned_start", sa.Date(), nullable=False),
        sa.Column("planned_end", sa.Date(), nullable=False),
        sa.Column("schedule_snapshot_json", sa.Text(), nullable=False),
        sa.Column("financial_snapshot_json", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("submitted_by", sa.String(255)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("technical_approved_by", sa.String(255)),
        sa.Column("technical_note", sa.Text()),
        sa.Column("technical_approved_at", sa.DateTime(timezone=True)),
        sa.Column("finance_approved_by", sa.String(255)),
        sa.Column("finance_note", sa.Text()),
        sa.Column("finance_approved_at", sa.DateTime(timezone=True)),
        sa.Column("leadership_approved_by", sa.String(255)),
        sa.Column("leadership_note", sa.Text()),
        sa.Column("leadership_approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "version", name="uq_project_control_baseline_version"),
        sa.CheckConstraint("status IN ('draft','review','approved','superseded','rejected')", name="ck_project_control_baseline_status"),
        sa.CheckConstraint("planned_end >= planned_start", name="ck_project_control_baseline_dates"),
    )
    _indexes("project_control_baselines", "project_control_baseline", ("baseline_id", "project_id", "status", "finance_plan_id", "scope_document_id", "scope_sha256", "planned_start", "planned_end", "content_sha256"))

    op.create_table(
        "project_control_forecasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("forecast_id", sa.String(140), nullable=False, unique=True),
        sa.Column("baseline_id", sa.String(140), sa.ForeignKey("project_control_baselines.baseline_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("planned_progress_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("actual_progress_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("schedule_variance_pct", sa.Numeric(7, 2), nullable=False),
        sa.Column("forecast_completion_date", sa.Date(), nullable=False),
        sa.Column("deadline_variance_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revenue_net", sa.Numeric(18, 2), nullable=False),
        sa.Column("budget_cost_net", sa.Numeric(18, 2), nullable=False),
        sa.Column("committed_cost_net", sa.Numeric(18, 2), nullable=False),
        sa.Column("actual_cost_net", sa.Numeric(18, 2), nullable=False),
        sa.Column("estimate_to_complete_net", sa.Numeric(18, 2), nullable=False),
        sa.Column("eac_cost_net", sa.Numeric(18, 2), nullable=False),
        sa.Column("cost_variance_net", sa.Numeric(18, 2), nullable=False),
        sa.Column("forecast_margin_net", sa.Numeric(18, 2), nullable=False),
        sa.Column("forecast_margin_percent", sa.Numeric(7, 2), nullable=False),
        sa.Column("approved_change_revenue_net", sa.Numeric(18, 2), nullable=False),
        sa.Column("approved_change_cost_net", sa.Numeric(18, 2), nullable=False),
        sa.Column("unauthorized_change_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_snapshot_json", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("submitted_by", sa.String(255)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("finance_approved_by", sa.String(255)),
        sa.Column("finance_note", sa.Text()),
        sa.Column("finance_approved_at", sa.DateTime(timezone=True)),
        sa.Column("leadership_approved_by", sa.String(255)),
        sa.Column("leadership_note", sa.Text()),
        sa.Column("leadership_approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("baseline_id", "version", name="uq_project_control_forecast_version"),
        sa.CheckConstraint("status IN ('draft','finance_review','leadership_review','approved','superseded','rejected')", name="ck_project_control_forecast_status"),
        sa.CheckConstraint("planned_progress_pct >= 0 AND planned_progress_pct <= 100 AND actual_progress_pct >= 0 AND actual_progress_pct <= 100", name="ck_project_control_forecast_progress"),
    )
    _indexes("project_control_forecasts", "project_control_forecast", ("forecast_id", "baseline_id", "status", "as_of_date", "forecast_completion_date", "content_sha256"))

    op.create_table(
        "project_control_variances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("variance_id", sa.String(140), nullable=False, unique=True),
        sa.Column("forecast_id", sa.String(140), sa.ForeignKey("project_control_forecasts.forecast_id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("impact_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impact_percent", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("root_cause", sa.String(80)),
        sa.Column("source_module", sa.String(100), nullable=False),
        sa.Column("source_object_id", sa.String(180), nullable=False),
        sa.Column("recovery_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("classified_by", sa.String(255)),
        sa.Column("classified_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.String(255)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("category IN ('schedule','progress','cost','margin','change','scope','quality','risk')", name="ck_project_control_variance_category"),
        sa.CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_project_control_variance_severity"),
        sa.CheckConstraint("status IN ('open','classified','recovery','resolved','accepted')", name="ck_project_control_variance_status"),
    )
    _indexes("project_control_variances", "project_control_variance", ("variance_id", "forecast_id", "category", "severity", "status", "root_cause", "source_object_id", "recovery_required"))

    op.create_table(
        "project_control_recovery_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_id", sa.String(140), nullable=False, unique=True),
        sa.Column("variance_id", sa.String(140), sa.ForeignKey("project_control_variances.variance_id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_amount_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("target_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("completion_note", sa.Text()),
        sa.Column("evidence_url", sa.String(1000)),
        sa.Column("completed_by", sa.String(255)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("verified_by", sa.String(255)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("verification_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('open','in_progress','completed','verified','rejected')", name="ck_project_control_recovery_status"),
    )
    _indexes("project_control_recovery_actions", "project_control_recovery", ("action_id", "variance_id", "owner", "due_at", "status"))

    op.create_table(
        "project_control_weekly_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.String(140), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("forecast_id", sa.String(140), sa.ForeignKey("project_control_forecasts.forecast_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("management_summary", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("submitted_by", sa.String(255)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approval_note", sa.Text()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "week_ending", name="uq_project_control_weekly_report"),
        sa.CheckConstraint("status IN ('draft','submitted','approved','rejected')", name="ck_project_control_weekly_report_status"),
    )
    _indexes("project_control_weekly_reports", "project_control_report", ("report_id", "project_id", "forecast_id", "week_ending", "status", "content_sha256"))


def downgrade() -> None:
    op.drop_table("project_control_weekly_reports")
    op.drop_table("project_control_recovery_actions")
    op.drop_table("project_control_variances")
    op.drop_table("project_control_forecasts")
    op.drop_table("project_control_baselines")
