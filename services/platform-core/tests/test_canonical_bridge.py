from __future__ import annotations

import hashlib

from sqlalchemy import func, select

from app.models import (
    CanonicalDeliveryRecord,
    CanonicalReconciliationRun,
    EnterpriseCanonicalRecord,
)
from app.services.canonical_bridge import (
    collect_canonical_envelopes,
    pull_itep_tasks_to_platform,
    push_canonical_to_crm,
    push_platform_events_to_itep,
    reconcile_canonical_with_crm,
)


def test_envelopes_have_stable_checksum_and_identity(db):
    db.add(
        EnterpriseCanonicalRecord(
            record_id="CAN-1",
            domain="customer",
            entity_type="customer",
            external_key="platform:customers:1",
            canonical_name="Teszt Ügyfél",
            project_id=None,
            target_module="crm",
            status="active",
            data_json='{"name":"Teszt Ügyfél"}',
            provenance_json='{"source":"test"}',
        )
    )
    db.commit()
    envelope = next(
        item for item in collect_canonical_envelopes(db) if item["externalKey"] == "canonical:CAN-1"
    )
    assert envelope["eventId"].startswith("ICS-")
    assert envelope["payloadSha256"] == hashlib.sha256(envelope["payloadJson"].encode()).hexdigest()
    assert all(" " not in item["entityType"] for item in collect_canonical_envelopes(db))


def test_push_is_durable_and_idempotent(db):
    db.add(
        EnterpriseCanonicalRecord(
            record_id="CAN-2",
            domain="project",
            entity_type="project",
            external_key="platform:projects:2",
            canonical_name="Teszt projekt",
            project_id="P-2",
            target_module="project-control",
            status="active",
            data_json='{"title":"Teszt projekt"}',
            provenance_json="{}",
        )
    )
    db.commit()
    seen = []

    def post_batch(envelopes):
        seen.extend(envelopes)
        return {
            "results": [
                {"eventId": item["eventId"], "status": "applied", "mirrorId": "REMOTE-1"}
                for item in envelopes
            ]
        }

    first = push_canonical_to_crm(db, post_batch=post_batch)
    assert first["applied"] >= 1
    delivered = db.scalar(select(func.count(CanonicalDeliveryRecord.id)))
    second = push_canonical_to_crm(db, post_batch=post_batch)
    assert second["pending"] == 0
    assert db.scalar(select(func.count(CanonicalDeliveryRecord.id))) == delivered


def test_reconciliation_detects_hash_mismatch(db):
    db.add(
        EnterpriseCanonicalRecord(
            record_id="CAN-3",
            domain="finance",
            entity_type="cashflow",
            external_key="platform:cashflow:3",
            canonical_name="Cashflow",
            project_id="P-3",
            target_module="financial-control",
            status="active",
            data_json='{"amount":100}',
            provenance_json="{}",
        )
    )
    db.commit()
    local = collect_canonical_envelopes(db)

    def read_page(_cursor, _limit):
        return {
            "counts": {"conflicts": 0},
            "mirrors": [
                {
                    "sourceSystem": "imperial-intelligence-platform",
                    "domain": item["domain"],
                    "entityType": item["entityType"],
                    "externalKey": item["externalKey"],
                    "payloadSha256": "0" * 64,
                }
                for item in local
            ],
            "nextCursor": None,
        }

    result = reconcile_canonical_with_crm(db, read_page=read_page)
    assert result["status"] == "attention_required"
    assert result["hash_mismatch"] == len(local)
    assert db.scalar(select(func.count(CanonicalReconciliationRun.id))) == 1


def test_crm_and_itep_owned_records_are_not_echoed_back_to_crm(db):
    for index, external_key in enumerate(("crm:customers:41", "itep:billingo_incoming:42"), 1):
        db.add(
            EnterpriseCanonicalRecord(
                record_id=f"SOURCE-{index}",
                domain="customer",
                entity_type="customer",
                external_key=external_key,
                canonical_name="Forrásrekord",
                project_id=None,
                target_module="crm",
                status="active",
                data_json="{}",
                provenance_json="{}",
            )
        )
    db.commit()

    event_ids = {item["externalKey"] for item in collect_canonical_envelopes(db)}

    assert "canonical:SOURCE-1" not in event_ids
    assert "canonical:SOURCE-2" not in event_ids


def test_itep_task_pull_is_checksum_verified_and_idempotent(db):
    payload = {
        "id": "ITEP-42",
        "title": "Projektindítás",
        "status": "IN_PROGRESS",
        "projectIds": ["PROJECT-42"],
    }
    payload_json = (
        '{"id":"ITEP-42","projectIds":["PROJECT-42"],'
        '"status":"IN_PROGRESS","title":"Projektindítás"}'
    )
    item = {
        "externalKey": "itep:task:ITEP-42",
        "sourceVersion": "2026-08-01T10:00:00.000Z#1",
        "payloadSha256": hashlib.sha256(payload_json.encode()).hexdigest(),
        "payload": payload,
    }

    def read_page(_cursor, _limit):
        return {"items": [item], "nextCursor": None}

    first = pull_itep_tasks_to_platform(db, read_page=read_page)
    second = pull_itep_tasks_to_platform(db, read_page=read_page)
    assert first["inserted"] == 1
    assert second["unchanged"] == 1
    record = db.scalar(
        select(EnterpriseCanonicalRecord).where(
            EnterpriseCanonicalRecord.external_key == "itep:task:ITEP-42"
        )
    )
    assert record.project_id == "PROJECT-42"


def test_platform_event_push_to_itep_is_idempotent(db):
    from app.models import EventRecord

    db.add(
        EventRecord(
            event_id="EVENT-42",
            dedupe_key="test:event:42",
            project_id="PROJECT-42",
            source_module="crm",
            event_type="LEAD_QUALIFIED",
            status="qualified",
            severity="info",
            payload_json='{"summary":"Minősített lead"}',
        )
    )
    db.commit()
    sent = []

    def post_event(payload):
        sent.append(payload)
        return {"idempotent": False, "eventId": "REMOTE-EVENT-42", "taskIds": ["TASK-42"]}

    first = push_platform_events_to_itep(db, post_event=post_event)
    second = push_platform_events_to_itep(db, post_event=post_event)
    assert first["applied"] == 1
    assert second["idempotent"] == 1
    assert len(sent) == 1
    assert sent[0]["projectId"] == "PROJECT-42"
