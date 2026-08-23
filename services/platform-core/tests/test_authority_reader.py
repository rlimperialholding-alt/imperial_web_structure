from __future__ import annotations

import ipaddress
import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select

from app.authority_reader.client import ETDRClient, ETDRPage, ETDRRecord, OENYClient, ReaderBlocked
from app.authority_reader.config import ReaderSettings
from app.authority_reader.models import (
    AuthorityCheckpoint,
    AuthorityEnrichmentQueue,
    AuthorityReaderRun,
    AuthorityRecord,
    AuthorityRecordRevision,
    AuthoritySignalOutbox,
)
from app.authority_reader.routes import current_settings
from app.authority_reader.service import process_enrichments, run_reader
from app.main import app


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
        "request_delay_seconds": 1.0,
        "request_timeout_seconds": 10.0,
        "max_response_bytes": 1_000_000,
        "max_pages_per_run": 100,
        "lease_seconds": 300,
    }
    values.update(overrides)
    return ReaderSettings(**values)


def raw_record(**overrides) -> dict:
    values = {
        "ConstructionActivity": "Új családi ház építése",
        "Street": "Kossuth",
        "HouseNumber": "1",
        "City": "Vöröstó",
        "StreetType": "utca",
        "TopographicalNumber": "047/3",
        "Type": "Építési engedélyezési eljárás",
        "ProcessNumber": "202600053739",
        "SubmissionDate": "2026-07-30T12:00:00+02:00",
        "FullAddress": "8291 Vöröstó, Kossuth utca 1",
    }
    values.update(overrides)
    return values


def record(**overrides) -> ETDRRecord:
    return ETDRRecord.model_validate(raw_record(**overrides))


def mock_client(payload, *, status: int = 200, content_type: str = "application/json"):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"Content-Type": content_type})

    return ETDRClient(
        settings(),
        transport=httpx.MockTransport(handler),
        resolver=lambda _host, _port: {ipaddress.ip_address("93.184.216.34")},
    )


def page_payload(rows: list[dict] | None = None, *, total: int | None = None) -> dict:
    rows = rows if rows is not None else [raw_record()]
    return {
        "@odata.context": "https://alk.etdr.gov.hu/query/$metadata#PublicProcessData",
        "@odata.count": len(rows) if total is None else total,
        "value": rows,
    }


def test_client_parses_exact_public_schema_and_query():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=page_payload())

    client = ETDRClient(
        settings(),
        transport=httpx.MockTransport(handler),
        resolver=lambda _host, _port: {ipaddress.ip_address("93.184.216.34")},
    )
    page = client.fetch_page(skip=0, page_size=100, filter_expression="City eq 'Vöröstó'")
    client.close()
    assert page.total == 1
    assert page.records[0].process_number == "202600053739"
    assert seen[0].url.host == "alk.etdr.gov.hu"
    assert seen[0].url.params["$filter"] == "City eq 'Vöröstó'"


@pytest.mark.parametrize(
    ("payload", "content_type", "code"),
    [
        (b"<html>captcha</html>", "text/html", "unexpected_content_type"),
        ({"@odata.count": 1, "value": [raw_record()]}, "application/json", "schema_drift_envelope"),
        (
            page_payload([{**raw_record(), "ApplicantName": "tiltott"}]),
            "application/json",
            "schema_drift_record",
        ),
        (
            page_payload([raw_record(ProcessNumber="not-stable")]),
            "application/json",
            "invalid_record",
        ),
    ],
)
def test_client_fails_closed(payload, content_type, code):
    client = mock_client(payload, content_type=content_type)
    with pytest.raises(ReaderBlocked, match=code):
        client.fetch_page(skip=0, page_size=100, filter_expression="")
    client.close()


@pytest.mark.parametrize(("status", "code"), [(403, "access_blocked"), (429, "rate_limited")])
def test_client_blocks_access_and_rate_limit(status, code):
    client = mock_client(page_payload(), status=status)
    with pytest.raises(ReaderBlocked, match=code):
        client.fetch_page(skip=0, page_size=100, filter_expression="")
    client.close()


def test_client_rejects_private_resolution():
    with pytest.raises(ReaderBlocked, match="unsafe_source_origin"):
        ETDRClient(
            settings(),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
            resolver=lambda _host, _port: {ipaddress.ip_address("127.0.0.1")},
        )


def test_oeny_client_validates_settlement_and_parcel_schema():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/settlements/search"):
            return httpx.Response(200, json=[{"kshCode": "11703", "name": "Vöröstó"}])
        return httpx.Response(200, json=[{"id": 2089996, "lotNumber": "047/3"}])

    client = OENYClient(
        settings(oeny_enabled=True),
        transport=httpx.MockTransport(handler),
        resolver=lambda _host, _port: {ipaddress.ip_address("93.184.216.34")},
    )
    with client:
        settlements = client.settlement_search("Vöröstó")
        parcels = client.parcel_search(ksh_code="11703", lot_number="047/3")
    assert settlements == [{"kshCode": "11703", "name": "Vöröstó"}]
    assert parcels == [{"id": 2089996, "lotNumber": "047/3"}]


class FakeClient:
    def __init__(self, _settings: ReaderSettings, pages: list[ETDRPage]) -> None:
        self.pages = pages
        self.index = 0

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_page(self, **_kwargs) -> ETDRPage:
        page = self.pages[self.index]
        self.index += 1
        return page


def factory(*pages: ETDRPage):
    return lambda reader_settings: FakeClient(reader_settings, list(pages))


def one_page(item: ETDRRecord, payload_hash: str = "a" * 64) -> ETDRPage:
    return ETDRPage(total=1, records=(item,), payload_sha256=payload_hash)


def test_policy_gate_stops_before_network(db):
    called = False

    def prohibited(_settings):
        nonlocal called
        called = True
        raise AssertionError

    with pytest.raises(ReaderBlocked, match="policy_authorization_required"):
        run_reader(
            db,
            settings(policy_authorized=False),
            mode="delta",
            trigger="test",
            client_factory=prohibited,
        )
    assert called is False
    assert db.scalar(select(func.count()).select_from(AuthorityReaderRun)) == 0


def test_pilot_is_persisted_with_held_enrichment_and_outbox(db):
    row = run_reader(
        db,
        settings(),
        mode="pilot",
        town="Vöröstó",
        trigger="test",
        client_factory=factory(one_page(record())),
    )
    assert row.status == "completed"
    assert (row.records_inserted, row.records_updated, row.records_unchanged) == (1, 0, 0)
    stored = db.scalar(select(AuthorityRecord))
    assert stored is not None
    assert stored.city == "Vöröstó"
    assert stored.evidence_url.endswith("/202600053739")
    assert db.scalar(select(AuthorityEnrichmentQueue)).status == "held"
    outbox = db.scalar(select(AuthoritySignalOutbox))
    assert outbox.status == "held"
    assert json.loads(outbox.payload_json)["recipient_email"] is None
    assert "full_address" not in outbox.payload_json


def test_replay_is_idempotent_and_changed_payload_creates_one_revision(db):
    first = factory(one_page(record(), "a" * 64))
    run_reader(db, settings(), mode="pilot", town="Vöröstó", trigger="test", client_factory=first)
    replay = run_reader(
        db,
        settings(),
        mode="pilot",
        town="Vöröstó",
        trigger="test",
        client_factory=factory(one_page(record(), "b" * 64)),
    )
    assert replay.records_unchanged == 1
    assert db.scalar(select(func.count()).select_from(AuthorityRecordRevision)) == 1
    changed = run_reader(
        db,
        settings(),
        mode="pilot",
        town="Vöröstó",
        trigger="test",
        client_factory=factory(
            one_page(record(ConstructionActivity="Módosított építési tevékenység"), "c" * 64)
        ),
    )
    assert changed.records_updated == 1
    assert db.scalar(select(func.count()).select_from(AuthorityRecordRevision)) == 2
    assert db.scalar(select(AuthorityRecord)).current_revision_no == 2


class FakeOENYClient:
    def __init__(self, _settings: ReaderSettings, parcels: list[dict]) -> None:
        self.parcels = parcels

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def settlement_search(self, name: str):
        return [{"kshCode": "11703", "name": name}]

    def parcel_search(self, **_kwargs):
        return self.parcels


def test_oeny_enrichment_completes_only_exact_single_match(db):
    enabled = settings(oeny_enabled=True)
    run_reader(
        db,
        enabled,
        mode="pilot",
        town="Vöröstó",
        trigger="test",
        client_factory=factory(one_page(record())),
    )
    result = process_enrichments(
        db,
        enabled,
        client_factory=lambda cfg: FakeOENYClient(cfg, [{"id": 2089996, "lotNumber": "047/3"}]),
    )
    assert result == {"completed": 1, "ambiguous": 0, "failed": 0}
    queue = db.scalar(select(AuthorityEnrichmentQueue))
    assert queue.status == "completed"
    assert json.loads(queue.result_json) == {
        "ksh_code": "11703",
        "parcels": [{"id": 2089996, "lot_number": "047/3"}],
    }


def test_oeny_multiple_parcels_remain_ambiguous(db):
    enabled = settings(oeny_enabled=True)
    run_reader(
        db,
        enabled,
        mode="pilot",
        town="Vöröstó",
        trigger="test",
        client_factory=factory(one_page(record())),
    )
    result = process_enrichments(
        db,
        enabled,
        client_factory=lambda cfg: FakeOENYClient(
            cfg,
            [
                {"id": 1, "lotNumber": "047/3"},
                {"id": 2, "lotNumber": "047/3"},
            ],
        ),
    )
    assert result == {"completed": 0, "ambiguous": 1, "failed": 0}
    assert db.scalar(select(AuthorityEnrichmentQueue)).status == "ambiguous"


def test_active_lease_blocks_second_worker(db):
    db.add(
        AuthorityCheckpoint(
            source_key="etdr_public",
            lease_owner="other-worker",
            lease_expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
    )
    db.commit()
    with pytest.raises(ReaderBlocked, match="active_lease"):
        run_reader(
            db,
            settings(),
            mode="delta",
            trigger="test",
            client_factory=factory(one_page(record())),
        )


def test_schema_failure_does_not_advance_checkpoint(db):
    class BlockedClient(FakeClient):
        def fetch_page(self, **_kwargs):
            raise ReaderBlocked("schema_drift_record")

    with pytest.raises(ReaderBlocked, match="schema_drift_record"):
        run_reader(
            db,
            settings(),
            mode="delta",
            trigger="test",
            client_factory=lambda cfg: BlockedClient(cfg, []),
        )
    checkpoint = db.get(AuthorityCheckpoint, "etdr_public")
    assert checkpoint is not None
    assert checkpoint.generation == 0
    assert checkpoint.cursor_json == "{}"
    failed = db.scalar(select(AuthorityReaderRun))
    assert failed.status == "blocked"
    assert failed.error_code == "schema_drift_record"


def test_internal_routes_require_token_and_expose_no_secret(client):
    disabled = settings(enabled=False, policy_authorized=False)
    app.dependency_overrides[current_settings] = lambda: disabled
    try:
        unauthorized = client.get("/api/internal/authority-reader/readiness")
        assert unauthorized.status_code == 401
        response = client.get(
            "/api/internal/authority-reader/readiness",
            headers={"X-Internal-Job-Token": disabled.internal_token},
        )
        assert response.status_code == 200
        assert disabled.internal_token not in response.text
        blocked = client.post(
            "/api/internal/authority-reader/runs",
            headers={"X-Internal-Job-Token": disabled.internal_token},
            json={"mode": "delta"},
        )
        assert blocked.status_code == 503
        assert blocked.json()["detail"]["code"] == "reader_disabled"
    finally:
        app.dependency_overrides.pop(current_settings, None)
