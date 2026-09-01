from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.market_intelligence import MarketActor

bearer = HTTPBearer(auto_error=False, scheme_name="MarketServiceBearer")
MAX_REGISTRY_BYTES = 1_000_000
MAX_BEARER_TOKEN_LENGTH = 512
TOKEN_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class MarketServicePrincipal:
    token_id: str
    subject_id: str
    tenant_id: str
    brand_id: str
    market_id: str
    permissions: frozenset[str]
    expires_at: datetime
    token_sha256: str

    def actor(self) -> MarketActor:
        return MarketActor(
            subject_id=self.subject_id,
            tenant_id=self.tenant_id,
            brand_id=self.brand_id,
            market_id=self.market_id,
            can_author="author" in self.permissions,
            can_review="review" in self.permissions,
            can_freeze="freeze" in self.permissions,
            can_handoff="handoff" in self.permissions,
            can_quarantine="quarantine" in self.permissions,
            permission_revision=f"service-token:{self.token_id}",
        )


def _registry_text() -> str:
    inline = os.getenv("MARKET_SERVICE_TOKENS", "").strip()
    if inline:
        return inline if len(inline.encode("utf-8")) <= MAX_REGISTRY_BYTES else ""
    file_name = os.getenv("MARKET_SERVICE_TOKENS_FILE", "").strip()
    if not file_name:
        return ""
    try:
        path = Path(file_name)
        if path.stat().st_size > MAX_REGISTRY_BYTES:
            return ""
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _principals() -> list[MarketServicePrincipal]:
    try:
        document = json.loads(_registry_text())
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(document, dict) or document.get("version") != 1:
        return []
    result: list[MarketServicePrincipal] = []
    token_ids: set[str] = set()
    token_digests: set[str] = set()
    for item in document.get("tokens", []):
        try:
            expires_at = datetime.fromisoformat(str(item["expiresAt"]).replace("Z", "+00:00"))
            permissions = frozenset(str(value) for value in item["permissions"])
            principal = MarketServicePrincipal(
                token_id=str(item["tokenId"]),
                subject_id=str(item["subjectId"]),
                tenant_id=str(item["tenantId"]),
                brand_id=str(item["brandId"]),
                market_id=str(item["marketId"]),
                permissions=permissions,
                expires_at=expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC),
                token_sha256=str(item["tokenSha256"]).lower(),
            )
        except (KeyError, TypeError, ValueError):
            return []
        if (
            TOKEN_SHA256_PATTERN.fullmatch(principal.token_sha256)
            and principal.token_id
            and principal.token_id not in token_ids
            and principal.token_sha256 not in token_digests
            and principal.subject_id.startswith("service:")
            and principal.tenant_id
            and principal.brand_id
            and principal.market_id
            and permissions
            and permissions
            <= {
                "read",
                "author",
                "review",
                "freeze",
                "handoff",
                "quarantine",
            }
        ):
            result.append(principal)
            token_ids.add(principal.token_id)
            token_digests.add(principal.token_sha256)
        else:
            return []
    return result


def authenticate_market_service(
    credentials: HTTPAuthorizationCredentials | None,
    permission: str,
) -> MarketServicePrincipal:
    if os.getenv("MARKET_SERVICE_API_ENABLED", "false").lower() != "true":
        raise HTTPException(503, detail={"code": "market_service_api_disabled"})
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, detail={"code": "service_token_required"})
    if not 32 <= len(credentials.credentials) <= MAX_BEARER_TOKEN_LENGTH:
        raise HTTPException(401, detail={"code": "service_token_invalid"})
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    principal = next(
        (item for item in _principals() if hmac.compare_digest(item.token_sha256, digest)),
        None,
    )
    if principal is None:
        raise HTTPException(401, detail={"code": "service_token_invalid"})
    if principal.expires_at <= datetime.now(UTC):
        raise HTTPException(401, detail={"code": "service_token_expired"})
    if permission not in principal.permissions:
        raise HTTPException(403, detail={"code": "service_token_scope_denied"})
    return principal
