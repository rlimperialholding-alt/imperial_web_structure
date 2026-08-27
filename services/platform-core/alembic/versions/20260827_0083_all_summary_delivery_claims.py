"""Backfill durable claims for every system summary.

Revision ID: 20260827_0083
Revises: 20260827_0082
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa

from alembic import op

revision = "20260827_0083"
down_revision = "20260827_0082"
branch_labels = None
depends_on = None


def _summary_key(message_type: str, recipient: str, local_date: object) -> str:
    material = f"{message_type}{recipient.strip().casefold()}{local_date}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, handoff_type, recipient_email, local_date,
                   attempt_count, sent_at, updated_at, created_at
            FROM canonical_internal_handoffs
            WHERE idempotency_key IS NULL OR claimed_at IS NULL
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
                    idempotency_key = COALESCE(idempotency_key, :idempotency_key),
                    claimed_at = COALESCE(claimed_at, :claimed_at)
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "recipient": str(row["recipient_email"]).strip().casefold(),
                "idempotency_key": _summary_key(
                    str(row["handoff_type"]),
                    str(row["recipient_email"]),
                    row["local_date"],
                ),
                "claimed_at": claimed_at,
            },
        )
    bind.execute(
        sa.text(
            """
            UPDATE canonical_internal_handoffs
            SET status = 'dead_letter',
                last_error = 'sev1_all_summary_failed_delivery_quarantined_no_retry'
            WHERE attempt_count > 0
              AND status = 'failed'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE canonical_internal_handoffs
        SET status = 'failed',
            last_error = 'downgraded_from_sev1_summary_dead_letter'
        WHERE status = 'dead_letter'
          AND last_error = 'sev1_all_summary_failed_delivery_quarantined_no_retry'
        """
    )
