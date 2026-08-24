from __future__ import annotations

import hashlib
import hmac
import json
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, case, func, or_, select, text, update
from sqlalchemy.orm import Session

from .client import (
    ETDRClient,
    ETDRDetail,
    ETDRDetailClient,
    ETDRPage,
    ETDRRecord,
    OENYClient,
    ReaderBlocked,
)
from .config import ReaderSettings
from .models import (
    AuthorityCheckpoint,
    AuthorityDetailQueue,
    AuthorityDetailRevision,
    AuthorityEnrichmentQueue,
    AuthorityReaderRun,
    AuthorityRecord,
    AuthorityRecordRevision,
    AuthoritySignalOutbox,
)

ClientFactory = Callable[[ReaderSettings], ETDRClient]
OENYClientFactory = Callable[[ReaderSettings], OENYClient]
DetailClientFactory = Callable[[ReaderSettings], ETDRDetailClient]


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


def _filter(
    mode: str,
    cutoff: datetime,
    since: datetime | None,
    town: str | None,
    *,
    baseline_lookback_days: int,
) -> str:
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
    elif mode == "baseline":
        parts.append(
            f"SubmissionDate ge {_iso(cutoff - timedelta(days=baseline_lookback_days))}"
        )
    parts.append(f"SubmissionDate le {_iso(cutoff)}")
    return " and ".join(parts)


def readiness(db: Session, settings: ReaderSettings) -> tuple[bool, dict[str, Any]]:
    db.scalar(select(func.count()).select_from(AuthorityCheckpoint))
    errors = settings.errors()
    policy_open = settings.enabled and settings.policy_authorized and settings.policy_evidence_valid
    return not errors, {
        "reader": "ready" if not errors else "blocked",
        "enabled": settings.enabled,
        "policy_authorized": settings.policy_authorized,
        "policy_evidence_valid": settings.policy_evidence_valid,
        "policy_evidence_sha256": settings.policy_evidence_sha256 or None,
        "schedule": "enabled" if policy_open and settings.schedule_enabled else "held",
        "detail_reader": "enabled" if policy_open and settings.detail_enabled else "held",
        "lead_export": "enabled" if policy_open and settings.lead_export_enabled else "held",
        "sales_digest": (
            "enabled"
            if policy_open
            and settings.sales_digest_enabled
            and settings.sales_digest_authorized
            else "held"
        ),
        "oeny": "enabled" if policy_open and settings.oeny_enabled else "held",
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
            parcel_key=_parcel_key(item.topographical_number),
            procedure_type=item.procedure_type,
            construction_activity=item.construction_activity or "",
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
        row.parcel_key = _parcel_key(item.topographical_number)
        row.procedure_type = item.procedure_type
        row.construction_activity = item.construction_activity or ""
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
    detail_candidate = _listing_may_qualify(
        procedure_type=row.procedure_type,
        construction_activity=row.construction_activity,
        submission_date=row.submission_date,
        settings=settings,
        as_of=now,
    )
    detail_pending = settings.detail_enabled and detail_candidate
    row.detail_status = "pending" if detail_pending else "held"
    db.add(
        AuthorityDetailQueue(
            record_id=row.record_id,
            source_revision_id=revision.revision_id,
            listing_payload_sha256=payload_hash,
            status="pending" if detail_pending else "held",
            reason_code=(
                "ready"
                if detail_pending
                else (
                    "detail_policy_gate"
                    if detail_candidate
                    else "lead_prefilter_not_candidate"
                )
            ),
        )
    )
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
    expression = resume.get("filter") or _filter(
        mode,
        cutoff,
        since,
        town,
        baseline_lookback_days=settings.lead_stalled_max_days,
    )
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


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


LEAD_POLICY_VERSION = "etdr-lead-v2"
CONSTRUCTION_INTENT_TERMS = ("epitesi engedelyezesi", "egyszeru bejelent")
NON_START_STATUS_TERMS = ("megszunt", "visszavon")
INTERRUPTED_STATUS_TERMS = ("felfuggeszt", "szunetel", "felbeszak")
REJECTED_STATUS_TERMS = ("elutasit", "ervenytelen")
POSITIVE_PERMIT_TERMS = ("engedely", "engedelyezes", "engedelyezett")
NEGATIVE_DECISION_TERMS = ("elutasit", "megszunt", "visszavon", "ervenytelen", "megtagad")
COMPLETION_TERMS = (
    "hasznalatbavet",
    "hasznalatba vet",
    "hatosagi bizonyitvany",
    "epitesi munkalatok befejez",
    "epitkezes befejez",
)


@dataclass(frozen=True)
class LeadDecision:
    eligible: bool
    reason: str
    confidence: int = 0
    urgency: int = 0
    evidence: tuple[str, ...] = ()
    next_evaluate_at: datetime | None = None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _age_days(submission_date: datetime, as_of: datetime) -> int:
    return (_aware(as_of).date() - _aware(submission_date).date()).days


def _is_construction_intent(procedure_type: str) -> bool:
    folded = _fold(procedure_type)
    return any(term in folded for term in CONSTRUCTION_INTENT_TERMS)


def _is_completion_text(procedure_type: str, construction_activity: str) -> bool:
    folded = _fold(f"{procedure_type} {construction_activity}")
    return any(term in folded for term in COMPLETION_TERMS)


def _is_completion_signal(record: AuthorityRecord) -> bool:
    return _is_completion_text(record.procedure_type, record.construction_activity)


def _parcel_key(value: str | None) -> str | None:
    if not value:
        return None
    return "".join(character for character in _fold(value) if not character.isspace())


def _listing_may_qualify(
    *,
    procedure_type: str,
    construction_activity: str,
    submission_date: datetime,
    settings: ReaderSettings,
    as_of: datetime,
) -> bool:
    age = _age_days(submission_date, as_of)
    return (
        _is_construction_intent(procedure_type)
        and not _is_completion_text(procedure_type, construction_activity)
        and 0 <= age <= settings.lead_stalled_max_days
    )


def _later_property_records(
    db: Session,
    record: AuthorityRecord,
) -> tuple[AuthorityRecord, ...]:
    parcel = _parcel_key(record.topographical_number)
    if parcel is None:
        return ()
    candidates = db.scalars(
        select(AuthorityRecord).where(
            AuthorityRecord.source_key == record.source_key,
            AuthorityRecord.city == record.city,
            AuthorityRecord.record_id != record.record_id,
            AuthorityRecord.status == "active",
            or_(
                AuthorityRecord.parcel_key == parcel,
                and_(
                    AuthorityRecord.parcel_key.is_(None),
                    AuthorityRecord.topographical_number == record.topographical_number,
                ),
            ),
        )
    ).all()
    current_order = (_aware(record.submission_date), record.public_process_number)
    return tuple(
        candidate
        for candidate in candidates
        if _parcel_key(candidate.topographical_number) == parcel
        and (_aware(candidate.submission_date), candidate.public_process_number) > current_order
    )


def _recent_positive_permit(detail: ETDRDetail, as_of: datetime, days: int) -> bool:
    cutoff = _aware(as_of).date() - timedelta(days=days)
    for decision in detail.decisions:
        folded = _fold(f"{decision.decision_type} {decision.summary}")
        if (
            cutoff <= decision.decision_date <= _aware(as_of).date()
            and any(term in folded for term in POSITIVE_PERMIT_TERMS)
            and not any(term in folded for term in NEGATIVE_DECISION_TERMS)
        ):
            return True
    return False


def _lead_decision(
    db: Session,
    settings: ReaderSettings,
    detail: ETDRDetail,
    record: AuthorityRecord,
    *,
    as_of: datetime | None = None,
) -> LeadDecision:
    evaluated_at = _aware(as_of or utcnow())
    age = _age_days(record.submission_date, evaluated_at)
    if not _is_construction_intent(record.procedure_type):
        return LeadDecision(False, "unsupported_procedure")
    if _is_completion_signal(record):
        return LeadDecision(False, "current_completion_signal")
    if age < 0 or age > settings.lead_stalled_max_days:
        return LeadDecision(False, "outside_recent_window")

    later_records = _later_property_records(db, record)
    if any(_is_construction_intent(candidate.procedure_type) for candidate in later_records):
        return LeadDecision(False, "superseded_by_later_property_filing")
    if any(_is_completion_signal(candidate) for candidate in later_records):
        return LeadDecision(False, "later_completion_signal_found")

    status = _fold(detail.status)
    if any(term in status for term in REJECTED_STATUS_TERMS):
        return LeadDecision(False, "rejected_or_invalid_procedure")
    if any(term in status for term in INTERRUPTED_STATUS_TERMS):
        return LeadDecision(
            True,
            "likely_interrupted",
            confidence=78,
            urgency=82,
            evidence=(
                "construction_intent_procedure",
                "procedure_suspended_paused_or_interrupted",
                "public_status_supports_interruption_indicator",
            ),
        )
    if any(term in status for term in NON_START_STATUS_TERMS):
        return LeadDecision(
            True,
            "likely_not_started",
            confidence=72,
            urgency=65,
            evidence=(
                "construction_intent_procedure",
                "procedure_discontinued_or_withdrawn",
                "public_status_supports_non_start_indicator",
            ),
        )
    if _recent_positive_permit(detail, evaluated_at, settings.lead_new_days):
        return LeadDecision(
            True,
            "recently_authorized",
            confidence=95,
            urgency=95,
            evidence=(
                "construction_intent_procedure",
                f"positive_permit_decision_within_{settings.lead_new_days}_days",
                "latest_known_filing_for_same_property",
            ),
        )
    if age <= settings.lead_new_days:
        return LeadDecision(
            True,
            "new_submission",
            confidence=92,
            urgency=90 if age <= 30 else 80,
            evidence=(
                "construction_intent_procedure",
                f"submission_within_{settings.lead_new_days}_days",
                "latest_known_filing_for_same_property",
            ),
        )
    if age < settings.lead_stalled_min_days:
        next_evaluate_at = _aware(record.submission_date) + timedelta(
            days=settings.lead_stalled_min_days
        )
        return LeadDecision(
            False,
            "waiting_for_no_completion_window",
            next_evaluate_at=next_evaluate_at,
        )
    if _parcel_key(record.topographical_number) is None:
        return LeadDecision(False, "stable_property_key_missing")
    return LeadDecision(
        True,
        "no_completion_signal",
        confidence=68,
        urgency=70,
        evidence=(
            "construction_intent_procedure",
            (
                f"submission_between_{settings.lead_stalled_min_days}_and_"
                f"{settings.lead_stalled_max_days}_days"
            ),
            "no_later_completion_signal_for_same_property",
            "latest_known_filing_for_same_property",
        ),
    )


def _lead_route(detail: ETDRDetail, record: AuthorityRecord) -> tuple[str, str]:
    text_value = _fold(f"{detail.subject} {record.construction_activity} {record.procedure_type}")
    routes = (
        (("csarnok", "raktar", "uzem", "logisztikai", "ipari"), "hall", "prefab"),
        (("bovit", "toldalek", "hozzaepites"), "extension", "bautica"),
        (("felujit", "atalakit", "korszerusit", "tetoter"), "renovation", "bautica"),
        (("belsoepit", "uzlet", "iroda", "vendeglato", "szalloda"), "fitout", "bautica"),
        (("lako", "csaladi haz", "lakashaz"), "residential_construction", "bautica"),
    )
    for terms, signal_type, brand_id in routes:
        if any(term in text_value for term in terms):
            return signal_type, brand_id
    return "construction_project", "bautica"


def _lead_payload(
    detail: ETDRDetail,
    record: AuthorityRecord,
    detail_payload_sha256: str,
    detail_revision_id: str,
    detail_revision_no: int,
    qualification: LeadDecision,
) -> dict[str, Any]:
    if not qualification.eligible:
        raise ValueError("ineligible_lead_payload")
    signal_type, brand_id = _lead_route(detail, record)
    decision = detail.decisions[-1] if detail.decisions else None
    facts = [
        f"Lead-indok: {qualification.reason}",
        detail.subject,
        f"Eljárás: {detail.procedure_type}",
        f"Státusz: {detail.status}",
        f"Hatóság: {detail.authority_name}",
        f"Minősítési jelek: {', '.join(qualification.evidence)}",
    ]
    if decision:
        facts.append(
            f"Legutóbbi döntés: {decision.decision_type} ({decision.decision_date.isoformat()})"
        )
        facts.append(decision.summary)
    if detail.documents:
        facts.append(f"Nyilvános dokumentumhivatkozások: {len(detail.documents)}")
    return {
        "schema_version": LEAD_POLICY_VERSION,
        "lead_reason": qualification.reason,
        "qualification_evidence": list(qualification.evidence),
        "source_id": "authority:etdr_public",
        "external_key": record.public_process_number,
        "motor_key": "construction",
        "source_bucket": "etdr",
        "signal_type": signal_type,
        "detected_at": _iso(record.submission_date),
        "company_name": None,
        "subject_type": "project",
        "recipient_email": None,
        "recipient_email_type": "none",
        "contact_basis": "unknown",
        "location": detail.property_address,
        "summary": " | ".join(facts)[:5000],
        "evidence_url": record.evidence_url,
        "brand_id": brand_id,
        "confidence": qualification.confidence,
        "urgency": qualification.urgency,
        "source_payload_hash": detail_payload_sha256,
        "revision_id": detail_revision_id,
        "revision_no": detail_revision_no,
        "rejection_reasons": [
            "authority_source_no_outreach",
            "contact_basis_unknown",
            "internal_review_only",
            "recipient_email_missing",
        ],
    }


def _queue_qualified_lead(
    db: Session,
    settings: ReaderSettings,
    *,
    detail: ETDRDetail,
    record: AuthorityRecord,
    detail_revision: AuthorityDetailRevision,
    detail_payload_sha256: str,
    qualification: LeadDecision,
) -> bool:
    existing_revision = db.scalar(
        select(AuthoritySignalOutbox).where(
            AuthoritySignalOutbox.revision_id == detail_revision.detail_revision_id
        )
    )
    if existing_revision:
        return False
    lead = _lead_payload(
        detail,
        record,
        detail_payload_sha256,
        detail_revision.detail_revision_id,
        detail_revision.revision_no,
        qualification,
    )
    idempotency_key = sha(
        {
            "record": record.record_id,
            "detail_payload": detail_payload_sha256,
            "lead_policy": LEAD_POLICY_VERSION,
            "lead_reason": qualification.reason,
        }
    )
    existing = db.scalar(
        select(AuthoritySignalOutbox).where(
            AuthoritySignalOutbox.idempotency_key == idempotency_key
        )
    )
    if existing:
        return False
    db.add(
        AuthoritySignalOutbox(
            idempotency_key=idempotency_key,
            record_id=record.record_id,
            revision_id=detail_revision.detail_revision_id,
            payload_sha256=sha(lead),
            payload_json=canonical_json(lead),
            status="pending" if settings.lead_export_enabled else "held",
            reason_code=(
                f"ready_for_daily_lead_generator_{qualification.reason}"
                if settings.lead_export_enabled
                else "lead_export_policy_gate"
            ),
        )
    )
    return True


def _detail_matches_record(detail: ETDRDetail, record: AuthorityRecord) -> bool:
    submitted = record.submission_date.date()
    same_property = (
        not record.topographical_number
        or not detail.topographical_number
        or _fold(record.topographical_number) == _fold(detail.topographical_number)
    )
    return (
        detail.process_number == record.public_process_number
        and detail.submission_date == submitted
        and _fold(detail.procedure_type) == _fold(record.procedure_type)
        and same_property
    )


def _promote_detail_queue(db: Session, settings: ReaderSettings) -> None:
    rows = db.scalars(
        select(AuthorityDetailQueue).where(
            AuthorityDetailQueue.status == "held",
            AuthorityDetailQueue.reason_code == "detail_policy_gate",
        )
    ).all()
    now = utcnow()
    for queue in rows:
        record = db.scalar(
            select(AuthorityRecord).where(AuthorityRecord.record_id == queue.record_id)
        )
        if record and record.current_payload_sha256 == queue.listing_payload_sha256:
            if _listing_may_qualify(
                procedure_type=record.procedure_type,
                construction_activity=record.construction_activity,
                submission_date=record.submission_date,
                settings=settings,
                as_of=now,
            ):
                queue.status = "pending"
                queue.reason_code = "ready"
                record.detail_status = "pending"
            else:
                queue.reason_code = "lead_prefilter_not_candidate"
            queue.updated_at = now
    if rows:
        db.commit()


def process_details(
    db: Session,
    settings: ReaderSettings,
    *,
    limit: int | None = None,
    client_factory: DetailClientFactory = ETDRDetailClient,
    as_of: datetime | None = None,
) -> dict[str, int]:
    if not settings.enabled or not settings.policy_authorized or not settings.policy_evidence_valid:
        raise ReaderBlocked("policy_authorization_required")
    if not settings.detail_enabled:
        raise ReaderBlocked("detail_reader_disabled")
    _promote_detail_queue(db, settings)
    now = utcnow()
    evaluation_time = _aware(as_of or now)
    db.execute(
        update(AuthorityDetailQueue)
        .where(
            AuthorityDetailQueue.status == "claimed",
            AuthorityDetailQueue.lease_expires_at < now,
        )
        .values(
            status="pending",
            reason_code="detail_lease_expired",
            lease_owner=None,
            lease_expires_at=None,
            updated_at=now,
        )
    )
    db.commit()
    recent_cutoff = evaluation_time - timedelta(days=settings.lead_new_days)
    candidate_ids = db.scalars(
        select(AuthorityDetailQueue.id)
        .join(AuthorityRecord, AuthorityRecord.record_id == AuthorityDetailQueue.record_id)
        .where(AuthorityDetailQueue.status == "pending")
        .order_by(
            case((AuthorityRecord.submission_date >= recent_cutoff, 0), else_=1),
            AuthorityRecord.submission_date.desc(),
            AuthorityDetailQueue.id,
        )
        .limit(max(1, min(limit or settings.detail_batch_size, 1000)))
    ).all()
    claim_owner = f"{settings.worker_id[:80]}:{uuid4().hex}"
    counts = {"completed": 0, "unchanged": 0, "blocked": 0}
    with client_factory(settings) as client:
        for queue_id in candidate_ids:
            claimed = db.execute(
                update(AuthorityDetailQueue)
                .where(
                    AuthorityDetailQueue.id == queue_id,
                    AuthorityDetailQueue.status == "pending",
                )
                .values(
                    status="claimed",
                    reason_code="detail_fetch_claimed",
                    lease_owner=claim_owner,
                    lease_expires_at=utcnow() + timedelta(seconds=settings.lease_seconds),
                    updated_at=utcnow(),
                )
            )
            db.commit()
            if getattr(claimed, "rowcount", 0) != 1:
                continue
            queue = db.scalar(
                select(AuthorityDetailQueue).where(
                    AuthorityDetailQueue.id == queue_id,
                    AuthorityDetailQueue.status == "claimed",
                    AuthorityDetailQueue.lease_owner == claim_owner,
                )
            )
            if not queue:
                continue
            record = db.scalar(
                select(AuthorityRecord).where(AuthorityRecord.record_id == queue.record_id)
            )
            if not record or record.current_payload_sha256 != queue.listing_payload_sha256:
                queue.status = "failed"
                queue.reason_code = "stale_listing_revision"
                queue.attempt_count += 1
                queue.lease_owner = None
                queue.lease_expires_at = None
                queue.updated_at = utcnow()
                db.commit()
                continue
            try:
                detail = client.fetch_detail(record.public_process_number)
                if not _detail_matches_record(detail, record):
                    raise ReaderBlocked("detail_identity_mismatch")
                normalized = detail.normalized()
                payload_hash = sha(normalized)
                existing = db.scalar(
                    select(AuthorityDetailRevision).where(
                        AuthorityDetailRevision.record_id == record.record_id,
                        AuthorityDetailRevision.payload_sha256 == payload_hash,
                    )
                )
                if existing:
                    detail_revision = existing
                    counts["unchanged"] += 1
                else:
                    record.current_detail_revision_no += 1
                    detail_revision = AuthorityDetailRevision(
                        detail_revision_id=f"etdrd-{uuid4().hex}",
                        record_id=record.record_id,
                        source_revision_id=queue.source_revision_id,
                        revision_no=record.current_detail_revision_no,
                        payload_sha256=payload_hash,
                        normalized_json=canonical_json(normalized),
                    )
                    db.add(detail_revision)
                    db.flush()
                    counts["completed"] += 1
                record.current_detail_payload_sha256 = payload_hash
                record.detail_status = "current"
                record.detail_checked_at = utcnow()
                queue.status = "completed"
                qualification = _lead_decision(
                    db,
                    settings,
                    detail,
                    record,
                    as_of=evaluation_time,
                )
                queue.reason_code = (
                    f"lead_qualified_{qualification.reason}"
                    if qualification.eligible
                    else f"lead_{qualification.reason}"
                )
                queue.attempt_count += 1
                queue.lease_owner = None
                queue.lease_expires_at = None
                queue.updated_at = utcnow()
                if qualification.eligible:
                    _queue_qualified_lead(
                        db,
                        settings,
                        detail=detail,
                        record=record,
                        detail_revision=detail_revision,
                        detail_payload_sha256=payload_hash,
                        qualification=qualification,
                    )
                db.commit()
                time.sleep(settings.request_delay_seconds)
            except ReaderBlocked as exc:
                db.rollback()
                blocked_queue = db.get(AuthorityDetailQueue, queue.id)
                blocked_record = db.scalar(
                    select(AuthorityRecord).where(AuthorityRecord.record_id == queue.record_id)
                )
                assert blocked_queue is not None
                if blocked_queue.lease_owner != claim_owner:
                    raise RuntimeError("detail_lease_lost") from exc
                blocked_queue.status = "blocked"
                blocked_queue.reason_code = exc.code
                blocked_queue.attempt_count += 1
                blocked_queue.lease_owner = None
                blocked_queue.lease_expires_at = None
                blocked_queue.updated_at = utcnow()
                if blocked_record:
                    blocked_record.detail_status = "blocked"
                    blocked_record.detail_checked_at = utcnow()
                db.commit()
                counts["blocked"] += 1
                continue
    return counts


def requalify_waiting_leads(
    db: Session,
    settings: ReaderSettings,
    *,
    limit: int = 500,
    as_of: datetime | None = None,
) -> dict[str, int]:
    if not settings.enabled or not settings.policy_authorized or not settings.policy_evidence_valid:
        raise ReaderBlocked("policy_authorization_required")
    if not settings.detail_enabled:
        raise ReaderBlocked("detail_reader_disabled")
    evaluated_at = _aware(as_of or utcnow())
    due_before = evaluated_at - timedelta(days=settings.lead_stalled_min_days)
    queue_ids = db.scalars(
        select(AuthorityDetailQueue.id)
        .join(AuthorityRecord, AuthorityRecord.record_id == AuthorityDetailQueue.record_id)
        .where(
            AuthorityDetailQueue.status == "completed",
            AuthorityDetailQueue.reason_code == "lead_waiting_for_no_completion_window",
            AuthorityRecord.detail_status == "current",
            AuthorityRecord.submission_date <= due_before,
        )
        .order_by(AuthorityDetailQueue.id)
        .limit(max(1, min(limit, 2000)))
    ).all()
    counts = {"qualified": 0, "ineligible": 0}
    for queue_id in queue_ids:
        queue = db.get(AuthorityDetailQueue, queue_id)
        if queue is None:
            continue
        record = db.scalar(
            select(AuthorityRecord).where(AuthorityRecord.record_id == queue.record_id)
        )
        if record is None:
            queue.status = "failed"
            queue.reason_code = "lead_requalification_record_missing"
            counts["ineligible"] += 1
            db.commit()
            continue
        detail_revision = db.scalar(
            select(AuthorityDetailRevision).where(
                AuthorityDetailRevision.record_id == record.record_id,
                AuthorityDetailRevision.revision_no == record.current_detail_revision_no,
            )
        )
        if detail_revision is None:
            queue.status = "failed"
            queue.reason_code = "lead_requalification_revision_missing"
            counts["ineligible"] += 1
            db.commit()
            continue
        detail = ETDRDetail.model_validate(json.loads(detail_revision.normalized_json))
        qualification = _lead_decision(
            db,
            settings,
            detail,
            record,
            as_of=evaluated_at,
        )
        queue.reason_code = (
            f"lead_qualified_{qualification.reason}"
            if qualification.eligible
            else f"lead_{qualification.reason}"
        )
        queue.updated_at = utcnow()
        if qualification.eligible:
            created = _queue_qualified_lead(
                db,
                settings,
                detail=detail,
                record=record,
                detail_revision=detail_revision,
                detail_payload_sha256=detail_revision.payload_sha256,
                qualification=qualification,
            )
            counts["qualified"] += int(created)
        else:
            counts["ineligible"] += 1
        db.commit()
    return counts


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
