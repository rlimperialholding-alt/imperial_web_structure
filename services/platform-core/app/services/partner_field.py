from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    EventRecord,
    OutboxMessage,
    PartnerAttendance,
    PartnerChangeNotice,
    PartnerEvidence,
    PartnerFieldAccess,
    PartnerProgressReport,
    PartnerWorker,
    PMWorkPackage,
    ProjectRegistry,
    SiteIssue,
    TaskRecord,
)
from ..schemas import (
    PartnerAccessCreateIn,
    PartnerAttendanceActionIn,
    PartnerChangeIn,
    PartnerProgressIn,
)
from ..security import hash_password, verify_password


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _actor(access: PartnerFieldAccess) -> str:
    return f"partner:{access.access_id}:{access.company_name}"


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def authenticate_access(db: Session, code: str) -> PartnerFieldAccess | None:
    now = utcnow()
    rows = db.scalars(select(PartnerFieldAccess).where(PartnerFieldAccess.active.is_(True))).all()
    for row in rows:
        valid_from = _as_aware(row.valid_from)
        valid_until = _as_aware(row.valid_until)
        if valid_from and valid_from > now:
            continue
        if valid_until and valid_until < now:
            continue
        if verify_password(code.strip(), row.access_code_hash):
            return row
    return None


def access_is_valid(access: PartnerFieldAccess | None) -> bool:
    if not access or not access.active:
        return False
    now = utcnow()
    valid_from = _as_aware(access.valid_from)
    valid_until = _as_aware(access.valid_until)
    if valid_from and valid_from > now:
        return False
    if valid_until and valid_until < now:
        return False
    return True


def create_access(db: Session, data: PartnerAccessCreateIn, actor: str) -> PartnerFieldAccess:
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == data.project_id))
    if not project:
        raise KeyError(data.project_id)
    if data.work_package_id:
        package = db.scalar(select(PMWorkPackage).where(
            PMWorkPackage.work_package_id == data.work_package_id,
            PMWorkPackage.project_id == data.project_id,
        ))
        if not package:
            raise KeyError(data.work_package_id)
    row = PartnerFieldAccess(
        access_id=_id("PFA"), company_name=data.company_name, company_tax_number=data.company_tax_number,
        contact_name=data.contact_name, contact_phone=data.contact_phone, project_id=data.project_id,
        work_package_id=data.work_package_id, access_code_hash=hash_password(data.access_code),
        active=True, valid_from=utcnow(), valid_until=data.valid_until,
    )
    db.add(row)
    db.flush()
    for name in data.worker_names:
        clean = name.strip()
        if clean:
            db.add(PartnerWorker(worker_id=_id("PWR"), access_id=row.access_id, name=clean, active=True))
    audit(db, actor=actor, action="partner_field.access.create", entity_type="partner_field_access", entity_id=row.access_id,
          after={"company_name": row.company_name, "project_id": row.project_id, "work_package_id": row.work_package_id,
                 "workers": len([x for x in data.worker_names if x.strip()]), "access_code_stored": False})
    db.commit()
    db.refresh(row)
    return row


def deactivate_access(db: Session, access_id: str, actor: str) -> PartnerFieldAccess:
    row = db.scalar(select(PartnerFieldAccess).where(PartnerFieldAccess.access_id == access_id))
    if not row:
        raise KeyError(access_id)
    if not row.active:
        raise ValueError("A hozzáférés már le van zárva.")
    row.active = False
    audit(db, actor=actor, action="partner_field.access.deactivate", entity_type="partner_field_access", entity_id=row.access_id)
    db.commit()
    return row


def partner_dashboard(db: Session, access: PartnerFieldAccess) -> dict:
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == access.project_id))
    package = db.scalar(select(PMWorkPackage).where(PMWorkPackage.work_package_id == access.work_package_id)) if access.work_package_id else None
    workers = db.scalars(select(PartnerWorker).where(
        PartnerWorker.access_id == access.access_id, PartnerWorker.active.is_(True)
    ).order_by(PartnerWorker.name)).all()
    today = utcnow().date()
    attendance = db.scalars(select(PartnerAttendance).where(
        PartnerAttendance.access_id == access.access_id, PartnerAttendance.work_date == today
    ).order_by(PartnerAttendance.check_in_at)).all()
    attendance_map = {a.worker_id: a for a in attendance}
    progress = db.scalars(select(PartnerProgressReport).where(
        PartnerProgressReport.access_id == access.access_id
    ).order_by(desc(PartnerProgressReport.created_at)).limit(20)).all()
    changes = db.scalars(select(PartnerChangeNotice).where(
        PartnerChangeNotice.access_id == access.access_id
    ).order_by(desc(PartnerChangeNotice.created_at)).limit(20)).all()
    evidence = db.scalars(select(PartnerEvidence).where(
        PartnerEvidence.access_id == access.access_id
    ).order_by(desc(PartnerEvidence.created_at)).limit(24)).all()
    open_count = sum(1 for a in attendance if a.status == "open")
    closed_hours = Decimal("0")
    for a in attendance:
        if a.check_in_at and a.check_out_at:
            check_out_at = _as_aware(a.check_out_at)
            check_in_at = _as_aware(a.check_in_at)
            if check_out_at is None or check_in_at is None:
                continue
            seconds = Decimal(str((check_out_at - check_in_at).total_seconds()))
            closed_hours += seconds / Decimal("3600")
    return {
        "access": access, "project": project, "package": package, "workers": workers,
        "attendance": attendance, "attendance_map": attendance_map, "progress_reports": progress,
        "change_notices": changes, "evidence": evidence,
        "metrics": {"workers": len(workers), "present_now": open_count, "closed_hours": closed_hours.quantize(Decimal("0.1"))},
    }


def attendance_action(db: Session, access: PartnerFieldAccess, data: PartnerAttendanceActionIn) -> list[PartnerAttendance]:
    if data.action not in {"check_in", "check_out"}:
        raise ValueError("Ismeretlen jelenléti művelet.")
    if not data.declaration_accepted:
        raise ValueError("A valós jelenlétről szóló nyilatkozat elfogadása kötelező.")
    workers = db.scalars(select(PartnerWorker).where(
        PartnerWorker.access_id == access.access_id,
        PartnerWorker.worker_id.in_(data.worker_ids),
        PartnerWorker.active.is_(True),
    )).all()
    if len(workers) != len(set(data.worker_ids)):
        raise PermissionError("A munkavállaló nem tartozik ehhez a hozzáféréshez.")
    now = utcnow()
    today = now.date()
    changed: list[PartnerAttendance] = []
    for worker in workers:
        row = db.scalar(select(PartnerAttendance).where(
            PartnerAttendance.worker_id == worker.worker_id,
            PartnerAttendance.project_id == access.project_id,
            PartnerAttendance.work_date == today,
        ))
        if data.action == "check_in":
            if row and row.check_in_at:
                raise ValueError(f"{worker.name} ma már bejelentkezett.")
            row = row or PartnerAttendance(
                attendance_id=_id("ATT"), access_id=access.access_id, worker_id=worker.worker_id,
                project_id=access.project_id, work_package_id=access.work_package_id, work_date=today,
            )
            row.check_in_at = now
            row.check_in_latitude = data.latitude
            row.check_in_longitude = data.longitude
            row.location_accuracy_m = data.accuracy_m
            row.status = "open"
            if row.id is None:
                db.add(row)
        else:
            if not row or not row.check_in_at:
                raise ValueError(f"{worker.name} nincs bejelentkezve.")
            if row.check_out_at:
                raise ValueError(f"{worker.name} ma már kijelentkezett.")
            row.check_out_at = now
            row.check_out_latitude = data.latitude
            row.check_out_longitude = data.longitude
            row.location_accuracy_m = data.accuracy_m or row.location_accuracy_m
            row.status = "closed"
        row.source_device_id = data.source_device_id
        row.declaration_accepted = True
        row.note = data.note
        changed.append(row)
    event = EventRecord(
        event_id=_id("EVT"), dedupe_key=f"PARTNER_ATT:{access.access_id}:{data.action}:{uuid4().hex}",
        project_id=access.project_id, source_module="partner_connect", event_type="SUBCONTRACTOR_ATTENDANCE_UPDATED",
        object_type="PartnerAttendanceBatch", object_id=_id("ATB"), severity="info", status="closed",
        responsible=access.company_name, executive_relevance=False,
        payload_json=json.dumps({"action": data.action, "worker_ids": data.worker_ids, "work_package_id": access.work_package_id}, ensure_ascii=False),
    )
    db.add(event)
    audit(db, actor=_actor(access), action=f"partner_field.attendance.{data.action}", entity_type="attendance_batch", entity_id=event.object_id or "",
          after={"workers": data.worker_ids, "project_id": access.project_id, "location_supplied": data.latitude is not None})
    db.commit()
    return changed


def create_progress(db: Session, access: PartnerFieldAccess, data: PartnerProgressIn) -> PartnerProgressReport:
    row = PartnerProgressReport(
        progress_report_id=_id("PPR"), access_id=access.access_id, project_id=access.project_id,
        work_package_id=access.work_package_id, report_date=utcnow().date(),
        reported_progress_pct=data.reported_progress_pct, quantity=data.quantity, unit=data.unit,
        summary=data.summary, problem_text=data.problem_text, safety_note=data.safety_note,
        quality_note=data.quality_note, source_device_id=data.source_device_id,
    )
    db.add(row)
    task = TaskRecord(
        task_id=_id("TASK"), project_id=access.project_id,
        title=f"Alvállalkozói haladás ellenőrzése – {access.company_name}",
        description=data.summary, assignee="Projektvezetés", due_at=utcnow()+timedelta(days=1),
        priority="high" if data.problem_text else "normal", status="open", executive_relevance=bool(data.problem_text),
    )
    db.add(task)
    event = EventRecord(
        event_id=_id("EVT"), dedupe_key=f"PARTNER_PROGRESS:{row.progress_report_id}",
        project_id=access.project_id, source_module="partner_connect", event_type="SUBCONTRACTOR_PROGRESS_REPORTED",
        object_type="PartnerProgressReport", object_id=row.progress_report_id,
        severity="high" if data.problem_text else "info", status="open", responsible="Projektvezetés",
        next_action="Alvállalkozói jelentés műszaki ellenőrzése és jóváhagyása.", executive_relevance=bool(data.problem_text),
        payload_json=json.dumps({"company": access.company_name, "work_package_id": access.work_package_id,
                                 "reported_progress_pct": data.reported_progress_pct, "problem_text": data.problem_text}, ensure_ascii=False),
    )
    db.add(event)
    db.add(OutboxMessage(
        message_id=_id("OUT"), source_event_id=event.event_id, destination_module="project_control",
        endpoint="/commands/partner-progress-review", payload_json=event.payload_json, status="pending", max_retries=5,
    ))
    audit(db, actor=_actor(access), action="partner_field.progress.create", entity_type="partner_progress", entity_id=row.progress_report_id,
          after={"project_id": access.project_id, "work_package_id": access.work_package_id,
                 "reported_progress_pct": data.reported_progress_pct, "problem": bool(data.problem_text)})
    db.commit()
    db.refresh(row)
    return row


def review_progress(db: Session, progress_report_id: str, decision: str, actor: str) -> PartnerProgressReport:
    row = db.scalar(select(PartnerProgressReport).where(PartnerProgressReport.progress_report_id == progress_report_id).with_for_update())
    if not row:
        raise KeyError(progress_report_id)
    if decision not in {"approved", "rejected"}:
        raise ValueError("Ismeretlen döntés.")
    if row.status != "pending_review":
        raise ValueError("A haladási jelentést már elbírálták.")
    before = {"status": row.status}
    row.status = decision
    row.reviewed_by = actor
    row.reviewed_at = utcnow()
    if decision == "approved" and row.work_package_id and row.reported_progress_pct is not None:
        package = db.scalar(select(PMWorkPackage).where(PMWorkPackage.work_package_id == row.work_package_id))
        if package:
            package.progress_pct = row.reported_progress_pct
            if package.progress_pct >= 100:
                package.progress_pct = 100
                package.status = "done"
                package.actual_end = package.actual_end or utcnow()
            elif package.progress_pct > 0 and package.status == "planned":
                package.status = "in_progress"
                package.actual_start = package.actual_start or utcnow()
            package.updated_at = utcnow()
    audit(db, actor=actor, action="partner_field.progress.review", entity_type="partner_progress", entity_id=row.progress_report_id,
          before=before, after={"status": decision, "applied_to_work_package": decision == "approved"})
    db.commit()
    return row


def create_partner_issue(db: Session, access: PartnerFieldAccess, *, issue_type: str, severity: str, title: str,
                         description: str | None, location: str | None, source_device_id: str | None) -> SiteIssue:
    row = SiteIssue(
        issue_id=_id("ISS"), project_id=access.project_id, work_package_id=access.work_package_id,
        issue_type=issue_type, severity=severity, title=title, description=description,
        location=location, responsible="Projektvezetés", due_at=utcnow()+timedelta(days=1), status="open",
    )
    db.add(row)
    db.add(TaskRecord(
        task_id=_id("TASK"), project_id=access.project_id, title=title, description=description,
        assignee="Projektvezetés", due_at=utcnow()+timedelta(days=1),
        priority="critical" if severity == "critical" else "high", status="open",
        executive_relevance=severity in {"critical", "high"},
    ))
    event_type = "QUALITY_VARIANCE_DETECTED" if issue_type == "quality" else "SITE_BLOCKER_RECORDED"
    db.add(EventRecord(
        event_id=_id("EVT"), dedupe_key=f"PARTNER_ISSUE:{row.issue_id}", project_id=access.project_id,
        source_module="partner_connect", event_type=event_type, object_type="SiteIssue", object_id=row.issue_id,
        severity=severity, status="open", responsible="Projektvezetés", next_action=title,
        executive_relevance=severity in {"critical", "high"},
        payload_json=json.dumps({"company": access.company_name, "work_package_id": access.work_package_id,
                                 "issue_type": issue_type, "source_device_id": source_device_id}, ensure_ascii=False),
    ))
    audit(db, actor=_actor(access), action="partner_field.issue.create", entity_type="site_issue", entity_id=row.issue_id,
          after={"project_id": access.project_id, "type": issue_type, "severity": severity})
    db.commit()
    db.refresh(row)
    return row


def create_change(db: Session, access: PartnerFieldAccess, data: PartnerChangeIn) -> PartnerChangeNotice:
    if not access.can_report_changes:
        raise PermissionError("Ehhez a hozzáféréshez nincs változásbejelentési jogosultság.")
    row = PartnerChangeNotice(
        change_notice_id=_id("PCN"), access_id=access.access_id, project_id=access.project_id,
        work_package_id=access.work_package_id, change_type=data.change_type, title=data.title,
        description=data.description, requested_by=data.requested_by or access.contact_name or access.company_name,
        deadline_impact_days=data.deadline_impact_days, source_device_id=data.source_device_id,
    )
    db.add(row)
    task = TaskRecord(
        task_id=_id("TASK"), project_id=access.project_id, title=f"Változásbejelentés: {data.title}",
        description=data.description, assignee="Projektvezetés / ChangeControl", due_at=utcnow()+timedelta(days=1),
        priority="high", status="open", executive_relevance=True,
    )
    db.add(task)
    event = EventRecord(
        event_id=_id("EVT"), dedupe_key=f"PARTNER_CHANGE:{row.change_notice_id}",
        project_id=access.project_id, source_module="partner_connect", event_type="SUBCONTRACTOR_CHANGE_REPORTED",
        object_type="PartnerChangeNotice", object_id=row.change_notice_id, severity="high", status="open",
        deadline_impact_days=data.deadline_impact_days, responsible="Projektvezetés / ChangeControl",
        next_action="Műszaki, ár- és határidőhatás vizsgálata; automatikus scope- vagy árváltozás tilos.",
        executive_relevance=True,
        payload_json=json.dumps({"company": access.company_name, "work_package_id": access.work_package_id,
                                 "change_type": data.change_type, "automatic_scope_change": False,
                                 "automatic_price_change": False}, ensure_ascii=False),
    )
    db.add(event)
    db.add(OutboxMessage(
        message_id=_id("OUT"), source_event_id=event.event_id, destination_module="change_control",
        endpoint="/commands/subcontractor-change-intake", payload_json=event.payload_json, status="pending", max_retries=5,
    ))
    audit(db, actor=_actor(access), action="partner_field.change.create", entity_type="partner_change", entity_id=row.change_notice_id,
          after={"project_id": access.project_id, "work_package_id": access.work_package_id,
                 "automatic_scope_change": False, "automatic_price_change": False})
    db.commit()
    db.refresh(row)
    return row


_ALLOWED_IMAGES = {
    "image/jpeg": (".jpg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "image/png": (".png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/webp": (".webp", lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
}
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_DEFAULT_PROJECT_EVIDENCE_QUOTA_BYTES = 5 * 1024 * 1024 * 1024


def save_evidence(db: Session, access: PartnerFieldAccess, *, file_name: str, mime_type: str, raw: bytes,
                  category: str, caption: str | None, progress_report_id: str | None,
                  issue_id: str | None, change_notice_id: str | None, latitude: Decimal | None,
                  longitude: Decimal | None, source_device_id: str | None, storage_root: Path) -> PartnerEvidence:
    if mime_type not in _ALLOWED_IMAGES:
        raise ValueError("Csak JPG, PNG vagy WEBP kép tölthető fel.")
    if not raw or len(raw) > _MAX_IMAGE_BYTES:
        raise ValueError("A kép üres vagy nagyobb 12 MB-nál.")
    ensure_project_evidence_quota(db, access.project_id, len(raw))
    extension, validator = _ALLOWED_IMAGES[mime_type]
    if not validator(raw):
        raise ValueError("A fájl tartalma nem egyezik a képformátummal.")
    if progress_report_id and not db.scalar(select(PartnerProgressReport).where(
        PartnerProgressReport.progress_report_id == progress_report_id,
        PartnerProgressReport.access_id == access.access_id,
    )):
        raise PermissionError("A haladási jelentés nem tartozik ehhez a hozzáféréshez.")
    if change_notice_id and not db.scalar(select(PartnerChangeNotice).where(
        PartnerChangeNotice.change_notice_id == change_notice_id,
        PartnerChangeNotice.access_id == access.access_id,
    )):
        raise PermissionError("A változásbejelentés nem tartozik ehhez a hozzáféréshez.")
    safe_project = re.sub(r"[^A-Za-z0-9_-]", "_", access.project_id)
    folder = storage_root / safe_project
    folder.mkdir(parents=True, exist_ok=True)
    evidence_id = _id("PEV")
    stored_name = f"{evidence_id}{extension}"
    path = folder / stored_name
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    row = PartnerEvidence(
        evidence_id=evidence_id, access_id=access.access_id, project_id=access.project_id,
        work_package_id=access.work_package_id, progress_report_id=progress_report_id,
        issue_id=issue_id, change_notice_id=change_notice_id, category=category,
        file_name=Path(file_name or stored_name).name[:500], mime_type=mime_type,
        file_size=len(raw), sha256=digest, storage_path=str(path), caption=caption,
        latitude=latitude, longitude=longitude, source_device_id=source_device_id,
    )
    db.add(row)
    audit(db, actor=_actor(access), action="partner_field.evidence.upload", entity_type="partner_evidence", entity_id=row.evidence_id,
          after={"project_id": access.project_id, "category": category, "mime_type": mime_type,
                 "file_size": len(raw), "sha256": digest})
    db.commit()
    db.refresh(row)
    return row


def ensure_project_evidence_quota(
    db: Session,
    project_id: str,
    incoming_bytes: int,
    *,
    quota_bytes: int | None = None,
) -> None:
    quota = quota_bytes
    if quota is None:
        raw_quota = os.getenv(
            "PARTNER_EVIDENCE_PROJECT_QUOTA_BYTES",
            str(_DEFAULT_PROJECT_EVIDENCE_QUOTA_BYTES),
        )
        try:
            quota = int(raw_quota)
        except ValueError as exc:
            raise ValueError(
                "A PARTNER_EVIDENCE_PROJECT_QUOTA_BYTES egész szám kell legyen."
            ) from exc
    if quota < _MAX_IMAGE_BYTES:
        raise ValueError("A projekt bizonyítéktár-korlátja nem lehet 12 MB-nál kisebb.")
    used = db.scalar(
        select(func.coalesce(func.sum(PartnerEvidence.file_size), 0)).where(
            PartnerEvidence.project_id == project_id
        )
    )
    if int(used or 0) + incoming_bytes > quota:
        quota_gib = quota / 1024 / 1024 / 1024
        raise ValueError(
            f"A projekt bizonyítéktára elérte a {quota_gib:.1f} GB-os korlátot. "
            "Kérj külön fájlszerver-kapacitást."
        )


def internal_partner_projection(db: Session, project_id: str) -> dict:
    accesses = db.scalars(select(PartnerFieldAccess).where(
        PartnerFieldAccess.project_id == project_id
    ).order_by(desc(PartnerFieldAccess.active), PartnerFieldAccess.company_name)).all()
    progress = db.scalars(select(PartnerProgressReport).where(
        PartnerProgressReport.project_id == project_id
    ).order_by(desc(PartnerProgressReport.created_at)).limit(50)).all()
    changes = db.scalars(select(PartnerChangeNotice).where(
        PartnerChangeNotice.project_id == project_id
    ).order_by(desc(PartnerChangeNotice.created_at)).limit(50)).all()
    today = utcnow().date()
    attendance = db.scalars(select(PartnerAttendance).where(
        PartnerAttendance.project_id == project_id, PartnerAttendance.work_date == today
    ).order_by(PartnerAttendance.check_in_at)).all()
    workers_by_id = {w.worker_id: w for w in db.scalars(select(PartnerWorker).where(
        PartnerWorker.access_id.in_([a.access_id for a in accesses] or ["__none__"])
    )).all()}
    access_by_id = {a.access_id: a for a in accesses}
    return {
        "partner_accesses": accesses, "partner_progress": progress, "partner_changes": changes,
        "partner_attendance": attendance, "partner_workers_by_id": workers_by_id,
        "partner_access_by_id": access_by_id,
        "partner_metrics": {
            "active_accesses": sum(1 for a in accesses if a.active),
            "present_now": sum(1 for a in attendance if a.status == "open"),
            "pending_progress": sum(1 for p in progress if p.status == "pending_review"),
            "open_changes": sum(1 for c in changes if c.status == "reported"),
        },
    }
