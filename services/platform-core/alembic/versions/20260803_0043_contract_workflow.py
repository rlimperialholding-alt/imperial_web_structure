"""Add governed contract workflow lifecycle.

Revision ID: 20260803_0043
Revises: 20260803_0042
"""

import sqlalchemy as sa

from alembic import op

revision = "20260803_0043"
down_revision = "20260803_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "contract_workflows" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "contract_workflows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.String(120), nullable=False, unique=True),
        sa.Column("contract_number", sa.String(160), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("opportunity_id", sa.String(120), nullable=False),
        sa.Column("partner_id", sa.String(120), nullable=False),
        sa.Column("contract_type", sa.String(100), nullable=False),
        sa.Column("counterparty_name", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="generated"),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("package_document_id", sa.String(120), nullable=False),
        sa.Column("manifest_document_id", sa.String(120), nullable=False),
        sa.Column("generated_by", sa.String(255), nullable=False),
        sa.Column("submitted_by", sa.String(255)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("commercial_approved_by", sa.String(255)),
        sa.Column("commercial_approved_at", sa.DateTime(timezone=True)),
        sa.Column("commercial_note", sa.Text()),
        sa.Column("technical_approved_by", sa.String(255)),
        sa.Column("technical_approved_at", sa.DateTime(timezone=True)),
        sa.Column("technical_note", sa.Text()),
        sa.Column("legal_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("legal_approved_by", sa.String(255)),
        sa.Column("legal_approved_at", sa.DateTime(timezone=True)),
        sa.Column("legal_note", sa.Text()),
        sa.Column("owner_approved_by", sa.String(255)),
        sa.Column("owner_approved_at", sa.DateTime(timezone=True)),
        sa.Column("owner_note", sa.Text()),
        sa.Column("rejected_by", sa.String(255)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("signed_file_id", sa.String(255)),
        sa.Column("signed_document_sha256", sa.String(64)),
        sa.Column("signed_at", sa.DateTime(timezone=True)),
        sa.Column("signed_recorded_by", sa.String(255)),
        sa.Column("postal_sent_at", sa.DateTime(timezone=True)),
        sa.Column("postal_tracking_number", sa.String(255)),
        sa.Column("postal_proof_file_id", sa.String(255)),
        sa.Column("electronic_sent_at", sa.DateTime(timezone=True)),
        sa.Column("electronic_message_id", sa.String(500)),
        sa.Column("electronic_recipient", sa.String(320)),
        sa.Column("electronic_attachment_sha256", sa.String(64)),
        sa.Column("dispatch_recorded_by", sa.String(255)),
        sa.Column("work_start_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("activated_by", sa.String(255)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('generated','review','approved','signed','dispatched','active','rejected')",
            name="ck_contract_workflow_status",
        ),
    )
    for column in (
        "contract_id",
        "contract_number",
        "project_id",
        "opportunity_id",
        "partner_id",
        "contract_type",
        "counterparty_name",
        "status",
        "payload_sha256",
        "package_document_id",
        "manifest_document_id",
        "signed_file_id",
        "signed_document_sha256",
        "postal_tracking_number",
        "electronic_message_id",
        "work_start_allowed",
    ):
        op.create_index(f"ix_contract_workflows_{column}", "contract_workflows", [column])


def downgrade() -> None:
    op.drop_table("contract_workflows")
