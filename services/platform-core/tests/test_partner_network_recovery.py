from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select, text

from app.growth_ops import partnerpoint, service
from app.growth_ops.models import GrowthAccountStop, GrowthSignal, OutreachMessage


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


def test_partnerpoint_candidate_filter_keeps_only_exact_current_pass_rows(monkeypatch):
    monkeypatch.setenv("GROWTH_PARTNERPOINT_ARCHITECT_DAILY_MAX", "8")
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
    manual = list(eligible)
    manual[0] = "PC-MANUAL"
    manual[1] = "Hofstädter Építőanyag Centrum Kft."
    manual[3] = partnerpoint.PARTNERPOINT_READY_STATUS
    manual[18] = "REFERRAL_PARTNER_FIRST_CONTACT_HU"
    manual[21] = "OWNER_MANUAL_ONLY"

    result = partnerpoint._candidate_rows({"Partner_Universe": [header, eligible, stale, manual]})

    assert [item["candidate_id"] for item in result] == ["PC-260908-A01"]


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
