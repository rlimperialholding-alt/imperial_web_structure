"""Add governed, source-cited Answer Center lifecycle.

Revision ID: 20260802_0037
Revises: 20260802_0036
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0037"
down_revision = "20260802_0036"
branch_labels = None
depends_on = None

TABLES = {
    "answer_knowledge_sources", "answer_knowledge_excerpts", "answer_questions",
    "answer_versions", "answer_citations", "answer_reviews", "answer_publications",
}


def _ix(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    present = existing & TABLES
    if present and present != TABLES:
        raise RuntimeError("Partial Answer Center schema: " + ", ".join(sorted(present)))
    if present == TABLES:
        return
    op.create_table(
        "answer_knowledge_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(120), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source_type", sa.String(60), nullable=False),
        sa.Column("canonical_ref", sa.String(1200), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("domain", sa.String(60), nullable=False),
        sa.Column("visibility", sa.String(40), nullable=False, server_default="internal"),
        sa.Column("allowed_roles_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("project_id", sa.String(100)),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("owner_role", sa.String(60), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", sa.String(255)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revocation_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("canonical_ref", "version", name="uq_answer_source_ref_version"),
    )
    _ix("answer_knowledge_sources", "source_id", "title", "source_type", "canonical_ref", "domain", "visibility", "project_id", "content_sha256", "status", "valid_from", "valid_until", "owner_role")
    op.create_table(
        "answer_knowledge_excerpts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("excerpt_id", sa.String(120), nullable=False, unique=True),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("locator", sa.String(500), nullable=False),
        sa.Column("excerpt_text", sa.Text(), nullable=False),
        sa.Column("excerpt_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "locator", "excerpt_sha256", name="uq_answer_excerpt_source_locator_hash"),
    )
    _ix("answer_knowledge_excerpts", "excerpt_id", "source_id", "excerpt_sha256")
    op.create_table(
        "answer_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.String(120), nullable=False, unique=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(60), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False, server_default="internal"),
        sa.Column("project_id", sa.String(100)),
        sa.Column("customer_reference", sa.String(255)),
        sa.Column("asked_by", sa.String(255), nullable=False),
        sa.Column("asker_role", sa.String(60), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="open"),
        sa.Column("assigned_role", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    _ix("answer_questions", "question_id", "domain", "channel", "project_id", "customer_reference", "asked_by", "asker_role", "status", "assigned_role")
    op.create_table(
        "answer_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("answer_version_id", sa.String(120), nullable=False, unique=True),
        sa.Column("question_id", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("answer_sha256", sa.String(64), nullable=False),
        sa.Column("certainty", sa.String(30), nullable=False),
        sa.Column("source_conflict", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("question_id", "version", name="uq_answer_question_version"),
    )
    _ix("answer_versions", "answer_version_id", "question_id", "answer_sha256", "certainty", "source_conflict", "status")
    op.create_table(
        "answer_citations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("citation_id", sa.String(120), nullable=False, unique=True),
        sa.Column("answer_version_id", sa.String(120), nullable=False),
        sa.Column("claim_key", sa.String(160), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("source_version", sa.String(100), nullable=False),
        sa.Column("source_content_sha256", sa.String(64), nullable=False),
        sa.Column("excerpt_id", sa.String(120), nullable=False),
        sa.Column("excerpt_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("answer_version_id", "claim_key", name="uq_answer_citation_claim"),
    )
    _ix("answer_citations", "citation_id", "answer_version_id", "source_id", "excerpt_id")
    op.create_table(
        "answer_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_id", sa.String(120), nullable=False, unique=True),
        sa.Column("answer_version_id", sa.String(120), nullable=False),
        sa.Column("reviewer_role", sa.String(60), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("answer_version_id", "reviewer_role", name="uq_answer_review_role"),
    )
    _ix("answer_reviews", "review_id", "answer_version_id", "reviewer_role", "decision", "reviewer")
    op.create_table(
        "answer_publications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("publication_id", sa.String(120), nullable=False, unique=True),
        sa.Column("answer_version_id", sa.String(120), nullable=False),
        sa.Column("audience", sa.String(40), nullable=False),
        sa.Column("destination", sa.String(100), nullable=False),
        sa.Column("project_id", sa.String(100)),
        sa.Column("publication_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="published"),
        sa.Column("published_by", sa.String(255), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retracted_by", sa.String(255)),
        sa.Column("retracted_at", sa.DateTime(timezone=True)),
        sa.Column("retraction_reason", sa.Text()),
    )
    _ix("answer_publications", "publication_id", "answer_version_id", "audience", "destination", "project_id", "publication_sha256", "status")


def downgrade() -> None:
    for table in ("answer_publications", "answer_reviews", "answer_citations", "answer_versions", "answer_questions", "answer_knowledge_excerpts", "answer_knowledge_sources"):
        op.drop_table(table)
