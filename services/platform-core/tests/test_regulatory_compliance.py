from app.services.house_designer_geometry import (
    apply_command,
    empty_geometry,
)
from app.services.regulatory_compliance import _binding_issue, evaluate_rules


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
