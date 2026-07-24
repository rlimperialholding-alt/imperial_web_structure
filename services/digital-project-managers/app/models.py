from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DigitalProjectManager(Base):
    __tablename__ = "digital_project_managers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    human_partner_name: Mapped[str] = mapped_column(String(128), nullable=False)
    human_manager_ref: Mapped[str | None] = mapped_column(String(128))
    authority_profile: Mapped[str] = mapped_column(
        String(64), nullable=False, default="standard-r0-r7"
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="limited-autonomy")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    assignments: Mapped[list[ProjectAssignment]] = relationship(back_populates="manager")


class ProjectAssignment(Base):
    __tablename__ = "project_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    digital_manager_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("digital_project_managers.id", ondelete="RESTRICT"), nullable=False
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restrictions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    approval_owner_ref: Mapped[str | None] = mapped_column(String(128))

    manager: Mapped[DigitalProjectManager] = relationship(back_populates="assignments")

    __table_args__ = (
        Index(
            "uq_project_assignments_active_project",
            "external_project_id",
            unique=True,
            postgresql_where=(valid_to.is_(None)),
        ),
    )


class ProjectMemory(Base):
    __tablename__ = "project_memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    digital_manager_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("digital_project_managers.id", ondelete="RESTRICT"), nullable=False
    )
    namespace: Mapped[str] = mapped_column(String(64), nullable=False, default="project")
    content: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "external_project_id",
            "digital_manager_id",
            "namespace",
            name="uq_project_memory_scope",
        ),
    )


class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("digital_project_managers.id", ondelete="RESTRICT"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(128), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    escalation_level: Mapped[str] = mapped_column(String(8), nullable=False, default="E0")
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("risk_level BETWEEN 0 AND 7", name="ck_task_risk_level"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_task_priority"),
    )


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False
    )
    external_project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_action: Mapped[str] = mapped_column(Text, nullable=False)
    impact: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    escalation_level: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    approver_ref: Mapped[str | None] = mapped_column(String(128))
    decision_rationale: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_project_id: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0")
    precedence: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "precedence BETWEEN 0 AND 1000",
            name="ck_knowledge_document_precedence",
        ),
        Index(
            "ix_knowledge_documents_project_precedence",
            "external_project_id",
            "precedence",
        ),
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    external_project_id: Mapped[str | None] = mapped_column(String(128))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "sequence",
            name="uq_knowledge_chunk_sequence",
        ),
        Index("ix_knowledge_chunks_project", "external_project_id"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    external_project_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(128))
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_refs: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
