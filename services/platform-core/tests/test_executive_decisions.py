from sqlalchemy import select

from app.models import ConsistencyIssue, EventRecord, ProjectRegistry, TaskRecord
from app.seed import DEMO_PASSWORD


PASSWORD = DEMO_PASSWORD


def login(client, role: str):
    email = "owner@imperial.local" if role == "owner" else f"{role}@imperial.local"
    response = client.post(
        "/login",
        data={"email": email, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303


def logout(client):
    assert client.post("/logout", follow_redirects=False).status_code == 303


def put_fact(client, project_id: str, source: str, key: str, value: int):
    response = client.post(
        "/api/facts",
        json={
            "project_id": project_id,
            "source_module": source,
            "fact_key": key,
            "value": value,
        },
    )
    assert response.status_code == 200


def test_executive_can_resolve_event_with_evidence_and_close_tasks(client, db):
    response = client.post(
        "/api/events",
        json={
            "event_id": "EVT-EXEC-RESOLVE-001",
            "dedupe_key": "EXEC-RESOLVE-001",
            "project_id": "PRJ-EXEC-RESOLVE-001",
            "source_module": "finance",
            "event_type": "PROJECT_MARGIN_AT_RISK",
            "severity": "critical",
            "financial_impact_huf": 4_500_000,
            "deadline_impact_days": 8,
            "responsible": "finance.lead@example.com",
            "next_action": "Az eltérés okának és fedezetének vezetői jóváhagyása.",
            "executive_relevance": True,
            "payload": {"project_name": "Vezetői döntési tesztprojekt"},
        },
    )
    assert response.status_code == 200
    event = db.scalar(select(EventRecord).where(EventRecord.event_id == "EVT-EXEC-RESOLVE-001"))
    task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == event.event_id))
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == event.project_id))
    assert event.status == "open"
    assert task.status == "open"
    assert project.blocked is True

    login(client, "managing-director")
    page = client.get("/exceptions")
    assert page.status_code == 200
    assert "EVT-EXEC-RESOLVE-001" in page.text
    assert "PROJECT_MARGIN_AT_RISK" in page.text
    resolved = client.post(
        f"/exceptions/events/{event.event_id}/resolve",
        data={
            "resolution_note": "A fedezet jóváhagyva, a projekt pénzügyi kockázata megszűnt.",
            "close_related_tasks": "on",
        },
        follow_redirects=False,
    )
    assert resolved.status_code == 303, resolved.text
    db.refresh(event)
    db.refresh(task)
    db.refresh(project)
    assert event.status == "resolved"
    assert event.resolved_by == "managing-director@imperial.local"
    assert event.resolution_note
    assert event.resolved_at is not None
    assert task.status == "done"
    assert int(project.financial_impact_huf) == 0
    assert project.deadline_impact_days == 0
    assert project.blocked is False
    assert project.risk_level == "green"

    repeated = client.post(
        f"/exceptions/events/{event.event_id}/resolve",
        data={"resolution_note": "Ismételt lezárás nem engedélyezett."},
    )
    assert repeated.status_code == 409


def test_finance_can_assign_and_recheck_consistency_issue(client, db):
    project_id = "PRJ-EXEC-CONS-001"
    client.post(
        "/api/events",
        json={
            "event_id": "EVT-EXEC-CONS-001",
            "dedupe_key": "EXEC-CONS-001",
            "project_id": project_id,
            "source_module": "crm",
            "event_type": "PROJECT_CREATED",
            "payload": {"project_name": "Adateltérés döntési tesztprojekt"},
        },
    )
    put_fact(client, project_id, "contract_generator", "approved_revenue", 70_000_000)
    put_fact(client, project_id, "finance", "approved_revenue", 65_000_000)
    assert client.post(f"/api/consistency/scan?project_id={project_id}").status_code == 200
    issue = db.scalar(select(ConsistencyIssue).where(ConsistencyIssue.project_id == project_id))
    assert issue.status == "open"

    login(client, "finance")
    assigned = client.post(
        f"/exceptions/issues/{issue.fingerprint}/assign",
        data={
            "responsible": "finance.owner@example.com",
            "assignment_note": "A pénzügyi törzsadat gazdája egyezteti a szerződéses értéket.",
        },
        follow_redirects=False,
    )
    assert assigned.status_code == 303, assigned.text
    db.refresh(issue)
    assert issue.responsible == "finance.owner@example.com"
    assert issue.assignment_note

    put_fact(client, project_id, "finance", "approved_revenue", 70_000_000)
    rechecked = client.post(
        f"/exceptions/issues/{issue.fingerprint}/recheck",
        follow_redirects=False,
    )
    assert rechecked.status_code == 303, rechecked.text
    db.refresh(issue)
    assert issue.status == "resolved"
    assert issue.resolved_at is not None


def test_customer_cannot_execute_executive_decisions(client):
    login(client, "customer")
    response = client.post(
        "/exceptions/events/EVT-NOT-ALLOWED/resolve",
        data={"resolution_note": "Jogosulatlan lezárási kísérlet."},
    )
    assert response.status_code == 403
