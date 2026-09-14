from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    BuildConfigCase,
    BuildConfigGate,
    BuildConfigValidation,
    BuildConfigVersion,
    HouseBuildCase,
    HouseBuildVariant,
    WorkspaceDocument,
)
from .pricing import ARTUKOR_FILE, INTERNAL_MODEL_FILE, WEB_PRICES_FILE, pricing_repository

CREATOR_ROLES = {
    "owner",
    "managing-director",
    "platform-admin",
    "technical-prep",
    "sales",
    "designer",
}
TECHNICAL_REVIEW_ROLES = {
    "owner",
    "managing-director",
    "platform-admin",
    "technical-prep",
    "designer",
}
FINANCE_REVIEW_ROLES = {"owner", "managing-director", "platform-admin", "finance"}
RELEASE_ROLES = {"owner", "managing-director", "platform-admin"}
AUTOMATIC_GATES = {
    "source",
    "houseplan",
    "compatibility",
    "bom",
    "pricing",
    "margin",
    "cashflow",
    "capacity",
}
GATE_KEYS = (
    "source",
    "houseplan",
    "compatibility",
    "bom",
    "pricing",
    "margin",
    "cashflow",
    "capacity",
    "technical",
    "finance",
)
MIN_MARGIN = Decimal("0.35")
POLICY_VERSION = "BUILDCONFIG-POLICY-2026-08-v1"
RUNTIME_ROOT = Path(os.getenv("PLATFORM_RUNTIME_ROOT", "/app/runtime")) / "buildconfig"

OPTION_CATALOG: dict[str, dict[str, Any]] = {
    "solar_ready": {
        "label": "Napelem-előkészítés",
        "net_price_huf": 1_800_000,
        "net_cost_huf": 1_050_000,
        "duration_days": 2,
    },
    "heat_pump_upgrade": {
        "label": "Emelt hőszivattyús gépészet",
        "net_price_huf": 3_200_000,
        "net_cost_huf": 1_900_000,
        "duration_days": 4,
        "minimum_completion": "Fűtéskész",
    },
    "smart_home": {
        "label": "Okosotthon csomag",
        "net_price_huf": 2_400_000,
        "net_cost_huf": 1_350_000,
        "duration_days": 3,
        "excluded_packages": ["Alap"],
    },
    "garage_package": {
        "label": "Garázs műszaki csomag",
        "net_price_huf": 8_500_000,
        "net_cost_huf": 5_200_000,
        "duration_days": 8,
        "requires_garage": True,
    },
    "accessible_package": {
        "label": "Akadálymentes részletcsomag",
        "net_price_huf": 3_500_000,
        "net_cost_huf": 2_100_000,
        "duration_days": 5,
        "requires_accessibility": True,
    },
    "green_roof": {
        "label": "Extenzív zöldtető",
        "net_price_huf": 6_800_000,
        "net_cost_huf": 4_200_000,
        "duration_days": 7,
        "required_roof_style": "lapostető",
    },
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def _identity(user: object) -> tuple[str, str]:
    return (
        str(getattr(user, "role", "")),
        str(getattr(user, "email", "")).strip().lower(),
    )


def _decimal(value: Any, label: str, minimum: str, maximum: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"A(z) {label} csak érvényes szám lehet.") from exc
    if number < Decimal(minimum) or number > Decimal(maximum):
        raise ValueError(f"A(z) {label} {minimum} és {maximum} között lehet.")
    return number


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"A(z) {label} csak egész szám lehet.") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"A(z) {label} {minimum} és {maximum} között lehet.")
    return number


def _parse_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"A(z) {label} érvényes ISO-dátum legyen.") from exc


def _case(db: Session, case_id: str, *, lock: bool = False) -> BuildConfigCase:
    stmt = select(BuildConfigCase).where(BuildConfigCase.case_id == case_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise KeyError(case_id)
    return row


def _version(db: Session, version_id: str, *, lock: bool = False) -> BuildConfigVersion:
    stmt = select(BuildConfigVersion).where(BuildConfigVersion.version_id == version_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise KeyError(version_id)
    return row


def option_catalog() -> list[dict[str, Any]]:
    return [{"code": code, **definition} for code, definition in OPTION_CATALOG.items()]


def housebuild_variants(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(HouseBuildCase, HouseBuildVariant)
        .join(
            HouseBuildVariant,
            HouseBuildVariant.variant_id == HouseBuildCase.selected_variant_id,
        )
        .where(HouseBuildCase.status.in_(("variant_selected", "review", "released")))
        .order_by(HouseBuildCase.updated_at.desc())
    ).all()
    return [
        {
            "case_id": case.case_id,
            "project_id": case.project_id,
            "title": case.title,
            "variant_id": variant.variant_id,
            "label": variant.label,
            "gross_area_m2": float(variant.gross_area_m2),
            "technology": _loads(case.requirement_json, {}).get("technology", ""),
            "status": case.status,
        }
        for case, variant in rows
    ]


def _source_snapshot() -> dict[str, Any]:
    files = {
        "public_pricing": {"name": WEB_PRICES_FILE.name, "sha256": _file_sha(WEB_PRICES_FILE)},
        "internal_model": {
            "name": INTERNAL_MODEL_FILE.name,
            "sha256": _file_sha(INTERNAL_MODEL_FILE),
        },
        "normbook": {"name": ARTUKOR_FILE.name, "sha256": _file_sha(ARTUKOR_FILE)},
    }
    return {"policy_version": POLICY_VERSION, "files": files, "snapshot_sha256": _sha(files)}


def _selected_options(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("options") or []
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",") if item.strip()]
    if not isinstance(raw, list):
        raise ValueError("A BuildConfig-opciók listája hibás.")
    codes = list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))
    unknown = sorted(set(codes) - set(OPTION_CATALOG))
    if unknown:
        raise ValueError("Ismeretlen BuildConfig-opció: " + ", ".join(unknown))
    return [{"code": code, **OPTION_CATALOG[code]} for code in codes]


def _compatibility_errors(
    options: list[dict[str, Any]],
    variant: HouseBuildVariant,
    completion_level: str,
    package_name: str,
) -> list[str]:
    completion_rank = {"Szerkezetkész": 1, "Fűtéskész": 2, "Kulcsrakész": 3}
    errors: list[str] = []
    for option in options:
        minimum = option.get("minimum_completion")
        if minimum and completion_rank.get(completion_level, 0) < completion_rank.get(minimum, 0):
            errors.append(f"{option['code']}: legalább {minimum} készültség szükséges")
        if package_name in option.get("excluded_packages", []):
            errors.append(f"{option['code']}: a(z) {package_name} csomaggal nem kompatibilis")
        if option.get("requires_garage") and variant.garage_spaces < 1:
            errors.append(f"{option['code']}: garázzsal rendelkező HousePlan szükséges")
        if option.get("requires_accessibility") and not variant.accessibility:
            errors.append(f"{option['code']}: akadálymentes HousePlan szükséges")
        required_roof_style = option.get("required_roof_style")
        if required_roof_style and variant.roof_style != required_roof_style:
            errors.append(f"{option['code']}: {required_roof_style} tetőforma szükséges")
    return errors


def _bom(base_cost: Decimal, options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    shares = (
        ("BOM-FOUNDATION", "Alapozás és földmunka", Decimal("0.12")),
        ("BOM-STRUCTURE", "Teherhordó szerkezet", Decimal("0.28")),
        ("BOM-ROOF", "Tető és vízszigetelés", Decimal("0.12")),
        ("BOM-MEP", "Gépészet és villamosság", Decimal("0.22")),
        ("BOM-FINISH", "Belső és külső befejező munkák", Decimal("0.20")),
        ("BOM-INDIRECT", "Közvetett kivitelezési költség", Decimal("0.06")),
    )
    rows: list[dict[str, Any]] = [
        {
            "line_id": code,
            "category": "base_scope",
            "name": label,
            "quantity": "1",
            "unit": "lot",
            "net_cost_huf": int((base_cost * share).quantize(Decimal("1"))),
            "source": POLICY_VERSION,
        }
        for code, label, share in shares
    ]
    base_target = base_cost.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    base_actual = sum((Decimal(str(row["net_cost_huf"])) for row in rows), Decimal("0"))
    rows[-1]["net_cost_huf"] += int(base_target - base_actual)
    rows.extend(
        {
            "line_id": f"BOM-OPT-{option['code'].upper()}",
            "category": "option",
            "name": option["label"],
            "quantity": "1",
            "unit": "lot",
            "net_cost_huf": option["net_cost_huf"],
            "source": f"{POLICY_VERSION}:{option['code']}",
        }
        for option in options
    )
    return rows


def _payment_schedule(
    net_price: Decimal, net_cost: Decimal
) -> tuple[list[dict[str, Any]], Decimal]:
    milestones = (
        ("contract", "Szerződés és mobilizáció", 10, 5),
        ("foundation", "Alapozás kész", 15, 15),
        ("structure", "Szerkezetkész", 25, 25),
        ("weatherproof", "Időjárásálló burok", 20, 25),
        ("mep_finish", "Gépészet és befejezés", 20, 20),
        ("handover", "Átadás", 10, 10),
    )
    rows: list[dict[str, Any]] = []
    cumulative_payment = Decimal("0")
    cumulative_cost = Decimal("0")
    minimum_balance = Decimal("0")
    for code, label, payment_percent, cost_percent in milestones:
        payment = (net_price * Decimal(payment_percent) / Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        cost = (net_cost * Decimal(cost_percent) / Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        cumulative_payment += payment
        cumulative_cost += cost
        balance = cumulative_payment - cumulative_cost
        minimum_balance = min(minimum_balance, balance)
        rows.append(
            {
                "milestone": code,
                "label": label,
                "payment_percent": payment_percent,
                "planned_cost_percent": cost_percent,
                "net_payment_huf": int(payment),
                "planned_net_cost_huf": int(cost),
                "cumulative_financing_balance_huf": int(balance),
            }
        )
    return rows, minimum_balance


def _capacity(data: dict[str, Any], area: Decimal, option_days: int) -> dict[str, Any]:
    start = _parse_date(data.get("planned_start"), "tervezett kezdés")
    promised = _parse_date(data.get("promised_delivery"), "vállalt átadás")
    crews = _integer(data.get("crew_count") or 1, "brigádszám", 1, 8)
    weekly_capacity = _decimal(
        data.get("weekly_capacity_m2") or "30", "heti kapacitás", "5", "1000"
    )
    weeks = Decimal(str(math.ceil(float(area / (weekly_capacity * crews)))))
    duration_days = max(30, int(weeks * 7) + option_days)
    estimated_finish = start + timedelta(days=duration_days)
    return {
        "planned_start": start.isoformat(),
        "promised_delivery": promised.isoformat(),
        "crew_count": crews,
        "weekly_capacity_m2": str(weekly_capacity),
        "duration_days": duration_days,
        "estimated_finish": estimated_finish.isoformat(),
        "capacity_ok": estimated_finish <= promised,
        "slack_days": (promised - estimated_finish).days,
    }


def _calculation(
    data: dict[str, Any], variant: HouseBuildVariant
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    brand = str(data.get("brand") or "").strip()
    technology = str(data.get("technology") or "").strip()
    completion_level = str(data.get("completion_level") or "Kulcsrakész").strip()
    package_name = str(data.get("package") or "Alap").strip()
    area = _decimal(data.get("gross_area_m2"), "bruttó alapterület", "20", "500")
    if abs(area - Decimal(variant.gross_area_m2)) > Decimal("0.1"):
        raise ValueError(
            "A BuildConfig alapterülete nem térhet el a kiválasztott HousePlan értékétől."
        )
    vat_rate = _decimal(data.get("vat_rate") or "0.05", "ÁFA-kulcs", "0", "0.30")
    options = _selected_options(data)
    compatibility = _compatibility_errors(options, variant, completion_level, package_name)
    pricing = pricing_repository.calculate_new_build(
        brand=brand,
        technology=technology,
        completion_level=completion_level,
        package=package_name,
        gross_area_m2=area,
        vat_rate=vat_rate,
        include_internal=True,
    )
    internal = pricing.get("internal_control") or {}
    if not internal.get("cash_cost_total_huf"):
        raise ValueError("Belső önköltségforrás nélkül BuildConfig-verzió nem hozható létre.")
    base_cost = Decimal(str(internal["cash_cost_total_huf"]))
    base_price = Decimal(str(pricing["estimated_net_total_huf"]))
    option_cost = sum((Decimal(str(item["net_cost_huf"])) for item in options), Decimal("0"))
    option_price = sum((Decimal(str(item["net_price_huf"])) for item in options), Decimal("0"))
    net_cost = base_cost + option_cost
    net_price = base_price + option_price
    vat = (net_price * vat_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    gross_price = net_price + vat
    margin = (Decimal("1") - net_cost / net_price) if net_price else Decimal("0")
    bom = _bom(base_cost, options)
    payment_schedule, minimum_balance = _payment_schedule(net_price, net_cost)
    capacity = _capacity(data, area, sum(int(item.get("duration_days", 0)) for item in options))
    source = _source_snapshot()
    pricing_snapshot = {
        "pricing": pricing,
        "source": source,
        "policy_version": POLICY_VERSION,
        "minimum_margin": str(MIN_MARGIN),
    }
    values = {
        "brand": brand,
        "technology": pricing["technology"],
        "completion_level": completion_level,
        "package_name": package_name,
        "gross_area_m2": area,
        "vat_rate": vat_rate,
        "options": options,
        "bom": bom,
        "payment_schedule": payment_schedule,
        "capacity": capacity,
        "pricing_snapshot": pricing_snapshot,
        "source_sha256": _sha(source),
        "bom_sha256": _sha(bom),
        "net_cost_huf": net_cost,
        "net_price_huf": net_price,
        "vat_huf": vat,
        "gross_price_huf": gross_price,
        "margin_percent": (margin * Decimal("100")).quantize(Decimal("0.0001")),
        "duration_days": capacity["duration_days"],
    }
    values["config_sha256"] = _sha(
        {
            "housebuild_variant_id": variant.variant_id,
            "brand": brand,
            "technology": pricing["technology"],
            "completion_level": completion_level,
            "package": package_name,
            "gross_area_m2": str(area),
            "vat_rate": str(vat_rate),
            "options": options,
            "bom_sha256": values["bom_sha256"],
            "source_sha256": values["source_sha256"],
            "payment_schedule": payment_schedule,
            "capacity": capacity,
        }
    )
    bom_total = sum((Decimal(str(row["net_cost_huf"])) for row in bom), Decimal("0"))
    validations: list[dict[str, Any]] = [
        {
            "key": "source_integrity",
            "decision": "pass"
            if all(item["sha256"] for item in source["files"].values())
            else "fail",
            "measured": source,
            "note": "Az ármodell, belső költségmodell és normakönyv SHA-256 pillanatképe.",
        },
        {
            "key": "houseplan_binding",
            "decision": "pass",
            "measured": {
                "variant_id": variant.variant_id,
                "variant_sha256": variant.content_sha256,
                "gross_area_m2": str(variant.gross_area_m2),
            },
            "note": "Azonos projekthez tartozó kiválasztott HousePlan-változat.",
        },
        {
            "key": "option_compatibility",
            "decision": "fail" if compatibility else "pass",
            "measured": {"selected": [item["code"] for item in options], "errors": compatibility},
            "note": "Opció- és műszakicsomag-kompatibilitás.",
        },
        {
            "key": "bom_balance",
            "decision": "pass" if bom_total == net_cost else "fail",
            "measured": {"bom_total_huf": str(bom_total), "net_cost_huf": str(net_cost)},
            "note": "A tételes BOM összege egyezik a verziózott nettó önköltséggel.",
        },
        {
            "key": "pricing_integrity",
            "decision": "pass" if net_price > net_cost > 0 else "fail",
            "measured": {"net_cost_huf": str(net_cost), "net_price_huf": str(net_price)},
            "note": "Pozitív, forráshoz kötött nettó költség és ajánlati ár.",
        },
        {
            "key": "margin_policy",
            "decision": "pass" if margin >= MIN_MARGIN else "fail",
            "measured": {"margin": str(margin), "minimum": str(MIN_MARGIN)},
            "note": "Vállalati minimum fedezeti politika.",
        },
        {
            "key": "cashflow_coverage",
            "decision": "pass" if minimum_balance >= 0 else "fail",
            "measured": {"minimum_balance_huf": str(minimum_balance)},
            "note": "A mérföldkő-fizetések kumuláltan fedezik a tervezett költséget.",
        },
        {
            "key": "capacity_commitment",
            "decision": "pass" if capacity["capacity_ok"] else "fail",
            "measured": capacity,
            "note": "A vállalt átadás a rögzített brigád- és heti kapacitásból tartható.",
        },
    ]
    return values, validations


VALIDATION_TO_GATE = {
    "source_integrity": "source",
    "houseplan_binding": "houseplan",
    "option_compatibility": "compatibility",
    "bom_balance": "bom",
    "pricing_integrity": "pricing",
    "margin_policy": "margin",
    "cashflow_coverage": "cashflow",
    "capacity_commitment": "capacity",
}


def _persist_version(
    db: Session,
    case: BuildConfigCase,
    data: dict[str, Any],
    actor: str,
    version_no: int,
) -> BuildConfigVersion:
    hb_case = db.scalar(
        select(HouseBuildCase).where(HouseBuildCase.case_id == case.housebuild_case_id)
    )
    variant = db.scalar(
        select(HouseBuildVariant).where(HouseBuildVariant.variant_id == case.housebuild_variant_id)
    )
    if hb_case is None or variant is None or hb_case.selected_variant_id != variant.variant_id:
        raise ValueError("A kapcsolt HouseBuild-ügy kiválasztott változata nem található.")
    if hb_case.project_id != case.project_id:
        raise ValueError("A HouseBuild és BuildConfig ProjectID nem egyezik.")
    values, validations = _calculation(data, variant)
    version_id = f"BCV-{case.case_id.split('-', 1)[-1]}-{version_no}"
    row = BuildConfigVersion(
        version_id=version_id,
        case_id=case.case_id,
        version_no=version_no,
        status="draft",
        brand=values["brand"],
        technology=values["technology"],
        completion_level=values["completion_level"],
        package_name=values["package_name"],
        gross_area_m2=values["gross_area_m2"],
        currency="HUF",
        vat_rate=values["vat_rate"],
        option_json=_canonical(values["options"]),
        bom_json=_canonical(values["bom"]),
        payment_schedule_json=_canonical(values["payment_schedule"]),
        capacity_json=_canonical(values["capacity"]),
        pricing_snapshot_json=_canonical(values["pricing_snapshot"]),
        source_sha256=values["source_sha256"],
        config_sha256=values["config_sha256"],
        bom_sha256=values["bom_sha256"],
        net_cost_huf=values["net_cost_huf"],
        net_price_huf=values["net_price_huf"],
        vat_huf=values["vat_huf"],
        gross_price_huf=values["gross_price_huf"],
        margin_percent=values["margin_percent"],
        duration_days=values["duration_days"],
        created_by=actor,
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    for validation in validations:
        evidence = _sha(
            {
                "version_id": version_id,
                "key": validation["key"],
                "decision": validation["decision"],
                "measured": validation["measured"],
            }
        )
        db.add(
            BuildConfigValidation(
                validation_id=f"BCVAL-{uuid4().hex[:12].upper()}",
                version_id=version_id,
                validation_key=validation["key"],
                decision=validation["decision"],
                measured_json=_canonical(validation["measured"]),
                note=validation["note"],
                evidence_sha256=evidence,
                checked_by="buildconfig-engine",
                checked_at=utcnow(),
            )
        )
        db.add(
            BuildConfigGate(
                version_id=version_id,
                gate_key=VALIDATION_TO_GATE[validation["key"]],
                decision="approved" if validation["decision"] == "pass" else "rejected",
                evidence_refs_json=_canonical([f"validation://{validation['key']}"]),
                evidence_sha256=evidence,
                note=validation["note"],
                decided_by="buildconfig-engine",
                decided_at=utcnow(),
                updated_at=utcnow(),
            )
        )
    for gate_key in ("technical", "finance"):
        db.add(
            BuildConfigGate(
                version_id=version_id,
                gate_key=gate_key,
                decision="pending",
                evidence_refs_json="[]",
                updated_at=utcnow(),
            )
        )
    case.current_version_id = version_id
    case.status = "calculated"
    case.updated_at = utcnow()
    return row


def create_case(db: Session, data: dict[str, Any], user: object) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in CREATOR_ROLES:
        raise PermissionError("BuildConfig ügy indításához nincs jogosultsága.")
    project_id = str(data.get("project_id") or "").strip()
    title = str(data.get("title") or "").strip()
    housebuild_case_id = str(data.get("housebuild_case_id") or "").strip()
    housebuild_variant_id = str(data.get("housebuild_variant_id") or "").strip()
    if len(project_id) < 3 or len(title) < 3:
        raise ValueError("A ProjectID és a legalább három karakteres megnevezés kötelező.")
    hb_case = db.scalar(select(HouseBuildCase).where(HouseBuildCase.case_id == housebuild_case_id))
    if (
        hb_case is None
        or hb_case.project_id != project_id
        or hb_case.selected_variant_id != housebuild_variant_id
    ):
        raise ValueError("Csak azonos projekt kiválasztott HousePlan-változata konfigurálható.")
    existing = db.scalar(
        select(BuildConfigCase).where(
            BuildConfigCase.project_id == project_id,
            BuildConfigCase.housebuild_variant_id == housebuild_variant_id,
            BuildConfigCase.status.notin_(("rejected", "superseded")),
        )
    )
    if existing is not None:
        raise ValueError(
            f"Ehhez a HousePlan-változathoz már van aktív BuildConfig: {existing.case_id}."
        )
    case_id = f"CFG-{uuid4().hex[:12].upper()}"
    case = BuildConfigCase(
        case_id=case_id,
        project_id=project_id,
        title=title,
        housebuild_case_id=housebuild_case_id,
        housebuild_variant_id=housebuild_variant_id,
        current_version_id="PENDING",
        status="draft",
        created_by=email,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(case)
    db.flush()
    version = _persist_version(db, case, data, email, 1)
    audit(
        db,
        actor=email,
        action="buildconfig.created",
        entity_type="buildconfig_case",
        entity_id=case_id,
        after={
            "project_id": project_id,
            "housebuild_variant_id": housebuild_variant_id,
            "version_id": version.version_id,
            "config_sha256": version.config_sha256,
        },
    )
    db.commit()
    return case_detail(db, case_id)


def create_revision(
    db: Session, case_id: str, data: dict[str, Any], user: object
) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in CREATOR_ROLES:
        raise PermissionError("BuildConfig revízióhoz nincs jogosultsága.")
    case = _case(db, case_id, lock=True)
    if case.status == "review":
        raise ValueError("Ellenőrzés alatt új revízió nem hozható létre.")
    current = _version(db, case.current_version_id, lock=True)
    next_no = current.version_no + 1
    current.status = "superseded"
    row = _persist_version(db, case, data, email, next_no)
    case.approved_by = None
    case.approved_at = None
    case.final_report_document_id = None
    case.rejection_reason = None
    audit(
        db,
        actor=email,
        action="buildconfig.revision_created",
        entity_type="buildconfig_case",
        entity_id=case_id,
        after={"version_id": row.version_id, "version_no": next_no},
    )
    db.commit()
    return case_detail(db, case_id)


def submit_case(db: Session, case_id: str, user: object) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in CREATOR_ROLES:
        raise PermissionError("BuildConfig ellenőrzésre küldéséhez nincs jogosultsága.")
    case = _case(db, case_id, lock=True)
    if case.status != "calculated":
        raise ValueError("Csak kiszámított BuildConfig-verzió küldhető ellenőrzésre.")
    version = _version(db, case.current_version_id, lock=True)
    gates = list(
        db.scalars(select(BuildConfigGate).where(BuildConfigGate.version_id == version.version_id))
    )
    blockers = [
        gate.gate_key
        for gate in gates
        if gate.gate_key in AUTOMATIC_GATES and gate.decision != "approved"
    ]
    if blockers:
        raise ValueError("Automatikus BuildConfig STOP kapu: " + ", ".join(blockers))
    case.status = "review"
    version.status = "submitted"
    version.submitted_at = utcnow()
    audit(
        db,
        actor=email,
        action="buildconfig.submitted",
        entity_type="buildconfig_case",
        entity_id=case_id,
        after={"version_id": version.version_id},
    )
    db.commit()
    return case_detail(db, case_id)


def review_gate(
    db: Session, case_id: str, gate_key: str, data: dict[str, Any], user: object
) -> dict[str, Any]:
    role, email = _identity(user)
    if gate_key not in {"technical", "finance"}:
        raise ValueError("Automatikus BuildConfig-kapu kézzel nem írható felül.")
    allowed = TECHNICAL_REVIEW_ROLES if gate_key == "technical" else FINANCE_REVIEW_ROLES
    if role not in allowed:
        raise PermissionError("Ehhez a BuildConfig-kapuhoz nincs jogosultsága.")
    case = _case(db, case_id, lock=True)
    if case.status != "review":
        raise ValueError("Kapudöntés csak ellenőrzés alatt rögzíthető.")
    version = _version(db, case.current_version_id)
    if version.created_by == email:
        raise ValueError(
            "A négy szem elve miatt a verzió készítője nem reviewzhatja saját munkáját."
        )
    decision = str(data.get("decision") or "").strip()
    note = str(data.get("note") or "").strip()
    evidence_ref = str(data.get("evidence_ref") or "").strip()
    evidence_sha256 = str(data.get("evidence_sha256") or "").strip().lower()
    if decision not in {"approved", "rejected"}:
        raise ValueError("Érvénytelen BuildConfig-kapudöntés.")
    if len(note) < 10 or len(evidence_ref) < 5:
        raise ValueError("Legalább 10 karakteres indoklás és bizonyítékhivatkozás kötelező.")
    if len(evidence_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in evidence_sha256
    ):
        raise ValueError("A kapubizonyíték érvényes SHA-256 értéke kötelező.")
    gate = db.scalar(
        select(BuildConfigGate).where(
            BuildConfigGate.version_id == version.version_id,
            BuildConfigGate.gate_key == gate_key,
        )
    )
    if gate is None:
        raise KeyError(gate_key)
    gate.decision = decision
    gate.evidence_refs_json = _canonical([evidence_ref])
    gate.evidence_sha256 = evidence_sha256
    gate.note = note
    gate.decided_by = email
    gate.decided_at = utcnow()
    gate.updated_at = utcnow()
    audit(
        db,
        actor=email,
        action="buildconfig.gate_reviewed",
        entity_type="buildconfig_gate",
        entity_id=f"{version.version_id}:{gate_key}",
        after={"decision": decision, "evidence_sha256": evidence_sha256},
    )
    db.commit()
    return case_detail(db, case_id)


def _report(
    case: BuildConfigCase,
    version: BuildConfigVersion,
    gates: list[BuildConfigGate],
) -> tuple[Path, str]:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    path = RUNTIME_ROOT / f"BuildConfig-{case.case_id}-{version.version_id}.pdf"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(f"BuildConfig {case.case_id}")
    lines = [
        "IMPERIAL INTELLIGENCE - BuildConfig kiadási jegyzőkönyv",
        f"BuildConfigID: {case.case_id}",
        f"VersionID: {version.version_id}",
        f"ProjectID: {case.project_id}",
        f"HousePlanID: {case.housebuild_variant_id}",
        f"Konfiguráció SHA-256: {version.config_sha256}",
        f"BOM SHA-256: {version.bom_sha256}",
        f"Forrás SHA-256: {version.source_sha256}",
        f"Nettó önköltség: {version.net_cost_huf} HUF",
        f"Nettó ajánlati ár: {version.net_price_huf} HUF + ÁFA",
        f"Fedezet: {version.margin_percent}%",
        f"Tervezett időtartam: {version.duration_days} nap",
        "KAPUK:",
        *[f"- {gate.gate_key}: {gate.decision}; {gate.evidence_sha256 or '-'}" for gate in gates],
    ]
    y = 805
    for line in lines:
        if y < 60:
            pdf.showPage()
            y = 805
        pdf.drawString(34, y, str(line)[:115])
        y -= 20
    pdf.save()
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def release_case(db: Session, case_id: str, note: str, user: object) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in RELEASE_ROLES:
        raise PermissionError("BuildConfig kiadáshoz nincs jogosultsága.")
    if len(note.strip()) < 10:
        raise ValueError("A kiadási indoklás legalább 10 karakter.")
    case = _case(db, case_id, lock=True)
    if case.status != "review":
        raise ValueError("Csak ellenőrzés alatt álló BuildConfig adható ki.")
    version = _version(db, case.current_version_id, lock=True)
    if version.created_by == email or case.created_by == email:
        raise ValueError("A négy szem elve miatt a készítő nem adhatja ki saját konfigurációját.")
    gates = list(
        db.scalars(
            select(BuildConfigGate)
            .where(BuildConfigGate.version_id == version.version_id)
            .order_by(BuildConfigGate.id)
        )
    )
    blockers = [gate.gate_key for gate in gates if gate.decision != "approved"]
    if blockers:
        raise ValueError("Minden BuildConfig-kapu jóváhagyása kötelező: " + ", ".join(blockers))
    reviewers = {gate.decided_by for gate in gates if gate.gate_key in {"technical", "finance"}}
    if None in reviewers or len(reviewers) < 2:
        raise ValueError(
            "A műszaki és pénzügyi kaput két név szerinti ellenőrnek kell jóváhagynia."
        )
    path, report_sha = _report(case, version, gates)
    document_id = f"DOC-BC-{uuid4().hex[:12].upper()}"
    db.add(
        WorkspaceDocument(
            document_id=document_id,
            project_id=case.project_id,
            title=f"BuildConfig kiadás – {case.case_id} / {version.version_id}",
            category="buildconfig_release_report",
            source_system="buildconfig",
            source_url=f"file://{path}",
            mime_type="application/pdf",
            version_label=f"v{version.version_no}",
            approval_status="approved",
            verification_status="sha256_verified",
            confidentiality="internal",
            owner="Műszaki előkészítés és pénzügy",
            extracted_summary=(
                f"{version.version_id}; config={version.config_sha256}; SHA-256={report_sha}"
            ),
            metadata_json=_canonical(
                {
                    "sha256": report_sha,
                    "local_path": str(path),
                    "config_sha256": version.config_sha256,
                    "bom_sha256": version.bom_sha256,
                }
            ),
        )
    )
    case.status = "approved"
    case.approved_by = email
    case.approved_at = utcnow()
    case.final_report_document_id = document_id
    case.rejection_reason = None
    version.status = "approved"
    version.approved_by = email
    version.approved_at = utcnow()
    audit(
        db,
        actor=email,
        action="buildconfig.released",
        entity_type="buildconfig_case",
        entity_id=case_id,
        after={
            "version_id": version.version_id,
            "report_document_id": document_id,
            "report_sha256": report_sha,
            "note": note.strip(),
        },
    )
    from ..schemas import EventIn
    from .integration import ingest_event

    ingest_event(
        db,
        EventIn(
            event_id=f"EVT-BC-{uuid4().hex[:14].upper()}",
            dedupe_key=f"CONFIGURATION_APPROVED:{case_id}:{version.version_id}",
            project_id=case.project_id,
            source_module="buildconfig",
            event_type="CONFIGURATION_APPROVED",
            object_type="BuildConfigVersion",
            object_id=version.version_id,
            status="approved",
            responsible="Műszaki előkészítés és pénzügy",
            next_action=(
                "A jóváhagyott ár- és műszaki verzió alkalmazása az ajánlatban és szerződésben."
            ),
            evidence_url=f"document://{document_id}",
            financial_impact_huf=version.net_price_huf,
            payload={
                "summary": f"BuildConfig {case_id} / {version.version_id}",
                "buildconfig_case_id": case_id,
                "version_id": version.version_id,
                "housebuild_case_id": case.housebuild_case_id,
                "housebuild_variant_id": case.housebuild_variant_id,
                "config_sha256": version.config_sha256,
                "bom_sha256": version.bom_sha256,
                "source_sha256": version.source_sha256,
                "net_price_huf": str(version.net_price_huf),
                "report_sha256": report_sha,
            },
            route_to=[
                "housebuild-agent",
                "sales",
                "reservation-engine",
                "contract-generator",
                "financial-control",
                "finance-intelligence",
                "procurement",
                "project-control",
                "crm",
                "my-imperial",
            ],
        ),
        actor=email,
    )
    return case_detail(db, case_id)


def reject_case(db: Session, case_id: str, reason: str, user: object) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in RELEASE_ROLES:
        raise PermissionError("BuildConfig elutasításhoz nincs jogosultsága.")
    if len(reason.strip()) < 10:
        raise ValueError("Az elutasítás indoklása legalább 10 karakter.")
    case = _case(db, case_id, lock=True)
    if case.status != "review":
        raise ValueError("Csak ellenőrzés alatt álló BuildConfig utasítható el.")
    version = _version(db, case.current_version_id, lock=True)
    case.status = "rejected"
    case.rejection_reason = reason.strip()
    version.status = "rejected"
    audit(
        db,
        actor=email,
        action="buildconfig.rejected",
        entity_type="buildconfig_case",
        entity_id=case_id,
        after={"reason": reason.strip(), "version_id": version.version_id},
    )
    db.commit()
    return case_detail(db, case_id)


def _version_payload(
    version: BuildConfigVersion,
    validations: list[BuildConfigValidation],
    gates: list[BuildConfigGate],
) -> dict[str, Any]:
    return {
        "version_id": version.version_id,
        "version_no": version.version_no,
        "status": version.status,
        "brand": version.brand,
        "technology": version.technology,
        "completion_level": version.completion_level,
        "package": version.package_name,
        "gross_area_m2": float(version.gross_area_m2),
        "currency": version.currency,
        "vat_rate": float(version.vat_rate),
        "options": _loads(version.option_json, []),
        "bom": _loads(version.bom_json, []),
        "payment_schedule": _loads(version.payment_schedule_json, []),
        "capacity": _loads(version.capacity_json, {}),
        "pricing_snapshot": _loads(version.pricing_snapshot_json, {}),
        "source_sha256": version.source_sha256,
        "config_sha256": version.config_sha256,
        "bom_sha256": version.bom_sha256,
        "net_cost_huf": float(version.net_cost_huf),
        "net_price_huf": float(version.net_price_huf),
        "vat_huf": float(version.vat_huf),
        "gross_price_huf": float(version.gross_price_huf),
        "margin_percent": float(version.margin_percent),
        "duration_days": version.duration_days,
        "created_by": version.created_by,
        "approved_by": version.approved_by,
        "validations": [
            {
                "validation_key": row.validation_key,
                "decision": row.decision,
                "measured": _loads(row.measured_json, {}),
                "note": row.note,
                "evidence_sha256": row.evidence_sha256,
                "checked_by": row.checked_by,
            }
            for row in validations
        ],
        "gates": [
            {
                "gate_key": row.gate_key,
                "decision": row.decision,
                "evidence_refs": _loads(row.evidence_refs_json, []),
                "evidence_sha256": row.evidence_sha256,
                "note": row.note,
                "decided_by": row.decided_by,
            }
            for row in gates
        ],
    }


def case_detail(db: Session, case_id: str) -> dict[str, Any]:
    case = _case(db, case_id)
    versions = list(
        db.scalars(
            select(BuildConfigVersion)
            .where(BuildConfigVersion.case_id == case_id)
            .order_by(BuildConfigVersion.version_no.desc())
        )
    )
    version_ids = [row.version_id for row in versions]
    validations = list(
        db.scalars(
            select(BuildConfigValidation)
            .where(BuildConfigValidation.version_id.in_(version_ids))
            .order_by(BuildConfigValidation.id)
        )
    )
    gates = list(
        db.scalars(
            select(BuildConfigGate)
            .where(BuildConfigGate.version_id.in_(version_ids))
            .order_by(BuildConfigGate.id)
        )
    )
    by_validation: dict[str, list[BuildConfigValidation]] = {}
    by_gate: dict[str, list[BuildConfigGate]] = {}
    for validation_row in validations:
        by_validation.setdefault(validation_row.version_id, []).append(validation_row)
    for gate_row in gates:
        by_gate.setdefault(gate_row.version_id, []).append(gate_row)
    return {
        "case_id": case.case_id,
        "project_id": case.project_id,
        "title": case.title,
        "housebuild_case_id": case.housebuild_case_id,
        "housebuild_variant_id": case.housebuild_variant_id,
        "current_version_id": case.current_version_id,
        "status": case.status,
        "created_by": case.created_by,
        "approved_by": case.approved_by,
        "final_report_document_id": case.final_report_document_id,
        "rejection_reason": case.rejection_reason,
        "versions": [
            _version_payload(
                row,
                by_validation.get(row.version_id, []),
                by_gate.get(row.version_id, []),
            )
            for row in versions
        ],
    }


def list_cases(db: Session, project_id: str | None = None) -> list[dict[str, Any]]:
    stmt = select(BuildConfigCase).order_by(BuildConfigCase.updated_at.desc())
    if project_id:
        stmt = stmt.where(BuildConfigCase.project_id == project_id)
    return [case_detail(db, row.case_id) for row in db.scalars(stmt)]


def compare_versions(
    db: Session,
    case_id: str,
    *,
    left_version_id: str | None = None,
    right_version_id: str | None = None,
) -> dict[str, Any]:
    detail = case_detail(db, case_id)
    versions = detail["versions"]
    if not versions:
        raise ValueError("A BuildConfig ügynek nincs összehasonlítható verziója.")
    by_id = {item["version_id"]: item for item in versions}
    right = by_id.get(right_version_id) if right_version_id else versions[0]
    left = by_id.get(left_version_id) if left_version_id else (versions[1] if len(versions) > 1 else versions[0])
    if left is None or right is None:
        raise KeyError(left_version_id or right_version_id or "")

    left_options = {item["code"]: item for item in left["options"]}
    right_options = {item["code"]: item for item in right["options"]}
    left_bom = {item["line_id"]: item for item in left["bom"]}
    right_bom = {item["line_id"]: item for item in right["bom"]}
    bom_rows = []
    for line_id in sorted(set(left_bom) | set(right_bom)):
        old = left_bom.get(line_id)
        new = right_bom.get(line_id)
        old_cost = int(old["net_cost_huf"]) if old else 0
        new_cost = int(new["net_cost_huf"]) if new else 0
        bom_rows.append(
            {
                "line_id": line_id,
                "name": (new or old or {}).get("name", line_id),
                "change": "added" if old is None else "removed" if new is None else "changed" if old_cost != new_cost else "unchanged",
                "left_cost_huf": old_cost,
                "right_cost_huf": new_cost,
                "delta_huf": new_cost - old_cost,
            }
        )

    left_validations = {item["validation_key"]: item for item in left["validations"]}
    right_validations = {item["validation_key"]: item for item in right["validations"]}
    validation_rows = [
        {
            "key": key,
            "left": left_validations.get(key, {}).get("decision", "missing"),
            "right": right_validations.get(key, {}).get("decision", "missing"),
        }
        for key in sorted(set(left_validations) | set(right_validations))
    ]
    left_gates = {item["gate_key"]: item for item in left["gates"]}
    right_gates = {item["gate_key"]: item for item in right["gates"]}
    gate_rows = [
        {
            "key": key,
            "left": left_gates.get(key, {}).get("decision", "missing"),
            "right": right_gates.get(key, {}).get("decision", "missing"),
        }
        for key in sorted(set(left_gates) | set(right_gates))
    ]
    return {
        "case": detail,
        "versions": versions,
        "left": left,
        "right": right,
        "same_version": left["version_id"] == right["version_id"],
        "deltas": {
            "net_price_huf": right["net_price_huf"] - left["net_price_huf"],
            "gross_price_huf": right["gross_price_huf"] - left["gross_price_huf"],
            "net_cost_huf": right["net_cost_huf"] - left["net_cost_huf"],
            "margin_percent": right["margin_percent"] - left["margin_percent"],
            "duration_days": right["duration_days"] - left["duration_days"],
        },
        "added_options": [right_options[key] for key in sorted(set(right_options) - set(left_options))],
        "removed_options": [left_options[key] for key in sorted(set(left_options) - set(right_options))],
        "bom_rows": bom_rows,
        "validation_rows": validation_rows,
        "gate_rows": gate_rows,
    }


def report_path(db: Session, document_id: str) -> Path:
    document = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.document_id == document_id,
            WorkspaceDocument.source_system == "buildconfig",
        )
    )
    if document is None:
        raise KeyError(document_id)
    metadata = _loads(document.metadata_json, {})
    path = Path(str(metadata.get("local_path") or ""))
    expected = str(metadata.get("sha256") or "")
    if not path.is_file() or len(expected) != 64 or _file_sha(path) != expected:
        raise ValueError("A BuildConfig-jelentés hiányzik vagy a SHA-256 ellenőrzése sikertelen.")
    return path
