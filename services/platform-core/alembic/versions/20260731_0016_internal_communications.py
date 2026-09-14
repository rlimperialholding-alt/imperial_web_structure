"""Add internal communications and notifications.

Revision ID: 20260731_0016
Revises: 20260731_0015
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0016"
down_revision = "20260731_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "cc_communication_threads" not in tables:
        op.create_table(
            "cc_communication_threads",
            sa.Column("thread_id", sa.String(120), primary_key=True),
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("thread_type", sa.String(30), nullable=False),
            sa.Column("project_id", sa.String(100), nullable=True),
            sa.Column("task_id", sa.String(120), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("cc_users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("subject", "thread_type", "project_id", "task_id", "created_by_user_id", "updated_at"):
            op.create_index(f"ix_cc_communication_threads_{column}", "cc_communication_threads", [column])
    if "cc_communication_participants" not in tables:
        op.create_table(
            "cc_communication_participants",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("thread_id", sa.String(120), sa.ForeignKey("cc_communication_threads.thread_id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("cc_users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("muted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("thread_id", "user_id", name="uq_cc_communication_participant"),
        )
        op.create_index("ix_cc_communication_participants_thread_id", "cc_communication_participants", ["thread_id"])
        op.create_index("ix_cc_communication_participants_user_id", "cc_communication_participants", ["user_id"])
    if "cc_communication_messages" not in tables:
        op.create_table(
            "cc_communication_messages",
            sa.Column("message_id", sa.String(120), primary_key=True),
            sa.Column("thread_id", sa.String(120), sa.ForeignKey("cc_communication_threads.thread_id", ondelete="CASCADE"), nullable=False),
            sa.Column("sender_user_id", sa.Integer(), sa.ForeignKey("cc_users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("reply_to_message_id", sa.String(120), sa.ForeignKey("cc_communication_messages.message_id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("thread_id", "sender_user_id", "created_at"):
            op.create_index(f"ix_cc_communication_messages_{column}", "cc_communication_messages", [column])
    if "cc_internal_notifications" not in tables:
        op.create_table(
            "cc_internal_notifications",
            sa.Column("notification_id", sa.String(120), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("cc_users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("thread_id", sa.String(120), sa.ForeignKey("cc_communication_threads.thread_id", ondelete="CASCADE"), nullable=True),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("target_url", sa.String(1000), nullable=False),
            sa.Column("actor_email", sa.String(255), nullable=True),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("user_id", "thread_id", "category", "read_at", "created_at"):
            op.create_index(f"ix_cc_internal_notifications_{column}", "cc_internal_notifications", [column])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (
        "cc_internal_notifications",
        "cc_communication_messages",
        "cc_communication_participants",
        "cc_communication_threads",
    ):
        if table in tables:
            op.drop_table(table)
