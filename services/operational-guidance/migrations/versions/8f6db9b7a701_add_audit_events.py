"""add audit events

Revision ID: 8f6db9b7a701
Revises: 431439b9fde5
Create Date: 2026-07-23 11:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8f6db9b7a701"
down_revision: Union[str, None] = "431439b9fde5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_subject", sa.String(length=255), nullable=True),
        sa.Column("actor_kind", sa.String(length=32), nullable=True),
        sa.Column("actor_role", sa.String(length=64), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_events_request_id"), "audit_events", ["request_id"], unique=False)
    op.create_index(op.f("ix_audit_events_event_type"), "audit_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_audit_events_actor_subject"), "audit_events", ["actor_subject"], unique=False)
    op.create_index(op.f("ix_audit_events_actor_role"), "audit_events", ["actor_role"], unique=False)
    op.create_index(op.f("ix_audit_events_path"), "audit_events", ["path"], unique=False)
    op.create_index(op.f("ix_audit_events_status_code"), "audit_events", ["status_code"], unique=False)
    op.create_index(op.f("ix_audit_events_created_at"), "audit_events", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_events_created_at"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_status_code"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_path"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_role"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_subject"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_event_type"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_request_id"), table_name="audit_events")
    op.drop_table("audit_events")
