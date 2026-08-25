from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.orm import Session

from ..config import settings as platform_settings
from ..database import get_db
from .models import GrowthRun, OutreachMessage
from .registry import GrowthRegistryError
from .schemas import GrowthControlIn, GrowthSignalIn, OutreachEventIn, OutreachReleaseIn
from .service import (
    ingest_signal,
    readiness,
    record_outreach_event,
    release_outreach,
    run_motor,
    set_control_state,
    unsubscribe,
)
from .wide_service import readiness as canonical_wide_readiness
from .wide_service import refresh_daily_run

router = APIRouter()


def require_internal_token(
    x_internal_job_token: str | None = Header(default=None, alias="X-Internal-Job-Token"),
) -> None:
    expected = platform_settings.internal_job_token
    if (
        not expected
        or not x_internal_job_token
        or not hmac.compare_digest(expected, x_internal_job_token)
    ):
        raise HTTPException(status_code=401, detail="invalid internal token")


def _run(row: GrowthRun) -> dict:
    return {
        "run_id": row.run_id,
        "motor_key": row.motor_key,
        "status": row.status,
        "attempted": row.attempted_sources,
        "succeeded": row.succeeded_sources,
        "raw": row.raw_signals,
        "accepted": row.accepted_signals,
        "queued": row.queued_outreach,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


def _outreach(row: OutreachMessage) -> dict:
    return {
        "outreach_id": row.outreach_id,
        "signal_id": row.signal_id,
        "brand_id": row.brand_id,
        "status": row.status,
        "sequence_step": row.sequence_step,
        "attempt_count": row.attempt_count,
        "sent_at": row.sent_at,
        "delivered_at": row.delivered_at,
        "response_at": row.response_at,
    }


def _outreach_artifact(row: OutreachMessage) -> dict:
    return {
        **_outreach(row),
        "sender_email": row.sender_email,
        "recipient_email": row.recipient_email,
        "subject": row.subject,
        "body_text": row.body_text,
        "body_html": row.body_html,
        "payload_sha256": row.payload_sha256,
        "release_approved_by": row.release_approved_by,
        "release_approved_at": row.release_approved_at,
    }


@router.get("/api/internal/growth-ops/readiness", dependencies=[Depends(require_internal_token)])
def growth_readiness(db: Session = Depends(get_db)):  # noqa: B008
    ready, detail = readiness(db)
    if not ready:
        raise HTTPException(status_code=503, detail=detail)
    return {"status": "ready", **detail}


@router.post("/api/internal/growth-ops/signals", dependencies=[Depends(require_internal_token)])
def growth_signal_ingest(data: GrowthSignalIn, db: Session = Depends(get_db)):  # noqa: B008
    try:
        return ingest_signal(db, data).model_dump(mode="json")
    except GrowthRegistryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/api/internal/growth-ops/motors/{motor_key}/run",
    dependencies=[Depends(require_internal_token)],
)
def growth_motor_run(motor_key: str, db: Session = Depends(get_db)):  # noqa: B008
    try:
        return _run(run_motor(db, motor_key))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown motor") from exc
    except GrowthRegistryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/api/internal/growth-ops/motors/{motor_key}/control",
    dependencies=[Depends(require_internal_token)],
)
def growth_motor_control(
    motor_key: str,
    data: GrowthControlIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    try:
        row = set_control_state(
            db,
            motor_key,
            enabled=data.enabled,
            reason=data.reason,
            actor="growth-admin",
        )
        return {"motor_key": motor_key, "enabled": row.enabled, "changed_at": row.changed_at}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/api/internal/growth-ops/outreach/{outreach_id}/events",
    dependencies=[Depends(require_internal_token)],
)
def growth_outreach_event(
    outreach_id: str,
    data: OutreachEventIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    try:
        return _outreach(record_outreach_event(db, outreach_id, data))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown outreach") from exc


@router.post(
    "/api/internal/growth-ops/outreach/{outreach_id}/release",
    dependencies=[Depends(require_internal_token)],
)
def growth_outreach_release(
    outreach_id: str,
    data: OutreachReleaseIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    try:
        return _outreach(release_outreach(db, outreach_id, data))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown outreach") from exc
    except (GrowthRegistryError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/api/internal/growth-ops/outreach/{outreach_id}/artifact",
    dependencies=[Depends(require_internal_token)],
)
def growth_outreach_artifact(
    outreach_id: str,
    db: Session = Depends(get_db),  # noqa: B008
):
    row = db.query(OutreachMessage).filter(OutreachMessage.outreach_id == outreach_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="unknown outreach")
    return _outreach_artifact(row)


@router.get(
    "/api/internal/growth-ops/canonical/readiness",
    dependencies=[Depends(require_internal_token)],
)
def canonical_growth_readiness(db: Session = Depends(get_db)):  # noqa: B008
    return canonical_wide_readiness(db)


@router.post(
    "/api/internal/growth-ops/canonical/runs/today",
    dependencies=[Depends(require_internal_token)],
)
def canonical_growth_run_today(db: Session = Depends(get_db)):  # noqa: B008
    try:
        row = refresh_daily_run(db)
    except GrowthRegistryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "run_id": row.run_id,
        "status": row.status,
        "route_attempts": row.route_attempts,
        "unique_leads": row.unique_leads,
        "question_topics": row.question_topics,
        "content_brands": row.content_brands,
        "internal_handoff_status": row.internal_handoff_status,
        "external_outreach_status": row.external_outreach_status,
        "external_publication_status": row.external_publication_status,
    }


@router.get("/growth/unsubscribe/{token}", response_class=Response)
def growth_unsubscribe(token: str, db: Session = Depends(get_db)):  # noqa: B008
    try:
        unsubscribe(db, token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="invalid unsubscribe link") from exc
    return Response(
        "A leiratkozást rögzítettük. Erre a címre nem küldünk további megkeresést.",
        media_type="text/plain; charset=utf-8",
    )
