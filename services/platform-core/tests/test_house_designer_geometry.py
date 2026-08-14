import pytest

from app.services.house_designer_geometry import (
    GeometryError,
    adapt_houseplan_geometry,
    apply_command,
    canonical_sha256,
    empty_geometry,
    gross_area_m2,
    validate_geometry,
)


def _ring(width: int, depth: int) -> list[dict[str, int]]:
    return [
        {"x": 0, "y": 0},
        {"x": width, "y": 0},
        {"x": width, "y": depth},
        {"x": 0, "y": depth},
        {"x": 0, "y": 0},
    ]


def test_blank_house_is_deterministic_and_measured_in_millimetres():
    first = empty_geometry(10_000, 8_000)
    second = empty_geometry(10_000, 8_000)
    assert canonical_sha256(first) == canonical_sha256(second)
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


def test_maximum_three_levels_and_attic_are_supported():
    geometry = apply_command(empty_geometry(), "add_level", {"levelType": "full_storey"})
    geometry = apply_command(geometry, "add_level", {"levelType": "attic"})
    assert geometry["levels"][-1]["type"] == "attic"
    with pytest.raises(GeometryError) as error:
        apply_command(geometry, "add_level", {"levelType": "full_storey"})
    assert error.value.code == "level_limit"


def test_unknown_command_and_invalid_dimension_fail_closed():
    with pytest.raises(GeometryError) as unknown:
        apply_command(empty_geometry(), "teleport_wall", {})
    assert unknown.value.code == "unknown_command"
    with pytest.raises(GeometryError) as invalid:
        empty_geometry(100, 8_000)
    assert invalid.value.code == "dimension_out_of_range"
