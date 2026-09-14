import json
from sqlalchemy import select

from app.models import ConsistencyIssue, PilotRun, ProjectRegistry


def test_preconstruction_pilot_passes(client, db):
    result = client.post("/api/pilots/run?scenario=preconstruction").json()
    assert result[0]["status"] == "passed"
    assert result[0]["steps_passed"] == result[0]["steps_total"]
    assert db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == "PILOT-HOUSE-001")) is not None


def test_all_three_pilots_pass_and_change_issue_resolves(client, db):
    result = client.post("/api/pilots/run?scenario=all").json()
    assert len(result) == 3
    assert all(r["status"] == "passed" for r in result)
    issue = db.scalar(select(ConsistencyIssue).where(ConsistencyIssue.project_id == "PILOT-CHANGE-003"))
    assert issue is not None and issue.status == "resolved"
    pilots = db.scalars(select(PilotRun)).all()
    assert len(pilots) == 3
    assert all(json.loads(p.result_json) for p in pilots)


def test_dashboard_reflects_pilot_exceptions(client):
    client.post("/api/pilots/run?scenario=active_procurement")
    metrics = client.get("/api/dashboard").json()
    assert metrics["project_count"] >= 1
    assert metrics["critical_events"] >= 1
    assert metrics["blocked_projects"] >= 1
