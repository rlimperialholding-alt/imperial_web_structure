from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import HouseCatalogPlan, HouseCatalogVersion, ProjectRegistry
from ..schemas import EventIn, HouseCatalogReviewIn, HouseCatalogVersionIn
from .housematch import housematch_repository
from .integration import ingest_event

CATALOG_PROJECT_ID = "HOUSE-CATALOG-GOVERNANCE"
CREATOR_ROLES = {"owner", "managing-director", "platform-admin", "technical-prep"}
RELEASE_ROLES = {"owner", "managing-director", "platform-admin"}
VIEW_ROLES = CREATOR_ROLES | {"designer", "legal", "finance", "sales"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _require(user: object, roles: set[str]) -> tuple[str, str]:
    role = str(getattr(user, "role", ""))
    email = str(getattr(user, "email", "")).strip().lower()
    if role not in roles or "@" not in email:
        raise PermissionError("A House Catalog művelethez nincs megfelelő jogosultság.")
    return role, email


def _ensure_governance_project(db: Session, responsible: str) -> None:
    if db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == CATALOG_PROJECT_ID)):
        return
    db.add(
        ProjectRegistry(
            project_id=CATALOG_PROJECT_ID,
            name="House Catalog kiadáskezelés",
            project_type="catalog_governance",
            status="active",
            responsible=responsible,
            next_action="Tervverziók ellenőrzése, kiadása és visszavonása.",
        )
    )
    db.flush()


def _plan(db: Session, house_id: str, *, lock: bool = False) -> HouseCatalogPlan:
    stmt = select(HouseCatalogPlan).where(HouseCatalogPlan.house_id == house_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(house_id)
    return row


def _version(db: Session, catalog_version_id: str, *, lock: bool = False) -> HouseCatalogVersion:
    stmt = select(HouseCatalogVersion).where(
        HouseCatalogVersion.catalog_version_id == catalog_version_id
    )
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        raise KeyError(catalog_version_id)
    return row


def _payload(plan: HouseCatalogPlan, row: HouseCatalogVersion) -> dict[str, Any]:
    return {
        "house_id": plan.house_id,
        "brand": plan.brand,
        "name": plan.canonical_name,
        "version": row.version,
        "catalog_price_huf": str(row.catalog_price_huf),
        "gross_area_m2": str(row.gross_area_m2),
        "rooms": row.rooms,
        "price_status": row.price_status,
        "data_quality": row.data_quality,
        "lifestyles": json.loads(row.lifestyles_json or "[]"),
        "source_type": row.source_type,
        "source_url": row.source_url,
        "source_verified_at": row.source_verified_at,
        "rights_evidence": row.rights_evidence,
        "technical_summary": row.technical_summary,
        "change_summary": row.change_summary,
    }


def _hash(plan: HouseCatalogPlan, row: HouseCatalogVersion) -> str:
    raw = json.dumps(
        _payload(plan, row), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _emit(
    db: Session,
    plan: HouseCatalogPlan,
    row: HouseCatalogVersion,
    *,
    event_type: str,
    actor: str,
    summary: str,
) -> None:
    ingest_event(
        db,
        EventIn(
            event_id=f"EVT-CAT-{plan.house_id}-V{row.version}-{event_type}",
            dedupe_key=f"house-catalog:{plan.house_id}:v{row.version}:{event_type}",
            project_id=CATALOG_PROJECT_ID,
            source_module="house-catalog",
            event_type=event_type,
            object_type="HouseCatalogVersion",
            object_id=row.catalog_version_id,
            status=row.status,
            financial_impact_huf=row.catalog_price_huf,
            payload={
                "summary": summary,
                "house_id": plan.house_id,
                "version": row.version,
                "content_sha256": row.content_sha256,
            },
            route_to=[
                "housematch",
                "housebuild-agent",
                "buildconfig",
                "website-content-control",
            ],
        ),
        actor=actor,
    )
    db.commit()


def ensure_house_catalog_seed(db: Session) -> int:
    """Import the verified legacy workbook once as released, immutable baseline versions."""

    _ensure_governance_project(db, "system:catalog-migration")
    inserted = 0
    for source in housematch_repository.catalog(active_only=False):
        house_id = str(source["house_id"])
        if db.scalar(select(HouseCatalogPlan).where(HouseCatalogPlan.house_id == house_id)):
            continue
        active = bool(source.get("active"))
        plan = HouseCatalogPlan(
            house_id=house_id,
            brand=str(source.get("brand") or ""),
            canonical_name=str(source.get("name") or house_id),
            lifecycle_status="active" if active else "withdrawn",
            current_released_version=1 if active else None,
            created_by="system:catalog-migration",
        )
        row = HouseCatalogVersion(
            catalog_version_id=f"CAT-{house_id}-V1",
            house_id=house_id,
            version=1,
            status="released" if active else "withdrawn",
            catalog_price_huf=Decimal(str(source.get("catalog_price_huf") or 0)),
            gross_area_m2=Decimal(str(source.get("gross_area_m2") or 0)),
            rooms=str(source.get("rooms") or "n/a"),
            price_status=str(source.get("price_status") or "legacy"),
            data_quality=str(source.get("data_quality") or "legacy_verified"),
            lifestyles_json=json.dumps(source.get("lifestyles") or [], ensure_ascii=False),
            source_type=str(source.get("source_type") or "verified_workbook"),
            source_url=str(source.get("source_url") or "legacy://housematch-catalog"),
            source_verified_at=str(source.get("verified_at") or "legacy-import"),
            rights_evidence="Vállalati HouseMatch forrásjegyzékből migrált, ellenőrzött baseline.",
            technical_summary=str(source.get("note") or "Ellenőrzött katalógus baseline."),
            change_summary="HouseMatch v0.1 vállalati katalógus migráció.",
            source_approved_by="system:catalog-migration",
            source_approval_note="Ellenőrzött vállalati forrásból migrálva.",
            source_approved_at=utcnow(),
            technical_approved_by="system:catalog-migration",
            technical_approval_note="A meglévő, használt katalógus baseline-ja.",
            technical_approved_at=utcnow(),
            commercial_approved_by="system:catalog-migration",
            commercial_approval_note="A meglévő katalógusárral migrálva.",
            commercial_approved_at=utcnow(),
            released_by="system:catalog-migration" if active else None,
            released_at=utcnow() if active else None,
            withdrawn_by="system:catalog-migration" if not active else None,
            withdrawn_at=utcnow() if not active else None,
            withdrawal_reason="A forráskatalógusban inaktív." if not active else None,
            created_by="system:catalog-migration",
        )
        row.content_sha256 = _hash(plan, row)
        db.add(plan)
        db.add(row)
        inserted += 1
    db.commit()
    return inserted


def public_catalog(db: Session, *, brand: str | None = None) -> list[dict[str, Any]]:
    ensure_house_catalog_seed(db)
    stmt = (
        select(HouseCatalogPlan, HouseCatalogVersion)
        .join(
            HouseCatalogVersion,
            (HouseCatalogVersion.house_id == HouseCatalogPlan.house_id)
            & (HouseCatalogVersion.version == HouseCatalogPlan.current_released_version),
        )
        .where(
            HouseCatalogPlan.lifecycle_status == "active",
            HouseCatalogVersion.status == "released",
        )
        .order_by(HouseCatalogPlan.brand, HouseCatalogPlan.canonical_name)
    )
    if brand:
        stmt = stmt.where(HouseCatalogPlan.brand.ilike(brand))
    return [
        {
            "house_id": plan.house_id,
            "brand": plan.brand,
            "name": plan.canonical_name,
            "catalog_price_huf": int(version.catalog_price_huf),
            "gross_area_m2": float(version.gross_area_m2),
            "price_per_m2_huf": int(version.catalog_price_huf / version.gross_area_m2),
            "rooms": version.rooms,
            "price_status": version.price_status,
            "active": True,
            "data_quality": version.data_quality,
            "lifestyles": json.loads(version.lifestyles_json or "[]"),
            "source_type": version.source_type,
            "source_url": version.source_url,
            "verified_at": version.source_verified_at,
            "note": version.technical_summary,
            "catalog_version_id": version.catalog_version_id,
            "catalog_version": version.version,
            "content_sha256": version.content_sha256,
        }
        for plan, version in db.execute(stmt).all()
    ]


def released_house(db: Session, house_id: str) -> dict[str, Any] | None:
    return next((row for row in public_catalog(db) if row["house_id"] == house_id), None)


def create_catalog_version(
    db: Session, data: HouseCatalogVersionIn, user: object
) -> HouseCatalogVersion:
    _role, email = _require(user, CREATOR_ROLES)
    ensure_house_catalog_seed(db)
    _ensure_governance_project(db, email)
    plan = db.scalar(
        select(HouseCatalogPlan).where(HouseCatalogPlan.house_id == data.house_id).with_for_update()
    )
    if not plan:
        plan = HouseCatalogPlan(
            house_id=data.house_id,
            brand=data.brand,
            canonical_name=data.canonical_name,
            lifecycle_status="active",
            created_by=email,
        )
        db.add(plan)
        db.flush()
    elif plan.brand != data.brand or plan.canonical_name != data.canonical_name:
        raise ValueError("Meglévő HouseID márkája és kanonikus neve nem írható át verzióval.")
    live = db.scalar(
        select(HouseCatalogVersion).where(
            HouseCatalogVersion.house_id == data.house_id,
            HouseCatalogVersion.status.in_({"draft", "review", "approved"}),
        )
    )
    if live:
        raise ValueError(f"A házhoz már van nyitott verzió: {live.catalog_version_id}.")
    previous = db.scalar(
        select(HouseCatalogVersion)
        .where(HouseCatalogVersion.house_id == data.house_id)
        .order_by(desc(HouseCatalogVersion.version))
    )
    version_number = previous.version + 1 if previous else 1
    row = HouseCatalogVersion(
        catalog_version_id=f"CAT-{data.house_id}-V{version_number}",
        house_id=data.house_id,
        version=version_number,
        catalog_price_huf=data.catalog_price_huf,
        gross_area_m2=data.gross_area_m2,
        rooms=data.rooms,
        price_status=data.price_status,
        data_quality=data.data_quality,
        lifestyles_json=json.dumps(data.lifestyles, ensure_ascii=False),
        source_type=data.source_type,
        source_url=data.source_url,
        source_verified_at=data.source_verified_at,
        rights_evidence=data.rights_evidence,
        technical_summary=data.technical_summary,
        change_summary=data.change_summary,
        created_by=email,
    )
    db.add(row)
    audit(
        db,
        actor=email,
        action="house_catalog_version_created",
        entity_type="house_catalog_version",
        entity_id=row.catalog_version_id,
        after=data.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(row)
    return row


def submit_catalog_version(
    db: Session, catalog_version_id: str, user: object
) -> HouseCatalogVersion:
    _role, email = _require(user, CREATOR_ROLES)
    row = _version(db, catalog_version_id, lock=True)
    plan = _plan(db, row.house_id, lock=True)
    if row.status != "draft":
        raise ValueError("Csak draft katalógusverzió küldhető review-ba.")
    if row.catalog_price_huf <= 0 or row.gross_area_m2 <= 0:
        raise ValueError("Pozitív katalógusár és bruttó alapterület kötelező.")
    if len(row.rights_evidence.strip()) < 8 or len(row.technical_summary.strip()) < 10:
        raise ValueError("Forrásjogi bizonyíték és részletes műszaki összefoglaló kötelező.")
    row.content_sha256 = _hash(plan, row)
    row.status = "review"
    audit(
        db,
        actor=email,
        action="house_catalog_version_submitted",
        entity_type="house_catalog_version",
        entity_id=row.catalog_version_id,
        after={"content_sha256": row.content_sha256},
    )
    _emit(
        db,
        plan,
        row,
        event_type="HOUSE_CATALOG_VERSION_SUBMITTED",
        actor=email,
        summary="A tervverzió változtathatatlan hash-sel review-ba került.",
    )
    db.refresh(row)
    return row


def review_catalog_version(
    db: Session,
    catalog_version_id: str,
    data: HouseCatalogReviewIn,
    user: object,
) -> HouseCatalogVersion:
    role, email = _require(user, VIEW_ROLES)
    row = _version(db, catalog_version_id, lock=True)
    plan = _plan(db, row.house_id, lock=True)
    if row.status != "review":
        raise ValueError("Csak review állapotú katalógusverzió bírálható.")
    roles = {
        "source": {"legal", "platform-admin"},
        "technical": {"technical-prep", "designer", "platform-admin"},
        "commercial": {"finance", "sales", "platform-admin"},
    }
    if role not in roles[data.gate]:
        raise PermissionError("A felhasználó nem jogosult erre a katalóguskapura.")
    prior = {
        "source": [],
        "technical": [row.source_approved_by],
        "commercial": [row.source_approved_by, row.technical_approved_by],
    }[data.gate]
    if any(value is None for value in prior):
        raise ValueError(
            "A katalóguskapuk csak source → technical → commercial sorrendben zárhatók."
        )
    reviewers = {
        row.created_by,
        row.source_approved_by,
        row.technical_approved_by,
    }
    if email in {value for value in reviewers if value}:
        raise ValueError("A készítő és korábbi bíráló nem hagyhat jóvá újabb kaput.")
    if data.decision == "reject":
        row.status = "rejected"
    else:
        setattr(row, f"{data.gate}_approved_by", email)
        setattr(row, f"{data.gate}_approval_note", data.note)
        setattr(row, f"{data.gate}_approved_at", utcnow())
        if data.gate == "commercial":
            row.status = "approved"
    audit(
        db,
        actor=email,
        action=f"house_catalog_{data.gate}_{data.decision}",
        entity_type="house_catalog_version",
        entity_id=row.catalog_version_id,
        after=data.model_dump(),
    )
    _emit(
        db,
        plan,
        row,
        event_type=f"HOUSE_CATALOG_{data.gate.upper()}_{data.decision.upper()}",
        actor=email,
        summary=f"A katalógusverzió {data.gate} kapuja: {data.decision}.",
    )
    db.refresh(row)
    return row


def release_catalog_version(
    db: Session, catalog_version_id: str, user: object
) -> HouseCatalogVersion:
    _role, email = _require(user, RELEASE_ROLES)
    row = _version(db, catalog_version_id, lock=True)
    plan = _plan(db, row.house_id, lock=True)
    if row.status != "approved":
        raise ValueError("Csak minden kapun jóváhagyott katalógusverzió adható ki.")
    if email in {
        row.created_by,
        row.source_approved_by,
        row.technical_approved_by,
        row.commercial_approved_by,
    }:
        raise ValueError(
            "A kiadási döntésnek a készítőtől és bírálóktól elkülönültnek kell lennie."
        )
    if row.content_sha256 != _hash(plan, row):
        raise ValueError("A katalógusverzió tartalma a jóváhagyás óta megváltozott.")
    current = db.scalar(
        select(HouseCatalogVersion).where(
            HouseCatalogVersion.house_id == plan.house_id,
            HouseCatalogVersion.status == "released",
        )
    )
    if current:
        current.status = "superseded"
    row.status = "released"
    row.released_by = email
    row.released_at = utcnow()
    plan.current_released_version = row.version
    plan.lifecycle_status = "active"
    audit(
        db,
        actor=email,
        action="house_catalog_version_released",
        entity_type="house_catalog_version",
        entity_id=row.catalog_version_id,
        after={"content_sha256": row.content_sha256},
    )
    _emit(
        db,
        plan,
        row,
        event_type="HOUSE_CATALOG_VERSION_RELEASED",
        actor=email,
        summary="A tervverzió a HouseMatch és HouseBuild számára kiadásra került.",
    )
    db.refresh(row)
    return row


def withdraw_catalog_plan(
    db: Session, house_id: str, *, reason: str, user: object
) -> HouseCatalogVersion:
    _role, email = _require(user, RELEASE_ROLES)
    if len(reason.strip()) < 10:
        raise ValueError("A visszavonás részletes indoklása kötelező.")
    plan = _plan(db, house_id, lock=True)
    if plan.lifecycle_status != "active" or plan.current_released_version is None:
        raise ValueError("Csak aktív, kiadott katalógusterv vonható vissza.")
    row = db.scalar(
        select(HouseCatalogVersion).where(
            HouseCatalogVersion.house_id == house_id,
            HouseCatalogVersion.version == plan.current_released_version,
        )
    )
    if row is None:
        raise KeyError(f"{house_id}/v{plan.current_released_version}")
    row.status = "withdrawn"
    row.withdrawn_by = email
    row.withdrawn_at = utcnow()
    row.withdrawal_reason = reason.strip()
    plan.lifecycle_status = "withdrawn"
    plan.current_released_version = None
    audit(
        db,
        actor=email,
        action="house_catalog_plan_withdrawn",
        entity_type="house_catalog_version",
        entity_id=row.catalog_version_id,
        after={"reason": reason.strip()},
    )
    _emit(
        db,
        plan,
        row,
        event_type="HOUSE_CATALOG_PLAN_WITHDRAWN",
        actor=email,
        summary=f"A katalógusterv visszavonva: {reason.strip()}",
    )
    db.refresh(row)
    return row


def catalog_workspace(db: Session) -> dict[str, Any]:
    ensure_house_catalog_seed(db)
    plans = db.scalars(
        select(HouseCatalogPlan).order_by(HouseCatalogPlan.brand, HouseCatalogPlan.canonical_name)
    ).all()
    versions = db.scalars(
        select(HouseCatalogVersion).order_by(
            HouseCatalogVersion.house_id, desc(HouseCatalogVersion.version)
        )
    ).all()
    by_house: dict[str, list[HouseCatalogVersion]] = {}
    for row in versions:
        by_house.setdefault(row.house_id, []).append(row)
    return {
        "plans": plans,
        "versions": versions,
        "by_house": by_house,
        "metrics": {
            "released": sum(1 for row in plans if row.lifecycle_status == "active"),
            "withdrawn": sum(1 for row in plans if row.lifecycle_status == "withdrawn"),
            "in_review": sum(1 for row in versions if row.status == "review"),
            "approved_waiting_release": sum(1 for row in versions if row.status == "approved"),
        },
    }


def serialize_catalog_plan(row: HouseCatalogPlan) -> dict[str, Any]:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name != "id"
    }


def serialize_catalog_version(row: HouseCatalogVersion) -> dict[str, Any]:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name != "id"
    }
