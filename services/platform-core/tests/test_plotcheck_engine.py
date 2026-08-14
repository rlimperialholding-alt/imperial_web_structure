from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

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


def user(email: str, role: str = "technical-prep") -> SimpleNamespace:
    return SimpleNamespace(email=email, role=role)


def verified_rule(db):
    rule = create_rule_set(
        db,
        {
            "municipality": "Mintaváros",
            "zoning_code": "LKE-1",
            "version": "HÉSZ-2026.08",
            "source_url": "https://example.invalid/hesz-2026",
            "source_document_version": "2026/8 kihirdetett",
            "source_note": "Kihirdetett önkormányzati rendelet ellenőrzött digitális példánya.",
            "maximum_coverage_percent": "30",
            "maximum_floor_area_ratio": "0.5",
            "maximum_height_m": "6.0",
            "minimum_green_percent": "50",
            "front_setback_m": "5",
            "side_setback_m": "3",
            "rear_setback_m": "6",
            "allowed_uses": ["residential"],
        },
        user("rule-author@imperial.local"),
    )
    return verify_rule_set(db, rule["rule_set_id"], user("rule-reviewer@imperial.local", "designer"))


def plot_case(db, rule):
    return create_case(
        db,
        {
            "project_id": "PRJ-PLOT-UAT-001",
            "title": "Kanonikus telekalkalmasság",
            "address": "1234 Mintaváros, Próba utca 1.",
            "parcel_number": "1234/5",
            "municipality": "Mintaváros",
            "zoning_code": "LKE-1",
            "rule_set_id": rule["rule_set_id"],
            "plot_width_m": "30",
            "plot_depth_m": "40",
            "declared_plot_area_m2": "1200",
            "proposed_width_m": "12",
            "proposed_depth_m": "10",
            "proposed_gross_floor_area_m2": "190",
            "proposed_height_m": "5.2",
            "proposed_use": "residential",
            "house_id": "HOUSE-UAT-001",
        },
        "pm@imperial.local",
    )


def test_demo_rule_cannot_be_verified_or_used(db):
    rule = create_rule_set(
        db,
        {
            "municipality": "Demo",
            "zoning_code": "D-1",
            "version": "demo-1",
            "lifecycle_status": "demo",
            "source_url": "https://example.invalid/demo",
            "source_document_version": "demo",
            "source_note": "Kizárólag felületi és oktatási tesztelésre szolgáló szabály.",
            "maximum_coverage_percent": "30",
            "maximum_floor_area_ratio": "0.5",
            "maximum_height_m": "6",
            "minimum_green_percent": "50",
            "front_setback_m": "5",
            "side_setback_m": "3",
            "rear_setback_m": "6",
            "allowed_uses": ["residential"],
        },
        user("author@imperial.local"),
    )
    with pytest.raises(ValueError, match="Demo szabály"):
        verify_rule_set(db, rule["rule_set_id"], user("reviewer@imperial.local", "designer"))


def test_rule_verification_enforces_four_eyes(db):
    rule = create_rule_set(
        db,
        {
            "municipality": "Négyszem",
            "zoning_code": "LKE-2",
            "version": "1",
            "source_url": "https://example.invalid/rule",
            "source_document_version": "1",
            "source_note": "Érdemi, ellenőrizhető szabályforrásra mutató tesztbejegyzés.",
            "maximum_coverage_percent": "30",
            "maximum_floor_area_ratio": "0.5",
            "maximum_height_m": "6",
            "minimum_green_percent": "50",
            "front_setback_m": "5",
            "side_setback_m": "3",
            "rear_setback_m": "6",
            "allowed_uses": ["residential"],
        },
        user("same@imperial.local"),
    )
    with pytest.raises(ValueError, match="négy szem"):
        verify_rule_set(db, rule["rule_set_id"], user("same@imperial.local", "designer"))


def test_plotcheck_full_fit_workflow_generates_verified_report_and_outbox(db, monkeypatch):
    runtime = Path(tempfile.gettempdir()) / f"plotcheck-test-{uuid4().hex}"
    monkeypatch.setattr("app.services.plotcheck.RUNTIME_ROOT", runtime)
    rule = verified_rule(db)
    case = plot_case(db, rule)
    evidence_ids = {}
    for category in ("land_registry", "cadastral_map", "hesz", "townscape", "geodesy", "soil", "utilities", "access", "logistics"):
        digest = hashlib.sha256(f"{category}:v1".encode()).hexdigest()
        case = add_evidence(
            db,
            case["case_id"],
            {
                "category": category,
                "source_reference": f"document://{category}-v1",
                "source_version": "v1",
                "source_sha256": digest,
                "note": f"A(z) {category} szakági forrás ellenőrzött és az ingatlannal egyezik.",
            },
            "evidence-uploader@imperial.local",
        )
        evidence_ids[category] = case["evidence"][-1]["evidence_id"]
        case = verify_evidence(db, case["case_id"], evidence_ids[category], "engineer@imperial.local")
    for gate_key in GATE_KEYS:
        ids = [evidence_ids[category] for category in sorted(GATE_EVIDENCE[gate_key])]
        case = review_gate(
            db,
            case["case_id"],
            gate_key,
            {"decision": "approved", "note": f"A(z) {gate_key} kapu tételesen ellenőrizve és megfelelő.", "evidence_ids": ids},
            "engineer@imperial.local",
        )
    case = assess_case(db, case["case_id"], "engineer@imperial.local")
    latest = case["assessments"][0]
    assert latest["outcome"] == "FIT"
    assert latest["stop_reasons"] == []
    assert latest["metrics"]["placement_fit_0_or_90_degrees"] is True
    final = finalize_case(
        db,
        case["case_id"],
        "FIT",
        "A hiteles források és a mérnöki számítás alapján alkalmas.",
        user("final-approver@imperial.local", "managing-director"),
    )
    assert final["status"] == "fit"
    assert final["final_report_document_id"].startswith("DOC-PLOT-")
    assert final["assessments"][0]["preliminary"] is False


def test_missing_evidence_is_stop_and_cannot_be_finalized_as_fit(db):
    rule = verified_rule(db)
    case = plot_case(db, rule)
    assessed = assess_case(db, case["case_id"], "engineer@imperial.local")
    latest = assessed["assessments"][0]
    assert latest["outcome"] == "FIT WITH CONDITIONS"
    assert len(latest["stop_reasons"]) == 9
    with pytest.raises(ValueError, match="minden PlotCheck kapu"):
        finalize_case(
            db,
            case["case_id"],
            "FIT WITH CONDITIONS",
            "Hiányos ügyet nem szabad pozitív alkalmassággal lezárni.",
            user("final@imperial.local", "managing-director"),
        )


def test_failed_geometry_returns_redesign_required(db):
    rule = verified_rule(db)
    case = create_case(
        db,
        {
            "project_id": "PRJ-PLOT-UAT-REDESIGN",
            "title": "Túl nagy ház",
            "address": "1234 Mintaváros, Próba utca 2.",
            "parcel_number": "1234/6",
            "municipality": "Mintaváros",
            "zoning_code": "LKE-1",
            "rule_set_id": rule["rule_set_id"],
            "plot_width_m": "20",
            "plot_depth_m": "30",
            "declared_plot_area_m2": "600",
            "proposed_width_m": "17",
            "proposed_depth_m": "14",
            "proposed_gross_floor_area_m2": "300",
            "proposed_height_m": "5.2",
            "proposed_use": "residential",
        },
        "pm@imperial.local",
    )
    assessed = assess_case(db, case["case_id"], "engineer@imperial.local")
    assert assessed["assessments"][0]["outcome"] == "RE-DESIGN REQUIRED"
    assert assessed["assessments"][0]["metrics"]["placement_fit_0_or_90_degrees"] is False


def test_condition_requires_complete_action_id(db):
    rule = verified_rule(db)
    case = plot_case(db, rule)
    case = add_action(
        db,
        case["case_id"],
        {
            "condition": "A kapubejáró teherbírását a kivitelezés előtt meg kell erősíteni.",
            "owner": "project-manager@imperial.local",
            "estimated_cost_huf": "1500000",
            "deadline_impact_days": "5",
            "design_impact": "A felvonulási és logisztikai terv módosul.",
        },
        "engineer@imperial.local",
    )
    assert case["actions"][0]["action_id"].startswith("ACTION-PLOT-")
    assert case["actions"][0]["estimated_cost_huf"] == 1_500_000


def test_plotcheck_workspace_is_protected_and_legacy_generic_api_is_closed(client):
    assert client.get("/plotcheck", follow_redirects=False).status_code == 303
    login = client.post(
        "/login",
        data={"email": "platform-admin@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    page = client.get("/plotcheck")
    assert page.status_code == 200
    assert "CHK-ENG-002" in page.text
    response = client.post(
        "/api/technical/cases",
        json={"module_key": "plotcheck", "project_id": "PRJ-LEGACY", "title": "Tiltott", "input": {}},
    )
    assert response.status_code == 409
