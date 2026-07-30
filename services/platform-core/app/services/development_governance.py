from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import DevelopmentDiscoveryRecord, ModuleRegistry
from ..schemas import DevelopmentDiscoveryIn, DevelopmentDiscoveryReviewIn

ALLOWED_DECISIONS = {"reuse", "extend", "integrate", "repair", "new_exception"}
PASSING_DECISIONS = {"reuse", "extend", "integrate", "repair"}


def canonical_module_key(module_key: str | None) -> str | None:
    if not module_key:
        return None
    return module_key.strip().replace("_", "-")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_discovery(db: Session, data: DevelopmentDiscoveryIn, *, actor: str = "api") -> DevelopmentDiscoveryRecord:
    requested_module_key = canonical_module_key(data.requested_module_key)
    canonical_key = canonical_module_key(data.canonical_module_key)
    if data.decision not in ALLOWED_DECISIONS:
        raise ValueError("Érvénytelen reuse döntés.")
    if data.decision in PASSING_DECISIONS and not canonical_key:
        raise ValueError("Újrafelhasználásnál kötelező a kanonikus ModuleKey.")
    if data.decision == "new_exception" and not data.exception_reason:
        raise ValueError("Új kivételes megvalósításnál kötelező az indoklás.")
    if canonical_key:
        module = db.scalar(
            select(ModuleRegistry).where(ModuleRegistry.module_key == canonical_key)
        )
        if not module:
            raise ValueError("A kanonikus ModuleKey nem található a modulregiszterben.")
    row = db.scalar(select(DevelopmentDiscoveryRecord).where(DevelopmentDiscoveryRecord.discovery_id == data.discovery_id))
    if not row:
        row = DevelopmentDiscoveryRecord(discovery_id=data.discovery_id, requested_capability=data.requested_capability, decision=data.decision, implementation_gap=data.implementation_gap)
        db.add(row)
    row.requested_capability = data.requested_capability
    row.requested_module_key = requested_module_key
    row.searched_terms_json = json.dumps(data.searched_terms, ensure_ascii=False)
    row.candidate_artifacts_json = json.dumps(data.candidate_artifacts, ensure_ascii=False)
    row.canonical_module_key = canonical_key
    row.canonical_object_owner = data.canonical_object_owner
    row.source_version = data.source_version
    row.source_sha256 = data.source_sha256
    row.decision = data.decision
    row.implementation_gap = data.implementation_gap
    row.exception_reason = data.exception_reason
    row.requested_by = data.requested_by or actor
    row.status = "pending_review"
    row.exception_approved = False
    audit(db, actor=actor, action="development_discovery_upsert", entity_type="development_discovery", entity_id=row.discovery_id, after=data.model_dump())
    db.commit(); db.refresh(row)
    return row


def review_discovery(db: Session, discovery_id: str, data: DevelopmentDiscoveryReviewIn, *, actor: str = "api") -> DevelopmentDiscoveryRecord:
    row = db.scalar(select(DevelopmentDiscoveryRecord).where(DevelopmentDiscoveryRecord.discovery_id == discovery_id))
    if not row:
        raise KeyError(discovery_id)
    if data.status not in {"approved", "rejected"}:
        raise ValueError("A review státusz approved vagy rejected lehet.")
    if row.decision == "new_exception" and data.status == "approved" and not data.exception_approved:
        raise ValueError("Az új kivételes megvalósításhoz tulajdonosi kivétel-jóváhagyás szükséges.")
    row.status = data.status
    row.exception_approved = bool(data.exception_approved)
    row.reviewed_by = data.reviewed_by
    row.reviewed_at = utcnow()
    audit(db, actor=actor, action="development_discovery_review", entity_type="development_discovery", entity_id=row.discovery_id, after=data.model_dump())
    db.commit(); db.refresh(row)
    return row


def discovery_passes(row: DevelopmentDiscoveryRecord | None) -> bool:
    if not row or row.status != "approved":
        return False
    if row.decision in PASSING_DECISIONS:
        return bool(row.canonical_module_key)
    return row.decision == "new_exception" and row.exception_approved


def latest_approved_for_module(db: Session, module_key: str) -> DevelopmentDiscoveryRecord | None:
    normalized_key = canonical_module_key(module_key)
    accepted_keys = {module_key, normalized_key}
    rows = db.scalars(select(DevelopmentDiscoveryRecord).where(
        DevelopmentDiscoveryRecord.status == "approved",
        (DevelopmentDiscoveryRecord.requested_module_key.in_(accepted_keys))
        | (DevelopmentDiscoveryRecord.canonical_module_key.in_(accepted_keys)),
    ).order_by(desc(DevelopmentDiscoveryRecord.reviewed_at), desc(DevelopmentDiscoveryRecord.id))).all()
    return next((r for r in rows if discovery_passes(r)), None)


def list_discoveries(db: Session) -> list[DevelopmentDiscoveryRecord]:
    return list(db.scalars(select(DevelopmentDiscoveryRecord).order_by(desc(DevelopmentDiscoveryRecord.created_at))).all())


def seed_canonical_discoveries(db: Session, modules: list[tuple[str, str, str, str, str]]) -> None:
    for key, name, version, owner, _criticality in modules:
        did = f"DISC-CANON-{key.upper()}"
        row = db.scalar(select(DevelopmentDiscoveryRecord).where(DevelopmentDiscoveryRecord.discovery_id == did))
        if row:
            continue
        db.add(DevelopmentDiscoveryRecord(
            discovery_id=did,
            requested_capability=name,
            requested_module_key=key,
            searched_terms_json=json.dumps([key, name], ensure_ascii=False),
            candidate_artifacts_json=json.dumps([{"module_key": key, "version": version, "source": "Control Center modulregiszter"}], ensure_ascii=False),
            canonical_module_key=key,
            canonical_object_owner=owner,
            source_version=version,
            decision="reuse",
            implementation_gap="A meglévő kanonikus modul továbbfejlesztése és integrációja; párhuzamos üzleti motor nem hozható létre.",
            status="approved",
            requested_by="system_seed",
            reviewed_by="owner_policy",
            reviewed_at=utcnow(),
        ))
