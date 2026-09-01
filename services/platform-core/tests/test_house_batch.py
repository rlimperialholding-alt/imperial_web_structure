from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from time import perf_counter

import pytest

from app.services.house_batch import (
    HouseBatchError,
    dry_run_batch,
    parse_batch_json,
    validate_dry_run_token,
)


@pytest.fixture(autouse=True)
def clean_database():
    yield


SOURCE = {"id": "SRC-001", "revision": 4, "sha256": "a" * 64}
SECRET = "test-house-batch-secret-with-sufficient-entropy"


def _row() -> dict:
    return {
        "brand": "Imperial",
        "technology": "timber-frame",
        "gross_area_m2": "126",
        "floors": 1,
        "layout": "compact",
        "rooms": [
            {"type": "entrance", "name": "Előtér", "target_area_m2": "16.32"},
            {"type": "living", "name": "Nappali", "target_area_m2": "19.72"},
            {"type": "kitchen", "name": "Konyha", "target_area_m2": "15.60"},
            {"type": "bathroom", "name": "Fürdő", "target_area_m2": "11.60"},
            {"type": "bedroom", "name": "Háló 1", "target_area_m2": "10.54"},
            {"type": "bedroom", "name": "Háló 2", "target_area_m2": "10.54"},
        ],
    }


def test_parse_enforces_object_rows_and_one_to_one_hundred_limit():
    assert parse_batch_json("[{}]") == [{}]
    with pytest.raises(HouseBatchError, match="1–100"):
        parse_batch_json("[]")
    with pytest.raises(HouseBatchError, match="JSON-objektum"):
        parse_batch_json("[1]")


def test_dry_run_is_read_only_deterministic_and_marks_duplicates():
    now = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    result = dry_run_batch(
        [_row(), _row()],
        source=SOURCE,
        actor_subject="ITEP-42",
        permission_revision="PERM-7",
        pricing_revision="PRICE-3",
        secret=SECRET,
        now=now,
    )
    assert result["counts"] == {"ready": 1, "invalid": 0, "duplicate": 1}
    assert result["results"][0]["svg"].startswith("<svg")
    assert result["results"][1]["duplicateOf"] == 1
    claims = validate_dry_run_token(
        result["dryRunToken"],
        rows=[_row(), _row()],
        secret=SECRET,
        actor_subject="ITEP-42",
        source=SOURCE,
        permission_revision="PERM-7",
        pricing_revision="PRICE-3",
        now=now + timedelta(minutes=29),
    )
    assert claims["batchHash"] == result["batchHash"]


def test_dry_run_returns_row_error_without_blocking_valid_rows():
    invalid = _row()
    invalid["gross_area_m2"] = 12
    result = dry_run_batch(
        [invalid, _row()],
        source=SOURCE,
        actor_subject="ITEP-42",
        permission_revision="PERM-7",
        pricing_revision="PRICE-3",
        secret=SECRET,
    )
    assert result["status"] == "has_errors"
    assert result["counts"] == {"ready": 1, "invalid": 1, "duplicate": 0}
    assert result["results"][0]["errorCode"] == "geometry_validation_failed"


def test_token_fails_closed_on_expiry_actor_and_source_revision():
    now = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    result = dry_run_batch(
        [_row()],
        source=SOURCE,
        actor_subject="ITEP-42",
        permission_revision="PERM-7",
        pricing_revision="PRICE-3",
        secret=SECRET,
        now=now,
    )
    with pytest.raises(HouseBatchError, match="lejárt"):
        validate_dry_run_token(
            result["dryRunToken"],
            rows=[_row()],
            secret=SECRET,
            actor_subject="ITEP-42",
            source=SOURCE,
            permission_revision="PERM-7",
            pricing_revision="PRICE-3",
            now=now + timedelta(minutes=30),
        )
    with pytest.raises(HouseBatchError, match="stale_dry_run"):
        validate_dry_run_token(
            result["dryRunToken"],
            rows=[_row()],
            secret=SECRET,
            actor_subject="ITEP-99",
            source=SOURCE,
            permission_revision="PERM-7",
            pricing_revision="PRICE-3",
            now=now,
        )
    changed = _row()
    changed["style"] = "eltérő"
    with pytest.raises(HouseBatchError, match="stale_dry_run"):
        validate_dry_run_token(
            result["dryRunToken"],
            rows=[changed],
            secret=SECRET,
            actor_subject="ITEP-42",
            source=SOURCE,
            permission_revision="PERM-7",
            pricing_revision="PRICE-3",
            now=now,
        )


def test_one_hundred_unique_rows_finish_within_five_seconds():
    rows = []
    for index in range(100):
        row = deepcopy(_row())
        row["style"] = f"kortárs-{index:03d}"
        rows.append(row)
    started = perf_counter()
    result = dry_run_batch(
        rows,
        source=SOURCE,
        actor_subject="ITEP-42",
        permission_revision="PERM-7",
        pricing_revision="PRICE-3",
        secret=SECRET,
        include_svg=False,
    )
    assert perf_counter() - started < 5
    assert result["counts"] == {"ready": 100, "invalid": 0, "duplicate": 0}
