from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.growth_ops import deepseek as deepseek_service
from app.growth_ops import service, wide_service
from app.growth_ops.canonical_policy import (
    ACTIVE_CONTENT_BRANDS,
    PARTNER_OUTREACH_ANCHOR,
    PARTNER_OUTREACH_ANCHOR_SHA256,
    SOURCE_LEDGER_ROUTE_COUNT,
    assert_outreach_copy,
)
from app.growth_ops.models import CanonicalGrowthDailyRun, DailyContentObligation, GrowthSignal
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


def test_owner_locked_partner_sentence_has_expected_hash():
    assert hashlib.sha256(PARTNER_OUTREACH_ANCHOR.encode()).hexdigest() == (
        PARTNER_OUTREACH_ANCHOR_SHA256
    )
    assert_outreach_copy(f"Tisztelt Partner!\n{PARTNER_OUTREACH_ANCHOR}")
    with pytest.raises(ValueError, match="anchor_missing"):
        assert_outreach_copy("Kérjen most ajánlatot!")


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
    assert row.external_publication_status.startswith("blocked_until")
    assert len(db.scalars(select(DailyContentObligation)).all()) == len(ACTIVE_CONTENT_BRANDS) == 19
    assert len(db.scalars(select(CanonicalGrowthDailyRun)).all()) == 1


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
