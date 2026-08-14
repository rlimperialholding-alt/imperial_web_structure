"""Market & Creative Intelligence research/evidence layer.

Revision ID: 20260810_0051
Revises: 20260810_0050
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260810_0051"
down_revision = "20260810_0050"
branch_labels = None
depends_on = None

TABLES = (
    "market_source_targets",
    "market_capture_jobs",
    "market_source_snapshots",
    "market_evidence_redactions",
    "market_assets",
    "market_observations",
    "market_voc_signals",
    "market_pattern_clusters",
    "market_research_hypotheses",
    "market_validations",
    "market_research_packs",
    "market_pack_handoffs",
    "market_handoff_watermarks",
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    present = existing.intersection(TABLES)
    if present:
        if present == set(TABLES):
            return
        raise RuntimeError(
            f"Partial MCI schema detected; refusing unsafe upgrade: {sorted(present)}"
        )
    op.create_table(
        "market_source_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target_id", sa.String(120), nullable=False, unique=True),
        sa.Column("family_id", sa.String(120), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("market_id", sa.String(120), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(60), nullable=False),
        sa.Column("normalized_origin", sa.String(1200), nullable=False),
        sa.Column("allowed_path", sa.String(1200), nullable=False, server_default="/"),
        sa.Column("capture_mode", sa.String(40), nullable=False, server_default="manual"),
        sa.Column("rights_status", sa.String(40), nullable=False),
        sa.Column("pii_policy", sa.String(80), nullable=False, server_default="reject"),
        sa.Column("policy_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("policy_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("author_subject_id", sa.String(160), nullable=False),
        sa.Column("reviewer_subject_id", sa.String(160)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("revoke_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_id", "revision_no", name="uq_mkt_target_family_revision"),
        sa.CheckConstraint(
            "status IN ('DRAFT','IN_REVIEW','APPROVED','REVOKED','SUPERSEDED')",
            name="ck_mkt_target_status",
        ),
    )
    op.create_table(
        "market_capture_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(120), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("market_id", sa.String(120), nullable=False),
        sa.Column("target_id", sa.String(120), nullable=False),
        sa.Column("target_revision_no", sa.Integer(), nullable=False),
        sa.Column("policy_sha256", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="QUEUED"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_mkt_capture_idempotency"),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','PARTIAL','FAILED','CANCELLED')",
            name="ck_mkt_capture_status",
        ),
    )
    op.create_table(
        "market_source_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.String(120), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("market_id", sa.String(120), nullable=False),
        sa.Column("target_id", sa.String(120), nullable=False),
        sa.Column("capture_job_id", sa.String(120), nullable=False),
        sa.Column("resolved_url", sa.String(1600), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_text_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("policy_sha256", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(120), nullable=False),
        sa.Column("parser_digest", sa.String(160), nullable=False),
        sa.Column("privacy_classification", sa.String(40), nullable=False, server_default="PUBLIC"),
        sa.Column("quarantine_state", sa.String(40), nullable=False, server_default="CLEAN"),
        sa.Column("storage_ref", sa.String(1200)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.UniqueConstraint("target_id", "content_sha256", name="uq_mkt_snapshot_target_content"),
    )
    op.create_table(
        "market_evidence_redactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("redaction_id", sa.String(120), nullable=False, unique=True),
        sa.Column("snapshot_id", sa.String(120), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("legal_basis", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_subject_id", sa.String(160), nullable=False),
        sa.Column("reviewer_subject_id", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "market_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.String(120), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("market_id", sa.String(120), nullable=False),
        sa.Column("snapshot_id", sa.String(120), nullable=False),
        sa.Column("channel", sa.String(60), nullable=False),
        sa.Column("asset_type", sa.String(60), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source_span_json", sa.Text(), nullable=False),
        sa.Column("claims_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("extraction_version", sa.String(120), nullable=False),
        sa.Column("canonical_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "market_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observation_id", sa.String(120), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("market_id", sa.String(120), nullable=False),
        sa.Column("snapshot_id", sa.String(120), nullable=False),
        sa.Column("source_span_json", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("evidence_level", sa.String(40), nullable=False),
        sa.Column("method", sa.Text()),
        sa.Column("confidence", sa.Numeric(6, 5)),
        sa.Column("canonical_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "evidence_level IN ('OBSERVED','INFERRED','VALIDATED_INTERNAL')",
            name="ck_mkt_observation_evidence",
        ),
    )
    op.create_table(
        "market_voc_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.String(120), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("market_id", sa.String(120), nullable=False),
        sa.Column("snapshot_id", sa.String(120), nullable=False),
        sa.Column("source_span_json", sa.Text(), nullable=False),
        sa.Column("masked_quote", sa.Text(), nullable=False),
        sa.Column("theme", sa.String(160), nullable=False),
        sa.Column("sentiment", sa.String(40)),
        sa.Column("canonical_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "market_pattern_clusters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cluster_id", sa.String(120), nullable=False, unique=True),
        sa.Column("family_id", sa.String(120), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("market_id", sa.String(120), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("algorithm_version", sa.String(120), nullable=False),
        sa.Column("member_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Numeric(6, 5)),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_id", "revision_no", name="uq_mkt_cluster_family_revision"),
    )
    op.create_table(
        "market_research_hypotheses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hypothesis_id", sa.String(120), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("market_id", sa.String(120), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("audience", sa.String(255), nullable=False),
        sa.Column("supporting_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("contradicting_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("falsification_criterion", sa.Text(), nullable=False),
        sa.Column("evidence_level", sa.String(40), nullable=False, server_default="INFERRED"),
        sa.Column("canonical_sha256", sa.String(64), nullable=False),
        sa.Column("owner_subject_id", sa.String(160), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "market_validations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("validation_id", sa.String(120), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("market_id", sa.String(120), nullable=False),
        sa.Column("subject_type", sa.String(40), nullable=False),
        sa.Column("subject_id", sa.String(120), nullable=False),
        sa.Column("subject_sha256", sa.String(64), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("metric_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("sample_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("author_subject_id", sa.String(160), nullable=False),
        sa.Column("reviewer_subject_id", sa.String(160)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "market_research_packs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pack_id", sa.String(120), nullable=False, unique=True),
        sa.Column("family_id", sa.String(120), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("market_id", sa.String(120), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("intended_use", sa.String(255), nullable=False),
        sa.Column("channels_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("member_refs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="DRAFT"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author_subject_id", sa.String(160), nullable=False),
        sa.Column("reviewer_subject_id", sa.String(160)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("frozen_by", sa.String(160)),
        sa.Column("frozen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_id", "revision_no", name="uq_mkt_pack_family_revision"),
        sa.CheckConstraint(
            "status IN ('DRAFT','IN_REVIEW','APPROVED','FROZEN','HANDED_OFF','EXPIRED',"
            "'REVOKED','SUPERSEDED','CHANGES_REQUESTED','REJECTED')",
            name="ck_mkt_pack_status",
        ),
    )
    op.create_table(
        "market_pack_handoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("handoff_id", sa.String(120), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("market_id", sa.String(120), nullable=False),
        sa.Column("pack_id", sa.String(120), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("downstream_purpose", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACCEPTED"),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_mkt_handoff_idempotency"),
    )
    op.create_table(
        "market_handoff_watermarks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("brand_id", sa.String(120), nullable=False),
        sa.Column("market_id", sa.String(120), nullable=False),
        sa.Column("downstream_purpose", sa.String(120), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("pack_id", sa.String(120), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "brand_id",
            "market_id",
            "downstream_purpose",
            name="uq_mkt_handoff_watermark_scope",
        ),
    )
    for table in (item for item in TABLES if item != "market_evidence_redactions"):
        op.create_index(f"ix_{table}_tenant_scope", table, ["tenant_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    populated = []
    for table in TABLES:
        if (
            table in existing
            and bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
        ):
            populated.append(table)
    if populated:
        raise RuntimeError(
            "MCI rollback blocked because business data exists; "
            "use the export-and-quarantine runbook: " + ", ".join(populated)
        )
    for table in reversed(TABLES):
        if table in existing:
            op.drop_table(table)
