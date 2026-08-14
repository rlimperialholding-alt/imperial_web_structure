from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from sqlalchemy import select

from app.copy_gate.models import PublicationState
from app.models import (
    ContentAssetRecord,
    ContentImageFactoryRequest,
    CopyBriefRecord,
    CreativeProductionRunRecord,
)
from app.services import content_image_factory as factory


def _asset(db, suffix: str, *, product_id: str | None = None) -> ContentAssetRecord:
    now = datetime.now(UTC)
    brief_id = f"CB-IMAGE-{suffix}"
    brief = {
        "brand_id": "imperial",
        "asset_type": "landing_page",
        "channel": "web",
        "purpose": "Egy ellenőrzött weboldal vizuális támogatása",
        "campaign_objective": "qualified_project_lead",
        "desired_outcome": "Átlátható döntési helyzet",
        "primary_promise": "A döntés műszaki és időhatása érthetően látható.",
        "product_id": product_id,
    }
    db.add(
        CopyBriefRecord(
            copy_brief_id=brief_id,
            brand_id="imperial",
            asset_type="landing_page",
            channel="web",
            page_id=None,
            campaign_id=f"CMP-{suffix}",
            status="STRATEGY_APPROVED",
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=30),
            brief_json=json.dumps(brief, ensure_ascii=False),
            source_snapshot_hash="a" * 64,
            created_by="test",
        )
    )
    asset = ContentAssetRecord(
        asset_id=f"ASSET-IMAGE-{suffix}",
        copy_brief_id=brief_id,
        project_id=None,
        brand_id="imperial",
        asset_type="landing_page",
        channel="web",
        state=PublicationState.VISUAL_PRODUCTION,
        content_version=1,
        content_hash=hashlib.sha256(suffix.encode()).hexdigest(),
        content_json=json.dumps(
            {
                "title": f"Ellenőrzött képi téma {suffix}",
                "purpose": "Vizuális döntéstámogatás",
                "visual_asset_ids": [],
                "content_blocks": [],
            },
            ensure_ascii=False,
        ),
        generation_trace_json=json.dumps(
            {
                "generation_run_id": f"COPY-{suffix}",
                "visual_direction_id": f"VD-{suffix}",
                "image_treatment": "világos, valós építészeti környezet",
                "background_treatment": "természetes nappali fény",
                "typehouse_offer_creative": bool(product_id),
            },
            ensure_ascii=False,
        ),
        gate_1_approved=True,
        expert_language_approved=True,
        expert_marketing_approved=True,
        copywriter_approved=True,
        four_gate_approved=True,
        editorial_approved=True,
        owner_approved=True,
        created_by="test",
    )
    db.add(asset)
    db.commit()
    return asset


def _jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1600, 900), (90, 130, 100)).save(output, "JPEG", quality=90)
    return output.getvalue()


def test_daily_content_assets_are_batched_and_imported_for_director_qa(db):
    asset = _asset(db, "001")
    raw = _jpeg()
    content_sha256 = hashlib.sha256(raw).hexdigest()
    post_response = {
        "batch_id": "BATCH-001",
        "jobs": [
            {
                "job_id": "JOB-001",
                "content_id": asset.asset_id,
                "status": "BRIEF_READY",
            }
        ],
    }
    completed_job = {
        "job_id": "JOB-001",
        "content_id": asset.asset_id,
        "status": "COMPLETED",
        "qa_score": 98,
        "release_state": "TEST_ONLY_REVIEW_REQUIRED",
        "generated_prompt": "one coherent text-free scene",
        "derived_assets": {
            "web_hero": {
                "sha256": content_sha256,
                "dimensions": [1600, 900],
            }
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        test_settings = replace(
            factory.settings,
            content_image_factory_enabled=True,
            content_image_factory_batch_size=100,
            content_image_factory_asset_root=tmp,
            image_factory_api_token="t" * 64,
        )
        with (
            patch.object(factory, "settings", test_settings),
            patch.object(factory, "_api_json", return_value=post_response) as api,
        ):
            queued = factory.queue_eligible_content_assets(db)
            submitted = factory.submit_queued_batches(db)
        assert queued == {"queued": 1, "blocked": 0, "existing": 0}
        assert submitted == {"submitted": 1, "submit_failed": 0}
        assert api.call_args.args[:2] == ("POST", "/api/v1/batches")
        assert len(api.call_args.args[2]["items"]) == 1
        assert api.call_args.args[2]["source_type"] == "content_factory_daily"
        request = db.scalar(
            select(ContentImageFactoryRequest).where(
                ContentImageFactoryRequest.asset_id == asset.asset_id
            )
        )
        request.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

        with (
            patch.object(factory, "settings", test_settings),
            patch.object(
                factory,
                "_api_json",
                return_value={"batch_id": "BATCH-001", "jobs": [completed_job]},
            ),
            patch.object(
                factory,
                "_download_asset",
                return_value=(
                    raw,
                    {
                        "content-type": "image/jpeg",
                        "x-content-sha256": content_sha256,
                        "x-release-state": "TEST_ONLY_REVIEW_REQUIRED",
                    },
                ),
            ),
        ):
            result = factory.poll_submitted_batches(db)

        assert result["imported"] == 1
        db.refresh(request)
        db.refresh(asset)
        assert request.status == "IMPORTED"
        assert request.output_sha256 == content_sha256
        assert request.release_state == "TEST_ONLY_REVIEW_REQUIRED"
        assert asset.state == PublicationState.CREATIVE_DIRECTOR_QA
        creative = db.scalar(
            select(CreativeProductionRunRecord).where(
                CreativeProductionRunRecord.asset_id == asset.asset_id
            )
        )
        assert creative is not None
        assert creative.producer_identity == "imperial-image-factory"
        assert creative.contains_text is False
        assert Path(tmp, f"{creative.generation_run_id}.jpg").is_file()

        assert factory.queue_eligible_content_assets(db)["queued"] == 0
        assert db.query(ContentImageFactoryRequest).count() == 1


def test_typehouse_specific_asset_is_blocked_from_generic_generation(db):
    asset = _asset(db, "TYPEHOUSE", product_id="HOUSE-126")
    queued = factory.queue_eligible_content_assets(db)
    assert queued == {"queued": 0, "blocked": 1, "existing": 0}
    request = db.scalar(
        select(ContentImageFactoryRequest).where(
            ContentImageFactoryRequest.asset_id == asset.asset_id
        )
    )
    assert request.status == "BLOCKED"
    assert "hiteles forráskép" in request.last_error
    with patch.object(factory, "_api_json") as api:
        assert factory.submit_queued_batches(db)["submitted"] == 0
    api.assert_not_called()


def test_changed_content_hash_is_never_imported(db):
    asset = _asset(db, "STALE")
    request = ContentImageFactoryRequest(
        request_id="CIF-STALE",
        asset_id=asset.asset_id,
        content_version=asset.content_version,
        content_sha256="f" * 64,
        status="PROCESSING",
        image_factory_batch_id="BATCH-STALE",
        image_factory_job_id="JOB-STALE",
        requested_role="hero",
        output_role="web_hero",
        request_payload_json="{}",
        next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    db.add(request)
    db.commit()
    job = {
        "job_id": "JOB-STALE",
        "status": "COMPLETED",
        "qa_score": 100,
        "release_state": "TEST_ONLY_REVIEW_REQUIRED",
        "generated_prompt": "safe",
        "derived_assets": {"web_hero": {"sha256": "a" * 64, "dimensions": [1600, 900]}},
    }
    with (
        patch.object(
            factory,
            "_api_json",
            return_value={"batch_id": "BATCH-STALE", "jobs": [job]},
        ),
        patch.object(factory, "_download_asset") as download,
    ):
        result = factory.poll_submitted_batches(db)
    db.refresh(request)
    assert result["failed"] == 1
    assert request.status == "STALE"
    download.assert_not_called()
    assert (
        db.scalar(
            select(CreativeProductionRunRecord).where(
                CreativeProductionRunRecord.asset_id == asset.asset_id
            )
        )
        is None
    )
