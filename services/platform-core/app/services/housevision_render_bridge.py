from __future__ import annotations

import base64
import binascii
import hashlib
import http.client
import json
import os
import re
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..models import (
    HouseVisionGeometryLock,
    HouseVisionJob,
    HouseVisionOutputAsset,
    HouseVisionPackage,
    HouseVisionSourceAsset,
)
from .fs_guard import contained_path


LEGACY_SAFE_RENDER_MODE = "GEOMETRY_SAFE_COMPOSITE_V1"
ENVIRONMENT_RENDER_MODE = "GEOMETRY_SAFE_ENVIRONMENT_V2"
SAFE_RENDER_MODE = "GEOMETRY_LOCKED_RESTYLE_V22"
SAFE_WIDTH = 1536
SAFE_HEIGHT = 1024


def _image_factory_token() -> str:
    value = os.getenv("IMAGE_FACTORY_API_TOKEN", "").strip()
    if value:
        return value
    path = os.getenv("IMAGE_FACTORY_API_TOKEN_FILE", "")
    return Path(path).read_text(encoding="utf-8").strip() if path else ""


def _call_image_factory(payload: dict) -> dict:
    token = _image_factory_token()
    if not token:
        raise ValueError("Az Image Factory API token nincs konfigurálva.")
    connection = http.client.HTTPConnection("image-factory", 8000, timeout=1200)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        connection.request(
            "POST",
            "/api/v1/typehouse/reference-render",
            body=body,
            headers={"Content-Type": "application/json", "X-API-Key": token},
        )
        response = connection.getresponse()
        raw = response.read()
    finally:
        connection.close()
    if response.status != 200:
        raise ValueError(
            f"Image Factory HTTP {response.status}: {raw[:1000].decode('utf-8', 'replace')}"
        )
    return json.loads(raw)


def _decode_restyle_provider_result(
    result: object,
) -> tuple[dict, dict, dict, bytes, bytes, str, str]:
    """Validate the provider contract before writing any returned artifact to disk."""
    if not isinstance(result, dict):
        raise ValueError("Az Image Factory válasza nem objektum.")
    qa = result.get("qa")
    restyle_qa = result.get("restyle_qa")
    proof = result.get("geometry_proof")
    if (
        not isinstance(qa, dict)
        or not isinstance(restyle_qa, dict)
        or not isinstance(proof, dict)
    ):
        raise ValueError("Az Image Factory bizonyítékcsomagja hiányos.")
    required_qa = {
        "passed",
        "geometry_fidelity",
        "roof_match",
        "opening_match",
        "floorplan_consistency",
        "full_house_in_frame",
        "daylight_pass",
        "photorealism_pass",
        "privacy_pass",
    }
    required_restyle = {
        "passed",
        "score",
        "perceptibly_different_house",
        "facade_material_changed",
        "facade_color_changed",
        "roof_finish_changed",
        "opening_frame_or_door_design_changed",
        "issues",
    }
    required_proof = {
        "protected_mask_sha256",
        "proof_type",
        "structural_pixels_generated",
        "protected_source_pixels_sha256",
        "protected_output_pixels_sha256",
        "changed_editable_house_ratio",
        "geometry_qa",
        "restyle_qa",
    }
    missing = (
        {f"qa.{key}" for key in required_qa - qa.keys()}
        | {f"restyle_qa.{key}" for key in required_restyle - restyle_qa.keys()}
        | {f"geometry_proof.{key}" for key in required_proof - proof.keys()}
    )
    if missing:
        raise ValueError(
            "Az Image Factory válaszából kötelező mező hiányzik: "
            + ", ".join(sorted(missing))
        )
    output_base64 = result.get("output_base64")
    mask_base64 = result.get("protected_mask_base64")
    output_sha256 = result.get("output_sha256")
    if (
        not isinstance(output_base64, str)
        or not output_base64
        or not isinstance(mask_base64, str)
        or not mask_base64
    ):
        raise ValueError("Az Image Factory kép- vagy maszkadata hiányzik.")
    if not isinstance(output_sha256, str) or len(output_sha256) != 64:
        raise ValueError("Az Image Factory képlenyomata érvénytelen.")
    try:
        output_bytes = base64.b64decode(output_base64, validate=True)
        mask_bytes = base64.b64decode(mask_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Az Image Factory kép- vagy maszkadata nem érvényes base64.") from exc
    output_hash = hashlib.sha256(output_bytes).hexdigest()
    mask_hash = hashlib.sha256(mask_bytes).hexdigest()
    if output_hash != output_sha256 or mask_hash != proof["protected_mask_sha256"]:
        raise ValueError("Az Image Factory kép- vagy maszklenyomatának ellenőrzése sikertelen.")
    return qa, restyle_qa, proof, output_bytes, mask_bytes, output_hash, mask_hash


def _source_path(job_id: str, content_sha256: str) -> Path:
    if re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None:
        raise ValueError("Érvénytelen forrás-képlenyomat.")
    # A job_id felhasználói paraméter: csak kanonikus feloldás és konténment-
    # ellenőrzés után érheti a fájlrendszert (traversal/symlink fail-closed).
    root = contained_path(Path(settings.typehouse_factory_asset_root) / "legacy", job_id)
    root = root / "source"
    matches = list(root.glob(f"*-{content_sha256[:16]}.*"))
    if len(matches) != 1:
        raise ValueError(f"A forrásfájl nem található egyértelműen: {content_sha256}")
    return matches[0]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_source_canvas(source_path: Path) -> Image.Image:
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    scale = min(SAFE_WIDTH / source.width, SAFE_HEIGHT / source.height)
    placed = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
        Image.Resampling.LANCZOS,
    )
    x = (SAFE_WIDTH - placed.width) // 2
    y = (SAFE_HEIGHT - placed.height) // 2
    cover_scale = max(SAFE_WIDTH / source.width, SAFE_HEIGHT / source.height)
    cover = source.resize(
        (
            max(1, round(source.width * cover_scale)),
            max(1, round(source.height * cover_scale)),
        ),
        Image.Resampling.LANCZOS,
    )
    left = (cover.width - SAFE_WIDTH) // 2
    top = (cover.height - SAFE_HEIGHT) // 2
    canvas = cover.crop((left, top, left + SAFE_WIDTH, top + SAFE_HEIGHT))
    canvas = canvas.filter(ImageFilter.GaussianBlur(radius=28))
    canvas.paste(placed, (x, y))
    return canvas


def _render_protected_source_frame(source_path: Path, target_path: Path, asset_type: str) -> dict:
    """Create a larger derivative while keeping the complete source frame protected.

    The authoritative frame is transformed only by a deterministic uniform resize, pasted
    over the canvas and then verified pixel-for-pixel after lossless PNG serialization.
    No generative model receives permission to redraw the house.
    """
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    source_width, source_height = source.size
    scale = min(SAFE_WIDTH / source_width, SAFE_HEIGHT / source_height)
    placed_width = max(1, round(source_width * scale))
    placed_height = max(1, round(source_height * scale))
    protected = source.resize((placed_width, placed_height), Image.Resampling.LANCZOS)
    x = (SAFE_WIDTH - placed_width) // 2
    y = (SAFE_HEIGHT - placed_height) // 2

    if asset_type == "FLOORPLAN":
        canvas = Image.new("RGB", (SAFE_WIDTH, SAFE_HEIGHT), "white")
    else:
        cover_scale = max(SAFE_WIDTH / source_width, SAFE_HEIGHT / source_height)
        cover_size = (
            max(1, round(source_width * cover_scale)),
            max(1, round(source_height * cover_scale)),
        )
        background = source.resize(cover_size, Image.Resampling.LANCZOS)
        left = (background.width - SAFE_WIDTH) // 2
        top = (background.height - SAFE_HEIGHT) // 2
        canvas = background.crop((left, top, left + SAFE_WIDTH, top + SAFE_HEIGHT))
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=28))

    canvas.paste(protected, (x, y))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target_path, format="PNG", optimize=True)

    protected_hash = hashlib.sha256(protected.tobytes()).hexdigest()
    with Image.open(target_path) as opened:
        verified = opened.convert("RGB")
        verified_crop = verified.crop((x, y, x + placed_width, y + placed_height))
    verified_hash = hashlib.sha256(verified_crop.tobytes()).hexdigest()
    if verified_hash != protected_hash:
        target_path.unlink(missing_ok=True)
        raise ValueError("A védett forrásképréteg pixel-ellenőrzése sikertelen; a kimenet elutasítva.")

    return {
        "source_sha256": _sha256_file(source_path),
        "output_sha256": _sha256_file(target_path),
        "protected_region_sha256": protected_hash,
        "protected_region_verified": True,
        "uniform_scale": scale,
        "content_box": {
            "x": x,
            "y": y,
            "width": placed_width,
            "height": placed_height,
        },
        "output_width": SAFE_WIDTH,
        "output_height": SAFE_HEIGHT,
        "house_pixels_generated": False,
    }


def verify_geometry_proof(
    source: HouseVisionSourceAsset, output: HouseVisionOutputAsset
) -> bool:
    """Verify an output independently at the QA boundary.

    Only exact source copies, legacy pixel-safe composites and proven geometry-locked
    restyles are admissible. This makes the
    protection apply to manual/API output registration as well as the normal render route.
    """
    output_path = Path(output.output_ref)
    if not output_path.is_file() or _sha256_file(output_path) != output.content_sha256:
        return False
    baseline_prefix = "SOURCE_PRESERVED_BASELINE:"
    if output.provider_job_id.startswith(baseline_prefix):
        return output.content_sha256 == source.content_sha256
    mode = output.provider_job_id.split(":", 1)[0]
    if mode not in {LEGACY_SAFE_RENDER_MODE, ENVIRONMENT_RENDER_MODE, SAFE_RENDER_MODE}:
        return False
    safe_prefix = mode + ":"
    manifest_path = output_path.parent / "geometry-proof.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest["mode"] != mode
            or manifest["job_id"] != output.job_id
            or output.provider_job_id != safe_prefix + manifest["geometry_lock_sha256"]
        ):
            return False
        proof = next(
            item
            for item in manifest["proofs"]
            if item["source_visual_id"] == source.source_visual_id
        )
        if (
            proof["source_sha256"] != source.content_sha256
            or proof["output_sha256"] != output.content_sha256
        ):
            return False
        if mode == SAFE_RENDER_MODE:
            geometry = proof["geometry_qa"]
            restyle = proof["restyle_qa"]
            mask_path = output_path.parent / proof["protected_mask_file"]
            if not mask_path.is_file() or _sha256_file(mask_path) != proof["protected_mask_sha256"]:
                return False
            with Image.open(mask_path) as opened:
                protected = np.asarray(opened.convert("RGBA"))[:, :, 3] > 0
            with Image.open(output_path) as opened:
                rendered = np.asarray(opened.convert("RGB"))
            prepared = np.asarray(
                _prepare_source_canvas(_source_path(source.job_id, source.content_sha256))
            )
            if protected.shape != rendered.shape[:2] or rendered.shape != prepared.shape:
                return False
            source_hash = hashlib.sha256(prepared[protected].tobytes()).hexdigest()
            output_hash = hashlib.sha256(rendered[protected].tobytes()).hexdigest()
            return bool(
                proof["proof_type"] == "SEMANTIC_GEOMETRY_AND_APPEARANCE_V1"
                and proof["structural_pixels_generated"] is False
                and source_hash == output_hash
                and source_hash == proof["protected_source_pixels_sha256"]
                and output_hash == proof["protected_output_pixels_sha256"]
                and float(proof["changed_editable_house_ratio"]) >= 0.20
                and geometry["passed"]
                and float(geometry["floorplan_consistency"]) >= 0.97
                and restyle["passed"]
                and int(restyle["score"]) >= 70
                and bool(restyle["perceptibly_different_house"])
                and sum(
                    bool(restyle[key])
                    for key in (
                        "facade_material_changed",
                        "facade_color_changed",
                        "roof_finish_changed",
                        "opening_frame_or_door_design_changed",
                    )
                ) >= 2
                and not restyle["issues"]
            )
        if mode == ENVIRONMENT_RENDER_MODE:
            mask_path = output_path.parent / proof["protected_mask_file"]
            if not mask_path.is_file() or _sha256_file(mask_path) != proof["protected_mask_sha256"]:
                return False
            with Image.open(mask_path) as opened:
                mask = np.asarray(opened.convert("L")) > 0
            with Image.open(output_path) as opened:
                rendered = np.asarray(opened.convert("RGB"))
            prepared = np.asarray(_prepare_source_canvas(_source_path(source.job_id, source.content_sha256)))
            if mask.shape != rendered.shape[:2] or rendered.shape != prepared.shape:
                return False
            coverage = float(np.mean(mask))
            if not 0.08 <= coverage <= 0.72:
                return False
            source_hash = hashlib.sha256(prepared[mask].tobytes()).hexdigest()
            output_hash = hashlib.sha256(rendered[mask].tobytes()).hexdigest()
            if (
                source_hash != proof["protected_source_pixels_sha256"]
                or output_hash != proof["protected_output_pixels_sha256"]
                or source_hash != output_hash
            ):
                return False
            outside = ~mask
            delta = np.max(
                np.abs(rendered.astype(np.int16) - prepared.astype(np.int16)), axis=2
            )
            changed_ratio = float(np.mean(delta[outside] >= 12))
            return changed_ratio >= 0.25 and abs(
                changed_ratio - float(proof["changed_outside_protected_ratio"])
            ) <= 0.001
        if proof["protected_region_verified"] is not True:
            return False
        box = proof["content_box"]
        with Image.open(output_path) as opened:
            image = opened.convert("RGB")
            if (
                box["x"] < 0
                or box["y"] < 0
                or box["width"] <= 0
                or box["height"] <= 0
                or box["x"] + box["width"] > image.width
                or box["y"] + box["height"] > image.height
            ):
                return False
            protected_region = image.crop(
                (
                    box["x"],
                    box["y"],
                    box["x"] + box["width"],
                    box["y"] + box["height"],
                )
            )
        return hashlib.sha256(protected_region.tobytes()).hexdigest() == proof[
            "protected_region_sha256"
        ]
    except (KeyError, StopIteration, TypeError, ValueError, OSError, json.JSONDecodeError):
        return False


def output_preview_path(db: Session, job_id: str, output_visual_id: str) -> Path:
    """Return only the latest QA-passed, geometry-proven output for authenticated preview."""
    output = db.scalar(
        select(HouseVisionOutputAsset).where(
            HouseVisionOutputAsset.job_id == job_id,
            HouseVisionOutputAsset.output_visual_id == output_visual_id,
        )
    )
    if not output:
        raise KeyError(output_visual_id)
    latest = db.scalar(
        select(HouseVisionOutputAsset)
        .where(
            HouseVisionOutputAsset.job_id == job_id,
            HouseVisionOutputAsset.source_visual_id == output.source_visual_id,
        )
        .order_by(desc(HouseVisionOutputAsset.revision))
    )
    if not latest or latest.id != output.id or output.status != "qa_passed":
        raise PermissionError("Csak a legfrissebb, ellenőrzött eredmény tekinthető meg.")
    source = db.scalar(
        select(HouseVisionSourceAsset).where(
            HouseVisionSourceAsset.job_id == job_id,
            HouseVisionSourceAsset.source_visual_id == output.source_visual_id,
        )
    )
    if not source or not verify_geometry_proof(source, output):
        raise PermissionError("A kép geometriai bizonyítéka nem érvényes.")
    root = Path(settings.typehouse_factory_asset_root).resolve()
    path = Path(output.output_ref).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise PermissionError("Az eredmény nem engedélyezett tárhelyen található.")
    return path


def _generate_legacy_source_derivatives(db: Session, job_id: str, actor: str) -> dict:
    """Create geometry-safe derivatives; generative house redraw is forbidden.

    A new camera angle cannot be proven from 2D references, so this compatible endpoint
    preserves every complete source view and produces a cryptographic proof manifest.
    """
    job = db.scalar(select(HouseVisionJob).where(HouseVisionJob.job_id == job_id))
    if not job:
        raise KeyError(job_id)
    if job.status not in {"RENDERING", "RENDER_RETRY", "QA", "PACKAGING"}:
        raise ValueError("A job nem áll geometriavédett kimenetkészítésre kész állapotban.")
    lock = db.scalar(
        select(HouseVisionGeometryLock)
        .where(HouseVisionGeometryLock.job_id == job_id)
        .order_by(desc(HouseVisionGeometryLock.version))
    )
    if not lock:
        raise ValueError("A geometriavédett kimenethez GeometryLock szükséges.")
    sources = db.scalars(
        select(HouseVisionSourceAsset)
        .where(
            HouseVisionSourceAsset.job_id == job_id,
            HouseVisionSourceAsset.status == "accepted",
            HouseVisionSourceAsset.asset_type.in_({"EXTERIOR", "FLOORPLAN"}),
        )
        .order_by(HouseVisionSourceAsset.sequence)
    ).all()
    if not any(item.asset_type == "EXTERIOR" for item in sources) or not any(
        item.asset_type == "FLOORPLAN" for item in sources
    ):
        raise ValueError("Legalább egy látványterv és egy alaprajz szükséges.")

    output_dir = (
        contained_path(Path(settings.typehouse_factory_asset_root) / "legacy", job_id)
        / "geometry-safe"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "geometry-proof.json"
    previous_proofs: dict[str, dict] = {}
    if manifest_path.is_file():
        previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            previous_manifest.get("mode") == SAFE_RENDER_MODE
            and previous_manifest.get("job_id") == job_id
            and previous_manifest.get("geometry_lock_sha256") == lock.content_sha256
        ):
            previous_proofs = {
                item["source_visual_id"]: item
                for item in previous_manifest.get("proofs", [])
                if isinstance(item, dict) and item.get("source_visual_id")
            }
    provider_job_id = f"{SAFE_RENDER_MODE}:{lock.content_sha256}"
    created: list[str] = []
    proofs: list[dict] = []

    for source in sources:
        existing = db.scalar(
            select(HouseVisionOutputAsset).where(
                HouseVisionOutputAsset.job_id == job_id,
                HouseVisionOutputAsset.source_visual_id == source.source_visual_id,
                HouseVisionOutputAsset.provider_job_id == provider_job_id,
            )
        )
        if existing:
            if not verify_geometry_proof(source, existing):
                raise ValueError(
                    "A meglévő geometriavédett kimenet bizonyítéka érvénytelen; "
                    "a művelet fail-closed módban leállt."
                )
            if source.source_visual_id not in previous_proofs:
                raise ValueError("A meglévő geometriavédett kimenet manifest-bejegyzése hiányzik.")
            created.append(existing.output_visual_id)
            proofs.append(previous_proofs[source.source_visual_id])
            continue

        source_path = _source_path(job_id, source.content_sha256)
        target_path = output_dir / (
            f"{source.sequence:02d}-{source.asset_type.lower()}-"
            f"{source.content_sha256[:16]}.png"
        )
        proof = _render_protected_source_frame(source_path, target_path, source.asset_type)
        if proof["source_sha256"] != source.content_sha256:
            target_path.unlink(missing_ok=True)
            raise ValueError("A forrásfájl hash-e eltér a GeometryLock forrásától; a kimenet elutasítva.")
        proof["source_visual_id"] = source.source_visual_id
        proofs.append(proof)

        row = HouseVisionOutputAsset(
            output_visual_id="HVO-"
            + hashlib.sha256(
                f"{job_id}:{source.source_visual_id}:{provider_job_id}".encode()
            ).hexdigest()[:12].upper(),
            job_id=job_id,
            source_visual_id=source.source_visual_id,
            revision=1
            + (db.scalar(
                select(func.count())
                .select_from(HouseVisionOutputAsset)
                .where(
                    HouseVisionOutputAsset.job_id == job_id,
                    HouseVisionOutputAsset.source_visual_id == source.source_visual_id,
                )
            ) or 0),
            provider_job_id=provider_job_id,
            output_ref=str(target_path),
            content_sha256=proof["output_sha256"],
            width_px=SAFE_WIDTH,
            height_px=SAFE_HEIGHT,
            edge_overlap=1,
            roof_match=1,
            opening_match=1,
            floorplan_fidelity=1 if source.asset_type == "FLOORPLAN" else None,
            full_house_in_frame=True,
            daylight_pass=True,
            photorealism_pass=source.asset_type != "FLOORPLAN",
            brand_identity_pass=True,
            privacy_pass=True,
            status="qa_pending",
        )
        db.add(row)
        created.append(row.output_visual_id)

    manifest = {
        "mode": SAFE_RENDER_MODE,
        "job_id": job_id,
        "geometry_lock_sha256": lock.content_sha256,
        "house_pixels_generated": False,
        "proofs": proofs,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    job.output_count = len(created)
    job.status = "QA"
    job.failure_reason = None
    audit(
        db,
        actor=actor,
        action="housevision.render.geometry_safe_composite",
        entity_type="housevision_job",
        entity_id=job_id,
        after={
            "created": created,
            "mode": SAFE_RENDER_MODE,
            "geometry_lock_sha256": lock.content_sha256,
            "house_pixels_generated": False,
            "protected_regions_verified": all(
                item["protected_region_verified"] for item in proofs
            ),
            "proof_manifest": str(manifest_path),
        },
    )
    db.commit()
    return {
        "created": created,
        "status": job.status,
        "mode": SAFE_RENDER_MODE,
        "proofs": proofs,
    }


def generate_typehouse_renders(db: Session, job_id: str, actor: str) -> dict:
    """Generate a visibly different house design while locking its architectural geometry."""
    job = db.scalar(select(HouseVisionJob).where(HouseVisionJob.job_id == job_id))
    if not job:
        raise KeyError(job_id)
    if job.status not in {"RENDERING", "RENDER_RETRY", "QA", "PACKAGING", "READY"}:
        raise ValueError("A munka nem áll AI-látványkészítésre kész állapotban.")
    lock = db.scalar(
        select(HouseVisionGeometryLock)
        .where(HouseVisionGeometryLock.job_id == job_id)
        .order_by(desc(HouseVisionGeometryLock.version))
    )
    if not lock:
        raise ValueError("A geometriavédett látványokhoz GeometryLock szükséges.")
    sources = db.scalars(
        select(HouseVisionSourceAsset)
        .where(
            HouseVisionSourceAsset.job_id == job_id,
            HouseVisionSourceAsset.status == "accepted",
            HouseVisionSourceAsset.asset_type.in_({"EXTERIOR", "FLOORPLAN"}),
        )
        .order_by(HouseVisionSourceAsset.sequence)
    ).all()
    exteriors = [item for item in sources if item.asset_type == "EXTERIOR"]
    floorplans = [item for item in sources if item.asset_type == "FLOORPLAN"]
    if not exteriors or not floorplans:
        raise ValueError("Legalább egy látványterv és egy alaprajz szükséges.")

    output_dir = (
        contained_path(Path(settings.typehouse_factory_asset_root) / "legacy", job_id)
        / "restyle-v22"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "geometry-proof.json"
    provider_job_id = f"{SAFE_RENDER_MODE}:{lock.content_sha256}"
    existing_rows = db.scalars(
        select(HouseVisionOutputAsset).where(
            HouseVisionOutputAsset.job_id == job_id,
            HouseVisionOutputAsset.provider_job_id == provider_job_id,
        )
    ).all()
    if len(existing_rows) == len(exteriors) and all(
        verify_geometry_proof(
            next(item for item in exteriors if item.source_visual_id == row.source_visual_id),
            row,
        )
        for row in existing_rows
    ):
        return {
            "created": [row.output_visual_id for row in existing_rows],
            "status": job.status,
            "mode": SAFE_RENDER_MODE,
            "idempotent": True,
        }

    reference_payload: dict[str, dict] = {}
    for source in sources:
        path = _source_path(job_id, source.content_sha256)
        reference_payload[source.source_visual_id] = {
            "asset_type": source.asset_type,
            "content_sha256": source.content_sha256,
            "mime_type": source.magic_mime_type,
            "data_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
        }

    pending: list[tuple[HouseVisionOutputAsset, HouseVisionSourceAsset]] = []
    proofs: list[dict] = []
    failures: list[dict] = []
    for source in exteriors:
        # The same-camera source is the only authority for visible facade geometry.
        # Floor plans prove topology; other camera angles are intentionally omitted here
        # because perspective changes can make a vision judge invent contradictions.
        ordered = [source, *floorplans]
        request_id = (
            f"{job_id}-{lock.content_sha256[:12]}-"
                f"{source.source_visual_id}-restyle-v22"
        )
        prompt = (
            "Create one premium photorealistic architectural visualization of a NEW, visibly distinct "
            "design variant based on the FIRST same-camera exterior. This must not look like a copy. "
            "LOCK exactly: the complete building massing and external volume; footprint and floor-plan "
            "topology; roof form, ridge/eave geometry, pitches and relative heights; storey count and "
            "level relationships; and the count, exact positions, sizes, proportions, sill/head lines "
            "and rhythm of every window, door, garage opening and entrance. Do not add, remove, move, "
            "resize or reshape any opening. Keep the same camera and complete house in frame. "
            "REDESIGN visibly: use a substantially different coordinated facade palette and material "
            "system, different roof covering material/color, different gutters, window/door frame "
            "colors and profiles, different door and garage-door design, terrace finish and non-structural "
            "treatment, paving, garden, vegetation, sky and daylight. Change at least three house-facing "
            "appearance categories, not only the surroundings. Favor refined contemporary Central "
            "European materials and a coherent, buildable result. No text, logo, watermark, people, "
            "vehicles or invented structural element. The house must be clearly the same geometric "
            "type, but immediately recognizable as a different visual design."
        )
        result = _call_image_factory(
            {
                "request_id": request_id,
                "job_id": job_id,
                "output_role": f"restyle-{source.sequence}",
                "prompt": prompt,
                "references": [reference_payload[item.source_visual_id] for item in ordered],
            }
        )
        (
            qa,
            restyle_qa,
            proof,
            output_bytes,
            mask_bytes,
            output_hash,
            mask_hash,
        ) = _decode_restyle_provider_result(result)
        if not qa["passed"] or not restyle_qa.get("passed"):
            failures.append(
                {
                    "source_visual_id": source.source_visual_id,
                    "qa": qa,
                    "restyle_qa": restyle_qa,
                    "geometry_proof": proof,
                }
            )
            continue

        target_path = output_dir / f"{source.sequence:02d}-restyle-{output_hash[:16]}.png"
        mask_path = output_dir / f"{source.sequence:02d}-geometry-mask-{mask_hash[:16]}.png"
        target_path.write_bytes(output_bytes)
        mask_path.write_bytes(mask_bytes)
        proof.update(
            {
                "source_visual_id": source.source_visual_id,
                "source_sha256": source.content_sha256,
                "output_sha256": output_hash,
                "protected_mask_file": mask_path.name,
            }
        )
        proofs.append(proof)
        row = HouseVisionOutputAsset(
            output_visual_id="HVO-"
            + hashlib.sha256(
                f"{job_id}:{source.source_visual_id}:{provider_job_id}".encode()
            ).hexdigest()[:12].upper(),
            job_id=job_id,
            source_visual_id=source.source_visual_id,
            revision=1
            + (db.scalar(
                select(func.count())
                .select_from(HouseVisionOutputAsset)
                .where(
                    HouseVisionOutputAsset.job_id == job_id,
                    HouseVisionOutputAsset.source_visual_id == source.source_visual_id,
                )
            ) or 0),
            provider_job_id=provider_job_id,
            output_ref=str(target_path),
            content_sha256=output_hash,
            width_px=SAFE_WIDTH,
            height_px=SAFE_HEIGHT,
            edge_overlap=qa["geometry_fidelity"],
            roof_match=qa["roof_match"],
            opening_match=qa["opening_match"],
            floorplan_fidelity=qa["floorplan_consistency"],
            full_house_in_frame=qa["full_house_in_frame"],
            daylight_pass=qa["daylight_pass"],
            photorealism_pass=qa["photorealism_pass"],
            brand_identity_pass=True,
            privacy_pass=qa["privacy_pass"],
            status="qa_pending",
        )
        pending.append((row, source))

    if failures or len(pending) != len(exteriors):
        job.status = "RENDER_RETRY"
        job.publication_eligibility = "blocked"
        job.failure_reason = json.dumps(failures, ensure_ascii=False)[:4000]
        audit(
            db,
            actor=actor,
            action="housevision.render.restyle_v20_rejected",
            entity_type="housevision_job",
            entity_id=job_id,
            after={"failures": failures, "created": 0, "mode": SAFE_RENDER_MODE},
        )
        db.commit()
        return {"created": [], "failures": failures, "status": job.status}

    manifest = {
        "mode": SAFE_RENDER_MODE,
        "job_id": job_id,
        "geometry_lock_sha256": lock.content_sha256,
        "geometry_locked_appearance_mutable": True,
        "proofs": proofs,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for row, source in pending:
        if not verify_geometry_proof(source, row):
            raise ValueError(
                f"A független geometriai bizonyíték-ellenőrzés sikertelen: {source.source_visual_id}"
            )
        db.add(row)
    for package in db.scalars(
        select(HouseVisionPackage).where(HouseVisionPackage.job_id == job_id)
    ).all():
        package.publication_status = "superseded"
    job.output_count = len(sources)
    job.status = "QA"
    job.publication_eligibility = "blocked"
    job.failure_reason = None
    audit(
        db,
        actor=actor,
        action="housevision.render.restyle_v20",
        entity_type="housevision_job",
        entity_id=job_id,
        after={
            "created": [row.output_visual_id for row, _ in pending],
            "mode": SAFE_RENDER_MODE,
            "geometry_lock_sha256": lock.content_sha256,
            "geometry_locked_appearance_mutable": True,
            "minimum_restyle_score": min(
                int(item["restyle_qa"]["score"]) for item in proofs
            ),
            "proof_manifest": str(manifest_path),
            "publication_status": "blocked",
        },
    )
    db.commit()
    return {
        "created": [row.output_visual_id for row, _ in pending],
        "status": job.status,
        "mode": SAFE_RENDER_MODE,
        "proofs": proofs,
    }


def create_source_preserved_baseline(db: Session, job_id: str, actor: str) -> dict:
    """Create an exact-byte baseline for every accepted source."""
    job = db.scalar(select(HouseVisionJob).where(HouseVisionJob.job_id == job_id))
    if not job:
        raise KeyError(job_id)
    lock = db.scalar(
        select(HouseVisionGeometryLock)
        .where(HouseVisionGeometryLock.job_id == job_id)
        .order_by(desc(HouseVisionGeometryLock.version))
    )
    if not lock:
        raise ValueError("A forráshű alapcsomaghoz GeometryLock szükséges.")
    sources = db.scalars(
        select(HouseVisionSourceAsset)
        .where(
            HouseVisionSourceAsset.job_id == job_id,
            HouseVisionSourceAsset.status == "accepted",
        )
        .order_by(HouseVisionSourceAsset.sequence)
    ).all()
    output_dir = (
        contained_path(Path(settings.typehouse_factory_asset_root) / "legacy", job_id)
        / "baseline"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    created = []
    provider_job_id = f"SOURCE_PRESERVED_BASELINE:{lock.content_sha256}"
    for source in sources:
        source_outputs = db.scalars(
            select(HouseVisionOutputAsset).where(
                HouseVisionOutputAsset.job_id == job_id,
                HouseVisionOutputAsset.source_visual_id == source.source_visual_id,
            )
        ).all()
        latest_output = max(source_outputs, key=lambda item: item.revision, default=None)
        if source.asset_type != "FLOORPLAN" and latest_output is not None:
            # Baseline repair is allowed to advance floorplans after reclassification,
            # but it must never supersede an existing exterior design revision.
            created.append(latest_output.output_visual_id)
            continue
        source_provider_job_id = provider_job_id
        if (
            source.asset_type == "FLOORPLAN"
            and latest_output is not None
            and not latest_output.provider_job_id.startswith("SOURCE_PRESERVED_BASELINE:")
        ):
            # Reclassification can leave a newer historical exterior render above the
            # original floorplan baseline.  Add a new exact-copy revision so all generic
            # "latest output" consumers see the type-correct floorplan.
            source_provider_job_id = (
                f"{provider_job_id}:floorplan-refresh-r{latest_output.revision + 1}"
            )
        existing = db.scalar(
            select(HouseVisionOutputAsset).where(
                HouseVisionOutputAsset.job_id == job_id,
                HouseVisionOutputAsset.source_visual_id == source.source_visual_id,
                HouseVisionOutputAsset.provider_job_id == source_provider_job_id,
            )
        )
        if existing:
            created.append(existing.output_visual_id)
            continue
        source_path = _source_path(job_id, source.content_sha256)
        target = output_dir / (
            f"{source.sequence:02d}-{source.asset_type.lower()}-"
            f"{source.content_sha256[:16]}{source_path.suffix.lower()}"
        )
        shutil.copyfile(source_path, target)
        if _sha256_file(target) != source.content_sha256:
            raise ValueError("A veszteségmentes baseline másolás hash-ellenőrzése sikertelen.")
        row = HouseVisionOutputAsset(
            output_visual_id="HVO-"
            + hashlib.sha256(
                f"{job_id}:{source.source_visual_id}:{source_provider_job_id}".encode()
            ).hexdigest()[:12].upper(),
            job_id=job_id,
            source_visual_id=source.source_visual_id,
            revision=1
            + (db.scalar(
                select(func.count())
                .select_from(HouseVisionOutputAsset)
                .where(
                    HouseVisionOutputAsset.job_id == job_id,
                    HouseVisionOutputAsset.source_visual_id == source.source_visual_id,
                )
            ) or 0),
            provider_job_id=source_provider_job_id,
            output_ref=str(target),
            content_sha256=source.content_sha256,
            width_px=source.width_px,
            height_px=source.height_px,
            edge_overlap=1,
            roof_match=1,
            opening_match=1,
            floorplan_fidelity=1 if source.asset_type == "FLOORPLAN" else None,
            full_house_in_frame=True,
            daylight_pass=True,
            photorealism_pass=source.asset_type != "FLOORPLAN",
            brand_identity_pass=True,
            privacy_pass=True,
            status="qa_pending",
        )
        db.add(row)
        created.append(row.output_visual_id)
    job.output_count = len(created)
    job.status = "QA"
    job.failure_reason = None
    audit(
        db,
        actor=actor,
        action="housevision.render.source_preserved_baseline",
        entity_type="housevision_job",
        entity_id=job_id,
        after={
            "output_count": len(created),
            "mode": "EXACT_BYTE_COPY",
            "geometry_lock_sha256": lock.content_sha256,
            "publication_status": "blocked",
        },
    )
    db.commit()
    return {"created": created, "status": job.status, "mode": "SOURCE_PRESERVED_BASELINE"}
