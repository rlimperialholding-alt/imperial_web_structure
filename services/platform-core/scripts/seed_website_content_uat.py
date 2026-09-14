from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    ContentAssetRecord,
    CopyBriefRecord,
    CreativeProductionRunRecord,
    OutboxMessage,
    PublicationBundleRecord,
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


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _approved_uat_asset(db, suffix: str, actor: str) -> ContentAssetRecord:
    now = datetime.now(UTC)
    brief_id = f"CB-WEB-UAT-{suffix}"
    asset_id = f"ASSET-WEB-UAT-{suffix}"
    run_id = f"VIS-WEB-UAT-{suffix}"
    bundle_id = f"BUNDLE-WEB-UAT-{suffix}"
    content = {
        "title": "Website Content Control szerver UAT",
        "body": "Kizárólag szintetikus tesztadat; külső publikációra nem használható.",
        "synthetic_test_data": True,
        "uat_suffix": suffix,
    }
    content_hash = _sha(json.dumps(content, ensure_ascii=False, sort_keys=True))
    db.add(
        CopyBriefRecord(
            copy_brief_id=brief_id,
            brand_id="imperial",
            asset_type="website_uat",
            channel="web",
            status="STRATEGY_APPROVED",
            valid_from=now - timedelta(minutes=5),
            valid_until=now + timedelta(days=1),
            brief_json=json.dumps({"synthetic_test_data": True}, sort_keys=True),
            source_snapshot_hash=_sha(f"source:{suffix}"),
            created_by=actor,
        )
    )
    db.flush()
    db.add(
        CreativeProductionRunRecord(
            generation_run_id=run_id,
            asset_id=asset_id,
            content_version=1,
            sequence_number=1,
            producer_identity="website-uat-runner",
            visual_direction_id=f"DIR-WEB-UAT-{suffix}",
            platform="web",
            width_px=1600,
            height_px=900,
            output_uri=f"uat://website-content/{suffix}.webp",
            output_sha256=_sha(f"visual:{suffix}"),
            generation_prompt_hash=_sha(f"prompt:{suffix}"),
            contains_text=False,
            status="APPROVED",
            created_by=actor,
        )
    )
    db.flush()
    db.add(
        PublicationBundleRecord(
            bundle_id=bundle_id,
            asset_id=asset_id,
            content_version=1,
            content_hash=content_hash,
            visual_generation_run_id=run_id,
            assembly_run_id=f"ASM-WEB-UAT-{suffix}",
            assembler_identity="website-uat-runner",
            bundle_hash=_sha(f"bundle:{suffix}"),
            exports_json=json.dumps({"web": "synthetic_uat"}, sort_keys=True),
            pairing_rationale="Szintetikus szerver UAT asset és vizuál determinisztikus párosítása.",
            status="APPROVED",
            created_by=actor,
        )
    )
    db.flush()
    asset = ContentAssetRecord(
        asset_id=asset_id,
        copy_brief_id=brief_id,
        brand_id="imperial",
        asset_type="website_uat",
        channel="web",
        state="PUBLISHED",
        content_version=1,
        content_hash=content_hash,
        content_json=json.dumps(content, ensure_ascii=False, sort_keys=True),
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
        campaign_package_hash=_sha(f"campaign:{suffix}"),
        campaign_artifact_set_hash=_sha(f"artifacts:{suffix}"),
        release_approved=True,
        live_review_approved=True,
        active_bundle_id=bundle_id,
        publication_proof_id=f"PROOF-WEB-UAT-{suffix}",
        published_at=now,
        created_by=actor,
    )
    db.add(asset)
    db.commit()
    return asset


def _complete_release(db, release, actor: str) -> list[WebsiteReleaseTarget]:
    dispatch_release(db, release.release_id, actor, "platform-admin")
    targets = db.scalars(
        select(WebsiteReleaseTarget)
        .where(WebsiteReleaseTarget.release_id == release.release_id)
        .order_by(WebsiteReleaseTarget.target_id)
    ).all()
    for index, target in enumerate(targets, start=1):
        record_delivery_receipt(
            db,
            WebsiteDeliveryReceiptIn(
                target_id=target.target_id,
                idempotency_key=target.target_id,
                success=True,
                external_version_id=f"uat-cms-v{release.version}-{index}",
                published_url=target.canonical_url + "?uat=verified",
                rendered_content_sha256=release.content_sha256,
            ),
            "website-uat-adapter",
            "adapter",
        )
    for target in targets:
        record_smoke_test(
            db,
            target.target_id,
            WebsiteSmokeTestIn(
                http_status=200,
                rendered_content_sha256=release.content_sha256,
                link_pass=True,
                form_pass=True,
                schema_pass=True,
                canonical_pass=True,
                accessibility_pass=True,
                analytics_pass=True,
                crm_pass=True,
                privacy_pass=True,
                mobile_render_pass=True,
            ),
            "website-uat-smoke-runner",
            "smoke-runner",
        )
    db.refresh(release)
    if release.status != "live":
        raise RuntimeError(f"A release nem lett live: {release.release_id}={release.status}")
    return targets


def run(suffix: str, actor: str) -> dict:
    with SessionLocal() as db:
        preexisting_message_ids = set(db.scalars(select(OutboxMessage.message_id)).all())
        asset = _approved_uat_asset(db, suffix, actor)
        sites = [
            register_site(
                db,
                WebsiteSiteIn(
                    brand_id="imperial",
                    name=f"Website szerver UAT A {suffix}",
                    base_url=f"https://8.8.8.8/imperial-uat/{suffix}/a",
                    adapter_endpoint=f"https://8.8.8.8/imperial-uat-adapter/{suffix}/a",
                    credential_ref=f"uat-only://website/{suffix}/a",
                ),
                actor,
                "platform-admin",
            ),
            register_site(
                db,
                WebsiteSiteIn(
                    brand_id="imperial",
                    name=f"Website szerver UAT B {suffix}",
                    base_url=f"https://1.1.1.1/imperial-uat/{suffix}/b",
                    adapter_endpoint=f"https://1.1.1.1/imperial-uat-adapter/{suffix}/b",
                    credential_ref=f"uat-only://website/{suffix}/b",
                ),
                actor,
                "platform-admin",
            ),
        ]
        target_inputs = [
            WebsiteTargetIn(site_id=site.site_id, route_path="/tudastar/website-uat", locale="hu-HU")
            for site in sites
        ]
        first = create_release(db, WebsiteReleaseIn(asset_id=asset.asset_id, targets=target_inputs), actor, "platform-admin")
        first_targets = _complete_release(db, first, actor)
        second = create_release(db, WebsiteReleaseIn(asset_id=asset.asset_id, targets=target_inputs), actor, "platform-admin")
        second_targets = _complete_release(db, second, actor)
        rollback_release(
            db,
            second.release_id,
            "Szintetikus szerver UAT: az előző last-known-good verzió kontrollált visszaállítása.",
            actor,
            "platform-admin",
        )
        routes = db.scalars(
            select(WebsiteRouteState).where(WebsiteRouteState.current_release_id == first.release_id)
        ).all()
        if len(routes) != 2 or {row.current_target_id for row in routes} != {
            row.target_id for row in first_targets
        }:
            raise RuntimeError("A rollback nem az előző két last-known-good célverziót állította vissza.")
        for site in sites:
            set_kill_switch(
                db,
                site.site_id,
                True,
                "A szintetikus szerver UAT lezárult; külső adapterforgalom tiltva.",
                actor,
                "platform-admin",
            )
        uat_messages = db.scalars(
            select(OutboxMessage).where(~OutboxMessage.message_id.in_(preexisting_message_ids))
        ).all()
        for message in uat_messages:
            message.status = "sent"
            message.last_error = "UAT_MANUAL_ADAPTER_SIMULATION_NO_EXTERNAL_DELIVERY"
        db.commit()
        db.refresh(second)
        return {
            "suffix": suffix,
            "asset_id": asset.asset_id,
            "site_ids": [site.site_id for site in sites],
            "first_release_id": first.release_id,
            "second_release_id": second.release_id,
            "final_release_status": second.status,
            "restored_route_count": len(routes),
            "first_target_statuses": [row.status for row in first_targets],
            "second_target_statuses": [row.status for row in second_targets],
            "uat_outbox_closed": len(uat_messages),
            "kill_switches_enabled": all(site.kill_switch for site in sites),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suffix", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--actor", default="platform-admin@imperial.local")
    args = parser.parse_args()
    print(json.dumps(run(args.suffix, args.actor), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
