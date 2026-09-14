from __future__ import annotations

import pytest

from app.seed import DEMO_PASSWORD
from app.services.housematch import housematch_repository
from app.services.technical_products import (
    create_case,
    decide_case,
    review_gate,
    select_housebuild_variant,
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
    assert row["result"]["estimated_net_total_huf"] == 68_000_000
    assert row["result"]["customer_facing_price_suffix"] == "+ ÁFA"
    assert row["source_snapshot"]["source_version"]
    margin = next(gate for gate in row["gates"] if gate["gate_key"] == "margin")
    assert margin["status"] in {"pass", "fail"}
    submit_case(db, row["case_id"], "technical-prep@imperial.local")
    with pytest.raises(ValueError, match="minden kötelező"):
        decide_case(db, row["case_id"], "approved", "", "managing-director@imperial.local")
    with pytest.raises(ValueError, match="kézzel nem írható felül"):
        review_gate(db, row["case_id"], "margin", "pass", "kézi felülírás", "owner@imperial.local")
    for gate_key in ("technical", "finance", "cashflow", "capacity"):
        review_gate(
            db,
            row["case_id"],
            gate_key,
            "pass",
            f"Ellenőrzött bizonyíték: {gate_key}",
            "owner@imperial.local",
        )
    if margin["status"] == "pass":
        approved = decide_case(
            db,
            row["case_id"],
            "approved",
            "Minden kapu rendben",
            "managing-director@imperial.local",
        )
        assert approved["status"] == "approved"
        assert approved["result"]["offer_eligible"] is True


def test_housebuild_uses_verified_catalog_source_and_stays_unpublishable_until_approval(db):
    source = next(
        row
        for row in housematch_repository.catalog(active_only=True)
        if row.get("source_url") and row.get("verified_at")
    )
    row = create_case(
        db,
        module_key="housebuild-agent",
        project_id="PRJ-TECH-002",
        title="Forrásalapú HousePlan",
        data={
            "source_house_id": source["house_id"],
            "rights_evidence": "LEGAL-2026-001",
            "desired_area_m2": "126",
            "bedrooms": "4",
            "bathrooms": "2",
            "floors": "1",
            "garage_spaces": "2",
            "roof_style": "nyeregtető",
            "facade_style": "kortárs",
            "orientation": "délkelet",
        },
        actor="technical-prep@imperial.local",
    )
    assert row["result"]["publication_allowed"] is False
    assert row["source_snapshot"]["source_url"] == source["source_url"]
    assert len(row["result"]["variants"]) == 3
    assert row["result"]["selection_required"] is True
    with pytest.raises(ValueError, match="változatot"):
        submit_case(db, row["case_id"], "technical-prep@imperial.local")
    selected = select_housebuild_variant(
        db,
        row["case_id"],
        row["result"]["variants"][1]["variant_id"],
        "technical-prep@imperial.local",
    )
    assert selected["result"]["selection_required"] is False
    assert selected["result"]["selected_variant"]["label"] == "Célprogramra hangolt változat"
    submitted = submit_case(db, row["case_id"], "technical-prep@imperial.local")
    for gate in submitted["gates"]:
        review_gate(
            db,
            row["case_id"],
            gate["gate_key"],
            "pass",
            f"Bizonyíték: {gate['gate_key']}",
            "owner@imperial.local",
        )
    approved = decide_case(db, row["case_id"], "approved", "Jóváhagyva", "owner@imperial.local")
    assert approved["result"]["publication_allowed"] is True
    assert approved["result"]["released_configuration"]["variant_id"] == selected["result"]["selected_variant_id"]


def test_housebuild_rejects_out_of_range_configuration(db):
    source = next(
        row
        for row in housematch_repository.catalog(active_only=True)
        if row.get("source_url") and row.get("verified_at")
    )
    with pytest.raises(ValueError, match="alapterület"):
        create_case(
            db,
            module_key="housebuild-agent",
            project_id="PRJ-TECH-RANGE",
            title="Hibás konfiguráció",
            data={
                "source_house_id": source["house_id"],
                "rights_evidence": "LEGAL-2026-002",
                "desired_area_m2": "999",
            },
            actor="technical-prep@imperial.local",
        )


def test_plotcheck_and_plancheck_require_canonical_inputs(db):
    with pytest.raises(ValueError, match="helyrajzi"):
        create_case(
            db,
            module_key="plotcheck",
            project_id="PRJ-X",
            title="Hiányos",
            data={},
            actor="pm@imperial.local",
        )
    with pytest.raises(ValueError, match="tervdokumentum"):
        create_case(
            db,
            module_key="plancheck",
            project_id="PRJ-X",
            title="Hiányos",
            data={"document_refs": []},
            actor="pm@imperial.local",
        )


def test_technical_screen_is_session_protected_and_available_to_authorized_user(client):
    assert client.get("/technical", follow_redirects=False).status_code == 303
    login = client.post(
        "/login",
        data={"email": "platform-admin@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303
    response = client.get("/technical")
    assert response.status_code == 200
    assert "HouseBuild" in response.text
    assert "megkerülhetetlen jóváhagyási kapukkal" in response.text


def test_customer_cannot_open_internal_technical_workspace(client):
    login = client.post(
        "/login",
        data={"email": "customer@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert client.get("/technical").status_code == 403
    assert client.get("/api/technical/cases").status_code == 200
    assert client.get("/api/technical/cases").json() == []


def test_finance_cannot_mutate_legacy_buildconfig_workflow(client, db):
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
    login = client.post(
        "/login",
        data={"email": "finance@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303
    page = client.get("/technical?module=buildconfig")
    assert page.status_code == 200
    assert "Számítás és verzió létrehozása" not in page.text
    denied_create = client.post(
        "/api/technical/cases",
        json={"module_key": "buildconfig", "project_id": "PRJ-X", "title": "Tiltott", "input": {}},
    )
    assert denied_create.status_code == 403
    locked_finance_gate = client.post(
        f"/api/technical/cases/{row['case_id']}/gates/finance",
        json={"status": "pass", "evidence": "Pénzügyi forrás igazolva"},
    )
    assert locked_finance_gate.status_code == 409
    locked_technical_gate = client.post(
        f"/api/technical/cases/{row['case_id']}/gates/technical",
        json={"status": "pass", "evidence": "Műszaki tartalom"},
    )
    assert locked_technical_gate.status_code == 409


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
        review_gate(
            db,
            row["case_id"],
            gate["gate_key"],
            "pass",
            f"Bizonyíték: {gate['gate_key']}",
            "technical-prep@imperial.local",
        )
    with pytest.raises(ValueError, match="négy szem"):
        decide_case(db, row["case_id"], "approved", "Saját jóváhagyás", "designer@imperial.local")
