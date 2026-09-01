"""Require the conversion campaign package before publication.

Revision ID: 20260731_0017
Revises: 20260731_0016
"""

import sqlalchemy as sa

from alembic import op

revision = "20260731_0017"
down_revision = "20260731_0016"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "ck_cq_published_requires_all_approvals"
NEW_CONSTRAINT = (
    "state NOT IN ('PUBLISHED', 'LIVE_QA', 'QUARANTINED') OR "
    "(gate_1_approved = true AND expert_language_approved = true "
    "AND expert_marketing_approved = true AND copywriter_approved = true "
    "AND four_gate_approved = true AND creative_director_approved = true "
    "AND assembly_approved = true AND campaign_package_approved = true "
    "AND campaign_package_hash IS NOT NULL AND campaign_artifact_set_hash IS NOT NULL "
    "AND release_approved = true AND active_bundle_id IS NOT NULL "
    "AND (source_prevalidated = true OR "
    "(editorial_approved = true AND owner_approved = true)) "
    "AND publication_proof_id IS NOT NULL AND published_at IS NOT NULL)"
)
OLD_CONSTRAINT = (
    "state NOT IN ('PUBLISHED', 'LIVE_QA', 'QUARANTINED') OR "
    "(gate_1_approved = true AND expert_language_approved = true "
    "AND expert_marketing_approved = true AND copywriter_approved = true "
    "AND four_gate_approved = true AND creative_director_approved = true "
    "AND assembly_approved = true AND release_approved = true "
    "AND active_bundle_id IS NOT NULL AND (source_prevalidated = true OR "
    "(editorial_approved = true AND owner_approved = true)) "
    "AND publication_proof_id IS NOT NULL AND published_at IS NOT NULL)"
)


def _replace_constraint(sqltext: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("cq_content_assets", recreate="always") as batch:
            batch.drop_constraint(CONSTRAINT_NAME, type_="check")
            batch.create_check_constraint(CONSTRAINT_NAME, sqltext)
    else:
        op.drop_constraint(CONSTRAINT_NAME, "cq_content_assets", type_="check")
        op.create_check_constraint(CONSTRAINT_NAME, "cq_content_assets", sqltext)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("cq_content_assets")}
    if "campaign_package_approved" not in columns:
        op.add_column(
            "cq_content_assets",
            sa.Column(
                "campaign_package_approved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "campaign_package_hash" not in columns:
        op.add_column(
            "cq_content_assets",
            sa.Column("campaign_package_hash", sa.String(length=64), nullable=True),
        )
    if "campaign_artifact_set_hash" not in columns:
        op.add_column(
            "cq_content_assets",
            sa.Column("campaign_artifact_set_hash", sa.String(length=64), nullable=True),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("cq_content_assets")}
    if "ix_cq_content_assets_campaign_package_hash" not in indexes:
        op.create_index(
            "ix_cq_content_assets_campaign_package_hash",
            "cq_content_assets",
            ["campaign_package_hash"],
        )
    if "ix_cq_content_assets_campaign_artifact_set_hash" not in indexes:
        op.create_index(
            "ix_cq_content_assets_campaign_artifact_set_hash",
            "cq_content_assets",
            ["campaign_artifact_set_hash"],
        )
    _replace_constraint(NEW_CONSTRAINT)


def downgrade() -> None:
    _replace_constraint(OLD_CONSTRAINT)
    op.drop_index(
        "ix_cq_content_assets_campaign_artifact_set_hash",
        table_name="cq_content_assets",
    )
    op.drop_index(
        "ix_cq_content_assets_campaign_package_hash",
        table_name="cq_content_assets",
    )
    op.drop_column("cq_content_assets", "campaign_artifact_set_hash")
    op.drop_column("cq_content_assets", "campaign_package_hash")
    op.drop_column("cq_content_assets", "campaign_package_approved")
