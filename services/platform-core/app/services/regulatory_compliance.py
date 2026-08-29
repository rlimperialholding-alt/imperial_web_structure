from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, func, insert, or_, select, text
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    HouseDesignRevision,
    HouseDesignSession,
    RegulatoryComplianceFinding,
    RegulatoryComplianceRun,
    RegulatoryRuleInterpretation,
    RegulatoryRuleSet,
    RegulatorySourceSnapshot,
)
from .house_designer import decode_revision_site
from .house_designer_geometry import gross_area_m2
from .regulatory_rule_schema import (
    RULE_SCHEMA_VERSION,
    RegulatoryRuleSchemaError,
    normalize_declarative_rules,
)

ENGINE_VERSION = "regulatory-compliance-v2"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    outcome: str
    explanation: str
    remediation: str
    rule_ref: str
    source_ref: str
    measured: dict[str, Any]
    limit: dict[str, Any]
    geometry_path: str | None = None


def evaluate_rules(
    geometry: dict[str, Any],
    site: dict[str, Any],
    rules: dict[str, Any] | None,
    configuration: dict[str, Any] | None = None,
) -> tuple[str, list[Finding]]:
    if site.get("verificationStatus") != "verified":
        return "UNKNOWN", [
            Finding(
                code="SITE_UNVERIFIED",
                severity="BLOCKER",
                outcome="UNKNOWN",
                explanation="A telek és a helyrajzi szám forrása még nincs igazolva.",
                remediation=(
                    "Igazolja a telekazonosítót és a hozzá tartozó helyi szabályforrásokat."
                ),
                rule_ref="HD-001/site-verification",
                source_ref="missing",
                measured={"verificationStatus": site.get("verificationStatus", "missing")},
                limit={"required": "verified"},
            )
        ]
    if rules is None:
        return "UNKNOWN", [
            Finding(
                code="RULESET_MISSING",
                severity="BLOCKER",
                outcome="UNKNOWN",
                explanation=(
                    "A telekhez nincs hatályos, jóváhagyott országos és helyi szabálykészlet."
                ),
                remediation=(
                    "Készítse el és külön szakmai szereplővel hagyassa jóvá "
                    "a HÉSZ/TÉKA szabálykészletet."
                ),
                rule_ref="HD-001/ruleset-selection",
                source_ref="missing",
                measured={},
                limit={"required": "latest-approved"},
            )
        ]
    if not isinstance(rules, dict):
        return "UNKNOWN", [_schema_finding("ruleset_not_object")]
    findings: list[Finding] = []
    executed_rule_count = 0
    checks = (
        (
            "MAX_STOREYS",
            len(geometry.get("levels", [])),
            rules.get("maxStoreys"),
            "levels",
            "A szintek száma meghaladja az övezetben megengedett értéket.",
        ),
        (
            "MAX_GROSS_AREA",
            Decimal(str(gross_area_m2(geometry))),
            _decimal_or_none(rules.get("maxGrossAreaM2")),
            "levels",
            "A bruttó szintterület meghaladja a jóváhagyott szabály határát.",
        ),
    )
    for code, measured, limit, path, message in checks:
        if limit is not None:
            executed_rule_count += 1
        if limit is not None and measured > limit:
            findings.append(
                Finding(
                    code=code,
                    severity="BLOCKER",
                    outcome="FAIL",
                    explanation=message,
                    remediation="Módosítsa a terv méretét vagy szintszámát.",
                    rule_ref=f"rules.{code}",
                    source_ref=str(rules.get("sourceRef") or "approved-ruleset"),
                    measured={"value": str(measured)},
                    limit={"maximum": str(limit)},
                    geometry_path=path,
                )
            )
    allowed_roofs = set(rules.get("allowedRoofTypes") or [])
    if allowed_roofs:
        executed_rule_count += 1
    roofs = {
        str(level["roof"]["type"]) for level in geometry.get("levels", []) if level.get("roof")
    }
    if allowed_roofs and not roofs:
        findings.append(
            Finding(
                code="ROOF_NOT_SELECTED",
                severity="BLOCKER",
                outcome="UNKNOWN",
                explanation="A tetőforma még nincs kiválasztva, ezért nem ellenőrizhető.",
                remediation="Válasszon a megengedett tetőformák közül.",
                rule_ref="rules.allowedRoofTypes",
                source_ref=str(rules.get("sourceRef") or "approved-ruleset"),
                measured={"selected": []},
                limit={"allowed": sorted(allowed_roofs)},
                geometry_path="levels[].roof",
            )
        )
    elif allowed_roofs and not roofs <= allowed_roofs:
        findings.append(
            Finding(
                code="ROOF_TYPE_FORBIDDEN",
                severity="BLOCKER",
                outcome="FAIL",
                explanation="A kiválasztott tetőforma nem megengedett ezen a telken.",
                remediation=(
                    "Válasszon a HÉSZ/településképi szabály szerint megengedett tetőformát."
                ),
                rule_ref="rules.allowedRoofTypes",
                source_ref=str(rules.get("sourceRef") or "approved-ruleset"),
                measured={"selected": sorted(roofs)},
                limit={"allowed": sorted(allowed_roofs)},
                geometry_path="levels[].roof",
            )
        )
    declarative = rules.get("checks")
    if declarative is not None:
        if rules.get("schemaVersion") != RULE_SCHEMA_VERSION:
            return "UNKNOWN", [_schema_finding("rule_schema_version_invalid")]
        try:
            normalized = normalize_declarative_rules(declarative)
        except RegulatoryRuleSchemaError as error:
            return "UNKNOWN", [_schema_finding(error.code)]
        executed_rule_count += len(normalized)
        try:
            facts = _compliance_facts(geometry, site, configuration or {})
        except (ArithmeticError, KeyError, TypeError, ValueError):
            return "UNKNOWN", [_schema_finding("fact_extraction_failed")]
        findings.extend(_evaluate_declarative_rules(normalized, facts))
    if executed_rule_count == 0:
        return "UNKNOWN", [_schema_finding("ruleset_empty")]
    if any(
        item.outcome == "FAIL" and item.severity in {"BLOCKER", "ERROR"}
        for item in findings
    ):
        return "FAIL", findings
    if any(
        item.outcome == "UNKNOWN" and item.severity in {"BLOCKER", "ERROR"}
        for item in findings
    ):
        return "UNKNOWN", findings
    return "PASS", findings


def _evaluate_declarative_rules(
    rules: list[dict[str, Any]], facts: dict[str, Any]
) -> list[Finding]:
    findings: list[Finding] = []
    for rule in rules:
        measured = facts.get(rule["fact"])
        operator = rule["operator"]
        # Numerikus összehasonlításoknál a határértéket szabályonként egyszer
        # konvertáljuk Decimal-lá, ne lelemezésenként többször (500 szabály
        # alatt ez a coverage-tracing mellett a kiértékelés domináns költsége).
        expected = (
            Decimal(str(rule["expected"]))
            if operator in {"lte", "gte"}
            else rule["expected"]
        )
        if measured is None:
            outcome = "UNKNOWN"
            explanation = f"A(z) {rule['fact']} hitelesített tény nem áll rendelkezésre."
        else:
            outcome = "PASS" if _compare(measured, operator, expected) else "FAIL"
            explanation = (
                "A szabály teljesült."
                if outcome == "PASS"
                else rule["explanation"]
            )
        findings.append(
            Finding(
                code=rule["code"],
                severity=rule["severity"],
                outcome=outcome,
                explanation=explanation,
                remediation="" if outcome == "PASS" else rule["remediation"],
                rule_ref=rule["ruleRef"],
                source_ref=rule["sourceRef"],
                measured={"fact": rule["fact"], "value": _json_value(measured)},
                limit={"operator": rule["operator"], "expected": rule["expected"]},
                geometry_path=rule.get("geometryPath"),
            )
        )
    return findings


def _compare(measured: Any, operator: str, expected: Any) -> bool:
    if operator in {"lte", "gte"}:
        # A mért tényeket a _compliance_facts már Decimal-ként adja, a
        # határértéket a hívó konvertálja: nincs szükség ismételt str/Decimal
        # körre. Más hívóktól érkező nyers értékek ugyanúgy konvertálódnak.
        left = measured if isinstance(measured, Decimal) else Decimal(str(measured))
        right = expected if isinstance(expected, Decimal) else Decimal(str(expected))
        return left <= right if operator == "lte" else left >= right
    if operator == "eq":
        if isinstance(measured, Decimal):
            return measured == Decimal(str(expected))
        return measured == expected
    if operator == "in":
        return str(measured) in set(expected)
    measured_values = {str(item) for item in measured}
    expected_values = set(expected)
    if operator == "subset":
        return measured_values <= expected_values
    if operator == "contains":
        return expected_values <= measured_values
    if operator == "contains_any":
        return bool(measured_values & expected_values)
    return False


def _compliance_facts(
    geometry: dict[str, Any], site: dict[str, Any], configuration: dict[str, Any]
) -> dict[str, Any]:
    raw_levels = geometry.get("levels")
    levels: list[Any] = raw_levels if isinstance(raw_levels, list) else []
    ground_area = _polygon_area_m2(levels[0].get("outerBoundary")) if levels else None
    gross_area = Decimal(str(gross_area_m2(geometry))) if levels else None
    heights = [
        Decimal(str(int(level.get("elevationMm") or 0) + int(level.get("heightMm") or 0)))
        / Decimal("1000")
        for level in levels
    ]
    rooms = [room for level in levels for room in (level.get("rooms") or [])]
    measured_room_areas = [_polygon_area_m2(room.get("polygon")) for room in rooms]
    room_areas = [area for area in measured_room_areas if area is not None]
    room_heights = [
        Decimal(str(int(level.get("heightMm") or 0))) / Decimal("1000")
        for level in levels
        if level.get("rooms")
    ]
    roofs = [level.get("roof") for level in levels if isinstance(level.get("roof"), dict)]
    roof_pitches = [Decimal(str(roof["pitchDeg"])) for roof in roofs if "pitchDeg" in roof]
    raw_verified = site.get("verifiedFacts")
    verified: dict[str, Any] = raw_verified if isinstance(raw_verified, dict) else {}
    plot_area = _decimal_fact(verified.get("plotAreaM2"))
    green_area = _decimal_fact(verified.get("greenAreaM2"))
    facts: dict[str, Any] = {
        "building.storeys": Decimal(len(levels)),
        "building.footprint_area_m2": ground_area,
        "building.gross_area_m2": gross_area,
        "building.height_m": max(heights) if heights else None,
        "building.site_coverage_percent": (
            ground_area * Decimal("100") / plot_area
            if ground_area is not None and plot_area and plot_area > 0
            else None
        ),
        "building.floor_area_ratio": (
            gross_area / plot_area
            if gross_area is not None and plot_area and plot_area > 0
            else None
        ),
        "rooms.count": Decimal(len(rooms)),
        "rooms.min_area_m2": min(room_areas) if room_areas else None,
        "rooms.min_height_m": min(room_heights) if room_heights else None,
        "roof.min_pitch_deg": min(roof_pitches) if roof_pitches else None,
        "roof.max_pitch_deg": max(roof_pitches) if roof_pitches else None,
        "roof.types": sorted({str(roof.get("type")) for roof in roofs if roof.get("type")}) or None,
        "site.zoning_code": _text_fact(verified.get("zoningCode")),
        "site.building_mode": _text_fact(verified.get("buildingMode")),
        "site.allowed_uses": _collection_fact(verified.get("allowedUses")),
        "site.green_area_percent": (
            green_area * Decimal("100") / plot_area
            if green_area is not None and plot_area and plot_area > 0
            else None
        ),
        "site.front_setback_m": _decimal_fact(verified.get("frontSetbackM")),
        "site.side_setback_m": _decimal_fact(verified.get("sideSetbackM")),
        "site.rear_setback_m": _decimal_fact(verified.get("rearSetbackM")),
        "site.parking_spaces": _decimal_fact(verified.get("parkingSpaces")),
        "site.access_verified": _boolean_fact(verified.get("accessVerified")),
        "site.utilities_verified": _boolean_fact(verified.get("utilitiesVerified")),
        "site.protection_clear": _boolean_fact(verified.get("protectionClear")),
        "building.stair_data_complete": True if len(levels) == 1 else bool(
            geometry.get("verticalCores") and geometry.get("verticalConnections")
        ),
        "building.accessibility_data_complete": _boolean_fact(
            configuration.get("accessibilityDataComplete")
        ),
        "handoff.fire_data_complete": _boolean_fact(configuration.get("fireDataComplete")),
        "handoff.energy_data_complete": _boolean_fact(configuration.get("energyDataComplete")),
    }
    return facts


def _polygon_area_m2(points: Any) -> Decimal | None:
    if not isinstance(points, list) or len(points) < 4 or points[0] != points[-1]:
        return None
    try:
        area_twice = sum(
            int(first["x"]) * int(second["y"]) - int(second["x"]) * int(first["y"])
            for first, second in zip(points, points[1:], strict=False)
        )
    except (KeyError, TypeError, ValueError):
        return None
    return Decimal(abs(area_twice)) / Decimal("2000000")


def _decimal_fact(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _text_fact(value: Any) -> str | None:
    text_value = str(value).strip() if value is not None else ""
    return text_value or None


def _collection_fact(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result = sorted({str(item).strip() for item in value if str(item).strip()})
    return result or None


def _boolean_fact(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _schema_finding(reason: str) -> Finding:
    return Finding(
        code="RULESET_SCHEMA_INVALID",
        severity="BLOCKER",
        outcome="UNKNOWN",
        explanation="A szabálykészlet végrehajtható sémája hiányos vagy érvénytelen.",
        remediation="Készítsen új, validált és négy-szem elvvel jóváhagyott szabálykészletet.",
        rule_ref="HD-001/ruleset-schema",
        source_ref="ruleset",
        measured={"reason": reason},
        limit={"schemaVersion": RULE_SCHEMA_VERSION},
    )


def run_compliance(
    db: Session,
    *,
    session_id: str,
    tenant_id: str,
    actor_subject_id: str,
) -> dict[str, Any]:
    session = db.scalar(
        select(HouseDesignSession)
        .where(
            HouseDesignSession.session_id == session_id,
            HouseDesignSession.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if session is None:
        raise KeyError(session_id)
    revision = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == session.current_revision_id
        )
    )
    if revision is None:
        raise ValueError("current_revision_missing")
    geometry = json.loads(revision.geometry_json)
    site = decode_revision_site(revision)
    now = datetime.now(UTC)
    scope_key = _scope_key(site)
    ruleset = None
    if scope_key:
        _lock_scope(db, scope_key)
        ruleset = db.scalar(
            select(RegulatoryRuleSet)
            .where(
                RegulatoryRuleSet.scope_key.in_([scope_key, _municipality_scope(site)]),
                RegulatoryRuleSet.status == "APPROVED",
                RegulatoryRuleSet.effective_from <= now,
                or_(
                    RegulatoryRuleSet.effective_to.is_(None),
                    RegulatoryRuleSet.effective_to >= now,
                ),
            )
            .order_by(desc(RegulatoryRuleSet.revision))
            .with_for_update()
        )
    binding_state = _ruleset_binding_state(db, ruleset, now) if ruleset else None
    binding_issue = _binding_issue(binding_state) if binding_state else None
    rules = json.loads(ruleset.rules_json) if ruleset and binding_issue is None else None
    if ruleset is not None and binding_issue is not None:
        outcome = "UNKNOWN"
        findings = [
            Finding(
                code="RULESET_CHANGED",
                severity="BLOCKER",
                outcome="UNKNOWN",
                explanation=(
                    "A kiválasztott szabálykészlet forrás- vagy értelmezéskötése "
                    "már nem aktuális, ezért abból új megfelelőségi PASS nem adható."
                ),
                remediation=(
                    "Készítsen új, a legfrissebb jóváhagyott forrásokra és "
                    "értelmezésekre kötött szabálykészletet."
                ),
                rule_ref="HD-001/ruleset-binding",
                source_ref=ruleset.ruleset_id,
                measured={"bindingIssue": binding_issue},
                limit={"required": "latest-active-approved-bindings"},
            )
        ]
    else:
        configuration = json.loads(revision.configuration_json)
        outcome, findings = evaluate_rules(geometry, site, rules, configuration)
    input_hash = _sha(
        {
            "revision": revision.canonical_sha256,
            "ruleset": ruleset.canonical_sha256 if ruleset else None,
            "rulesetBinding": binding_state,
            "engine": ENGINE_VERSION,
        }
    )
    existing = db.scalar(
        select(RegulatoryComplianceRun).where(
            RegulatoryComplianceRun.revision_id == revision.revision_id,
            RegulatoryComplianceRun.ruleset_id == (ruleset.ruleset_id if ruleset else None),
            RegulatoryComplianceRun.input_sha256 == input_hash,
        )
    )
    if existing:
        return _serialize_run(db, existing)
    run = RegulatoryComplianceRun(
        run_id=_id("RCR"),
        session_id=session_id,
        revision_id=revision.revision_id,
        ruleset_id=ruleset.ruleset_id if ruleset else None,
        ruleset_sha256=ruleset.canonical_sha256 if ruleset else None,
        input_sha256=input_hash,
        outcome=outcome,
        blocker_count=sum(
            item.severity == "BLOCKER" and item.outcome != "PASS" for item in findings
        ),
        error_count=sum(item.severity == "ERROR" and item.outcome != "PASS" for item in findings),
        warning_count=sum(
            item.severity == "WARNING" and item.outcome != "PASS" for item in findings
        ),
        engine_version=ENGINE_VERSION,
        completed_at=now,
        created_by=actor_subject_id,
    )
    db.add(run)
    # A run sora a lelemezések előtt flush-ölve kerül az adatbázisba, így a
    # Core-executemany sorai a hivatkozott run_id-val azonnal írhatók. Az 500
    # lelemezés ORM-objektumonkénti add + flush-lista helyett egyetlen batch
    # INSERT-ként íródik -- szemantikailag azonos sorok, nagyságrenddel kisebb
    # Python- és coverage-költséggel (Task43 p95 root-cause remediáció).
    db.flush()
    if findings:
        db.execute(
            insert(RegulatoryComplianceFinding),
            [
                {
                    "finding_id": _id("RCF"),
                    "run_id": run.run_id,
                    "finding_key": f"{sequence:04d}:{item.code}",
                    "code": item.code,
                    "severity": item.severity,
                    "outcome": item.outcome,
                    "rule_ref": item.rule_ref,
                    "source_ref": item.source_ref,
                    "geometry_path": item.geometry_path,
                    "measured_json": _json(item.measured),
                    "limit_json": _json(item.limit),
                    "explanation": item.explanation,
                    "remediation": item.remediation,
                    "created_at": now,
                }
                for sequence, item in enumerate(findings, start=1)
            ],
        )
    session.status = "CHECKED" if outcome == "PASS" else "CHECK_REQUIRED"
    session.updated_by = actor_subject_id
    session.row_version += 1
    audit(
        db,
        actor=actor_subject_id,
        action="house_designer.compliance.run",
        entity_type="HouseDesignSession",
        entity_id=session_id,
        after={"run_id": run.run_id, "outcome": outcome, "input_sha256": input_hash},
    )
    db.commit()
    return _serialize_fresh_run(run, findings)


def latest_compliance_result(
    db: Session, *, session_id: str, revision_id: str
) -> dict[str, Any] | None:
    run = db.scalar(
        select(RegulatoryComplianceRun)
        .where(
            RegulatoryComplianceRun.session_id == session_id,
            RegulatoryComplianceRun.revision_id == revision_id,
        )
        .order_by(desc(RegulatoryComplianceRun.completed_at), desc(RegulatoryComplianceRun.id))
    )
    return _serialize_run(db, run) if run is not None else None


def _serialize_run(db: Session, run: RegulatoryComplianceRun) -> dict[str, Any]:
    rows = db.scalars(
        select(RegulatoryComplianceFinding)
        .where(RegulatoryComplianceFinding.run_id == run.run_id)
        .order_by(RegulatoryComplianceFinding.finding_key)
    ).all()
    return {
        "runId": run.run_id,
        "outcome": run.outcome,
        "rulesetId": run.ruleset_id,
        "inputSha256": run.input_sha256,
        "findings": [
            {
                "code": row.code,
                "severity": row.severity,
                "outcome": row.outcome,
                "explanation": row.explanation,
                "remediation": row.remediation,
                "ruleRef": row.rule_ref,
                "sourceRef": row.source_ref,
                "geometryPath": row.geometry_path,
                "measured": json.loads(row.measured_json),
                "limit": json.loads(row.limit_json),
            }
            for row in rows
        ],
    }


def _serialize_fresh_run(
    run: RegulatoryComplianceRun, findings: list[Finding]
) -> dict[str, Any]:
    """A frissen kiírt futtatást a memóriában lévő lelemezésekből szerializálja.

    Az eredmény bájtra azonos a `_serialize_run` adatbázis-útvonalával: a
    measured/limit mezők ugyanazon `_json` + `json.loads` körön mennek át, a
    lelemezések sorrendje pedig a beszúráskor rögzített finding_key sorrend
    (a DB-útvonal e szerint rendez). A friss útvonal így nem olvassa vissza
    a 500 lelemezést, ami a coverage-tracing alatti p95-ünk fő költsége volt.
    """
    return {
        "runId": run.run_id,
        "outcome": run.outcome,
        "rulesetId": run.ruleset_id,
        "inputSha256": run.input_sha256,
        "findings": [
            {
                "code": item.code,
                "severity": item.severity,
                "outcome": item.outcome,
                "explanation": item.explanation,
                "remediation": item.remediation,
                "ruleRef": item.rule_ref,
                "sourceRef": item.source_ref,
                "geometryPath": item.geometry_path,
                "measured": json.loads(_json(item.measured)),
                "limit": json.loads(_json(item.limit)),
            }
            for item in findings
        ],
    }


def _scope_key(site: dict[str, Any]) -> str:
    municipality = str(site.get("municipalityCode") or "").strip()
    parcel = str(site.get("parcelNumber") or "").strip()
    return f"HU:{municipality}:{parcel}" if municipality and parcel else ""


def _municipality_scope(site: dict[str, Any]) -> str:
    municipality = str(site.get("municipalityCode") or "").strip()
    return f"HU:{municipality}:*" if municipality else ""


def _lock_scope(db: Session, scope_key: str) -> None:
    """Serialize ruleset selection with regulatory revisions on PostgreSQL."""

    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"house-designer-regulatory:{_municipality_scope_from_key(scope_key)}"},
        )


def _municipality_scope_from_key(scope_key: str) -> str:
    parts = scope_key.split(":")
    return f"{parts[0]}:{parts[1]}:*" if len(parts) >= 2 else scope_key


def _ruleset_binding_state(db: Session, ruleset: RegulatoryRuleSet, at: datetime) -> dict[str, Any]:
    source_ids = sorted(set(json.loads(ruleset.source_snapshot_ids_json)))
    interpretation_ids = sorted(set(json.loads(ruleset.interpretation_ids_json)))
    sources = db.scalars(
        select(RegulatorySourceSnapshot).where(
            RegulatorySourceSnapshot.source_snapshot_id.in_(source_ids)
        )
    ).all()
    interpretations = db.scalars(
        select(RegulatoryRuleInterpretation).where(
            RegulatoryRuleInterpretation.interpretation_id.in_(interpretation_ids)
        )
    ).all()
    source_state: list[dict[str, Any]] = []
    for source_row in sorted(sources, key=lambda item: item.source_snapshot_id):
        latest_source_revision = db.scalar(
            select(func.max(RegulatorySourceSnapshot.revision)).where(
                RegulatorySourceSnapshot.source_key == source_row.source_key
            )
        )
        source_state.append(
            {
                "id": source_row.source_snapshot_id,
                "key": source_row.source_key,
                "revision": source_row.revision,
                "latestRevision": latest_source_revision,
                "status": source_row.status,
                "securityStatus": source_row.security_status,
                "effective": _aware(source_row.effective_from) <= at
                and (source_row.effective_to is None or _aware(source_row.effective_to) >= at),
            }
        )
    interpretation_state: list[dict[str, Any]] = []
    for interpretation_row in sorted(interpretations, key=lambda item: item.interpretation_id):
        latest_interpretation_revision = db.scalar(
            select(func.max(RegulatoryRuleInterpretation.revision)).where(
                RegulatoryRuleInterpretation.source_snapshot_id
                == interpretation_row.source_snapshot_id
            )
        )
        interpretation_state.append(
            {
                "id": interpretation_row.interpretation_id,
                "sourceId": interpretation_row.source_snapshot_id,
                "revision": interpretation_row.revision,
                "latestRevision": latest_interpretation_revision,
                "status": interpretation_row.status,
            }
        )
    return {
        "sourceIds": source_ids,
        "sources": source_state,
        "interpretationIds": interpretation_ids,
        "interpretations": interpretation_state,
    }


def _binding_issue(state: dict[str, Any]) -> str | None:
    if not state["sourceIds"] or len(state["sources"]) != len(state["sourceIds"]):
        return "source_missing"
    if not state["interpretationIds"] or len(state["interpretations"]) != len(
        state["interpretationIds"]
    ):
        return "interpretation_missing"
    source_ids = set(state["sourceIds"])
    for row in state["sources"]:
        if row["status"] != "active" or row["securityStatus"] != "approved":
            return "source_inactive"
        if row["revision"] != row["latestRevision"]:
            return "source_not_latest"
        if not row["effective"]:
            return "source_not_effective"
    for row in state["interpretations"]:
        if row["status"] != "APPROVED":
            return "interpretation_not_approved"
        if row["revision"] != row["latestRevision"]:
            return "interpretation_not_latest"
        if row["sourceId"] not in source_ids:
            return "interpretation_source_mismatch"
    return None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _decimal_or_none(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex.upper()}"
