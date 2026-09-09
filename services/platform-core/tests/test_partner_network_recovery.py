from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.growth_ops import canonical_policy, partnerpoint, service
from app.growth_ops.models import (
    GrowthAccountStop,
    GrowthControlState,
    GrowthSignal,
    OutreachMessage,
)
from scripts.reconcile_partnerpoint_backlog import _historical_control_rows


def _signal(*, signal_id: str, email: str, status: str) -> GrowthSignal:
    now = datetime.now(UTC)
    return GrowthSignal(
        signal_id=signal_id,
        motor_key="construction",
        source_id="DYNAMIC_HU_BH_HU",
        source_bucket="architect_office",
        external_key=f"candidate:{signal_id}",
        signal_type="architect_office",
        detected_at=now - timedelta(days=10),
        company_name="Bánáti + Hartvig Építész Iroda Kft.",
        recipient_organization_name="Bánáti + Hartvig",
        subject_type="organization",
        recipient_role="unknown",
        recipient_email=email,
        recipient_email_type="role",
        contact_basis="public_business_contact",
        public_contact_url="https://bh.hu/kapcsolat/",
        summary="Verified architect office fixture for reply-stop regression.",
        evidence_url="https://bh.hu/kapcsolat/",
        brand_id="imperial",
        score=90,
        urgency=50,
        confidence=95,
        dedupe_hash=hashlib.sha256(signal_id.encode()).hexdigest(),
        source_payload_hash="1" * 64,
        status=status,
        rejection_reasons_json="[]",
    )


def _outreach(
    *,
    outreach_id: str,
    signal_id: str,
    email: str,
    status: str,
    sent_at: datetime | None,
) -> OutreachMessage:
    return OutreachMessage(
        outreach_id=outreach_id,
        signal_id=signal_id,
        motor_key="construction",
        brand_id="imperial",
        sender_email="info@imperialholding.hu",
        recipient_email=email,
        sequence_step=0,
        subject="együttműködés",
        body_text="fixture",
        unsubscribe_token_hash=hashlib.sha256((outreach_id + "u").encode()).hexdigest(),
        idempotency_key=hashlib.sha256((outreach_id + "i").encode()).hexdigest(),
        payload_sha256=hashlib.sha256((outreach_id + "p").encode()).hexdigest(),
        status=status,
        available_at=datetime.now(UTC),
        sent_at=sent_at,
    )


def test_banati_real_reply_replay_stops_account_and_pending_followup(db):
    sent_at = datetime.now(UTC) - timedelta(days=8)
    reply_at = datetime.now(UTC) - timedelta(days=7)
    sent_signal = _signal(signal_id="SIG-BANATI-SENT", email="bh@bh.hu", status="contacted")
    pending_signal = _signal(signal_id="SIG-BANATI-PENDING", email="office@bh.hu", status="queued")
    unrelated_signal = _signal(
        signal_id="SIG-UNRELATED", email="info@unrelated.hu", status="queued"
    )
    db.add_all(
        [
            sent_signal,
            pending_signal,
            unrelated_signal,
            _outreach(
                outreach_id="OUT-BANATI-SENT",
                signal_id=sent_signal.signal_id,
                email="bh@bh.hu",
                status="sent",
                sent_at=sent_at,
            ),
            _outreach(
                outreach_id="OUT-BANATI-PENDING",
                signal_id=pending_signal.signal_id,
                email="office@bh.hu",
                status="queued",
                sent_at=None,
            ),
            _outreach(
                outreach_id="OUT-UNRELATED",
                signal_id=unrelated_signal.signal_id,
                email="info@unrelated.hu",
                status="queued",
                sent_at=None,
            ),
        ]
    )
    db.execute(
        text(
            "CREATE TABLE sales_agent_processed_emails ("
            "gmail_message_id VARCHAR, sender VARCHAR, internal_date_ms BIGINT, "
            "created_at TIMESTAMP)"
        )
    )
    db.execute(
        text(
            "CREATE TABLE sales_agent_suppressions ("
            "id VARCHAR, normalized_value VARCHAR, reason TEXT, source VARCHAR, "
            "active BOOLEAN, created_at TIMESTAMP)"
        )
    )
    db.execute(
        text(
            "INSERT INTO sales_agent_processed_emails "
            "(gmail_message_id, sender, internal_date_ms, created_at) "
            "VALUES (:id, :sender, :millis, :created)"
        ),
        {
            "id": "1a05741f779b3103",
            "sender": "Bánáti Bodó <banatibodo@bh.hu>",
            "millis": int(reply_at.timestamp() * 1000),
            "created": reply_at,
        },
    )
    db.commit()
    try:
        result = service.sync_sales_agent_reply_stops(db)

        assert result["status"] == "healthy"
        assert result["matched"] == 1
        assert (
            db.scalar(
                select(OutreachMessage.status).where(
                    OutreachMessage.outreach_id == "OUT-BANATI-SENT"
                )
            )
            == "responded"
        )
        pending = db.scalar(
            select(OutreachMessage).where(OutreachMessage.outreach_id == "OUT-BANATI-PENDING")
        )
        assert pending.status == "blocked"
        assert pending.last_error == "STOP_RESPONSE"
        assert (
            db.scalar(
                select(OutreachMessage.status).where(OutreachMessage.outreach_id == "OUT-UNRELATED")
            )
            == "queued"
        )
        stop = db.scalar(
            select(GrowthAccountStop).where(GrowthAccountStop.account_key == "domain:bh.hu")
        )
        assert stop is not None
        assert stop.stop_kind == "response"
        assert stop.source_event_id == "1a05741f779b3103"
    finally:
        db.rollback()
        db.execute(text("DROP TABLE IF EXISTS sales_agent_processed_emails"))
        db.execute(text("DROP TABLE IF EXISTS sales_agent_suppressions"))
        db.commit()


def test_partnerpoint_candidate_filter_accepts_unsent_pass_rows_without_status_lock(monkeypatch):
    monkeypatch.setenv("GROWTH_PARTNERPOINT_ARCHITECT_DAILY_MAX", "30")
    monkeypatch.setenv("GROWTH_PARTNERPOINT_REFERRAL_DAILY_MAX", "2")
    header = [f"c{i}" for i in range(23)]
    eligible = [""] * 23
    eligible[0] = "PC-260908-A01"
    eligible[1] = "Sporaarchitects Kft."
    eligible[2] = "Építész-/tervezőiroda"
    eligible[3] = partnerpoint.PARTNERPOINT_READY_STATUS
    eligible[7] = "https://www.sporaarchitects.hu/team"
    eligible[10] = "spora@sporaarchitects.hu"
    eligible[14] = "https://www.sporaarchitects.hu/team"
    eligible[15] = "Primary=Imperial Holding; verified"
    eligible[18] = "ARCHITECT_OFFICE_FIRST_CONTACT_HU"
    eligible[21] = "PASS"
    stale = list(eligible)
    stale[0] = "PC-260827-A01"
    stale[3] = "MINŐSÍTVE – KÖZPONTI ÁTADÁSI CSOMAG KÉSZ"
    public_gmail = list(eligible)
    public_gmail[0] = "PC-PUBLIC-GMAIL"
    public_gmail[7] = "https://peldaepitesz.hu/kapcsolat"
    public_gmail[10] = "peldaepitesz@gmail.com"
    public_gmail[14] = "https://peldaepitesz.hu/kapcsolat"
    manual = list(eligible)
    manual[0] = "PC-MANUAL"
    manual[1] = "Hofstädter Építőanyag Centrum Kft."
    manual[3] = partnerpoint.PARTNERPOINT_READY_STATUS
    manual[18] = "REFERRAL_PARTNER_FIRST_CONTACT_HU"
    manual[21] = "OWNER_MANUAL_ONLY"

    result = partnerpoint._candidate_rows(
        {"Partner_Universe": [header, eligible, stale, public_gmail, manual]}
    )

    assert [item["candidate_id"] for item in result] == [
        "PC-260908-A01",
        "PC-260827-A01",
        "PC-PUBLIC-GMAIL",
    ]


def test_partnerpoint_shared_mailbox_history_checks_exact_address_only(db, monkeypatch):
    db.execute(
        text(
            "CREATE TABLE sales_agent_leads ("
            "id VARCHAR, email VARCHAR, created_at TIMESTAMP)"
        )
    )
    db.execute(
        text(
            "INSERT INTO sales_agent_leads (id, email, created_at) "
            "VALUES ('OTHER', 'someone.else@gmail.com', CURRENT_TIMESTAMP)"
        )
    )
    db.commit()
    gmail_queries: list[str] = []

    def gmail_messages(_token, query, **_kwargs):
        gmail_queries.append(query)
        return []

    monkeypatch.setattr(partnerpoint, "_gmail_message_ids", gmail_messages)
    try:
        result = partnerpoint._existing_relationship_gate(
            db,
            {
                "email": "peldaepitesz@gmail.com",
                "company": "Példa Építésziroda Kft.",
                "candidate_id": "PC-PUBLIC-GMAIL",
            },
            gmail_token="fixture",
        )

        assert result is None
        assert gmail_queries == [
            "in:sent newer_than:365d to:(peldaepitesz@gmail.com)",
            "newer_than:365d from:(peldaepitesz@gmail.com)",
        ]
    finally:
        db.rollback()
        db.execute(text("DROP TABLE sales_agent_leads"))
        db.commit()


@pytest.mark.parametrize(
    "status",
    [
        "MEGKERESVE – SENT READBACK IGAZOLT",
        "POZITÍV VÁLASZ – EGYEZTETÉSRE VÁR",
        "HARD BOUNCE",
        "SUPPRESSION_REVIEW",
        "BLOKKOLT – DNC",
        "90 NAPON BELÜLI IGAZOLT KAPCSOLATI ELŐZMÉNY",
    ],
)
def test_partnerpoint_terminal_statuses_remain_blocked(status):
    assert partnerpoint._status_allows_first_contact(status) is False


@pytest.mark.parametrize(
    "status",
    [
        "MINŐSÍTVE – ELSŐ KAPCSOLAT KÖVETKEZŐ KÖRRE",
        "MINŐSÍTVE – KÖZPONTI ÁTADÁSI CSOMAG KÉSZ",
        "MINŐSÍTVE – KÖZPONTI ÁTADÁSRA VÁR",
        "NINCS IGAZOLT ÜZLETI KAPCSOLAT",
        "ÚJ – KÖZPONTI ÁTADÁSRA KÉSZ",
    ],
)
def test_partnerpoint_unsent_status_labels_do_not_block_first_contact(status):
    assert partnerpoint._status_allows_first_contact(status) is True


def test_partnerpoint_daily_capacity_counts_existing_created_messages(db):
    architect = _signal(
        signal_id="SIG-ARCH-TODAY",
        email="architect@example.hu",
        status="queued",
    )
    referral = _signal(
        signal_id="SIG-REF-TODAY",
        email="referral@example.hu",
        status="queued",
    )
    referral.source_bucket = "referral_partner"
    old = _signal(
        signal_id="SIG-ARCH-YESTERDAY",
        email="old@example.hu",
        status="contacted",
    )
    db.add_all(
        [
            architect,
            referral,
            old,
            _outreach(
                outreach_id="OUT-ARCH-TODAY",
                signal_id=architect.signal_id,
                email="architect@example.hu",
                status="queued",
                sent_at=None,
            ),
            _outreach(
                outreach_id="OUT-REF-TODAY",
                signal_id=referral.signal_id,
                email="referral@example.hu",
                status="queued",
                sent_at=None,
            ),
            _outreach(
                outreach_id="OUT-ARCH-YESTERDAY",
                signal_id=old.signal_id,
                email="old@example.hu",
                status="sent",
                sent_at=datetime.now(UTC) - timedelta(days=1),
            ),
        ]
    )
    db.commit()
    yesterday = datetime.now(UTC) - timedelta(days=1)
    db.scalar(
        select(OutreachMessage).where(
            OutreachMessage.outreach_id == "OUT-ARCH-YESTERDAY"
        )
    ).created_at = yesterday
    db.commit()

    assert partnerpoint._partner_lane_created_today(db) == {
        "architect_office": 1,
        "referral_partner": 1,
    }
    assert partnerpoint._partner_external_keys_created_today(db) == {
        architect.external_key,
        referral.external_key,
    }


def test_partnerpoint_control_state_keeps_large_json_valid(db):
    detail = {
        "status": "healthy",
        "receipts": [
            {"candidate_id": f"PC-ARCH-{index:03d}", "status": "queued"}
            for index in range(100)
        ],
    }
    reason = json.dumps(detail, ensure_ascii=False, sort_keys=True)
    assert len(reason) > 4000

    partnerpoint._state(
        db,
        "partnerpoint:test-large-state",
        enabled=True,
        reason=reason,
    )

    stored = db.get(GrowthControlState, "partnerpoint:test-large-state")
    assert stored is not None
    assert json.loads(stored.reason) == detail


def test_partnerpoint_source_follows_same_domain_contact_page_for_public_email(monkeypatch):
    candidate = {
        "source_url": "https://example.hu/team",
        "email": "office@example.hu",
        "recipient_type": "architect_office",
        "company": "Példa Építésziroda Kft.",
        "organization_marker": "Példa",
        "recipient_name": "",
    }
    fetched: list[str] = []

    def fetch(url, **_kwargs):
        fetched.append(url)
        body = (
            '<a href="/kapcsolat">Kapcsolat</a>'
            if url != "https://example.hu/kapcsolat"
            else '<a href="mailto:office@example.hu">office@example.hu</a>'
        )
        return (
            SimpleNamespace(
                http_status=200,
                content_type="text/html; charset=utf-8",
                content_sha256="a" * 64,
            ),
            body,
        )

    monkeypatch.setattr(partnerpoint, "_fetch_html", fetch)

    source_id, source = partnerpoint._source_entry(
        candidate,
        architect_authority={"registry_id": "ARCHITECT_FIXTURE"},
    )

    assert source_id == "DYNAMIC_HU_EXAMPLE_HU"
    assert source["url"] == "https://example.hu/kapcsolat"
    assert source["public_contact_url"] == "https://example.hu/kapcsolat"
    assert (
        source["recipient_binding"]["verification_policy"]
        == service.GrowthRegistry.PARTNERPOINT_PUBLIC_EMAIL_POLICY
    )
    assert fetched == [
        "https://example.hu/team",
        "https://example.hu/",
        "https://example.hu/kapcsolat",
    ]


def test_partnerpoint_source_rejects_contact_pages_without_the_public_email(monkeypatch):
    candidate = {
        "source_url": "https://example.hu/team",
        "email": "office@example.hu",
        "recipient_type": "architect_office",
        "company": "Példa Építésziroda Kft.",
        "organization_marker": "Példa",
        "recipient_name": "",
    }

    monkeypatch.setattr(
        partnerpoint,
        "_fetch_html",
        lambda *_args, **_kwargs: (
            SimpleNamespace(
                http_status=200,
                content_type="text/html; charset=utf-8",
                content_sha256="b" * 64,
            ),
            '<a href="/kapcsolat">Kapcsolat</a>',
        ),
    )

    with pytest.raises(
        partnerpoint.GrowthRegistryError,
        match="partnerpoint_official_email_not_visible",
    ):
        partnerpoint._source_entry(
            candidate,
            architect_authority={"registry_id": "ARCHITECT_FIXTURE"},
        )


def test_unsubscribe_stops_the_corporate_account_without_touching_other_domains(db):
    first = _signal(signal_id="SIG-DNC-SENT", email="info@example.hu", status="contacted")
    sibling = _signal(signal_id="SIG-DNC-PENDING", email="sales@example.hu", status="queued")
    other = _signal(signal_id="SIG-DNC-OTHER", email="info@other.hu", status="queued")
    db.add_all(
        [
            first,
            sibling,
            other,
            _outreach(
                outreach_id="OUT-DNC-SENT",
                signal_id=first.signal_id,
                email="info@example.hu",
                status="sent",
                sent_at=datetime.now(UTC) - timedelta(days=1),
            ),
            _outreach(
                outreach_id="OUT-DNC-PENDING",
                signal_id=sibling.signal_id,
                email="sales@example.hu",
                status="queued",
                sent_at=None,
            ),
            _outreach(
                outreach_id="OUT-DNC-OTHER",
                signal_id=other.signal_id,
                email="info@other.hu",
                status="queued",
                sent_at=None,
            ),
        ]
    )
    db.commit()

    service.record_outreach_event(
        db,
        "OUT-DNC-SENT",
        service.OutreachEventIn(event_type="unsubscribe", provider_event_id="UNSUB-1"),
    )

    assert db.get(OutreachMessage, sibling.id).status == "blocked"
    assert db.get(OutreachMessage, sibling.id).last_error == "STOP_DNC"
    assert db.get(OutreachMessage, other.id).status == "queued"
    stop = db.scalar(
        select(GrowthAccountStop).where(GrowthAccountStop.source_event_id == "UNSUB-1")
    )
    assert stop.account_key == "domain:example.hu"
    assert stop.stop_kind == "dnc"


def test_bounce_blocks_only_the_failed_mailbox_route(db):
    failed = _signal(signal_id="SIG-BOUNCE-SENT", email="info@example.hu", status="contacted")
    same_mailbox = _signal(signal_id="SIG-BOUNCE-SAME", email="info@example.hu", status="queued")
    sibling = _signal(signal_id="SIG-BOUNCE-SIBLING", email="sales@example.hu", status="queued")
    db.add_all(
        [
            failed,
            same_mailbox,
            sibling,
            _outreach(
                outreach_id="OUT-BOUNCE-SENT",
                signal_id=failed.signal_id,
                email="info@example.hu",
                status="sent",
                sent_at=datetime.now(UTC) - timedelta(days=1),
            ),
            _outreach(
                outreach_id="OUT-BOUNCE-SAME",
                signal_id=same_mailbox.signal_id,
                email="info@example.hu",
                status="queued",
                sent_at=None,
            ),
            _outreach(
                outreach_id="OUT-BOUNCE-SIBLING",
                signal_id=sibling.signal_id,
                email="sales@example.hu",
                status="queued",
                sent_at=None,
            ),
        ]
    )
    db.commit()

    service.record_outreach_event(
        db,
        "OUT-BOUNCE-SENT",
        service.OutreachEventIn(event_type="bounce", provider_event_id="BOUNCE-1"),
    )

    assert db.get(OutreachMessage, same_mailbox.id).status == "blocked"
    assert db.get(OutreachMessage, same_mailbox.id).last_error == "STOP_BOUNCE"
    assert db.get(OutreachMessage, sibling.id).status == "queued"
    stop = db.scalar(
        select(GrowthAccountStop).where(GrowthAccountStop.source_event_id == "BOUNCE-1")
    )
    assert stop.account_key == "email:info@example.hu"
    assert stop.stop_kind == "bounce"


def test_stop_upsert_is_idempotent_before_a_no_autoflush_session_flush(db):
    db.autoflush = False
    when = datetime.now(UTC)

    first, first_created, _ = service.upsert_account_stop(
        db,
        recipient_email="info@example.hu",
        stop_kind="existing_relationship",
        source="partnerpoint_control",
        source_event_id="PC-EXISTING-1",
        reason="fixture",
        occurred_at=when,
    )
    second, second_created, _ = service.upsert_account_stop(
        db,
        recipient_email="sales@example.hu",
        stop_kind="existing_relationship",
        source="partnerpoint_control",
        source_event_id="PC-EXISTING-1",
        reason="fixture",
        occurred_at=when,
    )
    db.commit()

    assert first is second
    assert first_created is True
    assert second_created is False
    assert (
        db.scalar(
            select(service.func.count())
            .select_from(GrowthAccountStop)
            .where(GrowthAccountStop.source_event_id == "PC-EXISTING-1")
        )
        == 1
    )


def test_daily_checkpoint_keeps_sent_and_readback_as_distinct_kpis(db, monkeypatch):
    monkeypatch.setattr(
        partnerpoint,
        "settings",
        lambda: SimpleNamespace(partnerpoint_enabled=True, timezone="Europe/Budapest"),
    )
    sheet = [[f"h{number}" for number in range(21)], ["EXISTING", *([""] * 20)]]

    def snapshot():
        return {"Run_Checkpoints": [list(row) for row in sheet]}

    def update(_token, data):
        row_number = int(data[0]["range"].split("A", 1)[1].split(":", 1)[0])
        values = list(data[0]["values"][0])
        while len(sheet) < row_number:
            sheet.append([])
        sheet[row_number - 1] = values

    monkeypatch.setattr(partnerpoint, "fetch_snapshot", snapshot)
    monkeypatch.setattr(partnerpoint, "_sheet_token", lambda: "token")
    monkeypatch.setattr(partnerpoint, "_copy_checkpoint_row_format", lambda *_a, **_k: None)
    monkeypatch.setattr(partnerpoint, "_values_batch_update", update)
    lanes = {
        "architect": {
            "discovered": 5,
            "qualified": 5,
            "ready": 5,
            "queued": 5,
            "sent": 1,
            "readback_verified": 1,
            "replies": 0,
            "followups": 0,
            "blocked": 3,
        },
        "referral": {
            "discovered": 2,
            "qualified": 1,
            "ready": 1,
            "queued": 1,
            "sent": 0,
            "readback_verified": 0,
            "replies": 0,
            "followups": 0,
            "blocked": 1,
        },
        "real_estate": {
            key: 0
            for key in (
                "discovered",
                "qualified",
                "ready",
                "queued",
                "sent",
                "readback_verified",
                "replies",
                "followups",
                "blocked",
            )
        },
    }

    result = partnerpoint.write_daily_checkpoint(
        db,
        outbound={
            "status": "degraded",
            "fatal": [],
            "degraded": ["referral_ready_without_sent"],
            "queue_backlog": 5,
            "lanes": lanes,
        },
        writeback={"status": "healthy", "updated": 1, "failed": 0},
    )

    assert result["status"] == "healthy"
    saved = sheet[result["row"] - 1]
    assert saved[12] == 1
    assert saved[13] == 1
    assert saved[14] == "DEGRADED"


def test_legacy_reconciliation_set_preserves_two_rescoped_banati_rows():
    header = [f"h{number}" for number in range(15)]
    legacy = [""] * 15
    legacy[0] = "OUT-LEGACY-1"
    legacy[5] = "CENTRAL_QUEUE_HANDOFF_BLOCKED_ADAPTER_UNAVAILABLE"
    replied = [""] * 15
    replied[0] = "OUT-260825-002"
    replied[5] = "REPLIED"
    stopped_followup = [""] * 15
    stopped_followup[0] = "FU-260829-005"
    stopped_followup[5] = "NO_ACTION"
    unrelated = [""] * 15
    unrelated[0] = "OUT-OTHER"
    unrelated[7] = "Központi megjegyzés, de nem a történeti átadási sor része"

    selected = _historical_control_rows([header, legacy, replied, stopped_followup, unrelated])

    assert [row[0] for _number, row in selected] == [
        "OUT-LEGACY-1",
        "OUT-260825-002",
        "FU-260829-005",
    ]


def test_partnerpoint_copy_gate_accepts_only_the_two_owner_approved_template_types():
    registry_path = (
        Path(__file__).resolve().parents[3]
        / "config"
        / "outbound"
        / "canonical_first_contact_templates_hu_v1.json"
    )
    templates = {
        item["recipient_type"]: item["owner_approved_body_text"]
        for item in json.loads(registry_path.read_text(encoding="utf-8"))["templates"]
    }

    canonical_policy.assert_partnerpoint_outreach_copy(
        templates["architect_office"], recipient_type="architect_office"
    )
    canonical_policy.assert_partnerpoint_outreach_copy(
        templates["referral_partner"], recipient_type="referral_partner"
    )
    assert "2,5%" not in templates["architect_office"]
    with pytest.raises(ValueError, match="architect_outreach_copy_invalid"):
        canonical_policy.assert_partnerpoint_outreach_copy(
            templates["architect_office"] + " 2,5%", recipient_type="architect_office"
        )
