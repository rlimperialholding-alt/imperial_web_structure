from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    CanonicalDeliveryRecord,
    CanonicalReconciliationRun,
    EnterpriseCanonicalRecord,
    EventRecord,
    ModuleBusinessRecord,
    ProjectRegistry,
    TaskRecord,
    TechnicalCase,
)
from .canonical_sync_lease import (
    heartbeat_canonical_sync_lease,
    serialized_canonical_sync,
)
from .crm_transport import crm_service_headers

SOURCE_SYSTEM = "imperial-intelligence-platform"
TARGET_SYSTEM = "imperial-sales-crm"
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


class CanonicalBridgeError(RuntimeError):
    pass


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _datetime(value: datetime | None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _external_key(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) <= 255 and _SAFE_KEY.fullmatch(cleaned):
        return cleaned
    return f"sha256:{hashlib.sha256(cleaned.encode('utf-8')).hexdigest()}"


def _envelope(
    *,
    domain: str,
    entity_type: str,
    external_key: str,
    project_id: str | None,
    updated_at: datetime | None,
    payload: dict[str, Any],
    archived: bool = False,
) -> dict[str, Any]:
    payload_json = _dumps(payload)
    payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    source_version = _datetime(updated_at)
    business_key = _external_key(external_key)
    event_hash = hashlib.sha256(
        "|".join(
            (SOURCE_SYSTEM, domain, entity_type, business_key, source_version, payload_sha256)
        ).encode("utf-8")
    ).hexdigest()
    return {
        "eventId": f"ICS-{event_hash}",
        "workspaceId": settings.crm_workspace_id,
        "sourceSystem": SOURCE_SYSTEM,
        "domain": domain,
        "entityType": entity_type,
        "externalKey": business_key,
        "operation": "archive" if archived else "upsert",
        "sourceVersion": source_version,
        "payloadSha256": payload_sha256,
        "payloadJson": payload_json,
        "projectId": project_id,
    }


def collect_canonical_envelopes(db: Session) -> list[dict[str, Any]]:
    envelopes: list[dict[str, Any]] = []
    for canonical_row in db.scalars(
        select(EnterpriseCanonicalRecord)
        .where(
            ~EnterpriseCanonicalRecord.external_key.like("crm:%"),
            ~EnterpriseCanonicalRecord.external_key.like("itep:%"),
        )
        .order_by(EnterpriseCanonicalRecord.id)
    ):
        envelopes.append(
            _envelope(
                domain=canonical_row.domain,
                entity_type=canonical_row.entity_type,
                external_key=f"canonical:{canonical_row.record_id}",
                project_id=canonical_row.project_id,
                updated_at=canonical_row.updated_at,
                archived=canonical_row.status in {"archived", "rolled_back", "deleted"},
                payload={
                    "recordId": canonical_row.record_id,
                    "canonicalName": canonical_row.canonical_name,
                    "status": canonical_row.status,
                    "targetModule": canonical_row.target_module,
                    "data": json.loads(canonical_row.data_json or "{}"),
                    "provenance": json.loads(canonical_row.provenance_json or "{}"),
                },
            )
        )
    for module_row in db.scalars(select(ModuleBusinessRecord).order_by(ModuleBusinessRecord.id)):
        envelopes.append(
            _envelope(
                domain="module_business",
                entity_type=f"{module_row.module_key}_record",
                external_key=f"module:{module_row.module_key}:{module_row.record_id}",
                project_id=module_row.project_id,
                updated_at=module_row.updated_at,
                archived=module_row.archived,
                payload={
                    "recordId": module_row.record_id,
                    "moduleKey": module_row.module_key,
                    "title": module_row.title,
                    "description": module_row.description,
                    "status": module_row.status,
                    "customerReference": module_row.customer_reference,
                    "assignee": module_row.assignee,
                    "priority": module_row.priority,
                    "dueAt": _datetime(module_row.due_at) if module_row.due_at else None,
                    "amountHuf": str(Decimal(module_row.amount_huf or 0)),
                    "version": module_row.version,
                    "data": json.loads(module_row.data_json or "{}"),
                },
            )
        )
    for project_row in db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.id)):
        envelopes.append(
            _envelope(
                domain="project",
                entity_type="project_registry",
                external_key=f"project:{project_row.project_id}",
                project_id=project_row.project_id,
                updated_at=project_row.updated_at,
                archived=project_row.status == "archived",
                payload={
                    "projectId": project_row.project_id,
                    "name": project_row.name,
                    "customerName": project_row.customer_name,
                    "projectType": project_row.project_type,
                    "status": project_row.status,
                    "riskLevel": project_row.risk_level,
                    "blocked": project_row.blocked,
                    "financialImpactHuf": str(Decimal(project_row.financial_impact_huf or 0)),
                    "deadlineImpactDays": project_row.deadline_impact_days,
                    "responsible": project_row.responsible,
                    "nextAction": project_row.next_action,
                },
            )
        )
    for task_row in db.scalars(select(TaskRecord).order_by(TaskRecord.id)):
        envelopes.append(
            _envelope(
                domain="workflow",
                entity_type="platform_task",
                external_key=f"task:{task_row.task_id}",
                project_id=task_row.project_id,
                updated_at=task_row.updated_at,
                archived=task_row.status in {"closed", "cancelled"},
                payload={
                    "taskId": task_row.task_id,
                    "sourceEventId": task_row.source_event_id,
                    "title": task_row.title,
                    "description": task_row.description,
                    "assignee": task_row.assignee,
                    "dueAt": _datetime(task_row.due_at) if task_row.due_at else None,
                    "priority": task_row.priority,
                    "status": task_row.status,
                    "executiveRelevance": task_row.executive_relevance,
                },
            )
        )
    for technical_row in db.scalars(select(TechnicalCase).order_by(TechnicalCase.id)):
        envelopes.append(
            _envelope(
                domain="technical",
                entity_type=technical_row.module_key,
                external_key=f"technical:{technical_row.module_key}:{technical_row.case_id}",
                project_id=technical_row.project_id,
                updated_at=technical_row.updated_at,
                payload={
                    "caseId": technical_row.case_id,
                    "moduleKey": technical_row.module_key,
                    "title": technical_row.title,
                    "version": technical_row.version,
                    "status": technical_row.status,
                    "input": json.loads(technical_row.input_json or "{}"),
                    "result": json.loads(technical_row.result_json or "{}"),
                    "sourceSnapshot": json.loads(technical_row.source_snapshot_json or "{}"),
                    "assignedTo": technical_row.assigned_to,
                    "approvedBy": technical_row.approved_by,
                    "rejectionReason": technical_row.rejection_reason,
                },
            )
        )
    return envelopes


def canonical_integrity_report(db: Session) -> dict[str, Any]:
    """Validate cross-module canonical references without mutating business data."""
    enterprise = list(
        db.scalars(select(EnterpriseCanonicalRecord).order_by(EnterpriseCanonicalRecord.id))
    )
    module_records = list(
        db.scalars(select(ModuleBusinessRecord).order_by(ModuleBusinessRecord.id))
    )
    projects = list(db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.id)))
    tasks = list(db.scalars(select(TaskRecord).order_by(TaskRecord.id)))
    technical = list(db.scalars(select(TechnicalCase).order_by(TechnicalCase.id)))
    events = list(db.scalars(select(EventRecord).order_by(EventRecord.id)))

    project_masters = {row.project_id for row in projects if row.project_id}
    project_masters.update(
        row.project_id for row in enterprise if row.domain == "project" and row.project_id
    )
    references: list[dict[str, str]] = []

    def reference(source: str, record_id: str, project_id: str | None) -> None:
        if project_id:
            references.append({"source": source, "record_id": record_id, "project_id": project_id})

    for enterprise_row in enterprise:
        if enterprise_row.domain != "project":
            reference(
                f"canonical:{enterprise_row.domain}",
                enterprise_row.record_id,
                enterprise_row.project_id,
            )
    for module_row in module_records:
        reference(f"module:{module_row.module_key}", module_row.record_id, module_row.project_id)
    for task_row in tasks:
        reference("platform:task", task_row.task_id, task_row.project_id)
    for technical_row in technical:
        reference(
            f"technical:{technical_row.module_key}",
            technical_row.case_id,
            technical_row.project_id,
        )
    for event_row in events:
        reference(f"event:{event_row.source_module}", event_row.event_id, event_row.project_id)

    missing_project_masters = [
        item for item in references if item["project_id"] not in project_masters
    ]
    linked_by_source = Counter(item["source"] for item in references)
    project_reference_counts = Counter(item["project_id"] for item in references)
    finance_total = sum(1 for row in enterprise if row.domain == "finance") + sum(
        1
        for row in module_records
        if row.module_key in {"finance-intelligence", "financial-control"}
    )
    finance_linked = sum(
        1 for row in enterprise if row.domain == "finance" and row.project_id
    ) + sum(
        1
        for row in module_records
        if row.module_key in {"finance-intelligence", "financial-control"} and row.project_id
    )
    customer_masters = sum(1 for row in enterprise if row.domain == "customer")
    customer_references = sum(1 for row in module_records if row.customer_reference)
    customer_linked = sum(
        1 for row in module_records if row.customer_reference and row.project_id in project_masters
    )
    modules_with_records = {row.module_key for row in module_records} | {
        row.target_module for row in enterprise if row.target_module
    }

    warnings: list[dict[str, Any]] = []
    if finance_total and finance_linked < finance_total:
        warnings.append(
            {
                "code": "FINANCE_WITHOUT_PROJECT",
                "count": finance_total - finance_linked,
                "message": "Penzugyi rekordok ProjectID nelkul; emberi besorolast igenyelnek.",
            }
        )
    if customer_references and customer_linked < customer_references:
        warnings.append(
            {
                "code": "CUSTOMER_REFERENCE_WITHOUT_PROJECT",
                "count": customer_references - customer_linked,
                "message": (
                    "Ugyfelhivatkozassal rendelkezo modulrekordok ervenyes projektkapcsolat nelkul."
                ),
            }
        )

    return {
        "status": "passed" if not missing_project_masters else "attention_required",
        "checked_at": _datetime(datetime.now(UTC)),
        "project_masters": len(project_masters),
        "project_references": len(references),
        "linked_project_references": len(references) - len(missing_project_masters),
        "missing_project_masters": len(missing_project_masters),
        "missing": missing_project_masters[:100],
        "warnings": warnings,
        "finance": {
            "total": finance_total,
            "linked_to_project": finance_linked,
            "unlinked": max(0, finance_total - finance_linked),
        },
        "customers": {
            "canonical_masters": customer_masters,
            "module_references": customer_references,
            "references_with_valid_project": customer_linked,
        },
        "modules_with_canonical_data": len(modules_with_records),
        "linked_by_source": dict(sorted(linked_by_source.items())),
        "project_reference_counts": dict(sorted(project_reference_counts.items())),
    }


def _post_batch(envelopes: list[dict[str, Any]]) -> dict[str, Any]:
    if not settings.crm_write_base_url or len(settings.crm_write_token) < 32:
        raise CanonicalBridgeError("A CRM kanonikus írási kapcsolat nincs konfigurálva.")
    request = urllib.request.Request(
        f"{settings.crm_write_base_url}/api/integrations/platform-canonical",
        data=_dumps({"envelopes": envelopes}).encode("utf-8"),
        headers=crm_service_headers(
            "X-Platform-CRM-Token",
            settings.crm_write_token,
            content_type="application/json",
        ),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise CanonicalBridgeError(
            f"A CRM kanonikus írás {exc.code} hibával leállt: {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CanonicalBridgeError(f"A CRM kanonikus írás nem érhető el: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise CanonicalBridgeError("A CRM kanonikus írás érvénytelen választ adott.")
    return payload


def _read_remote_page(cursor: int, limit: int) -> dict[str, Any]:
    if not settings.crm_read_base_url or len(settings.crm_read_token) < 32:
        raise CanonicalBridgeError("A CRM kanonikus visszaellenőrzése nincs konfigurálva.")
    query = urllib.parse.urlencode(
        {
            "workspaceId": settings.crm_workspace_id,
            "cursor": cursor,
            "limit": limit,
        }
    )
    request = urllib.request.Request(
        f"{settings.crm_read_base_url}/api/integrations/platform-canonical?{query}",
        headers=crm_service_headers("X-ITEP-CRM-Token", settings.crm_read_token),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        raise CanonicalBridgeError(f"A CRM kanonikus visszaellenőrzése sikertelen: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("mirrors"), list):
        raise CanonicalBridgeError("A CRM kanonikus visszaellenőrzése érvénytelen választ adott.")
    return payload


def _itep_identity_headers(permissions: tuple[str, ...] = ("task.read.all",)) -> dict[str, str]:
    if not settings.itep_api_base_url or len(settings.itep_identity_shared_secret) < 32:
        raise CanonicalBridgeError("Az ITEP kanonikus olvasási kapcsolat nincs konfigurálva.")
    now = int(datetime.now(UTC).timestamp())
    identity = {
        "actorId": "platform-canonical-sync",
        "organizationId": "imperial-holding",
        "roles": ["SYSTEM"],
        "permissions": list(permissions),
        "issuedAt": now,
        "expiresAt": now + 120,
        "nonce": str(uuid.uuid4()),
    }
    encoded = base64.urlsafe_b64encode(_dumps(identity).encode("utf-8")).decode("ascii").rstrip("=")
    signature = hmac.new(
        settings.itep_identity_shared_secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Accept": "application/json",
        "X-Imperial-Identity": encoded,
        "X-Imperial-Identity-Signature": f"sha256={signature}",
    }


def _read_itep_tasks(cursor: str | None, limit: int) -> dict[str, Any]:
    query: dict[str, str | int] = {"limit": limit}
    if cursor:
        query["cursor"] = cursor
    request = urllib.request.Request(
        f"{settings.itep_api_base_url.rstrip('/')}/v1/integrations/canonical/tasks?"
        f"{urllib.parse.urlencode(query)}",
        headers=_itep_identity_headers(),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        raise CanonicalBridgeError(f"Az ITEP kanonikus task export sikertelen: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise CanonicalBridgeError("Az ITEP kanonikus task export érvénytelen választ adott.")
    return payload


def _post_itep_event(payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{settings.itep_api_base_url.rstrip('/')}/v1/orchestration/events",
        data=_dumps(payload).encode("utf-8"),
        headers={
            **_itep_identity_headers(("task.create", "task.read.all", "task.transition.all")),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise CanonicalBridgeError(
            f"Az ITEP eseményátadás {exc.code} hibával leállt: {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CanonicalBridgeError(f"Az ITEP eseményátadás sikertelen: {exc}") from exc
    if not isinstance(result, dict) or not isinstance(result.get("taskIds"), list):
        raise CanonicalBridgeError("Az ITEP eseményátadás érvénytelen választ adott.")
    return result


@serialized_canonical_sync("itep-push")
def push_platform_events_to_itep(
    db: Session,
    *,
    post_event: Callable[[dict[str, Any]], dict[str, Any]] = _post_itep_event,
) -> dict[str, int]:
    counts = {"source": 0, "applied": 0, "idempotent": 0, "failed": 0}
    for event in db.scalars(select(EventRecord).order_by(EventRecord.id)):
        payload = {
            "organizationId": "imperial-holding",
            "source": "imperial-intelligence-platform",
            "externalEventId": event.event_id,
            "eventType": event.event_type,
            "projectId": event.project_id,
            "ownerId": event.responsible or "system-business-review",
            "occurredAt": _datetime(event.occurred_at),
            "title": event.next_action or event.event_type.replace("_", " ").title(),
            "payload": {
                **json.loads(event.payload_json or "{}"),
                "severity": event.severity,
                "financialImpactHuf": str(Decimal(event.financial_impact_huf or 0)),
                "deadlineImpactDays": event.deadline_impact_days,
                "sourceModule": event.source_module,
                "objectType": event.object_type,
                "objectId": event.object_id,
            },
        }
        payload_json = _dumps(payload)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        delivery_event_id = f"ITEO-{hashlib.sha256(event.event_id.encode()).hexdigest()}"
        delivery = db.scalar(
            select(CanonicalDeliveryRecord).where(
                CanonicalDeliveryRecord.event_id == delivery_event_id
            )
        )
        if delivery is None:
            delivery = CanonicalDeliveryRecord(
                event_id=delivery_event_id,
                target_system="itep-core",
                domain="event",
                entity_type=event.event_type,
                external_key=event.event_id,
                source_version=_datetime(event.occurred_at),
                payload_sha256=payload_hash,
                payload_json=payload_json,
                project_id=event.project_id,
                status="pending",
            )
            db.add(delivery)
            db.flush()
        counts["source"] += 1
        if delivery.status == "applied":
            counts["idempotent"] += 1
            continue
        try:
            result = post_event(payload)
            delivery.attempt_count += 1
            delivery.status = "applied"
            delivery.remote_id = str(result.get("eventId") or "") or None
            delivery.last_error = None
            delivery.delivered_at = datetime.now(UTC)
            counts["idempotent" if result.get("idempotent") else "applied"] += 1
        except Exception as exc:
            delivery.attempt_count += 1
            delivery.status = "failed"
            delivery.last_error = str(exc)[:2000]
            counts["failed"] += 1
        db.commit()
        heartbeat_canonical_sync_lease()
    return counts


@serialized_canonical_sync("itep-pull")
def pull_itep_tasks_to_platform(
    db: Session,
    *,
    read_page: Callable[[str | None, int], dict[str, Any]] = _read_itep_tasks,
) -> dict[str, int]:
    existing = {
        row.external_key: row
        for row in db.scalars(
            select(EnterpriseCanonicalRecord).where(
                EnterpriseCanonicalRecord.domain == "workflow",
                EnterpriseCanonicalRecord.entity_type == "itep_task",
            )
        )
    }
    counts = {"source": 0, "inserted": 0, "updated": 0, "unchanged": 0, "conflicts": 0}
    cursor: str | None = None
    while True:
        page = read_page(cursor, 200)
        for item in page["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
                raise CanonicalBridgeError("Az ITEP kanonikus task rekord nem objektum.")
            external_key = str(item.get("externalKey") or "")
            source_version = str(item.get("sourceVersion") or "")
            source_hash = str(item.get("payloadSha256") or "")
            payload = item["payload"]
            payload_json = _dumps(payload)
            computed_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            if not external_key.startswith("itep:task:") or source_hash != computed_hash:
                raise CanonicalBridgeError("Az ITEP task üzleti kulcsa vagy SHA-256 értéke hibás.")
            project_ids = payload.get("projectIds")
            project_id = (
                str(project_ids[0])[:100] if isinstance(project_ids, list) and project_ids else None
            )
            provenance = _dumps(
                {
                    "source": "itep-core",
                    "source_version": source_version,
                    "payload_sha256": source_hash,
                    "synced_at": _datetime(datetime.now(UTC)),
                }
            )
            current = existing.get(external_key)
            if current is None:
                record_hash = hashlib.sha256(external_key.encode("utf-8")).hexdigest()[:24]
                current = EnterpriseCanonicalRecord(
                    record_id=f"ITEP-TASK-{record_hash}",
                    domain="workflow",
                    entity_type="itep_task",
                    external_key=external_key,
                    canonical_name=str(payload.get("title") or external_key)[:500],
                    project_id=project_id,
                    target_module="smart-calendar",
                    status=str(payload.get("status") or "active")[:30],
                    data_json=payload_json,
                    provenance_json=provenance,
                )
                db.add(current)
                existing[external_key] = current
                counts["inserted"] += 1
            else:
                old_provenance = json.loads(current.provenance_json or "{}")
                old_version = str(old_provenance.get("source_version") or "")
                old_hash = str(old_provenance.get("payload_sha256") or "")
                if source_version == old_version and source_hash != old_hash:
                    counts["conflicts"] += 1
                elif source_version < old_version:
                    counts["conflicts"] += 1
                elif source_hash == old_hash:
                    counts["unchanged"] += 1
                else:
                    current.canonical_name = str(payload.get("title") or external_key)[:500]
                    current.project_id = project_id
                    current.status = str(payload.get("status") or "active")[:30]
                    current.data_json = payload_json
                    current.provenance_json = provenance
                    counts["updated"] += 1
            counts["source"] += 1
        heartbeat_canonical_sync_lease()
        next_cursor = page.get("nextCursor")
        if next_cursor is None:
            break
        if not isinstance(next_cursor, str) or next_cursor == cursor:
            raise CanonicalBridgeError("Az ITEP task export lapozása nem monoton.")
        cursor = next_cursor
    db.commit()
    return counts


@serialized_canonical_sync("crm-push")
def push_canonical_to_crm(
    db: Session,
    *,
    post_batch: Callable[[list[dict[str, Any]]], dict[str, Any]] = _post_batch,
    batch_size: int = 10,
) -> dict[str, Any]:
    envelopes = collect_canonical_envelopes(db)
    pending: list[dict[str, Any]] = []
    deliveries: dict[str, CanonicalDeliveryRecord] = {}
    for envelope in envelopes:
        delivery = db.scalar(
            select(CanonicalDeliveryRecord).where(
                CanonicalDeliveryRecord.event_id == envelope["eventId"]
            )
        )
        if delivery is None:
            for obsolete in db.scalars(
                select(CanonicalDeliveryRecord).where(
                    CanonicalDeliveryRecord.target_system == TARGET_SYSTEM,
                    CanonicalDeliveryRecord.external_key == envelope["externalKey"],
                    CanonicalDeliveryRecord.status == "failed",
                    CanonicalDeliveryRecord.event_id != envelope["eventId"],
                )
            ):
                obsolete.status = "superseded"
                obsolete.last_error = "A rekord új, normalizált kanonikus verzióval újrakézbesítve."
            delivery = CanonicalDeliveryRecord(
                event_id=envelope["eventId"],
                target_system=TARGET_SYSTEM,
                domain=envelope["domain"],
                entity_type=envelope["entityType"],
                external_key=envelope["externalKey"],
                source_version=envelope["sourceVersion"],
                payload_sha256=envelope["payloadSha256"],
                payload_json=envelope["payloadJson"],
                project_id=envelope.get("projectId"),
                status="pending",
            )
            db.add(delivery)
            db.flush()
        deliveries[envelope["eventId"]] = delivery
        if delivery.status != "applied":
            pending.append(envelope)
    db.commit()

    summary = {
        "local": len(envelopes),
        "pending": len(pending),
        "applied": 0,
        "conflicts": 0,
        "rejected": 0,
        "failed": 0,
    }
    for offset in range(0, len(pending), max(1, min(batch_size, 200))):
        batch = pending[offset : offset + batch_size]
        try:
            response = post_batch(batch)
            result_map = {
                item.get("eventId"): item for item in response["results"] if isinstance(item, dict)
            }
            for envelope in batch:
                delivery = deliveries[envelope["eventId"]]
                delivery.attempt_count += 1
                result = result_map.get(envelope["eventId"])
                if not result:
                    delivery.status = "failed"
                    delivery.last_error = "MISSING_REMOTE_RESULT"
                    summary["failed"] += 1
                    continue
                status = str(result.get("status") or "failed")
                delivery.status = status
                delivery.remote_id = result.get("mirrorId")
                delivery.last_error = result.get("reason")
                if status == "applied":
                    delivery.delivered_at = datetime.now(UTC)
                    summary["applied"] += 1
                elif status == "conflict":
                    summary["conflicts"] += 1
                elif status == "rejected":
                    summary["rejected"] += 1
                else:
                    summary["failed"] += 1
            db.commit()
            heartbeat_canonical_sync_lease()
        except Exception as exc:
            for envelope in batch:
                delivery = deliveries[envelope["eventId"]]
                delivery.attempt_count += 1
                delivery.status = "failed"
                delivery.last_error = str(exc)[:2000]
                summary["failed"] += 1
            db.commit()
            if isinstance(exc, CanonicalBridgeError):
                raise
            raise CanonicalBridgeError(str(exc)) from exc
    return summary


@serialized_canonical_sync("crm-reconcile")
def reconcile_canonical_with_crm(
    db: Session,
    *,
    read_page: Callable[[int, int], dict[str, Any]] = _read_remote_page,
) -> dict[str, Any]:
    run = CanonicalReconciliationRun(
        run_id=f"RECON-{uuid.uuid4().hex.upper()}",
        target_system=TARGET_SYSTEM,
        status="processing",
    )
    db.add(run)
    db.flush()
    local = {
        (item["domain"], item["entityType"], item["externalKey"]): item
        for item in collect_canonical_envelopes(db)
    }
    remote: dict[tuple[str, str, str], dict[str, Any]] = {}
    cursor = 0
    conflict_count = 0
    try:
        while True:
            page = read_page(cursor, 200)
            conflict_count = max(conflict_count, int(page.get("counts", {}).get("conflicts") or 0))
            for item in page["mirrors"]:
                if item.get("sourceSystem") == SOURCE_SYSTEM:
                    remote[
                        (
                            str(item.get("domain")),
                            str(item.get("entityType")),
                            str(item.get("externalKey")),
                        )
                    ] = item
            heartbeat_canonical_sync_lease()
            next_cursor = page.get("nextCursor")
            if next_cursor is None:
                break
            if not isinstance(next_cursor, int) or next_cursor <= cursor:
                raise CanonicalBridgeError("A CRM egyeztetési lapozása nem monoton.")
            cursor = next_cursor
        matching = sum(
            1
            for key, item in local.items()
            if key in remote and remote[key].get("payloadSha256") == item["payloadSha256"]
        )
        mismatches = [
            {"domain": key[0], "entityType": key[1], "externalKey": key[2]}
            for key, item in local.items()
            if key in remote and remote[key].get("payloadSha256") != item["payloadSha256"]
        ]
        missing = [
            {"domain": key[0], "entityType": key[1], "externalKey": key[2]}
            for key in local
            if key not in remote
        ]
        status = (
            "passed"
            if not missing and not mismatches and conflict_count == 0
            else "attention_required"
        )
        summary = {
            "run_id": run.run_id,
            "status": status,
            "local": len(local),
            "remote": len(remote),
            "matching": matching,
            "missing_remote": len(missing),
            "hash_mismatch": len(mismatches),
            "conflicts": conflict_count,
            "missing": missing[:100],
            "mismatches": mismatches[:100],
        }
        run.status = status
        run.local_count = len(local)
        run.remote_count = len(remote)
        run.matching_count = matching
        run.missing_remote_count = len(missing)
        run.hash_mismatch_count = len(mismatches)
        run.conflict_count = conflict_count
        run.summary_json = _dumps(summary)
        run.completed_at = datetime.now(UTC)
        db.commit()
        return summary
    except Exception as exc:
        run.status = "failed"
        run.summary_json = _dumps({"error": str(exc)[:2000]})
        run.completed_at = datetime.now(UTC)
        db.commit()
        if isinstance(exc, CanonicalBridgeError):
            raise
        raise CanonicalBridgeError(str(exc)) from exc
