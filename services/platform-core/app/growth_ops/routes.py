from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.orm import Session

from ..config import settings as platform_settings
from ..database import get_db
from .models import GrowthRun, OutreachMessage
from .registry import GrowthRegistryError
from .schemas import GrowthControlIn, GrowthSignalIn, OutreachEventIn
from .service import (
    ingest_signal,
    readiness,
    record_outreach_event,
    run_motor,
    set_control_state,
    unsubscribe,
)

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
