from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
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
    HouseBuildCase,
    HouseBuildGate,
    HouseBuildValidation,
    HouseBuildVariant,
    PlanCheckCase,
    PlotCheckCase,
    TechnicalCase,
    WorkspaceDocument,
)
from .house_catalog import released_house

CREATOR_ROLES = {"owner", "managing-director", "platform-admin", "technical-prep", "designer"}
REVIEWER_ROLES = {"owner", "managing-director", "platform-admin", "technical-prep", "designer"}
RELEASE_ROLES = {"owner", "managing-director", "platform-admin", "technical-prep"}
GATE_KEYS = (
    "source_rights",
    "program",
    "deduplication",
    "topology",
    "plotcheck",
    "buildconfig",
    "plancheck",
    "technical",
)
AUTOMATIC_GATES = {"source_rights", "program", "deduplication", "topology"}
RUNTIME_ROOT = Path(os.getenv("PLATFORM_RUNTIME_ROOT", "/app/runtime")) / "housebuild"


def utcnow() -> datetime:
    return datetime.now(UTC)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


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


def _identity(user: object) -> tuple[str, str]:
    role = str(getattr(user, "role", ""))
    email = str(getattr(user, "email", "")).strip().lower()
    return role, email


def _case(db: Session, case_id: str, *, lock: bool = False) -> HouseBuildCase:
    stmt = select(HouseBuildCase).where(HouseBuildCase.case_id == case_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise KeyError(case_id)
    return row


def _variant(db: Session, variant_id: str) -> HouseBuildVariant:
    row = db.scalar(select(HouseBuildVariant).where(HouseBuildVariant.variant_id == variant_id))
    if row is None:
        raise KeyError(variant_id)
    return row


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def _room_program(
    net_area: Decimal, bedrooms: int, bathrooms: int, accessibility: bool
) -> tuple[list[dict[str, Any]], list[list[str]]]:
    fixed = [
        ("R-ENTRY", "Előtér", Decimal("4.5")),
        ("R-UTILITY", "Háztartási helyiség", Decimal("4.0")),
        ("R-MECH", "Gépészeti helyiség", Decimal("3.5")),
        ("R-CIRC", "Közlekedő", max(Decimal("6"), net_area * Decimal("0.075"))),
    ]
    if accessibility:
        fixed.append(("R-ACCESS", "Akadálymentes forduló- és közlekedőtér", Decimal("4")))
    rooms: list[dict[str, Any]] = [
        {"room_id": room_id, "name": name, "type": "support", "area_m2": float(_q(area))}
        for room_id, name, area in fixed
    ]
    allocated = sum((area for _, _, area in fixed), Decimal("0"))
    for index in range(bedrooms):
        area = Decimal("12") if index == 0 else Decimal("9.5")
        rooms.append(
            {
                "room_id": f"R-BED-{index + 1}",
                "name": f"Hálószoba {index + 1}",
                "type": "bedroom",
                "area_m2": float(area),
            }
        )
        allocated += area
    for index in range(bathrooms):
        area = Decimal("5.5") if index == 0 else Decimal("3.5")
        rooms.append(
            {
                "room_id": f"R-BATH-{index + 1}",
                "name": f"Fürdő {index + 1}",
                "type": "bathroom",
                "area_m2": float(area),
            }
        )
        allocated += area
    living = net_area - allocated
    if living < Decimal("18"):
        scale = net_area / (allocated + Decimal("18"))
        for room in rooms:
            room["area_m2"] = float(_q(Decimal(str(room["area_m2"])) * scale))
        living = _q(Decimal("18") * scale)
        allocated = sum((Decimal(str(room["area_m2"])) for room in rooms), Decimal("0"))
        living = net_area - allocated
    rooms.append(
        {
            "room_id": "R-LIVING",
            "name": "Nappali–étkező–konyha",
            "type": "living",
            "area_m2": float(_q(living)),
        }
    )
    adjacency = [
        ["R-ENTRY", "R-CIRC"],
        ["R-CIRC", "R-LIVING"],
        ["R-CIRC", "R-UTILITY"],
        ["R-UTILITY", "R-MECH"],
    ]
    adjacency.extend([["R-CIRC", f"R-BED-{index + 1}"] for index in range(bedrooms)])
    adjacency.extend([["R-CIRC", f"R-BATH-{index + 1}"] for index in range(bathrooms)])
    if accessibility:
        adjacency.append(["R-CIRC", "R-ACCESS"])
    return rooms, adjacency


def _topology_ok(rooms: list[dict[str, Any]], adjacency: list[list[str]]) -> bool:
    nodes = {str(room["room_id"]) for room in rooms}
    if not nodes or "R-ENTRY" not in nodes or "R-LIVING" not in nodes:
        return False
    graph: dict[str, set[str]] = {node: set() for node in nodes}
    for left, right in adjacency:
        if left not in nodes or right not in nodes:
            return False
        graph[left].add(right)
        graph[right].add(left)
    visited = set()
    stack = ["R-ENTRY"]
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        stack.extend(graph[node] - visited)
    return visited == nodes


def _variant_data(
    case_id: str,
    variant_no: int,
    label: str,
    strategy: str,
    area: Decimal,
    source_area: Decimal,
    source_price: Decimal,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    floors = int(requirements["floors"])
    bedrooms = int(requirements["bedrooms"])
    bathrooms = int(requirements["bathrooms"])
    if variant_no == 3 and bedrooms > 1:
        bedrooms -= 1
    efficiency = Decimal("0.82") if floors == 1 else Decimal("0.80")
    net_area = _q(area * efficiency)
    rooms, adjacency = _room_program(
        net_area, bedrooms, bathrooms, bool(requirements["accessibility"])
    )
    footprint = _q(area / Decimal(floors))
    base_aspect = Decimal("1.30") if requirements["roof_style"] == "lapostető" else Decimal("1.45")
    aspect = base_aspect + {1: Decimal("0"), 2: Decimal("-0.10"), 3: Decimal("-0.20")}[variant_no]
    width = _q((footprint / aspect).sqrt())
    depth = _q(footprint / width)
    geometry = {
        "type": "rectilinear-envelope",
        "width_m": str(width),
        "depth_m": str(depth),
        "floors": floors,
        "roof_style": requirements["roof_style"],
        "orientation": requirements["orientation"],
    }
    geometry_signature = _sha({"geometry": geometry, "rooms": rooms, "adjacency": adjacency})
    ratio = area / source_area if source_area else Decimal("1")
    price = (source_price * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    payload = {
        "variant_id": f"HBV-{case_id.split('-', 1)[-1]}-{variant_no}",
        "variant_no": variant_no,
        "label": label,
        "strategy": strategy,
        "gross_area_m2": str(_q(area)),
        "net_area_m2": str(net_area),
        "footprint_m2": str(footprint),
        "width_m": str(width),
        "depth_m": str(depth),
        "floors": floors,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "garage_spaces": requirements["garage_spaces"],
        "roof_style": requirements["roof_style"],
        "facade_style": requirements["facade_style"],
        "orientation": requirements["orientation"],
        "accessibility": requirements["accessibility"],
        "estimated_catalog_price_huf": str(price),
        "rooms": rooms,
        "adjacency": adjacency,
        "geometry": geometry,
        "geometry_signature": geometry_signature,
    }
    payload["content_sha256"] = _sha(payload)
    return payload


def _add_validation(
    db: Session, variant_id: str, key: str, decision: str, measured: dict[str, Any], note: str
) -> None:
    evidence_sha = _sha(
        {
            "variant_id": variant_id,
            "key": key,
            "decision": decision,
            "measured": measured,
            "note": note,
        }
    )
    db.add(
        HouseBuildValidation(
            validation_id=f"HBVAL-{uuid4().hex[:12].upper()}",
            variant_id=variant_id,
            validation_key=key,
            decision=decision,
            measured_json=_canonical(measured),
            note=note,
            evidence_sha256=evidence_sha,
            checked_by="housebuild-engine",
        )
    )


def _automatic_gate(
    db: Session, case_id: str, key: str, decision: str, refs: list[str], note: str
) -> None:
    db.add(
        HouseBuildGate(
            case_id=case_id,
            gate_key=key,
            decision=decision,
            evidence_refs_json=_canonical(refs),
            evidence_sha256=_sha({"refs": refs, "note": note}),
            note=note,
            decided_by="housebuild-engine",
            decided_at=utcnow(),
        )
    )


def create_case(db: Session, data: dict[str, Any], user: object) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in CREATOR_ROLES:
        raise PermissionError("HouseBuild ügy létrehozásához nincs jogosultsága.")
    required = (
        "project_id",
        "title",
        "source_house_id",
        "rights_evidence_ref",
        "rights_evidence_sha256",
    )
    missing = [key for key in required if not str(data.get(key) or "").strip()]
    if missing:
        raise ValueError("Hiányzó HouseBuild alapadatok: " + ", ".join(missing))
    rights_sha = str(data["rights_evidence_sha256"]).strip().lower()
    if len(rights_sha) != 64 or any(char not in "0123456789abcdef" for char in rights_sha):
        raise ValueError("A felhasználási jog bizonyítékához érvényes SHA-256 szükséges.")
    source = released_house(db, str(data["source_house_id"]).strip())
    if source is None or not source.get("content_sha256"):
        raise ValueError("Csak aktív, kiadott és hash-azonos házkatalógus-verzió használható.")
    desired_area = _decimal(data.get("desired_area_m2"), "cél alapterület", "45", "500")
    requirements: dict[str, Any] = {
        "desired_area_m2": str(desired_area),
        "bedrooms": _integer(data.get("bedrooms"), "hálószobák száma", 1, 10),
        "bathrooms": _integer(data.get("bathrooms"), "fürdőszobák száma", 1, 5),
        "floors": _integer(data.get("floors"), "szintek száma", 1, 3),
        "garage_spaces": _integer(data.get("garage_spaces") or 0, "garázshelyek száma", 0, 3),
        "technology": str(data.get("technology") or "").strip(),
        "roof_style": str(data.get("roof_style") or "nyeregtető").strip(),
        "facade_style": str(data.get("facade_style") or "kortárs").strip(),
        "orientation": str(data.get("orientation") or "délkelet").strip(),
        "accessibility": data.get("accessibility") is True
        or str(data.get("accessibility") or "").lower() in {"1", "true", "yes", "on"},
        "customization_notes": str(data.get("customization_notes") or "").strip(),
    }
    if len(requirements["technology"]) < 3:
        raise ValueError("A jóváhagyandó építési technológiát meg kell adni.")
    case_id = f"HB-{uuid4().hex[:12].upper()}"
    source_snapshot = {
        "house_id": source["house_id"],
        "catalog_version_id": source["catalog_version_id"],
        "catalog_version": source["catalog_version"],
        "brand": source["brand"],
        "name": source["name"],
        "gross_area_m2": source["gross_area_m2"],
        "catalog_price_huf": source["catalog_price_huf"],
        "source_url": source["source_url"],
        "source_verified_at": source["verified_at"],
        "catalog_content_sha256": source["content_sha256"],
    }
    source_sha = _sha(source_snapshot)
    requirement_sha = _sha(requirements)
    case = HouseBuildCase(
        case_id=case_id,
        project_id=str(data["project_id"]).strip(),
        title=str(data["title"]).strip(),
        source_house_id=source["house_id"],
        source_catalog_version_id=source["catalog_version_id"],
        source_snapshot_json=_canonical(source_snapshot),
        source_sha256=source_sha,
        rights_evidence_ref=str(data["rights_evidence_ref"]).strip(),
        rights_evidence_sha256=rights_sha,
        requirement_json=_canonical(requirements),
        requirement_sha256=requirement_sha,
        created_by=email,
    )
    db.add(case)
    db.flush()
    source_area = Decimal(str(source["gross_area_m2"]))
    source_price = Decimal(str(source["catalog_price_huf"]))
    areas = [source_area, desired_area, max(Decimal("45"), desired_area * Decimal("0.92"))]
    labels = [
        "Katalógushű változat",
        "Célprogramra hangolt változat",
        "Kompakt költségoptimalizált változat",
    ]
    strategies = [
        "A kiadott katalógusgeometriát és bruttó alapterületet tartja elsődlegesnek.",
        "A jóváhagyandó célprogramot és alapterületet követi.",
        "Kisebb közlekedő- és hálóterülettel csökkenti a beruházási becslést.",
    ]
    for index, (area, label, strategy) in enumerate(
        zip(areas, labels, strategies, strict=True), start=1
    ):
        payload = _variant_data(
            case_id, index, label, strategy, area, source_area, source_price, requirements
        )
        row = HouseBuildVariant(
            variant_id=payload["variant_id"],
            case_id=case_id,
            variant_no=index,
            label=label,
            strategy=strategy,
            gross_area_m2=Decimal(payload["gross_area_m2"]),
            net_area_m2=Decimal(payload["net_area_m2"]),
            footprint_m2=Decimal(payload["footprint_m2"]),
            width_m=Decimal(payload["width_m"]),
            depth_m=Decimal(payload["depth_m"]),
            floors=payload["floors"],
            bedrooms=payload["bedrooms"],
            bathrooms=payload["bathrooms"],
            garage_spaces=payload["garage_spaces"],
            roof_style=payload["roof_style"],
            facade_style=payload["facade_style"],
            orientation=payload["orientation"],
            accessibility=payload["accessibility"],
            estimated_catalog_price_huf=Decimal(payload["estimated_catalog_price_huf"]),
            rooms_json=_canonical(payload["rooms"]),
            adjacency_json=_canonical(payload["adjacency"]),
            geometry_json=_canonical(payload["geometry"]),
            geometry_signature=payload["geometry_signature"],
            content_sha256=payload["content_sha256"],
        )
        db.add(row)
        db.flush()
        room_sum = sum((Decimal(str(room["area_m2"])) for room in payload["rooms"]), Decimal("0"))
        area_ok = abs(room_sum - row.net_area_m2) <= Decimal("0.01")
        topology_ok = _topology_ok(payload["rooms"], payload["adjacency"])
        dimensions_ok = (
            row.width_m >= Decimal("5")
            and row.depth_m >= Decimal("5")
            and row.footprint_m2 <= row.gross_area_m2
        )
        program_ok = all(
            Decimal(str(room["area_m2"]))
            >= (
                {"bedroom": Decimal("8"), "bathroom": Decimal("3"), "living": Decimal("18")}.get(
                    room["type"], Decimal("2")
                )
            )
            for room in payload["rooms"]
        )
        _add_validation(
            db,
            row.variant_id,
            "area_consistency",
            "pass" if area_ok else "fail",
            {"room_sum_m2": str(room_sum), "net_area_m2": str(row.net_area_m2)},
            "A helyiségterületek összege a nettó területhez egyeztetve.",
        )
        _add_validation(
            db,
            row.variant_id,
            "dimensional_envelope",
            "pass" if dimensions_ok else "fail",
            {
                "width_m": str(row.width_m),
                "depth_m": str(row.depth_m),
                "footprint_m2": str(row.footprint_m2),
            },
            "Építhető, pozitív befoglaló geometria ellenőrzése.",
        )
        _add_validation(
            db,
            row.variant_id,
            "program_compliance",
            "pass" if program_ok else "fail",
            {
                "requested_bedrooms": requirements["bedrooms"],
                "generated_bedrooms": payload["bedrooms"],
                "minimum_net_area_m2": str(
                    Decimal("30")
                    + Decimal(payload["bedrooms"]) * Decimal("8")
                    + Decimal(payload["bathrooms"]) * Decimal("3.5")
                ),
                "actual_net_area_m2": str(row.net_area_m2),
            },
            "A helyiségek használhatósági minimumainak ellenőrzése.",
        )
        _add_validation(
            db,
            row.variant_id,
            "room_topology",
            "pass" if topology_ok else "fail",
            {"room_count": len(payload["rooms"]), "edge_count": len(payload["adjacency"])},
            "Minden helyiség az előtérből elérhető gráfban szerepel.",
        )
        _add_validation(
            db,
            row.variant_id,
            "catalog_fidelity",
            "warning"
            if abs(row.gross_area_m2 - source_area) / source_area > Decimal("0.20")
            else "pass",
            {"source_area_m2": str(source_area), "variant_area_m2": str(row.gross_area_m2)},
            "A forráskatalógushoz viszonyított területeltérés rögzítve.",
        )
    _automatic_gate(
        db,
        case_id,
        "source_rights",
        "approved",
        [source["catalog_version_id"], str(data["rights_evidence_ref"]).strip()],
        "A kiadott katalógusverzió és a SHA-256 azonosított jogbizonyíték rendelkezésre áll.",
    )
    for key, note in (
        ("program", "A kiválasztott változat helyiségprogram-ellenőrzésére vár."),
        (
            "deduplication",
            "A kiválasztott változat vállalati geometry signature ellenőrzésére vár.",
        ),
        ("topology", "A kiválasztott változat helyiségkapcsolati gráfjának ellenőrzésére vár."),
    ):
        db.add(HouseBuildGate(case_id=case_id, gate_key=key, decision="pending", note=note))
    for key in GATE_KEYS:
        if key not in AUTOMATIC_GATES:
            db.add(HouseBuildGate(case_id=case_id, gate_key=key))
    audit(
        db,
        actor=email,
        action="housebuild.created",
        entity_type="housebuild_case",
        entity_id=case_id,
        after={
            "project_id": case.project_id,
            "source_house_id": source["house_id"],
            "source_sha256": source_sha,
            "requirement_sha256": requirement_sha,
        },
    )
    db.commit()
    return case_detail(db, case_id)


def select_variant(db: Session, case_id: str, variant_id: str, user: object) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in CREATOR_ROLES:
        raise PermissionError("HouseBuild változatválasztáshoz nincs jogosultsága.")
    case = _case(db, case_id, lock=True)
    if case.status not in {"intake", "variant_selected"}:
        raise ValueError("Változat csak ellenőrzésre küldés előtt választható.")
    selected = _variant(db, variant_id)
    if selected.case_id != case_id:
        raise ValueError("A kiválasztott változat nem ehhez a HouseBuild ügyhöz tartozik.")
    for row in db.scalars(select(HouseBuildVariant).where(HouseBuildVariant.case_id == case_id)):
        row.status = "selected" if row.variant_id == variant_id else "generated"
    validations = list(
        db.scalars(
            select(HouseBuildValidation).where(HouseBuildValidation.variant_id == variant_id)
        )
    )
    by_key = {row.validation_key: row for row in validations}
    program_pass = all(
        by_key.get(key) is not None and by_key[key].decision == "pass"
        for key in ("area_consistency", "dimensional_envelope", "program_compliance")
    )
    topology_pass = (
        by_key.get("room_topology") is not None and by_key["room_topology"].decision == "pass"
    )
    duplicates = list(
        db.scalars(
            select(HouseBuildVariant.variant_id).where(
                HouseBuildVariant.geometry_signature == selected.geometry_signature,
                HouseBuildVariant.case_id != case_id,
            )
        )
    )
    decisions = {
        "program": (
            "approved" if program_pass else "rejected",
            [
                by_key[key].validation_id
                for key in ("area_consistency", "dimensional_envelope", "program_compliance")
                if by_key.get(key)
            ],
            "A kiválasztott változat program- és méretvalidációja.",
        ),
        "topology": (
            "approved" if topology_pass else "rejected",
            [by_key["room_topology"].validation_id] if by_key.get("room_topology") else [],
            "A kiválasztott változat helyiségtopológiai validációja.",
        ),
        "deduplication": (
            "rejected" if duplicates else "approved",
            duplicates or ["NO_MATCH"],
            "A kiválasztott geometry signature vállalati duplikációs ellenőrzése.",
        ),
    }
    for key, (decision, refs, note) in decisions.items():
        gate = db.scalar(
            select(HouseBuildGate).where(
                HouseBuildGate.case_id == case_id, HouseBuildGate.gate_key == key
            )
        )
        if gate is None:
            raise KeyError(f"{case_id}/{key}")
        gate.decision = decision
        gate.evidence_refs_json = _canonical(refs)
        gate.evidence_sha256 = _sha({"variant_id": variant_id, "refs": refs, "note": note})
        gate.note = note
        gate.decided_by = "housebuild-engine"
        gate.decided_at = utcnow()
    case.selected_variant_id = variant_id
    case.status = "variant_selected"
    case.current_revision += 1
    audit(
        db,
        actor=email,
        action="housebuild.variant_selected",
        entity_type="housebuild_case",
        entity_id=case_id,
        after={"variant_id": variant_id, "revision": case.current_revision},
    )
    db.commit()
    return case_detail(db, case_id)


def submit_case(db: Session, case_id: str, user: object) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in CREATOR_ROLES:
        raise PermissionError("HouseBuild ügy beküldéséhez nincs jogosultsága.")
    case = _case(db, case_id, lock=True)
    if case.status != "variant_selected" or not case.selected_variant_id:
        raise ValueError("Ellenőrzés előtt kötelező kiválasztani egy HousePlan-változatot.")
    auto = list(
        db.scalars(
            select(HouseBuildGate).where(
                HouseBuildGate.case_id == case_id, HouseBuildGate.gate_key.in_(AUTOMATIC_GATES)
            )
        )
    )
    blockers = [row.gate_key for row in auto if row.decision != "approved"]
    if blockers:
        raise ValueError("Automatikus HouseBuild STOP kapu: " + ", ".join(blockers))
    case.status = "review"
    audit(
        db,
        actor=email,
        action="housebuild.submitted",
        entity_type="housebuild_case",
        entity_id=case_id,
    )
    db.commit()
    return case_detail(db, case_id)


def _validate_dependency(db: Session, case: HouseBuildCase, gate_key: str, reference: str) -> None:
    if gate_key == "plotcheck":
        plotcheck_case = db.scalar(select(PlotCheckCase).where(PlotCheckCase.case_id == reference))
        if (
            plotcheck_case is None
            or plotcheck_case.project_id != case.project_id
            or plotcheck_case.status not in {"fit", "fit_with_conditions"}
        ):
            raise ValueError(
                "Csak azonos projekthez tartozó FIT vagy FIT WITH CONDITIONS PlotCheck kapcsolható."
            )
        case.plotcheck_case_id = reference
    elif gate_key == "buildconfig":
        canonical = db.scalar(select(BuildConfigCase).where(BuildConfigCase.case_id == reference))
        if canonical is not None:
            if canonical.project_id != case.project_id or canonical.status != "approved":
                raise ValueError(
                    "Csak azonos projekthez tartozó, jóváhagyott BuildConfig kapcsolható."
                )
            case.buildconfig_case_id = reference
            return
        legacy = db.scalar(
            select(TechnicalCase).where(
                TechnicalCase.case_id == reference, TechnicalCase.module_key == "buildconfig"
            )
        )
        if legacy is None or legacy.project_id != case.project_id or legacy.status != "approved":
            raise ValueError("Csak azonos projekthez tartozó, jóváhagyott BuildConfig kapcsolható.")
        case.buildconfig_case_id = reference
    elif gate_key == "plancheck":
        plancheck_case = db.scalar(select(PlanCheckCase).where(PlanCheckCase.case_id == reference))
        if plancheck_case is None or plancheck_case.project_id != case.project_id or plancheck_case.status != "sendable":
            raise ValueError("Csak azonos projekthez tartozó, SENDABLE PlanCheck kapcsolható.")
        case.plancheck_case_id = reference


def review_gate(
    db: Session, case_id: str, gate_key: str, data: dict[str, Any], user: object
) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in REVIEWER_ROLES:
        raise PermissionError("HouseBuild kapudöntéshez nincs jogosultsága.")
    if gate_key in AUTOMATIC_GATES:
        raise ValueError("Az automatikus HouseBuild kapu kézzel nem írható felül.")
    if gate_key not in GATE_KEYS:
        raise KeyError(gate_key)
    case = _case(db, case_id, lock=True)
    if case.status != "review":
        raise ValueError("Kapudöntés csak ellenőrzés alatt álló HouseBuild ügyön rögzíthető.")
    decision = str(data.get("decision") or "").strip().lower()
    note = str(data.get("note") or "").strip()
    refs = [str(item).strip() for item in data.get("evidence_refs", []) if str(item).strip()]
    digest = str(data.get("evidence_sha256") or "").strip().lower()
    if decision not in {"approved", "rejected"} or len(note) < 10 or not refs:
        raise ValueError(
            "Döntés, legalább 10 karakteres indoklás és bizonyítékhivatkozás kötelező."
        )
    if decision == "approved" and email == case.created_by:
        raise ValueError(
            "A négy szem elve miatt a létrehozó nem hagyhatja jóvá a saját HouseBuild kapuját."
        )
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("A kapubizonyíték érvényes SHA-256 értéke kötelező.")
    if decision == "approved" and gate_key in {"plotcheck", "buildconfig", "plancheck"}:
        _validate_dependency(db, case, gate_key, refs[0])
    gate = db.scalar(
        select(HouseBuildGate).where(
            HouseBuildGate.case_id == case_id, HouseBuildGate.gate_key == gate_key
        )
    )
    if gate is None:
        raise KeyError(gate_key)
    gate.decision = decision
    gate.note = note
    gate.evidence_refs_json = _canonical(refs)
    gate.evidence_sha256 = digest
    gate.decided_by = email
    gate.decided_at = utcnow()
    case.current_revision += 1
    audit(
        db,
        actor=email,
        action="housebuild.gate_reviewed",
        entity_type="housebuild_gate",
        entity_id=f"{case_id}:{gate_key}",
        after={"decision": decision, "refs": refs, "sha256": digest},
    )
    db.commit()
    return case_detail(db, case_id)


def _report(
    case: HouseBuildCase,
    variant: HouseBuildVariant,
    gates: list[HouseBuildGate],
    validations: list[HouseBuildValidation],
) -> tuple[Path, str]:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    path = RUNTIME_ROOT / f"HouseBuild-{case.case_id}-{variant.variant_id}.pdf"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(f"HouseBuild {case.case_id}")
    lines = [
        "IMPERIAL INTELLIGENCE - HouseBuild kiadási jegyzőkönyv",
        f"HouseBuildID: {case.case_id}",
        f"ProjectID: {case.project_id}",
        f"HousePlanID: {variant.variant_id}",
        f"Forrás: {case.source_catalog_version_id} / SHA-256 {case.source_sha256}",
        f"Követelmény SHA-256: {case.requirement_sha256}",
        f"Geometry signature: {variant.geometry_signature}",
        f"Tartalom SHA-256: {variant.content_sha256}",
        (
            f"Méret: {variant.gross_area_m2} m2 bruttó / {variant.net_area_m2} m2 nettó / "
            f"{variant.width_m} x {variant.depth_m} m"
        ),
        (
            f"Program: {variant.bedrooms} háló / {variant.bathrooms} fürdő / "
            f"{variant.floors} szint / {variant.garage_spaces} garázs"
        ),
        "KAPUK:",
        *[f"- {gate.gate_key}: {gate.decision}; {gate.evidence_sha256 or '-'}" for gate in gates],
        "VALIDÁCIÓK:",
        *[f"- {row.validation_key}: {row.decision}; {row.evidence_sha256}" for row in validations],
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
        raise PermissionError("HouseBuild kiadáshoz nincs jogosultsága.")
    if len(note.strip()) < 10:
        raise ValueError("A kiadási indoklás legalább 10 karakter.")
    case = _case(db, case_id, lock=True)
    if case.status != "review" or not case.selected_variant_id:
        raise ValueError(
            "Csak ellenőrzés alatt álló, kiválasztott változattal rendelkező ügy adható ki."
        )
    if case.created_by == email:
        raise ValueError(
            "A négy szem elve miatt a létrehozó nem adhatja ki a saját HouseBuild ügyét."
        )
    gates = list(
        db.scalars(
            select(HouseBuildGate)
            .where(HouseBuildGate.case_id == case_id)
            .order_by(HouseBuildGate.id)
        )
    )
    blockers = [row.gate_key for row in gates if row.decision != "approved"]
    if blockers:
        raise ValueError("Minden HouseBuild kapu jóváhagyása kötelező: " + ", ".join(blockers))
    variant = _variant(db, case.selected_variant_id)
    validations = list(
        db.scalars(
            select(HouseBuildValidation)
            .where(HouseBuildValidation.variant_id == variant.variant_id)
            .order_by(HouseBuildValidation.id)
        )
    )
    if not validations or any(row.decision == "fail" for row in validations):
        raise ValueError("Sikertelen vagy hiányzó HousePlan-validáció mellett nincs kiadás.")
    path, report_sha = _report(case, variant, gates, validations)
    document_id = f"DOC-HB-{uuid4().hex[:12].upper()}"
    db.add(
        WorkspaceDocument(
            document_id=document_id,
            project_id=case.project_id,
            title=f"HouseBuild kiadás – {case.case_id}",
            category="housebuild_release_report",
            source_system="housebuild-agent",
            source_url=f"file://{path}",
            mime_type="application/pdf",
            version_label=f"r{case.current_revision}",
            approval_status="approved",
            verification_status="sha256_verified",
            confidentiality="internal",
            owner="Műszaki előkészítés",
            extracted_summary=(
                f"{variant.variant_id}; geometry={variant.geometry_signature}; SHA-256={report_sha}"
            ),
            metadata_json=_canonical(
                {
                    "sha256": report_sha,
                    "local_path": str(path),
                    "variant_sha256": variant.content_sha256,
                }
            ),
        )
    )
    case.status = "released"
    case.final_report_document_id = document_id
    case.released_by = email
    case.released_at = utcnow()
    variant.status = "released"
    for other in db.scalars(
        select(HouseBuildVariant).where(
            HouseBuildVariant.case_id == case_id, HouseBuildVariant.variant_id != variant.variant_id
        )
    ):
        other.status = "superseded"
    audit(
        db,
        actor=email,
        action="housebuild.released",
        entity_type="housebuild_case",
        entity_id=case_id,
        after={
            "variant_id": variant.variant_id,
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
            event_id=f"EVT-HB-{uuid4().hex[:14].upper()}",
            dedupe_key=f"HOUSE_PLAN_APPROVED:{case_id}:r{case.current_revision}",
            project_id=case.project_id,
            source_module="housebuild-agent",
            event_type="HOUSE_PLAN_APPROVED",
            object_type="HouseBuildVariant",
            object_id=variant.variant_id,
            status="released",
            responsible="Műszaki előkészítés",
            next_action=(
                "A kiadott HousePlan alkalmazása az ajánlatban, látványban és projektbaseline-ban."
            ),
            evidence_url=f"document://{document_id}",
            financial_impact_huf=variant.estimated_catalog_price_huf,
            payload={
                "summary": f"HouseBuild {case_id}: {variant.label}",
                "housebuild_case_id": case_id,
                "house_plan_id": variant.variant_id,
                "source_house_id": case.source_house_id,
                "geometry_signature": variant.geometry_signature,
                "content_sha256": variant.content_sha256,
                "report_sha256": report_sha,
                "plotcheck_case_id": case.plotcheck_case_id,
                "buildconfig_case_id": case.buildconfig_case_id,
                "plancheck_case_id": case.plancheck_case_id,
            },
            route_to=[
                "house-catalog",
                "housevision",
                "housematch",
                "buildconfig",
                "plancheck",
                "crm",
                "my-imperial",
                "engineering-workspace",
                "contract-generator",
            ],
        ),
        actor=email,
    )
    return case_detail(db, case_id)


def reject_case(db: Session, case_id: str, reason: str, user: object) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in RELEASE_ROLES:
        raise PermissionError("HouseBuild elutasításhoz nincs jogosultsága.")
    if len(reason.strip()) < 10:
        raise ValueError("Az elutasítás indoklása legalább 10 karakter.")
    case = _case(db, case_id, lock=True)
    if case.status != "review":
        raise ValueError("Csak ellenőrzés alatt álló HouseBuild ügy utasítható el.")
    case.status = "rejected"
    case.rejection_reason = reason.strip()
    if case.selected_variant_id:
        _variant(db, case.selected_variant_id).status = "rejected"
    audit(
        db,
        actor=email,
        action="housebuild.rejected",
        entity_type="housebuild_case",
        entity_id=case_id,
        after={"reason": reason.strip()},
    )
    db.commit()
    return case_detail(db, case_id)


def case_detail(db: Session, case_id: str) -> dict[str, Any]:
    case = _case(db, case_id)
    variants = list(
        db.scalars(
            select(HouseBuildVariant)
            .where(HouseBuildVariant.case_id == case_id)
            .order_by(HouseBuildVariant.variant_no)
        )
    )
    variant_ids = [row.variant_id for row in variants]
    validations = (
        list(
            db.scalars(
                select(HouseBuildValidation)
                .where(HouseBuildValidation.variant_id.in_(variant_ids))
                .order_by(HouseBuildValidation.id)
            )
        )
        if variant_ids
        else []
    )
    by_variant: dict[str, list[HouseBuildValidation]] = {}
    for row in validations:
        by_variant.setdefault(row.variant_id, []).append(row)
    gates = list(
        db.scalars(
            select(HouseBuildGate)
            .where(HouseBuildGate.case_id == case_id)
            .order_by(HouseBuildGate.id)
        )
    )
    return {
        "case_id": case.case_id,
        "project_id": case.project_id,
        "title": case.title,
        "status": case.status,
        "source_house_id": case.source_house_id,
        "source_catalog_version_id": case.source_catalog_version_id,
        "source_snapshot": _loads(case.source_snapshot_json, {}),
        "source_sha256": case.source_sha256,
        "rights_evidence_ref": case.rights_evidence_ref,
        "rights_evidence_sha256": case.rights_evidence_sha256,
        "requirements": _loads(case.requirement_json, {}),
        "requirement_sha256": case.requirement_sha256,
        "current_revision": case.current_revision,
        "selected_variant_id": case.selected_variant_id,
        "plotcheck_case_id": case.plotcheck_case_id,
        "buildconfig_case_id": case.buildconfig_case_id,
        "plancheck_case_id": case.plancheck_case_id,
        "final_report_document_id": case.final_report_document_id,
        "created_by": case.created_by,
        "released_by": case.released_by,
        "rejection_reason": case.rejection_reason,
        "variants": [
            {
                "variant_id": row.variant_id,
                "variant_no": row.variant_no,
                "label": row.label,
                "strategy": row.strategy,
                "gross_area_m2": float(row.gross_area_m2),
                "net_area_m2": float(row.net_area_m2),
                "footprint_m2": float(row.footprint_m2),
                "width_m": float(row.width_m),
                "depth_m": float(row.depth_m),
                "floors": row.floors,
                "bedrooms": row.bedrooms,
                "bathrooms": row.bathrooms,
                "garage_spaces": row.garage_spaces,
                "roof_style": row.roof_style,
                "facade_style": row.facade_style,
                "orientation": row.orientation,
                "accessibility": row.accessibility,
                "estimated_catalog_price_huf": float(row.estimated_catalog_price_huf),
                "rooms": _loads(row.rooms_json, []),
                "adjacency": _loads(row.adjacency_json, []),
                "geometry": _loads(row.geometry_json, {}),
                "geometry_signature": row.geometry_signature,
                "content_sha256": row.content_sha256,
                "status": row.status,
                "validations": [
                    {
                        "validation_id": item.validation_id,
                        "validation_key": item.validation_key,
                        "decision": item.decision,
                        "measured": _loads(item.measured_json, {}),
                        "note": item.note,
                        "evidence_sha256": item.evidence_sha256,
                        "checked_by": item.checked_by,
                    }
                    for item in by_variant.get(row.variant_id, [])
                ],
            }
            for row in variants
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


def list_cases(db: Session) -> list[dict[str, Any]]:
    ids = list(
        db.scalars(select(HouseBuildCase.case_id).order_by(HouseBuildCase.updated_at.desc()))
    )
    return [case_detail(db, case_id) for case_id in ids]


def report_path(db: Session, document_id: str) -> Path:
    row = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.document_id == document_id,
            WorkspaceDocument.category == "housebuild_release_report",
        )
    )
    if row is None:
        raise KeyError(document_id)
    metadata = _loads(row.metadata_json, {})
    path = Path(str(metadata.get("local_path") or "")).resolve()
    root = RUNTIME_ROOT.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("A HouseBuild jelentés tárolási útvonala érvénytelen.") from exc
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != metadata.get(
        "sha256"
    ):
        raise ValueError("A HouseBuild jelentés hiányzik vagy a SHA-256 ellenőrzése sikertelen.")
    return path
