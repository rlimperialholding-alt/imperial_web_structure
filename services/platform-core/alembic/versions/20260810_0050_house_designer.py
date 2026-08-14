"""House Designer canonical aggregates and regulatory evidence.

Revision ID: 20260810_0050
Revises: 20260809_0049
"""

import sqlalchemy as sa

from alembic import op

revision = "20260810_0050"
down_revision = "20260809_0049"
branch_labels = None
depends_on = None


TABLES = (
    "house_designer_entitlements",
    "house_design_sessions",
    "house_design_revisions",
    "house_design_guest_claims",
    "regulatory_source_snapshots",
    "regulatory_rule_interpretations",
    "regulatory_rule_sets",
    "regulatory_compliance_runs",
    "regulatory_compliance_findings",
    "house_design_render_revisions",
    "house_design_estimate_snapshots",
    "house_design_schedule_snapshots",
    "house_design_snapshots",
    "house_design_submissions",
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    present = existing.intersection(TABLES)
    if present == set(TABLES):
        # The consolidated bootstrap migration creates current metadata on a fresh database.
        return
    if present:
        raise RuntimeError(
            "0050 upgrade aborted: partial House Designer schema exists: "
            + ", ".join(sorted(present))
        )
    op.create_table(
        "house_designer_entitlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entitlement_id", sa.String(120), nullable=False),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="sandbox"),
        sa.Column("standalone_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("order_intake_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "production_render_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "production_pricing_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "production_capacity_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("policy_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("entitlement_id", name="uq_hd_entitlement_id"),
        sa.UniqueConstraint("tenant_id", "brand_id", name="uq_hd_entitlement_tenant_brand"),
    )
    op.create_table(
        "house_design_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("owner_subject_id", sa.String(160)),
        sa.Column("project_id", sa.String(120)),
        sa.Column("origin", sa.String(30), nullable=False, server_default="blank"),
        sa.Column("template_plan_id", sa.String(120)),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("current_revision_id", sa.String(120)),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("locale", sa.String(20), nullable=False, server_default="hu-HU"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", name="uq_hd_session_id"),
        sa.CheckConstraint(
            "status IN ('DRAFT','CHECK_REQUIRED','CHECKED','ESTIMATED','CUSTOMER_APPROVED',"
            "'SUBMITTED','STALE','ARCHIVED','CANCELLED')",
            name="ck_hd_session_status",
        ),
    )
    op.create_table(
        "house_design_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_id", sa.String(120), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("predecessor_revision_id", sa.String(120)),
        sa.Column("command_id", sa.String(120), nullable=False),
        sa.Column("command_type", sa.String(80), nullable=False),
        sa.Column("command_sha256", sa.String(64), nullable=False),
        sa.Column("geometry_json", sa.Text(), nullable=False),
        sa.Column("configuration_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("site_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("canonical_sha256", sa.String(64), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "schema_version", sa.String(40), nullable=False, server_default="house-design-v1"
        ),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["house_design_sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("revision_id", name="uq_hd_revision_id"),
        sa.UniqueConstraint("session_id", "revision_no", name="uq_hd_revision_session_no"),
        sa.UniqueConstraint("session_id", "command_id", name="uq_hd_revision_command"),
    )
    op.create_table(
        "house_design_guest_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.String(120), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by_subject_id", sa.String(160)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["house_design_sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("claim_id", name="uq_hd_claim_id"),
        sa.UniqueConstraint("token_hash", name="uq_hd_claim_token_hash"),
    )
    op.create_table(
        "regulatory_source_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_snapshot_id", sa.String(120), nullable=False),
        sa.Column("source_key", sa.String(180), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("jurisdiction", sa.String(160), nullable=False),
        sa.Column("scope_key", sa.String(255), nullable=False),
        sa.Column("source_url", sa.String(1200), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_text_sha256", sa.String(64), nullable=False),
        sa.Column("storage_ref", sa.String(1200), nullable=False),
        sa.Column("parser_version", sa.String(120), nullable=False),
        sa.Column("security_status", sa.String(30), nullable=False, server_default="approved"),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("supersedes_snapshot_id", sa.String(120)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_snapshot_id", name="uq_reg_source_snapshot_id"),
        sa.UniqueConstraint("source_key", "revision", name="uq_reg_source_key_revision"),
    )
    op.create_table(
        "regulatory_rule_interpretations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("interpretation_id", sa.String(120), nullable=False),
        sa.Column("source_snapshot_id", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_spans_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("interpreted_rules_json", sa.Text(), nullable=False),
        sa.Column("test_vectors_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("interpreter_version", sa.String(120), nullable=False),
        sa.Column("canonical_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("authored_by", sa.String(255), nullable=False),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("interpretation_id", name="uq_reg_interpretation_id"),
        sa.UniqueConstraint(
            "source_snapshot_id",
            "revision",
            name="uq_reg_interpretation_source_revision",
        ),
    )
    op.create_table(
        "regulatory_rule_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ruleset_id", sa.String(120), nullable=False),
        sa.Column("family_key", sa.String(255), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("jurisdiction", sa.String(160), nullable=False),
        sa.Column("scope_key", sa.String(255), nullable=False),
        sa.Column("national_basis", sa.String(50), nullable=False),
        sa.Column("local_plan_basis", sa.String(255), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("source_snapshot_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("interpreter_version", sa.String(120), nullable=False),
        sa.Column("rules_json", sa.Text(), nullable=False),
        sa.Column("canonical_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("authored_by", sa.String(255), nullable=False),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("supersedes_ruleset_id", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ruleset_id", name="uq_reg_ruleset_id"),
        sa.UniqueConstraint("family_key", "revision", name="uq_reg_ruleset_family_revision"),
    )
    op.create_table(
        "regulatory_compliance_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(120), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("revision_id", sa.String(120), nullable=False),
        sa.Column("ruleset_id", sa.String(120)),
        sa.Column("ruleset_sha256", sa.String(64)),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("blocker_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engine_version", sa.String(120), nullable=False),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_reg_run_id"),
        sa.UniqueConstraint("revision_id", "ruleset_id", "input_sha256", name="uq_reg_run_input"),
    )
    op.create_table(
        "regulatory_compliance_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("finding_id", sa.String(120), nullable=False),
        sa.Column("run_id", sa.String(120), nullable=False),
        sa.Column("finding_key", sa.String(180), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("rule_ref", sa.String(500), nullable=False),
        sa.Column("source_ref", sa.String(1200), nullable=False),
        sa.Column("geometry_path", sa.String(1000)),
        sa.Column("measured_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("limit_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("remediation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["regulatory_compliance_runs.run_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("finding_id", name="uq_reg_finding_id"),
        sa.UniqueConstraint("run_id", "finding_key", name="uq_reg_finding_run_key"),
    )
    op.create_table(
        "house_design_render_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("render_id", sa.String(120), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("design_revision_id", sa.String(120), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("parent_render_id", sa.String(120)),
        sa.Column("geometry_lock_sha256", sa.String(64), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("provider_job_id", sa.String(255)),
        sa.Column("asset_ref", sa.String(1200)),
        sa.Column("asset_sha256", sa.String(64)),
        sa.Column("qa_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("non_production", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("accepted_by", sa.String(255)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("render_id", name="uq_hd_render_id"),
        sa.UniqueConstraint("session_id", "revision_no", name="uq_hd_render_session_revision"),
        sa.UniqueConstraint("provider_job_id", name="uq_hd_render_provider_job"),
    )
    op.create_table(
        "house_design_estimate_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("estimate_id", sa.String(120), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("design_revision_id", sa.String(120), nullable=False),
        sa.Column("buildconfig_case_id", sa.String(120)),
        sa.Column("buildconfig_revision_id", sa.String(120)),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("net_min_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_max_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("vat_rate", sa.Numeric(8, 4), nullable=False),
        sa.Column("gross_min_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("gross_max_huf", sa.Numeric(18, 2), nullable=False),
        sa.Column("line_items_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("assumptions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("exclusions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("non_production", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canonical_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("estimate_id", name="uq_hd_estimate_id"),
    )
    op.create_table(
        "house_design_schedule_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schedule_id", sa.String(120), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("design_revision_id", sa.String(120), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("earliest_start", sa.Date()),
        sa.Column("latest_start", sa.Date()),
        sa.Column("duration_min_workdays", sa.Integer(), nullable=False),
        sa.Column("duration_max_workdays", sa.Integer(), nullable=False),
        sa.Column("phases_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("assumptions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("capacity_snapshot_id", sa.String(120)),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("non_production", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canonical_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("schedule_id", name="uq_hd_schedule_id"),
    )
    op.create_table(
        "house_design_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.String(120), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("design_revision_id", sa.String(120), nullable=False),
        sa.Column("compliance_run_id", sa.String(120), nullable=False),
        sa.Column("estimate_id", sa.String(120), nullable=False),
        sa.Column("schedule_id", sa.String(120), nullable=False),
        sa.Column("selected_render_id", sa.String(120), nullable=False),
        sa.Column("terms_version_id", sa.String(120), nullable=False),
        sa.Column("consent_version_id", sa.String(120), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("approved_by_subject_id", sa.String(160), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", name="uq_hd_snapshot_id"),
        sa.UniqueConstraint("manifest_sha256", name="uq_hd_snapshot_manifest_hash"),
    )
    op.create_table(
        "house_design_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("submission_id", sa.String(120), nullable=False),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("snapshot_id", sa.String(120), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("submission_type", sa.String(30), nullable=False, server_default="ORDER_REQUEST"),
        sa.Column("status", sa.String(40), nullable=False, server_default="RECEIVED"),
        sa.Column("customer_subject_id", sa.String(160), nullable=False),
        sa.Column("lead_id", sa.String(120)),
        sa.Column("opportunity_id", sa.String(120)),
        sa.Column("project_id", sa.String(120)),
        sa.Column("booking_id", sa.String(120)),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("attribution_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("notice_version_id", sa.String(120), nullable=False),
        sa.Column("notice_accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("submission_id", name="uq_hd_submission_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_hd_submission_idempotency"),
    )

    indexed = {
        "house_design_sessions": (
            "tenant_id",
            "brand_id",
            "owner_subject_id",
            "project_id",
            "status",
        ),
        "house_design_revisions": ("session_id", "canonical_sha256"),
        "house_design_guest_claims": ("session_id", "expires_at", "status"),
        "regulatory_source_snapshots": ("source_key", "jurisdiction", "scope_key", "status"),
        "regulatory_rule_interpretations": (
            "source_snapshot_id",
            "canonical_sha256",
            "status",
        ),
        "regulatory_rule_sets": ("family_key", "jurisdiction", "scope_key", "status"),
        "regulatory_compliance_runs": ("session_id", "revision_id", "outcome"),
        "regulatory_compliance_findings": ("run_id", "code", "severity"),
        "house_design_render_revisions": ("session_id", "design_revision_id", "status"),
        "house_design_estimate_snapshots": ("session_id", "design_revision_id", "valid_until"),
        "house_design_schedule_snapshots": ("session_id", "design_revision_id", "valid_until"),
        "house_design_snapshots": ("session_id", "design_revision_id"),
        "house_design_submissions": ("tenant_id", "brand_id", "session_id", "status"),
    }
    for table, columns in indexed.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    populated: list[str] = []
    for table in TABLES:
        if table in existing and bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar():
            populated.append(table)
    if populated:
        raise RuntimeError(
            "0050 downgrade aborted: House Designer business data exists in "
            + ", ".join(populated)
            + ". Export/archive it under the approved rollback runbook before schema removal."
        )
    for table in reversed(TABLES):
        if table in existing:
            op.drop_table(table)
