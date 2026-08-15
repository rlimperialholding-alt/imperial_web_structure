from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

SCHEMA_VERSION = "house-design-v1"
MIN_DIMENSION_MM = 600
MAX_DIMENSION_MM = 100_000
MAX_LEVELS = 3
MIN_WALL_THICKNESS_MM = 80
MAX_WALL_THICKNESS_MM = 800
MIN_OPENING_WIDTH_MM = 300
MIN_OPENING_EDGE_CLEARANCE_MM = 100
MIN_OPENING_SPACING_MM = 100
STAIR_GEOMETRY_VERSION = "hd-stair-geometry-v1"
MAX_ROOMS_PER_LEVEL = 500
MAX_WALLS_PER_LEVEL = 500
MAX_OPENINGS_PER_LEVEL = 500


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
    normalized = _normalize(value)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_sha256_normalized(value: dict[str, Any]) -> str:
    """Hash a geometry already normalized by this module without another tree copy."""

    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def apply_command(
    geometry: dict[str, Any], command_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    result, _ = apply_command_with_findings(geometry, command_type, payload)
    return result


def apply_command_with_findings(
    geometry: dict[str, Any], command_type: str, payload: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    result = deepcopy(geometry)
    handlers = {
        "set_footprint": _set_footprint,
        "add_level": _add_level,
        "remove_level": _remove_level,
        "add_wall": _add_wall,
        "move_wall": _move_wall,
        "split_wall": _split_wall,
        "remove_wall": _remove_wall,
        "add_opening": _add_opening,
        "move_opening": _move_opening,
        "resize_opening": _resize_opening,
        "remove_opening": _remove_opening,
        "add_connection": _add_connection,
        "remove_connection": _remove_connection,
        "set_stair_geometry": _set_stair_geometry,
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
    _sort_id_lists_in_place(result)
    return result, findings


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
        level_type = str(level.get("type") or "")
        try:
            elevation = int(level.get("elevationMm"))
            height = int(level.get("heightMm"))
        except (TypeError, ValueError):
            elevation, height = 0, 0
        previous_elevation = (
            _integer_value(levels[index - 1], "elevationMm", default=0)
            if index > 0
            else None
        )
        if (
            level_type not in {"ground", "full_storey", "attic"}
            or (index == 0 and level_type != "ground")
            or (index > 0 and level_type == "ground")
            or height < 1_900
            or (previous_elevation is not None and elevation <= previous_elevation)
        ):
            findings.append(
                _finding(
                    "level_metadata_invalid",
                    "BLOCKER",
                    "A szint típusa, magassága vagy emelkedési sorrendje hibás.",
                    path,
                )
            )
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
        raw_rooms = level.get("rooms", [])
        room_boundary_boxes = (
            [
                room_box
                for room in raw_rooms
                if (room_box := _rectangle_box(room.get("polygon"))) is not None
            ]
            if isinstance(raw_rooms, list)
            else []
        )
        walls = level.get("wallSegments", [])
        if not isinstance(walls, list) or len(walls) > MAX_WALLS_PER_LEVEL:
            findings.append(
                _finding(
                    "wall_collection_invalid",
                    "BLOCKER",
                    f"Egy szinten legfeljebb {MAX_WALLS_PER_LEVEL} fal lehet.",
                    f"{path}.wallSegments",
                )
            )
            walls = []
        wall_by_id: dict[str, tuple[int, int, int, int]] = {}
        wall_thickness_by_id: dict[str, int] = {}
        wall_paths: dict[str, str] = {}
        for wall_index, wall in enumerate(walls):
            wall_path = f"{path}.wallSegments[{wall_index}]"
            wall_id = str(wall.get("id") or "")
            segment = _wall_segment(wall)
            if not wall_id or wall_id in wall_by_id or segment is None:
                findings.append(
                    _finding(
                        "wall_invalid",
                        "BLOCKER",
                        "A fal azonosítója vagy tengelyvonala hibás; csak vízszintes vagy "
                        "függőleges, nem nulla hosszúságú fal támogatott.",
                        wall_path,
                    )
                )
                continue
            thickness = _integer_value(wall, "thicknessMm", "thickness", default=150)
            if not MIN_WALL_THICKNESS_MM <= thickness <= MAX_WALL_THICKNESS_MM:
                findings.append(
                    _finding(
                        "wall_thickness_invalid",
                        "BLOCKER",
                        f"A falvastagság {MIN_WALL_THICKNESS_MM}–{MAX_WALL_THICKNESS_MM} mm lehet.",
                        wall_path,
                    )
                )
            if not _point_in_box((segment[0], segment[1]), box) or not _point_in_box(
                (segment[2], segment[3]), box
            ):
                findings.append(
                    _finding(
                        "wall_outside",
                        "BLOCKER",
                        "A fal egyik végpontja sem kerülhet a szintkontúron kívülre.",
                        wall_path,
                    )
                )
            wall_by_id[wall_id] = segment
            wall_thickness_by_id[wall_id] = thickness
            wall_paths[wall_id] = wall_path
        wall_items = sorted(wall_by_id.items())
        for wall_index, (wall_id, segment) in enumerate(wall_items):
            for other_id, other in wall_items[wall_index + 1 :]:
                if _segments_intersect_invalidly(segment, other):
                    findings.append(
                        _finding(
                            "wall_self_intersection",
                            "BLOCKER",
                            f"A(z) {wall_id} és {other_id} fal tiltott módon metszi egymást.",
                            wall_paths[other_id],
                        )
                    )
            for endpoint in ((segment[0], segment[1]), (segment[2], segment[3])):
                if _point_on_box_boundary(endpoint, box) or any(
                    _point_on_box_boundary(endpoint, room_box) for room_box in room_boundary_boxes
                ):
                    continue
                if not any(
                    candidate_id != wall_id and _point_on_segment(endpoint, candidate)
                    for candidate_id, candidate in wall_items
                ):
                    findings.append(
                        _finding(
                            "wall_floating_endpoint",
                            "BLOCKER",
                            f"A(z) {wall_id} fal végpontja nem csatlakozik falhoz vagy kontúrhoz.",
                            wall_paths[wall_id],
                        )
                    )

        openings = level.get("openings", [])
        if not isinstance(openings, list) or len(openings) > MAX_OPENINGS_PER_LEVEL:
            findings.append(
                _finding(
                    "opening_collection_invalid",
                    "BLOCKER",
                    f"Egy szinten legfeljebb {MAX_OPENINGS_PER_LEVEL} nyílás lehet.",
                    f"{path}.openings",
                )
            )
            openings = []
        opening_ids: set[str] = set()
        opening_wall_ids: dict[str, str] = {}
        opening_by_wall: dict[str, list[tuple[int, int, str]]] = {}
        for opening_index, opening in enumerate(openings):
            opening_path = f"{path}.openings[{opening_index}]"
            opening_id = str(opening.get("id") or "")
            wall_id = str(opening.get("wallId") or "")
            width = _integer_value(opening, "widthMm", "width", default=0)
            offset = _integer_value(opening, "offsetMm", "offset", default=-1)
            height = _integer_value(opening, "heightMm", "height", default=0)
            sill = _integer_value(opening, "sillHeightMm", "sill", default=0)
            if not opening_id or opening_id in opening_ids:
                findings.append(
                    _finding(
                        "opening_id_invalid",
                        "BLOCKER",
                        "A nyílás azonosítója hiányzik vagy ismétlődik.",
                        opening_path,
                    )
                )
                continue
            if height < 300 or sill < 0 or sill + height > int(level.get("heightMm") or 0):
                findings.append(
                    _finding(
                        "opening_height_invalid",
                        "BLOCKER",
                        "A nyílás magasságának és parapetének a szintmagasságon belül "
                        "kell maradnia.",
                        opening_path,
                    )
                )
            opening_ids.add(opening_id)
            segment = wall_by_id.get(wall_id)
            if segment is None:
                findings.append(
                    _finding(
                        "opening_wall_missing",
                        "BLOCKER",
                        "A nyílásnak pontosan egy létező falra kell hivatkoznia.",
                        opening_path,
                    )
                )
                continue
            opening_wall_ids[opening_id] = wall_id
            wall_length = _segment_length(segment)
            if width < MIN_OPENING_WIDTH_MM or offset < 0 or offset + width > wall_length:
                findings.append(
                    _finding(
                        "opening_outside_wall",
                        "BLOCKER",
                        "A nyílásnak a fal határain belül, a kötelező széltávolsággal "
                        "kell maradnia.",
                        opening_path,
                    )
                )
            elif (
                offset < MIN_OPENING_EDGE_CLEARANCE_MM
                or wall_length - (offset + width) < MIN_OPENING_EDGE_CLEARANCE_MM
            ):
                findings.append(
                    _finding(
                        "opening_edge_clearance_review",
                        "WARNING",
                        "A nyílás széltávolságát a jóváhagyott verziózott szabályban "
                        "ellenőrizni kell.",
                        opening_path,
                    )
                )
            opening_by_wall.setdefault(wall_id, []).append((offset, offset + width, opening_path))
        for rows in opening_by_wall.values():
            rows.sort()
            previous_end: int | None = None
            for start, end, opening_path in rows:
                if previous_end is not None and start < previous_end:
                    findings.append(
                        _finding(
                            "opening_overlap",
                            "BLOCKER",
                            "A nyílások között kötelező biztonsági távolságot kell tartani.",
                            opening_path,
                        )
                    )
                elif previous_end is not None and start < previous_end + MIN_OPENING_SPACING_MM:
                    findings.append(
                        _finding(
                            "opening_spacing_review",
                            "WARNING",
                            "A nyílásközt a jóváhagyott verziózott szabályban ellenőrizni kell.",
                            opening_path,
                        )
                    )
                previous_end = max(previous_end or end, end)

        rooms = raw_rooms
        if not isinstance(rooms, list) or len(rooms) > MAX_ROOMS_PER_LEVEL:
            findings.append(
                _finding(
                    "room_collection_invalid",
                    "BLOCKER",
                    f"Egy szinten legfeljebb {MAX_ROOMS_PER_LEVEL} helyiség lehet.",
                    f"{path}.rooms",
                )
            )
            rooms = []
        room_boxes: list[tuple[str, tuple[int, int, int, int], str]] = []
        room_box_by_id: dict[str, tuple[int, int, int, int]] = {}
        seen_room_ids: set[str] = set()
        for room_index, room in enumerate(rooms):
            room_path = f"{path}.rooms[{room_index}]"
            room_id = str(room.get("id") or "")
            room_box = _rectangle_box(room.get("polygon"))
            if not room_id or room_id in seen_room_ids or room_box is None:
                findings.append(
                    _finding(
                        "room_invalid",
                        "BLOCKER",
                        "A helyiség azonosítója vagy geometriája hibás.",
                        room_path,
                    )
                )
                continue
            seen_room_ids.add(room_id)
            room_box_by_id[room_id] = room_box
            if not _contains(box, room_box):
                findings.append(
                    _finding(
                        "room_outside",
                        "BLOCKER",
                        "A helyiség nem lóghat ki az épület kontúrjából.",
                        room_path,
                    )
                )
            room_boxes.append((room_id, room_box, room_path))
        # Sweep on the x axis instead of comparing every room with every other
        # room.  The editor currently accepts axis-aligned rectangles, so rooms
        # whose x intervals have already ended cannot overlap a later room.
        # This keeps validation effectively linear for ordinary floor plans and
        # removes allocation/GC spikes from the 200-object command path.
        active: list[tuple[str, tuple[int, int, int, int]]] = []
        for room_id, room_box, room_path in sorted(
            room_boxes, key=lambda item: (item[1][0], item[1][2], item[0])
        ):
            active = [item for item in active if item[1][2] > room_box[0]]
            for other_id, other_box in active:
                if _overlaps(room_box, other_box):
                    findings.append(
                        _finding(
                            "room_overlap",
                            "BLOCKER",
                            f"A(z) {room_id} és {other_id} helyiség átfedi egymást.",
                            room_path,
                        )
                    )
            active.append((room_id, room_box))
        room_ids = {room_id for room_id, _, _ in room_boxes}
        room_functions = {
            str(room.get("id") or ""): str(room.get("function") or "other") for room in rooms
        }
        connection_ids: set[str] = set()
        adjacency: dict[str, set[str]] = {room_id: set() for room_id in room_ids}
        for connection_index, connection in enumerate(level.get("connections", [])):
            connection_path = f"{path}.connections[{connection_index}]"
            connection_id = str(connection.get("id") or "")
            room_a = str(connection.get("roomA") or "")
            room_b = str(connection.get("roomB") or "")
            opening_id = str(connection.get("openingId") or "")
            if not connection_id or connection_id in connection_ids:
                findings.append(
                    _finding(
                        "connection_id_invalid",
                        "BLOCKER",
                        "A helyiségkapcsolat azonosítója hiányzik vagy ismétlődik.",
                        connection_path,
                    )
                )
                continue
            connection_ids.add(connection_id)
            if (
                room_a == room_b
                or room_a not in room_ids | {"outside"}
                or room_b not in room_ids | {"outside"}
                or opening_id not in opening_ids
            ):
                findings.append(
                    _finding(
                        "connection_invalid",
                        "BLOCKER",
                        "A helyiségkapcsolatnak két külön létező végpontot és nyílást kell kötnie.",
                        connection_path,
                    )
                )
                continue
            connection_wall_id = opening_wall_ids[opening_id]
            connection_wall = wall_by_id[connection_wall_id]
            connection_wall_thickness = wall_thickness_by_id[connection_wall_id]
            endpoints_match = all(
                _segment_on_box_boundary(connection_wall, box)
                if room_id == "outside"
                else _segment_near_box_boundary(
                    connection_wall,
                    room_box_by_id[room_id],
                    connection_wall_thickness,
                )
                for room_id in (room_a, room_b)
            )
            if not endpoints_match:
                findings.append(
                    _finding(
                        "connection_geometry_invalid",
                        "BLOCKER",
                        "A kapcsolat nyílásfalának mindkét hivatkozott tér határát érintenie kell.",
                        connection_path,
                    )
                )
                continue
            if room_a != "outside" and room_b != "outside":
                adjacency[room_a].add(room_b)
                adjacency[room_b].add(room_a)
        entrances = sorted(
            room_id for room_id, function in room_functions.items() if function == "entrance"
        )
        if entrances:
            reachable = set(entrances)
            pending = list(entrances)
            while pending:
                current = pending.pop()
                for neighbour in adjacency[current] - reachable:
                    reachable.add(neighbour)
                    pending.append(neighbour)
            for room_id in sorted(room_ids - reachable):
                findings.append(
                    _finding(
                        "room_unreachable",
                        "BLOCKER",
                        f"A(z) {room_id} helyiség nem érhető el a bejárati helyiségből.",
                        f"{path}.connections",
                    )
                )
        elif rooms:
            findings.append(
                _finding(
                    "entrance_missing",
                    "WARNING",
                    "A teljes elérhetőségi ellenőrzéshez bejárati funkciójú helyiség szükséges.",
                    f"{path}.rooms",
                )
            )
        if not rooms:
            findings.append(
                _finding(
                    "rooms_missing",
                    "WARNING",
                    "A szint még nem tartalmaz helyiséget.",
                    f"{path}.rooms",
                )
            )
        if level_type == "attic":
            if index != len(levels) - 1:
                findings.append(
                    _finding(
                        "attic_not_topmost",
                        "BLOCKER",
                        "A tetőtér csak a legfelső szint lehet.",
                        path,
                    )
                )
            zone = level.get("usableHeightZone")
            zone_box = _rectangle_box(zone.get("polygon") if isinstance(zone, dict) else None)
            min_height = (
                _integer_value(zone, "minClearHeightMm", default=0) if isinstance(zone, dict) else 0
            )
            if (
                zone_box is None
                or not _contains(box, zone_box)
                or min_height < 1_900
                or min_height > int(level.get("heightMm") or 0)
            ):
                findings.append(
                    _finding(
                        "attic_usable_zone_invalid",
                        "BLOCKER",
                        "A tetőtérhez kontúron belüli, legalább 1900 mm "
                        "hasznosmagassági zóna kell.",
                        f"{path}.usableHeightZone",
                    )
                )
            if not isinstance(level.get("roof"), dict):
                findings.append(
                    _finding(
                        "attic_roof_missing",
                        "BLOCKER",
                        "A tetőtérhez tetőgeometria szükséges.",
                        f"{path}.roof",
                    )
                )
    if len(levels) > 1:
        _validate_vertical_geometry(geometry, levels, findings)
    return findings


def _validate_vertical_geometry(
    geometry: dict[str, Any],
    levels: list[dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    level_index = {str(level.get("id")): index for index, level in enumerate(levels)}
    cores = geometry.get("verticalCores", [])
    core_by_id: dict[str, dict[str, Any]] = {}
    for core_index, core in enumerate(cores):
        path = f"verticalCores[{core_index}]"
        core_id = str(core.get("id") or "")
        try:
            core_box = (
                int(core["xMm"]),
                int(core["yMm"]),
                int(core["xMm"]) + int(core["widthMm"]),
                int(core["yMm"]) + int(core["depthMm"]),
            )
        except (KeyError, TypeError, ValueError):
            core_box = (0, 0, 0, 0)
        if (
            not core_id
            or core_id in core_by_id
            or core_box[0] >= core_box[2]
            or core_box[1] >= core_box[3]
        ):
            findings.append(
                _finding(
                    "vertical_core_invalid",
                    "BLOCKER",
                    "A függőleges közlekedőmag azonosítója vagy mérete hibás.",
                    path,
                )
            )
            continue
        core_by_id[core_id] = core
        if str(core.get("kind") or "stair") == "stair":
            stair = core.get("stairGeometry")
            if not isinstance(stair, dict) or not _stair_geometry_valid(stair):
                findings.append(
                    _finding(
                        "stair_geometry_invalid",
                        "BLOCKER",
                        "A lépcső szélesség-, fellépő-, belépő-, fejmagasság- vagy "
                        "pihenőadata hibás.",
                        f"{path}.stairGeometry",
                    )
                )
    covered_pairs: set[tuple[int, int]] = set()
    connection_ids: set[str] = set()
    for connection_index, connection in enumerate(geometry.get("verticalConnections", [])):
        path = f"verticalConnections[{connection_index}]"
        connection_id = str(connection.get("id") or "")
        core_id = str(connection.get("coreId") or "")
        from_id = str(connection.get("fromLevelId") or "")
        to_id = str(connection.get("toLevelId") or "")
        from_index = level_index.get(from_id)
        to_index = level_index.get(to_id)
        if (
            not connection_id
            or connection_id in connection_ids
            or core_id not in core_by_id
            or from_index is None
            or to_index is None
            or to_index != from_index + 1
        ):
            findings.append(
                _finding(
                    "vertical_connection_invalid",
                    "BLOCKER",
                    "A függőleges kapcsolatnak létező maggal két szomszédos szintet kell kötnie.",
                    path,
                )
            )
            continue
        connection_ids.add(connection_id)
        pair = (from_index, to_index)
        covered_pairs.add(pair)
        core = core_by_id[core_id]
        core_box = (
            int(core["xMm"]),
            int(core["yMm"]),
            int(core["xMm"]) + int(core["widthMm"]),
            int(core["yMm"]) + int(core["depthMm"]),
        )
        for linked_index in pair:
            level_box = _rectangle_box(levels[linked_index].get("outerBoundary"))
            if level_box is None or not _contains(level_box, core_box):
                findings.append(
                    _finding(
                        "vertical_core_outside",
                        "BLOCKER",
                        "A közlekedőmagnak mindkét összekötött szint kontúrján belül "
                        "kell maradnia.",
                        path,
                    )
                )
                break
    for index in range(len(levels) - 1):
        if (index, index + 1) not in covered_pairs:
            findings.append(
                _finding(
                    "vertical_connection_missing",
                    "BLOCKER",
                    "Minden szomszédos szintpár között koherens függőleges kapcsolat szükséges.",
                    "verticalConnections",
                )
            )


def _stair_geometry_valid(stair: dict[str, Any]) -> bool:
    if str(stair.get("ruleVersion") or "") != STAIR_GEOMETRY_VERSION:
        return False
    width = _integer_value(stair, "clearWidthMm", default=0)
    riser = _integer_value(stair, "riserMm", default=0)
    tread = _integer_value(stair, "treadMm", default=0)
    headroom = _integer_value(stair, "headroomMm", default=0)
    landing = _integer_value(stair, "landingDepthMm", default=0)
    return (
        800 <= width <= 3_000
        and 100 <= riser <= 220
        and 200 <= tread <= 450
        and 1_900 <= headroom <= 5_000
        and landing >= width
    )


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
                    "polygon": _adapt_polygon(polygon),
                }
            )
        levels.append(
            {
                "id": str(item.get("id") or f"L{index + 1:02d}"),
                "type": "ground" if index == 0 else str(item.get("type") or "full_storey"),
                "elevationMm": int(item.get("elevation") or 0),
                "heightMm": int(item.get("height") or 2_800),
                "outerBoundary": _adapt_polygon(boundary),
                "rooms": rooms,
                "wallSegments": [
                    _adapt_wall(wall, wall_index)
                    for wall_index, wall in enumerate(item.get("walls") or [])
                ],
                "openings": [
                    _adapt_opening(opening, opening_index)
                    for opening_index, opening in enumerate(item.get("openings") or [])
                ],
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
        kind = str(core.get("kind") or "stair")
        adapted_core = {
            "id": str(core.get("id") or f"CORE-{index + 1:02d}"),
            "kind": kind,
            "xMm": box[0],
            "yMm": box[1],
            "widthMm": box[2] - box[0],
            "depthMm": box[3] - box[1],
        }
        if kind == "stair":
            adapted_core["stairGeometry"] = deepcopy(
                core.get("stairGeometry") or _default_stair_geometry()
            )
        cores.append(adapted_core)
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
    if level_type == "attic":
        inset = min(1_000, max(300, min(source_box[2], source_box[3]) // 8))
        if source_box[2] - source_box[0] <= inset * 2 or source_box[3] - source_box[1] <= inset * 2:
            raise GeometryError(
                "attic_zone_unavailable",
                "A szintkontúr túl kicsi a tetőtér hasznosmagassági zónájához.",
            )
        created["usableHeightZone"] = {
            "minClearHeightMm": 1_900,
            "polygon": _ring(
                source_box[0] + inset,
                source_box[1] + inset,
                source_box[2] - inset,
                source_box[3] - inset,
            ),
        }
        created["roof"] = {"type": "gable", "pitchDeg": 30}
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
                "stairGeometry": _default_stair_geometry(),
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


def _add_wall(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level = _level(geometry, str(payload["levelId"]))
    wall_id = str(payload.get("wallId") or _next_id(level["wallSegments"], "W"))
    if any(str(item.get("id")) == wall_id for item in level["wallSegments"]):
        raise GeometryError("wall_exists", "A falazonosító már létezik.")
    level["wallSegments"].append(
        {
            "id": wall_id,
            "from": {"x": int(payload["x1Mm"]), "y": int(payload["y1Mm"])},
            "to": {"x": int(payload["x2Mm"]), "y": int(payload["y2Mm"])},
            "thicknessMm": int(payload.get("thicknessMm") or 150),
            "kind": str(payload.get("wallKind") or "partition"),
        }
    )


def _move_wall(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    wall = _wall(_level(geometry, str(payload["levelId"])), str(payload["wallId"]))
    wall["from"] = {"x": int(payload["x1Mm"]), "y": int(payload["y1Mm"])}
    wall["to"] = {"x": int(payload["x2Mm"]), "y": int(payload["y2Mm"])}


def _split_wall(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level = _level(geometry, str(payload["levelId"]))
    wall = _wall(level, str(payload["wallId"]))
    if any(str(item.get("wallId")) == str(wall["id"]) for item in level["openings"]):
        raise GeometryError(
            "wall_has_openings",
            "Nyílást tartalmazó fal csak a nyílások áthelyezése után hasítható.",
        )
    segment = _wall_segment(wall)
    assert segment is not None
    split = (int(payload["xMm"]), int(payload["yMm"]))
    if split in {(segment[0], segment[1]), (segment[2], segment[3])} or not _point_on_segment(
        split, segment
    ):
        raise GeometryError("wall_split_invalid", "A hasítási pontnak a fal belsejére kell esnie.")
    original_end = deepcopy(wall["to"])
    wall["to"] = {"x": split[0], "y": split[1]}
    level["wallSegments"].append(
        {
            **{
                key: deepcopy(value)
                for key, value in wall.items()
                if key not in {"id", "from", "to"}
            },
            "id": _next_id(level["wallSegments"], "W"),
            "from": {"x": split[0], "y": split[1]},
            "to": original_end,
        }
    )


def _remove_wall(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level = _level(geometry, str(payload["levelId"]))
    wall_id = str(payload["wallId"])
    if any(str(item.get("wallId")) == wall_id for item in level["openings"]):
        raise GeometryError(
            "wall_has_openings", "Nyílást tartalmazó fal nem törölhető részleges adatvesztéssel."
        )
    before = len(level["wallSegments"])
    level["wallSegments"] = [
        item for item in level["wallSegments"] if str(item.get("id")) != wall_id
    ]
    if len(level["wallSegments"]) == before:
        raise GeometryError("wall_not_found", "A fal nem található.")


def _add_opening(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level = _level(geometry, str(payload["levelId"]))
    opening_id = str(payload.get("openingId") or _next_id(level["openings"], "O"))
    if any(str(item.get("id")) == opening_id for item in level["openings"]):
        raise GeometryError("opening_exists", "A nyílásazonosító már létezik.")
    _wall(level, str(payload["wallId"]))
    level["openings"].append(
        {
            "id": opening_id,
            "wallId": str(payload["wallId"]),
            "kind": str(payload.get("openingKind") or "door"),
            "offsetMm": int(payload["offsetMm"]),
            "widthMm": int(payload["widthMm"]),
            "heightMm": int(payload.get("heightMm") or 2_100),
            "sillHeightMm": int(payload.get("sillHeightMm") or 0),
        }
    )


def _move_opening(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level = _level(geometry, str(payload["levelId"]))
    opening = _opening(level, str(payload["openingId"]))
    wall_id = str(payload.get("wallId") or opening["wallId"])
    _wall(level, wall_id)
    opening["wallId"] = wall_id
    opening["offsetMm"] = int(payload["offsetMm"])


def _resize_opening(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    opening = _opening(_level(geometry, str(payload["levelId"])), str(payload["openingId"]))
    opening["widthMm"] = int(payload["widthMm"])
    if "heightMm" in payload:
        opening["heightMm"] = int(payload["heightMm"])
    if "sillHeightMm" in payload:
        opening["sillHeightMm"] = int(payload["sillHeightMm"])


def _remove_opening(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level = _level(geometry, str(payload["levelId"]))
    opening_id = str(payload["openingId"])
    before = len(level["openings"])
    level["openings"] = [item for item in level["openings"] if str(item.get("id")) != opening_id]
    if len(level["openings"]) == before:
        raise GeometryError("opening_not_found", "A nyílás nem található.")
    level["connections"] = [
        item for item in level["connections"] if str(item.get("openingId")) != opening_id
    ]


def _add_connection(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level = _level(geometry, str(payload["levelId"]))
    connection_id = str(payload.get("connectionId") or _next_id(level["connections"], "C"))
    if any(str(item.get("id")) == connection_id for item in level["connections"]):
        raise GeometryError("connection_exists", "A kapcsolat azonosítója már létezik.")
    level["connections"].append(
        {
            "id": connection_id,
            "roomA": str(payload["roomA"]),
            "roomB": str(payload["roomB"]),
            "openingId": str(payload["openingId"]),
        }
    )


def _remove_connection(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    level = _level(geometry, str(payload["levelId"]))
    connection_id = str(payload["connectionId"])
    before = len(level["connections"])
    level["connections"] = [
        item for item in level["connections"] if str(item.get("id")) != connection_id
    ]
    if len(level["connections"]) == before:
        raise GeometryError("connection_not_found", "A kapcsolat nem található.")


def _set_stair_geometry(geometry: dict[str, Any], payload: dict[str, Any]) -> None:
    core_id = str(payload.get("coreId") or "CORE-01")
    core = next(
        (item for item in geometry.get("verticalCores", []) if str(item.get("id")) == core_id),
        None,
    )
    if core is None:
        raise GeometryError("vertical_core_missing", "A közlekedőmag nem található.")
    core["stairGeometry"] = {
        "ruleVersion": STAIR_GEOMETRY_VERSION,
        "clearWidthMm": int(payload["clearWidthMm"]),
        "riserMm": int(payload["riserMm"]),
        "treadMm": int(payload["treadMm"]),
        "headroomMm": int(payload["headroomMm"]),
        "landingDepthMm": int(payload["landingDepthMm"]),
    }


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


def _wall(level: dict[str, Any], wall_id: str) -> dict[str, Any]:
    for wall in level.get("wallSegments", []):
        if str(wall.get("id")) == wall_id:
            return wall
    raise GeometryError("wall_not_found", "A fal nem található.", path="wallSegments")


def _opening(level: dict[str, Any], opening_id: str) -> dict[str, Any]:
    for opening in level.get("openings", []):
        if str(opening.get("id")) == opening_id:
            return opening
    raise GeometryError("opening_not_found", "A nyílás nem található.", path="openings")


def _next_id(items: list[dict[str, Any]], prefix: str) -> str:
    used = {str(item.get("id") or "") for item in items}
    sequence = 1
    while f"{prefix}{sequence:03d}" in used:
        sequence += 1
    return f"{prefix}{sequence:03d}"


def _default_stair_geometry() -> dict[str, Any]:
    return {
        "ruleVersion": STAIR_GEOMETRY_VERSION,
        "clearWidthMm": 1_000,
        "riserMm": 175,
        "treadMm": 280,
        "headroomMm": 2_100,
        "landingDepthMm": 1_000,
    }


def _adapt_point(value: Any) -> dict[str, int]:
    if isinstance(value, dict):
        return {"x": int(value["x"]), "y": int(value["y"])}
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return {"x": int(value[0]), "y": int(value[1])}
    raise GeometryError("template_wall_unsupported", "A típusterv falpontja nem értelmezhető.")


def _adapt_polygon(value: Any) -> list[dict[str, int]]:
    if not isinstance(value, list):
        raise GeometryError("template_polygon_unsupported", "A típusterv poligonja hibás.")
    return [_adapt_point(point) for point in value]


def _adapt_wall(wall: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": str(wall.get("id") or f"W{index + 1:03d}"),
        "from": _adapt_point(wall.get("from") or wall.get("start")),
        "to": _adapt_point(wall.get("to") or wall.get("end")),
        "thicknessMm": _integer_value(wall, "thicknessMm", "thickness", default=150),
        "kind": str(wall.get("kind") or "partition"),
    }


def _adapt_opening(opening: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": str(opening.get("id") or f"O{index + 1:03d}"),
        "wallId": str(opening.get("wallId") or ""),
        "kind": str(opening.get("kind") or "door"),
        "offsetMm": _integer_value(opening, "offsetMm", "offset", default=-1),
        "widthMm": _integer_value(opening, "widthMm", "width", default=0),
        "heightMm": _integer_value(opening, "heightMm", "height", default=2_100),
        "sillHeightMm": _integer_value(opening, "sillHeightMm", "sill", default=0),
    }


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


def _integer_value(value: dict[str, Any], *keys: str, default: int) -> int:
    for key in keys:
        if key in value and value[key] is not None:
            try:
                return int(value[key])
            except (TypeError, ValueError):
                return default
    return default


def _wall_segment(wall: dict[str, Any]) -> tuple[int, int, int, int] | None:
    try:
        start = _adapt_point(wall.get("from") or wall.get("start"))
        end = _adapt_point(wall.get("to") or wall.get("end"))
    except (GeometryError, KeyError, TypeError, ValueError):
        return None
    segment = (start["x"], start["y"], end["x"], end["y"])
    if segment[0] == segment[2] and segment[1] != segment[3]:
        return segment
    if segment[1] == segment[3] and segment[0] != segment[2]:
        return segment
    return None


def _segment_length(segment: tuple[int, int, int, int]) -> int:
    return abs(segment[2] - segment[0]) + abs(segment[3] - segment[1])


def _point_in_box(point: tuple[int, int], box: tuple[int, int, int, int]) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _point_on_box_boundary(point: tuple[int, int], box: tuple[int, int, int, int]) -> bool:
    return _point_in_box(point, box) and (
        point[0] in {box[0], box[2]} or point[1] in {box[1], box[3]}
    )


def _segment_on_box_boundary(
    segment: tuple[int, int, int, int], box: tuple[int, int, int, int]
) -> bool:
    x1, y1, x2, y2 = segment
    if y1 == y2 and y1 in {box[1], box[3]}:
        return max(min(x1, x2), box[0]) < min(max(x1, x2), box[2])
    if x1 == x2 and x1 in {box[0], box[2]}:
        return max(min(y1, y2), box[1]) < min(max(y1, y2), box[3])
    return False


def _segment_near_box_boundary(
    segment: tuple[int, int, int, int],
    box: tuple[int, int, int, int],
    tolerance_mm: int,
) -> bool:
    x1, y1, x2, y2 = segment
    if y1 == y2 and min(abs(y1 - box[1]), abs(y1 - box[3])) <= tolerance_mm:
        return max(min(x1, x2), box[0]) < min(max(x1, x2), box[2])
    if x1 == x2 and min(abs(x1 - box[0]), abs(x1 - box[2])) <= tolerance_mm:
        return max(min(y1, y2), box[1]) < min(max(y1, y2), box[3])
    return False


def _point_on_segment(point: tuple[int, int], segment: tuple[int, int, int, int]) -> bool:
    x1, y1, x2, y2 = segment
    return (
        min(x1, x2) <= point[0] <= max(x1, x2)
        and min(y1, y2) <= point[1] <= max(y1, y2)
        and ((x1 == x2 == point[0]) or (y1 == y2 == point[1]))
    )


def _segments_intersect_invalidly(
    left: tuple[int, int, int, int], right: tuple[int, int, int, int]
) -> bool:
    left_horizontal = left[1] == left[3]
    right_horizontal = right[1] == right[3]
    if left_horizontal == right_horizontal:
        if left_horizontal and left[1] != right[1]:
            return False
        if not left_horizontal and left[0] != right[0]:
            return False
        left_start, left_end = (
            sorted((left[0], left[2])) if left_horizontal else sorted((left[1], left[3]))
        )
        right_start, right_end = (
            sorted((right[0], right[2])) if right_horizontal else sorted((right[1], right[3]))
        )
        return max(left_start, right_start) < min(left_end, right_end)
    horizontal = left if left_horizontal else right
    vertical = right if left_horizontal else left
    intersection = (vertical[0], horizontal[1])
    if not _point_on_segment(intersection, horizontal) or not _point_on_segment(
        intersection, vertical
    ):
        return False
    horizontal_endpoints = {(horizontal[0], horizontal[1]), (horizontal[2], horizontal[3])}
    vertical_endpoints = {(vertical[0], vertical[1]), (vertical[2], vertical[3])}
    return intersection not in horizontal_endpoints and intersection not in vertical_endpoints


def _rectangle_box(points: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(points, list) or len(points) != 5 or points[0] != points[-1]:
        return None
    try:
        coordinates = [
            (int(point["x"]), int(point["y"]))
            if isinstance(point, dict)
            else (int(point[0]), int(point[1]))
            for point in points[:-1]
        ]
        xs = sorted({point[0] for point in coordinates})
        ys = sorted({point[1] for point in coordinates})
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    if len(xs) != 2 or len(ys) != 2 or xs[0] >= xs[1] or ys[0] >= ys[1]:
        return None
    expected = {(xs[0], ys[0]), (xs[1], ys[0]), (xs[1], ys[1]), (xs[0], ys[1])}
    actual = set(coordinates)
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


def _sort_id_lists_in_place(value: Any) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _sort_id_lists_in_place(item)
        return
    if not isinstance(value, list):
        return
    for item in value:
        _sort_id_lists_in_place(item)
    if value and all(isinstance(item, dict) and "id" in item for item in value):
        value.sort(key=lambda item: str(item["id"]))
