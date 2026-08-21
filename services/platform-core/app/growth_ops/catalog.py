from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .canonical_policy import (
    DAILY_ROUTE_ATTEMPT_MINIMUM,
    SOURCE_LEDGER_ROUTE_COUNT,
    SOURCE_LEDGER_SHEET_ID,
    SOURCE_LEDGER_SPREADSHEET_ID,
    contains_no_monitoring_entity,
)
from .models import SourceCatalogRevision, SourceCoverageAttempt, SourceCoverageRoute
from .registry import GrowthRegistryError, settings

BLOCKED_MARKERS = (
    "captcha",
    "access denied",
    "too many requests",
    "bejelentkezés",
    "jelentkezzen be",
    "paywall",
)


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _visible_text(body_text: str, limit: int) -> str:
    parser = _VisibleText()
    try:
        parser.feed(body_text)
        value = " ".join(parser.parts)
    except Exception:
        value = re.sub(r"<[^>]+>", " ", body_text)
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value: Any, limit: int | None = None) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    if not result:
        return None
    return result[:limit] if limit else result


def _load_manifest(path: str | Path) -> tuple[dict[str, Any], str]:
    manifest_path = Path(path)
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise GrowthRegistryError("Canonical source-ledger manifest is unreadable") from exc
    expected = {
        "spreadsheet_id": SOURCE_LEDGER_SPREADSHEET_ID,
        "sheet_id": SOURCE_LEDGER_SHEET_ID,
        "route_count": SOURCE_LEDGER_ROUTE_COUNT,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise GrowthRegistryError("Canonical source-ledger manifest does not match policy")
    return manifest, hashlib.sha256(raw).hexdigest()


def _records(snapshot_path: str | Path) -> tuple[list[dict[str, Any]], str]:
    path = Path(snapshot_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GrowthRegistryError("Canonical source-ledger snapshot is unreadable") from exc
    snapshot_sha = hashlib.sha256(raw).hexdigest()
    records: list[dict[str, Any]] = []
    route_keys: set[str] = set()
    route_ids: set[str] = set()
    try:
        lines = raw.decode("utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"record {line_number} is not an object")
            route_key = _text(record.get("RouteKey"), 500)
            route_id = _text(record.get("RouteID"), 180)
            route_url = _text(record.get("Útvonal URL"), 3000)
            motor = _text(record.get("Motor"), 160)
            if not route_key or not route_id or not route_url or not motor:
                raise ValueError(f"record {line_number} lacks a required route field")
            if route_key in route_keys or route_id in route_ids:
                raise ValueError(f"record {line_number} duplicates a route identity")
            parsed = urlparse(route_url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError(f"record {line_number} contains a non-HTTPS route")
            canonical = _canonical_json(record)
            if contains_no_monitoring_entity(canonical):
                raise GrowthRegistryError("no_monitoring_hard_gate")
            route_keys.add(route_key)
            route_ids.add(route_id)
            records.append(record)
    except GrowthRegistryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GrowthRegistryError("Canonical source-ledger snapshot is invalid") from exc
    if len(records) != SOURCE_LEDGER_ROUTE_COUNT:
        raise GrowthRegistryError("Canonical source-ledger route count mismatch")
    return records, snapshot_sha


def _row(record: dict[str, Any], catalog_sha256: str, now: datetime) -> dict[str, Any]:
    canonical = _canonical_json(record)
    catalog_status = _text(record.get("Katalógusstátusz"), 120)
    return {
        "route_key": _text(record.get("RouteKey"), 500),
        "route_id": _text(record.get("RouteID"), 180),
        "catalog_sha256": catalog_sha256,
        "motor": _text(record.get("Motor"), 160),
        "catalog_part": _text(record.get("Katalógusrész"), 160),
        "country": _text(record.get("Ország"), 120),
        "brand_fit": _text(record.get("Márkailleszkedés"), 240),
        "category": _text(record.get("Kategória"), 240),
        "source_name": _text(record.get("Forrás neve"), 500),
        "source_type": _text(record.get("Forrástípus"), 120),
        "search_signal": _text(record.get("Keresési jel/kifejezés")),
        "route_url": _text(record.get("Útvonal URL"), 3000),
        "base_url": _text(record.get("Alap URL"), 3000),
        "route_mode": _text(record.get("Útvonalmód"), 80),
        "priority": _text(record.get("Prioritás"), 80),
        "validation": _text(record.get("Validáció"), 120),
        "catalog_status": catalog_status,
        "source_updated_value": _text(record.get("Katalógus frissítése"), 120),
        "notes": _text(record.get("Megjegyzés")),
        "source_row_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "source_record_json": canonical,
        "enabled": (catalog_status or "").casefold() not in {"disabled", "retired"},
        "created_at": now,
        "updated_at": now,
    }


def _upsert_routes(db: Session, rows: list[dict[str, Any]]) -> None:
    dialect = db.get_bind().dialect.name
    insert_factory = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect)
    if not insert_factory:
        for values in rows:
            existing = db.scalar(
                select(SourceCoverageRoute).where(
                    SourceCoverageRoute.route_key == values["route_key"]
                )
            )
            if not existing:
                db.add(SourceCoverageRoute(**values))
                continue
            for key, value in values.items():
                if key not in {"created_at"}:
                    setattr(existing, key, value)
        return
    immutable_runtime = {
        "id",
        "created_at",
        "attempt_count",
        "success_count",
        "last_attempt_at",
        "last_success_at",
        "last_result",
        "next_due_at",
    }
    for start in range(0, len(rows), 500):
        statement = insert_factory(SourceCoverageRoute).values(rows[start : start + 500])
        updates = {
            column.name: getattr(statement.excluded, column.name)
            for column in SourceCoverageRoute.__table__.columns
            if column.name not in immutable_runtime
        }
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[SourceCoverageRoute.route_key],
                set_=updates,
            )
        )


def import_snapshot(
    db: Session,
    *,
    snapshot_path: str | Path,
    manifest_path: str | Path,
) -> SourceCatalogRevision:
    manifest, _manifest_sha = _load_manifest(manifest_path)
    records, snapshot_sha = _records(snapshot_path)
    if manifest.get("catalog_sha256") != snapshot_sha:
        raise GrowthRegistryError("Canonical source-ledger snapshot hash mismatch")
    now = datetime.now(UTC)
    rows = [_row(record, snapshot_sha, now) for record in records]
    revision = db.scalar(
        select(SourceCatalogRevision).where(
            SourceCatalogRevision.catalog_sha256 == snapshot_sha
        )
    )
    if not revision:
        revision = SourceCatalogRevision(
            revision_id=f"SCR-{uuid4().hex[:20].upper()}",
            spreadsheet_id=SOURCE_LEDGER_SPREADSHEET_ID,
            sheet_id=SOURCE_LEDGER_SHEET_ID,
            source_modified_time=str(manifest["modified_time"]),
            catalog_sha256=snapshot_sha,
            route_count=len(rows),
            status="importing",
            imported_at=now,
        )
        db.add(revision)
        db.flush()
    _upsert_routes(db, rows)
    db.execute(
        update(SourceCoverageRoute)
        .where(SourceCoverageRoute.catalog_sha256 != snapshot_sha)
        .values(enabled=False, updated_at=now)
    )
    db.execute(
        update(SourceCatalogRevision)
        .where(SourceCatalogRevision.catalog_sha256 != snapshot_sha)
        .values(status="retired")
    )
    active_count = int(
        db.scalar(
            select(func.count())
            .select_from(SourceCoverageRoute)
            .where(
                SourceCoverageRoute.catalog_sha256 == snapshot_sha,
                SourceCoverageRoute.enabled.is_(True),
            )
        )
        or 0
    )
    if active_count != SOURCE_LEDGER_ROUTE_COUNT:
        db.rollback()
        raise GrowthRegistryError("Imported active source-route count mismatch")
    revision.status = "active"
    revision.route_count = active_count
    revision.imported_at = now
    db.commit()
    return revision


def active_revision(db: Session) -> SourceCatalogRevision:
    revision = db.scalar(
        select(SourceCatalogRevision)
        .where(SourceCatalogRevision.status == "active")
        .order_by(SourceCatalogRevision.imported_at.desc())
        .limit(1)
    )
    if not revision or revision.route_count != SOURCE_LEDGER_ROUTE_COUNT:
        raise GrowthRegistryError("DB-native source catalog is not active")
    return revision


def _local_start(now: datetime) -> tuple[datetime, datetime]:
    zone = ZoneInfo(settings().timezone)
    local_now = now.astimezone(zone)
    hour, minute = (int(part) for part in settings().canonical_daily_at.split(":"))
    start_local = datetime.combine(local_now.date(), time(hour, minute), zone)
    return local_now, start_local


def _fetch(route: SourceCoverageRoute) -> dict[str, Any]:
    cfg = settings()
    parsed = urlparse(route.route_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return {"status": "rejected", "error_type": "invalid_route_url"}
    if contains_no_monitoring_entity(route.source_record_json):
        return {"status": "rejected", "error_type": "no_monitoring_hard_gate"}
    content = bytearray()
    try:
        with httpx.Client(
            timeout=cfg.canonical_route_timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": "Imperial-Source-Coverage/1.0"},
        ) as client:
            with client.stream("GET", route.route_url) as response:
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > cfg.canonical_route_max_response_bytes:
                        return {
                            "status": "blocked",
                            "http_status": response.status_code,
                            "error_type": "response_too_large",
                        }
                status_code = response.status_code
                content_type = response.headers.get("content-type", "")[:240]
    except httpx.HTTPError as exc:
        return {"status": "failed", "error_type": type(exc).__name__}
    body = bytes(content)
    body_text = body[:200_000].decode("utf-8", errors="ignore")
    lowered = body_text.casefold()
    blocked = status_code in {401, 403, 407, 429, 451} or any(
        marker in lowered for marker in BLOCKED_MARKERS
    )
    if blocked or 300 <= status_code < 400:
        result_status = "blocked"
    elif 200 <= status_code < 300 and body:
        result_status = "succeeded"
    else:
        result_status = "failed"
    title_match = re.search(r"<title[^>]*>(.*?)</title>", body_text, re.I | re.S)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip()[:500] if title_match else None
    return {
        "status": result_status,
        "http_status": status_code,
        "response_sha256": hashlib.sha256(body).hexdigest() if body else None,
        "evidence": {
            "content_bytes": len(body),
            "content_type": content_type,
            "title": title,
            "host": parsed.hostname,
        },
        # Transient only: the worker gives this bounded visible-text sample to the
        # evidence extractor, but never persists the full fetched page body.
        "analysis_text": _visible_text(
            body_text, getattr(cfg, "canonical_analysis_text_chars", 6000)
        )
        if result_status == "succeeded"
        else "",
    }


def scan_due_routes(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    cfg = settings()
    if not cfg.canonical_wide_enabled or not cfg.canonical_route_scanning_enabled:
        return {"status": "disabled", "attempted": 0}
    current = now or datetime.now(UTC)
    local_now, start_local = _local_start(current)
    if local_now < start_local:
        return {"status": "not_due", "attempted": 0}
    revision = active_revision(db)
    start_utc = start_local.astimezone(UTC)
    attempted_today = int(
        db.scalar(
            select(func.count())
            .select_from(SourceCoverageAttempt)
            .where(SourceCoverageAttempt.started_at >= start_utc)
        )
        or 0
    )
    elapsed_minutes = max(0.0, (local_now - start_local).total_seconds() / 60)
    paced_target = min(
        DAILY_ROUTE_ATTEMPT_MINIMUM,
        max(
            cfg.canonical_route_batch_size,
            int(elapsed_minutes / (18 * 60) * DAILY_ROUTE_ATTEMPT_MINIMUM),
        ),
    )
    allowance = min(
        cfg.canonical_route_batch_size,
        DAILY_ROUTE_ATTEMPT_MINIMUM - attempted_today,
        paced_target - attempted_today,
    )
    if allowance <= 0:
        return {
            "status": "on_pace",
            "attempted": 0,
            "attempted_today": attempted_today,
            "paced_target": paced_target,
        }
    candidates = db.scalars(
        select(SourceCoverageRoute)
        .where(
            SourceCoverageRoute.enabled.is_(True),
            SourceCoverageRoute.catalog_sha256 == revision.catalog_sha256,
            or_(
                SourceCoverageRoute.next_due_at.is_(None),
                SourceCoverageRoute.next_due_at <= current,
            ),
        )
        .order_by(
            case((SourceCoverageRoute.route_mode == "direct", 0), else_=1),
            SourceCoverageRoute.last_attempt_at.asc().nulls_first(),
            SourceCoverageRoute.priority.asc(),
            SourceCoverageRoute.id.asc(),
        )
        .limit(max(allowance * 5, allowance))
    ).all()
    selected: list[SourceCoverageRoute] = []
    hosts: set[str] = set()
    for route in candidates:
        host = (urlparse(route.route_url).hostname or "").casefold()
        if host in hosts:
            continue
        hosts.add(host)
        selected.append(route)
        if len(selected) >= allowance:
            break
    outcomes: dict[str, int] = {}
    for route in selected:
        started = datetime.now(UTC)
        result = _fetch(route)
        completed = datetime.now(UTC)
        status = str(result["status"])
        attempt = SourceCoverageAttempt(
            attempt_id=f"SCA-{uuid4().hex[:20].upper()}",
            route_key=route.route_key,
            catalog_sha256=revision.catalog_sha256,
            status=status,
            http_status=result.get("http_status"),
            response_sha256=result.get("response_sha256"),
            evidence_json=_canonical_json(result.get("evidence") or {}),
            error_type=result.get("error_type"),
            started_at=started,
            completed_at=completed,
        )
        db.add(attempt)
        db.flush()
        if status == "succeeded" and getattr(cfg, "canonical_processing_enabled", False):
            from .processing import process_source_attempt

            process_source_attempt(db, route=route, attempt=attempt, text=result["analysis_text"])
        elif status != "succeeded":
            attempt.analysis_status = "skipped"
        route.attempt_count += 1
        route.last_attempt_at = completed
        route.last_result = status
        route.next_due_at = completed + timedelta(days=1)
        route.updated_at = completed
        if status == "succeeded":
            route.success_count += 1
            route.last_success_at = completed
        elif status == "rejected":
            route.enabled = False
        outcomes[status] = outcomes.get(status, 0) + 1
    db.commit()
    return {
        "status": "attempted" if selected else "no_due_routes",
        "attempted": len(selected),
        "attempted_today": attempted_today + len(selected),
        "paced_target": paced_target,
        "outcomes": outcomes,
    }
