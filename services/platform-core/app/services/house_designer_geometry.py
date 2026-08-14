from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

SCHEMA_VERSION = "house-design-v1"
MIN_DIMENSION_MM = 600
MAX_DIMENSION_MM = 100_000
MAX_LEVELS = 3


class GeometryError(ValueError):
    def __init__(self, code: str, message: str, *, path: str = "geometry") -> None:
        super().__init__(message)
        self.code = code
        self.path = path


def empty_geometry(width_mm: int = 10_000, depth_mm: int = 8_000) -> dict[str, Any]:
    _validate_dimension(width_mm, "widthMm")
    _validate_dimension(depth_mm, "depthMm")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "units": "mm",
        "northAngleDeg": 0,
        "levels": [_new_level("L01", 0, width_mm, depth_mm)],
        "verticalCores": [],
        "verticalConnections": [],
    }


def canonical_json(value: dict[str, Any]) -> str:
    normalized = _normalize(deepcopy(value))
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def apply_command(
    geometry: dict[str, Any], command_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    result = deepcopy(geometry)
    handlers = {
        "set_footprint": _set_footprint,
        "add_level": _add_level,
        "remove_level": _remove_level,
        "add_room": _add_room,
        "move_room": _move_room,
        "resize_room": _resize_room,
        "remove_room": _remove_room,
        "set_room_function": _set_room_function,
        "set_roof": _set_roof,
        "set_north": _set_north,
    }
    handler = handlers.get(command_type)
    if handler is None:
        raise GeometryError("unknown_command", "Ismeretlen alaprajz-szerkesztési művelet.")
    handler(result, payload)
    findings = validate_geometry(result)
    blocker = next((item for item in findings if item["severity"] == "BLOCKER"), None)
    if blocker:
        raise GeometryError(blocker["code"], blocker["message"], path=blocker["path"])
    return _normalize(result)


def validate_geometry(geometry: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if geometry.get("schemaVersion") != SCHEMA_VERSION or geometry.get("units") != "mm":
        findings.append(
            _finding("schema_invalid", "BLOCKER", "A geometriai séma vagy mértékegység hibás.")
        )
        return findings
    levels = geometry.get("levels")
    if not isinstance(levels, list) or not 1 <= len(levels) <= MAX_LEVELS:
        findings.append(
            _finding("level_count_invalid", "BLOCKER", "A ház 1–3 szintből állhat.", "levels")
        )
        return findings
    seen: set[str] = set()
    for index, level in enumerate(levels):
        path = f"levels[{index}]"
        level_id = str(level.get("id") or "")
        if not level_id or level_id in seen:
            findings.append(
                _finding(
                    "level_id_invalid",
                    "BLOCKER",
                    "A szint azonosítója hiányzik vagy ismétlődik.",
                    path,
                )
            )
            continue
        seen.add(level_id)
        boundary = level.get("outerBoundary")
        box = _rectangle_box(boundary)
        if box is None:
            findings.append(
                _finding(
                    "footprint_invalid",
                    "BLOCKER",
                    "A szint kontúrja csak érvényes, zárt téglalap lehet ebben a kiadásban.",
                    f"{path}.outerBoundary",
                )
            )
            continue
        rooms = level.get("rooms", [])
        room_boxes: list[tuple[str, tuple[int, int, int, int]]] = []
        for room_index, room in enumerate(rooms):
            room_path = f"{path}.rooms[{room_index}]"
            room_id = str(room.get("id") or "")
            room_box = _rectangle_box(room.get("polygon"))
            if not room_id or room_box is None:
                findings.append(
                    _finding(
                        "room_invalid",
                        "BLOCKER",
                        "A helyiség azonosítója vagy geometriája hibás.",
                        room_path,
                    )
                )
                continue
            if not _contains(box, room_box):
                findings.append(
                    _finding(
                        "room_outside",
                        "BLOCKER",
                        "A helyiség nem lóghat ki az épület kontúrjából.",
                        room_path,
                    )
                )
            for other_id, other_box in room_boxes:
                if _overlaps(room_box, other_box):
                    findings.append(
                        _finding(
                            "room_overlap",
                            "BLOCKER",
                            f"A(z) {room_id} és {other_id} helyiség átfedi egymást.",
                            room_path,
                        )
                    )
            room_boxes.append((room_id, room_box))
        if not rooms:
            findings.append(
                _finding(
                    "rooms_missing",
                    "WARNING",
                    "A szint még nem tartalmaz helyiséget.",
                    f"{path}.rooms",
                )
            )
    if len(levels) > 1:
        cores = geometry.get("verticalCores", [])
        connections = geometry.get("verticalConnections", [])
        if not cores or len(connections) < len(levels) - 1:
            findings.append(
                _finding(
                    "vertical_connection_missing",
                    "BLOCKER",
                    "Többszintes háznál folytonos lépcső- vagy közlekedőmag szükséges.",
                    "verticalConnections",
                )
            )
    return findings


def gross_area_m2(geometry: dict[str, Any]) -> float:
    area_mm2 = 0
    for level in geometry.get("levels", []):
        box = _rectangle_box(level.get("outerBoundary"))
        if box:
            area_mm2 += (box[2] - box[0]) * (box[3] - box[1])
    return round(area_mm2 / 1_000_000, 2)


def adapt_houseplan_geometry(source: dict[str, Any]) -> dict[str, Any]:
    """Convert a released HousePlan geometry snapshot to the editable HD schema."""
    if source.get("unit") != "mm" or not isinstance(source.get("levels"), list):
        raise GeometryError(
            "template_schema_invalid",
            "A típusterv geometriája nem támogatott vagy nem milliméter alapú.",
        )
    levels: list[dict[str, Any]] = []
    source_levels = source["levels"]
    for index, item in enumerate(source_levels):
        boundary = item.get("boundary")
        if _rectangle_box(boundary) is None:
            raise GeometryError(
                "template_boundary_unsupported",
                "A típusterv nem téglalap alakú külső kontúrja még nem szerkeszthető.",
                path=f"levels[{index}].boundary",
            )
        rooms = []
        for room_index, room in enumerate(item.get("rooms") or []):
            polygon = room.get("polygon")
            if _rectangle_box(polygon) is None:
                raise GeometryError(
                    "template_room_unsupported",
                    "A típusterv nem téglalap alakú helyisége még nem szerkeszthető.",
                    path=f"levels[{index}].rooms[{room_index}].polygon",
                )
            rooms.append(
                {
                    "id": str(room.get("id") or f"R{room_index + 1:02d}"),
                    "name": str(room.get("name") or room.get("type") or "Helyiség"),
                    "function": str(room.get("function") or room.get("type") or "other"),
                    "polygon": deepcopy(polygon),
                }
            )
        levels.append(
            {
                "id": str(item.get("id") or f"L{index + 1:02d}"),
                "type": "ground" if index == 0 else str(item.get("type") or "full_storey"),
                "elevationMm": int(item.get("elevation") or 0),
                "heightMm": int(item.get("height") or 2_800),
                "outerBoundary": deepcopy(boundary),
                "rooms": rooms,
                "wallSegments": deepcopy(item.get("walls") or []),
                "openings": deepcopy(item.get("openings") or []),
                "connections": deepcopy(item.get("connections") or []),
                "voids": [],
                "roof": None,
            }
        )
    if levels and isinstance(source.get("roof"), dict):
        roof = source["roof"]
        levels[-1]["roof"] = {
            "type": str(roof.get("kind") or "pitched"),
            "pitchDeg": round(int(roof.get("pitchMilliDegrees") or 0) / 1_000, 3),
            "ridgeAxis": roof.get("ridgeAxis"),
        }
    cores = []
    for index, core in enumerate(source.get("verticalCores") or []):
        box = _rectangle_box(core.get("polygon"))
        if box is None:
            raise GeometryError(
                "template_core_unsupported",
                "A típusterv függőleges közlekedőmagja nem szerkeszthető.",
                path=f"verticalCores[{index}].polygon",
            )
        cores.append(
            {
                "id": str(core.get("id") or f"CORE-{index + 1:02d}"),
                "kind": str(core.get("kind") or "stair"),
                "xMm": box[0],
                "yMm": box[1],
                "widthMm": box[2] - box[0],
                "depthMm": box[3] - box[1],
            }
        )
    result = _normalize(
        {
            "schemaVersion": SCHEMA_VERSION,
            "units": "mm",
            "northAngleDeg": int(source.get("northAngleDeg") or 0),
            "levels": levels,
            "verticalCores": cores,
            "verticalConnections": deepcopy(source.get("verticalConnections") or []),
        }
    )
    blocker = next(
        (item for item in validate_geometry(result) if item["severity"] == "BLOCKER"), None
    )
    if blocker:
        raise GeometryError(blocker["code"], blocker["message"], path=blocker["path"])
    return result


def _new_level(level_id: str, elevation_mm: int, width_mm: int, depth_mm: int) -> dict[str, Any]:
    return {
        "id": level_id,
        "type": "ground" if elevation_mm == 0 else "full_storey",
        "elevationMm": elevation_mm,
        "heightMm": 2_800,
        "outerBoundary": _ring(0, 0, width_mm, depth_mm),
        "rooms": [],
        "wallSegments": [],
        "openings": [],
        "connections": [],
        "voids": [],
        "roof": None,
    }


def _set_footprint(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level = _level(geometry, str(payload.get("levelId") or "L01"))
    width = int(payload["widthMm"])
    depth = int(payload["depthMm"])
    _validate_dimension(width, "widthMm")
    _validate_dimension(depth, "depthMm")
    if level.get("rooms"):
        raise GeometryError(
            "footprint_has_rooms",
            "A kontúr csak üres szinten méretezhető át; "
            "előbb módosítsa vagy törölje a helyiségeket.",
        )
    level["outerBoundary"] = _ring(0, 0, width, depth)


def _add_level(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    levels = geometry["levels"]
    if len(levels) >= MAX_LEVELS:
        raise GeometryError("level_limit", "Legfeljebb három szint hozható létre.", path="levels")
    source = levels[-1]
    source_box = _rectangle_box(source["outerBoundary"])
    assert source_box is not None
    level_id = f"L{len(levels) + 1:02d}"
    if payload.get("levelType") == "attic":
        level_type = "attic"
    else:
        level_type = "full_storey"
    created = _new_level(level_id, len(levels) * 3_000, source_box[2], source_box[3])
    created["type"] = level_type
    levels.append(created)
    core_id = str(payload.get("coreId") or "CORE-01")
    if not geometry["verticalCores"]:
        geometry["verticalCores"].append(
            {
                "id": core_id,
                "kind": "stair",
                "xMm": 1_000,
                "yMm": 1_000,
                "widthMm": 2_000,
                "depthMm": 3_000,
            }
        )
    geometry["verticalConnections"].append(
        {
            "id": f"VC-{len(levels) - 1:02d}",
            "coreId": core_id,
            "fromLevelId": source["id"],
            "toLevelId": level_id,
            "kind": "stair",
        }
    )


def _remove_level(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level_id = str(payload["levelId"])
    if len(geometry["levels"]) == 1:
        raise GeometryError("last_level", "Az egyetlen szint nem törölhető.")
    geometry["levels"] = [item for item in geometry["levels"] if item["id"] != level_id]
    geometry["verticalConnections"] = [
        item
        for item in geometry["verticalConnections"]
        if item["fromLevelId"] != level_id and item["toLevelId"] != level_id
    ]
    used_core_ids = {item["coreId"] for item in geometry["verticalConnections"]}
    geometry["verticalCores"] = [
        item for item in geometry["verticalCores"] if item["id"] in used_core_ids
    ]


def _add_room(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level = _level(geometry, str(payload["levelId"]))
    room_id = str(payload["roomId"])
    if any(item["id"] == room_id for item in level["rooms"]):
        raise GeometryError("room_exists", "A helyiségazonosító már létezik.")
    x, y = int(payload["xMm"]), int(payload["yMm"])
    width, depth = int(payload["widthMm"]), int(payload["depthMm"])
    _validate_dimension(width, "widthMm")
    _validate_dimension(depth, "depthMm")
    level["rooms"].append(
        {
            "id": room_id,
            "name": str(payload.get("name") or "Helyiség"),
            "function": str(payload.get("function") or "other"),
            "polygon": _ring(x, y, x + width, y + depth),
        }
    )


def _move_room(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    room = _room(_level(geometry, str(payload["levelId"])), str(payload["roomId"]))
    box = _rectangle_box(room["polygon"])
    assert box is not None
    x, y = int(payload["xMm"]), int(payload["yMm"])
    room["polygon"] = _ring(x, y, x + box[2] - box[0], y + box[3] - box[1])


def _resize_room(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    room = _room(_level(geometry, str(payload["levelId"])), str(payload["roomId"]))
    box = _rectangle_box(room["polygon"])
    assert box is not None
    width, depth = int(payload["widthMm"]), int(payload["depthMm"])
    _validate_dimension(width, "widthMm")
    _validate_dimension(depth, "depthMm")
    room["polygon"] = _ring(box[0], box[1], box[0] + width, box[1] + depth)


def _remove_room(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level = _level(geometry, str(payload["levelId"]))
    room_id = str(payload["roomId"])
    before = len(level["rooms"])
    level["rooms"] = [item for item in level["rooms"] if item["id"] != room_id]
    if len(level["rooms"]) == before:
        raise GeometryError("room_not_found", "A helyiség nem található.")


def _set_room_function(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    room = _room(_level(geometry, str(payload["levelId"])), str(payload["roomId"]))
    room["name"] = str(payload.get("name") or room["name"])
    room["function"] = str(payload["function"])


def _set_roof(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level = _level(geometry, str(payload.get("levelId") or geometry["levels"][-1]["id"]))
    roof_type = str(payload["roofType"])
    if roof_type not in {"flat", "gable", "hip", "shed"}:
        raise GeometryError("roof_type_invalid", "Nem támogatott tetőforma.")
    pitch = int(payload.get("pitchDeg") or (0 if roof_type == "flat" else 30))
    if not 0 <= pitch <= 60:
        raise GeometryError("roof_pitch_invalid", "A tető hajlásszöge 0–60 fok lehet.")
    level["roof"] = {"type": roof_type, "pitchDeg": pitch}


def _set_north(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    geometry["northAngleDeg"] = int(payload["northAngleDeg"]) % 360


def _level(geometry: dict[str, Any], level_id: str) -> dict[str, Any]:
    for level in geometry.get("levels", []):
        if level.get("id") == level_id:
            return level
    raise GeometryError("level_not_found", "A szint nem található.", path="levels")


def _room(level: dict[str, Any], room_id: str) -> dict[str, Any]:
    for room in level.get("rooms", []):
        if room.get("id") == room_id:
            return room
    raise GeometryError("room_not_found", "A helyiség nem található.", path="rooms")


def _validate_dimension(value: int, path: str) -> None:
    if not MIN_DIMENSION_MM <= value <= MAX_DIMENSION_MM:
        raise GeometryError(
            "dimension_out_of_range",
            f"A méret {MIN_DIMENSION_MM} és {MAX_DIMENSION_MM} mm között lehet.",
            path=path,
        )


def _ring(x1: int, y1: int, x2: int, y2: int) -> list[dict[str, int]]:
    return [
        {"x": x1, "y": y1},
        {"x": x2, "y": y1},
        {"x": x2, "y": y2},
        {"x": x1, "y": y2},
        {"x": x1, "y": y1},
    ]


def _rectangle_box(points: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(points, list) or len(points) != 5 or points[0] != points[-1]:
        return None
    try:
        xs = sorted({int(point["x"]) for point in points[:-1]})
        ys = sorted({int(point["y"]) for point in points[:-1]})
    except (KeyError, TypeError, ValueError):
        return None
    if len(xs) != 2 or len(ys) != 2 or xs[0] >= xs[1] or ys[0] >= ys[1]:
        return None
    expected = {(xs[0], ys[0]), (xs[1], ys[0]), (xs[1], ys[1]), (xs[0], ys[1])}
    actual = {(int(point["x"]), int(point["y"])) for point in points[:-1]}
    return (xs[0], ys[0], xs[1], ys[1]) if actual == expected else None


def _contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def _finding(code: str, severity: str, message: str, path: str = "geometry") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message, "path": path}


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [_normalize(item) for item in value]
        if normalized and all(isinstance(item, dict) and "id" in item for item in normalized):
            return sorted(normalized, key=lambda item: str(item["id"]))
        return normalized
    return value
