from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from dataclasses import replace

import pytest
from PIL import Image
from sqlalchemy import select

from app.models import (
    HouseCatalogPlan,
    HouseVisionGeometryLock,
    HouseVisionJob,
    HouseVisionOutputAsset,
    HouseVisionPackage,
    OutboxMessage,
)
from app.roles import can_access_role
from app.services import housevision as housevision_service
from app.services import housevision_render_bridge
from app.services.housevision_source_ingest import IngestedAsset

SOURCE_URL = "https://8.8.8.8/lawful-house/source-page"


def approve_rights(client, domain: str = "8.8.8.8", path: str = "/lawful-house") -> str:
    response = client.post(
        "/api/housevision/rights",
        json={
            "domain": domain,
            "path_prefix": path,
            "rights_status": "licensed",
            "evidence_ref": "drive://legal/source-license-001",
            "crawl_delay_seconds": 2,
            "max_assets_per_page": 8,
        },
    )
    assert response.status_code == 200, response.text
    policy_id = response.json()["policy_id"]
    response = client.post(f"/api/housevision/rights/{policy_id}/approve")
    assert response.status_code == 200 and response.json()["active"] is True
    return policy_id


def create_job(client) -> str:
    response = client.post(
        "/api/housevision/jobs",
        json={
            "brand_id": "imperial",
            "source_url": SOURCE_URL,
            "operation_mode": "package_only",
            "render_provider": "mock",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "SOURCE_CRAWL"
    return response.json()["job_id"]


def add_source(client, job_id: str, asset_type: str, sequence: int, digest_char: str) -> str:
    digest = digest_char if len(digest_char) == 64 else digest_char * 64
    response = client.post(
        f"/api/housevision/jobs/{job_id}/sources",
        json={
            "source_url": f"https://8.8.8.8/lawful-house/{asset_type.lower()}.png",
            "asset_type": asset_type,
            "sequence": sequence,
            "content_sha256": digest,
            "width_px": 2400,
            "height_px": 1600,
            "magic_mime_type": "image/png",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["source_visual_id"]


def add_output(
    client,
    job_id: str,
    source_visual_id: str,
    digest_char: str,
    *,
    floorplan: bool = False,
    passing: bool = True,
):
    score = "0.99" if passing else "0.40"
    return client.post(
        f"/api/housevision/jobs/{job_id}/outputs",
        json={
            "source_visual_id": source_visual_id,
            "provider_job_id": f"provider-{digest_char}",
            "output_ref": f"s3://housevision/{job_id}/{digest_char}.webp",
            "content_sha256": digest_char * 64,
            "width_px": 2400,
            "height_px": 1600,
            "edge_overlap": score,
            "roof_match": score,
            "opening_match": score,
            "floorplan_fidelity": score if floorplan else None,
            "full_house_in_frame": passing,
            "daylight_pass": passing,
            "photorealism_pass": passing,
            "brand_identity_pass": passing,
            "privacy_pass": passing,
        },
    )


def prepare_rendering_job(client):
    approve_rights(client)
    job_id = create_job(client)
    exterior = add_source(client, job_id, "EXTERIOR", 1, "a")
    floorplan = add_source(client, job_id, "FLOORPLAN", 2, "b")
    response = client.post(
        f"/api/housevision/jobs/{job_id}/geometry-lock",
        json={
            "floorplan_topology_sha256": "c" * 64,
            "massing_signature": "rectangular-two-wing",
            "roof_form": "nyeregtető",
            "roof_pitch_deg": "35",
            "storey_count": 1,
            "window_count": 8,
            "door_count": 2,
            "width_depth_height_ratio": "1.60:1.00:0.48",
            "immutable_features": [
                "külső falak",
                "nyílásrend",
                "tetőgerinc",
                "helyiségkapcsolatok",
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["content_sha256"]) == 64
    response = client.post(
        f"/api/housevision/jobs/{job_id}/name", params={"public_name": "Visegrád Ház"}
    )
    assert response.status_code == 200, response.text
    return job_id, exterior, floorplan


def test_housevision_full_rights_geometry_qa_package_and_handoffs(
    client, db, monkeypatch, tmp_path
):
    approve_rights(client)
    job_id = create_job(client)
    monkeypatch.setattr(
        housevision_render_bridge,
        "settings",
        replace(
            housevision_render_bridge.settings,
            typehouse_factory_asset_root=str(tmp_path),
        ),
    )
    source_dir = tmp_path / "legacy" / job_id / "source"
    source_dir.mkdir(parents=True)
    source_ids = []
    for sequence, asset_type, color in (
        (1, "EXTERIOR", "steelblue"),
        (2, "FLOORPLAN", "white"),
    ):
        buffer = BytesIO()
        Image.new("RGB", (96, 64), color).save(buffer, format="PNG")
        payload = buffer.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        (source_dir / f"{sequence:02d}-{digest[:16]}.png").write_bytes(payload)
        source_ids.append(add_source(client, job_id, asset_type, sequence, digest))
    exterior, floorplan = source_ids
    lock = client.post(
        f"/api/housevision/jobs/{job_id}/geometry-lock",
        json={
            "floorplan_topology_sha256": "c" * 64,
            "massing_signature": "rectangular-two-wing",
            "roof_form": "nyeregtető",
            "roof_pitch_deg": "35",
            "storey_count": 1,
            "window_count": 8,
            "door_count": 2,
            "width_depth_height_ratio": "1.60:1.00:0.48",
            "immutable_features": ["külső falak", "nyílásrend", "tetőgerinc"],
        },
    )
    assert lock.status_code == 200, lock.text
    named = client.post(
        f"/api/housevision/jobs/{job_id}/name", params={"public_name": "Visegrád Ház"}
    )
    assert named.status_code == 200, named.text
    baseline = housevision_render_bridge.create_source_preserved_baseline(
        db, job_id, "test@imperial.local"
    )
    assert len(baseline["created"]) == 2
    qa = client.post(f"/api/housevision/jobs/{job_id}/qa")
    assert qa.status_code == 200 and qa.json()["status"] == "PASS"

    db.add(
        HouseCatalogPlan(
            house_id="HOUSE-HV-001",
            brand="imperial",
            canonical_name="Visegrád Ház",
            lifecycle_status="active",
            current_released_version=1,
            created_by="test",
        )
    )
    db.commit()
    packaged = client.post(
        f"/api/housevision/jobs/{job_id}/package",
        params={"storage_ref": "s3://housevision/packages/HOUSE-HV-001-v1.tar.gz"},
    )
    assert packaged.status_code == 200, packaged.text
    assert len(packaged.json()["manifest_sha256"]) == 64
    assert packaged.json()["publication_status"] == "blocked"
    bound = client.post(f"/api/housevision/jobs/{job_id}/bind/HOUSE-HV-001")
    assert bound.status_code == 200 and bound.json()["house_id"] == "HOUSE-HV-001"

    job = db.scalar(select(HouseVisionJob).where(HouseVisionJob.job_id == job_id))
    package = db.scalar(select(HouseVisionPackage).where(HouseVisionPackage.job_id == job_id))
    db.refresh(package)
    assert job.status == "READY" and job.publication_eligibility == "eligible"
    assert (
        package.source_count == package.output_count == 2
        and package.publication_status == "eligible"
    )
    destinations = set(db.scalars(select(OutboxMessage.destination_module)).all())
    assert {
        "document-evidence",
        "buildconfig",
        "house-catalog",
        "content-factory",
        "marketing-control",
        "control-center",
    }.issubset(destinations)


def test_rights_and_ssrf_fail_closed(client, db):
    unknown = client.post(
        "/api/housevision/jobs",
        json={"brand_id": "imperial", "source_url": "https://8.8.8.8/unlicensed/house"},
    )
    assert unknown.status_code == 200 and unknown.json()["status"] == "RIGHTS_BLOCKED"
    private = client.post(
        "/api/housevision/jobs",
        json={"brand_id": "imperial", "source_url": "http://127.0.0.1/internal"},
    )
    assert private.status_code == 409
    metadata = client.post(
        "/api/housevision/jobs",
        json={"brand_id": "imperial", "source_url": "http://169.254.169.254/latest/meta-data"},
    )
    assert metadata.status_code == 409
    approve_rights(client, path="/unlicensed")
    rechecked = client.post(f"/api/housevision/jobs/{unknown.json()['job_id']}/rights-recheck")
    assert rechecked.status_code == 200 and rechecked.json()["status"] == "SOURCE_CRAWL"
    stored = db.scalars(select(HouseVisionJob)).all()
    assert len(stored) == 1 and stored[0].status == "SOURCE_CRAWL"


def test_geometry_lock_requires_exterior_and_floorplan(client):
    approve_rights(client)
    job_id = create_job(client)
    add_source(client, job_id, "EXTERIOR", 1, "a")
    response = client.post(
        f"/api/housevision/jobs/{job_id}/geometry-lock",
        json={
            "floorplan_topology_sha256": "c" * 64,
            "massing_signature": "rectangular",
            "roof_form": "nyeregtető",
            "storey_count": 1,
            "window_count": 8,
            "door_count": 2,
            "width_depth_height_ratio": "1.6:1:0.5",
            "immutable_features": ["walls"],
        },
    )
    assert response.status_code == 409


def test_qa_retries_three_times_then_fails_closed(client, db):
    job_id, exterior, floorplan = prepare_rendering_job(client)
    for revision in range(4):
        digest_one = "d" if revision % 2 == 0 else "e"
        digest_two = "f" if revision % 2 == 0 else "1"
        assert add_output(client, job_id, exterior, digest_one, passing=False).status_code == 200
        assert (
            add_output(
                client, job_id, floorplan, digest_two, floorplan=True, passing=False
            ).status_code
            == 200
        )
        qa = client.post(f"/api/housevision/jobs/{job_id}/qa")
        assert qa.status_code == 200
    job = db.scalar(select(HouseVisionJob).where(HouseVisionJob.job_id == job_id))
    assert job.status == "JOB_FAILED" and job.retry_count == 3
    assert qa.json()["automatic_retry"] is False


def test_housevision_workbench_and_role_access(logged_in_client, client):
    response = logged_in_client.get("/housevision")
    assert response.status_code == 200
    for marker in (
        "SOURCE RIGHTS",
        "GeometryLock",
        "Renderkimenet",
        "QA- és csomagbizonyíték",
        "HousePlan kötése",
    ):
        assert marker in response.text
    client.post("/logout")
    login = client.post(
        "/login",
        data={"email": "subcontractor@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert client.get("/housevision").status_code == 403
    for role in (
        "owner",
        "managing-director",
        "marketing",
        "creative-director",
        "technical-prep",
        "designer",
        "legal",
        "platform-admin",
    ):
        assert can_access_role(role, "housevision") is True
    for role in (
        "finance",
        "project-manager",
        "sales",
        "subcontractor",
        "customer",
        "copywriter",
        "language-editor",
    ):
        assert can_access_role(role, "housevision") is False


def test_housevision_queue_detail_upload_and_compare_screens(logged_in_client, client):
    job_id, exterior, floorplan = prepare_rendering_job(client)
    assert add_output(client, job_id, exterior, "d").status_code == 200
    assert add_output(client, job_id, floorplan, "e", floorplan=True).status_code == 200

    queue = logged_in_client.get(f"/housevision?q={job_id}&status=QA&brand_id=imperial")
    assert queue.status_code == 200
    assert job_id in queue.text
    assert "Aktív munkák" in queue.text

    detail = logged_in_client.get(f"/housevision/jobs/{job_id}")
    assert detail.status_code == 200
    for marker in (
        "Következő üzleti lépés",
        "Jog és forrásbizonyíték",
        "GeometryLock",
        "QA- és csomagbizonyíték",
    ):
        assert marker in detail.text

    upload = logged_in_client.get(f"/housevision/jobs/{job_id}/upload")
    assert upload.status_code == 200
    assert "Manuális asset-bevitel" in upload.text
    assert "Nem állít automatikus képgenerálást" in upload.text

    compare = logged_in_client.get(f"/housevision/jobs/{job_id}/compare")
    assert compare.status_code == 200
    assert "Forrás–kimenet megfelelőség" in compare.text
    assert "GeometryLock verziók" in compare.text
    assert "0.990000" in compare.text

    assert logged_in_client.get("/housevision/jobs/HVJ-NOT-FOUND").status_code == 404


def test_housevision_ui_action_permissions_are_fail_closed(logged_in_client, client):
    job_id, exterior, _floorplan = prepare_rendering_job(client)
    logged_in_client.post("/logout")
    login = logged_in_client.post(
        "/login",
        data={"email": "legal@imperial.local", "password": "Imperial2026!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert logged_in_client.get(f"/housevision/jobs/{job_id}").status_code == 200
    denied = logged_in_client.post(
        f"/housevision/jobs/{job_id}/outputs",
        data={
            "source_visual_id": exterior,
            "provider_job_id": "manual-denied",
            "output_ref": "s3://housevision/denied.webp",
            "content_sha256": "f" * 64,
            "width_px": "2400",
            "height_px": "1600",
            "edge_overlap": "0.99",
            "roof_match": "0.99",
            "opening_match": "0.99",
            "full_house_in_frame": "on",
            "daylight_pass": "on",
            "photorealism_pass": "on",
            "brand_identity_pass": "on",
            "privacy_pass": "on",
        },
        follow_redirects=False,
    )
    assert denied.status_code == 403


def test_housevision_automatic_source_ingest_locks_geometry(client, db, monkeypatch, tmp_path):
    approve_rights(client)
    job_id = create_job(client)
    monkeypatch.setattr(
        housevision_service,
        "settings",
        replace(housevision_service.settings, typehouse_factory_asset_root=str(tmp_path)),
    )

    def fake_ingest(_source_url, received_job_id, _limit):
        source_dir = tmp_path / "legacy" / received_job_id / "source"
        source_dir.mkdir(parents=True)
        exterior = source_dir / "01-exterior.png"
        floorplan = source_dir / "02-floorplan.png"
        exterior.write_bytes(b"exterior")
        floorplan.write_bytes(b"floorplan")
        return [
            IngestedAsset(
                source_url=SOURCE_URL + "/exterior.png",
                asset_type="EXTERIOR",
                content_sha256="a" * 64,
                width_px=2400,
                height_px=1600,
                magic_mime_type="image/png",
                storage_ref=str(exterior),
                label="exterior",
            ),
            IngestedAsset(
                source_url=SOURCE_URL + "/floorplan.png",
                asset_type="FLOORPLAN",
                content_sha256="b" * 64,
                width_px=2400,
                height_px=1600,
                magic_mime_type="image/png",
                storage_ref=str(floorplan),
                label="floorplan",
            ),
        ], {"source_html_sha256": "c" * 64}

    monkeypatch.setattr(housevision_service, "ingest_page_assets", fake_ingest)
    result = housevision_service.auto_ingest_source_assets(db, job_id, "test@imperial.local")

    assert result["added_count"] == 2
    assert result["status"] == "RENDERING"
    job = db.scalar(select(HouseVisionJob).where(HouseVisionJob.job_id == job_id))
    lock = db.scalar(
        select(HouseVisionGeometryLock).where(HouseVisionGeometryLock.job_id == job_id)
    )
    assert job.accepted_source_count == 2
    assert lock is not None and lock.storey_count == 0
    assert "DO_NOT_INVENT" in lock.immutable_features_json


def test_housevision_render_rejects_incomplete_provider_proof(
    client, db, monkeypatch, tmp_path
):
    job_id, _exterior, _floorplan = prepare_rendering_job(client)
    monkeypatch.setattr(
        housevision_render_bridge,
        "settings",
        replace(
            housevision_render_bridge.settings,
            typehouse_factory_asset_root=str(tmp_path),
        ),
    )
    source_dir = tmp_path / "legacy" / job_id / "source"
    source_dir.mkdir(parents=True)
    (source_dir / ("01-" + "a" * 16 + ".png")).write_bytes(b"exterior")
    (source_dir / ("02-" + "b" * 16 + ".png")).write_bytes(b"floorplan")

    def fake_render(_payload):
        payload = b"generated-image"
        return {
            "output_base64": base64.b64encode(payload).decode("ascii"),
            "output_sha256": hashlib.sha256(payload).hexdigest(),
            "qa": {
                "passed": True,
                "geometry_fidelity": "0.99",
                "roof_match": "0.99",
                "opening_match": "0.99",
                "floorplan_consistency": "0.99",
                "full_house_in_frame": True,
                "daylight_pass": True,
                "photorealism_pass": True,
                "privacy_pass": True,
            },
        }

    monkeypatch.setattr(housevision_render_bridge, "_call_image_factory", fake_render)
    with pytest.raises(ValueError, match="bizonyítékcsomagja hiányos"):
        housevision_render_bridge.generate_typehouse_renders(
            db, job_id, "test@imperial.local"
        )

    outputs = db.scalars(
        select(HouseVisionOutputAsset).where(HouseVisionOutputAsset.job_id == job_id)
    ).all()
    assert outputs == []


def test_housevision_ui_write_requires_csrf(logged_in_client):
    response = logged_in_client.post(
        "/housevision/jobs",
        data={"brand_id": "imperial", "source_url": SOURCE_URL},
        follow_redirects=False,
    )
    assert response.status_code == 403
