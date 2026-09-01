from __future__ import annotations

import json

import pytest

from app.services.house_geometry import (
    HouseGeometryError,
    canonical_json,
    generate_houseplan,
    geometry_signature,
    polygon_area_mm2,
)
from app.services.house_svg import render_houseplan_svg

SOURCE = {"id": "SRC-001", "revision": 4, "sha256": "a" * 64}


@pytest.fixture(autouse=True)
def clean_database():
    """Pure geometry tests must not pay for or mutate the application DB fixture."""
    yield


def _one_floor(name: str = "Nappali") -> dict:
    return {
        "brand": "Imperial",
        "technology": "timber-frame",
        "gross_area_m2": "126",
        "floors": 1,
        "layout": "compact",
        "roof": "gable",
        "style": "kortárs",
        "rooms": [
            {"type": "entrance", "name": "Előtér", "target_area_m2": "16.32", "level": 1},
            {"type": "living", "name": name, "target_area_m2": "19.72", "level": 1},
            {"type": "kitchen", "name": "Konyha", "target_area_m2": "15.60", "level": 1},
            {"type": "bathroom", "name": "Fürdő", "target_area_m2": "11.60", "level": 1},
            {"type": "bedroom", "name": "Háló 1", "target_area_m2": "10.54", "level": 1},
            {"type": "bedroom", "name": "Háló 2", "target_area_m2": "10.54", "level": 1},
        ],
    }


def _two_floor() -> dict:
    data = _one_floor()
    data["gross_area_m2"] = "192"
    data["floors"] = 2
    data["rooms"] = [
        {"type": "entrance", "name": "Előtér", "target_area_m2": "14.16", "level": 1},
        {"type": "living", "name": "Nappali", "target_area_m2": "18.29", "level": 1},
        {"type": "kitchen", "name": "Konyha", "target_area_m2": "12.48", "level": 1},
        {"type": "bathroom", "name": "Vendégfürdő", "target_area_m2": "8.40", "level": 1},
        {"type": "bedroom", "name": "Vendégszoba", "target_area_m2": "9.80", "level": 1},
        {"type": "living", "name": "Családi tér", "target_area_m2": "15.34", "level": 2},
        {"type": "bedroom", "name": "Háló 1", "target_area_m2": "13.68", "level": 2},
        {"type": "bedroom", "name": "Háló 2", "target_area_m2": "11.55", "level": 2},
        {"type": "bathroom", "name": "Fürdő", "target_area_m2": "14.16", "level": 2},
        {"type": "storage", "name": "Gardrób", "target_area_m2": "8.40", "level": 2},
    ]
    return data


def test_one_floor_is_deterministic_canonical_and_area_balanced():
    first = generate_houseplan(_one_floor(), SOURCE)
    second = generate_houseplan(
        json.loads(json.dumps(_one_floor())), dict(reversed(list(SOURCE.items())))
    )
    assert first == second
    assert len(first["geometrySignature"]) == 64
    assert geometry_signature(first["geometry"]) == first["geometrySignature"]
    level = first["geometry"]["levels"][0]
    equation = level["areaEquation"]
    assert (
        equation["roomTargetMm2"]
        + equation["circulationMm2"]
        + equation["coreMm2"]
        + equation["wallReserveMm2"]
        == equation["grossInternalAreaMm2"]
    )
    assert (
        sum(polygon_area_mm2(room["polygon"]) for room in level["rooms"])
        == equation["roomTargetMm2"]
    )
    assert all(room["areaDeviationBasisPoints"] <= 1000 for room in level["rooms"])
    assert all(room["targetAreaMm2"] == room["actualAreaMm2"] for room in level["rooms"])
    assert level["connections"][0]["id"].startswith("C")
    assert any(row["roomB"] == "outside" for row in level["connections"])
    assert any(row["kind"] == "window" for row in level["openings"])
    for wall_id in {row["wallId"] for row in level["openings"]}:
        intervals = sorted(
            (row["offset"], row["offset"] + row["width"])
            for row in level["openings"]
            if row["wallId"] == wall_id
        )
        assert all(
            left[1] <= right[0]
            for left, right in zip(intervals, intervals[1:], strict=False)
        )


def test_multi_floor_has_stable_overlapping_core_and_vertical_connection():
    result = generate_houseplan(_two_floor(), SOURCE)
    geometry = result["geometry"]
    assert len(geometry["levels"]) == 2
    assert len(geometry["verticalCores"]) == 1
    assert len(geometry["verticalConnections"]) == 1
    core = geometry["verticalCores"][0]
    assert polygon_area_mm2(core["polygon"]) == 8_000_000
    assert core["fromLevelId"] == "L01"
    assert core["toLevelId"] == "L02"


def test_accessible_multi_floor_adds_separate_lift_core_with_real_room_links():
    data = _two_floor()
    data["accessibility"] = True
    geometry = generate_houseplan(data, SOURCE)["geometry"]
    assert [core["kind"] for core in geometry["verticalCores"]] == ["stair", "lift"]
    room_ids = {room["id"] for level in geometry["levels"] for room in level["rooms"]}
    for connection in geometry["verticalConnections"]:
        assert connection["fromRoomId"] in room_ids
        assert connection["toRoomId"] in room_ids


def test_canonical_signature_ignores_object_and_id_array_order():
    geometry = generate_houseplan(_one_floor(), SOURCE)["geometry"]
    shuffled = dict(reversed(list(geometry.items())))
    shuffled["levels"] = list(reversed(geometry["levels"]))
    shuffled["levels"][0] = dict(reversed(list(shuffled["levels"][0].items())))
    shuffled["levels"][0]["rooms"] = list(reversed(shuffled["levels"][0]["rooms"]))
    assert canonical_json(shuffled) == canonical_json(geometry)
    assert geometry_signature(shuffled) == geometry_signature(geometry)


def test_svg_is_hash_stable_and_escapes_room_labels():
    result = generate_houseplan(_one_floor("Nappali <script>"), SOURCE)
    first = render_houseplan_svg(result["geometry"])
    second = render_houseplan_svg(result["geometry"])
    assert first == second
    assert "<script>" not in first
    assert "Nappali &lt;script&gt;" in first
    assert result["geometrySignature"] in first


def test_invalid_ratio_and_sub_grid_area_fail_closed():
    invalid = _one_floor()
    invalid["rooms"][0]["target_area_m2"] = "8.005"
    with pytest.raises(HouseGeometryError, match="0,01"):
        generate_houseplan(invalid, SOURCE)
    too_small = _one_floor()
    for room in too_small["rooms"]:
        room["target_area_m2"] = "2"
    with pytest.raises(HouseGeometryError, match="helyiségarány"):
        generate_houseplan(too_small, SOURCE)


def test_self_intersecting_polygon_is_rejected():
    with pytest.raises(HouseGeometryError, match="Önmetsző"):
        polygon_area_mm2([[0, 0], [1000, 1000], [0, 1000], [1000, 0], [0, 0]])


def test_required_adjacency_is_enforced_and_part_of_normalized_input():
    valid = generate_houseplan(_one_floor(), SOURCE)
    assert valid["normalizedInput"]["requiredAdjacencies"] == [
        ["entrance", "living"],
        ["kitchen", "living"],
    ]
    invalid = _one_floor()
    invalid["required_adjacencies"] = [["entrance", "bedroom"]]
    with pytest.raises(HouseGeometryError, match="Hiányzó kötelező"):
        generate_houseplan(invalid, SOURCE)
