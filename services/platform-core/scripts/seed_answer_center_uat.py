from __future__ import annotations

import argparse
import hashlib
import json

from sqlalchemy import select

from app.database import SessionLocal
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
    submit_for_review,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source(db, *, suffix: str, domain: str, visibility: str, project_id: str | None, sentence: str):
    source = register_source(
        db,
        AnswerKnowledgeSourceIn(
            title=f"Szintetikus Answer Center UAT {domain} {suffix}",
            source_type="operating_manual",
            canonical_ref=f"uat://answer-center/{suffix}/{domain}",
            version="1.0",
            domain=domain,
            visibility=visibility,
            project_id=project_id,
            content_sha256=_sha(sentence),
            owner_role="finance" if domain == "finance" else "project-manager",
        ),
        "answer-uat-author@imperial.local",
        "platform-admin",
    )
    excerpt = add_excerpt(
        db,
        source.source_id,
        AnswerKnowledgeExcerptIn(locator="UAT / 1. bekezdés", excerpt_text=sentence),
        "answer-uat-author@imperial.local",
        "platform-admin",
    )
    approve_source(db, source.source_id, "answer-uat-source-reviewer@imperial.local", "platform-admin")
    return source, excerpt


def _version(db, *, source, excerpt, sentence: str, actor: str, actor_role: str, channel: str, project_id: str | None, customer_reference: str | None, certainty: str = "high"):
    question = create_question(
        db,
        AnswerQuestionIn(
            question_text=f"Szintetikus {source.domain} UAT-kérdés: {source.source_id}",
            domain=source.domain,
            channel=channel,
            project_id=project_id,
            customer_reference=customer_reference,
        ),
        actor,
        "customer" if channel == "my-imperial" else actor_role,
    )
    version = create_draft(
        db,
        question.question_id,
        AnswerDraftIn(answer_text=sentence, certainty=certainty, source_conflict=False),
        "answer-uat-drafter@imperial.local",
        actor_role,
    )
    add_citation(
        db,
        version.answer_version_id,
        AnswerCitationIn(claim_key="paragraph-1", claim_text=sentence, source_id=source.source_id, excerpt_id=excerpt.excerpt_id),
        "answer-uat-drafter@imperial.local",
        actor_role,
    )
    submit_for_review(db, version.answer_version_id, "answer-uat-drafter@imperial.local", actor_role)
    db.refresh(version)
    return question, version


def run(suffix: str) -> dict:
    with SessionLocal() as db:
        before_messages = set(db.scalars(select(OutboxMessage.message_id)).all())
        finance_sentence = "A szintetikus UAT projektkeret kizárólag a jóváhagyott pénzügyi alapterv aktív változatából olvasható."
        finance_source, finance_excerpt = _source(db, suffix=suffix, domain="finance", visibility="internal", project_id=None, sentence=finance_sentence)
        internal_question, internal_version = _version(db, source=finance_source, excerpt=finance_excerpt, sentence=finance_sentence, actor="marketing@imperial.local", actor_role="marketing", channel="internal", project_id=None, customer_reference=None)
        review_answer(db, internal_version.answer_version_id, AnswerReviewIn(decision="approved", note="Szintetikus UAT pénzügyi szakértői review."), "answer-uat-finance-reviewer@imperial.local", "finance")
        internal_publication = publish_answer(db, internal_version.answer_version_id, AnswerPublicationIn(audience="internal", destination="answer-center"), "owner@imperial.local", "owner")

        project_id = f"PRJ-ANS-UAT-{suffix}"
        technical_sentence = "A szintetikus UAT projekt műszaki státusza kizárólag a kapcsolt, jóváhagyott projektforrás alapján közölhető az ügyféllel."
        technical_source, technical_excerpt = _source(db, suffix=suffix, domain="technical", visibility="project_customer", project_id=project_id, sentence=technical_sentence)
        customer_question, customer_version = _version(db, source=technical_source, excerpt=technical_excerpt, sentence=technical_sentence, actor="answer-uat-customer@example.test", actor_role="project-manager", channel="my-imperial", project_id=project_id, customer_reference=f"CUS-ANS-UAT-{suffix}")
        review_answer(db, customer_version.answer_version_id, AnswerReviewIn(decision="approved", note="Szintetikus UAT projektmenedzseri műszaki review."), "answer-uat-pm-reviewer@imperial.local", "project-manager")
        review_answer(db, customer_version.answer_version_id, AnswerReviewIn(decision="approved", note="Szintetikus UAT ügyvezetői ügyfélkommunikációs review."), "answer-uat-md-reviewer@imperial.local", "managing-director")
        customer_publication = publish_answer(db, customer_version.answer_version_id, AnswerPublicationIn(audience="customer", destination="my-imperial", project_id=project_id), "owner@imperial.local", "owner")

        _, escalated_version = _version(db, source=finance_source, excerpt=finance_excerpt, sentence=finance_sentence, actor="sales@imperial.local", actor_role="sales", channel="internal", project_id=None, customer_reference=None, certainty="low")
        if escalated_version.status != "escalated":
            raise RuntimeError("Az alacsony bizonyosságú UAT-válasz nem eszkalálódott.")
        escalation_task = db.scalar(select(TaskRecord).where(TaskRecord.source_event_id == escalated_version.answer_version_id))
        if not escalation_task:
            raise RuntimeError("Az alacsony bizonyosságú válaszhoz nem jött létre feladatkártya.")

        uat_messages = list(db.scalars(select(OutboxMessage).where(~OutboxMessage.message_id.in_(before_messages))).all())
        for message in uat_messages:
            message.status = "sent"
            message.last_error = "UAT_INTERCEPTED_NO_EXTERNAL_DELIVERY"
        db.commit()
        if db.scalar(select(AnswerPublication).where(AnswerPublication.publication_id == internal_publication.publication_id)).status != "published":
            raise RuntimeError("A belső UAT-publikáció nem olvasható vissza.")
        return {
            "suffix": suffix,
            "sources": [finance_source.source_id, technical_source.source_id],
            "questions": [internal_question.question_id, customer_question.question_id],
            "versions": [internal_version.answer_version_id, customer_version.answer_version_id, escalated_version.answer_version_id],
            "publications": [internal_publication.publication_id, customer_publication.publication_id],
            "escalation_task": escalation_task.task_id,
            "intercepted_outbox": len(uat_messages),
            "customer_project_id": project_id,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suffix", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.suffix), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
