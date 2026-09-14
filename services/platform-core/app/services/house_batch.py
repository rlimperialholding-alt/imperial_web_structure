from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.house_geometry import (
    RULESET_VERSION,
    HouseGeometryError,
    canonical_json,
    generate_houseplan_from_normalized,
    input_hash,
    normalize_input,
)
from app.services.house_svg import render_houseplan_svg

MAX_BATCH_ROWS = 100
DRY_RUN_TTL = timedelta(minutes=30)


class HouseBatchError(ValueError):
    pass


def parse_batch_json(raw: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HouseBatchError(f"Érvénytelen JSON a(z) {exc.lineno}. sorban.") from exc
    if not isinstance(value, list):
        raise HouseBatchError("A köteg gyökéreleme JSON-lista legyen.")
    if not 1 <= len(value) <= MAX_BATCH_ROWS:
        raise HouseBatchError("Egy köteg 1–100 sort tartalmazhat.")
    if any(not isinstance(row, dict) for row in value):
        raise HouseBatchError("A köteg minden sora JSON-objektum legyen.")
    return value


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _claims_token(claims: dict[str, Any], secret: str) -> str:
    encoded = _b64(canonical_json(claims).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256)
    return f"{encoded}.{signature.hexdigest()}"


def _batch_hash(
    rows: list[dict[str, Any]],
    *,
    actor_subject: str,
    source: dict[str, Any],
    permission_revision: str,
    pricing_revision: str,
) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "rows": rows,
                "actorSubject": actor_subject,
                "source": source,
                "permissionRevision": permission_revision,
                "pricingRevision": pricing_revision,
                "rulesetVersion": RULESET_VERSION,
            }
        ).encode("utf-8")
    ).hexdigest()


def validate_dry_run_token(
    token: str,
    *,
    rows: list[dict[str, Any]],
    secret: str,
    actor_subject: str,
    source: dict[str, Any],
    permission_revision: str,
    pricing_revision: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(
            secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise HouseBatchError("Érvénytelen dry-run aláírás.")
        claims = json.loads(_unb64(encoded))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        if isinstance(exc, HouseBatchError):
            raise
        raise HouseBatchError("Sérült dry-run token.") from exc
    current = now or datetime.now(UTC)
    expires_at = datetime.fromisoformat(claims["expiresAt"])
    expected = {
        "actorSubject": actor_subject,
        "sourceId": source["id"],
        "sourceRevision": source["revision"],
        "sourceSha256": source["sha256"],
        "permissionRevision": permission_revision,
        "pricingRevision": pricing_revision,
        "rulesetVersion": RULESET_VERSION,
    }
    if current >= expires_at:
        raise HouseBatchError("A dry-run token lejárt.")
    if any(claims.get(key) != value for key, value in expected.items()):
        raise HouseBatchError("stale_dry_run")
    expected_batch_hash = _batch_hash(
        rows,
        actor_subject=actor_subject,
        source=source,
        permission_revision=permission_revision,
        pricing_revision=pricing_revision,
    )
    if not hmac.compare_digest(str(claims.get("batchHash") or ""), expected_batch_hash):
        raise HouseBatchError("stale_dry_run")
    return claims


def dry_run_batch(
    rows: list[dict[str, Any]],
    *,
    source: dict[str, Any],
    actor_subject: str,
    permission_revision: str,
    pricing_revision: str,
    secret: str,
    now: datetime | None = None,
    include_svg: bool = True,
    execution_allowed: bool = True,
) -> dict[str, Any]:
    if not 1 <= len(rows) <= MAX_BATCH_ROWS:
        raise HouseBatchError("Egy köteg 1–100 sort tartalmazhat.")
    source_sha = str(source.get("sha256") or "").lower()
    if len(source_sha) != 64 or any(char not in "0123456789abcdef" for char in source_sha):
        raise HouseBatchError("A forrás nem rendelkezik érvényes SHA-256 azonosítóval.")
    current = now or datetime.now(UTC)
    seen: dict[str, int] = {}
    results: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=1):
        try:
            normalized = normalize_input(row)
            normalized_hash = input_hash(normalized, source)
            duplicate_of = seen.get(normalized_hash)
            if duplicate_of is not None:
                results.append(
                    {
                        "rowNumber": row_number,
                        "status": "duplicate",
                        "duplicateOf": duplicate_of,
                        "inputHash": normalized_hash,
                    }
                )
                continue
            generated = generate_houseplan_from_normalized(normalized, source)
            seen[generated["inputHash"]] = row_number
            item = {
                "rowNumber": row_number,
                "status": "ready",
                "inputHash": generated["inputHash"],
                "geometrySignature": generated["geometrySignature"],
                "normalizedInput": generated["normalizedInput"],
                "geometry": generated["geometry"],
            }
            if include_svg:
                item["svg"] = render_houseplan_svg(generated["geometry"])
            results.append(item)
        except (HouseGeometryError, KeyError, TypeError, ValueError) as exc:
            results.append(
                {
                    "rowNumber": row_number,
                    "status": "invalid",
                    "errorCode": "geometry_validation_failed",
                    "message": str(exc),
                }
            )
    batch_hash = _batch_hash(
        rows,
        actor_subject=actor_subject,
        source=source,
        permission_revision=permission_revision,
        pricing_revision=pricing_revision,
    )
    claims = {
        "actorSubject": actor_subject,
        "batchHash": batch_hash,
        "expiresAt": (current + DRY_RUN_TTL).isoformat(),
        "executionAllowed": execution_allowed,
        "issuedAt": current.isoformat(),
        "permissionRevision": permission_revision,
        "pricingRevision": pricing_revision,
        "rulesetVersion": RULESET_VERSION,
        "sourceId": source["id"],
        "sourceRevision": source["revision"],
        "sourceSha256": source_sha,
    }
    counts = {
        status: sum(item["status"] == status for item in results)
        for status in ("ready", "invalid", "duplicate")
    }
    return {
        "batchHash": batch_hash,
        "counts": counts,
        "dryRunToken": _claims_token(claims, secret),
        "expiresAt": claims["expiresAt"],
        "executionAllowed": execution_allowed,
        "results": results,
        "status": "ready" if counts["invalid"] == 0 else "has_errors",
    }
