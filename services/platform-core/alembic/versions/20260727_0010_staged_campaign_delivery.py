"""Add staged campaign production, release QA and live double-check workflow.

Revision ID: 20260727_0010
Revises: 20260727_0009
"""

import sqlalchemy as sa

from alembic import op
from app import models  # noqa: F401
from app.database import Base

revision = "20260727_0010"
down_revision = "20260727_0009"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "ck_cq_published_requires_all_approvals"
NEW_CONSTRAINT = (
    "state NOT IN ('PUBLISHED', 'LIVE_QA', 'QUARANTINED') OR "
    "(gate_1_approved = true AND expert_language_approved = true "
    "AND expert_marketing_approved = true AND four_gate_approved = true "
    "AND creative_director_approved = true AND assembly_approved = true "
    "AND release_approved = true AND active_bundle_id IS NOT NULL "
    "AND (source_prevalidated = true OR "
    "(editorial_approved = true AND owner_approved = true)) "
    "AND publication_proof_id IS NOT NULL AND published_at IS NOT NULL)"
)
OLD_CONSTRAINT = (
    "state <> 'PUBLISHED' OR "
    "(gate_1_approved = true AND expert_language_approved = true "
    "AND expert_marketing_approved = true AND four_gate_approved = true "
    "AND (source_prevalidated = true OR "
    "(editorial_approved = true AND owner_approved = true)) "
    "AND publication_proof_id IS NOT NULL AND published_at IS NOT NULL)"
)
NEW_TABLES = (
    "cq_strategy_reviews",
    "cq_creative_runs",
    "cq_workflow_reviews",
    "cq_publication_bundles",
)
NEW_COLUMNS = (
    ("creative_director_approved", sa.Boolean(), sa.false()),
    ("assembly_approved", sa.Boolean(), sa.false()),
    ("release_approved", sa.Boolean(), sa.false()),
    ("live_review_approved", sa.Boolean(), sa.false()),
    ("active_bundle_id", sa.String(length=120), None),
)


def _replace_constraint(sqltext: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("cq_content_assets", recreate="always") as batch:
            batch.drop_constraint(CONSTRAINT_NAME, type_="check")
            batch.create_check_constraint(CONSTRAINT_NAME, sqltext)
    else:
        op.drop_constraint(CONSTRAINT_NAME, "cq_content_assets", type_="check")
        op.create_check_constraint(
            CONSTRAINT_NAME,
            "cq_content_assets",
            sqltext,
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    asset_columns = {column["name"] for column in inspector.get_columns("cq_content_assets")}
    for name, column_type, default in NEW_COLUMNS:
        if name in asset_columns:
            continue
        op.add_column(
            "cq_content_assets",
            sa.Column(
                name,
                column_type,
                nullable=name == "active_bundle_id",
                server_default=default,
            ),
        )
    for table_name in NEW_TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("cq_content_assets")}
    if "ix_cq_content_assets_active_bundle_id" not in indexes:
        op.create_index(
            "ix_cq_content_assets_active_bundle_id",
            "cq_content_assets",
            ["active_bundle_id"],
            unique=False,
        )
    checks = {
        check["name"]: str(check.get("sqltext") or "")
        for check in inspector.get_check_constraints("cq_content_assets")
    }
    if "creative_director_approved" not in checks.get(CONSTRAINT_NAME, ""):
        _replace_constraint(NEW_CONSTRAINT)


def downgrade() -> None:
    bind = op.get_bind()
    _replace_constraint(OLD_CONSTRAINT)
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("cq_content_assets")}
    if "ix_cq_content_assets_active_bundle_id" in indexes:
        op.drop_index(
            "ix_cq_content_assets_active_bundle_id",
            table_name="cq_content_assets",
        )
    for table_name in reversed(NEW_TABLES):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
    for name, _, _ in reversed(NEW_COLUMNS):
        op.drop_column("cq_content_assets", name)
