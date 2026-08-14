from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models import HouseCatalogPlan, OutboxMessage
from app.schemas import HouseVisionGeometryLockIn, HouseVisionOutputAssetIn, HouseVisionRightsPolicyIn, HouseVisionSourceAssetIn
from app.services.housevision import add_output_asset, add_source_asset, approve_rights_policy, assign_name, bind_houseplan, create_job, create_rights_policy, lock_geometry, package_job, run_qa


def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    actor = "housevision-uat@imperial.local"
    with SessionLocal() as db:
        policy = create_rights_policy(db, HouseVisionRightsPolicyIn(domain="8.8.8.8", path_prefix=f"/housevision-uat/{stamp}", rights_status="licensed", evidence_ref=f"uat://source-rights/{stamp}", max_assets_per_page=8), actor, "platform-admin")
        approve_rights_policy(db, policy.policy_id, actor, "platform-admin")
        job = create_job(db, "imperial", f"https://8.8.8.8/housevision-uat/{stamp}/house", actor)
        exterior = add_source_asset(db, job.job_id, HouseVisionSourceAssetIn(source_url=f"https://8.8.8.8/housevision-uat/{stamp}/exterior.png", asset_type="EXTERIOR", sequence=1, content_sha256="a" * 64, width_px=2400, height_px=1600, magic_mime_type="image/png"), actor)
        floorplan = add_source_asset(db, job.job_id, HouseVisionSourceAssetIn(source_url=f"https://8.8.8.8/housevision-uat/{stamp}/floorplan.png", asset_type="FLOORPLAN", sequence=2, content_sha256="b" * 64, width_px=2400, height_px=1600, magic_mime_type="image/png"), actor)
        geometry = lock_geometry(db, job.job_id, HouseVisionGeometryLockIn(floorplan_topology_sha256="c" * 64, massing_signature="uat-rectangular-massing", roof_form="nyeregtető", roof_pitch_deg=Decimal("35"), storey_count=1, window_count=8, door_count=2, width_depth_height_ratio="1.60:1.00:0.48", immutable_features=["falak", "helyiségkapcsolatok", "nyílásrend", "tetőgerinc"]), actor, "platform-admin")
        name = assign_name(db, job.job_id, f"UAT Visegrád {stamp}", actor)
        for source, digest, floorplan_score in ((exterior, "d", None), (floorplan, "e", Decimal("0.995"))):
            add_output_asset(db, job.job_id, HouseVisionOutputAssetIn(source_visual_id=source.source_visual_id, provider_job_id=f"mock-{source.source_visual_id}", output_ref=f"uat://housevision/{job.job_id}/{source.source_visual_id}.webp", content_sha256=digest * 64, width_px=2400, height_px=1600, edge_overlap=Decimal("0.995"), roof_match=Decimal("0.995"), opening_match=Decimal("0.995"), floorplan_fidelity=floorplan_score, full_house_in_frame=True, daylight_pass=True, photorealism_pass=True, brand_identity_pass=True, privacy_pass=True), actor)
        qa = run_qa(db, job.job_id, actor)
        house_id = f"HOUSE-HV-UAT-{stamp}"
        db.add(HouseCatalogPlan(house_id=house_id, brand="imperial", canonical_name=name.public_name, lifecycle_status="active", current_released_version=1, created_by=actor))
        db.commit()
        bind_houseplan(db, job.job_id, house_id, actor, "platform-admin")
        package = package_job(db, job.job_id, f"uat://housevision/packages/{house_id}.tar.gz", actor)
        handoffs = db.scalars(select(OutboxMessage.destination_module).where(OutboxMessage.payload_json.contains(package.package_id))).all()
        print(f"job={job.job_id} status=READY")
        print(f"geometry_lock={geometry.geometry_lock_id} sha256={geometry.content_sha256}")
        print(f"qa={qa.qa_report_id} status={qa.status}")
        print(f"package={package.package_id} sources={package.source_count} outputs={package.output_count} sha256={package.manifest_sha256}")
        print(f"house_id={house_id} publication={package.publication_status}")
        print("handoffs=" + ",".join(sorted(handoffs)))


if __name__ == "__main__":
    main()
