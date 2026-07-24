from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.auth import Actor, ensure_role_access, require_actor, require_manager
from app.checklists.domain import ChecklistAnswer
from app.checklists.service import ChecklistValidationError
from app.config import get_settings
from app.operations.factory import get_operational_services

router = APIRouter(prefix="/checklists", tags=["checklists"])
service = get_operational_services().checklists
settings = get_settings()


class InstanceCreate(BaseModel):
    process_key: str
    object_id: str
    created_by: str | None = None
    object_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ItemAnswerInput(BaseModel):
    answer: ChecklistAnswer
    answered_by: str | None = None
    note: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    action_owner_role: str | None = None
    action_due_date: str | None = None


class EvidenceInput(BaseModel):
    evidence_ids: list[str] = Field(min_length=1)


class SubmitInput(BaseModel):
    submitted_by: str | None = None


class ApproveInput(BaseModel):
    approved_by: str | None = None


def _load_instance_with_access(instance_id: str, actor: Actor):
    try:
        instance = service.store.load_instance(instance_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Checklist instance not found") from exc
    ensure_role_access(actor, instance.role)
    return instance


@router.get("/templates")
def list_templates(_: Actor = Depends(require_actor)):
    return [template.to_dict() for template in service.store.list_templates()]


@router.get("/templates/process/{process_key}")
def get_template_for_process(process_key: str, _: Actor = Depends(require_actor)):
    template = service.template_for_process(process_key)
    if template is None:
        raise HTTPException(404, "Checklist template not found")
    return template.to_dict()


@router.post("/instances")
def create_instance(
    payload: InstanceCreate,
    actor: Actor = Depends(require_actor),
    x_idempotency_key: str = Header(default="", max_length=200),
):
    template = service.template_for_process(payload.process_key, approved_only=True)
    if template is None:
        raise HTTPException(409, "Nincs jóváhagyott checklist-sablon ehhez a folyamathoz.")
    ensure_role_access(actor, template.primary_role)
    if settings.require_idempotency_keys and not x_idempotency_key.strip():
        raise HTTPException(428, "X-Idempotency-Key header is required")
    try:
        return service.start_instance(
            payload.process_key,
            payload.object_id,
            actor.subject,
            object_type=payload.object_type,
            metadata=payload.metadata,
            idempotency_key=x_idempotency_key.strip() or None,
        ).to_dict()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ChecklistValidationError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/instances/{instance_id}")
def get_instance(instance_id: str, actor: Actor = Depends(require_actor)):
    return _load_instance_with_access(instance_id, actor).to_dict()


@router.put("/instances/{instance_id}/items/{item_id}")
def answer_item(
    instance_id: str,
    item_id: str,
    payload: ItemAnswerInput,
    actor: Actor = Depends(require_actor),
):
    _load_instance_with_access(instance_id, actor)
    try:
        return service.answer_item(
            instance_id,
            item_id,
            payload.answer,
            answered_by=actor.subject,
            note=payload.note,
            evidence_ids=payload.evidence_ids,
            action_owner_role=payload.action_owner_role,
            action_due_date=payload.action_due_date,
        ).to_dict()
    except KeyError as exc:
        raise HTTPException(404, "Checklist item not found") from exc
    except ChecklistValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/instances/{instance_id}/evidence")
def add_evidence(
    instance_id: str,
    payload: EvidenceInput,
    actor: Actor = Depends(require_actor),
):
    _load_instance_with_access(instance_id, actor)
    return service.add_evidence(instance_id, payload.evidence_ids).to_dict()


@router.post("/instances/{instance_id}/submit")
def submit(
    instance_id: str,
    payload: SubmitInput,
    actor: Actor = Depends(require_actor),
):
    _load_instance_with_access(instance_id, actor)
    try:
        return service.submit(instance_id, actor.subject)
    except ChecklistValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/instances/{instance_id}/approve")
def approve(
    instance_id: str,
    payload: ApproveInput,
    actor: Actor = Depends(require_manager),
):
    try:
        return service.approve_instance(instance_id, actor.subject)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Checklist instance not found") from exc
    except ChecklistValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/instances/{instance_id}/gate")
def gate_status(instance_id: str, actor: Actor = Depends(require_actor)):
    _load_instance_with_access(instance_id, actor)
    return service.gate_status(instance_id)
