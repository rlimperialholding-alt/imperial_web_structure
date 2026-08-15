from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import HouseDesignRevision, HouseDesignSession, HousePlanRecord
from .house_designer_geometry import (
    GeometryError,
    adapt_houseplan_geometry,
    apply_command_with_findings,
    canonical_sha256_normalized,
    empty_geometry,
    validate_geometry,
)
from .house_designer_privacy import (
    PRIVATE_SITE_FIELDS,
    SitePrivacyError,
    has_private_site_values,
    protect_site,
    unprotect_site,
)


class HouseDesignerError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ActorScope:
    subject_id: str
    tenant_id: str
    brand_ids: frozenset[str]
    can_read_all_owned: bool = False
    project_ids: frozenset[str] = frozenset()
    denied_project_ids: frozenset[str] = frozenset()

    def can_read(self, owner_subject_id: str | None, project_id: str | None) -> bool:
        if owner_subject_id == self.subject_id:
            return True
        if project_id is not None and project_id in self.denied_project_ids:
            return False
        if self.can_read_all_owned:
            return True
        return project_id is not None and project_id in self.project_ids


def create_session(
    db: Session,
    *,
    actor: ActorScope,
    brand_id: str,
    title: str,
    command_id: str,
    origin: str = "blank",
    template_plan_id: str | None = None,
    width_mm: int = 10_000,
    depth_mm: int = 8_000,
    commit: bool = True,
) -> dict[str, Any]:
    _require_brand(actor, brand_id)
    if origin not in {"blank", "template"}:
        raise HouseDesignerError("origin_invalid", "Ismeretlen tervindítási mód.")
    if origin == "template" and not template_plan_id:
        raise HouseDesignerError(
            "template_required", "Típusház indításakor tervazonosító szükséges."
        )
    command_payload = {
        "brandId": brand_id,
        "title": title.strip(),
        "origin": origin,
        "templatePlanId": template_plan_id,
        "widthMm": width_mm,
        "depthMm": depth_mm,
    }
    command_hash = _sha(command_payload)
    existing = db.scalar(
        select(HouseDesignRevision).where(HouseDesignRevision.command_id == command_id).limit(1)
    )
    if existing:
        row = db.scalar(
            select(HouseDesignSession).where(
                HouseDesignSession.session_id == existing.session_id,
                HouseDesignSession.tenant_id == actor.tenant_id,
                HouseDesignSession.owner_subject_id == actor.subject_id,
            )
        )
        if (
            row
            and existing.command_type == "create_session"
            and existing.command_sha256 == command_hash
        ):
            return session_detail(db, row.session_id, actor)
        raise HouseDesignerError(
            "idempotency_collision",
            "A műveletazonosító más tartalommal vagy másik hozzáférési körben már létezik.",
            status_code=409,
        )
    if origin == "template":
        template = db.scalar(
            select(HousePlanRecord).where(
                HousePlanRecord.plan_id == template_plan_id,
                HousePlanRecord.status.in_(("approved", "catalog_ready", "published")),
            )
        )
        if template is None:
            raise HouseDesignerError(
                "template_not_available",
                "A kiválasztott típusterv nem érhető el vagy még nincs jóváhagyva.",
                status_code=404,
            )
        try:
            geometry = adapt_houseplan_geometry(json.loads(template.geometry_json))
        except (GeometryError, json.JSONDecodeError) as error:
            raise HouseDesignerError(
                "template_geometry_unsupported",
                "A kiválasztott típusterv geometriája ebben a szerkesztőben nem használható.",
                status_code=409,
            ) from error
    else:
        geometry = empty_geometry(width_mm, depth_mm)
    session_id = _id("HDS")
    revision_id = _id("HDR")
    row = HouseDesignSession(
        session_id=session_id,
        tenant_id=actor.tenant_id,
        brand_id=brand_id,
        owner_subject_id=actor.subject_id,
        origin=origin,
        template_plan_id=template_plan_id,
        status="DRAFT",
        current_revision_id=revision_id,
        title=title.strip() or "Saját házterv",
        row_version=1,
        created_by=actor.subject_id,
        updated_by=actor.subject_id,
    )
    revision = HouseDesignRevision(
        revision_id=revision_id,
        session_id=session_id,
        revision_no=1,
        command_id=command_id,
        command_type="create_session",
        command_sha256=command_hash,
        geometry_json=_json(geometry),
        configuration_json="{}",
        site_json="{}",
        canonical_sha256=_revision_hash(geometry, {}, {}),
        change_summary="Új házterv létrehozva.",
        created_by=actor.subject_id,
    )
    db.add_all([row, revision])
    audit(
        db,
        actor=actor.subject_id,
        action="house_designer.session.create",
        entity_type="HouseDesignSession",
        entity_id=session_id,
        after={
            "tenant_id": actor.tenant_id,
            "brand_id": brand_id,
            "origin": origin,
            "revision_id": revision_id,
        },
    )
    if commit:
        db.commit()
    else:
        db.flush()
    return session_detail(db, session_id, actor)


def apply_session_command(
    db: Session,
    *,
    session_id: str,
    actor: ActorScope,
    base_revision_id: str,
    base_canonical_sha256: str,
    command_id: str,
    command_type: str,
    payload: dict[str, Any],
    change_summary: str = "",
) -> dict[str, Any]:
    row = _locked_session(db, session_id, actor)
    command_hash = _sha(
        {
            "sessionId": session_id,
            "baseRevisionId": base_revision_id,
            "baseCanonicalSha256": base_canonical_sha256,
            "commandType": command_type,
            "payload": payload,
        }
    )
    replay = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.session_id == session_id,
            HouseDesignRevision.command_id == command_id,
        )
    )
    if replay:
        if replay.command_sha256 != command_hash:
            raise HouseDesignerError(
                "idempotency_collision",
                "A műveletazonosítóhoz eltérő tartalom tartozik.",
                status_code=409,
            )
        return session_detail(db, session_id, actor)
    current = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == row.current_revision_id
        )
    )
    if current is None:
        raise HouseDesignerError(
            "current_revision_missing",
            "A terv aktuális verziója nem elérhető.",
            status_code=409,
        )
    if current.revision_id != base_revision_id or current.canonical_sha256 != base_canonical_sha256:
        raise HouseDesignerError(
            "stale_revision",
            "A tervet időközben módosították. Töltse be az aktuális verziót.",
            status_code=409,
        )
    geometry = json.loads(current.geometry_json)
    configuration = json.loads(current.configuration_json)
    site = decode_revision_site(current)
    geometry_findings: list[dict[str, str]] | None = None
    try:
        if command_type == "restore_revision":
            target_revision_id = str(payload.get("targetRevisionId") or "").strip()
            target = db.scalar(
                select(HouseDesignRevision).where(
                    HouseDesignRevision.session_id == session_id,
                    HouseDesignRevision.revision_id == target_revision_id,
                )
            )
            if target is None:
                raise HouseDesignerError(
                    "restore_revision_not_found",
                    "A visszaállítandó tervverzió nem található.",
                    status_code=404,
                )
            if target.revision_id == current.revision_id:
                raise HouseDesignerError(
                    "restore_revision_current",
                    "Az aktuális tervverzió önmagára nem állítható vissza.",
                    status_code=409,
                )
            geometry = json.loads(target.geometry_json)
            configuration = json.loads(target.configuration_json)
            site = decode_revision_site(target)
        elif command_type == "set_configuration":
            configuration = _merge_configuration(configuration, payload)
        elif command_type == "set_site":
            site = _validated_site(payload)
        else:
            geometry, geometry_findings = apply_command_with_findings(
                geometry, command_type, payload
            )
    except GeometryError as error:
        raise HouseDesignerError(error.code, str(error)) from error
    next_revision_no = current.revision_no + 1
    revision_id = _id("HDR")
    revision = HouseDesignRevision(
        revision_id=revision_id,
        session_id=session_id,
        revision_no=next_revision_no,
        predecessor_revision_id=current.revision_id,
        command_id=command_id,
        command_type=command_type,
        command_sha256=command_hash,
        geometry_json=_json(geometry),
        configuration_json=_json(configuration),
        site_json=_json(protect_site(site, revision_id)),
        canonical_sha256=_revision_hash(geometry, configuration, site),
        change_summary=change_summary.strip() or _default_summary(command_type),
        created_by=actor.subject_id,
    )
    before = {
        "revision_id": current.revision_id,
        "canonical_sha256": current.canonical_sha256,
        "status": row.status,
    }
    row.current_revision_id = revision_id
    row.row_version += 1
    row.updated_by = actor.subject_id
    row.status = (
        "STALE"
        if row.status
        in {
            "CHECKED",
            "ESTIMATED",
            "CUSTOMER_APPROVED",
        }
        else "CHECK_REQUIRED"
    )
    db.add(revision)
    audit(
        db,
        actor=actor.subject_id,
        action="house_designer.revision.create",
        entity_type="HouseDesignSession",
        entity_id=session_id,
        before=before,
        after={
            "revision_id": revision_id,
            "canonical_sha256": revision.canonical_sha256,
            "status": row.status,
            "command_type": command_type,
        },
    )
    db.commit()
    if geometry_findings is None:
        geometry_findings = validate_geometry(geometry)
    history = db.scalars(
        select(HouseDesignRevision)
        .where(HouseDesignRevision.session_id == session_id)
        .order_by(desc(HouseDesignRevision.revision_no))
        .limit(50)
    ).all()
    return _session_payload(
        row,
        revision,
        geometry=geometry,
        configuration=configuration,
        site=site,
        geometry_findings=geometry_findings,
        history=history,
    )


def session_detail(db: Session, session_id: str, actor: ActorScope) -> dict[str, Any]:
    row = db.scalar(
        select(HouseDesignSession).where(
            HouseDesignSession.session_id == session_id,
            HouseDesignSession.tenant_id == actor.tenant_id,
        )
    )
    if row is None or not _can_read(row, actor):
        raise HouseDesignerError("session_not_found", "A házterv nem található.", status_code=404)
    revision = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == row.current_revision_id
        )
    )
    if revision is None:
        raise HouseDesignerError(
            "current_revision_missing",
            "A terv aktuális verziója nem elérhető.",
            status_code=409,
        )
    geometry = json.loads(revision.geometry_json)
    history = db.scalars(
        select(HouseDesignRevision)
        .where(HouseDesignRevision.session_id == session_id)
        .order_by(desc(HouseDesignRevision.revision_no))
        .limit(50)
    ).all()
    return _session_payload(
        row,
        revision,
        geometry=geometry,
        configuration=json.loads(revision.configuration_json),
        site=decode_revision_site(revision),
        geometry_findings=validate_geometry(geometry),
        history=history,
    )


def _session_payload(
    row: HouseDesignSession,
    revision: HouseDesignRevision,
    *,
    geometry: dict[str, Any],
    configuration: dict[str, Any],
    site: dict[str, Any],
    geometry_findings: list[dict[str, str]],
    history: list[HouseDesignRevision],
) -> dict[str, Any]:
    return {
        "sessionId": row.session_id,
        "tenantId": row.tenant_id,
        "brandId": row.brand_id,
        "ownerSubjectId": row.owner_subject_id,
        "projectId": row.project_id,
        "origin": row.origin,
        "templatePlanId": row.template_plan_id,
        "title": row.title,
        "status": row.status,
        "rowVersion": row.row_version,
        "revision": {
            "revisionId": revision.revision_id,
            "revisionNo": revision.revision_no,
            "canonicalSha256": revision.canonical_sha256,
            "geometry": geometry,
            "configuration": configuration,
            "site": site,
            "geometryFindings": geometry_findings,
        },
        "history": [
            {
                "revisionId": item.revision_id,
                "revisionNo": item.revision_no,
                "commandType": item.command_type,
                "canonicalSha256": item.canonical_sha256,
                "changeSummary": item.change_summary,
                "createdAt": item.created_at,
            }
            for item in history
        ],
    }


def list_sessions(db: Session, actor: ActorScope, *, limit: int = 100) -> list[dict[str, Any]]:
    query = select(HouseDesignSession).where(
        HouseDesignSession.tenant_id == actor.tenant_id,
        HouseDesignSession.brand_id.in_(actor.brand_ids),
    )
    if actor.can_read_all_owned:
        if actor.denied_project_ids:
            query = query.where(
                or_(
                    HouseDesignSession.project_id.is_(None),
                    HouseDesignSession.project_id.not_in(actor.denied_project_ids),
                    HouseDesignSession.owner_subject_id == actor.subject_id,
                )
            )
    else:
        readable = [HouseDesignSession.owner_subject_id == actor.subject_id]
        if actor.project_ids:
            readable.append(HouseDesignSession.project_id.in_(actor.project_ids))
        query = query.where(or_(*readable))
    rows = db.scalars(query.order_by(desc(HouseDesignSession.updated_at)).limit(limit)).all()
    return [
        {
            "sessionId": row.session_id,
            "title": row.title,
            "brandId": row.brand_id,
            "status": row.status,
            "origin": row.origin,
            "updatedAt": row.updated_at,
        }
        for row in rows
    ]


def decode_revision_site(revision: HouseDesignRevision) -> dict[str, Any]:
    try:
        raw = json.loads(revision.site_json)
        if not isinstance(raw, dict):
            raise ValueError("site is not an object")
        return unprotect_site(raw, revision.revision_id)
    except SitePrivacyError as error:
        raise HouseDesignerError(error.code, str(error), status_code=error.status_code) from error
    except (json.JSONDecodeError, ValueError) as error:
        raise HouseDesignerError(
            "site_data_invalid", "A tárolt telekadat hibás.", status_code=409
        ) from error


def audit_site_read(
    db: Session,
    *,
    actor: ActorScope,
    session_id: str,
    revision_id: str,
    site: dict[str, Any],
    channel: str,
) -> None:
    if not has_private_site_values(site):
        return
    audit(
        db,
        actor=actor.subject_id,
        action="house_designer.site.read",
        entity_type="HouseDesignRevision",
        entity_id=revision_id,
        after={
            "session_id": session_id,
            "channel": channel,
            "fields": [field for field in PRIVATE_SITE_FIELDS if site.get(field)],
        },
    )
    db.commit()


def list_template_plans(db: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(HousePlanRecord)
        .where(HousePlanRecord.status.in_(("approved", "catalog_ready", "published")))
        .order_by(desc(HousePlanRecord.updated_at))
        .limit(limit)
    ).all()
    return [
        {
            "planId": row.plan_id,
            "title": row.title,
            "status": row.status,
            "versionNumber": row.version_number,
        }
        for row in rows
    ]


def _locked_session(db: Session, session_id: str, actor: ActorScope) -> HouseDesignSession:
    row = db.scalar(
        select(HouseDesignSession)
        .where(
            HouseDesignSession.session_id == session_id,
            HouseDesignSession.tenant_id == actor.tenant_id,
        )
        .with_for_update()
    )
    if (
        row is None
        or row.owner_subject_id != actor.subject_id
        or row.brand_id not in actor.brand_ids
    ):
        raise HouseDesignerError("session_not_found", "A házterv nem található.", status_code=404)
    if row.status in {"SUBMITTED", "ARCHIVED", "CANCELLED"}:
        raise HouseDesignerError(
            "session_not_editable",
            "A házterv ebben az állapotban nem szerkeszthető.",
            status_code=409,
        )
    return row


def _can_read(row: HouseDesignSession, actor: ActorScope) -> bool:
    return row.brand_id in actor.brand_ids and actor.can_read(row.owner_subject_id, row.project_id)


def _require_brand(actor: ActorScope, brand_id: str) -> None:
    if brand_id not in actor.brand_ids:
        raise HouseDesignerError(
            "brand_forbidden", "Ehhez a márkához nincs hozzáférése.", status_code=403
        )


def _validated_site(payload: dict[str, Any]) -> dict[str, Any]:
    municipality = str(payload.get("municipalityCode") or "").strip()
    parcel = str(payload.get("parcelNumber") or "").strip()
    return {
        "country": "HU",
        "municipalityCode": municipality,
        "postalCode": str(payload.get("postalCode") or "").strip(),
        "city": str(payload.get("city") or "").strip(),
        "address": str(payload.get("address") or "").strip(),
        "parcelNumber": parcel,
        "verificationStatus": "unverified" if municipality and parcel else "missing",
        "sourceRefs": [],
    }


def _merge_configuration(current: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "constructionTechnology",
        "completionLevel",
        "roofType",
        "foundationType",
        "slabType",
        "stairType",
        "technicalPackage",
        "options",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise HouseDesignerError(
            "configuration_field_unknown",
            "Nem támogatott műszaki mező: " + ", ".join(unknown),
        )
    merged = dict(current)
    merged.update(payload)
    return merged


def _revision_hash(
    geometry: dict[str, Any], configuration: dict[str, Any], site: dict[str, Any]
) -> str:
    return _sha(
        {
            "geometrySha256": canonical_sha256_normalized(geometry),
            "configuration": configuration,
            "site": site,
        }
    )


def _default_summary(command_type: str) -> str:
    labels = {
        "set_footprint": "Az épület kontúrja módosult.",
        "add_level": "Új szint került a tervbe.",
        "clone_level": "Egy szint másolata új szintként került a tervbe.",
        "remove_level": "Egy szint törölve lett.",
        "add_furniture": "Új bútorsegéd került a tervbe.",
        "move_furniture": "Egy bútorsegéd helyzete módosult.",
        "resize_furniture": "Egy bútorsegéd mérete módosult.",
        "remove_furniture": "Egy bútorsegéd törölve lett.",
        "add_room": "Új helyiség került a tervbe.",
        "move_room": "Egy helyiség elmozdult.",
        "resize_room": "Egy helyiség mérete módosult.",
        "remove_room": "Egy helyiség törölve lett.",
        "set_room_function": "A helyiség funkciója módosult.",
        "set_roof": "A tető paraméterei módosultak.",
        "set_north": "Az északi irány módosult.",
        "set_configuration": "A műszaki tartalom módosult.",
        "set_site": "A telekadatok módosultak.",
        "restore_revision": "Egy korábbi tervverzió tartalma visszaállítva.",
    }
    return labels.get(command_type, "A házterv módosult.")


def _sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex.upper()}"
