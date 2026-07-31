from __future__ import annotations

import pytest

from app.services.housematch import housematch_repository
from app.services.technical_products import (
    create_case,
    decide_case,
    get_case,
    review_gate,
    submit_case,
)


def test_buildconfig_is_persisted_and_cannot_bypass_required_gates(db):
    row = create_case(
        db,
        module_key="buildconfig",
        project_id="PRJ-TECH-001",
        title="Kulcsrakész konfiguráció",
        data={
            "brand": "imperial",
            "technology": "Danish Fabrik",
            "completion_level": "Kulcsrakész",
            "package": "Alap",
            "gross_area_m2": "100",
        },
        actor="technical-prep@imperial.local",
    )
    assert row["result"]["estimated_gross_total_huf"] == 68_000_000
    assert row["source_snapshot"]["source_version"]
    margin = next(gate for gate in row["gates"] if gate["gate_key"] == "margin")
    assert margin["status"] in {"pass", "fail"}
    submit_case(db, row["case_id"], "technical-prep@imperial.local")
    with pytest.raises(ValueError, match="minden kötelező"):
        decide_case(db, row["case_id"], "approved", "", "managing-director@imperial.local")
    with pytest.raises(ValueError, match="kézzel nem írható felül"):
        review_gate(db, row["case_id"], "margin", "pass", "kézi felülírás", "owner@imperial.local")
    for gate_key in ("technical", "finance", "cashflow", "capacity"):
        review_gate(db, row["case_id"], gate_key, "pass", f"Ellenőrzött bizonyíték: {gate_key}", "owner@imperial.local")
    if margin["status"] == "pass":
        approved = decide_case(db, row["case_id"], "approved", "Minden kapu rendben", "managing-director@imperial.local")
        assert approved["status"] == "approved"
        assert approved["result"]["offer_eligible"] is True


def test_housebuild_uses_verified_catalog_source_and_stays_unpublishable_until_approval(db):
    source = next(row for row in housematch_repository.catalog(active_only=True) if row.get("source_url") and row.get("verified_at"))
    row = create_case(
        db,
        module_key="housebuild-agent",
        project_id="PRJ-TECH-002",
        title="Forrásalapú HousePlan",
        data={"source_house_id": source["house_id"], "rights_evidence": "LEGAL-2026-001"},
        actor="technical-prep@imperial.local",
    )
    assert row["result"]["publication_allowed"] is False
    assert row["source_snapshot"]["source_url"] == source["source_url"]
    submit_case(db, row["case_id"], "technical-prep@imperial.local")
    for gate in row["gates"]:
        review_gate(db, row["case_id"], gate["gate_key"], "pass", f"Bizonyíték: {gate['gate_key']}", "owner@imperial.local")
    approved = decide_case(db, row["case_id"], "approved", "Jóváhagyva", "owner@imperial.local")
    assert approved["result"]["publication_allowed"] is True


def test_plotcheck_and_plancheck_require_canonical_inputs(db):
    with pytest.raises(ValueError, match="helyrajzi"):
        create_case(db, module_key="plotcheck", project_id="PRJ-X", title="Hiányos", data={}, actor="pm@imperial.local")
    with pytest.raises(ValueError, match="tervdokumentum"):
        create_case(db, module_key="plancheck", project_id="PRJ-X", title="Hiányos", data={"document_refs": []}, actor="pm@imperial.local")


def test_technical_screen_is_session_protected_and_available_to_authorized_user(client):
    assert client.get("/technical", follow_redirects=False).status_code == 303
    login = client.post("/login", data={"email": "platform-admin@imperial.local", "password": "Imperial2026!"}, follow_redirects=False)
    assert login.status_code == 303
    response = client.get("/technical")
    assert response.status_code == 200
    assert "HouseBuild" in response.text
    assert "megkerülhetetlen jóváhagyási kapukkal" in response.text


def test_customer_cannot_open_internal_technical_workspace(client):
    login = client.post("/login", data={"email": "customer@imperial.local", "password": "Imperial2026!"}, follow_redirects=False)
    assert login.status_code == 303
    assert client.get("/technical").status_code == 403
    assert client.get("/api/technical/cases").status_code == 200
    assert client.get("/api/technical/cases").json() == []


def test_finance_can_review_only_buildconfig_financial_gates(client, db):
    row = create_case(
        db,
        module_key="buildconfig",
        project_id="PRJ-TECH-FIN",
        title="Pénzügyi kaputeszt",
        data={
            "brand": "imperial",
            "technology": "Danish Fabrik",
            "completion_level": "Kulcsrakész",
            "package": "Alap",
            "gross_area_m2": "100",
        },
        actor="technical-prep@imperial.local",
    )
    submit_case(db, row["case_id"], "technical-prep@imperial.local")
    login = client.post("/login", data={"email": "finance@imperial.local", "password": "Imperial2026!"}, follow_redirects=False)
    assert login.status_code == 303
    page = client.get("/technical?module=buildconfig")
    assert page.status_code == 200
    assert "Számítás és verzió létrehozása" not in page.text
    denied_create = client.post(
        "/api/technical/cases",
        json={"module_key": "buildconfig", "project_id": "PRJ-X", "title": "Tiltott", "input": {}},
    )
    assert denied_create.status_code == 403
    allowed = client.post(
        f"/api/technical/cases/{row['case_id']}/gates/finance",
        json={"status": "pass", "evidence": "Pénzügyi forrás igazolva"},
    )
    assert allowed.status_code == 200
    denied = client.post(
        f"/api/technical/cases/{row['case_id']}/gates/technical",
        json={"status": "pass", "evidence": "Műszaki tartalom"},
    )
    assert denied.status_code == 403


def test_creator_cannot_approve_own_technical_case(db):
    row = create_case(
        db,
        module_key="plancheck",
        project_id="PRJ-TECH-4EYES",
        title="Négy szem teszt",
        data={"document_refs": ["DOC-001/v1"]},
        actor="designer@imperial.local",
    )
    submit_case(db, row["case_id"], "designer@imperial.local")
    for gate in row["gates"]:
        review_gate(db, row["case_id"], gate["gate_key"], "pass", f"Bizonyíték: {gate['gate_key']}", "technical-prep@imperial.local")
    with pytest.raises(ValueError, match="négy szem"):
        decide_case(db, row["case_id"], "approved", "Saját jóváhagyás", "designer@imperial.local")
