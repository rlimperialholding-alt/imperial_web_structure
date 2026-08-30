from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.growth_ops import catalog
from app.growth_ops.models import (
    SourceCatalogRevision,
    SourceCoverageAttempt,
    SourceCoverageRoute,
)
from app.growth_ops.processing import _signal_type, _specific_listing_permalink
from app.growth_ops.registry import GrowthRegistryError


def _record(index: int, *, note: str | None = None) -> dict:
    return {
        "RouteKey": f"ROUTE:{index}",
        "RouteID": f"R-{index}",
        "Motor": "Imperial–Bautica–Prefab",
        "Katalógusrész": "TEST",
        "Ország": "HU",
        "Forrástípus": "official_portal",
        "Forrás neve": f"Source {index}",
        "Útvonal URL": f"https://example{index}.test/search",
        "Útvonalmód": "direct",
        "Prioritás": "P1",
        "Validáció": "TEST",
        "Katalógusstátusz": "active",
        "Megjegyzés": note,
    }


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        ({"Motor": "ExitFlow–Veritas–BauShield"}, False),
        ({"Ország": "DE", "Keresési jel/kifejezés": "Hausbau"}, False),
        ({"Ország": "HU", "Forrástípus": "procurement"}, False),
        ({"Ország": "AT", "Keresési jel/kifejezés": "Wien | Hausbau"}, True),
        ({"Ország": "AT", "Keresési jel/kifejezés": "hotel construction"}, False),
        ({"Ország": "SK", "Keresési jel/kifejezés": "prístavba domu"}, True),
        ({"Ország": "SK", "Keresési jel/kifejezés": "house extension"}, True),
        ({"Ország": "HU/AT", "Keresési jel/kifejezés": "Hausbau"}, False),
    ],
)
def test_building_route_scope_is_fail_closed(overrides, expected):
    record = _record(1)
    record.update(overrides)

    assert catalog._building_route_enabled(record) is expected


def _snapshot(tmp_path, records: list[dict]):
    snapshot = tmp_path / "routes.jsonl"
    lines = (
        f"{json.dumps(record, ensure_ascii=False, sort_keys=True)}\n"
        for record in records
    )
    snapshot.write_text(
        "".join(lines),
        encoding="utf-8",
    )
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "spreadsheet_id": catalog.SOURCE_LEDGER_SPREADSHEET_ID,
                "sheet_id": catalog.SOURCE_LEDGER_SHEET_ID,
                "route_count": len(records),
                "modified_time": "2026-08-20T11:39:45.518Z",
                "catalog_sha256": digest,
            }
        ),
        encoding="utf-8",
    )
    return snapshot, manifest, digest


def test_catalog_import_is_hash_bound_and_idempotent(db, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "SOURCE_LEDGER_ROUTE_COUNT", 2)
    snapshot, manifest, digest = _snapshot(tmp_path, [_record(1), _record(2)])

    first = catalog.import_snapshot(db, snapshot_path=snapshot, manifest_path=manifest)
    second = catalog.import_snapshot(db, snapshot_path=snapshot, manifest_path=manifest)

    assert first.revision_id == second.revision_id
    assert first.catalog_sha256 == digest
    assert first.status == "active"
    assert db.scalar(select(func.count()).select_from(SourceCoverageRoute)) == 2
    assert db.scalar(select(func.count()).select_from(SourceCatalogRevision)) == 1


def test_catalog_import_blocks_named_no_monitoring_entity_before_storage(
    db, tmp_path, monkeypatch
):
    monkeypatch.setattr(catalog, "SOURCE_LEDGER_ROUTE_COUNT", 2)
    snapshot, manifest, _digest = _snapshot(
        tmp_path,
        [_record(1), _record(2, note="Homes4you")],
    )

    with pytest.raises(GrowthRegistryError, match="no_monitoring_hard_gate"):
        catalog.import_snapshot(db, snapshot_path=snapshot, manifest_path=manifest)

    assert db.scalar(select(func.count()).select_from(SourceCoverageRoute)) == 0
    assert db.scalar(select(func.count()).select_from(SourceCatalogRevision)) == 0


def test_catalog_import_replaces_robots_disallowed_legacy_land_route(
    db, tmp_path, monkeypatch
):
    monkeypatch.setattr(catalog, "SOURCE_LEDGER_ROUTE_COUNT", 1)
    record = _record(12)
    record.update(
        {
            "RouteKey": "BUILDING:SRC-0012",
            "RouteID": "SRC-0012",
            "Kategória": "Ingatlan",
            "Forrás neve": "ingatlan.com telek keresés",
            "Forrástípus": "real_estate",
            "Útvonal URL": "https://ingatlan.com/lista/elado+telek",
        }
    )
    snapshot, manifest, _digest = _snapshot(tmp_path, [record])

    catalog.import_snapshot(db, snapshot_path=snapshot, manifest_path=manifest)

    route = db.scalar(select(SourceCoverageRoute))
    assert route is not None
    assert route.route_url == "https://ingatlan.com/elado+telek"
    assert "/lista" in route.source_record_json


def test_land_public_html_route_and_listing_permalink_are_classified():
    route = SimpleNamespace(
        motor="Imperial–Bautica–Prefab",
        catalog_part="BASE",
        category="Ingatlan",
        source_name="ingatlan.com telek keresés",
        search_signal=None,
        route_url="https://ingatlan.com/elado+telek",
    )

    assert _signal_type(route) == "residential_building_plot"
    assert _specific_listing_permalink("https://ingatlan.com/35500001") is True
    assert _specific_listing_permalink("https://ingatlan.com/elado+telek") is False


def test_scanner_uses_db_catalog_and_records_real_attempt(db, tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "SOURCE_LEDGER_ROUTE_COUNT", 2)
    snapshot, manifest, _digest = _snapshot(tmp_path, [_record(1), _record(2)])
    catalog.import_snapshot(db, snapshot_path=snapshot, manifest_path=manifest)
    monkeypatch.setattr(
        catalog,
        "settings",
        lambda: SimpleNamespace(
            canonical_wide_enabled=True,
            canonical_route_scanning_enabled=True,
            canonical_route_batch_size=1,
            canonical_route_timeout_seconds=5,
            canonical_route_max_response_bytes=100_000,
            canonical_daily_at="05:30",
            timezone="Europe/Budapest",
        ),
    )
    monkeypatch.setattr(
        catalog,
        "_fetch",
        lambda _route, **_kwargs: {
            "status": "succeeded",
            "http_status": 200,
            "response_sha256": "a" * 64,
            "evidence": {"content_bytes": 12, "host": "example.test"},
        },
    )

    result = catalog.scan_due_routes(
        db,
        now=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
    )

    assert result["attempted"] == 1
    assert result["outcomes"] == {"succeeded": 1}
    attempt = db.scalar(select(SourceCoverageAttempt))
    assert attempt and attempt.status == "succeeded"
    assert attempt.run_id
    route = db.scalar(
        select(SourceCoverageRoute).where(SourceCoverageRoute.route_key == attempt.route_key)
    )
    assert route and route.attempt_count == 1 and route.success_count == 1

    second = catalog.scan_due_routes(
        db,
        now=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
    )
    complete = catalog.scan_due_routes(
        db,
        now=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
    )

    assert second["attempted"] == 1
    assert second["coverage_complete"] is True
    assert complete["status"] == "on_pace"
    assert complete["coverage_complete"] is True
    assert complete["attempted_today"] == complete["active_route_target"] == 2
