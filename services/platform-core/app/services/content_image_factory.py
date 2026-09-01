from __future__ import annotations

import hashlib
import http.client
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..copy_gate.models import PublicationState, VisualProductionSubmission
from ..models import (
    ContentAssetRecord,
    ContentImageFactoryRequest,
    CopyBriefRecord,
    CreativeProductionRunRecord,
)
from .content_quality import submit_visual_production

TERMINAL_REQUEST_STATES = {"IMPORTED", "BLOCKED", "STALE"}
POLLABLE_REQUEST_STATES = {"SUBMITTED", "PROCESSING", "NEEDS_REVIEW", "FAILED"}
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAX_RETRIES = 5


class PermanentImageFactoryError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _api_json(method: str, path: str, payload: dict | None = None) -> dict:
    body = _json(payload).encode("utf-8") if payload is not None else None
    connection = http.client.HTTPConnection(
        settings.content_image_factory_host,
        settings.content_image_factory_port,
        timeout=settings.content_image_factory_timeout_seconds,
    )
    try:
        connection.request(
            method,
            path,
            body=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-API-Key": settings.image_factory_api_token,
            },
        )
        response = connection.getresponse()
        raw = response.read(MAX_DOWNLOAD_BYTES + 1)
    finally:
        connection.close()
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Az Image Factory JSON-válasza túllépte a méretkorlátot.")
    if response.status < 200 or response.status >= 300:
        raise ValueError(
            f"Image Factory HTTP {response.status}: {raw[:1000].decode('utf-8', 'replace')}"
        )
    parsed = json.loads(raw or b"{}")
    if not isinstance(parsed, dict):
        raise TypeError("Az Image Factory válasza nem JSON objektum.")
    return parsed


def _download_asset(job_id: str, role: str) -> tuple[bytes, dict[str, str]]:
    connection = http.client.HTTPConnection(
        settings.content_image_factory_host,
        settings.content_image_factory_port,
        timeout=settings.content_image_factory_timeout_seconds,
    )
    try:
        connection.request(
            "GET",
            f"/api/v1/jobs/{job_id}/assets/{role}",
            headers={"X-API-Key": settings.image_factory_api_token},
        )
        response = connection.getresponse()
        raw = response.read(MAX_DOWNLOAD_BYTES + 1)
        headers = {key.lower(): value for key, value in response.getheaders()}
    finally:
        connection.close()
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise PermanentImageFactoryError("Az Image Factory-kép túllépte a 25 MB-os korlátot.")
    if response.status != 200:
        raise ValueError(
            f"Image Factory asset HTTP {response.status}: {raw[:1000].decode('utf-8', 'replace')}"
        )
    return raw, headers


def _safe_json(raw: str) -> dict:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise PermanentImageFactoryError("Sérült Content Factory JSON-adat.") from exc
    if not isinstance(value, dict):
        raise PermanentImageFactoryError("A Content Factory JSON-adat nem objektum.")
    return value


def _words(value: object, *, maximum: int = 10) -> str:
    return " ".join(str(value or "").strip().split()[:maximum])


def _request_payload(
    asset: ContentAssetRecord, brief_row: CopyBriefRecord
) -> tuple[dict, str, str]:
    content = _safe_json(asset.content_json)
    brief = _safe_json(brief_row.brief_json)
    trace = _safe_json(asset.generation_trace_json)
    blocks = content.get("content_blocks") or []
    if isinstance(blocks, list) and len(blocks) > 1:
        raise PermanentImageFactoryError(
            "A többoldalas vagy többblokkos csomagot külön ContentAssetekre kell bontani; "
            "egy kép nem fedhet le több önálló tartalmat."
        )
    if (
        trace.get("typehouse_offer_creative") is True
        or brief.get("house_plan_id")
        or brief.get("product_id")
    ):
        raise PermanentImageFactoryError(
            "Típusház- vagy termékspecifikus vizuálhoz hiteles forráskép szükséges; "
            "generikus Image Factory-kép nem helyettesítheti."
        )
    topic = _words(content.get("title") or brief.get("primary_promise"), maximum=80)
    if len(topic) < 2:
        raise PermanentImageFactoryError("A képgeneráláshoz hiányzik az ellenőrzött téma.")
    operational_title = _words(content.get("title") or topic, maximum=10)
    direction = {
        key: trace.get(key)
        for key in (
            "visual_direction_id",
            "image_treatment",
            "background_treatment",
            "primary_subject_dominance_required",
            "primary_text_zone",
        )
        if trace.get(key) not in {None, ""}
    }
    context = {
        "brand_id": asset.brand_id,
        "asset_type": asset.asset_type,
        "channel": asset.channel,
        "purpose": content.get("purpose") or brief.get("purpose"),
        "campaign_objective": brief.get("campaign_objective"),
        "desired_outcome": brief.get("desired_outcome"),
        "primary_promise": brief.get("primary_promise"),
        "visual_direction": direction,
    }
    source_brief = (
        "Készíts egyetlen koherens, fotórealisztikus, felirat- és logómentes jelenetet az "
        "ellenőrzött Content Factory assethez. Ne készíts kollázst vagy többpaneles képet. "
        "Belső, hash-kötött vizuális kontextus: " + _json(context)
    )
    social = asset.channel.lower() in {"facebook", "instagram", "meta", "social"}
    return (
        {
            "topic": topic[:500],
            "title": operational_title[:220],
            "article_slug": asset.asset_id.lower().replace("_", "-")[:180],
            "content_id": asset.asset_id,
            "image_role": "facebook" if social else "hero",
            "source_brief": source_brief[:8000],
            "target_aspect_ratio": "1:1" if social else "16:9",
        },
        "facebook" if social else "hero",
        "square" if social else "web_hero",
    )


def queue_eligible_content_assets(db: Session, *, limit: int = 500) -> dict[str, int]:
    assets = db.scalars(
        select(ContentAssetRecord)
        .where(ContentAssetRecord.state == PublicationState.VISUAL_PRODUCTION)
        .order_by(ContentAssetRecord.created_at, ContentAssetRecord.id)
        .limit(max(1, min(limit, 1000)))
    ).all()
    queued = blocked = existing = 0
    for asset in assets:
        if db.scalar(
            select(ContentImageFactoryRequest).where(
                ContentImageFactoryRequest.asset_id == asset.asset_id,
                ContentImageFactoryRequest.content_version == asset.content_version,
            )
        ):
            existing += 1
            continue
        if db.scalar(
            select(CreativeProductionRunRecord).where(
                CreativeProductionRunRecord.asset_id == asset.asset_id,
                CreativeProductionRunRecord.content_version == asset.content_version,
            )
        ):
            existing += 1
            continue
        brief = db.get(CopyBriefRecord, asset.copy_brief_id)
        if not brief:
            request_payload = {"blocked_reason": "A CopyBrief rekord hiányzik."}
            requested_role = "hero"
            output_role = "web_hero"
            status = "BLOCKED"
            last_error = request_payload["blocked_reason"]
        else:
            try:
                request_payload, requested_role, output_role = _request_payload(asset, brief)
                status = "QUEUED"
                last_error = None
            except PermanentImageFactoryError as exc:
                request_payload = {"blocked_reason": str(exc)}
                requested_role = "hero"
                output_role = "web_hero"
                status = "BLOCKED"
                last_error = str(exc)
        row = ContentImageFactoryRequest(
            request_id=f"CIF-{uuid.uuid4().hex[:16].upper()}",
            asset_id=asset.asset_id,
            content_version=asset.content_version,
            content_sha256=asset.content_hash,
            status=status,
            requested_role=requested_role,
            output_role=output_role,
            request_payload_json=_json(request_payload),
            last_error=last_error,
            next_attempt_at=utcnow() if status == "QUEUED" else None,
        )
        db.add(row)
        audit(
            db,
            actor="content-image-factory-worker",
            action=(
                "content_image_generation_queued"
                if status == "QUEUED"
                else "content_image_generation_blocked"
            ),
            entity_type="content_image_factory_request",
            entity_id=row.request_id,
            after={
                "asset_id": asset.asset_id,
                "content_version": asset.content_version,
                "content_sha256": asset.content_hash,
                "status": status,
                "reason": last_error,
            },
        )
        queued += int(status == "QUEUED")
        blocked += int(status == "BLOCKED")
    db.commit()
    return {"queued": queued, "blocked": blocked, "existing": existing}


def _retry_later(row: ContentImageFactoryRequest, error: Exception, status: str) -> None:
    row.attempt_count += 1
    row.last_error = str(error)[:2000]
    if isinstance(error, PermanentImageFactoryError) or row.attempt_count >= MAX_RETRIES:
        row.status = "FAILED"
        row.next_attempt_at = None
        return
    row.status = status
    row.next_attempt_at = utcnow() + timedelta(minutes=2 ** min(row.attempt_count, 6))


def submit_queued_batches(db: Session) -> dict[str, int]:
    now = utcnow()
    rows = db.scalars(
        select(ContentImageFactoryRequest)
        .where(
            ContentImageFactoryRequest.status == "QUEUED",
            (ContentImageFactoryRequest.next_attempt_at.is_(None))
            | (ContentImageFactoryRequest.next_attempt_at <= now),
        )
        .order_by(ContentImageFactoryRequest.created_at)
        .limit(settings.content_image_factory_batch_size)
        .with_for_update(skip_locked=True)
    ).all()
    if not rows:
        return {"submitted": 0, "submit_failed": 0}
    items = [_safe_json(row.request_payload_json) for row in rows]
    request_fingerprint = [
        f"{row.asset_id}:{row.content_version}:{row.content_sha256}" for row in rows
    ]
    idempotency_key = (
        "content-factory-daily-"
        + hashlib.sha256("\n".join(request_fingerprint).encode("utf-8")).hexdigest()
    )
    payload = {
        "idempotency_key": idempotency_key,
        "source_type": "content_factory_daily",
        "upload_to_drive": True,
        "items": items,
    }
    try:
        response = _api_json("POST", "/api/v1/batches", payload)
        batch_id = str(response.get("batch_id") or "")
        jobs = response.get("jobs") or []
        jobs_by_content = {str(job.get("content_id")): job for job in jobs if isinstance(job, dict)}
        if not batch_id or set(jobs_by_content) != {row.asset_id for row in rows}:
            raise PermanentImageFactoryError(
                "Az Image Factory batch-válasz nem képezhető vissza pontosan a ContentAssetekre."
            )
    except Exception as exc:  # noqa: BLE001 - durable queue retries transport/protocol failures
        for row in rows:
            _retry_later(row, exc, "QUEUED")
        db.commit()
        return {"submitted": 0, "submit_failed": len(rows)}
    for row in rows:
        job = jobs_by_content[row.asset_id]
        row.idempotency_key = idempotency_key
        row.image_factory_batch_id = batch_id
        row.image_factory_job_id = str(job["job_id"])
        row.status = "SUBMITTED"
        row.response_json = _json(job)
        row.attempt_count = 0
        row.last_error = None
        row.submitted_at = now
        row.next_attempt_at = now + timedelta(seconds=15)
    audit(
        db,
        actor="content-image-factory-worker",
        action="content_image_batch_submitted",
        entity_type="content_image_factory_batch",
        entity_id=batch_id,
        after={
            "idempotency_key": idempotency_key,
            "asset_ids": [row.asset_id for row in rows],
            "job_count": len(rows),
            "release_state": "TEST_ONLY_REVIEW_REQUIRED",
        },
    )
    db.commit()
    return {"submitted": len(rows), "submit_failed": 0}


def _persist_asset(run_id: str, raw: bytes, media_type: str) -> Path:
    suffix = ".png" if media_type == "image/png" else ".jpg"
    root = Path(settings.content_image_factory_asset_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{run_id}{suffix}"
    temporary = root / f".{run_id}.{uuid.uuid4().hex}.tmp"
    temporary.write_bytes(raw)
    os.replace(temporary, target)
    return target


def _import_completed_job(
    db: Session,
    row: ContentImageFactoryRequest,
    job: dict,
) -> None:
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == row.asset_id))
    if (
        not asset
        or asset.content_version != row.content_version
        or asset.content_hash != row.content_sha256
    ):
        raise PermanentImageFactoryError(
            "A ContentAsset megváltozott az Image Factory-kérés óta; a képet nem lehet importálni."
        )
    if asset.state != PublicationState.VISUAL_PRODUCTION:
        raise PermanentImageFactoryError(
            f"A ContentAsset már nincs VISUAL_PRODUCTION állapotban: {asset.state}."
        )
    if db.scalar(
        select(CreativeProductionRunRecord).where(
            CreativeProductionRunRecord.asset_id == asset.asset_id,
            CreativeProductionRunRecord.content_version == asset.content_version,
        )
    ):
        raise PermanentImageFactoryError(
            "A ContentAssethez időközben másik kreatív futás került rögzítésre."
        )
    if job.get("release_state") != "TEST_ONLY_REVIEW_REQUIRED":
        raise PermanentImageFactoryError(
            "Az automatikus import csak TEST_ONLY_REVIEW_REQUIRED release state-et fogad."
        )
    meta = (job.get("derived_assets") or {}).get(row.output_role) or {}
    expected_sha256 = str(meta.get("sha256") or "")
    dimensions = meta.get("dimensions") or []
    if len(expected_sha256) != 64 or len(dimensions) != 2:
        raise PermanentImageFactoryError("Hiányos Image Factory asset-metaadat.")
    raw, headers = _download_asset(str(row.image_factory_job_id), row.output_role)
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if (
        actual_sha256 != expected_sha256
        or headers.get("x-content-sha256") != expected_sha256
        or headers.get("x-release-state") != "TEST_ONLY_REVIEW_REQUIRED"
    ):
        raise PermanentImageFactoryError(
            "Az Image Factory asset hash- vagy release-ellenőrzése hibás."
        )
    try:
        with Image.open(BytesIO(raw)) as image:
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            actual_dimensions = list(image.size)
    except Exception as exc:
        raise PermanentImageFactoryError("Az Image Factory-kimenet nem érvényes kép.") from exc
    if actual_dimensions != [int(dimensions[0]), int(dimensions[1])]:
        raise PermanentImageFactoryError("Az Image Factory képmérete nem egyezik a metaadattal.")
    run_id = f"IMGF-{str(row.image_factory_job_id).replace('-', '')[:24].upper()}"
    media_type = headers.get("content-type", "image/jpeg").split(";", 1)[0]
    _persist_asset(run_id, raw, media_type)
    trace = _safe_json(asset.generation_trace_json)
    direction_base = str(trace.get("visual_direction_id") or "content-factory")
    direction_suffix = hashlib.sha256(row.request_id.encode("utf-8")).hexdigest()[:12]
    visual_direction_id = f"{direction_base[:140]}-{direction_suffix}"
    generated_prompt = str(job.get("generated_prompt") or "")
    submit_visual_production(
        db,
        asset.asset_id,
        VisualProductionSubmission(
            generation_run_id=run_id,
            producer_identity="imperial-image-factory",
            visual_direction_id=visual_direction_id,
            platform=asset.channel,
            width_px=actual_dimensions[0],
            height_px=actual_dimensions[1],
            output_uri=f"/marketing/assets/{asset.asset_id}/creative/{run_id}",
            output_sha256=actual_sha256,
            generation_prompt_hash=hashlib.sha256(generated_prompt.encode("utf-8")).hexdigest(),
            contains_text=False,
        ),
        actor="content-image-factory-worker",
    )
    row.status = "IMPORTED"
    row.response_json = _json(job)
    row.output_uri = f"/marketing/assets/{asset.asset_id}/creative/{run_id}"
    row.output_sha256 = actual_sha256
    row.qa_score = int(job["qa_score"]) if job.get("qa_score") is not None else None
    row.release_state = str(job["release_state"])
    row.last_error = None
    row.next_attempt_at = None
    row.completed_at = utcnow()
    audit(
        db,
        actor="content-image-factory-worker",
        action="content_image_imported_for_director_qa",
        entity_type="content_image_factory_request",
        entity_id=row.request_id,
        after={
            "asset_id": asset.asset_id,
            "image_factory_batch_id": row.image_factory_batch_id,
            "image_factory_job_id": row.image_factory_job_id,
            "output_role": row.output_role,
            "output_sha256": actual_sha256,
            "release_state": row.release_state,
            "content_state": PublicationState.CREATIVE_DIRECTOR_QA,
        },
    )
    db.commit()


def poll_submitted_batches(db: Session, *, batch_limit: int = 20) -> dict[str, int]:
    now = utcnow()
    rows = db.scalars(
        select(ContentImageFactoryRequest)
        .where(
            ContentImageFactoryRequest.status.in_(POLLABLE_REQUEST_STATES),
            ContentImageFactoryRequest.image_factory_batch_id.is_not(None),
            ContentImageFactoryRequest.next_attempt_at.is_not(None),
            ContentImageFactoryRequest.next_attempt_at <= now,
        )
        .order_by(ContentImageFactoryRequest.updated_at)
        .limit(max(1, min(batch_limit, 100)) * settings.content_image_factory_batch_size)
    ).all()
    by_batch: dict[str, list[ContentImageFactoryRequest]] = {}
    for row in rows:
        by_batch.setdefault(str(row.image_factory_batch_id), []).append(row)
    imported = processing = needs_review = failed = 0
    for batch_id, batch_rows in list(by_batch.items())[:batch_limit]:
        try:
            response = _api_json("GET", f"/api/v1/batches/{batch_id}")
            jobs_by_id = {
                str(job.get("job_id")): job
                for job in response.get("jobs") or []
                if isinstance(job, dict)
            }
        except Exception as exc:  # noqa: BLE001 - durable queue retries transport/protocol failures
            for row in batch_rows:
                _retry_later(row, exc, row.status)
                failed += int(row.status == "FAILED")
            db.commit()
            continue
        for row in batch_rows:
            job = jobs_by_id.get(str(row.image_factory_job_id))
            if not job:
                _retry_later(
                    row,
                    PermanentImageFactoryError("Az Image Factory-job eltűnt a batchből."),
                    row.status,
                )
                failed += 1
                continue
            row.response_json = _json(job)
            row.qa_score = int(job["qa_score"]) if job.get("qa_score") is not None else None
            row.release_state = str(job.get("release_state") or "") or None
            external_status = str(job.get("status") or "")
            if external_status == "COMPLETED":
                try:
                    _import_completed_job(db, row, job)
                    imported += 1
                except PermanentImageFactoryError as exc:
                    row.status = "STALE" if "megváltozott" in str(exc) else "FAILED"
                    row.last_error = str(exc)[:2000]
                    row.next_attempt_at = None
                    failed += 1
                    db.commit()
                except Exception as exc:  # noqa: BLE001 - one bad job must not stop the batch
                    _retry_later(row, exc, "PROCESSING")
                    failed += int(row.status == "FAILED")
                    db.commit()
            elif external_status == "NEEDS_REVIEW":
                row.status = "NEEDS_REVIEW"
                row.last_error = str(job.get("error_message") or "Image Factory review szükséges")
                row.next_attempt_at = now + timedelta(minutes=5)
                needs_review += 1
            elif external_status == "FAILED":
                row.status = "FAILED"
                row.last_error = str(job.get("error_message") or "Image Factory job sikertelen")
                row.next_attempt_at = now + timedelta(minutes=5)
                failed += 1
            else:
                row.status = "PROCESSING"
                row.last_error = None
                row.next_attempt_at = now + timedelta(seconds=30)
                processing += 1
        db.commit()
    return {
        "imported": imported,
        "processing": processing,
        "needs_review": needs_review,
        "failed": failed,
    }


def process_content_image_factory(db: Session) -> dict[str, int]:
    if not settings.content_image_factory_enabled:
        return {
            "enabled": 0,
            "queued": 0,
            "blocked": 0,
            "existing": 0,
            "submitted": 0,
            "submit_failed": 0,
            "imported": 0,
            "processing": 0,
            "needs_review": 0,
            "failed": 0,
        }
    queued = queue_eligible_content_assets(db)
    submitted = submit_queued_batches(db)
    polled = poll_submitted_batches(db)
    return {"enabled": 1, **queued, **submitted, **polled}


def serialize_request(row: ContentImageFactoryRequest) -> dict[str, Any]:
    return {
        "request_id": row.request_id,
        "asset_id": row.asset_id,
        "content_version": row.content_version,
        "content_sha256": row.content_sha256,
        "status": row.status,
        "image_factory_batch_id": row.image_factory_batch_id,
        "image_factory_job_id": row.image_factory_job_id,
        "requested_role": row.requested_role,
        "output_role": row.output_role,
        "output_uri": row.output_uri,
        "output_sha256": row.output_sha256,
        "qa_score": row.qa_score,
        "release_state": row.release_state,
        "last_error": row.last_error,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def list_requests(
    db: Session, *, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    query = select(ContentImageFactoryRequest)
    if status:
        query = query.where(ContentImageFactoryRequest.status == status)
    rows = db.scalars(
        query.order_by(ContentImageFactoryRequest.created_at.desc()).limit(max(1, min(limit, 500)))
    ).all()
    return [serialize_request(row) for row in rows]
