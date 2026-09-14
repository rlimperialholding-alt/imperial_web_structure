from __future__ import annotations

import hmac
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.auth import (
    Actor,
    ensure_role_access,
    require_actor,
    require_manager,
    require_manager_or_service,
)
from app.config import get_settings
from app.operations.factory import get_operational_services
from app.process_cards.adapters import DirectusOperationalCatalogAdapter
from app.schemas import DirectusWebhookEvent

router = APIRouter(prefix="/process-cards", tags=["process-cards"])
settings = get_settings()
operations = get_operational_services()
service = operations.process_cards
catalog_path = operations.catalog_path


class ProcessInput(BaseModel):
    process_key: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    title: str
    trigger: str
    inputs: list[str]
    steps: list[str]
    outputs: list[str]
    stop_conditions: list[str]
    completion_conditions: list[str]
    source_role: str | None = None
    policy_refs: list[str] = Field(default_factory=list)
    source_updated_at: str | None = None
    family: str | None = None
    gate_id: str | None = None
    checklist_template_id: str | None = None
    object_type: str = "BusinessObject"
    participant_roles: list[str] = Field(default_factory=list)
    external_participants: list[str] = Field(default_factory=list)
    approval_role: str | None = None
    checklist_required: bool = False
    source_version: str = "1.0"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalInput(BaseModel):
    approved_by: str | None = None


class ChecklistStartInput(BaseModel):
    object_id: str
    created_by: str | None = None
    object_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/catalog/import")
def import_catalog(_: Actor = Depends(require_manager_or_service)):
    if not catalog_path.exists():
        raise HTTPException(404, "Operational catalog file not found")
    return service.import_catalog(catalog_path, persist=False)


@router.post("/ingest")
def ingest(payload: ProcessInput, _: Actor = Depends(require_manager_or_service)):
    return asdict(service.ingest(payload.model_dump()))


@router.post("/{process_key}/generate")
def generate(
    process_key: str,
    force: bool = False,
    _: Actor = Depends(require_manager_or_service),
):
    try:
        return service.generate(process_key, force=force)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{process_key}/versions/{version}/approve")
def approve(
    process_key: str,
    version: int,
    payload: ApprovalInput,
    actor: Actor = Depends(require_manager),
):
    try:
        return service.approve(process_key, version, actor.subject)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Card version not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{process_key}/checklists/start")
def start_checklist(
    process_key: str,
    payload: ChecklistStartInput,
    actor: Actor = Depends(require_actor),
    x_idempotency_key: str = Header(default="", max_length=200),
):
    template = operations.checklists.template_for_process(process_key, approved_only=True)
    if template is None:
        raise HTTPException(409, "Nincs jóváhagyott checklist-sablon ehhez a folyamathoz.")
    ensure_role_access(actor, template.primary_role)
    if settings.require_idempotency_keys and not x_idempotency_key.strip():
        raise HTTPException(428, "X-Idempotency-Key header is required")
    try:
        return service.start_checklist(
            process_key,
            payload.object_id,
            actor.subject,
            object_type=payload.object_type,
            metadata=payload.metadata,
            idempotency_key=x_idempotency_key.strip() or None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/webhooks/directus", status_code=202)
def directus_operational_webhook(
    event: DirectusWebhookEvent,
    x_directus_secret: str = Header(default=""),
):
    expected = settings.directus_webhook_secret.get_secret_value()
    if not expected or not hmac.compare_digest(expected, x_directus_secret):
        raise HTTPException(status_code=401, detail="Invalid Directus webhook secret")
    if event.collection not in {
        settings.process_catalog_collection,
        settings.checklist_template_collection,
    }:
        return {"accepted": True, "changed": 0}
    adapter = DirectusOperationalCatalogAdapter(
        settings.directus_url,
        settings.directus_static_token.get_secret_value(),
        settings.process_catalog_collection,
        settings.checklist_template_collection,
    )
    imported = service.import_catalog(adapter.fetch_catalog(), persist=False)
    changed = service.regenerate_changed()
    return {"accepted": True, "imported": imported, "changed": len(changed)}


@router.post("/regenerate-changed")
def regenerate_changed(_: Actor = Depends(require_manager_or_service)):
    return service.regenerate_changed()
