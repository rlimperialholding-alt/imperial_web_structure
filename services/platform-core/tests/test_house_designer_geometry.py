from copy import deepcopy

import pytest

from app.services.house_designer_geometry import (
    GeometryError,
    adapt_houseplan_geometry,
    apply_command,
    canonical_sha256,
    canonical_sha256_normalized,
    empty_geometry,
    gross_area_m2,
    validate_geometry,
)
from app.services.house_geometry import generate_houseplan


def _ring(width: int, depth: int) -> list[dict[str, int]]:
    return [
        {"x": 0, "y": 0},
        {"x": width, "y": 0},
        {"x": width, "y": depth},
        {"x": 0, "y": depth},
        {"x": 0, "y": 0},
    ]


def _rect(x: int, y: int, width: int, depth: int) -> list[dict[str, int]]:
    return [
        {"x": x, "y": y},
        {"x": x + width, "y": y},
        {"x": x + width, "y": y + depth},
        {"x": x, "y": y + depth},
        {"x": x, "y": y},
    ]


def _released_template(level_count: int) -> dict:
    levels = []
    for index in range(level_count):
        levels.append(
            {
                "id": f"L{index + 1:02d}",
                "type": "ground" if index == 0 else "full_storey",
                "elevation": index * 3_000,
                "height": 2_800,
                "boundary": _ring(10_000, 8_000),
                "rooms": [
                    {
                        "id": f"R{index + 1:02d}",
                        "name": f"Szoba {index + 1}",
                        "type": "other",
                        "polygon": _rect(0, 0, 4_000, 3_000),
                    }
                ],
                "walls": [],
                "openings": [],
                "connections": [],
            }
        )
    cores = (
        [
            {
                "id": "CORE-01",
                "kind": "stair",
                "polygon": _rect(1_000, 1_000, 2_000, 3_000),
            }
        ]
        if level_count > 1
        else []
    )
    vertical_connections = [
        {
            "id": f"VC-{index:02d}",
            "coreId": "CORE-01",
            "fromLevelId": f"L{index:02d}",
            "toLevelId": f"L{index + 1:02d}",
            "kind": "stair",
        }
        for index in range(1, level_count)
    ]
    return {
        "unit": "mm",
        "levels": levels,
        "verticalCores": cores,
        "verticalConnections": vertical_connections,
        "roof": {"kind": "gable", "pitchMilliDegrees": 30_000},
    }


def test_blank_house_is_deterministic_and_measured_in_millimetres():
    first = empty_geometry(10_000, 8_000)
    second = empty_geometry(10_000, 8_000)
    assert canonical_sha256(first) == canonical_sha256(second)
    assert canonical_sha256_normalized(first) == canonical_sha256(first)
    assert gross_area_m2(first) == 80.0
    assert first["units"] == "mm"


def test_released_houseplan_can_be_adapted_to_editable_geometry():
    source = {
        "unit": "mm",
        "levels": [
            {
                "id": "L01",
                "elevation": 0,
                "height": 3_000,
                "boundary": _ring(10_000, 8_000),
                "rooms": [
                    {
                        "id": "R01",
                        "name": "Nappali",
                        "type": "living",
                        "polygon": _ring(5_000, 4_000),
                    }
                ],
                "walls": [],
                "openings": [],
                "connections": [],
            }
        ],
        "verticalCores": [],
        "verticalConnections": [],
        "roof": {"kind": "gable", "pitchMilliDegrees": 30_000},
    }
    adapted = adapt_houseplan_geometry(source)
    assert adapted["schemaVersion"] == "house-design-v1"
    assert adapted["levels"][0]["rooms"][0]["function"] == "living"
    assert adapted["levels"][0]["roof"]["pitchDeg"] == 30.0
    assert gross_area_m2(adapted) == 80.0


@pytest.mark.parametrize("level_count", [1, 2, 3])
def test_released_template_flow_supports_one_two_and_three_storeys(level_count: int):
    adapted = adapt_houseplan_geometry(_released_template(level_count))
    assert len(adapted["levels"]) == level_count
    assert len(adapted["verticalConnections"]) == max(0, level_count - 1)
    assert not [item for item in validate_geometry(adapted) if item["severity"] == "BLOCKER"]


def test_generated_houseplan_contract_adapts_with_walls_openings_and_connections():
    source = generate_houseplan(
        {
            "brand": "Imperial",
            "technology": "timber-frame",
            "gross_area_m2": "126",
            "floors": 1,
            "layout": "compact",
            "roof": "gable",
            "style": "kortárs",
            "rooms": [
                {"type": "entrance", "name": "Előtér", "target_area_m2": "16.32", "level": 1},
                {"type": "living", "name": "Nappali", "target_area_m2": "19.72", "level": 1},
                {"type": "kitchen", "name": "Konyha", "target_area_m2": "15.60", "level": 1},
                {"type": "bathroom", "name": "Fürdő", "target_area_m2": "11.60", "level": 1},
                {"type": "bedroom", "name": "Háló 1", "target_area_m2": "10.54", "level": 1},
                {"type": "bedroom", "name": "Háló 2", "target_area_m2": "10.54", "level": 1},
            ],
        },
        {"id": "SRC-001", "revision": 4, "sha256": "a" * 64},
    )["geometry"]
    adapted = adapt_houseplan_geometry(source)
    level = adapted["levels"][0]
    assert level["wallSegments"]
    assert level["openings"]
    assert level["connections"]
    assert not [item for item in validate_geometry(adapted) if item["severity"] == "BLOCKER"]


def test_room_command_is_atomic_and_rejects_overlap():
    geometry = empty_geometry()
    geometry = apply_command(
        geometry,
        "add_room",
        {
            "levelId": "L01",
            "roomId": "R01",
            "name": "Nappali",
            "function": "living",
            "xMm": 0,
            "yMm": 0,
            "widthMm": 5_000,
            "depthMm": 4_000,
        },
    )
    before_hash = canonical_sha256(geometry)
    with pytest.raises(GeometryError) as error:
        apply_command(
            geometry,
            "add_room",
            {
                "levelId": "L01",
                "roomId": "R02",
                "xMm": 4_000,
                "yMm": 3_000,
                "widthMm": 3_000,
                "depthMm": 3_000,
            },
        )
    assert error.value.code == "room_overlap"
    assert canonical_sha256(geometry) == before_hash


def test_room_overlap_sweep_handles_unsorted_rooms_and_touching_edges():
    geometry = empty_geometry(10_000, 8_000)
    geometry["levels"][0]["rooms"] = [
        {
            "id": "R-EDGE",
            "name": "Érintkező",
            "function": "other",
            "polygon": _rect(2_000, 0, 2_000, 2_000),
        },
        {
            "id": "R-CROSS",
            "name": "Átfedő",
            "function": "other",
            "polygon": _rect(500, 500, 2_000, 1_000),
        },
        {
            "id": "R-BASE",
            "name": "Alap",
            "function": "other",
            "polygon": _rect(0, 0, 2_000, 2_000),
        },
    ]
    overlaps = [item for item in validate_geometry(geometry) if item["code"] == "room_overlap"]
    assert len(overlaps) == 2
    assert {item["path"] for item in overlaps} == {
        "levels[0].rooms[0]",
        "levels[0].rooms[1]",
    }


def test_room_cannot_leave_the_footprint():
    with pytest.raises(GeometryError) as error:
        apply_command(
            empty_geometry(8_000, 8_000),
            "add_room",
            {
                "levelId": "L01",
                "roomId": "R01",
                "xMm": 7_000,
                "yMm": 0,
                "widthMm": 2_000,
                "depthMm": 2_000,
            },
        )
    assert error.value.code == "room_outside"


def test_add_level_creates_vertical_core_and_connection():
    geometry = apply_command(empty_geometry(), "add_level", {"levelType": "full_storey"})
    assert len(geometry["levels"]) == 2
    assert len(geometry["verticalCores"]) == 1
    assert len(geometry["verticalConnections"]) == 1
    assert not [item for item in validate_geometry(geometry) if item["severity"] == "BLOCKER"]


def test_clone_level_copies_content_without_mutating_source():
    geometry = apply_command(
        empty_geometry(),
        "add_room",
        {
            "levelId": "L01",
            "roomId": "R01",
            "name": "Nappali",
            "function": "living",
            "xMm": 0,
            "yMm": 0,
            "widthMm": 4_000,
            "depthMm": 3_000,
        },
    )
    source_hash = canonical_sha256(geometry)
    cloned = apply_command(
        geometry,
        "clone_level",
        {"sourceLevelId": "L01", "levelType": "full_storey"},
    )
    assert canonical_sha256(geometry) == source_hash
    assert [level["id"] for level in cloned["levels"]] == ["L01", "L02"]
    assert cloned["levels"][1]["rooms"] == cloned["levels"][0]["rooms"]
    assert cloned["levels"][1]["rooms"] is not cloned["levels"][0]["rooms"]
    assert cloned["levels"][1]["roof"] is None
    assert len(cloned["verticalConnections"]) == 1
    assert not [item for item in validate_geometry(cloned) if item["severity"] == "BLOCKER"]


def test_clone_level_can_create_attic_and_rejects_invalid_source_or_limit():
    geometry = apply_command(
        empty_geometry(),
        "clone_level",
        {"sourceLevelId": "L01", "levelType": "attic"},
    )
    assert geometry["levels"][1]["type"] == "attic"
    assert geometry["levels"][1]["usableHeightZone"]["minClearHeightMm"] == 1_900
    with pytest.raises(GeometryError) as attic:
        apply_command(
            geometry,
            "clone_level",
            {"sourceLevelId": "L02", "levelType": "full_storey"},
        )
    assert attic.value.code == "attic_clone_invalid"

    three_levels = apply_command(empty_geometry(), "add_level", {"levelType": "full_storey"})
    three_levels = apply_command(three_levels, "add_level", {"levelType": "full_storey"})
    with pytest.raises(GeometryError) as limit:
        apply_command(
            three_levels,
            "clone_level",
            {"sourceLevelId": "L01", "levelType": "full_storey"},
        )
    assert limit.value.code == "level_limit"


def test_furniture_helper_commands_are_bounded_atomic_and_cloneable():
    geometry = apply_command(
        empty_geometry(),
        "add_furniture",
        {
            "levelId": "L01",
            "furnitureKind": "sofa",
            "label": "Kanapé",
            "xMm": 1_000,
            "yMm": 1_000,
            "widthMm": 2_000,
            "depthMm": 900,
            "rotationDeg": 0,
        },
    )
    item = geometry["levels"][0]["furnitureLayer"][0]
    assert item["id"] == "F001"
    moved = apply_command(
        geometry,
        "move_furniture",
        {
            "levelId": "L01",
            "furnitureId": "F001",
            "xMm": 2_000,
            "yMm": 1_500,
            "rotationDeg": 90,
        },
    )
    resized = apply_command(
        moved,
        "resize_furniture",
        {
            "levelId": "L01",
            "furnitureId": "F001",
            "widthMm": 2_200,
            "depthMm": 1_000,
        },
    )
    assert resized["levels"][0]["furnitureLayer"][0]["rotationDeg"] == 90
    cloned = apply_command(
        resized,
        "clone_level",
        {"sourceLevelId": "L01", "levelType": "full_storey"},
    )
    assert cloned["levels"][1]["furnitureLayer"] == cloned["levels"][0]["furnitureLayer"]
    assert cloned["levels"][1]["furnitureLayer"] is not cloned["levels"][0]["furnitureLayer"]

    before_hash = canonical_sha256(resized)
    with pytest.raises(GeometryError) as outside:
        apply_command(
            resized,
            "move_furniture",
            {
                "levelId": "L01",
                "furnitureId": "F001",
                "xMm": 9_500,
                "yMm": 7_500,
                "rotationDeg": 0,
            },
        )
    assert outside.value.code == "furniture_outside"
    assert canonical_sha256(resized) == before_hash

    removed = apply_command(
        resized,
        "remove_furniture",
        {"levelId": "L01", "furnitureId": "F001"},
    )
    assert removed["levels"][0]["furnitureLayer"] == []


def test_maximum_three_levels_and_attic_are_supported():
    geometry = apply_command(empty_geometry(), "add_level", {"levelType": "full_storey"})
    geometry = apply_command(geometry, "add_level", {"levelType": "attic"})
    assert geometry["levels"][-1]["type"] == "attic"
    with pytest.raises(GeometryError) as error:
        apply_command(geometry, "add_level", {"levelType": "full_storey"})
    assert error.value.code == "level_limit"


@pytest.mark.parametrize(
    ("level_types", "expected_count"),
    [([], 1), (["full_storey"], 2), (["full_storey", "full_storey"], 3)],
)
def test_blank_one_two_and_three_storey_houses_are_traceably_valid(
    level_types: list[str], expected_count: int
):
    geometry = empty_geometry()
    for level_type in level_types:
        geometry = apply_command(geometry, "add_level", {"levelType": level_type})
    assert len(geometry["levels"]) == expected_count
    assert len(geometry["verticalConnections"]) == max(0, expected_count - 1)
    assert not [item for item in validate_geometry(geometry) if item["severity"] == "BLOCKER"]


def test_attic_has_bounded_usable_height_zone_and_must_remain_topmost():
    geometry = apply_command(empty_geometry(), "add_level", {"levelType": "attic"})
    attic = geometry["levels"][-1]
    assert attic["usableHeightZone"]["minClearHeightMm"] == 1_900
    assert attic["roof"] == {"pitchDeg": 30, "type": "gable"}
    with pytest.raises(GeometryError) as error:
        apply_command(geometry, "add_level", {"levelType": "full_storey"})
    assert error.value.code == "attic_not_topmost"


def test_wall_opening_and_t_junction_commands_are_atomic_and_bounded():
    geometry = apply_command(
        empty_geometry(),
        "add_wall",
        {
            "levelId": "L01",
            "x1Mm": 0,
            "y1Mm": 4_000,
            "x2Mm": 10_000,
            "y2Mm": 4_000,
            "thicknessMm": 150,
        },
    )
    wall_id = geometry["levels"][0]["wallSegments"][0]["id"]
    geometry = apply_command(
        geometry,
        "add_opening",
        {
            "levelId": "L01",
            "wallId": wall_id,
            "openingKind": "door",
            "offsetMm": 1_000,
            "widthMm": 900,
            "heightMm": 2_100,
        },
    )
    before_hash = canonical_sha256(geometry)
    with pytest.raises(GeometryError) as outside:
        apply_command(
            geometry,
            "add_opening",
            {
                "levelId": "L01",
                "wallId": wall_id,
                "offsetMm": 9_500,
                "widthMm": 900,
            },
        )
    assert outside.value.code == "opening_outside_wall"
    assert canonical_sha256(geometry) == before_hash

    without_opening = apply_command(
        empty_geometry(),
        "add_wall",
        {
            "levelId": "L01",
            "x1Mm": 0,
            "y1Mm": 4_000,
            "x2Mm": 10_000,
            "y2Mm": 4_000,
        },
    )
    t_junction = apply_command(
        without_opening,
        "add_wall",
        {
            "levelId": "L01",
            "x1Mm": 5_000,
            "y1Mm": 0,
            "x2Mm": 5_000,
            "y2Mm": 4_000,
        },
    )
    assert len(t_junction["levels"][0]["wallSegments"]) == 2
    with pytest.raises(GeometryError) as crossing:
        apply_command(
            without_opening,
            "add_wall",
            {
                "levelId": "L01",
                "x1Mm": 5_000,
                "y1Mm": 0,
                "x2Mm": 5_000,
                "y2Mm": 8_000,
            },
        )
    assert crossing.value.code == "wall_self_intersection"


def test_disconnected_upper_level_and_invalid_stair_fail_closed():
    geometry = apply_command(empty_geometry(), "add_level", {"levelType": "full_storey"})
    disconnected = deepcopy(geometry)
    disconnected["verticalConnections"] = []
    before_hash = canonical_sha256(disconnected)
    with pytest.raises(GeometryError) as missing:
        apply_command(disconnected, "set_north", {"northAngleDeg": 15})
    assert missing.value.code == "vertical_connection_missing"
    assert canonical_sha256(disconnected) == before_hash

    with pytest.raises(GeometryError) as stair:
        apply_command(
            geometry,
            "set_stair_geometry",
            {
                "coreId": "CORE-01",
                "clearWidthMm": 700,
                "riserMm": 300,
                "treadMm": 100,
                "headroomMm": 1_500,
                "landingDepthMm": 500,
            },
        )
    assert stair.value.code == "stair_geometry_invalid"


def test_room_connection_must_touch_both_referenced_room_boundaries():
    geometry = empty_geometry()
    for room_id, x_mm in (("R01", 0), ("R02", 3_000)):
        geometry = apply_command(
            geometry,
            "add_room",
            {
                "levelId": "L01",
                "roomId": room_id,
                "function": "other",
                "xMm": x_mm,
                "yMm": 0,
                "widthMm": 2_000,
                "depthMm": 2_000,
            },
        )
    geometry = apply_command(
        geometry,
        "add_wall",
        {
            "levelId": "L01",
            "x1Mm": 0,
            "y1Mm": 4_000,
            "x2Mm": 10_000,
            "y2Mm": 4_000,
        },
    )
    wall_id = geometry["levels"][0]["wallSegments"][0]["id"]
    geometry = apply_command(
        geometry,
        "add_opening",
        {
            "levelId": "L01",
            "wallId": wall_id,
            "offsetMm": 1_000,
            "widthMm": 900,
        },
    )
    opening_id = geometry["levels"][0]["openings"][0]["id"]
    before_hash = canonical_sha256(geometry)
    with pytest.raises(GeometryError) as error:
        apply_command(
            geometry,
            "add_connection",
            {
                "levelId": "L01",
                "roomA": "R01",
                "roomB": "R02",
                "openingId": opening_id,
            },
        )
    assert error.value.code == "connection_geometry_invalid"
    assert canonical_sha256(geometry) == before_hash


def test_unknown_command_and_invalid_dimension_fail_closed():
    with pytest.raises(GeometryError) as unknown:
        apply_command(empty_geometry(), "teleport_wall", {})
    assert unknown.value.code == "unknown_command"
    with pytest.raises(GeometryError) as invalid:
        empty_geometry(100, 8_000)
    assert invalid.value.code == "dimension_out_of_range"
