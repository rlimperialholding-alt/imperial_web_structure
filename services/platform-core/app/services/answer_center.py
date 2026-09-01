from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    AnswerCitation,
    AnswerKnowledgeExcerpt,
    AnswerKnowledgeSource,
    AnswerPublication,
    AnswerQuestion,
    AnswerReview,
    AnswerVersion,
    OutboxMessage,
    TaskRecord,
)
from ..schemas import (
    AnswerCitationIn,
    AnswerDraftIn,
    AnswerKnowledgeExcerptIn,
    AnswerKnowledgeSourceIn,
    AnswerPublicationIn,
    AnswerQuestionIn,
    AnswerReviewIn,
)


INTERNAL_ROLES = {
    "owner", "managing-director", "sales", "finance", "project-manager",
    "marketing", "copywriter", "language-editor", "creative-director", "technical-prep",
    "legal", "platform-admin",
}
SOURCE_ADMIN_ROLES = {"owner", "managing-director", "platform-admin"}
PUBLISH_ROLES = {"owner", "managing-director", "platform-admin"}
DOMAIN_REVIEWER = {
    "finance": "finance",
    "financial": "finance",
    "technical": "project-manager",
    "planning": "project-manager",
    "process": "project-manager",
    "sales": "sales",
    "marketing": "marketing",
    "content": "marketing",
    "contract": "legal",
    "legal": "legal",
    "corporate": "managing-director",
}
VALID_CERTAINTY = {"high", "medium", "low", "unknown"}
VALID_VISIBILITY = {"internal", "customer", "project_customer"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def _valid_sha(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError("Érvényes SHA-256 lenyomat szükséges.")
    return normalized


def _source(db: Session, source_id: str) -> AnswerKnowledgeSource:
    row = db.scalar(select(AnswerKnowledgeSource).where(AnswerKnowledgeSource.source_id == source_id))
    if not row:
        raise KeyError(source_id)
    return row


def _excerpt(db: Session, excerpt_id: str) -> AnswerKnowledgeExcerpt:
    row = db.scalar(select(AnswerKnowledgeExcerpt).where(AnswerKnowledgeExcerpt.excerpt_id == excerpt_id))
    if not row:
        raise KeyError(excerpt_id)
    return row


def _question(db: Session, question_id: str) -> AnswerQuestion:
    row = db.scalar(select(AnswerQuestion).where(AnswerQuestion.question_id == question_id))
    if not row:
        raise KeyError(question_id)
    return row


def _version(db: Session, answer_version_id: str) -> AnswerVersion:
    row = db.scalar(select(AnswerVersion).where(AnswerVersion.answer_version_id == answer_version_id))
    if not row:
        raise KeyError(answer_version_id)
    return row


def _roles(source: AnswerKnowledgeSource) -> set[str]:
    try:
        return set(json.loads(source.allowed_roles_json or "[]"))
    except (TypeError, ValueError):
        return set()


def _source_is_current(source: AnswerKnowledgeSource) -> bool:
    now = utcnow()
    return (
        source.status == "approved"
        and (source.valid_from is None or source.valid_from <= now)
        and (source.valid_until is None or source.valid_until >= now)
    )


def _can_read_source(source: AnswerKnowledgeSource, role: str, project_id: str | None) -> bool:
    allowed = _roles(source)
    if role == "customer":
        return (
            source.visibility in {"customer", "project_customer"}
            and (source.project_id is None or source.project_id == project_id)
        )
    return (
        (not allowed or role in allowed or role in SOURCE_ADMIN_ROLES)
        and (source.project_id is None or source.project_id == project_id)
    )


def _queue_task(db: Session, *, question: AnswerQuestion, version: AnswerVersion, reason: str) -> TaskRecord:
    existing = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == version.answer_version_id, TaskRecord.status == "open"))
    if existing:
        return existing
    task = TaskRecord(
        task_id=_id("TASK-ANS"),
        project_id=question.project_id or "GLOBAL",
        source_event_id=version.answer_version_id,
        title=f"Szakértői válaszfelülvizsgálat: {question.question_id}",
        description=reason,
        assignee=question.assigned_role,
        priority="high" if version.source_conflict else "normal",
        status="open",
        executive_relevance=version.source_conflict or question.domain in {"legal", "contract", "finance", "financial"},
    )
    db.add(task)
    return task


def register_source(db: Session, data: AnswerKnowledgeSourceIn, actor: str, actor_role: str) -> AnswerKnowledgeSource:
    if actor_role not in INTERNAL_ROLES:
        raise PermissionError("Tudásforrás regisztrálására nincs jogosultság.")
    if data.visibility not in VALID_VISIBILITY:
        raise ValueError("Ismeretlen forrásláthatóság.")
    if data.valid_from and data.valid_until and data.valid_until <= data.valid_from:
        raise ValueError("A forrás érvényességi időszaka hibás.")
    allowed_roles = sorted(set(data.allowed_roles))
    if any(role not in INTERNAL_ROLES | {"customer"} for role in allowed_roles):
        raise ValueError("A forrás ismeretlen szerepkört tartalmaz.")
    row = AnswerKnowledgeSource(
        source_id=_id("KSRC"), title=data.title.strip(), source_type=data.source_type.strip().lower(),
        canonical_ref=data.canonical_ref.strip(), version=data.version.strip(), domain=data.domain.strip().lower(),
        visibility=data.visibility, allowed_roles_json=_json(allowed_roles), project_id=data.project_id,
        content_sha256=_valid_sha(data.content_sha256), status="draft", valid_from=data.valid_from,
        valid_until=data.valid_until, owner_role=data.owner_role, created_by=actor,
    )
    db.add(row)
    audit(db, actor=actor, action="answer.source.register", entity_type="answer_knowledge_source", entity_id=row.source_id, after={"canonical_ref": row.canonical_ref, "version": row.version, "content_sha256": row.content_sha256})
    db.commit(); db.refresh(row); return row


def add_excerpt(db: Session, source_id: str, data: AnswerKnowledgeExcerptIn, actor: str, actor_role: str) -> AnswerKnowledgeExcerpt:
    source = _source(db, source_id)
    if actor_role not in SOURCE_ADMIN_ROLES and actor != source.created_by:
        raise PermissionError("A forrás kivonatolására nincs jogosultság.")
    if source.status != "draft":
        raise ValueError("Kivonat csak jóváhagyás előtt rögzíthető; változáshoz új forrásverzió kell.")
    row = AnswerKnowledgeExcerpt(
        excerpt_id=_id("KEX"), source_id=source_id, locator=data.locator.strip(),
        excerpt_text=data.excerpt_text.strip(), excerpt_sha256=_hash_text(data.excerpt_text), created_by=actor,
    )
    db.add(row)
    audit(db, actor=actor, action="answer.source.excerpt.add", entity_type="answer_knowledge_excerpt", entity_id=row.excerpt_id, after={"source_id": source_id, "locator": row.locator, "excerpt_sha256": row.excerpt_sha256})
    db.commit(); db.refresh(row); return row


def approve_source(db: Session, source_id: str, actor: str, actor_role: str) -> AnswerKnowledgeSource:
    source = _source(db, source_id)
    if actor == source.created_by:
        raise PermissionError("A forrás készítője nem hagyhatja jóvá a saját forrását.")
    if actor_role not in SOURCE_ADMIN_ROLES and actor_role != source.owner_role:
        raise PermissionError("A forrás jóváhagyásához tulajdonosi vagy tárgyköri jogosultság szükséges.")
    if source.status != "draft":
        raise ValueError("Csak draft forrás hagyható jóvá.")
    if not db.scalar(select(AnswerKnowledgeExcerpt).where(AnswerKnowledgeExcerpt.source_id == source_id)):
        raise ValueError("Legalább egy pontos, helymegjelöléssel ellátott forráskivonat szükséges.")
    source.status = "approved"; source.approved_by = actor; source.approved_at = utcnow()
    audit(db, actor=actor, action="answer.source.approve", entity_type="answer_knowledge_source", entity_id=source_id, after={"status": source.status, "approved_by": actor})
    db.commit(); db.refresh(source); return source


def create_question(db: Session, data: AnswerQuestionIn, actor: str, actor_role: str) -> AnswerQuestion:
    if actor_role not in INTERNAL_ROLES and actor_role != "customer":
        raise PermissionError("Kérdés rögzítésére nincs jogosultság.")
    if data.channel == "my-imperial" and actor_role == "customer" and (not data.project_id or not data.customer_reference):
        raise ValueError("Ügyfélkérdéshez projekt- és ügyfélhivatkozás szükséges.")
    if data.channel not in {"internal", "my-imperial", "crm"}:
        raise ValueError("Ismeretlen kérdéscsatorna.")
    domain = data.domain.strip().lower()
    row = AnswerQuestion(
        question_id=_id("ANSQ"), question_text=data.question_text.strip(), domain=domain,
        channel=data.channel, project_id=data.project_id, customer_reference=data.customer_reference,
        asked_by=actor, asker_role=actor_role, status="open",
        assigned_role=DOMAIN_REVIEWER.get(domain, "managing-director"),
    )
    db.add(row)
    audit(db, actor=actor, action="answer.question.create", entity_type="answer_question", entity_id=row.question_id, after={"domain": domain, "channel": row.channel, "project_id": row.project_id})
    db.commit(); db.refresh(row); return row


def create_draft(db: Session, question_id: str, data: AnswerDraftIn, actor: str, actor_role: str) -> AnswerVersion:
    question = _question(db, question_id)
    if actor_role not in INTERNAL_ROLES:
        raise PermissionError("Választervezet készítésére nincs jogosultság.")
    if data.certainty not in VALID_CERTAINTY:
        raise ValueError("Ismeretlen bizonyossági szint.")
    if question.status == "resolved":
        raise ValueError("Lezárt kérdéshez új kérdésverzió szükséges.")
    previous = list(db.scalars(select(AnswerVersion).where(AnswerVersion.question_id == question_id)).all())
    for item in previous:
        if item.status not in {"published", "retracted", "superseded"}:
            item.status = "superseded"; item.superseded_at = utcnow()
    row = AnswerVersion(
        answer_version_id=_id("ANSV"), question_id=question_id, version=len(previous) + 1,
        answer_text=data.answer_text.strip(), answer_sha256=_hash_text(data.answer_text),
        certainty=data.certainty, source_conflict=data.source_conflict, status="draft", created_by=actor,
    )
    db.add(row); question.status = "drafting"
    audit(db, actor=actor, action="answer.version.create", entity_type="answer_version", entity_id=row.answer_version_id, after={"question_id": question_id, "version": row.version, "certainty": row.certainty, "source_conflict": row.source_conflict})
    db.commit(); db.refresh(row); return row


def add_citation(db: Session, answer_version_id: str, data: AnswerCitationIn, actor: str, actor_role: str) -> AnswerCitation:
    version = _version(db, answer_version_id)
    question = _question(db, version.question_id)
    if actor_role not in INTERNAL_ROLES or version.status != "draft":
        raise PermissionError("Csak szerkeszthető választervezethez adható hivatkozás.")
    if data.claim_text.strip() not in version.answer_text:
        raise ValueError("A hivatkozott állításnak szó szerint szerepelnie kell a válaszban.")
    source = _source(db, data.source_id); excerpt = _excerpt(db, data.excerpt_id)
    if excerpt.source_id != source.source_id:
        raise ValueError("A kivonat nem a kijelölt forráshoz tartozik.")
    if not _source_is_current(source) or not _can_read_source(source, actor_role, question.project_id):
        raise ValueError("A forrás nem jóváhagyott, lejárt vagy a kérdéshez nem hozzáférhető.")
    if _hash_text(excerpt.excerpt_text) != excerpt.excerpt_sha256:
        raise ValueError("A forráskivonat integritás-ellenőrzése sikertelen.")
    row = AnswerCitation(
        citation_id=_id("CITE"), answer_version_id=answer_version_id, claim_key=data.claim_key,
        claim_text=data.claim_text.strip(), source_id=source.source_id, source_version=source.version,
        source_content_sha256=source.content_sha256, excerpt_id=excerpt.excerpt_id,
        excerpt_sha256=excerpt.excerpt_sha256, created_by=actor,
    )
    db.add(row)
    audit(db, actor=actor, action="answer.citation.add", entity_type="answer_citation", entity_id=row.citation_id, after={"answer_version_id": answer_version_id, "source_id": source.source_id, "source_version": source.version, "claim_key": row.claim_key})
    db.commit(); db.refresh(row); return row


def _validated_citations(db: Session, version: AnswerVersion, question: AnswerQuestion) -> list[AnswerCitation]:
    citations = list(db.scalars(select(AnswerCitation).where(AnswerCitation.answer_version_id == version.answer_version_id)).all())
    if not citations:
        raise ValueError("Forráshivatkozás nélküli válasz nem küldhető felülvizsgálatra.")
    paragraphs = [item.strip() for item in version.answer_text.split("\n") if item.strip()]
    if any(not any(citation.claim_text in paragraph for citation in citations) for paragraph in paragraphs):
        raise ValueError("Minden válaszbekezdéshez legalább egy konkrét, visszakereshető állításhivatkozás szükséges.")
    for citation in citations:
        source = _source(db, citation.source_id); excerpt = _excerpt(db, citation.excerpt_id)
        if (
            not _source_is_current(source)
            or not _can_read_source(source, question.asker_role, question.project_id)
            or source.version != citation.source_version
            or source.content_sha256 != citation.source_content_sha256
            or excerpt.source_id != source.source_id
            or excerpt.excerpt_sha256 != citation.excerpt_sha256
            or _hash_text(excerpt.excerpt_text) != citation.excerpt_sha256
        ):
            raise ValueError("A hivatkozás forrásverziója, jogosultsága vagy integritása megváltozott.")
    return citations


def submit_for_review(db: Session, answer_version_id: str, actor: str, actor_role: str) -> AnswerVersion:
    version = _version(db, answer_version_id); question = _question(db, version.question_id)
    if actor_role not in INTERNAL_ROLES or version.status != "draft":
        raise PermissionError("A válasz nem küldhető felülvizsgálatra.")
    _validated_citations(db, version, question)
    if version.source_conflict or version.certainty in {"low", "unknown"}:
        version.status = "escalated"; question.status = "expert_escalation"
        reason = "A források ütköznek; emberi döntés szükséges." if version.source_conflict else "A válasz bizonyossága nem elegendő; szakértői kiegészítés szükséges."
        _queue_task(db, question=question, version=version, reason=reason)
    else:
        version.status = "human_review"; question.status = "human_review"
    audit(db, actor=actor, action="answer.version.submit", entity_type="answer_version", entity_id=answer_version_id, after={"status": version.status, "assigned_role": question.assigned_role})
    db.commit(); db.refresh(version); return version


def review_answer(db: Session, answer_version_id: str, data: AnswerReviewIn, actor: str, actor_role: str) -> AnswerReview:
    version = _version(db, answer_version_id); question = _question(db, version.question_id)
    required = question.assigned_role
    supplemental_customer_review = (
        actor_role == "managing-director"
        and question.channel == "my-imperial"
        and version.status == "approved"
    )
    if actor_role != required and not (required == "managing-director" and actor_role == "owner") and not supplemental_customer_review:
        raise PermissionError(f"A tárgyköri felülvizsgálat szükséges szerepköre: {required}.")
    if actor == version.created_by:
        raise PermissionError("A válasz készítője nem hagyhatja jóvá saját válaszát.")
    if version.status not in {"human_review", "approved"}:
        raise ValueError("Csak megfelelő bizonyosságú, felülvizsgálatra beküldött válasz bírálható.")
    if data.decision not in {"approved", "rejected"}:
        raise ValueError("A review döntése approved vagy rejected lehet.")
    if db.scalar(select(AnswerReview).where(AnswerReview.answer_version_id == answer_version_id, AnswerReview.reviewer_role == actor_role)):
        raise ValueError("Ez a szerepkör már rögzített review-döntést.")
    row = AnswerReview(review_id=_id("ANSR"), answer_version_id=answer_version_id, reviewer_role=actor_role, decision=data.decision, note=data.note.strip(), reviewer=actor)
    db.add(row)
    if data.decision == "rejected":
        version.status = "rejected"; question.status = "needs_revision"
    else:
        version.status = "approved"; question.status = "approved"
    audit(db, actor=actor, action="answer.review.record", entity_type="answer_review", entity_id=row.review_id, after={"answer_version_id": answer_version_id, "role": actor_role, "decision": data.decision})
    db.commit(); db.refresh(row); return row


def _review_roles(db: Session, answer_version_id: str) -> set[str]:
    return set(db.scalars(select(AnswerReview.reviewer_role).where(AnswerReview.answer_version_id == answer_version_id, AnswerReview.decision == "approved")).all())


def publish_answer(db: Session, answer_version_id: str, data: AnswerPublicationIn, actor: str, actor_role: str) -> AnswerPublication:
    if actor_role not in PUBLISH_ROLES:
        raise PermissionError("Válasz publikálására nincs jogosultság.")
    version = _version(db, answer_version_id); question = _question(db, version.question_id)
    if version.status != "approved" or version.certainty not in {"high", "medium"} or version.source_conflict:
        raise ValueError("Csak jóváhagyott, megfelelő bizonyosságú, konfliktusmentes válasz publikálható.")
    citations = _validated_citations(db, version, question)
    if data.audience not in {"internal", "customer"}:
        raise ValueError("Ismeretlen közönség.")
    if data.audience == "customer":
        if data.destination != "my-imperial" or not data.project_id:
            raise ValueError("Ügyfélválasz kizárólag projekthez kötve, a MyImperial felületre publikálható.")
        if question.project_id and question.project_id != data.project_id:
            raise ValueError("A publikáció projektje eltér a kérdés projektjétől.")
        sources = [_source(db, citation.source_id) for citation in citations]
        if any(source.visibility not in {"customer", "project_customer"} for source in sources):
            raise ValueError("Belső forrásból származó válasz nem publikálható ügyfélnek.")
        if any(source.project_id and source.project_id != data.project_id for source in sources):
            raise ValueError("A projektforrás nem a címzett ügyfélprojektjéhez tartozik.")
        required_roles = {question.assigned_role, "managing-director"}
        if not required_roles.issubset(_review_roles(db, answer_version_id)):
            raise ValueError("Ügyfélpublikáláshoz tárgyköri és ügyvezetői jóváhagyás szükséges.")
    elif data.destination not in {"answer-center", "crm", "content-factory"}:
        raise ValueError("Ismeretlen belső publikációs cél.")
    payload = {
        "event": "ANSWER_PUBLISHED", "answer_version_id": answer_version_id,
        "question_id": question.question_id, "project_id": data.project_id or question.project_id,
        "audience": data.audience, "destination": data.destination, "answer_sha256": version.answer_sha256,
        "citations": [{"source_id": item.source_id, "source_version": item.source_version, "excerpt_id": item.excerpt_id} for item in citations],
    }
    publication = AnswerPublication(
        publication_id=_id("ANSP"), answer_version_id=answer_version_id, audience=data.audience,
        destination=data.destination, project_id=data.project_id or question.project_id,
        publication_sha256=hashlib.sha256(_json(payload).encode("utf-8")).hexdigest(),
        status="published", published_by=actor,
    )
    db.add(publication)
    for destination in {data.destination, "analytics", "crm"}:
        db.add(OutboxMessage(message_id=_id("MSG-ANS"), destination_module=destination, endpoint="/answer-center/publications", payload_json=_json({**payload, "publication_id": publication.publication_id}), status="pending", max_retries=5, next_attempt_at=utcnow()))
    version.status = "published"; question.status = "resolved"; question.resolved_at = utcnow()
    audit(db, actor=actor, action="answer.publication.publish", entity_type="answer_publication", entity_id=publication.publication_id, after={"answer_version_id": answer_version_id, "audience": data.audience, "destination": data.destination, "publication_sha256": publication.publication_sha256})
    db.commit(); db.refresh(publication); return publication


def retract_publication(db: Session, publication_id: str, reason: str, actor: str, actor_role: str) -> AnswerPublication:
    if actor_role not in PUBLISH_ROLES:
        raise PermissionError("Publikáció visszavonására nincs jogosultság.")
    if len(reason.strip()) < 10:
        raise ValueError("Részletes visszavonási indok szükséges.")
    row = db.scalar(select(AnswerPublication).where(AnswerPublication.publication_id == publication_id))
    if not row:
        raise KeyError(publication_id)
    if row.status != "published":
        raise ValueError("Csak aktív publikáció vonható vissza.")
    row.status = "retracted"; row.retracted_by = actor; row.retracted_at = utcnow(); row.retraction_reason = reason.strip()
    version = _version(db, row.answer_version_id); version.status = "retracted"
    db.add(OutboxMessage(message_id=_id("MSG-ANS"), destination_module=row.destination, endpoint="/answer-center/publications/retract", payload_json=_json({"event": "ANSWER_RETRACTED", "publication_id": publication_id, "reason": reason}), status="pending", max_retries=5, next_attempt_at=utcnow()))
    audit(db, actor=actor, action="answer.publication.retract", entity_type="answer_publication", entity_id=publication_id, after={"status": row.status, "reason": reason})
    db.commit(); db.refresh(row); return row


def revoke_source(db: Session, source_id: str, reason: str, actor: str, actor_role: str) -> AnswerKnowledgeSource:
    if actor_role not in SOURCE_ADMIN_ROLES:
        raise PermissionError("Forrás visszavonására nincs jogosultság.")
    if len(reason.strip()) < 10:
        raise ValueError("Részletes visszavonási indok szükséges.")
    source = _source(db, source_id)
    if source.status != "approved":
        raise ValueError("Csak jóváhagyott forrás vonható vissza.")
    source.status = "revoked"; source.revoked_by = actor; source.revoked_at = utcnow(); source.revocation_reason = reason.strip()
    version_ids = set(db.scalars(select(AnswerCitation.answer_version_id).where(AnswerCitation.source_id == source_id)).all())
    publications = list(db.scalars(select(AnswerPublication).where(AnswerPublication.answer_version_id.in_(version_ids), AnswerPublication.status == "published")).all()) if version_ids else []
    for publication in publications:
        publication.status = "retracted"; publication.retracted_by = actor; publication.retracted_at = utcnow(); publication.retraction_reason = f"Forrás visszavonva: {reason}"
        version = _version(db, publication.answer_version_id); version.status = "retracted"
        question = _question(db, version.question_id); question.status = "needs_revision"; question.resolved_at = None
        _queue_task(db, question=question, version=version, reason=f"A publikált válasz forrását visszavonták: {source.title}. {reason}")
        db.add(OutboxMessage(message_id=_id("MSG-ANS"), destination_module=publication.destination, endpoint="/answer-center/publications/retract", payload_json=_json({"event": "ANSWER_RETRACTED", "publication_id": publication.publication_id, "source_id": source_id, "reason": reason}), status="pending", max_retries=5, next_attempt_at=utcnow()))
    audit(db, actor=actor, action="answer.source.revoke", entity_type="answer_knowledge_source", entity_id=source_id, after={"status": source.status, "retracted_publications": len(publications), "reason": reason})
    db.commit(); db.refresh(source); return source


def workspace(db: Session) -> dict:
    sources = list(db.scalars(select(AnswerKnowledgeSource).order_by(desc(AnswerKnowledgeSource.updated_at))).all())
    excerpts = list(db.scalars(select(AnswerKnowledgeExcerpt).order_by(desc(AnswerKnowledgeExcerpt.created_at))).all())
    questions = list(db.scalars(select(AnswerQuestion).order_by(desc(AnswerQuestion.created_at))).all())
    versions = list(db.scalars(select(AnswerVersion).order_by(desc(AnswerVersion.created_at))).all())
    citations = list(db.scalars(select(AnswerCitation).order_by(desc(AnswerCitation.created_at))).all())
    reviews = list(db.scalars(select(AnswerReview).order_by(desc(AnswerReview.created_at))).all())
    publications = list(db.scalars(select(AnswerPublication).order_by(desc(AnswerPublication.published_at))).all())
    return {
        "sources": sources, "excerpts": excerpts, "questions": questions, "versions": versions,
        "citations": citations, "reviews": reviews, "publications": publications,
        "metrics": {
            "approved_sources": sum(row.status == "approved" for row in sources),
            "open_questions": sum(row.status != "resolved" for row in questions),
            "human_review": sum(row.status == "human_review" for row in versions),
            "escalated": sum(row.status == "escalated" for row in versions),
            "published": sum(row.status == "published" for row in publications),
            "retracted": sum(row.status == "retracted" for row in publications),
        },
    }
