from __future__ import annotations

import hmac
import json
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..config import settings as platform_settings
from ..database import get_db
from .canonical_templates import CanonicalFirstContactRegistry
from .email import EmailDeliveryError
from .models import GrowthRun, OutreachMessage
from .registry import GrowthRegistryError
from .scheduled_gmail_auth import (
    ScheduledGmailAuthError,
    ScheduledGmailAuthorizationError,
    ScheduledGmailClientPrincipal,
    ScheduledGmailPermission,
    authenticate_scheduled_gmail_client,
)
from .scheduled_gmail_escrow_service import (
    abort_scheduled_gmail_escrow_permit,
    issue_scheduled_gmail_escrow_bundle,
    scheduled_gmail_escrow_bundle_status,
    sync_scheduled_gmail_escrow_events,
)
from .schemas import (
    CanonicalFirstContactRenderIn,
    GrowthControlIn,
    GrowthSignalIn,
    OutreachEventIn,
    OutreachReleaseIn,
    PublicLandNameFallbackPromotionIn,
    PublicLandPolicyReplayIn,
    ScheduledGmailAbortIn,
    ScheduledGmailEscrowAbortIn,
    ScheduledGmailEscrowBundleIn,
    ScheduledGmailEscrowSyncIn,
    ScheduledGmailFinalizeIn,
    ScheduledGmailLeaseIn,
)
from .service import (
    abort_scheduled_gmail_outreach,
    finalize_scheduled_gmail_outreach,
    ingest_signal,
    lease_scheduled_gmail_outreach,
    promote_public_land_name_fallback_signals,
    readiness,
    record_outreach_event,
    release_outreach,
    run_motor,
    scheduled_gmail_coordination_readiness,
    scheduled_gmail_lease_status,
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


def _scheduled_gmail_principal(
    authorization: str | None,
    *,
    permission: ScheduledGmailPermission,
) -> ScheduledGmailClientPrincipal:
    try:
        return authenticate_scheduled_gmail_client(
            authorization,
            required_permission=permission,
        )
    except ScheduledGmailAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ScheduledGmailAuthError as exc:
        status = 503 if str(exc) != "scheduled_gmail_client_authentication_failed" else 401
        raise HTTPException(status_code=status, detail=str(exc)) from exc


def _scheduled_gmail_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ScheduledGmailAuthorizationError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


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
    try:
        canonical_metadata = json.loads(row.receipt_json or "{}").get("canonical_template")
    except json.JSONDecodeError:
        canonical_metadata = None
    return {
        **_outreach(row),
        "sender_email": row.sender_email,
        "recipient_email": row.recipient_email,
        "subject": row.subject,
        "body_text": row.body_text,
        "body_html": row.body_html or (
            canonical_metadata.get("body_html")
            if isinstance(canonical_metadata, dict)
            else None
        ),
        "canonical_template": canonical_metadata,
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


@router.get(
    "/api/internal/growth-ops/canonical-first-contact/readiness",
    dependencies=[Depends(require_internal_token)],
)
def canonical_first_contact_readiness():
    try:
        return CanonicalFirstContactRegistry.load().readiness()
    except GrowthRegistryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/api/internal/growth-ops/canonical-first-contact/render",
    dependencies=[Depends(require_internal_token)],
)
def canonical_first_contact_render(data: CanonicalFirstContactRenderIn):
    try:
        rendered = CanonicalFirstContactRegistry.load().render(**data.model_dump())
    except GrowthRegistryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "template_id": rendered.template_id,
        "recipient_type": rendered.recipient_type,
        "sender_brand_id": rendered.sender_brand_id,
        "subject": rendered.subject,
        "body_text": rendered.body_text,
        "body_html": rendered.body_html,
        "sendable": rendered.sendable,
        "blocked_reasons": list(rendered.blocked_reasons),
        "registry_sha256": rendered.registry_sha256,
        "owner_body_sha256": rendered.owner_body_sha256,
    }


@router.post("/api/internal/growth-ops/signals", dependencies=[Depends(require_internal_token)])
def growth_signal_ingest(data: GrowthSignalIn, db: Session = Depends(get_db)):  # noqa: B008
    try:
        return ingest_signal(db, data).model_dump(mode="json")
    except GrowthRegistryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/api/internal/growth-ops/public-land/policy-replay",
    dependencies=[Depends(require_internal_token)],
)
def public_land_policy_replay(
    data: PublicLandPolicyReplayIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    from .catalog import replay_public_land_policy_cursors

    try:
        return replay_public_land_policy_cursors(
            db,
            **data.model_dump(),
            actor="growth-admin",
        )
    except GrowthRegistryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/api/internal/growth-ops/public-land/name-fallback-promotion",
    dependencies=[Depends(require_internal_token)],
)
def public_land_name_fallback_promotion(
    data: PublicLandNameFallbackPromotionIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    try:
        return promote_public_land_name_fallback_signals(
            db,
            **data.model_dump(),
            actor="growth-admin",
        )
    except (GrowthRegistryError, ValueError) as exc:
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


@router.post("/api/internal/growth-ops/scheduled-gmail/lease")
def scheduled_gmail_lease(
    data: ScheduledGmailLeaseIn,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),  # noqa: B008
):
    principal = _scheduled_gmail_principal(authorization, permission="lease")
    try:
        return lease_scheduled_gmail_outreach(db, data, principal)
    except (EmailDeliveryError, GrowthRegistryError, RuntimeError, ValueError) as exc:
        raise _scheduled_gmail_error(exc) from exc


@router.get("/api/internal/growth-ops/scheduled-gmail/readiness")
def scheduled_gmail_readiness(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),  # noqa: B008
):
    principal = _scheduled_gmail_principal(authorization, permission="read")
    try:
        return scheduled_gmail_coordination_readiness(db, principal)
    except (EmailDeliveryError, GrowthRegistryError, RuntimeError, ValueError) as exc:
        raise _scheduled_gmail_error(exc) from exc


@router.post("/api/internal/growth-ops/scheduled-gmail/escrow/bundles")
def scheduled_gmail_escrow_bundle_issue(
    data: ScheduledGmailEscrowBundleIn,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),  # noqa: B008
):
    principal = _scheduled_gmail_principal(
        authorization,
        permission="escrow_prefetch",
    )
    try:
        return issue_scheduled_gmail_escrow_bundle(db, data, principal)
    except (EmailDeliveryError, GrowthRegistryError, RuntimeError, ValueError) as exc:
        raise _scheduled_gmail_error(exc) from exc


@router.get(
    "/api/internal/growth-ops/scheduled-gmail/escrow/bundles/{bundle_id}"
)
def scheduled_gmail_escrow_bundle_read(
    bundle_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),  # noqa: B008
):
    principal = _scheduled_gmail_principal(authorization, permission="read")
    try:
        return scheduled_gmail_escrow_bundle_status(db, bundle_id, principal)
    except (EmailDeliveryError, GrowthRegistryError, RuntimeError, ValueError) as exc:
        raise _scheduled_gmail_error(exc) from exc


@router.post("/api/internal/growth-ops/scheduled-gmail/escrow/sync")
def scheduled_gmail_escrow_sync(
    data: ScheduledGmailEscrowSyncIn,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),  # noqa: B008
):
    principal = _scheduled_gmail_principal(
        authorization,
        permission="escrow_sync",
    )
    try:
        return sync_scheduled_gmail_escrow_events(db, data, principal)
    except (EmailDeliveryError, GrowthRegistryError, RuntimeError, ValueError) as exc:
        raise _scheduled_gmail_error(exc) from exc


@router.post(
    "/api/internal/growth-ops/scheduled-gmail/escrow/bundles/{bundle_id}/sync"
)
def scheduled_gmail_escrow_bundle_sync(
    bundle_id: str,
    data: ScheduledGmailEscrowSyncIn,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),  # noqa: B008
):
    if data.bundle_id != bundle_id:
        raise HTTPException(status_code=409, detail="scheduled_gmail_escrow_bundle_conflict")
    return scheduled_gmail_escrow_sync(data, authorization, db)


@router.post(
    "/api/internal/growth-ops/scheduled-gmail/escrow/permits/{permit_id}/abort"
)
def scheduled_gmail_escrow_permit_abort(
    permit_id: str,
    data: ScheduledGmailEscrowAbortIn,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),  # noqa: B008
):
    principal = _scheduled_gmail_principal(authorization, permission="abort")
    try:
        return abort_scheduled_gmail_escrow_permit(
            db,
            permit_id,
            data,
            principal,
        )
    except (EmailDeliveryError, GrowthRegistryError, RuntimeError, ValueError) as exc:
        raise _scheduled_gmail_error(exc) from exc


@router.get("/api/internal/growth-ops/scheduled-gmail/{lease_id}")
def scheduled_gmail_status(
    lease_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),  # noqa: B008
):
    principal = _scheduled_gmail_principal(authorization, permission="read")
    try:
        return scheduled_gmail_lease_status(db, lease_id, principal)
    except (EmailDeliveryError, GrowthRegistryError, RuntimeError, ValueError) as exc:
        raise _scheduled_gmail_error(exc) from exc


@router.post("/api/internal/growth-ops/scheduled-gmail/{lease_id}/finalize")
def scheduled_gmail_finalize(
    lease_id: str,
    data: ScheduledGmailFinalizeIn,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),  # noqa: B008
):
    principal = _scheduled_gmail_principal(authorization, permission="finalize")
    try:
        return finalize_scheduled_gmail_outreach(db, lease_id, data, principal)
    except (EmailDeliveryError, GrowthRegistryError, RuntimeError, ValueError) as exc:
        raise _scheduled_gmail_error(exc) from exc


@router.post("/api/internal/growth-ops/scheduled-gmail/{lease_id}/abort")
def scheduled_gmail_abort(
    lease_id: str,
    data: ScheduledGmailAbortIn,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),  # noqa: B008
):
    principal = _scheduled_gmail_principal(authorization, permission="abort")
    try:
        return abort_scheduled_gmail_outreach(db, lease_id, data, principal)
    except (EmailDeliveryError, GrowthRegistryError, RuntimeError, ValueError) as exc:
        raise _scheduled_gmail_error(exc) from exc


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


@router.post("/growth/unsubscribe/{token}", response_class=Response)
async def growth_unsubscribe_one_click(
    token: str,
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008
):
    content_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    body = await request.body()
    try:
        fields = parse_qs(body.decode("ascii"), keep_blank_values=True, strict_parsing=True)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="invalid one-click unsubscribe request",
        ) from exc
    if content_type != "application/x-www-form-urlencoded" or fields != {
        "List-Unsubscribe": ["One-Click"]
    }:
        raise HTTPException(status_code=400, detail="invalid one-click unsubscribe request")
    try:
        unsubscribe(db, token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="invalid unsubscribe link") from exc
    return Response(status_code=204)
