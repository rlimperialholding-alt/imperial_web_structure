from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..models import TaskRecord
from .adapters import (
    AdapterError,
    AdapterResult,
    ProductionHttpClient,
    build_adapter,
    canonical_json,
    sha,
)
from .http import redact
from .models import (
    PublicationProofRecord,
    PublishingChannelState,
    PublishingEventRecord,
    PublishingExceptionRecord,
    PublishingJobRecord,
    PublishingWorkerHeartbeat,
)
from .registry import PublishingRegistry, RegistryError, writes_unlocked
from .schemas import (
    MANDATORY_GATES,
    OWNER_AUTO_PUBLICATION_POLICY_ID,
    PublicationJobIn,
    PublicationJobReceipt,
)

WEB_CHANNELS = ("nim_cms", "wordpress")
SOCIAL_CHANNELS = ("facebook", "instagram")
ATTRIBUTION_CHANNELS = ("analytics", "crm")
QUALITY_GATE_VERSION = "canonical-auto-quality-v2"
QUALITY_RELEASE_SECRET_FILE = Path("/run/secrets/platform_release_hmac_key")

EVENT_TYPES = {
    "PUBLICATION_JOB_QUEUED",
    "PUBLICATION_PREFLIGHT_PASSED",
    "PUBLICATION_PREFLIGHT_BLOCKED",
    "CHANNEL_DRAFT_CREATED",
    "CHANNEL_PUBLISH_STARTED",
    "CHANNEL_PUBLISHED",
    "CHANNEL_READBACK_VERIFIED",
    "CHANNEL_PUBLICATION_FAILED",
    "PUBLICATION_EXCEPTION_CREATED",
    "PUBLICATION_ROLLBACK_STARTED",
    "PUBLICATION_ROLLED_BACK",
    "CHANNEL_ROLLBACK_FAILED",
    "FORUM_SIGNAL_CAPTURED",
    "FORUM_POLICY_VERIFIED",
    "FORUM_ANSWER_DRAFTED",
    "FORUM_ANSWER_PUBLISHED",
    "FORUM_ANSWER_BLOCKED",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _trip_runtime_kill_switch() -> bool:
    try:
        Path("/app/runtime/publishing-kill-switch").write_text("KILLED\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _job_key(job: PublicationJobIn) -> str:
    raw = f"{job.brand_id}|{job.content_asset_id}|{job.content_version_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _channel_key(job: PublicationJobIn, channel: str) -> str:
    raw = f"{job.brand_id}|{job.content_asset_id}|{job.content_version_id}|{channel}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _automated_release_token_errors(job: PublicationJobIn) -> list[str]:
    try:
        token = json.loads(job.release_token)
        if not isinstance(token, dict):
            return ["automated_release_token_not_object"]
    except json.JSONDecodeError:
        return ["automated_release_token_not_json"]
    try:
        secret = QUALITY_RELEASE_SECRET_FILE.read_text(encoding="utf-8").strip().encode()
    except OSError:
        return ["automated_release_secret_missing"]
    if len(secret) < 32:
        return ["automated_release_secret_invalid"]
    signature = str(token.get("hmac_sha256") or "")
    unsigned = {key: value for key, value in token.items() if key != "hmac_sha256"}
    expected = hmac.new(
        secret,
        canonical_json(unsigned).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    errors: list[str] = []
    if not hmac.compare_digest(signature, expected):
        errors.append("automated_release_hmac_invalid")
    expected_bindings = {
        "schema": QUALITY_GATE_VERSION,
        "brand_id": job.brand_id,
        "content_asset_id": job.content_asset_id,
        "content_version_id": job.content_version_id,
        "content_hash": job.content_hash,
        "channels": list(job.channels),
    }
    for key, value in expected_bindings.items():
        if token.get(key) != value:
            errors.append(f"automated_release_binding_mismatch:{key}")
    if not str(token.get("quality_manifest_sha256") or ""):
        errors.append("automated_release_quality_manifest_missing")
    try:
        expires_at = datetime.fromisoformat(str(token.get("expires_at") or ""))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= utcnow():
            errors.append("automated_release_token_expired")
    except ValueError:
        errors.append("automated_release_expiry_invalid")
    return errors


def emit_event(
    db: Session,
    job: PublishingJobRecord,
    event_type: str,
    *,
    channel: str | None = None,
    external_id: str | None = None,
    payload: dict[str, Any] | None = None,
    discriminator: str = "",
) -> PublishingEventRecord:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown publication event: {event_type}")
    dedupe_key = sha(
        {
            "event_type": event_type,
            "job_id": job.job_id,
            "channel": channel,
            "external_id": external_id,
            "discriminator": discriminator,
        }
    )
    existing = db.scalar(
        select(PublishingEventRecord).where(PublishingEventRecord.dedupe_key == dedupe_key)
    )
    if existing:
        return existing
    row = PublishingEventRecord(
        event_id=f"PUBEV-{uuid4().hex[:20].upper()}",
        dedupe_key=dedupe_key,
        event_type=event_type,
        job_id=job.job_id,
        content_asset_id=job.content_asset_id,
        brand_id=job.brand_id,
        channel=channel,
        external_id=external_id,
        payload_json=canonical_json(redact(payload or {})),
        occurred_at=utcnow(),
    )
    db.add(row)
    return row


def preflight_errors(job: PublicationJobIn, registry: PublishingRegistry) -> list[str]:
    errors: list[str] = []
    now = utcnow()
    by_gate = {gate.gate: gate for gate in job.gate_results}
    owner_policy_gate = by_gate.get("owner_auto_publication_policy")
    owner_policy_channels = all(
        job.channel_payloads.get(channel, {}).get("owner_policy_release_id")
        == OWNER_AUTO_PUBLICATION_POLICY_ID
        for channel in job.channels
    )
    owner_policy_active = bool(
        owner_policy_gate
        and owner_policy_gate.decision == "PASS"
        and owner_policy_gate.evidence_id == OWNER_AUTO_PUBLICATION_POLICY_ID
        and owner_policy_channels
    )
    if not owner_policy_active:
        missing = sorted(MANDATORY_GATES - set(by_gate))
        errors.extend(f"missing_gate:{gate}" for gate in missing)
    for gate in job.gate_results:
        checked = gate.checked_at if gate.checked_at.tzinfo else gate.checked_at.replace(tzinfo=UTC)
        valid = (
            gate.valid_until if gate.valid_until.tzinfo else gate.valid_until.replace(tzinfo=UTC)
        )
        if checked > now:
            errors.append(f"future_gate:{gate.gate}")
        if valid <= now:
            errors.append(f"expired_gate:{gate.gate}")
        if gate.decision != "PASS":
            errors.append(f"gate_{gate.decision.lower()}:{gate.gate}")
    if job.idempotency_key != _job_key(job):
        errors.append("invalid_job_idempotency_key")
    if hashlib.sha256(job.release_token.encode()).hexdigest() != job.release_token_hash:
        errors.append("release_token_hash_mismatch")
    if by_gate.get("automated_content_quality"):
        errors.extend(_automated_release_token_errors(job))
    try:
        for channel in job.channels:
            binding = registry.binding(job.brand_id, channel)
            if channel in WEB_CHANNELS and binding.cms_route != job.cms_route:
                errors.append("cms_route_binding_mismatch")
    except RegistryError as exc:
        errors.append(f"registry:{exc}")
    if not writes_unlocked():
        errors.append("kill_switch_active")
    return sorted(set(errors))


def create_exception(
    db: Session,
    job: PublishingJobRecord,
    *,
    severity: str,
    error_type: str,
    channel: str | None,
    response: Any,
    recommended_action: str,
    proof_id: str | None = None,
    rollback_status: str | None = None,
) -> PublishingExceptionRecord:
    exception_id = f"PUBEX-{uuid4().hex[:20].upper()}"
    due_at = utcnow() + timedelta(hours=24)
    state = (
        db.scalar(
            select(PublishingChannelState).where(
                PublishingChannelState.job_id == job.job_id,
                PublishingChannelState.channel == channel,
            )
        )
        if channel
        else None
    )
    row = PublishingExceptionRecord(
        exception_id=exception_id,
        job_id=job.job_id,
        brand_id=job.brand_id,
        content_asset_id=job.content_asset_id,
        content_version_id=job.content_version_id,
        channel=channel,
        severity=severity,
        error_type=error_type,
        last_successful_step=job.last_successful_step,
        redacted_response_json=canonical_json(redact(response)),
        admin_url=state.admin_url if state else None,
        public_url=state.public_url if state else None,
        publication_proof_id=proof_id,
        rollback_status=rollback_status,
        recommended_action=recommended_action,
        owner="Molnár Andrea",
        due_at=due_at,
    )
    db.add(row)
    event = emit_event(
        db,
        job,
        "PUBLICATION_EXCEPTION_CREATED",
        channel=channel,
        payload={"exception_id": exception_id, "severity": severity, "error_type": error_type},
        discriminator=exception_id,
    )
    db.add(
        TaskRecord(
            task_id=f"TASK-{uuid4().hex[:12].upper()}",
            project_id="IMPERIAL-PUBLISHING",
            source_event_id=event.event_id,
            title=f"Publishing exception: {error_type}",
            description=f"{exception_id} / {job.job_id}. {recommended_action}",
            assignee="Molnár Andrea",
            due_at=due_at,
            priority="critical" if severity in {"BLOCKER", "CRITICAL"} else "high",
            executive_relevance=severity in {"BLOCKER", "CRITICAL"},
        )
    )
    return row


def submit_job(db: Session, job: PublicationJobIn) -> PublicationJobReceipt:
    payload_json = canonical_json(job.model_dump(mode="json"))
    payload_sha256 = hashlib.sha256(payload_json.encode()).hexdigest()
    existing = db.scalar(
        select(PublishingJobRecord).where(PublishingJobRecord.job_id == job.job_id)
    )
    if not existing:
        existing = db.scalar(
            select(PublishingJobRecord).where(
                PublishingJobRecord.idempotency_key == job.idempotency_key
            )
        )
    if existing:
        if existing.payload_sha256 != payload_sha256:
            raise ValueError("Idempotency conflict: existing job payload differs")
        return PublicationJobReceipt(
            job_id=existing.job_id,
            status=existing.status,
            idempotent=True,
            payload_sha256=existing.payload_sha256,
        )
    desired = job.desired_publish_at
    if desired and not desired.tzinfo:
        desired = desired.replace(tzinfo=UTC)
    row = PublishingJobRecord(
        job_id=job.job_id,
        content_asset_id=job.content_asset_id,
        content_version_id=job.content_version_id,
        brand_id=job.brand_id,
        cms_route=job.cms_route,
        idempotency_key=job.idempotency_key,
        correlation_id=job.correlation_id,
        payload_json=payload_json,
        payload_sha256=payload_sha256,
        desired_publish_at=desired,
        available_at=max(utcnow(), desired) if desired else utcnow(),
        status="QUEUED",
    )
    db.add(row)
    db.flush()
    try:
        registry = PublishingRegistry.load()
        errors = preflight_errors(job, registry)
    except RegistryError as exc:
        errors = [f"registry:{exc}"]
    if errors:
        row.status = "BLOCKED"
        row.last_error = ";".join(errors)
        emit_event(db, row, "PUBLICATION_PREFLIGHT_BLOCKED", payload={"errors": errors})
        create_exception(
            db,
            row,
            severity="BLOCKER",
            error_type="PREFLIGHT_BLOCKED",
            channel=None,
            response={"errors": errors},
            recommended_action=(
                "Javítsd a felsorolt kapu-, routing- vagy adapterhibát, majd indíts újragate-elést."
            ),
        )
    else:
        for channel in job.channels:
            db.add(
                PublishingChannelState(
                    channel_state_id=f"PUBCH-{uuid4().hex[:20].upper()}",
                    job_id=job.job_id,
                    brand_id=job.brand_id,
                    content_asset_id=job.content_asset_id,
                    content_version_id=job.content_version_id,
                    channel=channel,
                    idempotency_key=_channel_key(job, channel),
                    status="DRAFT_ONLY" if channel == "forum" else "QUEUED",
                    content_hash=job.content_hash,
                    canonical_url=job.canonical_url,
                )
            )
        emit_event(db, row, "PUBLICATION_JOB_QUEUED")
        emit_event(db, row, "PUBLICATION_PREFLIGHT_PASSED")
    audit(
        db,
        actor="content-factory",
        action="autonomous_publication_job_submitted",
        entity_type="publishing_job",
        entity_id=row.job_id,
        after={"status": row.status, "payload_sha256": payload_sha256, "channels": job.channels},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Concurrent idempotency conflict") from exc
    return PublicationJobReceipt(
        job_id=row.job_id, status=row.status, idempotent=False, payload_sha256=payload_sha256
    )


def heartbeat(
    db: Session, *, status: str, current_job_id: str | None = None, detail: dict | None = None
) -> None:
    worker_id = settings.autonomous_publishing_worker_id
    row = db.get(PublishingWorkerHeartbeat, worker_id)
    if not row:
        row = PublishingWorkerHeartbeat(worker_id=worker_id)
        db.add(row)
    row.status = status
    row.current_job_id = current_job_id
    row.detail_json = canonical_json(detail or {})
    row.heartbeat_at = utcnow()
    db.commit()


def _release_expired_leases(db: Session) -> None:
    now = utcnow()
    rows = db.scalars(
        select(PublishingJobRecord).where(
            PublishingJobRecord.status == "RUNNING",
            PublishingJobRecord.lease_expires_at.is_not(None),
            PublishingJobRecord.lease_expires_at <= now,
        )
    ).all()
    for row in rows:
        row.status = "FAILED" if row.attempt_count >= row.max_attempts else "QUEUED"
        row.available_at = now
        row.last_error = "worker lease expired"
        row.claimed_by = None
        row.claimed_at = None
        row.lease_expires_at = None


def claim_job(db: Session) -> PublishingJobRecord | None:
    _release_expired_leases(db)
    now = utcnow()
    row = db.scalar(
        select(PublishingJobRecord)
        .where(
            PublishingJobRecord.status == "QUEUED",
            PublishingJobRecord.available_at <= now,
            PublishingJobRecord.attempt_count < PublishingJobRecord.max_attempts,
        )
        .order_by(PublishingJobRecord.available_at, PublishingJobRecord.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if not row:
        db.commit()
        return None
    row.status = "RUNNING"
    row.claimed_by = settings.autonomous_publishing_worker_id
    row.claimed_at = now
    row.lease_expires_at = now + timedelta(seconds=settings.autonomous_publishing_lease_seconds)
    row.attempt_count += 1
    row.last_error = None
    db.commit()
    return row


def _proof(
    db: Session, job_row: PublishingJobRecord, state: PublishingChannelState, result: AdapterResult
) -> PublicationProofRecord:
    readback_json = canonical_json(redact(result.readback))
    existing = db.scalar(
        select(PublicationProofRecord).where(
            PublicationProofRecord.channel_state_id == state.channel_state_id
        )
    )
    if existing:
        existing.external_id = result.external_id
        existing.public_url = result.public_url
        existing.content_hash = result.content_hash
        existing.canonical_url = result.canonical_url
        existing.readback_json = readback_json
        existing.readback_sha256 = hashlib.sha256(readback_json.encode()).hexdigest()
        existing.analytics_event_id = (
            result.external_id if state.channel == "analytics" else None
        )
        existing.crm_event_id = result.external_id if state.channel == "crm" else None
        existing.verified_at = utcnow()
        return existing
    row = PublicationProofRecord(
        proof_id=f"PUBPROOF-{uuid4().hex[:20].upper()}",
        job_id=job_row.job_id,
        channel_state_id=state.channel_state_id,
        brand_id=job_row.brand_id,
        channel=state.channel,
        external_id=result.external_id,
        public_url=result.public_url,
        content_asset_id=job_row.content_asset_id,
        content_version_id=job_row.content_version_id,
        content_hash=result.content_hash,
        canonical_url=result.canonical_url,
        readback_json=readback_json,
        readback_sha256=hashlib.sha256(readback_json.encode()).hexdigest(),
        analytics_event_id=result.external_id if state.channel == "analytics" else None,
        crm_event_id=result.external_id if state.channel == "crm" else None,
        verified_at=utcnow(),
    )
    db.add(row)
    return row


def process_job(db: Session, job_row: PublishingJobRecord) -> dict[str, Any]:
    job = PublicationJobIn.model_validate_json(job_row.payload_json)
    registry = PublishingRegistry.load()
    errors = preflight_errors(job, registry)
    if errors:
        job_row.status = "BLOCKED"
        job_row.last_error = ";".join(errors)
        emit_event(
            db,
            job_row,
            "PUBLICATION_PREFLIGHT_BLOCKED",
            payload={"errors": errors},
            discriminator=str(job_row.attempt_count),
        )
        create_exception(
            db,
            job_row,
            severity="BLOCKER",
            error_type="PREFLIGHT_RECHECK_BLOCKED",
            channel=None,
            response={"errors": errors},
            recommended_action=(
                "A runtime preflight megváltozott; javítsd a routingot vagy gate-et és regate-elj."
            ),
        )
        db.commit()
        return {"status": "BLOCKED", "job_id": job_row.job_id}
    states = {
        row.channel: row
        for row in db.scalars(
            select(PublishingChannelState).where(PublishingChannelState.job_id == job_row.job_id)
        ).all()
    }
    ordered = [channel for channel in WEB_CHANNELS if channel in states]
    ordered += [channel for channel in SOCIAL_CHANNELS if channel in states]
    ordered += [channel for channel in ATTRIBUTION_CHANNELS if channel in states]
    ordered += [channel for channel in job.channels if channel not in ordered]
    completed: list[tuple[str, AdapterResult]] = []
    client = ProductionHttpClient(
        timeout_seconds=settings.autonomous_publishing_http_timeout_seconds
    )
    try:
        for channel in ordered:
            state = states[channel]
            if state.status == "READBACK_VERIFIED":
                ProductionHttpClient.metrics["duplicate_suppression"] += 1
                continue
            if channel == "forum":
                state.status = "DRAFT_ONLY"
                emit_event(db, job_row, "FORUM_ANSWER_DRAFTED", channel=channel)
                db.commit()
                continue
            if channel in SOCIAL_CHANNELS:
                web_state = next((states[name] for name in WEB_CHANNELS if name in states), None)
                if web_state:
                    if web_state.status != "READBACK_VERIFIED" or not web_state.public_url:
                        raise AdapterError("web-first readback prerequisite is not satisfied")
                    job.canonical_url = web_state.public_url
                elif channel != "facebook" or job.cms_route != "NONE":
                    raise AdapterError("web-first readback prerequisite is not satisfied")
            binding = registry.binding(job.brand_id, channel)
            adapter = build_adapter(binding, client)
            state.status = "PUBLISHING"
            job_row.last_successful_step = f"{channel}:publish_started"
            emit_event(
                db,
                job_row,
                "CHANNEL_PUBLISH_STARTED",
                channel=channel,
                discriminator=str(job_row.attempt_count),
            )
            db.commit()
            result = adapter.publish(job, state.idempotency_key)
            state.status = "PUBLISHED"
            state.external_id = result.external_id
            state.public_url = result.public_url
            state.admin_url = result.admin_url
            state.canonical_url = result.canonical_url
            state.published_at = result.published_at
            emit_event(
                db, job_row, "CHANNEL_PUBLISHED", channel=channel, external_id=result.external_id
            )
            proof = _proof(db, job_row, state, result)
            state.status = "READBACK_VERIFIED"
            state.verified_at = utcnow()
            job_row.last_successful_step = f"{channel}:readback_verified"
            emit_event(
                db,
                job_row,
                "CHANNEL_READBACK_VERIFIED",
                channel=channel,
                external_id=result.external_id,
                payload={"proof_id": proof.proof_id},
            )
            completed.append((channel, result))
            db.commit()
        unverified = [
            channel
            for channel in ordered
            if channel != "forum" and states[channel].status != "READBACK_VERIFIED"
        ]
        if unverified:
            raise AdapterError(
                "unverified publication channels: " + ",".join(sorted(unverified))
            )
        job_row.status = "VERIFIED"
        job_row.completed_at = utcnow()
        job_row.claimed_by = None
        job_row.claimed_at = None
        job_row.lease_expires_at = None
        db.commit()
        return {"status": "VERIFIED", "job_id": job_row.job_id, "channels": ordered}
    except Exception as exc:
        failed_channel = next(
            (channel for channel in ordered if states[channel].status == "PUBLISHING"), None
        )
        if failed_channel:
            states[failed_channel].status = "FAILED"
            emit_event(
                db,
                job_row,
                "CHANNEL_PUBLICATION_FAILED",
                channel=failed_channel,
                payload={"error_type": type(exc).__name__},
                discriminator=str(job_row.attempt_count),
            )
        rollback_failed = False
        if job.rollback_policy.on_partial_failure and completed:
            job_row.status = "ROLLING_BACK"
            emit_event(
                db,
                job_row,
                "PUBLICATION_ROLLBACK_STARTED",
                payload={"channels": [item[0] for item in completed]},
            )
            db.commit()
            for channel, result in reversed(completed):
                state = states[channel]
                state.status = "ROLLING_BACK"
                try:
                    adapter = build_adapter(registry.binding(job.brand_id, channel), client)
                    rollback = adapter.rollback(job, result, type(exc).__name__)
                    state.status = "ROLLED_BACK"
                    state.rollback_status = "VERIFIED"
                    state.rollback_readback_json = canonical_json(redact(rollback))
                    emit_event(
                        db,
                        job_row,
                        "PUBLICATION_ROLLED_BACK",
                        channel=channel,
                        external_id=result.external_id,
                    )
                except Exception as rollback_exc:
                    rollback_failed = True
                    state.status = "ROLLBACK_FAILED"
                    state.rollback_status = "FAILED"
                    emit_event(
                        db,
                        job_row,
                        "CHANNEL_ROLLBACK_FAILED",
                        channel=channel,
                        external_id=result.external_id,
                        payload={"error_type": type(rollback_exc).__name__},
                    )
                db.commit()

        can_retry = not rollback_failed and job_row.attempt_count < job_row.max_attempts
        job_row.last_error = type(exc).__name__
        job_row.claimed_by = None
        job_row.claimed_at = None
        job_row.lease_expires_at = None
        if can_retry:
            delay_seconds = min(1800, 30 * (2 ** max(0, job_row.attempt_count - 1)))
            for state in states.values():
                if state.channel == "forum":
                    continue
                state.status = "QUEUED"
                state.external_id = None
                state.public_url = None
                state.admin_url = None
                state.published_at = None
                state.verified_at = None
            job_row.status = "QUEUED"
            job_row.available_at = utcnow() + timedelta(seconds=delay_seconds)
            db.commit()
            return {
                "status": "RETRY_QUEUED",
                "job_id": job_row.job_id,
                "error_type": type(exc).__name__,
                "attempt": job_row.attempt_count,
                "retry_in_seconds": delay_seconds,
            }

        job_row.status = (
            "ROLLBACK_FAILED" if rollback_failed else "ROLLED_BACK" if completed else "FAILED"
        )
        severity = "CRITICAL" if rollback_failed else "MAJOR"
        create_exception(
            db,
            job_row,
            severity=severity,
            error_type=type(exc).__name__,
            channel=failed_channel,
            response={"message": str(exc)},
            recommended_action=(
                "Az automatikus újrapróbálások elfogytak. Ellenőrizd a readback/rollback "
                "bizonyítékot, javítsd az adaptert vagy routingot, majd replay-elj."
            ),
            rollback_status="FAILED" if rollback_failed else "VERIFIED" if completed else None,
        )
        if rollback_failed and job.rollback_policy.automatic_kill_switch_on_failure:
            _trip_runtime_kill_switch()
        db.commit()
        return {
            "status": job_row.status,
            "job_id": job_row.job_id,
            "error_type": type(exc).__name__,
        }
    finally:
        client.close()


def _daily_gate_deadline_reached(now: datetime | None = None) -> bool:
    timezone = ZoneInfo(os.getenv("AUTONOMOUS_PUBLISHING_DAILY_GATE_TIMEZONE", "Europe/Budapest"))
    local_now = (now or utcnow()).astimezone(timezone)
    try:
        hour = int(os.getenv("AUTONOMOUS_PUBLISHING_DAILY_GATE_HOUR", "12"))
    except ValueError:
        hour = 12
    return local_now.hour >= max(0, min(23, hour))


def daily_publication_integrity(
    db: Session, *, now: datetime | None = None
) -> dict[str, Any]:
    registry = PublishingRegistry.load()
    timezone = ZoneInfo(os.getenv("AUTONOMOUS_PUBLISHING_DAILY_GATE_TIMEZONE", "Europe/Budapest"))
    local_now = (now or utcnow()).astimezone(timezone)
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)

    expected: set[tuple[str, str]] = set()
    for brand_id, brand in registry.brands.items():
        for channel, config in (brand.get("channels") or {}).items():
            if channel in {*WEB_CHANNELS, *SOCIAL_CHANNELS} and config.get("enabled"):
                expected.add((brand_id, channel))

    rows = db.execute(
        select(
            PublishingChannelState.brand_id,
            PublishingChannelState.channel,
            PublishingChannelState.status,
            PublishingChannelState.public_url,
            PublicationProofRecord.proof_id,
            PublicationProofRecord.readback_json,
            PublishingJobRecord.payload_json,
        )
        .join(
            PublishingJobRecord,
            PublishingJobRecord.job_id == PublishingChannelState.job_id,
        )
        .outerjoin(
            PublicationProofRecord,
            PublicationProofRecord.channel_state_id
            == PublishingChannelState.channel_state_id,
        )
        .where(
            func.coalesce(
                PublishingJobRecord.desired_publish_at, PublishingJobRecord.created_at
            ) >= start_utc,
            func.coalesce(
                PublishingJobRecord.desired_publish_at, PublishingJobRecord.created_at
            ) < end_utc,
            PublishingChannelState.channel.in_([*WEB_CHANNELS, *SOCIAL_CHANNELS]),
        )
    ).all()

    verified: set[tuple[str, str]] = set()
    invalid: list[str] = []
    for brand_id, channel, state, public_url, proof_id, readback_json, payload_json in rows:
        key = (str(brand_id), str(channel))
        if key not in expected or key in verified:
            continue
        if state != "READBACK_VERIFIED" or not str(public_url or "").startswith("https://"):
            continue
        if not proof_id or not readback_json:
            continue
        try:
            readback = json.loads(readback_json)
            payload = json.loads(payload_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            invalid.append(f"{brand_id}/{channel}:invalid_proof_json")
            continue

        image_verified = False
        if channel == "wordpress":
            image_verified = int(readback.get("featured_media") or 0) > 0
        elif channel == "facebook":
            image_verified = str(readback.get("full_picture") or "").startswith("https://")
        elif channel == "instagram":
            image_verified = str(readback.get("media_url") or "").startswith("https://")
        elif channel == "nim_cms":
            brand = registry.brands.get(str(brand_id)) or {}
            config = ((brand.get("channels") or {}).get("nim_cms") or {})
            mapping = ((config.get("contract") or {}).get("readback_map") or {})
            visual_id_field = mapping.get("visual_asset_package_id")
            visual_url_field = mapping.get("featured_image_url")
            if visual_id_field:
                image_verified = str(readback.get(visual_id_field) or "") == str(
                    payload.get("visual_asset_package_id") or ""
                )
            elif visual_url_field:
                image_verified = str(readback.get(visual_url_field) or "").startswith("https://")
        if not image_verified:
            invalid.append(f"{brand_id}/{channel}:image_not_verified")
            continue
        verified.add(key)

    missing = sorted(f"{brand}/{channel}" for brand, channel in expected - verified)
    status = "healthy" if expected and not missing and not invalid else "degraded"
    return {
        "status": status,
        "local_date": start_local.date().isoformat(),
        "expected": len(expected),
        "verified": len(verified),
        "missing": missing,
        "invalid": sorted(set(invalid)),
        "deadline_reached": _daily_gate_deadline_reached(now),
    }


def run_once(db: Session) -> dict[str, Any]:
    if not settings.autonomous_publishing_enabled:
        heartbeat(db, status="disabled")
        return {"status": "disabled", "processed": 0}
    row = claim_job(db)
    try:
        daily_gate = daily_publication_integrity(db)
    except Exception as exc:
        daily_gate = {
            "status": "degraded",
            "error_type": type(exc).__name__,
            "deadline_reached": True,
        }
    if not row:
        worker_status = (
            "healthy"
            if daily_gate.get("status") == "healthy"
            else "degraded"
            if daily_gate.get("deadline_reached")
            else "working"
        )
        heartbeat(
            db,
            status=worker_status,
            detail={"status": "idle", "processed": 0, "daily_gate": daily_gate},
        )
        return {"status": "idle", "processed": 0, "daily_gate": daily_gate}
    heartbeat(db, status="working", current_job_id=row.job_id)
    result = process_job(db, row)
    try:
        daily_gate = daily_publication_integrity(db)
    except Exception as exc:
        daily_gate = {
            "status": "degraded",
            "error_type": type(exc).__name__,
            "deadline_reached": True,
        }
    if result.get("status") != "VERIFIED":
        worker_status = "degraded"
    elif daily_gate.get("status") == "healthy":
        worker_status = "healthy"
    elif daily_gate.get("deadline_reached"):
        worker_status = "degraded"
    else:
        worker_status = "working"
    heartbeat(db, status=worker_status, detail={**result, "daily_gate": daily_gate})
    return {"processed": 1, **result, "daily_gate": daily_gate}

def retry_job(db: Session, job_id: str, *, reason: str) -> PublishingJobRecord:
    row = db.scalar(select(PublishingJobRecord).where(PublishingJobRecord.job_id == job_id))
    if not row:
        raise KeyError(job_id)
    if row.status not in {"BLOCKED", "FAILED", "ROLLED_BACK", "ROLLBACK_FAILED"}:
        raise ValueError("Only blocked or failed publishing jobs can be replayed")
    row.status = "QUEUED"
    row.available_at = utcnow()
    row.last_error = None
    row.claimed_by = None
    row.claimed_at = None
    row.lease_expires_at = None
    for state in db.scalars(
        select(PublishingChannelState).where(PublishingChannelState.job_id == job_id)
    ).all():
        if state.status in {"FAILED", "ROLLED_BACK", "ROLLBACK_FAILED", "BLOCKED"}:
            state.status = "QUEUED"
    audit(
        db,
        actor="publishing-admin",
        action="autonomous_publication_job_replayed",
        entity_type="publishing_job",
        entity_id=job_id,
        after={"reason": reason},
    )
    db.commit()
    return row


def readiness(db: Session) -> tuple[bool, dict[str, Any]]:
    try:
        db.execute(select(func.count()).select_from(PublishingJobRecord))
        database_ok = True
    except Exception:
        db.rollback()
        database_ok = False
    try:
        registry = PublishingRegistry.load()
        registry_state = registry.readiness()
    except RegistryError as exc:
        registry_state = {"ready": False, "error": str(exc), "routes": []}
    heartbeat_row = (
        db.get(PublishingWorkerHeartbeat, settings.autonomous_publishing_worker_id)
        if database_ok
        else None
    )
    heartbeat_fresh = bool(
        heartbeat_row
        and heartbeat_row.heartbeat_at
        and (
            utcnow()
            - heartbeat_row.heartbeat_at.replace(tzinfo=heartbeat_row.heartbeat_at.tzinfo or UTC)
        ).total_seconds()
        <= settings.autonomous_publishing_heartbeat_stale_seconds
    )
    heartbeat_serving = bool(
        heartbeat_row
        and heartbeat_row.status in {"healthy", "working", "degraded"}
    )
    heartbeat_ok = heartbeat_fresh and heartbeat_serving
    queued = (
        db.scalar(
            select(func.count())
            .select_from(PublishingJobRecord)
            .where(PublishingJobRecord.status == "QUEUED")
        )
        or 0
        if database_ok
        else None
    )
    required = settings.autonomous_publishing_enabled
    ready = database_ok and (not required or (registry_state.get("ready") and heartbeat_ok))
    return ready, {
        "enabled": required,
        "database": "ok" if database_ok else "failed",
        "queue_depth": queued,
        "worker_heartbeat": (
            "degraded_sla"
            if heartbeat_ok and heartbeat_row and heartbeat_row.status == "degraded"
            else "ok" if heartbeat_ok else "stale_or_missing"
        ),
        "worker_status": heartbeat_row.status if heartbeat_row else "missing",
        "registry": registry_state,
        "writes_unlocked": writes_unlocked(),
        "http_metrics": ProductionHttpClient.metric_snapshot(),
    }
