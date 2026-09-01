from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_REGISTRY = ROOT / "data" / "platform_demo_seed.json"

NATIVE_TESTS: dict[str, tuple[str, ...]] = {
    "workspace": ("test_workspace.py",),
    "executive-dashboard": ("test_executive_decisions.py",),
    "control-center": ("test_consistency.py", "test_releases.py"),
    "completion-audit": ("test_releases.py", "test_canonical_integrity.py"),
    "integration-control-room": ("test_canonical_bridge.py", "test_events.py"),
    "admin": ("test_user_administration.py", "test_security.py"),
    "workflow-center": ("test_workspace.py", "test_communications.py"),
    "pm-cockpit": ("test_operations.py", "test_smart_calendar.py"),
    "operations-workspace": ("test_operations.py",),
    "booking-engine": ("test_booking_reservation_business.py",),
    "reservation-engine": ("test_booking_reservation_business.py",),
    "contract-generator": (
        "test_commercial_integration.py",
        "test_contract_workflow.py",
    ),
    "my-imperial": ("test_my_imperial_project_portal.py",),
    "housebuild-agent": ("test_technical_products.py",),
    "housematch": ("test_experience.py",),
    "house-designer": (
        "test_house_designer_api.py",
        "test_house_designer_guest.py",
        "test_house_designer_submission.py",
        "test_house_designer_vertical_slice.py",
    ),
    "plotcheck": ("test_technical_products.py",),
    "buildconfig": ("test_technical_products.py",),
    "plancheck": ("test_plancheck_v01.py", "test_technical_products.py"),
    "smart-calendar": ("test_smart_calendar.py",),
    "change-control": ("test_change_control_business.py",),
    "document-center": ("test_workspace.py", "test_canonical_documents.py"),
    "document-evidence": ("test_workspace.py", "test_canonical_documents.py"),
    "import-center": ("test_import_center.py",),
    "tendermail": ("test_tender_mail.py",),
    "partner-connect": (
        "test_tender_portal.py",
        "test_partner_control.py",
        "test_partner_field.py",
    ),
    "partner-control": (
        "test_partner_control.py",
        "test_tender_portal.py",
        "test_partner_field.py",
    ),
    "partner-field": ("test_partner_field.py",),
    "field-pwa": ("test_partner_field.py",),
    "finance-intelligence": ("test_financial_intelligence.py", "test_project_finance.py"),
    "financial-control": ("test_financial_allocations.py", "test_itep_finance.py"),
    "imperial-care": ("test_imperial_care.py",),
    "marketing-control": ("test_marketing_lead_automation.py",),
    "market-creative-intelligence": (
        "test_market_intelligence.py",
        "test_market_intelligence_performance.py",
    ),
    "campaign-factory": ("test_marketing_lead_automation.py",),
    "content-factory": ("test_content_quality_workflow.py",),
    "claim-registry": ("test_content_quality_workflow.py",),
    "lead-intelligence": ("test_marketing_lead_automation.py",),
    "sales": ("test_sales_pipeline.py", "test_booking_reservation_business.py"),
    "house-catalog": ("test_house_catalog_lifecycle.py", "test_technical_products.py"),
    "engineering-workspace": (
        "test_engineering_workspace_lifecycle.py",
        "test_technical_products.py",
        "test_canonical_documents.py",
    ),
    "project-control": (
        "test_project_control_lifecycle.py",
        "test_operations.py",
        "test_project_finance.py",
    ),
    "procurement": (
        "test_procurement_execution.py",
        "test_operations.py",
        "test_tender_portal.py",
        "test_partner_control.py",
    ),
    "housevision": (
        "test_housevision_production.py",
        "test_visual_generation_policy.py",
    ),
    "website-content-control": (
        "test_website_content_control.py",
        "test_content_quality_workflow.py",
    ),
    "answer-center": (
        "test_answer_center.py",
        "test_canonical_documents.py",
        "test_my_imperial_project_portal.py",
    ),
    "b2b-project-intake": (
        "test_b2b_project_intake.py",
        "test_marketing_lead_automation.py",
        "test_crm_canonical_sync.py",
    ),
}

EXTERNAL_INTEGRATED: dict[str, dict] = {
    "digital-project-managers": {
        "tests": ("test_canonical_bridge.py",),
        "gap": (
            "A külön DPM futtatókörnyezet böngészős UAT-ja és "
            "rendelkezésreállási SLA-ja külön kapu."
        ),
    },
    "crm": {
        "tests": ("test_crm_canonical_sync.py", "test_crm_sites_transport.py"),
        "gap": (
            "A kanonikus kétirányú kapcsolat bizonyított; a külön CRM alkalmazás "
            "teljes szerepkörös UAT-ja külön kapu."
        ),
    },
}

PARTIAL_NATIVE: dict[str, dict] = {}

GENERIC_ONLY: dict[str, str] = {}


def build_report() -> dict:
    registry = json.loads(MODULE_REGISTRY.read_text(encoding="utf-8"))["modules"]
    module_ids = {row["id"] for row in registry}
    classifications = {
        "native": set(NATIVE_TESTS),
        "external": set(EXTERNAL_INTEGRATED),
        "partial": set(PARTIAL_NATIVE),
        "generic": set(GENERIC_ONLY),
    }
    overlaps = {
        f"{left}/{right}": sorted(classifications[left] & classifications[right])
        for index, left in enumerate(classifications)
        for right in list(classifications)[index + 1 :]
        if classifications[left] & classifications[right]
    }
    if overlaps:
        raise RuntimeError(f"A release-mátrix osztályozása átfed: {overlaps}")
    classified = (
        set(NATIVE_TESTS) | set(EXTERNAL_INTEGRATED) | set(PARTIAL_NATIVE) | set(GENERIC_ONLY)
    )
    missing = sorted(module_ids - classified)
    extra = sorted(classified - module_ids)
    if missing or extra:
        raise RuntimeError(f"A release-mátrix osztályozása eltér: missing={missing}, extra={extra}")

    rows = []
    for module in registry:
        module_id = module["id"]
        if module_id in NATIVE_TESTS:
            status = "proven_native"
            tests = NATIVE_TESTS[module_id]
            gap = None
        elif module_id in EXTERNAL_INTEGRATED:
            status = "external_integrated"
            tests = EXTERNAL_INTEGRATED[module_id]["tests"]
            gap = EXTERNAL_INTEGRATED[module_id]["gap"]
        elif module_id in PARTIAL_NATIVE:
            status = "partial_native"
            tests = PARTIAL_NATIVE[module_id]["tests"]
            gap = PARTIAL_NATIVE[module_id]["gap"]
        else:
            status = "generic_only"
            tests = ()
            gap = GENERIC_ONLY[module_id]
        test_evidence = [
            {
                "file": file_name,
                "exists": (ROOT / "tests" / file_name).is_file(),
            }
            for file_name in tests
        ]
        rows.append(
            {
                "module_id": module_id,
                "name": module["name"],
                "declared_status": module.get("status"),
                "source_release": module.get("sourceRelease"),
                "release_status": status,
                "release_ready": status == "proven_native"
                and all(item["exists"] for item in test_evidence),
                "test_evidence": test_evidence,
                "remaining_gap": gap,
            }
        )
    counts = Counter(row["release_status"] for row in rows)
    return {
        "registered_modules": len(rows),
        "classification_complete": len(rows) == 49,
        "counts": dict(sorted(counts.items())),
        "all_test_files_present": all(
            evidence["exists"] for row in rows for evidence in row["test_evidence"]
        ),
        "fully_proven": all(row["release_ready"] for row in rows),
        "modules": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and not report["fully_proven"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
