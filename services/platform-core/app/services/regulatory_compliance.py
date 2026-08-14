from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, func, or_, select, text
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

ENGINE_VERSION = "regulatory-compliance-v1"


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
    geometry: dict[str, Any], site: dict[str, Any], rules: dict[str, Any] | None
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
    findings: list[Finding] = []
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
    if any(item.outcome == "FAIL" for item in findings):
        return "FAIL", findings
    if any(item.outcome == "UNKNOWN" for item in findings):
        return "UNKNOWN", findings
    return "PASS", findings


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
        outcome, findings = evaluate_rules(geometry, site, rules)
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
        blocker_count=sum(item.severity == "BLOCKER" for item in findings),
        error_count=sum(item.severity == "ERROR" for item in findings),
        warning_count=sum(item.severity == "WARNING" for item in findings),
        engine_version=ENGINE_VERSION,
        completed_at=now,
        created_by=actor_subject_id,
    )
    db.add(run)
    for sequence, item in enumerate(findings, start=1):
        db.add(
            RegulatoryComplianceFinding(
                finding_id=_id("RCF"),
                run_id=run.run_id,
                finding_key=f"{sequence:04d}:{item.code}",
                code=item.code,
                severity=item.severity,
                outcome=item.outcome,
                rule_ref=item.rule_ref,
                source_ref=item.source_ref,
                geometry_path=item.geometry_path,
                measured_json=_json(item.measured),
                limit_json=_json(item.limit),
                explanation=item.explanation,
                remediation=item.remediation,
            )
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
    return _serialize_run(db, run)


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
    for row in sorted(sources, key=lambda item: item.source_snapshot_id):
        latest_revision = db.scalar(
            select(func.max(RegulatorySourceSnapshot.revision)).where(
                RegulatorySourceSnapshot.source_key == row.source_key
            )
        )
        source_state.append(
            {
                "id": row.source_snapshot_id,
                "key": row.source_key,
                "revision": row.revision,
                "latestRevision": latest_revision,
                "status": row.status,
                "securityStatus": row.security_status,
                "effective": _aware(row.effective_from) <= at
                and (row.effective_to is None or _aware(row.effective_to) >= at),
            }
        )
    interpretation_state: list[dict[str, Any]] = []
    for row in sorted(interpretations, key=lambda item: item.interpretation_id):
        latest_revision = db.scalar(
            select(func.max(RegulatoryRuleInterpretation.revision)).where(
                RegulatoryRuleInterpretation.source_snapshot_id == row.source_snapshot_id
            )
        )
        interpretation_state.append(
            {
                "id": row.interpretation_id,
                "sourceId": row.source_snapshot_id,
                "revision": row.revision,
                "latestRevision": latest_revision,
                "status": row.status,
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
