"""Make the marketing, copywriter and visual gates publication invariants.

Revision ID: 20260730_0011
Revises: 20260727_0010
"""

import sqlalchemy as sa

from alembic import op

revision = "20260730_0011"
down_revision = "20260727_0010"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "ck_cq_published_requires_all_approvals"
NEW_CONSTRAINT = (
    "state NOT IN ('PUBLISHED', 'LIVE_QA', 'QUARANTINED') OR "
    "(gate_1_approved = true AND expert_language_approved = true "
    "AND expert_marketing_approved = true AND copywriter_approved = true "
    "AND four_gate_approved = true AND creative_director_approved = true "
    "AND assembly_approved = true AND release_approved = true "
    "AND active_bundle_id IS NOT NULL AND (source_prevalidated = true OR "
    "(editorial_approved = true AND owner_approved = true)) "
    "AND publication_proof_id IS NOT NULL AND published_at IS NOT NULL)"
)
OLD_CONSTRAINT = (
    "state NOT IN ('PUBLISHED', 'LIVE_QA', 'QUARANTINED') OR "
    "(gate_1_approved = true AND expert_language_approved = true "
    "AND expert_marketing_approved = true AND four_gate_approved = true "
    "AND creative_director_approved = true AND assembly_approved = true "
    "AND release_approved = true AND active_bundle_id IS NOT NULL "
    "AND (source_prevalidated = true OR "
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
    columns = {column["name"] for column in sa.inspect(bind).get_columns("cq_content_assets")}
    if "copywriter_approved" not in columns:
        op.add_column(
            "cq_content_assets",
            sa.Column(
                "copywriter_approved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    checks = {
        check["name"]: str(check.get("sqltext") or "")
        for check in sa.inspect(bind).get_check_constraints("cq_content_assets")
    }
    if "copywriter_approved" not in checks.get(CONSTRAINT_NAME, ""):
        _replace_constraint(NEW_CONSTRAINT)


def downgrade() -> None:
    _replace_constraint(OLD_CONSTRAINT)
    op.drop_column("cq_content_assets", "copywriter_approved")
