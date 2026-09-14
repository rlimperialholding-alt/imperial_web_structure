from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import ConsistencyIssue, ProjectFact, ProjectRegistry
from ..schemas import FactIn


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upsert_fact(db: Session, fact: FactIn, *, actor: str = "api") -> ProjectFact:
    row = db.scalar(select(ProjectFact).where(
        ProjectFact.project_id == fact.project_id,
        ProjectFact.source_module == fact.source_module,
        ProjectFact.fact_key == fact.fact_key,
    ))
    value_json = json.dumps(fact.value, ensure_ascii=False, default=str)
    if not row:
        row = ProjectFact(project_id=fact.project_id, source_module=fact.source_module, fact_key=fact.fact_key, value_json=value_json)
        db.add(row)
    else:
        row.value_json = value_json
    audit(db, actor=actor, action="fact_upsert", entity_type="project_fact", entity_id=f"{fact.project_id}:{fact.source_module}:{fact.fact_key}", after=fact.model_dump(mode="json"))
    db.commit()
    db.refresh(row)
    return row


RULES = [
    ("CONTRACT_REVENUE_MATCH", "contract_generator", "approved_revenue", "finance", "approved_revenue", "critical", "A szerződéses ár és a Finance bevételi bázisa eltér"),
    ("BILLING_SCHEDULE_MATCH", "project_control", "billing_points_hash", "finance", "billing_points_hash", "critical", "A pénzügyi–műszaki ütemterv számlázási pontjai eltérnek"),
    ("CHANGE_TOTAL_MATCH", "change_control", "approved_change_revenue_total", "finance", "change_revenue_total", "high", "A jóváhagyott változtatások bevétele nincs teljesen átvezetve"),
    ("PROCUREMENT_COMMITMENT_MATCH", "procurement", "committed_total", "finance", "procurement_commitment_total", "high", "A beszerzési kötelezettség és a Finance kötelezettsége eltér"),
    ("DELIVERY_INVOICE_QUANTITY_MATCH", "procurement", "received_quantity_hash", "finance", "invoice_quantity_hash", "high", "A szállított mennyiség és a számlázott mennyiség eltér"),
    ("PHASE_ACCEPTANCE_MATCH", "calendar", "completed_phase_count", "project_control", "accepted_phase_count", "high", "A naptárban lezárt és műszakilag elfogadott fázisok eltérnek"),
    ("CUSTOMER_DECISION_MATCH", "myimperial", "customer_decision_status", "project_control", "customer_decision_status", "medium", "Az ügyfél- és belső projektstátusz eltér"),
]


def _decode(value_json: str) -> Any:
    try:
        return json.loads(value_json)
    except Exception:
        return value_json


def _as_decimal(value: Any) -> Decimal | None:
    try:
        if isinstance(value, (int, float, str)):
            return Decimal(str(value))
    except (InvalidOperation, ValueError):
        pass
    return None


def _equivalent(a: Any, b: Any) -> bool:
    da, db = _as_decimal(a), _as_decimal(b)
    if da is not None and db is not None:
        return abs(da - db) <= Decimal("1")
    return a == b


def _fingerprint(project_id: str, rule_code: str) -> str:
    return hashlib.sha256(f"{project_id}|{rule_code}".encode()).hexdigest()


def scan_consistency(db: Session, *, project_id: str | None = None, actor: str = "system") -> dict[str, int]:
    project_ids = [project_id] if project_id else list(db.scalars(select(ProjectRegistry.project_id)).all())
    detected = resolved = checked = 0
    for pid in project_ids:
        facts = db.scalars(select(ProjectFact).where(ProjectFact.project_id == pid)).all()
        fact_map = {(f.source_module, f.fact_key): f for f in facts}
        for rule_code, source_a, key_a, source_b, key_b, severity, title in RULES:
            checked += 1
            fa, fb = fact_map.get((source_a, key_a)), fact_map.get((source_b, key_b))
            fp = _fingerprint(pid, rule_code)
            issue = db.scalar(select(ConsistencyIssue).where(ConsistencyIssue.fingerprint == fp))
            if not fa or not fb:
                continue
            va, vb = _decode(fa.value_json), _decode(fb.value_json)
            if not _equivalent(va, vb):
                detected += 1
                financial = Decimal("0")
                da, dbv = _as_decimal(va), _as_decimal(vb)
                if da is not None and dbv is not None:
                    financial = abs(da - dbv)
                if not issue:
                    issue = ConsistencyIssue(
                        fingerprint=fp,
                        project_id=pid,
                        rule_code=rule_code,
                        title=title,
                        severity=severity,
                        status="open",
                        source_a=source_a,
                        value_a=json.dumps(va, ensure_ascii=False, default=str),
                        source_b=source_b,
                        value_b=json.dumps(vb, ensure_ascii=False, default=str),
                        financial_impact_huf=financial,
                        responsible="Adatgazda / modulfelelős",
                    )
                    db.add(issue)
                else:
                    issue.status = "open"
                    issue.value_a = json.dumps(va, ensure_ascii=False, default=str)
                    issue.value_b = json.dumps(vb, ensure_ascii=False, default=str)
                    issue.financial_impact_huf = financial
                    issue.last_detected_at = utcnow()
                    issue.occurrence_count += 1
                    issue.resolved_at = None
            elif issue and issue.status != "resolved":
                issue.status = "resolved"
                issue.resolved_at = utcnow()
                resolved += 1
    audit(db, actor=actor, action="consistency_scan", entity_type="system", after={"checked": checked, "detected": detected, "resolved": resolved})
    db.commit()
    return {"projects": len(project_ids), "checked": checked, "detected": detected, "resolved": resolved}
