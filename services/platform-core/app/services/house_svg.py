from __future__ import annotations

from html import escape
from typing import Any

from app.services.house_geometry import canonical_json, geometry_signature

_COLORS = {
    "entrance": "#d8c381",
    "living": "#c9dfcf",
    "kitchen": "#f2d49b",
    "dining": "#ead9ae",
    "circulation": "#d9dde4",
    "bathroom": "#b9d8e8",
    "wc": "#b9d8e8",
    "bedroom": "#d8cfeb",
    "mechanical": "#d5d5d5",
    "utility": "#ddd5ca",
    "storage": "#ded7c7",
}


def _points(
    points: list[list[int]], scale: float, x_offset: float, y_offset: float, height: int
) -> str:
    return " ".join(
        f"{x_offset + x * scale:.2f},{y_offset + (height - y) * scale:.2f}" for x, y in points
    )


def _polygon_element(
    class_name: str,
    points: list[list[int]],
    scale: float,
    x_origin: float,
    y_origin: float,
    max_depth: int,
    *,
    fill: str | None = None,
) -> str:
    fill_attr = f' fill="{fill}"' if fill else ""
    point_value = _points(points, scale, x_origin, y_origin, max_depth)
    return f'<polygon class="{class_name}"{fill_attr} points="{point_value}"/>'


def render_houseplan_svg(geometry: dict[str, Any]) -> str:
    """Render canonical HousePlan geometry without becoming a second data source."""
    signature = geometry_signature(geometry)
    levels = geometry.get("levels") or []
    if not levels:
        raise ValueError("Nincs renderelhető szint.")
    max_width = max(level["boundary"][1][0] for level in levels)
    max_depth = max(level["boundary"][2][1] for level in levels)
    panel_width, panel_height, gap, margin = 520, 430, 28, 28
    total_width = margin * 2 + len(levels) * panel_width + (len(levels) - 1) * gap
    total_height = panel_height + margin * 2 + 44
    chunks = [
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-labelledby="title desc" viewBox="0 0 {total_width} {total_height}" '
        f'data-geometry-signature="{signature}">',
        '<title id="title">HousePlan alaprajzi előnézet</title>',
        f'<desc id="desc">Determinista SVG, {len(levels)} szint, '
        f"geometria SHA-256 {signature}</desc>",
        "<style>"
        ".boundary{fill:#fff;stroke:#122b45;stroke-width:3}"
        ".room{stroke:#42556a;stroke-width:1.5}"
        ".label{font:600 12px system-ui;fill:#102c49}"
        ".area{font:10px system-ui;fill:#43546a}"
        ".zone{fill:#eef0f3;stroke:#8c96a3;stroke-dasharray:5 4}"
        ".core{fill:#c8cdd4;stroke:#586475;stroke-width:2}"
        ".level-title{font:700 17px system-ui;fill:#102c49}"
        "</style>",
    ]
    core_by_level: dict[str, list[dict[str, Any]]] = {}
    for core in geometry.get("verticalCores", []):
        core_by_level.setdefault(core["fromLevelId"], []).append(core)
        core_by_level.setdefault(core["toLevelId"], []).append(core)
    for index, level in enumerate(levels):
        x_origin = margin + index * (panel_width + gap)
        y_origin = margin + 38
        scale = min((panel_width - 30) / max_width, (panel_height - 30) / max_depth)
        level_name = escape(level["id"])
        chunks.append(
            f'<text class="level-title" x="{x_origin}" y="{margin + 18}">{level_name}</text>'
        )
        chunks.append(
            _polygon_element("boundary", level["boundary"], scale, x_origin, y_origin, max_depth)
        )
        for zone in level.get("circulationZones", []):
            chunks.append(
                _polygon_element("zone", zone["polygon"], scale, x_origin, y_origin, max_depth)
            )
        for core in core_by_level.get(level["id"], []):
            chunks.append(
                _polygon_element("core", core["polygon"], scale, x_origin, y_origin, max_depth)
            )
        for room in level.get("rooms", []):
            polygon = room["polygon"]
            xs, ys = [point[0] for point in polygon[:-1]], [point[1] for point in polygon[:-1]]
            center_x = x_origin + (min(xs) + max(xs)) * scale / 2
            center_y = y_origin + (max_depth - (min(ys) + max(ys)) / 2) * scale
            color = _COLORS.get(room["type"], "#e5e7ea")
            chunks.append(
                _polygon_element("room", polygon, scale, x_origin, y_origin, max_depth, fill=color)
            )
            room_name = escape(room["name"])
            chunks.append(
                f'<text class="label" text-anchor="middle" x="{center_x:.2f}" '
                f'y="{center_y:.2f}">{room_name}</text>'
            )
            area_m2 = room["actualAreaMm2"] / 1_000_000
            chunks.append(
                f'<text class="area" text-anchor="middle" x="{center_x:.2f}" '
                f'y="{center_y + 15:.2f}">{area_m2:.2f} m²</text>'
            )
    metadata = canonical_json({"geometrySignature": signature, "renderer": "house-svg-v1"})
    chunks.append(f"<metadata>{escape(metadata)}</metadata>")
    chunks.append("</svg>")
    return "".join(chunks)
