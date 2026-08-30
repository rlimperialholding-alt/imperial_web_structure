from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.growth_ops import deepseek as deepseek_service
from app.growth_ops import service, wide_service
from app.growth_ops.canonical_policy import (
    ACTIVE_CONTENT_BRANDS,
    LAND_AGENT_COMMISSION_ANCHOR,
    LAND_OUTREACH_SERVICE_ANCHOR,
    LAND_OWNER_FREE_AD_ANCHOR,
    LAND_OWNER_PERMISSION_ANCHOR,
    LAND_OWNER_REPLY_ANCHOR,
    LAND_OWNER_SERVICE_ANCHOR,
    SOURCE_LEDGER_ROUTE_COUNT,
    DailyGateResult,
    assert_outreach_copy,
)
from app.growth_ops.canonical_templates import CanonicalFirstContactRegistry
from app.growth_ops.models import (
    CanonicalGrowthDailyRun,
    DailyContentObligation,
    GrowthSignal,
    SourceCatalogRevision,
    SourceCoverageAttempt,
    SourceCoverageRoute,
)
from app.growth_ops.registry import GrowthRegistryError
from app.growth_ops.schemas import GrowthSignalIn


def _signal(summary: str, *, motor_key: str = "construction") -> GrowthSignalIn:
    return GrowthSignalIn.model_validate(
        {
            "source_id": "construction-etdr",
            "external_key": hashlib.sha256(summary.encode()).hexdigest(),
            "motor_key": motor_key,
            "source_bucket": "etdr" if motor_key == "construction" else "existing_target_engine",
            "signal_type": "residential_construction"
            if motor_key == "construction"
            else "ivs_target",
            "detected_at": datetime.now(UTC),
            "company_name": "Minta Építő Kft.",
            "company_registration_id": "01-09-999999",
            "subject_type": "organization",
            "recipient_email": "iroda@minta-epito.test",
            "recipient_email_type": "role",
            "contact_basis": "public_business_contact",
            "public_contact_url": "https://minta-epito.test/kapcsolat",
            "summary": summary,
            "evidence_url": "https://source.test/project/1",
            "confidence": 90,
            "urgency": 80,
            "source_payload_hash": hashlib.sha256(b"payload").hexdigest(),
        }
    )


def test_owner_locked_first_contact_registry_replaces_the_generic_anchor():
    registry_path = (
        Path(os.environ["CANONICAL_FIRST_CONTACT_REGISTRY_FILE"])
        if "CANONICAL_FIRST_CONTACT_REGISTRY_FILE" in os.environ
        else Path(__file__).resolve().parents[3]
        / "config"
        / "outbound"
        / "canonical_first_contact_templates_hu_v1.json"
    )
    state = CanonicalFirstContactRegistry.load(registry_path).readiness()

    assert state["status"] == ["OWNER_APPROVED", "CANONICAL"]
    assert {item["template_id"] for item in state["templates"]} == {
        "ARCHITECT_OFFICE_FIRST_CONTACT_HU",
        "LAND_OWNER_FIRST_CONTACT_HU",
        "REAL_ESTATE_AGENT_FIRST_CONTACT_HU",
        "REFERRAL_PARTNER_FIRST_CONTACT_HU",
    }


def test_owner_locked_land_offers_are_distinct_and_required():
    assert_outreach_copy(
        f"{LAND_OUTREACH_SERVICE_ANCHOR}\n{LAND_AGENT_COMMISSION_ANCHOR}"
    )
    assert_outreach_copy(
        "\n".join(
            (
                LAND_OWNER_SERVICE_ANCHOR,
                LAND_OWNER_FREE_AD_ANCHOR,
                LAND_OWNER_PERMISSION_ANCHOR,
                LAND_OWNER_REPLY_ANCHOR,
            )
        )
    )
    with pytest.raises(ValueError, match="offer_missing_or_mixed"):
        assert_outreach_copy(LAND_OUTREACH_SERVICE_ANCHOR)
    with pytest.raises(ValueError, match="offer_missing_or_mixed"):
        assert_outreach_copy(
            f"{LAND_OWNER_SERVICE_ANCHOR}\n{LAND_AGENT_COMMISSION_ANCHOR}\n"
            f"{LAND_OWNER_FREE_AD_ANCHOR}\n{LAND_OWNER_PERMISSION_ANCHOR}\n"
            f"{LAND_OWNER_REPLY_ANCHOR}"
        )


def test_named_no_monitoring_hard_gate_blocks_before_storage(db):
    with pytest.raises(GrowthRegistryError, match="no_monitoring_hard_gate"):
        service.ingest_signal(db, _signal("Homes4you projektinformáció."))
    assert not db.scalars(select(GrowthSignal)).all()


def test_iora_is_internal_only_even_when_contact_fields_exist():
    reasons = service._eligibility(_signal("Érvényes IORA opportunity.", motor_key="ivs"), 95)
    assert "iora_internal_executive_review_only" in reasons


def test_daily_wide_run_creates_all_brand_obligations_and_fails_closed(db, tmp_path, monkeypatch):
    manifest = {
        "spreadsheet_id": "1ddn6e2EbuafPc_S9_eb6oetBQsp4iOO9cFuMD6sQ4H4",
        "sheet_id": 959591161,
        "route_count": SOURCE_LEDGER_ROUTE_COUNT,
        "modified_time": "2026-08-20T11:39:45.518Z",
        "catalog_sha256": "a" * 64,
    }
    manifest_path = tmp_path / "source-ledger-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        wide_service,
        "settings",
        lambda: SimpleNamespace(
            canonical_manifest_file=str(manifest_path),
            canonical_wide_enabled=True,
            canonical_daily_at="05:30",
            timezone="Europe/Budapest",
        ),
    )

    row = wide_service.refresh_daily_run(db, now=datetime(2026, 8, 20, 8, 0, tzinfo=UTC))

    assert row.status == "partial"
    assert row.source_route_catalog_size == SOURCE_LEDGER_ROUTE_COUNT
    assert row.internal_handoff_status == "required_pending"
    assert row.external_outreach_status.startswith("blocked_until")
    assert row.external_publication_status == "owner_approved_live_for_bound_channels" or (
        row.external_publication_status.startswith("blocked_until")
    )
    assert len(db.scalars(select(DailyContentObligation)).all()) == len(ACTIVE_CONTENT_BRANDS) == 19
    assert len(db.scalars(select(CanonicalGrowthDailyRun)).all()) == 1

    original_run_id = row.run_id
    row.spec_version = "stale-spec"
    row.source_manifest_sha256 = "0" * 64
    row.source_route_catalog_size = 1
    db.flush()

    refreshed = wide_service.refresh_daily_run(
        db, now=datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    )

    assert refreshed.run_id == original_run_id
    assert refreshed.spec_version == wide_service.SPEC_VERSION
    assert refreshed.source_manifest_sha256 == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    assert refreshed.source_route_catalog_size == SOURCE_LEDGER_ROUTE_COUNT


def test_quality_first_daily_gate_has_no_lead_quota():
    gate = DailyGateResult(
        route_attempts=1,
        route_target=1,
        unique_leads=0,
        question_topics=80,
        content_brands=19,
    )

    assert gate.passed


def test_daily_wide_route_attempts_exclude_managed_land_route_set(
    db, tmp_path, monkeypatch
):
    catalog_sha = "a" * 64
    manifest = {
        "spreadsheet_id": "1ddn6e2EbuafPc_S9_eb6oetBQsp4iOO9cFuMD6sQ4H4",
        "sheet_id": 959591161,
        "route_count": SOURCE_LEDGER_ROUTE_COUNT,
        "modified_time": "2026-08-20T11:39:45.518Z",
        "catalog_sha256": catalog_sha,
    }
    manifest_path = tmp_path / "source-ledger-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        wide_service,
        "settings",
        lambda: SimpleNamespace(
            canonical_manifest_file=str(manifest_path),
            canonical_wide_enabled=True,
            canonical_daily_at="05:30",
            timezone="Europe/Budapest",
        ),
    )
    now = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
    db.add(
        SourceCatalogRevision(
            revision_id="SCR-CANONICAL-ONLY",
            spreadsheet_id="1ddn6e2EbuafPc_S9_eb6oetBQsp4iOO9cFuMD6sQ4H4",
            sheet_id=959591161,
            source_modified_time="2026-08-20T11:39:45.518Z",
            catalog_sha256=catalog_sha,
            route_count=SOURCE_LEDGER_ROUTE_COUNT,
            status="active",
            imported_at=now,
        )
    )
    db.add(
        SourceCoverageRoute(
            route_key="CANONICAL-1",
            route_id="CANONICAL-1",
            catalog_sha256=catalog_sha,
            motor="construction",
            route_url="https://source.test/canonical",
            source_row_sha256="b" * 64,
            source_record_json="{}",
            enabled=True,
        )
    )
    db.commit()
    row = wide_service.refresh_daily_run(db, now=now)
    for attempt_id, attempt_catalog_sha, route_key in (
        ("SCA-CANONICAL", catalog_sha, "CANONICAL-1"),
        ("SCA-MANAGED-LAND", "f" * 64, "LAND-PUBLIC-HTML:dh"),
    ):
        db.add(
            SourceCoverageAttempt(
                attempt_id=attempt_id,
                route_key=route_key,
                catalog_sha256=attempt_catalog_sha,
                run_id=row.run_id,
                status="succeeded",
                started_at=now,
                completed_at=now,
            )
        )
    db.commit()

    refreshed = wide_service.refresh_daily_run(db, now=now)

    assert refreshed.route_attempts == 1


def test_deepseek_json_requests_disable_default_thinking(db, monkeypatch):
    cfg = SimpleNamespace(
        deepseek_api_key_file="managed-by-test",
        deepseek_base_url="https://api.deepseek.test",
        deepseek_routine_model="deepseek-v4-flash",
        deepseek_high_stakes_model="deepseek-v4-pro",
        deepseek_monthly_budget_usd=25.0,
        deepseek_input_usd_per_million=0.435,
        deepseek_output_usd_per_million=0.87,
    )
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            }

    def fake_post(_url, **kwargs):
        captured.update(kwargs["json"])
        return FakeResponse()

    monkeypatch.setattr(deepseek_service, "settings", lambda: cfg)
    monkeypatch.setattr(deepseek_service, "_api_key", lambda: "test-key")
    monkeypatch.setattr(deepseek_service.httpx, "post", fake_post)
    result = deepseek_service.complete_json(
        db,
        system_prompt="Return JSON.",
        user_prompt="Health check.",
        purpose="test",
        run_id=None,
    )

    assert captured["thinking"] == {"type": "disabled"}
    assert result.content == '{"ok":true}'
