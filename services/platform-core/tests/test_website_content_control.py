from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import (
    ContentAssetRecord,
    CopyBriefRecord,
    CreativeProductionRunRecord,
    OutboxMessage,
    PublicationBundleRecord,
    WebsitePublicationIncident,
    WebsiteReleaseTarget,
    WebsiteRouteState,
)
from app.schemas import (
    WebsiteDeliveryReceiptIn,
    WebsiteReleaseIn,
    WebsiteSiteIn,
    WebsiteSmokeTestIn,
    WebsiteTargetIn,
)
from app.services.website_content import (
    create_release,
    dispatch_release,
    record_delivery_receipt,
    record_smoke_test,
    register_site,
    rollback_release,
    set_kill_switch,
)
from app.seed import DEMO_PASSWORD


def _published_asset(db, suffix: str = "BASE", brand_id: str = "imperial") -> ContentAssetRecord:
    now = datetime.now(UTC)
    brief_id = f"CB-WEB-{suffix}"
    asset_id = f"ASSET-WEB-{suffix}"
    run_id = f"VIS-WEB-{suffix}"
    bundle_id = f"BUNDLE-WEB-{suffix}"
    content_hash = hashlib.sha256(f"approved-content:{suffix}".encode()).hexdigest()
    db.add(
        CopyBriefRecord(
            copy_brief_id=brief_id,
            brand_id=brand_id,
            asset_type="knowledge_page",
            channel="web",
            status="STRATEGY_APPROVED",
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=90),
            brief_json="{}",
            source_snapshot_hash="a" * 64,
            created_by="marketing@imperial.local",
        )
    )
    db.add(
        CreativeProductionRunRecord(
            generation_run_id=run_id,
            asset_id=asset_id,
            content_version=1,
            sequence_number=1,
            producer_identity="creative-producer",
            visual_direction_id=f"DIR-WEB-{suffix}",
            platform="web",
            width_px=1600,
            height_px=900,
            output_uri=f"s3://controlled-content/{suffix}.webp",
            output_sha256="b" * 64,
            generation_prompt_hash="c" * 64,
            contains_text=False,
            status="APPROVED",
            created_by="creative-producer",
        )
    )
    db.add(
        PublicationBundleRecord(
            bundle_id=bundle_id,
            asset_id=asset_id,
            content_version=1,
            content_hash=content_hash,
            visual_generation_run_id=run_id,
            assembly_run_id=f"ASM-WEB-{suffix}",
            assembler_identity="production-designer",
            bundle_hash="d" * 63 + content_hash[0],
            exports_json='{"web":"approved"}',
            pairing_rationale="A jóváhagyott szöveg és vizuál változatlan párosítása.",
            status="APPROVED",
            created_by="production-designer",
        )
    )
    asset = ContentAssetRecord(
        asset_id=asset_id,
        copy_brief_id=brief_id,
        brand_id=brand_id,
        asset_type="knowledge_page",
        channel="web",
        state="PUBLISHED",
        content_version=1,
        content_hash=content_hash,
        content_json=json.dumps({"title": f"Ellenőrzött webtartalom {suffix}", "body": "Jóváhagyott tartalom."}, ensure_ascii=False),
        gate_1_approved=True,
        expert_language_approved=True,
        expert_marketing_approved=True,
        copywriter_approved=True,
        four_gate_approved=True,
        editorial_approved=True,
        owner_approved=True,
        source_prevalidated=True,
        creative_director_approved=True,
        assembly_approved=True,
        campaign_package_approved=True,
        campaign_package_hash="e" * 64,
        campaign_artifact_set_hash="f" * 64,
        release_approved=True,
        live_review_approved=True,
        active_bundle_id=bundle_id,
        publication_proof_id=f"PROOF-WEB-{suffix}",
        published_at=now,
        created_by="marketing@imperial.local",
    )
    db.add(asset)
    db.commit()
    return asset


def _site(db, suffix: str, *, brand_id: str = "imperial"):
    octet = 8 if suffix == "A" else 1
    return register_site(
        db,
        WebsiteSiteIn(
            brand_id=brand_id,
            name=f"Kontrollált webhely {suffix}",
            base_url=f"https://{octet}.{octet}.{octet}.{octet}/site-{suffix.lower()}",
            adapter_endpoint=f"https://{octet}.{octet}.{octet}.{octet}/internal/content-adapter",
            credential_ref=f"vault://website/{suffix.lower()}",
        ),
        "platform-admin@imperial.local",
        "platform-admin",
    )


def _release(db, asset_id: str, sites, route: str = "/tudastar/uat"):
    return create_release(
        db,
        WebsiteReleaseIn(
            asset_id=asset_id,
            targets=[WebsiteTargetIn(site_id=site.site_id, route_path=route, locale="hu-HU") for site in sites],
        ),
        "marketing@imperial.local",
        "marketing",
    )


def _deliver_and_smoke(db, release, *, fail_target_id: str | None = None):
    dispatch_release(db, release.release_id, "marketing@imperial.local", "marketing")
    targets = db.scalars(select(WebsiteReleaseTarget).where(WebsiteReleaseTarget.release_id == release.release_id).order_by(WebsiteReleaseTarget.target_id)).all()
    for index, target in enumerate(targets, start=1):
        record_delivery_receipt(
            db,
            WebsiteDeliveryReceiptIn(
                target_id=target.target_id,
                idempotency_key=target.target_id,
                success=True,
                external_version_id=f"cms-v{release.version}-{index}",
                published_url=target.canonical_url + "?verified=1",
                rendered_content_sha256=release.content_sha256,
            ),
            "adapter",
            "adapter",
        )
    for target in targets:
        if release.status == "failed":
            break
        passing = target.target_id != fail_target_id
        record_smoke_test(
            db,
            target.target_id,
            WebsiteSmokeTestIn(
                http_status=200,
                rendered_content_sha256=release.content_sha256,
                link_pass=passing,
                form_pass=True,
                schema_pass=True,
                canonical_pass=True,
                accessibility_pass=True,
                analytics_pass=True,
                crm_pass=True,
                privacy_pass=True,
                mobile_render_pass=True,
            ),
            "smoke-runner",
            "smoke-runner",
        )
    db.refresh(release)
    return targets


def test_multi_site_release_requires_all_receipts_and_all_smoke_gates(db):
    asset = _published_asset(db)
    sites = [_site(db, "A"), _site(db, "B")]
    release = _release(db, asset.asset_id, sites)
    assert len(release.release_manifest_sha256) == 64

    targets = _deliver_and_smoke(db, release)
    assert release.status == "live"
    assert all(target.status == "live" for target in targets)
    routes = db.scalars(select(WebsiteRouteState)).all()
    assert len(routes) == 2
    assert {route.current_release_id for route in routes} == {release.release_id}
    messages = db.scalars(select(OutboxMessage)).all()
    assert len([row for row in messages if row.destination_module.startswith("website-adapter:")]) == 2
    assert {row.destination_module for row in messages if "CONTENT_PUBLISHED" in row.payload_json} == {"analytics", "crm", "control-center"}


def test_new_version_supersedes_and_manual_rollback_restores_last_known_good(db):
    asset = _published_asset(db, "ROLLBACK")
    sites = [_site(db, "A"), _site(db, "B")]
    first = _release(db, asset.asset_id, sites)
    first_targets = _deliver_and_smoke(db, first)
    second = _release(db, asset.asset_id, sites)
    second_targets = _deliver_and_smoke(db, second)

    assert second.status == "live"
    assert all(target.status == "superseded" for target in first_targets)
    assert {target.previous_target_id for target in second_targets} == {target.target_id for target in first_targets}
    rolled_back = rollback_release(
        db,
        second.release_id,
        "A visszaolvasott üzleti ellenőrzés eltérést jelzett, ezért visszaállítjuk az előző verziót.",
        "owner@imperial.local",
        "owner",
    )
    assert rolled_back.status == "rolled_back"
    assert all(target.status == "rolled_back" for target in second_targets)
    assert all(target.status == "live" for target in first_targets)
    assert {row.current_target_id for row in db.scalars(select(WebsiteRouteState)).all()} == {target.target_id for target in first_targets}
    assert {row.destination_module for row in db.scalars(select(OutboxMessage)).all() if "CONTENT_ROLLED_BACK" in row.payload_json} == {"analytics", "crm", "control-center"}


def test_smoke_failure_queues_automatic_rollback_without_replacing_live_route(db):
    asset = _published_asset(db, "FAIL")
    sites = [_site(db, "A"), _site(db, "B")]
    first = _release(db, asset.asset_id, sites)
    first_targets = _deliver_and_smoke(db, first)
    baseline = {row.site_id: row.current_target_id for row in db.scalars(select(WebsiteRouteState)).all()}
    second = _release(db, asset.asset_id, sites)
    dispatch_release(db, second.release_id, "marketing@imperial.local", "marketing")
    second_targets = db.scalars(select(WebsiteReleaseTarget).where(WebsiteReleaseTarget.release_id == second.release_id).order_by(WebsiteReleaseTarget.target_id)).all()
    for index, target in enumerate(second_targets, start=1):
        record_delivery_receipt(db, WebsiteDeliveryReceiptIn(target_id=target.target_id, idempotency_key=target.target_id, success=True, external_version_id=f"bad-v{index}", published_url=target.canonical_url, rendered_content_sha256=second.content_sha256), "adapter", "adapter")
    record_smoke_test(db, second_targets[0].target_id, WebsiteSmokeTestIn(http_status=200, rendered_content_sha256=second.content_sha256, link_pass=False, form_pass=True, schema_pass=True, canonical_pass=True, accessibility_pass=True, analytics_pass=True, crm_pass=True, privacy_pass=True, mobile_render_pass=True), "smoke-runner", "smoke-runner")
    db.refresh(second)
    assert second.status == "failed"
    assert second.auto_rollback_status == "queued"
    assert all(target.status == "rollback_queued" for target in second_targets)
    assert {row.site_id: row.current_target_id for row in db.scalars(select(WebsiteRouteState)).all()} == baseline
    assert all(target.status == "live" for target in first_targets)
    incident = db.scalar(select(WebsitePublicationIncident).where(WebsitePublicationIncident.release_id == second.release_id))
    assert incident and incident.status == "open" and incident.severity == "critical"


def test_fail_closed_brand_kill_switch_canonical_hash_and_role_controls(db):
    asset = _published_asset(db, "GATES")
    imperial_site = _site(db, "A")
    other_site = _site(db, "B", brand_id="timberhaus")
    with pytest.raises(ValueError, match="márkája"):
        _release(db, asset.asset_id, [other_site])
    with pytest.raises(PermissionError):
        create_release(db, WebsiteReleaseIn(asset_id=asset.asset_id, targets=[WebsiteTargetIn(site_id=imperial_site.site_id, route_path="/x")]), "copywriter@imperial.local", "copywriter")
    set_kill_switch(db, imperial_site.site_id, True, "Kontrollált UAT kill switch ellenőrzés.", "owner@imperial.local", "owner")
    with pytest.raises(ValueError, match="kill switch"):
        _release(db, asset.asset_id, [imperial_site])
    set_kill_switch(db, imperial_site.site_id, False, "Kontrollált UAT kill switch feloldása.", "owner@imperial.local", "owner")
    release = _release(db, asset.asset_id, [imperial_site])
    dispatch_release(db, release.release_id, "marketing@imperial.local", "marketing")
    target = db.scalar(select(WebsiteReleaseTarget).where(WebsiteReleaseTarget.release_id == release.release_id))
    with pytest.raises(ValueError, match="canonical"):
        record_delivery_receipt(db, WebsiteDeliveryReceiptIn(target_id=target.target_id, idempotency_key=target.target_id, success=True, external_version_id="cms-forged", published_url=target.canonical_url + "-forged", rendered_content_sha256=release.content_sha256), "adapter", "adapter")
    with pytest.raises(ValueError, match="hash"):
        record_delivery_receipt(db, WebsiteDeliveryReceiptIn(target_id=target.target_id, idempotency_key=target.target_id, success=True, external_version_id="cms-forged", published_url=target.canonical_url, rendered_content_sha256="0" * 64), "adapter", "adapter")
    changed_release = _release(db, asset.asset_id, [imperial_site], route="/tudastar/changed-after-approval")
    asset.publication_proof_id = "PROOF-WEB-CHANGED"
    db.commit()
    with pytest.raises(ValueError, match="megváltozott"):
        dispatch_release(db, changed_release.release_id, "marketing@imperial.local", "marketing")
    with pytest.raises(ValueError, match="jelszót"):
        register_site(db, WebsiteSiteIn(brand_id="imperial", name="Tiltott credential URL", base_url="https://user:secret@8.8.8.8/site", adapter_endpoint="https://8.8.8.8/adapter", credential_ref="vault://website/blocked"), "platform-admin@imperial.local", "platform-admin")


def test_website_content_control_ui_is_role_protected(client):
    login = client.post("/login", data={"email": "marketing@imperial.local", "password": DEMO_PASSWORD}, follow_redirects=False)
    assert login.status_code == 303
    assert client.get("/website-content-control").status_code == 200
    client.get("/logout")
    login = client.post("/login", data={"email": "subcontractor@imperial.local", "password": DEMO_PASSWORD}, follow_redirects=False)
    assert login.status_code == 303
    assert client.get("/website-content-control").status_code == 403
