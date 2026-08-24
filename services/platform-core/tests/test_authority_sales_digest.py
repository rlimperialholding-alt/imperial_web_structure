from __future__ import annotations

import base64
import ipaddress
import json
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser

import httpx
import pytest
from sqlalchemy import select

from app.authority_reader.config import ReaderSettings
from app.authority_reader.models import (
    AuthorityDetailRevision,
    AuthorityRecord,
    AuthoritySalesDigestItem,
    AuthoritySignalOutbox,
)
from app.authority_reader.sales_digest import (
    DigestBlocked,
    GmailDigestAdapter,
    GmailReceipt,
    create_digest,
    dispatch_digest,
    load_oauth,
    run_once,
)
from app.authority_reader.service import canonical_json, sha


def _settings(tmp_path, **overrides) -> ReaderSettings:
    recipients = tmp_path / "recipients.json"
    recipients.write_text(
        json.dumps(
            {
                "schema_version": "internal-sales-digest-v1",
                "purpose": "internal_sales_digest",
                "approved_by": "owner-test",
                "valid_until": "2099-01-01T00:00:00Z",
                "recipients": [{"email": "sales@example.com", "role": "sales"}],
            }
        ),
        encoding="utf-8",
    )
    oauth = tmp_path / "oauth.json"
    oauth.write_text(
        json.dumps(
            {
                "client_id": "client-id-that-is-long-enough",
                "client_secret": "client-secret-that-is-long-enough",
                "refresh_token": "refresh-token-that-is-long-enough-for-tests",
                "scope": "https://www.googleapis.com/auth/gmail.modify",
                "token_type": "Bearer",
            }
        ),
        encoding="utf-8",
    )
    values = {
        "enabled": True,
        "policy_authorized": True,
        "policy_evidence_valid": True,
        "policy_evidence_sha256": "e" * 64,
        "etdr_base_url": "https://alk.etdr.gov.hu",
        "etdr_public_url": "https://www.etdr.gov.hu",
        "oeny_base_url": "https://www.oeny.hu",
        "oeny_enabled": False,
        "internal_token": "internal-test-token-that-is-more-than-32-chars",
        "hmac_key": "hmac-test-key-that-is-more-than-32-characters",
        "worker_id": "digest-test-worker",
        "poll_seconds": 60,
        "interval_hours": 24,
        "overlap_days": 7,
        "page_size": 100,
        "request_delay_seconds": 1.0,
        "request_timeout_seconds": 10.0,
        "max_response_bytes": 1_000_000,
        "max_pages_per_run": 100,
        "lease_seconds": 300,
        "detail_enabled": True,
        "lead_export_enabled": True,
        "schedule_enabled": True,
        "sales_digest_enabled": True,
        "sales_digest_authorized": True,
        "sales_digest_oauth_file": str(oauth),
        "sales_digest_recipients_file": str(recipients),
    }
    values.update(overrides)
    return ReaderSettings(**values)


def _lead(db, *, process_number: str, created_at: datetime) -> AuthoritySignalOutbox:
    record = AuthorityRecord(
        record_id=f"digest-record-{process_number}",
        source_key="etdr_public",
        external_key_hmac=sha({"process": process_number}),
        public_process_number=process_number,
        city="Tesztváros",
        topographical_number="42/7",
        procedure_type="Építési engedélyezési eljárás",
        construction_activity="Új lakóépület építése",
        submission_date=datetime(2026, 8, 20, 10, tzinfo=UTC),
        evidence_url=f"https://www.etdr.gov.hu/nyilvanos-adatok/{process_number}",
        current_revision_no=1,
        current_payload_sha256="a" * 64,
        current_detail_revision_no=1,
        current_detail_payload_sha256="b" * 64,
        detail_status="current",
    )
    detail_id = f"etdrd-{process_number}"
    detail = AuthorityDetailRevision(
        detail_revision_id=detail_id,
        record_id=record.record_id,
        source_revision_id=f"etdrr-{process_number}",
        revision_no=1,
        payload_sha256="b" * 64,
        normalized_json=canonical_json(
            {
                "process_number": process_number,
                "subject": "Új lakóépület építése",
                "procedure_type": "Építési engedélyezési eljárás",
                "status": "Ügyintézés",
                "submission_date": "2026-08-20",
                "property_address": "1234 Tesztváros, Minta utca 7.",
                "topographical_number": "42/7",
                "authority_name": "Teszt Vármegyei Kormányhivatal",
                "decisions": [],
                "documents": [],
            }
        ),
    )
    outbox = AuthoritySignalOutbox(
        idempotency_key=sha({"digest": process_number}),
        record_id=record.record_id,
        revision_id=detail_id,
        payload_sha256="c" * 64,
        payload_json=canonical_json(
            {
                "schema_version": "etdr-lead-v2",
                "lead_reason": "new_submission",
                "confidence": 92,
                "urgency": 90,
            }
        ),
        status="delivered",
        reason_code="daily_lead_generator_imported",
        created_at=created_at,
        delivered_at=created_at,
    )
    db.add_all((record, detail, outbox))
    db.commit()
    return outbox


class FakeAdapter:
    sent: list[bytes] = []
    reconciled: GmailReceipt | None = None

    def __init__(self, _secret) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def preflight(self) -> str:
        return "info@imperialholding.hu"

    def find_sent(self, _message_id: str) -> GmailReceipt | None:
        return self.reconciled

    def send(self, raw_message: bytes) -> GmailReceipt:
        self.sent.append(raw_message)
        return GmailReceipt("gmail-message-1", "gmail-thread-1")


@pytest.fixture(autouse=True)
def _reset_adapter():
    FakeAdapter.sent = []
    FakeAdapter.reconciled = None


def test_digest_sends_each_day_once_and_contains_only_verified_public_fields(db, tmp_path):
    now = datetime(2026, 8, 24, 13, tzinfo=UTC)
    _lead(db, process_number="202600070207", created_at=now - timedelta(hours=1))
    active = _settings(tmp_path)

    first = run_once(db, active, force=True, now=now, adapter_factory=FakeAdapter)
    second = run_once(db, active, force=True, now=now, adapter_factory=FakeAdapter)

    assert first is not None and first.status == "sent" and first.item_count == 1
    assert second is not None and second.digest_id == first.digest_id
    assert len(FakeAdapter.sent) == 1
    message = BytesParser(policy=policy.default).parsebytes(FakeAdapter.sent[0])
    assert message["To"] == "sales@example.com"
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "202600070207" in body
    assert "1234 Tesztváros, Minta utca 7." in body
    assert "nincs ellenőrzött üzleti e-mail/telefon" in body
    assert "https://www.etdr.gov.hu/nyilvanos-adatok/202600070207" in body


def test_digest_payload_tamper_is_dead_lettered_before_gmail(db, tmp_path):
    now = datetime(2026, 8, 24, 13, tzinfo=UTC)
    _lead(db, process_number="202600070208", created_at=now)
    active = _settings(tmp_path)
    digest = create_digest(db, active, now=now, force=True)
    assert digest is not None
    digest_item = db.scalar(
        select(AuthoritySalesDigestItem).where(
            AuthoritySalesDigestItem.digest_id == digest.digest_id
        )
    )
    assert digest_item is not None
    digest_item.item_snapshot_json = digest_item.item_snapshot_json.replace(
        "Új lakóépület", "Manipulált épület"
    )
    db.commit()
    digest.status = "claimed"
    db.commit()

    result = dispatch_digest(db, active, digest, adapter_factory=FakeAdapter)
    assert result.status == "dead_letter"
    assert result.last_error == "digest_payload_hash_mismatch"
    assert FakeAdapter.sent == []


def test_digest_approval_evidence_change_is_dead_lettered_before_gmail(db, tmp_path):
    now = datetime(2026, 8, 24, 13, tzinfo=UTC)
    _lead(db, process_number="202600070210", created_at=now)
    active = _settings(tmp_path)
    digest = create_digest(db, active, now=now, force=True)
    assert digest is not None
    recipient_file = tmp_path / "recipients.json"
    payload = json.loads(recipient_file.read_text(encoding="utf-8"))
    payload["approved_by"] = "changed-after-freeze"
    recipient_file.write_text(json.dumps(payload), encoding="utf-8")
    digest.status = "claimed"
    db.commit()

    result = dispatch_digest(db, active, digest, adapter_factory=FakeAdapter)
    assert result.status == "dead_letter"
    assert result.last_error == "digest_recipients_changed"
    assert FakeAdapter.sent == []


def test_digest_reconciles_ambiguous_prior_send_without_duplicate(db, tmp_path):
    now = datetime(2026, 8, 24, 13, tzinfo=UTC)
    _lead(db, process_number="202600070209", created_at=now)
    active = _settings(tmp_path)
    digest = create_digest(db, active, now=now, force=True)
    assert digest is not None
    digest.status = "claimed"
    db.commit()
    FakeAdapter.reconciled = GmailReceipt("existing-message", "existing-thread", True)

    result = dispatch_digest(db, active, digest, adapter_factory=FakeAdapter)
    assert result.status == "sent"
    assert result.gmail_message_id == "existing-message"
    assert result.last_error == "reconciled_after_ambiguous_send"
    assert FakeAdapter.sent == []


def test_digest_is_fail_closed_without_explicit_delivery_authorization(db, tmp_path):
    active = _settings(tmp_path, sales_digest_authorized=False)
    with pytest.raises(DigestBlocked, match="sales_digest_policy_gate"):
        create_digest(db, active, force=True)


def test_empty_digest_is_audited_but_not_emailed(db, tmp_path):
    result = run_once(db, _settings(tmp_path), force=True, adapter_factory=FakeAdapter)
    assert result is not None and result.status == "skipped" and result.item_count == 0
    assert FakeAdapter.sent == []


def test_gmail_adapter_uses_refresh_token_reconciles_and_sends(tmp_path):
    active = _settings(tmp_path)
    requests: list[httpx.Request] = []

    def oauth_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"access_token": "access-token-that-is-long-enough"})

    def gmail_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "info@imperialholding.hu"})
        if request.method == "GET":
            return httpx.Response(200, json={"resultSizeEstimate": 0})
        raw = json.loads(request.content)["raw"]
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        assert b"Message-ID: <digest-test@digest.imperialholding.hu>" in decoded
        return httpx.Response(200, json={"id": "sent-id", "threadId": "thread-id"})

    def resolver(_host, _port):
        return {ipaddress.ip_address("93.184.216.34")}
    with GmailDigestAdapter(
        load_oauth(active),
        oauth_transport=httpx.MockTransport(oauth_handler),
        gmail_transport=httpx.MockTransport(gmail_handler),
        resolver=resolver,
    ) as adapter:
        assert adapter.preflight() == "info@imperialholding.hu"
        assert adapter.find_sent("<digest-test@digest.imperialholding.hu>") is None
        receipt = adapter.send(b"Message-ID: <digest-test@digest.imperialholding.hu>\r\n\r\nTest")
    assert receipt.message_id == "sent-id"
    assert requests[0].url.host == "oauth2.googleapis.com"
    assert requests[-1].url.host == "gmail.googleapis.com"
