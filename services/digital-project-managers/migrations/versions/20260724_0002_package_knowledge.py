"""Integrate package knowledge base and approval decision evidence.

Revision ID: 20260724_0002
Revises: 20260724_0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260724_0002"
down_revision = "20260724_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "approval_requests",
        sa.Column("decision_rationale", sa.Text(), nullable=True),
    )
    op.add_column(
        "approval_requests",
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "knowledge_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("external_project_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "source_type",
            sa.String(length=64),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "version",
            sa.String(length=64),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column(
            "precedence",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "precedence BETWEEN 0 AND 1000",
            name="ck_knowledge_document_precedence",
        ),
    )
    op.create_index(
        "ix_knowledge_documents_project_precedence",
        "knowledge_documents",
        ["external_project_id", "precedence"],
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_project_id", sa.String(length=128), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "document_id",
            "sequence",
            name="uq_knowledge_chunk_sequence",
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_project",
        "knowledge_chunks",
        ["external_project_id"],
    )
    # Statikus DDL literálok, nincs f-string interpoláció és nincs felhasználói bemenet.
    audit_trigger_ddl = {
        "knowledge_documents": """
            CREATE TRIGGER trg_audit_knowledge_documents
            AFTER INSERT OR UPDATE OR DELETE ON knowledge_documents
            FOR EACH ROW EXECUTE FUNCTION audit_dpm_write()
            """,
        "knowledge_chunks": """
            CREATE TRIGGER trg_audit_knowledge_chunks
            AFTER INSERT OR UPDATE OR DELETE ON knowledge_chunks
            FOR EACH ROW EXECUTE FUNCTION audit_dpm_write()
            """,
    }
    for table_name in ("knowledge_documents", "knowledge_chunks"):
        op.execute(audit_trigger_ddl[table_name])


def downgrade() -> None:
    drop_trigger_ddl = {
        "knowledge_chunks": "DROP TRIGGER IF EXISTS trg_audit_knowledge_chunks ON knowledge_chunks",
        "knowledge_documents": (
            "DROP TRIGGER IF EXISTS trg_audit_knowledge_documents ON knowledge_documents"
        ),
    }
    for table_name in ("knowledge_chunks", "knowledge_documents"):
        op.execute(drop_trigger_ddl[table_name])
    op.drop_index("ix_knowledge_chunks_project", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index(
        "ix_knowledge_documents_project_precedence",
        table_name="knowledge_documents",
    )
    op.drop_table("knowledge_documents")
    op.drop_column("approval_requests", "decided_at")
    op.drop_column("approval_requests", "decision_rationale")
