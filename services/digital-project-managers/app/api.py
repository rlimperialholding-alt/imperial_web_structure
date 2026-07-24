from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.platform import PlatformModelAdapter
from app.auth import (
    Principal,
    enforce_project_access,
    require_scope,
)
from app.config import get_settings
from app.db import get_session, set_audit_actor
from app.models import (
    AgentTask,
    ApprovalRequest,
    AuditEvent,
    DigitalProjectManager,
    ProjectAssignment,
    ProjectMemory,
)
from app.policy import evaluate_risk
from app.queue import enqueue_task
from app.schemas import (
    ApprovalDecision,
    ApprovalOut,
    AssignmentCreate,
    AssignmentOut,
    AuditOut,
    ManagerOut,
    MemoryOut,
    MemoryPatch,
    PolicyDecisionOut,
    TaskCreate,
    TaskCreateResult,
    TaskOut,
)

router = APIRouter(prefix="/api/v1")


def get_platform_adapter() -> PlatformModelAdapter:
    return PlatformModelAdapter(get_settings().platform_data_path)


@router.get("/agents", response_model=list[ManagerOut])
def list_agents(
    session: Session = Depends(get_session),
    _: Principal = Depends(require_scope("digital-pm:read")),
) -> list[DigitalProjectManager]:
    return list(session.scalars(select(DigitalProjectManager).order_by(DigitalProjectManager.slug)))


@router.get("/agents/{agent_id}", response_model=ManagerOut)
def get_agent(
    agent_id: uuid.UUID,
    session: Session = Depends(get_session),
    _: Principal = Depends(require_scope("digital-pm:read")),
) -> DigitalProjectManager:
    manager = session.get(DigitalProjectManager, agent_id)
    if manager is None:
        raise HTTPException(status_code=404, detail="Digital project manager not found")
    return manager


@router.post(
    "/agents/{agent_id}/assignments",
    response_model=AssignmentOut,
    status_code=status.HTTP_201_CREATED,
)
def assign_project(
    agent_id: uuid.UUID,
    request: AssignmentCreate,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_scope("digital-pm:write")),
    platform: PlatformModelAdapter = Depends(get_platform_adapter),
) -> ProjectAssignment:
    enforce_project_access(principal, request.external_project_id)
    manager = session.get(DigitalProjectManager, agent_id)
    if manager is None:
        raise HTTPException(status_code=404, detail="Digital project manager not found")
    if platform.get_project(request.external_project_id) is None:
        raise HTTPException(status_code=404, detail="Canonical project not found")
    if request.approval_owner_ref and platform.get_user(request.approval_owner_ref) is None:
        raise HTTPException(status_code=404, detail="Canonical approval owner not found")

    set_audit_actor(session, principal.subject)
    current = session.scalar(
        select(ProjectAssignment).where(
            ProjectAssignment.external_project_id == request.external_project_id,
            ProjectAssignment.valid_to.is_(None),
        )
    )
    if current and current.digital_manager_id == agent_id:
        return current
    if current:
        current.valid_to = datetime.now(UTC)
    assignment = ProjectAssignment(
        external_project_id=request.external_project_id,
        digital_manager_id=agent_id,
        restrictions=request.restrictions,
        approval_owner_ref=request.approval_owner_ref,
    )
    session.add(assignment)
    memory = session.scalar(
        select(ProjectMemory).where(
            ProjectMemory.external_project_id == request.external_project_id,
            ProjectMemory.digital_manager_id == agent_id,
            ProjectMemory.namespace == "project",
        )
    )
    if memory is None:
        session.add(
            ProjectMemory(
                external_project_id=request.external_project_id,
                digital_manager_id=agent_id,
                namespace="project",
                content={},
            )
        )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="Assignment conflict") from error
    session.refresh(assignment)
    return assignment


@router.get("/projects/{project_id}/context")
def project_context(
    project_id: str,
    principal: Principal = Depends(require_scope("digital-pm:read")),
    platform: PlatformModelAdapter = Depends(get_platform_adapter),
) -> dict[str, object]:
    enforce_project_access(principal, project_id)
    context = platform.project_context(project_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Canonical project not found")
    return context


@router.get(
    "/agents/{agent_id}/projects/{project_id}/memory",
    response_model=MemoryOut,
)
def get_memory(
    agent_id: uuid.UUID,
    project_id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_scope("digital-pm:read")),
) -> ProjectMemory:
    enforce_project_access(principal, project_id)
    memory = session.scalar(
        select(ProjectMemory).where(
            ProjectMemory.external_project_id == project_id,
            ProjectMemory.digital_manager_id == agent_id,
            ProjectMemory.namespace == "project",
        )
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Project memory not found")
    return memory


@router.patch(
    "/agents/{agent_id}/projects/{project_id}/memory",
    response_model=MemoryOut,
)
def update_memory(
    agent_id: uuid.UUID,
    project_id: str,
    request: MemoryPatch,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_scope("digital-pm:write")),
) -> ProjectMemory:
    enforce_project_access(principal, project_id)
    memory = session.scalar(
        select(ProjectMemory)
        .where(
            ProjectMemory.external_project_id == project_id,
            ProjectMemory.digital_manager_id == agent_id,
            ProjectMemory.namespace == "project",
        )
        .with_for_update()
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Project memory not found")
    if memory.version != request.expected_version:
        raise HTTPException(status_code=409, detail="Project memory version conflict")
    set_audit_actor(session, principal.subject)
    memory.content = request.content
    memory.version += 1
    session.commit()
    session.refresh(memory)
    return memory


@router.post(
    "/agents/{agent_id}/tasks",
    response_model=TaskCreateResult,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    agent_id: uuid.UUID,
    request: TaskCreate,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_scope("digital-pm:write")),
    platform: PlatformModelAdapter = Depends(get_platform_adapter),
) -> TaskCreateResult:
    enforce_project_access(principal, request.external_project_id)
    if platform.get_project(request.external_project_id) is None:
        raise HTTPException(status_code=404, detail="Canonical project not found")
    assignment = session.scalar(
        select(ProjectAssignment).where(
            ProjectAssignment.external_project_id == request.external_project_id,
            ProjectAssignment.digital_manager_id == agent_id,
            ProjectAssignment.valid_to.is_(None),
        )
    )
    if assignment is None:
        raise HTTPException(status_code=409, detail="Project is not assigned to agent")
    decision = evaluate_risk(request.risk_level)
    task = AgentTask(
        external_project_id=request.external_project_id,
        owner_agent_id=agent_id,
        task_type=request.task_type,
        objective=request.objective,
        priority=request.priority,
        risk_level=request.risk_level,
        status=decision.status,
        escalation_level=decision.escalation_level,
        requires_approval=decision.requires_approval,
        created_by=principal.subject,
    )
    set_audit_actor(session, principal.subject)
    session.add(task)
    session.flush()
    approval: ApprovalRequest | None = None
    if decision.requires_approval:
        approval = ApprovalRequest(
            task_id=task.id,
            external_project_id=request.external_project_id,
            requested_action=request.objective,
            impact=request.impact,
            recommendation=request.recommendation or decision.reason,
            escalation_level=decision.escalation_level,
            approver_ref=assignment.approval_owner_ref,
        )
        session.add(approval)
    session.commit()
    session.refresh(task)
    queued = enqueue_task(task.id) if decision.allowed else False
    return TaskCreateResult(
        task=TaskOut.model_validate(task),
        policy=PolicyDecisionOut(
            allowed=decision.allowed,
            status=decision.status,
            escalation_level=decision.escalation_level,
            requires_approval=decision.requires_approval,
            reason=decision.reason,
        ),
        approval_request_id=approval.id if approval else None,
        queued=queued,
    )


@router.get("/agents/{agent_id}/workqueue", response_model=list[TaskOut])
def workqueue(
    agent_id: uuid.UUID,
    project_id: str | None = None,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_scope("digital-pm:read")),
) -> list[AgentTask]:
    statement = select(AgentTask).where(AgentTask.owner_agent_id == agent_id)
    if project_id:
        enforce_project_access(principal, project_id)
        statement = statement.where(AgentTask.external_project_id == project_id)
    elif principal.role != "platform-admin":
        statement = statement.where(AgentTask.external_project_id.in_(principal.project_ids))
    return list(session.scalars(statement.order_by(AgentTask.created_at.desc())))


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalOut)
def decide_approval(
    approval_id: uuid.UUID,
    request: ApprovalDecision,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_scope("digital-pm:approve")),
) -> ApprovalRequest:
    approval = session.get(ApprovalRequest, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    enforce_project_access(principal, approval.external_project_id)
    if approval.status != "PENDING":
        raise HTTPException(status_code=409, detail="Approval already decided")
    set_audit_actor(session, principal.subject)
    approval.status = request.decision
    approval.approver_ref = principal.subject
    task = session.get(AgentTask, approval.task_id)
    if task is None:
        raise HTTPException(status_code=409, detail="Approval task is missing")
    if request.decision == "REJECTED":
        task.status = "CANCELLED"
    elif task.risk_level >= 6:
        task.status = "WAITING_APPROVAL"
    else:
        task.status = "READY"
        task.requires_approval = False
    session.commit()
    session.refresh(approval)
    return approval


@router.get("/audit/events", response_model=list[AuditOut])
def audit_events(
    project_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_scope("digital-pm:audit")),
) -> list[AuditEvent]:
    statement = select(AuditEvent)
    if project_id:
        enforce_project_access(principal, project_id)
        statement = statement.where(AuditEvent.external_project_id == project_id)
    elif principal.role != "platform-admin":
        statement = statement.where(AuditEvent.external_project_id.in_(principal.project_ids))
    return list(session.scalars(statement.order_by(AuditEvent.occurred_at.desc()).limit(limit)))
