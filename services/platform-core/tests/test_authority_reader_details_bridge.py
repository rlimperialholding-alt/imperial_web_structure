from __future__ import annotations

import ipaddress
import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.authority_reader.client import (
    ETDRDecision,
    ETDRDetail,
    ETDRDetailClient,
    ETDRDocument,
    ETDRPage,
    ETDRRecord,
    ReaderBlocked,
)
from app.authority_reader.config import ReaderSettings
from app.authority_reader.lead_bridge import ETDRLeadPayload, bridge_once
from app.authority_reader.models import (
    AuthorityDetailQueue,
    AuthorityDetailRevision,
    AuthorityRecord,
    AuthoritySignalOutbox,
)
from app.authority_reader.routes import lead_feed
from app.authority_reader.service import (
    _lead_decision,
    _listing_may_qualify,
    canonical_json,
    process_details,
    requalify_waiting_leads,
    run_reader,
    sha,
)
from app.database import SessionLocal
from app.growth_ops.models import GrowthSignal


def settings(**overrides) -> ReaderSettings:
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
        "worker_id": "test-reader",
        "poll_seconds": 60,
        "interval_hours": 24,
        "overlap_days": 7,
        "page_size": 100,
        "request_delay_seconds": 0.0,
        "request_timeout_seconds": 10.0,
        "max_response_bytes": 1_000_000,
        "max_pages_per_run": 100,
        "lease_seconds": 300,
        "detail_enabled": True,
        "lead_export_enabled": True,
        "detail_batch_size": 100,
    }
    values.update(overrides)
    return ReaderSettings(**values)


def detail_html(*, process_number: str = "202600063601", unsafe_document: bool = False) -> bytes:
    href = (
        "https://evil.example/file.pdf"
        if unsafe_document
        else "/PublicProcessData/DownloadDocument/51691180?"
        "guid=f9c48962-ad6c-4ad0-8411-95fb6482d07c"
    )
    return f"""<!doctype html><html><body>
<dap-ds-card class="details-card">
<dap-ds-card-title><dap-ds-typography variant="h3">Gazdasági épület építése</dap-ds-typography>
<dap-ds-label description="Azonosító: {process_number}"></dap-ds-label></dap-ds-card-title>
<dap-ds-card-content>
<dap-ds-stack><span class="label-big">Eljárás adatai</span>
<dap-ds-stack><div class="label-small">Eljárás típusa</div>
<div class="item">Építési engedélyezési eljárás</div></dap-ds-stack>
<dap-ds-stack><div class="label-small">Státusz</div>
<div class="item">Véglegessé vált döntés</div></dap-ds-stack>
<dap-ds-stack><div class="label-small">Benyújtás dátuma</div>
<div class="item">2026. 07. 29.</div></dap-ds-stack>
</dap-ds-stack>
<dap-ds-stack><span class="label-big">Hatósági irat típusa, dátuma és döntés rövid tartalma</span>
<dap-ds-accordion><span class="label-small" slot="heading">Engedély</span>
<span class="accordion-date" slot="heading">2026-08-19</span>
<dap-ds-typography variant="body">Gazdasági épület építésének engedélyezése</dap-ds-typography>
</dap-ds-accordion></dap-ds-stack>
<dap-ds-stack><span class="label-big">Ingatlan adatai</span>
<dap-ds-stack><div class="label-small">Cím</div><div class="item">8272 Óbudavár</div></dap-ds-stack>
<dap-ds-stack><div class="label-small">Helyrajzi szám</div>
<div class="item">243</div></dap-ds-stack>
</dap-ds-stack>
<dap-ds-stack><span class="label-big">Hatóság neve</span>
<div class="item">Veszprém Vármegyei Kormányhivatal</div></dap-ds-stack>
<div class="document-row"><dap-ds-link href="{href}">Helyszínrajz.pdf</dap-ds-link></div>
</dap-ds-card-content></dap-ds-card></body></html>""".encode()


def detail_client(body: bytes) -> ETDRDetailClient:
    return ETDRDetailClient(
        settings(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, content=body, headers={"content-type": "text/html; charset=utf-8"}
            )
        ),
        resolver=lambda _host, _port: {ipaddress.ip_address("93.184.216.34")},
    )


def test_detail_client_parses_public_procedure_decision_and_document_link():
    with detail_client(detail_html()) as client:
        detail = client.fetch_detail("202600063601")
    assert detail.subject == "Gazdasági épület építése"
    assert detail.status == "Véglegessé vált döntés"
    assert detail.submission_date == date(2026, 7, 29)
    assert detail.decisions[0].decision_type == "Engedély"
    assert detail.documents[0].download_url.startswith("https://www.etdr.gov.hu/")


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (detail_html(process_number="202600000000"), "detail_identity_mismatch"),
        (detail_html(unsafe_document=True), "detail_unsafe_document_link"),
    ],
)
def test_detail_client_fails_closed_on_identity_or_document_origin(body, code):
    with detail_client(body) as client, pytest.raises(ReaderBlocked, match=code):
        client.fetch_detail("202600063601")


class ListClient:
    def __init__(self, _settings: ReaderSettings) -> None:
        self.used = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_page(self, **_kwargs) -> ETDRPage:
        assert not self.used
        self.used = True
        row = ETDRRecord.model_validate(
            {
                "ConstructionActivity": "Gazdasági épület építése",
                "Street": None,
                "HouseNumber": None,
                "City": "Óbudavár",
                "StreetType": None,
                "TopographicalNumber": "243",
                "Type": "Építési engedélyezési eljárás",
                "ProcessNumber": "202600063601",
                "SubmissionDate": "2026-07-29T12:00:00+02:00",
                "FullAddress": "8272 Óbudavár",
            }
        )
        return ETDRPage(total=1, records=(row,), payload_sha256="a" * 64)


class DetailClient:
    def __init__(self, _settings: ReaderSettings) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_detail(self, _process_number: str) -> ETDRDetail:
        return ETDRDetail(
            process_number="202600063601",
            subject="Gazdasági épület építése",
            procedure_type="Építési engedélyezési eljárás",
            status="Véglegessé vált döntés",
            submission_date=date(2026, 7, 29),
            property_address="8272 Óbudavár",
            topographical_number="243",
            authority_name="Veszprém Vármegyei Kormányhivatal",
            decisions=(
                ETDRDecision(
                    decision_type="Engedély",
                    decision_date=date(2026, 8, 19),
                    summary="Gazdasági épület építésének engedélyezése",
                ),
            ),
            documents=(
                ETDRDocument(
                    name="Helyszínrajz.pdf",
                    download_url=(
                        "https://www.etdr.gov.hu/PublicProcessData/DownloadDocument/51691180?"
                        "guid=f9c48962-ad6c-4ad0-8411-95fb6482d07c"
                    ),
                ),
            ),
        )


class TwoRecordListClient:
    def __init__(self, _settings: ReaderSettings) -> None:
        self.used = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_page(self, **_kwargs) -> ETDRPage:
        assert not self.used
        self.used = True
        records = tuple(
            ETDRRecord.model_validate(
                {
                    "ConstructionActivity": "Gazdasági épület építése",
                    "Street": None,
                    "HouseNumber": None,
                    "City": "Óbudavár",
                    "StreetType": None,
                    "TopographicalNumber": topographical_number,
                    "Type": "Építési engedélyezési eljárás",
                    "ProcessNumber": process_number,
                    "SubmissionDate": "2026-07-29T12:00:00+02:00",
                    "FullAddress": "8272 Óbudavár",
                }
            )
            for process_number, topographical_number in (
                ("202600000001", "241"),
                ("202600000002", "242"),
            )
        )
        return ETDRPage(total=2, records=records, payload_sha256="b" * 64)


class FirstBlockedDetailClient(DetailClient):
    def fetch_detail(self, process_number: str) -> ETDRDetail:
        if process_number == "202600000001":
            raise ReaderBlocked("detail_schema_drift")
        detail = super().fetch_detail(process_number)
        return detail.model_copy(
            update={
                "process_number": process_number,
                "topographical_number": "242",
            }
        )


def test_detail_pipeline_creates_strict_pending_lead(db):
    active = settings()
    run_reader(
        db,
        active,
        mode="pilot",
        town="Óbudavár",
        trigger="test",
        client_factory=ListClient,
    )
    queue = db.scalar(select(AuthorityDetailQueue))
    assert queue.status == "pending"
    result = process_details(db, active, client_factory=DetailClient)
    assert result == {"completed": 1, "unchanged": 0, "blocked": 0}
    record = db.scalar(select(AuthorityRecord))
    assert record.detail_status == "current"
    assert record.current_detail_revision_no == 1
    assert db.scalar(select(func.count()).select_from(AuthorityDetailRevision)) == 1
    leads = db.scalars(
        select(AuthoritySignalOutbox).where(AuthoritySignalOutbox.status == "pending")
    ).all()
    assert len(leads) == 1
    payload = json.loads(leads[0].payload_json)
    assert payload["subject_type"] == "project"
    assert payload["schema_version"] == "etdr-lead-v2"
    assert payload["lead_reason"] == "recently_authorized"
    assert "construction_intent_procedure" in payload["qualification_evidence"]
    assert "positive_permit_decision_within_120_days" in payload["qualification_evidence"]
    assert payload["recipient_email"] is None
    assert payload["contact_basis"] == "unknown"
    assert payload["revision_id"].startswith("etdrd-")
    assert payload["revision_no"] == 1
    assert payload["rejection_reasons"] == sorted(payload["rejection_reasons"])


def _qualification_record(
    db,
    *,
    process_number: str,
    submitted_at: datetime,
    parcel: str | None,
    procedure_type: str = "Építési engedélyezési eljárás",
    construction_activity: str = "Új lakóépület építése",
) -> AuthorityRecord:
    record = AuthorityRecord(
        record_id=f"test-record-{process_number}",
        source_key="etdr_public",
        external_key_hmac=sha({"process_number": process_number}),
        public_process_number=process_number,
        city="Tesztváros",
        topographical_number=parcel,
        procedure_type=procedure_type,
        construction_activity=construction_activity,
        submission_date=submitted_at,
        evidence_url=f"https://www.etdr.gov.hu/nyilvanos-adatok/{process_number}",
        current_revision_no=1,
        current_payload_sha256=sha({"listing": process_number}),
    )
    db.add(record)
    db.flush()
    return record


def _qualification_detail(
    record: AuthorityRecord,
    *,
    status: str = "Véglegessé vált döntés",
) -> ETDRDetail:
    return ETDRDetail(
        process_number=record.public_process_number,
        subject=record.construction_activity,
        procedure_type=record.procedure_type,
        status=status,
        submission_date=record.submission_date.date(),
        property_address=f"Tesztváros, hrsz. {record.topographical_number or 'nincs'}",
        topographical_number=record.topographical_number,
        authority_name="Teszt Vármegyei Kormányhivatal",
        decisions=(),
        documents=(),
    )


def test_lead_qualification_selects_new_and_recent_no_completion_signals(db):
    as_of = datetime(2026, 8, 24, 12, tzinfo=UTC)
    active = settings()
    new_record = _qualification_record(
        db,
        process_number="202600000101",
        submitted_at=as_of - timedelta(days=10),
        parcel="101",
    )
    stalled_record = _qualification_record(
        db,
        process_number="202500000202",
        submitted_at=as_of - timedelta(days=365),
        parcel="202",
    )

    new_decision = _lead_decision(
        db, active, _qualification_detail(new_record), new_record, as_of=as_of
    )
    stalled_decision = _lead_decision(
        db, active, _qualification_detail(stalled_record), stalled_record, as_of=as_of
    )
    assert new_decision.eligible and new_decision.reason == "new_submission"
    assert stalled_decision.eligible and stalled_decision.reason == "no_completion_signal"


def test_lead_qualification_suppresses_duplicate_property_and_completed_project(db):
    as_of = datetime(2026, 8, 24, 12, tzinfo=UTC)
    active = settings()
    older = _qualification_record(
        db,
        process_number="202500000301",
        submitted_at=as_of - timedelta(days=365),
        parcel="301",
    )
    _qualification_record(
        db,
        process_number="202600000302",
        submitted_at=as_of - timedelta(days=5),
        parcel="301",
    )
    completed_candidate = _qualification_record(
        db,
        process_number="202500000401",
        submitted_at=as_of - timedelta(days=365),
        parcel="401",
    )
    _qualification_record(
        db,
        process_number="202600000402",
        submitted_at=as_of - timedelta(days=5),
        parcel="401",
        procedure_type="Használatbavételi eljárás",
        construction_activity="Lakóépület használatbavétele",
    )

    duplicate = _lead_decision(
        db, active, _qualification_detail(older), older, as_of=as_of
    )
    completed = _lead_decision(
        db,
        active,
        _qualification_detail(completed_candidate),
        completed_candidate,
        as_of=as_of,
    )
    assert not duplicate.eligible
    assert duplicate.reason == "superseded_by_later_property_filing"
    assert not completed.eligible
    assert completed.reason == "later_completion_signal_found"


def test_lead_qualification_labels_recent_discontinued_project_as_likely_not_started(db):
    as_of = datetime(2026, 8, 24, 12, tzinfo=UTC)
    record = _qualification_record(
        db,
        process_number="202600000501",
        submitted_at=as_of - timedelta(days=20),
        parcel="501",
    )
    decision = _lead_decision(
        db,
        settings(),
        _qualification_detail(record, status="Megszüntetve"),
        record,
        as_of=as_of,
    )
    assert decision.eligible
    assert decision.reason == "likely_not_started"


def test_lead_qualification_prioritizes_recent_positive_permit_decision(db):
    as_of = datetime(2026, 8, 24, 12, tzinfo=UTC)
    record = _qualification_record(
        db,
        process_number="202600000511",
        submitted_at=as_of - timedelta(days=60),
        parcel="511",
    )
    detail = _qualification_detail(record).model_copy(
        update={
            "decisions": (
                ETDRDecision(
                    decision_type="Építési engedély",
                    decision_date=date(2026, 8, 20),
                    summary="Új lakóépület építésének engedélyezése",
                ),
            )
        }
    )
    decision = _lead_decision(db, settings(), detail, record, as_of=as_of)
    assert decision.eligible
    assert decision.reason == "recently_authorized"
    assert "positive_permit_decision_within_120_days" in decision.evidence


def test_lead_qualification_rejects_completion_text_hidden_in_permit_type(db):
    as_of = datetime(2026, 8, 24, 12, tzinfo=UTC)
    record = _qualification_record(
        db,
        process_number="202500000551",
        submitted_at=as_of - timedelta(days=365),
        parcel="551",
        construction_activity=(
            "Lakóépület használatbavétel, hatósági bizonyítvány kérése"
        ),
    )
    decision = _lead_decision(
        db,
        settings(),
        _qualification_detail(record),
        record,
        as_of=as_of,
    )
    assert not decision.eligible
    assert decision.reason == "current_completion_signal"


def test_listing_prefilter_excludes_completion_procedure():
    as_of = datetime(2026, 8, 24, 12, tzinfo=UTC)
    active = settings()
    assert _listing_may_qualify(
        procedure_type="Építési engedélyezési eljárás",
        construction_activity="Új lakóépület építése",
        submission_date=as_of - timedelta(days=5),
        settings=active,
        as_of=as_of,
    )
    assert not _listing_may_qualify(
        procedure_type="Használatbavételi eljárás",
        construction_activity="Lakóépület használatbavétele",
        submission_date=as_of - timedelta(days=5),
        settings=active,
        as_of=as_of,
    )
    assert not _listing_may_qualify(
        procedure_type="Építési engedélyezési eljárás",
        construction_activity="Lakóépület használatbavétel, hatósági bizonyítvány kérése",
        submission_date=as_of - timedelta(days=365),
        settings=active,
        as_of=as_of,
    )


def test_waiting_record_is_requalified_when_no_completion_window_opens(db):
    initial_as_of = datetime(2026, 8, 24, 12, tzinfo=UTC)
    active = settings(lead_new_days=120, lead_stalled_min_days=180)
    record = _qualification_record(
        db,
        process_number="202600000601",
        submitted_at=initial_as_of - timedelta(days=150),
        parcel="601",
    )
    detail = _qualification_detail(record)
    payload_hash = sha(detail.normalized())
    revision = AuthorityDetailRevision(
        detail_revision_id="etdrd-" + "6" * 32,
        record_id=record.record_id,
        source_revision_id="etdrr-" + "6" * 32,
        revision_no=1,
        payload_sha256=payload_hash,
        normalized_json=canonical_json(detail.normalized()),
    )
    db.add(revision)
    record.current_detail_revision_no = 1
    record.current_detail_payload_sha256 = payload_hash
    record.detail_status = "current"
    db.add(
        AuthorityDetailQueue(
            record_id=record.record_id,
            source_revision_id=revision.source_revision_id,
            listing_payload_sha256=record.current_payload_sha256,
            status="completed",
            reason_code="lead_waiting_for_no_completion_window",
        )
    )
    db.commit()

    assert requalify_waiting_leads(
        db,
        active,
        as_of=initial_as_of + timedelta(days=31),
    ) == {"qualified": 1, "ineligible": 0}
    lead = db.scalar(
        select(AuthoritySignalOutbox).where(AuthoritySignalOutbox.status == "pending")
    )
    assert json.loads(lead.payload_json)["lead_reason"] == "no_completion_signal"


def test_detail_pipeline_continues_after_a_fail_closed_record(db):
    active = settings()
    run_reader(
        db,
        active,
        mode="pilot",
        town="Óbudavár",
        trigger="test",
        client_factory=TwoRecordListClient,
    )

    assert process_details(db, active, client_factory=FirstBlockedDetailClient) == {
        "completed": 1,
        "unchanged": 0,
        "blocked": 1,
    }
    queues = db.scalars(select(AuthorityDetailQueue).order_by(AuthorityDetailQueue.id)).all()
    records = db.scalars(
        select(AuthorityRecord).order_by(AuthorityRecord.public_process_number)
    ).all()
    assert [queue.status for queue in queues] == ["blocked", "completed"]
    assert [record.detail_status for record in records] == ["blocked", "current"]
    assert db.scalar(select(func.count()).select_from(AuthorityDetailRevision)) == 1
    assert (
        db.scalar(
            select(func.count())
            .select_from(AuthoritySignalOutbox)
            .where(AuthoritySignalOutbox.status == "pending")
        )
        == 1
    )


def test_detail_pipeline_recovers_only_expired_claim(db):
    active = settings()
    run_reader(
        db,
        active,
        mode="pilot",
        town="Óbudavár",
        trigger="test",
        client_factory=ListClient,
    )
    queue = db.scalar(select(AuthorityDetailQueue))
    queue.status = "claimed"
    queue.lease_owner = "crashed-worker"
    queue.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert process_details(db, active, client_factory=DetailClient) == {
        "completed": 1,
        "unchanged": 0,
        "blocked": 0,
    }
    assert queue.status == "completed"
    assert queue.lease_owner is None
    assert queue.lease_expires_at is None


def test_detail_pipeline_does_not_steal_active_claim(db):
    active = settings()
    run_reader(
        db,
        active,
        mode="pilot",
        town="Óbudavár",
        trigger="test",
        client_factory=ListClient,
    )
    queue = db.scalar(select(AuthorityDetailQueue))
    queue.status = "claimed"
    queue.lease_owner = "active-worker"
    queue.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    db.commit()
    assert process_details(db, active, client_factory=DetailClient) == {
        "completed": 0,
        "unchanged": 0,
        "blocked": 0,
    }
    assert queue.status == "claimed"
    assert queue.lease_owner == "active-worker"


def test_bridge_is_idempotent_and_keeps_signal_blocked(db):
    active = settings()
    run_reader(
        db,
        active,
        mode="pilot",
        town="Óbudavár",
        trigger="test",
        client_factory=ListClient,
    )
    process_details(db, active, client_factory=DetailClient)
    with SessionLocal() as target_db:
        first = bridge_once(db, target_db, active, limit=10)
    assert first == {"delivered": 1, "idempotent": 0, "blocked": 0, "failed": 0}
    signal_row = db.scalar(
        select(GrowthSignal).where(GrowthSignal.source_id == "authority:etdr_public")
    )
    assert signal_row.status == "blocked"
    assert signal_row.subject_type == "project"
    assert signal_row.recipient_email is None
    outbox = db.scalar(
        select(AuthoritySignalOutbox).where(AuthoritySignalOutbox.status == "delivered")
    )
    assert outbox.delivery_ref == signal_row.signal_id
    outbox.status = "pending"
    db.commit()
    with SessionLocal() as target_db:
        replay = bridge_once(db, target_db, active, limit=10)
    assert replay == {"delivered": 0, "idempotent": 1, "blocked": 0, "failed": 0}
    assert db.scalar(select(func.count()).select_from(GrowthSignal)) == 1


def test_bridge_recovers_only_expired_outbox_claim(db):
    active = settings()
    run_reader(
        db,
        active,
        mode="pilot",
        town="Óbudavár",
        trigger="test",
        client_factory=ListClient,
    )
    process_details(db, active, client_factory=DetailClient)
    outbox = db.scalar(
        select(AuthoritySignalOutbox).where(AuthoritySignalOutbox.status == "pending")
    )
    outbox.status = "claimed"
    outbox.lease_owner = "crashed-bridge"
    outbox.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    with SessionLocal() as target_db:
        assert bridge_once(db, target_db, active, limit=10)["delivered"] == 1
    assert outbox.status == "delivered"
    assert outbox.lease_owner is None
    assert outbox.lease_expires_at is None


def test_bridge_does_not_steal_active_outbox_claim(db):
    active = settings()
    run_reader(
        db,
        active,
        mode="pilot",
        town="Óbudavár",
        trigger="test",
        client_factory=ListClient,
    )
    process_details(db, active, client_factory=DetailClient)
    outbox = db.scalar(
        select(AuthoritySignalOutbox).where(AuthoritySignalOutbox.status == "pending")
    )
    outbox.status = "claimed"
    outbox.lease_owner = "active-bridge"
    outbox.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    db.commit()
    with SessionLocal() as target_db:
        assert bridge_once(db, target_db, active, limit=10) == {
            "delivered": 0,
            "idempotent": 0,
            "blocked": 0,
            "failed": 0,
        }
    assert outbox.status == "claimed"
    assert outbox.lease_owner == "active-bridge"


def test_bridge_fails_closed_if_existing_signal_becomes_outreach_capable(db):
    active = settings()
    run_reader(
        db,
        active,
        mode="pilot",
        town="Óbudavár",
        trigger="test",
        client_factory=ListClient,
    )
    process_details(db, active, client_factory=DetailClient)
    with SessionLocal() as target_db:
        assert bridge_once(db, target_db, active, limit=10)["delivered"] == 1
    signal_row = db.scalar(
        select(GrowthSignal).where(GrowthSignal.source_id == "authority:etdr_public")
    )
    outbox = db.scalar(
        select(AuthoritySignalOutbox).where(AuthoritySignalOutbox.status == "delivered")
    )
    signal_row.recipient_email = "unsafe@example.invalid"
    outbox.status = "pending"
    db.commit()
    raw_payload = json.loads(outbox.payload_json)
    assert sha(raw_payload) == outbox.payload_sha256
    ETDRLeadPayload.model_validate(raw_payload)
    with SessionLocal() as target_db:
        assert bridge_once(db, target_db, active, limit=10) == {
            "delivered": 0,
            "idempotent": 0,
            "blocked": 0,
            "failed": 1,
        }
    db.refresh(outbox)
    assert outbox.status == "pending"
    assert outbox.reason_code == "platform_delivery_failed"


def test_bridge_stops_when_policy_gate_closes(db):
    assert bridge_once(
        db,
        db,
        settings(policy_evidence_valid=False),
        limit=10,
    ) == {"delivered": 0, "idempotent": 0, "blocked": 0, "failed": 0}


def test_lead_feed_stops_when_policy_gate_closes(db):
    with pytest.raises(HTTPException) as blocked:
        lead_feed(limit=10, db=db, settings=settings(enabled=False))
    assert blocked.value.status_code == 503
    assert blocked.value.detail == {"code": "lead_export_policy_gate"}
