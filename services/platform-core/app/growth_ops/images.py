from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
from typing import Any


class CanonicalImageFactoryError(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    token = os.getenv("IMAGE_FACTORY_API_TOKEN", "").strip()
    if len(token) < 32:
        raise CanonicalImageFactoryError("image_factory_api_token_missing")
    host = os.getenv("CONTENT_IMAGE_FACTORY_HOST", "image-factory").strip()
    port = int(os.getenv("CONTENT_IMAGE_FACTORY_PORT", "8000"))
    timeout = max(3, min(120, int(os.getenv("CONTENT_IMAGE_FACTORY_TIMEOUT_SECONDS", "30"))))
    body = _json(payload).encode("utf-8") if payload is not None else None
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request(
            method,
            path,
            body=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-API-Key": token,
            },
        )
        response = connection.getresponse()
        raw = response.read(2_000_001)
    finally:
        connection.close()
    if len(raw) > 2_000_000:
        raise CanonicalImageFactoryError("image_factory_response_too_large")
    if response.status < 200 or response.status >= 300:
        raise CanonicalImageFactoryError(f"image_factory_http_{response.status}")
    try:
        value = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise CanonicalImageFactoryError("image_factory_invalid_json") from exc
    if not isinstance(value, dict):
        raise CanonicalImageFactoryError("image_factory_invalid_response")
    return value


def _asset(job: dict[str, Any], role: str) -> dict[str, Any]:
    meta = (job.get("derived_assets") or {}).get(role) or {}
    sha256 = str(meta.get("sha256") or "")
    dimensions = meta.get("dimensions") or []
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise CanonicalImageFactoryError(f"image_factory_{role}_sha256_missing")
    if len(dimensions) != 2 or min(int(value) for value in dimensions) < 600:
        raise CanonicalImageFactoryError(f"image_factory_{role}_dimensions_invalid")
    return {
        "job_id": str(job.get("job_id") or ""),
        "role": role,
        "sha256": sha256,
        "dimensions": [int(dimensions[0]), int(dimensions[1])],
    }


def sync_canonical_image(
    package: dict[str, Any], *, content_asset_id: str, article_slug: str
) -> tuple[str, dict[str, Any]]:
    """Submit or poll one hash-bound image job.

    Returns a state name and the durable state that the caller must persist with
    the exact content package. Publication remains fail-closed until both image
    QA and the canary-controlled automatic release switch pass.
    """
    if os.getenv("CANONICAL_IMAGE_FACTORY_ENABLED", "false").casefold() != "true":
        return "disabled", dict(package.get("image_factory") or {})
    title = str(package.get("title") or "").strip()
    body = str(package.get("body") or "").strip()
    brand_id = str(package.get("brand_id") or "").strip()
    if not title or not body or not brand_id:
        raise CanonicalImageFactoryError("image_factory_content_context_missing")
    artifact_sha256 = hashlib.sha256(
        _json(
            {
                "brand_id": brand_id,
                "title": title,
                "body": body,
                "facebook_post": package.get("facebook_post"),
            }
        ).encode("utf-8")
    ).hexdigest()
    state = dict(package.get("image_factory") or {})
    if state and state.get("artifact_sha256") != artifact_sha256:
        raise CanonicalImageFactoryError("image_factory_stale_content_binding")
    if not state.get("batch_id") or not state.get("job_id"):
        payload = {
            "idempotency_key": f"canonical-content-{artifact_sha256}",
            "source_type": "canonical_content_factory_daily",
            "upload_to_drive": False,
            "items": [
                {
                    "topic": title[:500],
                    "title": " ".join(title.split()[:10])[:220],
                    "article_slug": article_slug[:180],
                    "content_id": content_asset_id,
                    "image_role": "hero",
                    "source_brief": (
                        "Készíts egyetlen koherens, fotórealisztikus, felirat-, logó- és "
                        "vízjelmentes szerkesztőségi képet. Ne legyen kollázs vagy többpaneles "
                        f"elrendezés. Márka: {brand_id}. A cikk témája: {title}. "
                        f"Tartalmi kontextus: {body[:2500]}"
                    )[:8000],
                    "target_aspect_ratio": "16:9",
                }
            ],
        }
        response = _request("POST", "/api/v1/batches", payload)
        jobs = [job for job in response.get("jobs") or [] if isinstance(job, dict)]
        if len(jobs) != 1 or str(jobs[0].get("content_id") or "") != content_asset_id:
            raise CanonicalImageFactoryError("image_factory_job_mapping_invalid")
        state = {
            "artifact_sha256": artifact_sha256,
            "batch_id": str(response.get("batch_id") or ""),
            "job_id": str(jobs[0].get("job_id") or ""),
            "status": str(jobs[0].get("status") or "SUBMITTED"),
        }
        return "pending", state
    response = _request("GET", f"/api/v1/batches/{state['batch_id']}")
    jobs = [
        job
        for job in response.get("jobs") or []
        if isinstance(job, dict) and str(job.get("job_id") or "") == state["job_id"]
    ]
    if len(jobs) != 1:
        raise CanonicalImageFactoryError("image_factory_job_missing")
    job = jobs[0]
    external_status = str(job.get("status") or "")
    state["status"] = external_status
    if external_status in {"QUEUED", "PROCESSING", "SUBMITTED"}:
        return "pending", state
    if external_status in {"FAILED", "NEEDS_REVIEW"}:
        state["error_type"] = "provider_quota_or_generation_failure" if external_status == "FAILED" else "visual_review_required"
        return "failed", state
    if external_status != "COMPLETED":
        raise CanonicalImageFactoryError("image_factory_status_invalid")
    minimum_score = max(85, min(100, int(os.getenv("CANONICAL_IMAGE_FACTORY_QA_MIN_SCORE", "90"))))
    score = int(job.get("qa_score") or 0)
    if score < minimum_score:
        state["qa_score"] = score
        state["error_type"] = "visual_qa_score_below_threshold"
        return "failed", state
    if str(job.get("release_state") or "") != "TEST_ONLY_REVIEW_REQUIRED":
        raise CanonicalImageFactoryError("image_factory_release_state_invalid")
    state.update(
        {
            "qa_score": score,
            "release_state": "TEST_ONLY_REVIEW_REQUIRED",
            "web_hero": _asset(job, "web_hero"),
            # Use the unbranded hero for Facebook too. The legacy branded
            # derivative contains a single global logo and must never leak
            # across brands.
            "facebook": _asset(job, "web_hero"),
        }
    )
    if os.getenv("CANONICAL_IMAGE_AUTO_RELEASE_ENABLED", "false").casefold() != "true":
        state["status"] = "CANARY_REVIEW_REQUIRED"
        return "review_required", state
    state["status"] = "AUTO_RELEASE_APPROVED"
    return "ready", state
