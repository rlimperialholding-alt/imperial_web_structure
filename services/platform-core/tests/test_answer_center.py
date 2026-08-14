from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AnswerPublication, OutboxMessage, TaskRecord
from app.schemas import (
    AnswerCitationIn,
    AnswerDraftIn,
    AnswerKnowledgeExcerptIn,
    AnswerKnowledgeSourceIn,
    AnswerPublicationIn,
    AnswerQuestionIn,
    AnswerReviewIn,
)
from app.services.answer_center import (
    add_citation,
    add_excerpt,
    approve_source,
    create_draft,
    create_question,
    publish_answer,
    register_source,
    review_answer,
    revoke_source,
    submit_for_review,
)


def _source(db, suffix: str = "INTERNAL", *, visibility: str = "internal", project_id: str | None = None, domain: str = "finance"):
    source = register_source(
        db,
        AnswerKnowledgeSourceIn(
            title=f"Ellenőrzött tudásforrás {suffix}",
            source_type="operating_manual",
            canonical_ref=f"gdrive://canonical/{suffix}",
            version="1.0",
            domain=domain,
            visibility=visibility,
            allowed_roles=[],
            project_id=project_id,
            content_sha256=(suffix.lower().encode().hex() + "a" * 64)[:64],
            owner_role="finance" if domain == "finance" else "project-manager",
        ),
        "source-author@imperial.local",
        "platform-admin",
    )
    excerpt = add_excerpt(
        db,
        source.source_id,
        AnswerKnowledgeExcerptIn(
            locator="4. fejezet / 2. bekezdés",
            excerpt_text="A jóváhagyott projektkeret a pénzügyi alapterv aktív változatából származik.",
        ),
        "source-author@imperial.local",
        "platform-admin",
    )
    approve_source(db, source.source_id, "source-approver@imperial.local", "platform-admin")
    return source, excerpt


def _answer(db, source, excerpt, *, channel: str = "internal", project_id: str | None = None, actor: str = "marketing@imperial.local", actor_role: str = "marketing", certainty: str = "high", conflict: bool = False):
    question = create_question(
        db,
        AnswerQuestionIn(
            question_text="Melyik jóváhagyott projektkeretet kell használni?",
            domain=source.domain,
            channel=channel,
            project_id=project_id,
            customer_reference="CUS-UAT-001" if channel == "my-imperial" else None,
        ),
        actor,
        "customer" if channel == "my-imperial" else actor_role,
    )
    sentence = "A jóváhagyott projektkeret a pénzügyi alapterv aktív változatából származik."
    version = create_draft(
        db,
        question.question_id,
        AnswerDraftIn(answer_text=sentence, certainty=certainty, source_conflict=conflict),
        "draft-author@imperial.local",
        actor_role,
    )
    citation = add_citation(
        db,
        version.answer_version_id,
        AnswerCitationIn(claim_key="paragraph-1", claim_text=sentence, source_id=source.source_id, excerpt_id=excerpt.excerpt_id),
        "draft-author@imperial.local",
        actor_role,
    )
    return question, version, citation


def test_source_requires_exact_excerpt_and_independent_approval(db):
    source = register_source(
        db,
        AnswerKnowledgeSourceIn(
            title="Pénzügyi kézikönyv",
            source_type="operating_manual",
            canonical_ref="gdrive://canonical/finance-manual",
            version="2.0",
            domain="finance",
            content_sha256="a" * 64,
            owner_role="finance",
        ),
        "finance-author@imperial.local",
        "finance",
    )
    with pytest.raises(ValueError, match="kivonat"):
        approve_source(db, source.source_id, "finance-reviewer@imperial.local", "finance")
    excerpt = add_excerpt(db, source.source_id, AnswerKnowledgeExcerptIn(locator="p. 12", excerpt_text="A cash-flow riport napi zárás után hiteles."), "finance-author@imperial.local", "finance")
    assert len(excerpt.excerpt_sha256) == 64
    with pytest.raises(PermissionError, match="saját"):
        approve_source(db, source.source_id, "finance-author@imperial.local", "finance")
    approved = approve_source(db, source.source_id, "finance-reviewer@imperial.local", "finance")
    assert approved.status == "approved"
    with pytest.raises(ValueError, match="jóváhagyás előtt"):
        add_excerpt(db, source.source_id, AnswerKnowledgeExcerptIn(locator="p. 13", excerpt_text="Utólagos tiltott módosítás."), "finance-author@imperial.local", "finance")


def test_internal_answer_has_claim_coverage_domain_review_and_audited_distribution(db):
    source, excerpt = _source(db)
    question, version, citation = _answer(db, source, excerpt)
    assert citation.source_content_sha256 == source.content_sha256
    assert submit_for_review(db, version.answer_version_id, "draft-author@imperial.local", "marketing").status == "human_review"
    with pytest.raises(PermissionError, match="finance"):
        review_answer(db, version.answer_version_id, AnswerReviewIn(decision="approved", note="Nem tárgyköri review."), "sales-reviewer@imperial.local", "sales")
    review = review_answer(db, version.answer_version_id, AnswerReviewIn(decision="approved", note="A forrás és a következtetés pénzügyileg helyes."), "finance-reviewer@imperial.local", "finance")
    assert review.decision == "approved"
    publication = publish_answer(db, version.answer_version_id, AnswerPublicationIn(audience="internal", destination="answer-center"), "owner@imperial.local", "owner")
    assert publication.status == "published" and len(publication.publication_sha256) == 64
    destinations = {row.destination_module for row in db.scalars(select(OutboxMessage)).all()}
    assert {"answer-center", "analytics", "crm"}.issubset(destinations)
    db.refresh(question)
    assert question.status == "resolved"


def test_low_certainty_or_conflict_fails_closed_and_creates_expert_task(db):
    source, excerpt = _source(db, "ESCALATE")
    _, low, _ = _answer(db, source, excerpt, certainty="low")
    assert submit_for_review(db, low.answer_version_id, "draft-author@imperial.local", "marketing").status == "escalated"
    task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == low.answer_version_id))
    assert task and task.status == "open" and task.assignee == "finance"
    with pytest.raises(ValueError, match="felülvizsgálatra beküldött"):
        review_answer(db, low.answer_version_id, AnswerReviewIn(decision="approved", note="Tiltott átugrás."), "finance-reviewer@imperial.local", "finance")

    _, conflict, _ = _answer(db, source, excerpt, certainty="high", conflict=True)
    assert submit_for_review(db, conflict.answer_version_id, "draft-author@imperial.local", "marketing").status == "escalated"
    conflict_task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == conflict.answer_version_id))
    assert conflict_task and conflict_task.executive_relevance is True and conflict_task.priority == "high"


def test_customer_publication_is_project_scoped_and_requires_expert_plus_managing_director(db):
    source, excerpt = _source(db, "CUSTOMER", visibility="project_customer", project_id="PRJ-UAT-001", domain="technical")
    question, version, _ = _answer(db, source, excerpt, channel="my-imperial", project_id="PRJ-UAT-001", actor="customer@example.test", actor_role="project-manager")
    submit_for_review(db, version.answer_version_id, "draft-author@imperial.local", "project-manager")
    review_answer(db, version.answer_version_id, AnswerReviewIn(decision="approved", note="Műszaki tartalom és projektkapcsolat ellenőrizve."), "pm-reviewer@imperial.local", "project-manager")
    with pytest.raises(ValueError, match="ügyvezetői"):
        publish_answer(db, version.answer_version_id, AnswerPublicationIn(audience="customer", destination="my-imperial", project_id="PRJ-UAT-001"), "owner@imperial.local", "owner")
    review_answer(db, version.answer_version_id, AnswerReviewIn(decision="approved", note="Ügyfélkommunikáció és felelősségi határ jóváhagyva."), "md@imperial.local", "managing-director")
    with pytest.raises(ValueError, match="eltér"):
        publish_answer(db, version.answer_version_id, AnswerPublicationIn(audience="customer", destination="my-imperial", project_id="PRJ-OTHER"), "owner@imperial.local", "owner")
    publication = publish_answer(db, version.answer_version_id, AnswerPublicationIn(audience="customer", destination="my-imperial", project_id="PRJ-UAT-001"), "owner@imperial.local", "owner")
    assert publication.destination == "my-imperial" and publication.project_id == "PRJ-UAT-001"
    assert any(row.destination_module == "my-imperial" for row in db.scalars(select(OutboxMessage)).all())
    assert question.asker_role == "customer"


def test_source_snapshot_tamper_blocks_review_and_revocation_retracts_live_answers(db):
    source, excerpt = _source(db, "INTEGRITY")
    _, version, _ = _answer(db, source, excerpt)
    excerpt.excerpt_text = "Megváltoztatott kivonat."
    db.commit()
    with pytest.raises(ValueError, match="integritása"):
        submit_for_review(db, version.answer_version_id, "draft-author@imperial.local", "marketing")

    source2, excerpt2 = _source(db, "REVOKE")
    question2, version2, _ = _answer(db, source2, excerpt2)
    submit_for_review(db, version2.answer_version_id, "draft-author@imperial.local", "marketing")
    review_answer(db, version2.answer_version_id, AnswerReviewIn(decision="approved", note="A pénzügyi szakértő jóváhagyta."), "finance-reviewer@imperial.local", "finance")
    publication = publish_answer(db, version2.answer_version_id, AnswerPublicationIn(audience="internal", destination="crm"), "owner@imperial.local", "owner")
    revoke_source(db, source2.source_id, "Az irányelv új verzióval hatályát vesztette.", "owner@imperial.local", "owner")
    db.refresh(publication); db.refresh(question2)
    assert publication.status == "retracted"
    assert question2.status == "needs_revision"
    assert db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == version2.answer_version_id)) is not None


def test_answer_center_role_page_access(client):
    for email in ("owner@imperial.local", "finance@imperial.local", "project-manager@imperial.local", "sales@imperial.local", "marketing@imperial.local"):
        client.post("/logout")
        login = client.post("/login", data={"email": email, "password": "Imperial2026!"}, follow_redirects=False)
        if login.status_code == 303:
            assert client.get("/answer-center").status_code == 200
    client.post("/logout")
    assert client.post("/login", data={"email": "customer@imperial.local", "password": "Imperial2026!"}, follow_redirects=False).status_code == 303
    assert client.get("/answer-center").status_code == 403
