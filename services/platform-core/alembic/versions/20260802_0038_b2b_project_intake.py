"""Add native governed B2B project intake.

Revision ID: 20260802_0038
Revises: 20260802_0037
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0038"
down_revision = "20260802_0037"
branch_labels = None
depends_on = None

TABLES = {"b2b_project_intakes", "b2b_duplicate_matches", "b2b_technical_reviews", "b2b_financial_reviews", "b2b_qualification_decisions", "b2b_crm_deliveries"}


def _ix(table: str, *columns: str) -> None:
    for column in columns: op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names()); present = existing & TABLES
    if present and present != TABLES: raise RuntimeError("Partial B2B Project Intake schema: " + ", ".join(sorted(present)))
    if present == TABLES: return
    op.create_table("b2b_project_intakes",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("intake_id", sa.String(120), nullable=False, unique=True), sa.Column("source_system", sa.String(100), nullable=False), sa.Column("source_external_id", sa.String(255), nullable=False), sa.Column("source_reference", sa.String(1200), nullable=False), sa.Column("source_content_sha256", sa.String(64), nullable=False), sa.Column("lawful_basis", sa.String(120), nullable=False), sa.Column("source_use_approved", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("linked_marketing_lead_id", sa.String(120)),
        sa.Column("organization_name", sa.String(500), nullable=False), sa.Column("organization_name_normalized", sa.String(500), nullable=False), sa.Column("tax_number", sa.String(80)), sa.Column("website_domain", sa.String(255)), sa.Column("contact_name", sa.String(255), nullable=False), sa.Column("contact_email", sa.String(255)), sa.Column("contact_phone", sa.String(80)),
        sa.Column("project_type", sa.String(80), nullable=False), sa.Column("country", sa.String(100), nullable=False, server_default="HU"), sa.Column("city", sa.String(255), nullable=False), sa.Column("site_address", sa.String(500)), sa.Column("gross_floor_area_m2", sa.Numeric(18,2), nullable=False, server_default="0"), sa.Column("planned_start", sa.Date()), sa.Column("requested_deadline", sa.Date()), sa.Column("estimated_budget_huf", sa.Numeric(18,2), nullable=False, server_default="0"), sa.Column("project_summary", sa.Text(), nullable=False), sa.Column("document_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("company_fingerprint", sa.String(64), nullable=False), sa.Column("project_fingerprint", sa.String(64), nullable=False), sa.Column("missing_fields_json", sa.Text(), nullable=False, server_default="[]"), sa.Column("base_score", sa.Integer(), nullable=False, server_default="0"), sa.Column("score_reasons_json", sa.Text(), nullable=False, server_default="[]"), sa.Column("complexity", sa.String(30), nullable=False, server_default="medium"), sa.Column("strategic_review_required", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("status", sa.String(40), nullable=False, server_default="captured"), sa.Column("signal_count", sa.Integer(), nullable=False, server_default="1"), sa.Column("assigned_sales_email", sa.String(255)), sa.Column("canonical_record_id", sa.String(120)), sa.Column("crm_record_id", sa.String(120)), sa.Column("created_by", sa.String(255), nullable=False), sa.Column("updated_by", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("source_system", "source_external_id", name="uq_b2b_intake_source_key"))
    _ix("b2b_project_intakes", "intake_id", "source_system", "source_content_sha256", "source_use_approved", "linked_marketing_lead_id", "organization_name", "organization_name_normalized", "tax_number", "website_domain", "contact_email", "contact_phone", "project_type", "city", "planned_start", "requested_deadline", "company_fingerprint", "project_fingerprint", "base_score", "complexity", "strategic_review_required", "status", "assigned_sales_email", "canonical_record_id", "crm_record_id")
    op.create_table("b2b_duplicate_matches", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("match_id", sa.String(120), nullable=False, unique=True), sa.Column("intake_id", sa.String(120), nullable=False), sa.Column("candidate_intake_id", sa.String(120), nullable=False), sa.Column("match_scope", sa.String(40), nullable=False), sa.Column("match_score", sa.Integer(), nullable=False), sa.Column("reasons_json", sa.Text(), nullable=False, server_default="[]"), sa.Column("status", sa.String(30), nullable=False, server_default="pending"), sa.Column("reviewed_by", sa.String(255)), sa.Column("review_note", sa.Text()), sa.Column("reviewed_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("intake_id", "candidate_intake_id", "match_scope", name="uq_b2b_duplicate_pair_scope"))
    _ix("b2b_duplicate_matches", "match_id", "intake_id", "candidate_intake_id", "match_scope", "match_score", "status")
    op.create_table("b2b_technical_reviews", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("review_id", sa.String(120), nullable=False, unique=True), sa.Column("intake_id", sa.String(120), nullable=False), sa.Column("decision", sa.String(30), nullable=False), sa.Column("delivery_model", sa.String(80), nullable=False), sa.Column("capacity_fit", sa.String(30), nullable=False), sa.Column("site_feasibility", sa.String(30), nullable=False), sa.Column("complexity", sa.String(30), nullable=False), sa.Column("assumptions_json", sa.Text(), nullable=False, server_default="[]"), sa.Column("note", sa.Text(), nullable=False), sa.Column("reviewer", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    _ix("b2b_technical_reviews", "review_id", "intake_id", "decision", "reviewer")
    op.create_table("b2b_financial_reviews", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("review_id", sa.String(120), nullable=False, unique=True), sa.Column("intake_id", sa.String(120), nullable=False), sa.Column("decision", sa.String(30), nullable=False), sa.Column("budget_credibility", sa.String(30), nullable=False), sa.Column("funding_status", sa.String(40), nullable=False), sa.Column("preliminary_margin_band", sa.String(40), nullable=False), sa.Column("assumptions_json", sa.Text(), nullable=False, server_default="[]"), sa.Column("note", sa.Text(), nullable=False), sa.Column("reviewer", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    _ix("b2b_financial_reviews", "review_id", "intake_id", "decision", "reviewer")
    op.create_table("b2b_qualification_decisions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("decision_id", sa.String(120), nullable=False, unique=True), sa.Column("intake_id", sa.String(120), nullable=False), sa.Column("decision_type", sa.String(40), nullable=False), sa.Column("decision", sa.String(30), nullable=False), sa.Column("route", sa.String(80), nullable=False), sa.Column("next_action", sa.Text(), nullable=False), sa.Column("note", sa.Text(), nullable=False), sa.Column("decided_by", sa.String(255), nullable=False), sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("intake_id", "decision_type", name="uq_b2b_decision_type"))
    _ix("b2b_qualification_decisions", "decision_id", "intake_id", "decision_type", "decision", "decided_by")
    op.create_table("b2b_crm_deliveries", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("delivery_id", sa.String(120), nullable=False, unique=True), sa.Column("intake_id", sa.String(120), nullable=False, unique=True), sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True), sa.Column("payload_sha256", sa.String(64), nullable=False), sa.Column("status", sa.String(30), nullable=False, server_default="pending"), sa.Column("external_crm_id", sa.String(255)), sa.Column("failure_reason", sa.Text()), sa.Column("queued_by", sa.String(255), nullable=False), sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False), sa.Column("receipt_at", sa.DateTime(timezone=True)))
    _ix("b2b_crm_deliveries", "delivery_id", "intake_id", "idempotency_key", "payload_sha256", "status", "external_crm_id")


def downgrade() -> None:
    for table in ("b2b_crm_deliveries", "b2b_qualification_decisions", "b2b_financial_reviews", "b2b_technical_reviews", "b2b_duplicate_matches", "b2b_project_intakes"): op.drop_table(table)
