from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    CommunicationMessage,
    CommunicationParticipant,
    CommunicationThread,
    InternalNotification,
    ProjectRegistry,
    TaskRecord,
    User,
)


THREAD_TYPES = {"direct", "general", "project", "task"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


def _participant(db: Session, thread_id: str, user_id: int) -> CommunicationParticipant:
    row = db.scalar(
        select(CommunicationParticipant).where(
            CommunicationParticipant.thread_id == thread_id,
            CommunicationParticipant.user_id == user_id,
        )
    )
    if not row:
        raise PermissionError("A felhasználó nem résztvevője ennek a beszélgetésnek.")
    return row


def _notify(
    db: Session,
    *,
    user_id: int,
    thread_id: str,
    title: str,
    body: str,
    actor_email: str,
) -> None:
    db.add(
        InternalNotification(
            notification_id=_id("NTF"),
            user_id=user_id,
            thread_id=thread_id,
            category="message",
            title=title[:255],
            body=body[:1000],
            target_url=f"/communications?thread_id={thread_id}",
            actor_email=actor_email,
        )
    )


def _existing_direct_thread(db: Session, user_ids: set[int]) -> CommunicationThread | None:
    candidate_ids = list(
        db.scalars(
            select(CommunicationParticipant.thread_id).where(
                CommunicationParticipant.user_id.in_(user_ids)
            )
        )
    )
    for thread_id in set(candidate_ids):
        thread = db.get(CommunicationThread, thread_id)
        if not thread or thread.thread_type != "direct":
            continue
        participants = set(
            db.scalars(
                select(CommunicationParticipant.user_id).where(
                    CommunicationParticipant.thread_id == thread_id
                )
            )
        )
        if participants == user_ids:
            return thread
    return None


def create_thread(
    db: Session,
    *,
    creator: User,
    subject: str,
    thread_type: str,
    participant_user_ids: list[int],
    project_id: str | None = None,
    task_id: str | None = None,
    initial_message: str | None = None,
) -> CommunicationThread:
    normalized_type = thread_type.strip().lower()
    if normalized_type not in THREAD_TYPES:
        raise ValueError("Ismeretlen beszélgetéstípus.")
    participant_ids = {creator.id, *participant_user_ids}
    if len(participant_ids) < 2:
        raise ValueError("Legalább egy címzettet ki kell választani.")
    users = list(
        db.scalars(select(User).where(User.id.in_(participant_ids), User.active.is_(True)))
    )
    if {user.id for user in users} != participant_ids:
        raise ValueError("Legalább egy címzett nem létezik vagy inaktív.")
    if normalized_type == "direct" and len(participant_ids) != 2:
        raise ValueError("Közvetlen beszélgetésnek pontosan két résztvevője lehet.")
    clean_project_id = (project_id or "").strip() or None
    clean_task_id = (task_id or "").strip() or None
    if normalized_type == "project":
        if not clean_project_id or not db.scalar(
            select(ProjectRegistry).where(ProjectRegistry.project_id == clean_project_id)
        ):
            raise ValueError("Projektbeszélgetéshez létező projekt szükséges.")
    elif normalized_type == "task":
        task = db.scalar(select(TaskRecord).where(TaskRecord.task_id == clean_task_id))
        if not task:
            raise ValueError("Feladatbeszélgetéshez létező feladat szükséges.")
        if clean_project_id and clean_project_id != task.project_id:
            raise ValueError("A feladat és a projekt hivatkozása eltér.")
        clean_project_id = task.project_id
    elif clean_project_id or clean_task_id:
        raise ValueError("Projekt- vagy feladathivatkozás csak a megfelelő beszélgetéstípusnál adható meg.")
    if normalized_type == "direct":
        existing = _existing_direct_thread(db, participant_ids)
        if existing:
            if initial_message and initial_message.strip():
                post_message(db, thread_id=existing.thread_id, sender=creator, body=initial_message)
            return existing
    clean_subject = subject.strip()
    if len(clean_subject) < 3 or len(clean_subject) > 255:
        raise ValueError("A beszélgetés tárgya 3 és 255 karakter közötti legyen.")
    thread = CommunicationThread(
        thread_id=_id("CHAT"),
        subject=clean_subject,
        thread_type=normalized_type,
        project_id=clean_project_id,
        task_id=clean_task_id,
        created_by_user_id=creator.id,
    )
    db.add(thread)
    db.flush()
    for user_id in sorted(participant_ids):
        db.add(
            CommunicationParticipant(
                thread_id=thread.thread_id,
                user_id=user_id,
                last_read_at=utcnow() if user_id == creator.id else None,
            )
        )
    db.flush()
    if initial_message and initial_message.strip():
        _add_message(db, thread=thread, sender=creator, body=initial_message)
    else:
        for user_id in participant_ids - {creator.id}:
            _notify(
                db,
                user_id=user_id,
                thread_id=thread.thread_id,
                title=f"Új beszélgetés: {thread.subject}",
                body=f"{creator.name} meghívta a beszélgetésbe.",
                actor_email=creator.email,
            )
    audit(
        db,
        actor=creator.email,
        action="communication_thread_created",
        entity_type="communication_thread",
        entity_id=thread.thread_id,
        after={
            "subject": thread.subject,
            "thread_type": thread.thread_type,
            "project_id": thread.project_id,
            "task_id": thread.task_id,
            "participant_user_ids": sorted(participant_ids),
        },
    )
    db.commit()
    db.refresh(thread)
    return thread


def _add_message(
    db: Session,
    *,
    thread: CommunicationThread,
    sender: User,
    body: str,
) -> CommunicationMessage:
    clean_body = body.strip()
    if not clean_body or len(clean_body) > 5000:
        raise ValueError("Az üzenet 1 és 5000 karakter közötti legyen.")
    message = CommunicationMessage(
        message_id=_id("MSG"),
        thread_id=thread.thread_id,
        sender_user_id=sender.id,
        body=clean_body,
    )
    db.add(message)
    thread.updated_at = utcnow()
    participants = list(
        db.scalars(
            select(CommunicationParticipant).where(
                CommunicationParticipant.thread_id == thread.thread_id
            )
        )
    )
    for participant in participants:
        if participant.user_id == sender.id or participant.muted:
            continue
        _notify(
            db,
            user_id=participant.user_id,
            thread_id=thread.thread_id,
            title=f"Új üzenet: {thread.subject}",
            body=f"{sender.name}: {clean_body}",
            actor_email=sender.email,
        )
    return message


def post_message(
    db: Session,
    *,
    thread_id: str,
    sender: User,
    body: str,
) -> CommunicationMessage:
    _participant(db, thread_id, sender.id)
    thread = db.get(CommunicationThread, thread_id)
    if not thread:
        raise KeyError(thread_id)
    message = _add_message(db, thread=thread, sender=sender, body=body)
    audit(
        db,
        actor=sender.email,
        action="communication_message_sent",
        entity_type="communication_message",
        entity_id=message.message_id,
        after={"thread_id": thread_id, "body_length": len(message.body)},
    )
    db.commit()
    db.refresh(message)
    return message


def list_threads(db: Session, user: User) -> list[dict]:
    participant_rows = list(
        db.scalars(
            select(CommunicationParticipant).where(
                CommunicationParticipant.user_id == user.id
            )
        )
    )
    result: list[dict] = []
    for participant in participant_rows:
        thread = db.get(CommunicationThread, participant.thread_id)
        if not thread:
            continue
        latest = db.scalar(
            select(CommunicationMessage)
            .where(CommunicationMessage.thread_id == thread.thread_id)
            .order_by(CommunicationMessage.created_at.desc())
        )
        unread_query = select(func.count()).select_from(CommunicationMessage).where(
            CommunicationMessage.thread_id == thread.thread_id,
            CommunicationMessage.sender_user_id != user.id,
        )
        if participant.last_read_at:
            unread_query = unread_query.where(
                CommunicationMessage.created_at > participant.last_read_at
            )
        participant_ids = list(
            db.scalars(
                select(CommunicationParticipant.user_id).where(
                    CommunicationParticipant.thread_id == thread.thread_id
                )
            )
        )
        people = list(db.scalars(select(User).where(User.id.in_(participant_ids))))
        result.append(
            {
                "row": thread,
                "latest": latest,
                "unread": db.scalar(unread_query) or 0,
                "participants": people,
            }
        )
    return sorted(result, key=lambda item: item["row"].updated_at, reverse=True)


def get_thread(db: Session, *, thread_id: str, user: User) -> dict:
    participant = _participant(db, thread_id, user.id)
    thread = db.get(CommunicationThread, thread_id)
    if not thread:
        raise KeyError(thread_id)
    messages = list(
        db.scalars(
            select(CommunicationMessage)
            .where(CommunicationMessage.thread_id == thread_id)
            .order_by(CommunicationMessage.created_at)
        )
    )
    sender_ids = {message.sender_user_id for message in messages}
    senders = {
        sender.id: sender
        for sender in db.scalars(select(User).where(User.id.in_(sender_ids)))
    } if sender_ids else {}
    participant_ids = list(
        db.scalars(
            select(CommunicationParticipant.user_id).where(
                CommunicationParticipant.thread_id == thread_id
            )
        )
    )
    people = list(db.scalars(select(User).where(User.id.in_(participant_ids))))
    now = utcnow()
    participant.last_read_at = now
    for notification in db.scalars(
        select(InternalNotification).where(
            InternalNotification.user_id == user.id,
            InternalNotification.thread_id == thread_id,
            InternalNotification.read_at.is_(None),
        )
    ):
        notification.read_at = now
    db.commit()
    return {
        "row": thread,
        "messages": [
            {"row": message, "sender": senders.get(message.sender_user_id)}
            for message in messages
        ],
        "participants": people,
    }


def list_notifications(db: Session, user: User, *, limit: int = 100) -> list[InternalNotification]:
    return list(
        db.scalars(
            select(InternalNotification)
            .where(InternalNotification.user_id == user.id)
            .order_by(InternalNotification.created_at.desc())
            .limit(limit)
        )
    )


def unread_notification_count(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count()).select_from(InternalNotification).where(
            InternalNotification.user_id == user.id,
            InternalNotification.read_at.is_(None),
        )
    ) or 0


def mark_notifications_read(db: Session, user: User) -> None:
    now = utcnow()
    for row in db.scalars(
        select(InternalNotification).where(
            InternalNotification.user_id == user.id,
            InternalNotification.read_at.is_(None),
        )
    ):
        row.read_at = now
    audit(
        db,
        actor=user.email,
        action="internal_notifications_marked_read",
        entity_type="internal_notification",
        after={"read_at": now.isoformat()},
    )
    db.commit()
