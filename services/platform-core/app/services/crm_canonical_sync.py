from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import EnterpriseCanonicalRecord, ImportDataSource, ImportJob
from .canonical_sync_lease import (
    heartbeat_canonical_sync_lease,
    serialized_canonical_sync,
)
from .crm_transport import crm_service_headers
from .itep_finance import ItepFinanceError, incoming_invoices


class CrmCanonicalSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class EntityProfile:
    domain: str
    entity_type: str
    target_module: str
    name_fields: tuple[str, ...]
    project_fields: tuple[str, ...] = ()
    status_fields: tuple[str, ...] = ()


ENTITY_PROFILES: dict[str, EntityProfile] = {
    "leads": EntityProfile("customer", "lead", "crm", ("name", "email"), status_fields=("stage",)),
    "customers": EntityProfile(
        "customer", "customer", "crm", ("name", "email"), status_fields=("status",)
    ),
    "customer_imports": EntityProfile(
        "customer", "customer_source", "crm", ("externalId", "sourceKind")
    ),
    "business_partners": EntityProfile(
        "partner", "company", "partner-connect", ("name", "email"), status_fields=("recordStatus",)
    ),
    "business_projects": EntityProfile(
        "project",
        "project",
        "project-control",
        ("title", "externalKey"),
        project_fields=("externalKey",),
        status_fields=("projectStatus",),
    ),
    "projects": EntityProfile(
        "project",
        "client_project",
        "project-control",
        ("title", "portalCode"),
        project_fields=("id",),
        status_fields=("status",),
    ),
    "contracts": EntityProfile(
        "contract",
        "contract",
        "contract-generator",
        ("title", "contractNumber"),
        project_fields=("projectId",),
        status_fields=("status",),
    ),
    "invoices": EntityProfile(
        "finance",
        "supplier_invoice",
        "financial-control",
        ("invoiceNumber", "buyerName", "sellerName"),
        project_fields=("projectId",),
        status_fields=("customerMatchStatus",),
    ),
    "cashflow": EntityProfile(
        "finance",
        "cashflow_entry",
        "financial-control",
        ("description", "counterparty"),
        project_fields=("projectId",),
        status_fields=("status",),
    ),
    "migration_documents": EntityProfile(
        "document", "migration_document", "document-center", ("title", "fileName")
    ),
    "review_items": EntityProfile(
        "data_quality",
        "import_review",
        "import-center",
        ("summary", "reasonCode"),
        status_fields=("status",),
    ),
}

SOURCE_RECORD_PROFILES: dict[str, EntityProfile] = {
    "customer_source": EntityProfile("customer", "customer_source_evidence", "crm", ("title",)),
    "lead_source": EntityProfile("customer", "lead_source_evidence", "crm", ("title",)),
    "project": EntityProfile("project", "project_source_evidence", "project-control", ("title",)),
    "contract": EntityProfile(
        "contract", "contract_source_evidence", "contract-generator", ("title",)
    ),
    "project_document": EntityProfile(
        "document", "project_document_evidence", "document-center", ("title",)
    ),
    "invoice_source": EntityProfile(
        "finance", "invoice_source_evidence", "financial-control", ("title",)
    ),
    "partner_source": EntityProfile(
        "partner", "partner_source_evidence", "partner-connect", ("title",)
    ),
    "restricted_source": EntityProfile(
        "document", "restricted_source_evidence", "document-evidence", ("title",)
    ),
    "other": EntityProfile("document", "source_evidence", "document-evidence", ("title",)),
}

SYNC_ENTITIES = (*ENTITY_PROFILES.keys(), "source_records")
SOURCE_KEY = "crm-migrated-data"
ITEP_INVOICE_PROFILE = EntityProfile(
    "finance",
    "incoming_invoice",
    "financial-control",
    ("invoiceNumber", "partnerName"),
    status_fields=("paymentStatus",),
)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _manual_allocation(row: EnterpriseCanonicalRecord | None) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        provenance = json.loads(row.provenance_json or "{}")
    except json.JSONDecodeError:
        return None
    allocation = provenance.get("manualAllocation") if isinstance(provenance, dict) else None
    return allocation if isinstance(allocation, dict) else None


def _source_provenance(
    row: EnterpriseCanonicalRecord | None, payload: dict[str, Any]
) -> str:
    allocation = _manual_allocation(row)
    if allocation is not None:
        payload["manualAllocation"] = allocation
    return _dumps(payload)


def _first(row: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _profile(entity: str, row: dict[str, Any]) -> EntityProfile:
    if entity == "source_records":
        return SOURCE_RECORD_PROFILES.get(
            str(row.get("recordType") or "other"), SOURCE_RECORD_PROFILES["other"]
        )
    return ENTITY_PROFILES[entity]


def _external_key(entity: str, row: dict[str, Any]) -> str:
    source_id = row.get("id")
    if source_id in (None, ""):
        source_id = row.get("externalId") or row.get("externalKey") or row.get("invoiceNumber")
    if source_id in (None, ""):
        source_id = hashlib.sha256(_dumps(row).encode("utf-8")).hexdigest()[:24]
    value = f"crm:{entity}:{source_id}"
    if len(value) <= 255:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"crm:{entity}:sha256:{digest}"


def _limited(value: str | None, length: int) -> str | None:
    return value[:length] if value else None


def _safe_error(exc: Exception) -> str:
    message = str(exc).split("\n[SQL:", maxsplit=1)[0].strip()
    return f"{exc.__class__.__name__}: {message}"[:2000]


def _status(profile: EntityProfile, row: dict[str, Any]) -> str:
    value = _first(row, profile.status_fields)
    if not value and "reviewStatus" in row:
        value = str(row.get("reviewStatus") or "")
    return (value or "active")[:30]


def _fetch_page(entity: str, cursor: int, limit: int = 500) -> dict[str, Any]:
    if not settings.crm_read_base_url or not settings.crm_read_token:
        raise CrmCanonicalSyncError("A CRM olvasási kapcsolat nincs beállítva.")
    query = urllib.parse.urlencode(
        {
            "entity": entity,
            "workspaceId": settings.crm_workspace_id,
            "cursor": cursor,
            "limit": limit,
        }
    )
    request = urllib.request.Request(
        f"{settings.crm_read_base_url}/api/integrations/platform-export?{query}",
        headers=crm_service_headers("X-ITEP-CRM-Token", settings.crm_read_token),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CrmCanonicalSyncError(
            f"A CRM export nem olvasható ({entity}, cursor={cursor}): {exc}"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise CrmCanonicalSyncError(f"Érvénytelen CRM exportválasz: {entity}, cursor={cursor}.")
    return payload


def _fetch_itep_invoice_page(page: int, page_size: int = 100) -> dict[str, Any]:
    try:
        return incoming_invoices(
            SimpleNamespace(email="platform-data-sync@imperial.local", role="finance"),
            page=page,
            page_size=page_size,
        )
    except ItepFinanceError as exc:
        raise CrmCanonicalSyncError(str(exc)) from exc


def _source(db: Session) -> ImportDataSource:
    row = db.scalar(select(ImportDataSource).where(ImportDataSource.source_key == SOURCE_KEY))
    if row is None:
        row = ImportDataSource(
            source_key=SOURCE_KEY,
            name="CRM és ITEP – migrált vállalati adatvagyon",
            source_type="internal_service",
            domain_scope="enterprise",
            connector_reference="CRM protected export + ITEP financial API",
            query_or_path="/api/integrations/platform-export; /v1/financial/incoming-invoices",
            sync_mode="incremental",
            owner="Imperial Intelligence",
            enabled=True,
            settings_json=_dumps({"workspace_id": settings.crm_workspace_id}),
        )
        db.add(row)
        db.flush()
    return row


@serialized_canonical_sync("crm-import")
def sync_crm_canonical(
    db: Session,
    *,
    actor: str,
    fetch_page: Callable[[str, int, int], dict[str, Any]] = _fetch_page,
    fetch_itep_invoice_page: Callable[[int, int], dict[str, Any]] = _fetch_itep_invoice_page,
) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    source = _source(db)
    job = ImportJob(
        job_id=f"CRM-SYNC-{started_at.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}",
        source_key=SOURCE_KEY,
        name=f"CRM kanonikus szinkron – {started_at.strftime('%Y-%m-%d %H:%M UTC')}",
        status="processing",
        requested_by=actor,
        domain_hint="enterprise",
        started_at=started_at,
    )
    db.add(job)
    db.flush()

    existing = {
        (row.domain, row.entity_type, row.external_key): row
        for row in db.scalars(
            select(EnterpriseCanonicalRecord).where(
                or_(
                    EnterpriseCanonicalRecord.external_key.like("crm:%"),
                    EnterpriseCanonicalRecord.external_key.like("itep:%"),
                )
            )
        ).all()
    }
    summary: dict[str, Any] = {"entities": {}, "inserted": 0, "updated": 0, "unchanged": 0}

    try:
        for entity in SYNC_ENTITIES:
            cursor = 0
            entity_counts = {"source": 0, "inserted": 0, "updated": 0, "unchanged": 0}
            while True:
                page = fetch_page(entity, cursor, 500)
                rows = page["rows"]
                for raw in rows:
                    if not isinstance(raw, dict):
                        raise CrmCanonicalSyncError(
                            f"Nem objektum CRM rekord: {entity}, cursor={cursor}."
                        )
                    profile = _profile(entity, raw)
                    external_key = _external_key(entity, raw)
                    key = (profile.domain, profile.entity_type, external_key)
                    data_json = _dumps(raw)
                    current = existing.get(key)
                    provenance_json = _source_provenance(
                        current,
                        {
                            "source": "imperial-sales-crm",
                            "workspace_id": settings.crm_workspace_id,
                            "export_entity": entity,
                            "source_id": raw.get("id"),
                            "synced_at": started_at.isoformat(),
                        },
                    )
                    if current is None:
                        digest = hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()[:24]
                        current = EnterpriseCanonicalRecord(
                            record_id=f"CRM-{digest}",
                            domain=profile.domain,
                            entity_type=profile.entity_type,
                            external_key=external_key,
                            canonical_name=_limited(_first(raw, profile.name_fields), 500),
                            project_id=_limited(_first(raw, profile.project_fields), 100),
                            target_module=profile.target_module,
                            status=_status(profile, raw),
                            data_json=data_json,
                            provenance_json=provenance_json,
                            source_job_id=job.job_id,
                        )
                        db.add(current)
                        existing[key] = current
                        entity_counts["inserted"] += 1
                    elif current.data_json != data_json:
                        current.canonical_name = _limited(_first(raw, profile.name_fields), 500)
                        if _manual_allocation(current) is None:
                            current.project_id = _limited(_first(raw, profile.project_fields), 100)
                        current.target_module = profile.target_module
                        current.status = _status(profile, raw)
                        current.data_json = data_json
                        current.provenance_json = provenance_json
                        current.source_job_id = job.job_id
                        entity_counts["updated"] += 1
                    else:
                        entity_counts["unchanged"] += 1
                    entity_counts["source"] += 1
                heartbeat_canonical_sync_lease()
                next_cursor = page.get("nextCursor")
                if next_cursor is None:
                    break
                if not isinstance(next_cursor, int) or next_cursor <= cursor:
                    raise CrmCanonicalSyncError(f"Hibás CRM lapozás: {entity}, cursor={cursor}.")
                cursor = next_cursor
            summary["entities"][entity] = entity_counts
            for field in ("inserted", "updated", "unchanged"):
                summary[field] += entity_counts[field]

        page_number = 1
        itep_counts = {"source": 0, "inserted": 0, "updated": 0, "unchanged": 0}
        while True:
            payload = fetch_itep_invoice_page(page_number, 100)
            rows = payload.get("items")
            if not isinstance(rows, list):
                raise CrmCanonicalSyncError(f"Érvénytelen ITEP számlaexport: page={page_number}.")
            for raw in rows:
                if not isinstance(raw, dict):
                    raise CrmCanonicalSyncError(
                        f"Nem objektum ITEP számlarekord: page={page_number}."
                    )
                source_id = raw.get("id") or raw.get("sourceRowHash") or raw.get("invoiceNumber")
                if source_id in (None, ""):
                    source_id = hashlib.sha256(_dumps(raw).encode("utf-8")).hexdigest()[:24]
                external_key = f"itep:billingo_incoming:{source_id}"
                key = (ITEP_INVOICE_PROFILE.domain, ITEP_INVOICE_PROFILE.entity_type, external_key)
                data_json = _dumps(raw)
                current = existing.get(key)
                provenance_json = _source_provenance(
                    current,
                    {
                        "source": "itep-core",
                        "provider": "BILLINGO",
                        "direction": "INCOMING",
                        "organization_id": "imperial-holding",
                        "source_id": raw.get("id"),
                        "synced_at": started_at.isoformat(),
                    },
                )
                if current is None:
                    digest = hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()[:24]
                    current = EnterpriseCanonicalRecord(
                        record_id=f"ITEP-{digest}",
                        domain=ITEP_INVOICE_PROFILE.domain,
                        entity_type=ITEP_INVOICE_PROFILE.entity_type,
                        external_key=external_key,
                        canonical_name=_limited(_first(raw, ITEP_INVOICE_PROFILE.name_fields), 500),
                        project_id=None,
                        target_module=ITEP_INVOICE_PROFILE.target_module,
                        status=_status(ITEP_INVOICE_PROFILE, raw),
                        data_json=data_json,
                        provenance_json=provenance_json,
                        source_job_id=job.job_id,
                    )
                    db.add(current)
                    existing[key] = current
                    itep_counts["inserted"] += 1
                elif current.data_json != data_json:
                    current.canonical_name = _limited(
                        _first(raw, ITEP_INVOICE_PROFILE.name_fields), 500
                    )
                    current.status = _status(ITEP_INVOICE_PROFILE, raw)
                    current.data_json = data_json
                    current.provenance_json = provenance_json
                    current.source_job_id = job.job_id
                    itep_counts["updated"] += 1
                else:
                    itep_counts["unchanged"] += 1
                itep_counts["source"] += 1
            heartbeat_canonical_sync_lease()
            total_pages = payload.get("totalPages")
            if not isinstance(total_pages, int) or page_number >= total_pages:
                break
            page_number += 1
        summary["entities"]["itep_billingo_invoices"] = itep_counts
        for field in ("inserted", "updated", "unchanged"):
            summary[field] += itep_counts[field]

        total = summary["inserted"] + summary["updated"] + summary["unchanged"]
        job.status = "committed"
        job.items_total = len(SYNC_ENTITIES) + 1
        job.items_processed = len(SYNC_ENTITIES) + 1
        job.records_extracted = total
        job.records_committed = summary["inserted"] + summary["updated"]
        job.summary_json = _dumps(summary)
        job.completed_at = datetime.now(UTC)
        source.last_sync_at = job.completed_at
        db.commit()
        return {"job_id": job.job_id, "status": job.status, **summary, "total": total}
    except Exception as exc:
        db.rollback()
        failed_job = ImportJob(
            job_id=job.job_id,
            source_key=SOURCE_KEY,
            name=job.name,
            status="failed",
            requested_by=actor,
            domain_hint="enterprise",
            error_count=1,
            summary_json=_dumps({"error": _safe_error(exc), **summary}),
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        db.add(failed_job)
        db.commit()
        if isinstance(exc, CrmCanonicalSyncError):
            raise
        raise CrmCanonicalSyncError(_safe_error(exc)) from exc
