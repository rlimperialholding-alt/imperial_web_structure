"""Fájlfeltöltés-értelmező és PlotCheck fail-closed sweep (szintetikus, hálózatmentes).

A ``parse_upload`` minden formátumágát és a PlotCheck szabálytár/ügy
életciklus valós elutasítási ágait söpri végig; minden eset explicit elvárás.
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from app.services.file_ingestion import parse_upload
from app.services.plotcheck import (
    add_evidence,
    complete_action,
    create_case,
    create_rule_set,
    review_gate,
    verify_evidence,
    verify_rule_set,
)

LEGAL_USER = SimpleNamespace(role="designer", email="designer@imperial.local")
ADMIN_USER = SimpleNamespace(role="platform-admin", email="platform-admin@imperial.local")


def _valid_rule_data() -> dict:
    return {
        "municipality": "Pomáz",
        "zoning_code": "LKE-1",
        "version": "2026-sweep-1",
        "source_url": "https://oroksegvedelem.example/szabaly",
        "source_document_version": "hatalyos-2026",
        "source_note": "Szintetikus szabályverzió a sweep-teszthez.",
        "allowed_uses": ["lakó"],
        "lifecycle_status": "draft",
        "maximum_coverage_percent": "30",
        "maximum_floor_area_ratio": "0.6",
        "maximum_height_m": "7.5",
        "minimum_green_percent": "45",
        "front_setback_m": "5",
        "side_setback_m": "3",
        "rear_setback_m": "6",
    }


def _verified_rule(db) -> dict:
    created = create_rule_set(db, _valid_rule_data(), LEGAL_USER)
    return verify_rule_set(db, created["rule_set_id"], ADMIN_USER)


def _valid_case(rule: dict) -> dict:
    return {
        "project_id": "PRJ-SWEEP-001",
        "title": "Szintetikus PlotCheck ügy",
        "address": "Pomáz, Teszt utca 1.",
        "parcel_number": "1234/5",
        "municipality": rule["municipality"],
        "zoning_code": rule["zoning_code"],
        "rule_set_id": rule["rule_set_id"],
        "plot_width_m": "20",
        "plot_depth_m": "40",
        "declared_plot_area_m2": "800",
        "proposed_width_m": "10",
        "proposed_depth_m": "12",
        "proposed_footprint_m2": "120",
        "proposed_gross_floor_area_m2": "120",
        "proposed_paved_area_m2": "80",
        "proposed_height_m": "6.5",
        "proposed_use": "lakó",
    }


class TestParseUploadFormats:
    def test_json_list_and_records_and_dict(self) -> None:
        assert parse_upload("a.json", json.dumps([{"a": 1}]).encode())["records"] == [{"a": 1}]
        assert parse_upload("a.json", json.dumps({"records": [{"a": 1}, "x"]}).encode())["records"] == [{"a": 1}]
        assert parse_upload("a.json", json.dumps({"a": 1}).encode())["records"] == [{"a": 1}]

    def test_json_scalar_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_upload("a.json", json.dumps("csak-string").encode())

    def test_csv_sniffed_and_plain(self) -> None:
        rows = parse_upload("a.csv", "a,b\n1,2\n".encode("utf-8-sig"))["records"]
        assert rows == [{"a": "1", "b": "2"}]
        rows = parse_upload("a.csv", "a;b\n1;2\n".encode("utf-8-sig"))["records"]
        assert rows == [{"a": "1", "b": "2"}]

    def test_xlsx_single_sheet_with_empty_rows(self) -> None:
        buffer = io.BytesIO()
        wb = Workbook()
        ws = wb.active
        ws.title = "Adatok"
        ws.append(["nev", "ertek"])
        ws.append(["alfa", 1])
        ws.append([None, None])
        ws.append(["beta", 2])
        wb.save(buffer)
        result = parse_upload("a.xlsx", buffer.getvalue())
        assert result["records"][0]["nev"] == "alfa"
        assert result["records"][1]["nev"] == "beta"

    def test_txt_and_oversize_and_bad_extension(self) -> None:
        assert "text" in parse_upload("a.txt", "sima szöveg".encode("utf-8"))
        with pytest.raises(ValueError):
            parse_upload("a.txt", b"x" * (20 * 1024 * 1024 + 1))
        with pytest.raises(ValueError):
            parse_upload("a.exe", b"x")
        with pytest.raises(ValueError):
            parse_upload("", b"x")


class TestPlotCheckRuleLifecycle:
    def test_role_gate_fails_closed(self, db) -> None:
        with pytest.raises(PermissionError):
            create_rule_set(db, _valid_rule_data(), SimpleNamespace(role="sales", email="sales@imperial.local"))
        with pytest.raises(PermissionError):
            verify_rule_set(db, "PCRULE-NEM-LETEZIK", SimpleNamespace(role="sales", email="sales@imperial.local"))

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.update({"municipality": ""}),
            lambda d: d.update({"allowed_uses": []}),
            lambda d: d.update({"lifecycle_status": "verified"}),
            lambda d: d.update({"maximum_coverage_percent": "120"}),
            lambda d: d.update({"minimum_green_percent": "80"}),  # 30 + 80 > 100
            lambda d: d.update({"maximum_floor_area_ratio": "11"}),
            lambda d: d.update({"maximum_height_m": "101"}),
            lambda d: d.update({"front_setback_m": "101"}),
        ],
    )
    def test_rule_validation_fails_closed(self, db, mutate) -> None:
        data = _valid_rule_data()
        mutate(data)
        with pytest.raises(ValueError):
            create_rule_set(db, data, LEGAL_USER)

    def test_self_verify_and_demo_rejected(self, db) -> None:
        created = create_rule_set(db, _valid_rule_data(), LEGAL_USER)
        with pytest.raises(ValueError, match="négy szem"):
            verify_rule_set(db, created["rule_set_id"], LEGAL_USER)
        demo = create_rule_set(db, {**_valid_rule_data(), "version": "2026-demo-1", "lifecycle_status": "demo"}, LEGAL_USER)
        with pytest.raises(ValueError, match="[Dd]emo"):
            verify_rule_set(db, demo["rule_set_id"], ADMIN_USER)

    def test_verified_rule_retires_previous(self, db) -> None:
        first = _valid_rule_data()
        created = create_rule_set(db, first, LEGAL_USER)
        verified = verify_rule_set(db, created["rule_set_id"], ADMIN_USER)
        assert verified["lifecycle_status"] == "verified"


class TestPlotCheckCaseFailClosed:
    def _rule(self, db) -> dict:
        return _verified_rule(db)

    def test_case_validation_fails_closed(self, db) -> None:
        rule = self._rule(db)
        with pytest.raises(ValueError, match="Hiányzó"):
            create_case(db, {"project_id": "PRJ-X"}, "tester")
        with pytest.raises(ValueError, match="települése"):
            create_case(db, {**_valid_case(rule), "municipality": "Budapest"}, "tester")
        with pytest.raises(ValueError, match="terület"):
            create_case(db, {**_valid_case(rule), "declared_plot_area_m2": "999"}, "tester")
        with pytest.raises(ValueError, match="alapterület"):
            create_case(db, {**_valid_case(rule), "proposed_footprint_m2": "999"}, "tester")

    def test_case_happy_path_creates_gates(self, db) -> None:
        rule = self._rule(db)
        case = create_case(db, _valid_case(rule), "tester")
        assert case["case_id"].startswith("PLOT-")
        assert len(case["gates"]) == 8

    def test_evidence_and_action_gates_fail_closed(self, db) -> None:
        rule = self._rule(db)
        case = create_case(db, _valid_case(rule), "tester")
        case_id = case["case_id"]
        with pytest.raises(KeyError):
            add_evidence(db, "PLOT-NEM-LETEZIK", {"category": "other"}, "tester")
        with pytest.raises(KeyError):
            verify_evidence(db, case_id, "PLTEV-NEM-LETEZIK", "tester")
        with pytest.raises(KeyError):
            complete_action(db, case_id, "PLTAC-NEM-LETEZIK", {"note": "kész"}, "tester")
        with pytest.raises(ValueError):
            review_gate(db, case_id, "NEM-LETEZO-GATE", {"decision": "pass", "note": "ok"}, "tester")
