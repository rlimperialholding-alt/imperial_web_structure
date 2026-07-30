"""Make Hungarian-language and marketing-copy expert gates non-bypassable.

Revision ID: 20260727_0009
Revises: 20260726_0008
"""

import sqlalchemy as sa

from alembic import op

revision = "20260727_0009"
down_revision = "20260726_0008"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "ck_cq_published_requires_all_approvals"
NEW_CONSTRAINT = (
    "state <> 'PUBLISHED' OR "
    "(gate_1_approved = true AND expert_language_approved = true "
    "AND expert_marketing_approved = true AND four_gate_approved = true "
    "AND (source_prevalidated = true OR "
    "(editorial_approved = true AND owner_approved = true)) "
    "AND publication_proof_id IS NOT NULL AND published_at IS NOT NULL)"
)
OLD_CONSTRAINT = (
    "state <> 'PUBLISHED' OR "
    "(gate_1_approved = true AND four_gate_approved = true "
    "AND (source_prevalidated = true OR "
    "(editorial_approved = true AND owner_approved = true)) "
    "AND publication_proof_id IS NOT NULL AND published_at IS NOT NULL)"
)


def _replace_publication_constraint(sqltext: str) -> None:
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
    review_columns = {column["name"] for column in inspector.get_columns("cq_review_runs")}
    if "expert_language_approved" not in asset_columns:
        op.add_column(
            "cq_content_assets",
            sa.Column(
                "expert_language_approved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "expert_marketing_approved" not in asset_columns:
        op.add_column(
            "cq_content_assets",
            sa.Column(
                "expert_marketing_approved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "expert_review_json" not in review_columns:
        op.add_column(
            "cq_review_runs",
            sa.Column("expert_review_json", sa.Text(), nullable=False, server_default="{}"),
        )
    if "expert_review_hash" not in review_columns:
        op.add_column(
            "cq_review_runs",
            sa.Column(
                "expert_review_hash",
                sa.String(length=64),
                nullable=False,
                server_default="0" * 64,
            ),
        )
    index_names = {index["name"] for index in inspector.get_indexes("cq_review_runs")}
    if "ix_cq_review_runs_expert_review_hash" not in index_names:
        op.create_index(
            "ix_cq_review_runs_expert_review_hash",
            "cq_review_runs",
            ["expert_review_hash"],
            unique=False,
        )
    checks = {
        check["name"]: str(check.get("sqltext") or "")
        for check in inspector.get_check_constraints("cq_content_assets")
    }
    if "expert_language_approved" not in checks.get(CONSTRAINT_NAME, ""):
        _replace_publication_constraint(NEW_CONSTRAINT)


def downgrade() -> None:
    _replace_publication_constraint(OLD_CONSTRAINT)
    op.drop_index(
        "ix_cq_review_runs_expert_review_hash",
        table_name="cq_review_runs",
    )
    op.drop_column("cq_review_runs", "expert_review_hash")
    op.drop_column("cq_review_runs", "expert_review_json")
    op.drop_column("cq_content_assets", "expert_marketing_approved")
    op.drop_column("cq_content_assets", "expert_language_approved")
