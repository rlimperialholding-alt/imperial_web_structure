"""Add auditable MyImperial project updates and customer decisions.

Revision ID: 20260802_0024
Revises: 20260802_0023
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0024"
down_revision = "20260802_0023"
branch_labels = None
depends_on = None


def _index(table: str, column: str) -> None:
    prefixes = {
        "cc_customer_portal_updates": "myi_upd",
        "cc_customer_portal_update_acknowledgements": "myi_ack",
        "cc_customer_decision_requests": "myi_dec",
        "cc_customer_decision_responses": "myi_rsp",
    }
    op.create_index(f"ix_{prefixes[table]}_{column}", table, [column])


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    required = {
        "cc_customer_portal_updates",
        "cc_customer_portal_update_acknowledgements",
        "cc_customer_decision_requests",
        "cc_customer_decision_responses",
    }
    present = existing & required
    if present == required:
        return
    if present:
        raise RuntimeError(
            "Partial MyImperial project portal schema: " + ", ".join(sorted(present))
        )

    op.create_table(
        "cc_customer_portal_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("update_id", sa.String(120), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "requires_acknowledgement",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("published_by", sa.String(255), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_customer_portal_update_progress",
        ),
    )
    for column in ("update_id", "project_id", "requires_acknowledgement", "published_at"):
        _index("cc_customer_portal_updates", column)

    op.create_table(
        "cc_customer_portal_update_acknowledgements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("acknowledgement_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "update_id_fk",
            sa.Integer(),
            sa.ForeignKey("cc_customer_portal_updates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "update_id_fk", "customer_email", name="uq_customer_portal_update_ack_email"
        ),
    )
    for column in ("acknowledgement_id", "update_id_fk", "customer_email"):
        _index("cc_customer_portal_update_acknowledgements", column)

    op.create_table(
        "cc_customer_decision_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(120), nullable=False, unique=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('open','responded','cancelled','expired')",
            name="ck_customer_decision_request_status",
        ),
    )
    for column in ("decision_id", "project_id", "due_at", "status"):
        _index("cc_customer_decision_requests", column)

    op.create_table(
        "cc_customer_decision_responses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("response_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "decision_id_fk",
            sa.Integer(),
            sa.ForeignKey("cc_customer_decision_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("selected_option", sa.String(500), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "decision_id_fk", "customer_email", name="uq_customer_decision_response_email"
        ),
    )
    for column in ("response_id", "decision_id_fk", "customer_email"):
        _index("cc_customer_decision_responses", column)


def downgrade() -> None:
    op.drop_table("cc_customer_decision_responses")
    op.drop_table("cc_customer_decision_requests")
    op.drop_table("cc_customer_portal_update_acknowledgements")
    op.drop_table("cc_customer_portal_updates")
