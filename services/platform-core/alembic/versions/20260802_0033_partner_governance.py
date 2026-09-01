"""Add native Partner Connect and Partner Control governance.

Revision ID: 20260802_0033
Revises: 20260802_0032
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0033"
down_revision = "20260802_0032"
branch_labels = None
depends_on = None


TABLES = {
    "partner_profiles",
    "partner_certificates",
    "partner_capacity_declarations",
    "tender_line_items",
    "tender_bid_versions",
    "tender_bid_version_items",
    "tender_clarification_requests",
    "partner_project_evaluations",
    "partner_incidents",
    "partner_decisions",
    "tender_purchase_order_preparations",
}


def _ix(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    present = existing & TABLES
    if present and present != TABLES:
        raise RuntimeError("Partial Partner governance schema: " + ", ".join(sorted(present)))
    if present == TABLES:
        package_columns = {column["name"] for column in inspector.get_columns("tender_packages")}
        invitation_columns = {column["name"] for column in inspector.get_columns("tender_invitations")}
        missing_columns = {
            "tender_packages": {"prequalification_required", "certificate_gate_enabled", "required_certificate_types_json"} - package_columns,
            "tender_invitations": {"partner_id"} - invitation_columns,
        }
        missing_columns = {table: columns for table, columns in missing_columns.items() if columns}
        if missing_columns:
            raise RuntimeError("Partner governance tables exist with missing legacy columns: " + repr(missing_columns))
        return

    package_columns = {column["name"] for column in inspector.get_columns("tender_packages")}
    if "prequalification_required" not in package_columns:
        op.add_column("tender_packages", sa.Column("prequalification_required", sa.Boolean(), nullable=False, server_default=sa.true()))
        op.add_column("tender_packages", sa.Column("certificate_gate_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.add_column("tender_packages", sa.Column("required_certificate_types_json", sa.Text(), nullable=False, server_default='["liability_insurance","tax_clearance"]'))
    invitation_columns = {column["name"] for column in inspector.get_columns("tender_invitations")}
    if "partner_id" not in invitation_columns:
        op.add_column("tender_invitations", sa.Column("partner_id", sa.String(120)))
        op.create_index("ix_tender_invitations_partner_id", "tender_invitations", ["partner_id"])

    op.create_table(
        "partner_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("partner_id", sa.String(120), nullable=False, unique=True),
        sa.Column("company_name", sa.String(500), nullable=False),
        sa.Column("tax_number", sa.String(80), unique=True),
        sa.Column("primary_email", sa.String(320), nullable=False, unique=True),
        sa.Column("trade_categories_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("territories_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("external_score", sa.Numeric(6, 2)),
        sa.Column("internal_score", sa.Numeric(6, 2)),
        sa.Column("combined_score", sa.Numeric(6, 2)),
        sa.Column("external_evidence_ref", sa.String(1000)),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("current_decision_id", sa.String(120)),
        sa.Column("next_review_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending','approved','conditional','suspended','excluded','reinstatement_review')", name="ck_partner_profile_status"),
    )
    _ix("partner_profiles", "partner_id", "company_name", "tax_number", "primary_email", "status", "current_decision_id", "next_review_at")

    op.create_table(
        "partner_certificates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("certificate_id", sa.String(120), nullable=False, unique=True),
        sa.Column("partner_id", sa.String(120), nullable=False),
        sa.Column("certificate_type", sa.String(60), nullable=False),
        sa.Column("issuer", sa.String(500), nullable=False),
        sa.Column("reference_number", sa.String(255)),
        sa.Column("valid_from", sa.Date()), sa.Column("valid_until", sa.Date()),
        sa.Column("document_ref", sa.String(1000), nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("verification_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("verified_by", sa.String(255)), sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text()), sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("partner_id", "certificate_type", "document_sha256", name="uq_partner_certificate_document"),
    )
    _ix("partner_certificates", "certificate_id", "partner_id", "certificate_type", "valid_until", "document_sha256", "verification_status")

    op.create_table(
        "partner_capacity_declarations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("declaration_id", sa.String(120), nullable=False, unique=True),
        sa.Column("partner_id", sa.String(120), nullable=False), sa.Column("trade_category", sa.String(120), nullable=False),
        sa.Column("territory", sa.String(255), nullable=False), sa.Column("available_from", sa.Date(), nullable=False),
        sa.Column("available_until", sa.Date(), nullable=False), sa.Column("crew_count", sa.Integer(), nullable=False),
        sa.Column("monthly_capacity", sa.Numeric(18, 2), nullable=False), sa.Column("committed_capacity", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="submitted"), sa.Column("evidence_ref", sa.String(1000)),
        sa.Column("declared_by", sa.String(255), nullable=False), sa.Column("reviewed_by", sa.String(255)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)), sa.Column("review_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("partner_capacity_declarations", "declaration_id", "partner_id", "trade_category", "territory", "available_from", "available_until", "status")

    op.create_table(
        "tender_line_items",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("line_item_id", sa.String(120), nullable=False, unique=True),
        sa.Column("tender_id_fk", sa.Integer(), sa.ForeignKey("tender_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False), sa.Column("line_code", sa.String(100), nullable=False),
        sa.Column("category", sa.String(120), nullable=False), sa.Column("name", sa.String(1000), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False), sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("tender_id_fk", "line_code", name="uq_tender_line_code"),
    )
    _ix("tender_line_items", "line_item_id", "tender_id_fk", "category")

    op.create_table(
        "tender_bid_versions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("bid_version_id", sa.String(120), nullable=False, unique=True),
        sa.Column("bid_id_fk", sa.Integer(), sa.ForeignKey("tender_bids.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("lifecycle_status", sa.String(30), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False), sa.Column("net_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("vat_total", sa.Numeric(18, 2), nullable=False), sa.Column("gross_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("summary", sa.Text()), sa.Column("exclusions", sa.Text()),
        sa.Column("normalization_status", sa.String(30), nullable=False), sa.Column("normalization_issues_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("content_sha256", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("bid_id_fk", "version", name="uq_tender_bid_version"),
    )
    _ix("tender_bid_versions", "bid_version_id", "bid_id_fk", "lifecycle_status", "normalization_status", "content_sha256")
    op.create_table(
        "tender_bid_version_items",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("version_item_id", sa.String(120), nullable=False, unique=True),
        sa.Column("bid_version_id_fk", sa.Integer(), sa.ForeignKey("tender_bid_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False), sa.Column("tender_line_item_id", sa.String(120)),
        sa.Column("description", sa.String(1000), nullable=False), sa.Column("source_unit", sa.String(40), nullable=False),
        sa.Column("normalized_unit", sa.String(40), nullable=False), sa.Column("source_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("normalized_quantity", sa.Numeric(18, 4), nullable=False), sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_total", sa.Numeric(18, 2), nullable=False), sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_reason", sa.Text()), sa.UniqueConstraint("bid_version_id_fk", "line_no", name="uq_tender_bid_version_line"),
    )
    _ix("tender_bid_version_items", "version_item_id", "bid_version_id_fk", "tender_line_item_id")

    op.create_table(
        "tender_clarification_requests",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("request_id", sa.String(120), nullable=False, unique=True),
        sa.Column("tender_id_fk", sa.Integer(), sa.ForeignKey("tender_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bid_id_fk", sa.Integer(), sa.ForeignKey("tender_bids.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False), sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"), sa.Column("response", sa.Text()),
        sa.Column("responded_at", sa.DateTime(timezone=True)), sa.Column("acceptance_note", sa.Text()),
        sa.Column("created_by", sa.String(255), nullable=False), sa.Column("accepted_by", sa.String(255)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("tender_clarification_requests", "request_id", "tender_id_fk", "bid_id_fk", "due_at", "status")

    op.create_table(
        "partner_project_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("evaluation_id", sa.String(120), nullable=False, unique=True),
        sa.Column("partner_id", sa.String(120), nullable=False), sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=False), sa.Column("deadline_score", sa.Integer(), nullable=False),
        sa.Column("documentation_score", sa.Integer(), nullable=False), sa.Column("hse_score", sa.Integer(), nullable=False),
        sa.Column("commercial_score", sa.Integer(), nullable=False), sa.Column("score_100", sa.Numeric(6, 2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False), sa.Column("evaluator_email", sa.String(320), nullable=False),
        sa.Column("approved_by", sa.String(255)), sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("partner_id", "project_id", "evaluator_email", name="uq_partner_project_evaluator"),
    )
    _ix("partner_project_evaluations", "evaluation_id", "partner_id", "project_id", "evaluator_email")

    op.create_table(
        "partner_incidents",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("incident_id", sa.String(120), nullable=False, unique=True),
        sa.Column("partner_id", sa.String(120), nullable=False), sa.Column("project_id", sa.String(100)), sa.Column("contract_id", sa.String(120)),
        sa.Column("incident_type", sa.String(40), nullable=False), sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("facts", sa.Text(), nullable=False), sa.Column("requirement_breached", sa.Text(), nullable=False),
        sa.Column("immediate_risk", sa.Text(), nullable=False), sa.Column("evidence_refs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("recurring", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("immediate_suspension", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("partner_statement", sa.Text()), sa.Column("response_due_at", sa.DateTime(timezone=True)),
        sa.Column("corrective_action", sa.Text()), sa.Column("corrective_owner", sa.String(255)), sa.Column("corrective_due_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"), sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("closed_by", sa.String(255)), sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("partner_incidents", "incident_id", "partner_id", "project_id", "contract_id", "incident_type", "severity", "status")

    op.create_table(
        "partner_decisions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("decision_id", sa.String(120), nullable=False, unique=True),
        sa.Column("partner_id", sa.String(120), nullable=False), sa.Column("decision_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"), sa.Column("basis_json", sa.Text(), nullable=False),
        sa.Column("conditions_json", sa.Text(), nullable=False, server_default="{}"), sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True)), sa.Column("review_at", sa.DateTime(timezone=True)),
        sa.Column("proposed_by", sa.String(255), nullable=False), sa.Column("pm_reviewed_by", sa.String(255)),
        sa.Column("finance_legal_reviewed_by", sa.String(255)), sa.Column("approved_by", sa.String(255)), sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("notification_evidence_ref", sa.String(1000)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("partner_decisions", "decision_id", "partner_id", "decision_type", "status", "review_at")

    op.create_table(
        "tender_purchase_order_preparations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("preparation_id", sa.String(120), nullable=False, unique=True),
        sa.Column("tender_id", sa.String(120), nullable=False, unique=True), sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("partner_id", sa.String(120), nullable=False), sa.Column("bid_id", sa.String(120), nullable=False, unique=True),
        sa.Column("bid_version_id", sa.String(120), nullable=False), sa.Column("line_snapshot_json", sa.Text(), nullable=False),
        sa.Column("exclusions", sa.Text()), sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("eligibility_snapshot_json", sa.Text(), nullable=False), sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("prepared_by", sa.String(255), nullable=False), sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _ix("tender_purchase_order_preparations", "preparation_id", "tender_id", "project_id", "partner_id", "bid_id", "bid_version_id", "status", "content_sha256")


def downgrade() -> None:
    for table in [
        "tender_purchase_order_preparations", "partner_decisions", "partner_incidents",
        "partner_project_evaluations", "tender_clarification_requests", "tender_bid_version_items",
        "tender_bid_versions", "tender_line_items", "partner_capacity_declarations",
        "partner_certificates", "partner_profiles",
    ]:
        op.drop_table(table)
    op.drop_index("ix_tender_invitations_partner_id", table_name="tender_invitations")
    op.drop_column("tender_invitations", "partner_id")
    op.drop_column("tender_packages", "required_certificate_types_json")
    op.drop_column("tender_packages", "certificate_gate_enabled")
    op.drop_column("tender_packages", "prequalification_required")
