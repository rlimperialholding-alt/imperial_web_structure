from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import ContractWorkflowRecord
from .smart_calendar import assert_calendar_project_access

COMMERCIAL_ROLES = {"owner", "managing-director", "finance", "sales"}
TECHNICAL_ROLES = {"owner", "managing-director", "project-manager", "technical-prep"}
LEGAL_ROLES = {"owner", "managing-director", "legal"}
OWNER_ROLES = {"owner", "managing-director"}
SUBMIT_ROLES = {"owner", "managing-director", "platform-admin", "sales", "legal"}
SIGNED_ROLES = {"owner", "managing-director", "platform-admin", "legal"}
DISPATCH_ROLES = {"owner", "managing-director", "platform-admin", "legal", "sales"}
ACTIVATION_ROLES = {"owner", "managing-director", "platform-admin", "project-manager"}
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
GATE_FIELDS = {
    "commercial": ("commercial_approved_by", "commercial_approved_at", "commercial_note"),
    "technical": ("technical_approved_by", "technical_approved_at", "technical_note"),
    "legal": ("legal_approved_by", "legal_approved_at", "legal_note"),
    "owner": ("owner_approved_by", "owner_approved_at", "owner_note"),
}
GATE_ROLES = {
    "commercial": COMMERCIAL_ROLES,
    "technical": TECHNICAL_ROLES,
    "legal": LEGAL_ROLES,
    "owner": OWNER_ROLES,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _identity(user: object) -> tuple[str, str]:
    return (
        str(getattr(user, "role", "")),
        str(getattr(user, "email", "")).strip().lower(),
    )


def _require(user: object, roles: set[str]) -> tuple[str, str]:
    role, email = _identity(user)
    if role not in roles or not email:
        raise PermissionError("Ehhez a szerződésművelethez nincs jogosultsága.")
    return role, email


def _require_project_scope(
    db: Session, user: object, project_id: str
) -> None:
    if str(getattr(user, "role", "")) == "project-manager":
        assert_calendar_project_access(db, user, project_id)


def _row(
    db: Session, contract_id: str, *, for_update: bool = False
) -> ContractWorkflowRecord:
    stmt = select(ContractWorkflowRecord).where(
        ContractWorkflowRecord.contract_id == contract_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt.execution_options(populate_existing=True))
    if row is None:
        raise KeyError(contract_id)
    return row


def _canonical_payload(payload: dict[str, Any]) -> tuple[str, str]:
    value = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return value, hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_gates(row: ContractWorkflowRecord) -> tuple[str, ...]:
    gates = ["commercial", "technical"]
    if row.legal_required:
        gates.append("legal")
    gates.append("owner")
    return tuple(gates)


def _approved_actors(row: ContractWorkflowRecord) -> set[str]:
    return {
        value
        for value in (
            row.commercial_approved_by,
            row.technical_approved_by,
            row.legal_approved_by,
            row.owner_approved_by,
        )
        if value
    }


def _all_approved(row: ContractWorkflowRecord) -> bool:
    return all(getattr(row, GATE_FIELDS[gate][0]) for gate in _required_gates(row))


def create_contract_workflow(
    db: Session,
    *,
    payload: dict[str, Any],
    package_document_id: str,
    manifest_document_id: str,
    actor: str,
) -> ContractWorkflowRecord:
    payload_json, payload_sha256 = _canonical_payload(payload)
    contract_number = str(payload.get("contract_number") or "").strip()
    ids = payload.get("ids") or {}
    contract_id = str(ids.get("ContractID") or f"CTR-{uuid4().hex[:20].upper()}")
    relationship = str(payload.get("relationship") or "").strip().lower()
    contract_type = str(payload.get("contract_type") or "").strip()
    row = ContractWorkflowRecord(
        contract_id=contract_id,
        contract_number=contract_number,
        project_id=str(ids.get("ProjectID") or "").strip(),
        opportunity_id=str(ids.get("OpportunityID") or "").strip(),
        partner_id=str(ids.get("PartnerID") or "").strip(),
        contract_type=contract_type,
        counterparty_name=str((payload.get("counterparty") or {}).get("name") or "").strip(),
        payload_json=payload_json,
        payload_sha256=payload_sha256,
        package_document_id=package_document_id,
        manifest_document_id=manifest_document_id,
        generated_by=actor.strip().lower(),
        legal_required=relationship == "customer" or contract_type.startswith("customer_"),
    )
    db.add(row)
    audit(
        db,
        actor=actor,
        action="contract.workflow.created",
        entity_type="contract_workflow",
        entity_id=contract_id,
        after={
            "contract_number": contract_number,
            "project_id": row.project_id,
            "payload_sha256": payload_sha256,
            "legal_required": row.legal_required,
        },
    )
    return row


def list_contract_workflows(
    db: Session, *, project_id: str | None = None
) -> list[ContractWorkflowRecord]:
    stmt = select(ContractWorkflowRecord)
    if project_id:
        stmt = stmt.where(ContractWorkflowRecord.project_id == project_id)
    return list(db.scalars(stmt.order_by(desc(ContractWorkflowRecord.updated_at))).all())


def contract_workflow_detail(
    db: Session, contract_id: str, *, user: object | None = None
) -> dict[str, Any]:
    row = _row(db, contract_id)
    if user is not None:
        _require_project_scope(db, user, row.project_id)
    payload = json.loads(row.payload_json)
    return {
        "row": row,
        "payload": payload,
        "required_gates": _required_gates(row),
        "all_approved": _all_approved(row),
        "counterparty_email": str((payload.get("counterparty") or {}).get("email") or ""),
        "package_document_id": row.package_document_id,
        "manifest_document_id": row.manifest_document_id,
    }


def submit_contract_review(
    db: Session, contract_id: str, user: object
) -> ContractWorkflowRecord:
    _role, email = _require(user, SUBMIT_ROLES)
    row = _row(db, contract_id, for_update=True)
    _require_project_scope(db, user, row.project_id)
    if row.status != "generated":
        raise ValueError("Csak elkészült szerződéscsomag küldhető jóváhagyásra.")
    row.status = "review"
    row.submitted_by = email
    row.submitted_at = utcnow()
    audit(
        db,
        actor=email,
        action="contract.workflow.submitted",
        entity_type="contract_workflow",
        entity_id=contract_id,
        after={"status": row.status},
    )
    db.commit()
    db.refresh(row)
    return row


def review_contract(
    db: Session,
    contract_id: str,
    user: object,
    *,
    gate: str,
    decision: str,
    note: str,
) -> ContractWorkflowRecord:
    if gate not in GATE_FIELDS:
        raise ValueError("Ismeretlen szerződés-jóváhagyási kapu.")
    _role, email = _require(user, GATE_ROLES[gate])
    row = _row(db, contract_id, for_update=True)
    _require_project_scope(db, user, row.project_id)
    if gate == "legal" and not row.legal_required:
        raise ValueError("Ehhez a szerződéstípushoz nem szükséges jogi kapu.")
    if row.status != "review":
        raise ValueError("Jóváhagyás csak felülvizsgálati állapotban rögzíthető.")
    if len(note.strip()) < 10:
        raise ValueError("A jóváhagyási vagy elutasítási indoklás legalább 10 karakter.")
    if email == row.generated_by:
        raise ValueError("A szerződés készítője saját csomagját nem hagyhatja jóvá.")
    approved_by, approved_at, note_field = GATE_FIELDS[gate]
    if getattr(row, approved_by):
        raise ValueError("Ez a jóváhagyási kapu már lezárult.")
    if decision not in {"approve", "reject"}:
        raise ValueError("A döntés approve vagy reject lehet.")
    if decision == "reject":
        row.status = "rejected"
        row.rejected_by = email
        row.rejected_at = utcnow()
        row.rejection_reason = note.strip()
        action = "contract.workflow.rejected"
    else:
        if email in _approved_actors(row):
            raise ValueError("A jóváhagyási kapukhoz külön személyek szükségesek.")
        setattr(row, approved_by, email)
        setattr(row, approved_at, utcnow())
        setattr(row, note_field, note.strip())
        row.status = "approved" if _all_approved(row) else "review"
        action = "contract.workflow.approved_gate"
    audit(
        db,
        actor=email,
        action=action,
        entity_type="contract_workflow",
        entity_id=contract_id,
        after={"gate": gate, "decision": decision, "status": row.status, "note": note.strip()},
    )
    db.commit()
    db.refresh(row)
    return row


def record_signed_contract(
    db: Session,
    contract_id: str,
    user: object,
    *,
    file_id: str,
    document_sha256: str,
    signed_at: datetime,
) -> ContractWorkflowRecord:
    _role, email = _require(user, SIGNED_ROLES)
    row = _row(db, contract_id, for_update=True)
    _require_project_scope(db, user, row.project_id)
    if row.status != "approved":
        raise ValueError("Aláírt példány csak minden kötelező jóváhagyás után rögzíthető.")
    digest = document_sha256.strip().lower()
    if not file_id.strip() or not HASH_PATTERN.fullmatch(digest):
        raise ValueError("Az aláírt fájl bizonyítékazonosítója és SHA-256 lenyomata kötelező.")
    signed_at = _as_utc(signed_at)
    if signed_at > utcnow() + timedelta(minutes=5):
        raise ValueError("Jövőbeli aláírási időpont nem rögzíthető.")
    row.signed_file_id = file_id.strip()
    row.signed_document_sha256 = digest
    row.signed_at = signed_at
    row.signed_recorded_by = email
    row.status = "signed"
    audit(
        db,
        actor=email,
        action="contract.workflow.signed_recorded",
        entity_type="contract_workflow",
        entity_id=contract_id,
        after={"file_id": row.signed_file_id, "sha256": digest, "signed_at": signed_at},
    )
    db.commit()
    db.refresh(row)
    return row


def record_contract_dispatch(
    db: Session,
    contract_id: str,
    user: object,
    *,
    postal_sent_at: datetime,
    postal_tracking_number: str,
    postal_proof_file_id: str,
    electronic_sent_at: datetime,
    electronic_message_id: str,
    electronic_recipient: str,
    electronic_attachment_sha256: str,
) -> ContractWorkflowRecord:
    _role, email = _require(user, DISPATCH_ROLES)
    row = _row(db, contract_id, for_update=True)
    _require_project_scope(db, user, row.project_id)
    if row.status != "signed":
        raise ValueError("Kézbesítés csak az aláírt példány rögzítése után igazolható.")
    if not postal_tracking_number.strip() or not postal_proof_file_id.strip():
        raise ValueError("A postai nyomkövetési szám és kézbesítési bizonyíték kötelező.")
    payload = json.loads(row.payload_json)
    expected_recipient = str((payload.get("counterparty") or {}).get("email") or "").lower()
    recipient = electronic_recipient.strip().lower()
    digest = electronic_attachment_sha256.strip().lower()
    if not electronic_message_id.strip() or recipient != expected_recipient:
        raise ValueError(
            "Az elektronikus üzenetazonosító és a szerződés szerinti címzett kötelező."
        )
    if not HASH_PATTERN.fullmatch(digest) or digest != row.signed_document_sha256:
        raise ValueError("Az elektronikusan kézbesített melléklet nem az aláírt példány.")
    postal_sent_at = _as_utc(postal_sent_at)
    electronic_sent_at = _as_utc(electronic_sent_at)
    signed_at = _as_utc(row.signed_at) if row.signed_at else None
    if signed_at is None or min(postal_sent_at, electronic_sent_at) < signed_at:
        raise ValueError("Kézbesítési időpont nem előzheti meg az aláírást.")
    if max(postal_sent_at, electronic_sent_at) > utcnow() + timedelta(minutes=5):
        raise ValueError("Jövőbeli kézbesítési időpont nem rögzíthető.")
    row.postal_sent_at = postal_sent_at
    row.postal_tracking_number = postal_tracking_number.strip()
    row.postal_proof_file_id = postal_proof_file_id.strip()
    row.electronic_sent_at = electronic_sent_at
    row.electronic_message_id = electronic_message_id.strip()
    row.electronic_recipient = recipient
    row.electronic_attachment_sha256 = digest
    row.dispatch_recorded_by = email
    row.status = "dispatched"
    audit(
        db,
        actor=email,
        action="contract.workflow.dispatched",
        entity_type="contract_workflow",
        entity_id=contract_id,
        after={
            "postal_tracking_number": row.postal_tracking_number,
            "postal_proof_file_id": row.postal_proof_file_id,
            "electronic_message_id": row.electronic_message_id,
            "electronic_recipient": recipient,
            "sha256": digest,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def activate_contract(
    db: Session, contract_id: str, user: object
) -> ContractWorkflowRecord:
    _role, email = _require(user, ACTIVATION_ROLES)
    row = _row(db, contract_id, for_update=True)
    _require_project_scope(db, user, row.project_id)
    if row.status != "dispatched":
        raise ValueError("Munkakezdés csak kettős kézbesítési bizonyíték után engedélyezhető.")
    row.status = "active"
    row.work_start_allowed = True
    row.activated_by = email
    row.activated_at = utcnow()
    audit(
        db,
        actor=email,
        action="contract.workflow.activated",
        entity_type="contract_workflow",
        entity_id=contract_id,
        after={"status": row.status, "work_start_allowed": True},
    )
    from .commercial_integration import ingest_contract_signed

    ingest_contract_signed(
        db,
        project_id=row.project_id,
        contract_number=row.contract_number,
        evidence_url=f"document://{row.signed_file_id}",
        actor=email,
    )
    db.refresh(row)
    return row
