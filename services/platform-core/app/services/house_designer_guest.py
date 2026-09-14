from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..models import (
    HouseDesignerEntitlement,
    HouseDesignerGuestRateLimit,
    HouseDesignGuestClaim,
    HouseDesignSession,
)
from .house_designer import ActorScope, HouseDesignerError, create_session

GUEST_SESSION_COOKIE = "hd_guest_session"
GUEST_CLAIM_COOKIE = "hd_guest_claim"
TENANT_ID = "imperial-holding"


@dataclass(frozen=True)
class IssuedGuestAccess:
    design: dict[str, Any]
    expires_at: datetime
    guest_session_token: str = field(repr=False)
    claim_token: str = field(repr=False)


def create_guest_design(
    db: Session,
    *,
    brand_id: str,
    title: str,
    command_id: str,
    origin: str = "blank",
    template_plan_id: str | None = None,
    width_mm: int = 10_000,
    depth_mm: int = 8_000,
) -> IssuedGuestAccess:
    _require_standalone_entitlement(db, brand_id)
    claim_id = f"HDGC-{uuid4().hex.upper()}"
    guest_subject = f"guest:{claim_id}"
    guest_session_token = secrets.token_urlsafe(48)
    claim_token = secrets.token_urlsafe(48)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.house_designer_guest_ttl_hours)
    actor = ActorScope(guest_subject, TENANT_ID, frozenset({brand_id}))
    design = create_session(
        db,
        actor=actor,
        brand_id=brand_id,
        title=title,
        command_id=command_id,
        origin=origin,
        template_plan_id=template_plan_id,
        width_mm=width_mm,
        depth_mm=depth_mm,
        commit=False,
    )
    claim = HouseDesignGuestClaim(
        claim_id=claim_id,
        session_id=design["sessionId"],
        token_hash=_token_hash(claim_token),
        guest_session_hash=_token_hash(guest_session_token),
        status="active",
        expires_at=expires_at,
    )
    db.add(claim)
    audit(
        db,
        actor=guest_subject,
        action="house_designer.guest.issue",
        entity_type="HouseDesignGuestClaim",
        entity_id=claim_id,
        after={
            "session_id": design["sessionId"],
            "expires_at": expires_at.isoformat(),
        },
    )
    db.commit()
    return IssuedGuestAccess(
        design=design,
        expires_at=expires_at,
        guest_session_token=guest_session_token,
        claim_token=claim_token,
    )


def standalone_access_status(db: Session, *, brand_id: str) -> dict[str, Any]:
    entitlement = _standalone_entitlement(db, brand_id)
    now = datetime.now(UTC)
    available = bool(
        entitlement
        and entitlement.status in {"sandbox", "active"}
        and entitlement.standalone_enabled
        and _aware(entitlement.valid_from) <= now
        and (entitlement.valid_until is None or _aware(entitlement.valid_until) > now)
    )
    return {
        "available": available,
        "mode": entitlement.status if entitlement else "disabled",
        "validUntil": entitlement.valid_until if entitlement else None,
    }


def consume_guest_creation_quota(
    db: Session,
    *,
    brand_id: str,
    fingerprint_source: str,
    limit: int | None = None,
    window_seconds: int | None = None,
    block_seconds: int | None = None,
) -> dict[str, Any]:
    effective_limit = limit or settings.house_designer_guest_create_limit
    effective_window = window_seconds or settings.house_designer_guest_rate_window_seconds
    effective_block = block_seconds or settings.house_designer_guest_block_seconds
    fingerprint_hash = hmac.new(
        settings.session_secret.encode("utf-8"),
        fingerprint_source.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    now = datetime.now(UTC)
    row = db.scalar(
        select(HouseDesignerGuestRateLimit)
        .where(
            HouseDesignerGuestRateLimit.tenant_id == TENANT_ID,
            HouseDesignerGuestRateLimit.brand_id == brand_id,
            HouseDesignerGuestRateLimit.fingerprint_hash == fingerprint_hash,
        )
        .with_for_update()
    )
    if row is None:
        row = HouseDesignerGuestRateLimit(
            rate_limit_id=f"HDGRL-{uuid4().hex.upper()}",
            tenant_id=TENANT_ID,
            brand_id=brand_id,
            fingerprint_hash=fingerprint_hash,
            window_started_at=now,
            attempt_count=1,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return consume_guest_creation_quota(
                db,
                brand_id=brand_id,
                fingerprint_source=fingerprint_source,
                limit=effective_limit,
                window_seconds=effective_window,
                block_seconds=effective_block,
            )
        return _rate_limit_result(row, effective_limit)
    if row.blocked_until is not None and _aware(row.blocked_until) > now:
        _commit_rate_limit_block(db, row, now)
    if _aware(row.window_started_at) + timedelta(seconds=effective_window) <= now:
        row.window_started_at = now
        row.attempt_count = 0
        row.blocked_until = None
    if row.attempt_count >= effective_limit:
        row.blocked_until = now + timedelta(seconds=effective_block)
        row.row_version += 1
        _commit_rate_limit_block(db, row, now)
    row.attempt_count += 1
    row.row_version += 1
    db.commit()
    return _rate_limit_result(row, effective_limit)


def resolve_guest_actor(
    db: Session,
    *,
    guest_session_token: str,
    expected_session_id: str | None = None,
) -> ActorScope:
    claim = db.scalar(
        select(HouseDesignGuestClaim).where(
            HouseDesignGuestClaim.guest_session_hash == _token_hash(guest_session_token)
        )
    )
    if claim is None:
        raise HouseDesignerError(
            "guest_session_not_found", "A vendégterv nem található.", status_code=404
        )
    session = _valid_guest_session(db, claim, expected_session_id=expected_session_id)
    return ActorScope(
        subject_id=f"guest:{claim.claim_id}",
        tenant_id=session.tenant_id,
        brand_ids=frozenset({session.brand_id}),
    )


def claim_guest_design(
    db: Session,
    *,
    guest_session_token: str,
    claim_token: str,
    authenticated_subject_id: str,
    expected_tenant_id: str = TENANT_ID,
) -> dict[str, Any]:
    claim = db.scalar(
        select(HouseDesignGuestClaim)
        .where(HouseDesignGuestClaim.token_hash == _token_hash(claim_token))
        .with_for_update()
    )
    if claim is None:
        raise HouseDesignerError(
            "guest_claim_not_found", "A vendégterv nem vehető át.", status_code=404
        )
    if not secrets.compare_digest(
        claim.guest_session_hash, _token_hash(guest_session_token)
    ):
        raise HouseDesignerError(
            "guest_claim_scope_mismatch", "A vendégterv nem vehető át.", status_code=404
        )
    session = db.scalar(
        select(HouseDesignSession)
        .where(HouseDesignSession.session_id == claim.session_id)
        .with_for_update()
    )
    if session is None or session.tenant_id != expected_tenant_id:
        raise HouseDesignerError(
            "guest_claim_not_found", "A vendégterv nem vehető át.", status_code=404
        )
    if claim.status != "active":
        raise HouseDesignerError(
            "guest_claim_replayed",
            "A vendégtervet már átvették vagy visszavonták.",
            status_code=409,
        )
    now = datetime.now(UTC)
    if _aware(claim.expires_at) <= now:
        claim.status = "expired"
        claim.revoked_at = now
        db.commit()
        raise HouseDesignerError(
            "guest_claim_expired", "A vendégterv átvételi ideje lejárt.", status_code=409
        )
    if session.owner_subject_id != f"guest:{claim.claim_id}":
        raise HouseDesignerError(
            "guest_claim_owner_changed",
            "A vendégterv tulajdonosa már megváltozott.",
            status_code=409,
        )
    claims = db.scalars(
        select(HouseDesignGuestClaim)
        .where(HouseDesignGuestClaim.session_id == session.session_id)
        .with_for_update()
    ).all()
    for row in claims:
        if row.claim_id == claim.claim_id:
            row.status = "claimed"
            row.claimed_by_subject_id = authenticated_subject_id
            row.claimed_at = now
        elif row.status == "active":
            row.status = "revoked"
            row.revoked_at = now
    previous_owner = session.owner_subject_id
    session.owner_subject_id = authenticated_subject_id
    session.updated_by = authenticated_subject_id
    session.row_version += 1
    audit(
        db,
        actor=authenticated_subject_id,
        action="house_designer.guest.claim",
        entity_type="HouseDesignSession",
        entity_id=session.session_id,
        before={"owner_subject_id": previous_owner},
        after={"owner_subject_id": authenticated_subject_id, "claim_id": claim.claim_id},
    )
    db.commit()
    return {
        "sessionId": session.session_id,
        "ownerSubjectId": authenticated_subject_id,
        "claimedAt": now,
    }


def _valid_guest_session(
    db: Session,
    claim: HouseDesignGuestClaim | None,
    *,
    expected_session_id: str | None,
) -> HouseDesignSession:
    if claim is None or claim.status != "active" or _aware(claim.expires_at) <= datetime.now(UTC):
        raise HouseDesignerError(
            "guest_session_not_found", "A vendégterv nem található.", status_code=404
        )
    if expected_session_id and claim.session_id != expected_session_id:
        raise HouseDesignerError(
            "guest_session_not_found", "A vendégterv nem található.", status_code=404
        )
    session = db.scalar(
        select(HouseDesignSession).where(HouseDesignSession.session_id == claim.session_id)
    )
    if session is None or session.owner_subject_id != f"guest:{claim.claim_id}":
        raise HouseDesignerError(
            "guest_session_not_found", "A vendégterv nem található.", status_code=404
        )
    return session


def _require_standalone_entitlement(db: Session, brand_id: str) -> None:
    entitlement = _standalone_entitlement(db, brand_id)
    now = datetime.now(UTC)
    allowed = (
        entitlement is not None
        and entitlement.status in {"sandbox", "active"}
        and entitlement.standalone_enabled
        and _aware(entitlement.valid_from) <= now
        and (entitlement.valid_until is None or _aware(entitlement.valid_until) > now)
    )
    if not allowed:
        raise HouseDesignerError(
            "standalone_not_enabled",
            "A Háztervező önálló felülete jelenleg nem indítható.",
            status_code=503,
        )


def _standalone_entitlement(
    db: Session, brand_id: str
) -> HouseDesignerEntitlement | None:
    return db.scalar(
        select(HouseDesignerEntitlement).where(
            HouseDesignerEntitlement.tenant_id == TENANT_ID,
            HouseDesignerEntitlement.brand_id == brand_id,
        )
    )


def _token_hash(value: str) -> str:
    if not value:
        return hashlib.sha256(b"missing-token").hexdigest()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _commit_rate_limit_block(
    db: Session, row: HouseDesignerGuestRateLimit, now: datetime
) -> None:
    audit(
        db,
        actor=f"guest-rate:{row.fingerprint_hash[:16]}",
        action="house_designer.guest.rate_limited",
        entity_type="HouseDesignerGuestRateLimit",
        entity_id=row.rate_limit_id,
        after={
            "attempt_count": row.attempt_count,
            "blocked_until": row.blocked_until,
            "observed_at": now,
        },
    )
    db.commit()
    raise HouseDesignerError(
        "guest_rate_limited",
        "Túl sok tervindítási kérés érkezett; próbálja meg később.",
        status_code=429,
    )


def _rate_limit_result(row: HouseDesignerGuestRateLimit, limit: int) -> dict[str, Any]:
    return {
        "rateLimitId": row.rate_limit_id,
        "attemptCount": row.attempt_count,
        "limit": limit,
        "remaining": max(0, limit - row.attempt_count),
        "windowStartedAt": row.window_started_at,
        "blockedUntil": row.blocked_until,
    }


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
