from __future__ import annotations

from sqlalchemy import select

from app.models import TaskRecord, WorkspaceDocument


def create_project_with_task(client):
    response = client.post("/api/events", json={
        "event_id": "EVT-WS-001",
        "dedupe_key": "WS-TASK-001",
        "project_id": "IMP-WS-001",
        "source_module": "procurement",
        "event_type": "DELIVERY_NOTE_MISSING",
        "object_type": "Delivery",
        "object_id": "DEL-WS-001",
        "financial_impact_huf": "1250000",
        "payload": {"project_name": "Workspace tesztprojekt", "customer_name": "Teszt Ügyfél"},
    })
    assert response.status_code == 200


def test_workspace_action_center_and_task_update(logged_in_client, db):
    create_project_with_task(logged_in_client)
    home = logged_in_client.get("/")
    assert home.status_code == 200
    assert "Saját feladataim" in home.text
    page = logged_in_client.get("/tasks?project_id=IMP-WS-001")
    assert page.status_code == 200
    assert "szállítólevél" in page.text.lower()
    task = db.scalar(select(TaskRecord).where(TaskRecord.project_id == "IMP-WS-001"))
    update = logged_in_client.post(f"/tasks/{task.task_id}/update", data={"status": "done", "project_id": "IMP-WS-001"}, follow_redirects=False)
    assert update.status_code == 303
    db.expire_all()
    assert db.scalar(select(TaskRecord).where(TaskRecord.task_id == task.task_id)).status == "done"


def test_document_library_project_360_and_search(logged_in_client, db):
    create_project_with_task(logged_in_client)
    created = logged_in_client.post("/api/documents", json={
        "title": "Workspace teszt szállítólevél",
        "project_id": "IMP-WS-001",
        "category": "delivery_note",
        "source_url": "https://drive.google.com/test",
        "extracted_summary": "Teszt dokumentum ellenőrzési kivonata.",
    })
    assert created.status_code == 200
    document = db.scalar(select(WorkspaceDocument).where(WorkspaceDocument.project_id == "IMP-WS-001"))
    assert document is not None
    library = logged_in_client.get("/documents?project_id=IMP-WS-001")
    assert "Workspace teszt szállítólevél" in library.text
    project = logged_in_client.get("/projects/IMP-WS-001")
    assert project.status_code == 200
    assert "Projekt 360" in project.text
    assert "Workspace teszt szállítólevél" in project.text
    search = logged_in_client.get("/search?q=szállítólevél")
    assert search.status_code == 200
    assert "Workspace teszt szállítólevél" in search.text


def test_workspace_api_search_returns_grouped_results(client):
    create_project_with_task(client)
    response = client.get("/api/search?q=Workspace")
    assert response.status_code == 200
    data = response.json()
    assert data["projects"]
    assert set(data) == {"projects", "tasks", "events", "documents", "records"}


def test_document_form_accepts_onedrive_reference(logged_in_client, db):
    response = logged_in_client.post("/documents", data={
        "title": "OneDrive tervcsomag",
        "category": "plan",
        "source_system": "onedrive",
        "source_url": "https://imperialholding.sharepoint.com/example",
    }, follow_redirects=False)
    assert response.status_code == 303
    document = db.scalar(select(WorkspaceDocument).where(WorkspaceDocument.title == "OneDrive tervcsomag"))
    assert document is not None
    assert document.source_system == "onedrive"
