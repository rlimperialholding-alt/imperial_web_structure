"""Add dedicated Imperial Care case management.

Revision ID: 20260802_0022
Revises: 20260801_0021
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0022"
down_revision = "20260801_0021"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: list[str]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    required = {"care_cases", "care_messages", "care_evidence"}
    present = existing & required
    if present == required:
        return
    if present:
        raise RuntimeError(
            "Partial Imperial Care schema detected; refusing unsafe migration: "
            + ", ".join(sorted(present))
        )

    op.create_table(
        "care_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.String(120), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("reporter_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(30), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("preferred_contact", sa.String(120), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="submitted"),
        sa.Column("assigned_to", sa.String(255), nullable=True),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_summary", sa.Text(), nullable=True),
        sa.Column("customer_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_channel", sa.String(50), nullable=False, server_default="imperial-care"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('submitted','triaged','in_progress','waiting_customer','resolved','closed','rejected')",
            name="ck_care_case_status",
        ),
        sa.CheckConstraint(
            "severity IN ('low','medium','high','urgent')",
            name="ck_care_case_severity",
        ),
    )
    _indexes(
        "care_cases",
        ["case_id", "project_id", "customer_email", "category", "severity", "status", "assigned_to", "sla_due_at"],
    )

    op.create_table(
        "care_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.String(120), nullable=False, unique=True),
        sa.Column("case_id_fk", sa.Integer(), sa.ForeignKey("care_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_email", sa.String(255), nullable=False),
        sa.Column("author_role", sa.String(50), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("customer_visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("care_messages", ["message_id", "case_id_fk", "author_email"])

    op.create_table(
        "care_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evidence_id", sa.String(120), nullable=False, unique=True),
        sa.Column("case_id_fk", sa.Integer(), sa.ForeignKey("care_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("care_evidence", ["evidence_id", "case_id_fk", "sha256"])


def downgrade() -> None:
    op.drop_table("care_evidence")
    op.drop_table("care_messages")
    op.drop_table("care_cases")
