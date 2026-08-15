from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from ..audit import audit
from ..models import (
    CareCase,
    CareEvidence,
    CareMessage,
    CustomerPortalAccess,
    EventRecord,
    ProjectObjectState,
    ProjectRegistry,
    TaskRecord,
)
from ..schemas import EventIn
from .integration import ingest_event
from .tender_evidence_security import (
    TenderMalwareDetected,
    TenderScannerUnavailable,
    scan_care_evidence,
)

INTERNAL_ROLES = frozenset(
    {"owner", "managing-director", "platform-admin", "project-manager", "technical-prep"}
)
CASE_CATEGORIES = frozenset({"warranty", "defect", "service", "documentation", "other"})
CASE_SEVERITIES = frozenset({"low", "medium", "high", "urgent"})
SLA_HOURS = {"low": 72, "medium": 48, "high": 24, "urgent": 4}
OPEN_STATUSES = frozenset({"submitted", "triaged", "in_progress", "waiting_customer"})
TRANSITIONS = {
    "submitted": {"triaged", "rejected"},
    "triaged": {"in_progress", "waiting_customer", "rejected"},
    "in_progress": {"waiting_customer", "resolved"},
    "waiting_customer": {"in_progress", "resolved"},
    "resolved": {"in_progress", "closed"},
    "closed": set(),
    "rejected": {"triaged"},
}
ALLOWED_MIME = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
    "application/pdf": (b"%PDF-",),
}
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024


class CareEvidenceUnavailable(RuntimeError):
    """Raised when stored customer evidence is not safe to release."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def _role(user: object) -> str:
    return str(getattr(user, "role", ""))


def _email(user: object) -> str:
    return str(getattr(user, "email", "")).strip().lower()


def _name(user: object) -> str:
    return str(getattr(user, "name", "")).strip() or _email(user)


def _is_internal(user: object) -> bool:
    return _role(user) in INTERNAL_ROLES


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def accessible_care_projects(db: Session, user: object) -> list[ProjectRegistry]:
    if _is_internal(user):
        return list(db.scalars(select(ProjectRegistry).order_by(ProjectRegistry.name)))
    if _role(user) != "customer":
        return []
    project_ids = list(
        db.scalars(
            select(CustomerPortalAccess.project_id).where(
                CustomerPortalAccess.active.is_(True),
                CustomerPortalAccess.customer_email == _email(user),
            )
        )
    )
    if not project_ids:
        return []
    return list(
        db.scalars(
            select(ProjectRegistry)
            .where(ProjectRegistry.project_id.in_(project_ids))
            .order_by(ProjectRegistry.name)
        )
    )


def _case_query():
    return select(CareCase).options(
        selectinload(CareCase.messages), selectinload(CareCase.evidence)
    )


def care_case_for_user(
    db: Session, case_id: str, user: object, *, lock_for_update: bool = False
) -> CareCase:
    query = _case_query().where(CareCase.case_id == case_id)
    if lock_for_update:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise KeyError(case_id)
    if _is_internal(user):
        return row
    if _role(user) == "customer" and row.customer_email.lower() == _email(user):
        access = db.scalar(
            select(CustomerPortalAccess).where(
                CustomerPortalAccess.project_id == row.project_id,
                CustomerPortalAccess.customer_email == _email(user),
                CustomerPortalAccess.active.is_(True),
            )
        )
        if access:
            return row
    if _role(user) == "subcontractor" and row.assigned_to == _email(user):
        return row
    raise PermissionError(case_id)


def care_evidence_for_user(db: Session, evidence_id: str, user: object) -> CareEvidence:
    evidence = db.scalar(
        select(CareEvidence)
        .options(selectinload(CareEvidence.case))
        .where(CareEvidence.evidence_id == evidence_id)
    )
    if evidence is None:
        raise KeyError(evidence_id)
    care_case_for_user(db, evidence.case.case_id, user)
    return evidence


def care_workspace(
    db: Session,
    user: object,
    *,
    project_id: str = "",
    status: str = "",
    severity: str = "",
    assigned_to: str = "",
    query_text: str = "",
) -> dict[str, Any]:
    projects = accessible_care_projects(db, user)
    project_ids = [project.project_id for project in projects]
    query = _case_query().order_by(desc(CareCase.updated_at))
    if _is_internal(user):
        pass
    elif _role(user) == "customer":
        query = query.where(
            CareCase.customer_email == _email(user),
            CareCase.project_id.in_(project_ids) if project_ids else CareCase.id == -1,
        )
    elif _role(user) == "subcontractor":
        query = query.where(CareCase.assigned_to == _email(user))
    else:
        query = query.where(CareCase.id == -1)
    if project_id.strip():
        query = query.where(CareCase.project_id == project_id.strip())
    if status.strip():
        query = query.where(CareCase.status == status.strip())
    if severity.strip():
        query = query.where(CareCase.severity == severity.strip())
    if assigned_to.strip() and _is_internal(user):
        query = query.where(CareCase.assigned_to == assigned_to.strip().lower())
    if query_text.strip():
        pattern = f"%{query_text.strip()}%"
        query = query.where(
            or_(
                CareCase.case_id.ilike(pattern),
                CareCase.title.ilike(pattern),
                CareCase.customer_email.ilike(pattern),
                CareCase.location.ilike(pattern),
            )
        )
    cases = list(db.scalars(query))
    access_query = select(CustomerPortalAccess).where(CustomerPortalAccess.active.is_(True))
    if not _is_internal(user):
        access_query = access_query.where(CustomerPortalAccess.customer_email == _email(user))
    accesses = list(db.scalars(access_query.order_by(CustomerPortalAccess.customer_email)))
    now = utcnow()
    return {
        "internal": _is_internal(user),
        "projects": projects,
        "accesses": accesses,
        "cases": cases,
        "filters": {
            "project_id": project_id,
            "status": status,
            "severity": severity,
            "assigned_to": assigned_to,
            "query": query_text,
        },
        "metrics": {
            "open": sum(1 for row in cases if row.status in OPEN_STATUSES),
            "urgent": sum(
                1 for row in cases if row.status in OPEN_STATUSES and row.severity == "urgent"
            ),
            "overdue": sum(
                1
                for row in cases
                if row.status in OPEN_STATUSES
                and row.first_response_at is None
                and _aware(row.sla_due_at) < now
            ),
            "resolved": sum(1 for row in cases if row.status in {"resolved", "closed"}),
        },
    }


def create_care_case(
    db: Session,
    user: object,
    *,
    project_id: str,
    category: str,
    severity: str,
    title: str,
    description: str,
    location: str = "",
    preferred_contact: str = "",
    customer_email: str = "",
    reporter_name: str = "",
) -> CareCase:
    if _role(user) not in INTERNAL_ROLES | {"customer"}:
        raise PermissionError("Csak ügyfél vagy belső Imperial Care munkatárs nyithat ügyet.")
    if category not in CASE_CATEGORIES:
        raise ValueError("Érvénytelen Imperial Care ügytípus.")
    if severity not in CASE_SEVERITIES:
        raise ValueError("Érvénytelen súlyosság.")
    if len(title.strip()) < 5 or len(description.strip()) < 15:
        raise ValueError("A cím és a részletes hibaleírás kötelező.")
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
    if project is None:
        raise ValueError("A ProjectID nem található.")

    reporter_email = _email(user) if _role(user) == "customer" else customer_email.strip().lower()
    reporter = _name(user) if _role(user) == "customer" else reporter_name.strip()
    if not reporter_email or not reporter:
        raise ValueError("Ügyfél e-mail és bejelentő neve kötelező.")
    access = db.scalar(
        select(CustomerPortalAccess).where(
            CustomerPortalAccess.project_id == project_id,
            CustomerPortalAccess.customer_email == reporter_email,
            CustomerPortalAccess.active.is_(True),
        )
    )
    if access is None:
        raise PermissionError("Az ügyfélnek nincs aktív MyImperial-hozzáférése ehhez a projekthez.")

    now = utcnow()
    row = CareCase(
        case_id=f"CARE-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}",
        project_id=project_id,
        customer_email=reporter_email,
        reporter_name=reporter,
        category=category,
        severity=severity,
        title=title.strip(),
        description=description.strip(),
        location=location.strip() or None,
        preferred_contact=preferred_contact.strip() or None,
        status="submitted",
        sla_due_at=now + timedelta(hours=SLA_HOURS[severity]),
        source_channel="imperial-care",
    )
    db.add(row)
    db.flush()
    audit(
        db,
        actor=_email(user),
        action="imperial_care.case.created",
        entity_type="care_case",
        entity_id=row.case_id,
        after={
            "project_id": project_id,
            "category": category,
            "severity": severity,
            "customer_email": reporter_email,
            "source_channel": "imperial-care",
        },
    )
    event, _created = ingest_event(
        db,
        EventIn(
            event_id=f"EVT-{row.case_id}",
            dedupe_key=f"IMPERIAL_CARE_CASE:{row.case_id}",
            project_id=project_id,
            source_module="imperial-care",
            event_type="WARRANTY_CASE_OPENED",
            object_type="CareCase",
            object_id=row.case_id,
            severity="critical" if severity == "urgent" else severity,
            status="submitted",
            responsible=project.responsible or "Projektvezetés / Imperial Care",
            next_action=f"Imperial Care ügy triázsa az SLA előtt: {row.sla_due_at.isoformat()}",
            executive_relevance=severity in {"high", "urgent"},
            payload={
                "summary": title.strip(),
                "category": category,
                "customer_email": reporter_email,
                "source_channel": "imperial-care",
                "exclusive_customer_issue_channel": True,
            },
            route_to=["project-control", "myimperial"],
        ),
        actor=_email(user),
    )
    task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == event.event_id))
    if task:
        task.due_at = row.sla_due_at
        task.assignee = project.responsible or task.assignee
        task.priority = "critical" if severity == "urgent" else severity
        db.commit()
    return care_case_for_user(db, row.case_id, user)


def add_care_message(
    db: Session,
    case_id: str,
    user: object,
    *,
    body: str,
    customer_visible: bool = True,
) -> CareMessage:
    row = care_case_for_user(db, case_id, user)
    if len(body.strip()) < 2:
        raise ValueError("Az üzenet nem lehet üres.")
    if row.status in {"closed", "rejected"}:
        raise ValueError("Lezárt vagy elutasított Imperial Care ügyhöz nem adható új üzenet.")
    if not _is_internal(user):
        customer_visible = True
    message = CareMessage(
        message_id=f"CARE-MSG-{uuid.uuid4().hex[:12].upper()}",
        case_id_fk=row.id,
        author_email=_email(user),
        author_role=_role(user),
        body=body.strip(),
        customer_visible=customer_visible,
    )
    db.add(message)
    if _is_internal(user) and row.first_response_at is None:
        row.first_response_at = utcnow()
    row.updated_at = utcnow()
    audit(
        db,
        actor=_email(user),
        action="imperial_care.message.added",
        entity_type="care_case",
        entity_id=row.case_id,
        after={"message_id": message.message_id, "customer_visible": customer_visible},
    )
    db.commit()
    db.refresh(message)
    return message


def transition_care_case(
    db: Session,
    case_id: str,
    user: object,
    *,
    status: str,
    assigned_to: str = "",
    resolution_summary: str = "",
    expected_version: int | None = None,
) -> CareCase:
    row = care_case_for_user(db, case_id, user, lock_for_update=True)
    if expected_version is None:
        raise ValueError("A módosításhoz az ügy aktuális verziója kötelező.")
    if expected_version != row.version:
        raise ValueError(
            "Az ügyet időközben más módosította. Frissítse az oldalt, majd ismételje meg."
        )
    internal = _is_internal(user)
    if not internal:
        if not (
            _role(user) == "customer"
            and row.status == "resolved"
            and status in {"closed", "in_progress"}
        ):
            raise PermissionError("Az ügyfél csak a megoldás elfogadását vagy újranyitását kérheti.")
    if status not in TRANSITIONS.get(row.status, set()):
        raise ValueError(f"A(z) {row.status} állapotból {status} állapot nem indítható.")
    if internal and status in {"triaged", "in_progress"} and not assigned_to.strip() and not row.assigned_to:
        raise ValueError("Triázshoz és feldolgozáshoz felelős kötelező.")
    assignee = assigned_to.strip().lower()
    if assignee and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", assignee):
        raise ValueError("A felelős e-mail címe érvénytelen.")
    if status == "resolved" and len(resolution_summary.strip()) < 10:
        raise ValueError("Megoldásra állításhoz részletes megoldási összefoglaló kötelező.")
    if status == "rejected" and len(resolution_summary.strip()) < 10:
        raise ValueError("Elutasításhoz részletes indoklás kötelező.")
    before = {"status": row.status, "assigned_to": row.assigned_to, "version": row.version}
    if not internal:
        row.customer_confirmed = status == "closed"
    row.status = status
    if assignee:
        row.assigned_to = assignee
    if internal and row.first_response_at is None:
        row.first_response_at = utcnow()
    if status == "resolved":
        row.resolution_summary = resolution_summary.strip()
        row.resolved_at = utcnow()
    elif status == "rejected":
        row.resolution_summary = resolution_summary.strip()
    elif status == "in_progress":
        row.resolved_at = None
        row.closed_at = None
    elif status == "closed":
        row.closed_at = utcnow()
    row.version += 1
    row.updated_at = utcnow()
    state = db.scalar(
        select(ProjectObjectState).where(
            ProjectObjectState.project_id == row.project_id,
            ProjectObjectState.source_module == "imperial-care",
            ProjectObjectState.object_type == "CareCase",
            ProjectObjectState.object_id == row.case_id,
        )
    )
    if state:
        state.status = status
        state.summary = row.resolution_summary or row.title
        state.payload_json = json.dumps(
            {"category": row.category, "severity": row.severity, "customer_email": row.customer_email},
            ensure_ascii=False,
        )
    event = db.scalar(
        select(EventRecord).where(
            EventRecord.source_module == "imperial-care",
            EventRecord.object_type == "CareCase",
            EventRecord.object_id == row.case_id,
        )
    )
    if event:
        event.status = "resolved" if status in {"resolved", "closed", "rejected"} else "open"
        task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == event.event_id))
        if task:
            task.assignee = row.assigned_to or task.assignee
            task.status = (
                "done"
                if status in {"resolved", "closed", "rejected"}
                else "waiting_customer"
                if status == "waiting_customer"
                else "in_progress"
            )
    audit(
        db,
        actor=_email(user),
        action="imperial_care.case.transitioned",
        entity_type="care_case",
        entity_id=row.case_id,
        before=before,
        after={"status": status, "assigned_to": row.assigned_to, "version": row.version},
    )
    db.commit()
    return care_case_for_user(db, case_id, user)


def _safe_file_name(value: str) -> str:
    suffix = Path(value).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(value).stem).strip("._") or "evidence"
    return f"{stem[:80]}{suffix[:10]}"


def save_care_evidence(
    db: Session,
    case_id: str,
    user: object,
    *,
    file_name: str,
    mime_type: str,
    raw: bytes,
    caption: str,
    storage_root: Path,
) -> CareEvidence:
    row = care_case_for_user(db, case_id, user)
    if row.status in {"closed", "rejected"}:
        raise ValueError("Lezárt vagy elutasított Imperial Care ügyhöz nem tölthető fel bizonyíték.")
    if not raw or len(raw) > MAX_EVIDENCE_BYTES:
        raise ValueError("A bizonyíték mérete 1 bájt és 10 MB között lehet.")
    signatures = ALLOWED_MIME.get(mime_type)
    if signatures is None:
        raise ValueError("Csak JPG, PNG, WEBP vagy PDF bizonyíték tölthető fel.")
    valid_header = any(raw.startswith(signature) for signature in signatures)
    if mime_type == "image/webp":
        valid_header = raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"
    digest = hashlib.sha256(raw).hexdigest()
    if not valid_header:
        audit(
            db,
            actor=_email(user),
            action="imperial_care.evidence.rejected",
            entity_type="care_case",
            entity_id=row.case_id,
            after={
                "sha256": digest,
                "mime_type": mime_type,
                "scan_status": "content_rejected",
            },
        )
        db.commit()
        raise ValueError("A fájl tartalma nem egyezik a megadott típussal.")
    try:
        scan = scan_care_evidence(raw)
    except TenderMalwareDetected:
        audit(
            db,
            actor=_email(user),
            action="imperial_care.evidence.rejected",
            entity_type="care_case",
            entity_id=row.case_id,
            after={"sha256": digest, "mime_type": mime_type, "scan_status": "infected"},
        )
        db.commit()
        raise
    except TenderScannerUnavailable:
        audit(
            db,
            actor=_email(user),
            action="imperial_care.evidence.rejected",
            entity_type="care_case",
            entity_id=row.case_id,
            after={
                "sha256": digest,
                "mime_type": mime_type,
                "scan_status": "unavailable",
            },
        )
        db.commit()
        raise
    evidence_id = f"CARE-EV-{uuid.uuid4().hex[:12].upper()}"
    target_dir = storage_root / row.case_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{evidence_id}_{_safe_file_name(file_name)}"
    target.write_bytes(raw)
    evidence = CareEvidence(
        evidence_id=evidence_id,
        case_id_fk=row.id,
        file_name=_safe_file_name(file_name),
        mime_type=mime_type,
        sha256=digest,
        storage_path=str(target),
        caption=caption.strip() or None,
        scan_status=scan.status,
        scan_engine=scan.engine,
        scan_engine_version=scan.engine_version,
        scan_signature=scan.signature,
        scanned_at=utcnow(),
        uploaded_by=_email(user),
    )
    db.add(evidence)
    audit(
        db,
        actor=_email(user),
        action="imperial_care.evidence.added",
        entity_type="care_case",
        entity_id=row.case_id,
        after={
            "evidence_id": evidence_id,
            "sha256": digest,
            "mime_type": mime_type,
            "scan_status": scan.status,
            "scan_engine": scan.engine,
            "scan_engine_version": scan.engine_version,
        },
    )
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    db.refresh(evidence)
    return evidence


def verified_care_evidence_path(
    db: Session,
    evidence: CareEvidence,
    *,
    storage_root: Path,
    actor: str,
) -> Path:
    path = Path(evidence.storage_path).resolve()
    root = storage_root.resolve()
    failure: str | None = None
    if evidence.scan_status != "clean":
        failure = f"scan_status:{evidence.scan_status}"
    elif not path.is_relative_to(root) or not path.is_file():
        failure = "storage_path_unavailable"
    elif hashlib.sha256(path.read_bytes()).hexdigest() != evidence.sha256:
        failure = "sha256_mismatch"
    if failure:
        audit(
            db,
            actor=actor,
            action="imperial_care.evidence.download_blocked",
            entity_type="care_evidence",
            entity_id=evidence.evidence_id,
            after={"reason": failure},
        )
        db.commit()
        raise CareEvidenceUnavailable(
            "A bizonyíték nem rendelkezik érvényes tiszta scan- és "
            "integritásbizonyítékkal."
        )
    audit(
        db,
        actor=actor,
        action="imperial_care.evidence.downloaded",
        entity_type="care_evidence",
        entity_id=evidence.evidence_id,
        after={"sha256": evidence.sha256},
    )
    db.commit()
    return path
