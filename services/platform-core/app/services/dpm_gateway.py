from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import jwt

from ..config import Settings, settings

ADMIN_ROLES = frozenset({"owner", "managing-director", "platform-admin"})
ALL_SCOPES = frozenset(
    {"digital-pm:read", "digital-pm:write", "digital-pm:approve", "digital-pm:audit"}
)


class DpmGatewayError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class DpmIdentity:
    subject: str
    role: str
    scopes: frozenset[str]
    project_ids: frozenset[str]


@dataclass(frozen=True)
class DpmUserContext:
    identity: DpmIdentity
    agent_ids: frozenset[str]
    admin: bool


class DpmGateway:
    def __init__(self, app_settings: Settings = settings):
        self.settings = app_settings

    @property
    def configured(self) -> bool:
        token_source = bool(
            (self.settings.itep_api_base_url and self.settings.itep_identity_shared_secret)
            or self.settings.dpm_auth_hs256_secret
        )
        return bool(self.settings.dpm_api_base_url and token_source)

    def _token(self, identity: DpmIdentity) -> str:
        if not self.configured:
            raise DpmGatewayError(503, "A Digital Project Managers kapcsolat nincs konfigurálva.")
        if self.settings.itep_api_base_url and self.settings.itep_identity_shared_secret:
            return self._exchange_itep_token(identity)
        issued_at = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": identity.subject,
                "iss": self.settings.dpm_auth_issuer,
                "aud": self.settings.dpm_auth_audience,
                "iat": issued_at,
                "exp": issued_at + timedelta(minutes=2),
                "scope": " ".join(sorted(identity.scopes)),
                "projects": sorted(identity.project_ids),
                "role": identity.role,
            },
            self.settings.dpm_auth_hs256_secret,
            algorithm="HS256",
        )

    def _exchange_itep_token(self, identity: DpmIdentity) -> str:
        request = Request(
            f"{self.settings.itep_api_base_url.rstrip('/')}"
            "/v1/auth/service-tokens/digital-project-managers",
            data=b"{}",
            headers={
                **self._itep_identity_headers(identity),
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=8) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise DpmGatewayError(
                error.code, "Az ITEP nem adott ki DPM hozzáférési tokent."
            ) from error
        except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DpmGatewayError(
                503, "Az ITEP DPM tokenváltás nem érhető el."
            ) from error
        token = payload.get("accessToken") if isinstance(payload, dict) else None
        if not isinstance(token, str) or token.count(".") != 2:
            raise DpmGatewayError(502, "Az ITEP hibás DPM tokenválaszt adott.")
        return token

    def _itep_identity_headers(self, identity: DpmIdentity) -> dict[str, str]:
        now = int(datetime.now(UTC).timestamp())
        canonical_role = (
            "SYSTEM_ADMIN" if identity.role == "platform-admin" else "PROJECT_MANAGER"
        )
        permissions = (
            ["*"]
            if canonical_role == "SYSTEM_ADMIN"
            else ["project.read", "project.write", "task.accept.all", "audit.read.project"]
        )
        payload = {
            "actorId": identity.subject,
            "organizationId": "imperial-holding",
            "roles": [canonical_role],
            "permissions": permissions,
            "projectIds": sorted(identity.project_ids),
            "isSystemAdmin": canonical_role == "SYSTEM_ADMIN",
            "issuedAt": now,
            "expiresAt": now + 120,
            "nonce": str(uuid.uuid4()),
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).decode("ascii").rstrip("=")
        signature = hmac.new(
            self.settings.itep_identity_shared_secret.encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-Imperial-Identity": encoded,
            "X-Imperial-Identity-Signature": f"sha256={signature}",
        }

    def request(
        self,
        method: str,
        path: str,
        identity: DpmIdentity,
        *,
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        query_string = urlencode(
            {key: value for key, value in (query or {}).items() if value is not None}
        )
        url = f"{self.settings.dpm_api_base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"
        body = None
        headers = {
            "Authorization": f"Bearer {self._token(identity)}",
            "Accept": "application/json",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=8) as response:  # noqa: S310
                raw = response.read()
        except HTTPError as error:
            detail = f"DPM HTTP {error.code}"
            try:
                parsed = json.loads(error.read().decode("utf-8"))
                detail = str(parsed.get("detail") or detail)
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                pass
            raise DpmGatewayError(error.code, detail) from error
        except (URLError, TimeoutError) as error:
            raise DpmGatewayError(
                503, "A Digital Project Managers szolgáltatás nem érhető el."
            ) from error
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DpmGatewayError(502, "A Digital Project Managers hibás választ adott.") from error

    @staticmethod
    def admin_identity(subject: str) -> DpmIdentity:
        return DpmIdentity(
            subject=subject,
            role="platform-admin",
            scopes=ALL_SCOPES,
            project_ids=frozenset(),
        )

    def user_context(self, *, email: str, role: str) -> DpmUserContext:
        if role in ADMIN_ROLES:
            return DpmUserContext(
                identity=self.admin_identity(email),
                agent_ids=frozenset(),
                admin=True,
            )
        if role != "project-manager":
            raise DpmGatewayError(403, "Ehhez a DPM munkatérhez nincs jogosultság.")
        admin = self.admin_identity(f"platform-gateway:{email}")
        agents = self.request("GET", "/api/v1/agents", admin)
        agent_ids = frozenset(
            str(agent["id"])
            for agent in agents
            if str(agent.get("human_manager_ref") or "").casefold() == email.casefold()
        )
        assignments = self.request("GET", "/api/v1/assignments", admin)
        projects = frozenset(
            str(item["external_project_id"])
            for item in assignments
            if str(item["digital_manager_id"]) in agent_ids
        )
        return DpmUserContext(
            identity=DpmIdentity(
                subject=email,
                role="project-manager",
                scopes=ALL_SCOPES,
                project_ids=projects,
            ),
            agent_ids=agent_ids,
            admin=False,
        )


dpm_gateway = DpmGateway()
