from scripts.online_staging_uat import UATReport, escape_drive


def test_report_go_only_when_every_check_passes():
    report = UATReport(run_id="x", environment="staging", base_url="https://example.test")
    report.add("a", True, "ok")
    report.add("b", True, "ok")
    assert report.to_dict()["status"] == "GO"
    report.add("c", False, "bad")
    assert report.to_dict()["status"] == "NO-GO"
    assert report.to_dict()["failed_count"] == 1


def test_drive_query_escape():
    assert escape_drive("O'Reilly") == "O\\'Reilly"
