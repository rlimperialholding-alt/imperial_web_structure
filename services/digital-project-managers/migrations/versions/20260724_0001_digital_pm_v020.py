"""Create Digital Project Managers v0.2.0 schema and seed identities.

Revision ID: 20260724_0001
Revises:
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260724_0001"
down_revision = None
branch_labels = None
depends_on = None


MANAGERS = (
    (
        "11111111-1111-4111-8111-111111111101",
        "digitalis-kalman",
        "Digitális Kálmán",
        "Kálmán",
    ),
    (
        "11111111-1111-4111-8111-111111111102",
        "digitalis-mate",
        "Digitális Máté",
        "Máté",
    ),
    (
        "11111111-1111-4111-8111-111111111103",
        "digitalis-misi",
        "Digitális Misi",
        "Misi",
    ),
)

ASSIGNMENTS = (
    ("21111111-1111-4111-8111-111111111101", "P-5001", MANAGERS[0][0]),
    ("21111111-1111-4111-8111-111111111102", "P-5002", MANAGERS[1][0]),
    ("21111111-1111-4111-8111-111111111103", "P-5003", MANAGERS[2][0]),
)


def upgrade() -> None:
    op.create_table(
        "digital_project_managers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("human_partner_name", sa.String(128), nullable=False),
        sa.Column("human_manager_ref", sa.String(128)),
        sa.Column(
            "authority_profile",
            sa.String(64),
            nullable=False,
            server_default="standard-r0-r7",
        ),
        sa.Column(
            "mode",
            sa.String(32),
            nullable=False,
            server_default="limited-autonomy",
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "project_assignments",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column("external_project_id", sa.String(128), nullable=False),
        sa.Column(
            "digital_manager_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("digital_project_managers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column(
            "restrictions",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("approval_owner_ref", sa.String(128)),
    )
    op.create_index(
        "uq_project_assignments_active_project",
        "project_assignments",
        ["external_project_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_table(
        "project_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_project_id", sa.String(128), nullable=False),
        sa.Column(
            "digital_manager_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("digital_project_managers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("namespace", sa.String(64), nullable=False, server_default="project"),
        sa.Column(
            "content",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "external_project_id",
            "digital_manager_id",
            "namespace",
            name="uq_project_memory_scope",
        ),
    )
    op.create_table(
        "agent_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_project_id", sa.String(128), nullable=False),
        sa.Column(
            "owner_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("digital_project_managers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("task_type", sa.String(128), nullable=False),
        sa.Column("objective", sa.Text, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="3"),
        sa.Column("risk_level", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="CREATED"),
        sa.Column("escalation_level", sa.String(8), nullable=False, server_default="E0"),
        sa.Column(
            "requires_approval", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("risk_level BETWEEN 0 AND 7", name="ck_task_risk_level"),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name="ck_task_priority"),
    )
    op.create_table(
        "approval_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_project_id", sa.String(128), nullable=False),
        sa.Column("requested_action", sa.Text, nullable=False),
        sa.Column(
            "impact",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("recommendation", sa.Text, nullable=False),
        sa.Column("escalation_level", sa.String(8), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("approver_ref", sa.String(128)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("actor_ref", sa.String(256), nullable=False),
        sa.Column("external_project_id", sa.String(128)),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("entity_type", sa.String(128), nullable=False),
        sa.Column("entity_id", sa.String(128)),
        sa.Column("before_state", postgresql.JSONB),
        sa.Column("after_state", postgresql.JSONB),
        sa.Column(
            "source_refs",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_audit_events_project_time",
        "audit_events",
        ["external_project_id", "occurred_at"],
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_dpm_write() RETURNS trigger AS $$
        DECLARE
            before_row jsonb;
            after_row jsonb;
            row_data jsonb;
            entity_key text;
            project_key text;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                before_row := NULL;
                after_row := to_jsonb(NEW);
                row_data := after_row;
            ELSIF TG_OP = 'UPDATE' THEN
                before_row := to_jsonb(OLD);
                after_row := to_jsonb(NEW);
                row_data := after_row;
            ELSE
                before_row := to_jsonb(OLD);
                after_row := NULL;
                row_data := before_row;
            END IF;

            entity_key := row_data ->> 'id';
            project_key := COALESCE(
                row_data ->> 'external_project_id',
                row_data ->> 'project_id'
            );

            INSERT INTO audit_events (
                actor_ref,
                external_project_id,
                action,
                entity_type,
                entity_id,
                before_state,
                after_state,
                source_refs
            ) VALUES (
                COALESCE(NULLIF(current_setting('app.actor_ref', true), ''), 'system:unknown'),
                project_key,
                TG_OP,
                TG_TABLE_NAME,
                entity_key,
                before_row,
                after_row,
                '[]'::jsonb
            );
            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    # Statikus DDL literálok: a triggerek táblánként explicit néven léteznek,
    # nincs f-string interpoláció és nincs felhasználói bemenet.
    audit_trigger_ddl = {
        "digital_project_managers": """
            CREATE TRIGGER trg_audit_digital_project_managers
            AFTER INSERT OR UPDATE OR DELETE ON digital_project_managers
            FOR EACH ROW EXECUTE FUNCTION audit_dpm_write()
            """,
        "project_assignments": """
            CREATE TRIGGER trg_audit_project_assignments
            AFTER INSERT OR UPDATE OR DELETE ON project_assignments
            FOR EACH ROW EXECUTE FUNCTION audit_dpm_write()
            """,
        "project_memories": """
            CREATE TRIGGER trg_audit_project_memories
            AFTER INSERT OR UPDATE OR DELETE ON project_memories
            FOR EACH ROW EXECUTE FUNCTION audit_dpm_write()
            """,
        "agent_tasks": """
            CREATE TRIGGER trg_audit_agent_tasks
            AFTER INSERT OR UPDATE OR DELETE ON agent_tasks
            FOR EACH ROW EXECUTE FUNCTION audit_dpm_write()
            """,
        "approval_requests": """
            CREATE TRIGGER trg_audit_approval_requests
            AFTER INSERT OR UPDATE OR DELETE ON approval_requests
            FOR EACH ROW EXECUTE FUNCTION audit_dpm_write()
            """,
    }
    for table_name in (
        "digital_project_managers",
        "project_assignments",
        "project_memories",
        "agent_tasks",
        "approval_requests",
    ):
        op.execute(audit_trigger_ddl[table_name])

    connection = op.get_bind()
    connection.execute(
        sa.text("SELECT set_config('app.actor_ref', 'migration:v0.2.0', true)")
    )
    manager_table = sa.table(
        "digital_project_managers",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("human_partner_name", sa.String),
        sa.column("authority_profile", sa.String),
        sa.column("mode", sa.String),
        sa.column("status", sa.String),
    )
    op.bulk_insert(
        manager_table,
        [
            {
                "id": manager_id,
                "slug": slug,
                "name": name,
                "human_partner_name": partner_name,
                "authority_profile": "standard-r0-r7",
                "mode": "limited-autonomy",
                "status": "active",
            }
            for manager_id, slug, name, partner_name in MANAGERS
        ],
    )
    assignment_table = sa.table(
        "project_assignments",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("external_project_id", sa.String),
        sa.column("digital_manager_id", postgresql.UUID(as_uuid=True)),
        sa.column("restrictions", postgresql.JSONB),
    )
    op.bulk_insert(
        assignment_table,
        [
            {
                "id": assignment_id,
                "external_project_id": project_id,
                "digital_manager_id": manager_id,
                "restrictions": {},
            }
            for assignment_id, project_id, manager_id in ASSIGNMENTS
        ],
    )
    memory_table = sa.table(
        "project_memories",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("external_project_id", sa.String),
        sa.column("digital_manager_id", postgresql.UUID(as_uuid=True)),
        sa.column("namespace", sa.String),
        sa.column("content", postgresql.JSONB),
        sa.column("version", sa.Integer),
    )
    op.bulk_insert(
        memory_table,
        [
            {
                "id": f"31111111-1111-4111-8111-11111111110{index}",
                "external_project_id": project_id,
                "digital_manager_id": manager_id,
                "namespace": "project",
                "content": {},
                "version": 1,
            }
            for index, (_, project_id, manager_id) in enumerate(ASSIGNMENTS, start=1)
        ],
    )


def downgrade() -> None:
    drop_trigger_ddl = {
        "approval_requests": "DROP TRIGGER IF EXISTS trg_audit_approval_requests ON approval_requests",
        "agent_tasks": "DROP TRIGGER IF EXISTS trg_audit_agent_tasks ON agent_tasks",
        "project_memories": "DROP TRIGGER IF EXISTS trg_audit_project_memories ON project_memories",
        "project_assignments": "DROP TRIGGER IF EXISTS trg_audit_project_assignments ON project_assignments",
        "digital_project_managers": (
            "DROP TRIGGER IF EXISTS trg_audit_digital_project_managers ON digital_project_managers"
        ),
    }
    for table_name in (
        "approval_requests",
        "agent_tasks",
        "project_memories",
        "project_assignments",
        "digital_project_managers",
    ):
        op.execute(drop_trigger_ddl[table_name])
    op.execute("DROP FUNCTION IF EXISTS audit_dpm_write()")
    op.drop_index("ix_audit_events_project_time", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("approval_requests")
    op.drop_table("agent_tasks")
    op.drop_table("project_memories")
    op.drop_index(
        "uq_project_assignments_active_project",
        table_name="project_assignments",
    )
    op.drop_table("project_assignments")
    op.drop_table("digital_project_managers")
