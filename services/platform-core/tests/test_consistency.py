from sqlalchemy import select

from app.models import ConsistencyIssue


def put_fact(client, project, source, key, value):
    response = client.post("/api/facts", json={"project_id": project, "source_module": source, "fact_key": key, "value": value})
    assert response.status_code == 200


def test_consistency_detects_and_resolves_revenue_difference(client, db):
    project = "PRJ-CONS-001"
    client.post("/api/events", json={
        "event_id": "EVT-CONS-001", "dedupe_key": "CONS-001", "project_id": project,
        "source_module": "crm", "event_type": "PROJECT_CREATED", "payload": {"project_name": "Konzisztencia projekt"}
    })
    put_fact(client, project, "contract_generator", "approved_revenue", 65000000)
    put_fact(client, project, "finance", "approved_revenue", 63000000)
    result = client.post(f"/api/consistency/scan?project_id={project}").json()
    assert result["detected"] == 1
    issue = db.scalar(select(ConsistencyIssue).where(ConsistencyIssue.project_id == project))
    assert issue.status == "open"
    assert int(issue.financial_impact_huf) == 2000000

    put_fact(client, project, "finance", "approved_revenue", 65000000)
    result2 = client.post(f"/api/consistency/scan?project_id={project}").json()
    assert result2["resolved"] == 1
    db.expire_all()
    issue = db.scalar(select(ConsistencyIssue).where(ConsistencyIssue.project_id == project))
    assert issue.status == "resolved"


def test_missing_pair_does_not_create_false_issue(client, db):
    client.post("/api/events", json={
        "event_id": "EVT-CONS-002", "dedupe_key": "CONS-002", "project_id": "PRJ-CONS-002",
        "source_module": "crm", "event_type": "PROJECT_CREATED", "payload": {"project_name": "Hiányos tényprojekt"}
    })
    put_fact(client, "PRJ-CONS-002", "finance", "approved_revenue", 10)
    result = client.post("/api/consistency/scan?project_id=PRJ-CONS-002").json()
    assert result["detected"] == 0
