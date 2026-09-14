from scripts.report_module_release_readiness import build_report


def test_all_49_modules_are_explicitly_classified_with_existing_evidence_files():
    report = build_report()
    assert report["registered_modules"] == 49
    assert report["classification_complete"] is True
    assert report["all_test_files_present"] is True
    assert sum(report["counts"].values()) == 49


def test_release_report_fails_closed_for_non_native_modules():
    report = build_report()
    by_id = {row["module_id"]: row for row in report["modules"]}
    assert report["fully_proven"] is False
    assert by_id["answer-center"]["release_status"] == "proven_native"
    assert by_id["b2b-project-intake"]["release_status"] == "proven_native"
    assert by_id["sales"]["release_status"] == "proven_native"
    assert by_id["house-catalog"]["release_status"] == "proven_native"
    assert by_id["engineering-workspace"]["release_status"] == "proven_native"
    assert by_id["project-control"]["release_status"] == "proven_native"
    assert by_id["house-designer"]["release_status"] == "proven_native"
    assert by_id["market-creative-intelligence"]["release_status"] == "proven_native"
    assert by_id["partner-connect"]["release_status"] == "proven_native"
    assert by_id["partner-control"]["release_status"] == "proven_native"
    assert by_id["crm"]["release_status"] == "external_integrated"
