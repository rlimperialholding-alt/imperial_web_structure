from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..audit import audit
from ..models import ArtifactRecord, DevelopmentDiscoveryRecord, ReleaseRecord
from ..schemas import ArtifactIn, ReleaseIn
from .development_governance import discovery_passes, latest_approved_for_module


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_release(db: Session, data: ReleaseIn, *, actor: str = "api") -> ReleaseRecord:
    row = db.scalar(select(ReleaseRecord).where(ReleaseRecord.release_id == data.release_id))
    if not row:
        row = ReleaseRecord(release_id=data.release_id, module_key=data.module_key, version=data.version)
        db.add(row)
    for field, value in data.model_dump().items():
        if field != "release_id" and field != "discovery_request_id":
            setattr(row, field, value)
    discovery = None
    if data.discovery_request_id:
        discovery = db.scalar(select(DevelopmentDiscoveryRecord).where(DevelopmentDiscoveryRecord.discovery_id == data.discovery_request_id))
        if not discovery:
            raise ValueError("A megadott discovery rekord nem található.")
    else:
        discovery = latest_approved_for_module(db, data.module_key)
    row.discovery_request_id = discovery.discovery_id if discovery else None
    row.reuse_gate_passed = discovery_passes(discovery)
    row.status = calculate_release_status(row, [])
    audit(db, actor=actor, action="release_upsert", entity_type="release", entity_id=data.release_id, after=data.model_dump())
    db.commit()
    db.refresh(row)
    return row


def add_artifact(db: Session, release_id: str, data: ArtifactIn, *, actor: str = "api") -> ArtifactRecord:
    release = db.scalar(select(ReleaseRecord).where(ReleaseRecord.release_id == release_id))
    if not release:
        raise ValueError("Kiadás nem található.")
    artifact = db.scalar(select(ArtifactRecord).where(ArtifactRecord.artifact_id == data.artifact_id))
    if not artifact:
        artifact = ArtifactRecord(release_id_fk=release.id, **data.model_dump())
        db.add(artifact)
    else:
        for field, value in data.model_dump().items():
            if field != "artifact_id":
                setattr(artifact, field, value)
    if artifact.cloud_status == "verified":
        artifact.verified_at = utcnow()
    db.flush()
    artifacts = db.scalars(select(ArtifactRecord).where(ArtifactRecord.release_id_fk == release.id)).all()
    release.status = calculate_release_status(release, artifacts)
    audit(db, actor=actor, action="artifact_upsert", entity_type="artifact", entity_id=data.artifact_id, after=data.model_dump())
    db.commit()
    db.refresh(artifact)
    return artifact


def calculate_release_status(release: ReleaseRecord, artifacts: list[ArtifactRecord]) -> str:
    if not release.reuse_gate_passed:
        return "discovery_blocked"
    types_verified = {a.artifact_type for a in artifacts if a.cloud_status == "verified"}
    archive_ready = {"source_zip", "sha256"}.issubset(types_verified)
    tests_ok = release.tests_total > 0 and release.tests_passed == release.tests_total
    if not archive_ready:
        return "archive_pending"
    if not tests_ok:
        return "test_blocked"
    production_ready = all([
        release.migration_tested,
        release.uat_approved,
        release.security_reviewed,
        release.backup_restore_tested,
        release.owner_approved,
    ])
    return "production_ready" if production_ready else "uat_ready"


def release_gate(db: Session, release_id: str) -> dict:
    release = db.scalar(select(ReleaseRecord).where(ReleaseRecord.release_id == release_id).options(selectinload(ReleaseRecord.artifacts)))
    if not release:
        raise ValueError("Kiadás nem található.")
    types_verified = {a.artifact_type for a in release.artifacts if a.cloud_status == "verified"}
    checks = {
        "canonical_reuse_discovery_approved": bool(release.reuse_gate_passed and release.discovery_request_id),
        "source_zip_cloud_verified": "source_zip" in types_verified,
        "sha256_cloud_verified": "sha256" in types_verified,
        "tests_passed": release.tests_total > 0 and release.tests_passed == release.tests_total,
        "migration_tested": release.migration_tested,
        "uat_approved": release.uat_approved,
        "security_reviewed": release.security_reviewed,
        "backup_restore_tested": release.backup_restore_tested,
        "owner_approved": release.owner_approved,
    }
    release.status = calculate_release_status(release, list(release.artifacts))
    db.commit()
    return {"release_id": release.release_id, "status": release.status, "checks": checks, "production_allowed": all(checks.values())}
