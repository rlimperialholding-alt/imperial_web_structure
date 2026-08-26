from __future__ import annotations

import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from .schemas import (
    AuthorityGrantIn,
    AuthorityRevokeIn,
    DealIn,
    ListingPackageIn,
    ListingStateIn,
    PackageApprovalIn,
    PublicationConfirmationIn,
    PublicationRequestIn,
    SourceVerificationIn,
)
from .service import (
    approve_package,
    attempt_payload,
    confirm_publication,
    create_listing_package,
    grant_authority,
    opportunity_payload,
    package_payload,
    readiness,
    record_deal,
    request_publication,
    revoke_authority,
    scan_authority_expiry,
    set_listing_active,
    sync_growth_plot_signals,
    verify_source,
)

router = APIRouter(prefix="/api/internal/land-acquisition")


def require_internal_token(
    x_internal_job_token: str | None = Header(default=None, alias="X-Internal-Job-Token"),
) -> None:
    expected = settings.internal_job_token
    if (
        not expected
        or not x_internal_job_token
        or not hmac.compare_digest(expected, x_internal_job_token)
    ):
        raise HTTPException(status_code=401, detail="invalid internal token")


dependencies = [Depends(require_internal_token)]


def _translate(call):
    try:
        return call()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown land workflow object") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/readiness", dependencies=dependencies)
def land_readiness(db: Session = Depends(get_db)):  # noqa: B008
    ready, detail = readiness(db)
    if not ready:
        raise HTTPException(status_code=503, detail=detail)
    return {"status": "ready", **detail}


@router.post("/sync", dependencies=dependencies)
def sync(db: Session = Depends(get_db)):  # noqa: B008
    return sync_growth_plot_signals(db)


@router.post("/takedown-scan", dependencies=dependencies)
def takedown_scan(db: Session = Depends(get_db)):  # noqa: B008
    return _translate(lambda: scan_authority_expiry(db))


@router.post("/opportunities/{opportunity_id}/verify", dependencies=dependencies)
def source_verify(
    opportunity_id: str,
    data: SourceVerificationIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    return opportunity_payload(_translate(lambda: verify_source(db, opportunity_id, data)))


@router.post("/opportunities/{opportunity_id}/deal", dependencies=dependencies)
def deal(
    opportunity_id: str,
    data: DealIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    return opportunity_payload(_translate(lambda: record_deal(db, opportunity_id, data)))


@router.post("/opportunities/{opportunity_id}/authority", dependencies=dependencies)
def authority(
    opportunity_id: str,
    data: AuthorityGrantIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    row = _translate(lambda: grant_authority(db, opportunity_id, data))
    return {
        "grant_id": row.grant_id,
        "opportunity_id": row.opportunity_id,
        "status": row.status,
        "scopes": json.loads(row.scopes_json),
        "valid_from": row.valid_from,
        "valid_until": row.valid_until,
        "approved_by": row.approved_by,
    }


@router.post("/authorities/{grant_id}/revoke", dependencies=dependencies)
def authority_revoke(
    grant_id: str,
    data: AuthorityRevokeIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    row = _translate(lambda: revoke_authority(db, grant_id, actor=data.actor, reason=data.reason))
    return {"grant_id": row.grant_id, "status": row.status, "revoked_at": row.revoked_at}


@router.post("/opportunities/{opportunity_id}/listing-state", dependencies=dependencies)
def listing_state(
    opportunity_id: str,
    data: ListingStateIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    return opportunity_payload(
        _translate(
            lambda: set_listing_active(
                db,
                opportunity_id,
                active=data.active,
                evidence_ref=data.evidence_ref,
                actor=data.actor,
            )
        )
    )


@router.post("/opportunities/{opportunity_id}/packages", dependencies=dependencies)
def package_create(
    opportunity_id: str,
    data: ListingPackageIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    return package_payload(_translate(lambda: create_listing_package(db, opportunity_id, data)))


@router.post("/packages/{package_id}/approve", dependencies=dependencies)
def package_approve(
    package_id: str,
    data: PackageApprovalIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    return package_payload(_translate(lambda: approve_package(db, package_id, data)))


@router.post("/packages/{package_id}/publish", dependencies=dependencies)
def publish(
    package_id: str,
    data: PublicationRequestIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    rows = _translate(lambda: request_publication(db, package_id, data))
    return {"attempts": [attempt_payload(row) for row in rows]}


@router.post("/attempts/{attempt_id}/confirm", dependencies=dependencies)
def confirm(
    attempt_id: str,
    data: PublicationConfirmationIn,
    db: Session = Depends(get_db),  # noqa: B008
):
    return attempt_payload(_translate(lambda: confirm_publication(db, attempt_id, data)))
