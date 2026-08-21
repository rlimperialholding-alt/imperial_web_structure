from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .canonical_policy import (
    ACTIVE_CONTENT_BRANDS,
    IORA_EXECUTIVE_EMAIL,
    IORA_EXECUTIVE_NAME,
    SOURCE_LEDGER_ROUTE_COUNT,
    SOURCE_LEDGER_SHEET_ID,
    SOURCE_LEDGER_SPREADSHEET_ID,
    SPEC_VERSION,
    DailyGateResult,
    assert_policy_integrity,
)
from .models import (
    CanonicalGrowthDailyRun,
    DailyContentObligation,
    GrowthSignal,
    QuestionRadarTopic,
    SourceCatalogRevision,
    SourceCoverageAttempt,
)
from .registry import GrowthRegistryError, settings


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _manifest() -> tuple[dict[str, Any], str]:
    path = Path(settings().canonical_manifest_file)
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise GrowthRegistryError("Canonical source-ledger manifest is unreadable") from exc
    required = {
        "spreadsheet_id": SOURCE_LEDGER_SPREADSHEET_ID,
        "sheet_id": SOURCE_LEDGER_SHEET_ID,
        "route_count": SOURCE_LEDGER_ROUTE_COUNT,
    }
    if any(manifest.get(key) != value for key, value in required.items()):
        raise GrowthRegistryError("Canonical source-ledger manifest does not match policy")
    if not manifest.get("modified_time") or not manifest.get("catalog_sha256"):
        raise GrowthRegistryError("Canonical source-ledger manifest lacks version evidence")
    return manifest, hashlib.sha256(raw).hexdigest()


def _local_date(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(ZoneInfo(settings().timezone)).date()


def _bootstrap_content_obligations(db: Session, local_day: date) -> None:
    existing = set(
        db.scalars(
            select(DailyContentObligation.brand_id).where(
                DailyContentObligation.local_date == local_day
            )
        ).all()
    )
    for brand_id in ACTIVE_CONTENT_BRANDS:
        if brand_id not in existing:
            db.add(DailyContentObligation(local_date=local_day, brand_id=brand_id))
    db.flush()


def refresh_daily_run(db: Session, *, now: datetime | None = None) -> CanonicalGrowthDailyRun:
    assert_policy_integrity()
    current = now or datetime.now(UTC)
    local_day = _local_date(current)
    manifest, manifest_hash = _manifest()
    row = db.scalar(
        select(CanonicalGrowthDailyRun).where(CanonicalGrowthDailyRun.local_date == local_day)
    )
    if not row:
        row = CanonicalGrowthDailyRun(
            run_id=f"CGR-{uuid4().hex[:20].upper()}",
            local_date=local_day,
            spec_version=SPEC_VERSION,
            source_manifest_sha256=manifest_hash,
            source_route_catalog_size=int(manifest["route_count"]),
        )
        db.add(row)
        db.flush()
    _bootstrap_content_obligations(db, local_day)
    local_start = datetime.combine(local_day, datetime.min.time(), ZoneInfo(settings().timezone))
    start_utc = local_start.astimezone(UTC)
    row.route_attempts = int(
        db.scalar(
            select(func.count())
            .select_from(SourceCoverageAttempt)
            .where(SourceCoverageAttempt.started_at >= start_utc)
        )
        or 0
    )
    row.unique_leads = int(
        db.scalar(
            select(func.count())
            .select_from(GrowthSignal)
            .where(GrowthSignal.created_at >= start_utc)
        )
        or 0
    )
    row.question_topics = int(
        db.scalar(
            select(func.count())
            .select_from(QuestionRadarTopic)
            .where(QuestionRadarTopic.local_date == local_day)
        )
        or 0
    )
    row.content_brands = int(
        db.scalar(
            select(func.count(func.distinct(DailyContentObligation.brand_id))).where(
                DailyContentObligation.local_date == local_day,
                DailyContentObligation.status.in_(("release_passed", "published")),
            )
        )
        or 0
    )
    gate = DailyGateResult(
        route_attempts=row.route_attempts,
        unique_leads=row.unique_leads,
        question_topics=row.question_topics,
        content_brands=row.content_brands,
    )
    row.gate_errors_json = _canonical_json(gate.errors)
    row.status = "full" if gate.passed else "partial"
    row.internal_handoff_status = "required_pending"
    row.external_outreach_status = "blocked_until_adapter_test_and_release"
    row.external_publication_status = "blocked_until_adapter_test_and_release"
    row.detail_json = _canonical_json(
        {
            "executive": {"name": IORA_EXECUTIVE_NAME, "email": IORA_EXECUTIVE_EMAIL},
            "iora_mode": "internal_executive_review_only",
            "internal_handoff_always_required": True,
            "publication_does_not_replace_internal_handoff": True,
            "content_obligations_created": len(ACTIVE_CONTENT_BRANDS),
            "catalog_modified_time": manifest["modified_time"],
            "catalog_sha256": manifest["catalog_sha256"],
            "etdr_branches": [
                "NEW_OR_CHANGED_RECORD_DELTA",
                "ETDR_START_NOT_VERIFIED",
                "ETDR_COMPLETION_NOT_VERIFIED",
            ],
        }
    )
    row.completed_at = current
    db.commit()
    return row


def run_due(db: Session, *, now: datetime | None = None) -> CanonicalGrowthDailyRun | None:
    cfg = settings()
    if not cfg.canonical_wide_enabled:
        return None
    current = now or datetime.now(UTC)
    local_now = current.astimezone(ZoneInfo(cfg.timezone))
    hour, minute = (int(part) for part in cfg.canonical_daily_at.split(":"))
    if (local_now.hour, local_now.minute) < (hour, minute):
        return None
    local_day = local_now.date()
    existing = db.scalar(
        select(CanonicalGrowthDailyRun).where(CanonicalGrowthDailyRun.local_date == local_day)
    )
    if existing and existing.completed_at and existing.status == "full":
        return None
    return refresh_daily_run(db, now=current)


def readiness(db: Session) -> dict[str, Any]:
    try:
        manifest, manifest_hash = _manifest()
        manifest_state = "ok"
    except GrowthRegistryError as exc:
        manifest = {}
        manifest_hash = None
        manifest_state = str(exc)
    local_day = _local_date()
    row = db.scalar(
        select(CanonicalGrowthDailyRun).where(CanonicalGrowthDailyRun.local_date == local_day)
    )
    catalog = db.scalar(
        select(SourceCatalogRevision)
        .where(SourceCatalogRevision.status == "active")
        .order_by(SourceCatalogRevision.imported_at.desc())
        .limit(1)
    )
    return {
        "enabled": settings().canonical_wide_enabled,
        "spec_version": SPEC_VERSION,
        "source_ledger": {
            "spreadsheet_id": SOURCE_LEDGER_SPREADSHEET_ID,
            "sheet_id": SOURCE_LEDGER_SHEET_ID,
            "required_route_count": SOURCE_LEDGER_ROUTE_COUNT,
            "manifest": manifest_state,
            "manifest_sha256": manifest_hash,
            "catalog_modified_time": manifest.get("modified_time"),
            "db_runtime": (
                "active"
                if catalog and catalog.route_count == SOURCE_LEDGER_ROUTE_COUNT
                else "missing_or_incomplete"
            ),
            "db_catalog_sha256": catalog.catalog_sha256 if catalog else None,
            "db_route_count": catalog.route_count if catalog else 0,
        },
        "daily_gates": {
            "route_attempts": 800,
            "unique_leads": 100,
            "question_topics": 80,
            "content_brands": 19,
        },
        "iora": {
            "mode": "internal_executive_review_only",
            "recipient": IORA_EXECUTIVE_EMAIL,
            "autonomous_external_outreach": False,
        },
        "internal_handoff_always_required": True,
        "today": None
        if not row
        else {
            "run_id": row.run_id,
            "status": row.status,
            "route_attempts": row.route_attempts,
            "unique_leads": row.unique_leads,
            "question_topics": row.question_topics,
            "content_brands": row.content_brands,
            "gate_errors": json.loads(row.gate_errors_json),
        },
    }
