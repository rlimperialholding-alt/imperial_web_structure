from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .client import ETDRClient, ETDRPage, ETDRRecord, OENYClient, ReaderBlocked
from .config import ReaderSettings
from .models import (
    AuthorityCheckpoint,
    AuthorityEnrichmentQueue,
    AuthorityReaderRun,
    AuthorityRecord,
    AuthorityRecordRevision,
    AuthoritySignalOutbox,
)

ClientFactory = Callable[[ReaderSettings], ETDRClient]
OENYClientFactory = Callable[[ReaderSettings], OENYClient]


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _external_hmac(settings: ReaderSettings, external_key: str) -> str:
    return hmac.new(settings.hmac_key.encode(), external_key.encode(), hashlib.sha256).hexdigest()


def _scope(mode: str, town: str | None) -> str:
    return f"etdr_public:pilot:{town.casefold()}" if mode == "pilot" and town else "etdr_public"


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _filter(mode: str, cutoff: datetime, since: datetime | None, town: str | None) -> str:
    parts: list[str] = []
    if mode == "pilot":
        if not town or len(town.strip()) < 2:
            raise ValueError("pilot_town_required")
        safe_town = town.strip().replace("'", "''")
        parts.append(f"City eq '{safe_town}'")
    elif mode == "delta":
        if since is None:
            raise ValueError("delta_since_required")
        parts.append(f"SubmissionDate ge {_iso(since)}")
    parts.append(f"SubmissionDate le {_iso(cutoff)}")
    return " and ".join(parts)


def readiness(db: Session, settings: ReaderSettings) -> tuple[bool, dict[str, Any]]:
    db.scalar(select(func.count()).select_from(AuthorityCheckpoint))
    errors = settings.errors()
    return not errors, {
        "reader": "ready" if not errors else "blocked",
        "enabled": settings.enabled,
        "policy_authorized": settings.policy_authorized,
        "policy_evidence_valid": settings.policy_evidence_valid,
        "policy_evidence_sha256": settings.policy_evidence_sha256 or None,
        "oeny": "enabled" if settings.oeny_enabled else "held",
        "errors": errors,
    }


def _lease(
    db: Session, settings: ReaderSettings, scope: str, owner: str, now: datetime
) -> AuthorityCheckpoint:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        locked = db.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:scope))"), {"scope": scope}
        )
        if not locked:
            raise ReaderBlocked("active_lease")
    checkpoint = db.scalar(
        select(AuthorityCheckpoint).where(AuthorityCheckpoint.source_key == scope).with_for_update()
    )
    if checkpoint is None:
        checkpoint = AuthorityCheckpoint(source_key=scope)
        db.add(checkpoint)
        db.flush()
    expires = checkpoint.lease_expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if checkpoint.lease_owner and expires and expires > now and checkpoint.lease_owner != owner:
        raise ReaderBlocked("active_lease")
    checkpoint.lease_owner = owner
    checkpoint.lease_expires_at = now + timedelta(seconds=settings.lease_seconds)
    checkpoint.updated_at = now
    db.commit()
    return checkpoint


def _upsert_record(
    db: Session,
    settings: ReaderSettings,
    run: AuthorityReaderRun,
    item: ETDRRecord,
) -> str:
    normalized = item.normalized()
    payload_hash = sha(normalized)
    external_hash = _external_hmac(settings, item.process_number)
    row = db.scalar(
        select(AuthorityRecord).where(
            AuthorityRecord.source_key == "etdr_public",
            AuthorityRecord.external_key_hmac == external_hash,
        )
    )
    now = utcnow()
    if row and row.current_payload_sha256 == payload_hash:
        row.last_seen_at = now
        return "unchanged"
    if row is None:
        row = AuthorityRecord(
            record_id=f"etdr-{uuid4().hex}",
            source_key="etdr_public",
            external_key_hmac=external_hash,
            public_process_number=item.process_number,
            city=item.city,
            topographical_number=item.topographical_number,
            procedure_type=item.procedure_type,
            construction_activity=item.construction_activity,
            submission_date=item.submission_date,
            evidence_url=(f"{settings.etdr_public_url}/nyilvanos-adatok/{item.process_number}"),
            current_revision_no=1,
            current_payload_sha256=payload_hash,
        )
        db.add(row)
        db.flush()
        outcome = "inserted"
    else:
        row.current_revision_no += 1
        row.current_payload_sha256 = payload_hash
        row.city = item.city
        row.topographical_number = item.topographical_number
        row.procedure_type = item.procedure_type
        row.construction_activity = item.construction_activity
        row.submission_date = item.submission_date
        row.last_seen_at = now
        outcome = "updated"
    revision = AuthorityRecordRevision(
        revision_id=f"etdrr-{uuid4().hex}",
        record_id=row.record_id,
        run_id=run.run_id,
        revision_no=row.current_revision_no,
        payload_sha256=payload_hash,
        normalized_json=canonical_json(normalized),
    )
    db.add(revision)
    db.flush()
    if item.topographical_number:
        db.add(
            AuthorityEnrichmentQueue(
                record_id=row.record_id,
                payload_sha256=payload_hash,
                status="pending" if settings.oeny_enabled else "held",
                reason_code="ready" if settings.oeny_enabled else "oeny_policy_gate",
            )
        )
    signal_payload = {
        "record_id": row.record_id,
        "revision_id": revision.revision_id,
        "source": "etdr_public",
        "city": item.city,
        "procedure_type": item.procedure_type,
        "evidence_url": row.evidence_url,
        "contact_basis": "unknown",
        "recipient_email": None,
    }
    db.add(
        AuthoritySignalOutbox(
            idempotency_key=sha({"record": row.record_id, "payload": payload_hash}),
            record_id=row.record_id,
            revision_id=revision.revision_id,
            payload_sha256=sha(signal_payload),
            payload_json=canonical_json(signal_payload),
            status="held",
            reason_code="manual_promotion_required",
        )
    )
    return outcome


def _page_commit(
    db: Session,
    settings: ReaderSettings,
    checkpoint: AuthorityCheckpoint,
    run: AuthorityReaderRun,
    page: ETDRPage,
    *,
    next_skip: int,
    cursor: dict[str, Any],
) -> None:
    outcomes = {"inserted": 0, "updated": 0, "unchanged": 0}
    for item in page.records:
        outcomes[_upsert_record(db, settings, run, item)] += 1
    run.pages_completed += 1
    run.records_seen += len(page.records)
    run.records_inserted += outcomes["inserted"]
    run.records_updated += outcomes["updated"]
    run.records_unchanged += outcomes["unchanged"]
    cursor.update({"skip": next_skip, "last_page_sha256": page.payload_sha256})
    checkpoint.cursor_json = canonical_json(cursor)
    checkpoint.cursor_sha256 = sha(cursor)
    checkpoint.generation += 1
    checkpoint.lease_expires_at = utcnow() + timedelta(seconds=settings.lease_seconds)
    checkpoint.updated_at = utcnow()
    db.commit()


def run_reader(
    db: Session,
    settings: ReaderSettings,
    *,
    mode: str,
    trigger: str,
    town: str | None = None,
    max_pages: int | None = None,
    client_factory: ClientFactory = ETDRClient,
) -> AuthorityReaderRun:
    if mode not in {"baseline", "delta", "pilot"}:
        raise ValueError("invalid_mode")
    if not settings.enabled:
        raise ReaderBlocked("reader_disabled")
    if not settings.policy_authorized:
        raise ReaderBlocked("policy_authorization_required")
    errors = settings.errors()
    if errors:
        raise ReaderBlocked(errors[0])
    now = utcnow()
    scope = _scope(mode, town)
    owner = f"{settings.worker_id}:{uuid4().hex}"
    checkpoint = _lease(db, settings, scope, owner, now)
    previous_cursor = json.loads(checkpoint.cursor_json or "{}")
    resume = previous_cursor if previous_cursor.get("mode") == mode else {}
    cutoff = (
        datetime.fromisoformat(resume["cutoff"].replace("Z", "+00:00"))
        if resume.get("cutoff")
        else now
    )
    last_success = checkpoint.last_success_at
    if last_success and last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=UTC)
    since = last_success - timedelta(days=settings.overlap_days) if last_success else None
    if mode == "delta" and since is None:
        since = now - timedelta(days=settings.overlap_days)
    expression = resume.get("filter") or _filter(mode, cutoff, since, town)
    skip = int(resume.get("skip", 0))
    cursor = {
        "mode": mode,
        "town": town,
        "filter": expression,
        "cutoff": _iso(cutoff),
        "skip": skip,
    }
    run = AuthorityReaderRun(
        run_id=f"etdr-run-{uuid4().hex}",
        source_key=scope,
        mode=mode,
        trigger=trigger,
        status="running",
        filter_json=canonical_json({"town": town, "expression_sha256": sha(expression)}),
        cutoff_at=cutoff,
    )
    db.add(run)
    db.commit()
    limit = min(max_pages or settings.max_pages_per_run, settings.max_pages_per_run)
    expected_total: int | None = None
    prior_page_hash = resume.get("last_page_sha256")
    try:
        with client_factory(settings) as client:
            for _ in range(limit):
                page = client.fetch_page(
                    skip=skip, page_size=settings.page_size, filter_expression=expression
                )
                if expected_total is None:
                    expected_total = page.total
                    run.total_reported = page.total
                elif page.total != expected_total:
                    raise ReaderBlocked("upstream_count_drift")
                if page.records and page.payload_sha256 == prior_page_hash:
                    raise ReaderBlocked("repeated_page_detected")
                next_skip = skip + len(page.records)
                _page_commit(
                    db,
                    settings,
                    checkpoint,
                    run,
                    page,
                    next_skip=next_skip,
                    cursor=cursor,
                )
                prior_page_hash = page.payload_sha256
                skip = next_skip
                if not page.records or skip >= page.total:
                    run.status = "completed"
                    run.completed_at = utcnow()
                    checkpoint.cursor_json = "{}"
                    checkpoint.cursor_sha256 = sha({})
                    checkpoint.last_success_at = cutoff
                    checkpoint.lease_owner = None
                    checkpoint.lease_expires_at = None
                    db.commit()
                    return run
                time.sleep(settings.request_delay_seconds)
        run.status = "partial"
        run.completed_at = utcnow()
        checkpoint.lease_owner = None
        checkpoint.lease_expires_at = None
        db.commit()
        return run
    except ReaderBlocked as exc:
        db.rollback()
        failed_run = db.get(AuthorityReaderRun, run.id)
        failed_checkpoint = db.get(AuthorityCheckpoint, scope)
        assert failed_run is not None and failed_checkpoint is not None
        failed_run.status = "blocked"
        failed_run.error_code = exc.code
        failed_run.error_detail_json = canonical_json({"code": exc.code})
        failed_run.completed_at = utcnow()
        failed_checkpoint.lease_owner = None
        failed_checkpoint.lease_expires_at = None
        db.commit()
        raise


def run_summary(row: AuthorityReaderRun) -> dict[str, Any]:
    return {
        "run_id": row.run_id,
        "source_key": row.source_key,
        "mode": row.mode,
        "trigger": row.trigger,
        "status": row.status,
        "total_reported": row.total_reported,
        "pages_completed": row.pages_completed,
        "records_seen": row.records_seen,
        "inserted": row.records_inserted,
        "updated": row.records_updated,
        "unchanged": row.records_unchanged,
        "error_code": row.error_code,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


def process_enrichments(
    db: Session,
    settings: ReaderSettings,
    *,
    limit: int = 100,
    client_factory: OENYClientFactory = OENYClient,
) -> dict[str, int]:
    if not settings.enabled or not settings.policy_authorized:
        raise ReaderBlocked("policy_authorization_required")
    if not settings.oeny_enabled:
        raise ReaderBlocked("oeny_disabled")
    rows = db.scalars(
        select(AuthorityEnrichmentQueue)
        .where(AuthorityEnrichmentQueue.status == "pending")
        .order_by(AuthorityEnrichmentQueue.id)
        .limit(max(1, min(limit, 1000)))
    ).all()
    counts = {"completed": 0, "ambiguous": 0, "failed": 0}
    with client_factory(settings) as client:
        for queue in rows:
            record_row = db.scalar(
                select(AuthorityRecord).where(AuthorityRecord.record_id == queue.record_id)
            )
            if not record_row or not record_row.topographical_number:
                queue.status = "failed"
                queue.reason_code = "missing_property_identity"
                counts["failed"] += 1
                db.commit()
                continue
            try:
                settlements = client.settlement_search(record_row.city)
                exact = [
                    item
                    for item in settlements
                    if item["name"].casefold() == record_row.city.casefold()
                ]
                if len(exact) != 1:
                    queue.status = "ambiguous"
                    queue.reason_code = "settlement_ambiguous"
                    queue.result_json = canonical_json({"settlement_matches": len(exact)})
                    counts["ambiguous"] += 1
                else:
                    parcels = client.parcel_search(
                        ksh_code=exact[0]["kshCode"],
                        lot_number=record_row.topographical_number,
                    )
                    queue.result_json = canonical_json(
                        {
                            "ksh_code": exact[0]["kshCode"],
                            "parcels": [
                                {"id": item["id"], "lot_number": item["lotNumber"]}
                                for item in parcels
                            ],
                        }
                    )
                    if len(parcels) == 1:
                        queue.status = "completed"
                        queue.reason_code = "exact_single_match"
                        counts["completed"] += 1
                    else:
                        queue.status = "ambiguous"
                        queue.reason_code = "parcel_match_count_not_one"
                        counts["ambiguous"] += 1
                queue.attempt_count += 1
                queue.updated_at = utcnow()
                db.commit()
                time.sleep(settings.request_delay_seconds)
            except ReaderBlocked as exc:
                db.rollback()
                blocked_queue = db.get(AuthorityEnrichmentQueue, queue.id)
                assert blocked_queue is not None
                blocked_queue.status = "blocked"
                blocked_queue.reason_code = exc.code
                blocked_queue.attempt_count += 1
                blocked_queue.updated_at = utcnow()
                db.commit()
                raise
    return counts
