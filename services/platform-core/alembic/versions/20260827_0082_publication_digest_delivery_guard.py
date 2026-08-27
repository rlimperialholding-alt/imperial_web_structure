"""Add fail-closed publication digest delivery guards.

Revision ID: 20260827_0082
Revises: 20260826_0081
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa

from alembic import op

revision = "20260827_0082"
down_revision = "20260826_0081"
branch_labels = None
depends_on = None


def _digest_key(message_type: str, recipient: str, local_date: object) -> str:
    normalized_recipient = recipient.strip().casefold()
    material = f"{message_type}{normalized_recipient}{local_date}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("canonical_internal_handoffs") as batch:
            batch.add_column(sa.Column("idempotency_key", sa.String(64), nullable=True))
            batch.add_column(
                sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)
            )
            batch.drop_constraint("ck_canonical_handoff_status", type_="check")
            batch.create_check_constraint(
                "ck_canonical_handoff_status",
                "status IN ('pending','claimed','sent','failed','blocked','dead_letter')",
            )
            batch.drop_constraint("uq_canonical_handoff_day_type", type_="unique")
            batch.create_unique_constraint(
                "uq_canonical_handoff_type_recipient_day",
                ["handoff_type", "recipient_email", "local_date"],
            )
            batch.create_unique_constraint(
                "uq_canonical_handoff_idempotency_key",
                ["idempotency_key"],
            )
    else:
        op.add_column(
            "canonical_internal_handoffs",
            sa.Column("idempotency_key", sa.String(64), nullable=True),
        )
        op.add_column(
            "canonical_internal_handoffs",
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        )
    op.create_index(
        "ix_canonical_internal_handoffs_idempotency_key",
        "canonical_internal_handoffs",
        ["idempotency_key"],
    )
    op.create_index(
        "ix_canonical_internal_handoffs_claimed_at",
        "canonical_internal_handoffs",
        ["claimed_at"],
    )

    rows = bind.execute(
        sa.text(
            """
            SELECT id, handoff_type, recipient_email, local_date,
                   attempt_count, sent_at, updated_at, created_at
            FROM canonical_internal_handoffs
            WHERE handoff_type = 'daily_publication_digest'
            """
        )
    ).mappings()
    for row in rows:
        claimed_at = None
        if int(row["attempt_count"] or 0) > 0:
            claimed_at = row["sent_at"] or row["updated_at"] or row["created_at"]
        bind.execute(
            sa.text(
                """
                UPDATE canonical_internal_handoffs
                SET recipient_email = :recipient,
                    idempotency_key = :idempotency_key,
                    claimed_at = :claimed_at
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "recipient": str(row["recipient_email"]).strip().casefold(),
                "idempotency_key": _digest_key(
                    str(row["handoff_type"]),
                    str(row["recipient_email"]),
                    row["local_date"],
                ),
                "claimed_at": claimed_at,
            },
        )

    if bind.dialect.name != "sqlite":
        op.drop_constraint(
            "ck_canonical_handoff_status",
            "canonical_internal_handoffs",
            type_="check",
        )
        op.create_check_constraint(
            "ck_canonical_handoff_status",
            "canonical_internal_handoffs",
            "status IN ('pending','claimed','sent','failed','blocked','dead_letter')",
        )
    bind.execute(
        sa.text(
            """
            UPDATE canonical_internal_handoffs
            SET status = 'dead_letter',
                last_error = 'sev1_quarantined_ambiguous_or_failed_delivery_no_retry'
            WHERE handoff_type = 'daily_publication_digest'
              AND attempt_count > 0
              AND status IN ('failed', 'blocked')
            """
        )
    )

    if bind.dialect.name != "sqlite":
        op.drop_constraint(
            "uq_canonical_handoff_day_type",
            "canonical_internal_handoffs",
            type_="unique",
        )
        op.create_unique_constraint(
            "uq_canonical_handoff_type_recipient_day",
            "canonical_internal_handoffs",
            ["handoff_type", "recipient_email", "local_date"],
        )
        op.create_unique_constraint(
            "uq_canonical_handoff_idempotency_key",
            "canonical_internal_handoffs",
            ["idempotency_key"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE canonical_internal_handoffs
            SET status = 'blocked'
            WHERE status IN ('claimed', 'dead_letter')
            """
        )
    )
    op.drop_index(
        "ix_canonical_internal_handoffs_claimed_at",
        table_name="canonical_internal_handoffs",
    )
    op.drop_index(
        "ix_canonical_internal_handoffs_idempotency_key",
        table_name="canonical_internal_handoffs",
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("canonical_internal_handoffs") as batch:
            batch.drop_constraint(
                "uq_canonical_handoff_idempotency_key", type_="unique"
            )
            batch.drop_constraint(
                "uq_canonical_handoff_type_recipient_day", type_="unique"
            )
            batch.create_unique_constraint(
                "uq_canonical_handoff_day_type", ["local_date", "handoff_type"]
            )
            batch.drop_constraint("ck_canonical_handoff_status", type_="check")
            batch.create_check_constraint(
                "ck_canonical_handoff_status",
                "status IN ('pending','sent','failed','blocked')",
            )
            batch.drop_column("claimed_at")
            batch.drop_column("idempotency_key")
    else:
        op.drop_constraint(
            "uq_canonical_handoff_idempotency_key",
            "canonical_internal_handoffs",
            type_="unique",
        )
        op.drop_constraint(
            "uq_canonical_handoff_type_recipient_day",
            "canonical_internal_handoffs",
            type_="unique",
        )
        op.create_unique_constraint(
            "uq_canonical_handoff_day_type",
            "canonical_internal_handoffs",
            ["local_date", "handoff_type"],
        )
        op.drop_constraint(
            "ck_canonical_handoff_status",
            "canonical_internal_handoffs",
            type_="check",
        )
        op.create_check_constraint(
            "ck_canonical_handoff_status",
            "canonical_internal_handoffs",
            "status IN ('pending','sent','failed','blocked')",
        )
        op.drop_column("canonical_internal_handoffs", "claimed_at")
        op.drop_column("canonical_internal_handoffs", "idempotency_key")
