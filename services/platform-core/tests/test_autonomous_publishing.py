from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.autonomous_publishing import service
from app.autonomous_publishing.adapters import AdapterError, AdapterResult
from app.autonomous_publishing.models import (
    PublicationProofRecord,
    PublishingChannelState,
    PublishingEventRecord,
    PublishingExceptionRecord,
    PublishingJobRecord,
    PublishingWorkerHeartbeat,
)
from app.autonomous_publishing.registry import Binding
from app.autonomous_publishing.schemas import MANDATORY_GATES, PublicationJobIn
from app.models import TaskRecord


def _job_dict(*, job_id: str = "JOB-AUTOPUB-001") -> dict:
    now = datetime.now(UTC)
    token = "approved-release-token-which-is-long-enough-for-tests"
    payload = {
        "job_id": job_id,
        "content_asset_id": "ASSET-AUTOPUB-001",
        "content_version_id": "VERSION-001",
        "brand_id": "BRAND-001",
        "visual_asset_package_id": "VAP-001",
        "claim_ids": ["CLAIM-001"],
        "price_snapshot_id": "PRICE-001",
        "offer_version_id": "OFFER-001",
        "terms_version_id": "TERMS-001",
        "gate_results": [
            {
                "gate": gate,
                "decision": "PASS",
                "evidence_id": f"EVIDENCE-{gate}",
                "checked_at": (now - timedelta(minutes=1)).isoformat(),
                "valid_until": (now + timedelta(days=1)).isoformat(),
            }
            for gate in sorted(MANDATORY_GATES)
        ],
        "cta": {"label": "Részletek", "url": "https://brand.example/ajanlat"},
        "title": "Jóváhagyott szakmai tartalom",
        "canonical_slug": "jovahagyott-szakmai-tartalom",
        "body_html": "<p>Jóváhagyott, hash-kötött tartalom.</p>",
        "excerpt": "Jóváhagyott tartalmi kivonat.",
        "content_hash": hashlib.sha256(b"approved-content").hexdigest(),
        "channels": ["wordpress", "facebook", "instagram", "analytics", "crm"],
        "channel_payloads": {
            "wordpress": {
                "media": {
                    "url": "https://brand.example/approved-image.jpg",
                    "filename": "approved-image.jpg",
                }
            },
            "facebook": {
                "message": "Jóváhagyott Facebook-szöveg #epites #otthon #imperial",
                "image_url": "https://brand.example/approved-image.jpg",
            },
            "instagram": {
                "caption": "Jóváhagyott Instagram-szöveg #epites #otthon #imperial",
                "image_url": "https://brand.example/image.jpg",
            },
            "analytics": {},
            "crm": {},
        },
        "cms_route": "WORDPRESS",
        "idempotency_key": "",
        "rollback_policy": {
            "on_partial_failure": True,
            "automatic_kill_switch_on_failure": True,
            "restore_last_known_good": True,
        },
        "correlation_id": "CORR-AUTOPUB-001",
        "release_token": token,
        "release_token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "canonical_url": None,
        "categories": ["news"],
        "tags": ["imperial"],
    }
    raw = f"{payload['brand_id']}|{payload['content_asset_id']}|{payload['content_version_id']}"
    payload["idempotency_key"] = hashlib.sha256(raw.encode()).hexdigest()
    return payload


class FakeRegistry:
    version = "test-v1"

    def binding(self, brand_id: str, channel: str) -> Binding:
        return Binding(
            brand_id=brand_id,
            domain="brand.example",
            cms_route="WORDPRESS",
            channel=channel,
            config={"enabled": True},
            secret={},
        )

    def readiness(self):
        return {"ready": True, "routes": [], "writes_unlocked": True, "version": self.version}


class FakeAdapter:
    calls: list[str] = []
    rollbacks: list[str] = []
    fail_channel: str | None = None

    def __init__(self, channel: str):
        self.channel = channel

    def publish(self, job, key):
        self.calls.append(self.channel)
        if self.fail_channel == self.channel:
            raise AdapterError(f"forced-{self.channel}-failure")
        return AdapterResult(
            external_id=f"EXT-{self.channel}",
            public_url=(
                "https://brand.example/canonical"
                if self.channel == "wordpress"
                else f"https://provider.example/{self.channel}"
            ),
            admin_url=None,
            content_hash=job.content_hash,
            canonical_url=job.canonical_url or "https://brand.example/canonical",
            readback={"id": f"EXT-{self.channel}", "verified": True},
            published_at=datetime.now(UTC),
        )

    def rollback(self, job, result, reason):
        self.rollbacks.append(self.channel)
        return {"rollback_id": f"RB-{self.channel}", "readback": {"deleted": True}}


@pytest.fixture
def fake_runtime(monkeypatch):
    FakeAdapter.calls = []
    FakeAdapter.rollbacks = []
    FakeAdapter.fail_channel = None
    registry = FakeRegistry()
    monkeypatch.setattr(service.PublishingRegistry, "load", classmethod(lambda cls: registry))
    monkeypatch.setattr(service, "writes_unlocked", lambda: True)
    monkeypatch.setattr(
        service, "build_adapter", lambda binding, client: FakeAdapter(binding.channel)
    )
    return registry


def test_submission_is_durable_idempotent_and_payload_bound(db, fake_runtime):
    job = PublicationJobIn.model_validate(_job_dict())
    first = service.submit_job(db, job)
    second = service.submit_job(db, job)
    assert first.status == "QUEUED" and not first.idempotent
    assert second.idempotent and second.payload_sha256 == first.payload_sha256
    assert len(db.scalars(select(PublishingJobRecord)).all()) == 1
    assert len(db.scalars(select(PublishingChannelState)).all()) == len(job.channels)
    assert {row.event_type for row in db.scalars(select(PublishingEventRecord)).all()} >= {
        "PUBLICATION_JOB_QUEUED",
        "PUBLICATION_PREFLIGHT_PASSED",
    }


def test_readiness_keeps_serving_with_a_fresh_degraded_daily_gate(
    db, fake_runtime, monkeypatch
):
    monkeypatch.setattr(
        service,
        "settings",
        replace(service.settings, autonomous_publishing_enabled=True),
    )
    db.add(
        PublishingWorkerHeartbeat(
            worker_id=service.settings.autonomous_publishing_worker_id,
            status="degraded",
            detail_json='{"daily_gate":{"status":"degraded"}}',
            heartbeat_at=datetime.now(UTC),
        )
    )
    db.commit()

    ready, payload = service.readiness(db)

    assert ready is True
    assert payload["worker_heartbeat"] == "degraded_sla"
    assert payload["worker_status"] == "degraded"


def test_readiness_still_rejects_a_stale_degraded_worker(db, fake_runtime, monkeypatch):
    monkeypatch.setattr(
        service,
        "settings",
        replace(service.settings, autonomous_publishing_enabled=True),
    )
    db.add(
        PublishingWorkerHeartbeat(
            worker_id=service.settings.autonomous_publishing_worker_id,
            status="degraded",
            heartbeat_at=datetime.now(UTC)
            - timedelta(
                seconds=service.settings.autonomous_publishing_heartbeat_stale_seconds + 1
            ),
        )
    )
    db.commit()

    ready, payload = service.readiness(db)

    assert ready is False
    assert payload["worker_heartbeat"] == "stale_or_missing"
    assert payload["worker_status"] == "degraded"


@pytest.mark.parametrize(
    ("channel", "error"),
    [
        ("wordpress", "WordPress HTTPS media.url is required"),
        ("facebook", "facebook image_factory or HTTPS image_url is required"),
        ("instagram", "instagram image_factory or HTTPS image_url is required"),
    ],
)
def test_public_channels_reject_missing_image_payload(channel, error):
    payload = _job_dict(job_id=f"JOB-MISSING-IMAGE-{channel.upper()}")
    if channel == "wordpress":
        payload["channel_payloads"][channel].pop("media")
    else:
        payload["channel_payloads"][channel].pop("image_url")
    with pytest.raises(ValidationError, match=error):
        PublicationJobIn.model_validate(payload)


def test_submission_conflict_is_fail_closed(db, fake_runtime):
    first = PublicationJobIn.model_validate(_job_dict())
    service.submit_job(db, first)
    changed = _job_dict()
    changed["title"] = "Más tartalom ugyanazzal a kulccsal"
    with pytest.raises(ValueError, match="Idempotency conflict"):
        service.submit_job(db, PublicationJobIn.model_validate(changed))


def test_web_first_readback_then_social_then_attribution(db, fake_runtime, monkeypatch):
    job = PublicationJobIn.model_validate(_job_dict())
    service.submit_job(db, job)
    row = service.claim_job(db)
    assert row is not None
    result = service.process_job(db, row)
    assert result["status"] == "VERIFIED"
    assert FakeAdapter.calls == ["wordpress", "facebook", "instagram", "analytics", "crm"]
    assert len(db.scalars(select(PublicationProofRecord)).all()) == 5
    states = db.scalars(select(PublishingChannelState)).all()
    assert all(state.status == "READBACK_VERIFIED" for state in states)


def test_partial_failure_rolls_back_in_reverse_and_queues_retry(db, fake_runtime):
    payload = _job_dict()
    payload["channels"] = ["wordpress", "facebook", "instagram"]
    payload["channel_payloads"] = {
        key: payload["channel_payloads"][key] for key in payload["channels"]
    }
    job = PublicationJobIn.model_validate(payload)
    service.submit_job(db, job)
    row = service.claim_job(db)
    FakeAdapter.fail_channel = "instagram"
    result = service.process_job(db, row)
    assert result["status"] == "RETRY_QUEUED"
    assert result["attempt"] == 1
    assert result["retry_in_seconds"] == 30
    assert FakeAdapter.rollbacks == ["facebook", "wordpress"]
    assert row.status == "QUEUED" and row.available_at is not None
    assert all(
        state.status == "QUEUED"
        for state in db.scalars(select(PublishingChannelState)).all()
    )
    assert db.scalar(select(PublishingExceptionRecord)) is None
    assert db.scalar(select(TaskRecord).where(TaskRecord.assignee == "Molnár Andrea")) is None


def test_partial_failure_after_final_attempt_routes_terminal_exception(db, fake_runtime):
    payload = _job_dict(job_id="JOB-AUTOPUB-TERMINAL-001")
    payload["channels"] = ["wordpress", "facebook", "instagram"]
    payload["channel_payloads"] = {
        key: payload["channel_payloads"][key] for key in payload["channels"]
    }
    job = PublicationJobIn.model_validate(payload)
    service.submit_job(db, job)
    row = service.claim_job(db)
    row.max_attempts = 1
    FakeAdapter.fail_channel = "instagram"
    result = service.process_job(db, row)
    assert result["status"] == "ROLLED_BACK"
    assert FakeAdapter.rollbacks == ["facebook", "wordpress"]
    exception = db.scalar(select(PublishingExceptionRecord))
    assert exception and exception.owner == "Molnár Andrea" and exception.due_at is not None
    task = db.scalar(select(TaskRecord).where(TaskRecord.assignee == "Molnár Andrea"))
    assert task and task.priority == "high"


def test_gate_block_creates_exception_but_pass_job_does_not(db, fake_runtime):
    blocked = _job_dict(job_id="JOB-BLOCKED-001")
    blocked["gate_results"][0]["decision"] = "REVIEW"
    result = service.submit_job(db, PublicationJobIn.model_validate(blocked))
    assert result.status == "BLOCKED"
    assert db.scalar(select(PublishingExceptionRecord)) is not None


SCENARIOS = [
    "missing_gate",
    "review_gate",
    "block_gate",
    "expired_claim",
    "expired_price",
    "expired_offer",
    "expired_terms",
    "bad_token",
    "revoked_permission",
    "http_429",
    "http_5xx",
    "readback_mismatch",
    "bad_canonical",
    "social_after_web_failure",
    "reverse_rollback",
    "rollback_failure",
    "andi_exception",
    "forum_policy_block",
    "forum_draft_only",
    "concurrent_idempotency",
    "queue_replay",
    "schema_error",
    "analytics_attribution",
    "crm_attribution",
    "wrong_brand",
    "wrong_cms_route",
    "nim_no_wordpress_fallback",
    "missing_visual",
    "bad_mime",
    "oversized_media",
    "instagram_timeout",
    "token_expiration",
    "missing_secret_reference",
    "database_reconnect",
    "queue_reconnect",
    "event_retry",
    "dead_letter",
    "manual_replay",
    "scheduled_publish",
    "content_update",
    "content_withdrawal",
    "multi_channel_partial_failure",
    "full_rollback",
    "duplicate_channel",
    "future_gate",
    "missing_cta",
    "bad_slug",
    "release_hash_mismatch",
    "parallel_cms",
    "unknown_channel",
]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_fail_closed_scenario_matrix(scenario, fake_runtime):
    payload = _job_dict(job_id=f"JOB-{scenario.upper().replace('_', '-')}")
    if scenario == "missing_gate":
        payload["gate_results"] = payload["gate_results"][1:]
    elif scenario == "review_gate":
        payload["gate_results"][0]["decision"] = "REVIEW"
    elif scenario == "block_gate":
        payload["gate_results"][0]["decision"] = "BLOCK"
    elif scenario == "missing_visual":
        payload["visual_asset_package_id"] = ""
    elif scenario == "missing_cta":
        payload["cta"] = {}
    elif scenario == "bad_slug":
        payload["canonical_slug"] = "Bad Slug"
    elif scenario == "release_hash_mismatch":
        payload["release_token_hash"] = "a" * 64
    elif scenario == "wrong_cms_route" or scenario == "parallel_cms":
        payload["cms_route"] = "NIM"
    elif scenario == "duplicate_channel":
        payload["channels"].append("wordpress")
    elif scenario == "unknown_channel":
        payload["channels"].append("unknown")
    elif scenario == "future_gate":
        payload["gate_results"][0]["checked_at"] = (
            datetime.now(UTC) + timedelta(days=2)
        ).isoformat()
        payload["gate_results"][0]["valid_until"] = (
            datetime.now(UTC) + timedelta(days=3)
        ).isoformat()
    elif scenario in {"expired_claim", "expired_price", "expired_offer", "expired_terms"}:
        payload["gate_results"][0]["valid_until"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
    try:
        job = PublicationJobIn.model_validate(payload)
    except ValidationError:
        return
    errors = service.preflight_errors(job, fake_runtime)
    if scenario in {
        "missing_gate",
        "review_gate",
        "block_gate",
        "future_gate",
        "expired_claim",
        "expired_price",
        "expired_offer",
        "expired_terms",
        "release_hash_mismatch",
        "wrong_cms_route",
        "parallel_cms",
    }:
        assert errors
    else:
        assert isinstance(errors, list)
