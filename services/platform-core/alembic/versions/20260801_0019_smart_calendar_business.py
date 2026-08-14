"""Add production Smart Calendar business entities.

Revision ID: 20260801_0019
Revises: 20260801_0018
"""

import sqlalchemy as sa

from alembic import op

revision = "20260801_0019"
down_revision = "20260801_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    required = {
        "cc_calendar_entries",
        "cc_calendar_dependencies",
        "cc_calendar_change_requests",
    }
    present = existing & required
    if present == required:
        # Fresh installations receive the current metadata from the consolidated
        # bootstrap migration; the revision still needs to be stamped safely.
        return
    if present:
        raise RuntimeError(
            "Partial Smart Calendar schema detected; refusing an unsafe migration: "
            + ", ".join(sorted(present))
        )
    op.create_table(
        "cc_calendar_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_id", sa.String(length=120), nullable=False),
        sa.Column("project_id", sa.String(length=100), nullable=False),
        sa.Column("entry_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("assignee", sa.String(length=255), nullable=True),
        sa.Column("participants_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("location", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="planned"),
        sa.Column("priority", sa.String(length=30), nullable=False, server_default="normal"),
        sa.Column("source_module", sa.String(length=100), nullable=False, server_default="smart-calendar"),
        sa.Column("source_object_id", sa.String(length=160), nullable=True),
        sa.Column("linked_task_id", sa.String(length=120), nullable=True),
        sa.Column("contractual_deadline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("capacity_hours", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("conflict_override_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name="ck_cc_calendar_entry_time_order"),
        sa.UniqueConstraint("entry_id"),
    )
    for name, columns in (
        ("ix_cc_calendar_entries_entry_id", ["entry_id"]),
        ("ix_cc_calendar_entries_project_id", ["project_id"]),
        ("ix_cc_calendar_entries_entry_type", ["entry_type"]),
        ("ix_cc_calendar_entries_title", ["title"]),
        ("ix_cc_calendar_entries_starts_at", ["starts_at"]),
        ("ix_cc_calendar_entries_ends_at", ["ends_at"]),
        ("ix_cc_calendar_entries_assignee", ["assignee"]),
        ("ix_cc_calendar_entries_status", ["status"]),
        ("ix_cc_calendar_entries_priority", ["priority"]),
        ("ix_cc_calendar_entries_source_object_id", ["source_object_id"]),
        ("ix_cc_calendar_entries_linked_task_id", ["linked_task_id"]),
        ("ix_cc_calendar_entries_contractual_deadline", ["contractual_deadline"]),
    ):
        op.create_index(name, "cc_calendar_entries", columns)

    op.create_table(
        "cc_calendar_dependencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dependency_id", sa.String(length=120), nullable=False),
        sa.Column(
            "predecessor_entry_id",
            sa.String(length=120),
            sa.ForeignKey("cc_calendar_entries.entry_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "successor_entry_id",
            sa.String(length=120),
            sa.ForeignKey("cc_calendar_entries.entry_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dependency_type", sa.String(length=30), nullable=False, server_default="finish_to_start"),
        sa.Column("lag_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "predecessor_entry_id <> successor_entry_id",
            name="ck_cc_calendar_dependency_distinct",
        ),
        sa.UniqueConstraint("dependency_id"),
        sa.UniqueConstraint(
            "predecessor_entry_id",
            "successor_entry_id",
            name="uq_cc_calendar_dependency_pair",
        ),
    )
    for name, columns in (
        ("ix_cc_calendar_dependencies_dependency_id", ["dependency_id"]),
        ("ix_cc_calendar_dependencies_predecessor_entry_id", ["predecessor_entry_id"]),
        ("ix_cc_calendar_dependencies_successor_entry_id", ["successor_entry_id"]),
        ("ix_cc_calendar_dependencies_active", ["active"]),
    ):
        op.create_index(name, "cc_calendar_dependencies", columns)

    op.create_table(
        "cc_calendar_change_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(length=120), nullable=False),
        sa.Column(
            "entry_id",
            sa.String(length=120),
            sa.ForeignKey("cc_calendar_entries.entry_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requested_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("impact_summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("request_id"),
    )
    for name, columns in (
        ("ix_cc_calendar_change_requests_request_id", ["request_id"]),
        ("ix_cc_calendar_change_requests_entry_id", ["entry_id"]),
        ("ix_cc_calendar_change_requests_status", ["status"]),
    ):
        op.create_index(name, "cc_calendar_change_requests", columns)


def downgrade() -> None:
    op.drop_table("cc_calendar_change_requests")
    op.drop_table("cc_calendar_dependencies")
    op.drop_table("cc_calendar_entries")
