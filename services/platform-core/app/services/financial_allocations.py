from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import EnterpriseCanonicalRecord, ProjectRegistry

ALLOCATABLE_ENTITY_TYPES = frozenset({"cashflow_entry", "supplier_invoice", "incoming_invoice"})
ALLOCATION_SCOPES = frozenset({"project", "corporate", "unassigned"})
ALLOCATION_EDIT_ROLES = frozenset({"owner", "platform-admin", "finance"})


def _json(value: str | None) -> dict[str, Any]:
    try:
        payload = json.loads(value or "{}")
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def allocation_scope(row: EnterpriseCanonicalRecord) -> str:
    if row.project_id:
        return "project"
    manual = _json(row.provenance_json).get("manualAllocation")
    if isinstance(manual, dict) and manual.get("scope") == "corporate":
        return "corporate"
    return "unassigned"


def allocation_workspace(
    db: Session,
    *,
    scope: str = "unassigned",
    entity_type: str = "",
    search: str = "",
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    records = list(
        db.scalars(
            select(EnterpriseCanonicalRecord)
            .where(
                EnterpriseCanonicalRecord.domain == "finance",
                EnterpriseCanonicalRecord.entity_type.in_(ALLOCATABLE_ENTITY_TYPES),
            )
            .order_by(EnterpriseCanonicalRecord.updated_at.desc())
        )
    )
    items = []
    counts = {"project": 0, "corporate": 0, "unassigned": 0}
    needle = search.strip().casefold()
    for row in records:
        row_scope = allocation_scope(row)
        counts[row_scope] += 1
        data = _json(row.data_json)
        if scope in ALLOCATION_SCOPES and row_scope != scope:
            continue
        if entity_type in ALLOCATABLE_ENTITY_TYPES and row.entity_type != entity_type:
            continue
        haystack = " ".join(
            str(value or "")
            for value in (
                row.canonical_name,
                row.external_key,
                data.get("invoiceNumber"),
                data.get("partnerName"),
                data.get("buyerName"),
                data.get("sellerName"),
                data.get("counterparty"),
                data.get("description"),
            )
        ).casefold()
        if needle and needle not in haystack:
            continue
        items.append({"record": row, "data": data, "allocation_scope": row_scope})
    safe_page_size = min(200, max(25, page_size))
    safe_page = max(1, page)
    start = (safe_page - 1) * safe_page_size
    total = len(items)
    return {
        "items": items[start : start + safe_page_size],
        "total": total,
        "page": safe_page,
        "page_size": safe_page_size,
        "total_pages": max(1, (total + safe_page_size - 1) // safe_page_size),
        "counts": counts,
        "projects": list(db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name))),
        "filters": {"scope": scope, "entity_type": entity_type, "search": search},
    }


def allocate_financial_record(
    db: Session,
    record_id: str,
    *,
    scope: str,
    project_id: str | None,
    note: str,
    actor: str,
    actor_role: str,
) -> EnterpriseCanonicalRecord:
    if actor_role not in ALLOCATION_EDIT_ROLES:
        raise PermissionError("Pénzügyi tételt csak a pénzügy jogosult besorolni.")
    row = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.record_id == record_id,
            EnterpriseCanonicalRecord.domain == "finance",
            EnterpriseCanonicalRecord.entity_type.in_(ALLOCATABLE_ENTITY_TYPES),
        )
    )
    if row is None:
        raise KeyError(record_id)
    if scope not in ALLOCATION_SCOPES:
        raise ValueError("A pénzügyi besorolás csak project, corporate vagy unassigned lehet.")
    normalized_project_id = (project_id or "").strip() or None
    if scope == "project":
        if not normalized_project_id:
            raise ValueError("Projektbesoroláshoz ProjectID kötelező.")
        if db.scalar(
            select(ProjectRegistry).where(ProjectRegistry.project_id == normalized_project_id)
        ) is None:
            raise ValueError("A megadott ProjectID nem található a projekttörzsben.")
    elif normalized_project_id:
        raise ValueError("Vállalati vagy besorolatlan tételhez nem adható ProjectID.")
    if scope == "corporate" and len(note.strip()) < 5:
        raise ValueError("Vállalati besoroláshoz rövid indoklás kötelező.")

    before = {
        "project_id": row.project_id,
        "allocation_scope": allocation_scope(row),
        "provenance": _json(row.provenance_json).get("manualAllocation"),
    }
    provenance = _json(row.provenance_json)
    if scope == "unassigned":
        provenance.pop("manualAllocation", None)
        row.project_id = None
    else:
        provenance["manualAllocation"] = {
            "scope": scope,
            "projectId": normalized_project_id if scope == "project" else None,
            "note": note.strip(),
            "actor": actor,
            "allocatedAt": datetime.now(UTC).isoformat(),
        }
        row.project_id = normalized_project_id if scope == "project" else None
    row.provenance_json = json.dumps(
        provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    audit(
        db,
        actor=actor,
        action="financial_record_allocated",
        entity_type="canonical_finance_record",
        entity_id=row.record_id,
        before=before,
        after={
            "project_id": row.project_id,
            "allocation_scope": allocation_scope(row),
            "note": note.strip(),
        },
    )
    db.commit()
    db.refresh(row)
    return row
