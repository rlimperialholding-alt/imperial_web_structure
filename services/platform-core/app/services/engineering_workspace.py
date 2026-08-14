from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    ChangeControlCase,
    EngineeringCase,
    EngineeringDeliverable,
    EngineeringFinding,
    EngineeringRevision,
    EngineeringTransmittal,
    EngineeringTransmittalItem,
    ProjectFinanceCashflowLine,
    ProjectFinancePlan,
    ProjectRegistry,
    TechnicalCase,
)
from ..schemas import (
    EngineeringCaseIn,
    EngineeringDeliverableIn,
    EngineeringFindingIn,
    EngineeringFindingResolutionIn,
    EngineeringRevisionIn,
    EngineeringRevisionReviewIn,
    EngineeringTransmittalAckIn,
    EngineeringTransmittalIn,
    EventIn,
)
from .integration import ingest_event

VIEW_ROLES = {
    "owner",
    "managing-director",
    "platform-admin",
    "technical-prep",
    "designer",
    "project-manager",
    "finance",
}
CASE_ROLES = {"owner", "managing-director", "technical-prep", "project-manager"}
AUTHOR_ROLES = {"technical-prep", "designer"}
REVIEW_ROLES = {"technical-prep"}
RELEASE_ROLES = {"project-manager", "technical-prep"}
TRANSMITTAL_ROLES = {"project-manager", "technical-prep"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _identity(user: object, roles: set[str]) -> tuple[str, str]:
    role = str(getattr(user, "role", ""))
    email = str(getattr(user, "email", "")).strip().lower()
    if role not in roles or "@" not in email:
        raise PermissionError("Az Engineering Workspace művelethez nincs megfelelő jogosultság.")
    return role, email


def _case(db: Session, project_id: str, *, lock: bool = False) -> EngineeringCase:
    stmt = select(EngineeringCase).where(EngineeringCase.project_id == project_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(project_id)
    return row


def _deliverable(db: Session, deliverable_id: str, *, lock: bool = False) -> EngineeringDeliverable:
    stmt = select(EngineeringDeliverable).where(
        EngineeringDeliverable.deliverable_id == deliverable_id
    )
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(deliverable_id)
    return row


def _revision(db: Session, revision_id: str, *, lock: bool = False) -> EngineeringRevision:
    stmt = select(EngineeringRevision).where(EngineeringRevision.revision_id == revision_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(revision_id)
    return row


def _finding(db: Session, finding_id: str, *, lock: bool = False) -> EngineeringFinding:
    stmt = select(EngineeringFinding).where(EngineeringFinding.finding_id == finding_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(finding_id)
    return row


def _transmittal(db: Session, transmittal_id: str, *, lock: bool = False) -> EngineeringTransmittal:
    stmt = select(EngineeringTransmittal).where(
        EngineeringTransmittal.transmittal_id == transmittal_id
    )
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(transmittal_id)
    return row


def _case_for_deliverable(db: Session, deliverable: EngineeringDeliverable) -> EngineeringCase:
    row = db.scalar(
        select(EngineeringCase).where(
            EngineeringCase.engineering_case_id == deliverable.engineering_case_id
        )
    )
    if not row:
        raise RuntimeError("Az engineering case hiányzik a deliverable mögül.")
    return row


def _emit(
    db: Session,
    case: EngineeringCase,
    *,
    event_type: str,
    object_type: str,
    object_id: str,
    status: str,
    actor: str,
    summary: str,
    route_to: list[str],
    suffix: str = "1",
) -> None:
    ingest_event(
        db,
        EventIn(
            event_id=f"EVT-ENG-{event_type}-{object_id}-{suffix}"[:120],
            dedupe_key=f"engineering:{event_type}:{object_id}:{suffix}"[:255],
            project_id=case.project_id,
            source_module="engineering-workspace",
            event_type=event_type,
            object_type=object_type,
            object_id=object_id,
            status=status,
            executive_relevance=event_type in {
                "ENGINEERING_PROJECT_CREATED",
                "DESIGN_CRITICAL_FINDING",
                "ENGINEERING_CONSTRUCTION_READY",
            },
            payload={"summary": summary, "engineering_case_id": case.engineering_case_id},
            route_to=route_to,
        ),
        actor=actor,
    )


def create_engineering_case(db: Session, data: EngineeringCaseIn, user: object) -> EngineeringCase:
    _role, email = _identity(user, CASE_ROLES)
    existing = db.scalar(select(EngineeringCase).where(EngineeringCase.project_id == data.project_id))
    if existing:
        return existing
    midnight = datetime.combine(data.contract_date, time.min, tzinfo=UTC)
    case = EngineeringCase(
        engineering_case_id=f"ENG-{uuid4().hex[:12].upper()}",
        project_id=data.project_id,
        title=data.title,
        lead_designer=data.lead_designer.strip().lower(),
        project_manager=data.project_manager.strip().lower(),
        contract_date=data.contract_date,
        consultation_due_at=midnight + timedelta(days=3),
        absolute_deadline=midnight + timedelta(days=90),
        source_authority_json=json.dumps(
            {
                "plot": "plotcheck",
                "design_validation": "plancheck",
                "scope_price": "buildconfig",
                "documents": "document-evidence",
                "schedule": "smart-calendar",
                "customer_decisions": "my-imperial",
                "changes": "change-control",
                "finance": "financial-control",
            },
            sort_keys=True,
        ),
        created_by=email,
    )
    db.add(case)
    if not db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == data.project_id)):
        db.add(
            ProjectRegistry(
                project_id=data.project_id,
                name=data.title,
                project_type="design",
                status="active",
                responsible=data.project_manager.strip().lower(),
                next_action="Engineering indulási kapu és szakági deliverable-jegyzék összeállítása.",
            )
        )
    audit(
        db,
        actor=email,
        action="engineering_case_created",
        entity_type="engineering_case",
        entity_id=case.engineering_case_id,
        after=data.model_dump(mode="json"),
    )
    db.flush()
    _emit(
        db,
        case,
        event_type="ENGINEERING_PROJECT_CREATED",
        object_type="EngineeringCase",
        object_id=case.engineering_case_id,
        status=case.status,
        actor=email,
        summary="A ProjectID-alapú engineering case és a 3/90 napos határidők létrejöttek.",
        route_to=["crm", "smart-calendar", "document-evidence", "control-center"],
    )
    db.refresh(case)
    return case


def complete_consultation(db: Session, project_id: str, user: object) -> EngineeringCase:
    _role, email = _identity(user, CASE_ROLES | {"designer"})
    case = _case(db, project_id, lock=True)
    case.consultation_completed_at = case.consultation_completed_at or utcnow()
    if case.status == "planned":
        case.status = "in_design"
    audit(
        db,
        actor=email,
        action="engineering_consultation_completed",
        entity_type="engineering_case",
        entity_id=case.engineering_case_id,
        after={"consultation_completed_at": case.consultation_completed_at.isoformat()},
    )
    db.commit()
    db.refresh(case)
    return case


def create_deliverable(
    db: Session, project_id: str, data: EngineeringDeliverableIn, user: object
) -> EngineeringDeliverable:
    _role, email = _identity(user, CASE_ROLES | {"designer"})
    case = _case(db, project_id)
    existing = db.scalar(
        select(EngineeringDeliverable).where(
            EngineeringDeliverable.engineering_case_id == case.engineering_case_id,
            EngineeringDeliverable.discipline == data.discipline.strip().lower(),
            EngineeringDeliverable.deliverable_code == data.deliverable_code.strip().upper(),
        )
    )
    if existing:
        return existing
    if _aware(data.due_at) > _aware(case.absolute_deadline):
        raise ValueError("A deliverable határideje nem lépheti túl a 90 napos abszolút határidőt.")
    row = EngineeringDeliverable(
        deliverable_id=f"EDL-{uuid4().hex[:12].upper()}",
        engineering_case_id=case.engineering_case_id,
        discipline=data.discipline.strip().lower(),
        deliverable_code=data.deliverable_code.strip().upper(),
        title=data.title.strip(),
        document_type=data.document_type.strip().lower(),
        required=data.required,
        responsible=data.responsible.strip().lower(),
        due_at=data.due_at,
        created_by=email,
    )
    db.add(row)
    audit(
        db,
        actor=email,
        action="engineering_deliverable_created",
        entity_type="engineering_deliverable",
        entity_id=row.deliverable_id,
        after=data.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(row)
    return row


def create_revision(
    db: Session, deliverable_id: str, data: EngineeringRevisionIn, user: object
) -> EngineeringRevision:
    _role, email = _identity(user, AUTHOR_ROLES)
    deliverable = _deliverable(db, deliverable_id, lock=True)
    duplicate = db.scalar(
        select(EngineeringRevision).where(
            EngineeringRevision.source_document_id == data.source_document_id,
            EngineeringRevision.source_version == data.source_version,
        )
    )
    if duplicate:
        if duplicate.deliverable_id != deliverable_id:
            raise ValueError("A forrásdokumentum-verzió már másik deliverable-hez tartozik.")
        return duplicate
    latest = db.scalar(
        select(EngineeringRevision)
        .where(EngineeringRevision.deliverable_id == deliverable_id)
        .order_by(desc(EngineeringRevision.revision))
    )
    revision_no = (latest.revision if latest else 0) + 1
    row = EngineeringRevision(
        revision_id=f"REV-{uuid4().hex[:12].upper()}",
        deliverable_id=deliverable_id,
        revision=revision_no,
        revision_label=f"R{revision_no:02d}",
        source_document_id=data.source_document_id,
        source_version=data.source_version,
        source_url=data.source_url,
        file_name=data.file_name,
        mime_type=data.mime_type,
        file_size=data.file_size,
        content_sha256=data.content_sha256.lower(),
        change_summary=data.change_summary.strip(),
        metadata_json=json.dumps(data.metadata, ensure_ascii=False, sort_keys=True),
        created_by=email,
    )
    db.add(row)
    deliverable.status = "drafting"
    audit(
        db,
        actor=email,
        action="engineering_revision_created",
        entity_type="engineering_revision",
        entity_id=row.revision_id,
        after=data.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(row)
    return row


def submit_revision(db: Session, revision_id: str, user: object) -> EngineeringRevision:
    _role, email = _identity(user, AUTHOR_ROLES)
    row = _revision(db, revision_id, lock=True)
    deliverable = _deliverable(db, row.deliverable_id, lock=True)
    if row.status != "draft":
        raise ValueError("Csak draft tervrevízió küldhető review-ba.")
    if email != row.created_by and email != deliverable.responsible:
        raise PermissionError("Csak a készítő vagy a kijelölt szakági felelős küldheti review-ba.")
    row.status = "review"
    row.submitted_by = email
    row.submitted_at = utcnow()
    deliverable.status = "review"
    audit(
        db,
        actor=email,
        action="engineering_revision_submitted",
        entity_type="engineering_revision",
        entity_id=row.revision_id,
        after={"content_sha256": row.content_sha256},
    )
    db.commit()
    db.refresh(row)
    return row


def review_revision(
    db: Session,
    revision_id: str,
    data: EngineeringRevisionReviewIn,
    user: object,
) -> EngineeringRevision:
    _role, email = _identity(user, REVIEW_ROLES)
    row = _revision(db, revision_id, lock=True)
    deliverable = _deliverable(db, row.deliverable_id, lock=True)
    if row.status != "review":
        raise ValueError("Csak review állapotú tervrevízió bírálható.")
    if email in {row.created_by, row.submitted_by, deliverable.responsible}:
        raise ValueError("A terv készítője vagy szakági felelőse nem hagyhatja jóvá a saját revízióját.")
    row.reviewed_by = email
    row.review_note = data.note.strip()
    row.reviewed_at = utcnow()
    row.status = "approved" if data.decision == "approve" else "rejected"
    deliverable.status = "review" if data.decision == "approve" else "drafting"
    audit(
        db,
        actor=email,
        action=f"engineering_revision_{data.decision}d",
        entity_type="engineering_revision",
        entity_id=row.revision_id,
        after=data.model_dump(),
    )
    db.commit()
    db.refresh(row)
    return row


def release_revision(db: Session, revision_id: str, user: object) -> EngineeringRevision:
    _role, email = _identity(user, RELEASE_ROLES)
    row = _revision(db, revision_id, lock=True)
    deliverable = _deliverable(db, row.deliverable_id, lock=True)
    case = _case_for_deliverable(db, deliverable)
    if row.status != "approved":
        raise ValueError("Csak függetlenül jóváhagyott revízió adható ki.")
    if email in {row.created_by, row.submitted_by, row.reviewed_by, deliverable.responsible}:
        raise ValueError("A kiadónak el kell különülnie a készítőtől, felelőstől és reviewertől.")
    blocking = db.scalars(
        select(EngineeringFinding).where(
            EngineeringFinding.revision_id == row.revision_id,
            EngineeringFinding.blocking.is_(True),
            EngineeringFinding.status != "resolved",
        )
    ).all()
    if blocking:
        raise ValueError("Nyitott blokkoló finding mellett a tervrevízió nem adható ki.")
    current = db.scalar(
        select(EngineeringRevision).where(
            EngineeringRevision.deliverable_id == deliverable.deliverable_id,
            EngineeringRevision.status == "released",
        )
    )
    if current:
        current.status = "superseded"
    row.status = "released"
    row.released_by = email
    row.released_at = utcnow()
    deliverable.current_released_revision = row.revision
    deliverable.status = "released"
    case.status = "coordination"
    audit(
        db,
        actor=email,
        action="engineering_revision_released",
        entity_type="engineering_revision",
        entity_id=row.revision_id,
        after={"content_sha256": row.content_sha256},
    )
    _emit(
        db,
        case,
        event_type="DESIGN_DOCUMENT_APPROVED",
        object_type="DesignDocumentProjection",
        object_id=row.revision_id,
        status=row.status,
        actor=email,
        summary=f"A {deliverable.discipline} {deliverable.title} {row.revision_label} revíziója kiadva.",
        route_to=["plancheck", "document-evidence", "project-control", "smart-calendar"],
        suffix=row.content_sha256[:12],
    )
    db.refresh(row)
    return row


def create_finding(
    db: Session, project_id: str, data: EngineeringFindingIn, user: object
) -> EngineeringFinding:
    _role, email = _identity(user, REVIEW_ROLES | {"designer"})
    case = _case(db, project_id)
    revision = _revision(db, data.revision_id)
    deliverable = _deliverable(db, revision.deliverable_id)
    if deliverable.engineering_case_id != case.engineering_case_id:
        raise ValueError("A finding revíziója másik projekthez tartozik.")
    existing = db.scalar(
        select(EngineeringFinding).where(
            EngineeringFinding.source_fingerprint == data.source_fingerprint
        )
    )
    if existing:
        return existing
    row = EngineeringFinding(
        finding_id=f"FND-{uuid4().hex[:12].upper()}",
        revision_id=revision.revision_id,
        category=data.category.strip().lower(),
        severity=data.severity,
        blocking=data.blocking or data.severity in {"high", "critical"},
        title=data.title.strip(),
        description=data.description.strip(),
        location=data.location,
        responsible=data.responsible.strip().lower(),
        due_at=data.due_at,
        source_module=data.source_module,
        source_fingerprint=data.source_fingerprint,
        created_by=email,
    )
    db.add(row)
    if row.blocking:
        case.status = "hold"
        deliverable.status = "hold"
    audit(
        db,
        actor=email,
        action="engineering_finding_created",
        entity_type="engineering_finding",
        entity_id=row.finding_id,
        after=data.model_dump(mode="json"),
    )
    db.flush()
    if row.severity == "critical":
        _emit(
            db,
            case,
            event_type="DESIGN_CRITICAL_FINDING",
            object_type="DesignFinding",
            object_id=row.finding_id,
            status=row.status,
            actor=email,
            summary=row.title,
            route_to=["workflow-center", "control-center", "project-control"],
        )
    else:
        db.commit()
    db.refresh(row)
    return row


def propose_finding_resolution(
    db: Session,
    finding_id: str,
    data: EngineeringFindingResolutionIn,
    user: object,
) -> EngineeringFinding:
    _role, email = _identity(user, AUTHOR_ROLES)
    row = _finding(db, finding_id, lock=True)
    source_revision = _revision(db, row.revision_id)
    resolution_revision = _revision(db, data.resolution_revision_id)
    if resolution_revision.deliverable_id != source_revision.deliverable_id:
        raise ValueError("A feloldó revíziónak ugyanahhoz a deliverable-höz kell tartoznia.")
    if resolution_revision.revision <= source_revision.revision:
        raise ValueError("Finding csak újabb tervrevízióval oldható fel.")
    if resolution_revision.status not in {"approved", "released"}:
        raise ValueError("A feloldó revíziónak legalább jóváhagyott állapotúnak kell lennie.")
    row.status = "resolution_proposed"
    row.resolution_revision_id = resolution_revision.revision_id
    row.resolution_note = data.note.strip()
    row.resolution_proposed_by = email
    audit(
        db,
        actor=email,
        action="engineering_finding_resolution_proposed",
        entity_type="engineering_finding",
        entity_id=row.finding_id,
        after=data.model_dump(),
    )
    db.commit()
    db.refresh(row)
    return row


def approve_finding_resolution(db: Session, finding_id: str, user: object) -> EngineeringFinding:
    _role, email = _identity(user, REVIEW_ROLES)
    row = _finding(db, finding_id, lock=True)
    if row.status != "resolution_proposed" or not row.resolution_revision_id:
        raise ValueError("Csak bizonyított, új revízióhoz kötött feloldási javaslat zárható le.")
    if email in {row.created_by, row.resolution_proposed_by}:
        raise ValueError("A finding létrehozója vagy a javítás készítője nem zárhatja le saját tételét.")
    row.status = "resolved"
    row.resolved_by = email
    row.resolved_at = utcnow()
    revision = _revision(db, row.revision_id)
    deliverable = _deliverable(db, revision.deliverable_id)
    case = _case_for_deliverable(db, deliverable)
    if not db.scalars(
        select(EngineeringFinding).join(
            EngineeringRevision,
            EngineeringRevision.revision_id == EngineeringFinding.revision_id,
        ).join(
            EngineeringDeliverable,
            EngineeringDeliverable.deliverable_id == EngineeringRevision.deliverable_id,
        ).where(
            EngineeringDeliverable.engineering_case_id == case.engineering_case_id,
            EngineeringFinding.blocking.is_(True),
            EngineeringFinding.status != "resolved",
        )
    ).first():
        case.status = "coordination"
    audit(
        db,
        actor=email,
        action="engineering_finding_resolved",
        entity_type="engineering_finding",
        entity_id=row.finding_id,
        after={"resolution_revision_id": row.resolution_revision_id},
    )
    _emit(
        db,
        case,
        event_type="DESIGN_FINDING_RESOLVED",
        object_type="DesignFinding",
        object_id=row.finding_id,
        status=row.status,
        actor=email,
        summary="A finding újabb tervrevízióval és független review-val lezárult.",
        route_to=["plancheck", "workflow-center", "project-control"],
        suffix=row.resolution_revision_id,
    )
    db.refresh(row)
    return row


def issue_transmittal(
    db: Session, project_id: str, data: EngineeringTransmittalIn, user: object
) -> EngineeringTransmittal:
    _role, email = _identity(user, TRANSMITTAL_ROLES)
    case = _case(db, project_id)
    revisions = [_revision(db, revision_id) for revision_id in dict.fromkeys(data.revision_ids)]
    if len(revisions) != len(data.revision_ids):
        raise ValueError("A transmittal ugyanazt a revíziót csak egyszer tartalmazhatja.")
    for revision in revisions:
        deliverable = _deliverable(db, revision.deliverable_id)
        if deliverable.engineering_case_id != case.engineering_case_id:
            raise ValueError("A transmittal minden revíziójának ugyanahhoz a projekthez kell tartoznia.")
        allowed = {"released"} if data.purpose in {"construction", "authority"} else {"approved", "released"}
        if revision.status not in allowed:
            raise ValueError("A transmittal céljához nem megfelelő állapotú tervrevízió szerepel.")
    package_payload = [
        {"revision_id": row.revision_id, "content_sha256": row.content_sha256}
        for row in sorted(revisions, key=lambda item: item.revision_id)
    ]
    package_sha256 = hashlib.sha256(
        json.dumps(package_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    row = EngineeringTransmittal(
        transmittal_id=f"TRN-{uuid4().hex[:12].upper()}",
        engineering_case_id=case.engineering_case_id,
        purpose=data.purpose,
        subject=data.subject.strip(),
        recipient_name=data.recipient_name.strip(),
        recipient_email=data.recipient_email.strip().lower(),
        message=data.message.strip(),
        package_sha256=package_sha256,
        issued_by=email,
    )
    db.add(row)
    db.flush()
    for revision in revisions:
        db.add(
            EngineeringTransmittalItem(
                transmittal_item_id=f"TRI-{uuid4().hex[:12].upper()}",
                transmittal_id=row.transmittal_id,
                revision_id=revision.revision_id,
                revision_sha256=revision.content_sha256,
            )
        )
    audit(
        db,
        actor=email,
        action="engineering_transmittal_issued",
        entity_type="engineering_transmittal",
        entity_id=row.transmittal_id,
        after={**data.model_dump(), "package_sha256": package_sha256},
    )
    _emit(
        db,
        case,
        event_type="DESIGN_TRANSMITTAL_ISSUED",
        object_type="DesignTransmittal",
        object_id=row.transmittal_id,
        status=row.status,
        actor=email,
        summary=f"{data.purpose} tervcsomag kiadva {data.recipient_email} részére.",
        route_to=["document-evidence", "project-control", "my-imperial"],
        suffix=package_sha256[:12],
    )
    db.refresh(row)
    return row


def acknowledge_transmittal(
    db: Session,
    transmittal_id: str,
    data: EngineeringTransmittalAckIn,
    user: object,
) -> EngineeringTransmittal:
    _role, email = _identity(user, VIEW_ROLES)
    row = _transmittal(db, transmittal_id, lock=True)
    if row.status != "issued":
        raise ValueError("Csak issued transmittal igazolható vissza.")
    row.status = "acknowledged" if data.decision == "acknowledge" else "rejected"
    row.acknowledged_by = email
    row.acknowledged_at = utcnow()
    row.acknowledgement_note = data.note.strip()
    audit(
        db,
        actor=email,
        action=f"engineering_transmittal_{row.status}",
        entity_type="engineering_transmittal",
        entity_id=row.transmittal_id,
        after=data.model_dump(),
    )
    db.commit()
    db.refresh(row)
    return row


def readiness_blockers(db: Session, project_id: str) -> list[str]:
    case = _case(db, project_id)
    blockers: list[str] = []
    if not case.consultation_completed_at:
        blockers.append("A szerződés utáni tervezői konzultáció nincs lezárva.")
    plotcheck = db.scalar(
        select(TechnicalCase).where(
            TechnicalCase.project_id == project_id,
            TechnicalCase.module_key == "plotcheck",
            TechnicalCase.status == "approved",
        )
    )
    if not plotcheck:
        blockers.append("Nincs jóváhagyott PlotCheck-forráspillantkép.")
    deliverables = db.scalars(
        select(EngineeringDeliverable).where(
            EngineeringDeliverable.engineering_case_id == case.engineering_case_id,
            EngineeringDeliverable.required.is_(True),
        )
    ).all()
    if not deliverables:
        blockers.append("Nincs kötelező szakági deliverable meghatározva.")
    current_revision_ids: set[str] = set()
    for deliverable in deliverables:
        if deliverable.current_released_revision is None:
            blockers.append(f"Hiányzik a kiadott {deliverable.discipline} / {deliverable.title} revízió.")
            continue
        revision = db.scalar(
            select(EngineeringRevision).where(
                EngineeringRevision.deliverable_id == deliverable.deliverable_id,
                EngineeringRevision.revision == deliverable.current_released_revision,
                EngineeringRevision.status == "released",
            )
        )
        if not revision:
            blockers.append(f"A {deliverable.title} current revíziója nem hitelesen released.")
        else:
            current_revision_ids.add(revision.revision_id)
    open_blocking = db.scalars(
        select(EngineeringFinding)
        .join(EngineeringRevision, EngineeringRevision.revision_id == EngineeringFinding.revision_id)
        .join(EngineeringDeliverable, EngineeringDeliverable.deliverable_id == EngineeringRevision.deliverable_id)
        .where(
            EngineeringDeliverable.engineering_case_id == case.engineering_case_id,
            EngineeringFinding.blocking.is_(True),
            EngineeringFinding.status != "resolved",
        )
    ).all()
    if open_blocking:
        blockers.append(f"{len(open_blocking)} nyitott blokkoló engineering finding van.")
    changes = db.scalars(
        select(ChangeControlCase).where(
            ChangeControlCase.project_id == project_id,
            ChangeControlCase.status.not_in(("completed", "cancelled")),
        )
    ).all()
    if changes:
        blockers.append(f"{len(changes)} rendezetlen ChangeControl tétel van.")
    finance_plan = db.scalar(
        select(ProjectFinancePlan)
        .where(ProjectFinancePlan.project_id == project_id, ProjectFinancePlan.status == "approved")
        .order_by(desc(ProjectFinancePlan.version))
    )
    if not finance_plan:
        blockers.append("Nincs jóváhagyott végleges projektbudget.")
    elif not db.scalar(
        select(ProjectFinanceCashflowLine).where(ProjectFinanceCashflowLine.plan_id_fk == finance_plan.id)
    ):
        blockers.append("Nincs jóváhagyott budgethez kötött pénzügyi–műszaki cashflow-ütem.")
    acknowledged_items: set[str] = set()
    acknowledged_transmittals = db.scalars(
        select(EngineeringTransmittal).where(
            EngineeringTransmittal.engineering_case_id == case.engineering_case_id,
            EngineeringTransmittal.purpose == "construction",
            EngineeringTransmittal.status == "acknowledged",
        )
    ).all()
    for transmittal in acknowledged_transmittals:
        acknowledged_items.update(
            db.scalars(
                select(EngineeringTransmittalItem.revision_id).where(
                    EngineeringTransmittalItem.transmittal_id == transmittal.transmittal_id
                )
            ).all()
        )
    missing_transmittal = current_revision_ids - acknowledged_items
    if current_revision_ids and missing_transmittal:
        blockers.append(
            f"{len(missing_transmittal)} aktuális tervrevízió nincs visszaigazolt construction transmittalban."
        )
    return blockers


def mark_construction_ready(db: Session, project_id: str, user: object) -> EngineeringCase:
    _role, email = _identity(user, {"project-manager"})
    case = _case(db, project_id, lock=True)
    blockers = readiness_blockers(db, project_id)
    case.readiness_version += 1
    case.readiness_blockers_json = json.dumps(blockers, ensure_ascii=False)
    if blockers:
        case.status = "hold"
        db.commit()
        raise ValueError("Construction-ready STOP: " + " | ".join(blockers))
    case.status = "construction_ready"
    case.construction_ready_by = email
    case.construction_ready_at = utcnow()
    audit(
        db,
        actor=email,
        action="engineering_construction_ready",
        entity_type="engineering_case",
        entity_id=case.engineering_case_id,
        after={"readiness_version": case.readiness_version, "blockers": []},
    )
    _emit(
        db,
        case,
        event_type="ENGINEERING_CONSTRUCTION_READY",
        object_type="PermitReadiness",
        object_id=case.project_id,
        status=case.status,
        actor=email,
        summary="Minden forrásmodul-, szakági-, finding-, pénzügyi- és átadási kapu teljesült.",
        route_to=["project-control", "financial-control", "my-imperial", "control-center"],
        suffix=str(case.readiness_version),
    )
    db.refresh(case)
    return case


def engineering_workspace(db: Session, user: object) -> dict[str, Any]:
    _identity(user, VIEW_ROLES)
    cases = db.scalars(select(EngineeringCase).order_by(desc(EngineeringCase.updated_at))).all()
    deliverables = db.scalars(
        select(EngineeringDeliverable).order_by(EngineeringDeliverable.discipline, EngineeringDeliverable.title)
    ).all()
    revisions = db.scalars(
        select(EngineeringRevision).order_by(desc(EngineeringRevision.created_at))
    ).all()
    findings = db.scalars(
        select(EngineeringFinding).order_by(desc(EngineeringFinding.created_at))
    ).all()
    transmittals = db.scalars(
        select(EngineeringTransmittal).order_by(desc(EngineeringTransmittal.issued_at))
    ).all()
    return {
        "cases": cases,
        "deliverables": deliverables,
        "revisions": revisions,
        "findings": findings,
        "transmittals": transmittals,
        "deliverables_by_case": {
            case.engineering_case_id: [row for row in deliverables if row.engineering_case_id == case.engineering_case_id]
            for case in cases
        },
        "revisions_by_deliverable": {
            row.deliverable_id: [rev for rev in revisions if rev.deliverable_id == row.deliverable_id]
            for row in deliverables
        },
        "metrics": {
            "cases": len(cases),
            "construction_ready": sum(row.status == "construction_ready" for row in cases),
            "released_deliverables": sum(row.status == "released" for row in deliverables),
            "open_blockers": sum(row.blocking and row.status != "resolved" for row in findings),
            "unacknowledged_transmittals": sum(row.status == "issued" for row in transmittals),
            "overdue_cases": sum(
                _aware(row.absolute_deadline) < utcnow() and row.status != "closed" for row in cases
            ),
        },
    }


def serialize(row: object) -> dict[str, Any]:
    table = getattr(row, "__table__", None)
    if table is None:
        raise TypeError("A rekord nem SQLAlchemy modell.")
    return {
        column.name: getattr(row, column.name)
        for column in table.columns
        if column.name != "id"
    }
