from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..models import (
    BookingExperienceVersion,
    BookingRecord,
    BookingSlot,
    HouseDesignerEntitlement,
    HouseDesignEstimateSnapshot,
    HouseDesignRenderRevision,
    HouseDesignRevision,
    HouseDesignScheduleSnapshot,
    HouseDesignSession,
    HouseDesignSnapshot,
    HouseDesignSubmission,
    HouseDesignSubmissionDecision,
    ProjectRegistry,
    RegulatoryComplianceRun,
)
from ..schemas import BookingCreateIn, EventIn
from .booking_reservation import create_booking
from .house_designer import ActorScope, HouseDesignerError, decode_revision_site
from .house_designer_geometry import canonical_sha256
from .integration import ingest_event

HOUSE_DESIGN_TERMS_VERSION = "HD-TERMS-2026-08-10-V1"
HOUSE_DESIGN_NOTICE_VERSION = "HD-PRIVACY-2026-08-10-V1"
COMMERCIAL_INTAKE_PROJECT = "HOUSE-DESIGNER-INTAKE"
SUBMISSION_FINAL_STATUSES = frozenset({"ACCEPTED", "REJECTED", "CANCELLED"})
SALES_REVIEW_ROLES = frozenset({"sales", "project-manager", "managing-director", "owner"})
DESIGN_REVIEW_ROLES = frozenset(
    {"designer", "technical-prep", "project-manager", "managing-director", "owner"}
)
COMPLIANCE_REVIEW_ROLES = frozenset({"legal", "managing-director", "owner"})
PRICING_REVIEW_ROLES = frozenset({"finance", "managing-director", "owner"})


def approval_panel(db: Session, *, session_id: str, actor: ActorScope) -> dict[str, Any]:
    session = _session(db, session_id, actor)
    revision = _revision(db, session)
    snapshots = db.scalars(
        select(HouseDesignSnapshot)
        .where(HouseDesignSnapshot.session_id == session_id)
        .order_by(desc(HouseDesignSnapshot.approved_at))
        .limit(20)
    ).all()
    submissions = db.scalars(
        select(HouseDesignSubmission)
        .where(HouseDesignSubmission.session_id == session_id)
        .order_by(desc(HouseDesignSubmission.created_at))
        .limit(20)
    ).all()
    current_snapshot = next(
        (row for row in snapshots if row.design_revision_id == revision.revision_id), None
    )
    return {
        "canAct": session.owner_subject_id == actor.subject_id,
        "termsVersionId": HOUSE_DESIGN_TERMS_VERSION,
        "noticeVersionId": HOUSE_DESIGN_NOTICE_VERSION,
        "currentSnapshot": _snapshot_result(current_snapshot) if current_snapshot else None,
        "snapshots": [_snapshot_result(row) for row in snapshots],
        "submissions": [_submission_result(row) for row in submissions],
        "consultationSlots": available_consultation_slots(
            db, tenant_id=actor.tenant_id, brand_id=session.brand_id
        ),
        "orderGate": _order_gate(db, session, revision, current_snapshot),
    }


def approve_current_design(
    db: Session,
    *,
    session_id: str,
    actor: ActorScope,
    selected_render_id: str,
    terms_version_id: str,
    notice_version_id: str,
    terms_accepted: bool,
    notice_accepted: bool,
) -> dict[str, Any]:
    if not terms_accepted or terms_version_id != HOUSE_DESIGN_TERMS_VERSION:
        raise HouseDesignerError(
            "terms_not_accepted", "A megjelenített felhasználási feltételeket el kell fogadni."
        )
    if not notice_accepted or notice_version_id != HOUSE_DESIGN_NOTICE_VERSION:
        raise HouseDesignerError(
            "privacy_notice_not_accepted",
            "A megjelenített adatkezelési tájékoztató elfogadása kötelező.",
        )
    session = _session(db, session_id, actor, lock=True, owner_only=True)
    if session.status in {"SUBMITTED", "ARCHIVED", "CANCELLED"}:
        raise HouseDesignerError(
            "session_not_approvable",
            "A házterv ebben az állapotban nem hagyható jóvá.",
            status_code=409,
        )
    revision = _revision(db, session)
    compliance = _latest_compliance(db, session_id, revision.revision_id)
    if compliance is None or compliance.outcome != "PASS" or not compliance.ruleset_id:
        raise HouseDesignerError(
            "compliance_pass_required",
            "Jóváhagyáshoz a jelenlegi tervverzión igazolt PASS megfelelőség szükséges.",
            status_code=409,
        )
    estimate = _latest_estimate(db, session_id, revision.revision_id)
    schedule = _latest_schedule(db, session_id, revision.revision_id)
    if estimate is None or schedule is None:
        raise HouseDesignerError(
            "estimate_schedule_required",
            "Jóváhagyáshoz aktuális ár- és ütemsnapshot szükséges.",
            status_code=409,
        )
    now = _now()
    if _aware(estimate.valid_until) < now or _aware(schedule.valid_until) < now:
        raise HouseDesignerError(
            "estimate_schedule_expired",
            "Az ár- vagy ütemsnapshot lejárt; új számítás szükséges.",
            status_code=409,
        )
    if estimate.input_sha256 != schedule.input_sha256:
        raise HouseDesignerError(
            "estimate_schedule_mismatch",
            "Az ár és az ütem nem ugyanahhoz a konfigurációhoz tartozik.",
            status_code=409,
        )
    render = db.scalar(
        select(HouseDesignRenderRevision).where(
            HouseDesignRenderRevision.render_id == selected_render_id,
            HouseDesignRenderRevision.session_id == session_id,
            HouseDesignRenderRevision.design_revision_id == revision.revision_id,
        )
    )
    if render is None or render.status not in {"ready", "completed", "accepted"}:
        raise HouseDesignerError(
            "render_not_approvable",
            "A kiválasztott látvány nem elérhető vagy nincs kész.",
            status_code=409,
        )
    geometry_hash = canonical_sha256(json.loads(revision.geometry_json))
    if render.geometry_lock_sha256 != geometry_hash:
        raise HouseDesignerError(
            "render_geometry_mismatch",
            "A látvány nem a jelenlegi alaprajzhoz tartozik.",
            status_code=409,
        )
    manifest = {
        "schemaVersion": "house-design-approval-v1",
        "sessionId": session_id,
        "designRevisionId": revision.revision_id,
        "designSha256": revision.canonical_sha256,
        "complianceRunId": compliance.run_id,
        "complianceInputSha256": compliance.input_sha256,
        "rulesetId": compliance.ruleset_id,
        "rulesetSha256": compliance.ruleset_sha256,
        "estimateId": estimate.estimate_id,
        "estimateSha256": estimate.canonical_sha256,
        "estimateNonProduction": estimate.non_production,
        "scheduleId": schedule.schedule_id,
        "scheduleSha256": schedule.canonical_sha256,
        "scheduleNonProduction": schedule.non_production,
        "selectedRenderId": render.render_id,
        "renderGeometrySha256": render.geometry_lock_sha256,
        "renderAssetSha256": render.asset_sha256,
        "renderNonProduction": render.non_production,
        "termsVersionId": terms_version_id,
        "noticeVersionId": notice_version_id,
    }
    manifest_sha256 = _sha(manifest)
    replay = db.scalar(
        select(HouseDesignSnapshot).where(HouseDesignSnapshot.manifest_sha256 == manifest_sha256)
    )
    if replay:
        if replay.session_id != session_id or replay.approved_by_subject_id != actor.subject_id:
            raise HouseDesignerError(
                "approval_manifest_collision",
                "A jóváhagyási lenyomat más hozzáférési körhöz tartozik.",
                status_code=409,
            )
        return _snapshot_result(replay)
    snapshot = HouseDesignSnapshot(
        snapshot_id=_id("HDA"),
        session_id=session_id,
        design_revision_id=revision.revision_id,
        compliance_run_id=compliance.run_id,
        estimate_id=estimate.estimate_id,
        schedule_id=schedule.schedule_id,
        selected_render_id=render.render_id,
        terms_version_id=terms_version_id,
        consent_version_id=notice_version_id,
        manifest_json=_json(manifest),
        manifest_sha256=manifest_sha256,
        approved_by_subject_id=actor.subject_id,
    )
    render.accepted_by = actor.subject_id
    render.accepted_at = now
    if render.status == "ready":
        render.status = "accepted"
    session.status = "CUSTOMER_APPROVED"
    session.row_version += 1
    session.updated_by = actor.subject_id
    db.add(snapshot)
    audit(
        db,
        actor=actor.subject_id,
        action="house_designer.design.approve",
        entity_type="HouseDesignSnapshot",
        entity_id=snapshot.snapshot_id,
        after={
            "session_id": session_id,
            "revision_id": revision.revision_id,
            "manifest_sha256": manifest_sha256,
            "production_ready": not any(
                (estimate.non_production, schedule.non_production, render.non_production)
            ),
        },
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        replay = db.scalar(
            select(HouseDesignSnapshot).where(
                HouseDesignSnapshot.manifest_sha256 == manifest_sha256
            )
        )
        if (
            replay is not None
            and replay.session_id == session_id
            and replay.approved_by_subject_id == actor.subject_id
        ):
            return _snapshot_result(replay)
        raise HouseDesignerError(
            "approval_conflict",
            "A tervet párhuzamosan módosították vagy jóváhagyták; töltse újra az oldalt.",
            status_code=409,
        ) from error
    return _snapshot_result(snapshot)


def available_consultation_slots(
    db: Session, *, tenant_id: str, brand_id: str, limit: int = 30
) -> list[dict[str, Any]]:
    del tenant_id  # Booking experiences are brand-scoped in the canonical booking engine.
    now = _now()
    rows = db.execute(
        select(BookingSlot, BookingExperienceVersion)
        .join(
            BookingExperienceVersion,
            BookingExperienceVersion.experience_id == BookingSlot.experience_id,
        )
        .where(
            BookingSlot.brand_id == brand_id,
            BookingSlot.booking_type.in_(("personal", "online")),
            BookingSlot.status == "available",
            BookingSlot.starts_at > now,
            BookingExperienceVersion.active.is_(True),
        )
        .order_by(BookingSlot.starts_at)
        .limit(limit)
    ).all()
    return [
        {
            "slotId": slot.slot_id,
            "experienceId": experience.experience_id,
            "displayName": experience.display_name,
            "bookingType": slot.booking_type,
            "advisorEmail": slot.advisor_email,
            "startsAt": slot.starts_at,
            "endsAt": slot.ends_at,
            "location": slot.location,
        }
        for slot, experience in rows
    ]


def book_consultation(
    db: Session,
    *,
    session_id: str,
    actor: ActorScope,
    snapshot_id: str,
    slot_id: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str,
    plot_status: str,
    planned_start: str,
    notice_version_id: str,
    notice_accepted: bool,
    idempotency_key: str,
) -> dict[str, Any]:
    if not notice_accepted or notice_version_id != HOUSE_DESIGN_NOTICE_VERSION:
        raise HouseDesignerError(
            "privacy_notice_not_accepted",
            "Foglaláshoz az adatkezelési tájékoztató elfogadása kötelező.",
        )
    if not idempotency_key.strip():
        raise HouseDesignerError("idempotency_key_required", "Műveletazonosító szükséges.")
    session = _session(db, session_id, actor, lock=True, owner_only=True)
    revision = _revision(db, session)
    snapshot = _current_snapshot(db, session, revision, snapshot_id)
    replay = db.scalar(
        select(HouseDesignSubmission).where(
            HouseDesignSubmission.tenant_id == actor.tenant_id,
            HouseDesignSubmission.idempotency_key == idempotency_key.strip(),
        )
    )
    if replay:
        booking = db.scalar(
            select(BookingRecord).where(BookingRecord.booking_id == replay.booking_id)
        )
        if (
            replay.session_id == session_id
            and replay.snapshot_id == snapshot_id
            and replay.submission_type == "CONSULTATION_REQUEST"
            and booking is not None
            and booking.slot_id == slot_id
            and booking.customer_email == customer_email.strip().lower()
        ):
            return _consultation_result(replay, booking)
        raise HouseDesignerError(
            "idempotency_collision",
            "A műveletazonosító más konzultációhoz tartozik.",
            status_code=409,
        )
    site = decode_revision_site(revision)
    booking = create_booking(
        db,
        BookingCreateIn(
            slot_id=slot_id,
            project_id=session.project_id,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            project_description=(
                f"Háztervező konzultáció: {session.title}. "
                f"Terv: {session.session_id}, jóváhagyás: {snapshot.snapshot_id}."
            ),
            plot_status=plot_status,
            planned_start=planned_start,
            postal_code=str(site.get("postalCode") or "") or None,
            city=str(site.get("city") or "") or None,
            street_address=str(site.get("address") or "") or None,
            document_url=f"/house-designer/sessions/{session_id}",
            consent_version_id=notice_version_id,
            consent=True,
            attribution={
                "source": "house-designer",
                "sessionId": session_id,
                "revisionId": revision.revision_id,
                "snapshotId": snapshot.snapshot_id,
                "snapshotSha256": snapshot.manifest_sha256,
            },
        ),
        actor=actor.subject_id,
    )
    submission = HouseDesignSubmission(
        submission_id=_id("HDSUB"),
        tenant_id=actor.tenant_id,
        brand_id=session.brand_id,
        session_id=session_id,
        snapshot_id=snapshot.snapshot_id,
        snapshot_sha256=snapshot.manifest_sha256,
        submission_type="CONSULTATION_REQUEST",
        status="CALENDAR_SYNC_PENDING",
        customer_subject_id=actor.subject_id,
        lead_id=booking.lead_id,
        opportunity_id=booking.opportunity_id,
        project_id=booking.project_id,
        booking_id=booking.booking_id,
        idempotency_key=idempotency_key.strip(),
        attribution_json=booking.attribution_json,
        notice_version_id=notice_version_id,
        notice_accepted_at=_now(),
        created_by=actor.subject_id,
    )
    session.project_id = booking.project_id
    session.row_version += 1
    session.updated_by = actor.subject_id
    db.add(submission)
    audit(
        db,
        actor=actor.subject_id,
        action="house_designer.consultation.book",
        entity_type="HouseDesignSubmission",
        entity_id=submission.submission_id,
        after={
            "session_id": session_id,
            "snapshot_id": snapshot.snapshot_id,
            "booking_id": booking.booking_id,
            "project_id": booking.project_id,
        },
    )
    db.commit()
    return _consultation_result(submission, booking)


def submit_order_request(
    db: Session,
    *,
    session_id: str,
    actor: ActorScope,
    snapshot_id: str,
    notice_version_id: str,
    notice_accepted: bool,
    idempotency_key: str,
) -> dict[str, Any]:
    if not idempotency_key.strip():
        raise HouseDesignerError("idempotency_key_required", "Műveletazonosító szükséges.")
    if not notice_accepted or notice_version_id != HOUSE_DESIGN_NOTICE_VERSION:
        raise HouseDesignerError(
            "privacy_notice_not_accepted",
            "Beküldéshez az adatkezelési tájékoztató elfogadása kötelező.",
        )
    session = _session(db, session_id, actor, lock=True, owner_only=True)
    revision = _revision(db, session)
    snapshot = _current_snapshot(db, session, revision, snapshot_id)
    replay = db.scalar(
        select(HouseDesignSubmission).where(
            HouseDesignSubmission.tenant_id == actor.tenant_id,
            HouseDesignSubmission.idempotency_key == idempotency_key.strip(),
        )
    )
    if replay:
        if (
            replay.session_id == session_id
            and replay.snapshot_id == snapshot_id
            and replay.submission_type == "ORDER_REQUEST"
        ):
            return _submission_result(replay)
        raise HouseDesignerError(
            "idempotency_collision", "A műveletazonosító más beküldéshez tartozik.", status_code=409
        )
    existing_order = db.scalar(
        select(HouseDesignSubmission).where(
            HouseDesignSubmission.session_id == session_id,
            HouseDesignSubmission.snapshot_id == snapshot_id,
            HouseDesignSubmission.submission_type == "ORDER_REQUEST",
            HouseDesignSubmission.status.not_in(("CANCELLED", "REJECTED")),
        )
    )
    if existing_order:
        raise HouseDesignerError(
            "order_already_submitted",
            "Ehhez a jóváhagyott tervcsomaghoz már tartozik megrendelési igény.",
            status_code=409,
        )
    gate = _order_gate(db, session, revision, snapshot)
    if not gate["open"]:
        raise HouseDesignerError(
            "order_gate_closed",
            "A megrendelési kapu zárva: " + "; ".join(gate["reasons"]),
            status_code=409,
        )
    project_id = session.project_id or COMMERCIAL_INTAKE_PROJECT
    _ensure_intake_project(db, project_id)
    submission = HouseDesignSubmission(
        submission_id=_id("HDSUB"),
        tenant_id=actor.tenant_id,
        brand_id=session.brand_id,
        session_id=session_id,
        snapshot_id=snapshot.snapshot_id,
        snapshot_sha256=snapshot.manifest_sha256,
        submission_type="ORDER_REQUEST",
        status="RECEIVED",
        customer_subject_id=actor.subject_id,
        project_id=project_id,
        idempotency_key=idempotency_key.strip(),
        attribution_json=_json({"source": "house-designer"}),
        notice_version_id=notice_version_id,
        notice_accepted_at=_now(),
        created_by=actor.subject_id,
    )
    session.project_id = project_id
    session.status = "SUBMITTED"
    session.row_version += 1
    session.updated_by = actor.subject_id
    db.add(submission)
    db.flush()
    audit(
        db,
        actor=actor.subject_id,
        action="house_designer.order.submit",
        entity_type="HouseDesignSubmission",
        entity_id=submission.submission_id,
        after={"snapshot_id": snapshot.snapshot_id, "project_id": project_id},
    )
    ingest_event(
        db,
        EventIn(
            event_id=_id("EVT"),
            dedupe_key=f"house-designer-order:{submission.submission_id}",
            project_id=project_id,
            source_module="house-designer",
            event_type="HOUSE_DESIGN_ORDER_REQUESTED",
            object_type="HouseDesignSubmission",
            object_id=submission.submission_id,
            status=submission.status,
            responsible="ertekesites@imperialholding.hu",
            next_action=(
                "Az értékesítő ellenőrizze a jóváhagyott tervcsomagot, majd vegye fel "
                "a kapcsolatot az ügyféllel."
            ),
            payload={
                "summary": (
                    "Ügyfél által jóváhagyott, produkciós kapukon átment "
                    "házterv-megrendelési igény."
                ),
                "session_id": session_id,
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_sha256": snapshot.manifest_sha256,
            },
            route_to=["crm", "sales", "smart-calendar"],
        ),
        actor=actor.subject_id,
    )
    db.commit()
    return _submission_result(submission)


def submission_detail(db: Session, *, submission_id: str, actor: ActorScope) -> dict[str, Any]:
    submission = db.scalar(
        select(HouseDesignSubmission).where(
            HouseDesignSubmission.submission_id == submission_id,
            HouseDesignSubmission.tenant_id == actor.tenant_id,
        )
    )
    if submission is None:
        raise HouseDesignerError(
            "submission_not_found", "A beküldés nem található.", status_code=404
        )
    _session(db, submission.session_id, actor)
    return _submission_result(submission)


def list_submission_queue(
    db: Session, *, actor: ActorScope, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    query = select(HouseDesignSubmission).where(
        HouseDesignSubmission.tenant_id == actor.tenant_id,
        HouseDesignSubmission.brand_id.in_(actor.brand_ids),
        HouseDesignSubmission.submission_type == "ORDER_REQUEST",
    )
    if status:
        query = query.where(HouseDesignSubmission.status == status)
    if actor.can_read_all_owned:
        if actor.denied_project_ids:
            query = query.where(
                or_(
                    HouseDesignSubmission.project_id.not_in(actor.denied_project_ids),
                    HouseDesignSubmission.customer_subject_id == actor.subject_id,
                )
            )
    else:
        readable = [HouseDesignSubmission.customer_subject_id == actor.subject_id]
        if actor.project_ids:
            readable.append(HouseDesignSubmission.project_id.in_(actor.project_ids))
        query = query.where(or_(*readable))
    rows = db.scalars(
        query.order_by(
            desc(HouseDesignSubmission.updated_at), desc(HouseDesignSubmission.id)
        ).limit(limit)
    ).all()
    return [_submission_result(row) for row in rows]


def submission_review_detail(
    db: Session, *, submission_id: str, actor: ActorScope
) -> dict[str, Any]:
    submission = db.scalar(
        select(HouseDesignSubmission).where(
            HouseDesignSubmission.submission_id == submission_id,
            HouseDesignSubmission.tenant_id == actor.tenant_id,
            HouseDesignSubmission.submission_type == "ORDER_REQUEST",
        )
    )
    if submission is None:
        raise HouseDesignerError(
            "submission_not_found", "A beküldés nem található.", status_code=404
        )
    session = _session(db, submission.session_id, actor)
    decisions = db.scalars(
        select(HouseDesignSubmissionDecision)
        .where(HouseDesignSubmissionDecision.submission_id == submission_id)
        .order_by(HouseDesignSubmissionDecision.id)
    ).all()
    return {
        **_submission_result(submission),
        "sessionTitle": session.title,
        "customerSubjectId": submission.customer_subject_id,
        "snapshotSha256": submission.snapshot_sha256,
        "decisions": [_decision_result(row) for row in decisions],
        "allowedActions": _allowed_submission_actions(submission.status),
    }


def transition_submission_review(
    db: Session,
    *,
    submission_id: str,
    actor: ActorScope,
    actor_role: str,
    action: str,
    note: str,
    expected_row_version: int,
    idempotency_key: str,
    booking_id: str | None = None,
) -> dict[str, Any]:
    action = action.strip().lower()
    note = note.strip()
    idempotency_key = idempotency_key.strip()
    if not idempotency_key:
        raise HouseDesignerError("idempotency_key_required", "Műveletazonosító szükséges.")
    if len(note) < 10 or len(note) > 4_000:
        raise HouseDesignerError(
            "review_note_invalid", "A döntés indoklása 10–4000 karakter lehet."
        )
    replay = db.scalar(
        select(HouseDesignSubmissionDecision).where(
            HouseDesignSubmissionDecision.tenant_id == actor.tenant_id,
            HouseDesignSubmissionDecision.idempotency_key == idempotency_key,
        )
    )
    if replay is not None:
        if (
            replay.submission_id == submission_id
            and replay.action == action
            and replay.expected_row_version == expected_row_version
            and replay.note == note
            and replay.actor_subject_id == actor.subject_id
        ):
            return submission_review_detail(db, submission_id=submission_id, actor=actor)
        raise HouseDesignerError(
            "idempotency_collision",
            "A műveletazonosító eltérő submission döntéshez tartozik.",
            status_code=409,
        )
    submission = db.scalar(
        select(HouseDesignSubmission)
        .where(
            HouseDesignSubmission.submission_id == submission_id,
            HouseDesignSubmission.tenant_id == actor.tenant_id,
            HouseDesignSubmission.submission_type == "ORDER_REQUEST",
        )
        .with_for_update()
    )
    if submission is None:
        raise HouseDesignerError(
            "submission_not_found", "A beküldés nem található.", status_code=404
        )
    session = _session(db, submission.session_id, actor)
    if not submission.project_id:
        raise HouseDesignerError(
            "submission_project_missing",
            "Projektazonosító nélküli beküldés review-ja biztonsági okból nem indítható.",
            status_code=409,
        )
    if submission.row_version != expected_row_version:
        raise HouseDesignerError(
            "stale_submission", "A beküldés időközben módosult.", status_code=409
        )
    next_status, lane = _submission_transition(
        submission.status, action=action, actor_role=actor_role
    )
    if action in {"confirm_compliance", "confirm_pricing"}:
        review_started = db.scalar(
            select(HouseDesignSubmissionDecision)
            .where(
                HouseDesignSubmissionDecision.submission_id == submission_id,
                HouseDesignSubmissionDecision.action == "forward_design_review",
            )
            .order_by(desc(HouseDesignSubmissionDecision.id))
        )
        if review_started is None:
            raise HouseDesignerError(
                "submission_review_cycle_missing",
                "A compliance- és pricing-döntéshez dokumentált design review ciklus szükséges.",
                status_code=409,
            )
        cycle_confirmations = db.scalars(
            select(HouseDesignSubmissionDecision).where(
                HouseDesignSubmissionDecision.submission_id == submission_id,
                HouseDesignSubmissionDecision.action.in_(("confirm_compliance", "confirm_pricing")),
                HouseDesignSubmissionDecision.expected_row_version
                >= review_started.resulting_row_version,
            )
        ).all()
        if any(row.action == action for row in cycle_confirmations):
            raise HouseDesignerError(
                "submission_confirmation_exists",
                "Ebben a review-ciklusban ez az ellenőrzési sáv már jóváhagyott.",
                status_code=409,
            )
        if any(row.actor_subject_id == actor.subject_id for row in cycle_confirmations):
            raise HouseDesignerError(
                "submission_four_eyes_required",
                "A compliance- és pricing-ellenőrzést külön személyeknek kell rögzíteniük.",
                status_code=409,
            )
    if action == "accept":
        review_started = db.scalar(
            select(HouseDesignSubmissionDecision)
            .where(
                HouseDesignSubmissionDecision.submission_id == submission_id,
                HouseDesignSubmissionDecision.action == "forward_design_review",
            )
            .order_by(desc(HouseDesignSubmissionDecision.id))
        )
        confirmations = db.scalars(
            select(HouseDesignSubmissionDecision).where(
                HouseDesignSubmissionDecision.submission_id == submission_id,
                HouseDesignSubmissionDecision.action.in_(("confirm_compliance", "confirm_pricing")),
                HouseDesignSubmissionDecision.expected_row_version
                >= (
                    review_started.resulting_row_version
                    if review_started
                    else submission.row_version
                ),
            )
        ).all()
        confirmation_by_action = {row.action: row for row in confirmations}
        if set(confirmation_by_action) != {"confirm_compliance", "confirm_pricing"}:
            raise HouseDesignerError(
                "submission_gate_reviews_required",
                "Elfogadáshoz az aktuális review-ciklusban külön compliance- és "
                "pricing-ellenőrzés szükséges.",
                status_code=409,
            )
        confirmation_subjects = {row.actor_subject_id for row in confirmation_by_action.values()}
        if len(confirmation_subjects) != 2 or actor.subject_id in confirmation_subjects:
            raise HouseDesignerError(
                "submission_four_eyes_required",
                "A compliance-, pricing- és végső tervezői döntést külön személyeknek "
                "kell rögzíteniük.",
                status_code=409,
            )
    if action == "cancel" and session.owner_subject_id != actor.subject_id:
        raise HouseDesignerError(
            "submission_cancel_forbidden",
            "Csak a beküldő ügyfél vonhatja vissza a kérelmet.",
            status_code=403,
        )
    if action != "cancel" and session.owner_subject_id == actor.subject_id:
        raise HouseDesignerError(
            "independent_review_required",
            "A beküldő nem végezhet belső review döntést.",
            status_code=403,
        )
    if action == "link_consultation":
        booking = db.scalar(
            select(BookingRecord).where(
                BookingRecord.booking_id == str(booking_id or ""),
                BookingRecord.project_id == submission.project_id,
                BookingRecord.brand_id == submission.brand_id,
                BookingRecord.status.not_in(("cancelled", "expired")),
            )
        )
        if booking is None:
            raise HouseDesignerError(
                "consultation_booking_invalid",
                "Csak a submission projektjéhez tartozó aktív foglalás kapcsolható.",
                status_code=409,
            )
        submission.booking_id = booking.booking_id
    previous_status = submission.status
    submission.status = next_status
    submission.row_version += 1
    if next_status == "CHANGES_REQUESTED":
        session.status = "STALE"
        session.row_version += 1
        session.updated_by = actor.subject_id
    elif next_status == "CANCELLED":
        session.status = "CANCELLED"
        session.row_version += 1
        session.updated_by = actor.subject_id
    decision = HouseDesignSubmissionDecision(
        decision_id=_id("HDSD"),
        submission_id=submission.submission_id,
        tenant_id=submission.tenant_id,
        brand_id=submission.brand_id,
        project_id=str(submission.project_id or ""),
        review_lane=lane,
        action=action,
        from_status=previous_status,
        to_status=next_status,
        note=note,
        expected_row_version=expected_row_version,
        resulting_row_version=submission.row_version,
        actor_subject_id=actor.subject_id,
        actor_role=actor_role,
        idempotency_key=idempotency_key,
    )
    db.add(decision)
    db.flush()
    audit(
        db,
        actor=actor.subject_id,
        action=f"house_designer.submission.{action}",
        entity_type="HouseDesignSubmission",
        entity_id=submission.submission_id,
        before={"status": previous_status, "row_version": expected_row_version},
        after={
            "status": next_status,
            "row_version": submission.row_version,
            "decision_id": decision.decision_id,
            "review_lane": lane,
        },
    )
    ingest_event(
        db,
        EventIn(
            event_id=_id("EVT"),
            dedupe_key=f"house-designer-submission:{decision.decision_id}",
            project_id=str(submission.project_id),
            source_module="house-designer",
            event_type=(
                "HOUSE_DESIGN_CHANGES_REQUESTED"
                if next_status == "CHANGES_REQUESTED"
                else "HOUSE_DESIGN_SUBMISSION_STATUS_CHANGED"
            ),
            object_type="HouseDesignSubmission",
            object_id=submission.submission_id,
            status=next_status,
            responsible="ertekesites@imperialholding.hu",
            next_action=note,
            payload={
                "summary": f"House Designer submission: {previous_status} → {next_status}",
                "decision_id": decision.decision_id,
                "review_lane": lane,
                "snapshot_sha256": submission.snapshot_sha256,
            },
            route_to=["crm", "sales", "my-imperial"],
        ),
        actor=actor.subject_id,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HouseDesignerError(
            "submission_transition_conflict",
            "A döntést egy párhuzamos művelet már módosította.",
            status_code=409,
        ) from exc
    return submission_review_detail(db, submission_id=submission_id, actor=actor)


def _submission_transition(status: str, *, action: str, actor_role: str) -> tuple[str, str]:
    rules: dict[str, tuple[frozenset[str], str, str, frozenset[str]]] = {
        "start_sales_review": (
            frozenset({"RECEIVED", "CONSULTATION_BOOKED"}),
            "SALES_REVIEW",
            "sales",
            SALES_REVIEW_ROLES,
        ),
        "forward_design_review": (
            frozenset({"SALES_REVIEW"}),
            "DESIGN_REVIEW",
            "sales",
            SALES_REVIEW_ROLES,
        ),
        "request_changes": (
            frozenset({"SALES_REVIEW", "DESIGN_REVIEW", "CONSULTATION_BOOKED"}),
            "CHANGES_REQUESTED",
            "design" if status == "DESIGN_REVIEW" else "sales",
            DESIGN_REVIEW_ROLES if status == "DESIGN_REVIEW" else SALES_REVIEW_ROLES,
        ),
        "accept": (frozenset({"DESIGN_REVIEW"}), "ACCEPTED", "design", DESIGN_REVIEW_ROLES),
        "confirm_compliance": (
            frozenset({"DESIGN_REVIEW"}),
            "DESIGN_REVIEW",
            "compliance",
            COMPLIANCE_REVIEW_ROLES,
        ),
        "confirm_pricing": (
            frozenset({"DESIGN_REVIEW"}),
            "DESIGN_REVIEW",
            "pricing",
            PRICING_REVIEW_ROLES,
        ),
        "reject": (
            frozenset({"SALES_REVIEW", "DESIGN_REVIEW"}),
            "REJECTED",
            "design" if status == "DESIGN_REVIEW" else "sales",
            DESIGN_REVIEW_ROLES if status == "DESIGN_REVIEW" else SALES_REVIEW_ROLES,
        ),
        "link_consultation": (
            frozenset({"RECEIVED", "SALES_REVIEW", "DESIGN_REVIEW"}),
            "CONSULTATION_BOOKED",
            "sales",
            SALES_REVIEW_ROLES,
        ),
        "cancel": (
            frozenset(
                {
                    "RECEIVED",
                    "SALES_REVIEW",
                    "DESIGN_REVIEW",
                    "CHANGES_REQUESTED",
                    "CONSULTATION_BOOKED",
                }
            ),
            "CANCELLED",
            "customer",
            frozenset(
                {
                    "customer",
                    "owner",
                    "managing-director",
                    "platform-admin",
                    "sales",
                    "designer",
                    "technical-prep",
                    "project-manager",
                }
            ),
        ),
    }
    rule = rules.get(action)
    if rule is None:
        raise HouseDesignerError("submission_action_invalid", "Ismeretlen review művelet.")
    from_statuses, next_status, lane, roles = rule
    if status in SUBMISSION_FINAL_STATUSES or status not in from_statuses:
        raise HouseDesignerError(
            "submission_transition_invalid",
            f"A {status} állapotból a {action} művelet nem hajtható végre.",
            status_code=409,
        )
    if actor_role not in roles:
        raise HouseDesignerError(
            "submission_review_forbidden",
            "Ehhez a review lépéshez nincs jogosultsága.",
            status_code=403,
        )
    return next_status, lane


def _allowed_submission_actions(status: str) -> list[str]:
    actions = {
        "RECEIVED": ["start_sales_review", "link_consultation"],
        "SALES_REVIEW": ["forward_design_review", "request_changes", "reject", "link_consultation"],
        "DESIGN_REVIEW": [
            "confirm_compliance",
            "confirm_pricing",
            "accept",
            "request_changes",
            "reject",
            "link_consultation",
        ],
        "CONSULTATION_BOOKED": ["start_sales_review", "request_changes"],
    }
    return actions.get(status, [])


def _order_gate(
    db: Session,
    session: HouseDesignSession,
    revision: HouseDesignRevision,
    snapshot: HouseDesignSnapshot | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    now = _now()
    if not settings.house_design_order_intake_enabled:
        reasons.append("a környezeti megrendelésfogadási kill switch ki van kapcsolva")
    entitlement = db.scalar(
        select(HouseDesignerEntitlement).where(
            HouseDesignerEntitlement.tenant_id == session.tenant_id,
            HouseDesignerEntitlement.brand_id == session.brand_id,
        )
    )
    if (
        entitlement is None
        or entitlement.status != "active"
        or not entitlement.order_intake_enabled
    ):
        reasons.append("az éles megrendelésfogadás nincs engedélyezve")
    elif _aware(entitlement.valid_from) > now or (
        entitlement.valid_until and _aware(entitlement.valid_until) < now
    ):
        reasons.append("a Háztervező jogosultsága nem hatályos")
    if entitlement is not None and not all(
        (
            entitlement.production_render_enabled,
            entitlement.production_pricing_enabled,
            entitlement.production_capacity_enabled,
        )
    ):
        reasons.append("a produkciós render, ár vagy kapacitás adapter hiányzik")
    if snapshot is None or snapshot.design_revision_id != revision.revision_id:
        reasons.append("a jelenlegi tervverzió nincs jóváhagyva")
        return {"open": False, "reasons": reasons}
    compliance = db.scalar(
        select(RegulatoryComplianceRun).where(
            RegulatoryComplianceRun.run_id == snapshot.compliance_run_id,
            RegulatoryComplianceRun.revision_id == revision.revision_id,
        )
    )
    estimate = db.scalar(
        select(HouseDesignEstimateSnapshot).where(
            HouseDesignEstimateSnapshot.estimate_id == snapshot.estimate_id,
            HouseDesignEstimateSnapshot.design_revision_id == revision.revision_id,
        )
    )
    schedule = db.scalar(
        select(HouseDesignScheduleSnapshot).where(
            HouseDesignScheduleSnapshot.schedule_id == snapshot.schedule_id,
            HouseDesignScheduleSnapshot.design_revision_id == revision.revision_id,
        )
    )
    render = db.scalar(
        select(HouseDesignRenderRevision).where(
            HouseDesignRenderRevision.render_id == snapshot.selected_render_id,
            HouseDesignRenderRevision.design_revision_id == revision.revision_id,
        )
    )
    if compliance is None or compliance.outcome != "PASS" or not compliance.ruleset_id:
        reasons.append("nincs aktuális, igazolt PASS megfelelőségi eredmény")
    if estimate is None or estimate.non_production or _aware(estimate.valid_until) < now:
        reasons.append("nincs érvényes produkciós ársnapshot")
    if schedule is None or schedule.non_production or _aware(schedule.valid_until) < now:
        reasons.append("nincs érvényes produkciós kapacitás- és ütemsnapshot")
    if (
        render is None
        or render.non_production
        or render.status not in {"accepted", "completed"}
        or not render.asset_ref
        or not render.asset_sha256
    ):
        reasons.append("nincs elfogadott, ellenőrzött produkciós látvány")
    return {"open": not reasons, "reasons": reasons}


def _session(
    db: Session,
    session_id: str,
    actor: ActorScope,
    *,
    lock: bool = False,
    owner_only: bool = False,
) -> HouseDesignSession:
    query = select(HouseDesignSession).where(
        HouseDesignSession.session_id == session_id,
        HouseDesignSession.tenant_id == actor.tenant_id,
    )
    session = db.scalar(query.with_for_update() if lock else query)
    readable = (
        session is not None
        and session.brand_id in actor.brand_ids
        and actor.can_read(session.owner_subject_id, session.project_id)
    )
    if (
        session is None
        or not readable
        or (owner_only and session.owner_subject_id != actor.subject_id)
    ):
        raise HouseDesignerError("session_not_found", "A házterv nem található.", status_code=404)
    return session


def _revision(db: Session, session: HouseDesignSession) -> HouseDesignRevision:
    revision = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == session.current_revision_id
        )
    )
    if revision is None:
        raise HouseDesignerError(
            "current_revision_missing", "A terv aktuális verziója nem elérhető.", status_code=409
        )
    return revision


def _current_snapshot(
    db: Session,
    session: HouseDesignSession,
    revision: HouseDesignRevision,
    snapshot_id: str,
) -> HouseDesignSnapshot:
    snapshot = db.scalar(
        select(HouseDesignSnapshot).where(
            HouseDesignSnapshot.snapshot_id == snapshot_id,
            HouseDesignSnapshot.session_id == session.session_id,
            HouseDesignSnapshot.design_revision_id == revision.revision_id,
        )
    )
    if snapshot is None:
        raise HouseDesignerError(
            "current_approval_required",
            "A jelenlegi tervverzió jóváhagyása szükséges.",
            status_code=409,
        )
    return snapshot


def _latest_compliance(
    db: Session, session_id: str, revision_id: str
) -> RegulatoryComplianceRun | None:
    return db.scalar(
        select(RegulatoryComplianceRun)
        .where(
            RegulatoryComplianceRun.session_id == session_id,
            RegulatoryComplianceRun.revision_id == revision_id,
        )
        .order_by(desc(RegulatoryComplianceRun.completed_at), desc(RegulatoryComplianceRun.id))
    )


def _latest_estimate(
    db: Session, session_id: str, revision_id: str
) -> HouseDesignEstimateSnapshot | None:
    return db.scalar(
        select(HouseDesignEstimateSnapshot)
        .where(
            HouseDesignEstimateSnapshot.session_id == session_id,
            HouseDesignEstimateSnapshot.design_revision_id == revision_id,
        )
        .order_by(
            desc(HouseDesignEstimateSnapshot.created_at), desc(HouseDesignEstimateSnapshot.id)
        )
    )


def _latest_schedule(
    db: Session, session_id: str, revision_id: str
) -> HouseDesignScheduleSnapshot | None:
    return db.scalar(
        select(HouseDesignScheduleSnapshot)
        .where(
            HouseDesignScheduleSnapshot.session_id == session_id,
            HouseDesignScheduleSnapshot.design_revision_id == revision_id,
        )
        .order_by(
            desc(HouseDesignScheduleSnapshot.created_at), desc(HouseDesignScheduleSnapshot.id)
        )
    )


def _ensure_intake_project(db: Session, project_id: str) -> None:
    if db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id)):
        return
    db.add(
        ProjectRegistry(
            project_id=project_id,
            name="Háztervező értékesítési intake",
            project_type="commercial_pipeline",
            status="active",
            responsible="ertekesites@imperialholding.hu",
            next_action="A beérkezett háztervek értékesítési feldolgozása.",
        )
    )
    db.flush()


def _snapshot_result(row: HouseDesignSnapshot) -> dict[str, Any]:
    manifest = json.loads(row.manifest_json)
    return {
        "snapshotId": row.snapshot_id,
        "sessionId": row.session_id,
        "designRevisionId": row.design_revision_id,
        "manifestSha256": row.manifest_sha256,
        "approvedBy": row.approved_by_subject_id,
        "approvedAt": row.approved_at,
        "productionReady": not any(
            (
                manifest.get("estimateNonProduction", True),
                manifest.get("scheduleNonProduction", True),
                manifest.get("renderNonProduction", True),
            )
        ),
    }


def _submission_result(row: HouseDesignSubmission) -> dict[str, Any]:
    return {
        "submissionId": row.submission_id,
        "sessionId": row.session_id,
        "snapshotId": row.snapshot_id,
        "submissionType": row.submission_type,
        "status": row.status,
        "projectId": row.project_id,
        "bookingId": row.booking_id,
        "leadId": row.lead_id,
        "opportunityId": row.opportunity_id,
        "rowVersion": row.row_version,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


def _decision_result(row: HouseDesignSubmissionDecision) -> dict[str, Any]:
    return {
        "decisionId": row.decision_id,
        "reviewLane": row.review_lane,
        "action": row.action,
        "fromStatus": row.from_status,
        "toStatus": row.to_status,
        "note": row.note,
        "actorSubjectId": row.actor_subject_id,
        "actorRole": row.actor_role,
        "resultingRowVersion": row.resulting_row_version,
        "createdAt": row.created_at,
    }


def _consultation_result(
    submission: HouseDesignSubmission, booking: BookingRecord
) -> dict[str, Any]:
    return {
        **_submission_result(submission),
        "slotId": booking.slot_id,
        "bookingStatus": booking.status,
        "calendarSyncStatus": booking.external_sync_status,
        "calendarEntryId": booking.calendar_entry_id,
    }


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex.upper()}"
