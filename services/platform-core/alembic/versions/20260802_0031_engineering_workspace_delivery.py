"""Add native Engineering Workspace delivery governance.

Revision ID: 20260802_0031
Revises: 20260802_0030
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0031"
down_revision = "20260802_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    required = {
        "engineering_cases",
        "engineering_deliverables",
        "engineering_revisions",
        "engineering_findings",
        "engineering_transmittals",
        "engineering_transmittal_items",
    }
    present = existing & required
    if present and present != required:
        raise RuntimeError("Partial Engineering Workspace schema: " + ", ".join(sorted(present)))
    if present:
        return

    op.create_table(
        "engineering_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("engineering_case_id", sa.String(120), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False, unique=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="planned"),
        sa.Column("lead_designer", sa.String(255), nullable=False),
        sa.Column("project_manager", sa.String(255), nullable=False),
        sa.Column("contract_date", sa.Date(), nullable=False),
        sa.Column("consultation_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consultation_completed_at", sa.DateTime(timezone=True)),
        sa.Column("source_authority_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("readiness_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("readiness_blockers_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("construction_ready_by", sa.String(255)),
        sa.Column("construction_ready_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('planned','in_design','coordination','hold','construction_ready','closed')",
            name="ck_engineering_case_status",
        ),
    )
    for column in (
        "engineering_case_id", "project_id", "title", "status", "lead_designer",
        "project_manager", "contract_date", "consultation_due_at", "absolute_deadline",
    ):
        op.create_index(f"ix_engineering_case_{column}", "engineering_cases", [column])

    op.create_table(
        "engineering_deliverables",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deliverable_id", sa.String(140), nullable=False, unique=True),
        sa.Column(
            "engineering_case_id", sa.String(120),
            sa.ForeignKey("engineering_cases.engineering_case_id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("discipline", sa.String(80), nullable=False),
        sa.Column("deliverable_code", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(40), nullable=False, server_default="planned"),
        sa.Column("responsible", sa.String(255), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_released_revision", sa.Integer()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "engineering_case_id", "discipline", "deliverable_code",
            name="uq_engineering_deliverable_case_discipline_code",
        ),
        sa.CheckConstraint(
            "status IN ('planned','drafting','review','released','hold','not_required')",
            name="ck_engineering_deliverable_status",
        ),
    )
    for column in (
        "deliverable_id", "engineering_case_id", "discipline", "deliverable_code",
        "title", "document_type", "required", "status", "responsible", "due_at",
    ):
        op.create_index(f"ix_engineering_deliverable_{column}", "engineering_deliverables", [column])

    op.create_table(
        "engineering_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_id", sa.String(160), nullable=False, unique=True),
        sa.Column(
            "deliverable_id", sa.String(140),
            sa.ForeignKey("engineering_deliverables.deliverable_id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("revision_label", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("source_document_id", sa.String(160), nullable=False),
        sa.Column("source_version", sa.String(80), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("submitted_by", sa.String(255)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", sa.String(255)),
        sa.Column("review_note", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("released_by", sa.String(255)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawn_by", sa.String(255)),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawal_reason", sa.Text()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("deliverable_id", "revision", name="uq_engineering_deliverable_revision"),
        sa.UniqueConstraint("source_document_id", "source_version", name="uq_engineering_source_document_version"),
        sa.CheckConstraint(
            "status IN ('draft','review','rejected','approved','released','superseded','withdrawn')",
            name="ck_engineering_revision_status",
        ),
    )
    for column in ("revision_id", "deliverable_id", "status", "source_document_id", "content_sha256"):
        op.create_index(f"ix_engineering_revision_{column}", "engineering_revisions", [column])

    op.create_table(
        "engineering_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("finding_id", sa.String(140), nullable=False, unique=True),
        sa.Column(
            "revision_id", sa.String(160),
            sa.ForeignKey("engineering_revisions.revision_id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(30), nullable=False),
        sa.Column("blocking", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(40), nullable=False, server_default="open"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(500)),
        sa.Column("responsible", sa.String(255), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_module", sa.String(100), nullable=False, server_default="plancheck"),
        sa.Column("source_fingerprint", sa.String(255), nullable=False, unique=True),
        sa.Column("resolution_note", sa.Text()),
        sa.Column("resolution_revision_id", sa.String(160)),
        sa.Column("resolution_proposed_by", sa.String(255)),
        sa.Column("resolved_by", sa.String(255)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_engineering_finding_severity"),
        sa.CheckConstraint(
            "status IN ('open','resolution_proposed','resolved','superseded')",
            name="ck_engineering_finding_status",
        ),
    )
    for column in (
        "finding_id", "revision_id", "category", "severity", "blocking", "status",
        "responsible", "due_at", "source_fingerprint", "resolution_revision_id",
    ):
        op.create_index(f"ix_engineering_finding_{column}", "engineering_findings", [column])

    op.create_table(
        "engineering_transmittals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transmittal_id", sa.String(140), nullable=False, unique=True),
        sa.Column(
            "engineering_case_id", sa.String(120),
            sa.ForeignKey("engineering_cases.engineering_case_id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("recipient_name", sa.String(255), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="issued"),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("issued_by", sa.String(255), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_by", sa.String(255)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledgement_note", sa.Text()),
        sa.CheckConstraint(
            "purpose IN ('review','information','construction','authority','supersession')",
            name="ck_engineering_transmittal_purpose",
        ),
        sa.CheckConstraint(
            "status IN ('issued','acknowledged','rejected','cancelled')",
            name="ck_engineering_transmittal_status",
        ),
    )
    for column in (
        "transmittal_id", "engineering_case_id", "purpose", "recipient_email",
        "status", "package_sha256",
    ):
        op.create_index(f"ix_engineering_transmittal_{column}", "engineering_transmittals", [column])

    op.create_table(
        "engineering_transmittal_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transmittal_item_id", sa.String(160), nullable=False, unique=True),
        sa.Column(
            "transmittal_id", sa.String(140),
            sa.ForeignKey("engineering_transmittals.transmittal_id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "revision_id", sa.String(160),
            sa.ForeignKey("engineering_revisions.revision_id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("revision_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("transmittal_id", "revision_id", name="uq_engineering_transmittal_revision"),
    )
    for column in ("transmittal_item_id", "transmittal_id", "revision_id"):
        op.create_index(f"ix_engineering_transmittal_item_{column}", "engineering_transmittal_items", [column])


def downgrade() -> None:
    op.drop_table("engineering_transmittal_items")
    op.drop_table("engineering_transmittals")
    op.drop_table("engineering_findings")
    op.drop_table("engineering_revisions")
    op.drop_table("engineering_deliverables")
    op.drop_table("engineering_cases")
