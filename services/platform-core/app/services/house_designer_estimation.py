from __future__ import annotations

import hashlib
import json
import math
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    HouseDesignEstimateSnapshot,
    HouseDesignRevision,
    HouseDesignScheduleSnapshot,
    HouseDesignSession,
    utcnow,
)
from .house_designer import ActorScope, HouseDesignerError
from .house_designer_geometry import gross_area_m2

_BASE_NET_HUF_M2 = {
    "timber-frame": Decimal("570000"),
    "masonry": Decimal("620000"),
    "reinforced-concrete": Decimal("720000"),
}
_COMPLETION_FACTOR = {
    "structural": Decimal("0.48"),
    "ready-for-finishes": Decimal("0.72"),
    "turnkey": Decimal("1.00"),
}
_PACKAGE_FACTOR = {
    "comfort": Decimal("1.00"),
    "premium": Decimal("1.22"),
    "custom": Decimal("1.12"),
}
_PHASES = (
    ("Előkészítés és alapozás", Decimal("0.16")),
    ("Szerkezetépítés", Decimal("0.31")),
    ("Tető és külső nyílászárók", Decimal("0.17")),
    ("Gépészet és villamosság", Decimal("0.18")),
    ("Belső befejező munkák", Decimal("0.18")),
)


def create_sandbox_estimate(db: Session, *, session_id: str, actor: ActorScope) -> dict[str, Any]:
    session = db.scalar(
        select(HouseDesignSession)
        .where(
            HouseDesignSession.session_id == session_id,
            HouseDesignSession.tenant_id == actor.tenant_id,
        )
        .with_for_update()
    )
    if (
        session is None
        or session.brand_id not in actor.brand_ids
        or not actor.can_read(session.owner_subject_id, session.project_id)
    ):
        raise HouseDesignerError("session_not_found", "A házterv nem található.", status_code=404)
    revision = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == session.current_revision_id
        )
    )
    if revision is None:
        raise HouseDesignerError(
            "current_revision_missing", "A terv aktuális verziója nem elérhető.", status_code=409
        )
    geometry = json.loads(revision.geometry_json)
    configuration = json.loads(revision.configuration_json)
    required = ("constructionTechnology", "completionLevel", "technicalPackage")
    missing = [key for key in required if not configuration.get(key)]
    if missing:
        raise HouseDesignerError(
            "configuration_incomplete",
            "A becsléshez előbb válasszon technológiát, készültséget és műszaki csomagot.",
        )
    area = Decimal(str(gross_area_m2(geometry)))
    if area <= 0:
        raise HouseDesignerError("geometry_empty", "A becsléshez mérhető alaprajz szükséges.")
    technology = str(configuration["constructionTechnology"])
    completion = str(configuration["completionLevel"])
    package = str(configuration["technicalPackage"])
    try:
        central = (
            area
            * _BASE_NET_HUF_M2[technology]
            * _COMPLETION_FACTOR[completion]
            * _PACKAGE_FACTOR[package]
        )
    except KeyError as error:
        raise HouseDesignerError(
            "configuration_not_priced", "A kiválasztott műszaki kombinációhoz nincs tesztár."
        ) from error
    input_payload = {
        "revisionId": revision.revision_id,
        "canonicalSha256": revision.canonical_sha256,
        "areaM2": str(area),
        "configuration": configuration,
        "providerVersion": "sandbox-buildconfig-v1",
    }
    input_sha256 = _sha(input_payload)
    existing = db.scalar(
        select(HouseDesignEstimateSnapshot)
        .where(
            HouseDesignEstimateSnapshot.session_id == session_id,
            HouseDesignEstimateSnapshot.input_sha256 == input_sha256,
        )
        .order_by(desc(HouseDesignEstimateSnapshot.created_at))
    )
    existing_schedule = db.scalar(
        select(HouseDesignScheduleSnapshot)
        .where(
            HouseDesignScheduleSnapshot.session_id == session_id,
            HouseDesignScheduleSnapshot.input_sha256 == input_sha256,
        )
        .order_by(desc(HouseDesignScheduleSnapshot.created_at))
    )
    if existing and existing_schedule:
        return _result(existing, existing_schedule)
    net_min = _money(central * Decimal("0.88"))
    net_max = _money(central * Decimal("1.15"))
    vat_rate = Decimal("0.27")
    gross_min = _money(net_min * (Decimal("1") + vat_rate))
    gross_max = _money(net_max * (Decimal("1") + vat_rate))
    line_items = [
        {
            "name": name,
            "netMinHuf": int(_money(net_min * share)),
            "netMaxHuf": int(_money(net_max * share)),
        }
        for name, share in _PHASES
    ]
    workday_factor = Decimal("1.25") if technology == "timber-frame" else Decimal("1.55")
    duration_mid = max(45, math.ceil(float(area * workday_factor)))
    duration_min = max(35, math.floor(duration_mid * 0.86))
    duration_max = math.ceil(duration_mid * 1.2)
    phases = _schedule_phases(duration_min, duration_max)
    now = utcnow()
    estimate = HouseDesignEstimateSnapshot(
        estimate_id=_id("HDE"),
        session_id=session_id,
        design_revision_id=revision.revision_id,
        input_sha256=input_sha256,
        net_min_huf=net_min,
        net_max_huf=net_max,
        vat_rate=vat_rate,
        gross_min_huf=gross_min,
        gross_max_huf=gross_max,
        line_items_json=_json(line_items),
        assumptions_json=_json(
            [
                "Tesztárszint, nem minősül ajánlatnak.",
                f"Számított bruttó terület: {area} m².",
                "Normál telek- és kivitelezési feltételezés.",
            ]
        ),
        exclusions_json=_json(
            [
                "Telekár, közműfejlesztési díjak és hatósági díjak.",
                "Rendkívüli alapozás, talajcsere és egyedi tervezői tételek.",
            ]
        ),
        provider="sandbox_buildconfig_adapter_v1",
        non_production=True,
        valid_until=now + timedelta(days=14),
        canonical_sha256=_sha(
            {
                "input": input_sha256,
                "netMin": str(net_min),
                "netMax": str(net_max),
                "vat": str(vat_rate),
            }
        ),
        created_by=actor.subject_id,
    )
    schedule = HouseDesignScheduleSnapshot(
        schedule_id=_id("HDT"),
        session_id=session_id,
        design_revision_id=revision.revision_id,
        input_sha256=input_sha256,
        duration_min_workdays=duration_min,
        duration_max_workdays=duration_max,
        phases_json=_json(phases),
        assumptions_json=_json(
            [
                "Teszt kapacitásmodell; tényleges kezdés csak erőforrás-visszaigazolás után.",
                "Ötnapos munkahét és normál időjárási kockázat.",
            ]
        ),
        provider="sandbox_capacity_v1",
        non_production=True,
        valid_until=now + timedelta(days=7),
        canonical_sha256=_sha(
            {"input": input_sha256, "min": duration_min, "max": duration_max, "phases": phases}
        ),
        created_by=actor.subject_id,
    )
    db.add_all([estimate, schedule])
    audit(
        db,
        actor=actor.subject_id,
        action="house_designer.sandbox_estimate.create",
        entity_type="HouseDesignSession",
        entity_id=session_id,
        after={
            "revision_id": revision.revision_id,
            "estimate_id": estimate.estimate_id,
            "schedule_id": schedule.schedule_id,
            "non_production": True,
        },
    )
    db.commit()
    return _result(estimate, schedule)


def latest_estimate_bundle(db: Session, session_id: str, revision_id: str) -> dict[str, Any] | None:
    estimate = db.scalar(
        select(HouseDesignEstimateSnapshot)
        .where(
            HouseDesignEstimateSnapshot.session_id == session_id,
            HouseDesignEstimateSnapshot.design_revision_id == revision_id,
        )
        .order_by(desc(HouseDesignEstimateSnapshot.created_at))
    )
    if estimate is None:
        return None
    schedule = db.scalar(
        select(HouseDesignScheduleSnapshot)
        .where(
            HouseDesignScheduleSnapshot.session_id == session_id,
            HouseDesignScheduleSnapshot.design_revision_id == revision_id,
        )
        .order_by(desc(HouseDesignScheduleSnapshot.created_at))
    )
    return _result(estimate, schedule) if schedule else None


def _result(
    estimate: HouseDesignEstimateSnapshot, schedule: HouseDesignScheduleSnapshot
) -> dict[str, Any]:
    return {
        "estimateId": estimate.estimate_id,
        "scheduleId": schedule.schedule_id,
        "netMinHuf": estimate.net_min_huf,
        "netMaxHuf": estimate.net_max_huf,
        "grossMinHuf": estimate.gross_min_huf,
        "grossMaxHuf": estimate.gross_max_huf,
        "vatRate": estimate.vat_rate,
        "lineItems": json.loads(estimate.line_items_json),
        "estimateAssumptions": json.loads(estimate.assumptions_json),
        "exclusions": json.loads(estimate.exclusions_json),
        "durationMinWorkdays": schedule.duration_min_workdays,
        "durationMaxWorkdays": schedule.duration_max_workdays,
        "phases": json.loads(schedule.phases_json),
        "scheduleAssumptions": json.loads(schedule.assumptions_json),
        "estimateValidUntil": estimate.valid_until,
        "scheduleValidUntil": schedule.valid_until,
        "nonProduction": estimate.non_production or schedule.non_production,
    }


def _schedule_phases(duration_min: int, duration_max: int) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "minWorkdays": max(1, round(duration_min * float(share))),
            "maxWorkdays": max(1, round(duration_max * float(share))),
        }
        for name, share in _PHASES
    ]


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _id(prefix: str) -> str:
    from uuid import uuid4

    return f"{prefix}-{uuid4().hex}"
