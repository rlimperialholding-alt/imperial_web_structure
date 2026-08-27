from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, Header, HTTPException, Request, status

from app.config import Settings, get_settings
from app.process_cards.domain import RealRole


@dataclass(frozen=True, slots=True)
class Actor:
    subject: str
    kind: Literal["human", "service"]
    role: RealRole | None = None

    @property
    def is_service(self) -> bool:
        return self.kind == "service"

    @property
    def is_manager(self) -> bool:
        return self.role == RealRole.UGYVEZETO


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, value = authorization.partition(" ")
    if scheme.casefold() != "bearer":
        return ""
    return value.strip()


def _matches(candidate: str, expected: str) -> bool:
    return bool(candidate and expected and hmac.compare_digest(candidate, expected))


def authenticate_token(
    token: str,
    settings: Settings,
    *,
    legacy_admin_token: str = "",
) -> Actor | None:
    admin = settings.api_admin_token.get_secret_value().strip()
    if _matches(token, admin) or _matches(legacy_admin_token, admin):
        return Actor(subject="integration-admin", kind="service")

    for name, service_token in settings.service_tokens().items():
        if _matches(token, service_token):
            return Actor(subject=name, kind="service")

    for role, role_token in settings.human_role_tokens().items():
        if _matches(token, role_token):
            return Actor(subject=role.value, kind="human", role=role)

    return None


def require_actor(
    request: Request,
    authorization: str | None = Header(default=None),
    x_admin_token: str = Header(default=""),
    x_imperial_token: str = Header(default=""),
) -> Actor:
    settings = get_settings()
    token = _extract_bearer(authorization)
    actor = authenticate_token(
        token, settings, legacy_admin_token=x_admin_token or x_imperial_token
    )
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.actor = actor
    return actor


def require_manager(actor: Actor = Depends(require_actor)) -> Actor:
    if not actor.is_manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires the Ügyvezető role",
        )
    return actor


def require_manager_or_service(actor: Actor = Depends(require_actor)) -> Actor:
    if not actor.is_service and not actor.is_manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires the Ügyvezető role or a service token",
        )
    return actor


def ensure_role_access(actor: Actor, required_role: RealRole) -> None:
    if actor.is_service or actor.is_manager or actor.role == required_role:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"This operation belongs to the {required_role.value} role",
    )


def require_metrics_access(
    authorization: str | None = Header(default=None),
    x_metrics_token: str = Header(default=""),
) -> None:
    settings = get_settings()
    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="Metrics are disabled")
    token = _extract_bearer(authorization) or x_metrics_token.strip()
    expected = settings.metrics_token.get_secret_value().strip()
    if settings.is_development_like and not expected:
        return
    if not _matches(token, expected):
        raise HTTPException(status_code=401, detail="Invalid metrics token")
