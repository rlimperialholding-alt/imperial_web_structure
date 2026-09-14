from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.types import Options

from app.config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    subject: str
    scopes: frozenset[str]
    project_ids: frozenset[str]
    role: str | None = None

    def can_access_project(self, project_id: str) -> bool:
        return self.role == "platform-admin" or project_id in self.project_ids


@lru_cache
def _jwk_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url)


def _decode_token(token: str, settings: Settings) -> dict[str, object]:
    options: Options = {"require": ["exp", "iat", "sub", "iss", "aud"]}
    if settings.auth_jwks_url:
        signing_key = _jwk_client(settings.auth_jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
            options=options,
        )
    secret = settings.resolved_auth_hs256_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience=settings.auth_audience,
        issuer=settings.auth_issuer,
        options=options,
    )


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_test_subject: str | None = Header(default=None),
    x_test_scopes: str | None = Header(default=None),
    x_test_projects: str | None = Header(default=None),
    x_test_role: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Principal:
    if settings.auth_mode == "test":
        if not x_test_subject:
            raise HTTPException(status_code=401, detail="Missing test subject")
        return Principal(
            subject=x_test_subject,
            scopes=frozenset((x_test_scopes or "").split()),
            project_ids=frozenset(
                value.strip() for value in (x_test_projects or "").split(",") if value.strip()
            ),
            role=x_test_role,
        )

    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        claims = _decode_token(credentials.credentials, settings)
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from error
    scope_claim = claims.get("scope", "")
    project_claim = claims.get("projects", [])
    if isinstance(scope_claim, str):
        scopes = frozenset(scope_claim.split())
    elif isinstance(scope_claim, list):
        scopes = frozenset(str(value) for value in scope_claim)
    else:
        scopes = frozenset()
    projects = (
        frozenset(str(value) for value in project_claim)
        if isinstance(project_claim, list)
        else frozenset()
    )
    return Principal(
        subject=str(claims["sub"]),
        scopes=scopes,
        project_ids=projects,
        role=str(claims["role"]) if claims.get("role") else None,
    )


def require_scope(required_scope: str) -> Any:
    def dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if required_scope not in principal.scopes:
            raise HTTPException(status_code=403, detail=f"Missing scope: {required_scope}")
        return principal

    return dependency


def enforce_project_access(principal: Principal, project_id: str) -> None:
    if not principal.can_access_project(project_id):
        raise HTTPException(status_code=403, detail="Project access denied")
