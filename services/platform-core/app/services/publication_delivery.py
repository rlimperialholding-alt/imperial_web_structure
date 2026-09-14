from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    ContentAssetRecord,
    OutboxMessage,
    PublicationBundleRecord,
    PublicationDelivery,
)
from ..schemas import PublicationDeliveryClaimIn, PublicationDeliveryReceiptIn

DELIVERY_ROLES = {"owner", "managing-director", "marketing", "platform-admin"}
TARGET_RE = re.compile(r"^(META_ADS|GOOGLE_ADS|CONTENT:[A-Z0-9_-]{2,80})$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _identity(user: object) -> tuple[str, str]:
    return str(getattr(user, "role", "")), str(getattr(user, "email", "")).lower()


def _targets_for_exports(exports: object) -> list[str]:
    targets: set[str] = set()
    for export in exports if isinstance(exports, list) else []:
        if not isinstance(export, dict):
            continue
        platform = str(export.get("platform") or "").strip().lower()
        if platform in {"facebook", "instagram", "meta", "meta_ads"}:
            targets.add("META_ADS")
        elif platform in {"google", "google_ads"}:
            targets.add("GOOGLE_ADS")
        elif platform:
            targets.add(f"CONTENT:{platform.upper()}")
    return sorted(targets)


def _targets_for_payload(
    db: Session, payload: dict[str, Any], validation: dict[str, Any]
) -> list[str]:
    action = str(validation.get("action") or payload.get("action") or "PUBLISH")
    if action == "PUBLISH":
        contract = validation.get("adapter_contract")
        if not isinstance(contract, dict):
            raise ValueError("A publikációs adapterből hiányzik a validált szerződés.")
        raw_targets = contract.get("delivery_targets")
        targets = raw_targets if isinstance(raw_targets, list) else []
    else:
        proof_id = str(payload.get("publication_proof_id") or "")
        targets = list(
            db.scalars(
                select(PublicationDelivery.target).where(
                    PublicationDelivery.publication_proof_id == proof_id,
                    PublicationDelivery.action == "PUBLISH",
                )
            ).all()
        )
        if not targets:
            asset_id = str(payload.get("asset_id") or "")
            asset = db.scalar(
                select(ContentAssetRecord).where(
                    ContentAssetRecord.asset_id == asset_id,
                    ContentAssetRecord.publication_proof_id == proof_id,
                )
            )
            bundle = (
                db.get(PublicationBundleRecord, asset.active_bundle_id)
                if asset and asset.active_bundle_id
                else None
            )
            targets = _targets_for_exports(
                json.loads(bundle.exports_json) if bundle else None
            )
    normalized = sorted({str(target).strip().upper() for target in targets})
    if not normalized:
        raise ValueError("A publikációhoz nincs kézbesítési cél.")
    invalid = [target for target in normalized if not TARGET_RE.fullmatch(target)]
    if invalid:
        raise ValueError("Érvénytelen publikációs cél: " + ", ".join(invalid))
    return normalized


def stage_publication_deliveries(
    db: Session,
    message: OutboxMessage,
    payload: dict[str, Any],
    validation: dict[str, Any],
) -> list[PublicationDelivery]:
    action = str(validation.get("action") or payload.get("action") or "PUBLISH")
    proof_id = str(payload.get("publication_proof_id") or "").strip()
    asset_id = str(payload.get("asset_id") or "").strip()
    if not proof_id or not asset_id:
        raise ValueError("A kézbesítésből hiányzik az asset- vagy proofazonosító.")
    targets = _targets_for_payload(db, payload, validation)
    payload_json = _canonical_json(payload)
    payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    rows: list[PublicationDelivery] = []
    for target in targets:
        idempotency_key = _sha(
            {"publication_proof_id": proof_id, "target": target, "action": action}
        )
        existing = db.scalar(
            select(PublicationDelivery).where(
                PublicationDelivery.publication_proof_id == proof_id,
                PublicationDelivery.target == target,
                PublicationDelivery.action == action,
            )
        )
        if existing:
            if (
                existing.idempotency_key != idempotency_key
                or existing.payload_sha256 != payload_sha256
            ):
                raise ValueError("A meglévő publikációs kézbesítés tartalma eltér.")
            rows.append(existing)
            continue
        row = PublicationDelivery(
            delivery_id=f"PUBDEL-{uuid4().hex[:16].upper()}",
            message_id=message.message_id,
            asset_id=asset_id,
            publication_proof_id=proof_id,
            publication_bundle_id=str(payload.get("publication_bundle_id") or "") or None,
            target=target,
            action=action,
            idempotency_key=idempotency_key,
            payload_json=payload_json,
            payload_sha256=payload_sha256,
            status="ready",
            max_attempts=max(1, message.max_retries),
            available_at=utcnow(),
        )
        db.add(row)
        rows.append(row)
    message.status = "staged"
    message.last_error = None
    audit(
        db,
        actor="publication-delivery",
        action="publication_deliveries_staged",
        entity_type="outbox_message",
        entity_id=message.message_id,
        after={"proof_id": proof_id, "action": action, "targets": targets},
    )
    db.flush()
    return rows


def _release_expired_claims(db: Session, now: datetime) -> None:
    rows = db.scalars(
        select(PublicationDelivery).where(
            PublicationDelivery.status == "claimed",
            PublicationDelivery.lease_expires_at.is_not(None),
            PublicationDelivery.lease_expires_at <= now,
        )
    ).all()
    for row in rows:
        row.status = (
            "dead_letter" if row.attempt_count >= row.max_attempts else "retry"
        )
        row.available_at = now
        row.last_error = "Az adapter foglalási ideje lejárt visszaigazolás nélkül."
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None


def claim_publication_deliveries(
    db: Session, data: PublicationDeliveryClaimIn
) -> list[PublicationDelivery]:
    adapter_id = data.adapter_id.strip()
    targets = sorted({target.strip().upper() for target in data.targets})
    invalid = [target for target in targets if not TARGET_RE.fullmatch(target)]
    if invalid:
        raise ValueError("Érvénytelen adaptercél: " + ", ".join(invalid))
    now = utcnow()
    _release_expired_claims(db, now)
    rows = list(
        db.scalars(
            select(PublicationDelivery)
            .where(
                PublicationDelivery.target.in_(targets),
                PublicationDelivery.status.in_(("ready", "retry")),
                PublicationDelivery.available_at <= now,
                PublicationDelivery.attempt_count < PublicationDelivery.max_attempts,
            )
            .order_by(PublicationDelivery.created_at, PublicationDelivery.id)
            .limit(data.limit)
            .with_for_update(skip_locked=True)
        ).all()
    )
    for row in rows:
        row.status = "claimed"
        row.claimed_by = adapter_id
        row.claimed_at = now
        row.lease_expires_at = now + timedelta(minutes=data.lease_minutes)
        row.attempt_count += 1
        row.last_error = None
    db.commit()
    return rows


def serialize_delivery(
    row: PublicationDelivery, *, include_payload: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "delivery_id": row.delivery_id,
        "asset_id": row.asset_id,
        "publication_proof_id": row.publication_proof_id,
        "target": row.target,
        "action": row.action,
        "idempotency_key": row.idempotency_key,
        "payload_sha256": row.payload_sha256,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "max_attempts": row.max_attempts,
        "claimed_by": row.claimed_by,
        "lease_expires_at": row.lease_expires_at,
        "external_reference": row.external_reference,
        "last_error": row.last_error,
        "delivered_at": row.delivered_at,
        "created_at": row.created_at,
    }
    if include_payload:
        result["payload"] = json.loads(row.payload_json)
    return result


def record_publication_receipt(
    db: Session,
    delivery_id: str,
    data: PublicationDeliveryReceiptIn,
) -> PublicationDelivery:
    row = db.scalar(
        select(PublicationDelivery).where(PublicationDelivery.delivery_id == delivery_id)
    )
    if not row:
        raise KeyError(delivery_id)
    if data.idempotency_key != row.idempotency_key or data.payload_sha256 != row.payload_sha256:
        raise ValueError("A receipt idempotencia- vagy payload-hash kötése érvénytelen.")
    receipt_json = _canonical_json(data.receipt)
    receipt_sha256 = hashlib.sha256(receipt_json.encode("utf-8")).hexdigest()
    if row.status == "delivered":
        if (
            data.status == "delivered"
            and row.receipt_sha256 == receipt_sha256
            and row.external_reference == data.external_reference
        ):
            return row
        raise ValueError("A már kézbesített publikáció receiptje nem módosítható.")
    if row.status != "claimed" or row.claimed_by != data.adapter_id.strip():
        raise ValueError("A receiptet csak az aktív foglalást birtokló adapter rögzítheti.")
    external_reference = (data.external_reference or "").strip()
    error = (data.error_message or "").strip()
    if data.status == "delivered" and len(external_reference) < 3:
        raise ValueError("Sikeres kézbesítéshez külső referencia kötelező.")
    if data.status == "failed" and len(error) < 10:
        raise ValueError("Sikertelen kézbesítéshez részletes hibaüzenet kötelező.")
    now = utcnow()
    row.receipt_json = receipt_json
    row.receipt_sha256 = receipt_sha256
    row.claimed_by = None
    row.claimed_at = None
    row.lease_expires_at = None
    if data.status == "delivered":
        row.status = "delivered"
        row.external_reference = external_reference
        row.delivered_at = now
        row.last_error = None
    else:
        row.last_error = error
        row.status = "dead_letter" if row.attempt_count >= row.max_attempts else "retry"
        row.available_at = now + timedelta(minutes=2 ** min(row.attempt_count, 8))
    audit(
        db,
        actor=data.adapter_id.strip(),
        action=f"publication_delivery_{row.status}",
        entity_type="publication_delivery",
        entity_id=row.delivery_id,
        after={
            "target": row.target,
            "action": row.action,
            "external_reference": row.external_reference,
            "error": row.last_error,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def retry_publication_delivery(
    db: Session, delivery_id: str, user: object, *, reason: str
) -> PublicationDelivery:
    role, actor = _identity(user)
    if role not in DELIVERY_ROLES:
        raise PermissionError("Publikációs kézbesítés újraindítására nincs jogosultság.")
    if len(reason.strip()) < 10:
        raise ValueError("Az újraindítás részletes indoklása kötelező.")
    row = db.scalar(
        select(PublicationDelivery).where(PublicationDelivery.delivery_id == delivery_id)
    )
    if not row:
        raise KeyError(delivery_id)
    if row.status not in {"retry", "dead_letter"}:
        raise ValueError("Csak hibás vagy holt levél kézbesítés indítható újra.")
    row.status = "ready"
    row.attempt_count = 0
    row.available_at = utcnow()
    row.claimed_by = None
    row.claimed_at = None
    row.lease_expires_at = None
    row.last_error = None
    audit(
        db,
        actor=actor,
        action="publication_delivery_requeued",
        entity_type="publication_delivery",
        entity_id=delivery_id,
        after={"reason": reason.strip()},
    )
    db.commit()
    db.refresh(row)
    return row


def publication_delivery_workspace(db: Session) -> dict[str, Any]:
    rows = db.scalars(
        select(PublicationDelivery)
        .order_by(PublicationDelivery.created_at.desc())
        .limit(500)
    ).all()
    statuses = {status: sum(row.status == status for row in rows) for status in (
        "ready", "claimed", "retry", "delivered", "dead_letter"
    )}
    return {"rows": rows, "statuses": statuses, "total": len(rows)}
