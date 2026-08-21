from __future__ import annotations

import hashlib
import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..models import (
    HouseVisionFactoryArtifact,
    HouseVisionFactoryImport,
    HouseVisionFactoryImportItem,
    HouseVisionFactoryJob,
    HouseVisionFactoryQARun,
    HouseVisionFactoryStream,
    HouseVisionJob,
    HouseVisionRightsPolicy,
)
from ..schemas import TypehouseArtifactIn, TypehouseJobIn, TypehouseQARunIn
from .housevision import AUTO_APPROVED_SOURCE_DOMAINS, automatic_rights_grant_for_host

TERMINAL = {"COMPLETED", "NEEDS_REVIEW", "BLOCKED", "FAILED"}
ACTIVE = {
    "RIGHTS_VALIDATION",
    "EXTRACTING",
    "SOURCE_QA",
    "NORMALIZING",
    "GEOMETRY_LOCKED",
    "RENDERING",
    "FLOORPLAN_ENRICHMENT",
    "WEB_EXPORT",
    "QA_PASS_1",
    "QA_PASS_2",
    "REPAIR_REQUIRED",
    "REPAIRING",
}
ALLOWED_RIGHTS = {"owned", "licensed", "partner_permission", "open_license"}
REQUIRED_ARTIFACT_ROLES = {
    "source_manifest",
    "geometry_lock",
    "metadata",
    "life_situations",
    "floorplan_clean",
    "floorplan_catalog",
    "master_8k",
    "responsive_avif",
    "responsive_webp",
    "repair_log",
    "package_manifest",
}
EXTRADOM_HOSTS = {"extradom.pl", "www.extradom.pl"}
EXTRADOM_PATH = re.compile(r"^/projekt-domu-[a-z0-9-]+-([A-Za-z0-9]+)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVIEW_ERRORS = {
    "SOURCE_ASSET_REVIEW_REQUIRED",
    "VISUAL_RENDER_REVIEW_REQUIRED",
    "VISUAL_QA_REVIEW_REQUIRED",
}


class TypehouseError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def utcnow() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:16].upper()}"


def _sha(value: bytes | str) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _validated_sha(value: str) -> str:
    normalized = value.strip().lower()
    if not SHA256_RE.fullmatch(normalized):
        raise TypehouseError("PACKAGE_BINDING_FAIL", "Érvényes SHA-256 lenyomat szükséges.")
    return normalized


def _safe_catalog(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,159}", normalized):
        raise TypehouseError("INVALID_CATALOG_ID", "A catalog_id nem slug-safe.", 422)
    return normalized


def _resolve_rights_grant(canonical_url: str, requested_grant: str) -> str:
    normalized = requested_grant.strip()
    if normalized and normalized.lower() != "auto":
        return normalized
    host = urlsplit(canonical_url).hostname or ""
    automatic = automatic_rights_grant_for_host(host)
    if not automatic:
        raise TypehouseError(
            "RIGHTS_SCOPE_FAIL",
            "Ehhez a domainhez explicit rights_grant_id szükséges.",
            422,
        )
    return automatic


def _resolved_public_addresses(host: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        results = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise TypehouseError("SOURCE_IDENTITY_FAIL", "A forrásdomain nem oldható fel.") from exc
    addresses = {ipaddress.ip_address(result[4][0]) for result in results}
    if not addresses or any(not address.is_global for address in addresses):
        raise TypehouseError(
            "SOURCE_IDENTITY_FAIL",
            "Privát, loopback, link-local, reserved vagy multicast cél tiltott.",
        )
    return addresses


def canonicalize_source_url(value: str) -> tuple[str, str | None]:
    raw = value.strip()
    if len(raw) > 1600:
        raise TypehouseError("SOURCE_IDENTITY_FAIL", "A forrás URL túl hosszú.", 422)
    parsed = urlsplit(raw)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise TypehouseError("SOURCE_IDENTITY_FAIL", "Kizárólag HTTPS forrásoldal fogadható.", 422)
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise TypehouseError("SOURCE_IDENTITY_FAIL", "Userinfo és egyedi port tiltott.", 422)
    if parsed.query or parsed.fragment:
        raise TypehouseError("SOURCE_IDENTITY_FAIL", "Query és fragment tiltott.", 422)
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise TypehouseError("SOURCE_IDENTITY_FAIL", "Érvénytelen IDNA host.", 422) from exc
    if host.endswith(".") or host.startswith(".") or ".." in host:
        raise TypehouseError("SOURCE_IDENTITY_FAIL", "Megtévesztő host tiltott.", 422)
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise TypehouseError("SOURCE_IDENTITY_FAIL", "Belső vagy metadata host tiltott.", 422)
    path = parsed.path or "/"
    if not path.startswith("/") or "//" in path or "%" in path:
        raise TypehouseError(
            "SOURCE_IDENTITY_FAIL", "Kódolt vagy kétperjeles útvonal tiltott.", 422
        )
    segments = PurePosixPath(path).parts
    if any(segment in {".", ".."} for segment in segments):
        raise TypehouseError("SOURCE_IDENTITY_FAIL", "Dot-segment tiltott.", 422)
    project_code: str | None = None
    if host in EXTRADOM_HOSTS:
        match = EXTRADOM_PATH.fullmatch(path.rstrip("/"))
        if not match:
            raise TypehouseError(
                "SOURCE_IDENTITY_FAIL",
                "Extradom esetén csak kanonikus projekt-domu oldal engedett.",
                422,
            )
        path = path.rstrip("/")
        project_code = match.group(1).upper()
    canonical = urlunsplit(("https", host, path, "", ""))
    return canonical, project_code


def _ensure_stream(db: Session, catalog_id: str, actor: str) -> HouseVisionFactoryStream:
    stream = db.scalar(
        select(HouseVisionFactoryStream).where(HouseVisionFactoryStream.catalog_id == catalog_id)
    )
    if stream:
        return stream
    stream = HouseVisionFactoryStream(
        stream_id=_id("HVSTREAM"), catalog_id=catalog_id, created_by=actor
    )
    db.add(stream)
    db.flush()
    return stream


def create_source_import(
    db: Session,
    *,
    catalog_id: str,
    rights_grant_id: str,
    source_urls: list[str],
    actor: str,
    source_file_name: str | None = None,
) -> HouseVisionFactoryImport:
    catalog_id = _safe_catalog(catalog_id)
    requested_grant = rights_grant_id.strip()
    if not 1 <= len(source_urls) <= 1000:
        raise TypehouseError("IMPORT_SIZE_INVALID", "Egy import 1–1000 URL-t tartalmazhat.", 422)
    stream = _ensure_stream(db, catalog_id, actor)
    normalized: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    duplicates = 0
    for source_url in source_urls:
        canonical, _ = canonicalize_source_url(source_url)
        grant = _resolve_rights_grant(canonical, requested_grant)
        digest = _sha(canonical)
        if digest in seen:
            duplicates += 1
            continue
        seen.add(digest)
        normalized.append((canonical, digest, grant))
    existing = set(
        db.scalars(
            select(HouseVisionFactoryImportItem.requested_url_sha256).where(
                HouseVisionFactoryImportItem.catalog_id == catalog_id,
                HouseVisionFactoryImportItem.requested_url_sha256.in_(
                    [digest for _, digest, _ in normalized]
                ),
            )
        )
    )
    rows = [(url, digest, grant) for url, digest, grant in normalized if digest not in existing]
    duplicates += len(normalized) - len(rows)
    source_sha = _sha("\n".join(url for url, _, _ in normalized))
    record = HouseVisionFactoryImport(
        import_id=_id("HVI"),
        stream_id=stream.stream_id,
        catalog_id=catalog_id,
        source_file_name=source_file_name,
        source_sha256=source_sha,
        requested_count=len(source_urls),
        registered_count=len(rows),
        duplicate_count=duplicates,
        status="REGISTERED" if rows else "COMPLETED",
        created_by=actor,
    )
    db.add(record)
    db.flush()
    for sequence, (url, digest, grant) in enumerate(rows, start=1):
        db.add(
            HouseVisionFactoryImportItem(
                import_item_id=_id("HVII"),
                import_id=record.import_id,
                stream_id=stream.stream_id,
                catalog_id=catalog_id,
                sequence=sequence,
                requested_url=url,
                requested_url_sha256=digest,
                rights_grant_id=grant,
                status="PENDING",
            )
        )
    audit(
        db,
        actor=actor,
        action="housevision.factory.import.create",
        entity_type="housevision_factory_import",
        entity_id=record.import_id,
        after={
            "catalog_id": catalog_id,
            "requested": len(source_urls),
            "registered": len(rows),
            "duplicates": duplicates,
            "source_sha256": source_sha,
        },
    )
    db.commit()
    db.refresh(record)
    return record


def create_job(
    db: Session,
    payload: TypehouseJobIn,
    *,
    idempotency_key: str,
    actor: str,
    import_item_id: str | None = None,
) -> HouseVisionFactoryJob:
    if not idempotency_key.strip():
        raise TypehouseError("IDEMPOTENCY_REQUIRED", "Idempotency-Key fejléc szükséges.", 428)
    canonical, project_code = canonicalize_source_url(payload.source_url)
    rights_grant_id = _resolve_rights_grant(canonical, payload.rights_grant_id)
    catalog_id = _safe_catalog(payload.catalog_id)
    existing = db.scalar(
        select(HouseVisionFactoryJob).where(
            HouseVisionFactoryJob.idempotency_key == idempotency_key
        )
    )
    if existing:
        if existing.canonical_url != canonical or existing.catalog_id != catalog_id:
            raise TypehouseError(
                "IDEMPOTENCY_CONFLICT",
                "Az Idempotency-Key másik kanonikus forráshoz tartozik.",
            )
        return existing
    stream = _ensure_stream(db, catalog_id, actor)
    source_revision_hash = _sha(canonical)
    latest_revision = (
        db.scalar(
            select(func.max(HouseVisionFactoryJob.job_revision)).where(
                HouseVisionFactoryJob.catalog_id == catalog_id,
                HouseVisionFactoryJob.canonical_url == canonical,
            )
        )
        or 0
    )
    if latest_revision and not payload.regenerate:
        prior = db.scalar(
            select(HouseVisionFactoryJob)
            .where(
                HouseVisionFactoryJob.catalog_id == catalog_id,
                HouseVisionFactoryJob.canonical_url == canonical,
            )
            .order_by(HouseVisionFactoryJob.job_revision.desc())
        )
        if prior:
            return prior
    revision = latest_revision + 1
    row = HouseVisionFactoryJob(
        job_id=_id("HVJ"),
        job_revision=revision,
        stream_id=stream.stream_id,
        catalog_id=catalog_id,
        import_item_id=import_item_id,
        idempotency_key=idempotency_key,
        requested_url=payload.source_url,
        canonical_url=canonical,
        requested_url_sha256=_sha(payload.source_url.strip()),
        source_revision_hash=source_revision_hash,
        source_page_id="HVSP-" + _sha(canonical)[:24].upper(),
        project_code=project_code,
        rights_grant_id=rights_grant_id,
        visual_profile_id=payload.visual_profile_id,
        output_profile_id=payload.output_profile_id,
        render_provider=settings.typehouse_factory_render_provider,
        status="PENDING",
        stage="PENDING",
        created_by=actor,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise TypehouseError("IDEMPOTENCY_CONFLICT", "Ütköző HouseVision job.") from exc
    audit(
        db,
        actor=actor,
        action="housevision.factory.job.create",
        entity_type="housevision_factory_job",
        entity_id=row.job_id,
        after={
            "catalog_id": catalog_id,
            "canonical_url": canonical,
            "job_revision": revision,
            "single_house_contract": True,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def get_job(db: Session, job_id: str) -> HouseVisionFactoryJob:
    row = db.scalar(select(HouseVisionFactoryJob).where(HouseVisionFactoryJob.job_id == job_id))
    if not row:
        raise KeyError(job_id)
    return row


def serialize_job(db: Session, job: HouseVisionFactoryJob) -> dict:
    artifacts = list(
        db.scalars(
            select(HouseVisionFactoryArtifact)
            .where(HouseVisionFactoryArtifact.job_id == job.job_id)
            .order_by(HouseVisionFactoryArtifact.role, HouseVisionFactoryArtifact.relative_path)
        )
    )
    qa_runs = list(
        db.scalars(
            select(HouseVisionFactoryQARun)
            .where(HouseVisionFactoryQARun.job_id == job.job_id)
            .order_by(HouseVisionFactoryQARun.run_number)
        )
    )
    return {
        "job_id": job.job_id,
        "job_revision": job.job_revision,
        "status": job.status,
        "stage": job.stage,
        "single_house_contract": True,
        "source_url_count": 1,
        "catalog_id": job.catalog_id,
        "stream_id": job.stream_id,
        "requested_url": job.requested_url,
        "canonical_url": job.canonical_url,
        "final_url": job.final_url,
        "source_page_id": job.source_page_id,
        "project_code": job.project_code,
        "rights_grant_id": job.rights_grant_id,
        "HousePlanID": job.house_plan_id,
        "housevision_job_id": job.housevision_job_id,
        "outputs_url": (
            f"/housevision/jobs/{job.housevision_job_id}"
            if job.housevision_job_id
            else None
        ),
        "geographic_name": job.geographic_name,
        "gross_floor_area_m2": str(job.gross_floor_area_m2)
        if job.gross_floor_area_m2 is not None
        else None,
        "net_floor_area_m2": str(job.net_floor_area_m2)
        if job.net_floor_area_m2 is not None
        else None,
        "levels": job.levels,
        "rooms_total": job.rooms_total,
        "attempt_count": job.attempt_count,
        "repair_count": job.repair_count,
        "consecutive_full_qa_passes": job.consecutive_passes,
        "package_manifest_sha256": job.package_manifest_sha256,
        "package_url": job.package_url if job.status == "COMPLETED" else None,
        "last_error": {
            "code": job.last_error_code,
            "message": job.last_error_message,
        }
        if job.last_error_code
        else None,
        "artifacts": [
            {
                "artifact_id": item.artifact_id,
                "role": item.role,
                "relative_path": item.relative_path,
                "sha256": item.sha256,
                "width_px": item.width_px,
                "height_px": item.height_px,
            }
            for item in artifacts
        ],
        "qa_runs": [
            {
                "qa_run_id": item.qa_run_id,
                "run_number": item.run_number,
                "manifest_sha256": item.package_manifest_sha256,
                "decision": item.decision,
                "semantic_score": item.semantic_score,
                "verifier_id": item.verifier_id,
                "verifier_model": item.verifier_model,
            }
            for item in qa_runs
        ],
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }

def import_status(db: Session, import_id: str) -> dict:
    record = db.scalar(
        select(HouseVisionFactoryImport).where(HouseVisionFactoryImport.import_id == import_id)
    )
    if not record:
        raise KeyError(import_id)
    items = list(
        db.scalars(
            select(HouseVisionFactoryImportItem)
            .where(HouseVisionFactoryImportItem.import_id == import_id)
            .order_by(HouseVisionFactoryImportItem.sequence)
        )
    )
    counts: dict[str, int] = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return {
        "import_id": record.import_id,
        "catalog_id": record.catalog_id,
        "stream_id": record.stream_id,
        "status": record.status,
        "requested": record.requested_count,
        "registered": record.registered_count,
        "duplicates": record.duplicate_count,
        "generator_jobs_created": sum(1 for item in items if item.job_id),
        "processing_mode": "SERIAL_SINGLE_HOUSE",
        "counts": counts,
        "items": [
            {
                "sequence": item.sequence,
                "source_url": item.requested_url,
                "status": item.status,
                "job_id": item.job_id,
                "terminal_reason": item.terminal_reason,
            }
            for item in items
        ],
    }


def set_stream_paused(
    db: Session, catalog_or_stream_id: str, paused: bool, actor: str, reason: str | None = None
) -> HouseVisionFactoryStream:
    stream = db.scalar(
        select(HouseVisionFactoryStream).where(
            or_(
                HouseVisionFactoryStream.stream_id == catalog_or_stream_id,
                HouseVisionFactoryStream.catalog_id == catalog_or_stream_id,
            )
        )
    )
    if not stream:
        raise KeyError(catalog_or_stream_id)
    stream.paused = paused
    stream.pause_reason = reason if paused else None
    audit(
        db,
        actor=actor,
        action="housevision.factory.stream.pause"
        if paused
        else "housevision.factory.stream.resume",
        entity_type="housevision_factory_stream",
        entity_id=stream.stream_id,
        after={"paused": paused, "reason": stream.pause_reason},
    )
    db.commit()
    db.refresh(stream)
    return stream


def retry_job(db: Session, job_id: str, actor: str) -> HouseVisionFactoryJob:
    prior = get_job(db, job_id)
    if prior.status not in {"NEEDS_REVIEW", "FAILED"}:
        raise TypehouseError(
            "RETRY_NOT_ALLOWED", "Csak NEEDS_REVIEW vagy FAILED job indítható új revisionnel."
        )
    payload = TypehouseJobIn(
        source_url=prior.canonical_url,
        catalog_id=prior.catalog_id,
        rights_grant_id=prior.rights_grant_id,
        visual_profile_id=prior.visual_profile_id,
        output_profile_id=prior.output_profile_id,
        regenerate=True,
    )
    return create_job(
        db,
        payload,
        idempotency_key=f"{prior.idempotency_key}:revision:{prior.job_revision + 1}",
        actor=actor,
    )


def register_artifact(
    db: Session, job_id: str, payload: TypehouseArtifactIn, actor: str
) -> HouseVisionFactoryArtifact:
    job = get_job(db, job_id)
    digest = _validated_sha(payload.sha256)
    canonical_asset_source, _ = canonicalize_source_url(payload.source_page_url)
    if canonical_asset_source != job.canonical_url:
        raise TypehouseError(
            "PACKAGE_BINDING_FAIL", "Az artifact source_page_url eltér a job kanonikus oldalától."
        )
    pure_path = PurePosixPath(payload.relative_path)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        raise TypehouseError("PACKAGE_BINDING_FAIL", "Nem biztonságos relatív artifact útvonal.")
    if payload.role == "master_8k" and (payload.width_px != 7680 or payload.height_px != 4320):
        raise TypehouseError("WEB_SIZE_BLOCKED", "A master_8k kötelező mérete pontosan 7680×4320.")
    existing = db.scalar(
        select(HouseVisionFactoryArtifact).where(
            HouseVisionFactoryArtifact.job_id == job_id,
            HouseVisionFactoryArtifact.relative_path == str(pure_path),
        )
    )
    changed = False
    if existing:
        changed = existing.sha256 != digest or existing.role != payload.role
        existing.role = payload.role
        existing.storage_ref = payload.storage_ref
        existing.mime_type = payload.mime_type
        existing.byte_size = payload.byte_size
        existing.width_px = payload.width_px
        existing.height_px = payload.height_px
        existing.sha256 = digest
        existing.source_page_url = canonical_asset_source
        existing.evidence_json = json.dumps(payload.evidence, ensure_ascii=False, sort_keys=True)
        row = existing
    else:
        row = HouseVisionFactoryArtifact(
            artifact_id=_id("HVFA"),
            job_id=job_id,
            role=payload.role,
            relative_path=str(pure_path),
            storage_ref=payload.storage_ref,
            mime_type=payload.mime_type,
            byte_size=payload.byte_size,
            width_px=payload.width_px,
            height_px=payload.height_px,
            sha256=digest,
            source_page_url=canonical_asset_source,
            evidence_json=json.dumps(payload.evidence, ensure_ascii=False, sort_keys=True),
        )
        db.add(row)
        changed = True
    if payload.role == "package_manifest":
        if job.package_manifest_sha256 and job.package_manifest_sha256 != digest:
            changed = True
        job.package_manifest_sha256 = digest
        job.package_url = payload.storage_ref
    if changed:
        job.consecutive_passes = 0
        if job.status == "COMPLETED":
            job.status = "QA_PASS_1"
        job.stage = "QA"
    audit(
        db,
        actor=actor,
        action="housevision.factory.artifact.register",
        entity_type="housevision_factory_artifact",
        entity_id=row.artifact_id,
        after={"job_id": job_id, "role": payload.role, "sha256": digest, "qa_reset": changed},
    )
    db.commit()
    db.refresh(row)
    return row


def record_qa_run(
    db: Session, job_id: str, payload: TypehouseQARunIn, actor: str
) -> HouseVisionFactoryQARun:
    job = get_job(db, job_id)
    manifest = _validated_sha(payload.package_manifest_sha256)
    if not job.package_manifest_sha256 or manifest != job.package_manifest_sha256:
        job.consecutive_passes = 0
        db.commit()
        raise TypehouseError("QA_CONSECUTIVE_RESET", "A QA manifest hash nem az aktuális csomagé.")
    if payload.verifier_id == job.created_by or payload.verifier_id == actor:
        raise TypehouseError(
            "QA_INDEPENDENCE_FAIL", "A verifier nem lehet a generátor vagy az API actor."
        )
    artifacts = list(
        db.scalars(
            select(HouseVisionFactoryArtifact).where(HouseVisionFactoryArtifact.job_id == job_id)
        )
    )
    roles = {artifact.role for artifact in artifacts}
    missing = sorted(REQUIRED_ARTIFACT_ROLES - roles)
    hard_gate = not missing
    masters = [item for item in artifacts if item.role == "master_8k"]
    hard_gate = (
        hard_gate
        and bool(masters)
        and all(item.width_px == 7680 and item.height_px == 4320 for item in masters)
    )
    findings = list(payload.findings)
    if missing:
        findings.append({"code": "PACKAGE_BINDING_FAIL", "missing_roles": missing})
    decision = (
        "PASS"
        if hard_gate
        and payload.deterministic_pass
        and payload.semantic_pass
        and payload.semantic_score >= settings.typehouse_factory_qa_min_score
        else "FAIL"
    )
    run_number = 1 + int(
        db.scalar(
            select(func.max(HouseVisionFactoryQARun.run_number)).where(
                HouseVisionFactoryQARun.job_id == job_id
            )
        )
        or 0
    )
    previous = db.scalar(
        select(HouseVisionFactoryQARun)
        .where(
            HouseVisionFactoryQARun.job_id == job_id,
            HouseVisionFactoryQARun.decision == "PASS",
        )
        .order_by(HouseVisionFactoryQARun.run_number.desc())
    )
    if decision == "PASS" and previous and previous.verifier_id == payload.verifier_id:
        raise TypehouseError(
            "QA_INDEPENDENCE_FAIL",
            "A két egymást követő QA PASS verifierének különböznie kell.",
        )
    row = HouseVisionFactoryQARun(
        qa_run_id=_id("HVQ"),
        job_id=job_id,
        run_number=run_number,
        package_manifest_sha256=manifest,
        deterministic_pass=payload.deterministic_pass and hard_gate,
        semantic_pass=payload.semantic_pass,
        semantic_score=payload.semantic_score,
        decision=decision,
        verifier_id=payload.verifier_id,
        verifier_model=payload.verifier_model,
        findings_json=json.dumps(findings, ensure_ascii=False, sort_keys=True),
    )
    db.add(row)
    if decision == "PASS":
        if previous and previous.package_manifest_sha256 == manifest:
            job.consecutive_passes = min(2, job.consecutive_passes + 1)
        else:
            job.consecutive_passes = 1
        if job.consecutive_passes >= settings.typehouse_factory_required_consecutive_passes:
            job.status = "COMPLETED"
            job.stage = "COMPLETED"
            job.finished_at = utcnow()
            job.lease_owner = None
            job.lease_until = None
        else:
            job.status = "QA_PASS_1"
            job.stage = "QA_PASS_1"
    else:
        job.consecutive_passes = 0
        job.status = (
            "REPAIR_REQUIRED"
            if job.repair_count < settings.typehouse_factory_max_repair_cycles
            else "NEEDS_REVIEW"
        )
        job.stage = job.status
        job.finding_summary_json = json.dumps(findings, ensure_ascii=False)
    audit(
        db,
        actor=actor,
        action="housevision.factory.qa.run",
        entity_type="housevision_factory_qa_run",
        entity_id=row.qa_run_id,
        after={
            "job_id": job_id,
            "decision": decision,
            "manifest_sha256": manifest,
            "consecutive_passes": job.consecutive_passes,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def _match_rights_policy(db: Session, job: HouseVisionFactoryJob) -> HouseVisionRightsPolicy | None:
    parsed = urlsplit(job.canonical_url)
    policies = list(
        db.scalars(
            select(HouseVisionRightsPolicy).where(
                HouseVisionRightsPolicy.grant_id == job.rights_grant_id,
                HouseVisionRightsPolicy.domain == parsed.hostname,
                HouseVisionRightsPolicy.active.is_(True),
                HouseVisionRightsPolicy.rights_status.in_(ALLOWED_RIGHTS),
            )
        )
    )
    matches = [
        item
        for item in policies
        if item.path_prefix == "/"
        or parsed.path == item.path_prefix.rstrip("/")
        or parsed.path.startswith(item.path_prefix.rstrip("/") + "/")
    ]
    return max(matches, key=lambda item: len(item.path_prefix), default=None)


def _safe_fetch_html(url: str, *, expected_project_code: str | None) -> tuple[str, bytes, str]:
    current = url
    for _ in range(4):
        canonical, project_code = canonicalize_source_url(current)
        if expected_project_code and project_code != expected_project_code:
            raise TypehouseError("SOURCE_IDENTITY_FAIL", "A redirect projektkódot változtatott.")
        parsed = urlsplit(canonical)
        hostname = parsed.hostname or ""
        allowed = _resolved_public_addresses(hostname)
        connection = http.client.HTTPSConnection(
            hostname,
            port=443,
            timeout=30,
            context=ssl.create_default_context(),
        )
        try:
            connection.request(
                "GET",
                parsed.path,
                headers={
                    "User-Agent": "Imperial-HouseVision-TypehouseFactory/1.0",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            response = connection.getresponse()
            peer = (
                ipaddress.ip_address(connection.sock.getpeername()[0]) if connection.sock else None
            )
            if peer not in allowed or not peer.is_global:
                raise TypehouseError("SOURCE_IDENTITY_FAIL", "DNS/IP újraellenőrzés sikertelen.")
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise TypehouseError("SOURCE_IDENTITY_FAIL", "Üres redirect cél.")
                target = urljoin(canonical, location)
                target_canonical, target_code = canonicalize_source_url(target)
                if urlsplit(target_canonical).hostname != parsed.hostname:
                    raise TypehouseError("SOURCE_IDENTITY_FAIL", "Hostváltó redirect tiltott.")
                if expected_project_code and target_code != expected_project_code:
                    raise TypehouseError("SOURCE_IDENTITY_FAIL", "Projektváltó redirect tiltott.")
                current = target_canonical
                continue
            if response.status != 200:
                raise TypehouseError(
                    "SOURCE_FETCH_FAIL", f"A forrás HTTP {response.status} választ adott."
                )
            content_type = (response.getheader("Content-Type") or "").lower()
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                raise TypehouseError("SOURCE_FETCH_FAIL", "A forrás nem HTML tartalom.")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > 5 * 1024 * 1024:
                    raise TypehouseError(
                        "SOURCE_FETCH_FAIL", "A forrásoldal túllépi az 5 MiB limitet."
                    )
                chunks.append(chunk)
            return canonical, b"".join(chunks), content_type
        finally:
            connection.close()
    raise TypehouseError("SOURCE_IDENTITY_FAIL", "Túl sok redirect.")


def _extract_source_summary(body: bytes) -> dict:
    text = body.decode("utf-8", errors="replace")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = (
        html.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else None
    )
    visible = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    visible = html.unescape(re.sub(r"<[^>]+>", " ", visible))
    visible = re.sub(r"\s+", " ", visible)
    image_urls = []
    for match in re.finditer(r"<img\b[^>]*(?:src|data-src)=[\"']([^\"']+)", text, re.I):
        value = html.unescape(match.group(1)).strip()
        if value and value not in image_urls:
            image_urls.append(value)
        if len(image_urls) >= 100:
            break

    def number(patterns: list[str]) -> Decimal | None:
        for pattern in patterns:
            match = re.search(pattern, visible, re.I)
            if match:
                return Decimal(match.group(1).replace(" ", "").replace(",", "."))
        return None

    def integer(patterns: list[str]) -> int | None:
        value = number(patterns)
        return int(value) if value is not None else None

    return {
        "title": title,
        "gross_floor_area_m2": number(
            [
                r"(?:bruttó|powierzchnia\s+całkowita)[^0-9]{0,40}([0-9]+(?:[,.][0-9]+)?)\s*m",
            ]
        ),
        "net_floor_area_m2": number(
            [
                r"(?:nettó|powierzchnia\s+użytkowa)[^0-9]{0,40}([0-9]+(?:[,.][0-9]+)?)\s*m",
            ]
        ),
        "levels": integer([r"(?:szintek|kondygnacje)[^0-9]{0,30}([0-9]+)"]),
        "rooms_total": integer([r"(?:szobák|pokoje)[^0-9]{0,30}([0-9]+)"]),
        "discovered_image_urls": image_urls,
    }


def _write_source_manifest(
    job: HouseVisionFactoryJob, final_url: str, body: bytes, summary: dict
) -> tuple[Path, dict]:
    root = Path(settings.typehouse_factory_asset_root)
    target = root / job.catalog_id / job.job_id / "source-manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "job_id": job.job_id,
        "source_page_id": job.source_page_id,
        "requested_url": job.requested_url,
        "canonical_url": job.canonical_url,
        "final_url": final_url,
        "source_revision_hash": _sha(body),
        "project_code": job.project_code,
        "rights_grant_id": job.rights_grant_id,
        "rights_policy_id": job.rights_policy_id,
        "extractor_version": "typehouse-source-v1",
        "title": summary["title"],
        "facts": {
            key: str(summary[key]) if summary[key] is not None else None
            for key in ("gross_floor_area_m2", "net_floor_area_m2", "levels", "rooms_total")
        },
        "discovered_assets": summary["discovered_image_urls"],
    }
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    target.write_bytes(encoded)
    return target, manifest


def _run_legacy_visual_pipeline(
    db: Session, job: HouseVisionFactoryJob, actor: str
) -> HouseVisionJob:
    """Run the proven geometry-locked visual flow and retain a review-only result.

    The Factory queue never publishes or packages here. A visual QA pass only makes
    the gallery ready for an explicit human review.
    """
    from .housevision import auto_ingest_source_assets, run_qa
    from .housevision import create_job as create_housevision_job
    from .housevision_render_bridge import (
        create_source_preserved_baseline,
        generate_typehouse_renders,
    )

    visual_job = None
    if job.housevision_job_id:
        visual_job = db.scalar(
            select(HouseVisionJob).where(
                HouseVisionJob.job_id == job.housevision_job_id
            )
        )
    if visual_job is None:
        visual_job = create_housevision_job(
            db,
            brand_id="imperial-holding",
            source_url=job.final_url or job.canonical_url,
            actor=actor,
            operation_mode="provider_dispatch",
            render_provider="image-factory",
        )
        job.housevision_job_id = visual_job.job_id
        db.commit()

    if visual_job.status in {"SOURCE_CRAWL", "ASSET_CLASSIFICATION"}:
        ingest = auto_ingest_source_assets(db, visual_job.job_id, actor)
        visual_job = db.scalar(
            select(HouseVisionJob).where(HouseVisionJob.job_id == visual_job.job_id)
        )
        if not visual_job or visual_job.status != "RENDERING":
            raise TypehouseError(
                "SOURCE_ASSET_REVIEW_REQUIRED",
                "A forrásból nem igazolható automatikusan legalább egy külső kép és egy alaprajz. "
                f"Importeredmény: {json.dumps(ingest, ensure_ascii=False)}",
            )

    if visual_job.status in {"RENDERING", "RENDER_RETRY"}:
        job.stage = "RENDERING"
        job.render_attempt_count += 1
        db.commit()
        rendered = generate_typehouse_renders(db, visual_job.job_id, actor)
        if not rendered.get("created"):
            raise TypehouseError(
                "VISUAL_RENDER_REVIEW_REQUIRED",
                "A képgenerálás fail-closed módon elutasította a kimenetet; "
                "a hibás kép nem került a galériába.",
            )

    visual_job = db.scalar(
        select(HouseVisionJob).where(HouseVisionJob.job_id == visual_job.job_id)
    )
    if not visual_job:
        raise TypehouseError("VISUAL_QA_REVIEW_REQUIRED", "A vizuális munka nem található.")
    if visual_job.status == "QA":
        create_source_preserved_baseline(db, visual_job.job_id, actor)
        qa = run_qa(db, visual_job.job_id, actor)
        if qa.status != "PASS":
            raise TypehouseError(
                "VISUAL_QA_REVIEW_REQUIRED",
                "A normál HouseVision QA elutasította a kimenetet; publikálás blokkolva.",
            )

    db.refresh(visual_job)
    if visual_job.status != "PACKAGING":
        raise TypehouseError(
            "VISUAL_QA_REVIEW_REQUIRED",
            f"A vizuális munka nem jutott QA PASS állapotba ({visual_job.status}).",
        )
    visual_job.publication_eligibility = "blocked"
    job.status = "NEEDS_REVIEW"
    job.stage = "HUMAN_VISUAL_REVIEW"
    job.last_error_code = "HUMAN_VISUAL_REVIEW_REQUIRED"
    job.last_error_message = (
        "A geometriazárt kimenetek automatikus QA-n átmentek. "
        "Kézi vizuális jóváhagyás szükséges; publikálás blokkolva."
    )
    job.finding_summary_json = json.dumps(
        {
            "housevision_job_id": visual_job.job_id,
            "housevision_status": visual_job.status,
            "publication_eligibility": visual_job.publication_eligibility,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    db.commit()
    return visual_job


def process_job(db: Session, job_id: str, worker_id: str, fencing_token: int) -> None:
    job = get_job(db, job_id)
    if job.lease_owner != worker_id or job.fencing_token != fencing_token:
        raise TypehouseError("STALE_FENCING_TOKEN", "A worker lease már nem érvényes.")
    try:
        policy = _match_rights_policy(db, job)
        if not policy or not policy.owner_attestation_sha256 or not policy.page_scope_sha256:
            job.status = "BLOCKED"
            job.stage = "BLOCKED"
            job.last_error_code = "RIGHTS_SCOPE_FAIL"
            job.last_error_message = (
                "Nincs aktív, granthez és oldal-scope-hoz kötött tulajdonosi jogbizonyíték."
            )
            job.finished_at = utcnow()
            return
        job.rights_policy_id = policy.policy_id
        job.status = "EXTRACTING"
        job.stage = "EXTRACTING"
        db.commit()
        final_url, body, _ = _safe_fetch_html(
            job.canonical_url, expected_project_code=job.project_code
        )
        summary = _extract_source_summary(body)
        job.final_url = final_url
        job.source_revision_hash = _sha(body)
        job.source_title = summary["title"]
        job.gross_floor_area_m2 = summary["gross_floor_area_m2"]
        job.net_floor_area_m2 = summary["net_floor_area_m2"]
        job.levels = summary["levels"]
        job.rooms_total = summary["rooms_total"]
        path, manifest = _write_source_manifest(job, final_url, body, summary)
        encoded = path.read_bytes()
        artifact = db.scalar(
            select(HouseVisionFactoryArtifact).where(
                HouseVisionFactoryArtifact.job_id == job.job_id,
                HouseVisionFactoryArtifact.relative_path == "source-manifest.json",
            )
        )
        artifact_values = dict(
                artifact_id=_id("HVFA"),
                job_id=job.job_id,
                role="source_manifest",
                relative_path="source-manifest.json",
                storage_ref=str(path),
                mime_type="application/json",
                byte_size=len(encoded),
                sha256=_sha(encoded),
                source_page_url=job.canonical_url,
                evidence_json=json.dumps(
                    {
                        "source_html_sha256": _sha(body),
                        "extractor_version": manifest["extractor_version"],
                    },
                    sort_keys=True,
                ),
        )
        if artifact is None:
            db.add(HouseVisionFactoryArtifact(**artifact_values))
        else:
            artifact_values.pop("artifact_id")
            artifact_values.pop("job_id")
            for key, value in artifact_values.items():
                setattr(artifact, key, value)
        missing = [
            name
            for name in ("gross_floor_area_m2", "net_floor_area_m2", "levels", "rooms_total")
            if summary[name] is None
        ]
        _run_legacy_visual_pipeline(db, job, f"system:typehouse:{job.job_id}")
        if missing:
            job.last_error_message = (job.last_error_message or "") + (
                " Hiányzó, ember által ellenőrizendő forrásadatok: " + ", ".join(missing) + "."
            )
        job.finished_at = utcnow()
    except TypehouseError as exc:
        if exc.code in {"RIGHTS_SCOPE_FAIL", "SOURCE_IDENTITY_FAIL"}:
            job.status = "BLOCKED"
        elif exc.code in REVIEW_ERRORS:
            job.status = "NEEDS_REVIEW"
        else:
            job.status = "FAILED"
        job.stage = job.status
        job.last_error_code = exc.code
        job.last_error_message = str(exc)
        job.finished_at = utcnow()
    except Exception as exc:
        if job.housevision_job_id:
            visual_job = db.scalar(
                select(HouseVisionJob).where(
                    HouseVisionJob.job_id == job.housevision_job_id
                )
            )
            if visual_job and visual_job.status not in {
                "PACKAGING",
                "READY",
                "JOB_FAILED",
                "CANCELLED",
            }:
                visual_job.status = "RENDER_RETRY"
                visual_job.publication_eligibility = "blocked"
                visual_job.failure_reason = (
                    "A Factory vizuális feldolgozása biztonságosan leállt: "
                    f"{type(exc).__name__}: {str(exc)[:1200]}"
                )
        job.status = "NEEDS_REVIEW"
        job.stage = "NEEDS_REVIEW"
        job.last_error_code = "VISUAL_PIPELINE_FAILED"
        job.last_error_message = (
            "A vizuális feldolgozás biztonságosan leállt; nincs publikálható kimenet. "
            f"{type(exc).__name__}: {str(exc)[:1500]}"
        )
        job.finished_at = utcnow()
    finally:
        job.lease_owner = None
        job.lease_until = None
        db.commit()
        if job.import_item_id:
            item = db.scalar(
                select(HouseVisionFactoryImportItem).where(
                    HouseVisionFactoryImportItem.import_item_id == job.import_item_id
                )
            )
            if item:
                item.status = job.status
                item.terminal_reason = job.last_error_code
                db.flush()
                import_row = db.scalar(
                    select(HouseVisionFactoryImport).where(
                        HouseVisionFactoryImport.import_id == item.import_id
                    )
                )
                remaining = int(
                    db.scalar(
                        select(func.count())
                        .select_from(HouseVisionFactoryImportItem)
                        .where(
                            HouseVisionFactoryImportItem.import_id == item.import_id,
                            HouseVisionFactoryImportItem.status.in_({"PENDING", "DISPATCHED"}),
                        )
                    )
                    or 0
                )
                if import_row:
                    import_row.status = "COMPLETED" if remaining == 0 else "PROCESSING"
                db.commit()


def dispatch_and_claim(db: Session, worker_id: str) -> tuple[str, int] | None:
    now = utcnow()
    active_count = int(
        db.scalar(
            select(func.count())
            .select_from(HouseVisionFactoryJob)
            .where(
                HouseVisionFactoryJob.status.in_(ACTIVE),
                or_(
                    HouseVisionFactoryJob.lease_until.is_(None),
                    HouseVisionFactoryJob.lease_until >= now,
                ),
            )
        )
        or 0
    )
    if active_count:
        return None
    pending_job_query = (
        select(HouseVisionFactoryJob)
        .join(
            HouseVisionFactoryStream,
            HouseVisionFactoryStream.stream_id == HouseVisionFactoryJob.stream_id,
        )
        .where(
            HouseVisionFactoryJob.status == "PENDING",
            HouseVisionFactoryStream.paused.is_(False),
            or_(
                HouseVisionFactoryJob.lease_until.is_(None),
                HouseVisionFactoryJob.lease_until < now,
            ),
        )
        .order_by(HouseVisionFactoryJob.created_at, HouseVisionFactoryJob.id)
        .limit(1)
    )
    if not db.bind or db.bind.dialect.name != "sqlite":
        pending_job_query = pending_job_query.with_for_update(skip_locked=True)
    job = db.scalar(pending_job_query)
    if not job:
        item_query = (
            select(HouseVisionFactoryImportItem)
            .join(
                HouseVisionFactoryStream,
                HouseVisionFactoryStream.stream_id == HouseVisionFactoryImportItem.stream_id,
            )
            .where(
                HouseVisionFactoryImportItem.status == "PENDING",
                HouseVisionFactoryStream.paused.is_(False),
            )
            .order_by(
                HouseVisionFactoryImportItem.created_at,
                HouseVisionFactoryImportItem.sequence,
            )
            .limit(1)
        )
        if not db.bind or db.bind.dialect.name != "sqlite":
            item_query = item_query.with_for_update(skip_locked=True)
        item = db.scalar(item_query)
        if not item:
            return None
        payload = TypehouseJobIn(
            source_url=item.requested_url,
            catalog_id=item.catalog_id,
            rights_grant_id=item.rights_grant_id,
        )
        job = create_job(
            db,
            payload,
            idempotency_key=f"hv:{item.catalog_id}:{item.requested_url_sha256}",
            actor="system:typehouse-dispatcher",
            import_item_id=item.import_item_id,
        )
        item = db.scalar(
            select(HouseVisionFactoryImportItem).where(
                HouseVisionFactoryImportItem.import_item_id == item.import_item_id
            )
        )
        if item:
            item.job_id = job.job_id
            if job.status in TERMINAL:
                item.status = job.status
                item.terminal_reason = job.last_error_code
                db.flush()
                import_row = db.scalar(
                    select(HouseVisionFactoryImport).where(
                        HouseVisionFactoryImport.import_id == item.import_id
                    )
                )
                remaining = int(
                    db.scalar(
                        select(func.count())
                        .select_from(HouseVisionFactoryImportItem)
                        .where(
                            HouseVisionFactoryImportItem.import_id == item.import_id,
                            HouseVisionFactoryImportItem.status.in_(
                                {"PENDING", "DISPATCHED"}
                            ),
                        )
                    )
                    or 0
                )
                if import_row:
                    import_row.status = "COMPLETED" if remaining == 0 else "PROCESSING"
                db.commit()
                return None
            item.status = "DISPATCHED"
            db.commit()
    job.status = "RIGHTS_VALIDATION"
    job.stage = "RIGHTS_VALIDATION"
    job.lease_owner = worker_id
    job.lease_until = now + timedelta(seconds=settings.typehouse_factory_lease_seconds)
    job.fencing_token += 1
    job.attempt_count += 1
    job.started_at = job.started_at or now
    db.commit()
    return job.job_id, job.fencing_token


def workspace(db: Session) -> dict:
    jobs = list(
        db.scalars(
            select(HouseVisionFactoryJob)
            .order_by(HouseVisionFactoryJob.created_at.desc())
            .limit(100)
        )
    )
    imports = list(
        db.scalars(
            select(HouseVisionFactoryImport)
            .order_by(HouseVisionFactoryImport.created_at.desc())
            .limit(50)
        )
    )
    streams = list(
        db.scalars(select(HouseVisionFactoryStream).order_by(HouseVisionFactoryStream.catalog_id))
    )
    counts = dict(
        db.execute(
            select(HouseVisionFactoryJob.status, func.count()).group_by(
                HouseVisionFactoryJob.status
            )
        )
        .tuples()
        .all()
    )
    return {
        "factory_jobs": jobs,
        "factory_imports": imports,
        "factory_streams": streams,
        "factory_metrics": {
            "total": sum(counts.values()),
            "pending": counts.get("PENDING", 0),
            "active": sum(counts.get(status, 0) for status in ACTIVE),
            "completed": counts.get("COMPLETED", 0),
            "needs_review": counts.get("NEEDS_REVIEW", 0),
            "blocked": counts.get("BLOCKED", 0),
            "failed": counts.get("FAILED", 0),
        },
        "factory_processing_enabled": settings.typehouse_factory_processing_enabled,
        "factory_render_provider": settings.typehouse_factory_render_provider,
        "factory_auto_approved_domains": AUTO_APPROVED_SOURCE_DOMAINS,
    }
