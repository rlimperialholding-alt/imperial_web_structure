"""Extended deterministic business tests for HouseVision bridge, ingest and routes.

Covers ``app/services/housevision_render_bridge.py`` (provider contract, geometry
proof verification for baseline / legacy / geometry-locked modes, legacy derivatives,
restyle generation, source-preserved baseline), ``housevision_source_ingest.py``
(identity, fetch, candidate discovery, image identity, full ingest) with fully
synthetic, network-free inputs, the fail-closed branches of ``housevision.py`` and
the main.py HouseVision UI routes (CSRF-protected writes, role gates, redirects).
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select

from app.models import (
    HouseCatalogPlan,
    HouseVisionGeometryLock,
    HouseVisionJob,
    HouseVisionOutputAsset,
    HouseVisionRightsPolicy,
    HouseVisionSourceAsset,
)
from app.schemas import (
    HouseVisionSourceAssetIn,
)
from app.services import housevision as hv
from app.services import housevision_render_bridge as bridge
from app.services.housevision import (
    add_source_asset,
    auto_ingest_source_assets,
    bind_houseplan,
    create_job,
    package_job,
    run_qa,
)
from app.services.housevision_source_ingest import (
    IngestedAsset,
    SourceIngestError,
)
from synthetic_fixtures import synthetic_auth_value

SOURCE_URL = "https://8.8.8.8/lawful-house/source-page"


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _png_bytes(width: int, height: int, color: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()

def _reset_fake_http() -> None:
    FakeHTTPConnection.queue = []
    FakeHTTPConnection.captured = []

def _sha(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()
















def _seed_bridge_job(
    db,
    tmp_path,
    monkeypatch,
    *,
    job_status: str = "RENDERING",
    lock_sha: str | None = None,
    colors: tuple[str, str] = ("steelblue", "white"),
):
    """Seed a HouseVision job with a geometry lock and two accepted sources on disk."""
    monkeypatch.setattr(
        bridge,
        "settings",
        replace(bridge.settings, typehouse_factory_asset_root=str(tmp_path)),
    )
    job_id = "HVJ-BRIDGE-" + uuid4().hex[:6].upper()
    policy = HouseVisionRightsPolicy(
        policy_id="HVR-BRIDGE-" + uuid4().hex[:8].upper(),
        domain="8.8.8.8",
        path_prefix="/lawful-house",
        rights_status="licensed",
        evidence_ref="drive://legal/synthetic-bridge",
        grant_id="grant-bridge-" + uuid4().hex[:6],
        owner_attestation_sha256="a" * 64,
        page_scope_sha256="b" * 64,
        active=True,
        approved_by="tester",
        approved_at=datetime.now(UTC),
        created_by="tester",
    )
    db.add(policy)
    job = HouseVisionJob(
        job_id=job_id,
        brand_id="imperial",
        source_url="https://8.8.8.8/lawful-house/source-page",
        source_page_id="HVSP-BRIDGE-" + uuid4().hex[:6].upper(),
        rights_policy_id=policy.policy_id,
        status=job_status,
        operation_mode="package_only",
        render_provider="mock",
        publication_eligibility="blocked",
        created_by="tester",
    )
    db.add(job)
    lock_sha = lock_sha or "c" * 64
    lock = HouseVisionGeometryLock(
        geometry_lock_id="HVG-BRIDGE-" + uuid4().hex[:6].upper(),
        job_id=job_id,
        version=1,
        floorplan_topology_sha256="a" * 64,
        massing_signature="rectangular",
        roof_form="nyeregtető",
        roof_pitch_deg=None,
        storey_count=1,
        window_count=8,
        door_count=2,
        width_depth_height_ratio="1.6:1:0.5",
        immutable_features_json="[]",
        content_sha256=lock_sha,
        created_by="tester",
    )
    db.add(lock)
    source_dir = tmp_path / "legacy" / job_id / "source"
    source_dir.mkdir(parents=True)
    sources = []
    for sequence, asset_type, color in ((1, "EXTERIOR", colors[0]), (2, "FLOORPLAN", colors[1])):
        payload = _png_bytes(200, 100, color)
        digest = _sha(payload)
        (source_dir / f"{sequence:02d}-{digest[:16]}.png").write_bytes(payload)
        source = HouseVisionSourceAsset(
            source_visual_id=f"HVS-BRIDGE-{sequence}",
            job_id=job_id,
            source_url=f"https://8.8.8.8/lawful-house/{asset_type.lower()}.png",
            asset_type=asset_type,
            sequence=sequence,
            content_sha256=digest,
            width_px=200,
            height_px=100,
            magic_mime_type="image/png",
            status="accepted",
        )
        db.add(source)
        sources.append(source)
    db.commit()
    return job, lock, sources, source_dir


def _add_output_row(
    db,
    job_id: str,
    source: HouseVisionSourceAsset,
    provider_job_id: str,
    output_ref: str,
    content_sha256: str,
    *,
    revision: int = 1,
    status: str = "qa_pending",
) -> HouseVisionOutputAsset:
    row = HouseVisionOutputAsset(
        output_visual_id="HVO-" + uuid4().hex[:12].upper(),
        job_id=job_id,
        source_visual_id=source.source_visual_id,
        revision=revision,
        provider_job_id=provider_job_id,
        output_ref=str(output_ref),
        content_sha256=content_sha256,
        width_px=bridge.SAFE_WIDTH,
        height_px=bridge.SAFE_HEIGHT,
        edge_overlap=Decimal("0.99"),
        roof_match=Decimal("0.99"),
        opening_match=Decimal("0.99"),
        floorplan_fidelity=Decimal("0.99") if source.asset_type == "FLOORPLAN" else None,
        full_house_in_frame=True,
        daylight_pass=True,
        photorealism_pass=True,
        brand_identity_pass=True,
        privacy_pass=True,
        status=status,
    )
    db.add(row)
    db.commit()
    return row


def _safe_render_assets(source_path: Path, output_path: Path):
    """Render a geometry-locked frame plus an exact protected-region mask."""
    frame = bridge._render_protected_source_frame(source_path, output_path, "EXTERIOR")
    box = frame["content_box"]
    mask_image = np.zeros((bridge.SAFE_HEIGHT, bridge.SAFE_WIDTH, 4), dtype=np.uint8)
    mask_image[
        box["y"] : box["y"] + box["height"],
        box["x"] : box["x"] + box["width"],
        3,
    ] = 255
    mask_buffer = BytesIO()
    Image.fromarray(mask_image).save(mask_buffer, format="PNG")
    mask_bytes = mask_buffer.getvalue()
    prepared = np.asarray(bridge._prepare_source_canvas(source_path))
    protected = mask_image[:, :, 3] > 0
    source_hash = _sha(prepared[protected].tobytes())
    return frame, mask_bytes, source_hash


def _full_safe_proof(frame, mask_bytes, source_hash) -> dict:
    return {
        "protected_mask_sha256": _sha(mask_bytes),
        "proof_type": "SEMANTIC_GEOMETRY_AND_APPEARANCE_V1",
        "structural_pixels_generated": False,
        "protected_source_pixels_sha256": source_hash,
        "protected_output_pixels_sha256": source_hash,
        "changed_editable_house_ratio": "0.35",
        "geometry_qa": {
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
        "restyle_qa": {
            "passed": True,
            "score": 88,
            "perceptibly_different_house": True,
            "facade_material_changed": True,
            "facade_color_changed": True,
            "roof_finish_changed": False,
            "opening_frame_or_door_design_changed": True,
            "issues": [],
        },
        "protected_region_sha256": frame["protected_region_sha256"],
        "protected_region_verified": True,
        "uniform_scale": frame["uniform_scale"],
        "content_box": frame["content_box"],
        "output_width": frame["output_width"],
        "output_height": frame["output_height"],
        "house_pixels_generated": False,
        "source_sha256": frame["source_sha256"],
        "output_sha256": frame["output_sha256"],
    }


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class FakeHTTPConnection:
    queue: list[dict] = []
    captured: list[tuple[str, str, str]] = []

    def __init__(self, host, port=None, timeout=None, context=None):
        self.host = host
        self.port = port

    def request(self, method, url, body=None, headers=None):
        FakeHTTPConnection.captured.append((self.host, url, str(headers or {})))

    def getresponse(self):
        step = FakeHTTPConnection.queue.pop(0)
        return FakeResponse(step)

    def close(self):
        pass

    @property
    def sock(self):
        return FakeSock()


class FakeResponse:
    def __init__(self, step: dict):
        self.status = step["status"]
        self._headers = step.get("headers", {})
        self._body = step.get("body", b"")

    def read(self, size: int | None = None):
        if size is None:
            chunk, self._body = self._body, b""
            return chunk
        chunk, self._body = self._body[:size], self._body[size:]
        return chunk

    def getheader(self, name: str, default: str | None = None):
        return self._headers.get(name, default)


class FakeSock:
    def getpeername(self):
        return ("8.8.8.8", 443)






def test_bridge_call_image_factory_success(monkeypatch):
    _reset_fake_http()
    # Futásidőben képzett, egyértelműen szintetikus API-fixture érték a közös
    # factoryból; statikus credential-szerű literál nincs a diffben.
    api_value = synthetic_auth_value("housevision", "image-factory")
    monkeypatch.setenv("IMAGE_FACTORY_API_TOKEN", api_value)
    FakeHTTPConnection.queue.append({"status": 200, "body": b'{"ok": true}'})
    monkeypatch.setattr(http.client, "HTTPConnection", FakeHTTPConnection)
    result = bridge._call_image_factory({"request_id": "synthetic-1"})
    assert result == {"ok": True}
    host, url, headers = FakeHTTPConnection.captured[0]
    assert host == "image-factory" and url == "/api/v1/typehouse/reference-render"
    assert api_value in headers and "application/json" in headers




def _valid_provider_result(output_bytes: bytes, mask_bytes: bytes) -> dict:
    qa = {
        "passed": True,
        "geometry_fidelity": "0.99",
        "roof_match": "0.99",
        "opening_match": "0.99",
        "floorplan_consistency": "0.99",
        "full_house_in_frame": True,
        "daylight_pass": True,
        "photorealism_pass": True,
        "privacy_pass": True,
    }
    restyle_qa = {
        "passed": True,
        "score": 88,
        "perceptibly_different_house": True,
        "facade_material_changed": True,
        "facade_color_changed": True,
        "roof_finish_changed": False,
        "opening_frame_or_door_design_changed": True,
        "issues": [],
    }
    proof = {
        "protected_mask_sha256": _sha(mask_bytes),
        "proof_type": "SEMANTIC_GEOMETRY_AND_APPEARANCE_V1",
        "structural_pixels_generated": False,
        "protected_source_pixels_sha256": _sha(output_bytes),
        "protected_output_pixels_sha256": _sha(output_bytes),
        "changed_editable_house_ratio": "0.35",
        "geometry_qa": qa,
        "restyle_qa": restyle_qa,
    }
    return {
        "output_base64": base64.b64encode(output_bytes).decode("ascii"),
        "protected_mask_base64": base64.b64encode(mask_bytes).decode("ascii"),
        "output_sha256": _sha(output_bytes),
        "qa": qa,
        "restyle_qa": restyle_qa,
        "geometry_proof": proof,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result.update(output_sha256="f" * 64),
        lambda result: result.pop("protected_mask_base64"),
        lambda result: result["qa"].pop("passed"),
        lambda result: result["geometry_proof"].pop("proof_type"),
        lambda result: result.update(output_base64="not-base64!"),
    ],
)
def test_bridge_decode_restyle_provider_result_fails_closed(mutate):
    result = _valid_provider_result(b"output-bytes", b"mask-bytes")
    mutate(result)
    with pytest.raises(ValueError):
        bridge._decode_restyle_provider_result(result)


def test_bridge_decode_restyle_provider_result_not_dict():
    with pytest.raises(ValueError, match="nem objektum"):
        bridge._decode_restyle_provider_result("nope")


def test_bridge_decode_restyle_provider_result_success():
    qa, restyle_qa, proof, out, mask, out_hash, mask_hash = bridge._decode_restyle_provider_result(
        _valid_provider_result(b"output-bytes", b"mask-bytes")
    )
    assert qa["passed"] and restyle_qa["passed"] and proof["proof_type"].endswith("V1")
    assert out == b"output-bytes" and mask == b"mask-bytes"
    assert out_hash == _sha(b"output-bytes") and mask_hash == _sha(b"mask-bytes")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_bridge_verify_baseline_pass_and_tamper_fail(db, tmp_path, monkeypatch):
    job, lock, sources, source_dir = _seed_bridge_job(db, tmp_path, monkeypatch)
    source = sources[0]
    copy_path = tmp_path / "baseline-copy.png"
    copy_path.write_bytes((source_dir / f"01-{source.content_sha256[:16]}.png").read_bytes())

    baseline = _add_output_row(
        db,
        job.job_id,
        source,
        "SOURCE_PRESERVED_BASELINE:" + lock.content_sha256,
        copy_path,
        source.content_sha256,
    )
    assert bridge.verify_geometry_proof(source, baseline) is True

    tampered = _add_output_row(
        db,
        job.job_id,
        source,
        "SOURCE_PRESERVED_BASELINE:" + lock.content_sha256,
        copy_path,
        _sha("different-bytes"),
    )
    assert bridge.verify_geometry_proof(source, tampered) is False




def test_bridge_verify_legacy_mode_pass_and_tamper_fail(db, tmp_path, monkeypatch):
    job, lock, sources, source_dir = _seed_bridge_job(db, tmp_path, monkeypatch)
    source = sources[0]
    source_path = source_dir / f"01-{source.content_sha256[:16]}.png"
    output_path = tmp_path / "legacy-safe.png"
    frame = bridge._render_protected_source_frame(source_path, output_path, "EXTERIOR")
    frame["source_visual_id"] = source.source_visual_id
    manifest = {
        "mode": bridge.LEGACY_SAFE_RENDER_MODE,
        "job_id": job.job_id,
        "geometry_lock_sha256": lock.content_sha256,
        "proofs": [frame],
    }
    output_path.parent.joinpath("geometry-proof.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    legacy = _add_output_row(
        db,
        job.job_id,
        source,
        f"{bridge.LEGACY_SAFE_RENDER_MODE}:{lock.content_sha256}",
        output_path,
        frame["output_sha256"],
    )
    assert bridge.verify_geometry_proof(source, legacy) is True

    output_path.write_bytes(b"tampered")
    assert bridge.verify_geometry_proof(source, legacy) is False


def test_bridge_verify_safe_render_mode_pass(db, tmp_path, monkeypatch):
    job, lock, sources, source_dir = _seed_bridge_job(db, tmp_path, monkeypatch)
    source = sources[0]
    source_path = source_dir / f"01-{source.content_sha256[:16]}.png"
    output_path = tmp_path / "restyle-safe.png"
    frame, mask_bytes, source_hash = _safe_render_assets(source_path, output_path)
    mask_path = tmp_path / "geometry-mask.png"
    mask_path.write_bytes(mask_bytes)
    proof = _full_safe_proof(frame, mask_bytes, source_hash)
    proof["protected_mask_file"] = mask_path.name
    proof["source_visual_id"] = source.source_visual_id
    manifest = {
        "mode": bridge.SAFE_RENDER_MODE,
        "job_id": job.job_id,
        "geometry_lock_sha256": lock.content_sha256,
        "proofs": [proof],
    }
    output_path.parent.joinpath("geometry-proof.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    output = _add_output_row(
        db,
        job.job_id,
        source,
        f"{bridge.SAFE_RENDER_MODE}:{lock.content_sha256}",
        output_path,
        frame["output_sha256"],
    )
    assert bridge.verify_geometry_proof(source, output) is True


def test_bridge_verify_safe_render_mask_tamper_fails(db, tmp_path, monkeypatch):
    job, lock, sources, source_dir = _seed_bridge_job(db, tmp_path, monkeypatch)
    source = sources[0]
    source_path = source_dir / f"01-{source.content_sha256[:16]}.png"
    output_path = tmp_path / "restyle-tampered-mask.png"
    frame, mask_bytes, source_hash = _safe_render_assets(source_path, output_path)
    mask_path = tmp_path / "geometry-mask-t.png"
    mask_path.write_bytes(b"not-the-real-mask")
    proof = _full_safe_proof(frame, mask_bytes, source_hash)
    proof["protected_mask_file"] = mask_path.name
    proof["source_visual_id"] = source.source_visual_id
    manifest = {
        "mode": bridge.SAFE_RENDER_MODE,
        "job_id": job.job_id,
        "geometry_lock_sha256": lock.content_sha256,
        "proofs": [proof],
    }
    output_path.parent.joinpath("geometry-proof.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    output = _add_output_row(
        db,
        job.job_id,
        source,
        f"{bridge.SAFE_RENDER_MODE}:{lock.content_sha256}",
        output_path,
        frame["output_sha256"],
    )
    assert bridge.verify_geometry_proof(source, output) is False




# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------






def test_bridge_legacy_derivatives_happy_and_fail_closed_second_run(db, tmp_path, monkeypatch):
    job, lock, sources, _ = _seed_bridge_job(db, tmp_path, monkeypatch)
    result = bridge._generate_legacy_source_derivatives(db, job.job_id, "tester")
    assert len(result["created"]) == 2
    assert result["status"] == "QA" and result["mode"] == bridge.SAFE_RENDER_MODE
    rows = db.scalars(
        select(HouseVisionOutputAsset).where(HouseVisionOutputAsset.job_id == job.job_id)
    ).all()
    assert len(rows) == 2 and all(row.status == "qa_pending" for row in rows)

    with pytest.raises(ValueError, match="fail-closed"):
        bridge._generate_legacy_source_derivatives(db, job.job_id, "tester")




def test_bridge_generate_renders_negatives(db, tmp_path, monkeypatch):
    job, lock, sources, _ = _seed_bridge_job(db, tmp_path, monkeypatch)
    with pytest.raises(KeyError):
        bridge.generate_typehouse_renders(db, "HVJ-NOPE", "tester")

    job.status = "SOURCE_CRAWL"
    db.commit()
    with pytest.raises(ValueError, match="kész állapotban"):
        bridge.generate_typehouse_renders(db, job.job_id, "tester")

    job.status = "RENDERING"
    db.commit()
    db.delete(db.scalar(select(HouseVisionGeometryLock)))
    db.commit()
    with pytest.raises(ValueError, match="GeometryLock"):
        bridge.generate_typehouse_renders(db, job.job_id, "tester")


def test_bridge_generate_renders_happy_through_qa_package_bind(db, tmp_path, monkeypatch):
    job, lock, sources, source_dir = _seed_bridge_job(db, tmp_path, monkeypatch)

    def fake_provider(payload):
        first = payload["references"][0]
        reference = tmp_path / f"ref-{first['content_sha256'][:16]}.png"
        reference.write_bytes(base64.b64decode(first["data_base64"]))
        output_path = tmp_path / f"provider-{first['content_sha256'][:16]}.png"
        frame, mask_bytes, source_hash = _safe_render_assets(reference, output_path)
        proof = _full_safe_proof(frame, mask_bytes, source_hash)
        proof["source_visual_id"] = first.get("source_visual_id")
        proof["source_sha256"] = first["content_sha256"]
        proof["output_sha256"] = _sha(output_path.read_bytes())
        proof["protected_mask_file"] = "provider-mask.png"
        return {
            "output_base64": base64.b64encode(output_path.read_bytes()).decode("ascii"),
            "protected_mask_base64": base64.b64encode(mask_bytes).decode("ascii"),
            "output_sha256": _sha(output_path.read_bytes()),
            "qa": proof["geometry_qa"],
            "restyle_qa": proof["restyle_qa"],
            "geometry_proof": proof,
        }

    monkeypatch.setattr(bridge, "_call_image_factory", fake_provider)
    rendered = bridge.generate_typehouse_renders(db, job.job_id, "tester")
    assert len(rendered["created"]) == 1
    assert rendered["status"] == "QA" and rendered["mode"] == bridge.SAFE_RENDER_MODE

    baseline = bridge.create_source_preserved_baseline(db, job.job_id, "tester")
    assert len(baseline["created"]) == 2
    assert baseline["mode"] == "SOURCE_PRESERVED_BASELINE"

    qa = run_qa(db, job.job_id, "tester")
    assert qa.status == "PASS"
    assert db.scalar(
        select(HouseVisionJob).where(HouseVisionJob.job_id == job.job_id)
    ).status == "PACKAGING"

    package = package_job(db, job.job_id, "s3://housevision/packages/synthetic.tar.gz", "tester")
    assert package.publication_status == "blocked"
    assert package.source_count == package.output_count == 2
    assert (
        db.scalar(select(HouseVisionJob).where(HouseVisionJob.job_id == job.job_id)).status
        == "READY"
    )

    db.add(
        HouseCatalogPlan(
            house_id="HOUSE-BRIDGE-1",
            brand="imperial",
            canonical_name="Bridge Ház",
            lifecycle_status="active",
            current_released_version=1,
            created_by="tester",
        )
    )
    db.commit()
    bound = bind_houseplan(db, job.job_id, "HOUSE-BRIDGE-1", "tester", "platform-admin")
    assert bound.publication_eligibility == "eligible"
    db.refresh(package)
    assert package.publication_status == "eligible"








# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
















# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------














def test_service_auto_ingest_fail_closed_branches(db, monkeypatch, tmp_path):
    monkeypatch.setattr(
        hv, "settings", replace(hv.settings, typehouse_factory_asset_root=str(tmp_path))
    )
    job = create_job(db, "imperial", SOURCE_URL, "tester")
    job.status = "SOURCE_CRAWL"  # no matching policy -> the policy gate must fire
    db.commit()
    with pytest.raises(ValueError, match="aktív jogpolicy"):
        auto_ingest_source_assets(db, job.job_id, "tester")

    policy = HouseVisionRightsPolicy(
        policy_id="HVR-SVC-" + uuid4().hex[:8].upper(),
        domain="8.8.8.8",
        path_prefix="/lawful-house",
        rights_status="licensed",
        evidence_ref="drive://legal/synthetic-6",
        grant_id="grant-svc-6",
        owner_attestation_sha256="a" * 64,
        page_scope_sha256="b" * 64,
        active=True,
        approved_by="tester",
        approved_at=datetime.now(UTC),
        created_by="tester",
        max_assets_per_page=1,
    )
    db.add(policy)
    job.rights_policy_id = policy.policy_id
    db.commit()
    add_source_asset(
        db,
        job.job_id,
        HouseVisionSourceAssetIn(
            source_url=SOURCE_URL + "/a.png",
            asset_type="EXTERIOR",
            sequence=1,
            content_sha256="a" * 64,
            width_px=2400,
            height_px=1600,
            magic_mime_type="image/png",
        ),
        "tester",
    )
    result = auto_ingest_source_assets(db, job.job_id, "tester")
    assert result == {"added_count": 0, "total_count": 1, "status": "ASSET_CLASSIFICATION"}

    policy.max_assets_per_page = 12
    db.commit()

    def exploding_ingest(*_args, **_kwargs):
        raise SourceIngestError("provider refused")

    monkeypatch.setattr(hv, "ingest_page_assets", exploding_ingest)
    with pytest.raises(ValueError, match="sikertelen"):
        auto_ingest_source_assets(db, job.job_id, "tester")
    job = db.scalar(select(HouseVisionJob).where(HouseVisionJob.job_id == job.job_id))
    assert "sikertelen" in job.failure_reason
    ingest_dir = tmp_path / "legacy" / job.job_id

    def exteriors_only(*_args, **_kwargs):
        ingest_dir.mkdir(parents=True, exist_ok=True)
        return [
            IngestedAsset(
                source_url=SOURCE_URL + "/x.png",
                asset_type="EXTERIOR",
                content_sha256="x" * 64,
                width_px=2400,
                height_px=1600,
                magic_mime_type="image/png",
                storage_ref=str(tmp_path / "legacy" / job.job_id / "x.png"),
                label="x",
            )
        ], {"source_html_sha256": "c" * 64}

    monkeypatch.setattr(hv, "ingest_page_assets", exteriors_only)
    result = auto_ingest_source_assets(db, job.job_id, "tester")
    assert result["status"] == "SOURCE_CRAWL"
    assert "alaprajz" in db.scalar(
        select(HouseVisionJob).where(HouseVisionJob.job_id == job.job_id)
    ).failure_reason














# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
















