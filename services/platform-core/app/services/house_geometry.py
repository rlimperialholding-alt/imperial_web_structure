from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

SCHEMA_VERSION = "houseplan.geometry.v1"
GENERATOR_VERSION = "hb-grid-v1"
RULESET_VERSION = "hb-grid-v1.0.0"
GRID_MM = 100
EXTERNAL_WALL_MM = 300
INTERNAL_WALL_MM = 150
MIN_SHARED_DOOR_EDGE_MM = 900
DEFAULT_DOOR_MM = (900, 2100)
ENTRANCE_DOOR_MM = (1000, 2100)
MIN_ROOM_WIDTH_MM = 2400
MIN_CORRIDOR_WIDTH_MM = 1100
STAIR_CORE_MM = (2000, 4000)
STOREY_HEIGHT_MM = 2800
MIN_ROOM_RATIO = Decimal("0.65")
MAX_ROOM_RATIO = Decimal("0.88")


class HouseGeometryError(ValueError):
    """Raised when a requested concept cannot satisfy the frozen geometry contract."""


@dataclass(frozen=True)
class _Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height


_ROOM_ORDER = {
    "entrance": 0,
    "living": 1,
    "kitchen": 2,
    "dining": 3,
    "circulation": 4,
    "bathroom": 5,
    "wc": 6,
    "bedroom": 7,
    "mechanical": 8,
    "utility": 9,
    "storage": 10,
}


def _nfc(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_nfc(item) for item in value]
    if isinstance(value, dict):
        return {
            unicodedata.normalize("NFC", str(key)): _nfc(item)
            for key, item in value.items()
            if item is not None
        }
    return value


def _canonical_geometry(value: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(_nfc(value))
    result["levels"] = sorted(result.get("levels", []), key=lambda item: item["id"])
    for level in result["levels"]:
        for key in ("rooms", "walls", "openings"):
            level[key] = sorted(level.get(key, []), key=lambda item: item["id"])
        for connection in level.get("connections", []):
            left = connection["roomA"]
            right = connection["roomB"]
            if left == "outside":
                left, right = right, left
            elif right != "outside" and right < left:
                left, right = right, left
            connection["roomA"], connection["roomB"] = left, right
        level["connections"] = sorted(
            level.get("connections", []),
            key=lambda item: (
                level["id"],
                item["roomA"],
                item["roomB"],
                item["openingId"],
                item["id"],
            ),
        )
        level["circulationZones"] = sorted(
            level.get("circulationZones", []), key=lambda item: item["id"]
        )
    result["verticalCores"] = sorted(result.get("verticalCores", []), key=lambda item: item["id"])
    result["verticalConnections"] = sorted(
        result.get("verticalConnections", []), key=lambda item: item["id"]
    )
    return result


def canonical_json(value: Any) -> str:
    """JCS-compatible serialization for the integer/string subset used by HousePlan."""
    normalized = (
        _canonical_geometry(value)
        if isinstance(value, dict) and value.get("schemaVersion")
        else _nfc(value)
    )
    return json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def geometry_signature(geometry: dict[str, Any]) -> str:
    payload = "imperial-house-geometry:v1\n" + canonical_json(geometry)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def input_hash(normalized_input: dict[str, Any], source: dict[str, Any]) -> str:
    payload = {
        "generatorVersion": GENERATOR_VERSION,
        "normalizedInput": normalized_input,
        "rulesetVersion": RULESET_VERSION,
        "source": {
            "id": source["id"],
            "revision": source["revision"],
            "sha256": source["sha256"],
        },
    }
    return hashlib.sha256(
        ("imperial-house-input:v1\n" + canonical_json(payload)).encode("utf-8")
    ).hexdigest()


def _snap_mm(value: Decimal) -> int:
    return int((value / GRID_MM).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * GRID_MM


def _polygon(rect: _Rect, *, offset_x: int = 0, offset_y: int = 0) -> list[list[int]]:
    left, bottom = rect.x + offset_x, rect.y + offset_y
    right, top = left + rect.width, bottom + rect.height
    return [[left, bottom], [right, bottom], [right, top], [left, top], [left, bottom]]


def polygon_area_mm2(points: list[list[int]]) -> int:
    if len(points) < 4 or points[0] != points[-1]:
        raise HouseGeometryError("A poligonnak zártnak kell lennie.")
    if any(type(value) is not int for point in points for value in point):
        raise HouseGeometryError("A koordináták csak egész milliméterek lehetnek.")
    if len(set(map(tuple, points[:-1]))) != len(points) - 1:
        raise HouseGeometryError("A poligon nem tartalmazhat ismétlődő belső csúcspontot.")

    def orientation(a: list[int], b: list[int], c: list[int]) -> int:
        value = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
        return (value > 0) - (value < 0)

    def intersects(a: list[int], b: list[int], c: list[int], d: list[int]) -> bool:
        return orientation(a, b, c) != orientation(a, b, d) and orientation(c, d, a) != orientation(
            c, d, b
        )

    edges = list(zip(points[:-1], points[1:], strict=True))
    for left_index, (left_a, left_b) in enumerate(edges):
        for right_index, (right_a, right_b) in enumerate(
            edges[left_index + 1 :], start=left_index + 1
        ):
            if right_index in {left_index, left_index + 1} or {left_index, right_index} == {
                0,
                len(edges) - 1,
            }:
                continue
            if intersects(left_a, left_b, right_a, right_b):
                raise HouseGeometryError("Önmetsző poligon nem engedélyezett.")
    area2 = sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points[:-1], points[1:], strict=True)
    )
    if area2 <= 0 or area2 % 2:
        raise HouseGeometryError("A külső poligonnak pozitív, egész mm² területűnek kell lennie.")
    return area2 // 2


def _room_cells(value: Any) -> int:
    area = Decimal(str(value))
    if not area.is_finite():
        raise HouseGeometryError("A helyiségterületnek véges számnak kell lennie.")
    cells = area * Decimal("100")
    if cells != cells.to_integral_value() or cells <= 0:
        raise HouseGeometryError(
            "A helyiségterület legfeljebb 0,01 m² pontosságú és pozitív lehet."
        )
    return int(cells)


def _expanded_rooms(data: dict[str, Any], floors: int) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for original_index, item in enumerate(data.get("rooms") or []):
        count = int(item.get("count", 1))
        level = int(item.get("level", 1))
        if count < 1 or count > 20 or level < 1 or level > floors:
            raise HouseGeometryError("Érvénytelen helyiségdarabszám vagy szint.")
        room_type = str(item.get("type") or "").strip().lower()
        name = str(item.get("name") or room_type).strip()
        if len(name) > 120:
            raise HouseGeometryError("A helyiségnév legfeljebb 120 karakter lehet.")
        if room_type not in _ROOM_ORDER:
            raise HouseGeometryError(f"Nem támogatott helyiségtípus: {room_type or '(üres)'}.")
        for sequence in range(1, count + 1):
            expanded.append(
                {
                    "level": level,
                    "type": room_type,
                    "name": name,
                    "target_cells": _room_cells(item.get("target_area_m2")),
                    "sequence": sequence,
                    "original_index": original_index,
                }
            )
    if not expanded:
        raise HouseGeometryError("Legalább egy helyiséget meg kell adni.")
    if len(expanded) > 60:
        raise HouseGeometryError("Egy terv legfeljebb 60 helyiséget tartalmazhat.")
    present = {item["type"] for item in expanded}
    missing = {"entrance", "living", "kitchen", "bathroom", "bedroom"} - present
    if missing:
        raise HouseGeometryError("Hiányzó kötelező helyiségtípusok: " + ", ".join(sorted(missing)))
    expanded.sort(
        key=lambda item: (
            item["level"],
            _ROOM_ORDER[item["type"]],
            item["type"],
            unicodedata.normalize("NFC", item["name"]).casefold(),
            item["original_index"],
            item["sequence"],
        )
    )
    for index, item in enumerate(expanded, start=1):
        item["id"] = f"R{index:03d}"
    return expanded


def normalize_input(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise HouseGeometryError("A terv bemenete JSON-objektum legyen.")
    floors = int(data.get("floors", 1))
    gross_area = Decimal(str(data.get("gross_area_m2")))
    layout = str(data.get("layout") or "compact").strip().lower()
    if not gross_area.is_finite() or gross_area < 45 or gross_area > 450:
        raise HouseGeometryError("A bruttó alapterületnek 45 és 450 m² közé kell esnie.")
    if floors < 1 or floors > 3:
        raise HouseGeometryError("A szintek száma 1 és 3 közötti lehet.")
    if layout not in {"compact", "linear"}:
        raise HouseGeometryError("A v1 motor csak compact vagy linear alaprajzot támogat.")
    rooms = _expanded_rooms(data, floors)
    brand = str(data.get("brand") or "Imperial").strip()
    technology = str(data.get("technology") or "").strip()
    style = str(data.get("style") or "kortárs").strip()
    if not technology or max(len(brand), len(technology), len(style)) > 120:
        raise HouseGeometryError("A márka, technológia és stílus 1–120 karakter lehet.")
    requested_adjacencies = data.get("required_adjacencies")
    if requested_adjacencies is None:
        requested_adjacencies = [["entrance", "living"], ["living", "kitchen"]]
    if not isinstance(requested_adjacencies, list) or len(requested_adjacencies) > 30:
        raise HouseGeometryError("Legfeljebb 30 kötelező helyiségkapcsolat adható meg.")
    required_adjacencies: set[tuple[str, str]] = set()
    for pair in requested_adjacencies:
        if not isinstance(pair, list) or len(pair) != 2:
            raise HouseGeometryError("A kötelező helyiségkapcsolat két elemű lista legyen.")
        left, right = (str(value).strip().lower() for value in pair)
        if left not in _ROOM_ORDER or right not in _ROOM_ORDER or left == right:
            raise HouseGeometryError("Érvénytelen kötelező helyiségtípus-kapcsolat.")
        required_adjacencies.add((min(left, right), max(left, right)))
    return {
        "brand": brand,
        "technology": technology,
        "grossAreaM2": format(gross_area.normalize(), "f"),
        "floors": floors,
        "layout": layout,
        "accessibility": bool(data.get("accessibility", False)),
        "roof": str(data.get("roof") or "gable").strip().lower(),
        "style": style,
        "requiredAdjacencies": [list(pair) for pair in sorted(required_adjacencies)],
        "rooms": [
            {
                "id": item["id"],
                "level": item["level"],
                "type": item["type"],
                "name": item["name"],
                "targetCells": item["target_cells"],
            }
            for item in rooms
        ],
    }


def _footprint(gross_area_m2: Decimal, floors: int, layout: str) -> tuple[int, int]:
    area_mm2 = gross_area_m2 * Decimal("1000000") / floors
    aspect = Decimal(4) / Decimal(3) if layout == "compact" else Decimal(3) / Decimal(2)
    width = _snap_mm((area_mm2 * aspect).sqrt())
    depth = _snap_mm(area_mm2 / width)
    if min(width, depth) <= 2 * EXTERNAL_WALL_MM + MIN_ROOM_WIDTH_MM:
        raise HouseGeometryError("A számított footprint túl keskeny a helyiségminimumokhoz.")
    return width, depth


def _candidate_envelopes(area_cells: int, max_width: int, max_height: int) -> list[tuple[int, int]]:
    candidates: set[tuple[int, int]] = set()
    for width in range(MIN_ROOM_WIDTH_MM // GRID_MM, max_width + 1):
        if area_cells % width:
            continue
        height = area_cells // width
        if MIN_ROOM_WIDTH_MM // GRID_MM <= height <= max_height:
            candidates.add((width, height))
    target_ratio = Decimal(max_width) / Decimal(max_height)
    return sorted(
        candidates,
        key=lambda item: (
            abs(Decimal(item[0]) / Decimal(item[1]) - target_ratio),
            (max_width - item[0]) + (max_height - item[1]),
            -item[0],
            -item[1],
        ),
    )


def _partition(
    rect: _Rect, rooms: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], _Rect]] | None:
    """Deterministic guillotine layout with grid-rounded per-room target allocation."""
    if sum(item["target_cells"] for item in rooms) != rect.area:
        return None
    minimum = MIN_ROOM_WIDTH_MM // GRID_MM
    cache: dict[
        tuple[int, int, int, int, int, int],
        list[tuple[dict[str, Any], _Rect]] | None,
    ] = {}

    def solve(box: _Rect, start: int, end: int):
        key = (box.x, box.y, box.width, box.height, start, end)
        if key in cache:
            return cache[key]
        if end - start == 1:
            if min(box.width, box.height) < minimum:
                cache[key] = None
                return None
            target = rooms[start]["target_cells"]
            deviation = abs(Decimal(box.area - target)) / Decimal(target)
            if deviation > Decimal("0.10"):
                cache[key] = None
                return None
            result = [(rooms[start], box)]
            cache[key] = result
            return result
        total_target = sum(rooms[index]["target_cells"] for index in range(start, end))
        axes = ("vertical", "horizontal") if box.width >= box.height else ("horizontal", "vertical")
        for axis in axes:
            dimension = box.width if axis == "vertical" else box.height
            for split in range(start + 1, end):
                first_target = sum(rooms[index]["target_cells"] for index in range(start, split))
                ideal = Decimal(dimension) * Decimal(first_target) / Decimal(total_target)
                rounded = int(ideal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                cuts = sorted(
                    {
                        max(minimum, min(dimension - minimum, rounded + delta))
                        for delta in (0, -1, 1, -2, 2, -3, 3, -4, 4)
                    },
                    key=lambda cut: (abs(Decimal(cut) - ideal), cut),
                )
                for cut in cuts:
                    if not minimum <= cut <= dimension - minimum:
                        continue
                    if axis == "vertical":
                        first_box = _Rect(box.x, box.y, cut, box.height)
                        second_box = _Rect(box.x + cut, box.y, box.width - cut, box.height)
                    else:
                        first_box = _Rect(box.x, box.y, box.width, cut)
                        second_box = _Rect(box.x, box.y + cut, box.width, box.height - cut)
                    first_result = solve(first_box, start, split)
                    if first_result is None:
                        continue
                    second_result = solve(second_box, split, end)
                    if second_result is None:
                        continue
                    result = first_result + second_result
                    cache[key] = result
                    return result
        cache[key] = None
        return None

    solved = solve(rect, 0, len(rooms))
    return solved


def _shared_edge(left: _Rect, right: _Rect) -> tuple[tuple[int, int], tuple[int, int]] | None:
    if left.x + left.width == right.x or right.x + right.width == left.x:
        x = left.x + left.width if left.x < right.x else right.x + right.width
        start, end = max(left.y, right.y), min(left.y + left.height, right.y + right.height)
        if end - start >= MIN_SHARED_DOOR_EDGE_MM // GRID_MM:
            return (x, start), (x, end)
    if left.y + left.height == right.y or right.y + right.height == left.y:
        y = left.y + left.height if left.y < right.y else right.y + right.height
        start, end = max(left.x, right.x), min(left.x + left.width, right.x + right.width)
        if end - start >= MIN_SHARED_DOOR_EDGE_MM // GRID_MM:
            return (start, y), (end, y)
    return None


def _level_geometry(
    level_no: int,
    width_mm: int,
    depth_mm: int,
    rooms: list[dict[str, Any]],
    floors: int,
    accessibility: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    inner_width = (width_mm - 2 * EXTERNAL_WALL_MM) // GRID_MM
    inner_height = (depth_mm - 2 * EXTERNAL_WALL_MM) // GRID_MM
    target_cells = sum(item["targetCells"] for item in rooms)
    internal_cells = inner_width * inner_height
    ratio = Decimal(target_cells) / Decimal(internal_cells)
    if ratio < MIN_ROOM_RATIO or ratio > MAX_ROOM_RATIO:
        raise HouseGeometryError(
            f"L{level_no:02d}: a nettó helyiségarány {ratio:.3f}; megengedett 0,65–0,88."
        )
    reserve = internal_cells - target_cells
    long_side = max(inner_width, inner_height)
    corridor_width = math.ceil(
        max(
            Decimal(MIN_CORRIDOR_WIDTH_MM // GRID_MM),
            min(Decimal(reserve) / Decimal(long_side), Decimal(24)),
        )
    )
    horizontal = inner_width >= inner_height
    corridor_area = corridor_width * long_side
    if corridor_area > reserve:
        raise HouseGeometryError(
            f"L{level_no:02d}: a determinisztikus közlekedősáv nem fér el a tartalékban."
        )
    zones: list[_Rect]
    core_rects: list[tuple[str, _Rect]] = []
    if horizontal:
        available = _Rect(0, 0, inner_width, inner_height - corridor_width)
        band = _Rect(0, inner_height - corridor_width, inner_width, corridor_width)
        if floors > 1:
            core_width, core_height = STAIR_CORE_MM[1] // GRID_MM, STAIR_CORE_MM[0] // GRID_MM
            occupied_width = core_width + (20 if accessibility else 0)
            if band.width < occupied_width or band.height < core_height:
                raise HouseGeometryError("A lépcsőmag nem fér el a közlekedősávban.")
            stair_rect = _Rect(
                inner_width - core_width, inner_height - core_height, core_width, core_height
            )
            core_rects.append(("stair", stair_rect))
            if accessibility:
                core_rects.append(("lift", _Rect(stair_rect.x - 20, stair_rect.y, 20, core_height)))
            zones = [_Rect(0, band.y, inner_width - occupied_width, band.height)]
            if band.height > core_height:
                zones.append(
                    _Rect(
                        inner_width - occupied_width,
                        band.y,
                        occupied_width,
                        band.height - core_height,
                    )
                )
        else:
            zones = [band]
    else:
        available = _Rect(0, 0, inner_width - corridor_width, inner_height)
        band = _Rect(inner_width - corridor_width, 0, corridor_width, inner_height)
        if floors > 1:
            core_width, core_height = STAIR_CORE_MM[0] // GRID_MM, STAIR_CORE_MM[1] // GRID_MM
            occupied_height = core_height + (20 if accessibility else 0)
            if band.width < core_width or band.height < occupied_height:
                raise HouseGeometryError("A lépcsőmag nem fér el a közlekedősávban.")
            stair_rect = _Rect(
                inner_width - core_width, inner_height - core_height, core_width, core_height
            )
            core_rects.append(("stair", stair_rect))
            if accessibility:
                core_rects.append(("lift", _Rect(stair_rect.x, stair_rect.y - 20, core_width, 20)))
            zones = [_Rect(band.x, 0, band.width, inner_height - occupied_height)]
            if band.width > core_width:
                zones.append(
                    _Rect(
                        band.x,
                        inner_height - occupied_height,
                        band.width - core_width,
                        occupied_height,
                    )
                )
        else:
            zones = [band]
    partitions = None
    room_envelope = None
    room_specs = [{**item, "target_cells": item["targetCells"]} for item in rooms]
    for candidate_width, candidate_height in _candidate_envelopes(
        target_cells, available.width, available.height
    ):
        candidate = _Rect(available.x, available.y, candidate_width, candidate_height)
        candidate_partitions = _partition(candidate, room_specs)
        if candidate_partitions is not None:
            room_envelope, partitions = candidate, candidate_partitions
            break
    if partitions is None or room_envelope is None:
        raise HouseGeometryError(
            f"L{level_no:02d}: a helyiségprogram nem osztható 100 mm-es, "
            "legalább 2400 mm széles guillotine-poligonokra."
        )
    offset = EXTERNAL_WALL_MM
    level_rooms = [
        {
            "id": item["id"],
            "type": item["type"],
            "name": item["name"],
            "targetAreaMm2": item["targetCells"] * GRID_MM * GRID_MM,
            "actualAreaMm2": rect.area * GRID_MM * GRID_MM,
            "areaDeviationBasisPoints": int(
                (
                    abs(Decimal(rect.area - item["targetCells"]))
                    / Decimal(item["targetCells"])
                    * Decimal(10000)
                ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            ),
            "polygon": _polygon(
                _Rect(
                    rect.x * GRID_MM, rect.y * GRID_MM, rect.width * GRID_MM, rect.height * GRID_MM
                ),
                offset_x=offset,
                offset_y=offset,
            ),
        }
        for item, rect in partitions
    ]
    boundary = _polygon(_Rect(0, 0, width_mm, depth_mm))
    walls = [
        {
            "id": "W001",
            "from": [0, 0],
            "to": [width_mm, 0],
            "thickness": EXTERNAL_WALL_MM,
            "kind": "external",
        },
        {
            "id": "W002",
            "from": [width_mm, 0],
            "to": [width_mm, depth_mm],
            "thickness": EXTERNAL_WALL_MM,
            "kind": "external",
        },
        {
            "id": "W003",
            "from": [width_mm, depth_mm],
            "to": [0, depth_mm],
            "thickness": EXTERNAL_WALL_MM,
            "kind": "external",
        },
        {
            "id": "W004",
            "from": [0, depth_mm],
            "to": [0, 0],
            "thickness": EXTERNAL_WALL_MM,
            "kind": "external",
        },
    ]
    openings: list[dict[str, Any]] = []
    connections: list[dict[str, Any]] = []
    entrance = next((room for room in level_rooms if room["type"] == "entrance"), None)
    if level_no == 1 and entrance is not None:
        entrance_rect = next(rect for item, rect in partitions if item["id"] == entrance["id"])
        if entrance_rect.y == 0:
            wall_id, offset_mm = "W001", offset + entrance_rect.x * GRID_MM + ENTRANCE_DOOR_MM[0]
        elif entrance_rect.x == 0:
            wall_id, offset_mm = "W004", offset + entrance_rect.y * GRID_MM + ENTRANCE_DOOR_MM[0]
        else:
            raise HouseGeometryError("A bejárati helyiség nem ér el külső falat.")
        openings.append(
            {
                "id": "O001",
                "wallId": wall_id,
                "kind": "door",
                "offset": offset_mm,
                "width": ENTRANCE_DOOR_MM[0],
                "height": ENTRANCE_DOOR_MM[1],
                "sill": 0,
            }
        )
        connections.append(
            {"id": "C001", "roomA": entrance["id"], "roomB": "outside", "openingId": "O001"}
        )
    wall_index, opening_index, connection_index = 5, len(openings) + 1, len(connections) + 1
    adjacency: dict[str, set[str]] = {room["id"]: set() for room in level_rooms}
    for left_index, (left_item, left_rect) in enumerate(partitions):
        for right_item, right_rect in partitions[left_index + 1 :]:
            shared = _shared_edge(left_rect, right_rect)
            if shared is None:
                continue
            wall_id, opening_id, connection_id = (
                f"W{wall_index:03d}",
                f"O{opening_index:03d}",
                f"C{connection_index:03d}",
            )
            start, end = shared
            start_mm = [offset + start[0] * GRID_MM, offset + start[1] * GRID_MM]
            end_mm = [offset + end[0] * GRID_MM, offset + end[1] * GRID_MM]
            wall_length = max(abs(end_mm[0] - start_mm[0]), abs(end_mm[1] - start_mm[1]))
            walls.append(
                {
                    "id": wall_id,
                    "from": start_mm,
                    "to": end_mm,
                    "thickness": INTERNAL_WALL_MM,
                    "kind": "internal",
                }
            )
            openings.append(
                {
                    "id": opening_id,
                    "wallId": wall_id,
                    "kind": "door",
                    "offset": max(0, (wall_length - DEFAULT_DOOR_MM[0]) // 2),
                    "width": DEFAULT_DOOR_MM[0],
                    "height": DEFAULT_DOOR_MM[1],
                    "sill": 0,
                }
            )
            room_a, room_b = sorted((left_item["id"], right_item["id"]))
            connections.append(
                {"id": connection_id, "roomA": room_a, "roomB": room_b, "openingId": opening_id}
            )
            adjacency[room_a].add(room_b)
            adjacency[room_b].add(room_a)
            wall_index += 1
            opening_index += 1
            connection_index += 1
    if level_rooms:
        visited: set[str] = set()
        stack = [level_rooms[0]["id"]]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            stack.extend(adjacency[current] - visited)
        if visited != set(adjacency):
            raise HouseGeometryError(f"L{level_no:02d}: a helyiségkapcsolati gráf nem összefüggő.")
    for item, rect in partitions:
        exterior: tuple[str, int, int] | None = None
        if rect.y == 0:
            exterior = ("W001", rect.x, rect.width)
        elif rect.x == 0:
            exterior = ("W004", rect.y, rect.height)
        elif rect.x + rect.width == inner_width:
            exterior = ("W002", rect.y, rect.height)
        elif rect.y + rect.height == inner_height:
            exterior = ("W003", rect.x, rect.width)
        if exterior is None or exterior[2] * GRID_MM < 1200:
            continue
        wall_id, start_cell, length_cells = exterior
        openings.append(
            {
                "id": f"O{opening_index:03d}",
                "wallId": wall_id,
                "kind": "window",
                "offset": offset + start_cell * GRID_MM + (length_cells * GRID_MM - 1200) // 2,
                "width": 1200,
                "height": 1200,
                "sill": 900,
                "roomId": item["id"],
            }
        )
        opening_index += 1
    circulation_zones = [
        {
            "id": f"CZ{level_no:02d}{index:02d}",
            "kind": "corridor",
            "polygon": _polygon(
                _Rect(
                    zone.x * GRID_MM, zone.y * GRID_MM, zone.width * GRID_MM, zone.height * GRID_MM
                ),
                offset_x=offset,
                offset_y=offset,
            ),
        }
        for index, zone in enumerate((zone for zone in zones if zone.area), start=1)
    ]
    core_payloads: list[dict[str, Any]] = []
    for kind, core_rect in core_rects:
        touching_rooms = [
            item["id"] for item, room_rect in partitions if _shared_edge(room_rect, core_rect)
        ]
        if not touching_rooms:
            raise HouseGeometryError(
                f"L{level_no:02d}: a {kind} mag nem kapcsolódik tényleges helyiséghez."
            )
        core_payloads.append(
            {
                "kind": kind,
                "roomId": sorted(touching_rooms)[0],
                "polygon": _polygon(
                    _Rect(
                        core_rect.x * GRID_MM,
                        core_rect.y * GRID_MM,
                        core_rect.width * GRID_MM,
                        core_rect.height * GRID_MM,
                    ),
                    offset_x=offset,
                    offset_y=offset,
                ),
            }
        )
    core_area = sum(core_rect.area for _, core_rect in core_rects)
    covered_reserve = sum(zone.area for zone in zones) + core_area
    wall_reserve = (reserve - covered_reserve) * GRID_MM * GRID_MM
    level = {
        "id": f"L{level_no:02d}",
        "elevation": (level_no - 1) * STOREY_HEIGHT_MM,
        "height": STOREY_HEIGHT_MM,
        "boundary": boundary,
        "rooms": level_rooms,
        "walls": walls,
        "openings": openings,
        "connections": connections,
        "circulationZones": circulation_zones,
        "wallReserveMm2": wall_reserve,
        "areaEquation": {
            "grossInternalAreaMm2": internal_cells * GRID_MM * GRID_MM,
            "roomTargetMm2": target_cells * GRID_MM * GRID_MM,
            "circulationMm2": sum(zone.area for zone in zones) * GRID_MM * GRID_MM,
            "coreMm2": core_area * GRID_MM * GRID_MM,
            "wallReserveMm2": wall_reserve,
        },
    }
    return level, core_payloads


def generate_houseplan(data: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_input(data)
    floors = normalized["floors"]
    width_mm, depth_mm = _footprint(
        Decimal(normalized["grossAreaM2"]), floors, normalized["layout"]
    )
    levels: list[dict[str, Any]] = []
    core_shapes: list[list[dict[str, Any]]] = []
    for level_no in range(1, floors + 1):
        level_rooms = [item for item in normalized["rooms"] if item["level"] == level_no]
        if not level_rooms:
            raise HouseGeometryError(f"L{level_no:02d}: a szint nem maradhat helyiség nélkül.")
        level, level_cores = _level_geometry(
            level_no,
            width_mm,
            depth_mm,
            level_rooms,
            floors,
            normalized["accessibility"],
        )
        levels.append(level)
        core_shapes.append(level_cores)
    room_types = {room["id"]: room["type"] for room in normalized["rooms"]}
    actual_adjacencies = {
        tuple(
            sorted(
                (
                    room_types[connection["roomA"]],
                    room_types[connection["roomB"]],
                )
            )
        )
        for level in levels
        for connection in level["connections"]
        if connection["roomA"] != "outside" and connection["roomB"] != "outside"
    }
    missing_adjacencies = {
        tuple(pair) for pair in normalized["requiredAdjacencies"]
    } - actual_adjacencies
    if missing_adjacencies:
        labels = ", ".join("–".join(pair) for pair in sorted(missing_adjacencies))
        raise HouseGeometryError(f"Hiányzó kötelező helyiségkapcsolat: {labels}.")
    vertical_cores: list[dict[str, Any]] = []
    vertical_connections: list[dict[str, Any]] = []
    core_sequence = 1
    for index in range(1, floors):
        for kind in ("stair", "lift"):
            from_core = next(
                (item for item in core_shapes[index - 1] if item["kind"] == kind), None
            )
            to_core = next((item for item in core_shapes[index] if item["kind"] == kind), None)
            if from_core is None and to_core is None:
                continue
            if from_core is None or to_core is None or from_core["polygon"] != to_core["polygon"]:
                raise HouseGeometryError(
                    f"A {kind} mag XY-poligonja nem azonos minden érintett szinten."
                )
            core_id = f"VC{core_sequence:03d}"
            connection_id = f"CX{core_sequence:03d}"
            core_sequence += 1
            vertical_cores.append(
                {
                    "id": core_id,
                    "kind": kind,
                    "polygon": from_core["polygon"],
                    "fromLevelId": f"L{index:02d}",
                    "toLevelId": f"L{index + 1:02d}",
                }
            )
            vertical_connections.append(
                {
                    "id": connection_id,
                    "kind": kind,
                    "coreId": core_id,
                    "fromLevelId": f"L{index:02d}",
                    "fromRoomId": from_core["roomId"],
                    "toLevelId": f"L{index + 1:02d}",
                    "toRoomId": to_core["roomId"],
                }
            )
    geometry: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "generatorVersion": GENERATOR_VERSION,
        "unit": "mm",
        "levels": levels,
        "verticalCores": vertical_cores,
        "verticalConnections": vertical_connections,
        "roof": {
            "kind": normalized["roof"],
            "pitchMilliDegrees": 30000 if normalized["roof"] == "gable" else 0,
            "ridgeAxis": "x" if width_mm >= depth_mm else "y",
        },
    }
    result: dict[str, Any] = {
        "normalizedInput": normalized,
        "inputHash": input_hash(normalized, source),
        "geometry": _canonical_geometry(geometry),
    }
    result["geometrySignature"] = geometry_signature(result["geometry"])
    return result
