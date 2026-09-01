from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from shapely.geometry import Polygon, box, mapping, shape
from shapely.validation import explain_validity
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    PlotCheckAction,
    PlotCheckAssessment,
    PlotCheckCase,
    PlotCheckEvidence,
    PlotCheckGate,
    PlotRuleSet,
    WorkspaceDocument,
)

RULE_ADMIN_ROLES = {"owner", "managing-director", "platform-admin", "technical-prep", "designer"}
FINAL_ROLES = {"owner", "managing-director", "platform-admin", "technical-prep", "designer"}
GATE_KEYS = ("identity", "zoning", "geodesy", "soil", "utilities", "access", "logistics", "engineering")
MANDATORY_EVIDENCE = (
    "land_registry",
    "cadastral_map",
    "hesz",
    "townscape",
    "geodesy",
    "soil",
    "utilities",
    "access",
    "logistics",
)
GATE_EVIDENCE = {
    "identity": {"land_registry", "cadastral_map"},
    "zoning": {"hesz", "townscape"},
    "geodesy": {"geodesy"},
    "soil": {"soil"},
    "utilities": {"utilities"},
    "access": {"access"},
    "logistics": {"logistics"},
    "engineering": set(MANDATORY_EVIDENCE),
}
OUTCOME_TO_STATUS = {
    "FIT": "fit",
    "FIT WITH CONDITIONS": "fit_with_conditions",
    "RE-DESIGN REQUIRED": "redesign_required",
    "NOT SUITABLE": "not_suitable",
}
RUNTIME_ROOT = Path(os.getenv("PLATFORM_RUNTIME_ROOT", "/app/runtime")) / "plotcheck"


def utcnow() -> datetime:
    return datetime.now(UTC)


def _identity(user: object) -> tuple[str, str]:
    return str(getattr(user, "role", "")), str(getattr(user, "email", "")).strip().lower()


def _decimal(value: Any, label: str, *, minimum: str = "0") -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"A(z) {label} csak érvényes szám lehet.") from exc
    if number <= Decimal(minimum):
        raise ValueError(f"A(z) {label} értékének {minimum}-nál nagyobbnak kell lennie.")
    return number


def _nonnegative_decimal(value: Any, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"A(z) {label} csak érvényes szám lehet.") from exc
    if number < 0:
        raise ValueError(f"A(z) {label} nem lehet negatív.")
    return number


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _case(db: Session, case_id: str) -> PlotCheckCase:
    row = db.scalar(select(PlotCheckCase).where(PlotCheckCase.case_id == case_id))
    if row is None:
        raise KeyError(case_id)
    return row


def _rule(db: Session, rule_set_id: str) -> PlotRuleSet:
    row = db.scalar(select(PlotRuleSet).where(PlotRuleSet.rule_set_id == rule_set_id))
    if row is None:
        raise KeyError(rule_set_id)
    return row


def _geometry(data: dict[str, Any]) -> tuple[Polygon, dict[str, Any]]:
    geojson = data.get("geometry")
    if geojson:
        if isinstance(geojson, str):
            try:
                geojson = json.loads(geojson)
            except json.JSONDecodeError as exc:
                raise ValueError("A telek GeoJSON formátuma hibás.") from exc
        candidate = shape(geojson)
        if candidate.geom_type != "Polygon":
            raise ValueError("A telekgeometria csak egyetlen GeoJSON Polygon lehet.")
        polygon = candidate
    else:
        width = float(_decimal(data.get("plot_width_m"), "telekszélesség"))
        depth = float(_decimal(data.get("plot_depth_m"), "telekmélység"))
        polygon = box(0, 0, width, depth)
    if not polygon.is_valid:
        raise ValueError(f"Érvénytelen telekgeometria: {explain_validity(polygon)}")
    if polygon.area <= 0:
        raise ValueError("A telekgeometriának pozitív területet kell adnia.")
    normalized = mapping(polygon)
    return polygon, normalized


def serialize_rule(row: PlotRuleSet) -> dict[str, Any]:
    return {
        "rule_set_id": row.rule_set_id,
        "municipality": row.municipality,
        "zoning_code": row.zoning_code,
        "version": row.version,
        "lifecycle_status": row.lifecycle_status,
        "source_url": row.source_url,
        "source_document_version": row.source_document_version,
        "source_note": row.source_note,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "maximum_coverage_percent": float(row.maximum_coverage_percent),
        "maximum_floor_area_ratio": float(row.maximum_floor_area_ratio),
        "maximum_height_m": float(row.maximum_height_m),
        "minimum_green_percent": float(row.minimum_green_percent),
        "front_setback_m": float(row.front_setback_m),
        "side_setback_m": float(row.side_setback_m),
        "rear_setback_m": float(row.rear_setback_m),
        "allowed_uses": _loads(row.allowed_uses_json, []),
        "verified_by": row.verified_by,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
    }


def create_rule_set(db: Session, data: dict[str, Any], user: object) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in RULE_ADMIN_ROLES:
        raise PermissionError("PlotCheck szabálytár létrehozásához nincs jogosultsága.")
    required = ("municipality", "zoning_code", "version", "source_url", "source_document_version", "source_note")
    missing = [key for key in required if not str(data.get(key) or "").strip()]
    if missing:
        raise ValueError("Hiányzó szabályadatok: " + ", ".join(missing))
    allowed_uses = [str(item).strip().lower() for item in data.get("allowed_uses", []) if str(item).strip()]
    if not allowed_uses:
        raise ValueError("Legalább egy engedélyezett rendeltetést meg kell adni.")
    lifecycle = str(data.get("lifecycle_status") or "draft").strip().lower()
    if lifecycle not in {"draft", "demo", "uat"}:
        raise ValueError("Új szabályverzió csak draft, demo vagy elkülönített uat állapotban hozható létre.")
    coverage = _decimal(data.get("maximum_coverage_percent"), "legnagyobb beépítettség")
    floor_area_ratio = _decimal(data.get("maximum_floor_area_ratio"), "szintterületi mutató")
    height = _decimal(data.get("maximum_height_m"), "legnagyobb magasság")
    green = _decimal(data.get("minimum_green_percent"), "legkisebb zöldfelület")
    front = _nonnegative_decimal(data.get("front_setback_m"), "előkert")
    side = _nonnegative_decimal(data.get("side_setback_m"), "oldalkert")
    rear = _nonnegative_decimal(data.get("rear_setback_m"), "hátsókert")
    if coverage > 100 or green > 100 or coverage + green > 100:
        raise ValueError("A beépítettség és zöldfelület százalékos korlátai fizikailag nem teljesíthetők.")
    if floor_area_ratio > 10 or height > 100 or max(front, side, rear) > 100:
        raise ValueError("A megadott övezeti korlát kívül esik az elfogadható mérnöki tartományon.")
    row = PlotRuleSet(
        rule_set_id=f"PCRULE-{uuid4().hex[:14].upper()}",
        municipality=str(data["municipality"]).strip(),
        zoning_code=str(data["zoning_code"]).strip().upper(),
        version=str(data["version"]).strip(),
        lifecycle_status=lifecycle,
        source_url=str(data["source_url"]).strip(),
        source_document_version=str(data["source_document_version"]).strip(),
        source_note=str(data["source_note"]).strip(),
        effective_from=date.fromisoformat(str(data["effective_from"])) if data.get("effective_from") else None,
        maximum_coverage_percent=coverage,
        maximum_floor_area_ratio=floor_area_ratio,
        maximum_height_m=height,
        minimum_green_percent=green,
        front_setback_m=front,
        side_setback_m=side,
        rear_setback_m=rear,
        allowed_uses_json=_canonical(allowed_uses),
        created_by=email,
    )
    db.add(row)
    audit(db, actor=email, action="plotcheck.rule.created", entity_type="plotcheck_rule", entity_id=row.rule_set_id, after=serialize_rule(row))
    db.commit()
    return serialize_rule(row)


def verify_rule_set(db: Session, rule_set_id: str, user: object) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in RULE_ADMIN_ROLES:
        raise PermissionError("PlotCheck szabálytár hitelesítéséhez nincs jogosultsága.")
    row = _rule(db, rule_set_id)
    if row.lifecycle_status == "demo":
        raise ValueError("Demo szabály nem hitelesíthető és hivatalos döntésben nem használható.")
    if row.lifecycle_status not in {"draft", "uat"}:
        raise ValueError("Csak draft vagy elkülönített uat szabályverzió hitelesíthető.")
    if row.created_by == email:
        raise ValueError("A négy szem elv miatt a szabály létrehozója nem hitelesítheti a saját verzióját.")
    previous = list(db.scalars(select(PlotRuleSet).where(
        PlotRuleSet.municipality == row.municipality,
        PlotRuleSet.zoning_code == row.zoning_code,
        PlotRuleSet.lifecycle_status == "verified",
    )))
    for item in previous:
        item.lifecycle_status = "retired"
        item.retired_at = utcnow()
    row.lifecycle_status = "uat" if row.lifecycle_status == "uat" else "verified"
    row.verified_by = email
    row.verified_at = utcnow()
    audit(db, actor=email, action="plotcheck.rule.verified", entity_type="plotcheck_rule", entity_id=rule_set_id, after=serialize_rule(row))
    db.commit()
    return serialize_rule(row)


def list_rule_sets(db: Session, *, include_non_verified: bool = True) -> list[dict[str, Any]]:
    statement = select(PlotRuleSet).order_by(PlotRuleSet.municipality, PlotRuleSet.zoning_code, PlotRuleSet.created_at.desc())
    if not include_non_verified:
        statement = statement.where(PlotRuleSet.lifecycle_status == "verified")
    return [serialize_rule(row) for row in db.scalars(statement)]


def _evidence_rows(db: Session, case_id: str) -> list[PlotCheckEvidence]:
    return list(db.scalars(select(PlotCheckEvidence).where(PlotCheckEvidence.case_id == case_id).order_by(PlotCheckEvidence.created_at)))


def _gate_rows(db: Session, case_id: str) -> list[PlotCheckGate]:
    return list(db.scalars(select(PlotCheckGate).where(PlotCheckGate.case_id == case_id).order_by(PlotCheckGate.id)))


def _action_rows(db: Session, case_id: str) -> list[PlotCheckAction]:
    return list(db.scalars(select(PlotCheckAction).where(PlotCheckAction.case_id == case_id).order_by(PlotCheckAction.created_at)))


def _assessment_rows(db: Session, case_id: str) -> list[PlotCheckAssessment]:
    return list(db.scalars(select(PlotCheckAssessment).where(PlotCheckAssessment.case_id == case_id).order_by(PlotCheckAssessment.revision.desc())))


def create_case(db: Session, data: dict[str, Any], actor: str) -> dict[str, Any]:
    required = ("project_id", "title", "address", "parcel_number", "municipality", "zoning_code", "rule_set_id")
    missing = [key for key in required if not str(data.get(key) or "").strip()]
    if missing:
        raise ValueError("Hiányzó PlotCheck alapadatok: " + ", ".join(missing))
    rule = _rule(db, str(data["rule_set_id"]).strip())
    project_id = str(data["project_id"]).strip()
    uat_rule_allowed = rule.lifecycle_status == "uat" and project_id.startswith("PRJ-UAT-")
    if (rule.lifecycle_status != "verified" and not uat_rule_allowed) or not rule.verified_at:
        raise ValueError("Hivatalos PlotCheck ügy kizárólag hitelesített, nem demo szabályverzióval indítható.")
    if rule.municipality.casefold() != str(data["municipality"]).strip().casefold() or rule.zoning_code.casefold() != str(data["zoning_code"]).strip().casefold():
        raise ValueError("A kiválasztott szabályverzió települése vagy övezeti jele nem egyezik az üggyel.")
    polygon, geometry = _geometry(data)
    geometry_crs = str(data.get("geometry_crs") or "EPSG:23700").strip().upper() if data.get("geometry") else "LOCAL-METRIC"
    if data.get("geometry") and geometry_crs != "EPSG:23700":
        raise ValueError("GeoJSON telekgeometria kizárólag EOV / EPSG:23700 méter alapú koordinátákkal fogadható el.")
    declared_area = _decimal(data.get("declared_plot_area_m2"), "nyilvántartott telekterület")
    if abs(Decimal(str(polygon.area)) - declared_area) / declared_area > Decimal("0.05"):
        raise ValueError("A geometriából számított és a nyilvántartott telekterület eltérése meghaladja az 5%-ot.")
    width = _decimal(data.get("proposed_width_m"), "épületszélesség")
    depth = _decimal(data.get("proposed_depth_m"), "épületmélység")
    footprint = _decimal(data.get("proposed_footprint_m2") or width * depth, "épület-alapterület")
    if abs(footprint - width * depth) / footprint > Decimal("0.05"):
        raise ValueError("A tervezett épület szélesség/mélység és alapterület eltérése meghaladja az 5%-ot.")
    case = PlotCheckCase(
        case_id=f"PLOT-{uuid4().hex[:14].upper()}",
        project_id=project_id,
        title=str(data["title"]).strip(),
        address=str(data["address"]).strip(),
        parcel_number=str(data["parcel_number"]).strip(),
        municipality=str(data["municipality"]).strip(),
        zoning_code=str(data["zoning_code"]).strip().upper(),
        rule_set_id=rule.rule_set_id,
        geometry_json=_canonical(geometry),
        geometry_crs=geometry_crs,
        geometry_sha256=_sha({"crs": geometry_crs, "geometry": geometry}),
        declared_plot_area_m2=declared_area,
        proposed_footprint_m2=footprint,
        proposed_gross_floor_area_m2=_decimal(data.get("proposed_gross_floor_area_m2"), "bruttó szintterület"),
        proposed_paved_area_m2=_nonnegative_decimal(data.get("proposed_paved_area_m2") or "0", "burkolt terület"),
        proposed_height_m=_decimal(data.get("proposed_height_m"), "épületmagasság"),
        proposed_use=str(data.get("proposed_use") or "residential").strip().lower(),
        proposed_width_m=width,
        proposed_depth_m=depth,
        house_id=str(data.get("house_id") or "").strip() or None,
        created_by=actor,
    )
    db.add(case)
    db.flush()
    for gate_key in GATE_KEYS:
        db.add(PlotCheckGate(case_id=case.case_id, gate_key=gate_key))
    audit(db, actor=actor, action="plotcheck.case.created", entity_type="plotcheck_case", entity_id=case.case_id, after={"project_id": case.project_id, "rule_set_id": rule.rule_set_id, "geometry_sha256": case.geometry_sha256})
    db.commit()
    return case_detail(db, case.case_id)


def add_evidence(db: Session, case_id: str, data: dict[str, Any], actor: str) -> dict[str, Any]:
    case = _case(db, case_id)
    if case.status not in {"intake", "review"}:
        raise ValueError("Lezárt PlotCheck ügy bizonyítékai nem módosíthatók.")
    category = str(data.get("category") or "").strip()
    if category not in set(MANDATORY_EVIDENCE) | {"legal", "other"}:
        raise ValueError("Ismeretlen PlotCheck bizonyítékkategória.")
    source = str(data.get("source_reference") or "").strip()
    version = str(data.get("source_version") or "").strip()
    note = str(data.get("note") or "").strip()
    if not source or not version or len(note) < 5:
        raise ValueError("A bizonyíték forrása, verziója és érdemi megjegyzése kötelező.")
    digest = str(data.get("source_sha256") or "").strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("A bizonyítékhoz érvényes SHA-256 lenyomat kötelező.")
    row = PlotCheckEvidence(
        evidence_id=f"PCE-{uuid4().hex[:14].upper()}", case_id=case_id, category=category,
        source_reference=source, source_version=version, source_sha256=digest,
        verified=False, legal_blocker=bool(data.get("legal_blocker")), note=note,
        created_by=actor,
    )
    db.add(row)
    case.current_revision += 1
    audit(db, actor=actor, action="plotcheck.evidence.added", entity_type="plotcheck_evidence", entity_id=row.evidence_id, after={"case_id": case_id, "category": category, "verified": False, "sha256": digest})
    db.commit()
    return case_detail(db, case_id)


def verify_evidence(db: Session, case_id: str, evidence_id: str, actor: str) -> dict[str, Any]:
    case = _case(db, case_id)
    if case.status not in {"intake", "review"}:
        raise ValueError("Lezárt PlotCheck ügy bizonyítéka nem hitelesíthető.")
    row = db.scalar(select(PlotCheckEvidence).where(
        PlotCheckEvidence.case_id == case_id, PlotCheckEvidence.evidence_id == evidence_id
    ))
    if row is None:
        raise KeyError(evidence_id)
    if row.verified:
        return case_detail(db, case_id)
    if row.created_by.strip().lower() == actor.strip().lower():
        raise ValueError("A négy szem elv miatt a bizonyíték rögzítője nem hitelesítheti a saját forrását.")
    row.verified = True
    row.verified_by = actor
    row.verified_at = utcnow()
    case.current_revision += 1
    audit(db, actor=actor, action="plotcheck.evidence.verified", entity_type="plotcheck_evidence", entity_id=evidence_id, after={"case_id": case_id, "category": row.category, "sha256": row.source_sha256})
    db.commit()
    return case_detail(db, case_id)


def add_action(db: Session, case_id: str, data: dict[str, Any], actor: str) -> dict[str, Any]:
    case = _case(db, case_id)
    if case.status not in {"intake", "review"}:
        raise ValueError("Lezárt PlotCheck ügy intézkedései nem módosíthatók.")
    condition = str(data.get("condition") or "").strip()
    owner = str(data.get("owner") or "").strip()
    design_impact = str(data.get("design_impact") or "").strip()
    if len(condition) < 10 or not owner or len(design_impact) < 5:
        raise ValueError("A feltétel, felelős és tervezési hatás részletes megadása kötelező.")
    cost = Decimal(str(data.get("estimated_cost_huf") or "0"))
    days = int(data.get("deadline_impact_days") or 0)
    if cost < 0 or days < 0:
        raise ValueError("A költség- és határidőhatás nem lehet negatív.")
    row = PlotCheckAction(
        action_id=f"ACTION-PLOT-{uuid4().hex[:12].upper()}", case_id=case_id,
        condition=condition, owner=owner, estimated_cost_huf=cost,
        deadline_impact_days=days, design_impact=design_impact, created_by=actor,
    )
    db.add(row)
    case.current_revision += 1
    audit(db, actor=actor, action="plotcheck.action.created", entity_type="plotcheck_action", entity_id=row.action_id, after={"case_id": case_id, "cost_huf": str(cost), "deadline_impact_days": days})
    db.commit()
    return case_detail(db, case_id)


def complete_action(db: Session, case_id: str, action_id: str, data: dict[str, Any], actor: str) -> dict[str, Any]:
    case = _case(db, case_id)
    if case.status not in {"intake", "review"}:
        raise ValueError("Lezárt PlotCheck ügy intézkedése nem módosítható.")
    row = db.scalar(select(PlotCheckAction).where(
        PlotCheckAction.case_id == case_id, PlotCheckAction.action_id == action_id
    ))
    if row is None:
        raise KeyError(action_id)
    if row.status != "open":
        raise ValueError("Csak nyitott ActionID zárható le.")
    evidence_ref = str(data.get("completion_evidence_ref") or "").strip()
    digest = str(data.get("completion_evidence_sha256") or "").strip().lower()
    if not evidence_ref or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("Az ActionID lezárásához forráshivatkozás és érvényes SHA-256 bizonyíték kötelező.")
    row.status = "completed"
    row.completion_evidence_ref = evidence_ref
    row.completion_evidence_sha256 = digest
    row.completed_by = actor
    row.completed_at = utcnow()
    case.current_revision += 1
    audit(db, actor=actor, action="plotcheck.action.completed", entity_type="plotcheck_action", entity_id=action_id, after={"case_id": case_id, "completion_evidence_ref": evidence_ref, "completion_evidence_sha256": digest})
    db.commit()
    return case_detail(db, case_id)


def review_gate(db: Session, case_id: str, gate_key: str, data: dict[str, Any], actor: str) -> dict[str, Any]:
    case = _case(db, case_id)
    if case.status not in {"intake", "review"} or gate_key not in GATE_KEYS:
        raise ValueError("Ez a PlotCheck kapu most nem értékelhető.")
    decision = str(data.get("decision") or "").strip()
    note = str(data.get("note") or "").strip()
    evidence_ids = [str(item).strip() for item in data.get("evidence_ids", []) if str(item).strip()]
    if decision not in {"approved", "rejected"} or len(note) < 10:
        raise ValueError("A kapudöntés és legalább 10 karakteres indoklás kötelező.")
    evidence = {row.evidence_id: row for row in _evidence_rows(db, case_id)}
    if any(item not in evidence for item in evidence_ids):
        raise ValueError("A kapu más ügyhöz tartozó vagy ismeretlen bizonyítékra hivatkozik.")
    if decision == "approved":
        supplied = {evidence[item].category for item in evidence_ids if evidence[item].verified}
        missing = GATE_EVIDENCE[gate_key] - supplied
        if missing:
            raise ValueError("A kapuhoz hiányzó hiteles bizonyíték: " + ", ".join(sorted(missing)))
    row = db.scalar(select(PlotCheckGate).where(PlotCheckGate.case_id == case_id, PlotCheckGate.gate_key == gate_key))
    if row is None:
        raise KeyError(gate_key)
    row.decision = decision
    row.evidence_ids_json = _canonical(evidence_ids)
    row.note = note
    row.decided_by = actor
    row.decided_at = utcnow()
    case.status = "review"
    case.current_revision += 1
    audit(db, actor=actor, action="plotcheck.gate.decided", entity_type="plotcheck_gate", entity_id=f"{case_id}:{gate_key}", after={"decision": decision, "evidence_ids": evidence_ids, "note": note})
    db.commit()
    return case_detail(db, case_id)


def assess_case(db: Session, case_id: str, actor: str) -> dict[str, Any]:
    case = _case(db, case_id)
    if case.status not in {"intake", "review"}:
        raise ValueError("Lezárt PlotCheck ügy nem számítható újra.")
    rule = _rule(db, case.rule_set_id)
    if rule.lifecycle_status not in {"verified", "retired", "uat"} or not rule.verified_at:
        raise ValueError("A rögzített szabálypillanatkép nem hiteles.")
    polygon = shape(_loads(case.geometry_json, {}))
    setback = max(float(rule.front_setback_m), float(rule.side_setback_m), float(rule.rear_setback_m))
    buildable = polygon.buffer(-setback, join_style=2)
    width, depth = float(case.proposed_width_m), float(case.proposed_depth_m)
    footprint_a = box(-width / 2, -depth / 2, width / 2, depth / 2)
    footprint_b = box(-depth / 2, -width / 2, depth / 2, width / 2)
    center = buildable.centroid if not buildable.is_empty else polygon.centroid
    placement_fit = any(buildable.covers(item) for item in (
        Polygon([(x + center.x, y + center.y) for x, y in footprint_a.exterior.coords]),
        Polygon([(x + center.x, y + center.y) for x, y in footprint_b.exterior.coords]),
    )) if not buildable.is_empty else False
    area = float(polygon.area)
    coverage = float(case.proposed_footprint_m2) / area * 100
    floor_area_ratio = float(case.proposed_gross_floor_area_m2) / area
    green_percent = max(0.0, (area - float(case.proposed_footprint_m2) - float(case.proposed_paved_area_m2)) / area * 100)
    use_allowed = case.proposed_use in _loads(rule.allowed_uses_json, [])
    metrics = {
        "case_revision": case.current_revision,
        "geometry_crs": case.geometry_crs, "plot_area_m2": round(area, 3), "declared_plot_area_m2": float(case.declared_plot_area_m2),
        "area_difference_percent": round(abs(area - float(case.declared_plot_area_m2)) / float(case.declared_plot_area_m2) * 100, 3),
        "conservative_uniform_setback_m": setback, "buildable_area_m2": round(float(buildable.area), 3) if not buildable.is_empty else 0,
        "placement_fit_0_or_90_degrees": placement_fit,
        "coverage_percent": round(coverage, 3), "coverage_limit_percent": float(rule.maximum_coverage_percent),
        "floor_area_ratio": round(floor_area_ratio, 3), "floor_area_ratio_limit": float(rule.maximum_floor_area_ratio),
        "height_m": float(case.proposed_height_m), "height_limit_m": float(rule.maximum_height_m),
        "green_percent": round(green_percent, 3), "minimum_green_percent": float(rule.minimum_green_percent),
        "proposed_use": case.proposed_use, "use_allowed": use_allowed,
        "directional_setback_assumption": "A konzervatív maximum elő-/oldal-/hátsókerti távolságot minden irányban alkalmaztuk; a végső kitűzéshez tájolt kataszteri ellenőrzés szükséges.",
    }
    evidence = _evidence_rows(db, case_id)
    verified_categories = {row.category for row in evidence if row.verified}
    missing = [category for category in MANDATORY_EVIDENCE if category not in verified_categories]
    legal_blockers = [row.evidence_id for row in evidence if row.verified and row.legal_blocker]
    stop_reasons = [f"Hiányzó hiteles vizsgálat: {category}" for category in missing]
    if legal_blockers:
        stop_reasons.append("Igazolt jogi vagy építési jogosultsági akadály: " + ", ".join(legal_blockers))
    failed_constraints = []
    if buildable.is_empty:
        failed_constraints.append("A védőtávolságok után nem marad beépíthető terület.")
    if not placement_fit:
        failed_constraints.append("A megadott épülettéglalap 0°/90° helyzetben nem fér el a konzervatív építési helyen.")
    if coverage > float(rule.maximum_coverage_percent):
        failed_constraints.append("A tervezett beépítettség meghaladja az övezeti maximumot.")
    if floor_area_ratio > float(rule.maximum_floor_area_ratio):
        failed_constraints.append("A tervezett szintterületi mutató meghaladja az övezeti maximumot.")
    if float(case.proposed_height_m) > float(rule.maximum_height_m):
        failed_constraints.append("A tervezett épületmagasság meghaladja az övezeti maximumot.")
    if green_percent < float(rule.minimum_green_percent):
        failed_constraints.append("A tervezett zöldfelület nem éri el az övezeti minimumot.")
    if not use_allowed:
        failed_constraints.append("A tervezett rendeltetés nem szerepel a hiteles szabályverzióban.")
    actions = _action_rows(db, case_id)
    if legal_blockers or buildable.is_empty or not use_allowed:
        outcome = "NOT SUITABLE"
    elif failed_constraints:
        outcome = "RE-DESIGN REQUIRED"
    elif any(row.status == "open" for row in actions) or missing:
        outcome = "FIT WITH CONDITIONS"
    else:
        outcome = "FIT"
    conditions = [
        {"action_id": row.action_id, "condition": row.condition, "owner": row.owner, "estimated_cost_huf": str(row.estimated_cost_huf), "deadline_impact_days": row.deadline_impact_days, "design_impact": row.design_impact, "status": row.status}
        for row in actions
    ]
    snapshot = {"case": {"case_id": case.case_id, "revision": case.current_revision, "geometry_sha256": case.geometry_sha256}, "rule": serialize_rule(rule), "evidence": [{"id": row.evidence_id, "category": row.category, "sha256": row.source_sha256, "verified": row.verified, "legal_blocker": row.legal_blocker} for row in evidence], "metrics": metrics, "stop_reasons": stop_reasons, "failed_constraints": failed_constraints, "conditions": conditions, "outcome": outcome}
    revision = int(db.scalar(select(func.max(PlotCheckAssessment.revision)).where(PlotCheckAssessment.case_id == case_id)) or 0) + 1
    assessment = PlotCheckAssessment(
        assessment_id=f"PCA-{uuid4().hex[:14].upper()}", case_id=case_id, revision=revision,
        outcome=outcome, confidence_class="A" if not missing else "B" if len(missing) <= 2 else "C" if len(missing) <= 5 else "D",
        metrics_json=_canonical({**metrics, "failed_constraints": failed_constraints}),
        stop_reasons_json=_canonical(stop_reasons), conditions_json=_canonical(conditions),
        snapshot_sha256=_sha(snapshot), preliminary=True, assessed_by=actor,
    )
    db.add(assessment)
    case.final_assessment_id = assessment.assessment_id
    case.status = "review"
    audit(db, actor=actor, action="plotcheck.assessed", entity_type="plotcheck_assessment", entity_id=assessment.assessment_id, after={"outcome": outcome, "snapshot_sha256": assessment.snapshot_sha256, "stop_reasons": stop_reasons, "failed_constraints": failed_constraints})
    db.commit()
    return case_detail(db, case_id)


def _report(case: PlotCheckCase, rule: PlotRuleSet, assessment: PlotCheckAssessment, gates: list[PlotCheckGate], evidence: list[PlotCheckEvidence], actions: list[PlotCheckAction]) -> tuple[Path, str]:
    directory = RUNTIME_ROOT / case.case_id / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"PlotCheck-{case.case_id}-r{assessment.revision}-{assessment.outcome.replace(' ', '_')}.pdf"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    y = 805
    lines = [
        "IMPERIAL INTELLIGENCE - PlotCheck döntési jegyzőkönyv",
        f"PlotCheckID: {case.case_id}", f"ProjectID: {case.project_id}", f"Ingatlan: {case.address} / {case.parcel_number}",
        f"Övezet: {case.municipality} {case.zoning_code}; szabály: {rule.version} ({rule.rule_set_id})",
        f"Eredmény: {assessment.outcome}", f"Bizalmi osztály: {assessment.confidence_class}",
        f"Bizonyítékok: {len(evidence)}; intézkedések: {len(actions)}",
        "Kapuk: " + ", ".join(f"{gate.gate_key}={gate.decision}" for gate in gates),
        f"Telekgeometria SHA-256: {case.geometry_sha256}", f"Döntési snapshot SHA-256: {assessment.snapshot_sha256}",
        "Megjegyzés: a számítás konzervatív, egységes maximum oldalkerti visszahúzást használ; a végső kitűzés szakági feladat.",
    ]
    for line in lines:
        if y < 70:
            pdf.showPage(); y = 805
        pdf.drawString(36, y, line[:112]); y -= 23
    pdf.save()
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def finalize_case(db: Session, case_id: str, outcome: str, note: str, user: object) -> dict[str, Any]:
    role, email = _identity(user)
    if role not in FINAL_ROLES:
        raise PermissionError("A PlotCheck végső döntéshez nincs jogosultsága.")
    if outcome not in OUTCOME_TO_STATUS or len(note.strip()) < 10:
        raise ValueError("A kanonikus eredmény és legalább 10 karakteres döntési indoklás kötelező.")
    case = _case(db, case_id)
    if case.status != "review" or not case.final_assessment_id:
        raise ValueError("Csak frissen kiszámított, ellenőrzés alatt álló PlotCheck ügy zárható le.")
    if case.created_by == email:
        raise ValueError("A négy szem elv miatt a létrehozó nem zárhatja le a saját PlotCheck ügyét.")
    assessment = db.scalar(select(PlotCheckAssessment).where(PlotCheckAssessment.assessment_id == case.final_assessment_id))
    if assessment is None or assessment.outcome != outcome:
        raise ValueError("A döntésnek egyeznie kell a legfrissebb kanonikus mérnöki számítás eredményével.")
    if int(_loads(assessment.metrics_json, {}).get("case_revision") or 0) != case.current_revision:
        raise ValueError("A bizonyítékok, kapuk vagy intézkedések megváltoztak; a PlotCheck számítást újra kell futtatni.")
    gates = _gate_rows(db, case_id)
    if len(gates) != len(GATE_KEYS) or any(row.decision != "approved" for row in gates):
        raise ValueError("A lezáráshoz minden PlotCheck kapu jóváhagyása kötelező.")
    stop_reasons = _loads(assessment.stop_reasons_json, [])
    if stop_reasons and outcome != "NOT SUITABLE":
        raise ValueError("STOP feltétel mellett csak NOT SUITABLE döntés zárható le; előbb pótolni kell a vizsgálatokat.")
    actions = _action_rows(db, case_id)
    if outcome == "FIT WITH CONDITIONS" and not actions:
        raise ValueError("Minden feltételes alkalmassághoz legalább egy teljes ActionID szükséges.")
    if outcome == "FIT" and any(row.status == "open" for row in actions):
        raise ValueError("FIT döntés mellett nem maradhat nyitott feltételes intézkedés.")
    evidence = _evidence_rows(db, case_id)
    rule = _rule(db, case.rule_set_id)
    path, digest = _report(case, rule, assessment, gates, evidence, actions)
    document_id = f"DOC-PLOT-{uuid4().hex[:12].upper()}"
    db.add(WorkspaceDocument(
        document_id=document_id, project_id=case.project_id, title=f"PlotCheck {outcome} – {case.case_id}",
        category="plotcheck_report", source_system="plotcheck", source_url=f"file://{path}", mime_type="application/pdf",
        version_label=f"r{assessment.revision}", approval_status="approved", verification_status="sha256_verified",
        confidentiality="internal", owner="Műszaki előkészítés",
        extracted_summary=f"{outcome}; confidence={assessment.confidence_class}; SHA-256={digest}",
        metadata_json=_canonical({"sha256": digest, "snapshot_sha256": assessment.snapshot_sha256, "local_path": str(path), "rule_set_id": rule.rule_set_id}),
    ))
    assessment.preliminary = False
    case.status = OUTCOME_TO_STATUS[outcome]
    case.final_report_document_id = document_id
    case.finalized_by = email
    case.finalized_at = utcnow()
    audit(db, actor=email, action="plotcheck.finalized", entity_type="plotcheck_case", entity_id=case_id, after={"outcome": outcome, "report_document_id": document_id, "note": note.strip()})
    from ..schemas import EventIn
    from .integration import ingest_event
    ingest_event(db, EventIn(
        event_id=f"EVT-PLOT-{uuid4().hex[:14].upper()}", dedupe_key=f"PLOTCHECK_FINALIZED:{case_id}:r{assessment.revision}",
        project_id=case.project_id, source_module="plotcheck", event_type="PLOTCHECK_FINALIZED", object_type="PlotCheckCase", object_id=case_id,
        status=case.status, responsible="Műszaki előkészítés", next_action="A PlotCheck döntés átvezetése a ház- és projektkonfigurációba.",
        evidence_url=f"document://{document_id}", financial_impact_huf=sum((row.estimated_cost_huf for row in actions), Decimal("0")),
        deadline_impact_days=max((row.deadline_impact_days for row in actions), default=0),
        payload={"summary": f"PlotCheck {case_id}: {outcome}", "outcome": outcome, "assessment_sha256": assessment.snapshot_sha256, "report_sha256": digest, "rule_set_id": rule.rule_set_id, "house_id": case.house_id},
        route_to=["crm", "my-imperial", "housebuild-agent", "buildconfig", "engineering-workspace"],
    ), actor=email)
    return case_detail(db, case_id)


def case_detail(db: Session, case_id: str) -> dict[str, Any]:
    case = _case(db, case_id)
    rule = _rule(db, case.rule_set_id)
    evidence = _evidence_rows(db, case_id)
    gates = _gate_rows(db, case_id)
    actions = _action_rows(db, case_id)
    assessments = _assessment_rows(db, case_id)
    return {
        "case_id": case.case_id, "project_id": case.project_id, "title": case.title, "address": case.address,
        "parcel_number": case.parcel_number, "municipality": case.municipality, "zoning_code": case.zoning_code,
        "status": case.status, "current_revision": case.current_revision, "geometry_crs": case.geometry_crs, "geometry_sha256": case.geometry_sha256,
        "declared_plot_area_m2": float(case.declared_plot_area_m2), "proposed_footprint_m2": float(case.proposed_footprint_m2),
        "proposed_gross_floor_area_m2": float(case.proposed_gross_floor_area_m2), "proposed_paved_area_m2": float(case.proposed_paved_area_m2), "proposed_height_m": float(case.proposed_height_m),
        "proposed_width_m": float(case.proposed_width_m), "proposed_depth_m": float(case.proposed_depth_m), "proposed_use": case.proposed_use,
        "house_id": case.house_id, "rule": serialize_rule(rule), "created_by": case.created_by,
        "final_assessment_id": case.final_assessment_id, "final_report_document_id": case.final_report_document_id,
        "evidence": [{"evidence_id": row.evidence_id, "category": row.category, "source_reference": row.source_reference, "source_version": row.source_version, "source_sha256": row.source_sha256, "verified": row.verified, "legal_blocker": row.legal_blocker, "note": row.note, "verified_by": row.verified_by} for row in evidence],
        "gates": [{"gate_key": row.gate_key, "decision": row.decision, "evidence_ids": _loads(row.evidence_ids_json, []), "note": row.note, "decided_by": row.decided_by} for row in gates],
        "actions": [{"action_id": row.action_id, "condition": row.condition, "owner": row.owner, "estimated_cost_huf": float(row.estimated_cost_huf), "deadline_impact_days": row.deadline_impact_days, "design_impact": row.design_impact, "status": row.status, "completion_evidence_ref": row.completion_evidence_ref, "completion_evidence_sha256": row.completion_evidence_sha256, "completed_by": row.completed_by} for row in actions],
        "assessments": [{"assessment_id": row.assessment_id, "revision": row.revision, "outcome": row.outcome, "confidence_class": row.confidence_class, "metrics": _loads(row.metrics_json, {}), "stop_reasons": _loads(row.stop_reasons_json, []), "conditions": _loads(row.conditions_json, []), "snapshot_sha256": row.snapshot_sha256, "preliminary": row.preliminary, "assessed_by": row.assessed_by} for row in assessments],
    }


def list_cases(db: Session) -> list[dict[str, Any]]:
    ids = list(db.scalars(select(PlotCheckCase.case_id).order_by(PlotCheckCase.updated_at.desc())))
    return [case_detail(db, case_id) for case_id in ids]
