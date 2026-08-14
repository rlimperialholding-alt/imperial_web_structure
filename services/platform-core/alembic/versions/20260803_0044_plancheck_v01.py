"""Add canonical PlanCheck v0.1 workflow.

Revision ID: 20260803_0044
Revises: 20260803_0043
"""

import sqlalchemy as sa

from alembic import op

revision = "20260803_0044"
down_revision = "20260803_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "plancheck_cases" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "plancheck_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.String(120), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=False),
        sa.Column("contact_email", sa.String(320), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="intake"),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_revision_id", sa.String(140), nullable=False),
        sa.Column("upload_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("upload_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("final_report_document_id", sa.String(120)),
        sa.Column("finalized_by", sa.String(255)),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('intake','review','sendable','not_sendable')",
            name="ck_plancheck_case_status",
        ),
    )
    op.create_table(
        "plancheck_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_id", sa.String(140), nullable=False, unique=True),
        sa.Column(
            "case_id",
            sa.String(120),
            sa.ForeignKey("plancheck_cases.case_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("confidence_class", sa.String(1), nullable=False, server_default="D"),
        sa.Column("missing_items_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("final_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "version", name="uq_plancheck_revision_case_version"),
        sa.CheckConstraint("confidence_class IN ('A','B','C','D')", name="ck_plancheck_confidence"),
    )
    op.create_table(
        "plancheck_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.String(140), nullable=False, unique=True),
        sa.Column(
            "revision_id",
            sa.String(140),
            sa.ForeignKey("plancheck_revisions.revision_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(160), nullable=False),
        sa.Column("extension", sa.String(20), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("page_count", sa.Integer()),
        sa.Column("extracted_text", sa.Text()),
        sa.Column("validation_status", sa.String(30), nullable=False, server_default="verified"),
        sa.Column("uploaded_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("revision_id", "document_id", name="uq_plancheck_revision_document"),
        sa.CheckConstraint(
            "validation_status IN ('verified','rejected')", name="ck_plancheck_document_validation"
        ),
    )
    op.create_table(
        "plancheck_assumptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assumption_id", sa.String(140), nullable=False, unique=True),
        sa.Column(
            "revision_id",
            sa.String(140),
            sa.ForeignKey("plancheck_revisions.revision_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("impact", sa.String(20), nullable=False),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text()),
        sa.Column("resolved_by", sa.String(255)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "impact IN ('low','medium','high')", name="ck_plancheck_assumption_impact"
        ),
        sa.CheckConstraint("status IN ('open','resolved')", name="ck_plancheck_assumption_status"),
    )
    op.create_table(
        "plancheck_gates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "revision_id",
            sa.String(140),
            sa.ForeignKey("plancheck_revisions.revision_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gate_key", sa.String(40), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text()),
        sa.Column("decided_by", sa.String(255)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("revision_id", "gate_key", name="uq_plancheck_gate_revision_key"),
        sa.CheckConstraint(
            "gate_key IN ('input','engineering','commercial','finance','executive')",
            name="ck_plancheck_gate_key",
        ),
        sa.CheckConstraint(
            "decision IN ('pending','approved','rejected')", name="ck_plancheck_gate_decision"
        ),
    )
    for table, columns in {
        "plancheck_cases": (
            "case_id",
            "project_id",
            "contact_email",
            "status",
            "current_revision_id",
            "upload_token_hash",
            "final_report_document_id",
        ),
        "plancheck_revisions": ("revision_id", "case_id", "snapshot_sha256", "confidence_class"),
        "plancheck_documents": ("document_id", "revision_id", "category", "content_sha256"),
        "plancheck_assumptions": ("assumption_id", "revision_id", "impact", "status"),
        "plancheck_gates": ("revision_id", "gate_key", "decision"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in (
        "plancheck_gates",
        "plancheck_assumptions",
        "plancheck_documents",
        "plancheck_revisions",
        "plancheck_cases",
    ):
        op.drop_table(table)
