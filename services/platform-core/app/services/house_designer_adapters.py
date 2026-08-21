from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..models import (
    HouseDesignerAdapterJob,
    HouseDesignerAdapterReceipt,
    HouseDesignerAdapterRegistration,
    HouseDesignerEntitlement,
    HouseDesignEstimateSnapshot,
    HouseDesignRenderRevision,
    HouseDesignRevision,
    HouseDesignScheduleSnapshot,
    HouseDesignSession,
)
from .house_designer import ActorScope, HouseDesignerError, decode_revision_site
from .house_designer_geometry import canonical_sha256
from .house_designer_privacy import SitePrivacyError, protect_site, unprotect_site

CONTRACT_VERSION = "house-designer-adapter-v1"
ADAPTER_TYPES = frozenset({"pricing", "capacity", "render"})
AUTHOR_ROLES = frozenset({"designer", "technical-prep", "managing-director", "owner"})
REVIEWER_ROLES = frozenset({"managing-director", "owner"})
MAX_RESPONSE_AGE = timedelta(minutes=5)
MAX_DISPATCH_ATTEMPTS = 5
AdapterTransport = Callable[[str, dict[str, str], bytes, int], tuple[int, dict[str, Any]]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


def register_adapter(
    db: Session,
    *,
    actor_subject_id: str,
    actor_role: str,
    tenant_id: str,
    brand_id: str,
    adapter_type: str,
    provider: str,
    endpoint: str,
    key_id: str,
) -> dict[str, Any]:
    if actor_role not in AUTHOR_ROLES:
        raise HouseDesignerError(
            "adapter_author_forbidden", "Nincs adapter-szerkesztési joga.", status_code=403
        )
    clean_type = adapter_type.strip().lower()
    if clean_type not in ADAPTER_TYPES:
        raise HouseDesignerError("adapter_type_invalid", "Ismeretlen adaptertípus.")
    clean_endpoint = endpoint.strip()
    parsed = urlsplit(clean_endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HouseDesignerError(
            "adapter_endpoint_invalid",
            "Az adapter végpontja hitelesítő adat nélküli publikus HTTPS URL legyen.",
        )
    if parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise HouseDesignerError("adapter_endpoint_local", "Helyi adaptervégpont nem aktiválható.")
    if not provider.strip() or len(provider.strip()) > 120 or not key_id.strip():
        raise HouseDesignerError(
            "adapter_identity_invalid", "Szolgáltató és kulcsazonosító kötelező."
        )
    latest = db.scalar(
        select(func.max(HouseDesignerAdapterRegistration.revision_no)).where(
            HouseDesignerAdapterRegistration.tenant_id == tenant_id,
            HouseDesignerAdapterRegistration.brand_id == brand_id,
            HouseDesignerAdapterRegistration.adapter_type == clean_type,
        )
    )
    row = HouseDesignerAdapterRegistration(
        adapter_id=_id("HDAREG"),
        tenant_id=tenant_id,
        brand_id=brand_id,
        adapter_type=clean_type,
        revision_no=int(latest or 0) + 1,
        provider=provider.strip(),
        endpoint=clean_endpoint,
        key_id=key_id.strip(),
        status="IN_REVIEW",
        authored_by=actor_subject_id,
    )
    db.add(row)
    audit(
        db,
        actor=actor_subject_id,
        action="house_designer.adapter.submit_review",
        entity_type="HouseDesignerAdapterRegistration",
        entity_id=row.adapter_id,
        after=_registration_result(row),
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HouseDesignerError(
            "adapter_revision_conflict",
            "Párhuzamos adapterverzió készült; töltse újra.",
            status_code=409,
        ) from error
    return _registration_result(row)


def review_adapter(
    db: Session,
    *,
    adapter_id: str,
    actor_subject_id: str,
    actor_role: str,
    approve: bool,
) -> dict[str, Any]:
    if actor_role not in REVIEWER_ROLES:
        raise HouseDesignerError(
            "adapter_review_forbidden", "Nincs adapter-jóváhagyási joga.", status_code=403
        )
    row = db.scalar(
        select(HouseDesignerAdapterRegistration)
        .where(HouseDesignerAdapterRegistration.adapter_id == adapter_id)
        .with_for_update()
    )
    if row is None:
        raise HouseDesignerError("adapter_not_found", "Az adapter nem található.", status_code=404)
    if row.status != "IN_REVIEW":
        raise HouseDesignerError(
            "adapter_not_reviewable", "Az adapter nem vár jóváhagyásra.", status_code=409
        )
    if row.authored_by == actor_subject_id:
        raise HouseDesignerError(
            "four_eyes_required", "A szerző nem hagyhatja jóvá a saját adapterét.", status_code=409
        )
    if approve:
        active_rows = db.scalars(
            select(HouseDesignerAdapterRegistration)
            .where(
                HouseDesignerAdapterRegistration.tenant_id == row.tenant_id,
                HouseDesignerAdapterRegistration.brand_id == row.brand_id,
                HouseDesignerAdapterRegistration.adapter_type == row.adapter_type,
                HouseDesignerAdapterRegistration.status == "ACTIVE",
            )
            .with_for_update()
        ).all()
        for active in active_rows:
            active.status = "SUSPENDED"
            active.row_version += 1
        row.status = "ACTIVE"
    else:
        row.status = "REVOKED"
    row.reviewed_by = actor_subject_id
    row.reviewed_at = _now()
    row.row_version += 1
    audit(
        db,
        actor=actor_subject_id,
        action="house_designer.adapter.approve" if approve else "house_designer.adapter.reject",
        entity_type="HouseDesignerAdapterRegistration",
        entity_id=row.adapter_id,
        after=_registration_result(row),
    )
    db.commit()
    return _registration_result(row)


def suspend_adapter(
    db: Session, *, adapter_id: str, actor_subject_id: str, actor_role: str
) -> dict[str, Any]:
    if actor_role not in REVIEWER_ROLES:
        raise HouseDesignerError(
            "adapter_suspend_forbidden", "Nincs adapter-felfüggesztési joga.", status_code=403
        )
    row = db.scalar(
        select(HouseDesignerAdapterRegistration)
        .where(HouseDesignerAdapterRegistration.adapter_id == adapter_id)
        .with_for_update()
    )
    if row is None:
        raise HouseDesignerError("adapter_not_found", "Az adapter nem található.", status_code=404)
    if row.status != "ACTIVE":
        raise HouseDesignerError(
            "adapter_not_active", "Csak aktív adapter függeszthető fel.", status_code=409
        )
    row.status = "SUSPENDED"
    row.row_version += 1
    audit(
        db,
        actor=actor_subject_id,
        action="house_designer.adapter.suspend",
        entity_type="HouseDesignerAdapterRegistration",
        entity_id=row.adapter_id,
    )
    db.commit()
    return _registration_result(row)


def list_adapters(db: Session, *, tenant_id: str, brand_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(HouseDesignerAdapterRegistration)
        .where(
            HouseDesignerAdapterRegistration.tenant_id == tenant_id,
            HouseDesignerAdapterRegistration.brand_id == brand_id,
        )
        .order_by(
            HouseDesignerAdapterRegistration.adapter_type,
            desc(HouseDesignerAdapterRegistration.revision_no),
        )
    ).all()
    return [_registration_result(row) for row in rows]


def list_session_jobs(db: Session, *, session_id: str, actor: ActorScope) -> list[dict[str, Any]]:
    session = db.scalar(
        select(HouseDesignSession).where(
            HouseDesignSession.session_id == session_id,
            HouseDesignSession.tenant_id == actor.tenant_id,
        )
    )
    if (
        session is None
        or session.brand_id not in actor.brand_ids
        or not actor.can_read(session.owner_subject_id, session.project_id)
    ):
        raise HouseDesignerError("session_not_found", "A házterv nem található.", status_code=404)
    rows = db.scalars(
        select(HouseDesignerAdapterJob)
        .where(HouseDesignerAdapterJob.session_id == session_id)
        .order_by(desc(HouseDesignerAdapterJob.created_at))
        .limit(30)
    ).all()
    return [_job_result(row) for row in rows]


def queue_adapter_job(
    db: Session,
    *,
    session_id: str,
    adapter_type: str,
    actor: ActorScope,
    idempotency_key: str,
    prompt: str = "",
) -> dict[str, Any]:
    clean_type = adapter_type.strip().lower()
    if clean_type not in ADAPTER_TYPES:
        raise HouseDesignerError("adapter_type_invalid", "Ismeretlen adaptertípus.")
    if not idempotency_key.strip():
        raise HouseDesignerError("idempotency_key_required", "Műveletazonosító kötelező.")
    replay = db.scalar(
        select(HouseDesignerAdapterJob).where(
            HouseDesignerAdapterJob.tenant_id == actor.tenant_id,
            HouseDesignerAdapterJob.idempotency_key == idempotency_key.strip(),
        )
    )
    if replay:
        if replay.session_id == session_id and replay.adapter_type == clean_type:
            return _job_result(replay)
        raise HouseDesignerError(
            "idempotency_collision", "A kulcs más adapterfeladathoz tartozik.", status_code=409
        )
    session = db.scalar(
        select(HouseDesignSession)
        .where(
            HouseDesignSession.session_id == session_id,
            HouseDesignSession.tenant_id == actor.tenant_id,
        )
        .with_for_update()
    )
    if (
        session is None
        or session.brand_id not in actor.brand_ids
        or not actor.can_read(session.owner_subject_id, session.project_id)
    ):
        raise HouseDesignerError("session_not_found", "A házterv nem található.", status_code=404)
    revision = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == session.current_revision_id
        )
    )
    if revision is None:
        raise HouseDesignerError(
            "current_revision_missing", "Az aktuális tervverzió hiányzik.", status_code=409
        )
    entitlement = _active_entitlement(db, session)
    feature = {
        "pricing": entitlement.production_pricing_enabled,
        "capacity": entitlement.production_capacity_enabled,
        "render": entitlement.production_render_enabled,
    }[clean_type]
    if not settings.house_designer_adapters_enabled or not feature:
        raise HouseDesignerError(
            "production_adapter_disabled",
            "Az éles adapterkapu nincs engedélyezve.",
            status_code=409,
        )
    adapter = db.scalar(
        select(HouseDesignerAdapterRegistration)
        .where(
            HouseDesignerAdapterRegistration.tenant_id == actor.tenant_id,
            HouseDesignerAdapterRegistration.brand_id == session.brand_id,
            HouseDesignerAdapterRegistration.adapter_type == clean_type,
            HouseDesignerAdapterRegistration.status == "ACTIVE",
        )
        .order_by(desc(HouseDesignerAdapterRegistration.revision_no))
    )
    if adapter is None:
        raise HouseDesignerError(
            "active_adapter_missing", "Nincs jóváhagyott aktív adapter.", status_code=409
        )
    configuration = json.loads(revision.configuration_json)
    site = decode_revision_site(revision)
    geometry = json.loads(revision.geometry_json)
    input_payload = {
        "schemaVersion": "house-designer-production-input-v1",
        "sessionId": session_id,
        "designRevisionId": revision.revision_id,
        "designSha256": revision.canonical_sha256,
        "geometry": geometry,
        "configuration": configuration,
        "site": site,
    }
    input_sha = _sha(input_payload)
    request_payload = {
        "contractVersion": CONTRACT_VERSION,
        "adapterType": clean_type,
        "inputSha256": input_sha,
        "input": input_payload,
    }
    if clean_type == "render":
        request_payload["prompt"] = " ".join(prompt.strip().split())[:1000]
        request_payload["geometryLockSha256"] = canonical_sha256(geometry)
    job_id = _id("HDAJOB")
    request_sha256 = _sha(request_payload)
    stored_request = json.loads(_json(request_payload))
    stored_request["input"]["site"] = protect_site(site, job_id)
    job = HouseDesignerAdapterJob(
        job_id=job_id,
        tenant_id=actor.tenant_id,
        brand_id=session.brand_id,
        session_id=session_id,
        design_revision_id=revision.revision_id,
        adapter_id=adapter.adapter_id,
        adapter_type=clean_type,
        idempotency_key=idempotency_key.strip(),
        request_json=_json(stored_request),
        request_sha256=request_sha256,
        status="QUEUED",
        expires_at=_now() + timedelta(hours=2),
        created_by=actor.subject_id,
    )
    db.add(job)
    audit(
        db,
        actor=actor.subject_id,
        action="house_designer.adapter_job.queue",
        entity_type="HouseDesignerAdapterJob",
        entity_id=job.job_id,
        after={
            "adapter_id": adapter.adapter_id,
            "type": clean_type,
            "request_sha256": job.request_sha256,
        },
    )
    db.commit()
    return _job_result(job)


def dispatch_adapter_jobs(
    db: Session,
    *,
    limit: int = 20,
    transport: AdapterTransport | None = None,
) -> dict[str, int]:
    now = _now()
    expired = db.scalars(
        select(HouseDesignerAdapterJob)
        .where(
            HouseDesignerAdapterJob.status.in_(("QUEUED", "DISPATCHED")),
            HouseDesignerAdapterJob.expires_at <= now,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for job in expired:
        job.status = "EXPIRED"
        job.error_code = "job_expired"
        job.error_detail = "Az adapterfeladat kézbesítési vagy válaszadási ideje lejárt."
    rows = db.scalars(
        select(HouseDesignerAdapterJob)
        .where(
            HouseDesignerAdapterJob.status == "QUEUED",
            HouseDesignerAdapterJob.expires_at > now,
            (HouseDesignerAdapterJob.next_attempt_at.is_(None))
            | (HouseDesignerAdapterJob.next_attempt_at <= now),
        )
        .order_by(HouseDesignerAdapterJob.created_at)
        .limit(max(1, min(limit, 100)))
        .with_for_update(skip_locked=True)
    ).all()
    sent = retried = failed = 0
    sender = transport or _https_transport
    for job in rows:
        adapter = db.scalar(
            select(HouseDesignerAdapterRegistration).where(
                HouseDesignerAdapterRegistration.adapter_id == job.adapter_id
            )
        )
        if adapter is None or adapter.status != "ACTIVE":
            _dispatch_failure(
                job, "adapter_not_active", "Az adapter már nem aktív.", now, fatal=True
            )
            failed += 1
            continue
        secret = _secret(job.adapter_type)
        if (
            not settings.house_designer_adapters_enabled
            or len(secret) < 32
            or not settings.house_designer_callback_base_url.startswith("https://")
        ):
            _dispatch_failure(
                job,
                "adapter_runtime_not_configured",
                "A produkciós adapter környezeti konfigurációja hiányos.",
                now,
                fatal=True,
            )
            failed += 1
            continue
        try:
            _require_public_https_endpoint(adapter.endpoint)
            session = db.scalar(
                select(HouseDesignSession).where(HouseDesignSession.session_id == job.session_id)
            )
            if session is None:
                raise HouseDesignerError(
                    "session_not_found", "Az adapterfeladathoz tartozó terv hiányzik."
                )
            _active_entitlement(db, session)
            envelope = {
                "contractVersion": CONTRACT_VERSION,
                "adapterType": job.adapter_type,
                "jobId": job.job_id,
                "requestSha256": job.request_sha256,
                "callbackUrl": (
                    settings.house_designer_callback_base_url
                    + "/api/v1/house-designer/adapter-results"
                ),
                "issuedAt": now.isoformat(),
                "request": _provider_request(job),
            }
            body = _json(envelope).encode("utf-8")
            signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            status_code, response = sender(
                adapter.endpoint,
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-Imperial-Key-Id": adapter.key_id,
                    "X-Imperial-Signature": f"sha256={signature}",
                    "Idempotency-Key": job.job_id,
                },
                body,
                settings.house_designer_adapter_timeout_seconds,
            )
            provider_job_id = str(response.get("providerJobId") or "").strip()
            if status_code != 202 or not provider_job_id:
                raise ValueError("A szolgáltató nem adott 202 + providerJobId nyugtát.")
        except (HouseDesignerError, OSError, ValueError, urllib.error.URLError) as error:
            fatal = isinstance(error, HouseDesignerError) and error.code in {
                "production_entitlement_missing",
                "adapter_endpoint_not_public",
                "adapter_request_decryption_failed",
                "adapter_request_integrity_failed",
            }
            outcome = _dispatch_failure(
                job,
                getattr(error, "code", "adapter_dispatch_failed"),
                str(error),
                now,
                fatal=fatal,
            )
            failed += int(outcome == "FAILED")
            retried += int(outcome == "QUEUED")
            continue
        job.status = "DISPATCHED"
        job.attempt_count += 1
        job.last_attempt_at = now
        job.next_attempt_at = None
        job.dispatched_at = now
        job.provider_job_id = provider_job_id
        job.error_code = None
        job.error_detail = None
        sent += 1
        audit(
            db,
            actor="house-designer-adapter-worker",
            action="house_designer.adapter_job.dispatch",
            entity_type="HouseDesignerAdapterJob",
            entity_id=job.job_id,
            after={
                "adapter_id": adapter.adapter_id,
                "provider_job_id": provider_job_id,
                "attempt_count": job.attempt_count,
            },
        )
    db.commit()
    return {
        "processed": len(rows) + len(expired),
        "dispatched": sent,
        "retried": retried,
        "failed": failed,
        "expired": len(expired),
    }


def accept_signed_result(
    db: Session, *, payload: dict[str, Any], key_id: str, signature: str
) -> dict[str, Any]:
    body = _json(payload).encode("utf-8")
    job_id = str(payload.get("jobId") or "")
    job = db.scalar(
        select(HouseDesignerAdapterJob)
        .where(HouseDesignerAdapterJob.job_id == job_id)
        .with_for_update()
    )
    if job is None:
        raise HouseDesignerError(
            "adapter_job_not_found", "Az adapterfeladat nem található.", status_code=404
        )
    adapter = db.scalar(
        select(HouseDesignerAdapterRegistration)
        .where(HouseDesignerAdapterRegistration.adapter_id == job.adapter_id)
        .with_for_update()
    )
    if adapter is None or adapter.status != "ACTIVE":
        raise HouseDesignerError("adapter_not_active", "Az adapter már nem aktív.", status_code=409)
    if key_id != adapter.key_id:
        raise HouseDesignerError("adapter_key_mismatch", "Ismeretlen aláírókulcs.", status_code=401)
    secret = _secret(job.adapter_type)
    if not settings.house_designer_adapters_enabled or len(secret) < 32:
        raise HouseDesignerError(
            "adapter_secret_unavailable",
            "Az adapter hitelesítése nincs konfigurálva.",
            status_code=503,
        )
    supplied = signature.removeprefix("sha256=").lower()
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if len(supplied) != 64 or not hmac.compare_digest(expected, supplied):
        raise HouseDesignerError(
            "adapter_signature_invalid", "Érvénytelen adapter-aláírás.", status_code=401
        )
    response_sha = hashlib.sha256(body).hexdigest()
    replay = db.scalar(
        select(HouseDesignerAdapterReceipt).where(
            HouseDesignerAdapterReceipt.job_id == job.job_id,
            HouseDesignerAdapterReceipt.response_sha256 == response_sha,
        )
    )
    if replay:
        return {"job": _job_result(job), "receiptId": replay.receipt_id, "replayed": True}
    issued_at = _parse_datetime(payload.get("issuedAt"))
    provider_job_id = str(payload.get("providerJobId") or "").strip()
    violations: list[str] = []
    if payload.get("contractVersion") != CONTRACT_VERSION:
        violations.append("contract_version")
    if payload.get("adapterType") != job.adapter_type:
        violations.append("adapter_type")
    if payload.get("requestSha256") != job.request_sha256:
        violations.append("request_binding")
    if not provider_job_id:
        violations.append("provider_job_id")
    now = _now()
    if issued_at is None or abs(now - issued_at) > MAX_RESPONSE_AGE:
        violations.append("response_age")
    if _aware(job.expires_at) < now:
        violations.append("job_expired")
    if payload.get("status") != "SUCCEEDED" or not isinstance(payload.get("result"), dict):
        violations.append("provider_result")
    if violations:
        return _reject_signed_result(
            db,
            job,
            adapter,
            payload,
            key_id,
            response_sha,
            issued_at or now,
            provider_job_id or f"missing:{job.job_id}",
            ",".join(violations),
        )
    # A missing ``issuedAt`` always appends the ``response_age`` violation above and
    # returns through the gate before this point, so the timestamp is present here.
    accepted_issued_at = issued_at or now
    if job.status != "DISPATCHED":
        violations.append("job_not_dispatched")
    if job.provider_job_id and job.provider_job_id != provider_job_id:
        violations.append("provider_job_binding")
    if violations:
        return _reject_signed_result(
            db,
            job,
            adapter,
            payload,
            key_id,
            response_sha,
            accepted_issued_at,
            provider_job_id,
            ",".join(violations),
        )
    try:
        result_object_id = _materialize_result(db, job, adapter, payload["result"], provider_job_id)
    except (HouseDesignerError, InvalidOperation, KeyError, TypeError, ValueError) as error:
        code = error.code if isinstance(error, HouseDesignerError) else "result_schema_invalid"
        return _reject_signed_result(
            db,
            job,
            adapter,
            payload,
            key_id,
            response_sha,
            accepted_issued_at,
            provider_job_id,
            code,
        )
    receipt = HouseDesignerAdapterReceipt(
        receipt_id=_id("HDAREC"),
        job_id=job.job_id,
        adapter_id=adapter.adapter_id,
        provider_job_id=provider_job_id,
        key_id=key_id,
        request_sha256=job.request_sha256,
        response_sha256=response_sha,
        issued_at=accepted_issued_at,
        status="ACCEPTED",
        evidence_json=_json(payload),
    )
    db.add(receipt)
    job.status = "SUCCEEDED"
    job.provider_job_id = provider_job_id
    job.result_object_id = result_object_id
    adapter.health_status = "HEALTHY"
    adapter.last_health_at = now
    audit(
        db,
        actor=f"adapter:{adapter.key_id}",
        action="house_designer.adapter_result.accept",
        entity_type="HouseDesignerAdapterReceipt",
        entity_id=receipt.receipt_id,
        after={"job_id": job.job_id, "result_object_id": result_object_id},
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        existing = db.scalar(
            select(HouseDesignerAdapterReceipt).where(
                HouseDesignerAdapterReceipt.adapter_id == adapter.adapter_id,
                HouseDesignerAdapterReceipt.provider_job_id == provider_job_id,
            )
        )
        if existing and existing.job_id == job.job_id and existing.response_sha256 == response_sha:
            return {"job": _job_result(job), "receiptId": existing.receipt_id, "replayed": True}
        raise HouseDesignerError(
            "provider_job_collision", "A szolgáltatói azonosító már foglalt.", status_code=409
        ) from error
    return {"job": _job_result(job), "receiptId": receipt.receipt_id, "replayed": False}


def _materialize_result(
    db: Session,
    job: HouseDesignerAdapterJob,
    adapter: HouseDesignerAdapterRegistration,
    result: dict[str, Any],
    provider_job_id: str,
) -> str:
    request = json.loads(job.request_json)
    input_sha = str(request["inputSha256"])
    if result.get("inputSha256") != input_sha:
        raise HouseDesignerError(
            "result_input_mismatch", "A válasz más bemenethez tartozik.", status_code=409
        )
    valid_until = _parse_datetime(result.get("validUntil"))
    if job.adapter_type in {"pricing", "capacity"} and (
        valid_until is None or valid_until <= _now()
    ):
        raise HouseDesignerError(
            "result_validity_invalid", "A szolgáltatói eredmény már lejárt.", status_code=409
        )
    if job.adapter_type == "pricing":
        net_min = Decimal(str(result["netMinHuf"]))
        net_max = Decimal(str(result["netMaxHuf"]))
        vat = Decimal(str(result["vatRate"]))
        if net_min <= 0 or net_max < net_min or vat < 0 or vat > 1:
            raise ValueError("invalid pricing bounds")
        pricing_canonical = {
            "inputSha256": input_sha,
            "netMinHuf": str(net_min),
            "netMaxHuf": str(net_max),
            "vatRate": str(vat),
            "lineItems": _list(result, "lineItems"),
            "assumptions": _list(result, "assumptions"),
            "exclusions": _list(result, "exclusions"),
        }
        estimate_row = HouseDesignEstimateSnapshot(
            estimate_id=_id("HDE"),
            session_id=job.session_id,
            design_revision_id=job.design_revision_id,
            input_sha256=input_sha,
            net_min_huf=net_min,
            net_max_huf=net_max,
            vat_rate=vat,
            gross_min_huf=net_min * (Decimal("1") + vat),
            gross_max_huf=net_max * (Decimal("1") + vat),
            line_items_json=_json(pricing_canonical["lineItems"]),
            assumptions_json=_json(pricing_canonical["assumptions"]),
            exclusions_json=_json(pricing_canonical["exclusions"]),
            provider=adapter.provider,
            non_production=False,
            valid_until=valid_until,
            canonical_sha256=_sha(pricing_canonical),
            created_by=f"adapter:{adapter.key_id}",
        )
        db.add(estimate_row)
        return estimate_row.estimate_id
    if job.adapter_type == "capacity":
        minimum = int(result["durationMinWorkdays"])
        maximum = int(result["durationMaxWorkdays"])
        if minimum <= 0 or maximum < minimum:
            raise ValueError("invalid duration bounds")
        earliest = _parse_date(result.get("earliestStart"))
        latest = _parse_date(result.get("latestStart"))
        if earliest and latest and latest < earliest:
            raise ValueError("invalid start window")
        schedule_canonical = {
            "inputSha256": input_sha,
            "earliestStart": str(earliest or ""),
            "latestStart": str(latest or ""),
            "durationMinWorkdays": minimum,
            "durationMaxWorkdays": maximum,
            "phases": _list(result, "phases"),
            "assumptions": _list(result, "assumptions"),
        }
        schedule_row = HouseDesignScheduleSnapshot(
            schedule_id=_id("HDT"),
            session_id=job.session_id,
            design_revision_id=job.design_revision_id,
            input_sha256=input_sha,
            earliest_start=earliest,
            latest_start=latest,
            duration_min_workdays=minimum,
            duration_max_workdays=maximum,
            phases_json=_json(schedule_canonical["phases"]),
            assumptions_json=_json(schedule_canonical["assumptions"]),
            capacity_snapshot_id=str(result.get("capacitySnapshotId") or "") or None,
            provider=adapter.provider,
            non_production=False,
            valid_until=valid_until,
            canonical_sha256=_sha(schedule_canonical),
            created_by=f"adapter:{adapter.key_id}",
        )
        db.add(schedule_row)
        return schedule_row.schedule_id
    asset_ref = str(result.get("assetRef") or "")
    asset_sha = str(result.get("assetSha256") or "")
    geometry_lock = str(result.get("geometryLockSha256") or "")
    expected_lock = str(request.get("geometryLockSha256") or "")
    if urlsplit(asset_ref).scheme not in {"https", "s3"} or len(asset_sha) != 64:
        raise ValueError("invalid render asset")
    if geometry_lock != expected_lock:
        raise HouseDesignerError(
            "render_geometry_mismatch", "A render geometriája eltér.", status_code=409
        )
    revision_no = (
        int(
            db.scalar(
                select(func.max(HouseDesignRenderRevision.revision_no)).where(
                    HouseDesignRenderRevision.session_id == job.session_id
                )
            )
            or 0
        )
        + 1
    )
    parent = db.scalar(
        select(HouseDesignRenderRevision)
        .where(HouseDesignRenderRevision.session_id == job.session_id)
        .order_by(desc(HouseDesignRenderRevision.revision_no))
    )
    render_row = HouseDesignRenderRevision(
        render_id=_id("HDV"),
        session_id=job.session_id,
        design_revision_id=job.design_revision_id,
        revision_no=revision_no,
        parent_render_id=parent.render_id if parent else None,
        geometry_lock_sha256=geometry_lock,
        prompt=str(request.get("prompt") or ""),
        provider=adapter.provider,
        provider_job_id=provider_job_id,
        asset_ref=asset_ref,
        asset_sha256=asset_sha,
        qa_json=_json(result.get("qa") or {}),
        status="completed",
        non_production=False,
        created_by=f"adapter:{adapter.key_id}",
    )
    db.add(render_row)
    return render_row.render_id


def _provider_request(job: HouseDesignerAdapterJob) -> dict[str, Any]:
    request = json.loads(job.request_json)
    try:
        stored_site = request["input"]["site"]
        if not isinstance(stored_site, dict):
            raise ValueError("stored site is not an object")
        request["input"]["site"] = unprotect_site(stored_site, job.job_id)
    except (KeyError, TypeError, ValueError, SitePrivacyError) as error:
        raise HouseDesignerError(
            "adapter_request_decryption_failed",
            "Az adapterfeladat védett telekadata nem olvasható.",
            status_code=409,
        ) from error
    if _sha(request) != job.request_sha256:
        raise HouseDesignerError(
            "adapter_request_integrity_failed",
            "Az adapterfeladat bemeneti integritásellenőrzése sikertelen.",
            status_code=409,
        )
    return request


def _reject_signed_result(
    db: Session,
    job: HouseDesignerAdapterJob,
    adapter: HouseDesignerAdapterRegistration,
    payload: dict[str, Any],
    key_id: str,
    response_sha: str,
    issued_at: datetime,
    provider_job_id: str,
    code: str,
) -> dict[str, Any]:
    receipt = HouseDesignerAdapterReceipt(
        receipt_id=_id("HDAREC"),
        job_id=job.job_id,
        adapter_id=adapter.adapter_id,
        provider_job_id=provider_job_id,
        key_id=key_id,
        request_sha256=job.request_sha256,
        response_sha256=response_sha,
        issued_at=issued_at,
        status="REJECTED",
        rejection_code=code,
        evidence_json=_json(payload),
    )
    db.add(receipt)
    job.status = "FAILED"
    job.error_code = code
    adapter.health_status = "FAILED"
    adapter.last_health_at = _now()
    audit(
        db,
        actor=f"adapter:{key_id}",
        action="house_designer.adapter_result.reject",
        entity_type="HouseDesignerAdapterReceipt",
        entity_id=receipt.receipt_id,
        after={"job_id": job.job_id, "code": code},
    )
    db.commit()
    return {"job": _job_result(job), "receiptId": receipt.receipt_id, "replayed": False}


def _active_entitlement(db: Session, session: HouseDesignSession) -> HouseDesignerEntitlement:
    now = _now()
    row = db.scalar(
        select(HouseDesignerEntitlement).where(
            HouseDesignerEntitlement.tenant_id == session.tenant_id,
            HouseDesignerEntitlement.brand_id == session.brand_id,
            HouseDesignerEntitlement.status == "active",
            HouseDesignerEntitlement.valid_from <= now,
        )
    )
    if row is None or (row.valid_until and _aware(row.valid_until) <= now):
        raise HouseDesignerError(
            "production_entitlement_missing", "Nincs aktív éles jogosultság.", status_code=409
        )
    return row


def _secret(adapter_type: str) -> str:
    return {
        "pricing": settings.house_designer_pricing_hmac_secret,
        "capacity": settings.house_designer_capacity_hmac_secret,
        "render": settings.house_designer_render_hmac_secret,
    }[adapter_type]


def _registration_result(row: HouseDesignerAdapterRegistration) -> dict[str, Any]:
    return {
        "adapterId": row.adapter_id,
        "adapterType": row.adapter_type,
        "revisionNo": row.revision_no,
        "provider": row.provider,
        "endpoint": row.endpoint,
        "keyId": row.key_id,
        "contractVersion": row.contract_version,
        "status": row.status,
        "healthStatus": row.health_status,
        "lastHealthAt": row.last_health_at,
        "authoredBy": row.authored_by,
        "reviewedBy": row.reviewed_by,
        "rowVersion": row.row_version,
    }


def _job_result(row: HouseDesignerAdapterJob) -> dict[str, Any]:
    return {
        "jobId": row.job_id,
        "adapterId": row.adapter_id,
        "adapterType": row.adapter_type,
        "sessionId": row.session_id,
        "designRevisionId": row.design_revision_id,
        "requestSha256": row.request_sha256,
        "status": row.status,
        "attemptCount": row.attempt_count,
        "nextAttemptAt": row.next_attempt_at,
        "dispatchedAt": row.dispatched_at,
        "providerJobId": row.provider_job_id,
        "resultObjectId": row.result_object_id,
        "errorCode": row.error_code,
        "expiresAt": row.expires_at,
    }


def _dispatch_failure(
    job: HouseDesignerAdapterJob,
    code: str,
    detail: str,
    now: datetime,
    *,
    fatal: bool,
) -> str:
    job.attempt_count += 1
    job.last_attempt_at = now
    job.error_code = code[:120]
    job.error_detail = detail[:2000]
    if fatal or job.attempt_count >= MAX_DISPATCH_ATTEMPTS:
        job.status = "FAILED"
        job.next_attempt_at = None
    else:
        job.status = "QUEUED"
        job.next_attempt_at = now + timedelta(minutes=2 ** min(job.attempt_count, 6))
    return job.status


def _require_public_https_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HouseDesignerError(
            "adapter_endpoint_not_public",
            "Az adapter végpontja nem publikus HTTPS cím.",
            status_code=409,
        )
    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(
                parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
            )
        }
    except socket.gaierror as error:
        raise OSError("Az adapter DNS-címe nem oldható fel.") from error
    if not addresses:
        raise OSError("Az adapter DNS-címe nem adott címet.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise HouseDesignerError(
                "adapter_endpoint_not_public",
                "Az adapter DNS-címe privát vagy fenntartott hálózatra mutat.",
                status_code=409,
            )


def _https_transport(
    endpoint: str, headers: dict[str, str], body: bytes, timeout_seconds: int
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()), _NoRedirect()
    )
    with opener.open(request, timeout=timeout_seconds) as response:
        response_body = response.read(64 * 1024 + 1)
        if len(response_body) > 64 * 1024:
            raise ValueError("A szolgáltatói nyugta túl nagy.")
        parsed = json.loads(response_body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("A szolgáltatói nyugta nem JSON objektum.")
        return int(response.status), parsed


def _list(value: dict[str, Any], key: str) -> list[Any]:
    item = value.get(key, [])
    if not isinstance(item, list):
        raise ValueError(f"{key} must be a list")
    return item


def _parse_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _aware(parsed)


def _parse_date(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    return date.fromisoformat(str(value))


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"
