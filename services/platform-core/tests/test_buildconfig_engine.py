from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import (
    HouseBuildCase,
    HouseBuildVariant,
    OutboxMessage,
    WorkspaceDocument,
)
from app.services.buildconfig import (
    case_detail,
    compare_versions,
    create_case,
    create_revision,
    release_case,
    report_path,
    review_gate,
    submit_case,
)
from app.seed import DEMO_PASSWORD


def _user(role: str, email: str | None = None):
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _houseplan(db, project_id: str = "PRJ-BC-UAT-001", *, garage: int = 1):
    case_id = f"HB-{project_id[-3:]}"
    variant_id = f"HBV-{project_id[-3:]}-1"
    db.add(
        HouseBuildCase(
            case_id=case_id,
            project_id=project_id,
            title="BuildConfig HousePlan",
            source_house_id="HOUSE-BC-UAT",
            source_catalog_version_id="HCV-BC-UAT",
            source_snapshot_json='{"brand":"imperial"}',
            source_sha256="1" * 64,
            rights_evidence_ref="drive://uat/rights",
            rights_evidence_sha256="2" * 64,
            requirement_json='{"technology":"Danish Fabrik"}',
            requirement_sha256="3" * 64,
            status="released",
            current_revision=1,
            selected_variant_id=variant_id,
            created_by="technical-prep@imperial.local",
            released_by="owner@imperial.local",
            released_at=datetime.now(UTC),
        )
    )
    db.add(
        HouseBuildVariant(
            variant_id=variant_id,
            case_id=case_id,
            variant_no=1,
            label="BuildConfig UAT HousePlan",
            strategy="Kiadott szintetikus HousePlan a BuildConfig teszthez.",
            gross_area_m2=Decimal("100"),
            net_area_m2=Decimal("82"),
            footprint_m2=Decimal("100"),
            width_m=Decimal("10"),
            depth_m=Decimal("10"),
            floors=1,
            bedrooms=3,
            bathrooms=2,
            garage_spaces=garage,
            roof_style="nyeregtető",
            facade_style="kortárs",
            orientation="délkelet",
            accessibility=False,
            estimated_catalog_price_huf=Decimal("68000000"),
            rooms_json="[]",
            adjacency_json="[]",
            geometry_json='{"type":"rectilinear-envelope"}',
            geometry_signature="4" * 64,
            content_sha256="5" * 64,
            status="released",
        )
    )
    db.commit()
    return case_id, variant_id, project_id


def _data(binding, *, options=None, package="Alap"):
    case_id, variant_id, project_id = binding
    return {
        "project_id": project_id,
        "title": "Kanonikus BuildConfig UAT",
        "housebuild_case_id": case_id,
        "housebuild_variant_id": variant_id,
        "brand": "imperial",
        "technology": "Danish Fabrik",
        "completion_level": "Kulcsrakész",
        "package": package,
        "gross_area_m2": "100",
        "vat_rate": "0.05",
        "options": options or ["solar_ready"],
        "planned_start": (date.today() + timedelta(days=30)).isoformat(),
        "promised_delivery": (date.today() + timedelta(days=300)).isoformat(),
        "crew_count": 2,
        "weekly_capacity_m2": "30",
    }


def test_buildconfig_full_release_is_versioned_hashed_and_routed(db):
    binding = _houseplan(db)
    created = create_case(db, _data(binding), _user("technical-prep"))
    assert created["status"] == "calculated"
    version = created["versions"][0]
    assert len(version["bom"]) == 7
    assert len(version["validations"]) == 8
    assert all(item["decision"] == "pass" for item in version["validations"])
    assert len(version["gates"]) == 10
    assert len(version["config_sha256"]) == 64
    assert version["net_price_huf"] > version["net_cost_huf"] > 0

    submitted = submit_case(db, created["case_id"], _user("technical-prep"))
    assert submitted["status"] == "review"
    review_gate(
        db,
        created["case_id"],
        "technical",
        {
            "decision": "approved",
            "note": "A műszaki csomag és BOM tételesen ellenőrizve.",
            "evidence_ref": "document://BC/UAT/TECH",
            "evidence_sha256": "a" * 64,
        },
        _user("designer", "designer-review@imperial.local"),
    )
    review_gate(
        db,
        created["case_id"],
        "finance",
        {
            "decision": "approved",
            "note": "A fedezet, fizetési terv és cashflow ellenőrizve.",
            "evidence_ref": "document://BC/UAT/FINANCE",
            "evidence_sha256": "b" * 64,
        },
        _user("finance", "finance-review@imperial.local"),
    )
    with pytest.raises(ValueError, match="négy szem"):
        release_case(
            db,
            created["case_id"],
            "Saját konfiguráció tiltott kiadási kísérlete.",
            _user("owner", "technical-prep@imperial.local"),
        )
    released = release_case(
        db,
        created["case_id"],
        "Minden automatikus és emberi kapu bizonyítottan megfelelt.",
        _user("managing-director"),
    )
    assert released["status"] == "approved"
    assert released["versions"][0]["status"] == "approved"
    document = db.scalar(
        select(WorkspaceDocument).where(
            WorkspaceDocument.document_id == released["final_report_document_id"]
        )
    )
    assert document is not None
    path = report_path(db, document.document_id)
    assert hashlib.sha256(path.read_bytes()).hexdigest() in document.metadata_json
    destinations = {
        row.destination_module
        for row in db.scalars(
            select(OutboxMessage).where(OutboxMessage.source_event_id.like("EVT-BC-%"))
        )
    }
    assert {
        "housebuild-agent",
        "sales",
        "contract-generator",
        "financial-control",
        "procurement",
        "crm",
        "my-imperial",
    }.issubset(destinations)


def test_buildconfig_compatibility_and_capacity_are_fail_closed(db):
    binding = _houseplan(db, "PRJ-BC-UAT-STOP", garage=0)
    created = create_case(
        db,
        _data(binding, options=["garage_package"]),
        _user("technical-prep"),
    )
    version = created["versions"][0]
    compatibility = next(
        item for item in version["validations"] if item["validation_key"] == "option_compatibility"
    )
    assert compatibility["decision"] == "fail"
    with pytest.raises(ValueError, match="STOP"):
        submit_case(db, created["case_id"], _user("technical-prep"))


def test_buildconfig_revision_supersedes_previous_approved_snapshot(db):
    binding = _houseplan(db, "PRJ-BC-UAT-REV")
    created = create_case(db, _data(binding), _user("technical-prep"))
    revised_data = _data(binding, options=["solar_ready", "heat_pump_upgrade"])
    revised = create_revision(db, created["case_id"], revised_data, _user("technical-prep"))
    assert revised["current_version_id"].endswith("-2")
    assert [item["version_no"] for item in revised["versions"]] == [2, 1]
    assert revised["versions"][1]["status"] == "superseded"
    assert revised["versions"][0]["config_sha256"] != revised["versions"][1]["config_sha256"]
    assert case_detail(db, created["case_id"])["versions"][0]["bom_sha256"]
    comparison = compare_versions(db, created["case_id"])
    assert comparison["left"]["version_no"] == 1
    assert comparison["right"]["version_no"] == 2
    assert [item["code"] for item in comparison["added_options"]] == ["heat_pump_upgrade"]
    assert comparison["deltas"]["net_price_huf"] > 0
    assert any(row["line_id"] == "BOM-OPT-HEAT_PUMP_UPGRADE" and row["change"] == "added" for row in comparison["bom_rows"])


def test_buildconfig_workspace_is_visible_but_legacy_mutation_is_locked(client, db):
    _houseplan(db, "PRJ-BC-UAT-UI")
    login = client.post(
        "/login",
        data={"email": "platform-admin@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert client.get("/buildconfig").status_code == 200
    blocked = client.post(
        "/api/technical/cases",
        json={
            "module_key": "buildconfig",
            "project_id": "PRJ-LEGACY",
            "title": "Tiltott generikus BuildConfig",
            "input": {},
        },
    )
    assert blocked.status_code == 409


def test_buildconfig_compare_screen_and_version_scope(client, db):
    binding = _houseplan(db, "PRJ-BC-UAT-CMP")
    created = create_case(db, _data(binding), _user("technical-prep"))
    revised = create_revision(
        db,
        created["case_id"],
        _data(binding, options=["solar_ready", "heat_pump_upgrade"]),
        _user("technical-prep"),
    )
    login = client.post(
        "/login",
        data={"email": "platform-admin@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303
    page = client.get(f"/buildconfig/cases/{created['case_id']}/compare")
    assert page.status_code == 200
    for marker in ("verzió-összehasonlítás", "Hozzáadott és eltávolított opciók", "Tételes költségváltozás", "heat_pump_upgrade"):
        assert marker in page.text
    invalid = client.get(
        f"/buildconfig/cases/{created['case_id']}/compare",
        params={"left": revised["versions"][0]["version_id"], "right": "BCV-OTHER-CASE-1"},
    )
    assert invalid.status_code == 404
