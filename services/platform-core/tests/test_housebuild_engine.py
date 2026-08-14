from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import OutboxMessage, PlanCheckCase, PlotCheckCase, TechnicalCase, WorkspaceDocument
from app.services.house_catalog import public_catalog
from app.services.housebuild import (
    create_case,
    release_case,
    report_path,
    review_gate,
    select_variant,
    submit_case,
)


def _user(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _data(db, project_id: str = "PRJ-HB-UAT-001"):
    source = next(row for row in public_catalog(db) if row.get("content_sha256"))
    return {
        "project_id": project_id,
        "title": "Kanonikus HouseBuild UAT",
        "source_house_id": source["house_id"],
        "rights_evidence_ref": "drive://legal/HB-RIGHTS-001",
        "rights_evidence_sha256": "a" * 64,
        "desired_area_m2": "126",
        "technology": "Danish Fabrik",
        "bedrooms": 4,
        "bathrooms": 2,
        "floors": 1,
        "garage_spaces": 1,
        "roof_style": "nyeregtető",
        "facade_style": "kortárs",
        "orientation": "délkelet",
        "accessibility": False,
    }


def _dependencies(db, project_id: str, source_house_id: str):
    db.add(
        PlotCheckCase(
            case_id="PLOT-HB-UAT",
            project_id=project_id,
            title="HouseBuild telek",
            address="UAT utca 1.",
            parcel_number="UAT/1",
            municipality="UAT",
            zoning_code="LKE-UAT",
            rule_set_id="RULE-HB-UAT",
            status="fit",
            current_revision=1,
            geometry_json='{"type":"Polygon","coordinates":[[[0,0],[20,0],[20,40],[0,40],[0,0]]]}',
            geometry_crs="LOCAL-METRIC",
            geometry_sha256="b" * 64,
            declared_plot_area_m2=Decimal("800"),
            proposed_footprint_m2=Decimal("126"),
            proposed_gross_floor_area_m2=Decimal("126"),
            proposed_paved_area_m2=Decimal("80"),
            proposed_height_m=Decimal("5.5"),
            proposed_use="residential",
            proposed_width_m=Decimal("10"),
            proposed_depth_m=Decimal("12.6"),
            house_id=source_house_id,
            created_by="technical-prep@imperial.local",
        )
    )
    db.add(
        TechnicalCase(
            case_id="CFG-HB-UAT",
            module_key="buildconfig",
            project_id=project_id,
            title="HouseBuild BuildConfig",
            status="approved",
            input_json="{}",
            result_json="{}",
            source_snapshot_json="{}",
            created_by="technical-prep@imperial.local",
            approved_by="finance@imperial.local",
            approved_at=datetime.now(UTC),
        )
    )
    db.add(
        PlanCheckCase(
            case_id="PLC-HB-UAT",
            project_id=project_id,
            title="HouseBuild PlanCheck",
            contact_name="UAT Ügyfél",
            contact_email="uat@example.invalid",
            status="sendable",
            current_revision=1,
            current_revision_id="PLCR-HB-UAT",
            upload_token_hash="c" * 64,
            upload_token_expires_at=datetime.now(UTC) + timedelta(days=1),
            created_by="designer@imperial.local",
        )
    )
    db.commit()


def test_housebuild_generates_persisted_auditable_variants(db):
    row = create_case(db, _data(db), _user("technical-prep"))
    assert row["status"] == "intake"
    assert len(row["variants"]) == 3
    assert len({variant["geometry_signature"] for variant in row["variants"]}) == 3
    assert all(len(variant["content_sha256"]) == 64 for variant in row["variants"])
    assert all(len(variant["validations"]) == 5 for variant in row["variants"])
    assert all(
        any(room["room_id"] == "R-LIVING" for room in variant["rooms"])
        for variant in row["variants"]
    )
    automatic = {gate["gate_key"]: gate["decision"] for gate in row["gates"]}
    assert automatic["source_rights"] == "approved"
    assert automatic["program"] == "pending"
    assert automatic["deduplication"] == "pending"
    assert automatic["topology"] == "pending"
    with pytest.raises(ValueError, match="kiválasztani"):
        submit_case(db, row["case_id"], _user("technical-prep"))


def test_housebuild_full_release_requires_canonical_dependencies_and_four_eyes(db):
    row = create_case(db, _data(db), _user("technical-prep"))
    selected = select_variant(
        db, row["case_id"], row["variants"][1]["variant_id"], _user("technical-prep")
    )
    assert selected["status"] == "variant_selected"
    submit_case(db, row["case_id"], _user("technical-prep"))
    with pytest.raises(ValueError, match="négy szem"):
        review_gate(
            db,
            row["case_id"],
            "technical",
            {
                "decision": "approved",
                "note": "Saját műszaki kapu jóváhagyása tiltott.",
                "evidence_refs": ["DOC-SELF-REVIEW"],
                "evidence_sha256": "e" * 64,
            },
            _user("technical-prep"),
        )
    _dependencies(db, row["project_id"], row["source_house_id"])
    refs = {
        "plotcheck": "PLOT-HB-UAT",
        "buildconfig": "CFG-HB-UAT",
        "plancheck": "PLC-HB-UAT",
        "technical": "DOC-HB-TECH-UAT",
    }
    for gate_key, reference in refs.items():
        review_gate(
            db,
            row["case_id"],
            gate_key,
            {
                "decision": "approved",
                "note": f"Ellenőrzött HouseBuild bizonyíték: {gate_key}",
                "evidence_refs": [reference],
                "evidence_sha256": "d" * 64,
            },
            _user("designer"),
        )
    with pytest.raises(ValueError, match="négy szem"):
        release_case(db, row["case_id"], "A teljes HousePlan kiadható.", _user("technical-prep"))
    released = release_case(
        db, row["case_id"], "A teljes HousePlan kiadható.", _user("managing-director")
    )
    assert released["status"] == "released"
    assert released["plotcheck_case_id"] == "PLOT-HB-UAT"
    assert released["buildconfig_case_id"] == "CFG-HB-UAT"
    assert released["plancheck_case_id"] == "PLC-HB-UAT"
    assert released["final_report_document_id"]
    assert report_path(db, released["final_report_document_id"]).is_file()
    document = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.document_id == released["final_report_document_id"]
        )
    )
    assert document and document.verification_status == "sha256_verified"
    destinations = set(
        db.scalars(
            select(OutboxMessage.destination_module).where(
                OutboxMessage.source_event_id.like("EVT-HB-%")
            )
        )
    )
    assert {
        "house-catalog",
        "housevision",
        "buildconfig",
        "plancheck",
        "crm",
        "my-imperial",
        "contract-generator",
    }.issubset(destinations)
    from scripts.verify_housebuild_schema import main as verify_housebuild

    assert verify_housebuild() == 0


def test_housebuild_duplicate_geometry_is_a_stop_gate(db):
    first = create_case(db, _data(db, "PRJ-HB-DUP-1"), _user("technical-prep"))
    second = create_case(
        db, _data(db, "PRJ-HB-DUP-2"), _user("technical-prep", "other@imperial.local")
    )
    selected = select_variant(
        db,
        second["case_id"],
        second["variants"][1]["variant_id"],
        _user("technical-prep", "other@imperial.local"),
    )
    assert (
        next(g for g in selected["gates"] if g["gate_key"] == "deduplication")["decision"]
        == "rejected"
    )
    with pytest.raises(ValueError, match="deduplication"):
        submit_case(db, second["case_id"], _user("technical-prep", "other@imperial.local"))
    assert first["source_house_id"] == second["source_house_id"]


def test_housebuild_ui_and_legacy_mutation_are_scoped(client):
    login = client.post(
        "/login",
        data={"email": "technical-prep@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    page = client.get("/housebuild")
    assert page.status_code == 200
    assert "Kanonikus típusház-generátor" in page.text
    denied = client.post(
        "/api/technical/cases",
        json={
            "module_key": "housebuild-agent",
            "project_id": "PRJ-LEGACY-HB",
            "title": "Tiltott legacy",
            "input": {},
        },
    )
    assert denied.status_code == 409
    client.post("/logout")
    client.post(
        "/login",
        data={"email": "customer@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert client.get("/housebuild").status_code == 403
