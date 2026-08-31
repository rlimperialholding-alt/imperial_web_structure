from __future__ import annotations

import hashlib
import hmac
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from itertools import combinations
from math import ceil
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import audit
from app.models import (
    AuditLog,
    HouseBuildCase,
    HouseBuildGate,
    HouseBuildValidation,
    HouseBuildVariant,
    HouseCatalogPlan,
    HouseCatalogVersion,
    HousePlanBatch,
    HousePlanBatchItem,
    HousePlanRecord,
    HousePlanSource,
    HouseStudioPermissionGrant,
    ProjectRegistry,
    TaskRecord,
    User,
)
from app.services.house_batch import HouseBatchError, validate_dry_run_token
from app.services.house_geometry import (
    RULESET_VERSION,
    HouseGeometryError,
    canonical_json,
    generate_houseplan,
)
from app.services.house_svg import render_houseplan_svg

NEAR_DUPLICATE_WARNING = Decimal("0.90")
NEAR_DUPLICATE_BLOCK = Decimal("0.97")
CATALOG_GOVERNANCE_PROJECT = "HOUSE-CATALOG-GOVERNANCE"


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex.upper()}"


def _sha(value: Any) -> str:
    raw = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return canonical_json(value)


_DEMO_GRANTS = {
    "platform-admin": {
        "ii.houseplan.read",
        "ii.houseplan.generate",
        "ii.houseplan.review",
        "ii.house-source.create",
        "ii.house-source.approve",
        "ii.house-source.revoke",
        "ii.house-batch.retry",
    },
    "technical-prep": {
        "ii.houseplan.read",
        "ii.houseplan.generate",
        "ii.houseplan.review",
        "ii.house-source.create",
        "ii.house-batch.retry",
    },
    "designer": {"ii.houseplan.read"},
    "legal": {
        "ii.houseplan.read",
        "ii.house-source.approve",
        "ii.house-source.revoke",
    },
    "managing-director": {
        "ii.houseplan.read",
        "ii.house-source.approve",
        "ii.house-source.revoke",
    },
}

_HOUSE_STUDIO_PERMISSIONS = set().union(*_DEMO_GRANTS.values()) | {"ii.house-designer.read"}


def ingest_signed_permission_replica(
    db: Session,
    *,
    payload: dict[str, Any],
    signature: str,
    secret: str,
) -> int:
    """Atomically ingest an ITEP-signed, versioned identity/permission snapshot."""

    if len(secret) < 32:
        raise PermissionError("ITEP replica verification secret is not configured securely.")
    raw = canonical_json(payload)
    expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.strip().lower(), expected):
        raise PermissionError("Invalid ITEP permission replica signature.")
    if payload.get("issuer") != "itep":
        raise ValueError("Permission replica issuer must be itep.")
    subject = str(payload.get("subjectId") or "")
    email = str(payload.get("email") or "").strip().lower()
    revision = str(payload.get("revision") or "").strip()
    try:
        sequence = int(payload["sequence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("A positive integer sequence is required.") from exc
    if not subject.startswith("ITEP-") or not email or not revision or sequence < 1:
        raise ValueError("subjectId, email, revision and a positive sequence are required.")
    try:
        valid_from = _as_utc(datetime.fromisoformat(str(payload["validFrom"])))
        expires_at = _as_utc(datetime.fromisoformat(str(payload["expiresAt"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("validFrom and expiresAt must be ISO-8601 timestamps.") from exc
    now = utcnow()
    if not valid_from <= now < expires_at:
        raise ValueError("ITEP permission replica is not active.")
    raw_grants = payload.get("grants")
    if not isinstance(raw_grants, list) or not raw_grants:
        raise ValueError("At least one permission grant is required.")
    normalized: list[tuple[str, str, str, str | None]] = []
    for item in raw_grants:
        if not isinstance(item, dict):
            raise ValueError("Each grant must be a JSON object.")
        permission = str(item.get("permission") or "")
        effect = str(item.get("effect") or "")
        scope_type = str(item.get("scopeType") or "")
        project_id = str(item.get("projectId") or "").strip() or None
        if permission not in _HOUSE_STUDIO_PERMISSIONS:
            raise ValueError(f"Unknown House Studio permission: {permission}.")
        if effect not in {"allow", "deny"}:
            raise ValueError("Each grant effect must be allow or deny.")
        if scope_type not in {"global", "project"}:
            raise ValueError("scopeType must be global or project.")
        if scope_type == "global" and project_id is not None:
            raise ValueError("A global grant cannot contain projectId.")
        if scope_type == "project":
            if (
                project_id is None
                or db.scalar(
                    select(ProjectRegistry).where(ProjectRegistry.project_id == project_id)
                )
                is None
            ):
                raise ValueError("A project-scoped grant needs a canonical projectId.")
        normalized.append((permission, effect, scope_type, project_id))
    if len(normalized) != len(set(normalized)):
        raise ValueError("Permission replica contains duplicate grants.")

    user = db.scalar(
        select(User).where(User.email == email, User.active.is_(True)).with_for_update()
    )
    if user is None:
        raise ValueError("ITEP replica user is missing or inactive.")
    collision = db.scalar(select(User).where(User.itep_subject_id == subject, User.id != user.id))
    if collision:
        raise ValueError("ITEP subject already belongs to another user.")

    claim_sha = _sha(payload)
    prior_sequences = db.scalars(
        select(HouseStudioPermissionGrant.claim_sequence).where(
            HouseStudioPermissionGrant.subject_id == subject
        )
    ).all()
    watermark = max(prior_sequences, default=0)
    if sequence < watermark:
        raise ValueError("ITEP permission replica rollback is forbidden.")
    if sequence == watermark and watermark > 0:
        prior_claims = db.scalars(
            select(HouseStudioPermissionGrant.claim_sha256).where(
                HouseStudioPermissionGrant.subject_id == subject,
                HouseStudioPermissionGrant.claim_sequence == sequence,
            )
        ).all()
        if any(value != claim_sha for value in prior_claims):
            raise ValueError("ITEP permission sequence conflict.")
    revision_claims = db.scalars(
        select(HouseStudioPermissionGrant.claim_sha256).where(
            HouseStudioPermissionGrant.subject_id == subject,
            HouseStudioPermissionGrant.revision == revision,
        )
    ).all()
    if revision_claims and any(value != claim_sha for value in revision_claims):
        raise ValueError("ITEP permission revision conflict.")
    existing = db.scalars(
        select(HouseStudioPermissionGrant).where(
            HouseStudioPermissionGrant.subject_id == subject,
            HouseStudioPermissionGrant.revision == revision,
            HouseStudioPermissionGrant.claim_sha256 == claim_sha,
        )
    ).all()
    if len(existing) == len(normalized):
        user.itep_subject_id = subject
        db.commit()
        return 0

    previous_subject = str(user.itep_subject_id or "")
    active_subjects = {subject}
    if previous_subject.startswith("ITEP-"):
        active_subjects.add(previous_subject)
    active = db.scalars(
        select(HouseStudioPermissionGrant)
        .where(
            HouseStudioPermissionGrant.subject_id.in_(active_subjects),
            HouseStudioPermissionGrant.status == "active",
        )
        .with_for_update()
    ).all()
    for grant in active:
        grant.status = "revoked"
    user.itep_subject_id = subject
    for index, (permission, effect, scope_type, project_id) in enumerate(
        sorted(normalized), start=1
    ):
        grant_hash = _sha([subject, sequence, index, permission, effect, project_id])
        db.add(
            HouseStudioPermissionGrant(
                grant_id=f"HSG-{grant_hash[:40]}",
                subject_id=subject,
                permission=permission,
                effect=effect,
                scope_type=scope_type,
                project_id=project_id,
                revision=revision,
                claim_sequence=sequence,
                claim_issuer="itep",
                claim_sha256=claim_sha,
                status="active",
                valid_from=valid_from,
                expires_at=expires_at,
            )
        )
    audit(
        db,
        actor="ITEP-PERMISSION-REPLICA",
        action="house_studio_permissions_replicated",
        entity_type="User",
        entity_id=str(user.id),
        after={
            "claim_sha256": claim_sha,
            "grant_count": len(normalized),
            "revision": revision,
            "sequence": sequence,
            "subject_id": subject,
        },
    )
    db.commit()
    return len(normalized)


def ensure_house_studio_demo_grants(db: Session, *, enabled: bool) -> int:
    if not enabled:
        return 0
    now = utcnow()
    inserted = 0
    for user in db.scalars(
        select(User).where(User.active.is_(True), User.itep_subject_id.is_not(None))
    ).all():
        subject = str(user.itep_subject_id)
        for permission in sorted(_DEMO_GRANTS.get(user.role, set())):
            grant_id = f"HSG-DEMO-{user.id}-{_sha(permission)[:16]}"
            if db.scalar(
                select(HouseStudioPermissionGrant).where(
                    HouseStudioPermissionGrant.grant_id == grant_id
                )
            ):
                continue
            claim = {
                "issuer": "imperial-test-fixture",
                "permission": permission,
                "scope": "global",
                "subject": subject,
            }
            db.add(
                HouseStudioPermissionGrant(
                    grant_id=grant_id,
                    subject_id=subject,
                    permission=permission,
                    effect="allow",
                    scope_type="global",
                    project_id=None,
                    revision="demo-permissions-v1",
                    claim_sequence=1,
                    claim_issuer="imperial-test-fixture",
                    claim_sha256=_sha(claim),
                    status="active",
                    valid_from=now,
                    expires_at=now.replace(year=now.year + 5),
                )
            )
            inserted += 1
    if inserted:
        db.commit()
    return inserted


def authorize_house_studio(
    db: Session,
    user: User,
    permission: str,
    *,
    project_id: str | None = None,
) -> tuple[str, str]:
    subject = str(user.itep_subject_id or "")
    if not subject.startswith("ITEP-"):
        raise PermissionError("Kanonikus ITEP subject hiányzik.")
    now = utcnow()
    candidates = db.scalars(
        select(HouseStudioPermissionGrant).where(
            HouseStudioPermissionGrant.subject_id == subject,
            HouseStudioPermissionGrant.permission == permission,
            HouseStudioPermissionGrant.status == "active",
        )
    ).all()
    active_candidates = [
        grant
        for grant in candidates
        if _as_utc(grant.valid_from) <= now < _as_utc(grant.expires_at)
    ]
    if project_id is None and any(
        grant.effect == "deny" and grant.scope_type == "project" for grant in active_candidates
    ):
        raise PermissionError(
            "An explicit project_id is required because project-scoped deny grants exist."
        )
    grants = [
        grant
        for grant in active_candidates
        if (
            grant.scope_type == "global"
            or (project_id is not None and grant.project_id == project_id)
        )
    ]
    if any(grant.effect == "deny" for grant in grants):
        raise PermissionError("An active ITEP deny grant blocks this operation.")
    grants = [grant for grant in grants if grant.effect == "allow"]
    if not grants:
        raise PermissionError("A művelethez nincs aktív, scope-helyes ITEP jogosultság.")
    if (
        project_id is not None
        and db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == project_id))
        is None
    ):
        raise PermissionError("A megadott projekt nem létezik a kanonikus projekttörzsben.")
    revision = _sha(
        [
            {
                "claim": grant.claim_sha256,
                "grant": grant.grant_id,
                "revision": grant.revision,
            }
            for grant in sorted(grants, key=lambda item: item.grant_id)
        ]
    )
    return subject, f"itep-permissions:{revision}"


def ensure_houseplan_source_cutover(db: Session, *, demo_auto_approve: bool) -> int:
    """Idempotently quarantine legacy evidence; only test fixtures auto-approve."""

    inserted = 0
    released = db.scalars(
        select(HouseCatalogVersion).where(
            HouseCatalogVersion.status == "released",
            HouseCatalogVersion.content_sha256.is_not(None),
            HouseCatalogVersion.source_approved_by.is_not(None),
            HouseCatalogVersion.source_approved_at.is_not(None),
        )
    ).all()
    for version in released:
        approved_at = version.source_approved_at
        if approved_at is None:
            continue
        existing = db.scalar(
            select(HousePlanSource).where(
                HousePlanSource.catalog_version_id == version.catalog_version_id,
                HousePlanSource.source_revision == 1,
            )
        )
        if existing:
            continue
        evidence = version.rights_evidence.strip()
        row = HousePlanSource(
            source_id=f"HPS-{version.catalog_version_id}-R1",
            catalog_version_id=version.catalog_version_id,
            source_revision=1,
            content_sha256=str(version.content_sha256),
            legal_basis="owned" if demo_auto_approve else "unknown",
            licence_scope=(
                "Tesztkörnyezet: belső tervezés és katalóguspróba."
                if demo_auto_approve
                else "Karantén: a jogalap és a felhasználási hatály jogi ellenőrzésre vár."
            ),
            evidence_ref=f"catalog-version:{version.catalog_version_id}",
            evidence_sha256=_sha(evidence),
            rights_snapshot_json=_json(
                {
                    "catalogSourceApprovedAt": approved_at.isoformat(),
                    "catalogSourceApprovedBy": version.source_approved_by,
                    "rightsEvidence": evidence,
                }
            ),
            status="approved" if demo_auto_approve else "rights_review",
            approved_by_subject=("ITEP-TEST-RIGHTS-REVIEWER" if demo_auto_approve else None),
            approved_at=approved_at if demo_auto_approve else None,
            created_by_subject=(
                "ITEP-TEST-CATALOG-MIGRATION" if demo_auto_approve else "MIGRATION-QUARANTINE"
            ),
        )
        db.add(row)
        try:
            db.commit()
            inserted += 1
        except IntegrityError:
            db.rollback()
    return inserted


def list_houseplan_sources(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(HousePlanSource, HouseCatalogVersion, HouseCatalogPlan)
        .join(
            HouseCatalogVersion,
            HouseCatalogVersion.catalog_version_id == HousePlanSource.catalog_version_id,
        )
        .join(HouseCatalogPlan, HouseCatalogPlan.house_id == HouseCatalogVersion.house_id)
        .order_by(
            HouseCatalogPlan.canonical_name,
            HousePlanSource.source_revision.desc(),
        )
    ).all()
    return [
        {
            "source_id": source.source_id,
            "catalog_version_id": version.catalog_version_id,
            "house_id": plan.house_id,
            "house_name": plan.canonical_name,
            "revision": source.source_revision,
            "legal_basis": source.legal_basis,
            "licence_scope": source.licence_scope,
            "evidence_ref": source.evidence_ref,
            "status": source.status,
            "creator_subject": source.created_by_subject,
            "approved_by_subject": source.approved_by_subject,
            "expires_at": source.expires_at,
            "revocation_reason": source.revocation_reason,
        }
        for source, version, plan in rows
    ]


def house_studio_workspace(
    db: Session,
    *,
    batch_status: str = "",
    plan_status: str = "",
    project_id: str = "",
) -> dict[str, Any]:
    batch_stmt = select(HousePlanBatch).order_by(HousePlanBatch.created_at.desc())
    if batch_status:
        batch_stmt = batch_stmt.where(HousePlanBatch.status == batch_status)
    if project_id:
        batches = [
            batch
            for batch in db.scalars(batch_stmt).all()
            if any(
                str(row.get("project_id") or CATALOG_GOVERNANCE_PROJECT) == project_id
                for row in json.loads(batch.request_json)
                if isinstance(row, dict)
            )
        ][:100]
    else:
        batches = list(db.scalars(batch_stmt.limit(100)).all())
    plan_stmt = select(HousePlanRecord).order_by(HousePlanRecord.updated_at.desc()).limit(200)
    if plan_status:
        plan_stmt = plan_stmt.where(HousePlanRecord.status == plan_status)
    if project_id:
        plan_stmt = plan_stmt.where(HousePlanRecord.project_id == project_id)
    plans = db.scalars(plan_stmt).all()
    tasks = db.scalars(
        select(TaskRecord)
        .where(TaskRecord.source_event_id.in_([plan.plan_id for plan in plans]))
        .order_by(TaskRecord.updated_at.desc())
    ).all()
    return {
        "batches": batches,
        "plans": plans,
        "plancheck_tasks": tasks,
        "filters": {
            "batch_status": batch_status,
            "plan_status": plan_status,
            "project_id": project_id,
        },
    }


def houseplan_batch_detail(db: Session, batch_id: str) -> dict[str, Any]:
    batch = db.scalar(select(HousePlanBatch).where(HousePlanBatch.batch_id == batch_id))
    if batch is None:
        raise KeyError(batch_id)
    rows = json.loads(batch.request_json)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("A kĂ¶teg eltĂˇrolt kĂ©rĂ©se sĂ©rĂĽlt.")
    items = db.scalars(
        select(HousePlanBatchItem)
        .where(HousePlanBatchItem.batch_id == batch_id)
        .order_by(HousePlanBatchItem.row_number)
    ).all()
    return {"batch": batch, "items": items, "rows": rows}


def houseplan_detail(db: Session, plan_id: str) -> dict[str, Any]:
    plan = db.scalar(select(HousePlanRecord).where(HousePlanRecord.plan_id == plan_id))
    if plan is None:
        raise KeyError(plan_id)
    geometry = json.loads(plan.geometry_json)
    predecessor = (
        db.scalar(
            select(HousePlanRecord).where(HousePlanRecord.plan_id == plan.predecessor_plan_id)
        )
        if plan.predecessor_plan_id
        else None
    )
    history = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.entity_type == "HousePlanRecord",
            AuditLog.entity_id == plan_id,
        )
        .order_by(AuditLog.created_at)
    ).all()
    return {
        "plan": plan,
        "normalized": json.loads(plan.normalized_input_json),
        "geometry": geometry,
        "svg": render_houseplan_svg(geometry),
        "history": history,
        "predecessor": predecessor,
        "comparison": (
            {
                "geometry_changed": predecessor.geometry_signature != plan.geometry_signature,
                "input_changed": predecessor.input_hash != plan.input_hash,
                "previous_geometry_signature": predecessor.geometry_signature,
                "previous_input_hash": predecessor.input_hash,
                "previous_version": predecessor.version_number,
            }
            if predecessor
            else None
        ),
    }


def batch_retry_context(
    db: Session, batch_id: str
) -> tuple[HousePlanBatch, list[dict[str, Any]], dict[str, Any]]:
    batch = db.scalar(select(HousePlanBatch).where(HousePlanBatch.batch_id == batch_id))
    if batch is None:
        raise KeyError(batch_id)
    if batch.status not in {"failed", "partial"}:
        raise ValueError("Csak failed vagy partial köteg indítható újra.")
    rows = json.loads(batch.request_json)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("A köteg eltárolt kérése sérült.")
    source_row = db.execute(
        select(HousePlanSource, HouseCatalogVersion)
        .join(
            HouseCatalogVersion,
            HouseCatalogVersion.catalog_version_id == HousePlanSource.catalog_version_id,
        )
        .where(HousePlanSource.source_id == batch.source_id)
    ).first()
    if source_row is None:
        raise ValueError("A köteg forrása nem található.")
    _source, version = source_row
    return batch, rows, active_source_for_house(db, version.house_id)


def active_source_for_house(db: Session, house_id: str) -> dict[str, Any]:
    now = utcnow()
    row = db.execute(
        select(HousePlanSource, HouseCatalogVersion, HouseCatalogPlan)
        .join(
            HouseCatalogVersion,
            HouseCatalogVersion.catalog_version_id == HousePlanSource.catalog_version_id,
        )
        .join(HouseCatalogPlan, HouseCatalogPlan.house_id == HouseCatalogVersion.house_id)
        .where(
            HouseCatalogPlan.house_id == house_id,
            HouseCatalogPlan.lifecycle_status == "active",
            HouseCatalogVersion.status == "released",
        )
        .order_by(HousePlanSource.source_revision.desc())
    ).first()
    if row is None:
        raise HouseBatchError("A forráshoz nincs HouseSource jogi revízió.")
    source, version, plan = row
    if source.status != "approved":
        raise HouseBatchError(f"A legújabb HouseSource revízió nem végrehajtható: {source.status}.")
    if source.expires_at is not None and _as_utc(source.expires_at) <= now:
        source.status = "expired"
        _mark_rights_recheck(db, source.source_id, actor_subject="system:source-expiry")
        db.commit()
        raise HouseBatchError("A HouseSource jogi engedélye lejárt.")
    if source.content_sha256 != version.content_sha256:
        raise HouseBatchError("stale_source_rights")
    return {
        "id": source.source_id,
        "house_id": plan.house_id,
        "catalog_version_id": version.catalog_version_id,
        "revision": source.source_revision,
        "sha256": source.content_sha256,
        "catalog_price_huf": str(version.catalog_price_huf),
        "rights_evidence_ref": source.evidence_ref,
        "rights_evidence_sha256": source.evidence_sha256,
    }


def create_source_revision(
    db: Session,
    *,
    catalog_version_id: str,
    legal_basis: str,
    licence_scope: str,
    evidence_ref: str,
    evidence_sha256: str,
    actor_subject: str,
    expires_at: datetime | None = None,
) -> HousePlanSource:
    if legal_basis not in {
        "owned",
        "licensed",
        "public_domain",
        "customer_authorized",
        "unknown",
    }:
        raise ValueError("Érvénytelen jogalap.")
    if len(evidence_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in evidence_sha256
    ):
        raise ValueError("Az evidence SHA-256 formátuma érvénytelen.")
    version = db.scalar(
        select(HouseCatalogVersion)
        .where(HouseCatalogVersion.catalog_version_id == catalog_version_id)
        .with_for_update()
    )
    if version is None or not version.content_sha256:
        raise ValueError("A katalógusverzió nem található vagy nincs tartalomhash-e.")
    revisions = db.scalars(
        select(HousePlanSource.source_revision).where(
            HousePlanSource.catalog_version_id == catalog_version_id
        )
    ).all()
    revision = max(revisions, default=0) + 1
    row = HousePlanSource(
        source_id=f"HPS-{catalog_version_id}-R{revision}",
        catalog_version_id=catalog_version_id,
        source_revision=revision,
        content_sha256=version.content_sha256,
        legal_basis=legal_basis,
        licence_scope=licence_scope.strip(),
        evidence_ref=evidence_ref.strip(),
        evidence_sha256=evidence_sha256,
        rights_snapshot_json="{}",
        status="rights_review",
        expires_at=expires_at,
        created_by_subject=actor_subject,
    )
    if not row.licence_scope or not row.evidence_ref:
        raise ValueError("A licencterjedelem és a bizonyítékhivatkozás kötelező.")
    db.add(row)
    audit(
        db,
        actor=actor_subject,
        action="houseplan_source_revision_created",
        entity_type="HousePlanSource",
        entity_id=row.source_id,
        after={"legal_basis": row.legal_basis, "status": row.status},
    )
    db.commit()
    return row


def approve_source(db: Session, source_id: str, actor_subject: str) -> HousePlanSource:
    row = db.scalar(
        select(HousePlanSource).where(HousePlanSource.source_id == source_id).with_for_update()
    )
    if row is None:
        raise KeyError(source_id)
    if row.status != "rights_review":
        raise ValueError("Csak jogi ellenőrzés alatt álló forrás hagyható jóvá.")
    if row.created_by_subject == actor_subject:
        raise PermissionError("A forrás létrehozója nem hagyhatja jóvá saját revízióját.")
    if row.legal_basis == "unknown":
        raise ValueError("Ismeretlen jogalapú forrás nem hagyható jóvá.")
    if row.expires_at is not None and _as_utc(row.expires_at) <= utcnow():
        row.status = "expired"
        db.commit()
        raise ValueError("Lejárt forrás nem hagyható jóvá.")
    row.status = "approved"
    row.approved_by_subject = actor_subject
    row.approved_at = utcnow()
    audit(
        db,
        actor=actor_subject,
        action="houseplan_source_approved",
        entity_type="HousePlanSource",
        entity_id=row.source_id,
        before={"status": "rights_review"},
        after={"status": "approved"},
    )
    db.commit()
    return row


def revoke_source(db: Session, source_id: str, actor_subject: str, reason: str) -> HousePlanSource:
    row = db.scalar(
        select(HousePlanSource).where(HousePlanSource.source_id == source_id).with_for_update()
    )
    if row is None:
        raise KeyError(source_id)
    if row.status not in {"approved", "expired"}:
        raise ValueError("A forrás ebben az állapotban nem vonható vissza.")
    if not reason.strip():
        raise ValueError("A visszavonás indoka kötelező.")
    row.status = "revoked"
    row.revoked_by_subject = actor_subject
    row.revoked_at = utcnow()
    row.revocation_reason = reason.strip()
    _mark_rights_recheck(db, source_id, actor_subject=actor_subject)
    audit(
        db,
        actor=actor_subject,
        action="houseplan_source_revoked",
        entity_type="HousePlanSource",
        entity_id=row.source_id,
        before={"status": "approved"},
        after={"status": "revoked", "reason": row.revocation_reason},
    )
    db.commit()
    return row


def _mark_rights_recheck(db: Session, source_id: str, *, actor_subject: str) -> int:
    affected = db.scalars(
        select(HousePlanRecord).where(
            HousePlanRecord.source_id == source_id,
            HousePlanRecord.status.not_in(("rejected", "archived", "rights_recheck")),
        )
    ).all()
    for plan in affected:
        previous_status = plan.status
        previous_version = plan.row_version
        plan.status = "rights_recheck"
        plan.row_version += 1
        audit(
            db,
            actor=actor_subject,
            action="houseplan_rights_recheck_required",
            entity_type="HousePlanRecord",
            entity_id=plan.plan_id,
            before={"row_version": previous_version, "status": previous_status},
            after={
                "row_version": plan.row_version,
                "source_id": source_id,
                "status": "rights_recheck",
            },
        )
    return len(affected)


def block_source(db: Session, source_id: str, actor_subject: str, reason: str) -> HousePlanSource:
    row = db.scalar(
        select(HousePlanSource).where(HousePlanSource.source_id == source_id).with_for_update()
    )
    if row is None:
        raise KeyError(source_id)
    if row.status not in {"rights_review", "approved"}:
        raise ValueError("A forrás ebben az állapotban nem blokkolható.")
    if not reason.strip():
        raise ValueError("A blokkolás indoka kötelező.")
    previous = row.status
    row.status = "blocked"
    row.revoked_by_subject = actor_subject
    row.revoked_at = utcnow()
    row.revocation_reason = reason.strip()
    _mark_rights_recheck(db, source_id, actor_subject=actor_subject)
    audit(
        db,
        actor=actor_subject,
        action="houseplan_source_blocked",
        entity_type="HousePlanSource",
        entity_id=row.source_id,
        before={"status": previous},
        after={"status": "blocked", "reason": reason.strip()},
    )
    db.commit()
    return row


def _assert_source_approvable(
    db: Session, source_id: str, *, actor_subject: str
) -> HousePlanSource:
    row = db.scalar(
        select(HousePlanSource).where(HousePlanSource.source_id == source_id).with_for_update()
    )
    if row is None:
        raise ValueError("A terv HouseSource rekordja nem található.")
    if row.status != "approved":
        raise ValueError(f"A terv forrásjogi állapota nem jóváhagyható: {row.status}.")
    if row.expires_at is not None and _as_utc(row.expires_at) <= utcnow():
        row.status = "expired"
        _mark_rights_recheck(db, source_id, actor_subject=actor_subject)
        db.commit()
        raise ValueError("A terv forrásjogi engedélye lejárt.")
    version = db.scalar(
        select(HouseCatalogVersion).where(
            HouseCatalogVersion.catalog_version_id == row.catalog_version_id
        )
    )
    if version is None or version.content_sha256 != row.content_sha256:
        _mark_rights_recheck(db, source_id, actor_subject=actor_subject)
        db.commit()
        raise ValueError("A terv forrásjogi hash-e már nem egyezik a katalógussal.")
    return row


def _counter_similarity(left: Counter[str], right: Counter[str]) -> Decimal:
    keys = set(left) | set(right)
    maximum = sum(max(left[key], right[key]) for key in keys)
    if maximum == 0:
        return Decimal("1")
    return Decimal(sum(min(left[key], right[key]) for key in keys)) / Decimal(maximum)


def _area_vector(normalized: dict[str, Any]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for room in normalized["rooms"]:
        totals[room["type"]] = totals.get(room["type"], Decimal(0)) + Decimal(room["targetCells"])
    total = sum(totals.values(), Decimal(0))
    return {key: value / total for key, value in totals.items()}


def _adjacency_edges(normalized: dict[str, Any], geometry: dict[str, Any]) -> set[str]:
    room_types = {room["id"]: room["type"] for room in normalized["rooms"]}
    edges: set[str] = set()
    for level in geometry["levels"]:
        for connection in level.get("connections", []):
            left = room_types.get(connection["roomA"], "outside")
            right = room_types.get(connection["roomB"], "outside")
            edges.add("|".join(sorted((left, right))))
    return edges


def weighted_similarity(
    *,
    storey: Decimal,
    ratio: Decimal,
    counts: Decimal,
    areas: Decimal,
    adjacency: Decimal,
) -> Decimal:
    components = (storey, ratio, counts, areas, adjacency)
    if any(value < 0 or value > 1 for value in components):
        raise ValueError("A hasonlósági részpontszámoknak 0 és 1 közé kell esniük.")
    return (
        Decimal("0.10") * storey
        + Decimal("0.15") * ratio
        + Decimal("0.25") * counts
        + Decimal("0.25") * areas
        + Decimal("0.25") * adjacency
    ).quantize(Decimal("0.00001"))


def houseplan_similarity(
    left_normalized: dict[str, Any],
    left_geometry: dict[str, Any],
    right_normalized: dict[str, Any],
    right_geometry: dict[str, Any],
) -> Decimal:
    return _feature_similarity(
        _similarity_features(left_normalized, left_geometry),
        _similarity_features(right_normalized, right_geometry),
    )


def _similarity_features(normalized: dict[str, Any], geometry: dict[str, Any]) -> dict[str, Any]:
    boundary = geometry["levels"][0]["boundary"]
    width = Decimal(abs(boundary[1][0] - boundary[0][0]))
    depth = Decimal(abs(boundary[2][1] - boundary[1][1]))
    return {
        "floors": int(normalized["floors"]),
        "ratio": max(width, depth) / min(width, depth),
        "counts": Counter(room["type"] for room in normalized["rooms"]),
        "areas": _area_vector(normalized),
        "adjacency": _adjacency_edges(normalized, geometry),
    }


def _feature_similarity(left: dict[str, Any], right: dict[str, Any]) -> Decimal:
    storey = Decimal(left["floors"] == right["floors"])
    ratio = min(left["ratio"], right["ratio"]) / max(left["ratio"], right["ratio"])
    counts = _counter_similarity(left["counts"], right["counts"])
    left_areas, right_areas = left["areas"], right["areas"]
    area_keys = set(left_areas) | set(right_areas)
    areas = Decimal("1") - sum(
        abs(left_areas.get(key, Decimal(0)) - right_areas.get(key, Decimal(0))) for key in area_keys
    ) / Decimal(2)
    left_edges, right_edges = left["adjacency"], right["adjacency"]
    adjacency = (
        Decimal(len(left_edges & right_edges)) / Decimal(len(left_edges | right_edges))
        if left_edges or right_edges
        else Decimal("1")
    )
    return weighted_similarity(
        storey=storey,
        ratio=ratio,
        counts=counts,
        areas=areas,
        adjacency=adjacency,
    )


def _counter_similarity_float(left: Counter[str], right: Counter[str]) -> float:
    keys = left.keys() | right.keys()
    maximum = sum(max(left[key], right[key]) for key in keys)
    if maximum == 0:
        return 1.0
    return sum(min(left[key], right[key]) for key in keys) / maximum


def _feature_similarity_float(left: dict[str, Any], right: dict[str, Any]) -> float:
    ratio = float(min(left["ratio"], right["ratio"]) / max(left["ratio"], right["ratio"]))
    counts = _counter_similarity_float(left["counts"], right["counts"])
    left_areas, right_areas = left["areas"], right["areas"]
    area_keys = left_areas.keys() | right_areas.keys()
    areas = (
        1.0
        - sum(
            abs(float(left_areas.get(key, 0)) - float(right_areas.get(key, 0))) for key in area_keys
        )
        / 2.0
    )
    left_edges, right_edges = left["adjacency"], right["adjacency"]
    adjacency = (
        len(left_edges & right_edges) / len(left_edges | right_edges)
        if left_edges or right_edges
        else 1.0
    )
    return (
        0.10 * float(left["floors"] == right["floors"])
        + 0.15 * ratio
        + 0.25 * counts
        + 0.25 * areas
        + 0.25 * adjacency
    )


@dataclass
class _SimilarityIndex:
    rows: list[tuple[HousePlanRecord, dict[str, Any]]] = field(default_factory=list)
    edge_bits: dict[str, int] = field(default_factory=dict)
    room_count_bits: dict[int, int] = field(default_factory=dict)
    empty_edge_bits: int = 0

    def add(self, plan: HousePlanRecord, features: dict[str, Any]) -> None:
        bit = 1 << len(self.rows)
        self.rows.append((plan, features))
        room_count = sum(features["counts"].values())
        self.room_count_bits[room_count] = self.room_count_bits.get(room_count, 0) | bit
        edges = features["adjacency"]
        if not edges:
            self.empty_edge_bits |= bit
            return
        for edge in edges:
            self.edge_bits[edge] = self.edge_bits.get(edge, 0) | bit

    def eligible(self, features: dict[str, Any]) -> list[tuple[HousePlanRecord, dict[str, Any]]]:
        edges = sorted(features["adjacency"])
        if not edges:
            bits = self.empty_edge_bits
        else:
            # Jaccard >= 0.60 requires sharing at least 60% of the query's
            # edges. Bitset intersections retrieve that superset without a
            # 10 000-row Python scan and without approximation.
            minimum_shared = ceil(0.60 * len(edges))
            postings = [self.edge_bits.get(edge, 0) for edge in edges]
            bits = 0
            for posting_group in combinations(postings, minimum_shared):
                overlap = posting_group[0]
                for posting in posting_group[1:]:
                    overlap &= posting
                bits |= overlap

        requested_rooms = sum(features["counts"].values())
        minimum_rooms = ceil(0.60 * requested_rooms)
        maximum_rooms = int(requested_rooms / 0.60)
        room_bits = 0
        for room_count in range(minimum_rooms, maximum_rooms + 1):
            room_bits |= self.room_count_bits.get(room_count, 0)
        bits &= room_bits

        result: list[tuple[HousePlanRecord, dict[str, Any]]] = []
        while bits:
            least_bit = bits & -bits
            index = least_bit.bit_length() - 1
            result.append(self.rows[index])
            bits ^= least_bit
        return result


def _similarity_candidates(db: Session) -> _SimilarityIndex:
    index = _SimilarityIndex()
    for candidate in db.scalars(
        select(HousePlanRecord).where(HousePlanRecord.status != "archived")
    ).all():
        index.add(
            candidate,
            _similarity_features(
                json.loads(candidate.normalized_input_json),
                json.loads(candidate.geometry_json),
            ),
        )
    return index


def _nearest_plan(
    db: Session,
    generated: dict[str, Any],
    *,
    candidates: _SimilarityIndex | None = None,
) -> tuple[HousePlanRecord | None, Decimal]:
    best: HousePlanRecord | None = None
    best_features: dict[str, Any] | None = None
    best_fast_score = 0.0
    generated_features = _similarity_features(generated["normalizedInput"], generated["geometry"])
    candidate_index = candidates if candidates is not None else _similarity_candidates(db)
    for candidate, candidate_features in candidate_index.eligible(generated_features):
        # With all other components at 1.00, the frozen 0.90 warning threshold
        # still requires footprint-ratio similarity >= 1/3 and room-count
        # similarity >= 0.60. These precomputed guards therefore introduce no
        # false negatives at either governed threshold.
        ratio = float(
            min(generated_features["ratio"], candidate_features["ratio"])
            / max(generated_features["ratio"], candidate_features["ratio"])
        )
        if ratio < (1.0 / 3.0) - 1e-12:
            continue
        if (
            _counter_similarity_float(generated_features["counts"], candidate_features["counts"])
            < 0.60 - 1e-12
        ):
            continue
        fast_score = _feature_similarity_float(generated_features, candidate_features)
        if fast_score > best_fast_score:
            best, best_features, best_fast_score = candidate, candidate_features, fast_score
    if best is None or best_features is None:
        return None, Decimal("0")
    # The governed decision is still made by the frozen Decimal implementation;
    # float arithmetic is used only to find the maximum candidate efficiently.
    return best, _feature_similarity(generated_features, best_features)


def annotate_dry_run_duplicates(db: Session, preview: dict[str, Any]) -> dict[str, Any]:
    candidates = _similarity_candidates(db)
    for item in preview["results"]:
        if item["status"] != "ready":
            continue
        exact = db.scalar(
            select(HousePlanRecord).where(
                (HousePlanRecord.geometry_signature == item["geometrySignature"])
                | (HousePlanRecord.input_hash == item["inputHash"])
            )
        )
        if exact:
            item["status"] = "duplicate"
            item["duplicatePlanId"] = exact.plan_id
            item["message"] = "A terv már szerepel a kanonikus HousePlan tárban."
            continue
        nearest, score = _nearest_plan(
            db,
            {
                "normalizedInput": item["normalizedInput"],
                "geometry": item["geometry"],
            },
            candidates=candidates,
        )
        if nearest and score >= NEAR_DUPLICATE_BLOCK:
            item["status"] = "blocked"
            item["duplicatePlanId"] = nearest.plan_id
            item["similarityScore"] = str(score)
            item["errorCode"] = "near_duplicate_blocked"
            item["message"] = "A terv eléri a közelduplikációs blokkolási küszöböt."
        elif nearest and score >= NEAR_DUPLICATE_WARNING:
            item["nearDuplicatePlanId"] = nearest.plan_id
            item["similarityScore"] = str(score)
            item["warning"] = "Közelduplikáció: kötelező reviewer ellenőrzés."
    preview["counts"] = {
        status: sum(item["status"] == status for item in preview["results"])
        for status in ("ready", "invalid", "duplicate", "blocked")
    }
    if preview["counts"]["invalid"] or preview["counts"]["blocked"]:
        preview["status"] = "has_errors"
    return preview


def _housebuild_records(
    *,
    generated: dict[str, Any],
    source: dict[str, Any],
    project_id: str,
    title: str,
    actor_subject: str,
    warning_score: Decimal | None,
) -> tuple[HouseBuildCase, HouseBuildVariant, list[HouseBuildGate], list[HouseBuildValidation]]:
    normalized, geometry = generated["normalizedInput"], generated["geometry"]
    case_id, variant_id = _id("HBC"), _id("HBV")
    boundary = geometry["levels"][0]["boundary"]
    width_m = Decimal(abs(boundary[1][0] - boundary[0][0])) / Decimal(1000)
    depth_m = Decimal(abs(boundary[2][1] - boundary[1][1])) / Decimal(1000)
    net_area = sum(
        Decimal(room["actualAreaMm2"]) for level in geometry["levels"] for room in level["rooms"]
    ) / Decimal(1_000_000)
    requirement_json = _json(normalized)
    geometry_json = _json(geometry)
    source_snapshot = _json(source)
    case = HouseBuildCase(
        case_id=case_id,
        project_id=project_id,
        title=title,
        source_house_id=source["house_id"],
        source_catalog_version_id=source["catalog_version_id"],
        source_snapshot_json=source_snapshot,
        source_sha256=source["sha256"],
        rights_evidence_ref=source["rights_evidence_ref"],
        rights_evidence_sha256=source["rights_evidence_sha256"],
        requirement_json=requirement_json,
        requirement_sha256=_sha(requirement_json),
        status="review",
        current_revision=1,
        selected_variant_id=variant_id,
        created_by=actor_subject,
    )
    variant = HouseBuildVariant(
        variant_id=variant_id,
        case_id=case_id,
        variant_no=1,
        label=title,
        strategy="HousePlan hb-grid-v1 determinisztikus generálás",
        gross_area_m2=Decimal(normalized["grossAreaM2"]),
        net_area_m2=net_area,
        footprint_m2=width_m * depth_m,
        width_m=width_m,
        depth_m=depth_m,
        floors=int(normalized["floors"]),
        bedrooms=sum(room["type"] == "bedroom" for room in normalized["rooms"]),
        bathrooms=sum(room["type"] == "bathroom" for room in normalized["rooms"]),
        garage_spaces=0,
        roof_style=normalized["roof"],
        facade_style=normalized["style"],
        orientation="unassigned",
        accessibility=bool(normalized["accessibility"]),
        estimated_catalog_price_huf=Decimal(source["catalog_price_huf"]),
        rooms_json=_json(normalized["rooms"]),
        adjacency_json=_json(
            [connection for level in geometry["levels"] for connection in level["connections"]]
        ),
        geometry_json=geometry_json,
        geometry_signature=generated["geometrySignature"],
        content_sha256=_sha({"geometry": geometry, "normalizedInput": normalized}),
        status="selected",
    )
    gate_decisions = {
        "source_rights": "approved",
        "program": "approved",
        "deduplication": "approved" if warning_score is None else "pending",
        "topology": "approved",
        "plotcheck": "pending",
        "buildconfig": "pending",
        "plancheck": "pending",
        "technical": "pending",
    }
    gates = [
        HouseBuildGate(
            case_id=case_id,
            gate_key=key,
            decision=decision,
            evidence_refs_json=_json([generated["geometrySignature"]]),
            evidence_sha256=generated["geometrySignature"],
            note=(
                f"Közelduplikációs reviewer warning: {warning_score}"
                if key == "deduplication" and warning_score is not None
                else None
            ),
            decided_by=actor_subject if decision == "approved" else None,
            decided_at=utcnow() if decision == "approved" else None,
        )
        for key, decision in gate_decisions.items()
    ]
    validations = [
        HouseBuildValidation(
            validation_id=_id("HBVAL"),
            variant_id=variant_id,
            validation_key=key,
            decision="pass",
            measured_json=_json(value),
            note="HousePlan generátor determinisztikus validáció.",
            evidence_sha256=generated["geometrySignature"],
            checked_by="system:houseplan",
        )
        for key, value in (
            ("geometry_signature", {"sha256": generated["geometrySignature"]}),
            ("room_program", {"rooms": len(normalized["rooms"])}),
            ("connected_topology", {"levels": normalized["floors"]}),
        )
    ]
    return case, variant, gates, validations


def _serialize_batch(db: Session, batch: HousePlanBatch, *, replayed: bool) -> dict[str, Any]:
    items = db.scalars(
        select(HousePlanBatchItem)
        .where(HousePlanBatchItem.batch_id == batch.batch_id)
        .order_by(HousePlanBatchItem.row_number)
    ).all()
    return {
        "batchId": batch.batch_id,
        "status": batch.status,
        "replayed": replayed,
        "counts": {
            "total": batch.total_count,
            "created": batch.created_count,
            "invalid": batch.invalid_count,
            "duplicate": batch.duplicate_count,
            "blocked": batch.blocked_count,
        },
        "results": [
            {
                "rowNumber": item.row_number,
                "status": item.status,
                "planId": item.plan_id,
                "duplicatePlanId": item.duplicate_plan_id,
                "similarityScore": str(item.similarity_score) if item.similarity_score else None,
                "errorCode": item.error_code,
                "message": item.message,
            }
            for item in items
        ],
    }


def _lock_executable_source(db: Session, source: dict[str, Any]) -> HousePlanSource:
    snapshot = db.scalar(
        select(HousePlanSource).where(HousePlanSource.source_id == str(source.get("id") or ""))
    )
    if snapshot is None:
        raise HouseBatchError("source_not_executable:missing")
    version = db.scalar(
        select(HouseCatalogVersion)
        .where(HouseCatalogVersion.catalog_version_id == snapshot.catalog_version_id)
        .with_for_update()
    )
    if version is None:
        raise HouseBatchError("source_not_executable:catalog_missing")
    row = db.scalar(
        select(HousePlanSource)
        .where(HousePlanSource.catalog_version_id == snapshot.catalog_version_id)
        .order_by(HousePlanSource.source_revision.desc())
        .with_for_update()
    )
    if row is None or row.source_id != snapshot.source_id:
        raise HouseBatchError("source_not_executable:not_latest_revision")
    if row.status != "approved":
        raise HouseBatchError(f"source_not_executable:{row.status}")
    if row.expires_at is not None and _as_utc(row.expires_at) <= utcnow():
        raise HouseBatchError("source_not_executable:expired")
    if row.source_revision != int(source.get("revision") or 0) or row.content_sha256 != str(
        source.get("sha256") or ""
    ):
        raise HouseBatchError("source_not_executable:stale_snapshot")
    if version.content_sha256 != row.content_sha256:
        raise HouseBatchError("source_not_executable:catalog_hash_changed")
    return row


def _lock_family_version(db: Session, family_id: str) -> None:
    """Serialize version allocation even when a family has no row to lock yet."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:family_id, 0))"),
            {"family_id": family_id},
        )


def _execute_batch(
    db: Session,
    *,
    rows: list[dict[str, Any]],
    source: dict[str, Any],
    actor_subject: str,
    permission_revision: str,
    pricing_revision: str,
    dry_run_token: str,
    idempotency_key: str,
    secret: str,
    authorized_project_ids: set[str],
) -> dict[str, Any]:
    if not actor_subject.startswith("ITEP-"):
        raise PermissionError("Kanonikus ITEP subject nélkül végrehajtás nem engedélyezett.")
    if not 8 <= len(idempotency_key) <= 160:
        raise HouseBatchError("Az idempotency key 8–160 karakter legyen.")
    claims = validate_dry_run_token(
        dry_run_token,
        rows=rows,
        secret=secret,
        actor_subject=actor_subject,
        source=source,
        permission_revision=permission_revision,
        pricing_revision=pricing_revision,
    )
    if not claims.get("executionAllowed"):
        raise PermissionError("A dry-run csak előnézeti végrehajtásra jogosít.")
    request_sha = _sha(
        {
            "actorSubject": actor_subject,
            "batchHash": claims["batchHash"],
            "idempotencyKey": idempotency_key,
            "pricingRevision": pricing_revision,
            "rows": rows,
            "source": source,
        }
    )
    existing_batch = db.scalar(
        select(HousePlanBatch).where(HousePlanBatch.idempotency_key == idempotency_key)
    )
    if existing_batch:
        if existing_batch.request_sha256 != request_sha:
            raise HouseBatchError("idempotency_conflict")
        if existing_batch.status == "running":
            raise HouseBatchError("idempotency_in_progress")
        return _serialize_batch(db, existing_batch, replayed=True)
    _lock_executable_source(db, source)
    batch = HousePlanBatch(
        batch_id=_id("HPB"),
        source_id=source["id"],
        source_revision=source["revision"],
        source_sha256=source["sha256"],
        actor_subject=actor_subject,
        permission_revision=permission_revision,
        pricing_revision=pricing_revision,
        ruleset_version=RULESET_VERSION,
        batch_hash=claims["batchHash"],
        request_sha256=request_sha,
        request_json=_json(rows),
        idempotency_key=idempotency_key,
        dry_run_token_sha256=_sha(dry_run_token),
        status="running",
        total_count=len(rows),
    )
    db.add(batch)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalar(
            select(HousePlanBatch).where(HousePlanBatch.idempotency_key == idempotency_key)
        )
        if concurrent is None or concurrent.request_sha256 != request_sha:
            raise HouseBatchError("idempotency_conflict") from None
        if concurrent.status == "running":
            raise HouseBatchError("idempotency_in_progress") from None
        return _serialize_batch(db, concurrent, replayed=True)

    similarity_candidates = _similarity_candidates(db)
    for row_number, row in enumerate(rows, start=1):
        input_sha = _sha(row)
        try:
            _lock_executable_source(db, source)
            generated = generate_houseplan(row, source)
            requested_family = str(row.get("family_id") or "").strip()
            if requested_family and len(requested_family) > 140:
                raise ValueError("A HousePlan family_id legfeljebb 140 karakter lehet.")
            family_id = requested_family or f"HPF-{_sha(row)[:32].upper()}"
            exact = db.scalar(
                select(HousePlanRecord).where(
                    (HousePlanRecord.geometry_signature == generated["geometrySignature"])
                    | (HousePlanRecord.input_hash == generated["inputHash"])
                )
            )
            if exact:
                db.add(
                    HousePlanBatchItem(
                        item_id=f"{batch.batch_id}-R{row_number:03d}",
                        batch_id=batch.batch_id,
                        row_number=row_number,
                        status="duplicate",
                        input_hash=generated["inputHash"],
                        geometry_signature=generated["geometrySignature"],
                        duplicate_plan_id=exact.plan_id,
                        input_sha256=input_sha,
                    )
                )
                db.commit()
                batch.duplicate_count += 1
                continue
            nearest, score = _nearest_plan(db, generated, candidates=similarity_candidates)
            same_family_revision = bool(nearest and nearest.family_id == family_id)
            if nearest and score >= NEAR_DUPLICATE_BLOCK and not same_family_revision:
                db.add(
                    HousePlanBatchItem(
                        item_id=f"{batch.batch_id}-R{row_number:03d}",
                        batch_id=batch.batch_id,
                        row_number=row_number,
                        status="near_duplicate_blocked",
                        input_hash=generated["inputHash"],
                        geometry_signature=generated["geometrySignature"],
                        duplicate_plan_id=nearest.plan_id,
                        similarity_score=score,
                        error_code="near_duplicate_blocked",
                        message="A terv hasonlósága eléri a 0,97 blokkolási küszöböt.",
                        input_sha256=input_sha,
                    )
                )
                db.commit()
                batch.blocked_count += 1
                continue
            warning_score = (
                score
                if nearest and (score >= NEAR_DUPLICATE_WARNING or same_family_revision)
                else None
            )
            project_id = str(row.get("project_id") or CATALOG_GOVERNANCE_PROJECT).strip()
            if project_id not in authorized_project_ids:
                raise PermissionError("A terv projektje kívül esik az engedélyezett scope-on.")
            title = str(
                row.get("name")
                or (
                    f"{generated['normalizedInput']['brand']} "
                    f"{generated['normalizedInput']['grossAreaM2']} m²"
                )
            ).strip()[:255]
            _lock_family_version(db, family_id)
            predecessor = db.scalar(
                select(HousePlanRecord)
                .where(HousePlanRecord.family_id == family_id)
                .order_by(HousePlanRecord.version_number.desc())
                .with_for_update()
            )
            if predecessor and predecessor.project_id != project_id:
                raise ValueError("A HousePlan csalĂˇd nem vihetĹ‘ Ăˇt mĂˇsik projektbe.")
            version_number = predecessor.version_number + 1 if predecessor else 1
            plan_id, task_id = _id("HPLAN"), _id("TASK-HPLAN")
            case, variant, gates, validations = _housebuild_records(
                generated=generated,
                source=source,
                project_id=project_id,
                title=title,
                actor_subject=actor_subject,
                warning_score=warning_score,
            )
            plan = HousePlanRecord(
                plan_id=plan_id,
                batch_id=batch.batch_id,
                row_number=row_number,
                project_id=project_id,
                title=title,
                family_id=family_id,
                version_number=version_number,
                predecessor_plan_id=predecessor.plan_id if predecessor else None,
                source_id=source["id"],
                input_hash=generated["inputHash"],
                geometry_signature=generated["geometrySignature"],
                normalized_input_json=_json(generated["normalizedInput"]),
                geometry_json=_json(generated["geometry"]),
                status="plancheck_review",
                near_duplicate_score=warning_score,
                near_duplicate_plan_id=nearest.plan_id if warning_score and nearest else None,
                housebuild_case_id=case.case_id,
                housebuild_variant_id=variant.variant_id,
                plancheck_task_id=task_id,
                created_by_subject=actor_subject,
            )
            task = TaskRecord(
                task_id=task_id,
                project_id=project_id,
                source_event_id=plan_id,
                title=f"HousePlan tervellenőrzés: {title}",
                description=(
                    f"PlanID: {plan_id}; Geometry: {generated['geometrySignature']}"
                    + (f"; közelduplikáció: {warning_score}" if warning_score else "")
                ),
                assignee="technical-prep",
                priority="high" if warning_score else "normal",
                status="open",
                executive_relevance=False,
            )
            db.add_all([case, variant, plan, task, *gates, *validations])
            db.add(
                HousePlanBatchItem(
                    item_id=f"{batch.batch_id}-R{row_number:03d}",
                    batch_id=batch.batch_id,
                    row_number=row_number,
                    status="created",
                    input_hash=generated["inputHash"],
                    geometry_signature=generated["geometrySignature"],
                    plan_id=plan_id,
                    similarity_score=warning_score,
                    input_sha256=input_sha,
                )
            )
            audit(
                db,
                actor=actor_subject,
                action="houseplan_created",
                entity_type="HousePlanRecord",
                entity_id=plan_id,
                after={
                    "batch_id": batch.batch_id,
                    "geometry_signature": generated["geometrySignature"],
                    "family_id": family_id,
                    "predecessor_plan_id": predecessor.plan_id if predecessor else None,
                    "project_id": project_id,
                    "row_version": 1,
                    "source_id": source["id"],
                    "status": "plancheck_review",
                    "version_number": version_number,
                },
            )
            db.commit()
            similarity_candidates.add(
                plan,
                _similarity_features(generated["normalizedInput"], generated["geometry"]),
            )
            batch.created_count += 1
        except HouseBatchError as exc:
            db.rollback()
            for blocked_row_number, blocked_row in enumerate(
                rows[row_number - 1 :], start=row_number
            ):
                db.add(
                    HousePlanBatchItem(
                        item_id=f"{batch.batch_id}-R{blocked_row_number:03d}",
                        batch_id=batch.batch_id,
                        row_number=blocked_row_number,
                        status="invalid",
                        error_code="source_not_executable",
                        message=str(exc),
                        input_sha256=_sha(blocked_row),
                    )
                )
            db.commit()
            break
        except (HouseGeometryError, KeyError, TypeError, ValueError) as exc:
            db.rollback()
            db.add(
                HousePlanBatchItem(
                    item_id=f"{batch.batch_id}-R{row_number:03d}",
                    batch_id=batch.batch_id,
                    row_number=row_number,
                    status="invalid",
                    error_code="geometry_validation_failed",
                    message=str(exc),
                    input_sha256=input_sha,
                )
            )
            db.commit()
            batch.invalid_count += 1
        except IntegrityError:
            db.rollback()
            exact = db.scalar(
                select(HousePlanRecord).where(
                    HousePlanRecord.geometry_signature == generated["geometrySignature"]
                )
            )
            if exact is None:
                raise
            db.add(
                HousePlanBatchItem(
                    item_id=f"{batch.batch_id}-R{row_number:03d}",
                    batch_id=batch.batch_id,
                    row_number=row_number,
                    status="duplicate",
                    input_hash=generated["inputHash"],
                    geometry_signature=generated["geometrySignature"],
                    duplicate_plan_id=exact.plan_id,
                    input_sha256=input_sha,
                )
            )
            db.commit()
            batch.duplicate_count += 1
        finally:
            updated_batch = db.scalar(
                select(HousePlanBatch).where(HousePlanBatch.batch_id == batch.batch_id)
            )
            if updated_batch is None:
                raise RuntimeError("A HousePlan batch rekord eltűnt.")
            batch = updated_batch
    item_statuses = db.scalars(
        select(HousePlanBatchItem.status).where(HousePlanBatchItem.batch_id == batch.batch_id)
    ).all()
    batch.created_count = sum(status == "created" for status in item_statuses)
    batch.invalid_count = sum(status == "invalid" for status in item_statuses)
    batch.duplicate_count = sum(status == "duplicate" for status in item_statuses)
    batch.blocked_count = sum(status == "near_duplicate_blocked" for status in item_statuses)
    failures = batch.invalid_count + batch.blocked_count
    batch.status = (
        "completed"
        if failures == 0
        else "failed"
        if batch.created_count == 0 and batch.duplicate_count == 0
        else "partial"
    )
    batch.completed_at = utcnow()
    audit(
        db,
        actor=actor_subject,
        action="houseplan_batch_executed",
        entity_type="HousePlanBatch",
        entity_id=batch.batch_id,
        after={
            "status": batch.status,
            "created": batch.created_count,
            "invalid": batch.invalid_count,
            "duplicate": batch.duplicate_count,
            "blocked": batch.blocked_count,
        },
    )
    db.commit()
    return _serialize_batch(db, batch, replayed=False)


def execute_batch(
    db: Session,
    *,
    rows: list[dict[str, Any]],
    source: dict[str, Any],
    actor_subject: str,
    permission_revision: str,
    pricing_revision: str,
    dry_run_token: str,
    idempotency_key: str,
    secret: str,
    authorized_project_ids: set[str],
) -> dict[str, Any]:
    try:
        return _execute_batch(
            db,
            rows=rows,
            source=source,
            actor_subject=actor_subject,
            permission_revision=permission_revision,
            pricing_revision=pricing_revision,
            dry_run_token=dry_run_token,
            idempotency_key=idempotency_key,
            secret=secret,
            authorized_project_ids=authorized_project_ids,
        )
    except HouseBatchError:
        # Validation/idempotency conflicts belong to the caller. In particular,
        # never mark another request's concurrently running batch as failed.
        raise
    except Exception:
        db.rollback()
        batch = db.scalar(
            select(HousePlanBatch).where(
                HousePlanBatch.idempotency_key == idempotency_key,
                HousePlanBatch.status == "running",
            )
        )
        if batch:
            item_count = db.scalar(
                select(func.count())
                .select_from(HousePlanBatchItem)
                .where(HousePlanBatchItem.batch_id == batch.batch_id)
            )
            batch.status = "partial" if item_count else "failed"
            batch.completed_at = utcnow()
            db.commit()
        raise


def review_plan(
    db: Session,
    *,
    plan_id: str,
    reviewer_subject: str,
    decision: str,
    expected_version: int,
    reason: str = "",
) -> HousePlanRecord:
    plan = db.scalar(
        select(HousePlanRecord).where(HousePlanRecord.plan_id == plan_id).with_for_update()
    )
    if plan is None:
        raise KeyError(plan_id)
    if plan.row_version != expected_version:
        raise RuntimeError(f"version_conflict:{plan.row_version}")
    if plan.status != "plancheck_review":
        raise ValueError("Csak PlanCheck ellenőrzés alatt álló terv bírálható el.")
    if plan.created_by_subject == reviewer_subject:
        raise PermissionError("A terv készítője nem hagyhatja jóvá saját tervét.")
    if decision not in {"approve", "reject"}:
        raise ValueError("A döntés approve vagy reject lehet.")
    if decision == "reject" and not reason.strip():
        raise ValueError("Elutasításhoz indoklás szükséges.")
    if decision == "approve":
        _assert_source_approvable(db, plan.source_id, actor_subject=reviewer_subject)
    plan.status = "approved" if decision == "approve" else "rejected"
    plan.reviewed_by_subject = reviewer_subject
    plan.row_version += 1
    task = db.scalar(select(TaskRecord).where(TaskRecord.task_id == plan.plancheck_task_id))
    if task:
        task.status = "completed"
        task.description = (
            task.description or ""
        ) + f"; döntés: {decision}; indok: {reason.strip()}"
    gate = db.scalar(
        select(HouseBuildGate).where(
            HouseBuildGate.case_id == plan.housebuild_case_id,
            HouseBuildGate.gate_key == "plancheck",
        )
    )
    if gate:
        gate.decision = "approved" if decision == "approve" else "rejected"
        gate.decided_by = reviewer_subject
        gate.decided_at = utcnow()
        gate.note = reason.strip() or "PlanCheck jóváhagyva."
    audit(
        db,
        actor=reviewer_subject,
        action="houseplan_reviewed",
        entity_type="HousePlanRecord",
        entity_id=plan.plan_id,
        before={"status": "plancheck_review", "row_version": expected_version},
        after={"status": plan.status, "row_version": plan.row_version, "reason": reason},
    )
    db.commit()
    return plan
