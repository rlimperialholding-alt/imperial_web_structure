from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

RULE_SCHEMA_VERSION = "regulatory-rules-v2"
MAX_DECLARATIVE_RULES = 500

RULE_CATEGORIES = frozenset(
    {
        "zoning_use",
        "parcel_building_mode",
        "site_coverage",
        "green_area",
        "floor_area_ratio",
        "setbacks_buildable_area",
        "height_storeys",
        "roof_townscape",
        "parking_access_utilities",
        "room_environment",
        "circulation_stairs",
        "accessibility",
        "protection_special",
        "fire_energy_handoff",
    }
)

FACT_TYPES = {
    "building.storeys": "number",
    "building.footprint_area_m2": "number",
    "building.gross_area_m2": "number",
    "building.height_m": "number",
    "building.site_coverage_percent": "number",
    "building.floor_area_ratio": "number",
    "rooms.count": "number",
    "rooms.min_area_m2": "number",
    "rooms.min_height_m": "number",
    "roof.min_pitch_deg": "number",
    "roof.max_pitch_deg": "number",
    "roof.types": "collection",
    "site.zoning_code": "string",
    "site.building_mode": "string",
    "site.allowed_uses": "collection",
    "site.green_area_percent": "number",
    "site.front_setback_m": "number",
    "site.side_setback_m": "number",
    "site.rear_setback_m": "number",
    "site.parking_spaces": "number",
    "site.access_verified": "boolean",
    "site.utilities_verified": "boolean",
    "site.protection_clear": "boolean",
    "building.stair_data_complete": "boolean",
    "building.accessibility_data_complete": "boolean",
    "handoff.fire_data_complete": "boolean",
    "handoff.energy_data_complete": "boolean",
}

CATEGORY_FACTS = {
    "zoning_use": frozenset({"site.zoning_code", "site.allowed_uses"}),
    "parcel_building_mode": frozenset({"site.building_mode"}),
    "site_coverage": frozenset(
        {"building.footprint_area_m2", "building.site_coverage_percent"}
    ),
    "green_area": frozenset({"site.green_area_percent"}),
    "floor_area_ratio": frozenset({"building.floor_area_ratio"}),
    "setbacks_buildable_area": frozenset(
        {"site.front_setback_m", "site.side_setback_m", "site.rear_setback_m"}
    ),
    "height_storeys": frozenset({"building.height_m", "building.storeys"}),
    "roof_townscape": frozenset(
        {"roof.types", "roof.min_pitch_deg", "roof.max_pitch_deg"}
    ),
    "parking_access_utilities": frozenset(
        {"site.parking_spaces", "site.access_verified", "site.utilities_verified"}
    ),
    "room_environment": frozenset(
        {"rooms.count", "rooms.min_area_m2", "rooms.min_height_m"}
    ),
    "circulation_stairs": frozenset({"building.stair_data_complete"}),
    "accessibility": frozenset({"building.accessibility_data_complete"}),
    "protection_special": frozenset({"site.protection_clear"}),
    "fire_energy_handoff": frozenset(
        {"handoff.fire_data_complete", "handoff.energy_data_complete"}
    ),
}

_OPERATORS_BY_TYPE = {
    "number": frozenset({"lte", "gte", "eq"}),
    "string": frozenset({"eq", "in"}),
    "boolean": frozenset({"eq"}),
    "collection": frozenset({"subset", "contains", "contains_any"}),
}
_SEVERITIES = frozenset({"BLOCKER", "ERROR", "WARNING", "INFO"})
_RULE_KEYS = frozenset(
    {
        "code",
        "category",
        "fact",
        "operator",
        "expected",
        "severity",
        "sourceRef",
        "ruleRef",
        "explanation",
        "remediation",
        "geometryPath",
    }
)
_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_.-]{2,119}$")


class RegulatoryRuleSchemaError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_declarative_rules(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RegulatoryRuleSchemaError(
            "rules_list_invalid", "A deklaratív szabályok listája hibás."
        )
    if not 1 <= len(value) <= MAX_DECLARATIVE_RULES:
        raise RegulatoryRuleSchemaError(
            "rules_count_invalid",
            f"A deklaratív szabályok száma 1–{MAX_DECLARATIVE_RULES} lehet.",
        )
    normalized: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise RegulatoryRuleSchemaError(
                "rule_invalid", f"A(z) {index}. deklaratív szabály nem objektum."
            )
        unknown = sorted(set(raw) - _RULE_KEYS)
        if unknown:
            raise RegulatoryRuleSchemaError(
                "rule_key_unknown", f"Ismeretlen szabálymező: {', '.join(unknown)}."
            )
        code = _required_text(raw, "code", index, 120).upper()
        if not _CODE_PATTERN.fullmatch(code):
            raise RegulatoryRuleSchemaError(
                "rule_code_invalid", f"A(z) {index}. szabálykód formátuma hibás."
            )
        if code in seen_codes:
            raise RegulatoryRuleSchemaError("rule_code_duplicate", f"Ismétlődő szabálykód: {code}.")
        seen_codes.add(code)
        category = _required_text(raw, "category", index, 80)
        if category not in RULE_CATEGORIES:
            raise RegulatoryRuleSchemaError(
                "rule_category_invalid", f"A(z) {index}. szabálykategória nem támogatott."
            )
        fact = _required_text(raw, "fact", index, 120)
        fact_type = FACT_TYPES.get(fact)
        if fact_type is None:
            raise RegulatoryRuleSchemaError(
                "rule_fact_invalid", f"A(z) {index}. szabály nem engedélyezett tényre hivatkozik."
            )
        if fact not in CATEGORY_FACTS[category]:
            raise RegulatoryRuleSchemaError(
                "rule_category_fact_mismatch",
                f"A(z) {index}. szabály ténye nem tartozik a megadott kategóriához.",
            )
        operator = _required_text(raw, "operator", index, 40)
        if operator not in _OPERATORS_BY_TYPE[fact_type]:
            raise RegulatoryRuleSchemaError(
                "rule_operator_invalid",
                f"A(z) {index}. operátor nem használható a(z) {fact} ténnyel.",
            )
        expected = _normalize_expected(raw.get("expected"), fact_type, operator, index)
        severity = str(raw.get("severity") or "BLOCKER").strip().upper()
        if severity not in _SEVERITIES:
            raise RegulatoryRuleSchemaError(
                "rule_severity_invalid", f"A(z) {index}. szabály súlyossága hibás."
            )
        item: dict[str, Any] = {
            "code": code,
            "category": category,
            "fact": fact,
            "operator": operator,
            "expected": expected,
            "severity": severity,
            "sourceRef": _required_text(raw, "sourceRef", index, 1_200),
            "ruleRef": _required_text(raw, "ruleRef", index, 500),
            "explanation": _required_text(raw, "explanation", index, 2_000),
            "remediation": _required_text(raw, "remediation", index, 2_000),
        }
        geometry_path = str(raw.get("geometryPath") or "").strip()
        if len(geometry_path) > 1_000:
            raise RegulatoryRuleSchemaError(
                "rule_text_too_long", f"A(z) {index}. geometryPath mezője túl hosszú."
            )
        if geometry_path:
            item["geometryPath"] = geometry_path
        normalized.append(item)
    return sorted(normalized, key=lambda item: item["code"])


def _required_text(raw: dict[str, Any], key: str, index: int, maximum: int) -> str:
    value = str(raw.get(key) or "").strip()
    if not value:
        raise RegulatoryRuleSchemaError(
            "rule_field_required", f"A(z) {index}. szabály {key} mezője kötelező."
        )
    if len(value) > maximum:
        raise RegulatoryRuleSchemaError(
            "rule_text_too_long", f"A(z) {index}. szabály {key} mezője túl hosszú."
        )
    return value


def _normalize_expected(value: Any, fact_type: str, operator: str, index: int) -> Any:
    if fact_type == "number":
        if isinstance(value, bool):
            raise RegulatoryRuleSchemaError(
                "rule_expected_invalid", f"A(z) {index}. szabály határértéke nem szám."
            )
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise RegulatoryRuleSchemaError(
                "rule_expected_invalid", f"A(z) {index}. szabály határértéke nem szám."
            ) from error
        if not number.is_finite():
            raise RegulatoryRuleSchemaError(
                "rule_expected_invalid", f"A(z) {index}. szabály határértéke nem véges."
            )
        return format(number.normalize(), "f")
    if fact_type == "boolean":
        if not isinstance(value, bool):
            raise RegulatoryRuleSchemaError(
                "rule_expected_invalid", f"A(z) {index}. szabály boolean értéket vár."
            )
        return value
    if operator in {"in", "subset", "contains", "contains_any"}:
        if not isinstance(value, list) or not value:
            raise RegulatoryRuleSchemaError(
                "rule_expected_invalid", f"A(z) {index}. szabály nem üres listát vár."
            )
        values = sorted({str(item).strip() for item in value if str(item).strip()})
        if not values or any(len(item) > 160 for item in values):
            raise RegulatoryRuleSchemaError(
                "rule_expected_invalid", f"A(z) {index}. szabály értéklistája hibás."
            )
        return values
    text = str(value).strip()
    if not text or len(text) > 160:
        raise RegulatoryRuleSchemaError(
            "rule_expected_invalid", f"A(z) {index}. szabály várt értéke hibás."
        )
    return text
