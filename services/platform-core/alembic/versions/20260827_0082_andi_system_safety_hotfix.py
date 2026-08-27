"""Add fail-closed freshness, routing and canonical email delivery state.

Revision ID: 20260827_0082
Revises: 20260826_0081
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlparse, urlunparse

import sqlalchemy as sa

from alembic import op

revision = "20260827_0082"
down_revision = "20260826_0081"
branch_labels = None
depends_on = None


def _sha(value: dict[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _canonical_url(value: str) -> str:
    parsed = urlparse(value.strip())
    return urlunparse(parsed._replace(fragment=""))


def upgrade() -> None:
    op.create_table(
        "question_radar_identities",
        sa.Column("identity_hash", sa.String(64), primary_key=True),
        sa.Column("platform", sa.String(120), nullable=False),
        sa.Column("canonical_source_url", sa.String(1500), nullable=False),
        sa.Column("normalized_question", sa.Text(), nullable=False),
        sa.Column("first_topic_id", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_question_radar_identities_platform", "question_radar_identities", ["platform"]
    )
    op.create_index(
        "ix_question_radar_identities_first_topic_id",
        "question_radar_identities",
        ["first_topic_id"],
    )

    with op.batch_alter_table("question_radar_topics") as batch:
        batch.add_column(sa.Column("identity_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("platform", sa.String(120), nullable=True))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("published_at_raw", sa.String(255), nullable=True))
        batch.add_column(sa.Column("age_days", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("active_status", sa.String(40), nullable=False, server_default="unknown")
        )
        batch.add_column(sa.Column("existing_answer_count", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "freshness_decision", sa.String(40), nullable=False, server_default="unverified"
            )
        )
        batch.add_column(
            sa.Column(
                "eligibility_status", sa.String(30), nullable=False, server_default="quarantined"
            )
        )
        batch.add_column(
            sa.Column(
                "rejection_reasons_json",
                sa.Text(),
                nullable=False,
                server_default='["legacy_freshness_unverified"]',
            )
        )
        batch.create_check_constraint(
            "ck_question_radar_eligibility_status",
            "eligibility_status IN ('eligible','ineligible','quarantined')",
        )
    for column in (
        "identity_hash",
        "platform",
        "published_at",
        "age_days",
        "active_status",
        "freshness_decision",
        "eligibility_status",
    ):
        op.create_index(f"ix_question_radar_topics_{column}", "question_radar_topics", [column])

    bind = op.get_bind()
    topics = bind.execute(
        sa.text(
            "SELECT topic_id, question, source_url, created_at "
            "FROM question_radar_topics ORDER BY id"
        )
    ).mappings()
    seen: set[str] = set()
    for topic in topics:
        source_url = _canonical_url(str(topic["source_url"] or ""))
        platform = (urlparse(source_url).hostname or "unknown").casefold()
        normalized_question = " ".join(str(topic["question"] or "").casefold().split())
        identity = _sha(
            {"platform": platform, "source_url": source_url, "question": normalized_question}
        )
        if identity not in seen:
            bind.execute(
                sa.text(
                    "INSERT INTO question_radar_identities "
                    "(identity_hash, platform, canonical_source_url, normalized_question, "
                    "first_topic_id, created_at) "
                    "VALUES (:identity, :platform, :url, :question, :topic_id, :created_at)"
                ),
                {
                    "identity": identity,
                    "platform": platform,
                    "url": source_url,
                    "question": normalized_question,
                    "topic_id": topic["topic_id"],
                    "created_at": topic["created_at"],
                },
            )
            seen.add(identity)
        bind.execute(
            sa.text(
                "UPDATE question_radar_topics SET identity_hash=:identity, platform=:platform, "
                "eligibility_status='quarantined', freshness_decision='unverified', "
                "active_status='unknown', rejection_reasons_json=:reasons WHERE topic_id=:topic_id"
            ),
            {
                "identity": identity,
                "platform": platform,
                "reasons": '["legacy_freshness_unverified"]',
                "topic_id": topic["topic_id"],
            },
        )

    op.create_table(
        "canonical_email_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_id", sa.String(120), nullable=False, unique=True),
        sa.Column("handoff_id", sa.String(120), nullable=True),
        sa.Column("identity_sha256", sa.String(64), nullable=False),
        sa.Column("recipient_normalized", sa.String(320), nullable=False),
        sa.Column("report_type", sa.String(80), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("tenant_scope", sa.String(120), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_message_id", sa.String(500), nullable=True),
        sa.Column("lease_token", sa.String(120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("incident_reference", sa.String(160), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','sending','sent','accepted_unverified',"
            "'failed_retryable','failed_terminal')",
            name="ck_canonical_email_delivery_status",
        ),
        sa.UniqueConstraint("identity_sha256", name="uq_canonical_email_delivery_identity"),
    )
    for column in (
        "delivery_id",
        "handoff_id",
        "identity_sha256",
        "recipient_normalized",
        "report_type",
        "local_date",
        "tenant_scope",
        "status",
        "provider_message_id",
        "lease_token",
        "lease_expires_at",
        "next_attempt_at",
        "incident_reference",
        "accepted_at",
        "verified_at",
    ):
        op.create_index(
            f"ix_canonical_email_deliveries_{column}",
            "canonical_email_deliveries",
            [column],
            unique=column == "delivery_id",
        )

    handoffs = bind.execute(
        sa.text(
            "SELECT handoff_id, local_date, handoff_type, recipient_email, payload_sha256, "
            "status, attempt_count, provider_message_id, last_error, sent_at, "
            "created_at, updated_at "
            "FROM canonical_internal_handoffs ORDER BY id"
        )
    ).mappings()
    for handoff in handoffs:
        recipient = str(handoff["recipient_email"]).strip().casefold()
        identity = _sha(
            {
                "recipient": recipient,
                "report_type": handoff["handoff_type"],
                "local_date": handoff["local_date"].isoformat(),
                "tenant_scope": "imperial-holding",
            }
        )
        legacy_status = str(handoff["status"])
        last_error = str(handoff["last_error"] or "")
        if legacy_status == "sent":
            delivery_status = "sent"
        elif "accepted_but_unverified" in last_error:
            delivery_status = "accepted_unverified"
        elif legacy_status == "pending":
            delivery_status = "pending"
        else:
            delivery_status = "failed_terminal"
        incident_reference = None
        if last_error.startswith("sev1_quarantined_"):
            incident_reference = "SEV1-20260827-DUPLICATE-DIGEST"
        elif delivery_status == "accepted_unverified":
            incident_reference = "LEGACY-AMBIGUOUS-DELIVERY"
        bind.execute(
            sa.text(
                "INSERT INTO canonical_email_deliveries "
                "(delivery_id, handoff_id, identity_sha256, recipient_normalized, report_type, "
                "local_date, tenant_scope, payload_sha256, status, attempt_count, "
                "provider_message_id, "
                "last_error, incident_reference, accepted_at, created_at, updated_at) VALUES "
                "(:delivery_id, :handoff_id, :identity, :recipient, :report_type, :local_date, "
                ":tenant, :payload, :status, :attempts, :provider_id, :last_error, :incident, "
                ":accepted_at, :created_at, :updated_at)"
            ),
            {
                "delivery_id": f"CED-MIG-{str(handoff['handoff_id'])[:80]}",
                "handoff_id": handoff["handoff_id"],
                "identity": identity,
                "recipient": recipient,
                "report_type": handoff["handoff_type"],
                "local_date": handoff["local_date"],
                "tenant": "imperial-holding",
                "payload": handoff["payload_sha256"],
                "status": delivery_status,
                "attempts": handoff["attempt_count"],
                "provider_id": handoff["provider_message_id"],
                "last_error": handoff["last_error"],
                "incident": incident_reference,
                "accepted_at": handoff["sent_at"],
                "created_at": handoff["created_at"],
                "updated_at": handoff["updated_at"],
            },
        )

    bind.execute(
        sa.text(
            "UPDATE pub_exceptions SET owner='SYSTEM-TECHNICAL-INCIDENTS' "
            "WHERE status='OPEN' AND owner='Molnár Andrea'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE cc_tasks SET assignee=NULL, status='blocked', "
            "description=COALESCE(description, '') || "
            "' [Automatikus technikai incidens; személyhez rendelés csak kézi triage után.]' "
            "WHERE status='open' AND assignee='Molnár Andrea' AND source_event_id IN "
            "(SELECT event_id FROM pub_events WHERE event_type='PUBLICATION_EXCEPTION_CREATED')"
        )
    )
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "pub_exceptions",
            "owner",
            existing_type=sa.String(255),
            server_default="SYSTEM-TECHNICAL-INCIDENTS",
            nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "pub_exceptions",
            "owner",
            existing_type=sa.String(255),
            server_default="Molnár Andrea",
            nullable=False,
        )
    op.drop_table("canonical_email_deliveries")
    for column in (
        "identity_hash",
        "platform",
        "published_at",
        "age_days",
        "active_status",
        "freshness_decision",
        "eligibility_status",
    ):
        op.drop_index(f"ix_question_radar_topics_{column}", table_name="question_radar_topics")
    with op.batch_alter_table("question_radar_topics") as batch:
        batch.drop_constraint("ck_question_radar_eligibility_status", type_="check")
        for column in (
            "rejection_reasons_json",
            "eligibility_status",
            "freshness_decision",
            "existing_answer_count",
            "active_status",
            "age_days",
            "published_at_raw",
            "published_at",
            "platform",
            "identity_hash",
        ):
            batch.drop_column(column)
    op.drop_table("question_radar_identities")
