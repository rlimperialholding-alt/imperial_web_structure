import json
from types import SimpleNamespace

import pytest

from app.services.house_designer_geometry import (
    apply_command,
    empty_geometry,
)
from app.services.house_designer_readiness import _ruleset_categories
from app.services.regulatory_compliance import _binding_issue, evaluate_rules
from app.services.regulatory_rule_schema import (
    RULE_CATEGORIES,
    RegulatoryRuleSchemaError,
    normalize_declarative_rules,
)


def _verified_site():
    return {
        "verificationStatus": "verified",
        "municipalityCode": "TEST",
        "parcelNumber": "1/1",
    }


def test_missing_site_and_rules_are_unknown_not_pass():
    outcome, findings = evaluate_rules(empty_geometry(), {}, None)
    assert outcome == "UNKNOWN"
    assert findings[0].code == "SITE_UNVERIFIED"
    outcome, findings = evaluate_rules(empty_geometry(), _verified_site(), None)
    assert outcome == "UNKNOWN"
    assert findings[0].code == "RULESET_MISSING"


def test_ruleset_binding_requires_source_and_interpretation_evidence():
    empty = {"sourceIds": [], "sources": [], "interpretationIds": [], "interpretations": []}
    missing_interpretation = {
        "sourceIds": ["SRC-1"],
        "sources": [
            {
                "id": "SRC-1",
                "status": "active",
                "securityStatus": "approved",
                "revision": 1,
                "latestRevision": 1,
                "effective": True,
            }
        ],
        "interpretationIds": [],
        "interpretations": [],
    }

    assert _binding_issue(empty) == "source_missing"
    assert _binding_issue(missing_interpretation) == "interpretation_missing"


def test_numeric_boundary_is_inclusive_and_excess_fails():
    geometry = empty_geometry(10_000, 8_000)
    rules = {"maxStoreys": 1, "maxGrossAreaM2": "80", "sourceRef": "fixture"}
    assert evaluate_rules(geometry, _verified_site(), rules)[0] == "PASS"
    rules["maxGrossAreaM2"] = "79.99"
    outcome, findings = evaluate_rules(geometry, _verified_site(), rules)
    assert outcome == "FAIL"
    assert findings[0].code == "MAX_GROSS_AREA"


def test_roof_selection_and_allowed_values_fail_closed():
    rules = {"maxStoreys": 3, "allowedRoofTypes": ["gable"], "sourceRef": "fixture"}
    outcome, findings = evaluate_rules(empty_geometry(), _verified_site(), rules)
    assert outcome == "UNKNOWN"
    assert findings[0].code == "ROOF_NOT_SELECTED"
    geometry = apply_command(empty_geometry(), "set_roof", {"levelId": "L01", "roofType": "flat"})
    outcome, findings = evaluate_rules(geometry, _verified_site(), rules)
    assert outcome == "FAIL"
    assert findings[0].code == "ROOF_TYPE_FORBIDDEN"


def _declarative_rule(**overrides):
    value = {
        "code": "MAX_BUILDING_HEIGHT",
        "category": "height_storeys",
        "fact": "building.height_m",
        "operator": "lte",
        "expected": "3",
        "severity": "BLOCKER",
        "sourceRef": "SRC-1",
        "ruleRef": "12. § (3)",
        "explanation": "Az épület túl magas.",
        "remediation": "Csökkentse az épület magasságát.",
        "geometryPath": "levels",
    }
    value.update(overrides)
    return value


def test_declarative_rules_report_pass_fail_and_missing_fact_as_unknown():
    rules = {
        "schemaVersion": "regulatory-rules-v2",
        "checks": [_declarative_rule()],
    }
    outcome, findings = evaluate_rules(empty_geometry(), _verified_site(), rules)
    assert outcome == "PASS"
    assert findings[0].outcome == "PASS"
    assert findings[0].measured == {"fact": "building.height_m", "value": "2.8"}

    rules["checks"][0]["expected"] = "2.7"
    outcome, findings = evaluate_rules(empty_geometry(), _verified_site(), rules)
    assert outcome == "FAIL"
    assert findings[0].code == "MAX_BUILDING_HEIGHT"

    rules["checks"] = [
        _declarative_rule(
            code="MIN_GREEN_AREA",
            category="green_area",
            fact="site.green_area_percent",
            operator="gte",
            expected="40",
        )
    ]
    outcome, findings = evaluate_rules(empty_geometry(), _verified_site(), rules)
    assert outcome == "UNKNOWN"
    assert findings[0].outcome == "UNKNOWN"


def test_declarative_rules_use_only_allowlisted_facts_and_operators():
    with pytest.raises(RegulatoryRuleSchemaError) as arbitrary_path:
        normalize_declarative_rules([_declarative_rule(fact="site.__dict__.secret")])
    assert arbitrary_path.value.code == "rule_fact_invalid"

    with pytest.raises(RegulatoryRuleSchemaError) as arbitrary_operator:
        normalize_declarative_rules([_declarative_rule(operator="python")])
    assert arbitrary_operator.value.code == "rule_operator_invalid"

    with pytest.raises(RegulatoryRuleSchemaError) as category_spoofing:
        normalize_declarative_rules([_declarative_rule(category="green_area")])
    assert category_spoofing.value.code == "rule_category_fact_mismatch"


def test_declarative_site_facts_require_verified_fact_payload():
    rules = {
        "schemaVersion": "regulatory-rules-v2",
        "checks": [
            _declarative_rule(
                code="MAX_SITE_COVERAGE",
                category="site_coverage",
                fact="building.site_coverage_percent",
                operator="lte",
                expected="30",
            )
        ],
    }
    site = {
        **_verified_site(),
        "plotAreaM2": 1_000,
        "verifiedFacts": {"plotAreaM2": 400},
    }
    outcome, findings = evaluate_rules(empty_geometry(), site, rules)
    assert outcome == "PASS"
    assert findings[0].measured["value"] == "20"


def test_release_readiness_requires_v2_coverage_of_all_mandatory_categories():
    legacy = SimpleNamespace(rules_json=json.dumps({"maxStoreys": 2}))
    assert _ruleset_categories(legacy) == set()

    coverage_specs = {
        "zoning_use": ("site.zoning_code", "eq", "LKE-1"),
        "parcel_building_mode": ("site.building_mode", "eq", "side"),
        "site_coverage": ("building.site_coverage_percent", "lte", "30"),
        "green_area": ("site.green_area_percent", "gte", "40"),
        "floor_area_ratio": ("building.floor_area_ratio", "lte", "0.5"),
        "setbacks_buildable_area": ("site.front_setback_m", "gte", "5"),
        "height_storeys": ("building.height_m", "lte", "7.5"),
        "roof_townscape": ("roof.types", "subset", ["gable", "hip"]),
        "parking_access_utilities": ("site.parking_spaces", "gte", "1"),
        "room_environment": ("rooms.min_area_m2", "gte", "8"),
        "circulation_stairs": ("building.stair_data_complete", "eq", True),
        "accessibility": ("building.accessibility_data_complete", "eq", True),
        "protection_special": ("site.protection_clear", "eq", True),
        "fire_energy_handoff": ("handoff.fire_data_complete", "eq", True),
    }
    assert set(coverage_specs) == set(RULE_CATEGORIES)
    checks = []
    for index, (category, (fact, operator, expected)) in enumerate(
        sorted(coverage_specs.items())
    ):
        checks.append(
            _declarative_rule(
                code=f"COVERAGE_{index:02d}",
                category=category,
                fact=fact,
                operator=operator,
                expected=expected,
            )
        )
    complete = SimpleNamespace(
        rules_json=json.dumps(
            {"schemaVersion": "regulatory-rules-v2", "checks": checks}
        )
    )
    assert _ruleset_categories(complete) == set(RULE_CATEGORIES)
