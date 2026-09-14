"""Add governed regulatory review and site-verification evidence.

Revision ID: 20260810_0052
Revises: 20260810_0051
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260810_0052"
down_revision = "20260810_0051"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    required = {
        "house_design_sessions",
        "house_design_revisions",
        "regulatory_source_snapshots",
        "regulatory_rule_interpretations",
        "regulatory_rule_sets",
    }
    missing = required - tables
    if missing:
        raise RuntimeError(f"Regulatory base schema is incomplete: {sorted(missing)}")

    if "house_design_site_verifications" not in tables:
        op.create_table(
            "house_design_site_verifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("verification_id", sa.String(120), nullable=False),
            sa.Column("session_id", sa.String(120), nullable=False),
            sa.Column("source_revision_id", sa.String(120), nullable=False),
            sa.Column("verified_revision_id", sa.String(120), nullable=False),
            sa.Column("municipality_code", sa.String(80), nullable=False),
            sa.Column("parcel_number", sa.String(120), nullable=False),
            sa.Column("proof_ref", sa.String(1200), nullable=False),
            sa.Column("proof_sha256", sa.String(64), nullable=False),
            sa.Column("verification_method", sa.String(120), nullable=False),
            sa.Column("verified_by", sa.String(255), nullable=False),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("verification_id", name="uq_hd_site_verification_id"),
            sa.UniqueConstraint(
                "session_id", "verified_revision_id", name="uq_hd_site_verified_revision"
            ),
            sa.UniqueConstraint("session_id", "proof_sha256", name="uq_hd_site_session_proof"),
        )
        for column in (
            "verification_id",
            "session_id",
            "source_revision_id",
            "verified_revision_id",
            "municipality_code",
            "parcel_number",
            "proof_sha256",
            "verified_by",
            "verified_at",
        ):
            op.create_index(
                f"ix_house_design_site_verifications_{column}",
                "house_design_site_verifications",
                [column],
            )

    source_columns = _columns("regulatory_source_snapshots")
    for column in (
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
    ):
        if column.name not in source_columns:
            op.add_column("regulatory_source_snapshots", column)
    recreate = "always" if op.get_bind().dialect.name == "sqlite" else "auto"
    with op.batch_alter_table("regulatory_source_snapshots", recreate=recreate) as batch:
        batch.alter_column(
            "security_status",
            existing_type=sa.String(30),
            existing_nullable=False,
            server_default="pending_review",
        )
        batch.alter_column(
            "status",
            existing_type=sa.String(30),
            existing_nullable=False,
            server_default="captured",
        )

    interpretation_columns = _columns("regulatory_rule_interpretations")
    if "row_version" not in interpretation_columns:
        op.add_column(
            "regulatory_rule_interpretations",
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        )

    ruleset_columns = _columns("regulatory_rule_sets")
    if "interpretation_ids_json" not in ruleset_columns:
        op.add_column(
            "regulatory_rule_sets",
            sa.Column("interpretation_ids_json", sa.Text(), nullable=False, server_default="[]"),
        )
    if "row_version" not in ruleset_columns:
        op.add_column(
            "regulatory_rule_sets",
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        )

    # Records created before the four-eyes workflow have no approval evidence.
    # Quarantine them for explicit review rather than treating legacy defaults as proof.
    op.execute(
        sa.text(
            "UPDATE regulatory_source_snapshots "
            "SET security_status='pending_review', status='captured', "
            "approved_by=NULL, approved_at=NULL, row_version=1"
        )
    )


def downgrade() -> None:
    raise RuntimeError(
        "0052 contains regulatory approval and site-identity evidence and has no destructive "
        "automatic downgrade. Use a verified export and a forward migration."
    )
