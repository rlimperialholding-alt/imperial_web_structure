from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import get_engine
from app.worker import process_task
from tests.conftest import ADMIN_HEADERS

KALMAN_ID = "11111111-1111-4111-8111-111111111101"
MATE_ID = "11111111-1111-4111-8111-111111111102"
MISI_ID = "11111111-1111-4111-8111-111111111103"


def test_three_seeded_agents_and_separate_memories(client: TestClient) -> None:
    response = client.get("/api/v1/agents", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    agents = response.json()
    assert {item["name"] for item in agents} == {
        "Digitális Kálmán",
        "Digitális Máté",
        "Digitális Misi",
    }
    assert {item["authority_profile"] for item in agents} == {"standard-r0-r7"}

    memory = client.get(
        f"/api/v1/agents/{KALMAN_ID}/projects/P-5001/memory",
        headers=ADMIN_HEADERS,
    )
    assert memory.status_code == 200
    second_memory = client.get(
        f"/api/v1/agents/{MATE_ID}/projects/P-5002/memory",
        headers=ADMIN_HEADERS,
    )
    assert second_memory.status_code == 200
    assert memory.json()["id"] != second_memory.json()["id"]


def test_project_context_uses_canonical_adapter(client: TestClient) -> None:
    response = client.get("/api/v1/projects/P-5002/context", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["project"]["id"] == "P-5002"
    assert payload["customer"]["id"] == payload["project"]["customerId"]


def test_project_assignment_and_memory_are_audited(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/agents/{KALMAN_ID}/assignments",
        headers=ADMIN_HEADERS,
        json={
            "external_project_id": "P-5003",
            "approval_owner_ref": "USR-03",
            "restrictions": {"externalWrites": False},
        },
    )
    assert response.status_code == 201
    assert response.json()["digital_manager_id"] == KALMAN_ID

    memory = client.get(
        f"/api/v1/agents/{KALMAN_ID}/projects/P-5003/memory",
        headers=ADMIN_HEADERS,
    )
    assert memory.status_code == 200
    assert memory.json()["content"] == {}

    audit = client.get(
        "/api/v1/audit/events?project_id=P-5003",
        headers=ADMIN_HEADERS,
    )
    assert audit.status_code == 200
    entity_types = {item["entity_type"] for item in audit.json()}
    assert "project_assignments" in entity_types
    assert "project_memories" in entity_types


def test_r0_to_r3_tasks_are_created_and_all_writes_are_audited(
    client: TestClient,
) -> None:
    first_task_id = None
    for risk_level in range(4):
        response = client.post(
            f"/api/v1/agents/{KALMAN_ID}/tasks",
            headers=ADMIN_HEADERS,
            json={
                "external_project_id": "P-5001",
                "task_type": "internal-administration",
                "objective": f"Create reversible R{risk_level} test task",
                "risk_level": risk_level,
            },
        )
        assert response.status_code == 201
        assert response.json()["policy"]["allowed"] is True
        assert response.json()["task"]["status"] == "CREATED"
        first_task_id = first_task_id or response.json()["task"]["id"]

    assert first_task_id is not None
    assert process_task(first_task_id) == "COMPLETED"

    with get_engine().connect() as connection:
        task_count = connection.execute(
            text(
                "SELECT count(*) FROM agent_tasks "
                "WHERE external_project_id = 'P-5001' AND risk_level <= 3"
            )
        ).scalar_one()
        audit_count = connection.execute(
            text(
                "SELECT count(*) FROM audit_events "
                "WHERE external_project_id = 'P-5001' "
                "AND entity_type = 'agent_tasks' AND action = 'INSERT'"
            )
        ).scalar_one()
    assert audit_count >= task_count


def test_r6_r7_block_and_escalate_before_execution(client: TestClient) -> None:
    approval_ids = []
    for risk_level, escalation_level in ((6, "E3"), (7, "E4")):
        response = client.post(
            f"/api/v1/agents/{KALMAN_ID}/tasks",
            headers=ADMIN_HEADERS,
            json={
                "external_project_id": "P-5001",
                "task_type": "external-commitment",
                "objective": "Attempt contract modification or performance certification",
                "risk_level": risk_level,
                "impact": {"legal": "binding"},
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["task"]["status"] == "BLOCKED"
        assert body["policy"]["escalation_level"] == escalation_level
        assert body["approval_request_id"] is not None
        assert body["queued"] is False
        approval_ids.append(body["approval_request_id"])

    approved = client.post(
        f"/api/v1/approvals/{approval_ids[0]}/decision",
        headers=ADMIN_HEADERS,
        json={"decision": "APPROVED", "rationale": "Human review completed"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"

    rejected = client.post(
        f"/api/v1/approvals/{approval_ids[1]}/decision",
        headers=ADMIN_HEADERS,
        json={"decision": "REJECTED", "rationale": "Critical action rejected"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"


def test_memory_optimistic_lock_and_workqueue(client: TestClient) -> None:
    current = client.get(
        f"/api/v1/agents/{KALMAN_ID}/projects/P-5001/memory",
        headers=ADMIN_HEADERS,
    ).json()
    updated = client.patch(
        f"/api/v1/agents/{KALMAN_ID}/projects/P-5001/memory",
        headers=ADMIN_HEADERS,
        json={
            "expected_version": current["version"],
            "content": {"nextAction": "review-milestone"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == current["version"] + 1
    conflict = client.patch(
        f"/api/v1/agents/{KALMAN_ID}/projects/P-5001/memory",
        headers=ADMIN_HEADERS,
        json={"expected_version": current["version"], "content": {}},
    )
    assert conflict.status_code == 409

    queue = client.get(
        f"/api/v1/agents/{KALMAN_ID}/workqueue?project_id=P-5001",
        headers=ADMIN_HEADERS,
    )
    assert queue.status_code == 200
    assert queue.json()


def test_not_found_and_scope_failures(client: TestClient) -> None:
    assert (
        client.get(
            "/api/v1/agents/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            headers=ADMIN_HEADERS,
        ).status_code
        == 404
    )
    assert client.get("/api/v1/projects/UNKNOWN/context", headers=ADMIN_HEADERS).status_code == 404
    assert client.get("/api/v1/agents").status_code == 401


def test_project_scope_is_enforced(client: TestClient) -> None:
    headers = {
        "X-Test-Subject": "test:limited-user",
        "X-Test-Scopes": "digital-pm:read",
        "X-Test-Projects": "P-5002",
    }
    assert client.get("/api/v1/projects/P-5002/context", headers=headers).status_code == 200
    assert client.get("/api/v1/projects/P-5001/context", headers=headers).status_code == 403


def test_health(client: TestClient) -> None:
    assert client.get("/health/live").json()["version"] == "0.2.0"
    assert client.get("/health/ready").status_code == 200
