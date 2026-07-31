from sqlalchemy import func, select

from app.models import (
    CommunicationMessage,
    CommunicationParticipant,
    CommunicationThread,
    InternalNotification,
    TaskRecord,
    User,
)


PASSWORD = "Imperial2026!"


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


def user_for_role(db, role: str) -> User:
    email = "owner@imperial.local" if role == "owner" else f"{role}@imperial.local"
    return db.scalar(select(User).where(User.email == email))


def test_direct_messages_notifications_read_state_and_participant_security(client, db):
    manager = user_for_role(db, "project-manager")
    sales = user_for_role(db, "sales")
    finance = user_for_role(db, "finance")
    login(client, "project-manager")
    created = client.post(
        "/communications/threads",
        data={
            "thread_type": "direct",
            "subject": "Szerződéses egyeztetés",
            "participant_user_ids": str(sales.id),
            "initial_message": "Kérlek, ellenőrizd az ügyfél következő szerződéses lépését.",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    thread = db.scalar(
        select(CommunicationThread).where(
            CommunicationThread.subject == "Szerződéses egyeztetés"
        )
    )
    assert thread.thread_type == "direct"
    assert db.scalar(
        select(func.count()).select_from(CommunicationParticipant).where(
            CommunicationParticipant.thread_id == thread.thread_id
        )
    ) == 2
    assert db.scalar(
        select(func.count()).select_from(CommunicationMessage).where(
            CommunicationMessage.thread_id == thread.thread_id
        )
    ) == 1
    sales_notification = db.scalar(
        select(InternalNotification).where(
            InternalNotification.user_id == sales.id,
            InternalNotification.thread_id == thread.thread_id,
        )
    )
    assert sales_notification is not None
    assert sales_notification.read_at is None

    logout(client)
    login(client, "sales")
    assert client.get("/api/communications/unread").json()["unread"] == 1
    opened = client.get(f"/communications?thread_id={thread.thread_id}")
    assert opened.status_code == 200
    assert "ellenőrizd az ügyfél" in opened.text
    db.refresh(sales_notification)
    assert sales_notification.read_at is not None
    assert client.get("/api/communications/unread").json()["unread"] == 0

    reply = client.post(
        f"/communications/{thread.thread_id}/messages",
        data={"body": "Ellenőriztem, a következő lépés az ajánlat ügyféllel történő jóváhagyása."},
        follow_redirects=False,
    )
    assert reply.status_code == 303, reply.text
    manager_notification = db.scalar(
        select(InternalNotification).where(
            InternalNotification.user_id == manager.id,
            InternalNotification.thread_id == thread.thread_id,
            InternalNotification.read_at.is_(None),
        )
    )
    assert manager_notification is not None

    duplicate = client.post(
        "/communications/threads",
        data={
            "thread_type": "direct",
            "subject": "Másik tárgy nem hozhat létre párhuzamos direkt szálat",
            "participant_user_ids": str(manager.id),
            "initial_message": "Ezt az üzenetet a meglévő közvetlen beszélgetésbe kell fűzni.",
        },
        follow_redirects=False,
    )
    assert duplicate.status_code == 303
    assert thread.thread_id in duplicate.headers["location"]
    assert db.scalar(
        select(func.count()).select_from(CommunicationThread).where(
            CommunicationThread.thread_type == "direct"
        )
    ) == 1

    logout(client)
    login(client, "finance")
    denied = client.get(f"/communications?thread_id={thread.thread_id}")
    assert denied.status_code == 403


def test_project_and_task_context_threads_and_notification_bulk_read(client, db):
    project_id = "PRJ-COMMS-CONTEXT-001"
    client.post(
        "/api/events",
        json={
            "event_id": "EVT-COMMS-CONTEXT-001",
            "dedupe_key": "COMMS-CONTEXT-001",
            "project_id": project_id,
            "source_module": "crm",
            "event_type": "PROJECT_CREATED",
            "payload": {"project_name": "Kommunikációs kontextusteszt"},
        },
    )
    manager = user_for_role(db, "project-manager")
    technical = user_for_role(db, "technical-prep")
    task = TaskRecord(
        task_id="TASK-COMMS-CONTEXT-001",
        project_id=project_id,
        title="Műszaki kérdés lezárása",
        assignee=technical.email,
        priority="high",
        status="open",
    )
    db.add(task)
    db.commit()

    login(client, "project-manager")
    project_thread = client.post(
        "/communications/threads",
        data={
            "thread_type": "project",
            "subject": "Projekt státuszmegjegyzések",
            "participant_user_ids": str(technical.id),
            "project_id": project_id,
            "initial_message": "A projekt aktuális műszaki akadályait ezen a szálon egyeztetjük.",
        },
        follow_redirects=False,
    )
    assert project_thread.status_code == 303, project_thread.text
    task_thread = client.post(
        "/communications/threads",
        data={
            "thread_type": "task",
            "subject": "Feladat részletes egyeztetése",
            "participant_user_ids": str(technical.id),
            "task_id": task.task_id,
            "initial_message": "Kérlek, rögzítsd itt a feladat megoldásához szükséges műszaki bizonyítékot.",
        },
        follow_redirects=False,
    )
    assert task_thread.status_code == 303, task_thread.text
    task_row = db.scalar(
        select(CommunicationThread).where(CommunicationThread.task_id == task.task_id)
    )
    assert task_row.project_id == project_id

    logout(client)
    login(client, "technical-prep")
    assert client.get("/api/communications/unread").json()["unread"] == 2
    marked = client.post(
        "/communications/notifications/read-all",
        follow_redirects=False,
    )
    assert marked.status_code == 303
    assert client.get("/api/communications/unread").json()["unread"] == 0


def test_external_customer_cannot_access_internal_communications(client):
    login(client, "customer")
    assert client.get("/communications").status_code == 403
    assert client.get("/api/communications/unread").status_code == 403
