"""Create clearly marked, idempotent PlotCheck UAT scenarios in the configured database."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from sqlalchemy import select

from app.database import SessionLocal
from app.models import PlotCheckCase, PlotRuleSet
from app.services.plotcheck import (
    GATE_EVIDENCE,
    GATE_KEYS,
    add_action,
    add_evidence,
    assess_case,
    create_case,
    create_rule_set,
    finalize_case,
    review_gate,
    verify_evidence,
    verify_rule_set,
)

PROJECTS = {
    "PRJ-UAT-PLOTCHECK-FIT": {"width": "12", "depth": "10", "gfa": "190", "outcome": "FIT"},
    "PRJ-UAT-PLOTCHECK-CONDITIONAL": {"width": "12", "depth": "10", "gfa": "190", "outcome": "FIT WITH CONDITIONS"},
    "PRJ-UAT-PLOTCHECK-REDESIGN": {"width": "23", "depth": "18", "gfa": "500", "outcome": "RE-DESIGN REQUIRED"},
}


def identity(email: str, role: str) -> SimpleNamespace:
    return SimpleNamespace(email=email, role=role)


def ensure_rule(db) -> dict:
    row = db.scalar(select(PlotRuleSet).where(
        PlotRuleSet.municipality == "UAT Mintaváros",
        PlotRuleSet.zoning_code == "UAT-LKE-1",
        PlotRuleSet.lifecycle_status == "uat",
    ))
    if row:
        return {"rule_set_id": row.rule_set_id}
    rule = create_rule_set(db, {
        "municipality": "UAT Mintaváros", "zoning_code": "UAT-LKE-1", "version": "UAT-2026.08",
        "source_url": "https://example.invalid/uat/hesz", "source_document_version": "UAT-SYNTHETIC-v1",
        "source_note": "KIZÁRÓLAG SZINTETIKUS UAT TESZTADAT; üzleti vagy hatósági döntésre nem használható.",
        "lifecycle_status": "uat",
        "maximum_coverage_percent": "30", "maximum_floor_area_ratio": "0.5", "maximum_height_m": "6",
        "minimum_green_percent": "50", "front_setback_m": "5", "side_setback_m": "3", "rear_setback_m": "6",
        "allowed_uses": ["residential"],
    }, identity("uat-rule-author@imperial.local", "technical-prep"))
    return verify_rule_set(db, rule["rule_set_id"], identity("uat-rule-verifier@imperial.local", "designer"))


def seed_case(db, project_id: str, scenario: dict, rule: dict) -> dict:
    existing = db.scalar(select(PlotCheckCase).where(PlotCheckCase.project_id == project_id))
    if existing:
        from app.services.plotcheck import case_detail
        return case_detail(db, existing.case_id)
    detail = create_case(db, {
        "project_id": project_id, "title": f"SZINTETIKUS UAT – {scenario['outcome']}",
        "address": "9999 UAT Mintaváros, Tesztadat utca 1.", "parcel_number": f"UAT/{project_id[-3:]}",
        "municipality": "UAT Mintaváros", "zoning_code": "UAT-LKE-1", "rule_set_id": rule["rule_set_id"],
        "plot_width_m": "30", "plot_depth_m": "40", "declared_plot_area_m2": "1200",
        "proposed_width_m": scenario["width"], "proposed_depth_m": scenario["depth"],
        "proposed_gross_floor_area_m2": scenario["gfa"], "proposed_height_m": "5.2",
        "proposed_use": "residential", "house_id": "HOUSE-UAT-SYNTHETIC",
    }, "uat-pm@imperial.local")
    evidence_ids = {}
    for category in ("land_registry", "cadastral_map", "hesz", "townscape", "geodesy", "soil", "utilities", "access", "logistics"):
        digest = hashlib.sha256(f"{project_id}:{category}:synthetic-v1".encode()).hexdigest()
        detail = add_evidence(db, detail["case_id"], {
            "category": category, "source_reference": f"document://UAT/{project_id}/{category}",
            "source_version": "UAT-SYNTHETIC-v1", "source_sha256": digest,
            "note": f"SZINTETIKUS UAT {category} bizonyíték, valódi döntésre nem használható.",
        }, "uat-evidence-uploader@imperial.local")
        evidence_id = detail["evidence"][-1]["evidence_id"]
        verify_evidence(db, detail["case_id"], evidence_id, "uat-engineer@imperial.local")
        evidence_ids[category] = evidence_id
    if scenario["outcome"] == "FIT WITH CONDITIONS":
        add_action(db, detail["case_id"], {
            "condition": "SZINTETIKUS UAT: a felvonulási út ideiglenes megerősítése szükséges.",
            "owner": "uat-project-manager@imperial.local", "estimated_cost_huf": "1500000",
            "deadline_impact_days": "5", "design_impact": "A szintetikus logisztikai ütemterv módosul.",
        }, "uat-engineer@imperial.local")
    for gate_key in GATE_KEYS:
        review_gate(db, detail["case_id"], gate_key, {
            "decision": "approved", "note": f"SZINTETIKUS UAT {gate_key} kapu ellenőrizve.",
            "evidence_ids": [evidence_ids[key] for key in sorted(GATE_EVIDENCE[gate_key])],
        }, "uat-engineer@imperial.local")
    detail = assess_case(db, detail["case_id"], "uat-engineer@imperial.local")
    actual = detail["assessments"][0]["outcome"]
    if actual != scenario["outcome"]:
        raise RuntimeError(f"{project_id}: expected {scenario['outcome']}, got {actual}")
    return finalize_case(
        db, detail["case_id"], actual,
        "SZINTETIKUS UAT lezárás; valódi műszaki vagy üzleti döntésre nem használható.",
        identity("uat-final-approver@imperial.local", "managing-director"),
    )


def main() -> None:
    with SessionLocal() as db:
        rule = ensure_rule(db)
        results = [seed_case(db, project_id, scenario, rule) for project_id, scenario in PROJECTS.items()]
        for row in results:
            print(f"{row['project_id']} {row['case_id']} {row['status']} {row['final_report_document_id']}")


if __name__ == "__main__":
    main()
