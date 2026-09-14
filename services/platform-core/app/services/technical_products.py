from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import TechnicalCase, TechnicalGate
from .house_catalog import released_house
from .pricing import pricing_repository


MODULES = ("housebuild-agent", "plotcheck", "buildconfig", "plancheck")

GATE_SPECS: dict[str, tuple[tuple[str, str], ...]] = {
    "housebuild-agent": (
        ("source_rights", "Forrás és felhasználási jog igazolása"),
        ("deduplication", "Duplikáció-ellenőrzés"),
        ("configuration", "Helyiségprogram és kiválasztott változat"),
        ("buildconfig", "BuildConfig kalkuláció és műszaki csomag"),
        ("topology", "Alaprajzi topológia ellenőrzése"),
        ("plancheck", "PlanCheck megfelelőség"),
        ("human_approval", "Kötelező emberi jóváhagyás"),
    ),
    "plotcheck": (
        ("ownership", "Tulajdoni és helyrajzi adatok"),
        ("zoning", "Övezeti előírások"),
        ("buildability", "Beépíthetőség és telekméretek"),
        ("utilities", "Közműellátottság"),
        ("access", "Megközelíthetőség"),
        ("engineer_approval", "Mérnöki jóváhagyás"),
    ),
    "buildconfig": (
        ("technical", "Műszaki tartalom"),
        ("finance", "Pénzügyi forrás"),
        ("margin", "Fedezeti kapu"),
        ("cashflow", "Cashflow-kapu"),
        ("capacity", "Kapacitáskapu"),
    ),
    "plancheck": (
        ("completeness", "Tervcsomag teljessége"),
        ("geometry", "Geometriai és méretellenőrzés"),
        ("structural", "Tartószerkezeti ellenőrzés"),
        ("fire_safety", "Tűzvédelmi megfelelőség"),
        ("energy", "Energetikai megfelelőség"),
        ("human_approval", "Kötelező emberi jóváhagyás"),
    ),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_json(value: str) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def case_payload(case: TechnicalCase, gates: list[TechnicalGate]) -> dict:
    return {
        "case_id": case.case_id,
        "module_key": case.module_key,
        "project_id": case.project_id,
        "title": case.title,
        "version": case.version,
        "status": case.status,
        "input": parse_json(case.input_json),
        "result": parse_json(case.result_json),
        "source_snapshot": parse_json(case.source_snapshot_json),
        "created_by": case.created_by,
        "assigned_to": case.assigned_to,
        "submitted_at": case.submitted_at,
        "approved_at": case.approved_at,
        "approved_by": case.approved_by,
        "rejection_reason": case.rejection_reason,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "gates": [
            {
                "gate_key": gate.gate_key,
                "label": gate.label,
                "required": gate.required,
                "status": gate.status,
                "evidence": gate.evidence,
                "checked_by": gate.checked_by,
                "checked_at": gate.checked_at,
            }
            for gate in gates
        ],
    }


def list_cases(db: Session, module_key: str | None = None, project_id: str | None = None) -> list[dict]:
    query = select(TechnicalCase).order_by(TechnicalCase.updated_at.desc())
    if module_key:
        query = query.where(TechnicalCase.module_key == module_key)
    if project_id:
        query = query.where(TechnicalCase.project_id == project_id)
    cases = list(db.scalars(query))
    if not cases:
        return []
    gate_rows = list(db.scalars(select(TechnicalGate).where(TechnicalGate.case_id.in_([case.case_id for case in cases]))))
    by_case: dict[str, list[TechnicalGate]] = {}
    for gate in gate_rows:
        by_case.setdefault(gate.case_id, []).append(gate)
    return [case_payload(case, sorted(by_case.get(case.case_id, []), key=lambda row: row.id)) for case in cases]


def _housebuild_payload(db: Session, data: dict) -> tuple[dict, dict]:
    house_id = str(data.get("source_house_id") or "").strip()
    rights_evidence = str(data.get("rights_evidence") or "").strip()
    house = released_house(db, house_id)
    if not house:
        raise ValueError("Csak aktív, vállalati házkatalógus-forrás választható.")
    if not house.get("source_url") or not house.get("verified_at"):
        raise ValueError("A kiválasztott ház forrás- vagy ellenőrzési bizonyítéka hiányzik.")
    if len(rights_evidence) < 8:
        raise ValueError("A forrás felhasználási jogának bizonyítékát rögzíteni kell.")
    try:
        source_area = Decimal(str(house.get("gross_area_m2") or 0))
        desired_area = Decimal(str(data.get("desired_area_m2") or source_area))
        bedrooms = int(data.get("bedrooms") or 3)
        bathrooms = int(data.get("bathrooms") or 1)
        floors = int(data.get("floors") or 1)
        garage_spaces = int(data.get("garage_spaces") or 0)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("A típusterv számszerű konfigurációs adatai hibásak.") from exc
    if desired_area < 20 or desired_area > 500:
        raise ValueError("A kívánt bruttó alapterület 20 és 500 m² között lehet.")
    if bedrooms < 1 or bedrooms > 10 or bathrooms < 1 or bathrooms > 5 or floors < 1 or floors > 3 or garage_spaces < 0 or garage_spaces > 3:
        raise ValueError("A szoba-, fürdő-, szint- vagy garázsprogram kívül esik az engedélyezett tartományon.")
    roof_style = str(data.get("roof_style") or "nyeregtető").strip()
    facade_style = str(data.get("facade_style") or "kortárs").strip()
    orientation = str(data.get("orientation") or "helyszín szerint").strip()
    raw_accessibility = data.get("accessibility")
    accessibility = raw_accessibility is True or str(raw_accessibility or "").strip().lower() in {"1", "true", "yes", "on"}
    customization_notes = str(data.get("customization_notes") or "").strip()
    house_plan_id = f"HP-{uuid4().hex[:10].upper()}"

    def variant(code: str, label: str, area: Decimal, bed_count: int, bath_count: int, strategy: str) -> dict:
        ratio = area / source_area if source_area else Decimal("1")
        estimate = int(Decimal(str(house.get("catalog_price_huf") or 0)) * ratio)
        return {
            "variant_id": f"{house_plan_id}-{code}", "label": label,
            "gross_area_m2": float(area.quantize(Decimal("0.1"))), "floors": floors,
            "bedrooms": bed_count, "bathrooms": bath_count, "garage_spaces": garage_spaces,
            "roof_style": roof_style, "facade_style": facade_style, "orientation": orientation,
            "accessibility": accessibility, "estimated_catalog_price_huf": estimate,
            "strategy": strategy,
            "room_program": ["előtér", "nappali–étkező–konyha", *[f"hálószoba {index + 1}" for index in range(bed_count)], *[f"fürdő {index + 1}" for index in range(bath_count)], "háztartási helyiség", "gépészeti helyiség"],
        }

    compact_area = max(Decimal("20"), desired_area * Decimal("0.92"))
    variants = [
        variant("A", "Katalógushű változat", source_area or desired_area, bedrooms, bathrooms, "A forrásház méretét és tömegét tartja elsődlegesnek."),
        variant("B", "Célprogramra hangolt változat", desired_area, bedrooms, bathrooms, "A megadott helyiségprogramot és cél-alapterületet követi."),
        variant("C", "Kompakt költségoptimalizált változat", compact_area, max(1, bedrooms - 1), bathrooms, "Csökkentett közlekedő- és hálóterülettel javítja a fajlagos költséget."),
    ]
    area_delta_percent = float((abs(desired_area - source_area) / source_area * 100).quantize(Decimal("0.1"))) if source_area else 0.0
    result = {
        "house_plan_id": house_plan_id,
        "candidate": house,
        "configuration": {"desired_area_m2": float(desired_area), "bedrooms": bedrooms, "bathrooms": bathrooms, "floors": floors, "garage_spaces": garage_spaces, "roof_style": roof_style, "facade_style": facade_style, "orientation": orientation, "accessibility": accessibility, "customization_notes": customization_notes},
        "variants": variants,
        "selected_variant_id": None,
        "selection_required": True,
        "redesign_class": "major" if area_delta_percent > 20 else "controlled",
        "area_delta_percent": area_delta_percent,
        "required_deliverables": ["helyiségprogram", "méret- és területkimutatás", "sematikus alaprajz", "homlokzati koncepció", "műszaki specifikáció", "BuildConfig kalkuláció", "PlanCheck jegyzőkönyv"],
        "publication_allowed": False,
        "next_step": "Változatválasztás, BuildConfig, PlanCheck és emberi jóváhagyás",
    }
    source = {
        "house_id": house_id,
        "source_url": house["source_url"],
        "verified_at": house["verified_at"],
        "data_quality": house.get("data_quality"),
        "rights_evidence": rights_evidence,
    }
    return result, source


def select_housebuild_variant(db: Session, case_id: str, variant_id: str, actor: str) -> dict:
    case = db.scalar(select(TechnicalCase).where(TechnicalCase.case_id == case_id))
    if not case:
        raise KeyError(case_id)
    if case.module_key != "housebuild-agent":
        raise ValueError("Változat csak HouseBuild ügyön választható.")
    if case.status != "draft":
        raise ValueError("Változatot csak a tervezet ellenőrzésre küldése előtt lehet kiválasztani.")
    result = parse_json(case.result_json)
    raw_variants = result.get("variants")
    variants: list[dict[str, Any]] = (
        [item for item in raw_variants if isinstance(item, dict)]
        if isinstance(raw_variants, list)
        else []
    )
    selected = next((item for item in variants if item.get("variant_id") == variant_id), None)
    if not selected:
        raise ValueError("A kiválasztott HouseBuild-változat nem található.")
    before = {"selected_variant_id": result.get("selected_variant_id"), "version": case.version}
    result.update({"selected_variant_id": variant_id, "selected_variant": selected, "selection_required": False, "next_step": "BuildConfig és PlanCheck kapuk ellenőrzése"})
    case.result_json = json.dumps(result, ensure_ascii=False, default=str)
    case.version += 1
    case.updated_at = utcnow()
    audit(db, actor=actor, action="housebuild.variant_selected", entity_type="technical_case", entity_id=case_id, before=before, after={"selected_variant_id": variant_id, "version": case.version})
    db.commit()
    return get_case(db, case_id)


def _buildconfig_payload(data: dict) -> tuple[dict, dict]:
    result = pricing_repository.calculate_new_build(
        brand=str(data.get("brand") or ""),
        technology=str(data.get("technology") or ""),
        completion_level=str(data.get("completion_level") or "Kulcsrakész"),
        package=str(data.get("package") or "Alap"),
        gross_area_m2=Decimal(str(data.get("gross_area_m2") or "0")),
        include_internal=True,
    )
    source = {
        "source_version": result["source_version"],
        "price_basis": result["price_basis"],
        "calculated_at": utcnow().isoformat(),
    }
    return result, source


def create_case(db: Session, *, module_key: str, project_id: str, title: str, data: dict, actor: str, assigned_to: str | None = None) -> dict:
    if module_key not in MODULES:
        raise ValueError("Ismeretlen műszaki modul.")
    if len(project_id.strip()) < 3 or not title.strip():
        raise ValueError("A ProjectID és a megnevezés kötelező.")
    result: dict = {}
    source: dict = {}
    if module_key == "housebuild-agent":
        result, source = _housebuild_payload(db, data)
    elif module_key == "buildconfig":
        result, source = _buildconfig_payload(data)
    elif module_key == "plotcheck":
        required = ("address", "parcel_number", "zoning_code", "plot_area_m2")
        if any(not str(data.get(key) or "").strip() for key in required):
            raise ValueError("A cím, helyrajzi szám, övezeti jel és telekterület kötelező.")
        source = {"evidence_references": data.get("evidence_references", [])}
    elif module_key == "plancheck":
        document_refs = data.get("document_refs")
        if not isinstance(document_refs, list) or not [item for item in document_refs if str(item).strip()]:
            raise ValueError("Legalább egy verziózott tervdokumentum-hivatkozás kötelező.")
        source = {"document_refs": document_refs}

    now = utcnow()
    prefix = {"housebuild-agent": "HBJ", "plotcheck": "PLOT", "buildconfig": "CFG", "plancheck": "PLC"}[module_key]
    case = TechnicalCase(
        case_id=f"{prefix}-{uuid4().hex[:12].upper()}", module_key=module_key,
        project_id=project_id.strip(), title=title.strip(), status="draft",
        input_json=json.dumps(data, ensure_ascii=False, default=str),
        result_json=json.dumps(result, ensure_ascii=False, default=str),
        source_snapshot_json=json.dumps(source, ensure_ascii=False, default=str),
        created_by=actor, assigned_to=assigned_to or actor, created_at=now, updated_at=now,
    )
    db.add(case)
    db.flush()
    gates: list[TechnicalGate] = []
    for key, label in GATE_SPECS[module_key]:
        status = "pending"
        evidence = None
        if module_key == "buildconfig" and key == "margin":
            margin_gate = result.get("internal_control", {}).get("margin_gate")
            status = "pass" if margin_gate == "pass" else "fail"
            evidence = f"Automatikus fedezeti kapu: {margin_gate or 'nincs eredmény'}"
        gate = TechnicalGate(case_id=case.case_id, gate_key=key, label=label, required=True, status=status, evidence=evidence, checked_by="pricing-engine" if evidence else None, checked_at=now if evidence else None, created_at=now, updated_at=now)
        db.add(gate)
        gates.append(gate)
    audit(db, actor=actor, action="technical_case.created", entity_type="technical_case", entity_id=case.case_id, after={"module": module_key, "project_id": project_id})
    db.commit()
    return case_payload(case, gates)


def submit_case(db: Session, case_id: str, actor: str) -> dict:
    case = db.scalar(select(TechnicalCase).where(TechnicalCase.case_id == case_id))
    if not case:
        raise KeyError(case_id)
    if case.status != "draft":
        raise ValueError("Csak tervezet küldhető ellenőrzésre.")
    if case.module_key == "housebuild-agent" and not parse_json(case.result_json).get("selected_variant_id"):
        raise ValueError("Ellenőrzés előtt kötelező kiválasztani egy HouseBuild-változatot.")
    case.status = "review"
    case.submitted_at = utcnow()
    audit(db, actor=actor, action="technical_case.submitted", entity_type="technical_case", entity_id=case_id)
    db.commit()
    return get_case(db, case_id)


def review_gate(db: Session, case_id: str, gate_key: str, status: str, evidence: str, actor: str) -> dict:
    case = db.scalar(select(TechnicalCase).where(TechnicalCase.case_id == case_id))
    if not case:
        raise KeyError(case_id)
    if case.status != "review":
        raise ValueError("Kaput csak ellenőrzés alatt álló ügyön lehet értékelni.")
    if status not in {"pass", "fail", "not_applicable"}:
        raise ValueError("Érvénytelen kapueredmény.")
    gate = db.scalar(select(TechnicalGate).where(TechnicalGate.case_id == case_id, TechnicalGate.gate_key == gate_key))
    if not gate:
        raise KeyError(gate_key)
    if case.module_key == "buildconfig" and gate_key == "margin":
        raise ValueError("Az automatikus fedezeti kapu kézzel nem írható felül.")
    if gate.required and status == "not_applicable":
        raise ValueError("Kötelező kapu nem jelölhető nem alkalmazhatónak.")
    if len(evidence.strip()) < 3:
        raise ValueError("Az ellenőrzési bizonyíték kötelező.")
    before = {"status": gate.status, "evidence": gate.evidence}
    gate.status = status
    gate.evidence = evidence.strip()
    gate.checked_by = actor
    gate.checked_at = utcnow()
    audit(db, actor=actor, action="technical_gate.reviewed", entity_type="technical_gate", entity_id=f"{case_id}:{gate_key}", before=before, after={"status": status, "evidence": evidence})
    db.commit()
    return get_case(db, case_id)


def decide_case(db: Session, case_id: str, decision: str, reason: str, actor: str) -> dict:
    case = db.scalar(select(TechnicalCase).where(TechnicalCase.case_id == case_id))
    if not case:
        raise KeyError(case_id)
    if case.status != "review":
        raise ValueError("Csak ellenőrzés alatt álló ügy dönthető el.")
    gates = list(db.scalars(select(TechnicalGate).where(TechnicalGate.case_id == case_id)))
    if decision == "approved":
        if case.created_by.strip().lower() == actor.strip().lower():
            raise ValueError("A négy szem elve miatt a létrehozó nem hagyhatja jóvá a saját műszaki ügyét.")
        blockers = [gate.label for gate in gates if gate.required and gate.status != "pass"]
        if blockers:
            raise ValueError("Jóváhagyás előtt minden kötelező kapunak meg kell felelnie: " + ", ".join(blockers))
        case.status = "approved"
        case.approved_at = utcnow()
        case.approved_by = actor
        case.rejection_reason = None
        result = parse_json(case.result_json)
        if case.module_key == "housebuild-agent":
            result.update(
                {
                    "publication_allowed": True,
                    "released_configuration": result.get("selected_variant"),
                    "next_step": "HouseVision és ajánlatképzés",
                }
            )
        elif case.module_key == "plotcheck":
            result.update({"suitability": "suitable", "approved_for_design": True})
        elif case.module_key == "buildconfig":
            result.update({"offer_eligible": True})
        elif case.module_key == "plancheck":
            result.update({"compliant": True, "released_for_use": True})
        case.result_json = json.dumps(result, ensure_ascii=False, default=str)
    elif decision == "rejected":
        if len(reason.strip()) < 5:
            raise ValueError("Az elutasítás indoklása kötelező.")
        case.status = "rejected"
        case.rejection_reason = reason.strip()
        case.approved_at = None
        case.approved_by = None
    else:
        raise ValueError("Érvénytelen döntés.")
    audit(db, actor=actor, action=f"technical_case.{decision}", entity_type="technical_case", entity_id=case_id, after={"reason": reason})
    db.commit()
    return get_case(db, case_id)


def get_case(db: Session, case_id: str) -> dict:
    case = db.scalar(select(TechnicalCase).where(TechnicalCase.case_id == case_id))
    if not case:
        raise KeyError(case_id)
    gates = list(db.scalars(select(TechnicalGate).where(TechnicalGate.case_id == case_id).order_by(TechnicalGate.id)))
    return case_payload(case, gates)
