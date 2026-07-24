from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ManagerOut(ORMModel):
    id: uuid.UUID
    slug: str
    name: str
    human_partner_name: str
    human_manager_ref: str | None
    authority_profile: str
    mode: str
    status: str


class AssignmentCreate(BaseModel):
    external_project_id: str = Field(min_length=1, max_length=128)
    approval_owner_ref: str | None = Field(default=None, max_length=128)
    restrictions: dict[str, Any] = Field(default_factory=dict)


class AssignmentOut(ORMModel):
    id: uuid.UUID
    external_project_id: str
    digital_manager_id: uuid.UUID
    valid_from: datetime
    valid_to: datetime | None
    restrictions: dict[str, Any]
    approval_owner_ref: str | None


class TaskCreate(BaseModel):
    external_project_id: str = Field(min_length=1, max_length=128)
    task_type: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=3, max_length=4000)
    priority: int = Field(default=3, ge=1, le=5)
    risk_level: int = Field(ge=0, le=7)
    impact: dict[str, Any] = Field(default_factory=dict)
    recommendation: str | None = Field(default=None, max_length=4000)


class PolicyDecisionOut(BaseModel):
    allowed: bool
    status: str
    escalation_level: str
    requires_approval: bool
    reason: str


class TaskOut(ORMModel):
    id: uuid.UUID
    external_project_id: str
    owner_agent_id: uuid.UUID
    task_type: str
    objective: str
    priority: int
    risk_level: int
    status: str
    escalation_level: str
    requires_approval: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class TaskCreateResult(BaseModel):
    task: TaskOut
    policy: PolicyDecisionOut
    approval_request_id: uuid.UUID | None = None
    queued: bool = False


class MemoryPatch(BaseModel):
    content: dict[str, Any]
    expected_version: int = Field(ge=1)


class MemoryOut(ORMModel):
    id: uuid.UUID
    external_project_id: str
    digital_manager_id: uuid.UUID
    namespace: str
    content: dict[str, Any]
    version: int
    updated_at: datetime


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(APPROVED|REJECTED)$")
    rationale: str = Field(min_length=3, max_length=4000)


class ApprovalOut(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID
    external_project_id: str
    requested_action: str
    impact: dict[str, Any]
    recommendation: str
    escalation_level: str
    status: str
    approver_ref: str | None
    created_at: datetime


class AuditOut(ORMModel):
    id: int
    actor_ref: str
    external_project_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    source_refs: list[str]
    occurred_at: datetime
