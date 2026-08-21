from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import http.client
import ipaddress
import json
import re
import secrets
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..models import (
    AuditLog,
    MarketAsset,
    MarketCaptureJob,
    MarketEvidenceRedaction,
    MarketHandoffWatermark,
    MarketObservation,
    MarketPackHandoff,
    MarketPatternCluster,
    MarketPermissionGrant,
    MarketResearchHypothesis,
    MarketResearchPack,
    MarketSourceSnapshot,
    MarketSourceTarget,
    MarketValidation,
    MarketVocSignal,
    OutboxMessage,
    User,
    utcnow,
)

DEFAULT_CAPTURE_RATE_MAX = 10
DEFAULT_CAPTURE_RATE_WINDOW_SECONDS = 3600


class MarketIntelligenceError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class MarketActor:
    subject_id: str
    tenant_id: str
    brand_id: str
    market_id: str
    can_author: bool = False
    can_review: bool = False
    can_freeze: bool = False
    can_handoff: bool = False
    can_quarantine: bool = False
    permission_revision: str = "unverified"


@dataclass(frozen=True)
class PublicCaptureResponse:
    resolved_url: str
    mime_type: str
    content: str
    http_status: int
    response_headers: dict[str, str]
    source_ip: str


MARKET_PERMISSIONS = {
    "ii.market.read",
    "ii.market.author",
    "ii.market.review",
    "ii.market.freeze",
    "ii.market.handoff",
    "ii.market.quarantine",
}

_MARKET_DEMO_GRANTS = {
    "platform-admin": {"ii.market.read", "ii.market.author"},
    "marketing": {
        "ii.market.read",
        "ii.market.author",
        "ii.market.review",
        "ii.market.quarantine",
    },
    "owner": MARKET_PERMISSIONS,
    "managing-director": MARKET_PERMISSIONS,
}


def authorize_market_intelligence(
    db: Session,
    user: User,
    permission: str,
    *,
    tenant_id: str,
    brand_id: str,
    market_id: str,
) -> tuple[str, str]:
    if permission not in MARKET_PERMISSIONS:
        raise PermissionError("Ismeretlen Market Intelligence jogosultság.")
    subject = str(user.itep_subject_id or "")
    if not subject.startswith("ITEP-"):
        raise PermissionError("Kanonikus ITEP subject hiányzik.")
    now = utcnow()
    rows = db.scalars(
        select(MarketPermissionGrant).where(
            MarketPermissionGrant.subject_id == subject,
            MarketPermissionGrant.permission == permission,
            MarketPermissionGrant.status == "active",
        )
    ).all()
    active = [row for row in rows if _as_utc(row.valid_from) <= now < _as_utc(row.expires_at)]
    applicable = [
        row
        for row in active
        if row.scope_type == "global"
        or (row.tenant_id == tenant_id and row.brand_id == brand_id and row.market_id == market_id)
    ]
    if any(row.effect == "deny" for row in applicable):
        raise PermissionError("Aktív ITEP deny grant tiltja a műveletet.")
    allowed = [row for row in applicable if row.effect == "allow"]
    if not allowed:
        raise PermissionError("Nincs aktív, scope-helyes ITEP jogosultság.")
    revision = _sha(
        [
            {"grant": row.grant_id, "claim": row.claim_sha256}
            for row in sorted(allowed, key=lambda item: item.grant_id)
        ]
    )
    return subject, f"itep-market:{revision}"


def ingest_market_permission_replica(
    db: Session, *, payload: dict[str, Any], signature: str, secret: str
) -> int:
    if len(secret) < 32:
        raise PermissionError("Az ITEP replica secret nincs biztonságosan konfigurálva.")
    raw = _json(payload)
    expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.strip().lower(), expected):
        raise PermissionError("Érvénytelen ITEP permission replica aláírás.")
    if payload.get("issuer") != "itep":
        raise ValueError("A permission replica issuer értéke csak itep lehet.")
    subject = str(payload.get("subjectId") or "")
    email = str(payload.get("email") or "").strip().lower()
    revision = str(payload.get("revision") or "").strip()
    try:
        sequence = int(payload["sequence"])
        valid_from = _as_utc(datetime.fromisoformat(str(payload["validFrom"])))
        expires_at = _as_utc(datetime.fromisoformat(str(payload["expiresAt"])))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("A sequence és az ISO-8601 érvényességi idő kötelező.") from error
    if not subject.startswith("ITEP-") or not email or not revision or sequence < 1:
        raise ValueError("A subjectId, email, revision és pozitív sequence kötelező.")
    if not valid_from <= utcnow() < expires_at:
        raise ValueError("Az ITEP permission replica nem aktív.")
    grants = payload.get("grants")
    if not isinstance(grants, list) or not grants:
        raise ValueError("Legalább egy permission grant kötelező.")
    normalized: list[tuple[str, str, str, str, str | None, str | None, str | None]] = []
    for item in grants:
        if not isinstance(item, dict):
            raise ValueError("Minden grant JSON objektum.")
        permission = str(item.get("permission") or "")
        effect = str(item.get("effect") or "")
        scope_type = str(item.get("scopeType") or "")
        tenant = str(item.get("tenantId") or "").strip() or None
        brand = str(item.get("brandId") or "").strip() or None
        market = str(item.get("marketId") or "").strip() or None
        if permission not in MARKET_PERMISSIONS or effect not in {"allow", "deny"}:
            raise ValueError("Ismeretlen permission vagy effect.")
        if scope_type == "global":
            if any((tenant, brand, market)):
                raise ValueError("Global grant nem tartalmazhat brand/market scope-ot.")
            scope_key = "*"
        elif scope_type == "brand_market" and all((tenant, brand, market)):
            scope_key = f"{tenant}/{brand}/{market}"
        else:
            raise ValueError("A scope global vagy teljes brand_market lehet.")
        normalized.append((permission, effect, scope_type, scope_key, tenant, brand, market))
    if len(normalized) != len(set(normalized)):
        raise ValueError("A replica duplikált grantet tartalmaz.")
    user = db.scalar(
        select(User).where(User.email == email, User.active.is_(True)).with_for_update()
    )
    if user is None:
        raise ValueError("Az ITEP felhasználó hiányzik vagy inaktív.")
    collision = db.scalar(select(User).where(User.itep_subject_id == subject, User.id != user.id))
    if collision:
        raise ValueError("Az ITEP subject már más felhasználóhoz tartozik.")
    claim_sha = _sha(payload)
    prior = db.scalars(
        select(MarketPermissionGrant)
        .where(MarketPermissionGrant.subject_id == subject)
        .with_for_update()
    ).all()
    watermark = max((row.claim_sequence for row in prior), default=0)
    if sequence < watermark:
        raise ValueError("ITEP permission rollback tiltott.")
    if (
        sequence == watermark
        and prior
        and any(row.claim_sha256 != claim_sha for row in prior if row.claim_sequence == sequence)
    ):
        raise ValueError("ITEP permission sequence conflict.")
    existing = [row for row in prior if row.revision == revision and row.claim_sha256 == claim_sha]
    if len(existing) == len(normalized):
        user.itep_subject_id = subject
        db.commit()
        return 0
    for row in prior:
        if row.status == "active":
            row.status = "revoked"
    user.itep_subject_id = subject
    for index, item in enumerate(sorted(normalized), start=1):
        permission, effect, scope_type, scope_key, tenant, brand, market = item
        grant_hash = _sha([subject, sequence, index, *item])
        db.add(
            MarketPermissionGrant(
                grant_id=f"MPG-{grant_hash[:40]}",
                subject_id=subject,
                permission=permission,
                effect=effect,
                scope_type=scope_type,
                scope_key=scope_key,
                tenant_id=tenant,
                brand_id=brand,
                market_id=market,
                revision=revision,
                claim_sequence=sequence,
                claim_issuer="itep",
                claim_sha256=claim_sha,
                status="active",
                valid_from=valid_from,
                expires_at=expires_at,
            )
        )
    audit(
        db,
        actor="ITEP-PERMISSION-REPLICA",
        action="market_permissions_replicated",
        entity_type="User",
        entity_id=str(user.id),
        after={
            "subject_id": subject,
            "revision": revision,
            "sequence": sequence,
            "claim_sha256": claim_sha,
            "grant_count": len(normalized),
        },
    )
    db.commit()
    return len(normalized)


def ensure_market_demo_grants(db: Session, *, enabled: bool) -> int:
    if not enabled:
        return 0
    now = utcnow()
    inserted = 0
    users = db.scalars(
        select(User).where(User.active.is_(True), User.itep_subject_id.is_not(None))
    ).all()
    for user in users:
        for permission in sorted(_MARKET_DEMO_GRANTS.get(user.role, set())):
            grant_id = f"MPG-DEMO-{user.id}-{_sha(permission)[:16]}"
            if db.scalar(
                select(MarketPermissionGrant).where(MarketPermissionGrant.grant_id == grant_id)
            ):
                continue
            claim = {
                "issuer": "imperial-test-fixture",
                "subject": user.itep_subject_id,
                "permission": permission,
                "scope": "imperial-holding/imperial/HU",
            }
            db.add(
                MarketPermissionGrant(
                    grant_id=grant_id,
                    subject_id=str(user.itep_subject_id),
                    permission=permission,
                    effect="allow",
                    scope_type="brand_market",
                    scope_key="imperial-holding/imperial/HU",
                    tenant_id="imperial-holding",
                    brand_id="imperial",
                    market_id="HU",
                    revision="demo-market-v1",
                    claim_sequence=1,
                    claim_issuer="imperial-test-fixture",
                    claim_sha256=_sha(claim),
                    status="active",
                    valid_from=now,
                    expires_at=now + timedelta(days=1825),
                )
            )
            inserted += 1
    if inserted:
        db.commit()
    return inserted


def migrate_market_snapshot_encryption(db: Session) -> int:
    rows = db.scalars(
        select(MarketSourceSnapshot)
        .where(
            MarketSourceSnapshot.encrypted_content.is_(None),
            MarketSourceSnapshot.normalized_text != "",
            MarketSourceSnapshot.erased_at.is_(None),
        )
        .with_for_update()
    ).all()
    for row in rows:
        _apply_encrypted_text(row, row.normalized_text)
        row.normalized_text = ""
    if rows:
        audit(
            db,
            actor="system:mci-encryption-cutover",
            action="market_intelligence.snapshot.encryption_cutover",
            entity_type="MarketSourceSnapshot",
            after={"encrypted_count": len(rows), "key_id": settings.market_evidence_key_id},
        )
        db.commit()
    return len(rows)


def create_target(
    db: Session,
    *,
    actor: MarketActor,
    name: str,
    source_type: str,
    origin: str,
    allowed_path: str,
    rights_status: str,
    capture_mode: str = "manual",
    rate_limit_max: int = DEFAULT_CAPTURE_RATE_MAX,
    rate_limit_window_seconds: int = DEFAULT_CAPTURE_RATE_WINDOW_SECONDS,
) -> dict[str, Any]:
    _require_author(actor)
    normalized_origin = _origin(origin)
    path = allowed_path.strip() or "/"
    if not path.startswith("/") or ".." in path:
        raise MarketIntelligenceError("allowed_path_invalid", "Az engedélyezett útvonal hibás.")
    if rights_status not in {"PUBLIC_RESEARCH", "LICENSED", "OWNED", "CONSENTED"}:
        raise MarketIntelligenceError("rights_status_invalid", "A forrás jogalapja nem elfogadott.")
    if capture_mode not in {"manual", "public_fetch"}:
        raise MarketIntelligenceError("capture_mode_invalid", "Ismeretlen capture mód.")
    rate_limit = _capture_rate_policy(rate_limit_max, rate_limit_window_seconds)
    policy = {
        "captureMode": capture_mode,
        "allowedMimeTypes": ["text/plain", "text/html"],
        "maxBytes": 200_000,
        "piiPolicy": "reject",
        "productionFetchEnabled": capture_mode == "public_fetch",
        "rateLimit": rate_limit,
    }
    target_id = _id("MST")
    row = MarketSourceTarget(
        target_id=target_id,
        family_id=target_id,
        revision_no=1,
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        name=name.strip(),
        source_type=source_type.strip() or "public_web",
        normalized_origin=normalized_origin,
        allowed_path=path,
        capture_mode=capture_mode,
        rights_status=rights_status,
        pii_policy="reject",
        policy_json=_json(policy),
        policy_sha256=_sha(policy),
        status="DRAFT",
        row_version=1,
        author_subject_id=actor.subject_id,
    )
    if not row.name:
        raise MarketIntelligenceError("target_name_required", "A forrás neve kötelező.")
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.target.create",
        entity_type="MarketSourceTarget",
        entity_id=target_id,
        after={"brand_id": actor.brand_id, "market_id": actor.market_id, "status": "DRAFT"},
    )
    db.commit()
    return _target_result(row)


def transition_target(
    db: Session,
    *,
    actor: MarketActor,
    target_id: str,
    row_version: int,
    action: str,
    reason: str = "",
) -> dict[str, Any]:
    row = _target(db, actor, target_id, lock=True)
    if row.row_version != row_version:
        raise MarketIntelligenceError(
            "stale_target", "A forrás időközben módosult.", status_code=409
        )
    if action == "submit_review":
        if row.status != "DRAFT" or row.author_subject_id != actor.subject_id:
            raise MarketIntelligenceError(
                "transition_forbidden", "A forrás nem küldhető review-ra."
            )
        next_status = "IN_REVIEW"
    elif action == "approve":
        if not actor.can_review or row.status != "IN_REVIEW":
            raise MarketIntelligenceError(
                "review_forbidden", "A forrás nem hagyható jóvá.", status_code=403
            )
        if row.author_subject_id == actor.subject_id:
            raise MarketIntelligenceError(
                "four_eyes_required", "A szerző nem hagyhatja jóvá saját forrását.", status_code=409
            )
        next_status = "APPROVED"
        row.reviewer_subject_id = actor.subject_id
        row.reviewed_at = utcnow()
        previous = db.scalars(
            select(MarketSourceTarget)
            .where(
                MarketSourceTarget.family_id == row.family_id,
                MarketSourceTarget.target_id != row.target_id,
                MarketSourceTarget.status == "APPROVED",
            )
            .with_for_update()
        ).all()
        for item in previous:
            item.status = "SUPERSEDED"
            item.row_version += 1
            audit(
                db,
                actor=actor.subject_id,
                action="market_intelligence.target.supersede",
                entity_type="MarketSourceTarget",
                entity_id=item.target_id,
                before={"status": "APPROVED"},
                after={"status": "SUPERSEDED", "replacement_target_id": row.target_id},
            )
    elif action == "revoke":
        if not actor.can_review or row.status != "APPROVED":
            raise MarketIntelligenceError(
                "revoke_forbidden", "A forrás nem vonható vissza.", status_code=403
            )
        if row.author_subject_id == actor.subject_id:
            raise MarketIntelligenceError(
                "four_eyes_required",
                "A szerző nem vonhatja vissza saját forrását.",
                status_code=409,
            )
        if not reason.strip():
            raise MarketIntelligenceError("revoke_reason_required", "A visszavonás oka kötelező.")
        next_status = "REVOKED"
        row.revoke_reason = reason.strip()
    else:
        raise MarketIntelligenceError("transition_invalid", "Ismeretlen forrásművelet.")
    before = row.status
    row.status = next_status
    row.row_version += 1
    audit(
        db,
        actor=actor.subject_id,
        action=f"market_intelligence.target.{action}",
        entity_type="MarketSourceTarget",
        entity_id=target_id,
        before={"status": before},
        after={"status": next_status, "row_version": row.row_version},
    )
    db.commit()
    return _target_result(row)


def revise_target(
    db: Session,
    *,
    actor: MarketActor,
    target_id: str,
    row_version: int,
    name: str,
    origin: str,
    allowed_path: str,
    rights_status: str,
    rate_limit_max: int | None = None,
    rate_limit_window_seconds: int | None = None,
) -> dict[str, Any]:
    _require_author(actor)
    parent = _target(db, actor, target_id, lock=True)
    latest_revision = db.scalar(
        select(func.max(MarketSourceTarget.revision_no)).where(
            MarketSourceTarget.family_id == parent.family_id
        )
    )
    if parent.row_version != row_version or parent.revision_no != latest_revision:
        raise MarketIntelligenceError(
            "stale_target", "Csak a legújabb forrásverzió módosítható.", status_code=409
        )
    if parent.status not in {"APPROVED", "REVOKED"}:
        raise MarketIntelligenceError(
            "revision_forbidden", "Ebben az állapotban nem nyitható új revízió."
        )
    normalized_origin = _origin(origin)
    path = allowed_path.strip() or "/"
    if not path.startswith("/") or ".." in path:
        raise MarketIntelligenceError("allowed_path_invalid", "Az engedélyezett útvonal hibás.")
    if rights_status not in {"PUBLIC_RESEARCH", "LICENSED", "OWNED", "CONSENTED"}:
        raise MarketIntelligenceError("rights_status_invalid", "A forrás jogalapja nem elfogadott.")
    policy = json.loads(parent.policy_json)
    policy["productionFetchEnabled"] = parent.capture_mode == "public_fetch"
    previous_rate_limit = _target_rate_policy(parent)
    policy["rateLimit"] = _capture_rate_policy(
        rate_limit_max if rate_limit_max is not None else int(previous_rate_limit["maxRequests"]),
        rate_limit_window_seconds
        if rate_limit_window_seconds is not None
        else int(previous_rate_limit["windowSeconds"]),
    )
    row = MarketSourceTarget(
        target_id=_id("MST"),
        family_id=parent.family_id,
        revision_no=parent.revision_no + 1,
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        name=_required(name, "target_name_required"),
        source_type=parent.source_type,
        normalized_origin=normalized_origin,
        allowed_path=path,
        capture_mode=parent.capture_mode,
        rights_status=rights_status,
        pii_policy=parent.pii_policy,
        policy_json=_json(policy),
        policy_sha256=_sha(policy),
        status="DRAFT",
        row_version=1,
        author_subject_id=actor.subject_id,
    )
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.target.revise",
        entity_type="MarketSourceTarget",
        entity_id=row.target_id,
        after={
            "family_id": row.family_id,
            "revision_no": row.revision_no,
            "predecessor_target_id": parent.target_id,
        },
    )
    db.commit()
    return _target_result(row)


def import_manual_snapshot(
    db: Session,
    *,
    actor: MarketActor,
    target_id: str,
    resolved_url: str,
    mime_type: str,
    content: str,
    idempotency_key: str,
) -> dict[str, Any]:
    _require_author(actor)
    replay = db.scalar(
        select(MarketCaptureJob).where(
            MarketCaptureJob.tenant_id == actor.tenant_id,
            MarketCaptureJob.idempotency_key == idempotency_key,
        )
    )
    if replay:
        snapshot = db.scalar(
            select(MarketSourceSnapshot).where(MarketSourceSnapshot.capture_job_id == replay.job_id)
        )
        if snapshot is None and replay.error_code == "content_deduplicated" and replay.error_detail:
            snapshot = db.scalar(
                select(MarketSourceSnapshot).where(
                    MarketSourceSnapshot.snapshot_id == replay.error_detail
                )
            )
        if snapshot:
            return _snapshot_result(snapshot)
        raise MarketIntelligenceError(
            "idempotency_in_progress", "A beolvasás már folyamatban van.", status_code=409
        )
    target = _target(db, actor, target_id, lock=True)
    latest_revision = db.scalar(
        select(func.max(MarketSourceTarget.revision_no)).where(
            MarketSourceTarget.family_id == target.family_id
        )
    )
    if target.status != "APPROVED" or target.revision_no != latest_revision:
        raise MarketIntelligenceError(
            "target_not_approved",
            "Csak a legújabb jóváhagyott forrás használható.",
            status_code=409,
        )
    normalized_url = _allowed_url(target, resolved_url)
    if mime_type not in {"text/plain", "text/html"}:
        raise MarketIntelligenceError("mime_forbidden", "Ez a tartalomtípus nem engedélyezett.")
    encoded = content.encode("utf-8")
    if not encoded or len(encoded) > 200_000:
        raise MarketIntelligenceError(
            "content_size_invalid", "A forrástartalom üres vagy túl nagy."
        )
    _scan_content(content, mime_type)
    normalized_text = "\n".join(line.rstrip() for line in content.replace("\r", "").split("\n"))
    content_sha = hashlib.sha256(encoded).hexdigest()
    existing = db.scalar(
        select(MarketSourceSnapshot).where(
            MarketSourceSnapshot.target_id == target_id,
            MarketSourceSnapshot.content_sha256 == content_sha,
        )
    )
    job = MarketCaptureJob(
        job_id=_id("MCJ"),
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        target_id=target_id,
        requested_url=normalized_url,
        target_revision_no=target.revision_no,
        policy_sha256=target.policy_sha256,
        idempotency_key=idempotency_key,
        status="SUCCEEDED",
        attempts=1,
        created_by=actor.subject_id,
        finished_at=utcnow(),
    )
    db.add(job)
    if existing:
        job.error_code = "content_deduplicated"
        job.error_detail = existing.snapshot_id
        db.commit()
        return _snapshot_result(existing)
    snapshot = MarketSourceSnapshot(
        snapshot_id=_id("MSS"),
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        target_id=target_id,
        capture_job_id=job.job_id,
        resolved_url=normalized_url,
        http_status=None,
        response_headers_json="{}",
        source_ip=None,
        mime_type=mime_type,
        content_sha256=content_sha,
        normalized_text_sha256=hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        normalized_text="",
        policy_sha256=target.policy_sha256,
        parser_version="manual-sanitized-v1",
        parser_digest="builtin:manual-sanitized-v1",
        privacy_classification="PUBLIC",
        quarantine_state="CLEAN",
        created_by=actor.subject_id,
    )
    _apply_encrypted_text(snapshot, normalized_text)
    db.add(snapshot)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.snapshot.manual_import",
        entity_type="MarketSourceSnapshot",
        entity_id=snapshot.snapshot_id,
        after={
            "target_id": target_id,
            "content_sha256": content_sha,
            "policy_sha256": target.policy_sha256,
        },
    )
    db.commit()
    return _snapshot_result(snapshot)


def queue_public_capture(
    db: Session,
    *,
    actor: MarketActor,
    target_id: str,
    resolved_url: str,
    idempotency_key: str,
    connector_enabled: bool,
) -> dict[str, Any]:
    _require_author(actor)
    if not connector_enabled:
        raise MarketIntelligenceError(
            "public_fetch_disabled",
            "A nyilvános fetch connector kill switch-e OFF.",
            status_code=503,
        )
    key = _required(idempotency_key, "idempotency_key_required")
    target = _target(db, actor, target_id, lock=True)
    _require_executable_capture_target(db, target)
    requested_url = _allowed_url(target, resolved_url)
    replay = db.scalar(
        select(MarketCaptureJob).where(
            MarketCaptureJob.tenant_id == actor.tenant_id,
            MarketCaptureJob.idempotency_key == key,
        )
    )
    if replay:
        if replay.target_id != target.target_id or replay.requested_url != requested_url:
            raise MarketIntelligenceError(
                "idempotency_conflict",
                "Az idempotency kulcs más capture kéréshez tartozik.",
                status_code=409,
            )
        return _capture_job_result(replay)
    rate_policy = _target_rate_policy(target)
    window_started_at = utcnow() - timedelta(seconds=int(rate_policy["windowSeconds"]))
    family_target_ids = select(MarketSourceTarget.target_id).where(
        MarketSourceTarget.family_id == target.family_id,
        MarketSourceTarget.tenant_id == actor.tenant_id,
        MarketSourceTarget.brand_id == actor.brand_id,
        MarketSourceTarget.market_id == actor.market_id,
    )
    requests_in_window = int(
        db.scalar(
            select(func.count(MarketCaptureJob.id)).where(
                MarketCaptureJob.tenant_id == actor.tenant_id,
                MarketCaptureJob.target_id.in_(family_target_ids),
                MarketCaptureJob.created_at >= window_started_at,
            )
        )
        or 0
    )
    if requests_in_window >= int(rate_policy["maxRequests"]):
        raise MarketIntelligenceError(
            "capture_rate_limited",
            "A forrás capture-kvótája kimerült; a kérés később ismételhető.",
            status_code=429,
        )
    row = MarketCaptureJob(
        job_id=_id("MCJ"),
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        target_id=target.target_id,
        requested_url=requested_url,
        target_revision_no=target.revision_no,
        policy_sha256=target.policy_sha256,
        idempotency_key=key,
        status="QUEUED",
        attempts=0,
        created_by=actor.subject_id,
    )
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.capture.queue",
        entity_type="MarketCaptureJob",
        entity_id=row.job_id,
        after={
            "target_id": target.target_id,
            "target_revision_no": target.revision_no,
            "policy_sha256": target.policy_sha256,
        },
    )
    db.commit()
    return _capture_job_result(row)


def cancel_capture_job(
    db: Session, *, actor: MarketActor, job_id: str, reason: str
) -> dict[str, Any]:
    _require_author(actor)
    row = db.scalar(
        select(MarketCaptureJob)
        .where(
            MarketCaptureJob.job_id == job_id,
            MarketCaptureJob.tenant_id == actor.tenant_id,
            MarketCaptureJob.brand_id == actor.brand_id,
            MarketCaptureJob.market_id == actor.market_id,
        )
        .with_for_update()
    )
    if row is None:
        raise MarketIntelligenceError(
            "capture_job_not_found", "A capture job nem található.", status_code=404
        )
    if row.status not in {"QUEUED", "RUNNING"}:
        raise MarketIntelligenceError(
            "capture_cancel_forbidden",
            "Ez a capture job már nem állítható le.",
            status_code=409,
        )
    if not reason.strip():
        raise MarketIntelligenceError("capture_cancel_reason_required", "A leállítás oka kötelező.")
    row.status = "CANCELLED"
    row.error_code = "cancelled_by_user"
    row.error_detail = reason.strip()
    row.finished_at = utcnow()
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.capture.cancel",
        entity_type="MarketCaptureJob",
        entity_id=row.job_id,
        after={"status": "CANCELLED", "reason": reason.strip()},
    )
    db.commit()
    return _capture_job_result(row)


def retry_capture_job(
    db: Session,
    *,
    actor: MarketActor,
    job_id: str,
    idempotency_key: str,
    connector_enabled: bool,
) -> dict[str, Any]:
    _require_author(actor)
    row = db.scalar(
        select(MarketCaptureJob).where(
            MarketCaptureJob.job_id == job_id,
            MarketCaptureJob.tenant_id == actor.tenant_id,
            MarketCaptureJob.brand_id == actor.brand_id,
            MarketCaptureJob.market_id == actor.market_id,
        )
    )
    if row is None:
        raise MarketIntelligenceError(
            "capture_job_not_found", "A capture job nem található.", status_code=404
        )
    if row.status not in {"FAILED", "CANCELLED"} or not row.requested_url:
        raise MarketIntelligenceError(
            "capture_retry_forbidden",
            "Ez a capture job nem indítható újra.",
            status_code=409,
        )
    return queue_public_capture(
        db,
        actor=actor,
        target_id=row.target_id,
        resolved_url=row.requested_url,
        idempotency_key=idempotency_key,
        connector_enabled=connector_enabled,
    )


def process_public_capture_jobs(
    db: Session,
    *,
    connector_enabled: bool,
    limit: int = 3,
    fetcher: Callable[[MarketSourceTarget, str], PublicCaptureResponse] | None = None,
) -> dict[str, int]:
    stats = {"succeeded": 0, "failed": 0, "cancelled": 0}
    if not connector_enabled:
        return stats
    rows = db.scalars(
        select(MarketCaptureJob)
        .where(MarketCaptureJob.status == "QUEUED")
        .order_by(MarketCaptureJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(max(1, min(limit, 20)))
    ).all()
    job_ids = [row.job_id for row in rows]
    db.rollback()
    capture = fetcher or fetch_public_source
    for job_id in job_ids:
        try:
            job = db.scalar(
                select(MarketCaptureJob).where(MarketCaptureJob.job_id == job_id).with_for_update()
            )
            if job is None or job.status != "QUEUED":
                db.rollback()
                continue
            target = db.scalar(
                select(MarketSourceTarget)
                .where(MarketSourceTarget.target_id == job.target_id)
                .with_for_update()
            )
            if target is None:
                raise MarketIntelligenceError(
                    "target_changed", "A target már nem létezik.", status_code=409
                )
            _require_job_target_unchanged(db, target, job)
            job.status = "RUNNING"
            job.attempts += 1
            db.commit()
            response = capture(target, str(job.requested_url or ""))

            job = db.scalar(
                select(MarketCaptureJob).where(MarketCaptureJob.job_id == job_id).with_for_update()
            )
            if job is None or job.status == "CANCELLED":
                db.rollback()
                stats["cancelled"] += 1
                continue
            target = db.scalar(
                select(MarketSourceTarget)
                .where(MarketSourceTarget.target_id == job.target_id)
                .with_for_update()
            )
            if target is None:
                raise MarketIntelligenceError(
                    "target_changed", "A target már nem létezik.", status_code=409
                )
            _require_job_target_unchanged(db, target, job)
            _store_public_capture(db, target=target, job=job, response=response)
            db.commit()
            stats["succeeded"] += 1
        except MarketIntelligenceError as error:
            db.rollback()
            _fail_capture_job(db, job_id, error.code, str(error))
            stats["failed"] += 1
        except Exception:
            db.rollback()
            _fail_capture_job(db, job_id, "fetch_failed", "A biztonságos fetch sikertelen.")
            stats["failed"] += 1
    return stats


def _verified_tls_context() -> ssl.SSLContext:
    """Hitelesített TLS-kontextus, TLS 1.2 vagy újabb minimummal.

    A publikus provider-fetch útvonalon kizárólag igazolt, modern TLS
    használható; a TLS 1.0/1.1 és az SSL minden verziója tiltott.
    """
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def fetch_public_source(
    target: MarketSourceTarget,
    requested_url: str,
    *,
    timeout_seconds: float = 6.0,
    max_bytes: int = 200_000,
    max_redirects: int = 3,
) -> PublicCaptureResponse:
    current_url = _allowed_url(target, requested_url)
    for redirect_no in range(max_redirects + 1):
        parsed = urlsplit(current_url)
        host = str(parsed.hostname or "").lower().rstrip(".")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = _public_addresses(host, port)
        source_ip = sorted(addresses, key=lambda item: (item.version, str(item)))[0]
        connection: http.client.HTTPConnection
        raw_socket = socket.create_connection((str(source_ip), port), timeout=timeout_seconds)
        if parsed.scheme == "https":
            context = _verified_tls_context()
            tls_socket = context.wrap_socket(raw_socket, server_hostname=host)
            connection = http.client.HTTPSConnection(
                host, port=port, timeout=timeout_seconds, context=context
            )
            connection.sock = tls_socket
        else:
            connection = http.client.HTTPConnection(host, port=port, timeout=timeout_seconds)
            connection.sock = raw_socket
        try:
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            connection.request(
                "GET",
                path,
                headers={
                    "Host": host if parsed.port is None else f"{host}:{port}",
                    "User-Agent": "Imperial-Market-Research/1.0",
                    "Accept": "text/plain,text/html;q=0.9",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            headers = {key.lower(): value.strip() for key, value in response.getheaders()}
            if response.status in {301, 302, 303, 307, 308}:
                location = headers.get("location")
                if not location or redirect_no >= max_redirects:
                    raise MarketIntelligenceError(
                        "redirect_forbidden",
                        "A redirect hiányos vagy túl hosszú.",
                        status_code=422,
                    )
                current_url = _allowed_url(target, urljoin(current_url, location))
                continue
            if not 200 <= response.status < 300:
                raise MarketIntelligenceError(
                    "fetch_http_error",
                    f"A forrás HTTP {response.status} választ adott.",
                    status_code=422,
                )
            if headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                raise MarketIntelligenceError(
                    "compressed_content_forbidden",
                    "Tömörített válasz nem fogadható el.",
                    status_code=422,
                )
            mime_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if mime_type not in {"text/plain", "text/html"}:
                raise MarketIntelligenceError(
                    "mime_forbidden", "Tiltott válasz MIME típus.", status_code=422
                )
            declared_size = headers.get("content-length")
            if declared_size and int(declared_size) > max_bytes:
                raise MarketIntelligenceError(
                    "content_size_invalid", "A válasz túl nagy.", status_code=422
                )
            payload = response.read(max_bytes + 1)
            if not payload or len(payload) > max_bytes:
                raise MarketIntelligenceError(
                    "content_size_invalid", "A válasz üres vagy túl nagy."
                )
            try:
                content = payload.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise MarketIntelligenceError(
                    "charset_forbidden",
                    "A válasz nem érvényes UTF-8.",
                    status_code=422,
                ) from error
            _scan_content(content, mime_type)
            safe_headers = {
                key: headers[key]
                for key in ("content-type", "etag", "last-modified", "cache-control")
                if key in headers
            }
            return PublicCaptureResponse(
                resolved_url=current_url,
                mime_type=mime_type,
                content=content,
                http_status=response.status,
                response_headers=safe_headers,
                source_ip=str(source_ip),
            )
        finally:
            connection.close()
    raise MarketIntelligenceError("redirect_forbidden", "Túl sok redirect.", status_code=422)


def quarantine_snapshot(
    db: Session,
    *,
    actor: MarketActor,
    snapshot_id: str,
    legal_basis: str,
    reason: str,
) -> dict[str, Any]:
    snapshot = db.scalar(
        select(MarketSourceSnapshot)
        .where(
            MarketSourceSnapshot.snapshot_id == snapshot_id,
            MarketSourceSnapshot.tenant_id == actor.tenant_id,
            MarketSourceSnapshot.brand_id == actor.brand_id,
            MarketSourceSnapshot.market_id == actor.market_id,
        )
        .with_for_update()
    )
    if snapshot is None:
        raise MarketIntelligenceError(
            "snapshot_not_found", "A snapshot nem található.", status_code=404
        )
    if not actor.can_quarantine:
        raise MarketIntelligenceError(
            "quarantine_forbidden", "Nincs karantén-jogosultság.", status_code=403
        )
    if snapshot.created_by == actor.subject_id:
        raise MarketIntelligenceError(
            "four_eyes_required",
            "A snapshot létrehozója nem karanténozhatja saját adatát.",
            status_code=409,
        )
    if snapshot.quarantine_state != "CLEAN":
        raise MarketIntelligenceError(
            "snapshot_already_blocked", "A snapshot már blokkolt.", status_code=409
        )
    if legal_basis not in {
        "RIGHTS_REVOKED",
        "PRIVACY_REQUEST",
        "SECURITY_INCIDENT",
        "DATA_QUALITY",
    }:
        raise MarketIntelligenceError("redaction_basis_invalid", "Ismeretlen karantén-jogalap.")
    if not reason.strip():
        raise MarketIntelligenceError("redaction_reason_required", "A karantén oka kötelező.")
    snapshot.quarantine_state = "QUARANTINED"
    record = MarketEvidenceRedaction(
        redaction_id=_id("MER"),
        snapshot_id=snapshot.snapshot_id,
        action="QUARANTINE",
        legal_basis=legal_basis,
        reason=reason.strip(),
        actor_subject_id=snapshot.created_by,
        reviewer_subject_id=actor.subject_id,
    )
    db.add(record)
    invalidated = _invalidate_packs_for_snapshot(db, actor, snapshot.snapshot_id, reason.strip())
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.snapshot.quarantine",
        entity_type="MarketSourceSnapshot",
        entity_id=snapshot.snapshot_id,
        before={"quarantine_state": "CLEAN"},
        after={
            "quarantine_state": "QUARANTINED",
            "legal_basis": legal_basis,
            "invalidated_pack_ids": invalidated,
        },
    )
    db.commit()
    result = _snapshot_result(snapshot)
    result["invalidatedPackIds"] = invalidated
    return result


def erase_snapshot_content(
    db: Session,
    *,
    actor: MarketActor,
    snapshot_id: str,
    legal_basis: str,
    reason: str,
) -> dict[str, Any]:
    if not actor.can_quarantine:
        raise MarketIntelligenceError(
            "erasure_forbidden", "Nincs crypto-erasure jogosultság.", status_code=403
        )
    snapshot = db.scalar(
        select(MarketSourceSnapshot)
        .where(
            MarketSourceSnapshot.snapshot_id == snapshot_id,
            MarketSourceSnapshot.tenant_id == actor.tenant_id,
            MarketSourceSnapshot.brand_id == actor.brand_id,
            MarketSourceSnapshot.market_id == actor.market_id,
        )
        .with_for_update()
    )
    if snapshot is None:
        raise MarketIntelligenceError(
            "snapshot_not_found", "A snapshot nem található.", status_code=404
        )
    if snapshot.created_by == actor.subject_id:
        raise MarketIntelligenceError(
            "four_eyes_required",
            "A snapshot létrehozója nem törölheti saját bizonyítékát.",
            status_code=409,
        )
    if snapshot.quarantine_state == "ERASED" or snapshot.erased_at is not None:
        raise MarketIntelligenceError(
            "snapshot_already_erased", "A snapshot tartalma már törölt.", status_code=409
        )
    if snapshot.quarantine_state not in {"CLEAN", "QUARANTINED"}:
        raise MarketIntelligenceError(
            "snapshot_erasure_state_invalid", "Ebben az állapotban nem törölhető.", status_code=409
        )
    if legal_basis not in {"RIGHTS_REVOKED", "PRIVACY_REQUEST", "SECURITY_INCIDENT"}:
        raise MarketIntelligenceError(
            "erasure_basis_invalid", "Ehhez a jogalaphoz crypto-erasure nem engedélyezett."
        )
    if not reason.strip():
        raise MarketIntelligenceError("erasure_reason_required", "A törlés oka kötelező.")
    previous_state = snapshot.quarantine_state
    snapshot.encrypted_content = None
    snapshot.content_nonce = None
    snapshot.encrypted_dek = None
    snapshot.dek_nonce = None
    snapshot.encryption_key_id = None
    snapshot.normalized_text = ""
    snapshot.storage_ref = None
    snapshot.quarantine_state = "ERASED"
    snapshot.erased_at = utcnow()
    db.add(
        MarketEvidenceRedaction(
            redaction_id=_id("MER"),
            snapshot_id=snapshot.snapshot_id,
            action="CRYPTO_ERASE",
            legal_basis=legal_basis,
            reason=reason.strip(),
            actor_subject_id=snapshot.created_by,
            reviewer_subject_id=actor.subject_id,
        )
    )
    invalidated = _invalidate_packs_for_snapshot(db, actor, snapshot.snapshot_id, reason.strip())
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.snapshot.crypto_erase",
        entity_type="MarketSourceSnapshot",
        entity_id=snapshot.snapshot_id,
        before={"quarantine_state": previous_state},
        after={
            "quarantine_state": "ERASED",
            "legal_basis": legal_basis,
            "invalidated_pack_ids": invalidated,
            "content_sha256_retained": snapshot.content_sha256,
        },
    )
    db.commit()
    result = _snapshot_result(snapshot)
    result["invalidatedPackIds"] = invalidated
    return result


def create_observation(
    db: Session,
    *,
    actor: MarketActor,
    snapshot_id: str,
    statement: str,
    start_offset: int,
    end_offset: int,
    evidence_level: str,
    method: str = "",
    confidence: float | None = None,
) -> dict[str, Any]:
    _require_author(actor)
    snapshot = _snapshot(db, actor, snapshot_id)
    if snapshot.quarantine_state != "CLEAN":
        raise MarketIntelligenceError(
            "snapshot_blocked", "A forrás nem használható.", status_code=409
        )
    source_text = _snapshot_text(snapshot)
    if not 0 <= start_offset < end_offset <= len(source_text):
        raise MarketIntelligenceError("source_span_invalid", "A bizonyíték szövegtartománya hibás.")
    if evidence_level not in {"OBSERVED", "INFERRED"}:
        raise MarketIntelligenceError(
            "evidence_level_invalid", "Belső validáltság csak jóváhagyott Validationből adható."
        )
    if evidence_level == "INFERRED" and (not method.strip() or confidence is None):
        raise MarketIntelligenceError(
            "inference_metadata_required", "Következtetéshez módszer és konfidencia szükséges."
        )
    if confidence is not None and not 0 <= confidence <= 1:
        raise MarketIntelligenceError("confidence_invalid", "A konfidencia 0 és 1 közötti lehet.")
    canonical = {
        "snapshotId": snapshot_id,
        "sourceSpan": {"start": start_offset, "end": end_offset},
        "statement": statement.strip(),
        "evidenceLevel": evidence_level,
        "method": method.strip() or None,
        "confidence": confidence,
    }
    if not canonical["statement"]:
        raise MarketIntelligenceError("statement_required", "A megfigyelés szövege kötelező.")
    row = MarketObservation(
        observation_id=_id("MOB"),
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        snapshot_id=snapshot_id,
        source_span_json=_json(canonical["sourceSpan"]),
        statement=str(canonical["statement"]),
        evidence_level=evidence_level,
        method=method.strip() or None,
        confidence=confidence,
        canonical_sha256=_sha(canonical),
        created_by=actor.subject_id,
    )
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.observation.create",
        entity_type="MarketObservation",
        entity_id=row.observation_id,
        after={"snapshot_id": snapshot_id, "evidence_level": evidence_level},
    )
    db.commit()
    return _observation_result(row)


def create_asset(
    db: Session,
    *,
    actor: MarketActor,
    snapshot_id: str,
    channel: str,
    asset_type: str,
    title: str,
    start_offset: int,
    end_offset: int,
    claims: list[str],
) -> dict[str, Any]:
    _require_author(actor)
    snapshot = _usable_snapshot(db, actor, snapshot_id)
    span = _source_span(snapshot, start_offset, end_offset)
    canonical = {
        "snapshotId": snapshot_id,
        "channel": _required(channel, "asset_channel_required"),
        "assetType": _required(asset_type, "asset_type_required"),
        "title": _required(title, "asset_title_required"),
        "sourceSpan": span,
        "claims": sorted({item.strip() for item in claims if item.strip()}),
        "extractionVersion": "manual-evidence-v1",
    }
    row = MarketAsset(
        asset_id=_id("MAS"),
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        snapshot_id=snapshot_id,
        channel=canonical["channel"],
        asset_type=canonical["assetType"],
        title=canonical["title"],
        source_span_json=_json(span),
        claims_json=_json(canonical["claims"]),
        extraction_version=canonical["extractionVersion"],
        canonical_sha256=_sha(canonical),
        created_by=actor.subject_id,
    )
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.asset.create",
        entity_type="MarketAsset",
        entity_id=row.asset_id,
        after={"snapshot_id": snapshot_id, "canonical_sha256": row.canonical_sha256},
    )
    db.commit()
    return _asset_result(row)


def create_voc_signal(
    db: Session,
    *,
    actor: MarketActor,
    snapshot_id: str,
    masked_quote: str,
    theme: str,
    sentiment: str,
    start_offset: int,
    end_offset: int,
) -> dict[str, Any]:
    _require_author(actor)
    snapshot = _usable_snapshot(db, actor, snapshot_id)
    span = _source_span(snapshot, start_offset, end_offset)
    sentiment_value = sentiment.strip().upper() or None
    if sentiment_value not in {None, "POSITIVE", "NEUTRAL", "NEGATIVE", "MIXED"}:
        raise MarketIntelligenceError("voc_sentiment_invalid", "Ismeretlen VOC hangulat.")
    quote = _required(masked_quote, "voc_quote_required")
    _scan_content(quote, "text/plain")
    canonical = {
        "snapshotId": snapshot_id,
        "sourceSpan": span,
        "maskedQuote": quote,
        "theme": _required(theme, "voc_theme_required"),
        "sentiment": sentiment_value,
    }
    row = MarketVocSignal(
        signal_id=_id("MVS"),
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        snapshot_id=snapshot_id,
        source_span_json=_json(span),
        masked_quote=quote,
        theme=canonical["theme"],
        sentiment=sentiment_value,
        canonical_sha256=_sha(canonical),
        created_by=actor.subject_id,
    )
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.voc.create",
        entity_type="MarketVocSignal",
        entity_id=row.signal_id,
        after={"snapshot_id": snapshot_id, "theme": row.theme},
    )
    db.commit()
    return _voc_result(row)


def create_pattern_cluster(
    db: Session,
    *,
    actor: MarketActor,
    title: str,
    summary: str,
    member_ids: list[str],
    confidence: float | None,
) -> dict[str, Any]:
    _require_author(actor)
    members = _evidence_refs(db, actor, member_ids)
    if len(members) < 2:
        raise MarketIntelligenceError(
            "cluster_members_required", "Legalább két bizonyíték szükséges."
        )
    confidence_value = _confidence(confidence)
    cluster_id = _id("MPC")
    row = MarketPatternCluster(
        cluster_id=cluster_id,
        family_id=cluster_id,
        revision_no=1,
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        title=_required(title, "cluster_title_required"),
        summary=_required(summary, "cluster_summary_required"),
        algorithm_version="human-reviewed-v1",
        member_ids_json=_json(members),
        confidence=confidence_value,
        status="DRAFT",
        created_by=actor.subject_id,
    )
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.cluster.create",
        entity_type="MarketPatternCluster",
        entity_id=row.cluster_id,
        after={"member_count": len(members), "status": row.status},
    )
    db.commit()
    return _cluster_result(row)


def revise_pattern_cluster(
    db: Session,
    *,
    actor: MarketActor,
    cluster_id: str,
    title: str,
    summary: str,
    member_ids: list[str],
    confidence: float | None,
) -> dict[str, Any]:
    _require_author(actor)
    parent = _cluster(db, actor, cluster_id, lock=True)
    family = db.scalars(
        select(MarketPatternCluster)
        .where(MarketPatternCluster.family_id == parent.family_id)
        .order_by(desc(MarketPatternCluster.revision_no))
        .with_for_update()
    ).all()
    latest = family[0]
    if latest.cluster_id != parent.cluster_id:
        raise MarketIntelligenceError(
            "cluster_not_latest",
            "Csak a legújabb klaszterből készülhet új revízió.",
            status_code=409,
        )
    members = _evidence_refs(db, actor, sorted(set(member_ids)))
    if len(members) < 2:
        raise MarketIntelligenceError(
            "cluster_members_required", "Legalább két bizonyíték szükséges."
        )
    new_row = MarketPatternCluster(
        cluster_id=_id("MPC"),
        family_id=parent.family_id,
        revision_no=parent.revision_no + 1,
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        title=_required(title, "cluster_title_required"),
        summary=_required(summary, "cluster_summary_required"),
        algorithm_version="human-reviewed-v1",
        member_ids_json=_json(members),
        confidence=_confidence(confidence),
        status="DRAFT",
        created_by=actor.subject_id,
    )
    parent.status = "SUPERSEDED"
    db.add(new_row)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.cluster.revise",
        entity_type="MarketPatternCluster",
        entity_id=new_row.cluster_id,
        before={"cluster_id": parent.cluster_id, "revision_no": parent.revision_no},
        after={"revision_no": new_row.revision_no, "member_count": len(members)},
    )
    db.commit()
    return _cluster_result(new_row)


def compare_pattern_clusters(
    db: Session, *, actor: MarketActor, left_id: str, right_id: str
) -> dict[str, Any]:
    left = _cluster(db, actor, left_id)
    right = _cluster(db, actor, right_id)
    if left.family_id != right.family_id:
        raise MarketIntelligenceError(
            "cluster_family_mismatch", "Csak azonos klasztercsalád revíziói hasonlíthatók össze."
        )
    left_members = {item["id"]: item for item in json.loads(left.member_ids_json)}
    right_members = {item["id"]: item for item in json.loads(right.member_ids_json)}
    return {
        "left": _cluster_result(left),
        "right": _cluster_result(right),
        "addedMembers": [right_members[key] for key in sorted(right_members.keys() - left_members)],
        "removedMembers": [
            left_members[key] for key in sorted(left_members.keys() - right_members)
        ],
        "retainedMemberIds": sorted(left_members.keys() & right_members.keys()),
        "titleChanged": left.title != right.title,
        "summaryChanged": left.summary != right.summary,
        "confidenceChanged": left.confidence != right.confidence,
    }


def create_hypothesis(
    db: Session,
    *,
    actor: MarketActor,
    statement: str,
    audience: str,
    supporting_ids: list[str],
    contradicting_ids: list[str],
    falsification_criterion: str,
) -> dict[str, Any]:
    _require_author(actor)
    supporting = _evidence_refs(db, actor, supporting_ids)
    contradicting = _evidence_refs(db, actor, contradicting_ids) if contradicting_ids else []
    if not supporting:
        raise MarketIntelligenceError(
            "hypothesis_support_required", "Támogató bizonyíték szükséges."
        )
    overlap = {item["id"] for item in supporting} & {item["id"] for item in contradicting}
    if overlap:
        raise MarketIntelligenceError(
            "hypothesis_evidence_conflict", "Egy bizonyíték nem lehet egyszerre támogató és cáfoló."
        )
    canonical = {
        "statement": _required(statement, "hypothesis_statement_required"),
        "audience": _required(audience, "hypothesis_audience_required"),
        "supporting": supporting,
        "contradicting": contradicting,
        "falsificationCriterion": _required(falsification_criterion, "falsification_required"),
    }
    row = MarketResearchHypothesis(
        hypothesis_id=_id("MRH"),
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        statement=canonical["statement"],
        audience=canonical["audience"],
        supporting_ids_json=_json(supporting),
        contradicting_ids_json=_json(contradicting),
        falsification_criterion=canonical["falsificationCriterion"],
        evidence_level="INFERRED",
        canonical_sha256=_sha(canonical),
        owner_subject_id=actor.subject_id,
        status="DRAFT",
    )
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.hypothesis.create",
        entity_type="MarketResearchHypothesis",
        entity_id=row.hypothesis_id,
        after={"canonical_sha256": row.canonical_sha256},
    )
    db.commit()
    return _hypothesis_result(row)


def create_validation(
    db: Session,
    *,
    actor: MarketActor,
    subject_type: str,
    subject_id: str,
    method: str,
    metric: dict[str, Any],
    sample: dict[str, Any],
    outcome: str,
) -> dict[str, Any]:
    _require_author(actor)
    subject_type = subject_type.strip().upper()
    subject_sha = _validation_subject_hash(db, actor, subject_type, subject_id)
    if outcome not in {"SUPPORTED", "REFUTED", "INCONCLUSIVE"}:
        raise MarketIntelligenceError(
            "validation_outcome_invalid", "Ismeretlen validációs eredmény."
        )
    if not metric or not sample:
        raise MarketIntelligenceError("validation_evidence_required", "Mérőszám és minta kötelező.")
    row = MarketValidation(
        validation_id=_id("MVA"),
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        subject_type=subject_type,
        subject_id=subject_id,
        subject_sha256=subject_sha,
        method=_required(method, "validation_method_required"),
        metric_json=_json(metric),
        sample_json=_json(sample),
        outcome=outcome,
        status="DRAFT",
        author_subject_id=actor.subject_id,
    )
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.validation.create",
        entity_type="MarketValidation",
        entity_id=row.validation_id,
        after={"subject_type": subject_type, "subject_id": subject_id, "outcome": outcome},
    )
    db.commit()
    return _validation_result(row)


def transition_validation(
    db: Session,
    *,
    actor: MarketActor,
    validation_id: str,
    action: str,
    expected_subject_sha256: str | None = None,
) -> dict[str, Any]:
    row = _validation(db, actor, validation_id, lock=True)
    if expected_subject_sha256 is not None and row.subject_sha256 != expected_subject_sha256:
        raise MarketIntelligenceError(
            "stale_validation", "A validáció tárgya időközben módosult.", status_code=409
        )
    current_sha = _validation_subject_hash(db, actor, row.subject_type, row.subject_id)
    if current_sha != row.subject_sha256:
        raise MarketIntelligenceError(
            "validation_subject_changed", "A validált objektum megváltozott.", status_code=409
        )
    if (
        action == "submit_review"
        and row.status == "DRAFT"
        and row.author_subject_id == actor.subject_id
    ):
        next_status = "IN_REVIEW"
    elif action in {"approve", "reject"} and row.status == "IN_REVIEW" and actor.can_review:
        if row.author_subject_id == actor.subject_id:
            raise MarketIntelligenceError(
                "four_eyes_required",
                "A szerző nem bírálhatja el saját validációját.",
                status_code=409,
            )
        next_status = "APPROVED" if action == "approve" else "REJECTED"
        row.reviewer_subject_id = actor.subject_id
        row.reviewed_at = utcnow()
    else:
        raise MarketIntelligenceError(
            "validation_transition_forbidden", "A validációs átmenet tiltott.", status_code=403
        )
    before = row.status
    row.status = next_status
    if next_status == "APPROVED" and row.outcome == "SUPPORTED":
        _promote_validated_subject(db, actor, row)
    audit(
        db,
        actor=actor.subject_id,
        action=f"market_intelligence.validation.{action}",
        entity_type="MarketValidation",
        entity_id=row.validation_id,
        before={"status": before},
        after={"status": row.status},
    )
    db.commit()
    return _validation_result(row)


def create_pack(
    db: Session,
    *,
    actor: MarketActor,
    title: str,
    summary: str,
    intended_use: str,
    channels: list[str],
    observation_ids: list[str],
) -> dict[str, Any]:
    _require_author(actor)
    unique_ids = sorted(set(item for item in observation_ids if item))
    if not unique_ids:
        raise MarketIntelligenceError("pack_members_required", "Legalább egy bizonyíték kötelező.")
    members = _evidence_refs(db, actor, unique_ids)
    valid_until = utcnow() + timedelta(days=30)
    manifest = _pack_manifest(
        title.strip(), summary.strip(), intended_use.strip(), channels, members, valid_until
    )
    pack_id = _id("MRP")
    sequence_no = (
        db.scalar(
            select(func.max(MarketResearchPack.sequence_no)).where(
                MarketResearchPack.tenant_id == actor.tenant_id,
                MarketResearchPack.brand_id == actor.brand_id,
                MarketResearchPack.market_id == actor.market_id,
            )
        )
        or 0
    ) + 1
    row = MarketResearchPack(
        pack_id=pack_id,
        family_id=pack_id,
        revision_no=1,
        sequence_no=sequence_no,
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        title=title.strip(),
        summary=summary.strip(),
        intended_use=intended_use.strip(),
        channels_json=_json(sorted(set(channels))),
        member_refs_json=_json(members),
        manifest_sha256=_sha(manifest),
        status="DRAFT",
        row_version=1,
        valid_until=valid_until,
        author_subject_id=actor.subject_id,
    )
    if not row.title or not row.summary or not row.intended_use:
        raise MarketIntelligenceError("pack_fields_required", "A pack kötelező mezői hiányoznak.")
    db.add(row)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.pack.create",
        entity_type="MarketResearchPack",
        entity_id=pack_id,
        after={"manifest_sha256": row.manifest_sha256, "status": "DRAFT"},
    )
    db.commit()
    return _pack_result(row)


def revise_pack(
    db: Session,
    *,
    actor: MarketActor,
    pack_id: str,
    row_version: int,
    title: str,
    summary: str,
    intended_use: str,
    channels: list[str],
    observation_ids: list[str],
) -> dict[str, Any]:
    _require_author(actor)
    parent = _pack(db, actor, pack_id, lock=True)
    family = db.scalars(
        select(MarketResearchPack)
        .where(MarketResearchPack.family_id == parent.family_id)
        .order_by(desc(MarketResearchPack.revision_no))
        .with_for_update()
    ).all()
    latest = family[0]
    if latest.pack_id != parent.pack_id:
        raise MarketIntelligenceError(
            "pack_not_latest", "Csak a legújabb packből készülhet új revízió.", status_code=409
        )
    if parent.row_version != row_version:
        raise MarketIntelligenceError("stale_pack", "A kutatási pack módosult.", status_code=409)
    members = _evidence_refs(db, actor, sorted(set(item for item in observation_ids if item)))
    if not members:
        raise MarketIntelligenceError("pack_members_required", "Legalább egy bizonyíték kötelező.")
    valid_until = utcnow() + timedelta(days=30)
    normalized_channels = sorted(set(item.strip() for item in channels if item.strip()))
    manifest = _pack_manifest(
        _required(title, "pack_title_required"),
        _required(summary, "pack_summary_required"),
        _required(intended_use, "pack_intended_use_required"),
        normalized_channels,
        members,
        valid_until,
    )
    sequence_no = (
        db.scalar(
            select(func.max(MarketResearchPack.sequence_no)).where(
                MarketResearchPack.tenant_id == actor.tenant_id,
                MarketResearchPack.brand_id == actor.brand_id,
                MarketResearchPack.market_id == actor.market_id,
            )
        )
        or 0
    ) + 1
    new_row = MarketResearchPack(
        pack_id=_id("MRP"),
        family_id=parent.family_id,
        revision_no=parent.revision_no + 1,
        sequence_no=sequence_no,
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        title=title.strip(),
        summary=summary.strip(),
        intended_use=intended_use.strip(),
        channels_json=_json(normalized_channels),
        member_refs_json=_json(members),
        manifest_sha256=_sha(manifest),
        status="DRAFT",
        row_version=1,
        valid_until=valid_until,
        author_subject_id=actor.subject_id,
    )
    previous_status = parent.status
    if previous_status == "HANDED_OFF":
        _queue_pack_invalidation(db, actor, parent, "Új kutatási pack-revízió készült.")
    parent.status = "SUPERSEDED"
    parent.row_version += 1
    db.add(new_row)
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.pack.revise",
        entity_type="MarketResearchPack",
        entity_id=new_row.pack_id,
        before={"pack_id": parent.pack_id, "revision_no": parent.revision_no},
        after={
            "revision_no": new_row.revision_no,
            "manifest_sha256": new_row.manifest_sha256,
            "member_count": len(members),
        },
    )
    db.commit()
    return _pack_result(new_row)


def compare_packs(
    db: Session, *, actor: MarketActor, left_id: str, right_id: str
) -> dict[str, Any]:
    left = _pack(db, actor, left_id)
    right = _pack(db, actor, right_id)
    if left.family_id != right.family_id:
        raise MarketIntelligenceError(
            "pack_family_mismatch", "Csak azonos packcsalád revíziói hasonlíthatók össze."
        )
    left_members = {item["id"]: item for item in json.loads(left.member_refs_json)}
    right_members = {item["id"]: item for item in json.loads(right.member_refs_json)}
    return {
        "left": _pack_result(left),
        "right": _pack_result(right),
        "addedMembers": [right_members[key] for key in sorted(right_members.keys() - left_members)],
        "removedMembers": [
            left_members[key] for key in sorted(left_members.keys() - right_members)
        ],
        "retainedMemberIds": sorted(left_members.keys() & right_members.keys()),
        "titleChanged": left.title != right.title,
        "summaryChanged": left.summary != right.summary,
        "intendedUseChanged": left.intended_use != right.intended_use,
        "channelsChanged": json.loads(left.channels_json) != json.loads(right.channels_json),
        "manifestChanged": left.manifest_sha256 != right.manifest_sha256,
    }


def transition_pack(
    db: Session,
    *,
    actor: MarketActor,
    pack_id: str,
    row_version: int,
    action: str,
    reason: str = "",
) -> dict[str, Any]:
    row = _pack(db, actor, pack_id, lock=True)
    if row.row_version != row_version:
        raise MarketIntelligenceError("stale_pack", "A kutatási pack módosult.", status_code=409)
    current_hash = _sha(
        _pack_manifest(
            row.title,
            row.summary,
            row.intended_use,
            json.loads(row.channels_json),
            json.loads(row.member_refs_json),
            row.valid_until,
        )
    )
    if current_hash != row.manifest_sha256:
        raise MarketIntelligenceError(
            "manifest_mismatch", "A pack manifestje eltér.", status_code=409
        )
    if action != "revoke":
        _assert_pack_members_usable(db, actor, json.loads(row.member_refs_json))
    if action == "submit_review":
        if row.status != "DRAFT" or row.author_subject_id != actor.subject_id:
            raise MarketIntelligenceError("transition_forbidden", "A pack nem küldhető review-ra.")
        next_status = "IN_REVIEW"
    elif action == "approve":
        if not actor.can_review or row.status != "IN_REVIEW":
            raise MarketIntelligenceError(
                "review_forbidden", "A pack nem hagyható jóvá.", status_code=403
            )
        if row.author_subject_id == actor.subject_id:
            raise MarketIntelligenceError(
                "four_eyes_required", "A szerző nem hagyhatja jóvá saját packját.", status_code=409
            )
        next_status = "APPROVED"
        row.reviewer_subject_id = actor.subject_id
        row.reviewed_at = utcnow()
    elif action == "freeze":
        if not actor.can_freeze or row.status != "APPROVED":
            raise MarketIntelligenceError(
                "freeze_forbidden", "A pack nem fagyasztható.", status_code=403
            )
        if row.author_subject_id == actor.subject_id:
            raise MarketIntelligenceError(
                "four_eyes_required", "A szerző nem fagyaszthatja saját packját.", status_code=409
            )
        valid_until = row.valid_until
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=UTC)
        if valid_until <= utcnow():
            raise MarketIntelligenceError("pack_expired", "A pack lejárt.", status_code=409)
        next_status = "FROZEN"
        row.frozen_by = actor.subject_id
        row.frozen_at = utcnow()
    elif action == "revoke":
        if not actor.can_freeze or row.status not in {
            "DRAFT",
            "IN_REVIEW",
            "APPROVED",
            "FROZEN",
            "HANDED_OFF",
        }:
            raise MarketIntelligenceError(
                "pack_revoke_forbidden", "A pack nem vonható vissza.", status_code=403
            )
        if not reason.strip():
            raise MarketIntelligenceError("revoke_reason_required", "A visszavonás oka kötelező.")
        next_status = "REVOKED"
        _queue_pack_invalidation(db, actor, row, reason.strip())
    else:
        raise MarketIntelligenceError("transition_invalid", "Ismeretlen packművelet.")
    before = row.status
    row.status = next_status
    row.row_version += 1
    audit(
        db,
        actor=actor.subject_id,
        action=f"market_intelligence.pack.{action}",
        entity_type="MarketResearchPack",
        entity_id=pack_id,
        before={"status": before},
        after={"status": next_status, "manifest_sha256": row.manifest_sha256},
    )
    db.commit()
    return _pack_result(row)


def handoff_pack(
    db: Session,
    *,
    actor: MarketActor,
    pack_id: str,
    downstream_purpose: str,
    idempotency_key: str,
) -> dict[str, Any]:
    if not actor.can_handoff:
        raise MarketIntelligenceError(
            "handoff_forbidden", "Nincs ITEP handoff-jogosultság.", status_code=403
        )
    purpose = downstream_purpose.strip()
    allowed_purposes = {"campaign_research_brief", "content_research_brief", "sales_research_brief"}
    if purpose not in allowed_purposes:
        raise MarketIntelligenceError(
            "handoff_purpose_forbidden", "A cél nem engedélyezett kutatási bemenet."
        )
    if not idempotency_key.strip():
        raise MarketIntelligenceError("idempotency_key_required", "Idempotency kulcs kötelező.")
    replay = db.scalar(
        select(MarketPackHandoff).where(
            MarketPackHandoff.tenant_id == actor.tenant_id,
            MarketPackHandoff.idempotency_key == idempotency_key,
        )
    )
    if replay:
        if replay.pack_id != pack_id or replay.downstream_purpose != purpose:
            raise MarketIntelligenceError(
                "idempotency_conflict",
                "Az idempotency kulcs más művelethez tartozik.",
                status_code=409,
            )
        return _handoff_result(replay)
    pack = _pack(db, actor, pack_id, lock=True)
    latest_revision = db.scalar(
        select(func.max(MarketResearchPack.revision_no)).where(
            MarketResearchPack.family_id == pack.family_id,
            MarketResearchPack.tenant_id == actor.tenant_id,
            MarketResearchPack.brand_id == actor.brand_id,
            MarketResearchPack.market_id == actor.market_id,
        )
    )
    valid_until = (
        pack.valid_until if pack.valid_until.tzinfo else pack.valid_until.replace(tzinfo=UTC)
    )
    if (
        pack.status not in {"FROZEN", "HANDED_OFF"}
        or pack.revision_no != latest_revision
        or valid_until <= utcnow()
    ):
        raise MarketIntelligenceError(
            "pack_not_handoff_ready",
            "Csak a legújabb, érvényes, fagyasztott pack adható át.",
            status_code=409,
        )
    current_hash = _sha(
        _pack_manifest(
            pack.title,
            pack.summary,
            pack.intended_use,
            json.loads(pack.channels_json),
            json.loads(pack.member_refs_json),
            pack.valid_until,
        )
    )
    if current_hash != pack.manifest_sha256:
        raise MarketIntelligenceError(
            "manifest_mismatch", "A pack manifestje eltér.", status_code=409
        )
    _assert_pack_members_usable(db, actor, json.loads(pack.member_refs_json))
    watermark = db.scalar(
        select(MarketHandoffWatermark)
        .where(
            MarketHandoffWatermark.tenant_id == actor.tenant_id,
            MarketHandoffWatermark.brand_id == actor.brand_id,
            MarketHandoffWatermark.market_id == actor.market_id,
            MarketHandoffWatermark.downstream_purpose == purpose,
        )
        .with_for_update()
    )
    if watermark and pack.sequence_no < watermark.sequence_no:
        raise MarketIntelligenceError(
            "handoff_out_of_order", "Régebbi kutatási csomag nem aktiválható.", status_code=409
        )
    if (
        watermark
        and pack.sequence_no == watermark.sequence_no
        and pack.manifest_sha256 != watermark.manifest_sha256
    ):
        raise MarketIntelligenceError(
            "handoff_sequence_conflict",
            "Azonos sorszámhoz eltérő manifest tartozik.",
            status_code=409,
        )
    handoff = MarketPackHandoff(
        handoff_id=_id("MPH"),
        tenant_id=actor.tenant_id,
        brand_id=actor.brand_id,
        market_id=actor.market_id,
        pack_id=pack.pack_id,
        manifest_sha256=pack.manifest_sha256,
        downstream_purpose=purpose,
        idempotency_key=idempotency_key,
        status="ACCEPTED",
        created_by=actor.subject_id,
    )
    db.add(handoff)
    if watermark is None:
        watermark = MarketHandoffWatermark(
            tenant_id=actor.tenant_id,
            brand_id=actor.brand_id,
            market_id=actor.market_id,
            downstream_purpose=purpose,
            sequence_no=pack.sequence_no,
            manifest_sha256=pack.manifest_sha256,
            pack_id=pack.pack_id,
        )
        db.add(watermark)
    elif pack.sequence_no > watermark.sequence_no:
        watermark.sequence_no = pack.sequence_no
        watermark.manifest_sha256 = pack.manifest_sha256
        watermark.pack_id = pack.pack_id
    payload = {
        "eventType": "MCI_RESEARCH_PACK_HANDED_OFF",
        "schemaVersion": "mci-handoff-v1",
        "handoffId": handoff.handoff_id,
        "packId": pack.pack_id,
        "manifestSha256": pack.manifest_sha256,
        "tenantId": actor.tenant_id,
        "brandId": actor.brand_id,
        "marketId": actor.market_id,
        "downstreamPurpose": purpose,
        "sequenceNo": pack.sequence_no,
        "publicationAllowed": False,
    }
    db.add(
        OutboxMessage(
            message_id=_id("OUT-MCI"),
            destination_module="content-quality",
            endpoint="/commands/research-pack-intake",
            payload_json=_json(payload),
            payload_sha256=_sha(payload),
            delivery_mode="internal_only",
            status="pending",
            max_retries=5,
            next_attempt_at=utcnow(),
        )
    )
    before = pack.status
    pack.status = "HANDED_OFF"
    pack.row_version += 1
    audit(
        db,
        actor=actor.subject_id,
        action="market_intelligence.pack.handoff",
        entity_type="MarketResearchPack",
        entity_id=pack.pack_id,
        before={"status": before},
        after={
            "status": pack.status,
            "handoff_id": handoff.handoff_id,
            "publication_allowed": False,
        },
    )
    db.commit()
    return _handoff_result(handoff)


def dashboard(
    db: Session, actor: MarketActor, *, public_fetch_enabled: bool = False
) -> dict[str, Any]:
    scope = (
        actor.tenant_id,
        actor.brand_id,
        actor.market_id,
    )
    targets = db.scalars(
        select(MarketSourceTarget)
        .where(
            MarketSourceTarget.tenant_id == scope[0],
            MarketSourceTarget.brand_id == scope[1],
            MarketSourceTarget.market_id == scope[2],
        )
        .order_by(desc(MarketSourceTarget.updated_at))
        .limit(100)
    ).all()
    jobs = db.scalars(
        select(MarketCaptureJob)
        .where(
            MarketCaptureJob.tenant_id == scope[0],
            MarketCaptureJob.brand_id == scope[1],
            MarketCaptureJob.market_id == scope[2],
        )
        .order_by(desc(MarketCaptureJob.created_at))
        .limit(100)
    ).all()
    snapshots = db.scalars(
        select(MarketSourceSnapshot)
        .where(
            MarketSourceSnapshot.tenant_id == scope[0],
            MarketSourceSnapshot.brand_id == scope[1],
            MarketSourceSnapshot.market_id == scope[2],
        )
        .order_by(desc(MarketSourceSnapshot.captured_at))
        .limit(100)
    ).all()
    snapshot_ids = [row.snapshot_id for row in snapshots]
    redactions = (
        db.scalars(
            select(MarketEvidenceRedaction)
            .where(MarketEvidenceRedaction.snapshot_id.in_(snapshot_ids))
            .order_by(desc(MarketEvidenceRedaction.created_at))
        ).all()
        if snapshot_ids
        else []
    )
    observations = db.scalars(
        select(MarketObservation)
        .where(
            MarketObservation.tenant_id == scope[0],
            MarketObservation.brand_id == scope[1],
            MarketObservation.market_id == scope[2],
        )
        .order_by(desc(MarketObservation.created_at))
        .limit(100)
    ).all()
    assets = db.scalars(_scoped_latest(MarketAsset, actor, MarketAsset.created_at)).all()
    voc_signals = db.scalars(
        _scoped_latest(MarketVocSignal, actor, MarketVocSignal.created_at)
    ).all()
    clusters = db.scalars(
        _scoped_latest(MarketPatternCluster, actor, MarketPatternCluster.created_at)
    ).all()
    hypotheses = db.scalars(
        _scoped_latest(MarketResearchHypothesis, actor, MarketResearchHypothesis.created_at)
    ).all()
    validations = db.scalars(
        _scoped_latest(MarketValidation, actor, MarketValidation.created_at)
    ).all()
    packs = db.scalars(
        select(MarketResearchPack)
        .where(
            MarketResearchPack.tenant_id == scope[0],
            MarketResearchPack.brand_id == scope[1],
            MarketResearchPack.market_id == scope[2],
        )
        .order_by(desc(MarketResearchPack.updated_at))
        .limit(100)
    ).all()
    handoffs = db.scalars(
        _scoped_latest(MarketPackHandoff, actor, MarketPackHandoff.created_at)
    ).all()
    job_status_counts = {
        str(status): int(count)
        for status, count in db.execute(
            select(MarketCaptureJob.status, func.count(MarketCaptureJob.id))
            .where(
                MarketCaptureJob.tenant_id == scope[0],
                MarketCaptureJob.brand_id == scope[1],
                MarketCaptureJob.market_id == scope[2],
            )
            .group_by(MarketCaptureJob.status)
        ).all()
    }
    oldest_queued_at = db.scalar(
        select(func.min(MarketCaptureJob.created_at)).where(
            MarketCaptureJob.tenant_id == scope[0],
            MarketCaptureJob.brand_id == scope[1],
            MarketCaptureJob.market_id == scope[2],
            MarketCaptureJob.status == "QUEUED",
        )
    )
    approved_public_targets = int(
        db.scalar(
            select(func.count(MarketSourceTarget.id)).where(
                MarketSourceTarget.tenant_id == scope[0],
                MarketSourceTarget.brand_id == scope[1],
                MarketSourceTarget.market_id == scope[2],
                MarketSourceTarget.status == "APPROVED",
                MarketSourceTarget.capture_mode == "public_fetch",
            )
        )
        or 0
    )
    visible_ids = {
        str(value)
        for rows, attribute in (
            (targets, "target_id"),
            (jobs, "job_id"),
            (snapshots, "snapshot_id"),
            (observations, "observation_id"),
            (assets, "asset_id"),
            (voc_signals, "signal_id"),
            (clusters, "cluster_id"),
            (hypotheses, "hypothesis_id"),
            (validations, "validation_id"),
            (packs, "pack_id"),
            (handoffs, "handoff_id"),
        )
        for value in (getattr(row, attribute, None) for row in rows)
        if value
    }
    recent_audits = (
        db.scalars(
            select(AuditLog)
            .where(
                AuditLog.action.like("market_intelligence.%"),
                AuditLog.entity_id.in_(visible_ids),
            )
            .order_by(desc(AuditLog.created_at))
            .limit(100)
        ).all()
        if visible_ids
        else []
    )
    audit_events = [
        {
            "action": row.action,
            "entityType": row.entity_type,
            "entityId": row.entity_id,
            "actor": row.actor,
            "createdAt": row.created_at,
        }
        for row in recent_audits
        if row.entity_id in visible_ids
    ][:100]
    mci_outbox = []
    for row in db.scalars(
        select(OutboxMessage)
        .where(OutboxMessage.message_id.like("OUT-MCI-%"))
        .order_by(desc(OutboxMessage.created_at))
        .limit(200)
    ).all():
        try:
            payload = json.loads(row.payload_json)
        except (TypeError, ValueError):
            continue
        if (
            payload.get("tenantId"),
            payload.get("brandId"),
            payload.get("marketId"),
        ) != scope:
            continue
        mci_outbox.append(
            {
                "messageId": row.message_id,
                "eventType": payload.get("eventType"),
                "status": row.status,
                "retryCount": row.retry_count,
                "createdAt": row.created_at,
            }
        )
        if len(mci_outbox) == 100:
            break
    queue_depth = job_status_counts.get("QUEUED", 0)
    running_count = job_status_counts.get("RUNNING", 0)
    failed_count = int(
        db.scalar(
            select(func.count(MarketCaptureJob.id)).where(
                MarketCaptureJob.tenant_id == scope[0],
                MarketCaptureJob.brand_id == scope[1],
                MarketCaptureJob.market_id == scope[2],
                MarketCaptureJob.status == "FAILED",
                MarketCaptureJob.finished_at >= utcnow() - timedelta(hours=24),
            )
        )
        or 0
    )
    public_fetch_health = (
        "DISABLED"
        if not public_fetch_enabled
        else "BLOCKED"
        if approved_public_targets == 0
        else "DEGRADED"
        if failed_count > 0
        else "READY"
    )
    return {
        "targets": [_target_result(row) for row in targets],
        "captureJobs": [_capture_job_result(row) for row in jobs],
        "snapshots": [_snapshot_result(row) for row in snapshots],
        "redactions": [_redaction_result(row) for row in redactions],
        "observations": [_observation_result(row) for row in observations],
        "assets": [_asset_result(row) for row in assets],
        "vocSignals": [_voc_result(row) for row in voc_signals],
        "clusters": [_cluster_result(row) for row in clusters],
        "hypotheses": [_hypothesis_result(row) for row in hypotheses],
        "validations": [_validation_result(row) for row in validations],
        "packs": [_pack_result(row) for row in packs],
        "handoffs": [_handoff_result(row) for row in handoffs],
        "health": {
            "publicFetch": public_fetch_health,
            "approvedPublicTargets": approved_public_targets,
            "queueDepth": queue_depth,
            "running": running_count,
            "failed": failed_count,
            "oldestQueuedAt": oldest_queued_at,
            "handoffPending": sum(1 for row in mci_outbox if row["status"] == "pending"),
            "evidenceEncryption": "READY" if settings.market_evidence_kek else "BLOCKED",
        },
        "auditEvents": audit_events,
        "outbox": mci_outbox,
        "connectors": {
            "manual": True,
            "fixture": True,
            "publicFetch": public_fetch_enabled,
            "handoff": True,
            "externalPublication": False,
        },
    }


def service_resource_list(db: Session, actor: MarketActor, resource: str) -> list[dict[str, Any]]:
    """Return one bounded service resource without loading unrelated evidence."""
    scope = (actor.tenant_id, actor.brand_id, actor.market_id)
    if resource == "source-targets":
        target_rows = db.scalars(
            select(MarketSourceTarget)
            .where(
                MarketSourceTarget.tenant_id == scope[0],
                MarketSourceTarget.brand_id == scope[1],
                MarketSourceTarget.market_id == scope[2],
            )
            .order_by(desc(MarketSourceTarget.updated_at))
            .limit(100)
        ).all()
        return [_target_result(row) for row in target_rows]
    if resource == "capture-jobs":
        capture_job_rows = db.scalars(
            select(MarketCaptureJob)
            .where(
                MarketCaptureJob.tenant_id == scope[0],
                MarketCaptureJob.brand_id == scope[1],
                MarketCaptureJob.market_id == scope[2],
            )
            .order_by(desc(MarketCaptureJob.created_at))
            .limit(100)
        ).all()
        return [_capture_job_result(row) for row in capture_job_rows]
    if resource == "observations":
        observation_rows = db.scalars(
            select(MarketObservation)
            .where(
                MarketObservation.tenant_id == scope[0],
                MarketObservation.brand_id == scope[1],
                MarketObservation.market_id == scope[2],
            )
            .order_by(desc(MarketObservation.created_at))
            .limit(100)
        ).all()
        return [_observation_result(row) for row in observation_rows]
    if resource == "assets":
        return [
            _asset_result(row)
            for row in db.scalars(_scoped_latest(MarketAsset, actor, MarketAsset.created_at)).all()
        ]
    if resource == "voc-signals":
        return [
            _voc_result(row)
            for row in db.scalars(
                _scoped_latest(MarketVocSignal, actor, MarketVocSignal.created_at)
            ).all()
        ]
    if resource == "pattern-clusters":
        return [
            _cluster_result(row)
            for row in db.scalars(
                _scoped_latest(MarketPatternCluster, actor, MarketPatternCluster.created_at)
            ).all()
        ]
    if resource == "hypotheses":
        return [
            _hypothesis_result(row)
            for row in db.scalars(
                _scoped_latest(
                    MarketResearchHypothesis,
                    actor,
                    MarketResearchHypothesis.created_at,
                )
            ).all()
        ]
    if resource == "research-packs":
        pack_rows = db.scalars(
            select(MarketResearchPack)
            .where(
                MarketResearchPack.tenant_id == scope[0],
                MarketResearchPack.brand_id == scope[1],
                MarketResearchPack.market_id == scope[2],
            )
            .order_by(desc(MarketResearchPack.updated_at))
            .limit(100)
        ).all()
        return [_pack_result(row) for row in pack_rows]
    raise ValueError(f"Unsupported Market service resource: {resource}")


def _target(
    db: Session, actor: MarketActor, target_id: str, *, lock: bool = False
) -> MarketSourceTarget:
    query = select(MarketSourceTarget).where(
        MarketSourceTarget.target_id == target_id,
        MarketSourceTarget.tenant_id == actor.tenant_id,
        MarketSourceTarget.brand_id == actor.brand_id,
        MarketSourceTarget.market_id == actor.market_id,
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise MarketIntelligenceError(
            "target_not_found", "A forrás nem található.", status_code=404
        )
    return row


def _snapshot(db: Session, actor: MarketActor, snapshot_id: str) -> MarketSourceSnapshot:
    row = db.scalar(
        select(MarketSourceSnapshot).where(
            MarketSourceSnapshot.snapshot_id == snapshot_id,
            MarketSourceSnapshot.tenant_id == actor.tenant_id,
            MarketSourceSnapshot.brand_id == actor.brand_id,
            MarketSourceSnapshot.market_id == actor.market_id,
        )
    )
    if row is None:
        raise MarketIntelligenceError(
            "snapshot_not_found", "A snapshot nem található.", status_code=404
        )
    return row


def _usable_snapshot(db: Session, actor: MarketActor, snapshot_id: str) -> MarketSourceSnapshot:
    row = _snapshot(db, actor, snapshot_id)
    if row.quarantine_state != "CLEAN":
        raise MarketIntelligenceError(
            "snapshot_blocked", "A forrás karanténban van.", status_code=409
        )
    return row


def _source_span(snapshot: MarketSourceSnapshot, start: int, end: int) -> dict[str, int]:
    if not 0 <= start < end <= len(_snapshot_text(snapshot)):
        raise MarketIntelligenceError("source_span_invalid", "A bizonyíték szövegtartománya hibás.")
    return {"start": start, "end": end}


def _evidence_refs(db: Session, actor: MarketActor, member_ids: list[str]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for member_id in sorted({item.strip() for item in member_ids if item.strip()}):
        row: Any = db.scalar(
            select(MarketObservation).where(
                MarketObservation.observation_id == member_id,
                MarketObservation.tenant_id == actor.tenant_id,
                MarketObservation.brand_id == actor.brand_id,
                MarketObservation.market_id == actor.market_id,
            )
        )
        kind = "observation"
        if row is None:
            row = db.scalar(
                select(MarketVocSignal).where(
                    MarketVocSignal.signal_id == member_id,
                    MarketVocSignal.tenant_id == actor.tenant_id,
                    MarketVocSignal.brand_id == actor.brand_id,
                    MarketVocSignal.market_id == actor.market_id,
                )
            )
            kind = "voc"
        if row is None:
            row = db.scalar(
                select(MarketAsset).where(
                    MarketAsset.asset_id == member_id,
                    MarketAsset.tenant_id == actor.tenant_id,
                    MarketAsset.brand_id == actor.brand_id,
                    MarketAsset.market_id == actor.market_id,
                )
            )
            kind = "asset"
        if row is None:
            raise MarketIntelligenceError(
                "evidence_not_found", f"A bizonyíték nem érhető el: {member_id}", status_code=404
            )
        _usable_snapshot(db, actor, row.snapshot_id)
        refs.append({"type": kind, "id": member_id, "sha256": row.canonical_sha256})
    return refs


def _validation(
    db: Session, actor: MarketActor, validation_id: str, *, lock: bool = False
) -> MarketValidation:
    query = select(MarketValidation).where(
        MarketValidation.validation_id == validation_id,
        MarketValidation.tenant_id == actor.tenant_id,
        MarketValidation.brand_id == actor.brand_id,
        MarketValidation.market_id == actor.market_id,
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise MarketIntelligenceError(
            "validation_not_found", "A validáció nem található.", status_code=404
        )
    return row


def _validation_subject_hash(
    db: Session, actor: MarketActor, subject_type: str, subject_id: str
) -> str:
    subject_row: MarketObservation | MarketResearchHypothesis | None
    if subject_type == "OBSERVATION":
        subject_row = db.scalar(
            select(MarketObservation).where(
                MarketObservation.observation_id == subject_id,
                MarketObservation.tenant_id == actor.tenant_id,
                MarketObservation.brand_id == actor.brand_id,
                MarketObservation.market_id == actor.market_id,
            )
        )
    elif subject_type == "HYPOTHESIS":
        subject_row = db.scalar(
            select(MarketResearchHypothesis).where(
                MarketResearchHypothesis.hypothesis_id == subject_id,
                MarketResearchHypothesis.tenant_id == actor.tenant_id,
                MarketResearchHypothesis.brand_id == actor.brand_id,
                MarketResearchHypothesis.market_id == actor.market_id,
            )
        )
    else:
        raise MarketIntelligenceError(
            "validation_subject_type_invalid", "Csak megfigyelés vagy hipotézis validálható."
        )
    if subject_row is None:
        raise MarketIntelligenceError(
            "validation_subject_not_found", "A validáció tárgya nem található.", status_code=404
        )
    return subject_row.canonical_sha256


def _promote_validated_subject(
    db: Session, actor: MarketActor, validation: MarketValidation
) -> None:
    if validation.subject_type == "OBSERVATION":
        observation_row = db.scalar(
            select(MarketObservation)
            .where(
                MarketObservation.observation_id == validation.subject_id,
                MarketObservation.tenant_id == actor.tenant_id,
                MarketObservation.brand_id == actor.brand_id,
                MarketObservation.market_id == actor.market_id,
            )
            .with_for_update()
        )
        if (
            observation_row is None
            or observation_row.canonical_sha256 != validation.subject_sha256
        ):
            raise MarketIntelligenceError(
                "validation_subject_changed", "A megfigyelés megváltozott.", status_code=409
            )
        observation_row.evidence_level = "VALIDATED_INTERNAL"
    elif validation.subject_type == "HYPOTHESIS":
        hypothesis_row = db.scalar(
            select(MarketResearchHypothesis)
            .where(
                MarketResearchHypothesis.hypothesis_id == validation.subject_id,
                MarketResearchHypothesis.tenant_id == actor.tenant_id,
                MarketResearchHypothesis.brand_id == actor.brand_id,
                MarketResearchHypothesis.market_id == actor.market_id,
            )
            .with_for_update()
        )
        if hypothesis_row is None or hypothesis_row.canonical_sha256 != validation.subject_sha256:
            raise MarketIntelligenceError(
                "validation_subject_changed", "A hipotézis megváltozott.", status_code=409
            )
        hypothesis_row.evidence_level = "VALIDATED_INTERNAL"
        hypothesis_row.status = "VALIDATED"


def _invalidate_packs_for_snapshot(
    db: Session, actor: MarketActor, snapshot_id: str, reason: str
) -> list[str]:
    evidence_ids: set[str] = set(
        db.scalars(
            select(MarketObservation.observation_id).where(
                MarketObservation.snapshot_id == snapshot_id,
                MarketObservation.tenant_id == actor.tenant_id,
                MarketObservation.brand_id == actor.brand_id,
                MarketObservation.market_id == actor.market_id,
            )
        ).all()
    )
    evidence_ids.update(
        db.scalars(
            select(MarketAsset.asset_id).where(
                MarketAsset.snapshot_id == snapshot_id,
                MarketAsset.tenant_id == actor.tenant_id,
                MarketAsset.brand_id == actor.brand_id,
                MarketAsset.market_id == actor.market_id,
            )
        ).all()
    )
    evidence_ids.update(
        db.scalars(
            select(MarketVocSignal.signal_id).where(
                MarketVocSignal.snapshot_id == snapshot_id,
                MarketVocSignal.tenant_id == actor.tenant_id,
                MarketVocSignal.brand_id == actor.brand_id,
                MarketVocSignal.market_id == actor.market_id,
            )
        ).all()
    )
    if not evidence_ids:
        return []
    rows = db.scalars(
        select(MarketResearchPack)
        .where(
            MarketResearchPack.tenant_id == actor.tenant_id,
            MarketResearchPack.brand_id == actor.brand_id,
            MarketResearchPack.market_id == actor.market_id,
            MarketResearchPack.status.in_(
                ["DRAFT", "IN_REVIEW", "APPROVED", "FROZEN", "HANDED_OFF"]
            ),
        )
        .with_for_update()
    ).all()
    invalidated: list[str] = []
    for row in rows:
        member_ids = {str(item.get("id")) for item in json.loads(row.member_refs_json)}
        if not member_ids.intersection(evidence_ids):
            continue
        before = row.status
        _queue_pack_invalidation(db, actor, row, reason)
        row.status = "REVOKED"
        row.row_version += 1
        invalidated.append(row.pack_id)
        audit(
            db,
            actor=actor.subject_id,
            action="market_intelligence.pack.evidence_invalidated",
            entity_type="MarketResearchPack",
            entity_id=row.pack_id,
            before={"status": before},
            after={"status": "REVOKED", "snapshot_id": snapshot_id, "reason": reason},
        )
    return invalidated


def _queue_pack_invalidation(
    db: Session, actor: MarketActor, pack: MarketResearchPack, reason: str
) -> None:
    if pack.status != "HANDED_OFF":
        return
    payload = {
        "eventType": "MCI_RESEARCH_PACK_INVALIDATED",
        "schemaVersion": "mci-handoff-v1",
        "packId": pack.pack_id,
        "manifestSha256": pack.manifest_sha256,
        "tenantId": actor.tenant_id,
        "brandId": actor.brand_id,
        "marketId": actor.market_id,
        "reason": reason,
        "publicationAllowed": False,
    }
    db.add(
        OutboxMessage(
            message_id=_id("OUT-MCI"),
            destination_module="content-quality",
            endpoint="/commands/research-pack-invalidation",
            payload_json=_json(payload),
            payload_sha256=_sha(payload),
            delivery_mode="internal_only",
            status="pending",
            max_retries=5,
            next_attempt_at=utcnow(),
        )
    )


def _assert_pack_members_usable(
    db: Session, actor: MarketActor, refs: list[dict[str, Any]]
) -> None:
    for ref in refs:
        resolved = _evidence_refs(db, actor, [str(ref.get("id") or "")])
        if not resolved or resolved[0]["sha256"] != ref.get("sha256"):
            raise MarketIntelligenceError(
                "pack_member_changed", "A pack egyik bizonyítéka megváltozott.", status_code=409
            )


def _scoped_latest(model: Any, actor: MarketActor, order_column: Any) -> Any:
    return (
        select(model)
        .where(
            model.tenant_id == actor.tenant_id,
            model.brand_id == actor.brand_id,
            model.market_id == actor.market_id,
        )
        .order_by(desc(order_column))
        .limit(100)
    )


def _pack(
    db: Session, actor: MarketActor, pack_id: str, *, lock: bool = False
) -> MarketResearchPack:
    query = select(MarketResearchPack).where(
        MarketResearchPack.pack_id == pack_id,
        MarketResearchPack.tenant_id == actor.tenant_id,
        MarketResearchPack.brand_id == actor.brand_id,
        MarketResearchPack.market_id == actor.market_id,
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise MarketIntelligenceError(
            "pack_not_found", "A kutatási pack nem található.", status_code=404
        )
    return row


def _cluster(
    db: Session, actor: MarketActor, cluster_id: str, *, lock: bool = False
) -> MarketPatternCluster:
    query = select(MarketPatternCluster).where(
        MarketPatternCluster.cluster_id == cluster_id,
        MarketPatternCluster.tenant_id == actor.tenant_id,
        MarketPatternCluster.brand_id == actor.brand_id,
        MarketPatternCluster.market_id == actor.market_id,
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise MarketIntelligenceError(
            "cluster_not_found", "A bizonyítékklaszter nem található.", status_code=404
        )
    return row


def _require_executable_capture_target(db: Session, target: MarketSourceTarget) -> None:
    latest_revision = db.scalar(
        select(func.max(MarketSourceTarget.revision_no)).where(
            MarketSourceTarget.family_id == target.family_id
        )
    )
    try:
        policy = json.loads(target.policy_json)
    except (TypeError, json.JSONDecodeError) as error:
        raise MarketIntelligenceError(
            "target_policy_invalid", "A target policy nem értelmezhető.", status_code=409
        ) from error
    if (
        target.status != "APPROVED"
        or target.revision_no != latest_revision
        or target.capture_mode != "public_fetch"
        or policy.get("captureMode") != "public_fetch"
        or policy.get("productionFetchEnabled") is not True
        or _sha(policy) != target.policy_sha256
    ):
        raise MarketIntelligenceError(
            "target_not_executable",
            "Csak a legújabb, jóváhagyott public-fetch target futtatható.",
            status_code=409,
        )


def _require_job_target_unchanged(
    db: Session, target: MarketSourceTarget, job: MarketCaptureJob
) -> None:
    try:
        _require_executable_capture_target(db, target)
    except MarketIntelligenceError as error:
        raise MarketIntelligenceError(
            "target_changed", "A target vagy policy a capture közben megváltozott.", status_code=409
        ) from error
    if (
        target.target_id != job.target_id
        or target.revision_no != job.target_revision_no
        or target.policy_sha256 != job.policy_sha256
    ):
        raise MarketIntelligenceError(
            "target_changed", "A target vagy policy a capture közben megváltozott.", status_code=409
        )


def _store_public_capture(
    db: Session,
    *,
    target: MarketSourceTarget,
    job: MarketCaptureJob,
    response: PublicCaptureResponse,
) -> None:
    resolved_url = _allowed_url(target, response.resolved_url)
    if response.mime_type not in {"text/plain", "text/html"}:
        raise MarketIntelligenceError("mime_forbidden", "Tiltott válasz MIME típus.")
    encoded = response.content.encode("utf-8")
    if not encoded or len(encoded) > 200_000:
        raise MarketIntelligenceError("content_size_invalid", "A válasz üres vagy túl nagy.")
    _scan_content(response.content, response.mime_type)
    try:
        address = ipaddress.ip_address(response.source_ip)
    except ValueError as error:
        raise MarketIntelligenceError("source_ip_invalid", "A source IP érvénytelen.") from error
    if not address.is_global:
        raise MarketIntelligenceError(
            "private_address_forbidden", "Nem publikus source IP tiltott."
        )
    normalized_text = "\n".join(
        line.rstrip() for line in response.content.replace("\r", "").split("\n")
    )
    content_sha = hashlib.sha256(encoded).hexdigest()
    existing = db.scalar(
        select(MarketSourceSnapshot).where(
            MarketSourceSnapshot.target_id == target.target_id,
            MarketSourceSnapshot.content_sha256 == content_sha,
        )
    )
    job.status = "SUCCEEDED"
    job.finished_at = utcnow()
    job.error_code = None
    job.error_detail = None
    if existing:
        job.error_code = "content_deduplicated"
        job.error_detail = existing.snapshot_id
        return
    snapshot = MarketSourceSnapshot(
        snapshot_id=_id("MSS"),
        tenant_id=job.tenant_id,
        brand_id=job.brand_id,
        market_id=job.market_id,
        target_id=job.target_id,
        capture_job_id=job.job_id,
        resolved_url=resolved_url,
        http_status=response.http_status,
        response_headers_json=_json(response.response_headers),
        source_ip=str(address),
        mime_type=response.mime_type,
        content_sha256=content_sha,
        normalized_text_sha256=hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        normalized_text="",
        policy_sha256=job.policy_sha256,
        parser_version="public-text-v1",
        parser_digest="builtin:public-text-v1",
        privacy_classification="PUBLIC",
        quarantine_state="CLEAN",
        created_by=job.created_by,
    )
    _apply_encrypted_text(snapshot, normalized_text)
    db.add(snapshot)
    audit(
        db,
        actor="system:market-capture",
        action="market_intelligence.snapshot.public_fetch",
        entity_type="MarketSourceSnapshot",
        entity_id=snapshot.snapshot_id,
        after={
            "job_id": job.job_id,
            "target_id": target.target_id,
            "content_sha256": content_sha,
            "source_ip": str(address),
        },
    )


def _fail_capture_job(db: Session, job_id: str, code: str, detail: str) -> None:
    row = db.scalar(
        select(MarketCaptureJob).where(MarketCaptureJob.job_id == job_id).with_for_update()
    )
    if row is None or row.status == "CANCELLED":
        db.rollback()
        return
    row.status = "FAILED"
    row.error_code = code[:120]
    row.error_detail = detail[:2000]
    row.finished_at = utcnow()
    audit(
        db,
        actor="system:market-capture",
        action="market_intelligence.capture.failed",
        entity_type="MarketCaptureJob",
        entity_id=row.job_id,
        after={"status": "FAILED", "error_code": row.error_code},
    )
    db.commit()


def _public_addresses(host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    if not host or host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise MarketIntelligenceError(
            "private_address_forbidden", "Belső vagy metadata host tiltott."
        )
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            }
        except OSError as error:
            raise MarketIntelligenceError(
                "dns_resolution_failed", "A host nem oldható fel biztonságosan."
            ) from error
    if not addresses or any(not address.is_global for address in addresses):
        raise MarketIntelligenceError(
            "private_address_forbidden",
            "Privát, loopback, link-local, reserved vagy multicast cím tiltott.",
        )
    return addresses


def _origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise MarketIntelligenceError("origin_invalid", "Csak hiteles webes origin adható meg.")
    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError as error:
        raise MarketIntelligenceError("origin_invalid", "Az origin portja érvénytelen.") from error
    return urlunsplit((parsed.scheme.lower(), f"{parsed.hostname.lower()}{port}", "", "", ""))


def _allowed_url(target: MarketSourceTarget, value: str) -> str:
    parsed = urlsplit(value.strip())
    candidate_origin = _origin(value)
    requested_path = parsed.path or "/"
    allowed_path = target.allowed_path.rstrip("/") or "/"
    path_allowed = (
        allowed_path == "/"
        or requested_path == allowed_path
        or requested_path.startswith(f"{allowed_path}/")
    )
    if candidate_origin != target.normalized_origin or not path_allowed:
        raise MarketIntelligenceError(
            "url_outside_target", "Az URL a jóváhagyott forráson kívül van."
        )
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise MarketIntelligenceError(
            "url_credentials_forbidden", "Credential vagy fragment tiltott."
        )
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
    )


def _scan_content(content: str, mime_type: str) -> None:
    lowered = content.lower()
    if mime_type == "text/html" and re.search(
        r"<\s*(script|iframe|object|embed)\b|\bon\w+\s*=", lowered
    ):
        raise MarketIntelligenceError(
            "active_content_forbidden", "Aktív HTML-tartalom nem importálható."
        )
    secret_patterns = (
        r"\b(?:api[_ -]?key|secret|password)\s*[:=]",
        r"\bbearer\s+[a-z0-9._~-]{12,}",
        r"-----begin (?:rsa |ec )?private key-----",
    )
    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in secret_patterns):
        raise MarketIntelligenceError(
            "secret_detected", "A tartalom titkot vagy credentialt tartalmazhat."
        )
    if re.search(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", content, re.IGNORECASE):
        raise MarketIntelligenceError("pii_detected", "A tartalom személyes adatot tartalmazhat.")
    if any(
        phrase in lowered
        for phrase in ("ignore previous instructions", "system prompt", "developer message")
    ):
        raise MarketIntelligenceError(
            "prompt_injection_detected", "A forrás utasításbefecskendezést tartalmazhat."
        )


def _pack_manifest(
    title: str,
    summary: str,
    intended_use: str,
    channels: list[str],
    members: list[dict[str, Any]],
    valid_until: Any,
) -> dict[str, Any]:
    return {
        "title": title,
        "summary": summary,
        "intendedUse": intended_use,
        "channels": sorted(set(channels)),
        "members": sorted(members, key=lambda item: (item["type"], item["id"])),
        "validUntil": _utc_iso(valid_until),
        "schemaVersion": "mci-pack-v1",
    }


def _capture_rate_policy(max_requests: int, window_seconds: int) -> dict[str, int]:
    if not 1 <= int(max_requests) <= 1000:
        raise MarketIntelligenceError(
            "capture_rate_limit_invalid", "A capture-kvóta 1 és 1000 közötti lehet."
        )
    if not 60 <= int(window_seconds) <= 86_400:
        raise MarketIntelligenceError(
            "capture_rate_window_invalid",
            "A capture-időszak 60 és 86400 másodperc közötti lehet.",
        )
    return {"maxRequests": int(max_requests), "windowSeconds": int(window_seconds)}


def _target_rate_policy(row: MarketSourceTarget) -> dict[str, int]:
    try:
        policy = json.loads(row.policy_json or "{}")
        rate_limit = policy.get("rateLimit") or {}
        return _capture_rate_policy(
            int(rate_limit.get("maxRequests", DEFAULT_CAPTURE_RATE_MAX)),
            int(rate_limit.get("windowSeconds", DEFAULT_CAPTURE_RATE_WINDOW_SECONDS)),
        )
    except (TypeError, ValueError):
        return _capture_rate_policy(DEFAULT_CAPTURE_RATE_MAX, DEFAULT_CAPTURE_RATE_WINDOW_SECONDS)


def _target_result(row: MarketSourceTarget) -> dict[str, Any]:
    rate_policy = _target_rate_policy(row)
    return {
        "targetId": row.target_id,
        "familyId": row.family_id,
        "revisionNo": row.revision_no,
        "name": row.name,
        "origin": row.normalized_origin,
        "allowedPath": row.allowed_path,
        "captureMode": row.capture_mode,
        "rightsStatus": row.rights_status,
        "status": row.status,
        "rowVersion": row.row_version,
        "authorSubjectId": row.author_subject_id,
        "revokeReason": row.revoke_reason,
        "updatedAt": row.updated_at,
        "rateLimit": rate_policy,
    }


def _snapshot_result(row: MarketSourceSnapshot) -> dict[str, Any]:
    return {
        "snapshotId": row.snapshot_id,
        "targetId": row.target_id,
        "resolvedUrl": row.resolved_url,
        "httpStatus": row.http_status,
        "responseHeaders": json.loads(row.response_headers_json or "{}"),
        "sourceIp": row.source_ip,
        "mimeType": row.mime_type,
        "contentSha256": row.content_sha256,
        "text": _snapshot_text(row) if row.quarantine_state == "CLEAN" else None,
        "quarantineState": row.quarantine_state,
        "capturedAt": row.captured_at,
        "createdBy": row.created_by,
    }


def _capture_job_result(row: MarketCaptureJob) -> dict[str, Any]:
    return {
        "jobId": row.job_id,
        "targetId": row.target_id,
        "requestedUrl": row.requested_url,
        "targetRevisionNo": row.target_revision_no,
        "status": row.status,
        "attempts": row.attempts,
        "errorCode": row.error_code,
        "createdAt": row.created_at,
        "finishedAt": row.finished_at,
    }


def _redaction_result(row: MarketEvidenceRedaction) -> dict[str, Any]:
    return {
        "redactionId": row.redaction_id,
        "snapshotId": row.snapshot_id,
        "action": row.action,
        "legalBasis": row.legal_basis,
        "reason": row.reason,
        "reviewerSubjectId": row.reviewer_subject_id,
        "createdAt": row.created_at,
    }


def _observation_result(row: MarketObservation) -> dict[str, Any]:
    return {
        "observationId": row.observation_id,
        "snapshotId": row.snapshot_id,
        "statement": row.statement,
        "evidenceLevel": row.evidence_level,
        "sourceSpan": json.loads(row.source_span_json),
        "canonicalSha256": row.canonical_sha256,
        "createdAt": row.created_at,
    }


def _pack_result(row: MarketResearchPack) -> dict[str, Any]:
    members = json.loads(row.member_refs_json)
    return {
        "packId": row.pack_id,
        "familyId": row.family_id,
        "revisionNo": row.revision_no,
        "sequenceNo": row.sequence_no,
        "title": row.title,
        "summary": row.summary,
        "intendedUse": row.intended_use,
        "channels": json.loads(row.channels_json),
        "members": members,
        "memberIds": [item["id"] for item in members],
        "manifestSha256": row.manifest_sha256,
        "status": row.status,
        "rowVersion": row.row_version,
        "authorSubjectId": row.author_subject_id,
        "validUntil": row.valid_until,
        "updatedAt": row.updated_at,
    }


def _asset_result(row: MarketAsset) -> dict[str, Any]:
    return {
        "assetId": row.asset_id,
        "snapshotId": row.snapshot_id,
        "channel": row.channel,
        "assetType": row.asset_type,
        "title": row.title,
        "sourceSpan": json.loads(row.source_span_json),
        "claims": json.loads(row.claims_json),
        "canonicalSha256": row.canonical_sha256,
        "createdAt": row.created_at,
    }


def _voc_result(row: MarketVocSignal) -> dict[str, Any]:
    return {
        "signalId": row.signal_id,
        "snapshotId": row.snapshot_id,
        "maskedQuote": row.masked_quote,
        "theme": row.theme,
        "sentiment": row.sentiment,
        "sourceSpan": json.loads(row.source_span_json),
        "canonicalSha256": row.canonical_sha256,
        "createdAt": row.created_at,
    }


def _cluster_result(row: MarketPatternCluster) -> dict[str, Any]:
    members = json.loads(row.member_ids_json)
    return {
        "clusterId": row.cluster_id,
        "familyId": row.family_id,
        "revisionNo": row.revision_no,
        "title": row.title,
        "summary": row.summary,
        "members": members,
        "memberIds": [item["id"] for item in members],
        "algorithmVersion": row.algorithm_version,
        "confidence": row.confidence,
        "status": row.status,
        "createdAt": row.created_at,
    }


def _hypothesis_result(row: MarketResearchHypothesis) -> dict[str, Any]:
    return {
        "hypothesisId": row.hypothesis_id,
        "statement": row.statement,
        "audience": row.audience,
        "supporting": json.loads(row.supporting_ids_json),
        "contradicting": json.loads(row.contradicting_ids_json),
        "falsificationCriterion": row.falsification_criterion,
        "evidenceLevel": row.evidence_level,
        "status": row.status,
        "canonicalSha256": row.canonical_sha256,
        "createdAt": row.created_at,
    }


def _validation_result(row: MarketValidation) -> dict[str, Any]:
    return {
        "validationId": row.validation_id,
        "subjectType": row.subject_type,
        "subjectId": row.subject_id,
        "subjectSha256": row.subject_sha256,
        "method": row.method,
        "metric": json.loads(row.metric_json),
        "sample": json.loads(row.sample_json),
        "outcome": row.outcome,
        "status": row.status,
        "authorSubjectId": row.author_subject_id,
        "createdAt": row.created_at,
    }


def _handoff_result(row: MarketPackHandoff) -> dict[str, Any]:
    return {
        "handoffId": row.handoff_id,
        "packId": row.pack_id,
        "manifestSha256": row.manifest_sha256,
        "downstreamPurpose": row.downstream_purpose,
        "status": row.status,
        "createdAt": row.created_at,
    }


def _required(value: str, code: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise MarketIntelligenceError(code, "Kötelező mező hiányzik.")
    return normalized


def _evidence_kek() -> bytes:
    try:
        key = base64.b64decode(settings.market_evidence_kek, validate=True)
    except (binascii.Error, ValueError, TypeError) as error:
        raise MarketIntelligenceError(
            "evidence_key_unavailable",
            "A bizonyítéktitkosítás kulcsa érvénytelen.",
            status_code=503,
        ) from error
    if len(key) != 32:
        raise MarketIntelligenceError(
            "evidence_key_unavailable", "A bizonyítéktitkosítás kulcsa hiányzik.", status_code=503
        )
    return key


def _apply_encrypted_text(snapshot: MarketSourceSnapshot, text: str) -> None:
    dek = secrets.token_bytes(32)
    content_nonce = secrets.token_bytes(12)
    dek_nonce = secrets.token_bytes(12)
    content_aad = f"mci-content-v1:{snapshot.snapshot_id}:{snapshot.content_sha256}".encode()
    dek_aad = f"mci-dek-v1:{settings.market_evidence_key_id}".encode()
    snapshot.encrypted_content = base64.b64encode(
        AESGCM(dek).encrypt(content_nonce, text.encode("utf-8"), content_aad)
    ).decode("ascii")
    snapshot.content_nonce = base64.b64encode(content_nonce).decode("ascii")
    snapshot.encrypted_dek = base64.b64encode(
        AESGCM(_evidence_kek()).encrypt(dek_nonce, dek, dek_aad)
    ).decode("ascii")
    snapshot.dek_nonce = base64.b64encode(dek_nonce).decode("ascii")
    snapshot.encryption_key_id = settings.market_evidence_key_id


def _snapshot_text(snapshot: MarketSourceSnapshot) -> str:
    if snapshot.quarantine_state != "CLEAN" or snapshot.erased_at is not None:
        raise MarketIntelligenceError(
            "snapshot_blocked", "A bizonyíték tartalma nem olvasható.", status_code=409
        )
    if snapshot.encrypted_content is None:
        if snapshot.normalized_text:
            return snapshot.normalized_text
        raise MarketIntelligenceError(
            "evidence_key_destroyed",
            "A bizonyíték visszafejtési kulcsa nem létezik.",
            status_code=410,
        )
    if snapshot.encryption_key_id != settings.market_evidence_key_id:
        raise MarketIntelligenceError(
            "evidence_key_version_unknown",
            "Ismeretlen bizonyítéktitkosítási kulcsverzió.",
            status_code=409,
        )
    try:
        dek_nonce = base64.b64decode(str(snapshot.dek_nonce), validate=True)
        encrypted_dek = base64.b64decode(snapshot.encrypted_dek or "", validate=True)
        dek_aad = f"mci-dek-v1:{snapshot.encryption_key_id}".encode()
        dek = AESGCM(_evidence_kek()).decrypt(dek_nonce, encrypted_dek, dek_aad)
        content_nonce = base64.b64decode(str(snapshot.content_nonce), validate=True)
        ciphertext = base64.b64decode(snapshot.encrypted_content, validate=True)
        content_aad = f"mci-content-v1:{snapshot.snapshot_id}:{snapshot.content_sha256}".encode()
        return AESGCM(dek).decrypt(content_nonce, ciphertext, content_aad).decode("utf-8")
    except (InvalidTag, binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise MarketIntelligenceError(
            "evidence_decryption_failed",
            "A bizonyíték integritásellenőrzése sikertelen.",
            status_code=409,
        ) from error


def _require_author(actor: MarketActor) -> None:
    if not actor.can_author:
        raise MarketIntelligenceError(
            "author_forbidden", "Nincs ITEP author-jogosultság.", status_code=403
        )


def _confidence(value: float | None) -> Decimal | None:
    if value is None:
        return None
    if not 0 <= value <= 1:
        raise MarketIntelligenceError("confidence_invalid", "A konfidencia 0 és 1 közötti lehet.")
    return Decimal(str(value))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _utc_iso(value: Any) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
