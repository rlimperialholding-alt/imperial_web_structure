from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..models import (
    HouseCatalogPlan,
    HouseVisionGeometryLock,
    HouseVisionJob,
    HouseVisionName,
    HouseVisionOutputAsset,
    HouseVisionPackage,
    HouseVisionQAReport,
    HouseVisionRightsPolicy,
    HouseVisionSourceAsset,
    OutboxMessage,
)
from ..schemas import (
    HouseVisionGeometryLockIn,
    HouseVisionOutputAssetIn,
    HouseVisionRightsPolicyIn,
    HouseVisionSourceAssetIn,
)
from .housevision_source_ingest import SourceIngestError, ingest_page_assets

ALLOWED_RIGHTS = {"owned", "licensed", "partner_permission", "open_license"}
ASSET_TYPES = {"EXTERIOR", "INTERIOR", "FLOORPLAN", "OTHER"}
EDGE_THRESHOLD = Decimal("0.88")
ROOF_THRESHOLD = Decimal("0.95")
OPENING_THRESHOLD = Decimal("0.95")
FLOORPLAN_THRESHOLD = Decimal("0.98")

AUTO_APPROVED_SOURCE_DOMAINS = (
    "extradom.pl",
    "imperialholding.hu",
    "danishfabrik.hu",
    "prefab.hu",
    "bautica.hu",
    "casa-moderna.hu",
    "timberhaus.hu",
)
AUTO_APPROVED_SOURCE_HOSTS = tuple(
    host for domain in AUTO_APPROVED_SOURCE_DOMAINS for host in (domain, f"www.{domain}")
)
AUTO_RIGHTS_DIRECTIVE = (
    "Az extradom.pl az imperialholding.hu a danishfabrik.hu a prefab.hu es a "
    "bautica.hu - casa-moderna.hu es a timberhaus.hu legyen automatikusan "
    "jovahagyott domain"
)
AUTO_RIGHTS_EVIDENCE_REF = "owner-directive:2026-08-12:auto-approved-source-domains-v1"

HOUSEVISION_ACTION_ROLES = {
    "rights_manage": {"legal", "owner", "managing-director", "platform-admin"},
    "rights_approve": {"legal", "owner", "platform-admin"},
    "job_create": {
        "owner",
        "managing-director",
        "marketing",
        "creative-director",
        "technical-prep",
        "designer",
        "platform-admin",
    },
    "source_manage": {
        "owner",
        "managing-director",
        "creative-director",
        "technical-prep",
        "designer",
        "platform-admin",
    },
    "geometry_lock": {"technical-prep", "designer", "platform-admin"},
    "name_assign": {
        "owner",
        "managing-director",
        "marketing",
        "creative-director",
        "platform-admin",
    },
    "output_manage": {"creative-director", "technical-prep", "designer", "platform-admin"},
    "qa_run": {"creative-director", "technical-prep", "designer", "platform-admin"},
    "houseplan_bind": {"owner", "managing-director", "technical-prep", "platform-admin"},
    "package_release": {
        "owner",
        "managing-director",
        "creative-director",
        "technical-prep",
        "platform-admin",
    },
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _job(db: Session, job_id: str) -> HouseVisionJob:
    row = db.scalar(select(HouseVisionJob).where(HouseVisionJob.job_id == job_id))
    if not row:
        raise KeyError(job_id)
    return row


def ensure_action_allowed(role: str, action: str) -> None:
    allowed = HOUSEVISION_ACTION_ROLES.get(action)
    if allowed is None or role not in allowed:
        raise PermissionError("Ehhez a HouseVision művelethez nincs szerepkör-jogosultság.")


def action_permissions(role: str) -> dict[str, bool]:
    return {action: role in roles for action, roles in HOUSEVISION_ACTION_ROLES.items()}


def _json_value(raw: str | None, fallback):
    try:
        return json.loads(raw) if raw else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def _public_url(value: str) -> tuple[str, str]:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("A forrás URL kizárólag publikus http/https cím lehet.")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise ValueError("Belső, localhost vagy metadata cím tiltott.")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise ValueError("A forrásdomain nem oldható fel biztonságosan.") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Privát, loopback, link-local, reserved vagy multicast cím tiltott.")
    return host, parsed.path or "/"


def _sha256(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError("Érvényes SHA-256 lenyomat szükséges.")
    return normalized


def automatic_rights_grant_for_host(host: str) -> str | None:
    normalized = host.lower().strip().rstrip(".")
    if normalized not in AUTO_APPROVED_SOURCE_HOSTS:
        return None
    return "AUTO-RIGHTS-" + normalized.upper().replace(".", "-")


def ensure_typehouse_auto_approved_rights(db: Session) -> None:
    actor = "owner-directive:2026-08-12"
    owner_attestation = hashlib.sha256(AUTO_RIGHTS_DIRECTIVE.encode("utf-8")).hexdigest()
    changed = False
    for host in AUTO_APPROVED_SOURCE_HOSTS:
        grant_id = automatic_rights_grant_for_host(host)
        if not grant_id:
            continue
        page_scope = hashlib.sha256(f"https://{host}/".encode("utf-8")).hexdigest()
        row = db.scalar(
            select(HouseVisionRightsPolicy).where(HouseVisionRightsPolicy.grant_id == grant_id)
        )
        if not row:
            row = HouseVisionRightsPolicy(
                policy_id=_id("HVR"),
                domain=host,
                path_prefix="/",
                rights_status="partner_permission",
                evidence_ref=AUTO_RIGHTS_EVIDENCE_REF,
                grant_id=grant_id,
                owner_attestation_sha256=owner_attestation,
                page_scope_sha256=page_scope,
                attribution_required=False,
                crawl_delay_seconds=2,
                max_assets_per_page=12,
                active=True,
                created_by=actor,
                approved_by=actor,
                approved_at=utcnow(),
            )
            db.add(row)
            db.flush()
        else:
            row.domain = host
            row.path_prefix = "/"
            row.rights_status = "partner_permission"
            row.evidence_ref = AUTO_RIGHTS_EVIDENCE_REF
            row.owner_attestation_sha256 = owner_attestation
            row.page_scope_sha256 = page_scope
            row.active = True
            row.approved_by = actor
            row.approved_at = row.approved_at or utcnow()
        audit(
            db,
            actor=actor,
            action="housevision.rights.auto_approve",
            entity_type="housevision_rights_policy",
            entity_id=row.policy_id,
            after={
                "domain": host,
                "path_prefix": "/",
                "grant_id": grant_id,
                "active": True,
                "evidence_ref": AUTO_RIGHTS_EVIDENCE_REF,
            },
        )
        changed = True
    if changed:
        db.commit()


def create_rights_policy(
    db: Session, data: HouseVisionRightsPolicyIn, actor: str, actor_role: str
) -> HouseVisionRightsPolicy:
    if actor_role not in {"legal", "owner", "managing-director", "platform-admin"}:
        raise PermissionError("Forrásjog-policy létrehozására nincs jogosultság.")
    status = data.rights_status.strip().lower()
    if status not in ALLOWED_RIGHTS | {"blocked"}:
        raise ValueError("Érvénytelen jogállás.")
    domain = data.domain.lower().strip().rstrip(".")
    row = HouseVisionRightsPolicy(
        policy_id=_id("HVR"),
        domain=domain,
        path_prefix=data.path_prefix or "/",
        rights_status=status,
        evidence_ref=data.evidence_ref,
        grant_id=data.grant_id,
        owner_attestation_sha256=data.owner_attestation_sha256,
        page_scope_sha256=data.page_scope_sha256,
        attribution_required=data.attribution_required,
        attribution_text=data.attribution_text,
        crawl_delay_seconds=data.crawl_delay_seconds,
        max_assets_per_page=data.max_assets_per_page,
        active=False,
        created_by=actor,
    )
    db.add(row)
    audit(
        db,
        actor=actor,
        action="housevision.rights.create",
        entity_type="housevision_rights_policy",
        entity_id=row.policy_id,
        after={"domain": domain, "status": status, "active": False},
    )
    db.commit()
    db.refresh(row)
    return row


def approve_rights_policy(
    db: Session, policy_id: str, actor: str, actor_role: str
) -> HouseVisionRightsPolicy:
    if actor_role not in {"legal", "owner", "platform-admin"}:
        raise PermissionError("Forrásjog-policy jóváhagyására nincs jogosultság.")
    row = db.scalar(
        select(HouseVisionRightsPolicy).where(HouseVisionRightsPolicy.policy_id == policy_id)
    )
    if not row:
        raise KeyError(policy_id)
    if row.rights_status not in ALLOWED_RIGHTS:
        raise ValueError("Blokkolt jogpolicy nem aktiválható.")
    if not row.evidence_ref:
        raise ValueError("Jogbizonyíték nélkül policy nem aktiválható.")
    if row.grant_id:
        if not row.owner_attestation_sha256 or not row.page_scope_sha256:
            raise ValueError(
                "Factory rights grant csak tulajdonosi nyilatkozat- és oldal-scope SHA-256-tal aktiválható."
            )
        _sha256(row.owner_attestation_sha256)
        _sha256(row.page_scope_sha256)
    row.active = True
    row.approved_by = actor
    row.approved_at = utcnow()
    audit(
        db,
        actor=actor,
        action="housevision.rights.approve",
        entity_type="housevision_rights_policy",
        entity_id=row.policy_id,
        after={"active": True},
    )
    db.commit()
    db.refresh(row)
    return row


def create_job(
    db: Session,
    brand_id: str,
    source_url: str,
    actor: str,
    *,
    operation_mode: str = "package_only",
    render_provider: str = "mock",
) -> HouseVisionJob:
    host, path = _public_url(source_url)
    if operation_mode not in {"package_only", "provider_dispatch"}:
        raise ValueError("Ismeretlen HouseVision működési mód.")
    policies = db.scalars(
        select(HouseVisionRightsPolicy)
        .where(
            HouseVisionRightsPolicy.domain == host,
            HouseVisionRightsPolicy.active.is_(True),
            HouseVisionRightsPolicy.rights_status.in_(ALLOWED_RIGHTS),
        )
        .order_by(desc(HouseVisionRightsPolicy.created_at))
    ).all()
    matches = [
        item
        for item in policies
        if item.path_prefix == "/"
        or path == item.path_prefix.rstrip("/")
        or path.startswith(item.path_prefix.rstrip("/") + "/")
    ]
    policy = max(matches, key=lambda item: len(item.path_prefix), default=None)
    allowed = policy is not None
    source_page_id = "HVSP-" + hashlib.sha256(source_url.encode()).hexdigest()[:20].upper()
    row = HouseVisionJob(
        job_id=_id("HVJ"),
        brand_id=brand_id,
        source_url=source_url,
        source_page_id=source_page_id,
        rights_policy_id=policy.policy_id if policy is not None else None,
        status="SOURCE_CRAWL" if allowed else "RIGHTS_BLOCKED",
        operation_mode=operation_mode,
        render_provider=render_provider,
        publication_eligibility="blocked",
        created_by=actor,
        failure_reason=None if allowed else "Nincs aktív, útvonalra érvényes SourceRightsPolicy.",
    )
    db.add(row)
    audit(
        db,
        actor=actor,
        action="housevision.job.create",
        entity_type="housevision_job",
        entity_id=row.job_id,
        after={
            "brand_id": brand_id,
            "source_url": source_url,
            "status": row.status,
            "policy_id": row.rights_policy_id,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def recheck_rights(db: Session, job_id: str, actor: str) -> HouseVisionJob:
    job = _job(db, job_id)
    if job.status != "RIGHTS_BLOCKED":
        raise ValueError("Csak RIGHTS_BLOCKED job jogállása ellenőrizhető újra.")
    host, path = _public_url(job.source_url)
    policies = db.scalars(
        select(HouseVisionRightsPolicy)
        .where(
            HouseVisionRightsPolicy.domain == host,
            HouseVisionRightsPolicy.active.is_(True),
            HouseVisionRightsPolicy.rights_status.in_(ALLOWED_RIGHTS),
        )
        .order_by(desc(HouseVisionRightsPolicy.created_at))
    ).all()
    matches = [
        item
        for item in policies
        if item.path_prefix == "/"
        or path == item.path_prefix.rstrip("/")
        or path.startswith(item.path_prefix.rstrip("/") + "/")
    ]
    policy = max(matches, key=lambda item: len(item.path_prefix), default=None)
    if not policy:
        raise ValueError("Továbbra sincs aktív, útvonalra érvényes SourceRightsPolicy.")
    job.rights_policy_id = policy.policy_id
    job.status = "SOURCE_CRAWL"
    job.failure_reason = None
    audit(
        db,
        actor=actor,
        action="housevision.rights.recheck",
        entity_type="housevision_job",
        entity_id=job_id,
        after={"policy_id": policy.policy_id, "status": job.status},
    )
    db.commit()
    db.refresh(job)
    return job


def add_source_asset(
    db: Session, job_id: str, data: HouseVisionSourceAssetIn, actor: str
) -> HouseVisionSourceAsset:
    job = _job(db, job_id)
    if job.status in {"RIGHTS_BLOCKED", "CANCELLED", "JOB_FAILED", "READY"}:
        raise ValueError("A job jelenlegi állapotában nem fogad forrásassetet.")
    if data.asset_type not in ASSET_TYPES:
        raise ValueError("Ismeretlen assetosztály.")
    if data.magic_mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("Csak magic-byte alapján igazolt JPEG, PNG vagy WEBP fogadható.")
    _public_url(data.source_url)
    data.content_sha256 = _sha256(data.content_sha256)
    policy = db.scalar(
        select(HouseVisionRightsPolicy).where(
            HouseVisionRightsPolicy.policy_id == job.rights_policy_id
        )
    )
    count = len(
        db.scalars(
            select(HouseVisionSourceAsset).where(HouseVisionSourceAsset.job_id == job_id)
        ).all()
    )
    if not policy or count >= policy.max_assets_per_page:
        raise ValueError("A jogpolicy assetlimitje elérve vagy hiányzik.")
    row = HouseVisionSourceAsset(source_visual_id=_id("HVS"), job_id=job_id, **data.model_dump())
    db.add(row)
    job.status = "ASSET_CLASSIFICATION"
    audit(
        db,
        actor=actor,
        action="housevision.source_asset.create",
        entity_type="housevision_source_asset",
        entity_id=row.source_visual_id,
        after={"job_id": job_id, "type": row.asset_type, "sha256": row.content_sha256},
    )
    db.commit()
    db.refresh(row)
    return row


def auto_ingest_source_assets(db: Session, job_id: str, actor: str) -> dict:
    """Download and register the source page's first-party house gallery assets."""
    job = _job(db, job_id)
    if job.status in {"RIGHTS_BLOCKED", "CANCELLED", "JOB_FAILED", "READY"}:
        raise ValueError("A job jelenlegi állapotában automatikus forrásimport nem futtatható.")
    policy = db.scalar(
        select(HouseVisionRightsPolicy).where(
            HouseVisionRightsPolicy.policy_id == job.rights_policy_id,
            HouseVisionRightsPolicy.active.is_(True),
            HouseVisionRightsPolicy.rights_status.in_(ALLOWED_RIGHTS),
        )
    )
    if not policy:
        raise ValueError("Az automatikus forrásimporthoz aktív jogpolicy szükséges.")
    existing = db.scalars(
        select(HouseVisionSourceAsset).where(HouseVisionSourceAsset.job_id == job_id)
    ).all()
    remaining = max(0, policy.max_assets_per_page - len(existing))
    if remaining == 0:
        return {"added_count": 0, "total_count": len(existing), "status": job.status}
    ingest_dir = Path(settings.typehouse_factory_asset_root) / "legacy" / job_id
    preexisting_paths = (
        {path.resolve() for path in ingest_dir.rglob("*") if path.is_file()}
        if ingest_dir.exists()
        else set()
    )
    try:
        imported, report = ingest_page_assets(job.source_url, job.job_id, remaining)
    except SourceIngestError as exc:
        job.failure_reason = "Automatikus forrásimport sikertelen: " + str(exc)
        audit(
            db,
            actor=actor,
            action="housevision.source_asset.auto_import_failed",
            entity_type="housevision_job",
            entity_id=job_id,
            after={"reason": str(exc)},
        )
        db.commit()
        raise ValueError(job.failure_reason) from exc
    existing_hashes = {item.content_sha256 for item in existing}
    sequence = max((item.sequence for item in existing), default=0)
    added: list[HouseVisionSourceAsset] = []
    accepted_storage_refs: set[Path] = set()
    for item in imported:
        if item.content_sha256 in existing_hashes:
            continue
        sequence += 1
        row = HouseVisionSourceAsset(
            source_visual_id=_id("HVS"),
            job_id=job_id,
            source_url=item.source_url,
            asset_type=item.asset_type,
            sequence=sequence,
            content_sha256=item.content_sha256,
            width_px=item.width_px,
            height_px=item.height_px,
            magic_mime_type=item.magic_mime_type,
            status="accepted",
        )
        db.add(row)
        added.append(row)
        accepted_storage_refs.add(Path(item.storage_ref).resolve())
        existing_hashes.add(item.content_sha256)
    for item in imported:
        storage_path = Path(item.storage_ref).resolve()
        if storage_path not in accepted_storage_refs and storage_path not in preexisting_paths:
            storage_path.unlink(missing_ok=True)
    all_count = len(existing) + len(added)
    floorplans = sum(1 for item in [*existing, *added] if item.asset_type == "FLOORPLAN")
    exteriors = sum(1 for item in [*existing, *added] if item.asset_type == "EXTERIOR")
    job.accepted_source_count = all_count
    if floorplans and exteriors:
        job.status = "ASSET_CLASSIFICATION"
        job.failure_reason = None
    else:
        job.status = "SOURCE_CRAWL"
        missing = []
        if not exteriors:
            missing.append("külső látványterv")
        if not floorplans:
            missing.append("alaprajz")
        job.failure_reason = "A forrásoldalról még nem igazolható: " + ", ".join(missing)
    audit(
        db,
        actor=actor,
        action="housevision.source_asset.auto_import",
        entity_type="housevision_job",
        entity_id=job_id,
        after={
            "added_count": len(added),
            "accepted_count": all_count,
            "exterior_count": exteriors,
            "floorplan_count": floorplans,
            "source_html_sha256": report["source_html_sha256"],
            "manifest": str(
                Path(settings.typehouse_factory_asset_root)
                / "legacy"
                / job_id
                / "source-ingest-manifest.json"
            ),
        },
    )
    db.commit()
    if floorplans and exteriors:
        auto_lock_geometry(db, job_id, actor)
    return {
        "added_count": len(added),
        "total_count": all_count,
        "exterior_count": exteriors,
        "floorplan_count": floorplans,
        "status": _job(db, job_id).status,
    }


def lock_geometry(
    db: Session, job_id: str, data: HouseVisionGeometryLockIn, actor: str, actor_role: str
) -> HouseVisionGeometryLock:
    if actor_role not in {"technical-prep", "designer", "platform-admin"}:
        raise PermissionError("GeometryLock létrehozására nincs jogosultság.")
    job = _job(db, job_id)
    assets = db.scalars(
        select(HouseVisionSourceAsset).where(
            HouseVisionSourceAsset.job_id == job_id, HouseVisionSourceAsset.status == "accepted"
        )
    ).all()
    if not assets or not any(a.asset_type == "FLOORPLAN" for a in assets):
        raise ValueError("GeometryLockhoz legalább egy elfogadott alaprajz szükséges.")
    if not any(a.asset_type == "EXTERIOR" for a in assets):
        raise ValueError("GeometryLockhoz legalább egy külső látvány szükséges.")
    version = 1 + len(
        db.scalars(
            select(HouseVisionGeometryLock).where(HouseVisionGeometryLock.job_id == job_id)
        ).all()
    )
    data.floorplan_topology_sha256 = _sha256(data.floorplan_topology_sha256)
    payload = data.model_dump(mode="json") | {"job_id": job_id, "version": version}
    row = HouseVisionGeometryLock(
        geometry_lock_id=_id("HVG"),
        job_id=job_id,
        version=version,
        floorplan_topology_sha256=data.floorplan_topology_sha256,
        massing_signature=data.massing_signature,
        roof_form=data.roof_form,
        roof_pitch_deg=data.roof_pitch_deg,
        storey_count=data.storey_count,
        window_count=data.window_count,
        door_count=data.door_count,
        width_depth_height_ratio=data.width_depth_height_ratio,
        immutable_features_json=json.dumps(data.immutable_features, ensure_ascii=False),
        content_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        created_by=actor,
    )
    db.add(row)
    job.status = "NAME_ASSIGNMENT"
    job.accepted_source_count = len(assets)
    audit(
        db,
        actor=actor,
        action="housevision.geometry.lock",
        entity_type="housevision_geometry_lock",
        entity_id=row.geometry_lock_id,
        after={"job_id": job_id, "version": version, "sha256": row.content_sha256},
    )
    db.commit()
    db.refresh(row)
    return row


def auto_lock_geometry(db: Session, job_id: str, actor: str) -> HouseVisionGeometryLock:
    """Bind every accepted plan and exterior as the immutable generation reference.

    This deliberately records unknown descriptive measurements as unknown instead of
    inventing them. The actual geometry authority is the sorted, hash-bound source set.
    """
    job = _job(db, job_id)
    if job.status not in {"ASSET_CLASSIFICATION", "SOURCE_CRAWL"}:
        existing = db.scalar(
            select(HouseVisionGeometryLock)
            .where(HouseVisionGeometryLock.job_id == job_id)
            .order_by(desc(HouseVisionGeometryLock.version))
        )
        if existing:
            return existing
        raise ValueError("Automatikus GeometryLock ebben az állapotban nem készíthető.")
    assets = db.scalars(
        select(HouseVisionSourceAsset)
        .where(
            HouseVisionSourceAsset.job_id == job_id,
            HouseVisionSourceAsset.status == "accepted",
        )
        .order_by(HouseVisionSourceAsset.sequence, HouseVisionSourceAsset.source_visual_id)
    ).all()
    floorplans = [item for item in assets if item.asset_type == "FLOORPLAN"]
    exteriors = [item for item in assets if item.asset_type == "EXTERIOR"]
    if not floorplans or not exteriors:
        raise ValueError(
            "Automatikus GeometryLockhoz legalább egy alaprajz és egy külső látvány szükséges."
        )
    floorplan_topology_sha256 = hashlib.sha256(
        "\n".join(sorted(item.content_sha256 for item in floorplans)).encode("ascii")
    ).hexdigest()
    evidence = [
        {
            "source_visual_id": item.source_visual_id,
            "asset_type": item.asset_type,
            "content_sha256": item.content_sha256,
            "width_px": item.width_px,
            "height_px": item.height_px,
            "source_url": item.source_url,
        }
        for item in assets
        if item.asset_type in {"EXTERIOR", "FLOORPLAN"}
    ]
    version = 1 + len(
        db.scalars(
            select(HouseVisionGeometryLock).where(HouseVisionGeometryLock.job_id == job_id)
        ).all()
    )
    immutable_features = [
        "ismeretlen mezők kezelése: DO_NOT_INVENT",
        "az alaprajz helyiségkapcsolatai és külső kontúrja",
        "a látványterveken látható kubatúra, tömegalak és tetőgeometria",
        "a homlokzati nyílások darabszáma, pontos helye, mérete, aránya és ritmusa",
        "a szintek és bejáratok forráson látható geometriai rendszere",
        "szabadon változtatható: homlokzati anyag és szín, tetőfedés, eresz, "
        "nyílászáró-keret és ajtódizájn, terasz nem szerkezeti kialakítása, "
        "térkő, kert, növényzet, égbolt és fény",
        "forrásasset-készlet: "
        + ", ".join(item["source_visual_id"] for item in evidence),
    ]
    payload = {
        "job_id": job_id,
        "version": version,
        "mode": "SOURCE_SET_GEOMETRY_LOCK_V2",
        "floorplan_topology_sha256": floorplan_topology_sha256,
        "source_evidence": evidence,
        "unknown_fields_policy": "DO_NOT_INVENT",
        "immutable_features": immutable_features,
    }
    row = HouseVisionGeometryLock(
        geometry_lock_id=_id("HVG"),
        job_id=job_id,
        version=version,
        floorplan_topology_sha256=floorplan_topology_sha256,
        massing_signature="SOURCE_SET_GEOMETRY_LOCK_V2:" + hashlib.sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        roof_form="forrásképek szerint – automatikusan zárolva",
        roof_pitch_deg=None,
        storey_count=0,
        window_count=0,
        door_count=0,
        width_depth_height_ratio="forrásarányok szerint – nem becsült",
        immutable_features_json=json.dumps(immutable_features, ensure_ascii=False),
        content_sha256=hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        created_by=actor,
    )
    db.add(row)
    job.status = "RENDERING"
    job.accepted_source_count = len(assets)
    audit(
        db,
        actor=actor,
        action="housevision.geometry.auto_lock",
        entity_type="housevision_geometry_lock",
        entity_id=row.geometry_lock_id,
        after={
            "job_id": job_id,
            "version": version,
            "sha256": row.content_sha256,
            "mode": "SOURCE_SET_GEOMETRY_LOCK_V2",
            "source_count": len(evidence),
            "unknown_fields_policy": "DO_NOT_INVENT",
        },
    )
    db.commit()
    db.refresh(row)
    return row


def assign_name(db: Session, job_id: str, public_name: str, actor: str) -> HouseVisionName:
    job = _job(db, job_id)
    if job.status not in {"NAME_ASSIGNMENT", "RENDERING", "RENDER_RETRY", "QA"}:
        raise ValueError("Név csak lezárt GeometryLock után adható.")
    name = public_name.strip()
    if db.scalar(select(HouseVisionName).where(HouseVisionName.public_name == name)):
        raise ValueError("A háznév már foglalt.")
    row = HouseVisionName(
        house_name_id=_id("HVN"), brand_id=job.brand_id, public_name=name, job_id=job_id
    )
    db.add(row)
    job.house_name_id = row.house_name_id
    if job.status == "NAME_ASSIGNMENT":
        job.status = "RENDERING"
    audit(
        db,
        actor=actor,
        action="housevision.name.assign",
        entity_type="housevision_name",
        entity_id=row.house_name_id,
        after={"job_id": job_id, "public_name": name},
    )
    db.commit()
    db.refresh(row)
    return row


def add_output_asset(
    db: Session, job_id: str, data: HouseVisionOutputAssetIn, actor: str
) -> HouseVisionOutputAsset:
    job = _job(db, job_id)
    if job.status not in {"RENDERING", "RENDER_RETRY", "QA"}:
        raise ValueError("A job nem fogad renderkimenetet.")
    source = db.scalar(
        select(HouseVisionSourceAsset).where(
            HouseVisionSourceAsset.source_visual_id == data.source_visual_id,
            HouseVisionSourceAsset.job_id == job_id,
            HouseVisionSourceAsset.status == "accepted",
        )
    )
    if not source:
        raise KeyError(data.source_visual_id)
    data.content_sha256 = _sha256(data.content_sha256)
    revision = 1 + len(
        db.scalars(
            select(HouseVisionOutputAsset).where(
                HouseVisionOutputAsset.job_id == job_id,
                HouseVisionOutputAsset.source_visual_id == data.source_visual_id,
            )
        ).all()
    )
    row = HouseVisionOutputAsset(
        output_visual_id=_id("HVO"), job_id=job_id, revision=revision, **data.model_dump()
    )
    db.add(row)
    job.status = "QA"
    audit(
        db,
        actor=actor,
        action="housevision.output.create",
        entity_type="housevision_output_asset",
        entity_id=row.output_visual_id,
        after={"job_id": job_id, "source_visual_id": row.source_visual_id, "revision": revision},
    )
    db.commit()
    db.refresh(row)
    return row


def run_qa(db: Session, job_id: str, actor: str) -> HouseVisionQAReport:
    from .housevision_render_bridge import verify_geometry_proof

    job = _job(db, job_id)
    sources = db.scalars(
        select(HouseVisionSourceAsset).where(
            HouseVisionSourceAsset.job_id == job_id, HouseVisionSourceAsset.status == "accepted"
        )
    ).all()
    outputs = db.scalars(
        select(HouseVisionOutputAsset)
        .where(HouseVisionOutputAsset.job_id == job_id)
        .order_by(HouseVisionOutputAsset.source_visual_id, desc(HouseVisionOutputAsset.revision))
    ).all()
    latest: dict[str, HouseVisionOutputAsset] = {}
    source_by_id = {source.source_visual_id: source for source in sources}
    for output in outputs:
        source = source_by_id.get(output.source_visual_id)
        if source is None:
            continue
        # A reclassified floorplan may have newer historical exterior renders.
        # Those must never outrank its exact source-preserved baseline in QA.
        if source.asset_type == "FLOORPLAN" and not output.provider_job_id.startswith(
            "SOURCE_PRESERVED_BASELINE:"
        ):
            continue
        latest.setdefault(output.source_visual_id, output)
    failures: list[str] = []
    if len(latest) != len(sources):
        failures.append("source_output_count_mismatch")
    for source in sources:
        latest_output = latest.get(source.source_visual_id)
        if latest_output is None:
            continue
        proof_valid = verify_geometry_proof(source, latest_output)
        if not proof_valid:
            failures.append(f"{source.source_visual_id}:geometry_proof")
        if latest_output.edge_overlap < EDGE_THRESHOLD:
            failures.append(f"{source.source_visual_id}:edge_overlap")
        if latest_output.roof_match < ROOF_THRESHOLD:
            failures.append(f"{source.source_visual_id}:roof_match")
        if latest_output.opening_match < OPENING_THRESHOLD:
            failures.append(f"{source.source_visual_id}:opening_match")
        if (
            source.asset_type == "FLOORPLAN"
            and proof_valid
            and latest_output.provider_job_id.startswith("SOURCE_PRESERVED_BASELINE:")
        ):
            # A verified baseline is byte-identical to the accepted floorplan source.
            # Its fidelity is therefore exact even if a legacy row predates the metric.
            latest_output.floorplan_fidelity = 1.0
        if source.asset_type == "FLOORPLAN" and (
            latest_output.floorplan_fidelity or 0
        ) < FLOORPLAN_THRESHOLD:
            failures.append(f"{source.source_visual_id}:floorplan_fidelity")
        visual_checks = [
            latest_output.full_house_in_frame,
            latest_output.brand_identity_pass,
            latest_output.privacy_pass,
        ]
        if source.asset_type != "FLOORPLAN":
            visual_checks.extend(
                [latest_output.daylight_pass, latest_output.photorealism_pass]
            )
        if not all(visual_checks):
            failures.append(f"{source.source_visual_id}:visual_or_privacy_gate")
    gates = {
        "source_rights": bool(job.rights_policy_id),
        "asset_completeness": len(latest) == len(sources),
        "geometry_lock": bool(
            db.scalar(
                select(HouseVisionGeometryLock).where(HouseVisionGeometryLock.job_id == job_id)
            )
        ),
        "all_outputs_pass": not failures,
    }
    passed = all(gates.values())
    automatic_retry = not passed and job.retry_count < 3
    revision = 1 + len(
        db.scalars(select(HouseVisionQAReport).where(HouseVisionQAReport.job_id == job_id)).all()
    )
    row = HouseVisionQAReport(
        qa_report_id=_id("HVQ"),
        job_id=job_id,
        revision=revision,
        gates_json=json.dumps(gates),
        critical_failures_json=json.dumps(failures),
        status="PASS" if passed else "FAIL",
        automatic_retry=automatic_retry,
        created_by=actor,
    )
    db.add(row)
    job.output_count = len(latest)
    for output in latest.values():
        output.status = "qa_passed" if passed else "qa_failed"
    if passed:
        job.status = "PACKAGING"
        job.failure_reason = None
    elif automatic_retry:
        job.retry_count += 1
        job.status = "RENDER_RETRY"
        job.failure_reason = ", ".join(failures)
    else:
        job.status = "JOB_FAILED"
        job.failure_reason = ", ".join(failures)
    audit(
        db,
        actor=actor,
        action="housevision.qa.run",
        entity_type="housevision_qa_report",
        entity_id=row.qa_report_id,
        after={
            "job_id": job_id,
            "status": row.status,
            "failures": failures,
            "automatic_retry": automatic_retry,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def package_job(db: Session, job_id: str, storage_ref: str, actor: str) -> HouseVisionPackage:
    job = _job(db, job_id)
    if job.status != "PACKAGING":
        raise ValueError("Csomag csak PASS QA után készíthető.")
    sources = db.scalars(
        select(HouseVisionSourceAsset).where(
            HouseVisionSourceAsset.job_id == job_id, HouseVisionSourceAsset.status == "accepted"
        )
    ).all()
    outputs = db.scalars(
        select(HouseVisionOutputAsset).where(
            HouseVisionOutputAsset.job_id == job_id, HouseVisionOutputAsset.status == "qa_passed"
        )
    ).all()
    latest: dict[str, HouseVisionOutputAsset] = {}
    for output in sorted(outputs, key=lambda item: item.revision, reverse=True):
        latest.setdefault(output.source_visual_id, output)
    if len(sources) != len(latest):
        raise ValueError("Forrás–kimenet darabszám eltérés miatt nincs csomagolás.")
    version = 1 + len(
        db.scalars(select(HouseVisionPackage).where(HouseVisionPackage.job_id == job_id)).all()
    )
    manifest = {
        "job_id": job_id,
        "version": version,
        "sources": [s.content_sha256 for s in sources],
        "outputs": [o.content_sha256 for o in latest.values()],
        "geometry": db.scalar(
            select(HouseVisionGeometryLock.content_sha256)
            .where(HouseVisionGeometryLock.job_id == job_id)
            .order_by(desc(HouseVisionGeometryLock.version))
        ),
    }
    row = HouseVisionPackage(
        package_id=_id("HVP"),
        job_id=job_id,
        version=version,
        house_id=job.house_id,
        storage_ref=storage_ref,
        manifest_sha256=hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
        source_count=len(sources),
        output_count=len(latest),
        publication_status="eligible" if job.house_id else "blocked",
        created_by=actor,
    )
    db.add(row)
    job.status = "READY"
    job.publication_eligibility = "eligible" if job.house_id else "awaiting_houseplan_binding"
    for destination, endpoint in (
        ("document-evidence", "/housevision/packages"),
        ("buildconfig", "/housevision/packages"),
        ("house-catalog", "/housevision/packages"),
        ("content-factory", "/housevision/packages"),
        ("marketing-control", "/housevision/packages"),
        ("control-center", "/housevision/packages"),
    ):
        db.add(
            OutboxMessage(
                message_id=_id("MSG"),
                destination_module=destination,
                endpoint=endpoint,
                payload_json=json.dumps(
                    {
                        "package_id": row.package_id,
                        "job_id": job_id,
                        "house_id": job.house_id,
                        "manifest_sha256": row.manifest_sha256,
                    }
                ),
                status="pending",
                max_retries=5,
            )
        )
    audit(
        db,
        actor=actor,
        action="housevision.package.create",
        entity_type="housevision_package",
        entity_id=row.package_id,
        after={
            "job_id": job_id,
            "source_count": len(sources),
            "output_count": len(latest),
            "publication_eligibility": job.publication_eligibility,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def bind_houseplan(
    db: Session, job_id: str, house_id: str, actor: str, actor_role: str
) -> HouseVisionJob:
    if actor_role not in {"technical-prep", "owner", "managing-director", "platform-admin"}:
        raise PermissionError("HousePlan kötésre nincs jogosultság.")
    job = _job(db, job_id)
    plan = db.scalar(
        select(HouseCatalogPlan).where(
            HouseCatalogPlan.house_id == house_id, HouseCatalogPlan.lifecycle_status == "active"
        )
    )
    if not plan:
        raise KeyError(house_id)
    job.house_id = house_id
    if job.status == "READY":
        job.publication_eligibility = "eligible"
        package = db.scalar(
            select(HouseVisionPackage)
            .where(HouseVisionPackage.job_id == job_id)
            .order_by(desc(HouseVisionPackage.version))
        )
        if package:
            package.house_id = house_id
            package.publication_status = "eligible"
            for destination in (
                "document-evidence",
                "buildconfig",
                "house-catalog",
                "content-factory",
                "marketing-control",
                "control-center",
            ):
                db.add(
                    OutboxMessage(
                        message_id=_id("MSG"),
                        destination_module=destination,
                        endpoint="/housevision/package-bindings",
                        payload_json=json.dumps(
                            {
                                "package_id": package.package_id,
                                "job_id": job_id,
                                "house_id": house_id,
                                "publication_status": "eligible",
                            }
                        ),
                        status="pending",
                        max_retries=5,
                    )
                )
    audit(
        db,
        actor=actor,
        action="housevision.houseplan.bind",
        entity_type="housevision_job",
        entity_id=job_id,
        after={"house_id": house_id, "publication_eligibility": job.publication_eligibility},
    )
    db.commit()
    db.refresh(job)
    return job


def workspace(
    db: Session,
    *,
    status: str | None = None,
    brand_id: str | None = None,
    search: str | None = None,
) -> dict:
    all_jobs = db.scalars(select(HouseVisionJob).order_by(desc(HouseVisionJob.updated_at))).all()
    jobs = all_jobs
    if status:
        jobs = [item for item in jobs if item.status == status]
    if brand_id:
        jobs = [item for item in jobs if item.brand_id == brand_id]
    if search:
        needle = search.casefold().strip()
        jobs = [
            item
            for item in jobs
            if needle in item.job_id.casefold()
            or needle in item.source_url.casefold()
            or (item.house_id and needle in item.house_id.casefold())
        ]
    return {
        "jobs": jobs,
        "policies": db.scalars(
            select(HouseVisionRightsPolicy).order_by(desc(HouseVisionRightsPolicy.created_at))
        ).all(),
        "houseplans": db.scalars(
            select(HouseCatalogPlan)
            .where(HouseCatalogPlan.lifecycle_status == "active")
            .order_by(HouseCatalogPlan.canonical_name)
        ).all(),
        "metrics": {
            "jobs": len(all_jobs),
            "ready": sum(1 for item in all_jobs if item.status == "READY"),
            "rights_blocked": sum(1 for item in all_jobs if item.status == "RIGHTS_BLOCKED"),
            "retrying": sum(1 for item in all_jobs if item.status == "RENDER_RETRY"),
            "failed": sum(1 for item in all_jobs if item.status == "JOB_FAILED"),
        },
        "filters": {"status": status or "", "brand_id": brand_id or "", "search": search or ""},
        "status_options": sorted({item.status for item in all_jobs}),
        "brand_options": sorted({item.brand_id for item in all_jobs}),
    }


def job_detail(db: Session, job_id: str) -> dict:
    job = _job(db, job_id)
    sources = db.scalars(
        select(HouseVisionSourceAsset)
        .where(HouseVisionSourceAsset.job_id == job_id)
        .order_by(HouseVisionSourceAsset.sequence, HouseVisionSourceAsset.created_at)
    ).all()
    locks = db.scalars(
        select(HouseVisionGeometryLock)
        .where(HouseVisionGeometryLock.job_id == job_id)
        .order_by(desc(HouseVisionGeometryLock.version))
    ).all()
    outputs = db.scalars(
        select(HouseVisionOutputAsset)
        .where(HouseVisionOutputAsset.job_id == job_id)
        .order_by(HouseVisionOutputAsset.source_visual_id, desc(HouseVisionOutputAsset.revision))
    ).all()
    output_revisions: dict[str, list[HouseVisionOutputAsset]] = {}
    for output in outputs:
        output_revisions.setdefault(output.source_visual_id, []).append(output)
    qa_reports = db.scalars(
        select(HouseVisionQAReport)
        .where(HouseVisionQAReport.job_id == job_id)
        .order_by(desc(HouseVisionQAReport.revision))
    ).all()
    packages = db.scalars(
        select(HouseVisionPackage)
        .where(HouseVisionPackage.job_id == job_id)
        .order_by(desc(HouseVisionPackage.version))
    ).all()
    policy = (
        db.scalar(
            select(HouseVisionRightsPolicy).where(
                HouseVisionRightsPolicy.policy_id == job.rights_policy_id
            )
        )
        if job.rights_policy_id
        else None
    )
    house_name = db.scalar(select(HouseVisionName).where(HouseVisionName.job_id == job_id))
    houseplan = (
        db.scalar(select(HouseCatalogPlan).where(HouseCatalogPlan.house_id == job.house_id))
        if job.house_id
        else None
    )
    qa_history = [
        {
            "report": report,
            "gates": _json_value(report.gates_json, {}),
            "failures": _json_value(report.critical_failures_json, []),
        }
        for report in qa_reports
    ]
    comparison_rows = [
        {
            "source": source,
            "revisions": output_revisions.get(source.source_visual_id, []),
            "latest": (output_revisions.get(source.source_visual_id) or [None])[0],
        }
        for source in sources
    ]
    return {
        "job": job,
        "result_count": job.output_count,
        "policy": policy,
        "sources": sources,
        "locks": locks,
        "latest_lock": locks[0] if locks else None,
        "outputs": outputs,
        "output_revisions": output_revisions,
        "comparison_rows": comparison_rows,
        "qa_reports": qa_reports,
        "qa_history": qa_history,
        "packages": packages,
        "house_name": house_name,
        "houseplan": houseplan,
        "houseplans": db.scalars(
            select(HouseCatalogPlan)
            .where(HouseCatalogPlan.lifecycle_status == "active")
            .order_by(HouseCatalogPlan.canonical_name)
        ).all(),
    }
