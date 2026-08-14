from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import app.services.house_designer_readiness as readiness_service
from app.models import (
    AuditLog,
    HouseDesignerAdapterJob,
    HouseDesignerAdapterReceipt,
    HouseDesignerEntitlement,
    HouseDesignEstimateSnapshot,
    HouseDesignRenderRevision,
    HouseDesignScheduleSnapshot,
)
from app.services.house_designer import (
    ActorScope,
    HouseDesignerError,
    apply_session_command,
    create_session,
)
from app.services.house_designer_adapters import (
    accept_signed_result,
    dispatch_adapter_jobs,
    queue_adapter_job,
    register_adapter,
    review_adapter,
)
from app.services.house_designer_readiness import (
    house_designer_release_readiness,
    request_entitlement_activation,
    review_entitlement_activation,
    set_sandbox_entitlement,
    suspend_entitlement,
)

TENANT = "imperial-holding"
BRAND = "imperial"
OWNER = ActorScope("customer-1", TENANT, frozenset({BRAND}))
SECRETS = {
    "pricing": "test-only-house-designer-pricing-secret-which-is-distinct",
    "capacity": "test-only-house-designer-capacity-secret-which-is-distinct",
    "render": "test-only-house-designer-render-secret-which-is-distinct",
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sign(adapter_type: str, payload: dict) -> str:
    return (
        "sha256="
        + hmac.new(
            SECRETS[adapter_type].encode(), _json(payload).encode(), hashlib.sha256
        ).hexdigest()
    )


def _activate(db, adapter_type: str) -> dict:
    row = register_adapter(
        db,
        actor_subject_id="technical-1",
        actor_role="technical-prep",
        tenant_id=TENANT,
        brand_id=BRAND,
        adapter_type=adapter_type,
        provider=f"verified-{adapter_type}",
        endpoint=f"https://8.8.8.8/v1/{adapter_type}",
        key_id=f"{adapter_type}-key-v1",
    )
    return review_adapter(
        db,
        adapter_id=row["adapterId"],
        actor_subject_id="owner-1",
        actor_role="owner",
        approve=True,
    )


def _session_and_entitlement(db) -> str:
    design = create_session(
        db,
        actor=OWNER,
        brand_id=BRAND,
        title="Production adapter test",
        command_id="adapter-test-create",
    )
    revision = design["revision"]
    apply_session_command(
        db,
        session_id=design["sessionId"],
        actor=OWNER,
        base_revision_id=revision["revisionId"],
        base_canonical_sha256=revision["canonicalSha256"],
        command_id="adapter-test-site",
        command_type="set_site",
        payload={
            "municipalityCode": "011",
            "postalCode": "1111",
            "city": "Mintaváros",
            "address": "Minta utca 12.",
            "parcelNumber": "12345/6",
        },
    )
    db.add(
        HouseDesignerEntitlement(
            entitlement_id="HDE-TEST-ACTIVE",
            tenant_id=TENANT,
            brand_id=BRAND,
            status="active",
            standalone_enabled=True,
            order_intake_enabled=True,
            production_render_enabled=True,
            production_pricing_enabled=True,
            production_capacity_enabled=True,
            policy_json="{}",
            valid_from=datetime.now(UTC) - timedelta(days=1),
            created_by="owner-1",
        )
    )
    db.commit()
    return design["sessionId"]


def _envelope(job: dict, adapter_type: str, result: dict, provider_job_id: str) -> dict:
    return {
        "contractVersion": "house-designer-adapter-v1",
        "adapterType": adapter_type,
        "jobId": job["jobId"],
        "requestSha256": job["requestSha256"],
        "issuedAt": datetime.now(UTC).isoformat(),
        "providerJobId": provider_job_id,
        "status": "SUCCEEDED",
        "result": result,
    }


def _dispatch(db, job: dict, provider_job_id: str) -> dict:
    seen: dict = {}

    def transport(endpoint, headers, body, timeout):
        seen.update(
            endpoint=endpoint,
            headers=headers,
            body=json.loads(body),
            timeout=timeout,
        )
        return 202, {"providerJobId": provider_job_id}

    outcome = dispatch_adapter_jobs(db, transport=transport)
    assert outcome["dispatched"] == 1
    adapter_type = seen["body"]["adapterType"]
    expected_signature = (
        "sha256="
        + hmac.new(
            SECRETS[adapter_type].encode(),
            _json(seen["body"]).encode(),
            hashlib.sha256,
        ).hexdigest()
    )
    assert hmac.compare_digest(seen["headers"]["X-Imperial-Signature"], expected_signature)
    assert seen["body"]["callbackUrl"].endswith("/api/v1/house-designer/adapter-results")
    return seen


def _input_sha(db, job_id: str) -> tuple[str, dict]:
    row = db.scalar(select(HouseDesignerAdapterJob).where(HouseDesignerAdapterJob.job_id == job_id))
    request = json.loads(row.request_json)
    return request["inputSha256"], request


def test_four_eyes_adapter_activation_is_enforced(db):
    row = register_adapter(
        db,
        actor_subject_id="author-1",
        actor_role="technical-prep",
        tenant_id=TENANT,
        brand_id=BRAND,
        adapter_type="pricing",
        provider="pricing-provider",
        endpoint="https://provider.example/pricing",
        key_id="pricing-key-v1",
    )
    with pytest.raises(HouseDesignerError) as same_actor:
        review_adapter(
            db,
            adapter_id=row["adapterId"],
            actor_subject_id="author-1",
            actor_role="owner",
            approve=True,
        )
    assert same_actor.value.code == "four_eyes_required"
    with pytest.raises(HouseDesignerError) as platform_admin:
        review_adapter(
            db,
            adapter_id=row["adapterId"],
            actor_subject_id="platform-admin-1",
            actor_role="platform-admin",
            approve=True,
        )
    assert platform_admin.value.code == "adapter_review_forbidden"


def test_signed_provider_results_create_only_production_snapshots(db):
    session_id = _session_and_entitlement(db)
    for adapter_type in ("pricing", "capacity", "render"):
        _activate(db, adapter_type)

    pricing_job = queue_adapter_job(
        db,
        session_id=session_id,
        adapter_type="pricing",
        actor=OWNER,
        idempotency_key="pricing-job-1",
    )
    dispatched = _dispatch(db, pricing_job, "provider-pricing-1")
    input_sha, stored_request = _input_sha(db, pricing_job["jobId"])
    serialized_stored = _json(stored_request)
    assert "Mintaváros" not in serialized_stored
    assert "Minta utca" not in serialized_stored
    assert "12345/6" not in serialized_stored
    assert dispatched["body"]["request"]["input"]["site"]["parcelNumber"] == "12345/6"
    pricing = _envelope(
        pricing_job,
        "pricing",
        {
            "inputSha256": input_sha,
            "netMinHuf": 60_000_000,
            "netMaxHuf": 70_000_000,
            "vatRate": "0.27",
            "lineItems": [{"name": "Szerkezet", "netMinHuf": 30_000_000}],
            "assumptions": ["Normál talaj"],
            "exclusions": ["Telekár"],
            "validUntil": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        },
        "provider-pricing-1",
    )
    accepted = accept_signed_result(
        db, payload=pricing, key_id="pricing-key-v1", signature=_sign("pricing", pricing)
    )
    assert accepted["job"]["status"] == "SUCCEEDED"
    estimate = db.scalar(select(HouseDesignEstimateSnapshot))
    assert estimate is not None and estimate.non_production is False

    capacity_job = queue_adapter_job(
        db,
        session_id=session_id,
        adapter_type="capacity",
        actor=OWNER,
        idempotency_key="capacity-job-1",
    )
    _dispatch(db, capacity_job, "provider-capacity-1")
    capacity_input, _ = _input_sha(db, capacity_job["jobId"])
    assert capacity_input == input_sha
    capacity = _envelope(
        capacity_job,
        "capacity",
        {
            "inputSha256": capacity_input,
            "earliestStart": "2026-10-01",
            "latestStart": "2026-11-01",
            "durationMinWorkdays": 120,
            "durationMaxWorkdays": 150,
            "phases": [{"name": "Alapozás", "minWorkdays": 15, "maxWorkdays": 20}],
            "assumptions": ["Ötnapos munkahét"],
            "capacitySnapshotId": "capacity-2026-w32",
            "validUntil": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        },
        "provider-capacity-1",
    )
    accept_signed_result(
        db, payload=capacity, key_id="capacity-key-v1", signature=_sign("capacity", capacity)
    )
    schedule = db.scalar(select(HouseDesignScheduleSnapshot))
    assert schedule is not None and schedule.non_production is False

    render_job = queue_adapter_job(
        db,
        session_id=session_id,
        adapter_type="render",
        actor=OWNER,
        idempotency_key="render-job-1",
        prompt="Fehér vakolat, antracit tető",
    )
    _dispatch(db, render_job, "provider-render-1")
    render_input, request = _input_sha(db, render_job["jobId"])
    render = _envelope(
        render_job,
        "render",
        {
            "inputSha256": render_input,
            "assetRef": "https://assets.example/render-1.webp",
            "assetSha256": "a" * 64,
            "geometryLockSha256": request["geometryLockSha256"],
            "qa": {"geometryLockVerified": True, "moderation": "PASS"},
        },
        "provider-render-1",
    )
    result = accept_signed_result(
        db, payload=render, key_id="render-key-v1", signature=_sign("render", render)
    )
    rendered = db.scalar(select(HouseDesignRenderRevision))
    assert rendered is not None and rendered.non_production is False
    replay = accept_signed_result(
        db, payload=render, key_id="render-key-v1", signature=_sign("render", render)
    )
    assert replay["replayed"] is True
    assert replay["receiptId"] == result["receiptId"]


def test_signed_result_rejects_tamper_and_stale_binding(db):
    session_id = _session_and_entitlement(db)
    _activate(db, "pricing")
    job = queue_adapter_job(
        db,
        session_id=session_id,
        adapter_type="pricing",
        actor=OWNER,
        idempotency_key="pricing-job-reject",
    )
    _dispatch(db, job, "provider-reject-1")
    input_sha, _ = _input_sha(db, job["jobId"])
    payload = _envelope(
        job,
        "pricing",
        {
            "inputSha256": input_sha,
            "netMinHuf": 1,
            "netMaxHuf": 2,
            "vatRate": "0.27",
            "lineItems": [],
            "assumptions": [],
            "exclusions": [],
            "validUntil": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
        "provider-reject-1",
    )
    with pytest.raises(HouseDesignerError) as invalid_signature:
        accept_signed_result(
            db, payload=payload, key_id="pricing-key-v1", signature="sha256=" + "0" * 64
        )
    assert invalid_signature.value.code == "adapter_signature_invalid"
    assert db.scalar(select(HouseDesignerAdapterReceipt)) is None

    payload["requestSha256"] = "f" * 64
    rejected = accept_signed_result(
        db, payload=payload, key_id="pricing-key-v1", signature=_sign("pricing", payload)
    )
    assert rejected["job"]["status"] == "FAILED"
    receipt = db.scalar(select(HouseDesignerAdapterReceipt))
    assert receipt.status == "REJECTED"
    assert receipt.rejection_code == "request_binding"


def test_dispatch_retries_without_false_success(db):
    session_id = _session_and_entitlement(db)
    _activate(db, "pricing")
    queued = queue_adapter_job(
        db,
        session_id=session_id,
        adapter_type="pricing",
        actor=OWNER,
        idempotency_key="pricing-job-retry",
    )

    def unavailable(endpoint, headers, body, timeout):
        del endpoint, headers, body, timeout
        raise OSError("provider unavailable")

    result = dispatch_adapter_jobs(db, transport=unavailable)
    assert result == {
        "processed": 1,
        "dispatched": 0,
        "retried": 1,
        "failed": 0,
        "expired": 0,
    }
    job = db.scalar(
        select(HouseDesignerAdapterJob).where(HouseDesignerAdapterJob.job_id == queued["jobId"])
    )
    assert job.status == "QUEUED"
    assert job.attempt_count == 1
    assert job.next_attempt_at is not None


def test_entitlement_activation_requires_fresh_four_eyes_readiness(db, monkeypatch):
    ready = {
        "schemaVersion": "house-designer-release-readiness-v1",
        "readinessSha256": "a" * 64,
        "readyForActivation": True,
        "checks": [{"key": "all", "passed": True, "detail": "verified"}],
    }
    monkeypatch.setattr(
        readiness_service,
        "house_designer_release_readiness",
        lambda db, tenant_id, brand_id: ready,
    )
    requested = request_entitlement_activation(
        db,
        tenant_id=TENANT,
        brand_id=BRAND,
        actor_subject_id="technical-author",
        actor_role="technical-prep",
        expected_row_version=None,
    )
    assert requested["status"] == "pending_review"
    assert requested["orderIntakeEnabled"] is True
    with pytest.raises(HouseDesignerError) as duplicate_request:
        request_entitlement_activation(
            db,
            tenant_id=TENANT,
            brand_id=BRAND,
            actor_subject_id="owner-rewriter",
            actor_role="owner",
            expected_row_version=requested["rowVersion"],
        )
    assert duplicate_request.value.code == "entitlement_request_pending"
    with pytest.raises(HouseDesignerError) as stale_version:
        review_entitlement_activation(
            db,
            tenant_id=TENANT,
            brand_id=BRAND,
            actor_subject_id="managing-director-2",
            actor_role="managing-director",
            approve=True,
            expected_row_version=requested["rowVersion"] + 1,
            expected_readiness_sha256=requested["readinessSha256"],
        )
    assert stale_version.value.code == "entitlement_precondition_failed"
    with pytest.raises(HouseDesignerError) as stale_readiness:
        review_entitlement_activation(
            db,
            tenant_id=TENANT,
            brand_id=BRAND,
            actor_subject_id="managing-director-2",
            actor_role="managing-director",
            approve=True,
            expected_row_version=requested["rowVersion"],
            expected_readiness_sha256="b" * 64,
        )
    assert stale_readiness.value.code == "entitlement_precondition_failed"
    with pytest.raises(HouseDesignerError) as same_actor:
        review_entitlement_activation(
            db,
            tenant_id=TENANT,
            brand_id=BRAND,
            actor_subject_id="technical-author",
            actor_role="owner",
            approve=True,
            expected_row_version=requested["rowVersion"],
            expected_readiness_sha256=requested["readinessSha256"],
        )
    assert same_actor.value.code == "four_eyes_required"
    activated = review_entitlement_activation(
        db,
        tenant_id=TENANT,
        brand_id=BRAND,
        actor_subject_id="managing-director-2",
        actor_role="managing-director",
        approve=True,
        expected_row_version=requested["rowVersion"],
        expected_readiness_sha256=requested["readinessSha256"],
    )
    assert activated["status"] == "active"
    suspended = suspend_entitlement(
        db,
        tenant_id=TENANT,
        brand_id=BRAND,
        actor_subject_id="owner-2",
        actor_role="owner",
        expected_row_version=activated["rowVersion"],
    )
    assert suspended["status"] == "suspended"
    assert suspended["standaloneEnabled"] is False
    assert suspended["orderIntakeEnabled"] is False
    assert suspended["validUntil"] is not None
    requested_again = request_entitlement_activation(
        db,
        tenant_id=TENANT,
        brand_id=BRAND,
        actor_subject_id="technical-author-2",
        actor_role="technical-prep",
        expected_row_version=suspended["rowVersion"],
    )
    assert requested_again["status"] == "pending_review"
    assert requested_again["validUntil"] is None


def test_sandbox_entitlement_is_owner_managed_and_external_writes_stay_closed(db):
    with pytest.raises(HouseDesignerError) as forbidden:
        set_sandbox_entitlement(
            db,
            tenant_id=TENANT,
            brand_id=BRAND,
            actor_subject_id="designer-1",
            actor_role="designer",
            enabled=True,
            expected_row_version=None,
        )
    assert forbidden.value.code == "sandbox_entitlement_forbidden"

    enabled = set_sandbox_entitlement(
        db,
        tenant_id=TENANT,
        brand_id=BRAND,
        actor_subject_id="owner-uat",
        actor_role="owner",
        enabled=True,
        expected_row_version=None,
    )
    assert enabled["status"] == "sandbox"
    assert enabled["standaloneEnabled"] is True
    assert enabled["orderIntakeEnabled"] is False
    assert enabled["productionRenderEnabled"] is False
    assert enabled["productionPricingEnabled"] is False
    assert enabled["productionCapacityEnabled"] is False

    with pytest.raises(HouseDesignerError) as stale_disable:
        set_sandbox_entitlement(
            db,
            tenant_id=TENANT,
            brand_id=BRAND,
            actor_subject_id="managing-director-uat",
            actor_role="managing-director",
            enabled=False,
            expected_row_version=enabled["rowVersion"] + 1,
        )
    assert stale_disable.value.code == "entitlement_precondition_failed"

    disabled = set_sandbox_entitlement(
        db,
        tenant_id=TENANT,
        brand_id=BRAND,
        actor_subject_id="managing-director-uat",
        actor_role="managing-director",
        enabled=False,
        expected_row_version=enabled["rowVersion"],
    )
    assert disabled["status"] == "suspended"
    assert disabled["standaloneEnabled"] is False
    actions = set(
        db.scalars(
            select(AuditLog.action).where(AuditLog.entity_id == disabled["entitlementId"])
        ).all()
    )
    assert "house_designer.entitlement.enable_sandbox" in actions
    assert "house_designer.entitlement.disable_sandbox" in actions


def test_entitlement_review_ui_rejects_stale_form_before_transition(client, db):
    entitlement = HouseDesignerEntitlement(
        entitlement_id="HDENT-STALE-UI",
        tenant_id=TENANT,
        brand_id=BRAND,
        status="pending_review",
        standalone_enabled=True,
        order_intake_enabled=True,
        production_render_enabled=True,
        production_pricing_enabled=True,
        production_capacity_enabled=True,
        created_by="ITEP-DEMO-TECHNICAL-PREP",
        readiness_sha256="c" * 64,
        row_version=7,
    )
    db.add(entitlement)
    db.commit()
    login = client.post(
        "/login",
        data={"email": "owner@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    page = client.get("/house-designer/adapters")
    assert page.status_code == 200
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert csrf
    assert 'name="row_version" value="7"' in page.text
    assert f'name="readiness_sha256" value="{"c" * 64}"' in page.text

    stale = client.post(
        "/house-designer/entitlement/review",
        headers={"Origin": "http://testserver"},
        data={
            "csrf_token": csrf.group(1),
            "row_version": "6",
            "readiness_sha256": "c" * 64,
            "decision": "reject",
        },
        follow_redirects=False,
    )
    assert stale.status_code == 303
    assert stale.headers["location"].endswith("error=entitlement_precondition_failed")
    db.expire_all()
    assert (
        db.scalar(
            select(HouseDesignerEntitlement).where(
                HouseDesignerEntitlement.entitlement_id == entitlement.entitlement_id
            )
        ).status
        == "pending_review"
    )

    rejected = client.post(
        "/house-designer/entitlement/review",
        headers={"Origin": "http://testserver"},
        data={
            "csrf_token": csrf.group(1),
            "row_version": "7",
            "readiness_sha256": "c" * 64,
            "decision": "reject",
        },
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    db.expire_all()
    assert (
        db.scalar(
            select(HouseDesignerEntitlement).where(
                HouseDesignerEntitlement.entitlement_id == entitlement.entitlement_id
            )
        ).status
        == "sandbox"
    )


def test_adapter_admin_and_production_job_screens_are_rendered(client, db):
    design = create_session(
        db,
        actor=ActorScope("ITEP-DEMO-TECHNICAL-PREP", TENANT, frozenset({BRAND}), True),
        brand_id=BRAND,
        title="Adapter UI test",
        command_id="adapter-ui-create",
    )
    login = client.post(
        "/login",
        data={"email": "technical-prep@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    response = client.get("/house-designer/adapters")
    assert response.status_code == 200
    assert "Adapter regisztrálása" in response.text
    assert "A külső adapterkapu környezeti szinten engedélyezve van" in response.text
    assert "Éles aktiválási feltételek" in response.text
    assert "ZÁRVA" in response.text
    readiness = house_designer_release_readiness(db, tenant_id=TENANT, brand_id=BRAND)
    assert readiness["readyForActivation"] is False
    checks = {item["key"]: item["passed"] for item in readiness["checks"]}
    assert checks["site_data_encryption"] is True
    assert checks["runtime_security"] is True
    assert checks["production_release"] is False
    detail = client.get(f"/house-designer/sessions/{design['sessionId']}")
    assert detail.status_code == 200
    assert "Produkciós ár, ütem és látvány" in detail.text
    assert "Még nincs produkciós adapterfeladat" in detail.text
