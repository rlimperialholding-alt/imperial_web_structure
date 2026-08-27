from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ConsistencyIssue, PilotRun
from ..schemas import EventIn, FactIn
from .consistency import scan_consistency, upsert_fact
from .integration import ingest_event, process_outbox


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _event(project_id: str, source: str, event_type: str, *, payload: dict, severity: str = "info", financial: int = 0, days: int = 0, executive: bool = False, object_type: str | None = None, object_id: str | None = None) -> EventIn:
    token = uuid.uuid4().hex[:10].upper()
    return EventIn(
        event_id=f"EVT-{token}",
        dedupe_key=f"PILOT:{project_id}:{source}:{event_type}:{token}",
        project_id=project_id,
        source_module=source,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        severity=severity,
        financial_impact_huf=Decimal(financial),
        deadline_impact_days=days,
        executive_relevance=executive,
        responsible="Pilot felelős",
        payload=payload,
    )


def run_pilot_scenario(db: Session, scenario: str) -> PilotRun:
    scenarios = {
        "preconstruction": ("PILOT-HOUSE-001", "Családi ház – előkészítés"),
        "active_procurement": ("PILOT-BUILD-002", "Aktív kivitelezés – beszerzés"),
        "change_warranty": ("PILOT-CHANGE-003", "Változtatás és garancia"),
    }
    if scenario not in scenarios:
        raise ValueError("Ismeretlen pilot forgatókönyv.")
    project_id, name = scenarios[scenario]
    pilot = PilotRun(
        pilot_id=f"PILOTRUN-{uuid.uuid4().hex[:12].upper()}",
        name=name,
        project_id=project_id,
        scenario=scenario,
        status="running",
        started_at=utcnow(),
    )
    db.add(pilot)
    db.flush()
    steps: list[dict] = []

    def run_step(label: str, fn):
        try:
            result = fn()
            steps.append({"step": label, "status": "passed", "result": result})
        except Exception as exc:  # pragma: no cover - diagnostic path
            steps.append({"step": label, "status": "failed", "error": str(exc)})

    if scenario == "preconstruction":
        run_step("Szerződés esemény", lambda: ingest_event(db, _event(project_id, "contract_generator", "CONTRACT_SIGNED", payload={"project_name": name, "customer_name": "Pilot ügyfél", "summary": "Szerződés aláírva"}, financial=65_000_000, object_type="Contract", object_id="CTR-PILOT-001"))[1])
        run_step("Projekt létrehozás", lambda: ingest_event(db, _event(project_id, "crm", "PROJECT_CREATED", payload={"project_name": name, "project_type": "family_house"}, object_type="Project", object_id=project_id))[1])
        run_step("Ütemterv jóváhagyás", lambda: ingest_event(db, _event(project_id, "project_control", "SCHEDULE_APPROVED", payload={"project_name": name, "summary": "Pénzügyi–műszaki ütemterv jóváhagyva"}, object_type="Schedule", object_id="SCH-PILOT-001"))[1])
        for src, key, value in [
            ("contract_generator", "approved_revenue", 65_000_000),
            ("finance", "approved_revenue", 65_000_000),
            ("project_control", "billing_points_hash", "sha-billing-001"),
            ("finance", "billing_points_hash", "sha-billing-001"),
            ("myimperial", "customer_decision_status", "approved"),
            ("project_control", "customer_decision_status", "approved"),
        ]:
            run_step(f"Tényadat: {src}.{key}", lambda src=src, key=key, value=value: upsert_fact(db, FactIn(project_id=project_id, source_module=src, fact_key=key, value=value)).id)
        run_step("Konzisztenciavizsgálat", lambda: scan_consistency(db, project_id=project_id))

    elif scenario == "active_procurement":
        run_step("Beszerzési rendelés", lambda: ingest_event(db, _event(project_id, "procurement", "PROCUREMENT_ORDERED", payload={"project_name": name, "summary": "Tetőanyag megrendelve"}, financial=8_500_000, object_type="PurchaseOrder", object_id="PO-PILOT-002"))[1])
        run_step("Szállítólevél-hiány esemény", lambda: ingest_event(db, _event(project_id, "procurement", "DELIVERY_NOTE_MISSING", payload={"project_name": name, "summary": "Szállítólevél nincs feltöltve"}, severity="critical", financial=2_500_000, executive=True, object_type="Delivery", object_id="DEL-PILOT-002"))[1])
        for src, key, value in [
            ("procurement", "committed_total", 8_500_000),
            ("finance", "procurement_commitment_total", 8_500_000),
            ("procurement", "received_quantity_hash", "qty-hash-002"),
            ("finance", "invoice_quantity_hash", "qty-hash-002"),
            ("calendar", "completed_phase_count", 4),
            ("project_control", "accepted_phase_count", 4),
        ]:
            run_step(f"Tényadat: {src}.{key}", lambda src=src, key=key, value=value: upsert_fact(db, FactIn(project_id=project_id, source_module=src, fact_key=key, value=value)).id)
        run_step("Konzisztenciavizsgálat", lambda: scan_consistency(db, project_id=project_id))
        run_step("Outbox továbbítás", lambda: process_outbox(db, simulate_success=True))

    else:
        run_step("Jóváhagyott változtatás", lambda: ingest_event(db, _event(project_id, "change_control", "CHANGE_APPROVED", payload={"project_name": name, "summary": "Ügyfél által jóváhagyott pótmunka"}, financial=3_200_000, object_type="Change", object_id="CHG-PILOT-003"))[1])
        run_step("Garanciális ügy", lambda: ingest_event(db, _event(project_id, "imperial_care", "WARRANTY_CASE_OPENED", payload={"project_name": name, "summary": "Nyílászáró beállítási ügy"}, severity="high", executive=True, object_type="WarrantyCase", object_id="WAR-PILOT-003"))[1])
        run_step("Eltérő ChangeControl tény", lambda: upsert_fact(db, FactIn(project_id=project_id, source_module="change_control", fact_key="approved_change_revenue_total", value=3_200_000)).id)
        run_step("Eltérő Finance tény", lambda: upsert_fact(db, FactIn(project_id=project_id, source_module="finance", fact_key="change_revenue_total", value=2_900_000)).id)
        run_step("Eltérés felismerése", lambda: scan_consistency(db, project_id=project_id))
        run_step("Finance korrekció", lambda: upsert_fact(db, FactIn(project_id=project_id, source_module="finance", fact_key="change_revenue_total", value=3_200_000)).id)
        run_step("Eltérés automatikus lezárása", lambda: scan_consistency(db, project_id=project_id))

    pilot.steps_total = len(steps)
    pilot.steps_passed = sum(1 for s in steps if s["status"] == "passed")
    pilot.status = "passed" if pilot.steps_passed == pilot.steps_total else "failed"
    pilot.completed_at = utcnow()
    pilot.result_json = json.dumps(steps, ensure_ascii=False, default=str)
    db.commit()
    db.refresh(pilot)
    return pilot


def run_all_pilots(db: Session) -> list[PilotRun]:
    return [run_pilot_scenario(db, s) for s in ("preconstruction", "active_procurement", "change_warranty")]
