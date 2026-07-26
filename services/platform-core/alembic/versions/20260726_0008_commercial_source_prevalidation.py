"""Commercial source prevalidation and source-based publication integrity.

Revision ID: 20260726_0008
Revises: 20260726_0007
"""

import sqlalchemy as sa

from alembic import op

revision = "20260726_0008"
down_revision = "20260726_0007"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "ck_cq_published_requires_all_approvals"
NEW_CONSTRAINT = (
    "state <> 'PUBLISHED' OR "
    "(gate_1_approved = true AND four_gate_approved = true "
    "AND (source_prevalidated = true OR "
    "(editorial_approved = true AND owner_approved = true)) "
    "AND publication_proof_id IS NOT NULL AND published_at IS NOT NULL)"
)
OLD_CONSTRAINT = (
    "state <> 'PUBLISHED' OR "
    "(gate_1_approved = true AND four_gate_approved = true "
    "AND editorial_approved = true AND owner_approved = true "
    "AND publication_proof_id IS NOT NULL AND published_at IS NOT NULL)"
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("cq_content_assets")}
    checks = {
        check["name"]: str(check.get("sqltext") or "")
        for check in inspector.get_check_constraints("cq_content_assets")
    }

    if "source_prevalidated" not in columns:
        op.add_column(
            "cq_content_assets",
            sa.Column(
                "source_prevalidated",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    current_constraint = checks.get(CONSTRAINT_NAME, "")
    if "source_prevalidated" not in current_constraint:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(
                "cq_content_assets",
                recreate="always",
            ) as batch:
                batch.drop_constraint(CONSTRAINT_NAME, type_="check")
                batch.create_check_constraint(CONSTRAINT_NAME, NEW_CONSTRAINT)
        else:
            op.drop_constraint(
                CONSTRAINT_NAME,
                "cq_content_assets",
                type_="check",
            )
            op.create_check_constraint(
                CONSTRAINT_NAME,
                "cq_content_assets",
                NEW_CONSTRAINT,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "cq_content_assets",
            recreate="always",
        ) as batch:
            batch.drop_constraint(CONSTRAINT_NAME, type_="check")
            batch.create_check_constraint(CONSTRAINT_NAME, OLD_CONSTRAINT)
        with op.batch_alter_table(
            "cq_content_assets",
            recreate="always",
        ) as batch:
            batch.drop_column("source_prevalidated")
    else:
        op.drop_constraint(
            CONSTRAINT_NAME,
            "cq_content_assets",
            type_="check",
        )
        op.create_check_constraint(
            CONSTRAINT_NAME,
            "cq_content_assets",
            OLD_CONSTRAINT,
        )
        op.drop_column("cq_content_assets", "source_prevalidated")
